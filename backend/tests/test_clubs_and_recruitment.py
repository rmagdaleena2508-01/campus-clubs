from tests.conftest import make_owner, onboard, sign_in, window

CLUB = {
    "name": "Robotics Club",
    "slug": "robotics",
    "tagline": "Build robots",
    "description": "We build autonomous robots and compete in national contests every year.",
    "category": "technical",
}

QUESTIONS = [
    {"id": "why", "label": "Why do you want to join?", "type": "long_text"},
    {"id": "team", "label": "Team", "type": "choice", "options": ["Tech", "Design"]},
    {"id": "github", "label": "GitHub", "type": "url", "required": False},
]

ANSWERS = {"why": "I love robots", "team": "Tech"}


async def setup_club(client_factory):
    """Owner approves a club requested by a student. Returns (owner, admin, club)."""
    owner, admin = client_factory(), client_factory()
    await sign_in(owner, "owner01@srmist.edu.in", "Owner")
    await make_owner("owner01@srmist.edu.in")
    await sign_in(admin, "pres01@srmist.edu.in", "President")
    await onboard(admin, "RA0000000000001")

    r = await admin.post("/clubs", json=CLUB)
    assert r.status_code == 201, r.text
    club = r.json()
    r = await owner.post(f"/clubs/{club['id']}/review", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    return owner, admin, club


async def open_drive(admin, club_id, **overrides):
    opens, closes = window()
    body = {"title": "Core Team 2026", "opens_at": opens, "closes_at": closes, "form_schema": QUESTIONS} | overrides
    r = await admin.post(f"/clubs/{club_id}/drives", json=body)
    assert r.status_code == 201, r.text
    drive = r.json()
    assert (await admin.post(f"/drives/{drive['id']}/open")).status_code == 200
    return drive


async def student(client_factory, email, register_no, **kw):
    c = client_factory()
    await sign_in(c, email)
    await onboard(c, register_no, **kw)
    return c


# --- Clubs ---

async def test_club_request_needs_onboarding(client_factory):
    c = client_factory()
    await sign_in(c, "new01@srmist.edu.in")
    assert (await c.post("/clubs", json=CLUB)).status_code == 428


async def test_only_owner_can_review_clubs(client_factory):
    a = await student(client_factory, "s1@srmist.edu.in", "RA0000000000010")
    club = (await a.post("/clubs", json=CLUB)).json()
    assert (await a.post(f"/clubs/{club['id']}/review", json={"decision": "approve"})).status_code == 403
    assert (await a.get("/clubs/review-queue")).status_code == 403


async def test_pending_club_hidden_from_directory_until_approved(client_factory):
    owner = client_factory()
    await sign_in(owner, "owner01@srmist.edu.in")
    await make_owner("owner01@srmist.edu.in")
    a = await student(client_factory, "s1@srmist.edu.in", "RA0000000000010")
    club = (await a.post("/clubs", json=CLUB)).json()

    assert (await client_factory().get("/clubs")).json() == []
    assert (await client_factory().get("/clubs/robotics")).status_code == 404
    assert (await a.get("/clubs/robotics")).status_code == 200  # requester can see it

    queue = (await owner.get("/clubs/review-queue")).json()
    assert [c["slug"] for c in queue] == ["robotics"]
    await owner.post(f"/clubs/{club['id']}/review", json={"decision": "approve"})
    assert [c["slug"] for c in (await client_factory().get("/clubs")).json()] == ["robotics"]


async def test_approval_makes_requester_admin(client_factory):
    _, _, club = await setup_club(client_factory)
    members = (await client_factory().get(f"/clubs/{club['id']}/members")).json()
    assert [(m["handle"], m["role"]) for m in members] == [("pres01", "admin")]


async def test_last_admin_cannot_step_down(client_factory):
    _, admin, club = await setup_club(client_factory)
    me = (await admin.get("/me")).json()["user"]
    r = await admin.put(f"/clubs/{club['id']}/members/{me['id']}/role", json={"role": "member"})
    assert r.status_code == 400


# --- Recruitment ---

async def test_full_recruitment_flow(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"])

    s = await student(client_factory, "stu01@srmist.edu.in", "RA0000000000100")
    r = await s.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]

    # applying twice is refused
    assert (await s.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})).status_code == 409
    # a student can't see the review queue
    assert (await s.get(f"/drives/{drive['id']}/applications")).status_code == 403

    queue = (await admin.get(f"/drives/{drive['id']}/applications")).json()
    assert [a["applicant_handle"] for a in queue] == ["stu01"]

    for stage in ("shortlisted", "interview"):
        assert (await admin.patch(f"/applications/{app_id}", json={"stage": stage})).status_code == 200
    r = await admin.patch(f"/applications/{app_id}", json={"stage": "selected", "internal_note": "Strong"})
    assert r.status_code == 200, r.text

    # the student is now a member, and never sees the internal note
    members = (await client_factory().get(f"/clubs/{club['id']}/members")).json()
    assert ("stu01", "member") in [(m["handle"], m["role"]) for m in members]
    mine = (await s.get("/me/applications")).json()
    assert mine[0]["stage"] == "selected" and "internal_note" not in mine[0]

    # decided applications can't move again
    assert (await admin.patch(f"/applications/{app_id}", json={"stage": "rejected"})).status_code == 409


async def test_answers_are_checked_against_the_form(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"])
    s = await student(client_factory, "stu01@srmist.edu.in", "RA0000000000100")
    url = f"/drives/{drive['id']}/applications"

    assert (await s.post(url, json={"answers": {"team": "Tech"}})).status_code == 422          # missing required
    assert (await s.post(url, json={"answers": ANSWERS | {"team": "Hacking"}})).status_code == 422  # bad choice
    assert (await s.post(url, json={"answers": ANSWERS | {"github": "javascript:x"}})).status_code == 422


async def test_eligibility_rules(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"], eligibility={"years": [1]})
    second_year = await student(client_factory, "stu01@srmist.edu.in", "RA0000000000100", year=2)
    first_year = await student(client_factory, "stu02@srmist.edu.in", "RA0000000000101", year=1)

    url = f"/drives/{drive['id']}/applications"
    assert (await second_year.post(url, json={"answers": ANSWERS})).status_code == 403
    assert (await first_year.post(url, json={"answers": ANSWERS})).status_code == 201


async def test_drive_not_yet_open_refuses_applications(client_factory):
    _, admin, club = await setup_club(client_factory)
    opens, closes = window(hours_from_now_start=24)
    drive = await open_drive(admin, club["id"], opens_at=opens, closes_at=closes)
    s = await student(client_factory, "stu01@srmist.edu.in", "RA0000000000100")
    assert (await s.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})).status_code == 400


async def test_seat_limit(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"], seats=1)
    ids = []
    for i in range(2):
        s = await student(client_factory, f"stu0{i}@srmist.edu.in", f"RA000000000020{i}")
        ids.append((await s.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})).json()["id"])

    assert (await admin.patch(f"/applications/{ids[0]}", json={"stage": "selected"})).status_code == 200
    assert (await admin.patch(f"/applications/{ids[1]}", json={"stage": "selected"})).status_code == 409


async def test_outside_participants_cannot_apply_to_clubs(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"])

    guest = client_factory()
    await sign_in(guest, "guest@gmail.com", "Guest", institution="VIT")
    assert (await guest.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})).status_code == 403


async def test_member_cannot_manage_drives(client_factory):
    _, admin, club = await setup_club(client_factory)
    drive = await open_drive(admin, club["id"])
    s = await student(client_factory, "stu01@srmist.edu.in", "RA0000000000100")
    app_id = (await s.post(f"/drives/{drive['id']}/applications", json={"answers": ANSWERS})).json()["id"]
    await admin.patch(f"/applications/{app_id}", json={"stage": "selected"})

    # now a member, but members can't create drives or close them
    opens, closes = window()
    body = {"title": "Sneaky", "opens_at": opens, "closes_at": closes, "form_schema": QUESTIONS}
    assert (await s.post(f"/clubs/{club['id']}/drives", json=body)).status_code == 403
    assert (await s.post(f"/drives/{drive['id']}/close")).status_code == 403


async def test_every_admin_action_is_audited(client_factory):
    _, admin, club = await setup_club(client_factory)
    await open_drive(admin, club["id"])

    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import AuditLog

    async with SessionLocal() as db:
        actions = (await db.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["club.request", "club.approve", "drive.create", "drive.open"]
