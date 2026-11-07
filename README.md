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

## Automated tests

No application/development package installs or credentials are required. Use
Python 3.9+ and Node.js 24 (the CI runtime):

```bash
python3 -m unittest discover -s tests -v
node --test tests/js/*.test.cjs
```

Tests cover production environment overrides, runtime endpoint tampering,
redirect denial, direct mutation guards, exact confirmation, stale/expired plans,
changed connection/catalog/location/data, replay, concurrent submissions,
restart/crash persistence, unknown outcomes, missing-item creation and seed
idempotency. Browser checks exercise all six views, read-only review, typed
confirmation, stale simulations and repeated clicks/chat without duplicate writes.
No production credentials or real Square/AI calls are used.

## Contributing and development workflow

`development` is the integration branch. Start a dedicated task branch from its
latest state and target `development` in the PR; never commit directly to `main`
or merge/deploy automatically. See [AGENTS.md](AGENTS.md) and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for workflow, product constraints, CI,
verification and migration/recovery conventions. Use the pull request template.
