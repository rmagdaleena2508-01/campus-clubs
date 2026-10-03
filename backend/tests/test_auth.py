import pytest

from tests.conftest import onboard, sign_in


# --- Google sign-in rules (the real _verify, with Google's signature check faked) ---

@pytest.fixture
def google_claims(monkeypatch):
    from app.security import google

    claims = {}
    monkeypatch.setattr(google.id_token, "verify_oauth2_token", lambda *a, **k: dict(claims))
    return claims


def base_claims(email, hd):
    c = {"iss": "https://accounts.google.com", "sub": "123", "email": email, "email_verified": True, "name": "A"}
    if hd:
        c["hd"] = hd
    return c


def test_google_accepts_srm_workspace_account(google_claims):
    from app.security.google import _verify

    google_claims.update(base_claims("AB1234@srmist.edu.in", "srmist.edu.in"))
    assert _verify("token").email == "ab1234@srmist.edu.in"


@pytest.mark.parametrize("email,hd", [
    ("someone@gmail.com", None),                     # personal Gmail
    ("ab1234@srmist.edu.in", None),                  # missing hd claim
    ("x@otheruni.edu", "otheruni.edu"),              # another college's Workspace
    ("ab1234@srmist.edu.in.evil.com", "srmist.edu.in"),  # lookalike email
])
def test_google_rejects_non_srm(google_claims, email, hd):
    from app.errors import NotAuthenticated
    from app.security.google import _verify

    google_claims.update(base_claims(email, hd))
    with pytest.raises(NotAuthenticated):
        _verify("token")


def test_google_rejects_unverified_email(google_claims):
    from app.errors import NotAuthenticated
    from app.security.google import _verify

    google_claims.update(base_claims("ab1234@srmist.edu.in", "srmist.edu.in") | {"email_verified": False})
    with pytest.raises(NotAuthenticated):
        _verify("token")


# --- Sessions ---

async def test_sign_in_sets_httponly_cookie_and_needs_onboarding(client_factory):
    c = client_factory()
    r = await c.post("/auth/google", json={"id_token": "ab1234@srmist.edu.in|Asha"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert r.json()["user"]["needs_onboarding"] is True
    assert r.json()["user"]["handle"] == "ab1234"


async def test_write_without_csrf_token_is_refused(client_factory):
    c = client_factory()
    await sign_in(c, "ab1234@srmist.edu.in")
    del c.headers["X-CSRF-Token"]
    r = await c.put("/me/onboarding", json={"campus_id": 1, "department_id": 1, "year_of_study": 2,
                                           "register_no": "RA2211003"})
    assert r.status_code == 403


async def test_logout_ends_session(client_factory):
    c = client_factory()
    await sign_in(c, "ab1234@srmist.edu.in")
    assert (await c.post("/auth/logout")).status_code == 200
    assert (await c.get("/me")).status_code == 401


async def test_onboarding_rejects_duplicate_register_no(client_factory):
    a, b = client_factory(), client_factory()
    await sign_in(a, "aa1111@srmist.edu.in")
    await onboard(a, "RA2211003010001")
    await sign_in(b, "bb2222@srmist.edu.in")
    r = await b.put("/me/onboarding", json={"campus_id": 1, "department_id": 1, "year_of_study": 2,
                                           "register_no": "ra2211003010001"})
    assert r.status_code == 409


# --- Outside participants (email code) ---

async def test_outside_participant_code_flow(client_factory, sent_emails):
    c = client_factory()
    assert (await c.post("/auth/email/start", json={"email": "Guest@Gmail.com"})).status_code == 200
    to, body = sent_emails[-1]
    code = body.split()[3].rstrip(".")
    assert to == "guest@gmail.com"

    wrong = await c.post("/auth/email/verify", json={
        "email": "guest@gmail.com", "code": "000000" if code != "000000" else "111111",
        "full_name": "Guest Person", "institution": "VIT"})
    assert wrong.status_code == 400

    r = await c.post("/auth/email/verify", json={
        "email": "guest@gmail.com", "code": code, "full_name": "Guest Person", "institution": "VIT"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["kind"] == "external"
    assert r.json()["user"]["needs_onboarding"] is False


async def test_srm_email_cannot_use_email_codes(client_factory, sent_emails):
    r = await client_factory().post("/auth/email/start", json={"email": "ab1234@srmist.edu.in"})
    assert r.status_code == 400
    assert sent_emails == []


async def test_email_code_is_burned_after_too_many_wrong_guesses(client_factory, sent_emails):
    c = client_factory()
    await c.post("/auth/email/start", json={"email": "guest@gmail.com"})
    code = sent_emails[-1][1].split()[3].rstrip(".")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        await c.post("/auth/email/verify", json={"email": "guest@gmail.com", "code": wrong,
                                                 "full_name": "G P", "institution": "VIT"})
    r = await c.post("/auth/email/verify", json={"email": "guest@gmail.com", "code": code,
                                                 "full_name": "G P", "institution": "VIT"})
    assert r.status_code == 400  # even the right code no longer works


async def test_email_code_requests_are_rate_limited(client_factory, sent_emails):
    c = client_factory()
    codes = [(await c.post("/auth/email/start", json={"email": "spam@gmail.com"})).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
