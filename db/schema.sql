-- Campus Clubs: PostgreSQL schema (v1 draft)
-- Design notes are in docs/ARCHITECTURE.md.
-- This file is the source of truth for the first Alembic migration.

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
CREATE TYPE user_kind          AS ENUM ('college', 'external');
CREATE TYPE club_status        AS ENUM ('pending', 'active', 'rejected', 'suspended', 'archived');
CREATE TYPE club_role          AS ENUM ('admin', 'core', 'member');
CREATE TYPE membership_status  AS ENUM ('active', 'left', 'removed');
CREATE TYPE drive_status       AS ENUM ('draft', 'open', 'closed');
CREATE TYPE application_stage  AS ENUM ('applied', 'shortlisted', 'interview', 'selected', 'rejected', 'withdrawn');
CREATE TYPE event_status       AS ENUM ('draft', 'published', 'live', 'completed', 'cancelled');
CREATE TYPE event_visibility   AS ENUM ('members', 'college', 'public');
CREATE TYPE registration_status AS ENUM ('pending', 'confirmed', 'rejected', 'cancelled');
CREATE TYPE event_result       AS ENUM ('none', 'participant', 'runner_up', 'winner', 'special');
CREATE TYPE update_kind        AS ENUM ('general', 'venue_change', 'time_change', 'starting', 'cancelled');

-- ---------------------------------------------------------------------------
-- People
-- ---------------------------------------------------------------------------
CREATE TABLE users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             citext NOT NULL UNIQUE,
    full_name         text   NOT NULL,
    handle            citext NOT NULL UNIQUE,          -- public profile: /u/<handle>
    kind              user_kind NOT NULL,              -- college = verified @srmist.edu.in
    google_sub        text UNIQUE,                     -- set for Google sign-in (all college users)
    avatar_key        text,
    is_platform_owner boolean NOT NULL DEFAULT false,  -- set from CLI only, never via API
    created_at        timestamptz NOT NULL DEFAULT now(),
    deleted_at        timestamptz,                     -- soft delete (DPDP account deletion)
    CONSTRAINT college_email_domain CHECK (
        kind <> 'college' OR email::text ~* '@srmist\.edu\.in$'
    ),
    CONSTRAINT handle_format CHECK (handle::text ~ '^[a-z0-9][a-z0-9-]{2,29}$')
);

-- SRM has several campuses sharing one email domain
CREATE TABLE campuses (
    id    smallserial PRIMARY KEY,
    code  text NOT NULL UNIQUE,   -- e.g. KTR, RMP, VDP, NCR, TRP
    name  text NOT NULL
);

CREATE TABLE departments (
    id    smallserial PRIMARY KEY,
    code  text NOT NULL UNIQUE,   -- e.g. CSE, ECE, MECH
    name  text NOT NULL
);

-- Extra details for SRM students
CREATE TABLE student_profiles (
    user_id        uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    register_no    text UNIQUE,
    campus_id      smallint REFERENCES campuses(id),  -- asked during onboarding
    department_id  smallint REFERENCES departments(id),
    year_of_study  smallint CHECK (year_of_study BETWEEN 1 AND 5),
    bio            text,
    interests      text[] NOT NULL DEFAULT '{}'
);

-- Extra details for outside participants
CREATE TABLE external_profiles (
    user_id      uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    institution  text NOT NULL,
    phone        text
);

-- Platform-wide rules set by the Platform Owner, e.g. ('max_clubs_per_student', '3')
CREATE TABLE platform_settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_by  uuid REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Clubs and membership
-- ---------------------------------------------------------------------------
CREATE TABLE clubs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           citext NOT NULL UNIQUE,              -- /clubs/<slug>
    name           text   NOT NULL,
    tagline        text,
    description    text   NOT NULL,
    category       text   NOT NULL,                     -- technical, cultural, sports, ...
    campus_id      smallint NOT NULL REFERENCES campuses(id),
    department_id  smallint REFERENCES departments(id), -- null = open to all departments
    logo_key       text,
    links          jsonb  NOT NULL DEFAULT '[]',        -- [{label, url}]
    status         club_status NOT NULL DEFAULT 'pending',
    requested_by   uuid NOT NULL REFERENCES users(id),
    reviewed_by    uuid REFERENCES users(id),           -- the Platform Owner
    reviewed_at    timestamptz,
    review_note    text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_clubs_directory ON clubs (campus_id, status, category);

CREATE TABLE memberships (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id      uuid NOT NULL REFERENCES clubs(id),
    user_id      uuid NOT NULL REFERENCES users(id),
    role         club_role NOT NULL DEFAULT 'member',
    title        text,                                  -- display title, e.g. "Tech Lead"
    status       membership_status NOT NULL DEFAULT 'active',
    joined_at    timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    UNIQUE (club_id, user_id)
);
CREATE INDEX ix_memberships_user ON memberships (user_id) WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- Recruitment (replaces Google Forms)
-- ---------------------------------------------------------------------------
CREATE TABLE recruitment_drives (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id         uuid NOT NULL REFERENCES clubs(id),
    title           text NOT NULL,                      -- e.g. "Core Team 2026"
    description     text,
    status          drive_status NOT NULL DEFAULT 'draft',
    opens_at        timestamptz NOT NULL,
    closes_at       timestamptz NOT NULL,
    seats           integer CHECK (seats > 0),          -- how many to select (null = no limit)
    -- Who may apply: {"years": [1,2], "department_ids": [3,4]}; empty = everyone at SRM
    eligibility     jsonb NOT NULL DEFAULT '{}',
    -- The form: [{id, label, type: text|long_text|choice|multi|url|file, required, options}]
    form_schema     jsonb NOT NULL DEFAULT '[]',
    created_by      uuid NOT NULL REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (closes_at > opens_at)
);
CREATE INDEX ix_drives_club_status ON recruitment_drives (club_id, status);

CREATE TABLE applications (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_id        uuid NOT NULL REFERENCES recruitment_drives(id),
    user_id         uuid NOT NULL REFERENCES users(id),
    answers         jsonb NOT NULL,                     -- keyed by form_schema question id
    stage           application_stage NOT NULL DEFAULT 'applied',
    internal_note   text,                               -- only club admins see this
    decided_by      uuid REFERENCES users(id),
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (drive_id, user_id)
);
CREATE INDEX ix_applications_queue ON applications (drive_id, stage);
CREATE INDEX ix_applications_user  ON applications (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Events
-- ---------------------------------------------------------------------------
CREATE TABLE events (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id               uuid NOT NULL REFERENCES clubs(id),
    slug                  citext NOT NULL,
    title                 text NOT NULL,
    description           text NOT NULL,
    category              text,                         -- hackathon, workshop, quiz... (used by badges)
    venue                 text NOT NULL,
    map_url               text,
    starts_at             timestamptz NOT NULL,
    ends_at               timestamptz NOT NULL,
    registration_opens_at timestamptz,
    registration_closes_at timestamptz,
    capacity              integer CHECK (capacity > 0), -- null = unlimited
    seats_taken           integer NOT NULL DEFAULT 0,
    visibility            event_visibility NOT NULL DEFAULT 'college',
    allow_external        boolean NOT NULL DEFAULT false,
    status                event_status NOT NULL DEFAULT 'draft',
    banner_key            text,
    results_published_at  timestamptz,
    created_by            uuid NOT NULL REFERENCES users(id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (club_id, slug),
    CHECK (ends_at > starts_at),
    CHECK (capacity IS NULL OR seats_taken <= capacity),
    CHECK (NOT allow_external OR visibility = 'public')
);
CREATE INDEX ix_events_upcoming ON events (starts_at) WHERE status IN ('published', 'live');
CREATE INDEX ix_events_club     ON events (club_id, starts_at DESC);

CREATE TABLE registrations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        uuid NOT NULL REFERENCES events(id),
    user_id         uuid NOT NULL REFERENCES users(id),
    status          registration_status NOT NULL,       -- college users start 'confirmed', external 'pending'
    decided_by      uuid REFERENCES users(id),          -- organizer who approved/rejected an outsider
    decided_at      timestamptz,
    checkin_secret  bytea NOT NULL DEFAULT gen_random_bytes(32), -- seeds the rotating check-in QR
    checked_in_at   timestamptz,
    checked_in_by   uuid REFERENCES users(id),
    result          event_result NOT NULL DEFAULT 'none',
    position        smallint,                           -- 1st, 2nd, ... for ranked results
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, user_id),
    CHECK (result = 'none' OR checked_in_at IS NOT NULL)  -- no result without attendance
);
CREATE INDEX ix_registrations_approval ON registrations (event_id, status);
CREATE INDEX ix_registrations_user     ON registrations (user_id, created_at DESC);

-- Live updates pushed to registered people ("venue moved", "starting now")
CREATE TABLE event_updates (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id    uuid NOT NULL REFERENCES events(id),
    kind        update_kind NOT NULL DEFAULT 'general',
    body        text NOT NULL,
    created_by  uuid NOT NULL REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_event_updates_event ON event_updates (event_id, created_at DESC);

-- Club-wide announcements (members only)
CREATE TABLE announcements (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    club_id     uuid NOT NULL REFERENCES clubs(id),
    title       text NOT NULL,
    body        text NOT NULL,
    is_pinned   boolean NOT NULL DEFAULT false,
    created_by  uuid NOT NULL REFERENCES users(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_announcements_club ON announcements (club_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Proof: certificates and badges
-- ---------------------------------------------------------------------------
CREATE TABLE certificates (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id        text NOT NULL UNIQUE,              -- 128-bit random, base62; used in /verify/<public_id>
    registration_id  uuid NOT NULL UNIQUE REFERENCES registrations(id),
    result           event_result NOT NULL,
    pdf_key          text,                              -- null until the job has rendered it
    issued_at        timestamptz NOT NULL DEFAULT now(),
    revoked_at       timestamptz,
    revoke_reason    text
);

CREATE TABLE badges (
    id           smallserial PRIMARY KEY,
    slug         text NOT NULL UNIQUE,                  -- e.g. 'hackathon-x3'
    name         text NOT NULL,
    description  text NOT NULL,
    icon_key     text NOT NULL,
    tier         smallint NOT NULL DEFAULT 1,           -- 1 = base, 2/3/4 = x2/x3/x4 like GitHub
    -- Rule as data, e.g. {"type": "events_attended", "category": "hackathon", "count": 3}
    criteria     jsonb NOT NULL,
    is_active    boolean NOT NULL DEFAULT true
);

CREATE TABLE user_badges (
    user_id     uuid NOT NULL REFERENCES users(id),
    badge_id    smallint NOT NULL REFERENCES badges(id),
    public_id   text NOT NULL UNIQUE,                   -- public verify link
    awarded_at  timestamptz NOT NULL DEFAULT now(),
    source      jsonb,                                  -- which records earned it
    PRIMARY KEY (user_id, badge_id)                     -- awarding twice is a no-op
);

-- ---------------------------------------------------------------------------
-- Notifications
-- ---------------------------------------------------------------------------
CREATE TABLE notifications (
    id          bigserial PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id),
    kind        text NOT NULL,                          -- application_stage_changed, event_update, ...
    payload     jsonb NOT NULL,
    read_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_notifications_unread ON notifications (user_id, created_at DESC) WHERE read_at IS NULL;

CREATE TABLE push_subscriptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint    text NOT NULL UNIQUE,
    p256dh      text NOT NULL,
    auth        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Audit log: every admin / core / owner action
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id           bigserial PRIMARY KEY,
    actor_id     uuid REFERENCES users(id),
    action       text NOT NULL,                         -- e.g. 'club.approve', 'application.move'
    entity_type  text NOT NULL,
    entity_id    text NOT NULL,
    club_id      uuid REFERENCES clubs(id),
    before       jsonb,
    after        jsonb,
    ip           inet,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_club  ON audit_log (club_id, created_at DESC);
CREATE INDEX ix_audit_actor ON audit_log (actor_id, created_at DESC);
