import sys
from time import sleep
import asyncio
import logger
from config import settings

from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy_utils import create_database, database_exists

db_password = ""


# init database
def get_engine(database):
    args = dict(max_overflow=10, echo=False, pool_size=20)

    if "pytest" in sys.modules:
        logger.warning("Running with testing NullPool DB engine")
        args = dict(poolclass=NullPool)

    engine = create_async_engine(db_url(database), **args)
    return engine


engine = get_engine(settings.postgres.dbname)

SessionMaker = sessionmaker(bind=engine, class_=AsyncSession)

utils_url = engine.url.render_as_string(hide_password=False).replace("+asyncpg", "")


# database
class Base(DeclarativeBase):
    pass


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def init_database(create=False, force_tables=False):
    while not database_exists(utils_url):
        if create:
            logger.info("Creating database")
            create_database(utils_url)
            force_tables = True
        sleep(0.5)
    if force_tables:
        asyncio.run(create_tables())
        sleep(0.5)


def db_url(database):
    return "postgresql+asyncpg://{user}:{db_password}@{host}:{port}/{dbname}".format(
        host=settings.postgres.host,
        port=settings.postgres.port,
        user=settings.postgres.user,
        db_password=db_password,
        dbname=database,
    )
