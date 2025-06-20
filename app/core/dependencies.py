from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional, List
from redis.asyncio import Redis

from app.db.session import get_db
from app.db.redis import get_redis
from app.models.users import User, UserRole
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


async def get_current_user(
        db: AsyncSession = Depends(get_db),
        token: str = Depends(oauth2_scheme),
        redis: Redis = Depends(get_redis),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        token_jti = payload.get("jti")
        user_sid = payload.get("sub")

        if user_sid is None:
            raise credentials_exception

        blacklisted = await redis.get(f"blacklist:{token_jti}")
        if blacklisted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise credentials_exception

    user_query = select(User).where(User.sid == user_sid)
    result = await db.execute(user_query)
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
        current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return current_user


async def get_admin_user(
        current_user: User = Depends(get_current_active_user),
) -> User:
    if current_user.role != UserRole.ADMIN and current_user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


def rate_limit_dependency(
        requests_limit: int = 100,
        time_window: int = 60
):
    async def rate_limit(
            request: Request,
            redis: Redis = Depends(get_redis)
    ):
        client_ip = request.client.host
        key = f"rate_limit:{client_ip}"
        count = await redis.incr(key)

        if count == 1:
            await redis.expire(key, time_window)

        if count > requests_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
            )

    return rate_limit