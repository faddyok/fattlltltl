# Deploy the Fattle shop on Botkeep

This package contains the shop, web admin and Telegram webhook. Temp Mail and
the downloader are external services; their backend source is not in this ZIP.
This package has been checked offline, not deployed to a live Botkeep account.

## Create the service

1. Choose the Python application profile and Python 3.11 or newer if offered.
2. Upload this ZIP. Ensure `main.py`, `app.py` and `requirements.txt` are in the
   working directory, rather than nested inside an extra folder.
3. Install dependencies using `pip install -r requirements.txt` if the profile
   does not install them automatically. Set the start command to `python main.py`.
4. Check Network for the assigned port. The launcher reads `SERVER_PORT`, then
   `PORT`, falling back to 8000. Use the assigned port, not an arbitrary number.
5. Configure an HTTPS address under Domains for this application.

## Environment

Copy your existing configuration into Botkeep Environment. Do not upload live
secrets in the ZIP. The launcher loads the managed `.env` before importing app.py.
Keep `VERCEL` unset so the persistent reminder worker runs.

Required settings: `BOT_TOKEN`, `PUBLIC_URL`, `ADMIN_CHAT_ID`, `WEBHOOK_SECRET`,
`ADMIN_PASSWORD`, `MONGODB_URI`. Set `PUBLIC_URL` to this service's new HTTPS
address, without a trailing slash. Preserve `MONGODB_DB` and your existing
`INVENTORY_ENCRYPTION_KEY` exactly; changing the encryption key can make existing
encrypted inventory unreadable. Preserve optional settings from `.env.example`.

Keep using your existing external MongoDB: Botkeep does not offer a MongoDB
profile. Make sure that database's access controls allow this service to connect.
Keep `TEMP_MAIL_API_URL`, `TEMP_MAIL_API_SECRET`, `DOWNLOADER_API_URL` and
`DOWNLOADER_API_SECRET` pointing to the existing Render services.

## Check, then switch Telegram

1. Start the service and check Console for startup/database errors.
2. Open `/health`, `/`, and `/admin` on the new HTTPS address. Log in to admin.
3. For the same bot token, keep only one host active during migration: this app
   starts a reminder worker on persistent hosts, so do not run two persistent
   instances against the same bot/database. Use a test bot/database for staging.
4. When ready to switch, open the NEW HTTPS address followed by `/admin`,
   log in, and click the **Telegram** button in the top toolbar. This calls
   `/admin/setup-webhook` on the new host. Do not use the old Telegram chat
   Refresh Webhook button before switching: it still reaches the old host.
   Telegram has one webhook per bot: this redirects updates away from Vercel.
5. Run `/start` again to obtain fresh shop buttons with the new address. Test
   shop navigation, balance, an order, Temp Mail and downloader integration.
6. Disable the old shop's Vercel reminder cron after the new worker is verified.
   Keep the Render backends running.

For rollback, open the old Vercel `/admin` page and click its Telegram button
(with its original PUBLIC_URL still configured). Stop the Botkeep shop and
restore the old reminder cron. Keep the original Vercel project until testing
has succeeded; do not delete it during migration.

## Resources and limitations

Start with one shop service and measure RAM/CPU before allocating other slots.
Five slots share the account resource budget; they are not five independent
2 GB servers. This ZIP does not migrate or optimize the downloader, and no
speed improvement is guaranteed without measuring real requests.

Botkeep references (checked 10 October 2026):
- https://botkeep.cloud/docs/hosting
- https://botkeep.cloud/docs/python
- https://botkeep.cloud/faq


## Exact configuration for your current Render services

| Setting in Botkeep | What to enter |
| --- | --- |
| PUBLIC_URL | New shop HTTPS base address, no /admin suffix |
| BOT_TOKEN | Existing shop bot token |
| ADMIN_CHAT_ID | Existing numeric admin Telegram ID |
| ADMIN_PASSWORD | Existing web admin password |
| WEBHOOK_SECRET | Existing webhook secret |
| MONGODB_URI / MONGODB_DB | Existing shop database connection and database name |
| INVENTORY_ENCRYPTION_KEY | Existing value, if configured; never regenerate for migration |
| TEMP_MAIL_API_URL | Existing Render Temp Mail base URL |
| TEMP_MAIL_API_SECRET | Same value as TEMP_MAIL_API_SECRET on Render |
| DOWNLOADER_API_URL | Existing Render coordinator base URL, not an individual worker |
| DOWNLOADER_API_SECRET | Same value as DOWNLOADER_API_SECRET on the coordinator |

Also copy existing Cloudinary settings, required-group settings, BOT_USERNAME,
OWNER_USERNAME, SHOP_NAME, ADMIN_TOTP_SECRET and any other custom settings.
Copy real values from Vercel, not the placeholders in .env.example. The app does
not use DATA_DIR. Leave TELEGRAM_BOT_API_BASE_URL blank unless your existing
shop actually uses a configured self-hosted Telegram Bot API server.

Your admin address is PUBLIC_URL plus `/admin`. Your health-check address is
PUBLIC_URL plus `/health`. The shop root and `/index.html` are served by the
same Python application. HTTPS routing must be configured in Botkeep Domains;
an internal IP/port by itself is not the Mini App address. If no HTTPS address
is available in your panel, resolve that before switching Telegram.

The Render coordinator keeps WORKER_1 through WORKER_4 and WORKER_SECRET.
The shop connects only to the coordinator. Keep all five existing downloader
services and the Temp Mail service running. Keep their existing database,
storage and Telegram credentials, including any TEMP_MAIL_STORAGE_KEY.
Neither supplied Render backend requires a Vercel callback address: progress
and inbox updates are sent directly to Telegram.

The uploaded telegram-downloader-main project is a separate Cloudflare /
Northflank system and is not required for this migration. Do not configure its
Telegram webhook for the shop bot. The uploaded fattle-downloads-main reports
build 3.7; this migration does not replace or downgrade your deployed backend.

## Verification performed, 14 October 2026

- Existing shop suite: 20 Python and 12 JavaScript tests passed in local checks.
- Shop launcher, admin pages/login and webhook target were checked locally.
- All 15 distinct Temp Mail routes and 6 downloader routes called by the shop
  match the uploaded Render backend route declarations.
- Actual Temp Mail and coordinator handlers accepted matching request formats
  and secret headers, and rejected missing secrets. Database/provider responses
  were simulated and actual download execution was disabled.
- Live Botkeep DNS/HTTPS, MongoDB access, Render credentials, Telegram delivery,
  inbox providers and video downloads have NOT been verified.

## Live acceptance checks after switching

1. `/health` returns healthy with mongodb-connected.
2. `/admin` accepts your password; products and existing order history appear.
3. Run `/start`; open Shop / Methods and verify the new address loads.
4. Check your balance and place an authorized small test order; verify delivery.
5. Open Temp Mail, view a saved mailbox, receive a test email, and check refresh.
6. Submit a small public test download, check status and delivery in Telegram.
7. Check the private archive caption and the Render worker logs.
8. If a Telegram menu/Main App URL was set separately in BotFather, update that
   configured URL as well. Existing old messages can still contain old URLs.

A 401 from a backend usually means the API secrets differ. A coordinator 404
can mean DOWNLOADER_API_URL points at a worker rather than the coordinator.
A MongoDB 503 requires checking the database credentials and network access.
