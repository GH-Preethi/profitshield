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
3. Restart, open Sources → "Create 3 test orders in Square, then sync". Orders are created in your Square sandbox and pulled back through the Orders API.

## What's real vs. what isn't (say this to judges)

| Piece | Status |
|---|---|
| SQLite database, CSV importers, dedupe on re-import | Real |
| Column mapping for unfamiliar export layouts | Real (AI via OpenRouter, rules fallback) |
| PII removal before storage and before any AI call | Real (customer/staff/driver/email/phone columns dropped, emails and phones scrubbed) |
| Square POS sync | Real API (sandbox or production) |
| Receipt photos and multi-page PDF invoices | Real (vision model via OpenRouter), each line tagged with its page |
| Ask: tool-calling agent | Real: model picks tools, tools run exact SQL/Python over your data |
| DoorDash / Uber Eats / Grubhub APIs | Not public. They need partner approval, so ProfitShield reads the payout CSVs owners already download from each merchant portal |
| Execute price increase | Square POS: real Catalog API call (finds or creates the item, sets the price). DoorDash / Uber Eats / Grubhub: menu APIs are partner-only, so it outputs the exact change list for each merchant portal |
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
4. **Ask (25s).** "Why did my profit drop?" then "What if I raise pizza prices by $0.75?" Point at the tools-used line and the chart. Type "execute": Square gets the new price via API, the delivery apps get a change list.
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

## Input and HTTP security

The server escapes imported order IDs, invoice units/pages/quantities and review
input values before inserting them into HTML. Text remains text, including
legacy records that predate validation. A fresh per-response nonce authorizes
the dashboard script; inline event handlers and eval are blocked by CSP. Google
Fonts are still allowed, and inline styles remain allowed for the existing UI.
Responses also set nosniff, frame denial, same-origin referrer policy and disabled
camera/microphone/geolocation permissions. HTTPS origins additionally enable
HSTS; configure TLS at a trusted reverse proxy before hosted use.

All POST requests must use `application/json`, a single valid Content-Length and
the exact configured Origin. Compressed/chunked request bodies and cross-site
Fetch Metadata requests are rejected. Configure the browser origin explicitly:

```bash
# Local default is http://localhost:8000; use this if opening via 127.0.0.1:
export PROFITSHIELD_ORIGIN=http://127.0.0.1:8000
# Hosted: use the actual HTTPS browser origin, without a path or trailing slash.
# export PROFITSHIELD_ORIGIN=https://your-profitshield-host.example
```

The origin is never inferred from Host or forwarded headers. Non-browser clients
must supply the same Origin and JSON content type. These checks defend browser
cross-origin writes; they are not authentication. Owner authentication remains
in its separate PR and must be integrated before exposing sensitive APIs to a
hosted network. Keep the backend private behind the HTTPS proxy.

Validation happens before database writes or integration dispatch. JSON must be
an object with recognized fields, supported nested shapes, valid dates, allowed
channels/SKUs/ingredients/units, and finite bounded numbers. Duplicate JSON keys,
NaN/Infinity, excessive nesting, malformed structures and invalid Unicode are
rejected. Monetary inputs are bounded by 1e12; menu prices by 1e6. Invoice lines
require positive quantities (up to 1e6), nonnegative unit prices (up to 1e6), and
units matching the selected ingredient. Negative invoice/credit-note quantities
are not supported. Existing refund/sign accounting semantics are unchanged.
AI extraction output and tool arguments are also validated before use.

Limits:
- JSON body: 16 MiB; CSV text: 4 MiB, 20,000 rows, 100 distinct headers,
  4,096 characters per cell.
- Receipt/PDF: 8 MiB decoded; only base64 JPEG, PNG, WebP and PDF with matching
  signatures. Signature checks do not prove a complete document is readable.
- Invoice: 1–500 lines. Questions: 2,000 characters; history: six messages.
- Per process: 120 requests/minute per peer IP, 300 total requests/minute and
  10 write/integration requests/minute globally. Rejections return 429 with
  Retry-After: 60. Limits use locked, bounded in-memory sliding windows and reset
  on process restart. At most 1,024 active peer windows are retained.
- Client sockets use a 10-second inactivity timeout. Proxy-level connection,
  header/body deadline and DDoS limits are still required for hosted access.

All peer limits use the direct connection IP, ignoring spoofable forwarded IP
headers. Behind a proxy, requests may share its IP. This policy is intended for
one restaurant and one server process, not multiple workers or replicas.

Invalid CSV rows reject and roll back the whole import instead of silently
skipping rows or converting bad numeric values to zero. Blank optional numbers
still default to zero; supported CSV date formats are preserved. Error statuses
are 400 for invalid data/file limits, 403 for origin policy, 413 for oversized
HTTP bodies/unsupported encodings, 415 for content type, and 429 for throttling.
Internal exceptions return generic errors without upstream diagnostic details.
Live-data load failures show an error instead of silently switching to demo.

Run the dependency-free suite:

```bash
python3 -m unittest discover -s tests -v
```

With Playwright and Chromium already installed, run the optional stored-XSS/UI
regression (temporary sample databases; integrations mocked/blocked):

```bash
python3 tests/browser_input_security.py
```

It checks imported malicious IDs, legacy malicious invoice units/pages, receipt
review attributes, all six views, a sample receipt save, the current Ask request
schema with AI mocked, and mobile rendering. No production credentials or real
financial documents are used.
