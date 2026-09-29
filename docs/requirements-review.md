> Auth update (29 September 2026): the owner requested email/password-only login. Two-factor authentication has been removed and demo password recovery is disabled. References to 2FA below describe the earlier review.

# Requirements & Implementation Review

**Prepared:** 26 September 2026 · **Scope:** read-only review of the local `profit_tracker` project.
**Author:** engineering partner, for Avni.

This review assesses each requirement in `docs/requirements.md` against the **actual current code**.
The code — not an earlier ZIP or prior conversation — is the source of truth.

---

## A. Method and what was inspected

**Documents read:** `README.md`, `DESIGN_NOTES.md`, `DEPLOYMENT.md`, `VERIFICATION.md`,
`CHANGELOG.md`, `render.yaml`, `.env.example`, `.gitignore`, `build.sh`, `gunicorn.conf.py`,
`requirements*.txt`, `config/settings.py`, `config/test_settings.py`, `config/logging.py`,
`config/urls.py`, and both DOCX files (`Profit_Tracker_Requirements_Specification.docx`,
`Profit_Tracker_Design_Document.docx`).

**Code read:** `tracker/{models,forms,views,services,domain,guards,security,auth_views,admin,urls}.py`,
`tracker/templatetags/tracker_tags.py`, all 16 templates, `static/tracker/app.js`, all 5 migrations,
the management commands, and all 4 test modules.

No `AGENTS.md` exists in the project. No project file was modified during this review; only the four
`docs/` files created by it. The existing local database was read only.

---

## B. Actual current stack (confirmed against the repo)

| Layer | What is actually present | Evidence |
| --- | --- | --- |
| Language / framework | Python 3.12, Django 5.2.x | `requirements.in`, `manage.py`, `render.yaml` |
| UI | Django templates + plain CSS + small vanilla JS (same-origin `fetch` shell navigation) | `templates/`, `static/tracker/app.css`, `app.js` |
| Local DB | SQLite (`db.sqlite3`) | `config/settings.py` |
| Hosted DB | PostgreSQL via `dj-database-url`; refused when missing and `DEBUG=false` | `config/settings.py` |
| Auth | Django email/password auth + `django-axes` lockout | `requirements.in`, `config/settings.py`, `tracker/security.py` |
| Serving | Gunicorn + WhiteNoise; health at `/healthz/` | `gunicorn.conf.py`, `tracker/views.py::health` |
| Hosting | Render **Free web service only** (no DB provisioned); Supabase PostgreSQL supplied externally | `render.yaml`, `DEPLOYMENT.md` |
| Backup | `pg_dump` piped into `age` encryption helper | `scripts/backup_database.py` |
| CI | GitHub Actions: PostgreSQL 16 service, hash-locked deps, `check`, migrations check, tests, `--deploy` check | `.github/workflows/verify.yml` |

**Not present (as documented):** a hash-locked `requirements.lock` (deliberately absent); any deployed
environment; any provisioned Supabase/Render/SMTP resource.

---

## C. Status legend

| Code | Meaning |
| --- | --- |
| **IV** | Implemented and **verified** — exercised by a passing test I actually ran |
| **IU** | Implemented but unverified — code exists; not covered by my executed tests/browser |
| **PI** | Partially implemented — some of the requirement exists; gaps noted |
| **M** | Missing |
| **C** | Conflicting with intended behaviour |

"Verified" below means verified **by a test in this repository that I ran**, not by inspection alone.

---

## D. Dashboard and monthly result

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| DASH01 selected month; default previous month (Asia/Kolkata); totals; month change does not move dates | **IV** | `services.py::chosen_month`; `views.py::dashboard`; `test_workflows.py::test_edit_get_preserves_actual_date` | Default uses `timezone.localdate()`; `TIME_ZONE="Asia/Kolkata"`. |
| DASH01 money in / expenses / monthly result | **IV** | `domain.py::statement_summary`; `services.py::report`; `dashboard.html` | Exact-decimal addition verified in `test_domain.py`. |
| DASH02 revenue-source + category breakdowns | **IU** | `report()` `sources`/`categories`; `dashboard.html` | Rendered; no dedicated assertion. |
| DASH02 bags / thrift units sold | **IV** | `report()` `sold_bags`/`sold_thrift`; `dashboard.html` | Reversal correctness in `test_safeguards.py`. |
| DASH02 select a total to open underlying records | **PI** | Category has a link; **source rows and stock figures have no drill-down** | Gap. |
| DASH02 no duplicated full transaction list | **IV** | Single paginated entries panel with tabs; `test_dashboard_tabs_and_search_filter_monthly_entries` | Good. |
| DASH02 distinguish all-time / current / selected-month | **PI** | Labels exist only on `product_detail.html` | Dashboard figures are all monthly. |
| DASH03 result = receipts − expenses, not labelled profit | **IV** | `statement_summary`; footer + report footnote; `test_domain.py` | Wording is careful. |
| Withdrawals separate; after-withdrawal only when present | **IV** | `statement_summary`; `dashboard.html`; `test_domain.py::test_owner_withdrawal_separate` | Salary-vs-expense pending. |

---

## E. Money In

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| IN01 four sources; CRED/gift card excluded as revenue | **IV** | `models.py::Entry.Source` = razorpay, cod, upi, cash; `EntryForm` income choices | CRED/gift card exist only as *accounts*. |
| IN02 receipt fields (date, positive amount, source, account, optional ref/notes) | **IV** | `models.py::Entry`; `EntryForm` income branch | Labels: "Actual receipt date", "Amount received", "Received in". |
| IN02 source ≠ account | **IV** | Separate `source` and `account`; `Entry.clean` | — |
| IN02 multiple same-source entries accumulate | **IV** | `report()`; `test_workflows.py::test_income_entries_cumulative` | Razorpay subtotal verified. |
| IN03 net-settlement guidance, no double fee/refund, cash included | **IU** | `EntryForm` income `help_text`; `form.html` notice | Guidance only; cash source exists. |
| IN04 Save & add another clears amount/reference/notes; fresh token; errors retain entry; double-save = one record | **IV** | `views.py::entry_form` session prefs; `submission_token`; `guards.py::prior_submission`; `test_save_and_add_another_uses_fresh_amount_and_reference`; `test_same_post_token_returns_single_entry` | **Gap:** retained prefs are `account`+`source` (+`category` for expense); **date is not retained** (spec says "may", so minor). |
| IN05 individual receipts | **IV** | `Entry` per receipt | — |
| IN05 monthly aggregate receipt entry | **M / Decision** | None | Correctly absent pending OD-12. |
---

## F. Expenses and categories

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| EXP01 date, amount, category, Paid using; optional product/reference/notes | **IV** | `forms.py::EntryForm` expense branch | Order: date, amount, category, account, paid_by, product, reference, notes. |
| EXP01 initial account labels | **IV** | `services.py::setup_defaults` creates exactly: Bank 1, Bank 2, Cash, Credit card, CRED wallet, Gift card, Paid by someone else | Kinds: bank, bank, cash, card, wallet, wallet, other. |
| EXP01 "Who paid" shown/required only for Paid by someone else, with server validation | **IV** | `Entry.clean` (requires `paid_by` when `account.kind == other`); `EntryForm.clean` clears it otherwise; `app.js::updatePaidByVisibility`; `test_paid_by_required_and_highlighted` | UI toggle + server rule. |
| EXP02 custom categories, no limit of 13, main categories only | **IV** | `models.py::Category`; `CategoryForm`; `settings.html` | No subcategories. |
| EXP02 inline category/account creation preserving the unfinished entry | **IV** | `views.py::inline_item`, `entry_form` HTML fallback; `form.html`; `test_inline_category_creation_preserves_unfinished_expense` | Rebuilds from `request.POST.dict()` and re-selects the new item. |
| EXP02 duplicate-name handling | **PI** | `CategoryForm.clean_name`/`AccountForm.clean_name` use `name__iexact`; DB constraint `unique_owner_category`/`unique_owner_account` is **case-sensitive** | Form blocks case-insensitive dupes; DB would allow "Packaging"/"packaging" via another path. Minor. |
| EXP03 keep the existing defaults, don't invent 13 | **IV (as data)** | `setup_defaults` seeds exactly: **Manufacturing, Packaging material, Shipping & transit, Warehouse, Samples, Tech & subscriptions, Staff salaries, General, Refund** (9) | 13-name list still missing → OD-07. |
| EXP04 rename/archive categories and accounts; historical labels | **M** | No archive flag, no rename UI (`workspace_settings` only creates) | Proposed; needs a data decision (OD-07). |
| EXP05 one expense, two views; product preselect; consistent edit/void; stock receipt ≠ expense | **IV** | `Entry.product`; `views.py::entry_form` prefill; `entry_snapshot`; `test_product_detail_has_separate_stock_actions_and_prefills_expense`; `test_advance_and_next_month_stock_count_once` | Verified. |
| EXP06 transfers/repayments excluded; accessible as movements | **IV** | `Entry.Kind.TRANSFER`; `statement_summary` ignores transfers; `bank_activity` counts both sides; `test_domain.py::test_transfers_and_repayments_never_count_twice` | Transfer requires an explanatory note. |
| EXP07 third-party counts on payment date; repayment excluded; no amount-owed; withdrawals separate | **IV** | `report()` `third_party`; `dashboard.html`; `test_paid_by_required_and_highlighted` | Provisional policy; no balance tracking (correct). |
| EXP08 reasoned edits/voids, revision checks, closed-period protection | **IV** | `services.py::save_entry`/`void_entry`; `guards.py::require_open_months`; `ChangeLog`; `test_edit_and_void_audited`; `test_stale_editor_cannot_overwrite`; `test_closed_month_blocks_new_entry`; `test_closed_month_blocks_moving_existing_entry_out` | Strong. |

---

## G. Bags and inventory

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| BAG01 unique SKU per workspace, name, bag/thrift, notes | **IV** | `models.py::Product` (`unique_owner_sku`); `ProductForm.clean_sku` uppercases + checks | Type cannot change once stock exists (`views.py::product_form`). |
| BAG01 product may exist before stock | **IV** | `Product` has no stock requirement; `test_advance_and_next_month_stock_count_once` | — |
| BAG01 current stock, month sold, month spend, lifetime spend, payment + stock history | **IV** | `services.py::product_stats`; `product_detail.html` | "Available now" vs "end of `{{month}}`" distinguished. |
| BAG02 cross-month payments; receipt adds stock only | **IV** | `test_advance_and_next_month_stock_count_once` | September advance stays September; September expense ₹0; stock 50. |
| BAG03 SKU profit not calculated | **IV (absent by design)** | No margin computation; `product_stats` returns spend + units only | `sales_amount` is recorded but not used for margin. |
| INV01 stock events: receipt, sale, opening, saleable return, damage, ±adjustment, reversal | **IV** | `models.py::StockMovement.Kind` (received, sold, returned, damaged, adjust_in, adjust_out); `models.py::StockReversal` | All present. |
| INV01 separate Receive stock / Record units sold / Add expense; no batch field on sales | **IV** | `product_detail.html`; `StockForm` pops `batch_name` for `sold`; `test_more_stock_actions_exclude_receive_and_sale` | Verified. |
| INV02 availability formula + chronological negative rejection | **IV** | `domain.py::stock_delta`/`validate_stock_timeline`; `services.py::add_stock`; `test_domain.py`; `test_backdated_stock_cannot_make_past_negative`; `test_backdated_stock_blocked_by_later_closed_month` | Verified incl. backdating into a closed later month. |
| INV02 correction separate from genuine return | **IV** | `reverse_stock` vs `returned`; `test_reversal_restores_stock_and_sales_stats`; `test_cannot_reverse_receipt_used_by_sales` | Verified. |
| INV03 "Bags made" definition; month-end total add-vs-correct | **PI / Decision** | `StockForm` date help text allows a month-end date; `More stock actions` excludes received/sold | No explicit "this corrects last month's total" guard beyond reverse-then-re-enter. OD-08. |
| INV04 saleable vs damaged returns; damaged return never double-removed; "third-face clearance" | **PI / Decision** | Separate `returned` and `damaged` movements; no damaged-return register | Full workflow deferred; OD-04/OD-08. |

---

## H. Monthly reports and Bank Tally

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| REP01 historical receipts/expenses/result; source/category totals; product spend; units sold | **IV** | `views.py::monthly_reports`; `report()`; `test_monthly_report_sums_existing_monthly_results_and_sku_annotations` | Reports reuse `report()` — same rules as dashboard. |
| REP01 month-to-month comparison, labeled | **IV** | `monthly_reports.html` 12-row table + year totals; footnote "not accounting profit" | — |
| REP01 drill-down to source records | **PI** | Month rows link to that month's dashboard; no per-category/source drill-down from the report | Acceptable for V1. |
| REP02 export financial **details** | **IV** | `views.py::export_csv` | — |
| REP02 export **summary** | **M** | Only one CSV endpoint (details) | Gap. |
| REP02 state whether export respects filters | **IV** | `transactions.html` note; `export_csv` ignores `q`/`kind` | Documented accurately. |
| REP02 spreadsheet formula-injection protection | **IV** | `domain.py::safe_csv_cell`; `test_csv_formula_injection`; `test_csv_escapes_formula_notes` | Verified. |
| REP02 optional review/close with reason + snapshot | **IV** | `MonthReview`; `change_month`; `month_review.html`; `test_reopen_requires_current_revision` | Snapshot in `MonthReview.snapshot` + `ChangeLog`. |
| BANK01 manual statement-total comparison per account/period | **IV** | `models.py::BankTally`; `views.py::bank_tally`; `test_bank_tally_compares_month_totals_and_is_replay_safe` | Manual totals only. |
| BANK02 actual credits/debits without reclassifying records | **PI** | `services.py::bank_activity` derives credits/debits from `Entry` rows (transfers on both sides) | A *derived* view, not a stored register; no explicit unclassified/personal movements. |
| BANK03 opening + credits − debits = closing | **M** | `BankTally` stores only `statement_credits`/`statement_debits` — **no opening/closing balance** | Differences *are* shown. Gap vs BANK03. |
| BANK04 line matching, split/grouped, duplicate flags | **M** | None | Deferred; OD-11. |
| BANK05 CSV import with preview/mapping/dedupe | **M** | None | Deferred; OD-11. |

---

## I. Interface, persistence, security, operations, deferred modules

| Req | Status | Evidence / files | Notes |
| --- | --- | --- | --- |
| UX01 three primary destinations; security in profile; secondary actions | **IV** | `base.html` sidebar (Monthly tracker / Bags & stock / Settings) + tools + profile "Security"; `dashboard.html` "More actions" | Resale/bank reconciliation are secondary. |
| UX02 labels, inline creation, optional disclosure, product context, preserve-on-error, contextual return, confirm destructive | **IV** | `fields.html`; `form.html`; `confirm_void.html`; `confirm_stock.html`; workflows tests | Gap: no explicit "date is outside the reviewing month" hint. |
| UX03 responsive, keyboard, focus, labels, non-colour cues, empty states, no dev notes | **IU** | `app.css`, `fields.html` (`role="alert"`), empty states, `sr-only` | **Not browser-verified.** Needs desktop + phone QA. |
| DATA01 cross-device persistence on the hosted DB | **IU** | DB-backed models; server-side sessions | Local SQLite verified; hosted path unverified. |
| DATA02 atomic writes, decimals, idempotent retries, stale-edit conflict, no false success | **IV (SQLite)** / **IU (PostgreSQL)** | `@transaction.atomic`; `Submission`; `Entry.revision`; `guards.py::lock_workspace`; safeguards tests | The two **PostgreSQL-only concurrency tests are skipped locally**. |
| SEC01 auth, workspace scoping, 2FA, separate admin, recovery, backup codes, CSRF, throttling | **IV (local)** | `security.py`; `auth_views.py`; `config/urls.py` (`AdminSiteOTPRequired`); read-only `admin.py`; 2FA/throttle/lockout/scoping tests | Hosted SMTP/2FA/recovery not exercised. |
| OPS01 encrypted backup + documented restore | **PI** | `scripts/backup_database.py` present; no schedule, no restore drill run | Operational. |
| RES01–RES06 resale | **M** | None | Correctly deferred; do not enable. |
---

## J. Acceptance-scenario assessment

| # | Scenario | Result | Evidence |
| --- | --- | --- | --- |
| A01 | ₹10k + ₹15k + ₹5k Razorpay = ₹30,000 | **Pass (logic)** | `test_income_entries_cumulative` (subset) + `test_domain` exact decimals |
| A02 | ₹35k + ₹5k = ₹40k expenses, −₹10k | **Pass** | `statement_summary` + `test_advance_and_next_month_stock_count_once` |
| A03 | Correction to ₹4.5k → −₹9.5k, history kept | **Pass (mechanism)** | `test_edit_and_void_audited`; exact figures by arithmetic |
| A04 | 20 received + 3 sold = 17, no new financial entry | **Pass** | `test_advance_and_next_month_stock_count_once` |
| A05 | Inline category keeps unfinished form; product preselected | **Pass** | `test_inline_category_creation_preserves_unfinished_expense`; `test_product_detail_has_separate_stock_actions_and_prefills_expense` |
| A06 | Retry = one entry; stale edit rejected | **Pass** | `test_same_post_token_returns_single_entry`; `test_stale_editor_cannot_overwrite`; `test_changed_payload_with_same_token_rejected` |
| A07 | Top-up/card repayment/reimbursement no duplicate expense | **Pass** | `test_transfers_and_repayments_never_count_twice` |
| A08 | Closed-month blocked; workspace isolation | **Pass** | `test_closed_month_blocks_new_entry`; `test_record_urls_and_csv_are_owner_scoped`; `test_bank_tally_is_owner_scoped_and_closed_month_protected` |
| A09 | Persistence/recovery on device change & redeploy | **Not verified** | Needs hosted PostgreSQL + restore drill |
| A10 | Resale commission maths | **N/A (not implemented)** | Deferred |
| A11 | Bank tally closing ₹11,000 | **Fail (missing feature)** | No opening/closing balance in `BankTally` |
| A12 | SKU margin unavailable without data | **Pass** | No margin computed |

---

## K. Repeated or unnecessary screens and fields

- **`templates/tracker/transactions.html` is dead.** `views.py::transactions` now only redirects to the
  dashboard; nothing renders that template. Remove it (or repurpose) so there are not two overlapping
  "transaction list" designs.
- **Conditional sales-amount UI is exposed ahead of the decision.** `products.html`,
  `product_detail.html` and `monthly_reports.html` display "sales total noted" figures, and
  `StockForm` exposes an optional "SKU sales total". Migration 0004 shipped this field, so a
  *conditional* (BAG03) feature is partly visible. **Recommend hiding it in V1** until OD-02/03 is
  approved, while keeping the stored data.
- **Repeated per-page banners.** `dashboard.html` has two `.notice subtle` blocks; every form page adds
  another; `product_detail.html` carries a long disclaimer. Consolidate into one short hint plus an
  expandable "help" disclosure.
- **`monthly_reports.html` "SKU sales noted" column reads like a financial total** while being
  explicitly *not* added to Money In — label clearly or hide.
- **"Bank tally" sits in the `More actions` menu** while being a conditional module. Fine for V1, but it
  should not read as a primary feature.

---

## L. Calculation and data-integrity conflicts

1. **Docs describe an older, smaller system than the code.** `README.md`, `VERIFICATION.md` and
   `CHANGELOG.md` say three migrations and call SKU sales totals and bank tally deferred; the code has
   migrations 0004–0005 and both features partly built. Documentation must be reconciled.
2. **`BankTally` cannot satisfy BANK03.** It stores only statement credits/debits; the spec requires
   opening balance, credits, debits and closing balance. Genuine feature gap.
3. **Bank "credits" derived from income entries ≠ statement credits.** A settlement recorded once as a
   receipt and once in the transfer flow could be counted twice in `bank_activity`. Today classification
   is manual, so this is a **risk**, not a proven bug — but it is exactly what BANK04 reconciliation
   exists to close.
4. **Third-party expense + repayment.** Under the provisional rule the expense is counted once and the
   repayment is a transfer; `bank_activity` correctly shows the October bank debit with no second
   expense, but **bank tally cannot explain the matching gap** without an opening balance and movement
   register. Expected; feeds the BANK scope decision.
5. **No conflict found** in the core money/stock rules: transfers are excluded from the result, stock
   movements never create `Entry` rows, and the monthly result never includes `withdrawal`. Correctly
   implemented and tested.
6. **Case-sensitivity mismatch** on category/account names (see EXP02) — form-level `iexact` check vs
   case-sensitive DB constraint. Low impact.
7. **`sales_amount` is never added to Money In** — verified by
   `test_sku_sales_total_is_separate_from_money_in`. So the exposure risk in §K is cosmetic, not
   numerical.

---

## M. Checks run, results, and blocked checks

**Run in this review (all isolated from real data — the test DB is created and destroyed per run):**

| Check | Command | Result |
| --- | --- | --- |
| Django system check | `manage.py check` | **1 warning** (`axes.W006`, deliberate username-only lockout) |
| Migration sync | `manage.py makemigrations --check --dry-run` | **No changes detected** |
| Full test suite | `manage.py test --settings=config.test_settings` | **63 tests, OK, 2 skipped** (PostgreSQL-only concurrency) |
| Local DB inspection | `manage.py shell -c ...` (read only) | 0 entries, 1 orphan product, 0 accounts/categories/movements |

**Blocked / not run here (and why):**

- **PostgreSQL concurrency tests** — no PostgreSQL locally; they are `skipUnless(vendor == "postgresql")`.
  This covers overselling the last unit and the same submission recorded concurrently.
- **Browser/desktop/mobile rendering, focus, responsive layout** — not yet run.
- **Hosted 2FA, SMTP password recovery, backup restore drill, Render/Supabase deploy** — no provisioned
  services, and this review must not provision them.
- **Dependency lock resolution and `pip-audit`** — intentionally deferred to the Linux CI workflow.

The `axes.W006` warning is expected: the app locks by **username** and deliberately refuses to trust
forwarded IP headers (`tracker/security.py::no_client_ip`). Locking by username still defeats
brute-force against a named account; the warning concerns rotating *other* lockout keys, which does not
apply here. No action required for V1; a short comment in `settings.py` would document the intent.

---

## N. Recommended V1 scope (for Avni's approval)

**Keep and polish — already working and largely tested:**

- Monthly dashboard; money-in and expense entry; categories/accounts; product/SKU spending and stock;
  monthly reports; CSV details export; corrections/voids/reversals; month close/reopen; workspace
  isolation; duplicate-submission protection; 2FA and login security.

**Simplifications to make in V1 (no business decision required):**

1. Delete the dead `transactions.html`; keep the dashboard entry list as the single list.
2. Hide the conditional SKU **sales-amount** UI until OD-02/03 is approved (keep the data field).
3. Consolidate repeated banners into one hint + expandable help; ensure no development notes appear on
   client screens.
4. Add source-row and stock-figure drill-down on the dashboard (DASH02).
5. Add a "this date is outside the month you are reviewing" hint (UX02).
6. Fix the category/account case-sensitivity mismatch.
7. Reconcile `README.md` / `VERIFICATION.md` / `CHANGELOG.md` with the current migration count and
   features.

**Add only if approved (small, well-defined):**

8. Bank tally **opening/closing balance** fields (BANK03) — only if OD-11 says keep the manual check.
9. A summary CSV export (REP02) — cosmetic, low risk.

**Defer (conditional — do not enable):**

- Resale/commission (RES), bank line matching and CSV import (BANK04–05), SKU margin (BAG03),
  returns/clearance workflow (INV03–04), aggregate receipts (IN05), category/account rename+archive
  (EXP04).

---

## O. Ordered implementation plan (summary)

Full detail in `docs/v1-plan.md`:

1. Reconcile documentation with the code (fast, zero risk).
2. UI simplification: dead template, banner consolidation, hide sales-amount UI.
3. DASH02/UX02 polish: drill-down links, out-of-month date hint.
4. Case-sensitivity fix + a focused test.
5. Optional: bank-tally opening/closing and summary export (on approval).
6. Verify: `check`, `makemigrations --check`, full suite, then a **PostgreSQL** run so the two
   concurrency tests execute; browser desktop + phone QA.
7. Hand off to Tanvi: fictional-data trial, then reconcile one historical month.

No database reset; no schema change to existing tables unless bank-tally/OD is approved; no unresolved
financial policy invented.
