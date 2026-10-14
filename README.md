# Fattle Shop — Advanced upgrade

An upgrade of the supplied Telegram shop: the FastAPI + aiogram + MongoDB architecture and existing Telegram/admin workflows are retained.

## What's new

- **My account:** customers can view their order status and recorded credit activity inside the Mini App. History loads in pages; each request checks their signed session, group membership and suspension status. Delivery secrets and internal admin notes are excluded.
- **Product discovery:** recommended, price and alphabetical sorting; availability and delivery filters; result counts; one-click filter reset. Methods can be filtered by free, premium or unlocked.
- **Saved cart:** product/variant IDs and quantities survive reopening on the same device for up to seven days. The cart is isolated by Telegram user ID, reconciled against current stock, and capped at 50 lines / 20 units per line. Email setup and login assistance remain limited to one unit. Passwords, purchase keys, email addresses and session tokens are never saved to browser storage.
- **Admin order search:** database-backed search and 50-order pages replace the latest-200-only dashboard search. Search order codes, exact Telegram customer IDs, product/variant names, requested email addresses and private order notes. Filter by pending/completed and inclusive UTC dates. Pending results show oldest orders first.
- **CSV export:** export the matching orders, including date, customer ID, status, credits and item summary. Spreadsheet formula payloads are escaped. Exports exclude delivery credentials, requested emails and internal notes. More than 5,000 matching orders requires a narrower date range; exports are never silently truncated.
- **Checkout reliability:** whole-number quantities are enforced on the server; stale variants are removed instead of silently replaced; changed prices require a fresh review; oversized Telegram payloads are stopped before submission; repeated method/favorite taps are guarded.
- **Usability:** keyboard-accessible cart, focus-managed sheets, Escape / Telegram Back handling, clearer account loading/error states, offline feedback, and English/Indonesian labels for the new features.

## Upgrade an existing installation

1. Download a current backup from the existing admin dashboard.
2. Replace the application source with this folder's contents, including `shop_extensions.py`, `shop_domain.py`, `static/assets/` and `public/assets/`. Keep the hosting project's existing environment variables.
3. Keep `MONGODB_URI`, `MONGODB_DB` and `INVENTORY_ENCRYPTION_KEY` unchanged. If the existing shop derives its encryption key from `WEBHOOK_SECRET`, preserve that secret as well. Do not generate a new key during this upgrade.
4. Install the unchanged production requirements: `python -m pip install -r requirements.txt`.
5. Run `python scripts/sync_storefront.py` after any future storefront edit. The FastAPI source lives in `static/`; Vercel's public copies must match it.
6. Redeploy through your existing host. On startup, the new schema marker creates additional order/history indexes. Existing users, credits, products, inventory and order records are preserved; there is no destructive migration.
7. Reopen the shop from Telegram to load the new page. Check My account, a saved cart, admin search and a CSV export. Use a separate staging bot/database for purchase and fulfillment testing before production use.

No new production environment variables or paid service integrations are required by this upgrade. It has not been deployed to your hosting account.

## Local development

Python 3.10+ is required by the existing project. Python 3.12 is recommended for consistency with the source checks performed here. Node.js 18+ is needed only for the offline JavaScript checks.

```sh
python -m venv .venv
```

Activate on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Activate on macOS/Linux:

```sh
source .venv/bin/activate
cp .env.example .env
```

Fill `.env` using your own configuration, then:

```sh
python -m pip install -r requirements.txt
python -m uvicorn app:app --env-file .env --reload
```

MongoDB transactions in the existing purchase flow require Atlas or another replica set; a standalone MongoDB server is insufficient. Startup also requires a reachable database to create/check indexes. A customer shop link must come from the bot; opening `/` without a signed launcher/session intentionally stays locked. Local HTTP is useful for source work, but the admin cookie is Secure and the real Telegram Mini App flow needs an HTTPS origin matching `PUBLIC_URL`.

The current `vercel.json` cron configuration is retained. Verify its schedule is suitable for the reminder timing you require; this upgrade does not change reminder scheduling or Telegram delivery infrastructure.

## Checks

Run checks that need only Python and Node:

```sh
python scripts/sync_storefront.py
python scripts/check_project.py
python -m unittest discover -s tests -p test_shop_domain.py -v
node --test tests/shop-core.test.cjs
```

Run the additional API suite after installing its development dependencies:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The API suite uses an in-memory MongoDB substitute and synthetic credentials. It checks customer isolation, authorization, pagination, sensitive-data filtering, search beyond 200 orders, exports and checkout validation. It does not contact Telegram or exercise real MongoDB transactions. If dependencies are missing, it explicitly reports a skipped suite.

### Verification performed for this delivery

- **Passed:** 10 Python reporting/serialization tests and 12 JavaScript cart/catalog tests.
- **Passed:** Python syntax, JSON configuration, JavaScript syntax for all six inline/external source blocks, duplicate HTML ID checks, local script references and equality of public/source storefront files.
- **Not run:** the API integration suite, because the required packages were unavailable and dependency installation could not complete in this environment.
- **Not verified:** browser rendering, a live Telegram purchase/delivery, real MongoDB transactions/index creation, or a deployment. No production messages or account changes were made.

## Source map

| File | Purpose |
| --- | --- |
| `app.py` | Existing bot, checkout, administration, fulfillment and startup; validation/cache/index integrations |
| `shop_extensions.py` | Authenticated account history, admin search and CSV endpoints |
| `shop_domain.py` | Pure query-building, UTC serialization and export safety rules |
| `static/index.html` | Customer Mini App source |
| `static/assets/shop-core.js` | Testable cart and catalog rules |
| `static/assets/shop-advanced.js` | Account navigation, cart persistence, feedback and modal behavior |
| `static/admin.html` | Admin dashboard with database search, paging and exports |
| `public/` | Vercel storefront copy, maintained by the sync script |
| `tests/` | Offline unit tests and optional API integration suite |

The earlier upgrade documents are retained as historical notes. This README describes the latest changes and the actual verification scope.

Framework testing reference: [FastAPI TestClient documentation](https://fastapi.tiangolo.com/tutorial/testing/).


## Render-owned saved Temp Mail accounts

The **Saved Mails** list is now fetched from the Render backend instead of being
read directly from Vercel's MongoDB code. Creating a mailbox, creating a custom
mailbox, and logging into an old mailbox all send `user_id` to Render, which
stores the encrypted account in MongoDB collection `temp_mail_saved_accounts`.

Vercel still keeps only the currently selected mailbox credentials in the user's
existing record so inbox commands can work normally.


## V3: Lower Vercel Temp Mail load

Temp Mail state and Mail.tm work have been moved to the Render backend.
Vercel remains the Telegram webhook/shop application and makes short API calls
to Render for Temp Mail operations.

Keep these Vercel variables:
- `TEMP_MAIL_API_URL`
- `TEMP_MAIL_API_SECRET`

The old `temp_mail_address` / `temp_mail_password_enc` fields are read only as a
one-time migration fallback. New Temp Mail actions do not write those fields.


## Downloader integration

This build adds a **📥 Downloader** menu while keeping the heavy work off Vercel.

Set on Vercel:

- `DOWNLOADER_API_URL` = Render #1 coordinator URL
- `DOWNLOADER_API_SECRET` = same coordinator client secret

For normal Telegram Bot API use, leave `TELEGRAM_BOT_API_BASE_URL` empty.
After you correctly migrate the bot to a self-hosted Local Telegram Bot API server,
set `TELEGRAM_BOT_API_BASE_URL` to that API server's HTTPS base URL. aiogram will then
send API calls through the custom server.

Do not switch this variable until the Local Bot API server is fully working and the bot has been migrated according to Telegram's local-server procedure.


## Downloader delivery — no VPS

The downloader backend now delivers without a Local Telegram Bot API server:

- small files: private archive channel -> `copyMessage` -> user
- large files: Cloudflare R2 -> temporary download button

The user does not see the private archive channel as the source of copied small-file messages.
The Downloader menu also includes **🔄 Fresh Link** for generating a new R2 link for the most recent completed job.


## Downloader URL-first flow

`🔗 Send Link` asks for the URL first. Vercel calls Render #1 `/api/probe`.
Direct files start immediately in original quality; media pages show the quality
keyboard. `.com` is never used by itself to decide the source type.
