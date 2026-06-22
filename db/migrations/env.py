import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Loyiha ildizini Python path-ga qo'shamiz (bot.config va db.models import uchun)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bot.config import settings  # noqa: E402
from db.database import Base     # noqa: E402
import db.models                 # noqa: E402, F401 — barcha modellarni Base.metadata-ga ro'yxatdan o'tkazadi

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini dagi placeholder URL-ni haqiqiy URL bilan almashtiramiz
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """SQL skriptini DB-ga ulanmay generatsiya qiladi."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
