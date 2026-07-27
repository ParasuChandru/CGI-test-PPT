from db import query
from utils import format_name


def get_user(user_id):
    name = query("SELECT name FROM users WHERE id=" + str(user_id))
    return format_name(name)


def create_user(name):
    clean = format_name(name)
    return query("INSERT INTO users (name) VALUES ('{}')".format(clean))
