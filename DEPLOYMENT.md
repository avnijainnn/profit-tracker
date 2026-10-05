# Single-owner production deployment (Render Free + Neon Free)

The free hosting alternatives and their tradeoffs are recorded in
[hosting-options.md](docs/hosting-options.md).

This repository deploys the existing Django application. The Render Blueprint creates
one free web service; create the Neon Free PostgreSQL database separately. No paid
subscription or additional storage service is required. Stay within both providers'
free limits. This client's existing SQLite workspace, including its product photo,
must be transferred before the site is handed over. The existing login is preserved;
the client can change its username, email, and password after signing in.

## Before deployment

1. Keep `.env`, `.local-secret`, `db.sqlite3`, `media/`, and backups out of Git.
2. Push this repository, including `render.yaml`, `requirements.lock`, `build.sh`,
   and `start.sh`, to GitHub.
3. Run the project tests and verify the production configuration. Treat a failed
   check or migration as a deployment blocker.
4. Keep a private backup of both `db.sqlite3` and `media/`. Stop entering records
   in the local site for the final transfer, so the new site receives every entry.

## Create the free database

Create a Neon Free PostgreSQL project. Copy its **direct** connection string into
Render's private `DATABASE_URL` environment variable. Use the direct URL because
`prepare_deploy` takes a PostgreSQL session advisory lock during migration. Keep
SSL enabled. Do not commit or paste the URL into a public issue or chat.

Neon stores records and product photos. Monitor its storage and compute allowances;
photos count toward the free database storage limit.
Create independent database backups and test a restore before relying on the
service for financial records. The app's CSV export is not a full backup.

## Deploy the web service

1. In Render, create a Blueprint from this GitHub repository. Review `render.yaml`
   and select the Free web service plan. Auto deploy is initially off. Avoid adding
   a payment method if you want Render to suspend service instead of billing when
   a free allowance is exhausted.
2. Supply the private values Render requests:
   - `DJANGO_SECRET_KEY`: a random value of at least 50 characters. Generate one
     locally with `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
   - `DATABASE_URL`: the Neon direct PostgreSQL connection string.
   - `INITIAL_OWNER_SETUP_TOKEN`: generate a random value locally with
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`. This keeps
     the empty site ready for transfer. **Do not send a setup link to the client**:
     it would create a new account and make the empty-database import refuse to run.
3. Create the service. On first startup, `prepare_deploy` migrates the empty Neon
   database and waits for the existing workspace to be transferred. It does not
   add fictional transactions because `APP_ENV=production` and
   `DEMO_SEED_DATA=false`.

## Transfer the existing SQLite workspace

The transfer command reads a consistent SQLite snapshot, copies the existing user,
financial records, products, and local photos, then verifies the imported records
and photo bytes. It refuses a destination that already contains user or workspace
data. It never edits the local source or the private backup.

1. Keep the old site closed to new entries during the final transfer. In the
   project directory, run this read-only preview against the **current** local
   files (not an older backup):

   ```powershell
   .\.venv\Scripts\python.exe manage.py import_sqlite_workspace --source-db db.sqlite3 --media-root media
   ```

2. After the Render service has created the Neon tables, set its **direct** Neon
   connection string in the local PowerShell session, without putting it in Git
   or chat. `DJANGO_DEBUG=true` is for this local command only; Render remains
   configured with `DJANGO_DEBUG=false`.

   ```powershell
   $privateUrl = Read-Host 'Direct Neon DATABASE_URL' -AsSecureString
   $env:DATABASE_URL = [System.Net.NetworkCredential]::new('', $privateUrl).Password
   $env:DJANGO_DEBUG = 'true'
   $env:DATABASE_SSL_REQUIRE = 'true'
   .\.venv\Scripts\python.exe manage.py import_sqlite_workspace --source-db db.sqlite3 --media-root media --apply
   $env:DATABASE_URL = $null
   $privateUrl = $null
   ```

3. Confirm that the command reports a verified transfer. If it fails, do not
   enter data in Neon or rerun against a nonempty target; inspect the error first.
   Once the old user is imported, the private setup link is disabled automatically.
   The client signs in with her **existing** email and password, then uses
   **Settings → Change username, sign-in email, or password** if she wants new
   credentials. Sign-in continues to use the email address.

Do not send the client the live URL before this transfer and the read-only checks
below are complete.

The free service sleeps after 15 minutes without traffic, so the next visit may
take about a minute to load. Render's local filesystem is temporary: do not use
its local files for a SQLite database or backups.

## Product photos and account recovery

Product photos use the PostgreSQL database in production, so they survive Render
restarts, sleep, and redeploys. Photos remain available only through the app's
authenticated endpoint. Locally, Django keeps using the `media/` folder. Local
photos and records are copied by the one-time transfer command above.

Password reset is disabled in the free Blueprint because no mail provider is
configured. The client should keep her password in a password manager. To enable email
recovery later, configure a supported transactional email provider, set
`ENABLE_PASSWORD_RESET=true`, and verify delivery before relying on it.

## Verification and rollback

Check Render deploy logs for successful dependency installation, static collection,
and migrations. Confirm the `/healthz/` endpoint and sign in over HTTPS. Check that
the existing entry, both products, and the product photo appear, and compare their
values with the local site. The deployed interface must not show a demo banner or
fictional entries. Back up the database before later updates. If an update fails,
restore the previous code version and investigate before retrying. Do not delete
the Neon project to reset a password or repair a failed deployment.

Provider free plans and limits can change. Check the current Render and Neon
dashboards before deployment and during use.
