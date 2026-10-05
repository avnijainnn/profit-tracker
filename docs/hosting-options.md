# Free hosting decision (October 2026)

Requirements: one user, real business records, product photos, no paid subscription,
and as little delay as possible when opening the site. The selected setup is
**Render Free web service + Neon Free PostgreSQL**, using the existing Django code.
Product photos are stored in PostgreSQL in production, so no paid disk or separate
media service is needed. The database and photos count toward Neon's free storage.

| Option | Cost and fit | Reason for decision |
| --- | --- | --- |
| Render Free + Neon Free | $0 within free allowances; existing accounts and code | Selected. Render sleeps after 15 minutes idle and may take about a minute to wake. No payment method on the Render account prevents overage billing; service may pause at a limit. |
| Vercel Hobby + Neon | Hobby is free, but restricted to personal or non-commercial use | This application tracks business income, expenses, and stock. Its use is commercial even with one user. Vercel also runs Django as functions with cold starts, so it does not guarantee an instant first request. |
| MongoDB Atlas Free | Free database, but no hosting benefit | The official Django MongoDB backend does not support `select_for_update()`, which the app uses to serialize financial and stock changes. Replacing PostgreSQL would require redesigning those operations and migrations. |
| PythonAnywhere Beginner + SQLite | $0, one worker and persistent files | Free app has a one-month expiry and 512 MiB disk allowance. PythonAnywhere does not recommend SQLite as a production database and reserves external database access for paid plans. |
| Koyeb Free + Neon | Free web instance | Sleeps after one hour idle. It has only 0.1 vCPU and 512 MiB RAM, is limited to US or EU regions, and is described as a preview/hobby instance. |
| Oracle Always Free VM | No subscription for eligible resources | Requires another account, usually a card for verification, server administration, and free capacity in the chosen region. Oracle may reclaim an idle VM, which is likely for a one-user app. |
| Railway Free + Neon | $1 of monthly usage credit | An always-running web service can exceed the free credit, so it cannot be assumed to stay at $0. |

No free option above guarantees both continuous availability and production-grade
service for this business app. Do not add a paid service, payment method, persistent
disk, or domain purchase without deliberately changing the cost requirement.

Sources: [Render Free](https://render.com/docs/free),
[Vercel pricing and Hobby use](https://vercel.com/pricing),
[Vercel function lifecycle](https://vercel.com/docs/functions/runtimes),
[MongoDB Django compatibility](https://www.mongodb.com/docs/languages/python/django-mongodb/current/limitations-upcoming/),
[PythonAnywhere Free features](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/),
[PythonAnywhere databases](https://help.pythonanywhere.com/pages/KindsOfDatabases),
[Koyeb free instance](https://www.koyeb.com/docs/reference/instances),
[Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Railway Free plan](https://docs.railway.com/pricing/plans).
