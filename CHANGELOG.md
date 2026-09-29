# Production safeguards update

This update modifies the original Django project; existing schema changes are included as migrations 0002 and 0003. It has not been deployed or cleared for real financial data.

## Data safeguards

- Submission tokens and committed receipts for financial/stock retries.
- Database uniqueness for active statement references per owner/account.
- Revision checks and mandatory correction reasons for financial edits/voids.
- Completed-month closing, reasoned reopening, and historical close snapshots.
- Stock reversals preserving the original entry and correcting sales statistics.
- PostgreSQL workspace locks around financial, stock, and month-state mutations.
- Backdated stock changes cannot alter later closed-month inventory.

## Access and operations

- Production-enforced authenticator two-factor authentication and backup-code support.
- Separate normal-user creation command; privileged maintenance admin requires OTP.
- Password reset email with generic responses and per-identifier sending limits.
- Django Axes login lockout configuration.
- Production PostgreSQL, HTTPS/cookie/host/origin checks, Gunicorn, and WhiteNoise.
- Minimal redacted operational logs and a database health endpoint.
- Encrypted PostgreSQL backup helper; scheduling, offsite copies and restore testing remain operator tasks.

## Deployment and handoff

- Render configuration template with manual releases and private database access.
- GitHub PostgreSQL verification workflow with an opt-in Linux lock-resolution mode.
- Build fails when the required dependency lock is absent.
- Updated README, design notes, deployment guide, tests, and verification report.

**Verification:** 12 independent tests plus syntax/configuration parsing checks passed. Dependencies could not be installed here; Django, PostgreSQL, browser, actual recovery, backup restoration and hosting checks remain unexecuted. See VERIFICATION.md and DEPLOYMENT.md before launch.
