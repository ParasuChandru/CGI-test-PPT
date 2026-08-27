const React = require('react');
const ReactDOMServer = require('react-dom/server');
const sharp = require('sharp');
const fs = require('fs');
const {
  FaExclamationTriangle, FaHandHoldingUsd, FaHourglassHalf,
  FaSearch, FaCommentAlt, FaBullseye,
  FaCheckCircle, FaTimesCircle,
  FaLock, FaUserShield, FaClipboardList, FaUserCheck,
  FaLayerGroup, FaChartLine, FaRobot,
} = require('react-icons/fa');

const icons = {
  problem_unseen: FaExclamationTriangle,
  problem_discount: FaHandHoldingUsd,
  problem_late: FaHourglassHalf,
  step_predict: FaSearch,
  step_explain: FaCommentAlt,
  step_act: FaBullseye,
  in_scope: FaCheckCircle,
  out_scope: FaTimesCircle,
  guard_lock: FaLock,
  guard_shield: FaUserShield,
  guard_audit: FaClipboardList,
  guard_approve: FaUserCheck,
  ask_layers: FaLayerGroup,
  changed_analytics: FaChartLine,
  changed_ai: FaRobot,
};

const outDir = __dirname + '/icons';
fs.mkdirSync(outDir, { recursive: true });

async function run() {
  for (const [name, Comp] of Object.entries(icons)) {
    for (const [suffix, color] of [['white', '#FFFFFF'], ['red', '#E31937'], ['dark', '#1A1A1A']]) {
      const el = React.createElement(Comp, { color });
      const svg = ReactDOMServer.renderToStaticMarkup(el);
      const viewBoxMatch = svg.match(/viewBox="([^"]+)"/);
      const viewBox = viewBoxMatch ? viewBoxMatch[1] : '0 0 512 512';
      const inner = svg.replace(/<svg[^>]*>/, '').replace(/<\/svg>/, '');
      const fullSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${viewBox}" width="512" height="512">${inner}</svg>`;
      const pngPath = `${outDir}/${name}_${suffix}.png`;
      await sharp(Buffer.from(fullSvg)).resize(512, 512, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toFile(pngPath);
    }
  }
  console.log('Icons generated:', fs.readdirSync(outDir).length);
}
run().catch(e => { console.error(e); process.exit(1); });
