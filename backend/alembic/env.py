import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.db.models import *  # noqa: F401,F403  (import all models so metadata is populated)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # One transaction per revision, not one for the whole upgrade.
        #
        # This is not a style preference. Postgres allows ALTER TYPE ... ADD
        # VALUE inside a transaction but forbids *using* the new value in that
        # same transaction, so the usual recipe - add the value in one revision,
        # use it in the next - only works if the two revisions are separate
        # transactions. Without this flag `alembic upgrade head` ran every
        # pending revision in one, which meant such a pair passed when applied
        # one at a time by hand and failed on a fresh database. That failure
        # would have surfaced for the first time in Railway's preDeployCommand,
        # taking the deploy down with it.
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.database_url)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
