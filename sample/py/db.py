from utils import format_name


def get_connection():
    return "conn"


def query(sql):
    conn = get_connection()
    return "{}:{}".format(conn, sql)
