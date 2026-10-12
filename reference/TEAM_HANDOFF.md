# Team Handoff: AI-Powered E-Complaint Analysis System

Written for the teammate picking up the next part of the project. This file lives **outside** the
git repo (in `Implementation/`, while the repo root is `Implementation/work/`), so it is not on GitHub.
Share it and the `reference/` folder with them directly, because neither is in the repository.

- Repo: https://github.com/AaryanKulkarni125/AI-based-E-Complaint-Analysis-System-for-Citizens-.git (branch `main`)
- Authors: Aabhash Khemka (2024300115), Aaryan Kulkarni (2024300121)
- State as of this handoff: **52 automated tests pass**; the three flows below were also exercised by hand in a browser.

---

## 1. Documents the work is based on

All in `Implementation/reference/` (not in the repo). The SRS is the authority; where the experiment
diagrams disagree with it, see section 8.

| File | What it is | How it was used |
|---|---|---|
| `SRS_E-Complaint_System-1.pdf` | Software Requirements Specification v1.0 (requirement IDs like `REQ-AUTH-006`) | Main source: stack, roles, rules, validations, workflow, non-functional targets |
| `SE_EXP2.pdf` | Use case diagram + tables (UC-1 Login, UC-2 Submit, UC-3 Track, UC-4 Resolve, UC-5 Assign) | Flows and alternate flows (AI failure, incomplete remarks, invalid tracking ID) |
| `SE_EXP3_115_121.pdf` + `ClassDiagram1.png` | UML class diagram | User/Citizen/Officer/Administrator/SystemAdministrator, Complaint, Category, Attachment; field names |
| `SE_EXP4_115_121.pdf` | Sequence diagrams for UC-2, UC-3, UC-4 | UI → Controller → AI service → Repository → Notification layering; "Uncategorized" fallback |
| `SE_EXP5_115_121.pdf` | Activity diagram | Overall login → four parallel flows |
| `SE_EXP6_115_121.pdf` | DFD level 0, 1, 2 | Read for context only; it describes a bigger "municipal grievance" product than the SRS (section 8) |

---

## 2. What is implemented

Stack: Python 3.13, **Django 5.2 LTS**, SQLite for development, plain HTML/CSS/JS (no JS framework),
templates and static files in `frontend/`. The SRS asks for PostgreSQL/MySQL in production. Nothing in the
code is SQLite-specific, so switching is a settings change.

### Stage 1: frontend and backend wiring
- Django project `config/`, apps `accounts` and `complaints`, shared base template, responsive CSS with dark mode.
- `/api/health/` returns JSON, and the landing page's JS calls it to show "System online".

### Stage 2: login and logout, three actors
- Roles: `citizen`, `officer`, `admin` (shown as "System Administrator"), stored in `User.role`.
- Each role gets its own dashboard at `/accounts/dashboard/`.
- Logout is POST-only. Sessions expire after **30 minutes of inactivity** (REQ-AUTH-008).
- **Lockout** (REQ-AUTH-006): 5 failed logins inside 10 minutes locks the account for 15 minutes. Attempts made
  while locked are logged as `locked` and do not extend the lock. See `accounts/security.py`.
- Every attempt is stored in `LoginAudit` (REQ-AUTH-009). The sysadmin dashboard shows the last 10.
- Generic "Incorrect username or password." for unknown user, wrong password and deactivated account.
- `?next=` redirects are checked against the host (no open redirect).

### Stage 3: create account, all three actors
- `/accounts/register/` (chooser), then `/accounts/register/<citizen|officer|admin>/`.
- Rules: unique username and e-mail (case-insensitive), password policy from the SRS (8+ chars, letters and digits,
  not all numeric, not common, not similar to personal info), passwords hashed (PBKDF2).
- Officers also give a department and get an `OfficerProfile` (availability defaults to `active`).
- **Officer and admin sign-up require a registration code** (see decision D1).

### Stage 4: citizens submit complaints
- `/complaints/submit/`: location, description (min 20 chars), up to 3 attachments (JPEG/PNG/PDF, max 5 MB each).
- Uploads are checked for extension **and** magic bytes, and they must agree (`complaints/validators.py`).
  Files are stored under random names, and downloaded only via an access-checked view (`/complaints/attachments/<id>/`).
  There is deliberately **no public `/media/` route**.
- Tracking ID `CMP-000001` is derived from the primary key (unique, never reused).
- **AI step is skipped**: `services.pick_officer()` routes each new complaint to the active officer with the fewest
  open complaints (placeholder). If nobody is active, the complaint stays `Submitted` and is routed automatically
  when an officer registers or becomes active (`complaints/signals.py`).
- Citizen pages: `/complaints/mine/` (status filter and search by tracking ID), `/complaints/<id>/` (details, attachments,
  status timeline). Citizens only ever see their own complaints (404 otherwise, not 403).
- E-mails (console backend in dev): acknowledgment to the citizen, "assigned" to the officer.

### Stage 5: officers update complaints
- `/complaints/assigned/`: only that officer's complaints, filter by status, sort by priority or date, pending/resolved counts.
- On the detail page the officer sees a form offering **only the next legal status**.
  Workflow: `Assigned → Acknowledged → In Progress → Resolved`. No skipping, only the assigned officer can act.
- Resolving needs remarks of 10+ characters and may carry up to 3 evidence files. It records who resolved it,
  when, and the resolution time (REQ-RES-003/005).
- Every change is appended to `StatusHistory`, and the citizen is e-mailed on each change.
- `Closed` exists as a status but **nothing can set it yet** (admin task, see section 6).

### Default development accounts (`python manage.py seed_defaults`)

| Role | Username | Password |
|---|---|---|
| Citizen | `citizen1` | `Citizen@2026` |
| Officer | `officer1` | `Officer@2026` |
| System Administrator | `sysadmin` | `SysAdmin@2026` |

`seed_defaults` refuses to run with `DEBUG` off. `sysadmin` is also a Django superuser (`/django-admin/`).
Registration codes (dev defaults): officer `OFFICER-DEV-2026`, admin `SYSADMIN-DEV-2026`.

---

## 3. Project layout

```
work/                          <- git root
  manage.py  requirements.txt  README.md
  config/                      settings.py, urls.py, views.py (home + /api/health/)
  accounts/
    models.py                  User (role), OfficerProfile, LoginAudit
    forms.py                   LoginForm, Citizen/Officer/Admin registration forms
    views.py                   login, logout, dashboard (per role), register
    security.py                lockout + audit helpers
    decorators.py              @role_required(...)
    validators.py              letters-and-digits password rule
    management/commands/seed_defaults.py
    tests.py                   19 tests
  complaints/
    models.py                  Category, Complaint, Attachment, StatusHistory
    services.py                *** workflow logic: create_complaint, route_complaint, pick_officer,
                               assign_queued_complaints, change_status, record_history ***
    forms.py                   ComplaintForm, OfficerUpdateForm, MultipleFileField
    validators.py              upload validation
    notifications.py           e-mail helpers (errors swallowed and logged)
    signals.py                 route queued complaints when an officer becomes active
    views.py                   submit, my_list, officer_list, detail (+officer update), download_attachment
    admin.py                   Django admin (complaint delete disabled, REQ-WFL-006)
    tests.py                   33 tests
  frontend/
    templates/                 base.html, home.html, accounts/*, complaints/*
    static/                    css/app.css, js/app.js
```

Design rule used throughout: **views stay thin, business rules live in `complaints/services.py`**
so the AI and admin modules can call the same functions.

---

## 4. Data model (current)

- `User` (extends `AbstractUser`): `role`, unique `email`. `is_active` is the account status.
- `OfficerProfile`: `user` (1:1), `department` (free-text **CharField for now**), `availability_status` (`active`/`inactive`),
  `workload` (computed property: open assigned complaints).
- `LoginAudit`: `username`, `user`, `outcome` (`success`/`failed`/`locked`), `ip_address`, `timestamp`.
- `Category`: `name`, `description`. **Exists but unused and empty** (no seed data yet).
- `Complaint`: `citizen`, `description`, `location`, `status`, `category` (nullable FK), `priority` (default `medium`),
  `confidence_score` (nullable), `assigned_officer`, `submitted_at`, `updated_at`, `resolution_remarks`, `resolved_by`,
  `resolved_at`, `resolution_time`.
- `Attachment`: `complaint`, `file`, `original_name`, `content_type`, `size`, `is_resolution_evidence`.
- `StatusHistory`: `complaint`, `from_status`, `to_status`, `changed_by`, `note`, `timestamp`.

Statuses: `submitted, assigned, acknowledged, in_progress, resolved, closed`.
The officer transition table is `Complaint.OFFICER_TRANSITIONS`. Extend it there when adding admin actions.

---

## 5. Run it

```powershell
git clone https://github.com/AaryanKulkarni125/AI-based-E-Complaint-Analysis-System-for-Citizens-.git
cd AI-based-E-Complaint-Analysis-System-for-Citizens-
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_defaults
.\.venv\Scripts\python manage.py runserver        # http://127.0.0.1:8000/
.\.venv\Scripts\python manage.py test             # ~1 minute (password hashing is slow)
```

Gotchas:
- `db.sqlite3` and `media/` are **git-ignored**, so each of you has your own local database and uploads.
  Don't commit them. The data in Aaryan's dev DB is test data only.
- **Migrations are committed.** If you change a model, run `makemigrations` and commit the new file. Two people adding migrations
  to the same app at once will conflict, so tell each other before touching `accounts/models.py` or `complaints/models.py`.
- E-mails are printed to the runserver console (`EmailBackend` = console). Look there for the acknowledgment and status mails.
- Tests run with `DEBUG=False`, which is why `seed_defaults` is called with `force=True` in them.
- On SQLite `select_for_update()` is a no-op. The row lock in `change_status` only takes effect on PostgreSQL/MySQL.

---

## 6. What we are going to do next

Suggested order (follows the SRS priorities). Pick up whatever you and Aaryan agree on; the AI step is the next planned
piece, since the pipeline already has a hook for it.

### A. AI categorization and priority (SRS 4.3: REQ-AI-001..006). The planned next step
- Train/serve a TF-IDF + Naive Bayes (scikit-learn) classifier for **category** and a **priority** (High/Medium/Low) rule or model.
  Add `scikit-learn` to `requirements.txt`.
- **Hook point:** in `services.create_complaint()`, call the classifier **before** `route_complaint()`. Store `category`,
  `priority`, `confidence_score` (REQ-AI-001..003). Must finish in < 10 s.
- **Failure path (UC-2 alternate flow / sequence diagram):** if the classifier errors or is unavailable, save the complaint as
  "Uncategorized" and flag it for manual categorization. The citizen still gets a tracking ID. Don't let an AI failure block submission.
- Low confidence (below a configurable threshold) must flag the complaint for admin review (REQ-AI-006). That needs a new
  field such as `needs_review`.
- Admin override of category/priority needs an **override log model** (original value, corrected value, who, when), which
  doubles as retraining data (REQ-AI-004/005).
- **Training data:** the SRS (TBD-2, TBD-3) leaves the department list and accuracy target open, and no dataset exists. We must
  agree a category list, seed `Category`, and produce or find labeled complaint text.
- Update `pick_officer()` to prefer officers whose department matches the category (REQ-WFL-002). This needs
  `OfficerProfile.department` to become a FK to `Category` (or a mapping). Right now it is free text.

### B. Administrator role and dashboard (SRS 4.5, 4.7, 4.8: REQ-ADM, REQ-WFL-004, REQ-RES-004)
- View all complaints; filter, search, sort (category, priority, status, date, ID, citizen name, keyword).
- Manual assign and **reassign with a recorded reason**, with an assignment/audit record.
- **Close** a resolved complaint, or **reopen and reassign** it. Add `closed` to the allowed transitions for the admin only.
- Confirmation prompt before irreversible actions (REQ-SAFE-003).
- See decision D2 below: first decide which role this belongs to.

### C. Notification log and retries (REQ-NOT-004/005)
- Retry failed mails up to 3 times, store a notification log with delivery status, and show it to admins.
  `complaints/notifications.py` currently sends once and just logs failures.

### D. Account features still missing (SRS 4.1, 4.12)
- Password reset by e-mailed single-use link (REQ-AUTH-007). Profile view/edit and change password (REQ-PRF-001..004).
- Admin-only creation and deactivation of officer accounts (business rule; see D1).

### E. Analytics and reports (SRS 4.10, 4.11)
- Dashboard charts (volume by category, priority breakdown, average resolution time, per-officer metrics), refreshed
  at least every 15 min. Reports exportable as PDF and CSV (10,000 rows in < 30 s).
- `Complaint.resolution_time` is already stored for this.

### F. Hardening and deployment
- PostgreSQL, HTTPS (TLS 1.2+), real SMTP, daily backups, `DJANGO_DEBUG=0`, real `DJANGO_SECRET_KEY`, change/delete the dev
  accounts and registration codes, serve uploads properly, WCAG 2.1 AA review, user guides (SRS 2.6).

---

## 7. Decisions made that you should know about

- **D1: Officer/admin self-registration needs a code.** The SRS business rule says *only an Administrator* may create/modify/deactivate
  officer accounts. We were asked to let all three actors register themselves, so we allowed it but gated officer and
  admin sign-up behind `OFFICER_REGISTRATION_CODE` / `ADMIN_REGISTRATION_CODE` (env vars; wrong-code guessing is throttled to
  10 per IP per 15 min). Revisit when admin-managed officer accounts are built.
- **D2: "Administrator" vs "System Administrator" are one role for now.** The SRS and class diagram have both: *Administrator*
  (assigns complaints, overrides AI, closes, analytics) and *System Administrator* (backups, security, deployment).
  We only built three roles as requested, and `admin` is labelled System Administrator. Decide whether to add a fourth role
  (`administrator`) or give the complaint-management powers to `admin`. A fourth role needs a migration plus `role_required` updates.
- **D3: Added an `Acknowledged` status.** The SRS flow is Submitted → Assigned → In Progress → Resolved → Closed. We were asked for
  "acknowledged, being resolved, resolved", so the officer's accept step is its own status between Assigned and In Progress.
  If the SRS is followed strictly, remove it from `Complaint.Status` and `OFFICER_TRANSITIONS` (needs a migration).
- **D4: Routing is a placeholder.** `pick_officer()` = least-loaded active officer. Meant to be replaced by AI category plus admin assignment.
- **D5: Citizens do not choose a category.** Per the SRS the AI assigns it, so the form has only location and description. UC-2 in the
  experiments shows a category field. We followed the SRS.
- **D6: Location is a required field** (class diagram and UC-2 have it, the SRS doesn't mention it).
- **D7: Complaints are never deleted** (Django admin delete disabled), per REQ-WFL-006.
- **D8: Rate-limit state uses Django's default in-process cache**, so it resets on restart and isn't shared across workers. Fine for dev; use a shared cache in production.

---

## 8. Inconsistencies in the reference documents

- **DFDs (Exp 6) go beyond the SRS:** ImageKit media storage, geocoding/map API, SMS and push notifications, OTP, wards/GPS/SLA,
  citizen feedback and ratings, duplicate-complaint detection, and "Municipal Corporation" framing. None are in the SRS and none are built.
  SRS TBD-3 only asks whether SMS comes later. Treat these as out of scope unless the team decides otherwise.
- The Exp 6 captions are swapped relative to the pictures. The first picture is Level 0, the second is Level 2 (grievance filing),
  and the third is Level 1 (seven processes).
- The class diagram has typos: `accpetComplaint()`, and `trackComplaint()` listed twice on Citizen.
- The SRS lists entities Assignment, Notification and AuditLog in its ERD, but the class diagram has none of them. We will need them
  for reassignment history (B), the notification log (C) and the AI override log (A).

---

## 9. Conventions and tips

- Keep business rules in `services.py` and add tests next to the feature (`accounts/tests.py`, `complaints/tests.py`).
  `ComplaintTestBase` in `complaints/tests.py` provides a citizen, a second citizen and an officer, plus temp `MEDIA_ROOT` handling.
- Use `captureOnCommitCallbacks(execute=True)` in tests that expect e-mails, because notifications are sent in `transaction.on_commit`.
- Use `@role_required(User.Role.X, ...)` from `accounts/decorators.py` on every new view. It returns 403 for the wrong role and redirects
  anonymous users to login.
- When a citizen/officer shouldn't know a record exists, return **404** (see `visible_complaints()`), not 403.
- Don't expose uploaded files by URL. Go through an access-checked view like `download_attachment`.
- Git: work on a branch per feature and open a PR into `main`, and don't force-push `main` (we force-pushed once, early, to fix the
  first commit's author line). Never commit `db.sqlite3`, `media/` or `.env`.
