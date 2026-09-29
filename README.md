# Profit Studio — Tanvi's month-end tracker

An editable **Python / Django** project. Open this folder in VS Code, change ordinary Python, HTML, and CSS files, and run the website locally. There is no dependency on a chat session, proprietary website builder, or JavaScript build service.

**Status: production safeguards added; launch verification still required.** This is not a deployed or certified production system. Start with local fictional data. The free Render Blueprint uses Neon PostgreSQL and disables password reset in demo mode, so no mail service is required for the client preview. Follow `DEPLOYMENT.md` to create the fictional client workspace. `VERIFICATION.md` records the checks completed.

The accounting and inventory work is being implemented in stages. See [`docs/technical-design-progress.md`](docs/technical-design-progress.md) for the selected Cash Profit / Operating Profit rules, completed changes, and remaining gaps.

## What this version does

- Login-protected workspace; each user's records are isolated from other users in the app.
- Month dashboard with net receipts, expenses, Cash Profit and Operating Profit.
- Internal navigation and forms update the app content without a full document reload; browser Back/Forward continues to work, and CSV exports remain downloads.
- Year-at-a-glance reports with Cash Profit, Operating Profit, FIFO COGS and stock write-offs.
- Manual payment-mode credit/debit totals compared with recorded account activity; this is not a bank feed or transaction-level match.
- Multiple Razorpay, COD, UPI, and cash receipt entries; automatic monthly source totals.
- Expenses with an actual date, amount, category, payment account, optional SKU, payer, reference, and notes.
- Quick repeated entry with **Save & add another**; input can happen next month without changing the transaction month.
- Persistent custom accounts/categories and a starter setup button.
- Separate transfers/repayments, excluded from income and expenses.
- Products/SKUs for bags or thrift items, with dated inventory lots and landed-cost history.
- FIFO lot-cost allocation for sold units, plus separately reported Cash Profit and Operating Profit.
- Stock receipts with manufacturing/shipping costs, units sold, saleable returns, damage removals, and opening-stock adjustments.
- Negative-stock validation, including backdated movements.
- Financial edits and voids with a change history; read-only maintenance records in Django admin.
- Monthly financial CSV export with spreadsheet-formula escaping.
- An opt-in fictional demo. No bank connection, payment credentials, or real client records are included.
- Database-backed submission receipts prevent the same money/stock form being saved twice; changed retry payloads are rejected.
- Active statement references are unique per account; stale financial edits cannot overwrite a newer change.
- Month review/closing, reasoned reopening, and snapshots; stock backdating cannot alter a later closed month.
- Stock reversals preserve the original record and correct both available stock and sold-unit statistics.
- Production-enforced authenticator 2FA, backup codes, password-recovery email, and login throttling.
- PostgreSQL/Gunicorn/WhiteNoise configuration, a Render Starter web-service template for use with separately configured Supabase PostgreSQL, a PostgreSQL CI workflow, and an encrypted-backup helper. Cloud saving is not active until those services are provisioned and `DATABASE_URL` is configured.

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

`createsuperuser` asks you to choose your own username and password. There is no default login. Password characters are not displayed as you type — that is normal. An email address can be left blank for this local prototype.

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

Open **Accounts & categories**, then click **Add starter accounts & categories**. Repeating this button preserves existing records and does not create duplicate defaults.

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
- Django authentication/CSRF/password validation, django-two-factor-auth for authenticator/backup codes, and django-axes for login throttling.
- Decimal database fields for money; integer quantities for stock.

Money, stock, and month-closing services serialize changes per workspace using PostgreSQL row locks. The CI suite includes real concurrent PostgreSQL submissions. SQLite is only a convenient local demo database; it does not provide those concurrency guarantees.

## Rules that matter

**Actual date controls the month.** A ₹35,000 payment on August 22 remains an August expense even when typed in September. Linking it to Aqua Babe also displays it in Aqua Babe's history; that is one record, not another expense.

**Stock receipts capture costs by lot.** Enter the arrival date, quantity, full manufacturing/shipping/other direct costs, and payment details. Cash Profit counts the payment on its payment date; Operating Profit moves that inventory cost into FIFO COGS when units sell. Keep ordinary operating expenses separate from lot costs.

**Receipts are net statement amounts.** Don't enter fees or refunds again if already deducted from a settlement. A separately paid manual refund is an expense. This is application workflow guidance, not a substitute for accounting advice.

**Transfers are excluded.** Credit-card purchases can be expenses; credit-card bill payments, wallet top-ups, own-bank transfers, and reimbursements use the transfer/repayment type. Classification is manual — the app cannot recognize a transfer you accidentally enter as an expense.

**These are management reports, not statutory accounts or live balances.** Cash Profit uses actual receipts and payments from your accounts; expenses someone else paid do not reduce it. Operating Profit uses separately entered gross sales amounts and sale dates, operating expenses, FIFO COGS, and recorded stock write-offs. Legacy stock costs and receipts without a recognized sales amount are flagged as incomplete. Liabilities, GST/tax, depreciation, accrued unpaid expenses, and settlement matching are not calculated.

**Stock history is preserved.** Enter receipts/opening stock before sales. A saleable return adds stock. Use **Reverse mistake** to cancel an incorrect movement in its original month, then enter its replacement. This also corrects sold-unit statistics. Generic adjustments are for genuine stock-count differences. Reversing a receipt is blocked if subsequent stock would become negative. A damaged customer return that never becomes saleable needs a dedicated damaged-return workflow, still deferred.

**Duplicate protection has defined boundaries.** The same submitted money/stock form is processed once, even with retries; active nonblank statement references are constrained in the database. Two separately opened forms with blank references can still represent the same real-world payment, so enter statement references and review entries. An identical amount alone is not evidence of duplication.

**Closed means protected.** A completed month can be closed after review. Its transactions cannot be added, edited, or voided until reopened with a reason. Stock changes affecting any later closed month's ending inventory also require reopening those affected months. The original close snapshots remain in change history. These records are application history, not a tamper-proof regulatory audit ledger.

## Deferred / awaiting Tanvi's answers

1. Complete historical SKU costs: current lots support FIFO unit costs, but old stock has unknown cost until reviewed and corrected.
2. Sales-to-settlement reconciliation: no assumption that gross sales equal same-month net settlements.
3. Matching supplier advances to deliveries, reconciliation of actual supplier payments, and correction of legacy lot costs.
4. Dedicated case-by-case customer return and damaged-stock register; only basic stock movements exist now.
5. Final owner salary/withdrawal policy: this version shows before and after owner withdrawals.
6. Final third-party payment policy: expenses currently count on the original payment date and are highlighted separately. Repayments are excluded; outstanding amounts owed are not tracked.
7. CSV/bank-statement import, bank/Shopify/Razorpay integration, receipt attachments, subcategories, and bulk spreadsheet entry. Bank tally currently compares manually entered monthly totals only.
8. Reimbursement matching, shared staff workspaces/permissions, account/category editing/archiving, product image uploads, and live account balances.
9. Actual hosting/account setup, SMTP delivery verification, backup scheduling and restore drill, external alert destinations, browser QA, and production acceptance. Source configuration does not mean those services exist.

## Backups and safety

For local backups, **stop the server first**, then copy `db.sqlite3` to a dated private backup location. It contains your records and account/password-hash data; don't commit it or send it with source ZIPs. Restore only after confirming the target and retaining a copy of the current database. CSV is a financial export, **not a full backup**: it doesn't include stock, users, or audit history.

The `.gitignore` excludes the database, virtualenv, local secret, and environment files. Review files before publishing a repository. This source archive contains no generated database, passwords, or bank credentials.

## Before any public launch

This folder is **not deployed**. Do not expose `runserver` to the internet.

Read **`DEPLOYMENT.md`** in order. It covers locking dependencies, PostgreSQL CI, a separate staging deployment, SMTP/2FA verification, backup restoration, and a controlled first-month pilot. `render.yaml` defines a Render Free web service only; it does not create Supabase resources or a database. No account, database, server, domain, monitoring subscription, or paid service has been created by this handoff.

Production settings reject missing secrets, hosts, origins, PostgreSQL, or email setup. The build also rejects a missing **`requirements.lock`**. This lockfile must be resolved on a network-enabled development machine, tested, audited, and committed; it has not been fabricated here. Do not bypass these checks to make a deployment appear successful.

Useful official references:

- Django documentation: https://docs.djangoproject.com/en/5.2/
- Deployment checklist: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
- VS Code Python: https://code.visualstudio.com/docs/python/python-tutorial
