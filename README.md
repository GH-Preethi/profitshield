# ProfitShield

The money brain for restaurants on delivery apps. ProfitShield pulls delivery payout reports, POS sales and supplier invoices into one database, explains why profit moved, and shows the exact rows behind every answer.

Built for the DoorDash Back House track at NOVA 2026 (ScottyLabs).

## Run it

Easiest: copy `.env.example` to `.env`, paste your key into it, then `python3 server.py`. Or use exports:

```bash
export OPENROUTER_API_KEY=sk-or-...               # AI agent + receipt reading
export OPENROUTER_MODEL=google/gemini-2.5-flash   # optional; must support tool calling + images
export SQUARE_ACCESS_TOKEN=EAAA...                # optional; free sandbox token, see below
python3 server.py
# open http://localhost:8000
```

Python 3.9+ standard library only. No pip installs. The first run creates `backhouse.db` (SQLite) and imports everything in `samples/` through the same importer you use for real files. Delete `backhouse.db` (or POST /api/reset) to start fresh.

Without keys the app still runs: database, imports, every number, chart and finding work; Ask falls back to built-in rules.

### Square POS (real API, 3 minutes)
1. developer.squareup.com → sign in → create an application
2. Credentials → **Sandbox** access token → `export SQUARE_ACCESS_TOKEN=...`
3. Restart, open Sources → "Review 3 sandbox test orders". Inspect the location, quantities and prices, then type `CREATE 3 SANDBOX ORDERS` and confirm. Orders are created only in the sandbox and pulled back through the Orders API.

## What's real vs. what isn't (say this to judges)

| Piece | Status |
|---|---|
| SQLite database, CSV importers, dedupe on re-import | Real |
| Column mapping for unfamiliar export layouts | Real (AI via OpenRouter, rules fallback) |
| PII removal before storage and before any AI call | Real (customer/staff/driver/email/phone columns dropped, emails and phones scrubbed) |
| Square POS sync | Real API, sandbox only |
| Receipt photos and multi-page PDF invoices | Real (vision model via OpenRouter), each line tagged with its page |
| Ask: tool-calling agent | Real: model picks tools, tools run exact SQL/Python over your data |
| DoorDash / Uber Eats / Grubhub APIs | Not public. They need partner approval, so ProfitShield reads the payout CSVs owners already download from each merchant portal |
| Execute price increase | Square sandbox: reviewed, confirmed Catalog API call (finds or creates the item, sets the price). DoorDash / Uber Eats / Grubhub: menu APIs are partner-only, so it outputs the exact change list for each merchant portal |
| Demo store data | Example: Forbes Ave Slice Co., 1,776 orders over 4 weeks with planted problems |

## Architecture

```
CSV exports ─┐                         ┌─ /api/data ──▶ engine in the browser: profit bridge,
Square API ──┼─▶ redact PII ─▶ map ─▶ SQLite             findings, margins, evidence
Photos ──────┘   columns      (known │ AI │ rules)  └─ /api/ask ──▶ agent ──▶ tools (SQL over SQLite)
```

**AI reads and explains. Code does the math.** Every chat answer comes with a profit bridge (the bars it cites are highlighted and clickable) or a simulation chart.

AI is used for:
1. **Column mapping** of unfamiliar export layouts (`/api/import`). Headers plus 3 PII-free sample rows go to the model; it returns a mapping; code does the import.
2. **Receipt and invoice photos** (`/api/extract`). Vision model returns line items matched to ingredients with confidence; owner confirms; the confirmed match is remembered.
3. **Ask ProfitShield** (`/api/ask`). Tool-calling agent. Tools: `get_profit_bridge`, `check_commissions`, `find_unapproved_promos`, `find_price_changes`, `find_duplicate_invoices`, `error_charge_pattern`, `menu_margins`, `simulate_price_change`. The UI shows which tools ran, renders a chart under the answer, and turns [F1]-style citations into buttons that open the evidence.

No AI in: the profit bridge (variance decomposition), contract checks, promo approval checks, duplicate detection, error-charge patterns, margins, simulations.

## The profit bridge

Profit = gross sales − contract commission − overcharge − promos − error charges − food cost − duplicate payments (before labor and rent).

Week-over-week change splits into sales & mix, a price effect per ingredient (this week's quantity × price change), and leaks (overcharges, unapproved promos, error charges, double payments). The steps add up exactly to the change.

## Demo story (week of Oct 26 – Nov 1)
- Sales up 12.4%, profit down $574
- F1 US Foods invoice paid twice: −$738
- F2 Mozzarella up 37% at Sysco: −$253 a week
- F3 Uber Eats ran a $5-off promo nobody approved: −$190
- F4 DoorDash billed 25% vs a 20% contract on 112 orders: −$136
- F5 Missing-item charges up, mostly soda on Fri–Sat dinner rush

## Files in `samples/`
- `doordash_payouts_…csv`, `ubereats_payments_…csv`, `grubhub_transactions_…csv`, `square_orders_…csv`, `supplier_invoices_…csv`: seeded on first run
- `grubhub_export_unusual_columns.csv`: drop this on Sources live to show unfamiliar-column mapping (and dedupe: 0 new rows)
- `receipt_restaurant_depot_2026-10-30.jpg`: drop on "Add a paper receipt" to show the vision model reading a photo
- `sysco_invoice_SY-88214.pdf`: 3-page scanned Sysco invoice; mozzarella is on page 2. Drop it on the same box; the evidence panel then shows "PDF page 2" next to that line
- The unusual Grubhub CSV includes customer names and phone numbers: the import reports 100 personal fields removed

## How it scales (the "receipts are still manual" question)

| Layer | Share | How |
|---|---|---|
| Automatic | ~80% | Payout reports and POS arrive as data |
| Learned formats | ~15% | Known supplier layouts parse without AI after the first one |
| AI read | ~4% | New layouts and phone photos |
| Owner confirms | ~1% | Only low-confidence lines, remembered next time |

## 2-minute demo script
1. **Problem (15s).** Read DoorDash's Back House prompt.
2. **Overview (20s).** "Sales up 12%. Profit down $574." Five portals can't tell you why.
3. **Bridge (25s).** Click the DoorDash commission bar: 112 orders at 25% vs 20%. Dispute drafted; the owner files it.
4. **Ask (25s).** "Why did my profit drop?" then "What if I raise pizza prices by $0.75?" Point at the tools-used line and the chart. Click "Review sandbox changes", inspect the exact targets, then type the confirmation phrase. Square sandbox gets the new price; delivery apps get manual instructions.
5. **Real data (25s).** Sources: drop the unusual Grubhub CSV (AI maps the columns, 100 personal fields removed, 0 duplicates). Drop the Sysco PDF; it reads all 3 pages and the mozzarella line shows its page number.
6. **Close (10s).** "Swiggy built Guru for one platform. Owners live across five. ProfitShield sees all of them and shows its receipts."

## HTTP file access and regression tests

Only `/` and `/index.html` serve the dashboard. Its scripts, styles and icons
are embedded; fonts load from Google Fonts. All other file paths return 404,
including sample files, configuration, database files and Python source.
GET and HEAD share this allowlist. Query strings do not change the selected
asset; encoded or noncanonical asset paths are not accepted. Future public
assets must be added individually to `PUBLIC_ASSETS` in `server.py`.

Run the standard-library HTTP regression tests with:

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary dummy private files and mock API operations; they do not
use integration credentials, call external services or reset the real database.
This file allowlist does not add authentication to the application APIs.

## Square sandbox mutation safety

Square is now **sandbox only**. `SQUARE_ENV=production` is ignored; requests use
only the literal `https://connect.squareupsandbox.com` host. A changed runtime
base URL, unsupported endpoint or redirect fails closed. Authorization headers
are never forwarded through redirects. Supply only a sandbox access token;
opaque tokens cannot be identified as sandbox/production from their text, but
a production token cannot cause the app to send a production-host request.
OpenRouter behavior is unchanged.

Square read/search sync calls remain available. Test-order creation and price
changes use a mandatory two-step review contract. Direct mutation helper calls
without a claimed plan and the old unreviewed HTTP payloads are rejected.

| Step | Endpoint | Input |
|---|---|---|
| Review prices (read only) | POST `/api/menu/preview` | `week` (ISO Monday), `channels`, `changes` with SKU, `old_price` and absolute `price` |
| Confirm prices | POST `/api/menu/apply` | Returned `plan_id`, exact `confirmation` phrase, and selected `week` |
| Review test orders (read only) | POST `/api/square/seed/preview` | `{}` |
| Confirm test orders | POST `/api/square/seed` | Returned `plan_id` and exact `confirmation` phrase |

New/reviewed mutation endpoints require JSON, the exact configured browser
Origin and a body up to 32 KiB. Set `PROFITSHIELD_ORIGIN` to the actual browser
origin when it differs from `http://localhost:8000` (or configured PORT).
These origin checks are not owner authentication. The separate owner-auth and
input-security PRs still need integration before hosted network exposure.

The review lists old local reference prices, current sandbox variation/price
(or an explicit new-item creation), proposed absolute prices, selected channels
and week. Missing/multiple catalog matches are not silently resolved: multiple
items/variations or paginated matches require cleanup in the sandbox first.
Prices must be finite, positive, at most 1,000,000 and have no more than two
decimal places. The seed review freezes three baskets and their unit prices
for one named sandbox location.

Each server-stored plan expires after five minutes. Confirmation cannot change
its prices, channels or baskets. Changing the selected week, restaurant data,
local prices, menu definition, sandbox catalog/location or connection invalidates
it. All catalog targets are rechecked before the first price write; existing
variation writes retain Square's version check. Remote catalog changes in the
small interval after validation can still reject a write; creation-by-name is
not an atomic uniqueness constraint in Square.

The `square_actions` table is part of the private application SQLite database.
Plans transition from pending to executing **before** external mutations, then
completed or failed. Atomic SQLite claiming rejects replay and concurrent
confirmation of the same plan, including after process restart. An interrupted
executing plan stays consumed. Deleting/resetting the database also invalidates
old plan IDs; it never makes them executable again.

Each external write has a stable Square idempotency key derived from its plan
and item/order index. Errors, partial multi-item success, network timeouts and
uncertain responses are never automatically retried. Inspect the sandbox and
local reference prices before explicitly creating a fresh review. This is
at-most-once plan submission, not a distributed transaction or a guarantee that
all requested external changes succeeded together. Use one application process
per restaurant database.

There is no global `LAST_SIM` or text-command execution. Each simulation button
captures its own prices and week; old buttons cannot silently reuse a newer
simulation. Chat commands such as `execute`, `apply` and `do it` only explain
how to open a review. The owner must review the specific plan and type
`APPLY SANDBOX PRICES` or `CREATE 3 SANDBOX ORDERS` before its confirmation button
enables. A submitted button cannot send again; after cancellation/expiry/failure,
run a new simulation or request a fresh seed review.

Delivery channels still require manual merchant-portal edits. Disconnected
Square selections make no Square write. Local reference prices update on a
completed price step, and are not proof that a production/delivery menu changed;
this PR does not redesign the financial price-history model.

Run regression tests (all external integrations mocked/blocked):

```bash
python3 -m unittest discover -s tests -v
# Optional, with Playwright and Chromium already installed:
python3 tests/browser_square_guard.py
```

Tests cover production environment overrides, runtime endpoint tampering,
redirect denial, direct mutation guards, exact confirmation, stale/expired plans,
changed connection/catalog/location/data, replay, concurrent submissions,
restart/crash persistence, unknown outcomes, missing-item creation and seed
idempotency. Browser checks exercise all six views, read-only review, typed
confirmation, stale simulations and repeated clicks/chat without duplicate writes.
No production credentials or real Square/AI calls are used.

## Input/Square integration reconciliation

The common HTTP boundary applies origin, JSON, size, throttle and CSP protections
to both ordinary APIs and the two-step Square review routes. Price/seed preview
payloads are validated separately from one-use confirmation payloads; unreviewed
legacy price writes remain rejected. The review endpoints retain their 32 KiB
limit and action failures retain their conflict/status codes. Import validation
helpers and request-security imports must remain wired when merging features.
