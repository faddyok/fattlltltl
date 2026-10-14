# Security & Stability Hardening

This build preserves the existing shop, Telegram admin, web admin, purchase-key, reminder, email-fulfillment, OTP, methods, inventory, credits, referral and broadcast workflows while hardening the highest-risk paths.

## Fixed security issues

### 1. Methods authorization / account impersonation
The premium Methods buy/read endpoints now require the same signed shop session and required-group membership as the storefront. A caller can no longer submit only another Telegram user ID to buy/read a Method as that user.

Method purchase ownership is rechecked inside the MongoDB transaction and the existing unique `(user_id, method_id)` index is used to prevent race/double-click duplicate purchases.

### 2. Duplicate order charge on Telegram webhook retry
Paid product orders now store a unique `telegram_event_id` derived from the Telegram service message. MongoDB has a unique sparse index on this value. If Telegram retries the same Web App update, the existing receipt/delivery is replayed instead of charging the customer again.

Order codes were also lengthened from a 24-bit random suffix to 48 bits to make accidental collisions negligible.

### 3. Atomic credits
Credit deductions now include `credits >= required_amount` in the same MongoDB update. Two concurrent deductions cannot both pass a stale balance check and drive a customer below zero.

Admin credit mutations validate user IDs, modes and amount bounds.

### 4. Checkout/server-price validation
The server remains authoritative for all prices and now additionally rejects:
- malformed cart lines;
- more than 50 cart lines;
- invalid quantities;
- nonexistent/mismatched variants rather than silently falling back;
- negative/corrupt product or variant prices;
- absurdly large prices.

This protects against edited browser JavaScript, forged POST bodies and corrupted product records.

### 5. Purchase-key brute-force protection
Purchase keys are still stored only as a keyed one-way SHA-256 HMAC. Wrong key attempts are now rate-limited per Telegram user and product, with TTL-backed MongoDB attempt records. Web Admin also enforces the same 4–128 character key rule as Telegram Admin.

### 6. Admin CSRF/session hardening
Admin mutations still require the signed HttpOnly/Secure/SameSite=Strict admin cookie. Unsafe admin requests now reject cross-site browser requests and validate Origin when `PUBLIC_URL` is configured. Webhook setup changed from GET to POST.

Admin login keeps its per-IP limit and now also has a global failure ceiling to reduce simple X-Forwarded-For rotation abuse.

### 7. Telegram webhook authentication
Webhook-secret comparison now uses constant-time `hmac.compare_digest`.

### 8. Safer uploaded images
Product/Method uploads are accepted only when their actual magic bytes identify JPEG, PNG, GIF or WebP. A renamed HTML/SVG/script file is rejected. Image URLs are restricted to HTTP(S) or the application's own `/media/` path.

Cloudinary network upload work is moved off the async event loop, preventing a slow upload from freezing unrelated bot/web requests.

### 9. Inventory encryption safeguards
Legacy inventory still stored in the old plaintext `value` field is migrated gradually to encrypted `payload_enc` records.

A new encryption sentinel verifies the configured inventory key at startup. If `INVENTORY_ENCRYPTION_KEY` (or `WEBHOOK_SECRET` when using the legacy derived-key fallback) is accidentally changed, the app stops with a clear error instead of silently turning stored credentials into blank deliveries.

For production, set a dedicated `INVENTORY_ENCRYPTION_KEY` and keep it backed up securely.

### 10. Reminder/fulfillment idempotency repair
Email fulfillment remains idempotent across Telegram and Web Admin. A retry now also repairs the derived order status and recreates an expected reminder if a previous request was interrupted after marking the line fulfilled but before the reminder write completed.

### 11. Stored-content/output hardening
Customer-controlled display names shown in Telegram admin output are HTML-escaped. Product/method text and upload sizes have bounded server-side limits.

### 12. Security response headers
Responses now add `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and a restrictive Permissions Policy. Admin responses are non-cacheable and denied framing. Purchased Method content is also marked private/no-store.

A strict CSP was intentionally not forced in this build because the existing Mini App/admin pages contain inline script/style behavior; adding one without a frontend refactor would break features.

## Performance / smoothness improvements

Several N+1 MongoDB query patterns were replaced with grouped aggregations:
- storefront stock counts;
- admin sold/wishlist product statistics;
- Method buyer counts;
- customer order totals;
- dashboard revenue.

Normal Telegram webhook traffic now processes only a small reminder batch; the worker/cron remains responsible for the full queue. This reduces Telegram webhook response latency.

## Dependency security updates

The previous `fastapi==0.116.1` constrained Starlette below the patched range for the 2025 FileResponse Range-header DoS. The build now uses `fastapi==0.128.3`, whose Starlette compatibility range allows patched/current Starlette releases.

`python-multipart` was upgraded from `0.0.20` to `0.0.31` to include 2026 file-upload/parser/DoS security fixes.

`cryptography` now requires at least `46.0.7` while remaining below the next major compatibility boundary.

Aiogram and PyMongo were left on the versions already used by the project to minimize unrelated behavior changes.

## Important residual security model

The storefront `uid + sig` URL is a signed bearer session. It cannot be forged without the server secret, and `Referrer-Policy: no-referrer` now reduces accidental URL leakage, but anyone who obtains a still-valid complete shop URL could reuse that session until it expires. Do not post/share customer shop URLs.

Telegram recommends validating `Telegram.WebApp.initData` for launch modes that provide authenticated Mini App user data. This project intentionally retains both Reply-Keyboard `sendData` and Inline/Menu Mini App behavior; a mandatory initData-only policy was not imposed because it would alter/break the Reply-Keyboard path. If you later standardize the shop on Inline/Menu/Main Mini App launching only, migrating every sensitive web API to validated initData is the next defense-in-depth step.

## Deployment checklist

- Use a long unique `ADMIN_PASSWORD`; enable `ADMIN_TOTP_SECRET`.
- Use a long random `WEBHOOK_SECRET` and `CRON_SECRET`.
- Set and safely back up a dedicated `INVENTORY_ENCRYPTION_KEY`.
- Never publish `.env` or production secrets.
- Keep MongoDB network/user permissions restricted to what the app needs.
- Redeploy after the dependency changes so the patched packages are actually installed.
- Test one low-value real order, one Method purchase, one email fulfillment and one reminder after deployment before normal use.

No software can honestly guarantee that nobody will ever manipulate it. This pass closes the concrete manipulation/race/authentication issues found in the reviewed code and adds defense-in-depth without intentionally removing existing functionality.

## Fulfilled-by-request delivery hardening

The manual admin fulfillment feature added after this hardening pass stores prepared customer delivery details encrypted at rest. The admin order-list API does not return the encrypted ciphertext to the browser. Manual fulfillment uses a conditional MongoDB update so Telegram and Web Admin cannot intentionally fulfill the same pending line twice, and retry paths repair derived order/reminder state. Non-instant products do not consume inventory or participate in low-stock alerts.
