"""
Module: auth.py
Description: JWT authentication and RBAC for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


class Role(str, Enum):
    """RBAC roles."""

    VIEWER = "viewer"
    TRADER = "trader"
    RISK_OFFICER = "risk_officer"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: {"read:signals", "read:portfolio", "read:research"},
    Role.TRADER: {"read:signals", "read:portfolio", "read:research", "approve:signals"},
    Role.RISK_OFFICER: {"read:*", "veto:trades", "halt:trading"},
    Role.ADMIN: {"*"},
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data to encode.
        expires_delta: Optional custom expiration.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT string.

    Returns:
        Decoded payload or None if invalid.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.warning("JWT decode failed: %s", e)
        return None


def has_permission(role: Role, permission: str) -> bool:
    """Check if a role has a specific permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return "*" in perms or permission in perms
