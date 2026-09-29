# Verification — 29 September 2026

This review covers the implemented Django application. It does not certify the
unbuilt modules in `docs/technical-design-progress.md`. No hosted URL has been
created: GitHub, Render, Neon and Brevo accounts must still be connected before deployment.

## Executed checks

- Initial SQLite suite: 71 tests passed, with two PostgreSQL-only tests skipped.
- Six new regression tests cover invalid receipt dates, changed receipt retries,
  stale expense reuse, FIFO lot balances after damage, fractional cost display,
  and missing revenue/cost warnings.
- Linux Python 3.12.14: 16 calculation/receipt regression tests passed.
- Browser workflows: eight scenarios exercised in headless Edge, covering login,
  expense/income entry, inline account/category creation, editing/voiding,
  save-and-add-another, products, receipts/sales/damage/reversals, failed-save
  recovery, no-JavaScript forms, payment checks, CSV downloads, month closing and
  reopening, search/filter/navigation, and authenticator/backup-code recovery.
- Responsive screens checked at 1440, 390 and 320 pixels, including populated
  dashboard/lot history and the receive-stock form. Page-width overflow is
  asserted; wide data tables scroll within their panels. Screenshots were
  visually inspected, including amounts with paise and action buttons.
- `manage.py check` passed. `makemigrations --check --dry-run` found no changes.
  JavaScript syntax validation passed. All ten tracker migrations are applied
  to the existing local database; this review did not change its records.
- Production configuration check with `--deploy --fail-level WARNING` passed
  and WhiteNoise static collection succeeded, using disposable test settings.
- Python 3.12.14 Linux dependency lock generated and installed with hash
  verification. Audit reported **no known vulnerabilities** for the locked
  runtime dependencies. This is a point-in-time result, not a future guarantee.

The Linux Python 3.12.14 `bash build.sh` completed successfully (exit 0),
including hash-checked installation, static collection and production checks. The free Render demo configuration also passes `check --deploy --fail-level WARNING` with its inferred HTTPS host.
Browser reruns of authentication and populated responsive pages passed (2/2).
Production-mode startup applied PostgreSQL migrations, inferred the Render hostname, created the fictional workspace, enforced 2FA, and passed a second restart without resetting the password or data. Eight bootstrap tests cover fresh/empty startup, production with no demo data, bad/missing credentials, rollback, restarts and concurrent startup.
Final PostgreSQL 16 suite: **85 tests passed, zero skipped, exit 0**, including
overselling and idempotent-submission concurrency tests. Database creation,
migrations and teardown completed. The thread-connection cleanup issue found
in the first PostgreSQL run was fixed in the test harness.

One browser run timed out during the initial login-page load while the test
infrastructure was starting. The other seven scenarios passed on that run;
authentication and populated responsive screens were rerun explicitly; both passed (exit 0). This was not an HTTP 500 or JavaScript exception. Screenshots are in the OS temp
folder `profit-tracker-ui-review`.

## Corrections made during this review

- Missing stock dates now produce field errors instead of a server error.
- Receipt retry fingerprints include cost amounts, dates, payment account and
  linked expenses. Changed retries are rejected without duplicate writes.
- Previously recorded expenses are re-read and locked before capitalization;
  stale forms cannot assign the same payment to a second lot. PostgreSQL locks
  the expense row without locking the nullable category join.
- Lot remaining quantities are calculated in chronological order. Sold stock
  followed by damage no longer misstates the remaining balance per lot.
- Lot cost presentation retains paise; operating expense lists exclude
  capitalized costs. Audit snapshots retain capitalization and lot links.
- Empty subcategory/prior-payment controls are hidden; optional choices have
  meaningful labels. Small-phone month pickers show the full selected month.
- Reports show stock write-offs and flag unknown write-off costs or missing
  sales revenue in affected months.
- Free deployment now applies migrations and safely bootstraps one owner at startup,
  without provider shell access. Restart is idempotent and generates fictional data
  only when explicitly enabled. Render-host URL inference and Brevo port 2525 are set.

Hosted setup uses a one-time randomly generated account password (not stored in source); database initialization is safe to repeat. The production defaults retain secure password hashing. Faster hashing is used
only in explicitly selected test settings. Two documented check exceptions are
intentional: optional HSTS preload and username-only login throttling (tested
across changing user agents/cookies); HTTPS and login lockout remain enforced.

## Boundaries before showing the client

- Client demo should contain fictional records in a separate PostgreSQL database.
- Revenue and units sold are entered separately. They must be reconciled during
  the walkthrough; sales-to-settlement matching is not automated.
- Opening stock/returns with unknown landed costs make relevant profit figures
  incomplete. Historical lot-cost correction is not yet a guided workflow.
- Shared Owner/Staff roles, team/salary records, borrowing balances and a full
  subcategory management UI are not implemented. Wallet checks compare totals;
  they are not a dedicated liability/balance ledger.
- Actual hosted HTTPS/proxy behavior, live SMTP delivery and recovery email,
  restart persistence, scheduled backups and a restore drill remain unverified.
- No hosted services were provisioned during local setup. The blueprint uses Render
  Free, Neon Free and Brevo Free. `DEPLOYMENT.md` contains setup and walkthrough steps.
