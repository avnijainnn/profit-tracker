# Single-owner production deployment (Render Free + Neon Free)

The free hosting alternatives and their tradeoffs are recorded in
[hosting-options.md](docs/hosting-options.md).

The client is already using `https://profit-tracker-q4eo.onrender.com/`. Its live
database is the source of truth. The `db.sqlite3` in this checkout is a separate
local workspace and must **not** be imported over the live client workspace.
The client can change the existing account's username, email, and password after
the live service is updated to this revision.

## Update the existing live service

1. In Render, find the service whose public URL is
   `https://profit-tracker-q4eo.onrender.com/`. Confirm its current GitHub
   repository/branch and the database configured by its private `DATABASE_URL`.
   Keep that connection string out of Git and chat. Do not create a second
   database or change `DATABASE_URL` during the code update.
2. Pause client data entry. Take an independent backup of the **live PostgreSQL
   database** and verify it can be read. Record the existing user's email and
   counts of entries, products, stock events, and uploaded photos. Inspect
   `workspace_initialized` for `fictional_data` and any `DEMO` records; review
   these separately from the client's records before removing anything.
3. Check product photos on the current live site and retain copies of any that
   still load. The older deployment stored uploads on Render's temporary local
   filesystem, so a code redeploy cannot be assumed to preserve those files.
4. Update the **same Render service** from the verified `main` commit. In its
   Settings, confirm the build command is `bash build.sh`, the start command is
   `bash start.sh`, and the health check is `/healthz/`. Retain its existing
   `DATABASE_URL` and `DJANGO_SECRET_KEY`. In Environment, set
   `APP_ENV=production`, `DJANGO_DEBUG=false`, `DEMO_SEED_DATA=false`,
   `ENABLE_PASSWORD_RESET=false`, `DATABASE_SSL_REQUIRE=true`, and
   `TRUST_PROXY_HTTPS=true`. Existing users and records are left unchanged by
   `prepare_deploy`; migrations run before the web process starts. Check the
   deploy logs, live sign-in, record counts, and photos before reopening data
   entry. Do not run `import_sqlite_workspace` against this database: it is
   intended only for an empty destination and refuses nonempty workspaces.

## Empty new service only

The steps below apply only if an entirely new, empty PostgreSQL database and
Render service are deliberately created. The Render Blueprint creates one free
web service; create the Neon Free PostgreSQL database separately. No paid
subscription or additional storage service is required. Stay within both
providers' free limits.

## Before deployment

1. Keep `.env`, `.local-secret`, `db.sqlite3`, `media/`, and backups out of Git.
2. Push this repository, including `render.yaml`, `requirements.lock`, `build.sh`,
   and `start.sh`, to GitHub.
3. Run the project tests and verify the production configuration. Treat a failed
   check or migration as a deployment blocker.
4. For an empty new service, keep a private backup of both `db.sqlite3` and
   `media/`. Stop entering records in the local site for the final transfer.

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

## Transfer a SQLite workspace to an empty new service only

Never run this transfer for `profit-tracker-q4eo.onrender.com` or its live database.
For a separate empty service, the transfer command reads a consistent SQLite
snapshot, copies the existing user, financial records, products, and local
photos, then verifies the imported records and photo bytes. It refuses a
destination that already contains user or workspace data. It never edits the
local source or the private backup.

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

With this revision, newly uploaded product photos use the PostgreSQL database in
production, so they survive Render restarts, sleep, and redeploys. Photos remain
available only through the app's authenticated endpoint. Files uploaded under
the older live deployment are **not** moved into PostgreSQL automatically;
retain and migrate those separately before updating it. Locally, Django keeps
using the `media/` folder. For an empty new service, the transfer command above
copies local photos and records.

Password reset is disabled in the free Blueprint because no mail provider is
configured. The client should keep her password in a password manager. To enable email
recovery later, configure a supported transactional email provider, set
`ENABLE_PASSWORD_RESET=true`, and verify delivery before relying on it.

## Verification and rollback

Check Render deploy logs for successful dependency installation, static collection,
and migrations. Confirm the `/healthz/` endpoint and sign in over HTTPS. For the
existing live service, compare its user and record counts with the live backup
made before deployment, and verify uploaded photos separately. For an empty new
service receiving the local SQLite import, check its entry, products, and photo
against the local source. The production interface must not show a demo banner
or fictional entries. Back up the database before later updates. If an update
fails, restore the previous code version and investigate before retrying. Do
not delete the Neon project to reset a password or repair a failed deployment.

Provider free plans and limits can change. Check the current Render and Neon
dashboards before deployment and during use.
