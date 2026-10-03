# Architecture

See [PROBLEM.md](PROBLEM.md) for what we are building and why.
The database schema is in [../db/schema.sql](../db/schema.sql).

## Tech stack

| Layer | Pick | Why |
|---|---|---|
| Frontend | **Next.js (React + TypeScript)** | Most-used React framework. Public pages (directory, results, profiles, verify) render on the server: fast and searchable. |
| UI | **Tailwind CSS + shadcn/ui** | Clean, accessible components we own. |
| Data + forms | **TanStack Query, React Hook Form, Zod** | Caching, retries, type-safe validation. |
| Check-in scanner | **Browser camera QR scanner** (inside the web app) | Core members scan from their phone browser. Nothing to install. |
| Backend | **FastAPI (Python)** | Async, Pydantic validates every input, free OpenAPI docs, best libraries for PDF/QR/AI. |
| API types | **OpenAPI → generated TypeScript client** | Frontend and backend can't drift. |
| Database | **PostgreSQL** | Strict relational rules, transactions, row-level security. |
| ORM | **SQLAlchemy 2 (async) + Alembic** | Standard Python stack. |
| Cache / limits / sessions | **Redis** | One tool, three jobs. |
| Background jobs | **arq (Redis)** | Certificates, notifications, badge awards run off the request path. |
| Files | **Cloudflare R2** (S3-compatible) | No download fees. |
| Email | **Amazon SES or Resend** | Cheap and reliable. |
| Push | **Web Push** (optional later: WhatsApp Cloud API) | Reaches students where they are. |
| Host (start) | Vercel + Railway/Render + Neon/Supabase Postgres + Upstash Redis | Free or cheap tiers. |
| Host (scale) | Docker on Fly.io or AWS ECS, Postgres read replica, Cloudflare CDN | Same containers, more of them. |
| Monitoring | Sentry, OpenTelemetry, structured logs | |
| CI | GitHub Actions: pytest, Vitest, Playwright, dependency scan | |

## Campuses

All SRM campuses share `@srmist.edu.in`, so email can't tell them apart. The student picks
a campus at onboarding; every club belongs to one campus. The directory shows the
student's own campus first, with a filter for others. Events are open to any SRM student
unless the club limits them.

## Roles and permissions

Club roles live in the `memberships` table, not in the login token. A student can be
Admin of one club and Member of another. Every check is made on the server, per
request, from the database.

| Action | Platform Owner | Club Admin | Core | Member | SRM Student | Outside |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Request a new club | ✓ | ✓ | ✓ | ✓ | ✓ | – |
| Approve / reject / suspend a club | ✓ | – | – | – | – | – |
| Hand a club to a new admin | ✓ | ✓ (own) | – | – | – | – |
| Set platform rules (max clubs per student) | ✓ | – | – | – | – | – |
| Edit club profile, recruitment rules | – | ✓ | – | – | – | – |
| Open recruitment drive, move applicants | – | ✓ | – | – | – | – |
| Make someone Core / Admin, remove members | – | ✓ | – | – | – | – |
| Create / edit / publish events | – | ✓ | ✓ | – | – | – |
| Approve outside participants | – | ✓ | ✓ (own events) | – | – | – |
| Scan check-ins, post event updates | – | ✓ | ✓ | – | – | – |
| Publish results, issue certificates | – | ✓ | – | – | – | – |
| Apply to clubs | – | ✓ | ✓ | ✓ | ✓ | – |
| Register for events | – | ✓ | ✓ | ✓ | ✓ (instant) | ✓ (needs approval) |

The Platform Owner does **not** automatically see inside clubs (applications, members'
data). They only manage which clubs exist. This keeps one person from holding
everyone's data, and it is fairer to the clubs.

The **Platform Owner** flag is set from the command line (`is_platform_owner`). It is
never available through signup or the API. More owners can be added later, so the
platform survives after the developer graduates.

All permission checks go through one function:

```python
can(user, action, resource) -> bool
```

Every endpoint calls it. Postgres row-level security is a second lock.

## Security

**Sign-in**
- Everyone signs in with a 6-digit code sent to their email. No passwords to store.
- A code that reaches an `@srmist.edu.in` inbox proves the person is at SRM, so they get a
  college account. Any other email gets an outside-guest account (`kind = external`).
- Codes are stored only as a hash, expire after 10 minutes, die after 5 wrong tries, and
  sending is rate-limited per email and per IP.
- Google sign-in (with the `hd = "srmist.edu.in"` check) is built but switched off with
  `GOOGLE_SIGNIN_ENABLED=false`, because SRM's Google Workspace blocks outside apps for
  students. It can be turned on if SRM IT allows the app.
- Codes must reach SRM inboxes, so the email service needs a real sender domain with
  SPF, DKIM and DMARC set up, or SRM's mail filter may mark codes as spam.
- First sign-in asks for campus, department and year (onboarding).

**Sessions**
- Server sessions in Redis. The session ID sits in an **httpOnly, Secure, SameSite=Lax**
  cookie. Nothing goes in `localStorage`. Supports "log out of all devices".
- The API lives on the same site (`api.<domain>`) so cookies work. Every write needs a
  CSRF token.

**Abuse limits**
- Redis rate limits on: OTP send/verify, applications, registrations, verify pages.
- An idempotency key on registration and application, so double clicks do nothing.

**QR codes**
- **Check-in:** each registration's QR is an HMAC-signed token that rotates every 30 s.
  It works once. Screenshots shared on WhatsApp stop working.
- **Certificates / badges:** 128-bit random public IDs. They can't be guessed.

**Files**
- Private bucket. Downloads use short-lived presigned URLs. Uploads are checked by real
  file type and size.

**Records**
- An **audit log** of every admin, core and owner action, with who, what, before/after
  and when.

**Baseline**
- Pydantic + Zod validation, CSP + HSTS headers, secrets in the host's secret store,
  daily backups, Dependabot.

**Privacy (India DPDP Act 2023)**
- Collect only what is needed.
- Clear consent at signup.
- Account deletion.
- Outside users' data is visible only to the clubs whose events they joined.

## Scaling

Load comes in **spikes**: a hackathon opens 300 seats and 3,000 people click in the
same minute.

1. **No overbooking.** A seat is taken with one atomic statement:
   ```sql
   UPDATE events SET seats_taken = seats_taken + 1
   WHERE id = $1 AND seats_taken < capacity
   RETURNING seats_taken;
   ```
   It is backed by `UNIQUE (event_id, user_id)`.
2. **The API holds no state.** Sessions live in Redis, so we can run 1 or 20 API
   containers.
3. **Slow work goes to the queue.** Certificate PDFs, emails, push and badge awards are
   background jobs.
4. **Public pages are cached at the CDN edge.** This covers the club directory, results,
   profiles and verify pages.
5. **Database:** PgBouncer pooling, indexes that match real queries, cursor pagination,
   and a read replica for the leaderboard and profiles.
6. **Load test with k6** ("3,000 registrations in 60 s") before the first real event.

## Main flows

**New club**
1. Student requests a club.
2. Status is `pending`.
3. Platform Owner approves.
4. Status is `active`, and the requester becomes Club Admin.

**Recruitment**
1. Club Admin creates a drive with rules and questions.
2. The drive opens.
3. Students apply. The backend checks eligibility, the window dates and the max-clubs
   rule.
4. Applications land in the club's queue.
5. The admin moves each one through the stages.
6. **Selected** creates the membership.

**Event**
1. Draft.
2. Published.
3. Registration:
   - SRM students are confirmed.
   - Outside participants are `pending` until an organizer approves them.
4. The event goes live. Updates are pushed and check-in is by QR scan.
5. The event is completed.
6. Results are published.
7. A job creates the certificates and checks the badge rules.
8. Notifications are sent.

**Badges**
1. A badge's rule is stored as data in `badges.criteria`, for example
   `{"type": "events_attended", "count": 5}`.
2. After check-in or results, a job counts the user's records and awards any badges
   they now meet.
3. Awarding is safe to run twice, because of `UNIQUE (user_id, badge_id)`.
