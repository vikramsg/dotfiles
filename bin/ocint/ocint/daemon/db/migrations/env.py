from alembic import context
from ocint.daemon.db.schema import metadata
from sqlalchemy import Connection, Engine

config = context.config
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    engine = config.attributes.get("engine")
    if not isinstance(connection, Connection) or not isinstance(engine, Engine):
        raise RuntimeError("daemon migrations require a validated database connection")
    try:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    finally:
        connection.close()
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
