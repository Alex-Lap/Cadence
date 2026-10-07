"""Who is making this request.

Clerk signs a short-lived session JWT for the browser. It reaches us either as
`Authorization: Bearer <token>` (fetch calls) or as the `__session` cookie
(same-origin navigations such as the .ics download -- the Next.js proxy
forwards cookies). We verify it against Clerk's public keys; the `sub` claim
(Clerk's user id) becomes our User.external_id.

When no issuer is configured, auth is off and everyone is "demo". That keeps
local development and the test suite free of any Clerk dependency.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import HTTPException, Request

from app.config import get_settings

DEMO_USER = "demo"


@lru_cache
def _jwks(issuer: str) -> jwt.PyJWKClient:
    # Cached per process; PyJWKClient itself caches keys and refetches on an
    # unknown `kid`, so key rotation needs no restart.
    return jwt.PyJWKClient(f"{issuer.rstrip('/')}/.well-known/jwks.json")


def signing_key(token: str, issuer: str):
    """The public key that should have signed `token`. Patched in tests."""
    return _jwks(issuer).get_signing_key_from_jwt(token).key


def verify(token: str) -> dict:
    """Validate a Clerk session token and return its claims, or raise 401."""
    settings = get_settings()
    issuer = settings.clerk_issuer.rstrip("/")
    try:
        claims = jwt.decode(
            token,
            signing_key(token, issuer),
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
            leeway=5,  # small clock skew between Clerk and us
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid session: {exc}") from exc

    parties = {p.strip() for p in settings.clerk_authorized_parties.split(",") if p.strip()}
    if claims.get("azp") and parties and claims["azp"] not in parties:
        raise HTTPException(401, "Session was issued for a different site.")
    if claims.get("sts") == "pending":
        raise HTTPException(401, "Finish signing up first.")
    return claims


def current_external_id(request: Request) -> str:
    """FastAPI dependency: the signed-in user's id (Clerk `sub`)."""
    if not get_settings().clerk_issuer:
        return DEMO_USER

    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or request.cookies.get("__session", "")
    if not token:
        raise HTTPException(401, "Sign in required.")
    return verify(token)["sub"]
