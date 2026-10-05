# Profit Studio — Tanvi's month-end tracker

An editable **Python / Django** project. Open this folder in VS Code, change ordinary Python, HTML, and CSS files, and run the website locally. There is no dependency on a chat session, proprietary website builder, or JavaScript build service.

**Status: production safeguards added; live deployment still requires the existing SQLite workspace to be transferred and verified.** The free Render Blueprint uses Neon PostgreSQL and preserves the client's existing login and records through a guarded one-time import. Public signup is closed. Password reset is disabled until a mail provider is configured. Follow `DEPLOYMENT.md` for setup. `VERIFICATION.md` records earlier checks.

The client UI uses three monthly totals: **Money received, Expenses, and Profit**. Profit is money received minus expenses, using actual receipt/payment dates. Stock receipts and unit sales are tracked separately from payments. Earlier technical notes describe legacy lot-cost calculations retained for historical records.

## What this version does

- Login-protected workspace; each user's records are isolated from other users in the app.
- A simple month dashboard with money received, expenses, profit, and one searchable entries list.
- Internal navigation and forms update the app content without a full document reload; browser Back/Forward continues to work, and CSV exports remain downloads.
- Monthly reports with money received, expenses, and profit.
- Automatic monthly money-received and expense totals for each payment account, using existing entries without statement-total input.
- Multiple Razorpay, COD, UPI, and cash receipt entries; automatic monthly source totals.
- Expenses with an actual date, amount, category, payment account, optional SKU, payer, reference, and notes.
- Quick repeated entry with **Save & add another**; input can happen next month without changing the transaction month.
- Persistent custom payment accounts and expense categories, managed in Settings.
- Separate transfers/repayments, excluded from income and expenses.
- Products/SKUs with optional photos beside their names. Production photos are stored in PostgreSQL and count toward its storage limit.
- Simple stock receipt and units-sold forms, with date, quantity, and optional batch/notes.
- One stock history table and payment-month expenses on each SKU page; refunds/damage costs are entered as ordinary expenses.
- Negative-stock validation, including backdated movements.
- Edit/Delete actions on money and stock entries, with a retained change history.
- Monthly financial CSV export with spreadsheet-formula escaping.
- An opt-in fictional demo. No bank connection, payment credentials, or real client records are included.
- Database-backed submission receipts prevent the same money/stock form being saved twice; changed retry payloads are rejected.
- Active statement references are unique per account; stale financial edits cannot overwrite a newer change.
- Month review/closing, reasoned reopening, and snapshots; stock backdating cannot alter a later closed month.
- Stock reversals preserve the original record and correct both available stock and sold-unit statistics.
- Email/password login and login throttling. Password recovery is disabled in the free deployment until an email provider is configured.
- PostgreSQL/Gunicorn/WhiteNoise configuration, a Render Free web-service Blueprint for use with separately configured Neon PostgreSQL, a PostgreSQL CI workflow, and an encrypted-backup helper. Cloud saving is not active until those services are provisioned and `DATABASE_URL` is configured.

## 1. Open it in VS Code

1. Install **Python 3.12** and **VS Code** if needed.
2. Extract the ZIP. In VS Code choose **File → Open Folder → `profit_tracker`** — the folder containing `manage.py`.
3. Accept the recommended Python and Python Debugger extensions.
4. Open **Terminal → New Terminal**.

### Windows / PowerShell

Use these commands inside the `profit_tracker` folder. They do not require PowerShell script activation:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --settings=config.test_settings
.\.venv\Scripts\python.exe manage.py runserver
```

`createsuperuser` asks you to choose your own username and password. There is no default login. Password characters are not displayed as you type — that is normal. Supply an email address: it is required for sign-in. The username is an internal/display identifier.

### macOS / Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test --settings=config.test_settings
.venv/bin/python manage.py runserver
```

Open **http://127.0.0.1:8000/** and sign in. The server is on your computer only. Press **Ctrl+C** in the terminal to stop it.

If a verification command fails, stop before using real records. Share the full error so it can be fixed; do not ignore migration errors.

## 2. Choose an empty workspace or a demo

### Empty workspace

Open **Accounts & categories** to see saved accounts/categories and add any additional ones. New empty workspaces can create their accounts and categories there; demo/bootstrap commands seed their defaults during setup.

The default review month is the previous calendar month. Use the month picker to change it.

### Fictional demo

Before adding products or transactions, stop the server and run:

```powershell
# Windows — replace YOUR_USERNAME with the username you created
.\.venv\Scripts\python.exe manage.py seed_demo --username YOUR_USERNAME
.\.venv\Scripts\python.exe manage.py runserver
```

```bash
# macOS / Linux
.venv/bin/python manage.py seed_demo --username YOUR_USERNAME
.venv/bin/python manage.py runserver
```

Then open **http://127.0.0.1:8000/?month=2025-09**. The demo includes an August advance and a September stock delivery. Demo data uses fixed historical dates so the examples are repeatable.

The command refuses a workspace with existing products or transactions. For real records later, create a **new user**, rather than mixing demo and real data. Ordinary app users have separate workspaces; a superuser can inspect all records through admin.

## 3. Debug and make changes

In VS Code press **Ctrl+Shift+P → Python: Select Interpreter** and choose this project's `.venv`. Then press **F5** and select **Profit Studio: Django**. The included launch configuration starts the local server. Do not run a second server on port 8000 at the same time.

| What you want to change | File or folder |
| --- | --- |
| Colors, spacing, responsive layout | `static/tracker/app.css` — start with the `:root` tokens |
| Same-page navigation and form behavior | `static/tracker/app.js` |
| Dashboard layout and wording | `templates/tracker/dashboard.html` |
| Sidebar and shared page layout | `templates/tracker/base.html` |
| Form labels and input validation | `tracker/forms.py` |
| Fields stored in the database | `tracker/models.py` |
| Monthly calculations and stock recording | `tracker/services.py` |
| Small money/date/stock rules | `tracker/domain.py` |
| Screen request handling and CSV export | `tracker/views.py` |
| URL paths | `tracker/urls.py` |
| Sample records | `tracker/management/commands/seed_demo.py` |
| Settings and database configuration | `config/settings.py` |
| Automated tests | `tracker/tests/` |

After editing Python, HTML, CSS, or JavaScript, save and refresh the browser. Django's development server reloads Python automatically. If a static-file change does not appear, hard-refresh to bypass the browser cache.

If you change database fields, back up your database, then run with your virtualenv Python:

```text
python manage.py makemigrations tracker
python manage.py migrate
python manage.py test --settings=config.test_settings
```

Here `python` means your selected `.venv` interpreter; use the explicit Windows/macOS paths above if your terminal isn't activated.

## Technology choices

- **Django 5.2 LTS series**, using the latest compatible patch installed by pip.
- **SQLite** for local demos; **PostgreSQL** is required when debug is disabled. Local data persists in `db.sqlite3`.
- **Django templates + plain CSS + small vanilla JavaScript**. Internal links and forms use same-origin fetch navigation to keep the shared app shell in place; server-rendered pages remain the source of truth. No React, API layer, HTMX, Bootstrap, npm build, or external CDN is required. Full-page navigation remains available when JavaScript is disabled, and file exports use normal browser downloads.
- Django email/password authentication, CSRF/password validation, and django-axes for login throttling.
- Decimal database fields for money; integer quantities for stock.

Money, stock, and month-closing changes are serialized with PostgreSQL row locks, or SQLite's database write lock for local use. Concurrent local tests use a disposable on-disk SQLite database. PostgreSQL concurrency is covered by the CI suite and requires a PostgreSQL test server.

## Rules that matter

**Payment date controls the month.** An August payment stays in August, even if stock arrives in September. Linking an expense to a SKU shows the same record in both places.

**Profit = money received minus expenses.** All recorded expenses count, including expenses paid by someone else. Payment summary groups those same entries by account. There is no manual statement-total entry.

**Stock and payments are separate.** Receiving stock and recording units sold change quantities only. Record manufacturing, shipping, refund, damage, repayment, or withdrawal payments through the expense form as required by the client's workflow. Existing historical transfer/withdrawal records keep their original classification; the app does not silently convert them into expenses.

**Edit and Delete are available.** Money and stock corrections retain an audit record. A stock correction cannot make the dated stock balance negative. Deleting a SKU removes it from the active list and new expense selections, while preserving existing payments and stock history.

**Duplicate protection has boundaries.** Repeating a submitted money or stock form uses its saved submission receipt. A nonblank statement reference must be unique among active entries for an account. Separately opened forms with blank references can still describe the same payment.

**Closed months are protected.** Close/reopen controls are on the monthly tracker. Financial changes require reopening the affected month. Stock changes also require reopening later closed months whose inventory would change.

**Photos are optional.** Add, replace, or remove a JPG, PNG, or WebP in the SKU form. Replaced files are removed after a successful database commit. See [client-workflow.md](docs/client-workflow.md) for storage requirements.

## Historical compatibility and remaining setup

Historical lot costs, statement tallies, transfer/withdrawal entries, and audit records remain in the database. The current screens do not request those extra inputs or calculate hidden FIFO/operating-profit panels. Retaining historical tables prevents destructive changes to existing records.

The app does not connect to a bank, import settlements, calculate live balances, or generate statutory accounts. Hosting, SMTP delivery, backups, and PostgreSQL verification still require their own configured environments. Production photos use the PostgreSQL database.

## Local verification

Run the read-only database audit:

```powershell
.\.venv\Scripts\python.exe manage.py audit_data
```

Run the regular suite and isolated stress suite:

```powershell
.\.venv\Scripts\python.exe manage.py test tracker.tests --settings=config.test_settings --noinput
.\.venv\Scripts\python.exe manage.py test tracker.stress_tests --settings=config.stress_settings --noinput
```

Browser checks require Playwright and permission to launch a headless browser:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe manage.py test tracker.browser_tests --settings=config.browser_settings --keepdb --noinput
```

See [audit-results.md](docs/audit-results.md) for observed results and limits.

## Backups and safety

For local backups, **stop the server first**, then copy `db.sqlite3` to a dated private backup location. It contains your records and account/password-hash data; don't commit it or send it with source ZIPs. Restore only after confirming the target and retaining a copy of the current database. CSV is a financial export, **not a full backup**: it doesn't include stock, users, or audit history.

The `.gitignore` excludes the database, virtualenv, local secret, and environment files. Review files before publishing a repository. This source archive contains no generated database, passwords, or bank credentials.

## Before any public launch

This folder is **not deployed**. Do not expose `runserver` to the internet.

Read **`DEPLOYMENT.md`** in order. It covers the single-owner production setup, database connection, sign-in verification, backups, and photo storage budget. `render.yaml` defines a Render Free web service only; it does not create the Neon database. No hosted service has been created by this repository alone.

Production settings reject missing secrets, hosts, origins, or PostgreSQL. Email setup is required if password recovery is enabled. The build also rejects a missing **`requirements.lock`**. Do not bypass these checks to make a deployment appear successful.

Useful official references:

- Django documentation: https://docs.djangoproject.com/en/5.2/
- Deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- VS Code Python: https://code.visualstudio.com/docs/python/python-tutorial
