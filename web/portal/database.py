"""Manage access to the database."""

import json
import sqlite3
import time
import uuid

from flask import g


class Database:
    """Database access."""

    def __init__(self, app):
        """Constructor."""
        self.app = app

        @app.teardown_appcontext
        def close_connection(exception):
            """Close database connection when finished handling request."""
            db = getattr(g, '_database', None)

            if db is not None:
                db.close()

    SCHEMA = """
        create table if not exists profile (
            id integer primary key autoincrement,
            identity_id text not null,
            name text not null,
            email text not null,
            institution text
        );
        create table if not exists pending_form (
            key text primary key,
            created integer,
            form text
        );
    """

    def connect_to_db(self):
        """Open database and return a connection handle."""
        db = sqlite3.connect(self.app.config['DATABASE'])
        db.executescript(self.SCHEMA)
        return db

    def get_db(self):
        """Return the app global db connection or create one."""
        db = getattr(g, '_database', None)

        if db is None:
            db = g._database = self.connect_to_db()
            db.row_factory = sqlite3.Row

        return db

    def query_db(self, query, args=(), one=False):
        """Query the database."""
        cur = self.get_db().execute(query, args)

        rv = cur.fetchall()
        cur.close()

        return (rv[0] if rv else None) if one else rv

    def save_profile(self,
                     identity_id=None,
                     name=None,
                     email=None,
                     institution=None):
        """Persist user profile."""
        db = self.get_db()

        db.execute("""update profile set name = ?, email = ?, institution = ?
                   where identity_id = ?""",
                   (name, email, institution, identity_id))

        db.execute("""insert into profile (identity_id, name, email, institution)
                   select ?, ?, ?, ? where changes() = 0""",
                   (identity_id, name, email, institution))
        db.commit()

    def save_pending_form(self, form):
        """Stash a transfer form server-side and return a lookup key.

        The form can list thousands of simulation IDs, far exceeding the
        4 KB cookie limit if kept in the session.
        """
        db = self.get_db()

        db.execute("delete from pending_form where created < ?",
                   (int(time.time()) - 86400,))

        key = uuid.uuid4().hex
        db.execute("insert into pending_form (key, created, form) values (?, ?, ?)",
                   (key, int(time.time()), json.dumps(form)))
        db.commit()

        return key

    def load_pending_form(self, key):
        row = self.query_db("select form from pending_form where key = ?",
                            [key], one=True)
        return json.loads(row['form']) if row else None

    def load_profile(self, identity_id):
        """Load user profile."""
        return self.query_db("""select name, email, institution from profile
                             where identity_id = ?""",
                             [identity_id],
                             one=True)
