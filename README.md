# AI-Powered E-Complaint Analysis System

Django 5.2 (LTS) web app. Implements, from the SRS in `../reference`: authentication and
account creation for three actors (Citizen, Officer, System Administrator), citizen complaint
submission and tracking, and officer status updates. The AI categorization step is intentionally
not built yet: new complaints are routed to the least-loaded **active** officer instead.

## Run

```powershell
cd work
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_defaults      # dev accounts, see below
.\.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/. Run the tests with `.\.venv\Scripts\python manage.py test`.
(New machine: `python -m venv .venv`, then `.\.venv\Scripts\pip install -r requirements.txt`.)

## Default development accounts (`seed_defaults`, refuses to run with DEBUG off)

| Role                 | Username   | Password       |
|----------------------|------------|----------------|
| Citizen              | `citizen1` | `Citizen@2026` |
| Officer              | `officer1` | `Officer@2026` |
| System Administrator | `sysadmin` | `SysAdmin@2026`|

`sysadmin` can also use the Django admin at `/django-admin/`. Delete or change these before any real deployment.

## Self-registration

`/accounts/register/` has a form per role. Officer and System Administrator sign-ups also need a
registration code (env vars `OFFICER_REGISTRATION_CODE`, `ADMIN_REGISTRATION_CODE`; dev defaults
`OFFICER-DEV-2026` and `SYSADMIN-DEV-2026`).

## Layout

- `config/` settings and root URLs (+ `/api/health/`)
- `accounts/` custom `User` (role), `OfficerProfile`, `LoginAudit`, login/logout/register, lockout
- `complaints/` `Complaint`, `Attachment`, `StatusHistory`, `Category`; `services.py` holds the workflow
- `frontend/templates`, `frontend/static` HTML, CSS, JS

## Complaint workflow

Submitted → Assigned (automatic) → Acknowledged → In Progress → Resolved → (Closed: administrator, not built yet).
Only the assigned officer can move a complaint, one step at a time; resolving needs remarks of at least 10 characters.

## Not built yet

AI categorization/priority, administrator assignment/reassignment/closing, analytics, reports,
password reset, profile editing, notification log and retries.
