# Campus Clubs (SRM)

One web app where SRM clubs recruit members, run events, take attendance, publish
results, and issue certificates and badges. It replaces Google Forms and WhatsApp groups.

- [docs/PROBLEM.md](docs/PROBLEM.md): what we're solving and for whom
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): stack, roles, security, scaling
- [db/schema.sql](db/schema.sql): the database
- [docs/PRD.pdf](docs/PRD.pdf): the full product plan

Project page: https://rmagdaleena2508-01.github.io/campus-clubs/

## Status

| Phase | What | State |
|---|---|---|
| 0 | GitHub repo, auto tests on every push, project page on GitHub Pages | **Done** |
| 1 | Sign-in with email codes (an @srmist.edu.in inbox makes you an SRM student), onboarding, clubs, owner review, roles, recruitment drives and applications | Backend **done** (33 tests). Web app next |
| 2 | Events, registration, outside-participant approval, event updates | |
| 3 | QR check-in, results, certificates | |
| 4 | Badges, public profiles | |
| 5 | Pilot with 3 clubs, then all SRM campuses | |
| 6 | AI club finder | |

Each phase ships both backend and web app pages. See the PRD for details.

## Run the backend locally

You need Docker Desktop and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d                 # Postgres on :5433, Redis on :6380
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head          # create the tables
uv run python -m app.cli seed        # campuses + departments
uv run uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

To make yourself Platform Owner, sign in once, then run:

```bash
uv run python -m app.cli make-owner you@srmist.edu.in
```

## Tests

```bash
cd backend && uv run pytest
```

Tests use a separate `clubs_test` database and Redis db 15, so they never touch your dev data.
