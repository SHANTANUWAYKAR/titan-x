from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Added 2026-08-21 -- wires this scaffold to the project's real models
# and real settings.database_url (core.config.settings), same
# convention as core.database.session.init_db()'s own
# Base.metadata.create_all(). Backfilled onto an already-deployed
# schema (every table already existed via init_db()/deployment/docker/
# init.sql before Alembic was ever added -- see the initial revision's
# own message for how that was reconciled) rather than a fresh project,
# so target_metadata being real matters immediately: the very first
# `alembic revision --autogenerate` run against the live DB is what
# confirms there's no drift between the ORM models and what's actually
# deployed, before any new migration is trusted.
from project_titan_x.core.config import get_settings
from project_titan_x.core.database.models import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Real connection string, not the placeholder alembic.ini one -- same
# source of truth as core.database.session.engine, so migrations always
# target the actual configured database (respects env-based overrides
# via .env, including the local-vs-Docker postgres_port distinction
# settings.py's own comments document).
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
