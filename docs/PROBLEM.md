# Problem Statement

## The idea

One platform where SRM clubs recruit members, run events, take attendance, publish
results and issue certificates and badges. It replaces Google Forms and WhatsApp
groups.

College domain: **`@srmist.edu.in`**. Everyone signs in with a 6-digit code sent to their email. A code that reaches an `@srmist.edu.in` inbox proves the person is at SRM.
(Google sign-in was tried first, but SRM's Google Workspace blocks outside apps for student accounts.)
Covers **all SRM campuses** (KTR, Ramapuram, Vadapalani, NCR, Trichy, ...), which share that domain.
It is a **web app**: it runs in any browser on laptop or phone. Nothing to install.

## The problem

How clubs run today:

| Step | Tool used now | What goes wrong |
|---|---|---|
| Hiring club members | Google Form | Every club has its own form and rules. Answers sit in a sheet only the leader sees. Applicants never hear back. |
| Telling people about an event | WhatsApp group | Messages get buried. People outside the group never know. Venue or time changes are missed. |
| Event registration | Another Google Form | No seat limit, duplicate entries, no way to check outside students. |
| Attendance | Paper or a sheet | Slow, easy to fake, often never saved. |
| Results | Nowhere | Winners are announced on stage and then forgotten. |
| Proof of taking part | Hand-made certificates, if any | Easy to fake, impossible to verify, nothing to show recruiters. |

**Root cause:** each club keeps its data in a different tool, and no tool talks to the
next one. Nothing flows from **join → register → attend → result → proof**.

## Who uses it

| Role | Who | What they do |
|---|---|---|
| **Platform Owner** | The developer (a student who knows the clubs) | Approves or rejects new clubs. Can suspend a club or hand a club to a new admin. Sets the few platform-wide rules. |
| **Club Admin** | Club president / head | Runs everything for their own club: recruitment rules and drives, approving applicants, events, approving outside participants, attendance, results, certificates, announcements. Can make other members Core or Admin. |
| **Core Member** | Club core team | Helps run events: creates and edits events, scans check-ins, posts event updates. Cannot change club rules or roles. |
| **Member** | Selected club member | Sees member-only events and announcements. |
| **SRM Student** | Anyone signed in with `@srmist.edu.in` | Trusted automatically. Applies to clubs, registers for events (confirmed instantly), earns certificates and badges. |
| **Outside Participant** | Student from another college, personal email | Proves their email with a one-time code. Every event registration waits for approval from that event's organizers. |

There is no separate "campus admin". Each club runs itself; the Platform Owner only
decides which clubs exist.

## What it must do (v1)

### 1. Recruitment: one approval queue, rules in one place

- The Club Admin sets the club's recruitment rules once. These include the window dates,
  who can apply (year, department), how many seats, and the form questions. This
  replaces the Google Form.
- Applicants move through stages: **Applied → Shortlisted → Interview → Selected / Rejected**.
- All applications for the club land in **one queue** for the club's admins.
- Applicants see their status live and get notified on every change.
- **Selected** makes them a Member automatically.
- Platform-wide rule set by the Platform Owner: the most clubs one student can join.

### 2. Events without WhatsApp guessing

- Each event page shows the venue, time, map link, seats left and live status.
- Updates like "venue moved to Hall B" or "starting now" are pushed to every registered
  person by email and web push.
- SRM students are confirmed instantly. Outside participants go to the organizers'
  approval queue.

### 3. One flow: register → check in → result → certificate → badge

- Check-in is a QR scan at the door. The code rotates so screenshots can't be shared.
- Results are published on the event page and stay there for good.
- Certificates are generated automatically, with a QR code anyone can scan to verify.

### 4. One directory, one profile, real proof

- A directory of every club, filtered by campus, department and category. Students see their own campus first.
- A public profile at `/u/<handle>` with clubs, events, results, certificates and badges.

### 5. Badges, like GitHub achievements

- Badges are awarded automatically from real data. Examples: *First Event*,
  *Hackathon x3*, *Winner*, *Core Member*, *Recruiter*.
- They have tiers like GitHub's: x2, x3, x4.
- Every badge has a public verify link.
- There is an embeddable SVG profile card for GitHub READMEs and LinkedIn.

## Not in v1

Payments or paid events, chat, a mobile app (it's a web app that works in the phone browser),
AI features (they come after the core flow works).

## How we know it works

- A club runs a full recruitment drive with **no Google Form**.
- A club goes from "event ended" to "certificates sent" in **under 10 minutes**.
- **Every** event has public results.
- Students share their profile link or badge card.
