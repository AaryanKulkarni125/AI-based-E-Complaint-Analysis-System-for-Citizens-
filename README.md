# AI-Powered Citizen E-Complaint Analysis System

An end-to-end civic grievance redressal and AI analysis platform built with **Python 3.13**, **Django 5.2 (LTS)**, **scikit-learn**, **ReportLab**, and **Leaflet.js**. The application empowers citizens to lodge geo-tagged complaints with photographic evidence, utilizes machine learning (TF-IDF + Multinomial Naive Bayes) to categorize and prioritize grievances automatically, routes tickets to active department officers based on queue workload, provides officers with a resolution workflow requiring remarks and evidence, and gives administrators deep oversight including manual assignment overrides, AI audit logs, formal closure, live GIS mapping, SLA tracking, and CSV/PDF export capabilities.

---

## Architecture & Technology Stack

While the initial SRS referenced a MERN-oriented architecture, this codebase implements and completes a robust, unified **Python/Django 5.2 LTS** stack. This architecture delivers server-side role enforcement, atomic transactions, CSRF/XSS protection, and integrated REST APIs without the overhead of dual frontend/backend microservices:

- **Backend**: Python 3.13, Django 5.2 LTS
- **Database**: SQLite (Development) / PostgreSQL-ready (Production via `DATABASE_URL`)
- **Machine Learning**: `scikit-learn` (TF-IDF Vectorizer + Multinomial Naive Bayes with synthetic civic dataset and urgency heuristics)
- **Reporting**: `ReportLab` (PDF generation) and standard CSV streaming
- **GIS Mapping**: Leaflet.js with OpenStreetMap integration
- **Frontend**: Responsive HTML5, Vanilla CSS3 (modern glassmorphism design system), Vanilla JavaScript (`ApiClient` with CSRF handling), bilingual EN/HI switcher, and WCAG-aligned persistent help modal.

---

## Core System Workflows & Roles

### 1. Citizen Portal
- **Authentication**: Email/password registration and login, plus phone-based **OTP authentication** (`/accounts/otp-login/`).
- **Profile & Security**: User profile updates, secure password change, password reset requests with audit logging.
- **Lodge Grievance**: Ward selection, location input with HTML5 one-click GPS coordinate auto-detection (`latitude`, `longitude`), issue description (minimum 20 characters), and up to 3 attachments (JPEG, PNG, PDF up to 5MB).
- **Duplicate Detection**: Flags potential duplicate complaints submitted in the same ward and category within 48 hours.
- **Unique Tracking ID**: Generates structured reference IDs (`CMP-000001`).
- **Citizen Dashboard & History**: Real-time grievance tracking with status badges, SLA countdowns, and attachment inspection.
- **Resolution Feedback & Reopening**: 1–5 star rating with comments upon resolution, or reopen within 7 days if the grievance recurs.

### 2. Officer Operations Console
- **Assigned Worklist**: Filterable by status (`Assigned`, `Acknowledged`, `In Progress`, `Resolved`) and sortable by priority or date.
- **SLA Breach Monitoring**: Real-time SLA hours remaining and overdue breach banners.
- **Status Progression**: Enforces strict state transitions (`Assigned` → `Acknowledged` → `In Progress` → `Resolved`).
- **Resolution Proof**: Marking as "Resolved" requires at least 10 characters of remarks and optional proof-of-resolution attachments.

### 3. Administrator & Civic Governance Console
- **Global Grievance Registry**: Search and filter by status, priority, category, ward, and keyword.
- **Interactive GIS Map**: Live Leaflet map displaying geo-located grievances with clickable pins.
- **Manual Assignment & AI Override**: Reassign complaints to active officers with mandatory reason logging (`AssignmentLog`); override AI category and priority with audit logging (`AIOverrideLog`).
- **Formal Case Closure**: Close resolved complaints with administrative sign-off remarks.
- **Officer Roster Management**: Toggle officer availability (`active` / `inactive`).
- **Notification Audit & Retries**: Inspect delivery logs (`NotificationLog`) for emails and execute automated retries for transient delivery failures.
- **Analytics & Reporting**: Summary KPI metrics, grievance distribution charts, and one-click **CSV** and **PDF** report downloads.

---

## Local Setup & Quickstart

### Prerequisites
- Python 3.11+ or 3.13 installed
- Git
- PowerShell (Windows) or Bash (macOS/Linux)

### 1. Clone & Set Up Virtual Environment

```powershell
# Clone the repository
git clone https://github.com/AaryanKulkarni125/AI-based-E-Complaint-Analysis-System-for-Citizens-.git
cd AI-based-E-Complaint-Analysis-System-for-Citizens-

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy the example environment file:

```powershell
cp .env.example .env
```

Review `.env` settings:
- `DEBUG=True` (Keep True for local development)
- `SECRET_KEY` (Auto-generated or custom secret)
- `OFFICER_REGISTRATION_CODE=OFFICER-DEV-2026`
- `ADMIN_REGISTRATION_CODE=SYSADMIN-DEV-2026`

### 3. Database Migrations & Seed Defaults

```powershell
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py seed_defaults
```

The `seed_defaults` command populates default municipal categories (Roads & Infrastructure, Sanitation & Waste Management, Water Supply, Drainage & Sewerage, Electricity & Street Lighting, Public Health, General Administration) and initializes default test accounts.

### 4. Run the Development Server

```powershell
.\.venv\Scripts\python manage.py runserver
```

Open your browser at **http://127.0.0.1:8000/**.

---

## Default Development Accounts

| Role | Username | Password | Notes |
| :--- | :--- | :--- | :--- |
| **Citizen** | `citizen1` | `Citizen@2026` | Citizen dashboard & complaint lodging |
| **Officer** | `officer1` | `Officer@2026` | Assigned grievance resolution queue |
| **System Administrator** | `sysadmin` | `SysAdmin@2026` | Full oversight, mapping, reports, Django admin |

*Django Admin Console is accessible at `/django-admin/` using the `sysadmin` credentials.*

---

## Automated Test Suite

Run the full automated test suite covering authentication, role boundaries, complaint creation, AI analysis, SLA tracking, notification logging, and admin operations:

```powershell
.\.venv\Scripts\python manage.py test
```

To run individual test modules:
```powershell
.\.venv\Scripts\python manage.py test accounts.tests
.\.venv\Scripts\python manage.py test complaints.tests
```

---

## Centralized REST API Documentation

All API endpoints return JSON and require standard session authentication and CSRF protection (`X-CSRFToken` header).

| Endpoint | Method | Role | Description |
| :--- | :--- | :--- | :--- |
| `/api/health/` | `GET` | Public | System health check (`status`, `timestamp`) |
| `/api/categories/` | `GET` | Public | List categories with SLA hours and departments |
| `/api/complaints/` | `GET` | Authenticated | List complaints scoped to user role |
| `/api/complaints/` | `POST` | Citizen | Submit a new complaint with geo coordinates |
| `/api/complaints/<pk>/` | `GET` | Scoped | Retrieve full complaint details and history |
| `/api/complaints/<pk>/status/` | `POST` | Officer | Update complaint status (with remarks & evidence) |
| `/api/complaints/<pk>/reassign/` | `POST` | Admin | Manually reassign complaint to officer |
| `/api/complaints/<pk>/override-ai/` | `POST` | Admin | Override category and priority with audit log |
| `/api/complaints/<pk>/close/` | `POST` | Admin | Formally close a resolved complaint |
| `/api/complaints/<pk>/feedback/` | `POST` | Citizen | Submit 1–5 star rating and feedback remarks |
| `/api/complaints/<pk>/reopen/` | `POST` | Citizen / Admin | Reopen a resolved complaint within 7 days |
| `/api/complaints/map/` | `GET` | Admin / Officer | GeoJSON coordinate list for GIS mapping |
| `/api/analytics/` | `GET` | Admin | KPI metrics, counts, and category distribution |

---

## Production Security & Deployment Notes

- **Transport Security**: Deploy behind a TLS 1.3 reverse proxy (Nginx / Caddy / Cloudflare). In `.env`, set `SECURE_SSL_REDIRECT=True` and configure `CSRF_COOKIE_SECURE=True` / `SESSION_COOKIE_SECURE=True`.
- **Database**: Configure PostgreSQL via `DATABASE_URL` for multi-worker concurrency.
- **Account Lockout**: 5 consecutive failed login attempts automatically trigger a 15-minute account lock.
- **File Uploads**: Restrict uploads to valid MIME types (JPEG, PNG, PDF) with magic-byte header validation.
- **Notification Services**: SMTP email backend logs outbound messages to `NotificationLog`. In production without live Twilio/AWS SNS credentials, the OTP module safely outputs verification codes to development logs.
