# Single-owner production deployment (Render Free + Neon Free)

The free hosting alternatives and their tradeoffs are recorded in
[hosting-options.md](docs/hosting-options.md).

This repository deploys the existing Django application. The Render Blueprint creates
one free web service; create the Neon Free PostgreSQL database separately. No paid
subscription or additional storage service is required. Stay within both providers'
free limits. The live workspace starts empty and creates one ordinary owner account.
It does not import the local `db.sqlite3` file.

## Before deployment

1. Keep `.env`, `.local-secret`, `db.sqlite3`, `media/`, and backups out of Git.
2. Push this repository, including `render.yaml`, `requirements.lock`, `build.sh`,
   and `start.sh`, to GitHub.
3. Run the project tests and verify the production configuration. Treat a failed
   check or migration as a deployment blocker.
4. Decide whether records in the local SQLite database must be migrated. Do not
   enter live records in a new empty database and then overwrite it with a later
   import.

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
   - `INITIAL_OWNER_EMAIL`: the one user's sign-in email address.
3. Render generates `INITIAL_OWNER_PASSWORD`. Save the generated password in a
   password manager before using the site. Do not send it through chat or Git.
4. Create the service. On first startup, `prepare_deploy` migrates the database
   and creates the owner account and default accounts/categories. It does not
   add fictional transactions because `APP_ENV=production` and
   `DEMO_SEED_DATA=false`. Later restarts preserve the account and its records.
5. Visit the Render HTTPS URL and sign in with `INITIAL_OWNER_EMAIL` and the
   generated password. Check the dashboard, add and edit a small test entry,
   check its report, then remove the test entry before entering real data.

The free service sleeps after 15 minutes without traffic, so the next visit may
take about a minute to load. Render's local filesystem is temporary: do not use
its local files for a SQLite database or backups.

## Product photos and account recovery

Product photos use the PostgreSQL database in production, so they survive Render
restarts, sleep, and redeploys. Photos remain available only through the app's
authenticated endpoint. Locally, Django keeps using the `media/` folder. Local
photos and records are not copied to the new empty Neon database.

Password reset is disabled in the free Blueprint because no mail provider is
configured. Keep the owner's password in a password manager. To enable email
recovery later, configure a supported transactional email provider, set
`ENABLE_PASSWORD_RESET=true`, and verify delivery before relying on it.

## Verification and rollback

Check Render deploy logs for successful dependency installation, static collection,
migrations, and account initialization. Confirm the `/healthz/` endpoint and sign
in over HTTPS. Back up the database before updates. If an update fails, restore
the previous code version and investigate the migration before retrying. Do not
delete the Neon project to reset a password or repair a failed deployment.

Provider free plans and limits can change. Check the current Render and Neon
dashboards before deployment and during use.
