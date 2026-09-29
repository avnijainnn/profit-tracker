# Profit Studio — Consolidated Requirements

**Status:** Consolidated review specification, derived from `Profit_Tracker_Requirements_Specification.docx`
(v1.0, 26 Sep 2026), the `Profit_Tracker_Design_Document.docx` (v2.0, 26 Sep 2026), the existing
project documentation, and a read-only inspection of the current codebase.

**This document describes what the system must do. It is not a statement that a requirement is approved
or implemented.** Implementation status for each requirement is recorded separately in
`docs/requirements-review.md`.

## How to read this document

Every requirement carries one of three **business statuses**:

| Status | Meaning |
| --- | --- |
| **Confirmed** | Supported by Tanvi's transcribed answers or the agreed V1 design. |
| **Proposed** | A recommended requirement or UX improvement that still needs validation. |
| **Decision needed** | A policy or scope question is unresolved. Dependent calculations must not be built or assumed. |

A feature appearing here does **not** mean Tanvi approved it or that it belongs in V1.

## 1. Business context

Tanvi sells bags and thrift items. She reviews the **previous month on the first of the next month**
and does not want a daily-entry workflow. Her month-end review draws on:

- Two bank statements
- Credit-card purchases
- CRED wallet expenditure
- Gift-card expenditure
- Cash notes
- Business expenses paid by someone else

She needs to know, for a chosen month:

1. How much money came in?
2. How much was spent?
3. What is the difference (the monthly result)?
4. How many bags and thrift items sold?
5. How much stock remains?
6. How much has been paid towards each bag design?

The existing interface felt too complicated. The solution must make month-end work **easier without
weakening data correctness**.

## 2. Core financial rules (Confirmed)

These rules are authoritative and apply to every module:

1. **One real payment → one authoritative financial record.** The same expense may appear in a monthly
   report and under a product, but those are two *views* of one record.
2. **Actual event dates control the month.** Receipt date for money in; expense/payment date for
   spending (subject to the card and third-party rules below); arrival date for stock; sales date or an
   explicit month-end total date for units sold. Entering September records in October must not move
   them into October.
3. **Monthly result = money received − recorded expenses.** It is a management tracking figure. It may
   include advances and expenses paid by card or by other people. It is **not** accounting profit, a
   bank balance, or a complete cash-flow statement.
4. **True SKU margin is not derivable** from units sold or lifetime spend alone. It requires additional
   sales and cost-allocation information (see §6).
5. **Own-account transfers, wallet top-ups, credit-card bill repayments and reimbursements of
   previously recorded expenses must not create a second expense.**
6. **Do not classify every bank debit as an expense or every bank credit as business revenue.**
   Classification is the operator's decision.

## 3. Dashboard and monthly result

### DASH01 — Monthly overview · Confirmed (core), Proposed (presentation)
- Show a selected calendar month, defaulting to the **previous month in Asia/Kolkata**.
- Show **money received**, **recorded expenses**, and **monthly result**.
- Changing the selected reporting month must **not** change any stored transaction date.

### DASH02 — Useful detail without duplication · Proposed
- Show compact **revenue-source** and **expense-category** breakdowns.
- Show **bags sold** and **thrift units sold** for the month.
- Selecting a total should open its underlying records.
- Clearly distinguish: all-time vs current stock vs selected-month figures.
- Do **not** repeat the same full transaction list in multiple sections of one page.

### DASH03 — Meaning of profit · Decision needed
- For the confirmed statement-based workflow, display **Monthly result = receipts − recorded
  expenses**. Include paid advances and the chosen card/third-party expense policy.
- Never label it accounting profit or bank balance.
- A true sales margin requires the revenue and inventory-cost rules to be approved first (§6).

### Withdrawals · Confirmed
- Owner withdrawals remain **separately identifiable**.
- Show a **secondary after-withdrawal result** only when withdrawals exist.
- Whether Tanvi's salary is an expense or a withdrawal is **unresolved** (see OD-05).

## 4. Money In

### IN01 — Revenue sources · Confirmed
Support four revenue sources: **Razorpay settlements**, **occasional COD settlements**,
**manual UPI sales**, and **cash sales**.
- CRED and gift cards were mentioned as *spending methods*. Do **not** seed them as revenue sources
  unless Tanvi confirms she receives business income through them.

### IN02 — Receipt entry · Confirmed (core), Proposed (fields)
- Required: actual receipt date, positive INR amount, revenue **source**, receiving **account**.
- Optional: statement reference, notes.
- **Source ≠ receiving account.** (Example: Razorpay is the source; Bank 1 is where money arrived.)
- Multiple same-source entries are allowed and their monthly total accumulates automatically.

### IN03 — Net settlement treatment · Confirmed
- Enter the amount **actually received** from the statement (**net**).
- If gateway fees or refunds were already deducted before settlement, do **not** deduct them again.
- A separately paid refund is recorded as an expense.
- Cash receipts must be included even though they do not appear on a bank statement.

### IN04 — Repeated entry · Proposed
- **Save & add another** may retain date, source and receiving account after user review, but must
  **clear amount, reference and record-specific notes**.
- Each new entry needs a **fresh submission token**.
- Validation errors must retain the unfinished entry.
- Saving the same submission twice must create **one** record.

### IN05 — Receipt granularity · Decision needed
- Individual receipts are **Confirmed**.
- Monthly aggregate receipt entry is **not confirmed**. If proposed, it must clarify how it avoids
  duplicating individual receipts and how it affects statement matching. Aggregate-only entries cannot
  support exact statement-line matching without allocation.

## 5. Expenses and categories

### EXP01 — Expense entry · Confirmed (core), Proposed (fields)
- Show **actual payment date**, **amount**, **category**, **Paid using**.
- Payment account/method labels to support initially: **Bank 1, Bank 2, Cash, Credit card,
  CRED wallet, Gift card, Paid by someone else**.
- Optional: product link, reference, notes.
- Show **and require** *Who paid* **only** when someone else paid. Validate on the server as well.

### EXP02 — Reusable custom categories · Confirmed
- Allow user-created categories with **no fixed business limit of 13**.
- Save once; reuse across months. V1 needs **main categories only** (no subcategories).
- Allow creating a category **inside the expense form** without losing the unfinished entry; save it
  for future months and select it immediately. Consider the same behavior for payment accounts.
- Handle duplicate names so near-identical defaults are not created.

### EXP03 — Default category list · Decision needed
- The app contains **9 default categories** (listed in `docs/requirements-review.md`). Keep its
  existing categories and records while reviewing the names.
- The complete **13-name list has not been supplied.** Obtain it before changing seed data; do **not**
  invent names just to reach 13.

### EXP04 — Category/account maintenance · Proposed
- Allow **renaming and archiving** categories and accounts without deleting historical records.
- Archived choices remain visible on old records and cannot be selected for new entries by default.
- Preserve change history.
- Whether historical reports use **original or current labels** is a decision (OD-07).

### EXP05 — One expense in multiple views · Confirmed
- A product link makes the same payment visible in monthly expenses **and** the product's history.
- Opening **Add expense** from a product **preselects that product**.
- Editing or voiding it changes both views consistently.
- A stock receipt never creates a second expense automatically.

### EXP06 — Transfers and repayment · Proposed (needs policy validation)
- Own-account transfers, wallet top-ups, credit-card bill repayments and repayments of previously
  recorded third-party expenses must **not** become a second business expense.
- Keep them accessible as **non-expense movements** when tracking requires them.
- Account movements and business classification are **separate concepts**.

### EXP07 — Third-party and owner payments · Decision needed
- Provisional behavior: count the expense when the other person pays; exclude Tanvi's later repayment
  from expenses.
- Do **not** imply the app calculates an amount owed.
- Retain owner withdrawals separately; show after-withdrawal result when present.
- Confirm Tanvi's **salary treatment** before changing the main result.

### EXP08 — Corrections · Proposed
- Allow permitted edits to open periods; preserve who changed what and when.
- Use a reasoned **void or reversal** instead of silent deletion.
- Require **reopening** before changing a closed period.
- Preserve old records and existing user data when simplifying the interface.
## 6. Bags and inventory

### BAG01 — Product records · Confirmed (core), Proposed (fields)
- Store: unique **SKU** within the workspace, **name**, **type (bag or thrift)**, optional notes.
- A product may exist **before stock arrives**.
- Product views show: current available stock, selected-month units sold, selected-month linked
  spend, lifetime linked spend, payment history, stock history.
- **Separate current stock from historical month-end stock.**

### BAG02 — Payments across months · Confirmed
Validating example:

| Event | Monthly effect | Product effect |
| --- | --- | --- |
| September: pay ₹35,000 advance for Aqua Babe | September expense ₹35,000 | Lifetime spend ₹35,000; stock 0 |
| October: receive 20 Aqua Babe bags | **No** financial expense | Stock 20 |
| October: record 3 units sold | October units sold +3; **no** automatic revenue | Available stock 17 |

- Each payment keeps its own actual date. A later payment must not rewrite an earlier month.

### BAG03 — SKU profit · Decision needed (do not calculate yet)
Do not calculate SKU profit until all of the following are agreed:
- Whether Tanvi enters **sales amounts** at all
- Whether amounts are **gross or net** of discounts/refunds
- Which **date** controls the sales report
- How **payments relate to deliveries**
- How **costs are allocated** to sold units
- Whether **batch costing, weighted cost or another method** applies
- How **shared costs and missing costs** are handled
- How **SKU sales relate to bank settlements**

Rules while undecided:
- Never add SKU sales amounts to settlement receipts as if they were additional revenue.
- Do not subtract all lifetime product spending from one month's sales and call it that month's profit.
- Show product **spending** and **units sold**; do not claim a margin.

### INV01 — Stock events · Confirmed (core), Proposed (actions)
Stock events to support: **receipt**, **sale**, **opening stock**, **saleable return**,
**damaged-stock removal**, **positive and negative adjustments**, and **reversal of an erroneous event**.
- Date and quantity required; delivery label optional (receipts only).
- **Separate primary actions:** Add expense, Receive stock, Record units sold.
- Do **not** show delivery/batch fields by default when entering sales.

### INV02 — Stock calculation and validation · Proposed
```
available = opening stock
          + receipts
          + saleable returns
          + positive adjustments
          − units sold
          − damaged stock removed
          − negative adjustments
          (excluding reversed mistakes)
```
- Validate the **whole chronological history**; reject negative availability, including backdated changes.
- Record a correction separately from a genuine customer return.

### INV03 — "Bags made" and monthly sales totals · Decision needed
- Clarify whether **Bags made** means *ordered*, *production completed*, or *physically received*.
  An advance payment is **not** stock.
- Monthly units-sold totals may be dated explicitly to month-end, but must not duplicate daily sales;
  repeated entry needs clear **add-versus-correct** behavior and must preserve stock validation.

### INV04 — Returns and stock clearance · Decision needed
- Ask case by case whether a returned bag is **saleable** or **damaged**.
- A damaged return that never re-enters available stock must **not** remove another available unit.
- **"Third-face stock clearance" is undefined.** Determine whether it means discount clearance, thrift
  sales, third-party selling, or something else before creating the workflow.
- *If* clearance later means discounted selling: tag the sale as clearance, record the actual price if
  SKU sales amounts are enabled, and **reduce stock once**. A discount is not a second physical movement.

## 7. Resale proposal — Decision needed (do not enable)

Tanvi has **not confirmed** that resale is part of her workflow. First determine whether she
**buys and owns** thrift inventory or **sells someone else's item on commission**. These require
different ownership and payment treatment.

If commission-based, the proposed (unconfirmed) requirements are:
- **RES01** Identify the item owner / payout recipient. If Tanvi owns the item, use the owned-inventory
  workflow instead of a commission payout.
- **RES02** One commission method per sale: **percentage** or **fixed INR**. Store the agreed value and
  calculated commission as a **sale snapshot**; changing a default must not change historical sales.
  Validate percentage 0–100; prevent negative payout. Define the **commission base**.
- **RES03** Record sale date, actual customer-payment date and each seller-payout date separately;
  selling price, discounts/refunds, commission base/method/amount, seller entitlement, received amount,
  payout amounts, accounts and references.
- **RES04** Derive **unpaid / partly paid / paid** from actual payout records. Prevent duplicate payouts
  and unexplained overpayments. Never mark money paid merely because the sale occurred.
- **RES05** Agree who pays shipping, whether commission is refundable, how partial refunds affect
  entitlement, what happens after the seller has been paid, and when payout becomes due.
- **RES06** If approved, link a resale receipt to its existing financial receipt and a payout to its
  existing account movement. Do not double-count. Dashboard treatment of gross customer collections vs
  seller payouts vs commission earned needs an explicit decision.

*Illustrative only:* ₹2,000 price, 20% commission → ₹400 commission, ₹1,600 entitlement; a ₹600 payout
leaves ₹1,000 outstanding. This is an example, not an approved policy.

**Release condition:** do not activate resale totals or payout actions until ownership, commission base,
refund rules, payout timing and dashboard presentation are approved.

## 8. Monthly reports

### REP01 — Monthly reporting · Confirmed (visibility), Proposed (reports)
- Historical monthly receipts, expenses and result; source and category totals; product spending;
  units sold; drill-down to source records.
- A **clearly labeled month-to-month comparison**.
- All reports use the **same underlying records and rules** as the dashboard.

### REP02 — Export and close · Proposed
- Export monthly financial **details** and a **summary** (date, source/category, account, amount,
  relevant SKU links).
- **State whether export respects filters or includes the whole month.**
- Protect spreadsheet exports against **formula injection**.
- Allow **optional** review/close, with **reopening reason** and a historical closure snapshot.

## 9. Bank Tally — Decision needed (scope), Proposed (implementation)

Bank tally is **separate from calculating the monthly result**. It is an optional reconciliation
capability, not evidence that the monthly result equals the bank balance.

First clarify:
- Which accounts are included
- Manual statement-total comparison vs transaction-level matching
- Whether CSV import is needed
- How split and grouped matches are handled

If approved:
- **BANK02** Represent actual debits and credits per reconciled account, including transfers, card
  repayments, owner movements and seller payouts. Link movements to business records **without turning
  every debit into an expense or every credit into revenue**.
- **BANK03** Per account and period, record **opening balance, total credits, total debits, closing
  balance**. Calculate `expected closing = opening + credits − debits` and compare with recorded
  movements. Show differences and unresolved items.
- **BANK04** Match statement lines by account, date, amount and reference; support explicit **split or
  grouped** matches; flag duplicates, missing entries, personal/unclassified movements and timing
  differences. Matching status must **never** alter an expense date or create a balancing expense.
- **BANK05** Start with manual comparison unless CSV import is approved. If import is added, require
  **preview, field mapping, duplicate-import checks and user confirmation**. Bank credentials,
  automated feeds and PDF extraction are outside baseline scope.

**Zero net difference alone does not prove every statement line is reconciled. Never create an
artificial expense just to force a match.**

*Example:* a friend pays a ₹5,000 business expense in September; Tanvi reimburses in October. September
has the expense; October has the bank debit with **no** second expense. Bank tally must explain this
difference rather than force either month to equal the bank movement.

## 10. Simple interface

### UX01 — Information structure · Proposed
- Primary navigation: **Monthly tracker**, **Bags and stock**, **Settings**.
- Dashboard, Money In, Expenses and Monthly Reports are **views within** these destinations. Nine
  capabilities do not require nine primary menu items.
- Add optional resale/reconciliation destinations only after validation.
- Move login security into **Settings or the profile menu**.
- Make history available through relevant records or secondary links.

### UX02 — Forms and correction flow · Proposed
- Clear labels; inline creation of categories/accounts; optional details under a disclosure.
- Context-aware product selection.
- Preserve values after validation errors.
- Show the actual selected date when it falls outside the reviewing month.
- Return to the relevant list/product after saving.
- Confirm destructive-looking actions while preserving historical records.

### UX03 — Accessible mobile use · Proposed
- Support common phone and desktop widths without clipped totals or inaccessible controls.
- Keyboard navigation, visible focus, field labels, readable contrast, errors associated with fields.
- Do not rely on colour alone. Show useful empty states and compact help.
- **Keep internal development notes out of client screens.**
- Replace repeated banners with short hints and expandable help.

## 11. Persistence, integrity and security

### DATA01 — Cross-device persistence · Proposed (essential)
- Save records to the **authenticated hosted database**; a confirmed save must be visible on another
  device, and must survive refresh, logout and redeployment.
- Browser local storage and ephemeral server files must **not** be the authoritative financial store.

### DATA02 — Reliable saving and concurrency · Proposed (essential)
- Atomic writes; exact decimal INR amounts; integer stock quantities.
- Retrying a submitted operation returns **one** committed result.
- Concurrent edits cannot corrupt totals; outdated edits show a **conflict** instead of overwriting.
- A network failure must **not** display a false success.

### SEC01 — Access and recovery · Proposed (essential)
- Require login; scope reads/writes/exports to the permitted workspace.
- Protect hosted access with **two-factor authentication**.
- Keep privileged maintenance access **separate** from Tanvi's ordinary account.
- Verify password recovery, backup codes, CSRF protection and login throttling.
- Shared staff roles need separate approval.

### OPS01 — Backup and operational recovery · Proposed (essential)
- Maintain protected database backups and verify **restoration into an isolated database**.
- Cloud saving is **not** a backup guarantee.
- Agree acceptable **data loss and restoration time** before relying on the app.
- Keep secrets out of source and logs; configure a way to notice failed saves or outages.

## 12. Technology and ownership · Confirmed direction

- Keep the **editable Django project**: Django templates + CSS + small amounts of JavaScript.
- **SQLite** for local development; **PostgreSQL** for hosted data.
- Django handles authentication and authorization; Supabase is the hosted PostgreSQL provider, **not**
  a replacement authentication system.
- Planned trial hosting: **Render Free web service + Supabase Free PostgreSQL**; validate current plan
  constraints and email delivery at deployment time.
- **No React**, no Supabase Auth, no rebuild in another framework without specific agreement.
- Avni maintains the code; Tanvi validates the business workflow.

## 13. Exclusions (unless separately approved)

Automated bank feeds, website/order synchronization, PDF statement extraction, payment execution,
GST/tax filing, payroll, invoicing, multi-currency accounting and agency-management features.

Wallet balances, borrowing balances, inventory valuation, FIFO and true SKU margin are **not promised**
by the baseline tracker. Receipt attachments and bulk imports may be considered later.

## 14. Acceptance scenarios

One cumulative example unless stated otherwise:

| # | Scenario | Expected |
| --- | --- | --- |
| A01 | Three Razorpay receipts ₹10,000 + ₹15,000 + ₹5,000 | Receipts and Razorpay subtotal = ₹30,000 |
| A02 | ₹35,000 advance + ₹5,000 delivery expense | Expenses ₹40,000; result −₹10,000 |
| A03 | Correct delivery to ₹4,500 | Expenses ₹39,500; result −₹9,500; history retained |
| A04 | Receive 20 units, sell 3 | Available 17; no new financial entry; earlier payment stays put |
| A05 | Add expense from a bag; create category inline | Bag preselected; unfinished values retained; reusable next month |
| A06 | Retry a POST; edit from an outdated tab | One entry; stale edit rejected |
| A07 | Top-up, card repayment, reimbursement | No duplicated purchase expense |
| A08 | Closed-month edit; another user's records | Blocked; reopening logged; isolation holds |
| A09 | Device change, redeploy, failed save, backup restore | Persists; no false success; restore works |
| A10 *(conditional)* | ₹2,000 sale at 20% → ₹400 / ₹1,600; ₹600 payout | ₹1,000 outstanding; no duplicated receipt |
| A11 *(conditional)* | Opening ₹10,000 + credits ₹3,000 − debits ₹2,000 | Closing ₹11,000; unmatched movements still visible |
| A12 *(conditional)* | SKU margin with missing sales/cost data | Margin remains unavailable |

Run on fictional data first. A green deployment alone does not satisfy these criteria.

## 15. Decision register (see `docs/open-decisions.md`)

| ID | Question | Affects |
| --- | --- | --- |
| Q01 | Net receipts − expenses, or a separate accounting margin? | DASH03 |
| Q02 | Units only, or SKU sales amounts too? How do they reconcile with settlements? | BAG03, IN05 |
| Q03 | Can deliveries be matched to advances? Which cost-allocation method? | BAG03 |
| Q04 | Saleable vs damaged returns, including after a refund? | INV04 |
| Q05 | Is Tanvi's salary an expense or a withdrawal? | EXP07, DASH03 |
| Q06 | Do third-party expenses count on the original payment date? Are reimbursement balances needed? | EXP06–07 |
| Q07 | Complete default category names — are 13 actually required? | EXP02–04 |
| Q08 | What is "third-face stock clearance"? What does "bags made" measure? | INV03–04 |
| Q09 | Is resale owned thrift stock or commission selling? Who is paid, what base/method? | RES01–03 |
| Q10 | For resale, who bears deductions/refunds, when is payout due, what appears in monthly totals? | RES04–06 |
| Q11 | Is bank tally manual totals or line matching? Which accounts/formats/split matches? | BANK01–05 |
| Q12 | Individual or aggregate receipts? Does the business receive money through CRED/gift cards? | IN01, IN05 |
| Q13 | Who needs access, how much history, and what backup loss/restoration window is acceptable? | SEC01, OPS01 |

## 16. Release order

**V1 candidate:** validate and simplify monthly receipts, expenses, categories, product spending,
stock, reports and persistent saving. Retain security and correction controls. Trial with sample data,
then reconcile one historical month before real-data reliance.

**Later candidates:** resale, bank matching, clearance workflows and SKU margin — only after their
decisions are approved. Tag the exact release, review migrations, back up affected data and verify the
deployed behaviour.
