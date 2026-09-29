# Free Render client demo

This blueprint costs **$0 within provider free-tier limits**. It creates only a
Render web service; it does not create a database or send credentials anywhere.
The workspace remains separate from this machine's SQLite database.

## Accounts to create

- A GitHub account/repository for this project. Put the contents of
  `profit_tracker-client-demo-source.zip` in the repository root. The enclosing
  Downloads folder is a separate workspace: never upload it. Add `render.yaml`,
  `requirements.lock`, and `start.sh`. Keep `.venv`, `.env`, `.local-secret`,
  database files and backups out of Git.
- A free Neon PostgreSQL project. Copy its **direct connection string** (not a
  transaction-pooler URL); migrations need a session-level advisory lock.
  Leave Neon SSL enabled.
- A free Brevo account for password-reset mail. Verify a sender address and
  copy the SMTP login and SMTP key from Brevo. It currently offers up to 300
  messages/day on its free tier.

## Render setup

1. Create a free Render web service from this GitHub repo using `render.yaml`.
   The blueprint leaves auto-deploy off. Review the deploy, then enable it once
   setup succeeds. Render supplies an HTTPS `*.onrender.com` address; Django
   reads the matching host and CSRF origin automatically.
2. At first setup, enter these secret values when Render prompts for them:
   - `DJANGO_SECRET_KEY`: generate locally with
     `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
   - `DATABASE_URL`: direct Neon connection string (contains its password).
   - `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`: your
     verified Brevo SMTP credentials and sender.
   - `INITIAL_OWNER_EMAIL`: mailbox where the owner can receive password resets.
   The blueprint generates a separate random password for `client-demo`.
   Copy it from this private Render environment into your password manager.
   **Do not commit secrets or paste credentials into chat.**
3. Create the service. `start.sh` runs `prepare_deploy`: it applies migrations,
   initializes the first regular (non-admin) user, and adds a fictional tote
   walkthrough to the empty Neon database. Subsequent starts see the existing
   account and leave its password, demo entries and database alone. It never
   prints the password. On first sign-in, enroll authenticator 2FA and save the
   recovery codes.
4. Check password recovery in the deployed site. Render's free plan blocks
   outbound ports 25, 465 and 587; this setup uses Brevo's supported STARTTLS
   port 2525. Email delivery and sender approval require a live check. If mail
   does not arrive, use Brevo's delivery logs before presenting account recovery.
5. Open the URL once before the meeting. A free Render service sleeps after
   15 minutes without traffic; the next request can take about a minute to wake.
   Neon also has per-project compute and storage limits. Monitor both free plans.

## Five-minute walkthrough

The fictional sample is seeded in the last completed month (August 2026 when
first created in September 2026). It receives 10 bags for Rs 5,000 manufacturing
and Rs 500 shipping, sells four, records Rs 4,000 sales revenue, pays Rs 300
operating expense and transfers Rs 200 to the CRED wallet.

The sale month should show Rs 2,200 FIFO COGS and Rs 1,500 Operating Profit.
Cash Profit in that month is minus Rs 5,800. The Rs 4,000 cash settlement lands
in the following month. Six bags remain in the lot. The transfer affects the
wallet check, not profit. Use the month picker to view both months, then inspect
the lot, payment checks, CSV and month close/reopen.

This sample uses invented data. Do not enter client financial data into a free
preview or rely on it for bookkeeping. Render Free services can sleep and have
an ephemeral filesystem, so Neon is the durable store. Free-plan availability,
limits and provider terms can change; read each account's current dashboard.

## If initialization needs retrying

`prepare_deploy` is safe to rerun. If the first account was partially set up,
the transaction rolls back. If an existing user or demo workspace is present,
startup never resets it. Do not delete the Neon database to reset a password;
use the normal recovery link after verifying SMTP.

The full management tracking design still has unfinished staff roles, salaries,
borrowing balances and subcategory management. See
`docs/technical-design-progress.md` before promising those features.
