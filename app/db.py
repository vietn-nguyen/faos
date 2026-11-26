from pathlib import Path

import click
import psycopg
from flask import current_app, g
from psycopg.rows import dict_row

SCHEMA = Path(__file__).parent / "schema.sql"


def connect():
    return psycopg.connect(current_app.config["DATABASE_URL"], row_factory=dict_row)


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        if exc is None:
            db.commit()
        else:
            db.rollback()
        db.close()


def query(sql, params=None, one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()


def execute(sql, params=None, returning=False):
    with get_db().cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone() if returning else None


def commit():
    get_db().commit()


def rollback():
    get_db().rollback()


@click.command("init-db")
def init_db_command():
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
    click.echo("Database initialised.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
