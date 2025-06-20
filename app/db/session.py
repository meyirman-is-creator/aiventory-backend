from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import settings
import logging
from fastapi import HTTPException, status
import asyncio

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI.replace("postgresql://", "postgresql+asyncpg://"),
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args={"server_settings": {"application_name": "inventory_system"}},
)

AsyncSessionLocal = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db():
    db = AsyncSessionLocal()
    try:
        try:
            await db.execute(text("SELECT 1"))
            logger.debug("Database connection successful")
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            error_message = (
                f"Database connection error: {str(e)}. "
                "Please check that PostgreSQL is running and accessible. "
                f"Current connection: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}"
            )

            retry_count = 3
            retry_delay = 1

            for attempt in range(retry_count):
                try:
                    await asyncio.sleep(retry_delay)
                    logger.info(f"Retrying database connection (attempt {attempt + 1}/{retry_count})...")
                    await db.execute(text("SELECT 1"))
                    logger.info("Database connection successful after retry")
                    break
                except Exception as retry_e:
                    logger.warning(f"Retry {attempt + 1} failed: {str(retry_e)}")
                    retry_delay *= 2
                    if attempt == retry_count - 1:
                        logger.error(f"All {retry_count} connection attempts failed")
                        if settings.POSTGRES_SERVER == "postgres":
                            error_message += (
                                "\nIf running outside Docker, set POSTGRES_SERVER=localhost in .env"
                            )
                        elif settings.POSTGRES_SERVER == "localhost":
                            error_message += (
                                "\nIf running in Docker, set POSTGRES_SERVER=postgres in .env"
                            )
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=error_message
                        )

        yield db
    finally:
        await db.close()