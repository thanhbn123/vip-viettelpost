"""Engine / session factory (sync SQLAlchemy 2.0).

This module never creates or alters schema. Schema is owned by Alembic
(``migrations/``); run ``alembic -c migrations/alembic.ini upgrade head``.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str, **kwargs) -> Engine:
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _configure_sqlite(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _configure_sqlite(engine: Engine) -> None:
    """Enforce foreign keys and make SAVEPOINT work under pysqlite.

    pysqlite's own transaction handling breaks SAVEPOINT; per the SQLAlchemy
    docs we disable it and emit BEGIN ourselves. BEGIN IMMEDIATE takes the write
    lock up front, so two concurrent writers queue (busy timeout) instead of
    deadlocking on a read-then-write upgrade (e.g. two deliveries of one webhook).
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")
