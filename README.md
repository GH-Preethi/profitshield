# ProfitShield

The money brain for restaurants on delivery apps. ProfitShield pulls delivery payout reports, POS sales and supplier invoices into one database, explains why profit moved, and shows the exact rows behind every answer.

Built for the DoorDash Back House track at NOVA 2026 (ScottyLabs).

## Run it

Authentication is required. Bootstrap the owner before starting the server; see
**Owner authentication and recovery** below. No pip installs are needed.
The first run creates `backhouse.db` (SQLite) and imports `samples/`.
AI and Square are optional; without keys, calculations and imports work and
Ask uses built-in rules. Real receipt extraction requires an approved privacy
policy before sending any real documents to an AI provider.

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
The owner-authentication layer protects the application APIs in addition to file isolation.

## Owner authentication and recovery

This is one restaurant with one owner account; there is no public signup,
password reset by email, role hierarchy or default password. The owner has
access to all restaurant operations. Financial calculations are unchanged.

### Bootstrap on the server console

Use an interactive trusted terminal, not a URL or password argument:

```bash
# Optional: set a private, persistent path, consistently for CLI and server.
export PROFITSHIELD_AUTH_DB=/private/persistent/owner-auth.sqlite3
python3 owner_auth.py bootstrap
```

The parent directory must already exist and be writable only by the service
administrator. Use a unique passphrase (14–1024 characters); input is hidden
and confirmed. Passwords use scrypt (N=131072, r=8, p=1, random 32-byte salt,
64-byte derived key). Only the salt/hash is stored; scrypt uses about 128 MiB
per verification. The auth SQLite file is separate from restaurant data,
created with mode 0600, and excluded from Git and HTTP. If the owner has not
been bootstrapped, login fails closed. Bootstrap refuses to overwrite an owner.

For the default location, omit the export. When using a custom path in `.env`,
pass that same path using CLI `--db` or export it before running the CLI;
`owner_auth.py` does not read `.env`. `server.py` does.

### Hosted configuration

```bash
export PROFITSHIELD_ORIGIN=https://your-actual-profitshield-host.example
python3 server.py
```

The origin is required and must match the browser's scheme, hostname and port.
Terminate HTTPS at a trusted reverse proxy, redirect HTTP to HTTPS, configure
HSTS there, and restrict the backend port to that proxy. Do not expose the raw
Python HTTP port publicly or serve the repository through the proxy. The app
does not trust forwarded headers to derive its origin. TLS certificates and
proxy deployment are outside this repository's configuration.

Hosted cookies are host-only `__Host-profitshield`, Secure, HttpOnly,
SameSite=Strict, Path=/, with a 12-hour maximum lifetime. Random 256-bit session
tokens are stored only as SHA-256 hashes. Sessions expire after 30 minutes of
inactivity or 12 hours absolutely, survive restarts, rotate on a new login from
the same browser, and are revoked on logout/recovery. The CSRF token is derived
from the session and delivered only in authenticated responses; it is not a
replacement for the HttpOnly session cookie. No session token is kept in browser
localStorage. Auth responses use `Cache-Control: no-store`.

All sensitive GET/HEAD APIs require a session. All POST APIs require a session,
the exact configured Origin, `application/json`, and `X-CSRF-Token`; login is
the sole session/CSRF-token exception, but still requires Origin and JSON to
prevent login CSRF. `/api/auth/session` returns the owner's CSRF token.
`/api/auth/logout` revokes the current session. Public `/api/health` exposes only
liveness/backend indicators, without integration details. Dashboard access
without a session shows only the sign-in page. Live load failure shows an error
instead of silently substituting demo data.

Five failed logins lock further attempts for 60 seconds, persisted across
restarts. This single-owner lockout deliberately applies globally, so an attacker
could temporarily deny login. Add proxy-level request/connection limits and
monitor failed login status codes; application lockout is not DDoS protection.
JSON requests are capped at 16 KiB for login and 16 MiB for other POST APIs.

### Local development

```bash
python3 owner_auth.py bootstrap   # once, using the same DB path as the server
export PROFITSHIELD_LOCAL_HTTP=1
export PROFITSHIELD_ORIGIN=http://127.0.0.1:8000
python3 server.py
```

This explicit development mode binds only to 127.0.0.1 and uses a separate
non-Secure cookie name. It must never be used for hosted access. No Square or
AI credentials are needed for auth tests or sample-data development. Never
configure production Square credentials/endpoints for development or tests.

### Recovery and revocation

With trusted server-console access, stop the server and run:

```bash
python3 owner_auth.py recover  # add --db /the/same/auth/path when applicable
```

Enter and confirm a new passphrase, then restart. Recovery revokes every session
and clears login lockouts without changing restaurant data. If a session is
suspected compromised, use this procedure. Keep the auth database and its backups
private; it contains password hashes and active session metadata. Do not delete
or reset restaurant data to recover access. There is no remote recovery endpoint.

### Validation and limitations

```bash
python3 -m unittest discover -s tests -v
```

If Playwright and Chromium are already available, run the optional UI regression:

```bash
python3 tests/browser_owner_auth.py
```

It checks sign-in, all six live views, authenticated local save, sign-out,
expiry redirects, and failed-live-load behavior using temporary databases and
blocked external requests. It does not install browser dependencies.

Tests cover password verification, anonymous denial, owner authorization, login
CSRF, session CSRF, secure cookies, rotation, idle/absolute expiry, logout,
lockout persistence, recovery, bootstrap and HTTP file isolation. Integration
operations are mocked. Existing authentication-independent business behavior
is preserved; external execution approval and accounting corrections remain
separate work. Existing XSS risks in imported-data rendering also need their
own fix: HttpOnly cookies do not stop malicious same-origin scripts from acting
as the owner. This release does not add MFA, email recovery or multiple users.
