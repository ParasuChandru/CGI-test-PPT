"""Query engine over the symbol dependency graph built by indexer.py.

See IMPACT_STUDIO_SPEC.md section 6.
"""

import sqlite3


class ImpactEngine:
    def __init__(self, db_path):
        self.db_path = db_path

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    # -- stats ---------------------------------------------------------

    def stats(self):
        con = self._connect()
        try:
            frow = con.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(loc), 0) AS loc FROM files"
            ).fetchone()
            symbols = con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            refs = con.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
            return {"files": frow["n"], "loc": frow["loc"], "symbols": symbols, "refs": refs}
        finally:
            con.close()

    # -- search ----------------------------------------------------------

    def search(self, term):
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT s.name, s.kind, f.path FROM symbols s "
                "JOIN files f ON f.id = s.file_id "
                "WHERE s.name LIKE ? ORDER BY s.name LIMIT 50",
                (f"%{term}%",),
            ).fetchall()
            return [{"name": r["name"], "kind": r["kind"], "path": r["path"]} for r in rows]
        finally:
            con.close()

    # -- symbol impact (reverse BFS) --------------------------------------

    def symbol_impact(self, name, max_depth=6, max_nodes=5000):
        con = self._connect()
        try:
            return self._impact_from_seeds(con, [name], max_depth, max_nodes)
        finally:
            con.close()

    def multi_symbol_impact(self, names, max_depth=6, max_nodes=5000):
        con = self._connect()
        try:
            result = self._impact_from_seeds(con, list(names), max_depth, max_nodes)
        finally:
            con.close()
        result["seeds"] = sorted(set(names))
        del result["target"]
        return result

    def _impact_from_seeds(self, con, seed_names, max_depth, max_nodes):
        seeds = set(seed_names)
        visited = {name: 0 for name in seeds}
        queue = [(name, 0) for name in seeds]
        impacted = {}          # name -> first-seen depth
        impacted_files = {}    # path -> set(symbol names)
        edges = []
        truncated = False

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                exists = con.execute(
                    "SELECT 1 FROM refs WHERE name = ? LIMIT 1", (current,)
                ).fetchone()
                if exists is not None:
                    truncated = True
                continue

            rows = con.execute(
                "SELECT r.line, r.src_symbol_id, s.name AS caller_name, "
                "s.kind AS caller_kind, f.path AS path "
                "FROM refs r "
                "LEFT JOIN symbols s ON s.id = r.src_symbol_id "
                "JOIN files f ON f.id = r.file_id "
                "WHERE r.name = ?",
                (current,),
            ).fetchall()

            for row in rows:
                path = row["path"]
                if row["src_symbol_id"] is None:
                    edges.append({
                        "caller": "<module-level>",
                        "callee": current,
                        "path": path,
                        "line": row["line"],
                        "kind": "module",
                    })
                    impacted_files.setdefault(path, set()).add("<module-level>")
                    continue

                caller_name = row["caller_name"]
                edges.append({
                    "caller": caller_name,
                    "callee": current,
                    "path": path,
                    "line": row["line"],
                    "kind": row["caller_kind"],
                })

                if caller_name in visited:
                    continue  # already visited (or is a seed) -- cycle guard

                if len(impacted) >= max_nodes:
                    truncated = True
                    continue

                next_depth = depth + 1
                visited[caller_name] = next_depth
                impacted[caller_name] = next_depth
                impacted_files.setdefault(path, set()).add(caller_name)
                queue.append((caller_name, next_depth))

        depth_reached = max(impacted.values()) if impacted else 0

        entry_points = []
        for sym_name in impacted:
            row = con.execute(
                "SELECT 1 FROM refs WHERE name = ? LIMIT 1", (sym_name,)
            ).fetchone()
            if row is None:
                entry_points.append(sym_name)

        impacted_files_sorted = {
            path: sorted(names) for path, names in impacted_files.items()
        }

        target = seed_names[0] if len(seed_names) == 1 else None

        return {
            "target": target,
            "impacted_symbols": sorted(impacted.keys()),
            "impacted_files": dict(sorted(impacted_files_sorted.items())),
            "entry_points": sorted(entry_points),
            "edges": edges,
            "depth_reached": depth_reached,
            "truncated": truncated,
        }

    # -- file impact -------------------------------------------------------

    @staticmethod
    def _module_keys(rel_path):
        no_ext = rel_path.rsplit(".", 1)[0] if "." in rel_path else rel_path
        full = no_ext.replace("/", ".")
        last = full.rsplit(".", 1)[-1]
        return full, last

    def file_impact(self, path):
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT f.path AS path, d.dst_module AS dst_module "
                "FROM file_deps d JOIN files f ON f.id = d.src_file_id"
            ).fetchall()

            reverse_map = {}
            for row in rows:
                dst = row["dst_module"]
                last = dst.rsplit(".", 1)[-1]
                reverse_map.setdefault(dst, set()).add(row["path"])
                reverse_map.setdefault(last, set()).add(row["path"])

            visited = {path}
            queue = [path]
            dependents = set()
            while queue:
                current = queue.pop(0)
                full, last = self._module_keys(current)
                candidates = reverse_map.get(full, set()) | reverse_map.get(last, set())
                for dep in candidates:
                    if dep not in visited:
                        visited.add(dep)
                        dependents.add(dep)
                        queue.append(dep)

            return {"target_file": path, "dependent_files": sorted(dependents)}
        finally:
            con.close()
