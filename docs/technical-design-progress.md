# Technical design implementation status

This file tracks the proposed accounting and inventory design against the current Django implementation. The application keeps Django and PostgreSQL because the suggested Next.js/Prisma stack was explicitly adjustable and replacing the working app would not add accounting correctness.

## Agreed reporting assumptions

- **Cash Profit** uses actual receipt dates and payments from the business's own accounts. Third-party-paid expenses do not reduce cash profit. Inventory acquisition payments are included here.
- **Operating Profit** uses a separately entered gross sales amount and the date that revenue was earned, minus operating expenses, FIFO cost of units sold, and recorded inventory write-offs. Inventory acquisition costs are capitalized and are not also treated as operating expenses.
- Net settlements and earned sales revenue can differ. Income entries therefore have a cash amount/date and optional recognized sales amount/sale date. Advances can be recorded as cash without being counted as earned revenue yet.
- Legacy stock movements are retained. Their landed costs were not captured, so migration-created lots are marked as unconfirmed; reports count their cost as zero and visibly flag affected sold units. Historical costs must be entered/corrected before relying on those periods.

## Implemented in this slice

- `InventoryLot` stores product, received date, received quantity, manufacturer, manufacturing, shipping and other direct costs, batch, and cost confirmation. Returned/opening/adjustment stock with no known cost is flagged as unconfirmed too.
- Receiving stock captures arrival date separately from payment date. It can link existing SKU expenses into the lot (preserving their original cash rows) or create linked capitalized expense entries for new costs, avoiding duplicate cash outflow.
- `LotDepletion` records per-sale FIFO lot allocations using Decimal unit cost. Damaged/adjusted-out units also consume FIFO stock allocations and reduce Operating Profit as write-offs.
- Income can record cash received separately from recognized sales revenue and sale date. Operating Profit uses recognized sales amounts only; missing amounts are counted and called out so a net settlement is not silently presented as gross revenue.
- Dashboard and yearly report now show Cash Profit, Operating Profit, COGS, unknown legacy cost units, and receipts without recognized sales amounts.
- Category cost behavior and optional subcategory data structures exist. Category behavior is captured on expense entries. The subcategory management UI is not implemented yet.
- Manual account statement totals now include cash, cards, and wallets as well as banks. This is still a totals comparison, without opening/closing balances or statement-line matching.
- SKU sales-amount input/display was removed; only units sold are entered in stock flows.
- Existing rows are migrated without deleting financial or stock history. Income sale dates are backfilled from their old dates, but recognized sales amounts and legacy lot costs remain unknown.

## Still required to meet the full design

- Salary/team-member transactions and a role model with Owner-only month close/reopen. Current authentication is workspace-isolated, but all workspace users effectively have the same permissions.
- Borrowing records and repayment balances/status. Current transfers/repayments remain separate from expenses but do not track liabilities.
- A dedicated wallet transaction ledger and live per-mode balances. Current account transfers and expenses can be compared to manual totals but do not produce authoritative wallet balances.
- Subcategory creation/editing UI. Category behavior totals are shown on the dashboard; behavior does not itself change recognition timing.
- Unpaid operating expenses/accruals, sales-to-settlement matching, and sale allocation across a settlement spanning multiple sale dates. For now, enter a separate recognized sales amount/date when known; a missing amount remains explicitly incomplete.
- Staff access/invitation flow, PWA manifest/service worker, restore-tested backups, hosted SMTP/2FA delivery check, and deployment verification. Local PostgreSQL verification is tracked in `VERIFICATION.md`.
- A migration/review process to enter real historical lot costs. Until then, flagged legacy COGS makes historical Operating Profit incomplete.

The current implementation should be treated as a staged management-tracking build, not certified accounting software or a complete ledger system.
