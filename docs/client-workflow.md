# Client workflow

- Record money received on the actual receipt date.
- Add expenses from the Monthly tracker, using the actual payment date, and optionally select the SKU in that form. An August payment appears in August, even if the product arrives in September. SKU pages show the linked entries but do not have a separate Add Expense shortcut.
- Record stock arrivals and units sold using their actual dates. These forms ask only for date, quantity, and optional batch/notes. They do not create expenses.
- The dashboard shows money received, expenses, and profit (money received minus expenses), followed by one entries list.
- Payment summary automatically groups the selected month's money received and expenses by payment account. Enter each payment only once in the monthly tracker. Transfers and owner withdrawals are excluded; expenses paid by someone else retain their own account row.
- SKU cards show a photo beside the name and available quantity. The detail page has one stock history table and the selected month's expenses.
- Each SKU has Edit and Delete options. Deleting hides it from the SKU list and new expense selections; existing expenses and stock history are retained.
- Edit and Delete are available on money and stock entries. Deleting removes an entry from active lists and totals while retaining an audit record. Closed months must be reopened; stock changes cannot leave a negative quantity.
- Record refunds and damage costs as ordinary expenses; there is no separate return/damage stock menu.

## Product photos

Add, replace, or remove a JPG, PNG, or WebP photo in the SKU form. Uploads are optional, limited to 5 MB and 16 million pixels, and saved as normalized JPEG thumbnails. Photos are served only to the logged-in workspace owner.

Local uploads are stored in `media/`, which is excluded from Git; back up this directory alongside the local database. In production, photos are stored with records in PostgreSQL, so a database backup includes them and Render restarts do not remove them.
