# Open Decisions

**Update (2026-09-29):** The technical design supplied by the user resolves the primary-result question as two separate reports (Cash Profit and Operating Profit), chooses units-sold-only product tracking for v1, and selects FIFO landed-cost allocation with inventory costs capitalized until sale. The implementation assumptions and remaining qualifications are in [`technical-design-progress.md`](technical-design-progress.md). Advance-to-delivery matching, salary treatment, borrowing, returns, shared access, and opening/closing payment balances remain unresolved or unimplemented.

Unresolved business questions that affect what Profit Studio builds or displays. **No answer is assumed
here.** Resolve a decision before enabling any calculation that depends on it. Record the answer, who
approved it, and the date.

Status values: **Blocks V1** (cannot ship the affected piece without an answer) · **Affects V1 display**
(ship the rest, keep this hidden) · **Later** (belongs to a deferred module) · **Resolved**.

| ID | Question | Affects | Status |
| --- | --- | --- | --- |
| OD-01 | Does the primary result mean net receipts − expenses, or a separate accounting margin? | DASH03 | Affects V1 display |
| OD-02 | Units only, or SKU sales amounts too? How do they reconcile with settlements? | BAG03, IN05 | **Blocks V1 display** (sales figures currently visible) |
| OD-03 | Can deliveries be matched to advances? Which cost-allocation method? | BAG03 | Later |
| OD-04 | Saleable vs damaged returns, including after a refund? | INV04 | Affects V1 display |
| OD-05 | Is Tanvi's salary an expense or a withdrawal? | EXP07, DASH03 | Affects V1 display |
| OD-06 | Do third-party expenses count on the original payment date? Are reimbursement balances needed? | EXP06–07 | Affects V1 display (provisional rule in place) |
| OD-07 | Complete default category names — are 13 actually required? Also rename/archive policy. | EXP02–04 | **Blocks V1 seed/UI** |
| OD-08 | What is "third-face stock clearance"? What does "bags made" measure? | INV03–04 | Later |
| OD-09 | Is resale owned thrift stock or commission selling? Who is paid, what base/method? | RES01–03 | Later |
| OD-10 | For resale, who bears deductions/refunds, when is payout due, what appears in monthly totals? | RES04–06 | Later |
| OD-11 | Is bank tally manual totals, or manual totals **plus** opening/closing and line matching? | BANK01–05 | Affects V1 scope |
| OD-12 | Individual or aggregate receipts? Does the business receive money through CRED/gift cards? | IN01, IN05 | Affects V1 display |
| OD-13 | Who needs access, how much history, and what backup loss/restoration window is acceptable? | SEC01, OPS01 | Operational |

---

## OD-01 — Meaning of the primary result

**Question.** Does the main figure mean *net receipts minus recorded expenses*, or does Tanvi need a
separate accounting-style margin?

**Why it matters.** It decides the dashboard headline and the report footnote. The current code computes
`receipts − expenses` and explicitly does **not** call it profit.

**Options.** (a) Keep the management-tracking figure and label it "monthly result" (current). (b) Add a
separate accounting margin later, with approval of revenue-recognition and cost rules.

**Current provisional behaviour.** `domain.py::statement_summary` → `result = income − expense`;
after-withdrawal shown separately. No accounting margin anywhere.

**Recommendation (scope, not policy).** Keep (a) for V1. Do not build (b) until OD-02/03 are answered.

---

## OD-02 — Units only, or SKU sales amounts? *(blocks V1 display)*

**Question.** Will Tanvi enter units sold only, or also a **sales amount** per SKU? If amounts are
entered, how do they reconcile with the net settlements already recorded as receipts?

**Why it matters.** A conditional field (`StockMovement.sales_amount`) already exists in the database
(migration 0004) and is shown on the product list, product detail and monthly report. That exposes an
unapproved concept and risks being read as revenue.

**Current provisional behaviour.** The field can be saved. It is **never** added to Money In (verified by
`test_sku_sales_total_is_separate_from_money_in`). It is not used for any margin. It is displayed as
"sales total noted".

**Options.** (a) Hide the field and all "sales noted" figures in V1 (keep the stored data). (b) Keep it
visible but clearly labelled as a non-financial breakdown. (c) Remove the field entirely (requires a
migration and a data decision — **not** recommended without an answer).

**Recommendation.** **(a)** for V1: hide, keep data, revisit once Tanvi confirms. This removes the
largest source of confusion without deleting anything.

---

## OD-03 — Delivery-to-advance matching and cost allocation

**Question.** Can an advance payment be matched to a specific delivery/batch? If a margin is eventually
required, which costing method applies (batch, weighted average, other) and how are shared or missing
costs handled?

**Why it matters.** True SKU margin cannot be derived from units sold and lifetime spend.

**Current provisional behaviour.** Payments link to a **product**, not a batch. No allocation, no FIFO,
no weighted average. Batch labels are descriptive only.

**Recommendation.** Keep product-level linking. Decide the costing method only if Tanvi actually needs a
margin.

---

## OD-04 — Returns: saleable vs damaged

**Question.** When a bag is returned, is it saleable (goes back into available stock) or damaged (does
not)? What happens if there was already a refund?

**Why it matters.** A damaged return that never re-enters stock must **not** remove another available
unit. The current model has separate `returned` and `damaged` movements but no dedicated damaged-return
workflow, so an operator could double-remove.

**Current provisional behaviour.** `returned` adds stock; `damaged` removes stock; both are explicit
operator choices. No automatic rule.

**Recommendation.** Keep the manual movements for V1. Ask Tanvi whether returned bags ever become
saleable before building a returns register.

---

## OD-05 — Tanvi's salary

**Question.** Is Tanvi's salary an **expense** (reduces the monthly result) or a **withdrawal** (shown
separately)?

**Why it matters.** It changes what the main result means.

**Current provisional behaviour.** Owner withdrawals are stored as `Entry.Kind.WITHDRAWAL`, excluded
from the result, and shown as a secondary after-withdrawal figure. Salary is not special-cased.

**Recommendation.** Keep withdrawals separate until Tanvi decides. Do not silently move salary into
expenses.

---

## OD-06 — Third-party expenses

**Question.** Do expenses paid by someone else count on the **original payment date**? Does Tanvi need
to track outstanding reimbursement balances?

**Why it matters.** Wrong treatment duplicates an expense or hides the reimbursement.

**Current provisional behaviour.** The expense counts once on its payment date and is highlighted as
"paid by someone else". The later repayment is a **transfer** and is excluded from expenses. **No**
amount-owed calculation exists (and none is claimed).

**Recommendation.** Keep the provisional rule. Only build balance tracking if Tanvi explicitly needs it.

---

## OD-07 — Default categories and rename/archive policy *(blocks V1 seed/UI)*

**Question.** What are the complete default category names, and are 13 genuinely required? Separately,
should categories/accounts be renameable and archivable without deleting history — and if a label
changes, do historical reports show the original or the current label?

**Why it matters.** The app currently seeds **9** categories. Inventing four more to reach 13 would put
unapproved labels in Tanvi's workspace.

**Current 9 seeded categories** (from `services.py::setup_defaults`) —
**Manufacturing, Packaging material, Shipping & transit, Warehouse, Samples, Tech & subscriptions,
Staff salaries, General, Refund.**
Seeded payment accounts (7) — **Bank 1, Bank 2, Cash, Credit card, CRED wallet, Gift card,
Paid by someone else.**

**Current provisional behaviour.** Users can add unlimited custom categories/accounts. There is **no**
rename or archive UI; labels are effectively fixed once created. The database constraint is
case-sensitive while the form checks case-insensitively.

**Recommendation.** (1) Do **not** change the seed list until Tanvi supplies the real names. (2) Treat
rename+archive as a later feature unless she asks for it. (3) Fix the case-sensitivity mismatch in V1
(see `docs/v1-plan.md`).

---

## OD-08 — "Third-face stock clearance" and "bags made"

**Question.** What exactly does *third-face stock clearance* mean (discount clearance, thrift selling,
third-party selling, something else)? Does *bags made* mean ordered, production completed, or physically
received?

**Why it matters.** An advance or an order is **not** available stock. Clearance workflow design depends
entirely on the answer.

**Current provisional behaviour.** Neither concept is implemented. Stock changes only via explicit dated
movements.

**Recommendation.** Leave both undefined in code until Tanvi explains them. If clearance turns out to be
discounted selling, stock should decrease **once** and the actual price recorded only under the approved
sales workflow.

---

## OD-09 — Resale ownership and commission

**Question.** Does Tanvi **buy and own** thrift inventory, or **sell someone else's item on commission**?
If commission: who is paid, is the rate a percentage or a fixed INR amount, and what is the commission
base?

**Why it matters.** The two models have completely different ownership and payment handling.

**Current provisional behaviour.** Resale is **not implemented**. Do not enable any resale totals or
payout actions.

**Recommendation.** Confirm ownership first. Only then design commission snapshots (percentage/fixed),
seller entitlement and payout records.

---

## OD-10 — Resale refunds, deductions and payout timing

**Question.** For commission resale: who bears shipping and other deductions, is commission refundable,
how do partial refunds affect seller entitlement, what happens after a seller has already been paid, and
when does a payout become due?

**Why it matters.** These rules determine entitlement and payout status.

**Current provisional behaviour.** Not implemented.

**Recommendation.** Decide together with OD-09; do not invent deductions.

---

## OD-11 — Bank tally scope

**Question.** Is bank tally a **manual statement-total comparison** (what exists today) or does it need
**opening/closing balances** and **transaction-level matching**? Which accounts, formats and split
matches are involved? Is CSV import required?

**Why it matters.** BANK03 (opening + credits − debits = closing) is **not implemented** — `BankTally`
stores only statement credits/debits. Adding opening/closing is a small change; line matching is a large
module.

**Current provisional behaviour.** Manual monthly totals per bank account, compared against recorded
activity. Transfers count on both sides. No balances, no matching, no import.

**Options.** (a) Keep manual totals. (b) Add opening/closing balance fields (small). (c) Add line
matching + CSV import (large, later).

**Recommendation.** (b) if Tanvi wants the arithmetic check; defer (c).

---

## OD-12 — Receipt granularity and CRED/gift-card revenue

**Question.** Will receipts be recorded **individually**, or as **monthly aggregates** per source? Does
the business actually receive **income** through CRED or gift cards?

**Why it matters.** Aggregate-only receipts cannot support statement-line matching without allocation,
and could duplicate individually entered receipts.

**Current provisional behaviour.** Individual receipts only. CRED and gift card exist as **spending
accounts**, not revenue sources.

**Recommendation.** Keep individual receipts. Do not add CRED/gift card as revenue unless Tanvi confirms
she receives business income through them.

---

## OD-13 — Access, history and recovery window

**Question.** Who needs access to the workspace, how much history must be retained, and what data loss /
restoration window is acceptable?

**Why it matters.** It sets backup frequency, retention and whether shared roles are ever needed.

**Current provisional behaviour.** One ordinary user per workspace with isolated records; a separate
privileged maintenance admin. An encrypted backup helper exists but is **not scheduled** and has **not**
been restore-tested.

**Recommendation.** Keep the single-user model for V1. Agree a backup frequency and a restore drill
before real-data reliance.

---

## Answers

| ID | Answer | Approved by | Date |
| --- | --- | --- | --- |
| OD-01 |  |  |  |
| OD-02 |  |  |  |
| OD-03 |  |  |  |
| OD-04 |  |  |  |
| OD-05 |  |  |  |
| OD-06 |  |  |  |
| OD-07 |  |  |  |
| OD-08 |  |  |  |
| OD-09 |  |  |  |
| OD-10 |  |  |  |
| OD-11 |  |  |  |
| OD-12 |  |  |  |
| OD-13 |  |  |  |
