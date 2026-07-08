from logging.config import fileConfig

from alembic import context
from alembic.ddl import impl as alembic_impl
from alembic.ddl.impl import DefaultImpl
from sqlalchemy import engine_from_config, pool

from ocint.ctx.duckdb_schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata

# Alembic does not ship a named DuckDB DDL implementation; duckdb-sqlalchemy
# supplies the SQLAlchemy dialect and the default Alembic DDL runner is enough
# for these create-table/create-view migrations.
alembic_impl._impls.setdefault("duckdb", DefaultImpl)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
