"""Clerk session verification, end to end through the API.

Real RSA keys, real signatures; only the JWKS fetch is replaced by a local key.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import app.auth as auth
from app.config import get_settings

ISSUER = "https://example.clerk.accounts.dev"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(sub="user_alice", key=KEY, **claims):
    now = int(time.time())
    payload = {"sub": sub, "iss": ISSUER, "iat": now, "nbf": now, "exp": now + 60,
               "azp": "http://localhost:3000", **claims}
    return jwt.encode(payload, key, algorithm="RS256")


@pytest.fixture
def auth_on(monkeypatch):
    settings = get_settings().model_copy(update={"clerk_issuer": ISSUER})
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "signing_key", lambda tok, iss: KEY.public_key())


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_auth_off_everyone_is_demo(client):
    assert client.get("/api/settings").status_code == 200


def test_no_token_is_401(client, auth_on):
    assert client.get("/api/settings").status_code == 401


def test_valid_token_is_accepted(client, auth_on):
    assert client.get("/api/settings", headers=bearer(token())).status_code == 200


def test_session_cookie_works_too(client, auth_on):
    """The .ics download is a plain link, so it arrives with the cookie only."""
    client.cookies.set("__session", token())
    assert client.get("/api/settings").status_code == 200


def test_expired_token_is_401(client, auth_on):
    old = token(exp=int(time.time()) - 60, iat=int(time.time()) - 120)
    assert client.get("/api/settings", headers=bearer(old)).status_code == 401


def test_forged_signature_is_401(client, auth_on):
    assert client.get("/api/settings", headers=bearer(token(key=OTHER_KEY))).status_code == 401


def test_wrong_issuer_is_401(client, auth_on):
    t = token(iss="https://evil.example")
    assert client.get("/api/settings", headers=bearer(t)).status_code == 401


def test_token_for_another_site_is_401(client, auth_on):
    t = token(azp="https://evil.example")
    assert client.get("/api/settings", headers=bearer(t)).status_code == 401


def test_pending_signup_is_401(client, auth_on):
    t = token(sts="pending")
    assert client.get("/api/settings", headers=bearer(t)).status_code == 401


def test_users_cannot_see_each_others_data(client, auth_on):
    alice, bob = bearer(token("user_alice")), bearer(token("user_bob"))
    made = client.post("/api/commitments", headers=alice, json={
        "title": "Alice's shift", "weekday": 0, "start_time": "18:00", "end_time": "20:00"})
    assert made.status_code == 201
    client.get("/api/settings", headers=bob)  # bob exists, with nothing
    assert client.get("/api/commitments", headers=bob).json() == []
    # Bob can't delete Alice's commitment by id either.
    assert client.delete(f"/api/commitments/{made.json()['id']}", headers=bob).status_code == 404
    assert len(client.get("/api/commitments", headers=alice).json()) == 1


def test_query_string_cannot_pick_the_user(client, auth_on):
    """The old ?external_id= parameter must not let one user read another."""
    alice = bearer(token("user_alice"))
    client.post("/api/commitments", headers=alice, json={
        "title": "Private", "weekday": 1, "start_time": "09:00", "end_time": "10:00"})
    bob = bearer(token("user_bob"))
    client.get("/api/settings", headers=bob)
    resp = client.get("/api/commitments?external_id=user_alice", headers=bob)
    assert resp.json() == []
