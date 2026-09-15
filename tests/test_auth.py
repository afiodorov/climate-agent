"""GitHub sign-in and the admin gate on deleting conversations.

The flow runs against a fake GitHub (an httpx mock transport), so what is
tested is this side: the state cookie, the signed user cookie, who counts as
an admin, and that DELETE refuses everyone else.
"""

import time

import httpx
import pytest
import pytest_asyncio

from climate_agent import climate, gateway, store
from climate_agent.api import auth
from climate_agent.api.app import app

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _allow(question, history):
    return True


async def _ask(question, history):
    return "An answer.", history


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    # No lifespan and no MCP session manager here: that manager can start only
    # once per process and test_agents owns it. These routes need only the
    # gateway on app.state.
    app.state.gateway = gateway.Gateway(
        climate.build_graph(ask=_ask, guard=_allow), store_=store.MemoryStore()
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://climate.example"
    ) as c:
        yield c


@pytest.fixture
def github(monkeypatch):
    """A configured deployment and a GitHub that accepts one code."""
    monkeypatch.setenv("GITHUB_CLIENT_ID", "id-123")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "secret-456")
    monkeypatch.setenv("ADMIN_GITHUB_USERS", "afiodorov, Other-Admin")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == auth.GITHUB_TOKEN:
            seen["token_request"] = dict(httpx.QueryParams(request.content.decode()))
            if seen["token_request"].get("code") != "good-code":
                return httpx.Response(200, json={"error": "bad_verification_code"})
            return httpx.Response(
                200, json={"access_token": "tok", "token_type": "bearer"}
            )
        if request.url == auth.GITHUB_USER:
            seen["auth_header"] = request.headers.get("authorization")
            return httpx.Response(200, json={"login": seen.get("login", "afiodorov")})
        return httpx.Response(404)

    monkeypatch.setattr(auth, "_transport", httpx.MockTransport(handler))
    return seen


def _cookie(login: str, days: int = 1) -> str:
    return auth._sign(login, int(time.time()) + days * 86400)


async def test_anonymous_me_and_unconfigured_delete(client, monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTH_TRUSTED_USER_HEADER", raising=False)
    r = await client.get("/auth/me")
    assert r.json() == {"login": None, "admin": False, "configured": False}
    r = await client.delete("/api/sessions/anything")
    assert r.status_code == 403
    assert "not configured" in r.json()["detail"]
    r = await client.get("/auth/login")
    assert r.status_code == 404


async def test_login_redirects_to_github_with_a_state_cookie(client, github):
    r = await client.get("/auth/login")
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(auth.GITHUB_AUTHORIZE)
    assert "client_id=id-123" in location
    assert "redirect_uri=https%3A%2F%2Fclimate.example%2Foauth2%2Fcallback" in location
    state = httpx.URL(location).params["state"]
    assert r.cookies[auth.STATE_COOKIE] == state


async def test_callback_signs_the_user_in(client, github):
    r = await client.get("/auth/login")
    state = httpx.URL(r.headers["location"]).params["state"]
    client.cookies.set(auth.STATE_COOKIE, state)

    r = await client.get(
        auth.CALLBACK_PATH, params={"code": "good-code", "state": state}
    )
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert github["token_request"]["client_secret"] == "secret-456"
    assert github["auth_header"] == "Bearer tok"
    assert auth.USER_COOKIE in r.cookies

    client.cookies.set(auth.USER_COOKIE, r.cookies[auth.USER_COOKIE])
    me = (await client.get("/auth/me")).json()
    assert me == {"login": "afiodorov", "admin": True, "configured": True}

    r = await client.post("/auth/logout")
    assert r.status_code == 204
    client.cookies.clear()


async def test_callback_rejects_a_bad_state_or_code(client, github):
    r = await client.get(auth.CALLBACK_PATH, params={"code": "good-code", "state": "x"})
    assert r.status_code == 400
    client.cookies.set(auth.STATE_COOKIE, "s")
    r = await client.get(auth.CALLBACK_PATH, params={"code": "bad-code", "state": "s"})
    assert r.status_code == 502
    client.cookies.clear()


async def test_delete_needs_an_admin(client, github):
    r = await client.delete("/api/sessions/s1")
    assert r.status_code == 403 and "Sign in" in r.json()["detail"]

    r = await client.delete(
        "/api/sessions/s1", cookies={auth.USER_COOKIE: _cookie("someone-else")}
    )
    assert r.status_code == 403 and "not an admin" in r.json()["detail"]

    forged = _cookie("afiodorov").rsplit("|", 1)[0] + "|" + "0" * 64
    r = await client.delete("/api/sessions/s1", cookies={auth.USER_COOKIE: forged})
    assert r.status_code == 403

    expired = auth._sign("afiodorov", int(time.time()) - 1)
    r = await client.delete("/api/sessions/s1", cookies={auth.USER_COOKIE: expired})
    assert r.status_code == 403

    r = await client.delete(
        "/api/sessions/s1", cookies={auth.USER_COOKIE: _cookie("afiodorov")}
    )
    assert r.status_code == 204
    # Admin names are case-insensitive, and the list is trimmed.
    r = await client.delete(
        "/api/sessions/s1", cookies={auth.USER_COOKIE: _cookie("other-admin")}
    )
    assert r.status_code == 204


async def test_me_ignores_a_cookie_once_the_secret_changes(client, github, monkeypatch):
    good = _cookie("afiodorov")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "rotated")
    r = await client.get("/auth/me", cookies={auth.USER_COOKIE: good})
    assert r.json()["login"] is None


async def test_trusted_proxy_header_names_the_user(client, monkeypatch):
    """Staging: Caddy copies X-Auth-Request-User from oauth2-proxy."""
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.setenv("AUTH_TRUSTED_USER_HEADER", "X-Auth-Request-User")
    r = await client.get("/auth/me")
    assert r.json() == {"login": None, "admin": False, "configured": False}
    r = await client.get("/auth/me", headers={"X-Auth-Request-User": "AFiodorov"})
    assert r.json() == {"login": "AFiodorov", "admin": True, "configured": False}
    r = await client.delete(
        "/api/sessions/s1", headers={"X-Auth-Request-User": "guest"}
    )
    assert r.status_code == 403
    r = await client.delete(
        "/api/sessions/s1", headers={"X-Auth-Request-User": "afiodorov"}
    )
    assert r.status_code == 204
