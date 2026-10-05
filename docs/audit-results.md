# Data-flow and calculation audit

Local audit: 5 October 2026. All stress fixtures were created in disposable test databases. Client payment and stock records were not changed.

## Data flow

| Input | Stored record | Monthly calculations | Stock |
| --- | --- | --- | --- |
| Money received | Income entry | Receipt date; adds to money received | No change |
| Expense, optionally linked to a SKU | Expense entry | Actual payment date; adds once to expenses | No change |
| Receive stock | Stock movement and quantity lot | Does not create an expense | Adds units on arrival date |
| Units sold | Stock movement | Does not create income; record received money separately | Removes units on sale date |
| Edit/Delete money entry | Corrected entry or retained void record | Active totals update in the affected payment month | No change |
| Edit/Delete stock entry | Corrected movement or retained reversal | Existing payments stay in their original month | Dated balance recalculated; negative stock is rejected |
| Delete SKU | SKU becomes inactive | Existing expenses remain counted | Historical stock remains stored |

Profit is money received minus all active expenses. Expenses paid by someone else are included. Payment summary groups the same active entries by account. Dashboard, yearly reports, payment summary, and CSV use the payment-date timeline and owner scope.

Historical transfer and owner-withdrawal entries retain their original classifications and remain excluded from the three client totals. New payments entered through Expenses count as expenses. Historical records are not silently reclassified.

## Fixes made during the audit

- Replaced hidden FIFO and operating-profit work in client pages with direct database summaries.
- Removed queries that grew with the number of SKU expense rows.
- Added SQLite write locking before money/stock validation; PostgreSQL continues to use row locks.
- Serialized account creation and rechecked duplicate SKUs while holding the workspace lock.
- Removed unused statement-entry form, More actions CSS/JavaScript, and selling-price/active inputs from the SKU form.
- Delete SKU preserves recorded payments; stale forms cannot link a new payment or stock receipt to a deleted SKU.
- Replaced and cleared photo files are removed after successful database commit.
- Malformed account/product query parameters return 404 instead of server errors.
- Allowed empty audit metadata and open-month snapshots in model validation. Migration 0012 changes validation metadata and preserves stored records.
- Updated regression and browser tests to the current client workflow.

## Verification

Latest regular results: 119 tests ran, with 116 passing and 3 PostgreSQL-only tests skipped locally. All 8 stress tests passed. The latest stress run served 50 screen requests with a median of 402.0 ms, a 95th percentile of 2097.9 ms, and at most 10 database queries per request. These timings are Django test-client measurements on this machine while other verification processes were also running.

The read-only `audit_data` command checks applied migrations, SQLite integrity, foreign keys, model validation, related workspace ownership, missing photo files, stock timelines, and monthly/payment totals against the stored ledger. The latest local database audit passed with 28 validated application records and no financial-month groups; financial calculations were exercised using test fixtures.

Stress coverage uses 10,000 money entries, 200 SKUs, and 4,000 stock movements. Every month's totals are compared with an independently calculated Decimal ledger. Repeated screen requests have a maximum database-query budget. Eight simultaneous workers test overselling, receipt retries, expense retries, stale corrections, and duplicate SKU/account creation.

Commands:

```powershell
.\.venv\Scripts\python.exe manage.py test tracker.tests --settings=config.test_settings --noinput
.\.venv\Scripts\python.exe manage.py test tracker.stress_tests --settings=config.stress_settings --noinput
.\.venv\Scripts\python.exe manage.py test tracker.browser_tests --settings=config.browser_settings --noinput
.\.venv\Scripts\python.exe manage.py audit_data
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pip check
```

## Limits

- Browser verification could not complete: Windows denied Playwright's Edge launch with `spawn EPERM`. Visual layout, JavaScript navigation, browser uploads, and downloads have not been verified in this session. Browser tests remain available for a machine that permits headless Edge.
- Three existing PostgreSQL-only tests are skipped locally because this workspace uses SQLite. PostgreSQL-specific behavior requires the configured PostgreSQL CI environment.
- Stress timings describe this local test machine and dataset, not hosted capacity or guarantees for arbitrary workloads.
- Historical cost/allocation and statement tables remain for data compatibility; they are not requested by the simplified client UI. No tables or historical records were dropped.
