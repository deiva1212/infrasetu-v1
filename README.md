# Infrasetu — Heavy Vehicle & Equipment Marketplace

Web application to **buy, sell and rent** heavy commercial vehicles (trucks, tippers, trailers, buses, transit mixers) and heavy equipment (excavators, backhoe loaders, cranes, graders, rollers, dozers, forklifts), with a full **admin back office** for category, catalogue and product management.

**Stack:** Python 3.10+ · Flask · SQLAlchemy · any SQL database (SQLite by default, MySQL / PostgreSQL via one env variable) · server-rendered Jinja templates · vanilla JS (no build step).

---

## Quick start

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed        # creates tables + sample data (drops existing data!)
flask --app app run         # http://127.0.0.1:5000
```

Sample accounts (after `seed`). Everyone signs in at `/login` with **email or mobile number**.

| Account | Email | Password | Can do |
|---|---|---|---|
| Super Admin | admin@infrasetu.in | Admin@123 | Everything, including roles |
| Listing Moderator | moderator@infrasetu.in | Staff@123 | Review and edit listings |
| Catalogue Manager | catalogue@infrasetu.in | Staff@123 | Categories, fields, make/model catalogue |
| Support & Leads | support@infrasetu.in | Staff@123 | Enquiries, requirements, users, KYC |
| Seller | ravi@example.com (also priya@, arjun@, fatima@) | Seller@123 | Post listings, receive enquiries |
| Buyer | buyer@example.com, meena@example.com | Buyer@123 | Search, contact sellers |
| Partner (verified) | finance@example.com, haulage@example.com | Partner@123 | Partner directory, listings |
| Partner (pending / rejected KYC) | inspect@example.com / spares@example.com | Partner@123 | Waiting for verification |

A Super Admin is created automatically on first start, even if you skip `seed` (set `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars to choose different credentials).

**Can't log in as admin?** Run `flask --app app reset-admin`. It restores and unlocks `admin@infrasetu.in` / `Admin@123`. To create more Super Admins use `flask --app app create-admin`.

**Upgrading from an earlier version?** Just start the app. It adds the new columns and tables to your existing database, creates the built-in roles, and gives existing users roles: the old admin becomes Super Admin, anyone with listings becomes a Seller, everyone else a Buyer.

### Using MySQL or PostgreSQL

```bash
pip install PyMySQL                      # or psycopg2-binary
export DATABASE_URL="mysql+pymysql://user:pass@localhost:3306/infrasetu"
# export DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/infrasetu"
export SECRET_KEY="a-long-random-string"
flask --app app init-db
```

`schema_mysql.sql` and `schema_postgresql.sql` contain the equivalent DDL if your DBA prefers to create tables manually.

Other settings (env vars): `AUTO_APPROVE_LISTINGS=1` skips moderation; `REQUIRE_LOGIN_TO_ENQUIRE=0` lets visitors contact sellers without an account; `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` send password-reset emails; `SESSION_COOKIE_SECURE=1` in production. Upload folder, size limits and page sizes are in `config.py`.

---

## Features

### Public marketplace
- **Search to Buy or Rent** — required: *Buy/Rent*, *Category*, *State* (or explicitly "All India"). Server and client validation; missing fields are highlighted.
  Optional refinements: city, make, model (from catalogue), year range, budget range, max km/hours, condition, fuel, keyword, rental period, "with operator", plus **category-specific filters** (e.g. axle configuration, payload, bucket capacity) that admins mark as searchable. Sorting and pagination. Parent category searches include sub-categories.
- **Post a listing to Sell or Rent out** — 7-section form with all relevant required fields:
  - listing type, leaf category, make/model picked from the admin catalogue, title
  - year, condition, km or engine-hours (depends on category), fuel, registration no. (required for *used* commercial vehicles), ownership (required if used), insurance
  - **category-specific fields** defined by admin (required/optional, number / dropdown / yes-no / text)
  - Sell → expected price, negotiable · Rent → rate, period (hour/day/week/month), minimum duration, available-from, operator/fuel included
  - location (state, city, 6-digit pincode), description (min 30 chars), 1–8 photos, contact
- **Listing detail** — gallery, key facts, full specs (catalogue specs + category fields), and a structured **enquiry** form: offer price for buyers; dates + work site for renters.
- **Post a requirement** — when search finds nothing, buyers/renters post a "wanted" request (pre-filled from their search).
- **My listings** — edit, mark sold/rented, pause, relist, delete (edits go back to moderation); *Enquiries* received & sent.

### Accounts, sign-in and access control
- **Three ways to register** (`/register`): **Buyer** (individual, contractor, company, government), **Seller** (individual owner, fleet owner, dealer, rental company) and **Partner** (dealer/OEM, financier/NBFC, insurance, inspection & valuation, logistics, service & spares, operator/manpower). Each type asks for its own required fields; dealers, rental companies and partners must give a valid **GSTIN** (PAN is checked against it).
- **Login** with email or mobile; "keep me signed in" (30 days); **lockout** for 15 minutes after 5 failed attempts; **forgot / reset password** with a signed, single-use, 1-hour link (sent by SMTP if `MAIL_SERVER` is set); change password; profile edit.
- **Account area** (`/account`): overview by account type, my listings, enquiries received and sent, profile & KYC. Buyers can **become a seller** in one click.
- **KYC verification**: partners must be verified before they can post listings or appear in the **partner directory** (`/partners`); sellers can optionally get a verified badge shown on their listings. Changing GSTIN/PAN sends an account back for review.
- Buyers must be logged in to **contact sellers** (switch off with `REQUIRE_LOGIN_TO_ENQUIRE=0`).

### Roles and permissions (RBAC)
Access is decided by **roles**, each a set of **permissions**; a user can hold several roles.

| Built-in role | Type | Permissions |
|---|---|---|
| Super Admin | Staff | All (fixed) |
| Listing Moderator | Staff | admin panel, dashboard, view/moderate/edit listings, view users |
| Catalogue Manager | Staff | admin panel, dashboard, catalogue, view listings |
| Support & Leads | Staff | admin panel, dashboard, leads, view listings, view/manage users, verify KYC |
| Buyer | Marketplace | contact sellers |
| Seller | Marketplace | contact sellers, post listings |
| Partner | Marketplace | contact sellers, post listings (once verified), partner directory |

Admins with **Manage roles** can edit these or create new roles from 14 permissions; the admin menu and buttons show only what each person may use, and every admin route checks its permission on the server. Safeguards: only staff-role managers can grant staff roles, only a Super Admin can grant Super Admin, nobody can change their own roles or suspend themselves, and the last active Super Admin can't be removed.

### Admin: user management (`/admin/users`)
Filter by account type, role, status (active, suspended, locked) and KYC; KYC review queue; create users (staff or marketplace) with a generated temporary password; edit profile and account type; assign roles; verify or reject KYC with a note the user sees; suspend / re-activate, unlock, issue a temporary password; delete accounts with no activity; see each user's listings and history.

### Audit log (`/admin/audit`)
Records registrations, staff logins, lockouts, password resets, user and role changes, KYC decisions and listing moderation, with who, when, what and IP.

### Admin back office (`/admin`)
- **Dashboard** — approval queue with one-click approve/reject (with reason), stats, status and category breakdowns, latest enquiries.
- **Category management** — two-level tree (e.g. *Trucks › Tipper*), group (Commercial Vehicle / Heavy Equipment), usage unit (km / hours), allow sell/rent, active, ordering. **Per-category listing fields** (label, type, dropdown options, unit, required, searchable) — inherited by sub-categories. Deletion is blocked when products/models exist.
- **Catalogue management** — master list of manufacturer / model / variant per category with power, GVW / operating weight and standard specs (shown on every listing of that model). Filter, search, activate/deactivate, duplicate protection, **CSV export and bulk import/update**.
- **Product management** — tabs by status (pending, approved, rejected, sold, rented, inactive), search & filters, bulk actions (approve, reject, deactivate, feature, delete), full edit of any listing including photos and moderation fields, create listings on behalf of a user, see enquiries per listing.
- **Leads** — enquiries and requirements with status tracking (new → contacted → closed).

### Security
Password hashing (Werkzeug), CSRF token on every POST, permission checks on every admin route, login lockout, single-use reset tokens, HttpOnly/SameSite session cookies (set `SESSION_COOKIE_SECURE=1` behind HTTPS), audit log, owner checks on listing edits, upload type/count/size limits, server-side validation of every field (client validation is only a convenience).

---

## Data model

```
roles ──< role_permissions          users >──< roles  (user_roles)
users ──  partner_profiles (1:1)    audit_logs >── users (actor)
users ─┬─< products >── categories (self-ref parent_id) ──< category_attributes
       │       │  └──> catalogue (make/model) >── categories
       │       ├──< product_images
       │       ├──< product_attribute_values >── category_attributes
       │       └──< enquiries
       └──< requirements >── categories
```

## Project layout

```
app.py        app factory, CLI commands (init-db, seed, reset-admin, create-admin)
accounts.py   registration, login, lockout, password reset, account area
admin_users.py admin users, roles & permissions, audit log
db_setup.py   start-up: create/upgrade tables, built-in roles, role back-fill, default Super Admin
config.py     settings (DATABASE_URL, uploads, paging)
models.py     SQLAlchemy models, permission catalogue, built-in roles, reference lists
public.py     marketplace routes + JSON API /api/categories/<id>/meta
admin.py      admin routes
utils.py      auth, CSRF, validation, uploads, listing form processing
seed.py       sample data (25 categories, 49 models, 54 listings, 14 users across all roles)
templates/    Jinja templates (admin/ for back office)
static/       css/style.css, js/app.js, uploads/
tests/        pytest end-to-end tests  →  pip install pytest && pytest -q
```

## Production notes
Run behind a WSGI server, e.g. `pip install gunicorn && gunicorn -w 4 "app:create_app()"`, set a strong `SECRET_KEY`, use MySQL/PostgreSQL, and serve `static/uploads` from persistent storage (or swap `save_image` in `utils.py` for S3). For schema changes over time, add Flask-Migrate (Alembic).
