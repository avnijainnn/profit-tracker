# Design notes and implementation boundaries

## Purpose

Support Tanvi's month-end review from statements and cash notes without requiring daily input. Keep money movements and physical inventory separate, connected by SKU only where appropriate. Preserve the user's control over how unresolved accounting choices will eventually work.

## Data model

| Record | Meaning | Date behavior |
| --- | --- | --- |
| Account | A payment/receipt location: bank, card, cash, wallet, or someone else | Reused across all months |
| Category | A persistent expense label | Reused across all months |
| Product | Bag design/variant SKU or thrift SKU | Lifetime identity |
| Entry | One income, expense, withdrawal, or transfer record | `date` is actual event date; `created_at` is entry timestamp |
| StockMovement | One receipt/batch, sale, saleable return, removal, or adjustment | Actual receipt/sales date; never creates an Entry |
| ChangeLog | App-created history of financial edits/voids and stock changes | Timestamp when the change was recorded |
| Submission | Committed result and payload fingerprint for one submitted form | Retained to make retries safe |
| MonthReview | Close state, revision and snapshot of the reviewed month | One row per workspace/month; prior snapshots in ChangeLog |
| StockReversal | Reasoned cancellation referencing the preserved original movement | Corrects original effective month; records correction timestamp |
| RecoveryThrottle | Hashed email identifier and password-reset rate window | Up to three sends per hour per identifier |

Accounts, categories, products, entries, and change logs belong to a user. Stock belongs to a product. All ordinary views and related-field choices are scoped to the signed-in user. Superuser admin access is privileged, not another tenant-scoped interface. These workspaces are separate, not a shared multi-staff business ledger.

## Financial formulas

For active records whose actual dates fall in the selected month:

```text
net receipts = sum(income amounts)
recorded spending = sum(expense amounts)
result before withdrawals = net receipts − recorded spending
result after withdrawals = result before withdrawals − owner withdrawals
```

Transfers, repayments, and voided records contribute zero. SKU-linked spending is a filtered view of the same expense records, never a duplicate table of costs.

This hybrid manual spending view is intentionally not named accounting profit or cash balance: advances, card purchases, noncash wallet spending, and third-party payments can be included. An accountant-reviewed financial reporting model is a later decision.

## Worked cross-month case

1. August 22: create Aqua Babe before any stock exists; record a ₹35,000 manufacturing expense linked to that SKU.
2. September 3: receive 50 units under a delivery label. Stock becomes 50. September manufacturing spending remains zero unless another payment is recorded.
3. September 4: record ₹1,600 inbound shipping linked to Aqua Babe.
4. September 30: record 12 units sold for Aqua Babe. Available stock becomes 38. Financial receipts remain whatever was entered from statements.

The product's lifetime recorded spend is ₹36,600, split August ₹35,000 and September ₹1,600. This does **not** imply a verified unit cost: the payments may cover multiple batches, incomplete deliveries, wastage, or other unallocated costs.

## Implementation layers

- Models define the schema and cross-workspace relationship validation.
- Forms scope selectable objects and validate actual dates, references, categories, and payer details.
- Services save audited financial records and validate the stock timeline inside a transaction.
- Domain functions calculate money and stock rules without Django, allowing a small offline test suite.
- Views coordinate form submissions and scope every object lookup to its owner.
- Templates and CSS are intentionally separate and editable with no Node build step.

## MVP choices, explicitly provisional

- Show withdrawals separately; do not decide founder salary accounting for Tanvi.
- Highlight third-party-paid spending and count it on the original payment date, with a visible note that this needs confirmation.
- Capture sold units, not SKU sales money. Never add SKU revenue to already-recorded receipts.
- Record batch labels, not payment-to-batch matching.
- Offer basic saleable-return and damage-removal movements; defer full return and damaged-stock workflows.
- Keep all month records in one database and filter by date. No monthly duplicated sheets/tables.
- Financial corrections are revision-checked edits/voids with mandatory reasons. Stock mistakes are reversed, preserving the original and excluding it from quantity and sales statistics.
- Completed months can be closed and reopened with a reason. Financial mutations check both original and destination months; stock mutations also check every affected later closed month.
- Workspace row locking serializes financial/stock/month mutations on PostgreSQL. Submission receipts make money/stock retries idempotent; active statement references also have a database uniqueness constraint.

## Known operational limits

- SQLite is a local demo convenience, not the production concurrency model. PostgreSQL is required for hosted deployment and its row-locking behavior has dedicated CI tests.
- Request tokens prevent repeats of the same financial/stock form. Distinct forms with no statement reference still require manual real-world duplicate review.
- No bank/account balances, no automatically calculated amount owed to third parties, no formal double-entry ledger.
- Stock validation requires earlier opening/received stock. Per-SKU monthly sold totals are recorded as one dated movement; this cannot reconstruct daily inventory timing within that month.
- Use reversal to correct an erroneous sale/receipt; generic stock-count adjustments intentionally do not change historical sold-unit counts.
- No payment allocations across SKUs/batches and no FIFO/weighted-average cost calculation.
- No bank import, matching, attachments, automated settlement synchronization, or background jobs.
- Account/category labels cannot be edited through the current UI. Starter labels plus custom additions are the supported setup flow.
- Audit history logs application changes, not raw database edits. Site administrators can inspect all workspaces.
- The app is not deployed and has not completed security review or browser QA. See VERIFICATION.md for the exact checks run. A dependency lockfile is a deliberate release prerequisite, not an already completed deliverable.

## Next iteration after local review

1. Run the included suite and manually exercise the fictional demo on Avni's machine.
2. Have Tanvi review one completed month against her actual workflow, using fictional figures first.
3. Confirm the six outstanding questions before implementing SKU financial profit, allocations, reimbursements, and a full returns policy.
4. Add bank CSV import and review only after the manual records and classification rules are accepted.
5. Follow DEPLOYMENT.md to finish dependency locking, PostgreSQL CI, staging, actual SMTP/2FA checks, backup restoration, and production release.
