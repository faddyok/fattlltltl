import asyncio
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import struct
import sys
import time
import zipfile
from contextlib import asynccontextmanager
from html import escape as html_escape
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request as UrlRequest, urlopen

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
    BufferedInputFile,
    InputMediaPhoto,
)
from bson import ObjectId, json_util
from bson.binary import Binary
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Form, Header, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse, Response, JSONResponse
from starlette.background import BackgroundTask
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError, DuplicateKeyError
import math

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("fattle-shop")

BASE_DIR = Path(__file__).resolve().parent
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
SHOP_NAME = os.getenv("SHOP_NAME", "Fattle Shop").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_SECRET_SAFE = re.sub(r"[^A-Za-z0-9_-]", "_", WEBHOOK_SECRET)[:256]
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "").strip().lstrip("@")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
ADMIN_TOTP_SECRET = os.getenv("ADMIN_TOTP_SECRET", "").strip().replace(" ", "")
ADMIN_SESSION_HOURS = max(1, min(168, int(os.getenv("ADMIN_SESSION_HOURS", "12"))))
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB = os.getenv("MONGODB_DB", "telegram_shop").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "").strip()
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
TEMP_MAIL_API_URL = os.getenv("TEMP_MAIL_API_URL", "").strip().rstrip("/")
TEMP_MAIL_API_SECRET = os.getenv("TEMP_MAIL_API_SECRET", "").strip()
DOWNLOADER_API_URL = os.getenv("DOWNLOADER_API_URL", "").strip().rstrip("/")
DOWNLOADER_API_SECRET = os.getenv("DOWNLOADER_API_SECRET", "").strip()
TELEGRAM_BOT_API_BASE_URL = os.getenv("TELEGRAM_BOT_API_BASE_URL", "").strip().rstrip("/")
REQUIRED_CHAT_INVITE_URL = os.getenv("REQUIRED_CHAT_INVITE_URL", "https://t.me/+23Ao1LMrgLgxMjc9").strip()
REQUIRED_CHAT_ID_ENV = os.getenv("REQUIRED_CHAT_ID", "").strip()
REFERRAL_CREDIT = max(0, int(os.getenv("REFERRAL_CREDIT", "10")))
OTP_PRICE = max(1, int(os.getenv("OTP_PRICE", "10")))
CREDIT_RATE_INR = os.getenv("CREDIT_RATE_INR", "₹1 = 1 credit").strip()
CREDIT_RATE_USD = os.getenv("CREDIT_RATE_USD", "$1 = 100 credits").strip()
DEFAULT_LOW_STOCK = max(0, int(os.getenv("DEFAULT_LOW_STOCK", "3")))
INVENTORY_ENCRYPTION_KEY = os.getenv("INVENTORY_ENCRYPTION_KEY", "").strip()
CRON_SECRET = os.getenv("CRON_SECRET", "").strip()
ADMIN_UTC_OFFSET_MINUTES = max(-720, min(840, int(os.getenv("ADMIN_UTC_OFFSET_MINUTES", "330"))))
ADMIN_TIMEZONE_LABEL = os.getenv("ADMIN_TIMEZONE_LABEL", "IST").strip() or "Local time"
ADMIN_LOCAL_TZ = timezone(timedelta(minutes=ADMIN_UTC_OFFSET_MINUTES))
FULFILLMENT_WARNING_HOURS = max(1, min(168, int(os.getenv("FULFILLMENT_WARNING_HOURS", "6"))))
FULFILLMENT_URGENT_HOURS = max(FULFILLMENT_WARNING_HOURS + 1, min(720, int(os.getenv("FULFILLMENT_URGENT_HOURS", "24"))))
TELEGRAM_BACKUP_MAX_BYTES = 45 * 1024 * 1024
MAX_INTERNAL_NOTE_LENGTH = 2000
MAX_FULFILLMENT_TEMPLATES = 50
MAX_METHOD_GALLERY_IMAGES = 8
MAX_METHOD_GALLERY_IMAGE_BYTES = 2 * 1024 * 1024
SHOP_LAUNCH_VERSION = (os.getenv("SHOP_LAUNCH_VERSION", "1").strip() or "1")[:32]

# Performance tuning. Values are deliberately short so security/state changes remain responsive.
MEMBERSHIP_CACHE_SECONDS = max(15, min(600, int(os.getenv("MEMBERSHIP_CACHE_SECONDS", "180"))))
SHOP_CATALOG_CACHE_SECONDS = max(1, min(30, int(os.getenv("SHOP_CATALOG_CACHE_SECONDS", "3"))))
METHOD_CATALOG_CACHE_SECONDS = max(1, min(60, int(os.getenv("METHOD_CATALOG_CACHE_SECONDS", "10"))))
WEBHOOK_HOUSEKEEPING_SECONDS = max(60, min(1800, int(os.getenv("WEBHOOK_HOUSEKEEPING_SECONDS", "300"))))
DB_SCHEMA_VERSION = "2026-09-temp-mail-v3"
IS_VERCEL = bool(os.getenv("VERCEL"))

for key, value in {
    "BOT_TOKEN": BOT_TOKEN,
    "PUBLIC_URL": PUBLIC_URL,
    "ADMIN_CHAT_ID": ADMIN_CHAT_ID,
    "WEBHOOK_SECRET": WEBHOOK_SECRET,
    "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "MONGODB_URI": MONGODB_URI,
}.items():
    if not value:
        raise RuntimeError(f"{key} is missing.")

ADMIN_ID = int(ADMIN_CHAT_ID)
if TELEGRAM_BOT_API_BASE_URL:
    _bot_session = AiohttpSession(api=TelegramAPIServer.from_base(TELEGRAM_BOT_API_BASE_URL, is_local=True))
    bot = Bot(BOT_TOKEN, session=_bot_session)
else:
    bot = Bot(BOT_TOKEN)
dp = Dispatcher()

mongo_client = MongoClient(
    MONGODB_URI,
    connect=False,
    serverSelectionTimeoutMS=4000,
    connectTimeoutMS=3000,
    socketTimeoutMS=10000,
    maxPoolSize=30,
    minPoolSize=0,
    maxIdleTimeMS=60000,
    appname="fattle-shop",
)
mdb = mongo_client[MONGODB_DB]
users_col = mdb["users"]

DEFAULT_LANGUAGE = "en"

I18N = {
    "en": {
        "start": "🔄 Start / Restart",
        "shop_methods": "🛍 Shop / Methods",
        "temp_mail": "📧 Temp Mail",
        "downloader": "📥 Downloader",
        "balance": "💳 Balance",
        "buy_credits": "💰 Buy Credits",
        "orders": "📦 My Orders",
        "otp": "🔐 OTP",
        "wishlist": "❤️ Wishlist",
        "refer": "🎁 Refer & Earn",
        "language": "🌐 Language",
        "help": "ℹ️ Help Guide",
        "admin": "🛠 Admin Dashboard",
        "choose_language": "🌐 <b>Language</b>\n\nChoose your language:",
        "changed": "✅ Language changed to English.",
        "home_choose": "Choose an option below.",
        "menu_unlocked": "✨ Store menu unlocked",
    },
    "id": {
        "start": "🔄 Mulai / Ulangi",
        "shop_methods": "🛍 Toko / Metode",
        "temp_mail": "📧 Temp Mail",
        "downloader": "📥 Downloader",
        "balance": "💳 Saldo",
        "buy_credits": "💰 Beli Kredit",
        "orders": "📦 Pesanan Saya",
        "otp": "🔐 OTP",
        "wishlist": "❤️ Favorit",
        "refer": "🎁 Referensi & Dapatkan",
        "language": "🌐 Bahasa",
        "help": "ℹ️ Panduan Bantuan",
        "admin": "🛠 Dasbor Admin",
        "choose_language": "🌐 <b>Bahasa</b>\n\nPilih bahasa:",
        "changed": "✅ Bahasa diubah ke Bahasa Indonesia.",
        "home_choose": "Pilih opsi di bawah ini.",
        "menu_unlocked": "✨ Menu toko terbuka",
    },
}

_language_cache = {}

def _invalidate_language_cache(uid: int):
    _language_cache.pop(int(uid), None)

def get_user_language(uid: int):
    uid = int(uid)
    now = time.monotonic()
    cached = _language_cache.get(uid)
    if cached and cached[1] > now:
        return cached[0]
    doc = users_col.find_one({"user_id": uid}, {"language": 1}) or {}
    value = doc.get("language", DEFAULT_LANGUAGE)
    value = value if value in I18N else DEFAULT_LANGUAGE
    _language_cache[uid] = (value, now + 60)
    return value

def tr(uid: int, key: str):
    lang = get_user_language(uid)
    return I18N[lang].get(key, I18N["en"].get(key, key))

products_col = mdb["products"]
orders_col = mdb["orders"]
credit_log_col = mdb["credit_log"]
digital_inventory_col = mdb["digital_inventory"]
product_images_col = mdb["product_images"]
settings_col = mdb["settings"]
referrals_col = mdb["referrals"]
wishlists_col = mdb["wishlists"]
login_attempts_col = mdb["login_attempts"]
methods_col = mdb["methods"]
method_images_col = mdb["method_images"]
method_gallery_col = mdb["method_gallery"]
method_purchases_col = mdb["method_purchases"]
broadcasts_col = mdb["broadcasts"]
otp_events_col = mdb["otp_events"]
subscription_reminders_col = mdb["subscription_reminders"]
purchase_key_attempts_col = mdb["purchase_key_attempts"]
fulfillment_templates_col = mdb["fulfillment_templates"]

# Explicit key is preferred. Fallback keeps existing installs working while still encrypting at rest.
if INVENTORY_ENCRYPTION_KEY:
    try:
        _fernet = Fernet(INVENTORY_ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise RuntimeError("INVENTORY_ENCRYPTION_KEY must be a valid Fernet key") from exc
    ENCRYPTION_KEY_SOURCE = "environment"
else:
    derived = base64.urlsafe_b64encode(hashlib.sha256((WEBHOOK_SECRET + "|inventory").encode()).digest())
    _fernet = Fernet(derived)
    ENCRYPTION_KEY_SOURCE = "derived"


def utcnow():
    return datetime.now(timezone.utc)


def money(n):
    return f"{int(n):,} credits"


def slugify(s):
    s = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(s)).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:48] or secrets.token_hex(4)


def purchase_key_hash(product_id: str, value: str) -> str:
    """One-way, server-secret keyed digest for product purchase keys."""
    normalized = str(value or "").strip()
    body = f"purchase-key|{product_id}|{normalized}".encode()
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def purchase_key_matches(product, supplied: str) -> bool:
    if not bool(product.get("purchase_key_required", False)):
        return True
    expected = str(product.get("purchase_key_hash") or "")
    if not expected:
        return False
    actual = purchase_key_hash(str(product.get("id") or ""), str(supplied or ""))
    return hmac.compare_digest(expected, actual)


def valid_email_address(value: str) -> bool:
    value = str(value or "").strip()
    if len(value) < 5 or len(value) > 254 or " " in value:
        return False
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def parse_datetime_value(value, field_name="date"):
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"Missing {field_name}")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid {field_name}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_admin_datetime_text(value: str):
    """Parse Telegram-admin date input. Naive dates use the configured admin UTC offset."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Date/time is required")
    # Explicit timezone / ISO input remains authoritative.
    try:
        if "T" in raw or re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", raw):
            return parse_datetime_value(raw, "expiry date")
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            local_dt = datetime.strptime(raw, fmt).replace(tzinfo=ADMIN_LOCAL_TZ)
            return local_dt.astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date/time. Use DD-MM-YYYY HH:MM ({ADMIN_TIMEZONE_LABEL}) "
        "or an ISO date with timezone."
    )


def format_admin_datetime(value):
    if not isinstance(value, datetime):
        return str(value or "Unknown")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ADMIN_LOCAL_TZ).strftime(f"%d %b %Y • %H:%M {ADMIN_TIMEZONE_LABEL}")


def admin_flow_key(uid: int):
    return f"telegram_admin_flow:{int(uid)}"


def set_admin_flow(uid: int, action: str, **data):
    if int(uid) != ADMIN_ID:
        return
    set_setting(admin_flow_key(uid), {
        "action": str(action),
        "data": data,
        "created_at": utcnow().isoformat(),
    })


def get_admin_flow(uid: int):
    if int(uid) != ADMIN_ID:
        return None
    flow = get_setting(admin_flow_key(uid), None)
    if not isinstance(flow, dict) or not flow.get("action"):
        return None
    try:
        created = parse_datetime_value(flow.get("created_at"), "flow time")
        if utcnow() - created > timedelta(hours=2):
            clear_admin_flow(uid)
            return None
    except Exception:
        clear_admin_flow(uid)
        return None
    return flow


def clear_admin_flow(uid: int):
    if int(uid) == ADMIN_ID:
        settings_col.delete_one({"_id": admin_flow_key(uid)})


def customer_activation_flow_key(uid: int):
    return f"customer_activation_flow:{int(uid)}"


def set_customer_activation_flow(uid: int, **data):
    set_setting(customer_activation_flow_key(uid), {**data, "created_at": utcnow().isoformat()})


def get_customer_activation_flow(uid: int):
    flow = get_setting(customer_activation_flow_key(uid), None)
    if not isinstance(flow, dict):
        return None
    try:
        created = parse_datetime_value(flow.get("created_at"), "activation flow time")
        if utcnow() - created > timedelta(hours=2):
            clear_customer_activation_flow(uid)
            return None
    except Exception:
        clear_customer_activation_flow(uid)
        return None
    return flow


def clear_customer_activation_flow(uid: int):
    settings_col.delete_one({"_id": customer_activation_flow_key(uid)})


def reminder_document(*, reminder_id: str, title: str, expires_at: datetime,
                      source: str = "manual", custom_message: str = "",
                      product_id: str = "", product_name: str = "",
                      order_code: str = "", item_index: int | None = None,
                      user_id: int | None = None, email: str = ""):
    expiry = parse_datetime_value(expires_at, "expiry date")
    return {
        "reminder_id": reminder_id,
        "title": str(title or product_name or "Subscription").strip()[:200],
        "source": str(source or "manual")[:40],
        "product_id": str(product_id or "")[:100],
        "product_name": str(product_name or "")[:200],
        "order_code": str(order_code or "")[:100],
        "item_index": item_index,
        "user_id": int(user_id) if user_id not in (None, "") else None,
        "email": str(email or "").strip()[:254],
        "expires_at": expiry,
        "remind_at": expiry - timedelta(days=1),
        "custom_message": str(custom_message or "").strip()[:2000],
        "status": "pending",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }


def format_admin_reminder(reminder):
    expires = reminder.get("expires_at")
    if isinstance(expires, datetime):
        expires_text = format_admin_datetime(expires)
    else:
        expires_text = str(expires or "Unknown")
    lines = [
        "⏰ <b>SUBSCRIPTION EXPIRY REMINDER</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📦 <b>{html_escape(str(reminder.get('title') or reminder.get('product_name') or 'Subscription'))}</b>",
        f"📅 Expires: <b>{html_escape(expires_text)}</b>",
    ]
    if reminder.get("order_code"):
        lines.append(f"🧾 Order: <code>#{html_escape(str(reminder['order_code']))}</code>")
    if reminder.get("user_id"):
        lines.append(f"👤 Customer ID: <code>{int(reminder['user_id'])}</code>")
    if reminder.get("email"):
        lines.append(f"📧 Email: <code>{html_escape(str(reminder['email']))}</code>")
    if reminder.get("custom_message"):
        lines.append("\n📝 <b>Your note</b>\n" + html_escape(str(reminder["custom_message"])))
    lines.append("━━━━━━━━━━━━━━━━━━\nThis subscription expires in about 24 hours.")
    return "\n".join(lines)


async def process_due_reminders(limit: int = 50):
    """Send due admin reminders with an atomic claim to prevent duplicate notices."""
    now = utcnow()
    stale = now - timedelta(minutes=15)
    subscription_reminders_col.update_many(
        {"status": "sending", "claimed_at": {"$lt": stale}},
        {"$set": {"status": "pending", "updated_at": now}},
    )
    due_ids = [
        d["reminder_id"]
        for d in subscription_reminders_col.find(
            {"status": "pending", "remind_at": {"$lte": now}},
            {"_id": 0, "reminder_id": 1},
        ).sort("remind_at", 1).limit(max(1, min(int(limit), 200)))
    ]
    sent = 0
    failed = 0
    for rid in due_ids:
        claimed = subscription_reminders_col.find_one_and_update(
            {"reminder_id": rid, "status": "pending"},
            {"$set": {"status": "sending", "claimed_at": utcnow(), "updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            continue
        try:
            await bot.send_message(
                ADMIN_ID, format_admin_reminder(claimed), parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⏰ Open Reminders", callback_data="adm_reminders")
                ]]),
            )
            subscription_reminders_col.update_one(
                {"reminder_id": rid},
                {"$set": {"status": "sent", "sent_at": utcnow(), "updated_at": utcnow()}, "$unset": {"last_error": "", "claimed_at": ""}},
            )
            sent += 1
        except Exception as exc:
            log.exception("Reminder delivery failed for %s", rid)
            subscription_reminders_col.update_one(
                {"reminder_id": rid},
                {"$set": {"status": "pending", "last_error": str(exc)[:500], "updated_at": utcnow()}, "$inc": {"retry_count": 1}, "$unset": {"claimed_at": ""}},
            )
            failed += 1
    return {"checked": len(due_ids), "sent": sent, "failed": failed}


async def reminder_worker():
    while True:
        try:
            await process_due_reminders()
            await process_fulfillment_escalations(40)
            await process_scheduled_backup()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Background admin worker error")
        await asyncio.sleep(300)


def encrypt_payload(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_payload(doc_or_value) -> str:
    if isinstance(doc_or_value, dict):
        if doc_or_value.get("payload_enc"):
            value = doc_or_value["payload_enc"]
        elif "value" in doc_or_value:  # backward compatibility for old stock
            return str(doc_or_value.get("value", ""))
        else:
            return ""
    else:
        value = str(doc_or_value or "")
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def verify_inventory_encryption_key():
    """Detect an accidental encryption-key/WEBHOOK_SECRET rotation before stock is delivered blank."""
    sentinel_id = "inventory_encryption_sentinel"
    sentinel_plain = "telegram-shop-inventory-key-v1"
    doc = settings_col.find_one({"_id": sentinel_id}, {"value": 1})
    if doc and doc.get("value"):
        try:
            plain = _fernet.decrypt(str(doc["value"]).encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                "Inventory encryption key mismatch. Restore the previous INVENTORY_ENCRYPTION_KEY "
                "(or previous WEBHOOK_SECRET when using the derived fallback) before serving orders."
            ) from exc
        if plain != sentinel_plain:
            raise RuntimeError("Inventory encryption sentinel is invalid; refusing to serve encrypted stock.")
        return

    # Older databases predate the sentinel. Verify one encrypted record first, if present,
    # so a changed key is caught before the current key is trusted and recorded.
    sample = digital_inventory_col.find_one({"payload_enc": {"$exists": True, "$ne": ""}}, {"payload_enc": 1})
    if sample:
        try:
            _fernet.decrypt(str(sample["payload_enc"]).encode())
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                "Existing inventory cannot be decrypted with the configured key. "
                "Restore the original INVENTORY_ENCRYPTION_KEY/WEBHOOK_SECRET."
            ) from exc

    settings_col.update_one(
        {"_id": sentinel_id},
        {"$setOnInsert": {"value": encrypt_payload(sentinel_plain), "created_at": utcnow()}},
        upsert=True,
    )


def mask_secret(value: str) -> str:
    value = str(value or "")
    if len(value) <= 6:
        return "•" * max(4, len(value))
    return value[:3] + "•" * min(12, len(value) - 6) + value[-3:]


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not secret:
        return True
    code = re.sub(r"\D", "", code or "")
    if len(code) != 6:
        return False
    try:
        key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    except Exception:
        return False
    counter = int(time.time()) // 30
    for offset in range(-window, window + 1):
        msg = struct.pack(">Q", counter + offset)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        pos = digest[-1] & 0x0F
        num = (struct.unpack(">I", digest[pos:pos+4])[0] & 0x7FFFFFFF) % 1000000
        if hmac.compare_digest(f"{num:06d}", code):
            return True
    return False



def normalize_totp_secret(secret: str) -> str:
    return re.sub(r"[^A-Z2-7]", "", str(secret or "").upper())


def generate_totp(secret: str):
    secret = normalize_totp_secret(secret)
    if not secret:
        raise ValueError("Missing TOTP secret")
    try:
        key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    except Exception as exc:
        raise ValueError("Invalid TOTP secret") from exc
    now = int(time.time())
    counter = now // 30
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    pos = digest[-1] & 0x0F
    num = (struct.unpack(">I", digest[pos:pos+4])[0] & 0x7FFFFFFF) % 1000000
    remaining = 30 - (now % 30)
    return f"{num:06d}", remaining


def parse_account_inventory_payload(payload: str):
    """
    Supports two formats:

    New structured JSON:
      {"email":"...","password":"...","profile":"...","pin":"...","totp_secret":"..."}

    Legacy pipe format:
      login|password|TOTP_SECRET
    """
    text = str(payload or "").strip()
    if not text:
        return None

    # Compatibility fix for older structured inventory entries that were saved as
    #   VariantLabel|{"email":...,"password":...}
    # instead of storing only the JSON payload. The variant itself is already stored
    # separately in digital_inventory.variant_id, so strip this accidental prefix
    # before parsing the account fields. This repairs old records at read/delivery
    # time without exposing or rewriting their encrypted payloads.
    if "|" in text and not text.startswith("{"):
        _prefix, _rest = text.split("|", 1)
        if _rest.lstrip().startswith("{"):
            text = _rest.strip()

    # New structured format.
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except Exception:
            data = None
        if isinstance(data, dict):
            clean = {
                "email": str(data.get("email") or "").strip(),
                "password": str(data.get("password") or "").strip(),
                "profile": str(data.get("profile") or "").strip(),
                "pin": str(data.get("pin") or "").strip(),
                "username": str(data.get("username") or "").strip(),
                "totp_secret": normalize_totp_secret(data.get("totp_secret") or ""),
            }
            if any(clean.values()):
                return clean

    # Legacy format remains supported.
    parts = [x.strip() for x in text.split("|")]
    if len(parts) >= 2:
        result = {
            "email": parts[0],
            "password": parts[1],
            "profile": "",
            "pin": "",
            "username": "",
            "totp_secret": "",
        }
        if len(parts) >= 3:
            possible_secret = normalize_totp_secret(parts[-1])
            try:
                if possible_secret:
                    generate_totp(possible_secret)
                    result["totp_secret"] = possible_secret
                    # Keep any middle values as a generic profile only for legacy entries.
                    if len(parts) > 3:
                        result["profile"] = " | ".join(parts[2:-1])
            except ValueError:
                result["profile"] = " | ".join(parts[2:])
        return result

    return None


def split_otp_inventory_payload(payload: str):
    data = parse_account_inventory_payload(payload)
    if not data:
        return None
    secret = normalize_totp_secret(data.get("totp_secret") or "")
    if len(secret) < 8:
        return None
    try:
        generate_totp(secret)
    except ValueError:
        return None
    return data, secret


def format_visible_credentials(data):
    # New structured data.
    if isinstance(data, dict):
        rows = []
        if data.get("email"):
            rows.append(f"📧 <b>Email</b>\n<code>{html_escape(data['email'])}</code>")
        if data.get("username"):
            rows.append(f"👤 <b>Username / ID</b>\n<code>{html_escape(data['username'])}</code>")
        if data.get("password"):
            rows.append(f"🔑 <b>Password</b>\n<code>{html_escape(data['password'])}</code>")
        if data.get("profile"):
            rows.append(f"🧑‍💻 <b>Profile</b>\n<code>{html_escape(data['profile'])}</code>")
        if data.get("pin"):
            rows.append(f"🔢 <b>PIN</b>\n<code>{html_escape(data['pin'])}</code>")
        return "\n\n".join(rows) if rows else "<i>No visible account details configured.</i>"

    # Legacy list fallback.
    if len(data) == 2:
        return (
            f"👤 ID: <code>{html_escape(data[0])}</code>\n"
            f"🔑 Password: <code>{html_escape(data[1])}</code>"
        )
    return "<code>" + html_escape(" | ".join(data)) + "</code>"



def detect_image_content_type(content: bytes):
    """Allow only raster image formats we can safely serve back from our own origin."""
    data = bytes(content or b"")
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def safe_image_url(value: str):
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("/media/") or value.startswith(("https://", "http://")):
        return value[:2000]
    raise HTTPException(400, "Image URL must use http:// or https://")


def cloudinary_credentials():
    # Separate variables are safer when manually configuring Vercel because
    # special characters in an API secret cannot confuse URL parsing.
    if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
        return CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

    if not CLOUDINARY_URL:
        return None

    parsed = urlparse(CLOUDINARY_URL)
    if parsed.scheme != "cloudinary" or not parsed.username or not parsed.password or not parsed.hostname:
        raise HTTPException(500, "Invalid CLOUDINARY_URL")

    return parsed.hostname, parsed.username, parsed.password


def cloudinary_upload(content: bytes, filename: str, public_id: str):
    creds = cloudinary_credentials()
    if not creds:
        return None
    cloud_name, api_key, api_secret = creds
    boundary = "----Fattle" + secrets.token_hex(12)
    parts = []
    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("public_id", public_id)
    field("overwrite", "true")
    field("folder", "fattle-shop")
    safe_name = Path(filename or "image.jpg").name.replace('"', '')
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    auth = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    req = UrlRequest(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
    except Exception as exc:
        detail = str(exc)
        try:
            if hasattr(exc, "read"):
                raw = exc.read().decode("utf-8", "replace")
                if raw:
                    detail = raw[:1000]
        except Exception:
            pass
        raise HTTPException(502, f"Cloudinary upload failed: {detail}")
    return {"secure_url": result.get("secure_url") or result.get("url"), "public_id": result.get("public_id")}


def migrate_legacy_inventory_batch(limit: int = 500):
    """Gradually remove legacy plaintext inventory without making startup unbounded."""
    migrated = 0
    cursor = digital_inventory_col.find(
        {"payload_enc": {"$exists": False}, "value": {"$exists": True}},
        {"_id": 1, "value": 1},
    ).limit(max(1, min(int(limit), 2000)))
    for doc in cursor:
        plain = str(doc.get("value") or "")
        result = digital_inventory_col.update_one(
            {"_id": doc["_id"], "payload_enc": {"$exists": False}},
            {"$set": {"payload_enc": encrypt_payload(plain)}, "$unset": {"value": ""}},
        )
        migrated += int(result.modified_count)
    if migrated:
        log.info("Migrated %s legacy plaintext inventory records to encrypted payloads", migrated)
    return migrated


def _create_required_indexes():
    """Create/verify indexes only when the schema version changes, not on every cold start."""
    users_col.create_index("user_id", unique=True)
    products_col.create_index("id", unique=True)
    orders_col.create_index("order_code", unique=True)
    orders_col.create_index([("user_id", 1), ("created_at", -1)])
    orders_col.create_index([("created_at", -1), ("_id", -1)])
    orders_col.create_index([("user_id", 1), ("_id", -1)])
    orders_col.create_index("telegram_event_id", unique=True, sparse=True)
    credit_log_col.create_index([("user_id", 1), ("created_at", -1)])
    credit_log_col.create_index([("user_id", 1), ("_id", -1)])
    digital_inventory_col.create_index([("product_id", 1), ("variant_id", 1), ("sold", 1)])
    product_images_col.create_index("product_id", unique=True)
    referrals_col.create_index("referred_id", unique=True)
    wishlists_col.create_index([("user_id", 1), ("product_id", 1)], unique=True)
    login_attempts_col.create_index("expires_at", expireAfterSeconds=0)
    methods_col.create_index("id", unique=True)
    method_images_col.create_index("method_id", unique=True)
    method_gallery_col.create_index("image_id", unique=True)
    method_gallery_col.create_index([("method_id", 1), ("created_at", 1)])
    method_purchases_col.create_index([("user_id", 1), ("method_id", 1)], unique=True)
    broadcasts_col.create_index("broadcast_id", unique=True)
    broadcasts_col.create_index("created_at")
    otp_events_col.create_index([("user_id", 1), ("created_at", -1)])
    otp_events_col.create_index("created_at", expireAfterSeconds=60 * 60 * 24 * 90)
    subscription_reminders_col.create_index("reminder_id", unique=True)
    subscription_reminders_col.create_index([("status", 1), ("remind_at", 1)])
    subscription_reminders_col.create_index([("order_code", 1), ("item_index", 1)])
    purchase_key_attempts_col.create_index("expires_at", expireAfterSeconds=0)
    purchase_key_attempts_col.create_index([("user_id", 1), ("product_id", 1), ("created_at", -1)])
    fulfillment_templates_col.create_index("id", unique=True)
    fulfillment_templates_col.create_index([("active", 1), ("product_id", 1), ("name", 1)])

def init_db():
    # A single lightweight metadata read replaces dozens of create_index round-trips on every
    # Vercel cold start. Existing hardened installs already have the encryption sentinel, which was
    # created only after the old init_db finished its index setup, so they can adopt this marker
    # without re-checking every index on the first deployment of this speed build.
    meta = {
        d.get("_id"): d
        for d in settings_col.find(
            {"_id": {"$in": ["db_schema_version", "inventory_encryption_sentinel"]}},
            {"value": 1},
        )
    }
    marker = meta.get("db_schema_version") or {}
    if marker.get("value") != DB_SCHEMA_VERSION:
        # Schema changes should run index creation once for the new version. create_index is idempotent.
        _create_required_indexes()
        if "inventory_encryption_sentinel" not in meta:
            migrate_legacy_inventory_batch(500)
        verify_inventory_encryption_key()
        settings_col.update_one(
            {"_id": "db_schema_version"},
            {"$set": {"value": DB_SCHEMA_VERSION, "updated_at": utcnow()}},
            upsert=True,
        )
    else:
        # Keep the encryption safety check on every process start; it is only one indexed lookup.
        verify_inventory_encryption_key()


def get_setting(key, default=None):
    doc = settings_col.find_one({"_id": key})
    return doc.get("value", default) if doc else default


def set_setting(key, value):
    settings_col.update_one({"_id": key}, {"$set": {"value": value, "updated_at": utcnow()}}, upsert=True)


_required_chat_cache = {"value": None, "expires": 0.0}

def required_chat_id():
    if REQUIRED_CHAT_ID_ENV:
        raw = REQUIRED_CHAT_ID_ENV
    else:
        now = time.monotonic()
        if _required_chat_cache["expires"] > now:
            return _required_chat_cache["value"]
        raw = get_setting("required_chat_id", "")
    if raw in (None, ""):
        value = None
    else:
        try:
            value = int(raw)
        except Exception:
            value = raw
    if not REQUIRED_CHAT_ID_ENV:
        _required_chat_cache["value"] = value
        _required_chat_cache["expires"] = time.monotonic() + 60
    return value


def upsert_user(user):
    if not user:
        return
    users_col.update_one(
        {"user_id": user.id},
        {
            "$set": {
                "username": user.username,
                "full_name": user.full_name,
                "last_seen": utcnow(),
            },
            "$setOnInsert": {"credits": 0, "created_at": utcnow(), "language": DEFAULT_LANGUAGE},
        },
        upsert=True,
    )


def get_balance(uid):
    doc = users_col.find_one({"user_id": int(uid)}, {"credits": 1})
    return int(doc.get("credits", 0)) if doc else 0


def adjust_credit(uid, amount, admin_id=None, set_to=None, note="Admin"):
    """Atomically adjust a balance so concurrent deductions can never cross below zero."""
    uid = int(uid)
    if set_to is not None:
        new_value = int(set_to)
        if new_value < 0:
            raise ValueError("Balance cannot go below zero.")
        before = users_col.find_one({"user_id": uid}, {"credits": 1}) or {}
        old = int(before.get("credits", 0))
        doc = users_col.find_one_and_update(
            {"user_id": uid},
            {"$set": {"credits": new_value}, "$setOnInsert": {"created_at": utcnow()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        credit_log_col.insert_one({
            "user_id": uid, "amount": new_value - old, "action": "set",
            "admin_id": int(admin_id) if admin_id else None, "note": note, "created_at": utcnow()
        })
        return int(doc.get("credits", 0))

    amount = int(amount)
    query = {"user_id": uid}
    # For deductions, include the balance condition in the same atomic update.
    if amount < 0:
        query["credits"] = {"$gte": -amount}
    doc = users_col.find_one_and_update(
        query,
        {"$inc": {"credits": amount}, "$setOnInsert": {"created_at": utcnow()}},
        upsert=(amount >= 0),
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        raise ValueError("Balance cannot go below zero.")
    credit_log_col.insert_one({
        "user_id": uid, "amount": amount, "action": "adjust",
        "admin_id": int(admin_id) if admin_id else None, "note": note, "created_at": utcnow()
    })
    return int(doc.get("credits", 0))


def normalize_variants(product):
    variants = product.get("variants") or []
    default_days = max(0, int(product.get("subscription_days", 0) or 0))
    if not variants:
        variants = [{
            "id": "default", "label": "Standard", "price": int(product.get("price", 0)),
            "low_stock": int(product.get("low_stock", DEFAULT_LOW_STOCK)),
            "subscription_days": default_days,
        }]
    out = []
    for v in variants:
        out.append({
            "id": str(v.get("id") or slugify(v.get("label", "variant"))),
            "label": str(v.get("label") or "Standard"),
            "price": int(v.get("price", product.get("price", 0))),
            "low_stock": max(0, int(v.get("low_stock", DEFAULT_LOW_STOCK))),
            "subscription_days": max(0, int(v.get("subscription_days", default_days) or 0)),
        })
    return out


def get_products(active_only=True):
    query = {"delivery_type": "digital"}
    if active_only:
        query["active"] = True
    rows = list(products_col.find(query, {"_id": 0}))

    # One aggregation replaces per-product/per-variant count queries and keeps the storefront fast.
    stock_counts = {}
    product_ids = [str(p.get("id")) for p in rows]
    for row in digital_inventory_col.aggregate([
        {"$match": {"sold": False, "product_id": {"$in": product_ids}}},
        {"$group": {"_id": {"product_id": "$product_id", "variant_id": {"$ifNull": ["$variant_id", "__legacy__"]}}, "count": {"$sum": 1}}},
    ]):
        key = (str(row.get("_id", {}).get("product_id") or ""), str(row.get("_id", {}).get("variant_id") or "__legacy__"))
        stock_counts[key] = int(row.get("count", 0))

    for p in rows:
        variants = normalize_variants(p)
        fulfillment_mode = str(p.get("fulfillment_mode") or "instant")
        unlimited = fulfillment_mode in {"email", "manual", "login_assist"}
        total = 0
        for v in variants:
            if unlimited:
                stock = 20
            else:
                stock = stock_counts.get((str(p["id"]), str(v["id"])), 0)
                if v["id"] == "default":
                    stock += stock_counts.get((str(p["id"]), "__legacy__"), 0)
            v["stock"] = stock
            total += stock
        p["variants"] = variants
        p["stock"] = total
        p["unlimited_stock"] = unlimited
        p["fulfillment_mode"] = fulfillment_mode
        p["purchase_key_required"] = bool(p.get("purchase_key_required", False))
        p["purchase_key_configured"] = bool(p.get("purchase_key_hash"))
        if not p.get("price") and variants:
            p["price"] = min(v["price"] for v in variants)
        p["badge_new"] = bool(p.get("badge_new", False))
        p["bestseller"] = bool(p.get("bestseller", False))
    rows.sort(key=lambda x: (not bool(x.get("featured", False)), not bool(x.get("bestseller", False)), x.get("name", "").lower()))
    return rows


def public_product(product, include_admin_fields=False):
    """Return a safe product copy. Purchase-key hashes never leave the server."""
    safe = dict(product)
    safe.pop("purchase_key_hash", None)
    safe["purchase_key_required"] = bool(product.get("purchase_key_required", False))
    safe["purchase_key_configured"] = bool(product.get("purchase_key_hash"))
    if not include_admin_fields:
        safe.pop("reminder_note", None)
        safe.pop("purchase_key_configured", None)
    return safe


def product_map():
    return {p["id"]: p for p in get_products(True)}


def variant_for(product, variant_id):
    variants = normalize_variants(product)
    wanted = str(variant_id or "default")
    for v in variants:
        if str(v["id"]) == wanted:
            return v
    return None


def shop_token(uid, ttl=21600):
    """Short-lived API session used after a Mini App launch is authenticated."""
    exp = int(time.time()) + ttl
    body = f"{int(uid)}:{exp}"
    sig = hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_shop_token(uid, token):
    try:
        exp_s, sig = str(token).split(".", 1)
        exp = int(exp_s)
        if exp < int(time.time()):
            return False
        body = f"{int(uid)}:{exp}"
        expected = hmac.new(WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def _shop_launch_key():
    # Purpose-separate the durable launcher from the normal 6-hour API session signature.
    return hmac.new(WEBHOOK_SECRET.encode(), b"shop-launch-key-v1", hashlib.sha256).digest()


def shop_launch_token(uid):
    """Durable, non-guessable launcher for Telegram reply-keyboard Mini Apps.

    Telegram reply-keyboard Mini Apps do not provide user identity to the webpage. The durable
    launcher therefore only bootstraps a fresh short-lived shop session; API calls never use it
    directly. SHOP_LAUNCH_VERSION can be changed to revoke every existing launcher at once.
    """
    uid = int(uid)
    body = f"{SHOP_LAUNCH_VERSION}:{uid}:shop"
    mac = hmac.new(_shop_launch_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{uid}.{mac}"


def verify_shop_launch_token(token):
    try:
        uid_s, mac = str(token or "").split(".", 1)
        uid = int(uid_s)
        if uid <= 0 or len(mac) != 64:
            return None
        body = f"{SHOP_LAUNCH_VERSION}:{uid}:shop"
        expected = hmac.new(_shop_launch_key(), body.encode(), hashlib.sha256).hexdigest()
        return uid if hmac.compare_digest(mac, expected) else None
    except Exception:
        return None


def shop_url(uid):
    """Legacy short-lived URL retained for compatibility with already-generated messages."""
    return f"{PUBLIC_URL}/?uid={int(uid)}&sig={shop_token(uid)}"


def direct_shop_url(uid, wishlist=False):
    """Stable one-tap launcher. /index.html is a Vercel CDN asset; APIs remain protected."""
    url = f"{PUBLIC_URL}/index.html?launch={quote(shop_launch_token(uid))}"
    if wishlist:
        url += "&wishlist=1"
    return url


def fresh_shop_markup(uid, wishlist=False):
    # Despite the historical function name, this is now a durable one-tap launcher. The webpage
    # immediately exchanges it for a fresh short-lived API session and removes it from its URL.
    url = direct_shop_url(uid, wishlist=wishlist)
    if wishlist:
        text = "🛍 Open Wishlist" if get_user_language(uid) == "en" else "🛍 Buka Favorit"
    else:
        text = tr(uid, "shop_methods")
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]])


_membership_cache = {}

async def user_is_member(uid, force=False):
    uid = int(uid)
    chat_id = required_chat_id()
    if not chat_id:
        return uid == ADMIN_ID
    now = time.monotonic()
    cached = _membership_cache.get(uid)
    # Cache successful membership briefly. Negative results are intentionally not cached so a user
    # who just joined can verify immediately. This also removes the duplicate Telegram API call
    # between launcher exchange and shop-data loading.
    if not force and cached and cached > now:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=uid)
        status = str(getattr(member, "status", "")).lower()
        ok = any(x in status for x in ("creator", "administrator", "member"))
        if "restricted" in status and bool(getattr(member, "is_member", False)):
            ok = True
        if ok:
            _membership_cache[uid] = now + MEMBERSHIP_CACHE_SECONDS
        else:
            _membership_cache.pop(uid, None)
        return ok
    except Exception as exc:
        log.warning("Membership check failed for %s: %s", uid, exc)
        return False


def join_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Join required group", url=REQUIRED_CHAT_INVITE_URL)],
        [InlineKeyboardButton(text="✅ I joined — Verify", callback_data="verify_join")],
    ])


async def gate_message(m: Message):
    upsert_user(m.from_user)
    if await user_is_member(m.from_user.id):
        await maybe_award_referral(m.from_user.id)
        return True
    chat_id = required_chat_id()
    extra = "\n\n⚙️ Admin must run /bindgroup inside the required group first." if not chat_id and m.from_user.id == ADMIN_ID else ""
    await m.answer(
        "🔒 <b>Join required</b>\n\nJoin our Telegram group to unlock the shop, balance, orders, wishlist and referral menu."
        + extra,
        parse_mode="HTML",
        reply_markup=join_markup(),
    )
    await m.answer("Menu locked until membership is verified.", reply_markup=ReplyKeyboardRemove())
    return False


async def gate_callback(q: CallbackQuery):
    if await user_is_member(q.from_user.id):
        await maybe_award_referral(q.from_user.id)
        return True
    await q.answer("Join the required group first.", show_alert=True)
    if q.message:
        await q.message.answer("🔒 Join the group, then tap Verify.", reply_markup=join_markup())
    return False


def record_pending_referral(referred_id, referrer_id):
    referred_id, referrer_id = int(referred_id), int(referrer_id)
    if referred_id == referrer_id:
        return
    existing = referrals_col.find_one({"referred_id": referred_id})
    if existing:
        return
    referrals_col.update_one(
        {"referred_id": referred_id},
        {"$setOnInsert": {
            "referred_id": referred_id,
            "referrer_id": referrer_id,
            "status": "pending_join",
            "created_at": utcnow(),
        }},
        upsert=True,
    )


async def maybe_award_referral(referred_id):
    referred_id = int(referred_id)
    ref = referrals_col.find_one({"referred_id": referred_id, "status": "pending_join"})
    if not ref:
        return False
    if not await user_is_member(referred_id):
        return False
    referrer_id = int(ref["referrer_id"])
    if referrer_id == referred_id:
        return False
    result = referrals_col.update_one(
        {"_id": ref["_id"], "status": "pending_join"},
        {"$set": {"status": "awarded", "awarded_at": utcnow(), "credit": REFERRAL_CREDIT}},
    )
    if result.modified_count != 1:
        return False
    new_balance = adjust_credit(referrer_id, REFERRAL_CREDIT, note=f"Referral {referred_id}")
    users_col.update_one({"user_id": referred_id}, {"$set": {"referred_by": referrer_id}})
    try:
        await bot.send_message(
            referrer_id,
            f"🎁 <b>Referral reward!</b>\n\nYour referral joined the required group.\n+<b>{REFERRAL_CREDIT} credits</b>\nNew balance: <b>{money(new_balance)}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return True


async def get_bot_username():
    if BOT_USERNAME:
        return BOT_USERNAME
    me = await bot.get_me()
    return me.username


def shop_keyboard(uid):
    rows = [
        [KeyboardButton(text=tr(uid, "start"))],
        # One tap opens the Mini App directly. The durable launcher is exchanged inside the
        # webpage for a fresh 6-hour API session, so this persistent keyboard never goes stale.
        [
            KeyboardButton(text=tr(uid, "shop_methods"), web_app=WebAppInfo(url=direct_shop_url(uid))),
            KeyboardButton(text=tr(uid, "temp_mail")),
        ],
        [KeyboardButton(text=tr(uid, "downloader"))],
        [KeyboardButton(text=tr(uid, "balance")), KeyboardButton(text=tr(uid, "buy_credits"))],
        [KeyboardButton(text=tr(uid, "orders")), KeyboardButton(text=tr(uid, "otp"))],
        [KeyboardButton(text=tr(uid, "wishlist")), KeyboardButton(text=tr(uid, "refer"))],
        [KeyboardButton(text=tr(uid, "language")), KeyboardButton(text=tr(uid, "help"))],
    ]
    if int(uid) == ADMIN_ID:
        rows.append([KeyboardButton(text=tr(uid, "admin"))])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose an option…" if get_user_language(uid) == "en" else "Pilih opsi…",
    )


def admin_keyboard(uid):
    """Persistent reply keyboard used while the owner is working in Telegram Admin."""
    if int(uid) != ADMIN_ID:
        return shop_keyboard(uid)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Customer Menu")],
            [KeyboardButton(text="📥 Action Center")],
            [KeyboardButton(text="🧾 Orders"), KeyboardButton(text="🛍 Products")],
            [KeyboardButton(text="📦 Inventory"), KeyboardButton(text="👥 Customers")],
            [KeyboardButton(text="⏰ Reminders"), KeyboardButton(text="📣 Broadcast")],
            [KeyboardButton(text="📊 Dashboard"), KeyboardButton(text="⚙️ More tools")],
            [KeyboardButton(text="🌐 Web Admin Panel", web_app=WebAppInfo(url=f"{PUBLIC_URL}/admin"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Admin controls…",
    )


ADMIN_SECTION_TITLES = {
    "main": "Admin",
    "action": "Action Center",
    "orders": "Orders",
    "products": "Products",
    "inventory": "Inventory",
    "customers": "Customers",
    "reminders": "Reminders",
    "broadcast": "Broadcast",
    "dashboard": "Dashboard",
    "more": "More tools",
    "methods": "Methods",
    "analytics": "Analytics",
    "fulfillment": "Fulfillment",
    "keys": "Purchase keys",
    "referrals": "Referrals",
    "security": "Security",
    "templates": "Delivery templates",
    "backups": "Backups",
    "features": "Feature controls",
}

# Context-aware persistent keyboards. They contain only shortcuts for the section that
# is currently open, so the bottom Telegram keyboard mirrors the inline admin view.
ADMIN_SECTION_ROWS = {
    "action": [
        ["🛠 Pending Requests", "📧 Pending Email"],
        ["🧾 All Orders", "⏱ Check Waiting Orders"],
        ["📦 Inventory", "⏰ Reminders"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "orders": [
        ["🔄 Refresh Orders"],
        ["🛠 Pending Requests", "📧 Pending Email"],
        ["📥 Action Center"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "products": [
        ["🔄 Refresh Products", "➕ New Product"],
        ["📦 Inventory", "🔐 Purchase Keys"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "inventory": [
        ["🔄 Refresh Inventory"],
        ["🛍 Products"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "customers": [
        ["🔎 Search Customer", "🔄 Refresh Customers"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "reminders": [
        ["📋 Upcoming Reminders", "➕ Manual Reminder"],
        ["⚙️ Product Expiry", "▶️ Process Due"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "broadcast": [
        ["➕ New Broadcast", "🔄 Refresh Broadcast"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "dashboard": [
        ["🔄 Refresh Dashboard", "📊 Analytics"],
        ["📥 Action Center"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "more": [
        ["📚 Methods", "📊 Analytics"],
        ["📦 Fulfillment Settings", "🔐 Purchase Keys"],
        ["🔗 Referrals", "🔐 Security"],
        ["🧾 Delivery Templates", "💾 Backups"],
        ["🧩 Feature Controls"],
        ["⬅️ Admin Menu", "🏠 Customer Menu"],
    ],
    "methods": [
        ["🔄 Refresh Methods", "➕ New Method"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "analytics": [
        ["🔄 Refresh Analytics", "📊 Dashboard"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "fulfillment": [
        ["🛠 Pending Requests", "📧 Pending Email"],
        ["⚙️ Product Modes"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "keys": [
        ["🔄 Refresh Purchase Keys", "🛍 Products"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "referrals": [
        ["🔄 Refresh Referrals", "👥 Customers"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "security": [
        ["🔄 Refresh Security", "🔗 Refresh Webhook"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "templates": [
        ["➕ New Template", "🔄 Refresh Templates"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "backups": [
        ["⬇️ Export Backup", "🔄 Refresh Backups"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
    "features": [
        ["🔐 Purchase Keys", "⏰ Reminders"],
        ["📦 Fulfillment Settings"],
        ["⬅️ More Tools", "🏠 Customer Menu"],
    ],
}

_ADMIN_KEYBOARD_SECTION = {}

def admin_section_keyboard(uid, section="main"):
    if int(uid) != ADMIN_ID:
        return shop_keyboard(uid)
    if section == "main" or section not in ADMIN_SECTION_ROWS:
        return admin_keyboard(uid)
    rows = [[KeyboardButton(text=label) for label in row] for row in ADMIN_SECTION_ROWS[section]]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=f"{ADMIN_SECTION_TITLES.get(section, 'Admin')} controls…",
    )


async def sync_admin_reply_keyboard(target, section="main", force=False):
    """Switch Telegram's persistent bottom keyboard to match the open admin section."""
    uid = getattr(getattr(target, "from_user", None), "id", None)
    message = getattr(target, "message", None) or target
    if uid != ADMIN_ID or not hasattr(message, "answer"):
        return
    if not force and _ADMIN_KEYBOARD_SECTION.get(uid) == section:
        return
    _ADMIN_KEYBOARD_SECTION[uid] = section
    title = ADMIN_SECTION_TITLES.get(section, "Admin")
    await message.answer(
        f"⌨️ <b>{html_escape(title)}</b> controls",
        parse_mode="HTML",
        reply_markup=admin_section_keyboard(uid, section),
    )


class _AdminReplyCallback:
    """Small adapter so reply-keyboard buttons can reuse the existing admin callback views."""
    def __init__(self, message: Message, data: str):
        self.from_user = message.from_user
        self.message = message
        self.data = data

    async def answer(self, *args, **kwargs):
        return None


def admin_reply_callback(message: Message, data: str):
    return _AdminReplyCallback(message, data)


def action_menu(uid, is_admin=False):
    rows = [
        [InlineKeyboardButton(text=tr(uid, "start"), callback_data="menu_restart")],
        [InlineKeyboardButton(text=tr(uid, "shop_methods"), web_app=WebAppInfo(url=direct_shop_url(uid)))],
        [
            InlineKeyboardButton(text=tr(uid, "balance"), callback_data="menu_balance"),
            InlineKeyboardButton(text=("📦 Orders & Receipts" if get_user_language(uid) == "en" else "📦 Pesanan & Struk"), callback_data="menu_orders"),
        ],
        [InlineKeyboardButton(text=("🔐 Get OTP" if get_user_language(uid) == "en" else "🔐 Ambil OTP"), callback_data="menu_otp")],
        [
            InlineKeyboardButton(text=tr(uid, "wishlist"), callback_data="menu_wishlist"),
            InlineKeyboardButton(text=tr(uid, "refer"), callback_data="menu_referral"),
        ],
        [InlineKeyboardButton(text=tr(uid, "language"), callback_data="menu_language")],
        [InlineKeyboardButton(text=("ℹ️ Help" if get_user_language(uid) == "en" else "ℹ️ Bantuan"), callback_data="menu_help")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text=("🛠 Telegram Admin" if get_user_language(uid) == "en" else "🛠 Admin Telegram"), callback_data="admin_enter")])
        rows.append([InlineKeyboardButton(text="🌐 Web Admin", url=f"{PUBLIC_URL}/admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def language_markup(uid: int):
    current = get_user_language(uid)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ " if current == "en" else "") + "🇬🇧 English", callback_data="lang:en")],
        [InlineKeyboardButton(text=("✅ " if current == "id" else "") + "🇮🇩 Bahasa Indonesia", callback_data="lang:id")],
    ])



def buy_credit_url(uid: int):
    if not OWNER_USERNAME:
        return None
    text = (
        f"Hello, I want to buy credits for {SHOP_NAME}.\n"
        f"My Telegram ID: {uid}\n"
        f"Rates: {CREDIT_RATE_INR} | {CREDIT_RATE_USD}\n"
        f"Please tell me the payment method."
    )
    return f"https://t.me/{OWNER_USERNAME}?text={quote(text)}"


def buy_credit_markup(uid: int):
    url = buy_credit_url(uid)
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Contact Admin to Buy Credits", url=url)
    ]])


def support_markup(order_code=None):
    if not OWNER_USERNAME:
        return None
    text = f"Hello, I need support for order #{order_code}" if order_code else "Hello, I need shop support"
    url = f"https://t.me/{OWNER_USERNAME}?text={quote(text)}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Contact support", url=url)]])


def delivery_markup(order):
    rows = []
    code = str(order.get("order_code") or "")
    for di, delivery in enumerate(order.get("digital_delivery", [])):
        if not delivery.get("otp_enabled"):
            continue
        price = int(delivery.get("otp_price") or OTP_PRICE)
        count = len(delivery.get("items_enc") or delivery.get("items") or [])
        for ii in range(count):
            label = f"🔐 Get OTP — {price} credits"
            if count > 1:
                label = f"🔐 OTP #{ii+1} — {price} credits"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"paidotp:{code}:{di}:{ii}")])
    if OWNER_USERNAME:
        text = f"Hello, I need support for order #{code}" if code else "Hello, I need shop support"
        rows.append([InlineKeyboardButton(text="💬 Contact support", url=f"https://t.me/{OWNER_USERNAME}?text={quote(text)}")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_home(m: Message):
    if not await gate_message(m):
        return
    is_admin = m.from_user.id == ADMIN_ID
    if is_admin:
        _ADMIN_KEYBOARD_SECTION.pop(m.from_user.id, None)
    await m.answer(
        f"⚡ <b>{SHOP_NAME}</b>\n\n"
        f"💳 Balance: <b>{money(get_balance(m.from_user.id))}</b>\n"
        f"🆔 Customer ID: <code>{m.from_user.id}</code>\n\n"
        + tr(m.from_user.id, "home_choose"),
        parse_mode="HTML",
        reply_markup=action_menu(m.from_user.id, is_admin),
    )
    await m.answer(tr(m.from_user.id, "menu_unlocked"), reply_markup=shop_keyboard(m.from_user.id))


async def run_start_flow(m: Message):
    upsert_user(m.from_user)
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            record_pending_referral(m.from_user.id, int(parts[1][4:]))
        except Exception:
            pass
    await send_home(m)


@dp.message(CommandStart())
async def start(m: Message):
    await run_start_flow(m)


@dp.message(F.text.in_({"🔄 Start / Restart", "🔄 Mulai / Ulangi"}))
async def restart_button(m: Message):
    # Reply-keyboard buttons send normal text, so explicitly route this text
    # through the same logic used by /start.
    await run_start_flow(m)


def temp_mail_menu_markup():
    # Legacy inline menu kept for old messages that may still have callback buttons.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Temp Mail Menu", callback_data="tmpmail_menu")],
    ])


def temp_mail_keyboard(uid):
    """Persistent bottom keyboard used while the customer is inside Temp Mail."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Create Mail"), KeyboardButton(text="📥 Received Mail")],
            [KeyboardButton(text="✏️ Custom Mail"), KeyboardButton(text="🔐 Login Old Mail")],
            [KeyboardButton(text="🪪 Mail ID & Password"), KeyboardButton(text="💾 Saved Mails")],
            [KeyboardButton(text="🔄 Change Mail")],
            [KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Temp Mail options…",
    )


def _legacy_temp_mail_credentials(uid: int):
    """Read the pre-offload Vercel temp-mail fields only for one-time migration."""
    doc = users_col.find_one(
        {"user_id": int(uid)},
        {"temp_mail_address": 1, "temp_mail_password_enc": 1},
    ) or {}
    address = str(doc.get("temp_mail_address") or "").strip().lower()
    password = decrypt_payload(doc.get("temp_mail_password_enc") or "")
    if not address or not password:
        return None
    return address, password


async def _get_temp_mail_current(uid: int):
    """Current mailbox metadata now lives on Render/MongoDB."""
    try:
        data = await temp_mail_api("/api/mail/current", {"user_id": int(uid)})
        if data.get("exists"):
            address = str(data.get("address") or "").strip().lower()
            if address:
                return address
    except Exception:
        log.info("Could not fetch current temp mail from Render", exc_info=True)

    # One-time migration path for a mailbox saved by an older Vercel version.
    legacy = _legacy_temp_mail_credentials(uid)
    if legacy:
        try:
            await temp_mail_api(
                "/api/mail/saved/save",
                {
                    "user_id": int(uid),
                    "address": legacy[0],
                    "password": legacy[1],
                    "source": "vercel-migration",
                },
            )
            return legacy[0]
        except Exception:
            log.info("Could not migrate legacy temp mail to Render", exc_info=True)
    return None


async def _get_temp_mail_credentials(uid: int):
    """Fetch current credentials from Render only when the UI truly needs them."""
    try:
        data = await temp_mail_api("/api/mail/credentials", {"user_id": int(uid)})
        if data.get("exists"):
            address = str(data.get("address") or "").strip().lower()
            password = str(data.get("password") or "")
            if address and password:
                return address, password
    except Exception:
        log.info("Could not fetch temp-mail credentials from Render", exc_info=True)

    # One-time backward-compatibility migration.
    legacy = _legacy_temp_mail_credentials(uid)
    if legacy:
        try:
            await temp_mail_api(
                "/api/mail/saved/save",
                {
                    "user_id": int(uid),
                    "address": legacy[0],
                    "password": legacy[1],
                    "source": "vercel-migration",
                },
            )
            return legacy
        except Exception:
            log.info("Could not migrate legacy temp mail credentials", exc_info=True)
    return None


def _save_temp_mail_credentials(uid: int, address: str, password: str, source: str = "generated"):
    """Compatibility no-op.

    Render now stores both the current mailbox and saved mailbox history.
    Keeping this function avoids touching older handler paths while removing
    temp-mail MongoDB writes from Vercel.
    """
    return None


def _saved_temp_mail_markup(accounts):
    rows = []
    for doc in list(accounts or [])[:50]:
        address = str(doc.get("address") or "").strip()
        saved_id = str(doc.get("id") or "").strip()
        if not address or not saved_id:
            continue
        label = address if len(address) <= 42 else address[:39] + "…"
        rows.append([
            InlineKeyboardButton(
                text=f"📧 {label}",
                callback_data=f"tmpmail_saved_use:{saved_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Close", callback_data="tmpmail_saved_close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _set_temp_mail_flow(uid: int, action: str, **data):
    await temp_mail_api(
        "/api/temp-flow/set",
        {"user_id": int(uid), "action": str(action), "data": data},
    )


async def _get_temp_mail_flow(uid: int):
    try:
        data = await temp_mail_api("/api/temp-flow/get", {"user_id": int(uid)})
        flow = data.get("flow")
        return flow if isinstance(flow, dict) and flow.get("action") else None
    except Exception:
        log.info("Could not fetch temp-mail flow from Render", exc_info=True)
        return None


async def _clear_temp_mail_flow(uid: int):
    try:
        await temp_mail_api("/api/temp-flow/clear", {"user_id": int(uid)})
    except Exception:
        log.info("Could not clear temp-mail flow on Render", exc_info=True)


def _temp_mail_api_sync(path: str, payload=None):
    if not TEMP_MAIL_API_URL or not TEMP_MAIL_API_SECRET:
        raise RuntimeError("Temp Mail backend is not configured.")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = UrlRequest(
        f"{TEMP_MAIL_API_URL}{path}",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Temp-Mail-Secret": TEMP_MAIL_API_SECRET,
        },
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        detail = str(exc)
        try:
            if hasattr(exc, "read"):
                raw = exc.read().decode("utf-8", "replace")
                parsed = json.loads(raw)
                detail = str(parsed.get("detail") or raw)[:500]
        except Exception:
            pass
        raise RuntimeError(detail) from exc


async def temp_mail_api(path: str, payload=None):
    return await asyncio.to_thread(_temp_mail_api_sync, path, payload)


async def _stop_temp_mail_watches(uid: int):
    if not TEMP_MAIL_API_URL or not TEMP_MAIL_API_SECRET:
        return
    try:
        await temp_mail_api("/api/watch/stop-user", {"user_id": int(uid)})
    except Exception:
        # Auto-refresh is optional; never break the normal inbox if the watcher is unavailable.
        log.info("Could not stop temp-mail watcher for user %s", uid, exc_info=True)


def _temp_mail_inbox_markup(messages, auto_refresh=True):
    rows = []
    for idx, item in enumerate(messages, 1):
        mid = str(item.get("id") or "")
        if mid:
            rows.append([InlineKeyboardButton(text=f"📨 Open #{idx}", callback_data=f"tmpmail_read:{mid}")])
    if auto_refresh:
        rows.append([InlineKeyboardButton(text="⏹ Stop Auto Refresh", callback_data="tmpmail_watch_stop")])
    else:
        rows.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="tmpmail_inbox")])
    rows.append([InlineKeyboardButton(text="⬅️ Temp Mail Menu", callback_data="tmpmail_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _temp_mail_inbox_text(address: str, messages, auto_refresh=True):
    lines = [
        "📥 <b>Received Mail</b>",
        f"\n<code>{html_escape(address)}</code>",
        "\n🔁 Auto-check: every 15 seconds" if auto_refresh else "\n⏸ Auto-refresh stopped",
    ]
    if not messages:
        lines.append("\n\nNo messages yet.")
        return "".join(lines)
    for idx, item in enumerate(messages, 1):
        sender = str((item.get("from") or {}).get("address") or "Unknown")
        subject = str(item.get("subject") or "(No subject)")
        lines.append(f"\n\n{idx}. <b>{html_escape(subject[:70])}</b>\nFrom: {html_escape(sender[:80])}")
    return "".join(lines)


async def show_temp_mail_menu(message: Message, edit=False):
    current_address = await _get_temp_mail_current(message.from_user.id if message.from_user else message.chat.id)
    status = f"Current: <code>{html_escape(current_address)}</code>" if current_address else "No temp mail created yet."
    text = f"📧 <b>Temp Mail</b>\n\n{status}\n\nUse the buttons at the bottom:"
    await message.answer(text, parse_mode="HTML", reply_markup=temp_mail_keyboard(message.chat.id))


@dp.message(F.text == "📧 Temp Mail")
async def temp_mail_button(m: Message):
    if not await gate_message(m):
        return
    await show_temp_mail_menu(m)


async def _create_or_change_temp_mail_message(m: Message, changing=False):
    if not await gate_message(m):
        return
    if not TEMP_MAIL_API_URL or not TEMP_MAIL_API_SECRET:
        await m.answer("⚠️ Temp Mail backend is not configured yet.", reply_markup=temp_mail_keyboard(m.from_user.id))
        return
    try:
        await _stop_temp_mail_watches(m.from_user.id)
        data = await temp_mail_api("/api/mail/create", {"user_id": int(m.from_user.id)})
        address = str(data.get("address") or "")
        password = str(data.get("password") or "")
        if not address or not password:
            raise RuntimeError("Backend returned incomplete mailbox details.")
        _save_temp_mail_credentials(m.from_user.id, address, password, "changed" if changing else "generated")
        title = "🔄 <b>Mail changed</b>" if changing else "✅ <b>Temp mail created</b>"
        await m.answer(
            f"{title}\n\n📧 <b>Mail ID:</b> <code>{html_escape(address)}</code>\n"
            f"🔑 <b>Password:</b> <code>{html_escape(password)}</code>\n\n"
            "Saved securely in MongoDB. Use 📥 Received Mail to check messages.",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )
    except Exception as exc:
        log.exception("Temp mail create failed")
        await m.answer(
            f"❌ Could not create temp mail: {html_escape(str(exc))}",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )


@dp.message(F.text == "➕ Create Mail")
async def temp_mail_create_button(m: Message):
    if not await gate_message(m):
        return
    current_address = await _get_temp_mail_current(m.from_user.id)
    if current_address:
        await m.answer(
            "You already have a mail. Use 🔄 Change Mail or ✏️ Custom Mail.",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )
        return
    await _create_or_change_temp_mail_message(m, changing=False)


@dp.message(F.text == "🔄 Change Mail")
async def temp_mail_change_button(m: Message):
    await _create_or_change_temp_mail_message(m, changing=True)


@dp.message(F.text == "✏️ Custom Mail")
async def temp_mail_custom_button(m: Message):
    if not await gate_message(m):
        return
    await _set_temp_mail_flow(m.from_user.id, "custom_username")
    await m.answer(
        "✏️ <b>Create Custom Mail</b>\n\n"
        "Send the username you want before the @ sign.\n"
        "Example: <code>myname123</code>\n\n"
        "Allowed: letters, numbers, dot, underscore and hyphen.\n"
        "Send /cancel to stop.",
        parse_mode="HTML",
        reply_markup=temp_mail_keyboard(m.from_user.id),
    )


@dp.message(F.text == "🔐 Login Old Mail")
async def temp_mail_login_button(m: Message):
    if not await gate_message(m):
        return
    await _set_temp_mail_flow(m.from_user.id, "login_address")
    await m.answer(
        "🔐 <b>Login Old Mail</b>\n\n"
        "Send your existing Mail.tm email address.\n"
        "Example: <code>name@domain.tld</code>\n\n"
        "Send /cancel to stop.",
        parse_mode="HTML",
        reply_markup=temp_mail_keyboard(m.from_user.id),
    )


@dp.message(F.text == "💾 Saved Mails")
async def temp_mail_saved_button(m: Message):
    if not m.from_user:
        return
    try:
        # Saved-mail history is entirely Render-owned.
        # Trigger current lookup once so older Vercel-only mailboxes can migrate.
        await _get_temp_mail_current(m.from_user.id)
        data = await temp_mail_api("/api/mail/saved/list", {"user_id": int(m.from_user.id)})
        saved = list(data.get("accounts") or [])
    except Exception as exc:
        log.exception("Could not load saved temp mails from Render")
        return await m.answer(
            f"❌ Could not load saved mails: {html_escape(str(exc))}",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )

    if not saved:
        return await m.answer(
            "💾 <b>Saved Mails</b>\n\nNo saved Mail.tm accounts yet. Create or log in to one first.",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )
    await m.answer(
        "💾 <b>Saved Mail.tm accounts</b>\n\nTap an address to make it your current Temp Mail. "
        "Saved credentials are stored encrypted by the Render backend in MongoDB.",
        parse_mode="HTML",
        reply_markup=_saved_temp_mail_markup(saved),
    )
    await m.answer("Temp Mail controls", reply_markup=temp_mail_keyboard(m.from_user.id))


@dp.message(F.text == "🪪 Mail ID & Password")
async def temp_mail_credentials_button(m: Message):
    if not await gate_message(m):
        return
    creds = await _get_temp_mail_credentials(m.from_user.id)
    if not creds:
        await m.answer(
            "📭 No temp mail yet. Tap ➕ Create Mail first.",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )
        return
    address, password = creds
    await m.answer(
        f"🪪 <b>Mail ID & Password</b>\n\n📧 <b>Mail ID:</b> <code>{html_escape(address)}</code>\n"
        f"🔑 <b>Password:</b> <code>{html_escape(password)}</code>\n\n"
        "These credentials are stored encrypted in MongoDB.",
        parse_mode="HTML",
        reply_markup=temp_mail_keyboard(m.from_user.id),
    )


@dp.message(F.text == "📥 Received Mail")
async def temp_mail_inbox_button(m: Message):
    if not await gate_message(m):
        return
    try:
        await _stop_temp_mail_watches(m.from_user.id)
        data = await temp_mail_api(
            "/api/mail/inbox/current",
            {"user_id": int(m.from_user.id)},
        )
        address = str(data.get("address") or "")
        messages = list(data.get("messages") or [])[:8]
        sent = await m.answer(
            _temp_mail_inbox_text(address, messages, auto_refresh=True),
            parse_mode="HTML",
            reply_markup=_temp_mail_inbox_markup(messages, auto_refresh=True),
        )
        try:
            await temp_mail_api(
                "/api/watch/start-current",
                {
                    "user_id": int(m.from_user.id),
                    "chat_id": int(sent.chat.id),
                    "message_id": int(sent.message_id),
                },
            )
        except Exception as watch_exc:
            log.warning("Temp mail auto-refresh unavailable: %s", watch_exc)
            try:
                await sent.edit_text(
                    _temp_mail_inbox_text(address, messages, auto_refresh=False)
                    + "\n\n⚠️ Auto-refresh unavailable; use Refresh manually.",
                    parse_mode="HTML",
                    reply_markup=_temp_mail_inbox_markup(messages, auto_refresh=False),
                )
            except Exception:
                pass
        await m.answer("📧 Temp Mail controls", reply_markup=temp_mail_keyboard(m.from_user.id))
    except Exception as exc:
        detail = str(exc)
        if "No current temp mail" in detail or "404" in detail:
            return await m.answer(
                "📭 No temp mail yet. Tap ➕ Create Mail first.",
                reply_markup=temp_mail_keyboard(m.from_user.id),
            )
        log.exception("Temp mail inbox failed")
        await m.answer(
            f"❌ Could not check inbox: {html_escape(detail)}",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(m.from_user.id),
        )


@dp.message(F.text == "⬅️ Back")
async def temp_mail_back_button(m: Message):
    if not await gate_message(m):
        return
    await _stop_temp_mail_watches(m.from_user.id)
    await _clear_temp_mail_flow(m.from_user.id)
    await m.answer("🏠 Main menu", reply_markup=shop_keyboard(m.from_user.id))


@dp.callback_query(F.data == "tmpmail_back")
async def temp_mail_back(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    await _stop_temp_mail_watches(q.from_user.id)
    await _clear_temp_mail_flow(q.from_user.id)
    if q.message:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.answer("🏠 Main menu", reply_markup=shop_keyboard(q.from_user.id))


async def _create_or_change_temp_mail(q: CallbackQuery, changing=False):
    if not await gate_callback(q):
        return
    await q.answer("Creating a new inbox…")
    if not TEMP_MAIL_API_URL or not TEMP_MAIL_API_SECRET:
        if q.message:
            await q.message.answer("⚠️ Temp Mail backend is not configured yet.")
        return
    try:
        await _stop_temp_mail_watches(q.from_user.id)
        data = await temp_mail_api("/api/mail/create", {"user_id": int(q.from_user.id)})
        address = str(data.get("address") or "")
        password = str(data.get("password") or "")
        if not address or not password:
            raise RuntimeError("Backend returned incomplete mailbox details.")
        _save_temp_mail_credentials(q.from_user.id, address, password, "changed" if changing else "generated")
        title = "🔄 <b>Mail changed</b>" if changing else "✅ <b>Temp mail created</b>"
        if q.message:
            await q.message.answer(
                f"{title}\n\n📧 <b>Mail ID:</b> <code>{html_escape(address)}</code>\n"
                f"🔑 <b>Password:</b> <code>{html_escape(password)}</code>\n\n"
                "Saved securely in MongoDB. Use 📥 Received Mail to check messages.",
                parse_mode="HTML",
                reply_markup=temp_mail_keyboard(q.from_user.id),
            )
    except Exception as exc:
        log.exception("Temp mail create failed")
        if q.message:
            await q.message.answer(f"❌ Could not create temp mail: {html_escape(str(exc))}", parse_mode="HTML")


@dp.callback_query(F.data == "tmpmail_create")
async def temp_mail_create(q: CallbackQuery):
    current_address = await _get_temp_mail_current(q.from_user.id)
    if current_address:
        await q.answer("You already have a mail. Use Change Mail or Custom Mail.", show_alert=True)
        return
    await _create_or_change_temp_mail(q, changing=False)


@dp.callback_query(F.data == "tmpmail_change")
async def temp_mail_change(q: CallbackQuery):
    await _create_or_change_temp_mail(q, changing=True)


@dp.callback_query(F.data == "tmpmail_custom")
async def temp_mail_custom(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    await _set_temp_mail_flow(q.from_user.id, "custom_username")
    if q.message:
        await q.message.answer(
            "✏️ <b>Create Custom Mail</b>\n\n"
            "Send the username you want before the @ sign.\n"
            "Example: <code>myname123</code>\n\n"
            "Allowed: letters, numbers, dot, underscore and hyphen.\n"
            "Send /cancel to stop.",
            parse_mode="HTML",
        )


@dp.callback_query(F.data == "tmpmail_login")
async def temp_mail_login(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    await _set_temp_mail_flow(q.from_user.id, "login_address")
    if q.message:
        await q.message.answer(
            "🔐 <b>Login Old Mail</b>\n\n"
            "Send your existing Mail.tm email address.\n"
            "Example: <code>name@domain.tld</code>\n\n"
            "Send /cancel to stop.",
            parse_mode="HTML",
        )


@dp.callback_query(F.data == "tmpmail_credentials")
async def temp_mail_credentials(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    creds = await _get_temp_mail_credentials(q.from_user.id)
    if not creds:
        if q.message:
            await q.message.answer("📭 No temp mail yet. Tap ➕ Create Mail first.", reply_markup=temp_mail_keyboard(q.from_user.id))
        return
    address, password = creds
    if q.message:
        await q.message.answer(
            f"🪪 <b>Mail ID & Password</b>\n\n📧 <b>Mail ID:</b> <code>{html_escape(address)}</code>\n"
            f"🔑 <b>Password:</b> <code>{html_escape(password)}</code>\n\n"
            "These credentials are stored encrypted in MongoDB.",
            parse_mode="HTML",
            reply_markup=temp_mail_keyboard(q.from_user.id),
        )


@dp.callback_query(F.data == "tmpmail_inbox")
async def temp_mail_inbox(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer("Checking inbox…")
    try:
        await _stop_temp_mail_watches(q.from_user.id)
        data = await temp_mail_api(
            "/api/mail/inbox/current",
            {"user_id": int(q.from_user.id)},
        )
        address = str(data.get("address") or "")
        messages = list(data.get("messages") or [])[:8]
        if q.message:
            sent = await q.message.answer(
                _temp_mail_inbox_text(address, messages, auto_refresh=True),
                parse_mode="HTML",
                reply_markup=_temp_mail_inbox_markup(messages, auto_refresh=True),
            )
            try:
                await temp_mail_api(
                    "/api/watch/start-current",
                    {
                        "user_id": int(q.from_user.id),
                        "chat_id": int(sent.chat.id),
                        "message_id": int(sent.message_id),
                    },
                )
            except Exception as watch_exc:
                log.warning("Temp mail auto-refresh unavailable: %s", watch_exc)
                try:
                    await sent.edit_text(
                        _temp_mail_inbox_text(address, messages, auto_refresh=False)
                        + "\n\n⚠️ Auto-refresh unavailable; use Refresh manually.",
                        parse_mode="HTML",
                        reply_markup=_temp_mail_inbox_markup(messages, auto_refresh=False),
                    )
                except Exception:
                    pass
    except Exception as exc:
        detail = str(exc)
        if q.message:
            if "No current temp mail" in detail or "404" in detail:
                await q.message.answer(
                    "📭 No temp mail yet. Tap ➕ Create Mail first.",
                    reply_markup=temp_mail_keyboard(q.from_user.id),
                )
            else:
                log.exception("Temp mail inbox failed")
                await q.message.answer(
                    f"❌ Could not check inbox: {html_escape(detail)}",
                    parse_mode="HTML",
                )


@dp.callback_query(F.data == "tmpmail_watch_stop")
async def temp_mail_watch_stop(q: CallbackQuery):
    if not await gate_callback(q):
        return
    try:
        if q.message:
            await temp_mail_api("/api/watch/stop", {
                "user_id": int(q.from_user.id),
                "chat_id": int(q.message.chat.id),
                "message_id": int(q.message.message_id),
            })
            # Preserve the existing inbox text and switch to a manual refresh keyboard.
            rows = []
            for row in (q.message.reply_markup.inline_keyboard if q.message.reply_markup else []):
                for btn in row:
                    if btn.callback_data and btn.callback_data.startswith("tmpmail_read:"):
                        rows.append([InlineKeyboardButton(text=btn.text, callback_data=btn.callback_data)])
            rows.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="tmpmail_inbox")])
            rows.append([InlineKeyboardButton(text="⬅️ Temp Mail Menu", callback_data="tmpmail_menu")])
            await q.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await q.answer("Auto-refresh stopped.")
    except Exception:
        log.exception("Could not stop temp mail watcher")
        await q.answer("Could not stop auto-refresh right now.", show_alert=True)


@dp.callback_query(F.data.startswith("tmpmail_saved_use:"))
async def temp_mail_saved_use(q: CallbackQuery):
    if not q.from_user:
        return
    await q.answer()
    saved_id = str(q.data or "").split(":", 1)[1].strip()
    if not saved_id:
        return await q.answer("Invalid saved mailbox.", show_alert=True)

    try:
        data = await temp_mail_api(
            "/api/mail/saved/use",
            {"user_id": int(q.from_user.id), "saved_id": saved_id},
        )
        address = str(data.get("address") or "").strip().lower()
        if not address:
            raise RuntimeError("Render returned an incomplete saved-mail response.")
    except Exception as exc:
        log.exception("Could not restore saved temp mail from Render")
        if q.message:
            return await q.message.answer(
                f"❌ Could not restore that mailbox: {html_escape(str(exc))}",
                parse_mode="HTML",
                reply_markup=temp_mail_keyboard(q.from_user.id),
            )
        return

    if q.message:
        try:
            await q.message.edit_text(
                "✅ <b>Saved mailbox restored</b>\n\n"
                f"📧 <code>{html_escape(address)}</code>\n\n"
                "Use 📥 Received Mail to open its inbox or 🪪 Mail ID & Password to view the credentials.",
                parse_mode="HTML",
            )
        except Exception:
            await q.message.answer(
                "✅ <b>Saved mailbox restored</b>\n\n"
                f"📧 <code>{html_escape(address)}</code>",
                parse_mode="HTML",
                reply_markup=temp_mail_keyboard(q.from_user.id),
            )


@dp.callback_query(F.data == "tmpmail_saved_close")
async def temp_mail_saved_close(q: CallbackQuery):
    await q.answer()
    try:
        await q.message.delete()
    except Exception:
        pass


@dp.callback_query(F.data == "tmpmail_menu")
async def temp_mail_menu_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    await _stop_temp_mail_watches(q.from_user.id)
    await _clear_temp_mail_flow(q.from_user.id)
    if q.message:
        await show_temp_mail_menu(q.message)


@dp.callback_query(F.data.startswith("tmpmail_read:"))
async def temp_mail_read(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer("Opening mail…")
    message_id = q.data.split(":", 1)[1]
    try:
        data = await temp_mail_api(
            "/api/mail/message/current",
            {"user_id": int(q.from_user.id), "message_id": message_id},
        )
        sender = str(data.get("from") or "Unknown")
        subject = str(data.get("subject") or "(No subject)")
        body = str(data.get("text") or data.get("intro") or "[No plain-text body]")
        if len(body) > 3200:
            body = body[:3200] + "\n\n[Message shortened]"
        if q.message:
            await q.message.answer(
                f"📨 <b>{html_escape(subject)}</b>\nFrom: {html_escape(sender)}\n\n{html_escape(body)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Inbox", callback_data="tmpmail_inbox")],
                    [InlineKeyboardButton(text="📧 Temp Mail Menu", callback_data="tmpmail_menu")],
                ]),
            )
    except Exception as exc:
        log.exception("Temp mail read failed")
        if q.message:
            await q.message.answer(
                f"❌ Could not read message: {html_escape(str(exc))}",
                parse_mode="HTML",
            )




def downloader_keyboard(uid):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔗 Send Link"), KeyboardButton(text="📊 Active Download")],
            [KeyboardButton(text="📁 Recent Downloads"), KeyboardButton(text="❌ Cancel Download")],
            [KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Downloader options…",
    )


DOWNLOAD_QUALITY_MAP = {
    "✨ Best": "best",
    "🎬 1080p": "1080p",
    "🎬 720p": "720p",
    "🎬 480p": "480p",
    "🎬 360p": "360p",
    "🎵 Audio": "audio",
}


def downloader_quality_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✨ Best"), KeyboardButton(text="🎬 1080p")],
            [KeyboardButton(text="🎬 720p"), KeyboardButton(text="🎬 480p")],
            [KeyboardButton(text="🎬 360p"), KeyboardButton(text="🎵 Audio")],
            [KeyboardButton(text="❌ Cancel Download"), KeyboardButton(text="⬅️ Back")],
        ],
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="Choose quality…",
    )


def _download_progress_bar(percent, width=12):
    percent = max(0, min(100, int(percent or 0)))
    filled = int(round(width * percent / 100))
    return "▓" * filled + "░" * (width - filled)


async def downloader_api(method: str, path: str, payload=None):
    if not DOWNLOADER_API_URL or not DOWNLOADER_API_SECRET:
        raise RuntimeError("Downloader backend is not configured yet.")
    import aiohttp
    headers = {"X-Downloader-Secret": DOWNLOADER_API_SECRET}
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        url = DOWNLOADER_API_URL + path
        if method == "GET":
            async with session.get(url, headers=headers) as r:
                text = await r.text()
                if r.status >= 400:
                    raise RuntimeError(text[:500])
                return json.loads(text)
        async with session.post(url, headers=headers, json=payload or {}) as r:
            text = await r.text()
            if r.status >= 400:
                raise RuntimeError(text[:500])
            return json.loads(text)


def _download_state(uid: int):
    return users_col.find_one(
        {"user_id": int(uid)},
        {
            "downloader_flow": 1,
            "downloader_last_job_id": 1,
            "downloader_quality": 1,
            "downloader_pending_url": 1,
            "downloader_probe": 1,
        },
    ) or {}


def _download_status_text(doc):
    status = str(doc.get("status") or "unknown").replace("_", " ").upper()
    progress = int(doc.get("progress") or 0)
    filename = html_escape(str(doc.get("filename") or "Preparing…"))
    size = int(doc.get("size") or 0)
    quality = html_escape(str(doc.get("requested_quality") or "best"))
    size_text = f"{size / (1024**3):.2f} GB" if size >= 1024**3 else (f"{size / (1024**2):.1f} MB" if size else "—")
    workers = int(doc.get("worker_count") or 0)
    fragments = int(doc.get("fragment_workers") or 0)
    worker_text = str(workers or "—")
    if fragments:
        worker_text = f"{workers or 1} media worker • {fragments} fragments"
    text = (
        "📥 <b>Download Status</b>\n\n"
        f"📄 {filename}\n"
        f"🎚 Quality: <b>{quality}</b>\n"
        f"📊 Status: <b>{status}</b>\n"
        f"⏳ <code>{_download_progress_bar(progress)}</code> <b>{progress}%</b>\n"
        f"📦 Size: <b>{size_text}</b>\n"
        f"⚡ Workers: <b>{html_escape(worker_text)}</b>"
    )
    tg_progress = doc.get("telegram_upload_progress")
    if str(doc.get("status") or "") == "uploading_telegram" and tg_progress is not None:
        try:
            tg = int(tg_progress)
            text += "\n\n☁️ <b>Uploading to Telegram</b>\n" + f"<code>{_download_progress_bar(tg)}</code> <b>{tg}%</b>"
        except Exception:
            pass
    delivery_mode = str(doc.get("delivery_mode") or "")
    delivery_status = str(doc.get("delivery_status") or "")
    if delivery_mode in {"telegram_archive_copy", "telegram_mtproto_archive_copy"}:
        text += "\n\n✅ Delivery: <b>File sent in Telegram</b>"
    elif delivery_status == "failed":
        text += "\n\n❌ Delivery: <b>Telegram delivery failed</b>"
    error = str(doc.get("error") or "")
    if error:
        text += f"\n\n❌ <code>{html_escape(error[:500])}</code>"
    return text


@dp.message(F.text == "📥 Downloader")
async def downloader_menu(m: Message):
    if not m.from_user:
        return
    await m.answer(
        "📥 <b>Downloader</b>\n\n"
        "Send the URL first. Direct files start immediately in original quality; "
        "media pages ask for quality only when needed. Direct range-capable files "
        "can use up to 4 workers; media extractors can use concurrent fragments.\n\n"
        "TeraBox is supported only when the URL resolves to a public direct file; "
        "the bot does not bypass login/private-share restrictions.",
        parse_mode="HTML",
        reply_markup=downloader_keyboard(m.from_user.id),
    )


@dp.message(F.text == "🔗 Send Link")
async def downloader_send_link(m: Message):
    if not m.from_user:
        return
    users_col.update_one(
        {"user_id": int(m.from_user.id)},
        {
            "$set": {"downloader_flow": "await_url"},
            "$unset": {
                "downloader_quality": "",
                "downloader_pending_url": "",
                "downloader_probe": "",
            },
        },
        upsert=True,
    )
    await m.answer(
        "🔗 <b>Send the URL</b>\n\n"
        "I will detect it automatically:\n"
        "• Direct file → starts immediately in original quality\n"
        "• Media page → asks you to choose quality\n\n"
        "Send /cancel to stop.",
        parse_mode="HTML",
        reply_markup=downloader_keyboard(m.from_user.id),
    )


@dp.message(F.text == "📊 Active Download")
async def downloader_active(m: Message):
    if not m.from_user:
        return
    state = _download_state(m.from_user.id)
    job_id = str(state.get("downloader_last_job_id") or "")
    if not job_id:
        return await m.answer("No active/recent download yet.", reply_markup=downloader_keyboard(m.from_user.id))
    try:
        doc = await downloader_api("GET", f"/api/jobs/{job_id}")
        await m.answer(_download_status_text(doc), parse_mode="HTML", reply_markup=downloader_keyboard(m.from_user.id))
    except Exception as exc:
        await m.answer(f"❌ Could not load status: {html_escape(str(exc))}", parse_mode="HTML", reply_markup=downloader_keyboard(m.from_user.id))


@dp.message(F.text == "📁 Recent Downloads")
async def downloader_recent(m: Message):
    if not m.from_user:
        return
    try:
        data = await downloader_api("GET", f"/api/users/{int(m.from_user.id)}/recent")
        items = list(data.get("jobs") or [])
        if not items:
            return await m.answer("No recent downloads yet.", reply_markup=downloader_keyboard(m.from_user.id))
        lines = ["📁 <b>Recent Downloads</b>"]
        for item in items[:8]:
            lines.append(f"\n• <b>{html_escape(str(item.get('status','?')).upper())}</b> — {html_escape(str(item.get('filename') or item.get('job_id','')[:10]))}")
        await m.answer("".join(lines), parse_mode="HTML", reply_markup=downloader_keyboard(m.from_user.id))
    except Exception as exc:
        await m.answer(f"❌ Could not load downloads: {html_escape(str(exc))}", parse_mode="HTML", reply_markup=downloader_keyboard(m.from_user.id))


@dp.message(F.text == "🔄 Fresh Link")
async def downloader_fresh_link(m: Message):
    if not m.from_user:
        return
    state = _download_state(m.from_user.id)
    job_id = str(state.get("downloader_last_job_id") or "")
    if not job_id:
        return await m.answer("No completed download yet.", reply_markup=downloader_keyboard(m.from_user.id))
    try:
        data = await downloader_api("GET", f"/api/jobs/{job_id}/download-link")
        url = str(data.get("url") or "")
        if not url:
            raise RuntimeError("Backend did not return a download URL")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬇️ Download File", url=url)]])
        await m.answer(
            "🔗 <b>Fresh temporary link</b>\n\nUse the button below before it expires.",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await m.answer("Downloader controls", reply_markup=downloader_keyboard(m.from_user.id))
    except Exception as exc:
        await m.answer(
            f"❌ Could not create a fresh link: {html_escape(str(exc))}",
            parse_mode="HTML",
            reply_markup=downloader_keyboard(m.from_user.id),
        )


@dp.message(F.text == "❌ Cancel Download")
async def downloader_cancel(m: Message):
    if not m.from_user:
        return
    state = _download_state(m.from_user.id)
    if state.get("downloader_flow") in {"await_quality", "await_url"}:
        users_col.update_one(
            {"user_id": int(m.from_user.id)},
            {"$unset": {"downloader_flow": "", "downloader_quality": "", "downloader_pending_url": "", "downloader_probe": ""}},
        )
        return await m.answer(
            "❌ Downloader action cancelled.",
            reply_markup=downloader_keyboard(m.from_user.id),
        )
    job_id = str(state.get("downloader_last_job_id") or "")
    if not job_id:
        return await m.answer("No download to cancel.", reply_markup=downloader_keyboard(m.from_user.id))
    try:
        await downloader_api("POST", f"/api/jobs/{job_id}/cancel", {"user_id": int(m.from_user.id)})
        await m.answer("Cancellation requested. A worker may finish its current chunk first.", reply_markup=downloader_keyboard(m.from_user.id))
    except Exception as exc:
        await m.answer(f"❌ Could not cancel: {html_escape(str(exc))}", parse_mode="HTML", reply_markup=downloader_keyboard(m.from_user.id))


@dp.message(F.text.in_({"🛍 Shop / Methods", "🛍 Toko / Metode"}))
async def shop_open_message(m: Message):
    """Generate a fresh signed Mini App URL every time the persistent Shop button is pressed."""
    if not await gate_message(m):
        return
    await m.answer(
        "🛍 <b>Shop ready</b>\n\nTap below to open a fresh secure shop session."
        if get_user_language(m.from_user.id) == "en"
        else "🛍 <b>Toko siap</b>\n\nTekan di bawah untuk membuka sesi toko aman yang baru.",
        parse_mode="HTML",
        reply_markup=fresh_shop_markup(m.from_user.id),
    )


@dp.callback_query(F.data == "menu_shop")
async def shop_open_callback(q: CallbackQuery):
    """Long-lived inline menus call this first, so the Web App URL is never stale."""
    if not await gate_callback(q):
        return
    await q.answer("Fresh shop link ready ✅")
    if q.message:
        await q.message.answer(
            "🛍 <b>Shop ready</b>\n\nTap below to open a fresh secure shop session."
            if get_user_language(q.from_user.id) == "en"
            else "🛍 <b>Toko siap</b>\n\nTekan di bawah untuk membuka sesi toko aman yang baru.",
            parse_mode="HTML",
            reply_markup=fresh_shop_markup(q.from_user.id),
        )


@dp.callback_query(F.data == "menu_shop_wishlist")
async def shop_open_wishlist_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer("Fresh wishlist link ready ✅")
    if q.message:
        await q.message.answer(
            "❤️ <b>Wishlist ready</b>\n\nTap below to open your wishlist with a fresh secure session."
            if get_user_language(q.from_user.id) == "en"
            else "❤️ <b>Favorit siap</b>\n\nTekan di bawah untuk membuka favorit dengan sesi aman yang baru.",
            parse_mode="HTML",
            reply_markup=fresh_shop_markup(q.from_user.id, wishlist=True),
        )


@dp.callback_query(F.data == "menu_restart")
async def restart_inline(q: CallbackQuery):
    await q.answer("Restarting…")
    if q.message:
        # Use the real user from the callback, not the bot-authored message.
        upsert_user(q.from_user)
        if q.from_user.id == ADMIN_ID:
            _ADMIN_KEYBOARD_SECTION.pop(q.from_user.id, None)
        if not await user_is_member(q.from_user.id):
            await gate_callback(q)
            return
        await q.message.answer(
            f"⚡ <b>{SHOP_NAME}</b>\n\n"
            f"💳 Balance: <b>{money(get_balance(q.from_user.id))}</b>\n"
            f"🆔 Customer ID: <code>{q.from_user.id}</code>\n\n"
            + tr(q.from_user.id, "home_choose"),
            parse_mode="HTML",
            reply_markup=action_menu(q.from_user.id, q.from_user.id == ADMIN_ID),
        )
        await q.message.answer(tr(q.from_user.id, "menu_unlocked"), reply_markup=shop_keyboard(q.from_user.id))


@dp.callback_query(F.data == "verify_join")
async def verify_join(q: CallbackQuery):
    if await user_is_member(q.from_user.id):
        await maybe_award_referral(q.from_user.id)
        await q.answer("Membership verified ✅")
        if q.message:
            upsert_user(q.from_user)
            if q.from_user.id == ADMIN_ID:
                _ADMIN_KEYBOARD_SECTION.pop(q.from_user.id, None)
            await q.message.answer(
                "🎉 <b>Verified! The shop is unlocked.</b>",
                parse_mode="HTML",
                reply_markup=action_menu(q.from_user.id, q.from_user.id == ADMIN_ID),
            )
            await q.message.answer("Menu unlocked 👇", reply_markup=shop_keyboard(q.from_user.id))
    else:
        await q.answer("I still can't verify your membership. Join first, then retry.", show_alert=True)


@dp.message(Command("bindgroup"))
async def bind_group(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    if m.chat.type == "private":
        return await m.answer("Add me to the required group as an admin, then run /bindgroup inside that group.")
    set_setting("required_chat_id", m.chat.id)
    set_setting("required_chat_title", m.chat.title or "Required group")
    _required_chat_cache["expires"] = 0.0
    _membership_cache.clear()
    await m.answer(f"✅ Required group bound.\nChat ID: <code>{m.chat.id}</code>", parse_mode="HTML")


@dp.message(Command("stopbroadcast"))
async def stop_broadcasts(m: Message):
    upsert_user(m.from_user)
    users_col.update_one({"user_id": m.from_user.id}, {"$set": {"broadcast_opt_out": True}})
    await m.answer("🔕 Broadcast messages disabled. You can enable them again with /startbroadcast.")


@dp.message(Command("startbroadcast"))
async def start_broadcasts(m: Message):
    upsert_user(m.from_user)
    users_col.update_one({"user_id": m.from_user.id}, {"$set": {"broadcast_opt_out": False, "broadcast_blocked": False}})
    await m.answer("🔔 Broadcast messages enabled.")


@dp.message(F.text.in_({"🛠 Admin Dashboard", "🛠 Dasbor Admin"}))
async def admin_dashboard_button(m: Message):
    if not m.from_user or m.from_user.id != ADMIN_ID:
        return await m.answer("Admin only.")
    clear_admin_flow(m.from_user.id)
    await show_admin_menu(m, switch_reply_keyboard=True)


@dp.message(Command("admin"))
@dp.message(Command("adminmenu"))
async def adminmenu_cmd(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    clear_admin_flow(m.from_user.id)
    await show_admin_menu(m, switch_reply_keyboard=True)


@dp.callback_query(F.data == "admin_enter")
async def admin_enter_cb(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer("Admin mode")
    if q.message:
        await show_admin_menu(q.message, switch_reply_keyboard=True, admin_uid=q.from_user.id)


async def show_admin_menu(target, switch_reply_keyboard=False, admin_uid=None):
    pending_email = orders_col.count_documents({"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    pending_manual = orders_col.count_documents({"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    attention = pending_email + pending_manual
    uid = int(admin_uid or getattr(getattr(target, "from_user", None), "id", 0) or 0)
    reply_markup = None
    if switch_reply_keyboard and uid == ADMIN_ID:
        _ADMIN_KEYBOARD_SECTION[uid] = "main"
        reply_markup = admin_keyboard(uid)
    await target.answer(
        "🛠 <b>Admin</b>\n\n"
        f"Needs action: <b>{attention}</b> order(s).\n"
        "Use the <b>bottom keyboard</b> for Admin navigation. Open Action Center for work waiting on you, or More tools for less-used controls.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


# Persistent Telegram Admin reply-keyboard controls. These reuse the same handlers/data
# as the inline admin panel, so both surfaces stay synchronized.
@dp.message(F.text == "🏠 Customer Menu")
async def admin_reply_customer_menu(m: Message):
    if not m.from_user or m.from_user.id != ADMIN_ID:
        return
    clear_admin_flow(m.from_user.id)
    _ADMIN_KEYBOARD_SECTION.pop(m.from_user.id, None)
    await send_home(m)


@dp.message(F.text == "📥 Action Center")
async def admin_reply_action_center(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tgadm_action_center(admin_reply_callback(m, "tgadm_action"))


@dp.message(F.text == "🧾 Orders")
async def admin_reply_orders(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tg_orders_page(admin_reply_callback(m, "tgadm_orders:0"))


@dp.message(F.text == "🛍 Products")
async def admin_reply_products(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tg_products_cb(admin_reply_callback(m, "tgadm_products:0"))


@dp.message(F.text == "📦 Inventory")
async def admin_reply_inventory(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tg_inventory_products(admin_reply_callback(m, "tgadm_inventory:0"))


@dp.message(F.text == "👥 Customers")
async def admin_reply_customers(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tg_customers(admin_reply_callback(m, "tgadm_customers:0"))


@dp.message(F.text == "⏰ Reminders")
async def admin_reply_reminders(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await adm_reminders_cb(admin_reply_callback(m, "adm_reminders"))


@dp.message(F.text == "📣 Broadcast")
async def admin_reply_broadcast(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await admin_broadcast_cb(admin_reply_callback(m, "admin_broadcast"))


@dp.message(F.text == "📊 Dashboard")
async def admin_reply_dashboard(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tg_dashboard(admin_reply_callback(m, "tgadm_dashboard"))


@dp.message(F.text.in_({"⚙️ More tools", "⚙ More tools"}))
async def admin_reply_more_tools(m: Message):
    if m.from_user and m.from_user.id == ADMIN_ID:
        clear_admin_flow(m.from_user.id)
        await tgadm_more_tools(admin_reply_callback(m, "tgadm_more"))


# Section-specific reply-keyboard shortcuts. These call the exact same handlers as
# the inline buttons, so Telegram Admin stays synchronized regardless of which surface is used.
ADMIN_SECTION_REPLY_ACTIONS = {
    "⬅️ Admin Menu": ("admin_menu_cb", "admin_menu"),
    "⬅️ More Tools": ("tgadm_more_tools", "tgadm_more"),
    "🛠 Pending Requests": ("manual_pending_cb", "am_pending"),
    "📧 Pending Email": ("email_pending_cb", "ae_pending"),
    "🧾 All Orders": ("tg_orders_page", "tgadm_orders:0"),
    "⏱ Check Waiting Orders": ("tg_sla_run", "tgsla_run"),
    "🔄 Refresh Orders": ("tg_orders_page", "tgadm_orders:0"),
    "🔄 Refresh Products": ("tg_products_cb", "tgadm_products:0"),
    "➕ New Product": ("tg_new_product", "tgp_new"),
    "🔐 Purchase Keys": ("adm_keys_cb", "adm_keys"),
    "🔄 Refresh Inventory": ("tg_inventory_products", "tgadm_inventory:0"),
    "🔎 Search Customer": ("tg_customer_search_prompt", "tgc_search"),
    "🔄 Refresh Customers": ("tg_customers", "tgadm_customers:0"),
    "📋 Upcoming Reminders": ("reminder_list_cb", "ar_list"),
    "➕ Manual Reminder": ("reminder_add_cb", "ar_add"),
    "⚙️ Product Expiry": ("reminder_products_cb", "ar_products"),
    "▶️ Process Due": ("reminder_run_cb", "ar_run"),
    "➕ New Broadcast": ("tg_broadcast_new", "tgbc_new"),
    "🔄 Refresh Broadcast": ("admin_broadcast_cb", "admin_broadcast"),
    "🔄 Refresh Dashboard": ("tg_dashboard", "tgadm_dashboard"),
    "📊 Analytics": ("admin_sales", "admin_sales"),
    "📚 Methods": ("tg_methods", "tgadm_methods:0"),
    "📦 Fulfillment Settings": ("email_menu_cb", "adm_email"),
    "🔗 Referrals": ("admin_referrals_cb", "admin_referrals"),
    "🔐 Security": ("tg_security", "tgadm_security"),
    "🧾 Delivery Templates": ("tg_templates_menu", "tgtpl"),
    "💾 Backups": ("tg_backup_menu", "tgbackup"),
    "🧩 Feature Controls": ("admin_features_cb", "admin_features"),
    "🔄 Refresh Methods": ("tg_methods", "tgadm_methods:0"),
    "➕ New Method": ("tg_method_new", "tgm_new"),
    "🔄 Refresh Analytics": ("admin_sales", "admin_sales"),
    "⚙️ Product Modes": ("email_products_cb", "ae_products"),
    "🔄 Refresh Purchase Keys": ("adm_keys_cb", "adm_keys"),
    "🔄 Refresh Referrals": ("admin_referrals_cb", "admin_referrals"),
    "🔄 Refresh Security": ("tg_security", "tgadm_security"),
    "🔗 Refresh Webhook": ("tg_setup_webhook", "tgadm_webhook"),
    "➕ New Template": ("tg_template_new", "tgtpl_new"),
    "🔄 Refresh Templates": ("tg_templates_menu", "tgtpl"),
    "⬇️ Export Backup": ("tg_backup_now", "tgbackup_now"),
    "🔄 Refresh Backups": ("tg_backup_menu", "tgbackup"),
}


@dp.message(F.text.in_(set(ADMIN_SECTION_REPLY_ACTIONS)))
async def admin_section_reply_action(m: Message):
    if not m.from_user or m.from_user.id != ADMIN_ID:
        return
    clear_admin_flow(m.from_user.id)
    handler_name, data = ADMIN_SECTION_REPLY_ACTIONS[m.text]
    handler = globals().get(handler_name)
    if not handler:
        return await m.answer("Admin action is temporarily unavailable. Open /admin and retry.")
    await handler(admin_reply_callback(m, data))


@dp.callback_query(F.data == "tgadm_action")
async def tgadm_action_center(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "action")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    pending_email = orders_col.count_documents({"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    pending_manual = orders_col.count_documents({"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    products = get_products(False)
    low_products = [p for p in products if str(p.get("fulfillment_mode") or "instant") == "instant" and 0 < int(p.get("stock") or 0) <= DEFAULT_LOW_STOCK]
    out_products = [p for p in products if str(p.get("fulfillment_mode") or "instant") == "instant" and int(p.get("stock") or 0) <= 0]
    due = subscription_reminders_col.count_documents({"status": "pending", "remind_at": {"$lte": utcnow()}})
    sla = pending_fulfillment_sla_counts()
    text = (
        "📥 <b>Action Center</b>\n\n"
        f"🛠 By-request waiting: <b>{pending_manual}</b>\n"
        f"📧 Email fulfillment waiting: <b>{pending_email}</b>\n"
        f"📦 Low / out of stock: <b>{len(low_products) + len(out_products)}</b>\n"
        f"⏰ Reminders due: <b>{due}</b>\n"
        f"🟠 Waiting ≥{FULFILLMENT_WARNING_HOURS}h: <b>{sla['warning']}</b>\n"
        f"🔴 Waiting ≥{FULFILLMENT_URGENT_HOURS}h: <b>{sla['urgent']}</b>\n\n"
        + ("✅ Nothing urgent right now." if not (pending_manual or pending_email or low_products or out_products or due or sla['warning'] or sla['urgent']) else "Choose what you want to handle next.")
    )
    await q.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "tgadm_more")
async def tgadm_more_tools(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "more")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    await q.message.answer(
        "⚙️ <b>More tools</b>\n\nLess frequent admin controls live here. Use the <b>bottom keyboard</b> to choose a tool.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_menu")
async def admin_menu_cb(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    if q.message:
        await show_admin_menu(q.message, switch_reply_keyboard=True, admin_uid=q.from_user.id)


def admin_back_markup(feature_callback="admin_features"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data=feature_callback)],
        [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
    ])


async def show_feature_controls(target):
    await target.answer(
        "🧩 <b>Feature Controls</b>\n\n"
        "🔐 <b>Purchase keys</b> — lock selected products and rotate keys.\n"
        "⏰ <b>Reminders</b> — automatic product expiry settings plus manual/non-listed reminders.\n"
        "📦 <b>Fulfillment modes</b> — instant delivery, email setup, or admin-prepared fulfilled-by-request orders.\n\n"
        "Use the <b>bottom keyboard</b> to choose a feature.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_features")
async def admin_features_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "features")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    if q.message:
        await show_feature_controls(q.message)


def admin_products_page_markup(mode: str, page: int = 0):
    products = get_products(False)
    per_page = 8
    max_page = max(0, (len(products) - 1) // per_page)
    page = max(0, min(int(page), max_page))
    start = page * per_page
    rows = []
    callback_prefix = {"key": "akp", "reminder": "arp", "email": "aep"}[mode]
    page_prefix = {"key": "akpg", "reminder": "arpg", "email": "aepg"}[mode]
    for product in products[start:start + per_page]:
        if mode == "key":
            state = "🔒" if product.get("purchase_key_required") else "🔓"
        elif mode == "email":
            fm = str(product.get("fulfillment_mode") or "instant")
            state = "📧" if fm == "email" else ("🛠" if fm == "manual" else ("🔐" if fm == "login_assist" else "⚡"))
        else:
            days = max(0, int(product.get("subscription_days", 0) or 0))
            state = f"⏰ {days}d" if days else "⏰ Off"
        rows.append([InlineKeyboardButton(text=f"{state} {product.get('name','Product')[:38]}", callback_data=f"{callback_prefix}:{product['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{page_prefix}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{max_page+1}", callback_data="noop"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{page_prefix}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Feature Controls", callback_data="admin_features")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "noop")
async def noop_cb(q: CallbackQuery):
    await q.answer()


async def show_key_products(target, page=0):
    await target.answer(
        "🔐 <b>Purchase Key Control</b>\n\nSelect a product. 🔒 means a key is required; 🔓 means normal checkout.",
        parse_mode="HTML", reply_markup=admin_products_page_markup("key", page),
    )


@dp.callback_query(F.data == "adm_keys")
async def adm_keys_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_key_products(q.message, 0)


@dp.callback_query(F.data.startswith("akpg:"))
async def adm_keys_page_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    await show_key_products(q.message, int(q.data.split(":", 1)[1]))


async def show_key_product(target, pid: str):
    product = products_col.find_one({"id": pid}, {"_id": 0})
    if not product:
        return await target.answer("Product not found.")
    required = bool(product.get("purchase_key_required", False))
    configured = bool(product.get("purchase_key_hash"))
    text = (
        f"🔐 <b>{html_escape(str(product.get('name') or pid))}</b>\n\n"
        f"Requirement: <b>{'ON 🔒' if required else 'OFF 🔓'}</b>\n"
        f"Key configured: <b>{'Yes ✅' if configured else 'No'}</b>\n\n"
        "The saved key itself cannot be displayed because only its one-way hash is stored. You can rotate it at any time."
    )
    rows = [
        [InlineKeyboardButton(text="✏️ Set / Rotate Custom Key", callback_data=f"aks:{pid}")],
        [InlineKeyboardButton(text="🎲 Generate New Key", callback_data=f"akg:{pid}")],
    ]
    if required:
        rows.append([InlineKeyboardButton(text="🔓 Disable Key Requirement", callback_data=f"ako:{pid}")])
    elif configured:
        rows.append([InlineKeyboardButton(text="🔒 Enable Saved Key", callback_data=f"ake:{pid}")])
    rows.extend([
        [InlineKeyboardButton(text="⬅️ Products", callback_data="adm_keys")],
        [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
    ])
    await target.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("akp:"))
async def adm_key_product_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_key_product(q.message, q.data.split(":", 1)[1])


@dp.callback_query(F.data.startswith("aks:"))
async def adm_key_set_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    set_admin_flow(q.from_user.id, "set_purchase_key", product_id=pid)
    await q.answer()
    await q.message.answer(
        f"🔐 Send the <b>new purchase key</b> for <b>{html_escape(product.get('name', pid))}</b>.\n\n"
        "Minimum 4 characters. The message will be deleted when possible and only a one-way hash will be stored.\n"
        "Send <code>/cancel</code> to stop.", parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("akg:"))
async def adm_key_generate_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    key = secrets.token_urlsafe(12)
    products_col.update_one({"id": pid}, {"$set": {
        "purchase_key_required": True,
        "purchase_key_hash": purchase_key_hash(pid, key),
        "updated_at": utcnow(),
    }})
    await q.answer("New key generated")
    await q.message.answer(
        f"✅ <b>New key generated and enabled</b>\n\nProduct: <b>{html_escape(product.get('name', pid))}</b>\n"
        f"Key: <code>{html_escape(key)}</code>\n\n⚠️ Save/copy this key now. It cannot be displayed again.",
        parse_mode="HTML", reply_markup=admin_back_markup("adm_keys"),
    )


@dp.callback_query(F.data.startswith("ako:"))
async def adm_key_disable_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    result = products_col.update_one({"id": pid}, {"$set": {"purchase_key_required": False, "updated_at": utcnow()}})
    await q.answer("Key requirement disabled" if result.matched_count else "Product not found", show_alert=not bool(result.matched_count))
    if result.matched_count:
        await show_key_product(q.message, pid)


@dp.callback_query(F.data.startswith("ake:"))
async def adm_key_enable_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "keys")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    product = products_col.find_one({"id": pid})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    if not product.get("purchase_key_hash"):
        return await q.answer("Set a key first.", show_alert=True)
    products_col.update_one({"id": pid}, {"$set": {"purchase_key_required": True, "updated_at": utcnow()}})
    await q.answer("Key requirement enabled")
    await show_key_product(q.message, pid)


async def show_reminder_menu(target):
    pending = subscription_reminders_col.count_documents({"status": "pending"})
    due = subscription_reminders_col.count_documents({"status": "pending", "remind_at": {"$lte": utcnow()}})
    await target.answer(
        f"⏰ <b>Subscription Reminders</b>\n\nPending: <b>{pending}</b>\nDue now: <b>{due}</b>\n"
        f"Manual dates entered without a timezone use <b>{html_escape(ADMIN_TIMEZONE_LABEL)}</b>.\n\n"
        "Use the <b>bottom keyboard</b> for reminder actions.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "adm_reminders")
async def adm_reminders_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_reminder_menu(q.message)


@dp.callback_query(F.data == "ar_products")
async def reminder_products_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    await q.message.answer(
        "⚙️ <b>Product Expiry Settings</b>\n\nChoose a product. Setting days to 0 disables automatic expiry reminders for future purchases.",
        parse_mode="HTML", reply_markup=admin_products_page_markup("reminder", 0),
    )


@dp.callback_query(F.data.startswith("arpg:"))
async def reminder_products_page_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    page = int(q.data.split(":", 1)[1])
    await q.message.answer("⚙️ <b>Product Expiry Settings</b>", parse_mode="HTML", reply_markup=admin_products_page_markup("reminder", page))


async def show_reminder_product(target, pid: str):
    product = products_col.find_one({"id": pid}, {"_id": 0})
    if not product:
        return await target.answer("Product not found.")
    variants = normalize_variants(product)
    variant_lines = "\n".join(
        f"• {html_escape(v['label'])}: <b>{int(v.get('subscription_days', 0) or 0)} days</b>" for v in variants[:12]
    )
    note = str(product.get("reminder_note") or "")
    await target.answer(
        f"⏰ <b>{html_escape(str(product.get('name') or pid))}</b>\n\n"
        f"Default duration: <b>{max(0, int(product.get('subscription_days', 0) or 0))} days</b>\n"
        f"Reminder note: <i>{html_escape(note) if note else 'None'}</i>\n\n"
        f"<b>Variants</b>\n{variant_lines or 'No variants'}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Set Duration for All Variants", callback_data=f"ard:{pid}")],
            [InlineKeyboardButton(text="📝 Set Reminder Note", callback_data=f"arn:{pid}")],
            [InlineKeyboardButton(text="⬅️ Products", callback_data="ar_products")],
            [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
        ]),
    )


@dp.callback_query(F.data.startswith("arp:"))
async def reminder_product_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_reminder_product(q.message, q.data.split(":", 1)[1])


@dp.callback_query(F.data.startswith("ard:"))
async def reminder_days_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    set_admin_flow(q.from_user.id, "set_subscription_days", product_id=pid)
    await q.answer()
    await q.message.answer(
        f"📅 Send subscription duration in <b>days</b> for <b>{html_escape(product.get('name', pid))}</b>.\n\n"
        "This updates all variants. Send <code>0</code> to disable automatic reminders for future purchases.\n"
        "Send <code>/cancel</code> to stop.", parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("arn:"))
async def reminder_note_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    set_admin_flow(q.from_user.id, "set_reminder_note", product_id=pid)
    await q.answer()
    await q.message.answer(
        f"📝 Send the private admin reminder note for <b>{html_escape(product.get('name', pid))}</b>.\n\n"
        "Send <code>clear</code> to remove it, or <code>/cancel</code> to stop.", parse_mode="HTML",
    )


@dp.callback_query(F.data == "ar_list")
async def reminder_list_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    rows = list(subscription_reminders_col.find(
        {"status": "pending"}
    ).sort("expires_at", 1).limit(15))
    if not rows:
        return await q.message.answer("⏰ No pending reminders.", reply_markup=admin_back_markup("adm_reminders"))
    kb = []
    lines = []
    for r in rows:
        oid = str(r.get("_id"))
        title = str(r.get("title") or r.get("product_name") or "Subscription")
        lines.append(f"• <b>{html_escape(title[:35])}</b> — {html_escape(format_admin_datetime(r.get('expires_at')))}")
        kb.append([InlineKeyboardButton(text=f"🔎 {title[:32]}", callback_data=f"arv:{oid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Reminders", callback_data="adm_reminders")])
    await q.message.answer("📋 <b>Upcoming reminders</b>\n\n" + "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data.startswith("arv:"))
async def reminder_view_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        oid = ObjectId(q.data.split(":", 1)[1])
    except Exception:
        return await q.answer("Invalid reminder", show_alert=True)
    r = subscription_reminders_col.find_one({"_id": oid})
    if not r:
        return await q.answer("Reminder not found", show_alert=True)
    await q.answer()
    text = format_admin_reminder(r).replace("This subscription expires in about 24 hours.", "Telegram control view.")
    await q.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Cancel Reminder", callback_data=f"arc:{oid}")],
            [InlineKeyboardButton(text="⬅️ Upcoming", callback_data="ar_list")],
        ]),
    )


@dp.callback_query(F.data.startswith("arc:"))
async def reminder_cancel_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        oid = ObjectId(q.data.split(":", 1)[1])
    except Exception:
        return await q.answer("Invalid reminder", show_alert=True)
    result = subscription_reminders_col.update_one(
        {"_id": oid, "status": {"$ne": "sent"}},
        {"$set": {"status": "cancelled", "cancelled_at": utcnow(), "updated_at": utcnow()}},
    )
    await q.answer("Reminder cancelled" if result.modified_count else "Could not cancel", show_alert=not bool(result.modified_count))
    if result.modified_count:
        await show_reminder_menu(q.message)


@dp.callback_query(F.data == "ar_add")
async def reminder_add_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    set_admin_flow(q.from_user.id, "manual_reminder_title")
    await q.answer()
    await q.message.answer(
        "➕ <b>New manual / non-listed reminder</b>\n\nStep 1/4: Send a title, e.g. <code>Netflix - John</code>.\n"
        "Send <code>/cancel</code> at any time.", parse_mode="HTML",
    )


@dp.callback_query(F.data == "ar_run")
async def reminder_run_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "reminders")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer("Checking reminders…")
    result = await process_due_reminders(100)
    await q.message.answer(
        f"✅ Reminder check finished.\nChecked: <b>{result['checked']}</b>\nSent: <b>{result['sent']}</b>\nFailed: <b>{result['failed']}</b>",
        parse_mode="HTML", reply_markup=admin_back_markup("adm_reminders"),
    )


async def show_email_menu(target):
    email_pending = orders_col.count_documents({"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    manual_pending = orders_col.count_documents({"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    await target.answer(
        f"📦 <b>Fulfillment Modes</b>\n\n"
        f"📧 Email setup waiting: <b>{email_pending}</b>\n"
        f"🛠 Fulfilled-by-request waiting: <b>{manual_pending}</b>\n\n"
        "Product modes:\n⚡ Instant = deliver from saved inventory\n📧 Email = ask customer email, then admin activates\n🛠 By request = admin prepares the order after payment\n🔐 Login assistance = customer completes sign-in on their own device; admin handles setup guidance.\n\n"
        "Use the <b>bottom keyboard</b> for fulfillment actions.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "adm_email")
async def email_menu_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_email_menu(q.message)


@dp.callback_query(F.data == "ae_products")
async def email_products_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    await q.message.answer(
        "📦 <b>Product Fulfillment Mode</b>\n\n⚡ Instant inventory delivery\n📧 Ask customer email\n🛠 Fulfilled by request / admin prepares after payment\n🔐 Customer login assistance / guided setup",
        parse_mode="HTML", reply_markup=admin_products_page_markup("email", 0),
    )


@dp.callback_query(F.data.startswith("aepg:"))
async def email_products_page_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    page = int(q.data.split(":", 1)[1])
    await q.message.answer("📦 <b>Product Fulfillment Mode</b>", parse_mode="HTML", reply_markup=admin_products_page_markup("email", page))


async def show_email_product(target, pid: str):
    product = products_col.find_one({"id": pid}, {"_id": 0})
    if not product:
        return await target.answer("Product not found.")
    mode = str(product.get("fulfillment_mode") or "instant")
    days = max(0, int(product.get("subscription_days", 0) or 0))
    mode_label = {
        "instant": "Instant digital delivery ⚡",
        "email": "Ask email / admin fulfills 📧",
        "manual": "Fulfilled by request / admin prepares 🛠",
        "login_assist": "Send activation code to admin 🔐",
    }.get(mode, mode)
    await target.answer(
        f"📦 <b>{html_escape(str(product.get('name') or pid))}</b>\n\n"
        f"Current mode: <b>{mode_label}</b>\n"
        f"Subscription duration: <b>{days} days</b>\n\n"
        "Email, by-request, and login-assistance modes do not consume saved digital inventory. Login assistance lets the customer complete sign-in on their own device while the admin handles the setup request.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=("✅ ⚡ Instant" if mode == "instant" else "⚡ Set Instant"), callback_data=f"aet:instant:{pid}")],
            [InlineKeyboardButton(text=("✅ 📧 Ask Email" if mode == "email" else "📧 Set Ask Email"), callback_data=f"aet:email:{pid}")],
            [InlineKeyboardButton(text=("✅ 🛠 By Request" if mode == "manual" else "🛠 Set Fulfilled by Request"), callback_data=f"aet:manual:{pid}")],
            [InlineKeyboardButton(text=("✅ 🔐 Login Assistance" if mode == "login_assist" else "🔐 Set Login Assistance"), callback_data=f"aet:login_assist:{pid}")],
            [InlineKeyboardButton(text="📅 Set Subscription Days", callback_data=f"ard:{pid}")],
            [InlineKeyboardButton(text="⬅️ Products", callback_data="ae_products")],
            [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
        ]),
    )


@dp.callback_query(F.data.startswith("aep:"))
async def email_product_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    clear_admin_flow(q.from_user.id)
    await q.answer()
    await show_email_product(q.message, q.data.split(":", 1)[1])


@dp.callback_query(F.data.startswith("aet:"))
async def email_toggle_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    parts = q.data.split(":", 2)
    if len(parts) == 3 and parts[1] in {"instant", "email", "manual", "login_assist"}:
        new_mode, pid = parts[1], parts[2]
    else:
        # Backward compatibility with old two-part buttons.
        pid = q.data.split(":", 1)[1]
        product = products_col.find_one({"id": pid})
        current = str((product or {}).get("fulfillment_mode") or "instant")
        new_mode = "instant" if current != "instant" else "email"
    product = products_col.find_one({"id": pid})
    if not product:
        return await q.answer("Product not found", show_alert=True)
    update = {"fulfillment_mode": new_mode, "updated_at": utcnow()}
    if new_mode != "instant":
        update["otp_enabled"] = False
    products_col.update_one({"id": pid}, {"$set": update})
    await q.answer("Product mode updated")
    await show_email_product(q.message, pid)



@dp.callback_query(F.data == "am_pending")
async def manual_pending_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    orders = list(orders_col.find(
        {"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
        {"digital_delivery": 0},
    ).sort("created_at", 1).limit(30))
    buttons = []
    lines = []
    for order in orders:
        code = str(order.get("order_code") or "")
        for idx, entry in enumerate(order.get("manual_fulfillment") or []):
            if str(entry.get("status") or "pending") == "fulfilled":
                continue
            title = str(entry.get("name") or "Requested product")
            qty = int(entry.get("qty") or 1)
            wait = fulfillment_wait_seconds(order, entry)
            level = fulfillment_sla_level(order, entry)
            marker = "🔴" if level >= 2 else ("🟠" if level == 1 else "🟢")
            lines.append(f"• {marker} <b>#{html_escape(code)}</b> — {html_escape(title[:34])} × {qty} • {html_escape(format_wait_duration(wait))}")
            buttons.append([InlineKeyboardButton(text=f"🛠 #{code} • {title[:22]}", callback_data=f"amv:{code}:{idx}")])
    if not buttons:
        return await q.message.answer("✅ No pending fulfilled-by-request orders.", reply_markup=admin_back_markup("adm_email"))
    buttons.append([InlineKeyboardButton(text="⬅️ Fulfillment Modes", callback_data="adm_email")])
    await q.message.answer(
        "🛠 <b>Pending fulfilled-by-request orders</b>\n\n" + "\n".join(lines),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def show_pending_manual_entry(target, code: str, idx: int):
    order = orders_col.find_one({"order_code": code}, {"_id": 0, "digital_delivery": 0})
    if not order:
        return await target.answer("Order not found.")
    entries = list(order.get("manual_fulfillment") or [])
    if idx < 0 or idx >= len(entries):
        return await target.answer("Fulfillment item not found.")
    entry = entries[idx]
    status = str(entry.get("status") or "pending")
    days = max(0, int(entry.get("subscription_days", 0) or 0))
    text = (
        f"🛠 <b>Order #{html_escape(code)}</b>\n\n"
        f"Product: <b>{html_escape(str(entry.get('name') or 'Requested product'))}</b>\n"
        f"Quantity: <b>{int(entry.get('qty') or 1)}</b>\n"
        f"Customer ID: <code>{int(order.get('user_id'))}</code>\n"
        f"Configured duration: <b>{days} days</b>\n"
        f"Waiting: <b>{html_escape(format_wait_duration(fulfillment_wait_seconds(order, entry)))}</b>\n"
        f"Status: <b>{html_escape(status.replace('_',' ').title())}</b>\n\n"
        "When ready, tap Deliver and send the prepared account/details exactly as the customer should receive them."
    )
    rows = []
    if status != "fulfilled":
        rows.append([InlineKeyboardButton(text="🎁 Deliver prepared order", callback_data=f"amd:{code}:{idx}")])
    rows.extend([
        [InlineKeyboardButton(text="⬅️ Pending By-Request", callback_data="am_pending")],
        [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
    ])
    await target.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("lac:"))
async def login_assistance_code_prompt_cb(q: CallbackQuery):
    if not q.from_user:
        return await q.answer("Unable to identify customer", show_alert=True)
    try:
        _, code = q.data.split(":", 1)
    except Exception:
        return await q.answer("Invalid activation request", show_alert=True)
    order = orders_col.find_one({"order_code": code, "user_id": int(q.from_user.id)}, {"_id": 0})
    if not order:
        return await q.answer("Order not found", show_alert=True)
    entries = list(order.get("manual_fulfillment") or [])
    login_entries = [(i, e) for i, e in enumerate(entries) if bool(e.get("login_assistance")) and str(e.get("status") or "pending") != "fulfilled"]
    if not login_entries:
        return await q.answer("No pending activation request", show_alert=True)
    idx, entry = login_entries[0]
    if entry.get("activation_code_submitted"):
        await q.answer("Activation code already sent", show_alert=True)
        return await q.message.answer("✅ Your activation code was already sent to the admin. Please wait for activation.")
    set_customer_activation_flow(int(q.from_user.id), order_code=code, fulfillment_index=idx)
    prompt = str(entry.get("activation_prompt") or "Please send the activation code shown by the service.").strip()
    await q.answer()
    await q.message.answer(
        f"🔐 <b>Send activation code</b>\n\n{html_escape(prompt)}\n\n"
        "Reply to this message with the code.\nSend /cancel to stop.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("amv:"))
async def manual_entry_view_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2)
        idx = int(idx)
    except Exception:
        return await q.answer("Invalid order item", show_alert=True)
    await q.answer()
    await show_pending_manual_entry(q.message, code, idx)


async def begin_manual_delivery_input(target, code: str, idx: int, template_id: str = ""):
    order = orders_col.find_one({"order_code": code}, {"_id": 0, "manual_fulfillment": 1, "user_id": 1})
    entries = list((order or {}).get("manual_fulfillment") or [])
    if idx < 0 or idx >= len(entries):
        return await target.answer("Order item not found")
    entry = entries[idx]
    if str(entry.get("status") or "pending") == "fulfilled":
        return await target.answer("Already fulfilled")
    set_admin_flow(ADMIN_ID, "manual_order_delivery", order_code=code, fulfillment_index=idx)
    template_text = ""
    if template_id:
        tpl = fulfillment_templates_col.find_one({"id": template_id, "active": {"$ne": False}})
        if tpl and (not tpl.get("product_id") or str(tpl.get("product_id")) == str(entry.get("product_id") or "")):
            rendered = render_fulfillment_template(str(tpl.get("body") or ""), {"order_code": code, "user_id": order.get("user_id")}, entry)
            template_text = f"\n\n<b>Template — {html_escape(str(tpl.get('name') or 'Saved'))}</b>\n<pre>{html_escape(rendered)}</pre>\nCopy/edit it and send the final delivery as your next message."
    await target.answer(
        f"🎁 <b>Prepare delivery for order #{html_escape(code)}</b>\n\n"
        "Send the account, login, code, subscription details, instructions, or other prepared delivery text exactly as the customer should receive it."
        + template_text
        + "\n\nThe final delivery is encrypted before it is stored. Maximum 3000 characters. Send /cancel to stop.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("amd:"))
async def manual_delivery_prompt_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2)
        idx = int(idx)
    except Exception:
        return await q.answer("Invalid order item", show_alert=True)
    order = orders_col.find_one({"order_code": code}, {"_id": 0, "manual_fulfillment": 1})
    entries = list((order or {}).get("manual_fulfillment") or [])
    if idx < 0 or idx >= len(entries):
        return await q.answer("Order item not found", show_alert=True)
    entry = entries[idx]
    if str(entry.get("status") or "pending") == "fulfilled":
        return await q.answer("Already fulfilled", show_alert=True)
    templates = applicable_fulfillment_templates(str(entry.get("product_id") or ""))[:8]
    await q.answer()
    if not templates:
        return await begin_manual_delivery_input(q.message, code, idx)
    rows = [[InlineKeyboardButton(text=f"🧾 {t['name'][:35]}", callback_data=f"amdt:{code}:{idx}:{t['id']}")] for t in templates]
    rows.append([InlineKeyboardButton(text="✍️ Write manually", callback_data=f"amdr:{code}:{idx}")])
    rows.append([InlineKeyboardButton(text="⬅️ Order", callback_data=f"amv:{code}:{idx}")])
    await q.message.answer(
        "🧾 <b>Choose a delivery template</b>\n\nSelect a saved template or write the delivery manually.",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.callback_query(F.data.startswith("amdr:"))
async def manual_delivery_raw_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2); idx = int(idx)
    except Exception:
        return await q.answer("Invalid order item", show_alert=True)
    await q.answer()
    await begin_manual_delivery_input(q.message, code, idx)


@dp.callback_query(F.data.startswith("amdt:"))
async def manual_delivery_template_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx, tid = q.data.split(":", 3); idx = int(idx)
    except Exception:
        return await q.answer("Invalid template selection", show_alert=True)
    await q.answer()
    await begin_manual_delivery_input(q.message, code, idx, tid)


@dp.callback_query(F.data == "ae_pending")
async def email_pending_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    orders = list(orders_col.find(
        {"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
        {"digital_delivery": 0},
    ).sort("created_at", 1).limit(20))
    buttons = []
    lines = []
    for order in orders:
        code = str(order.get("order_code") or "")
        for idx, entry in enumerate(order.get("email_fulfillment") or []):
            if str(entry.get("status") or "pending") == "fulfilled":
                continue
            title = str(entry.get("name") or "Subscription")
            email = str(entry.get("email") or "")
            wait = fulfillment_wait_seconds(order, entry)
            level = fulfillment_sla_level(order, entry)
            marker = "🔴" if level >= 2 else ("🟠" if level == 1 else "🟢")
            lines.append(f"• {marker} <b>#{html_escape(code)}</b> — {html_escape(title[:30])} • {html_escape(format_wait_duration(wait))}\n  <code>{html_escape(email)}</code>")
            buttons.append([InlineKeyboardButton(text=f"📧 #{code} • {title[:24]}", callback_data=f"aev:{code}:{idx}")])
    if not buttons:
        return await q.message.answer("✅ No pending email-subscription orders.", reply_markup=admin_back_markup("adm_email"))
    buttons.append([InlineKeyboardButton(text="⬅️ Email Fulfillment", callback_data="adm_email")])
    await q.message.answer(
        "⏳ <b>Pending email subscriptions</b>\n\n" + "\n".join(lines),
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def show_pending_email_entry(target, code: str, idx: int):
    order = orders_col.find_one({"order_code": code}, {"_id": 0, "digital_delivery": 0})
    if not order:
        return await target.answer("Order not found.")
    entries = list(order.get("email_fulfillment") or [])
    if idx < 0 or idx >= len(entries):
        return await target.answer("Fulfillment item not found.")
    entry = entries[idx]
    status = str(entry.get("status") or "pending")
    days = max(0, int(entry.get("subscription_days", 0) or 0))
    text = (
        f"📧 <b>Order #{html_escape(code)}</b>\n\n"
        f"Product: <b>{html_escape(str(entry.get('name') or 'Subscription'))}</b>\n"
        f"Customer ID: <code>{int(order.get('user_id'))}</code>\n"
        f"Email: <code>{html_escape(str(entry.get('email') or ''))}</code>\n"
        f"Configured duration: <b>{days} days</b>\n"
        f"Waiting: <b>{html_escape(format_wait_duration(fulfillment_wait_seconds(order, entry)))}</b>\n"
        f"Status: <b>{html_escape(status.replace('_',' ').title())}</b>"
    )
    rows = []
    if status != "fulfilled":
        label = f"✅ Fulfill + {days}d Expiry" if days > 0 else "✅ Fulfill (No Expiry)"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"aea:{code}:{idx}")])
        rows.append([InlineKeyboardButton(text="📅 Fulfill with Custom Expiry", callback_data=f"aec:{code}:{idx}")])
    rows.extend([
        [InlineKeyboardButton(text="⬅️ Pending Orders", callback_data="ae_pending")],
        [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
    ])
    await target.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("aev:"))
async def email_entry_view_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2)
        idx = int(idx)
    except Exception:
        return await q.answer("Invalid order item", show_alert=True)
    await q.answer()
    await show_pending_email_entry(q.message, code, idx)


@dp.callback_query(F.data.startswith("aea:"))
async def email_fulfill_auto_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2)
        idx = int(idx)
        result = await fulfill_email_order(code, idx)
    except (ValueError, LookupError) as exc:
        return await q.answer(str(exc), show_alert=True)
    await q.answer("Already fulfilled" if result.get("already_fulfilled") else "Fulfilled ✅")
    expiry = result.get("expires_at")
    await q.message.answer(
        "✅ <b>Subscription fulfilled</b>" + (f"\nExpiry: <b>{html_escape(format_admin_datetime(expiry))}</b>" if expiry else "\nNo expiry reminder was scheduled."),
        parse_mode="HTML", reply_markup=admin_back_markup("adm_email"),
    )


@dp.callback_query(F.data.startswith("aec:"))
async def email_fulfill_custom_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "fulfillment")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    try:
        _, code, idx = q.data.split(":", 2)
        idx = int(idx)
    except Exception:
        return await q.answer("Invalid order item", show_alert=True)
    set_admin_flow(q.from_user.id, "fulfill_custom_expiry", order_code=code, fulfillment_index=idx)
    await q.answer()
    await q.message.answer(
        f"📅 Send the exact expiry for <b>order #{html_escape(code)}</b>.\n\n"
        f"Use <code>DD-MM-YYYY HH:MM</code> ({html_escape(ADMIN_TIMEZONE_LABEL)}), e.g. <code>30-09-2026 18:00</code>.\n"
        "You can also send ISO with an explicit timezone. Send <code>/cancel</code> to stop.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "menu_balance")
async def cb_balance(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    if q.message:
        await q.message.answer(f"💳 <b>{money(get_balance(q.from_user.id))}</b>\n🆔 <code>{q.from_user.id}</code>", parse_mode="HTML")


async def send_orders(target, uid):
    rows = list(orders_col.find({"user_id": int(uid)}, {"_id": 0, "digital_delivery": 0}).sort("created_at", -1).limit(10))
    if not rows:
        return await target.answer("📦 No completed orders yet.")
    kb = []
    lines = []
    for r in rows:
        code = r["order_code"]
        lines.append(f"• <b>#{code}</b> — {money(r.get('total_credits', 0))}")
        row = [InlineKeyboardButton(text=f"🧾 #{code}", callback_data=f"receipt:{code}")]
        if OWNER_USERNAME:
            row.append(InlineKeyboardButton(text="💬 Support", url=f"https://t.me/{OWNER_USERNAME}?text={quote('Support for order #'+code)}"))
        kb.append(row)
    await target.answer("📦 <b>Orders & receipt history</b>\n\n" + "\n".join(lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))



def otp_order_choices(uid: int, limit: int = 30):
    orders = list(
        orders_col.find({"user_id": int(uid)}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    result = []
    for order in orders:
        enabled = []
        for di, delivery in enumerate(order.get("digital_delivery") or []):
            if not delivery.get("otp_enabled"):
                continue
            count = len(delivery.get("items_enc") or delivery.get("items") or [])
            if count:
                enabled.append((di, delivery, count))
        if enabled:
            result.append((order, enabled))
    return result


async def send_otp_order_selector(target, uid: int):
    choices = otp_order_choices(uid)
    if not choices:
        return await target.answer(
            "🔐 <b>OTP</b>\n\nYou do not have any OTP-enabled orders yet.",
            parse_mode="HTML",
        )

    rows = []
    for order, enabled in choices[:20]:
        code = str(order.get("order_code") or "")
        total_accounts = sum(count for _, _, count in enabled)
        rows.append([
            InlineKeyboardButton(
                text=f"🔐 #{code} • {total_accounts} account{'s' if total_accounts != 1 else ''}",
                callback_data=f"otporder:{code}",
            )
        ])

    await target.answer(
        "🔐 <b>Select an order for OTP</b>\n\n"
        "Choose the order whose OTP you need. "
        "After that, select the account/product.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(F.text == "🔐 OTP")
async def otp_menu_message(m: Message):
    if await gate_message(m):
        await send_otp_order_selector(m, m.from_user.id)


@dp.callback_query(F.data == "menu_otp")
async def otp_menu_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    if q.message:
        await send_otp_order_selector(q.message, q.from_user.id)


@dp.callback_query(F.data.startswith("otporder:"))
async def otp_order_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return

    code = q.data.split(":", 1)[1]
    order = orders_col.find_one(
        {"order_code": code, "user_id": q.from_user.id},
        {"_id": 0},
    )
    if not order:
        return await q.answer("Order not found.", show_alert=True)

    rows = []
    for di, delivery in enumerate(order.get("digital_delivery") or []):
        if not delivery.get("otp_enabled"):
            continue

        price = max(1, int(delivery.get("otp_price") or OTP_PRICE))
        items = delivery.get("items_enc") or delivery.get("items") or []
        product_name = str(delivery.get("name") or "Digital product")

        for ii in range(len(items)):
            label = product_name
            if len(items) > 1:
                label += f" • Account #{ii + 1}"
            rows.append([
                InlineKeyboardButton(
                    text=f"🔐 {label[:38]} • {price} credits",
                    callback_data=f"paidotp:{code}:{di}:{ii}",
                )
            ])

    if not rows:
        return await q.answer("No OTP-enabled account was found in this order.", show_alert=True)

    await q.answer()
    await q.message.answer(
        f"🔐 <b>Order #{html_escape(code)}</b>\n\n"
        "Select the account/product for which you want a fresh OTP.\n\n"
        "The bot waits for the start of a new TOTP cycle, so the OTP is delivered "
        "with approximately the full <b>30-second</b> validity window. "
        "Credits are charged only after the fresh OTP is generated.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@dp.message(F.text.in_({"🌐 Language", "🌐 Bahasa"}))
async def language_button(m: Message):
    await m.answer(tr(m.from_user.id, "choose_language"), parse_mode="HTML", reply_markup=language_markup(m.from_user.id))


@dp.callback_query(F.data == "menu_language")
async def language_inline(q: CallbackQuery):
    await q.answer()
    if q.message:
        await q.message.answer(tr(q.from_user.id, "choose_language"), parse_mode="HTML", reply_markup=language_markup(q.from_user.id))


@dp.callback_query(F.data.startswith("lang:"))
async def set_language(q: CallbackQuery):
    lang = q.data.split(":", 1)[1]
    if lang not in {"en", "id"}:
        return await q.answer("Invalid language", show_alert=True)
    users_col.update_one({"user_id": q.from_user.id}, {"$set": {"language": lang}}, upsert=True)
    _invalidate_language_cache(q.from_user.id)
    await q.answer(I18N[lang]["changed"], show_alert=False)
    if q.message:
        await q.message.answer(
            I18N[lang]["changed"],
            reply_markup=shop_keyboard(q.from_user.id),
        )
        await q.message.answer(
            I18N[lang]["home_choose"],
            reply_markup=action_menu(q.from_user.id, q.from_user.id == ADMIN_ID),
        )


@dp.message(F.text.in_({"💰 Buy Credits", "💰 Beli Kredit"}))
async def buy_credits_message(m: Message):
    if not await user_is_member(m.from_user.id):
        return await send_join_gate(m)
    text = (
        f"💰 <b>Buy Credits</b>\n\n"
        f"🇮🇳 <b>{html_escape(CREDIT_RATE_INR)}</b>\n"
        f"🇺🇸 <b>{html_escape(CREDIT_RATE_USD)}</b>\n\n"
        f"Tap the button below to message the admin directly. "
        f"Your Telegram ID will be included automatically."
    )
    await m.answer(text, parse_mode="HTML", reply_markup=buy_credit_markup(m.from_user.id))


@dp.callback_query(F.data == "menu_buy_credits")
async def buy_credits_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    text = (
        f"💰 <b>Buy Credits</b>\n\n"
        f"🇮🇳 <b>{html_escape(CREDIT_RATE_INR)}</b>\n"
        f"🇺🇸 <b>{html_escape(CREDIT_RATE_USD)}</b>\n\n"
        f"Tap below to contact the admin directly."
    )
    await q.message.answer(text, parse_mode="HTML", reply_markup=buy_credit_markup(q.from_user.id))


@dp.message(F.text.in_({"📦 My Orders", "📦 Pesanan Saya"}))
async def orders_message(m: Message):
    if await gate_message(m):
        await send_orders(m, m.from_user.id)


@dp.callback_query(F.data == "menu_orders")
async def cb_orders(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    if q.message:
        await send_orders(q.message, q.from_user.id)


@dp.callback_query(F.data.startswith("receipt:"))
async def receipt_cb(q: CallbackQuery):
    if not await gate_callback(q):
        return
    code = q.data.split(":", 1)[1]
    order = orders_col.find_one({"order_code": code, "user_id": q.from_user.id}, {"_id": 0})
    if not order:
        return await q.answer("Receipt not found", show_alert=True)
    await q.answer()
    if q.message:
        await q.message.answer(build_receipt(order, q.from_user.id), parse_mode="HTML", reply_markup=support_markup(code))


@dp.message(F.text.in_({"💳 Balance", "💳 Saldo"}))
async def balance_message(m: Message):
    if await gate_message(m):
        await m.answer(f"💳 <b>{money(get_balance(m.from_user.id))}</b>\n🆔 <code>{m.from_user.id}</code>", parse_mode="HTML")


async def send_wishlist(target, uid):
    ids = [x["product_id"] for x in wishlists_col.find({"user_id": int(uid)}, {"_id": 0, "product_id": 1})]
    if not ids:
        return await target.answer("❤️ Your wishlist is empty. Add favorites inside the shop.")
    products = {p["id"]: p for p in get_products(False)}
    lines = []
    for pid in ids:
        product = products.get(pid)
        if product:
            lines.append(f"❤️ <b>{product['name']}</b> — {product.get('stock', 0)} available")
    await target.answer("❤️ <b>Your wishlist</b>\n\n" + ("\n".join(lines) or "No saved products."), parse_mode="HTML", reply_markup=fresh_shop_markup(uid, wishlist=True))


@dp.message(F.text.in_({"❤️ Wishlist", "❤️ Favorit"}))
async def wishlist_message(m: Message):
    if await gate_message(m):
        await send_wishlist(m, m.from_user.id)


@dp.callback_query(F.data == "menu_wishlist")
async def wishlist_cb(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    if q.message:
        await send_wishlist(q.message, q.from_user.id)


async def send_referral(target, uid):
    username = await get_bot_username()
    link = f"https://t.me/{username}?start=ref_{int(uid)}"
    awarded = referrals_col.count_documents({"referrer_id": int(uid), "status": "awarded"})
    await target.answer(
        f"🎁 <b>Refer & Earn</b>\n\nEarn <b>{REFERRAL_CREDIT} credits</b> for each referred user who starts the bot <b>and joins the required group</b>.\n\n"
        f"Successful referrals: <b>{awarded}</b>\nYour link:\n<code>{link}</code>",
        parse_mode="HTML",
    )


@dp.message(F.text.in_({"🎁 Refer & Earn", "🎁 Referensi & Dapatkan"}))
async def referral_message(m: Message):
    if await gate_message(m):
        await send_referral(m, m.from_user.id)


@dp.callback_query(F.data == "menu_referral")
async def referral_cb(q: CallbackQuery):
    if not await gate_callback(q):
        return
    await q.answer()
    if q.message:
        await send_referral(q.message, q.from_user.id)


@dp.message(F.text.in_({"ℹ️ Help Guide", "ℹ️ Panduan Bantuan"}))
async def help_message(m: Message):
    if not await gate_message(m):
        return
    await m.answer(
        "ℹ️ <b>Help Guide</b>\n\n1. Join the required group.\n2. Open the shop.\n3. Choose a product/variant.\n4. Review the cart confirmation.\n5. Pay with credits.\n6. Your receipt and digital delivery arrive privately.\n7. Use Orders for receipt history or Support for help.",
        parse_mode="HTML",
        reply_markup=support_markup(),
    )


@dp.message(Command("credit_add"))
async def credit_add(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, amt = m.text.split()
        new = adjust_credit(int(uid), int(amt), ADMIN_ID)
        await m.answer(f"✅ <code>{uid}</code>: {int(amt):+,} → <b>{money(new)}</b>", parse_mode="HTML")
        try:
            await bot.send_message(int(uid), f"💳 Balance updated: <b>{money(new)}</b>", parse_mode="HTML")
        except Exception:
            pass
    except Exception as exc:
        await m.answer(f"Usage: /credit_add USER_ID AMOUNT\n{exc}")


@dp.message(Command("credit_set"))
async def credit_set(m: Message):
    if m.from_user.id != ADMIN_ID:
        return
    try:
        _, uid, amt = m.text.split()
        new = adjust_credit(int(uid), 0, ADMIN_ID, set_to=int(amt))
        await m.answer(f"✅ Balance set: <b>{money(new)}</b>", parse_mode="HTML")
    except Exception as exc:
        await m.answer(f"Usage: /credit_set USER_ID AMOUNT\n{exc}")



# ─────────────────────────────────────────────────────────────────────────────
# Full Telegram admin parity helpers/handlers
# These controls use the same MongoDB collections as the web admin.
# ─────────────────────────────────────────────────────────────────────────────

TG_ADMIN_PAGE_SIZE = 8


def tg_admin_only(q: CallbackQuery) -> bool:
    return bool(q.from_user and q.from_user.id == ADMIN_ID)


def tg_trim(value, limit=700):
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def tg_product_variants_text(product):
    rows = []
    for v in product.get("variants") or []:
        rows.append(f"{v.get('label','Default')}|{int(v.get('price', product.get('price', 0)))}|{int(v.get('low_stock', DEFAULT_LOW_STOCK))}|{int(v.get('subscription_days', product.get('subscription_days', 0)) or 0)}")
    return "\n".join(rows)


def tg_product_summary(p):
    fm = str(p.get("fulfillment_mode") or "instant")
    mode = (
        "📧 Email fulfillment" if fm == "email"
        else ("🛠 Fulfilled by request" if fm == "manual"
              else ("🔐 Customer login assistance" if fm == "login_assist"
                    else f"⚡ Instant • stock {product_total_stock(p['id'])}"))
    )
    return (
        f"{html_escape(str(p.get('emoji') or '🔑'))} <b>{html_escape(str(p.get('name') or p['id']))}</b>\n"
        f"ID: <code>{html_escape(str(p['id']))}</code>\n"
        f"Price: <b>{money(p.get('price', 0))}</b> • Category: {html_escape(str(p.get('category') or 'General'))}\n"
        f"{mode}\n"
        f"Active: {'✅' if p.get('active') else '❌'} • Featured: {'✅' if p.get('featured') else '❌'} • Bestseller: {'✅' if p.get('bestseller') else '❌'} • New: {'✅' if p.get('badge_new') else '❌'}\n"
        f"Purchase key: {'🔒 required' if p.get('purchase_key_required') else ('🔓 saved/off' if p.get('purchase_key_hash') else '—')}\n"
        f"Subscription: {int(p.get('subscription_days') or 0)} days • OTP: {'✅ '+money(p.get('otp_price', OTP_PRICE)) if p.get('otp_enabled') else '❌'}"
    )


def tg_product_list_markup(page=0):
    products = get_products(False)
    start = max(0, page) * TG_ADMIN_PAGE_SIZE
    rows = []
    for p in products[start:start + TG_ADMIN_PAGE_SIZE]:
        state = "✅" if p.get("active") else "⛔"
        rows.append([InlineKeyboardButton(text=f"{state} {p.get('emoji','🔑')} {str(p.get('name') or p['id'])[:34]}", callback_data=f"tgp:{p['id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"tgadm_products:{page-1}"))
    if start + TG_ADMIN_PAGE_SIZE < len(products):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"tgadm_products:{page+1}"))
    if nav:
        rows.append(nav)
    rows += [
        [InlineKeyboardButton(text="➕ Create product", callback_data="tgp_new")],
        [InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def tg_show_products(target, page=0):
    count = products_col.count_documents({})
    await target.answer(
        f"🛍 <b>Products</b>\n\nTotal: <b>{count}</b>\nSelect a product to edit every field, inventory, image, visibility, OTP, fulfillment, reminders and purchase-key settings.",
        parse_mode="HTML", reply_markup=tg_product_list_markup(page),
    )


@dp.callback_query(F.data.startswith("tgadm_products:"))
async def tg_products_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q):
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    page = int(q.data.rsplit(":", 1)[1])
    await tg_show_products(q.message, page)


@dp.callback_query(F.data.startswith("tgp:"))
async def tg_product_detail_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q):
        return await q.answer("Admin only", show_alert=True)
    pid = q.data.split(":", 1)[1]
    p = products_col.find_one({"id": pid}, {"_id": 0})
    if not p:
        return await q.answer("Product not found", show_alert=True)
    await q.answer()
    rows = [
        [InlineKeyboardButton(text="✏️ Basic fields", callback_data=f"tgpb:{pid}"), InlineKeyboardButton(text="📝 Delivery notes", callback_data=f"tgpd:{pid}")],
        [InlineKeyboardButton(text="🏷 Variants", callback_data=f"tgpv:{pid}"), InlineKeyboardButton(text="📦 Add inventory", callback_data=f"tgpi:{pid}")],
        [InlineKeyboardButton(text="🖼 Image", callback_data=f"tgpimg:{pid}"), InlineKeyboardButton(text="🔐 OTP settings", callback_data=f"tgp_otp:{pid}")],
        [InlineKeyboardButton(text="👁 Visibility/badges", callback_data=f"tgpflags:{pid}"), InlineKeyboardButton(text="🧩 Purchase/subscription", callback_data=f"tgpfeat:{pid}")],
        [InlineKeyboardButton(text="🗑 Delete / archive", callback_data=f"tgpdelask:{pid}")],
        [InlineKeyboardButton(text="⬅️ Products", callback_data="tgadm_products:0"), InlineKeyboardButton(text="🏠 Dashboard", callback_data="admin_menu")],
    ]
    await q.message.answer(tg_product_summary(p), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


TG_PRODUCT_FIELD_CODES = {
    "n": ("name", "Product name"), "p": ("price", "Base price"), "c": ("category", "Category"), "e": ("emoji", "Emoji"),
    "d": ("description", "Description"), "i": ("instructions", "Instructions"), "w": ("warranty", "Warranty"),
    "s": ("support_note", "Support note"), "l": ("delivery_note", "Delivery note"), "op": ("otp_price", "OTP price"),
    "sd": ("subscription_days", "Subscription days"), "rn": ("reminder_note", "Reminder note"),
}


def tg_field_buttons(pid, codes, back):
    rows = []
    for code in codes:
        field, label = TG_PRODUCT_FIELD_CODES[code]
        rows.append([InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"tgpf:{code}:{pid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Product", callback_data=f"tgp:{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("tgpb:"))
async def tg_product_basic(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]; p=products_col.find_one({"id":pid},{"_id":0})
    await q.answer()
    if not p: return await q.message.answer("Product not found")
    text=(f"✏️ <b>Basic fields</b>\n\nName: {html_escape(str(p.get('name','')))}\nPrice: {money(p.get('price',0))}\nCategory: {html_escape(str(p.get('category','General')))}\nEmoji: {html_escape(str(p.get('emoji','🔑')))}\n\nDescription:\n{html_escape(tg_trim(p.get('description'),500) or '—')}")
    await q.message.answer(text,parse_mode="HTML",reply_markup=tg_field_buttons(pid,["n","p","c","e","d"],""))


@dp.callback_query(F.data.startswith("tgpd:"))
async def tg_product_delivery_fields(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]; p=products_col.find_one({"id":pid},{"_id":0})
    await q.answer()
    if not p: return await q.message.answer("Product not found")
    text=("📝 <b>Delivery information</b>\n\n"
          f"Instructions: {html_escape(tg_trim(p.get('instructions'),240) or '—')}\n\n"
          f"Warranty: {html_escape(tg_trim(p.get('warranty'),180) or '—')}\n\n"
          f"Support: {html_escape(tg_trim(p.get('support_note'),180) or '—')}\n\n"
          f"Delivery note: {html_escape(tg_trim(p.get('delivery_note'),180) or '—')}")
    await q.message.answer(text,parse_mode="HTML",reply_markup=tg_field_buttons(pid,["i","w","s","l"],""))


@dp.callback_query(F.data.startswith("tgpf:"))
async def tg_product_field_prompt(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    try: _,code,pid=q.data.split(":",2)
    except ValueError: return
    spec=TG_PRODUCT_FIELD_CODES.get(code); p=products_col.find_one({"id":pid},{"_id":0})
    if not spec or not p: return await q.answer("Invalid field",show_alert=True)
    field,label=spec
    set_admin_flow(q.from_user.id,"tg_product_field",product_id=pid,field_code=code)
    await q.answer()
    current=p.get(field,"")
    await q.message.answer(f"✏️ <b>{html_escape(label)}</b>\n\nCurrent: <code>{html_escape(tg_trim(current,400) or '—')}</code>\n\nSend the new value. For text fields send <code>clear</code> to empty it, or /cancel.",parse_mode="HTML")


@dp.callback_query(F.data == "tgp_new")
async def tg_new_product(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    set_admin_flow(q.from_user.id,"tg_product_new_name")
    await q.answer()
    await q.message.answer("➕ <b>Create product</b>\n\nStep 1/2: send the product name. Send /cancel to stop.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgpflags:"))
async def tg_product_flags(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]; p=products_col.find_one({"id":pid},{"_id":0})
    if not p: return await q.answer("Product not found",show_alert=True)
    await q.answer()
    rows=[]
    for key,label in [("active","Active"),("featured","Featured"),("bestseller","Bestseller"),("badge_new","New badge")]:
        rows.append([InlineKeyboardButton(text=f"{'✅' if p.get(key) else '❌'} {label}", callback_data=f"tgpt:{key}:{pid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Product",callback_data=f"tgp:{pid}")])
    await q.message.answer("👁 <b>Visibility & badges</b>\n\nTap a setting to toggle it.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("tgpt:"))
async def tg_product_toggle(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    try: _,key,pid=q.data.split(":",2)
    except ValueError: return
    if key not in {"active","featured","bestseller","badge_new","otp_enabled"}: return await q.answer("Invalid",show_alert=True)
    p=products_col.find_one({"id":pid})
    if not p: return await q.answer("Product not found",show_alert=True)
    if key=="otp_enabled" and str(p.get("fulfillment_mode") or "instant")!="instant":
        return await q.answer("OTP can only be enabled for instant-delivery products.",show_alert=True)
    new=not bool(p.get(key))
    products_col.update_one({"id":pid},{"$set":{key:new,"updated_at":utcnow()}})
    await q.answer(f"{key} {'ON' if new else 'OFF'}")
    if key=="otp_enabled":
        await tg_product_otp_menu(q.message,pid)
    else:
        p=products_col.find_one({"id":pid},{"_id":0})
        rows=[]
        for k,label in [("active","Active"),("featured","Featured"),("bestseller","Bestseller"),("badge_new","New badge")]:
            rows.append([InlineKeyboardButton(text=f"{'✅' if p.get(k) else '❌'} {label}", callback_data=f"tgpt:{k}:{pid}")])
        rows.append([InlineKeyboardButton(text="⬅️ Product",callback_data=f"tgp:{pid}")])
        await q.message.answer("👁 <b>Visibility & badges updated</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("tgpv:"))
async def tg_product_variants(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]; p=products_col.find_one({"id":pid},{"_id":0})
    if not p: return await q.answer("Product not found",show_alert=True)
    await q.answer()
    txt=tg_product_variants_text(p) or f"Default|{p.get('price',0)}|{DEFAULT_LOW_STOCK}|{p.get('subscription_days',0)}"
    set_admin_flow(q.from_user.id,"tg_product_variants",product_id=pid)
    await q.message.answer("🏷 <b>Edit variants</b>\n\nCurrent:\n<pre>"+html_escape(txt)+"</pre>\nSend the full replacement list, one per line:\n<code>Label|Price|LowStock|SubscriptionDays</code>\n\nSend /cancel to stop.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgpi:"))
async def tg_product_inventory_prompt(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]; p=products_col.find_one({"id":pid},{"_id":0})
    if not p: return await q.answer("Product not found",show_alert=True)
    if str(p.get("fulfillment_mode") or "instant")!="instant": return await q.answer("Only instant-delivery products use digital inventory.",show_alert=True)
    await q.answer(); set_admin_flow(q.from_user.id,"tg_product_inventory",product_id=pid)
    variants=tg_product_variants_text(p)
    await q.message.answer("📦 <b>Add account inventory</b>\n\nSend inventory lines using the same format accepted by the panel. For multiple variants, prefix each line with the variant label/id as supported by your current parser.\n\nVariants:\n<pre>"+html_escape(variants or 'Default')+"</pre>\nSend /cancel to stop.",parse_mode="HTML")


async def tg_product_otp_menu(target,pid):
    p=products_col.find_one({"id":pid},{"_id":0})
    if not p: return await target.answer("Product not found")
    rows=[
        [InlineKeyboardButton(text=f"{'✅' if p.get('otp_enabled') else '❌'} OTP enabled",callback_data=f"tgpt:otp_enabled:{pid}")],
        [InlineKeyboardButton(text=f"💳 OTP price: {int(p.get('otp_price') or OTP_PRICE)}",callback_data=f"tgpf:op:{pid}")],
        [InlineKeyboardButton(text="⬅️ Product",callback_data=f"tgp:{pid}")],
    ]
    await target.answer(f"🔐 <b>OTP settings</b>\n\nAvailable only for instant-delivery products.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("tgp_otp:"))
async def tg_product_otp(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    await q.answer(); await tg_product_otp_menu(q.message,q.data.split(":",1)[1])


@dp.callback_query(F.data.startswith("tgpimg:"))
async def tg_product_image(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]
    if not products_col.find_one({"id":pid}): return await q.answer("Product not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_product_image",product_id=pid)
    await q.answer()
    await q.message.answer("🖼 <b>Product image</b>\n\nSend either:\n• a Telegram photo, or\n• an <code>https://...</code> image URL\n\nSend <code>clear</code> to remove the image or /cancel.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgpfeat:"))
async def tg_product_features_link(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]
    p=products_col.find_one({"id":pid},{"_id":0})
    if not p:return await q.answer("Product not found",show_alert=True)
    await q.answer()
    rows=[
        [InlineKeyboardButton(text="🔐 Purchase key controls",callback_data=f"akp:{pid}")],
        [InlineKeyboardButton(text="⏰ Subscription/reminder",callback_data=f"arp:{pid}")],
        [InlineKeyboardButton(text="📧 Fulfillment mode",callback_data=f"aep:{pid}")],
        [InlineKeyboardButton(text="⬅️ Product",callback_data=f"tgp:{pid}")],
    ]
    await q.message.answer("🧩 <b>Purchase & subscription controls</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("tgpdelask:"))
async def tg_product_delete_ask(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1];p=products_col.find_one({"id":pid},{"_id":0,"name":1})
    if not p:return await q.answer("Product not found",show_alert=True)
    await q.answer()
    await q.message.answer(f"⚠️ Delete/archive <b>{html_escape(str(p.get('name') or pid))}</b>?\n\nIf it has order history it will be archived instead of physically deleted.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Confirm",callback_data=f"tgpdel:{pid}")],
        [InlineKeyboardButton(text="❌ Cancel",callback_data=f"tgp:{pid}")],
    ]))


@dp.callback_query(F.data.startswith("tgpdel:"))
async def tg_product_delete(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "products")
    if not tg_admin_only(q): return
    pid=q.data.split(":",1)[1]
    if orders_col.count_documents({"items.id":pid})>0:
        products_col.update_one({"id":pid},{"$set":{"active":False,"archived":True,"updated_at":utcnow()}}); msg="Product archived because it has order history."
    else:
        products_col.delete_one({"id":pid}); digital_inventory_col.delete_many({"product_id":pid}); product_images_col.delete_one({"product_id":pid}); wishlists_col.delete_many({"product_id":pid}); msg="Product deleted."
    await q.answer("Done")
    await q.message.answer("✅ "+msg,reply_markup=admin_back_markup("tgadm_products:0"))


# Methods parity

def tg_methods_markup(page=0):
    methods=list(methods_col.find({}, {"_id":0}).sort("sort_order",1)); start=max(0,page)*TG_ADMIN_PAGE_SIZE; rows=[]
    for m in methods[start:start+TG_ADMIN_PAGE_SIZE]:
        rows.append([InlineKeyboardButton(text=f"{'✅' if m.get('active') else '⛔'} 📘 {str(m.get('title') or m['id'])[:35]}",callback_data=f"tgm:{m['id']}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"tgadm_methods:{page-1}"))
    if start+TG_ADMIN_PAGE_SIZE<len(methods): nav.append(InlineKeyboardButton(text="➡️",callback_data=f"tgadm_methods:{page+1}"))
    if nav: rows.append(nav)
    rows += [[InlineKeyboardButton(text="➕ Create method",callback_data="tgm_new")],[InlineKeyboardButton(text="🏠 Dashboard",callback_data="admin_menu")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data.startswith("tgadm_methods:"))
async def tg_methods(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q): return await q.answer("Admin only",show_alert=True)
    await q.answer(); page=int(q.data.rsplit(":",1)[1]); count=methods_col.count_documents({})
    await q.message.answer(f"📚 <b>Methods</b>\n\nTotal: <b>{count}</b>\nCreate, edit, price, publish, image and delete Methods directly here.",parse_mode="HTML",reply_markup=tg_methods_markup(page))


@dp.callback_query(F.data.startswith("tgm:"))
async def tg_method_detail(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q): return
    mid=q.data.split(":",1)[1]; m=methods_col.find_one({"id":mid},{"_id":0})
    if not m:return await q.answer("Method not found",show_alert=True)
    await q.answer(); buyers=method_purchases_col.count_documents({"method_id":mid}); gallery_count=len(method_gallery_urls(m))
    text=(f"📘 <b>{html_escape(str(m.get('title') or mid))}</b>\nID: <code>{html_escape(mid)}</code>\n"
          f"Price: <b>{'FREE' if m.get('is_free') or not m.get('price') else money(m.get('price'))}</b> • Buyers: <b>{buyers}</b>\n"
          f"Sort: {int(m.get('sort_order') or 0)} • Active: {'✅' if m.get('active') else '❌'}\n"
          f"Images: <b>{gallery_count + (1 if m.get('image') else 0)}</b> ({gallery_count} gallery)\n\n"
          f"Preview: {html_escape(tg_trim(m.get('summary'),350) or '—')}")
    rows=[
        [InlineKeyboardButton(text="✏️ Title",callback_data=f"tgmf:t:{mid}"),InlineKeyboardButton(text="📝 Preview",callback_data=f"tgmf:s:{mid}")],
        [InlineKeyboardButton(text="📖 Full content",callback_data=f"tgmf:b:{mid}")],
        [InlineKeyboardButton(text="💳 Price",callback_data=f"tgmf:p:{mid}"),InlineKeyboardButton(text="↕️ Sort order",callback_data=f"tgmf:o:{mid}")],
        [InlineKeyboardButton(text=f"{'✅' if m.get('is_free') else '❌'} FREE",callback_data=f"tgmt:free:{mid}"),InlineKeyboardButton(text=f"{'✅' if m.get('active') else '❌'} Active",callback_data=f"tgmt:active:{mid}")],
        [InlineKeyboardButton(text="🖼 Cover",callback_data=f"tgmimg:{mid}"),InlineKeyboardButton(text=f"🖼 Gallery ({gallery_count})",callback_data=f"tgmgal:{mid}")],
        [InlineKeyboardButton(text="🗑 Delete",callback_data=f"tgmdelask:{mid}")],
        [InlineKeyboardButton(text="⬅️ Methods",callback_data="tgadm_methods:0")],
    ]
    await q.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


TG_METHOD_FIELDS={"t":("title","Method title"),"s":("summary","Short description / preview"),"b":("body","Full method content"),"p":("price","Price"),"o":("sort_order","Sort order")}

@dp.callback_query(F.data.startswith("tgmf:"))
async def tg_method_field(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    try:_,code,mid=q.data.split(":",2)
    except ValueError:return
    m=methods_col.find_one({"id":mid},{"_id":0}); spec=TG_METHOD_FIELDS.get(code)
    if not m or not spec:return await q.answer("Invalid method/field",show_alert=True)
    field,label=spec; set_admin_flow(q.from_user.id,"tg_method_field",method_id=mid,field_code=code); await q.answer()
    await q.message.answer(f"✏️ <b>{html_escape(label)}</b>\n\nCurrent:\n<code>{html_escape(tg_trim(m.get(field),700) or '—')}</code>\n\nSend the new value. Text fields accept <code>clear</code>.",parse_mode="HTML")

@dp.callback_query(F.data=="tgm_new")
async def tg_method_new(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    set_admin_flow(q.from_user.id,"tg_method_new_title");await q.answer();await q.message.answer("➕ <b>Create Method</b>\n\nSend the title. It will be created with safe defaults, then you can edit every field.",parse_mode="HTML")

@dp.callback_query(F.data.startswith("tgmt:"))
async def tg_method_toggle(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    try:_,key,mid=q.data.split(":",2)
    except ValueError:return
    field="is_free" if key=="free" else "active" if key=="active" else ""
    m=methods_col.find_one({"id":mid})
    if not field or not m:return await q.answer("Invalid",show_alert=True)
    new=not bool(m.get(field));methods_col.update_one({"id":mid},{"$set":{field:new,"updated_at":utcnow()}});invalidate_method_catalog_cache();await q.answer("Updated");
    fake=type('Q',(),{})
    # redraw by sending fresh detail
    m2=methods_col.find_one({"id":mid},{"_id":0});buyers=method_purchases_col.count_documents({"method_id":mid})
    await q.message.answer(f"✅ Updated <b>{html_escape(str(m2.get('title') or mid))}</b> • {'FREE' if m2.get('is_free') else money(m2.get('price',0))} • {'Active' if m2.get('active') else 'Hidden'}",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Open method",callback_data=f"tgm:{mid}")]]))

@dp.callback_query(F.data.startswith("tgmimg:"))
async def tg_method_image(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    mid=q.data.split(":",1)[1]
    if not methods_col.find_one({"id":mid}):return await q.answer("Method not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_method_image",method_id=mid);await q.answer();await q.message.answer("🖼 <b>Method cover</b>\n\nSend a Telegram photo or an http/https image URL. Send <code>clear</code> to remove the cover.",parse_mode="HTML")

@dp.callback_query(F.data.startswith("tgmgal:"))
async def tg_method_gallery(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):
        return
    mid = q.data.split(":", 1)[1]
    method = methods_col.find_one({"id": mid}, {"_id": 0})
    if not method:
        return await q.answer("Method not found", show_alert=True)
    count = len(method_gallery_urls(method))
    set_admin_flow(q.from_user.id, "tg_method_gallery", method_id=mid)
    await q.answer()
    await q.message.answer(
        f"🖼 <b>Method gallery</b> • {count}/{MAX_METHOD_GALLERY_IMAGES}\n\n"
        "Send Telegram photos or http/https image URLs one at a time.\n"
        "Send <code>done</code> when finished, or <code>clear</code> to remove the whole gallery.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("tgmdelask:"))
async def tg_method_delete_ask(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    mid=q.data.split(":",1)[1];m=methods_col.find_one({"id":mid},{"_id":0,"title":1})
    if not m:return await q.answer("Method not found",show_alert=True)
    await q.answer();await q.message.answer(f"⚠️ Delete method <b>{html_escape(str(m.get('title') or mid))}</b>?",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Confirm",callback_data=f"tgmdel:{mid}")],[InlineKeyboardButton(text="❌ Cancel",callback_data=f"tgm:{mid}")]]))

@dp.callback_query(F.data.startswith("tgmdel:"))
async def tg_method_delete(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "methods")
    if not tg_admin_only(q):return
    mid=q.data.split(":",1)[1];methods_col.delete_one({"id":mid});method_images_col.delete_one({"method_id":mid});method_gallery_col.delete_many({"method_id":mid});invalidate_method_catalog_cache();await q.answer("Deleted");await q.message.answer("✅ Method deleted.",reply_markup=admin_back_markup("tgadm_methods:0"))


# Inventory parity
@dp.callback_query(F.data.startswith("tgadm_inventory:"))
async def tg_inventory_products(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "inventory")
    if not tg_admin_only(q):return await q.answer("Admin only",show_alert=True)
    await q.answer();page=int(q.data.rsplit(":",1)[1]);ps=get_products(False);start=page*TG_ADMIN_PAGE_SIZE;rows=[]
    for p in ps[start:start+TG_ADMIN_PAGE_SIZE]:
        a=digital_inventory_col.count_documents({"product_id":p['id'],"sold":False});s=digital_inventory_col.count_documents({"product_id":p['id'],"sold":True})
        rows.append([InlineKeyboardButton(text=f"📦 {str(p.get('name') or p['id'])[:27]} • {a} avail/{s} sold",callback_data=f"tginvp:{p['id']}:0")])
    nav=[]
    if page>0:nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"tgadm_inventory:{page-1}"))
    if start+TG_ADMIN_PAGE_SIZE<len(ps):nav.append(InlineKeyboardButton(text="➡️",callback_data=f"tgadm_inventory:{page+1}"))
    if nav:rows.append(nav)
    rows.append([InlineKeyboardButton(text="🏠 Dashboard",callback_data="admin_menu")])
    await q.message.answer("📦 <b>Inventory dashboard</b>\n\nSelect a product to inspect available/sold encrypted inventory and remove unused entries.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("tginvp:"))
async def tg_inventory_items(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "inventory")
    if not tg_admin_only(q):return
    try:_,pid,page_s=q.data.split(":",2);page=int(page_s)
    except:return
    p=products_col.find_one({"id":pid},{"_id":0,"name":1})
    if not p:return await q.answer("Product not found",show_alert=True)
    await q.answer();docs=list(digital_inventory_col.find({"product_id":pid}).sort("_id",-1).skip(page*TG_ADMIN_PAGE_SIZE).limit(TG_ADMIN_PAGE_SIZE));rows=[]
    for d in docs:
        state="🔴 SOLD" if d.get("sold") else "🟢 AVAILABLE";label=mask_secret(decrypt_payload(d))[:28]
        rows.append([InlineKeyboardButton(text=f"{state} • {label}",callback_data=f"tginvi:{str(d['_id'])}")])
    nav=[]
    if page>0:nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"tginvp:{pid}:{page-1}"))
    if len(docs)==TG_ADMIN_PAGE_SIZE:nav.append(InlineKeyboardButton(text="➡️",callback_data=f"tginvp:{pid}:{page+1}"))
    if nav:rows.append(nav)
    rows += [[InlineKeyboardButton(text="➕ Add inventory",callback_data=f"tgpi:{pid}")],[InlineKeyboardButton(text="⬅️ Inventory",callback_data="tgadm_inventory:0")]]
    await q.message.answer(f"📦 <b>{html_escape(str(p.get('name') or pid))}</b>\nAvailable: <b>{digital_inventory_col.count_documents({'product_id':pid,'sold':False})}</b> • Sold: <b>{digital_inventory_col.count_documents({'product_id':pid,'sold':True})}</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("tginvi:"))
async def tg_inventory_item(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "inventory")
    if not tg_admin_only(q):return
    oid=q.data.split(":",1)[1]
    try:d=digital_inventory_col.find_one({"_id":ObjectId(oid)})
    except:return await q.answer("Invalid item",show_alert=True)
    if not d:return await q.answer("Inventory item not found",show_alert=True)
    await q.answer();plain=decrypt_payload(d);account=parse_account_inventory_payload(plain) or {};lines=[]
    for k,label in [("email","Email"),("username","ID"),("password","Password"),("profile","Profile"),("pin","PIN"),("totp_secret","TOTP Secret")]:
        if account.get(k):lines.append(f"{label}: <code>{html_escape(str(account[k]))}</code>")
    if not lines:lines=["<pre>"+html_escape(tg_trim(plain,1800))+"</pre>"]
    text=f"📦 <b>Inventory item</b>\nProduct: <code>{html_escape(str(d.get('product_id')))}</code> • Variant: <code>{html_escape(str(d.get('variant_id','default')))}</code>\nStatus: <b>{'SOLD' if d.get('sold') else 'AVAILABLE'}</b>"
    if d.get('sold_to'):text+=f"\nSold to: <code>{d.get('sold_to')}</code> • Order: <code>#{html_escape(str(d.get('order_code') or ''))}</code>"
    text+="\n\n"+"\n".join(lines)
    kb=[]
    if not d.get('sold'):kb.append([InlineKeyboardButton(text="🗑 Remove unused item",callback_data=f"tginvdel:{oid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Product inventory",callback_data=f"tginvp:{d.get('product_id')}:0")])
    await q.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("tginvdel:"))
async def tg_inventory_delete(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "inventory")
    if not tg_admin_only(q):return
    oid=q.data.split(":",1)[1]
    try:doc=digital_inventory_col.find_one({"_id":ObjectId(oid)})
    except:return await q.answer("Invalid item",show_alert=True)
    if not doc:return await q.answer("Not found",show_alert=True)
    if doc.get('sold'):return await q.answer("Sold delivery records cannot be deleted.",show_alert=True)
    digital_inventory_col.delete_one({"_id":doc['_id']});await q.answer("Removed");await q.message.answer("✅ Unused inventory removed.",reply_markup=admin_back_markup(f"tginvp:{doc.get('product_id')}:0"))


# Customers parity
@dp.callback_query(F.data.startswith("tgadm_customers:"))
async def tg_customers(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q):return await q.answer("Admin only",show_alert=True)
    await q.answer();page=int(q.data.rsplit(":",1)[1]);rows=list(users_col.find({}, {"_id":0}).sort("last_seen",-1).skip(page*TG_ADMIN_PAGE_SIZE).limit(TG_ADMIN_PAGE_SIZE));kb=[]
    for u in rows:kb.append([InlineKeyboardButton(text=f"👤 {str(u.get('full_name') or u.get('username') or u['user_id'])[:27]} • {int(u.get('credits',0))} cr",callback_data=f"tgc:{u['user_id']}")])
    nav=[]
    if page>0:nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"tgadm_customers:{page-1}"))
    if len(rows)==TG_ADMIN_PAGE_SIZE:nav.append(InlineKeyboardButton(text="➡️",callback_data=f"tgadm_customers:{page+1}"))
    if nav:kb.append(nav)
    kb += [[InlineKeyboardButton(text="🔎 Search customer",callback_data="tgc_search")],[InlineKeyboardButton(text="🏠 Dashboard",callback_data="admin_menu")]]
    await q.message.answer("👥 <b>Customers</b>\n\nRecent customers. Open a profile for balance and complete purchase history.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data=="tgc_search")
async def tg_customer_search_prompt(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q):return
    set_admin_flow(q.from_user.id,"tg_customer_search");await q.answer();await q.message.answer("🔎 Send Telegram ID, username, or customer name.")

@dp.callback_query(F.data.startswith("tgc:"))
async def tg_customer_detail(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q):return
    try:uid=int(q.data.split(":",1)[1])
    except:return
    u=users_col.find_one({"user_id":uid},{"_id":0})
    if not u:return await q.answer("Customer not found",show_alert=True)
    await q.answer();orders=list(orders_col.find({"user_id":uid},{"_id":0,"digital_delivery":0}).sort("created_at",-1).limit(10));spent=sum(int(x.get('total_credits',0)) for x in orders_col.find({"user_id":uid},{"total_credits":1}))
    restrictions = customer_restrictions(uid)
    note = str(u.get("admin_note") or "")
    text=(f"👤 <b>{html_escape(str(u.get('full_name') or 'Customer'))}</b>\n@{html_escape(str(u.get('username') or '-'))} • <code>{uid}</code>\n"
          f"Balance: <b>{money(u.get('credits',0))}</b>\nOrders: <b>{orders_col.count_documents({'user_id':uid})}</b> • Total spent: <b>{money(spent)}</b>\n"
          f"Restrictions: {'⛔ suspended' if restrictions['suspended'] else '✅ active'} • {'🚫 products' if restrictions['purchase_blocked'] else 'products allowed'} • {'🚫 Methods' if restrictions['methods_blocked'] else 'Methods allowed'}"
          + (f"\n\n📝 <b>Private note</b>\n{html_escape(note[:600])}" if note else ""))
    kb=[[InlineKeyboardButton(text="➕ Add/subtract credits",callback_data=f"tgcc:add:{uid}"),InlineKeyboardButton(text="🎯 Set balance",callback_data=f"tgcc:set:{uid}")]]
    kb.append([InlineKeyboardButton(text="📝 Edit private note",callback_data=f"tgcn:{uid}")])
    kb.append([
        InlineKeyboardButton(text=("✅ Products" if restrictions['purchase_blocked'] else "🚫 Block products"), callback_data=f"tgr:{uid}:purchase_blocked"),
        InlineKeyboardButton(text=("✅ Methods" if restrictions['methods_blocked'] else "🚫 Block Methods"), callback_data=f"tgr:{uid}:methods_blocked"),
    ])
    kb.append([InlineKeyboardButton(text=("✅ Unsuspend" if restrictions['suspended'] else "⛔ Suspend purchases"), callback_data=f"tgr:{uid}:suspended")])
    kb.append([InlineKeyboardButton(text="📜 Full purchase history",callback_data=f"tgch:{uid}:0")])
    for o in orders[:4]:kb.append([InlineKeyboardButton(text=f"🧾 #{o.get('order_code')} • {int(o.get('total_credits',0))} cr",callback_data=f"tgo:{o.get('order_code')}")])
    kb.append([InlineKeyboardButton(text="⬅️ Customers",callback_data="tgadm_customers:0")])
    await q.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("tgcc:"))
async def tg_customer_credit_prompt(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q):return
    try:_,mode,uid=q.data.split(":",2);uid=int(uid)
    except:return
    if mode not in {'add','set'}:return
    set_admin_flow(q.from_user.id,"tg_customer_credit",user_id=uid,mode=mode);await q.answer();await q.message.answer(("➕ Send credits to add/subtract (negative allowed)." if mode=='add' else "🎯 Send the exact new balance." )+"\nSend /cancel to stop.")


# Order browsing/detail parity
@dp.callback_query(F.data.startswith("tgadm_orders:"))
async def tg_orders_page(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "orders")
    if not tg_admin_only(q): return await q.answer("Admin only", show_alert=True)
    await q.answer()
    page = max(0, int(q.data.rsplit(":", 1)[1]))
    rows = list(orders_col.find({}, {"_id": 0, "digital_delivery": 0}).sort("created_at", -1).skip(page * TG_ADMIN_PAGE_SIZE).limit(TG_ADMIN_PAGE_SIZE))
    kb = []
    lines = []
    for o in rows:
        code = str(o.get("order_code") or "")
        lines.append(f"• <b>#{html_escape(code)}</b> • <code>{o.get('user_id')}</code> • {money(o.get('total_credits', 0))} • {html_escape(str(o.get('status') or 'delivered'))}")
        kb.append([InlineKeyboardButton(text=f"🧾 #{code}", callback_data=f"tgo:{code}"), InlineKeyboardButton(text="♻️ Resend", callback_data=f"admin_resend:{code}")])
    nav=[]
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"tgadm_orders:{page-1}"))
    if len(rows) == TG_ADMIN_PAGE_SIZE: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"tgadm_orders:{page+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton(text="🏠 Dashboard", callback_data="admin_menu")])
    await q.message.answer("🧾 <b>Orders & receipts</b>\n\n" + ("\n".join(lines) or "No orders."), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("tgch:"))
async def tg_customer_history(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q): return
    try: _, uid_s, page_s = q.data.split(":", 2); uid=int(uid_s); page=max(0,int(page_s))
    except Exception: return
    u=users_col.find_one({"user_id":uid},{"_id":0})
    if not u: return await q.answer("Customer not found",show_alert=True)
    await q.answer()
    orders=list(orders_col.find({"user_id":uid},{"_id":0,"digital_delivery":0}).sort("created_at",-1).skip(page*TG_ADMIN_PAGE_SIZE).limit(TG_ADMIN_PAGE_SIZE))
    kb=[]; lines=[]
    for o in orders:
        code=str(o.get('order_code') or ''); lines.append(f"• #{html_escape(code)} • {money(o.get('total_credits',0))}"); kb.append([InlineKeyboardButton(text=f"🧾 #{code}",callback_data=f"tgo:{code}")])
    nav=[]
    if page>0:nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"tgch:{uid}:{page-1}"))
    if len(orders)==TG_ADMIN_PAGE_SIZE:nav.append(InlineKeyboardButton(text="➡️",callback_data=f"tgch:{uid}:{page+1}"))
    if nav:kb.append(nav)
    kb.append([InlineKeyboardButton(text="⬅️ Customer",callback_data=f"tgc:{uid}")])
    await q.message.answer(f"📜 <b>Purchase history — {html_escape(str(u.get('full_name') or uid))}</b>\n\n"+("\n".join(lines) or "No orders."),parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# Order detail parity
@dp.callback_query(F.data.startswith("tgo:"))
async def tg_order_detail(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "orders")
    if not tg_admin_only(q):return
    code=q.data.split(":",1)[1];o=orders_col.find_one({"order_code":code},{"_id":0,"digital_delivery":0})
    if not o:return await q.answer("Order not found",show_alert=True)
    await q.answer();items=[]
    for it in o.get('items') or []:
        extra=f" • 📧 {html_escape(str(it.get('requested_email')))}" if it.get('requested_email') else ''
        items.append(f"• {html_escape(str(it.get('name') or it.get('id')))} {html_escape(str(it.get('variant_label') or ''))} ×{int(it.get('qty',1))}{extra}")
    pending_parts=[]
    for field in ("manual_fulfillment","email_fulfillment"):
        for entry in o.get(field) or []:
            if str(entry.get("status") or "pending") != "fulfilled":
                level=fulfillment_sla_level(o,entry); marker="🔴" if level>=2 else ("🟠" if level==1 else "🟢")
                pending_parts.append(f"{marker} {html_escape(str(entry.get('name') or 'Pending'))}: {html_escape(format_wait_duration(fulfillment_wait_seconds(o,entry)))}")
    order_note=str(o.get("admin_note") or "")
    text=(f"🧾 <b>Order #{html_escape(code)}</b>\nCustomer: <code>{o.get('user_id')}</code>\nTotal: <b>{money(o.get('total_credits',0))}</b>\nStatus: <b>{html_escape(str(o.get('status') or 'delivered'))}</b>\n\n"+("\n".join(items) or 'No items')
          + ("\n\n⏱ <b>Waiting</b>\n"+"\n".join(pending_parts) if pending_parts else "")
          + (f"\n\n📝 <b>Private note</b>\n{html_escape(order_note[:800])}" if order_note else ""))
    kb=[[InlineKeyboardButton(text="♻️ Resend delivery",callback_data=f"admin_resend:{code}")],[InlineKeyboardButton(text="👤 Customer",callback_data=f"tgc:{o.get('user_id')}")],[InlineKeyboardButton(text="📝 Order note",callback_data=f"tgon:{code}")]]
    for i,e in enumerate(o.get('email_fulfillment') or []):
        if str(e.get('status'))!='fulfilled':kb.append([InlineKeyboardButton(text=f"📧 Fulfill {str(e.get('name') or 'subscription')[:28]}",callback_data=f"aev:{code}:{i}")])
    for i,e in enumerate(o.get('manual_fulfillment') or []):
        if str(e.get('status'))!='fulfilled':kb.append([InlineKeyboardButton(text=f"🛠 Deliver {str(e.get('name') or 'requested product')[:27]}",callback_data=f"amv:{code}:{i}")])
    kb.append([InlineKeyboardButton(text="⬅️ Orders",callback_data="admin_orders")])
    await q.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data == "tgsla_run")
async def tg_sla_run(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "action")
    if not tg_admin_only(q): return
    await q.answer("Checking waiting orders…")
    result = await process_fulfillment_escalations(100)
    await q.message.answer(
        f"⏱ SLA check complete. Alerts sent: <b>{result['sent']}</b> • Failed: <b>{result['failed']}</b>.",
        parse_mode="HTML", reply_markup=admin_back_markup("tgadm_action"),
    )


@dp.callback_query(F.data.startswith("tgcn:"))
async def tg_customer_note_prompt(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q): return
    try: uid=int(q.data.split(":",1)[1])
    except Exception: return await q.answer("Invalid customer",show_alert=True)
    if not users_col.find_one({"user_id":uid}): return await q.answer("Customer not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_customer_note",user_id=uid); await q.answer()
    await q.message.answer("📝 Send the private customer note (max 2000 characters), or <code>clear</code> to remove it.\nThis note is visible only to admin.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgon:"))
async def tg_order_note_prompt(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "orders")
    if not tg_admin_only(q): return
    code=q.data.split(":",1)[1]
    if not orders_col.find_one({"order_code":code}): return await q.answer("Order not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_order_note",order_code=code); await q.answer()
    await q.message.answer("📝 Send the private order note (max 2000 characters), or <code>clear</code> to remove it.\nThis note is visible only to admin.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgr:"))
async def tg_customer_restriction_toggle(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if not tg_admin_only(q): return
    try:
        _,uid_s,field=q.data.split(":",2);uid=int(uid_s)
    except Exception: return await q.answer("Invalid restriction",show_alert=True)
    if field not in {"purchase_blocked","methods_blocked","suspended"}: return await q.answer("Invalid restriction",show_alert=True)
    u=users_col.find_one({"user_id":uid})
    if not u:return await q.answer("Customer not found",show_alert=True)
    new_value=not bool(u.get(field,False))
    users_col.update_one({"user_id":uid},{"$set":{field:new_value,"restriction_updated_at":utcnow()}})
    # Render refreshed customer profile through the same callback handler logic.
    q.data=f"tgc:{uid}"
    await tg_customer_detail(q)


@dp.callback_query(F.data == "tgtpl")
async def tg_templates_menu(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    await q.answer()
    docs=[template_public(x) for x in fulfillment_templates_col.find({}, {"_id":0}).sort("name",1).limit(MAX_FULFILLMENT_TEMPLATES)]
    rows=[[InlineKeyboardButton(text=f"🧾 {d['name'][:34]}",callback_data=f"tgtplv:{d['id']}")] for d in docs]
    rows.append([InlineKeyboardButton(text="➕ New template",callback_data="tgtpl_new")])
    rows.append([InlineKeyboardButton(text="⬅️ More tools",callback_data="tgadm_more")])
    await q.message.answer(
        f"🧾 <b>Delivery templates</b>\n\nSaved: <b>{len(docs)}</b> / {MAX_FULFILLMENT_TEMPLATES}.\nTemplates are tiny bounded documents and can be global or linked to one product.",
        parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("tgtplv:"))
async def tg_template_view(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    tid=q.data.split(":",1)[1];d=fulfillment_templates_col.find_one({"id":tid},{"_id":0})
    if not d:return await q.answer("Template not found",show_alert=True)
    await q.answer();p=products_col.find_one({"id":str(d.get('product_id') or '')},{"name":1}) if d.get('product_id') else None
    body=str(d.get('body') or '')
    rows=[
        [InlineKeyboardButton(text="✏️ Replace body",callback_data=f"tgtple:{tid}"),InlineKeyboardButton(text=("⏸ Disable" if d.get('active',True) else "▶️ Enable"),callback_data=f"tgtplt:{tid}")],
        [InlineKeyboardButton(text="🗑 Delete",callback_data=f"tgtpld:{tid}")],
        [InlineKeyboardButton(text="⬅️ Templates",callback_data="tgtpl")],
    ]
    await q.message.answer(f"🧾 <b>{html_escape(str(d.get('name') or 'Template'))}</b>\nProduct: <b>{html_escape(str((p or {}).get('name') or 'Global'))}</b>\nStatus: <b>{'Active' if d.get('active',True) else 'Disabled'}</b>\n\n<pre>{html_escape(body[:2600])}</pre>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "tgtpl_new")
async def tg_template_new(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    if fulfillment_templates_col.count_documents({})>=MAX_FULFILLMENT_TEMPLATES:return await q.answer("Template limit reached",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_template_name");await q.answer();await q.message.answer("🧾 New template — Step 1/3: send a short template name (max 60 characters).")


@dp.callback_query(F.data.startswith("tgtplp:"))
async def tg_template_product(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    flow=get_admin_flow(q.from_user.id);data=dict((flow or {}).get('data') or {})
    if str((flow or {}).get('action'))!="tg_template_choose_product":return await q.answer("Template flow expired",show_alert=True)
    token=q.data.split(":",1)[1]
    choices=list(data.get("product_choices") or [])
    if token=="g":
        pid=""
    else:
        try: pid=str(choices[int(token)])
        except Exception: return await q.answer("Product choice expired",show_alert=True)
        if not products_col.find_one({"id":pid}):return await q.answer("Product not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_template_body",name=str(data.get('name') or 'Template'),product_id=pid);await q.answer()
    await q.message.answer("Step 3/3: send the template body (max 3000 characters).\n\nAvailable placeholders: <code>{{order_code}}</code>, <code>{{customer_id}}</code>, <code>{{product}}</code>, <code>{{variant}}</code>, <code>{{email}}</code>, <code>{{qty}}</code>.",parse_mode="HTML")


@dp.callback_query(F.data.startswith("tgtple:"))
async def tg_template_edit_body(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    tid=q.data.split(":",1)[1]
    if not fulfillment_templates_col.find_one({"id":tid}):return await q.answer("Template not found",show_alert=True)
    set_admin_flow(q.from_user.id,"tg_template_edit_body",template_id=tid);await q.answer();await q.message.answer("✏️ Send the replacement template body (max 3000 characters).")


@dp.callback_query(F.data.startswith("tgtplt:"))
async def tg_template_toggle(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    tid=q.data.split(":",1)[1];d=fulfillment_templates_col.find_one({"id":tid})
    if not d:return await q.answer("Template not found",show_alert=True)
    fulfillment_templates_col.update_one({"id":tid},{"$set":{"active":not bool(d.get('active',True)),"updated_at":utcnow()}})
    q.data=f"tgtplv:{tid}";await tg_template_view(q)


@dp.callback_query(F.data.startswith("tgtpld:"))
async def tg_template_delete(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "templates")
    if not tg_admin_only(q): return
    tid=q.data.split(":",1)[1];fulfillment_templates_col.delete_one({"id":tid});q.data="tgtpl";await tg_templates_menu(q)


@dp.callback_query(F.data == "tgbackup")
async def tg_backup_menu(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "backups")
    if not tg_admin_only(q): return
    await q.answer();schedule=backup_schedule_config();state=settings_col.find_one({"_id":"auto_backup_state"}) or {};last=state.get('last_sent_at');last_text=format_admin_datetime(last) if isinstance(last,datetime) else "Never"
    rows=[
        [InlineKeyboardButton(text="💾 Export now to Telegram",callback_data="tgbackup_now")],
        [InlineKeyboardButton(text=("✅ Off" if schedule=='off' else "Off"),callback_data="tgbackup_set:off"),InlineKeyboardButton(text=("✅ Daily" if schedule=='daily' else "Daily"),callback_data="tgbackup_set:daily"),InlineKeyboardButton(text=("✅ Weekly" if schedule=='weekly' else "Weekly"),callback_data="tgbackup_set:weekly")],
        [InlineKeyboardButton(text="⬅️ More tools",callback_data="tgadm_more")],
    ]
    await q.message.answer(f"💾 <b>Backups</b>\n\nAutomatic schedule: <b>{html_escape(schedule.title())}</b>\nLast sent: <b>{html_escape(last_text)}</b>\n\nBackups are generated on demand, sent to this admin chat, and are <b>not stored back in MongoDB</b>. Inventory remains encrypted.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "tgbackup_now")
async def tg_backup_now(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "backups")
    if not tg_admin_only(q): return
    await q.answer("Building backup…")
    try:
        result=await send_backup_to_admin("manual Telegram export")
        await q.message.answer(f"✅ Backup sent • {result['bytes']/(1024*1024):.2f} MB",reply_markup=admin_back_markup("tgbackup"))
    except Exception as exc:
        await q.message.answer(f"❌ Backup failed: {html_escape(str(exc))}",parse_mode="HTML",reply_markup=admin_back_markup("tgbackup"))


@dp.callback_query(F.data.startswith("tgbackup_set:"))
async def tg_backup_set(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "backups")
    if not tg_admin_only(q): return
    schedule=q.data.split(":",1)[1]
    try:configure_backup_schedule(schedule)
    except ValueError as exc:return await q.answer(str(exc),show_alert=True)
    q.data="tgbackup";await tg_backup_menu(q)


# Dashboard/security parity
@dp.callback_query(F.data=="tgadm_dashboard")
async def tg_dashboard(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "dashboard")
    if not tg_admin_only(q):return await q.answer("Admin only",show_alert=True)
    await q.answer();a=analytics_data();ps=get_products(False);available=digital_inventory_col.count_documents({"sold":False});sold=digital_inventory_col.count_documents({"sold":True});low=sum(1 for p in ps if 0<int(p.get('stock',0))<=DEFAULT_LOW_STOCK);out=sum(1 for p in ps if int(p.get('stock',0))==0)
    text=(f"🏠 <b>Admin Dashboard</b>\n\nCustomers: <b>{users_col.count_documents({})}</b> • Orders: <b>{orders_col.count_documents({})}</b>\n"
          f"Revenue: <b>{money(sum(int(x.get('total_credits',0)) for x in orders_col.find({}, {'total_credits':1})))}</b>\n"
          f"Inventory: <b>{available}</b> available • <b>{sold}</b> sold • 🟠 {low} low • 🔴 {out} out\n\n"
          f"Today: {a['today']['orders']} orders / {money(a['today']['revenue'])}\n7 days: {a['week']['orders']} / {money(a['week']['revenue'])}\n30 days: {a['month']['orders']} / {money(a['month']['revenue'])}")
    await q.message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data=="tgadm_security")
async def tg_security(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "security")
    if not tg_admin_only(q):return await q.answer("Admin only",show_alert=True)
    await q.answer()
    try:info=await bot.get_webhook_info();wh=f"✅ {html_escape(info.url)}" if info.url else "❌ Not set"
    except Exception as exc:wh=f"⚠️ {html_escape(str(exc)[:120])}"
    try:creds=cloudinary_credentials();cloud=bool(creds)
    except Exception:cloud=False
    text=(f"🔐 <b>Security & integrations</b>\n\nInventory encryption: <b>{'✅ Dedicated key' if ENCRYPTION_KEY_SOURCE=='environment' else '🟠 Derived key'}</b>\n"
          f"Admin 2FA: <b>{'✅ Enabled' if ADMIN_TOTP_SECRET else '⚪ Optional'}</b>\nCloudinary: <b>{'✅ Enabled' if cloud else '⚪ Mongo fallback'}</b>\nCron secret: <b>{'✅ Configured' if CRON_SECRET else '⚠️ Missing'}</b>\nWebhook: {wh}\n\n"
          "Group gate can be bound with <code>/bindgroup</code> inside the required group. Sensitive environment secrets remain environment-only and are never displayed or editable in Telegram/panel.")
    await q.message.answer(text, parse_mode="HTML")

@dp.callback_query(F.data=="tgadm_webhook")
async def tg_setup_webhook(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "security")
    if not tg_admin_only(q):return
    try:
        result=await bot.set_webhook(url=f"{PUBLIC_URL}/telegram/webhook",secret_token=WEBHOOK_SECRET_SAFE,allowed_updates=dp.resolve_used_update_types(),drop_pending_updates=False);info=await bot.get_webhook_info();msg=f"Webhook {'connected' if result else 'request returned false'}: {info.url}"
        await q.answer("Webhook updated")
    except Exception as exc:msg=f"Webhook error: {exc}";await q.answer("Webhook error",show_alert=True)
    await q.message.answer(html_escape(msg))


# Broadcast guided flow, with serverless-safe batches.
async def tg_broadcast_batch(data, cursor=0, broadcast_id=""):
    message=str(data.get('message') or '').strip();image_url=str(data.get('image_url') or '').strip();button_text=str(data.get('button_text') or '').strip();button_url=str(data.get('button_url') or '').strip()
    if not broadcast_id:broadcast_id=secrets.token_hex(8)
    if cursor==0:
        broadcasts_col.update_one({"broadcast_id":broadcast_id},{"$setOnInsert":{"broadcast_id":broadcast_id,"preview":message[:180],"image_url":image_url,"button_text":button_text,"button_url":button_url,"created_at":utcnow(),"sent":0,"failed":0,"status":"sending"}},upsert=True)
    recipients=list(users_col.find({"user_id":{"$gt":int(cursor)},"broadcast_opt_out":{"$ne":True},"broadcast_blocked":{"$ne":True}},{"user_id":1,"_id":0}).sort("user_id",1).limit(30))
    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text[:64],url=button_url)]]) if button_text and button_url else None
    sent=failed=0;last=int(cursor)
    for row in recipients:
        uid=int(row['user_id']);last=uid
        try:
            if image_url:await bot.send_photo(uid,photo=image_url)
            await bot.send_message(uid,message,reply_markup=markup,disable_web_page_preview=False);sent+=1
        except Exception as exc:
            failed+=1;err=str(exc).lower()
            if any(x in err for x in ('bot was blocked','chat not found','user is deactivated','forbidden')):users_col.update_one({"user_id":uid},{"$set":{"broadcast_blocked":True,"broadcast_blocked_at":utcnow()}})
        await asyncio.sleep(.04)
    done=len(recipients)<30
    broadcasts_col.update_one({"broadcast_id":broadcast_id},{"$inc":{"sent":sent,"failed":failed},"$set":{"updated_at":utcnow(),"status":"completed" if done else "sending",**({"completed_at":utcnow()} if done else {})}},upsert=True)
    return {"broadcast_id":broadcast_id,"next_cursor":last,"sent":sent,"failed":failed,"done":done}

@dp.callback_query(F.data=="tgbc_new")
async def tg_broadcast_new(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "broadcast")
    if not tg_admin_only(q):return
    set_admin_flow(q.from_user.id,"tg_broadcast_message");await q.answer();await q.message.answer("📣 <b>New broadcast</b>\n\nStep 1/4: send the message (max 3900 characters).",parse_mode="HTML")

@dp.callback_query(F.data.startswith("tgbc_send:"))
async def tg_broadcast_send_cb(q:CallbackQuery):
    await sync_admin_reply_keyboard(q, "broadcast")
    if not tg_admin_only(q):return
    token=q.data.split(":",1)[1];draft=get_setting(f"tg_broadcast:{token}",None)
    if not isinstance(draft,dict):return await q.answer("Broadcast draft expired",show_alert=True)
    await q.answer("Sending batch…")
    result=await tg_broadcast_batch(draft,int(draft.get('cursor') or 0),str(draft.get('broadcast_id') or ''))
    draft.update(cursor=result['next_cursor'],broadcast_id=result['broadcast_id'],sent=int(draft.get('sent',0))+result['sent'],failed=int(draft.get('failed',0))+result['failed']);set_setting(f"tg_broadcast:{token}",draft)
    if result['done']:
        settings_col.delete_one({"_id":f"tg_broadcast:{token}"});kb=admin_back_markup("admin_broadcast")
        msg=f"✅ Broadcast complete — {draft['sent']} delivered, {draft['failed']} failed."
    else:
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Continue next batch",callback_data=f"tgbc_send:{token}")],[InlineKeyboardButton(text="🏠 Admin Dashboard",callback_data="admin_menu")]])
        msg=f"📣 Batch sent. Running total: {draft['sent']} delivered, {draft['failed']} failed. Tap Continue for the next batch."
    await q.message.answer(msg,reply_markup=kb)


@dp.message(F.photo)
async def telegram_admin_photo_input(m:Message):
    if not m.from_user or m.from_user.id!=ADMIN_ID:return
    flow=get_admin_flow(m.from_user.id)
    if not flow:return
    action=str(flow.get('action'));data=dict(flow.get('data') or {})
    if action not in {'tg_product_image','tg_method_image','tg_method_gallery'}:return
    try:
        buf=await bot.download(m.photo[-1]);content=buf.getvalue() if hasattr(buf,'getvalue') else buf.read()
    except Exception as exc:return await m.answer(f"Could not download photo: {html_escape(str(exc))}",parse_mode="HTML")
    if len(content)>5*1024*1024:return await m.answer("Image too large (max 5 MB).")
    detected_type = detect_image_content_type(content) or "image/jpeg"
    if action=='tg_product_image':
        pid=str(data.get('product_id') or '');product_images_col.update_one({"product_id":pid},{"$set":{"product_id":pid,"content_type":detected_type,"data":Binary(content)}},upsert=True);products_col.update_one({"id":pid},{"$set":{"image":f"/media/product/{pid}","updated_at":utcnow()}});back=f"tgp:{pid}";label="Product"
        clear_admin_flow(m.from_user.id);await m.answer(f"✅ {label} image updated from Telegram photo.",reply_markup=admin_back_markup(back));return
    mid=str(data.get('method_id') or '')
    if not methods_col.find_one({"id": mid}):
        clear_admin_flow(m.from_user.id);return await m.answer("Method not found.")
    if action=='tg_method_image':
        method_images_col.update_one({"method_id":mid},{"$set":{"method_id":mid,"content_type":detected_type,"data":Binary(content)}},upsert=True);methods_col.update_one({"id":mid},{"$set":{"image":f"/media/method/{mid}","updated_at":utcnow()}});invalidate_method_catalog_cache();clear_admin_flow(m.from_user.id);await m.answer("✅ Method cover updated from Telegram photo.",reply_markup=admin_back_markup(f"tgm:{mid}"));return
    method=methods_col.find_one({"id":mid},{"_id":0}) or {}
    gallery=method_gallery_urls(method)
    if len(gallery)>=MAX_METHOD_GALLERY_IMAGES:
        return await m.answer(f"Gallery is full ({MAX_METHOD_GALLERY_IMAGES} images). Send <code>done</code> or <code>clear</code>.",parse_mode="HTML")
    gid=secrets.token_hex(6)
    if cloudinary_credentials():
        uploaded=await asyncio.to_thread(cloudinary_upload,content,f"method-{mid}-gallery-{gid}.jpg",f"method-{mid}-gallery-{gid}")
        url=uploaded["secure_url"]
    else:
        if len(content)>MAX_METHOD_GALLERY_IMAGE_BYTES:
            return await m.answer("Gallery image is too large for MongoDB storage (max 2 MB). Use a smaller image/URL or configure Cloudinary.")
        method_gallery_col.insert_one({"image_id":gid,"method_id":mid,"content_type":detected_type,"data":Binary(content),"created_at":utcnow()})
        url=f"/media/method/{mid}/gallery/{gid}"
    methods_col.update_one({"id":mid},{"$addToSet":{"gallery":url},"$set":{"updated_at":utcnow()}});invalidate_method_catalog_cache()
    count=len(gallery)+1
    await m.answer(f"✅ Gallery image added • {count}/{MAX_METHOD_GALLERY_IMAGES}\nSend another photo/URL, or <code>done</code>.",parse_mode="HTML")


@dp.message(F.text)
async def telegram_admin_flow_input(m: Message):
    if not m.from_user:
        return

    # Normalize message text once before any flow uses it.
    text = str(m.text or "").strip()

    # Downloader URL-first flow. Direct files start immediately; media pages
    # ask for quality only after Render #1 classifies the URL.
    _dl_state = _download_state(m.from_user.id)

    async def _start_download_job(url: str, quality: str, probe: dict | None = None):
        probe = probe or {}
        direct = str(probe.get("kind") or "") == "direct"
        filename = html_escape(str(probe.get("filename") or "Preparing…"))
        size = int(probe.get("size") or 0)
        if size >= 1024**3:
            size_text = f"{size / (1024**3):.2f} GB"
        elif size:
            size_text = f"{size / (1024**2):.1f} MB"
        else:
            size_text = "—"
        worker_count = int(probe.get("worker_count") or 0)
        workers_text = str(worker_count) if direct and worker_count else "—"

        status_message = await m.answer(
            "📥 <b>Download Status</b>\n\n"
            f"📄 {filename}\n"
            f"🎚 Quality: <b>{html_escape(quality)}</b>\n"
            "📊 Status: <b>QUEUED</b>\n"
            f"⏳ <code>{_download_progress_bar(0)}</code> <b>0%</b>\n"
            f"📦 Size: <b>{size_text}</b>\n"
            f"⚡ Workers: <b>{workers_text}</b>",
            parse_mode="HTML",
        )
        result = await downloader_api("POST", "/api/jobs", {
            "user_id": int(m.from_user.id),
            "chat_id": int(m.chat.id),
            "url": url,
            "quality": quality,
            "status_message_id": int(status_message.message_id),
        })
        job_id = str(result.get("job_id") or "")
        users_col.update_one(
            {"user_id": int(m.from_user.id)},
            {
                "$set": {
                    "downloader_last_job_id": job_id,
                    "downloader_quality": quality,
                },
                "$unset": {
                    "downloader_flow": "",
                    "downloader_pending_url": "",
                    "downloader_probe": "",
                },
            },
            upsert=True,
        )
        await m.answer(
            "✅ Download started. The status message above will update automatically.\n"
            "When finished, the file will be delivered inside Telegram.",
            reply_markup=downloader_keyboard(m.from_user.id),
        )

    if _dl_state.get("downloader_flow") == "await_url":
        if text.lower() in {"/cancel", "cancel"} or text == "❌ Cancel Download":
            users_col.update_one(
                {"user_id": int(m.from_user.id)},
                {"$unset": {
                    "downloader_flow": "",
                    "downloader_quality": "",
                    "downloader_pending_url": "",
                    "downloader_probe": "",
                }},
            )
            return await m.answer("❌ Downloader action cancelled.", reply_markup=downloader_keyboard(m.from_user.id))
        if not re.match(r"^https?://", text, re.I):
            return await m.answer("Please send a valid http:// or https:// URL, or /cancel.", reply_markup=downloader_keyboard(m.from_user.id))

        try:
            probe = await downloader_api("POST", "/api/probe", {"url": text})
            if str(probe.get("kind") or "media") == "direct":
                workers = int(probe.get("worker_count") or 1)
                range_note = (
                    f"⚡ Up to <b>{workers}</b> workers will download this file together."
                    if workers > 1 else "⚡ This source will use <b>1 worker</b>."
                )
                await m.answer(
                    "✅ <b>Direct file detected</b>\n"
                    "🎚 Quality: <b>Original</b>\n"
                    f"{range_note}",
                    parse_mode="HTML",
                )
                await _start_download_job(text, "original", probe)
                return

            users_col.update_one(
                {"user_id": int(m.from_user.id)},
                {"$set": {
                    "downloader_flow": "await_quality",
                    "downloader_pending_url": text,
                    "downloader_probe": probe,
                }},
                upsert=True,
            )
            return await m.answer(
                "🎬 <b>Media page detected</b>\n\n"
                "Choose the quality you want. If that exact quality is unavailable, "
                "the downloader will use the best available format.",
                parse_mode="HTML",
                reply_markup=downloader_quality_keyboard(),
            )
        except Exception as exc:
            return await m.answer(
                f"❌ Could not inspect this URL: {html_escape(str(exc))}",
                parse_mode="HTML",
                reply_markup=downloader_keyboard(m.from_user.id),
            )

    if _dl_state.get("downloader_flow") == "await_quality":
        if text.lower() in {"/cancel", "cancel"} or text == "❌ Cancel Download":
            users_col.update_one(
                {"user_id": int(m.from_user.id)},
                {"$unset": {
                    "downloader_flow": "",
                    "downloader_quality": "",
                    "downloader_pending_url": "",
                    "downloader_probe": "",
                }},
            )
            return await m.answer("❌ Downloader action cancelled.", reply_markup=downloader_keyboard(m.from_user.id))

        quality = DOWNLOAD_QUALITY_MAP.get(text)
        if not quality:
            return await m.answer("Choose one of the quality buttons below.", reply_markup=downloader_quality_keyboard())

        pending_url = str(_dl_state.get("downloader_pending_url") or "")
        if not pending_url:
            users_col.update_one(
                {"user_id": int(m.from_user.id)},
                {"$unset": {"downloader_flow": "", "downloader_probe": ""}},
            )
            return await m.answer(
                "The pending URL expired. Tap 🔗 Send Link and send it again.",
                reply_markup=downloader_keyboard(m.from_user.id),
            )
        try:
            await _start_download_job(pending_url, quality, dict(_dl_state.get("downloader_probe") or {}))
            return
        except Exception as exc:
            users_col.update_one(
                {"user_id": int(m.from_user.id)},
                {"$unset": {"downloader_flow": "", "downloader_pending_url": "", "downloader_probe": ""}},
            )
            return await m.answer(
                f"❌ Could not start download: {html_escape(str(exc))}",
                parse_mode="HTML",
                reply_markup=downloader_keyboard(m.from_user.id),
            )

    # Temp Mail text-entry flows are persisted in MongoDB so they work across Vercel cold starts.
    temp_flow = await _get_temp_mail_flow(int(m.from_user.id))
    if temp_flow:
        text = str(m.text or "").strip()
        if text.lower() in {"/cancel", "cancel"}:
            await _clear_temp_mail_flow(int(m.from_user.id))
            return await m.answer("❌ Temp Mail action cancelled.", reply_markup=temp_mail_keyboard(m.from_user.id))

        action = str(temp_flow.get("action") or "")
        flow_data = dict(temp_flow.get("data") or {})

        if action == "custom_username":
            username = text.lower().strip()
            if "@" in username:
                username = username.split("@", 1)[0]
            if not re.fullmatch(r"[a-z0-9._-]{3,30}", username):
                return await m.answer(
                    "Use 3–30 characters: letters, numbers, dot, underscore or hyphen.\n"
                    "Example: <code>myname123</code>",
                    parse_mode="HTML",
                )
            try:
                await _stop_temp_mail_watches(m.from_user.id)
                data = await temp_mail_api("/api/mail/create", {
                    "user_id": int(m.from_user.id),
                    "username": username,
                })
                address = str(data.get("address") or "")
                password = str(data.get("password") or "")
                if not address or not password:
                    raise RuntimeError("Backend returned incomplete mailbox details.")
                _save_temp_mail_credentials(m.from_user.id, address, password, "custom")
                await _clear_temp_mail_flow(m.from_user.id)
                return await m.answer(
                    "✅ <b>Custom temp mail created</b>\n\n"
                    f"📧 <b>Mail ID:</b> <code>{html_escape(address)}</code>\n"
                    f"🔑 <b>Password:</b> <code>{html_escape(password)}</code>\n\n"
                    "Saved securely in MongoDB.",
                    parse_mode="HTML",
                    reply_markup=temp_mail_keyboard(m.from_user.id),
                )
            except Exception as exc:
                log.exception("Custom temp mail creation failed")
                return await m.answer(
                    f"❌ Could not create that address: {html_escape(str(exc))}\n\n"
                    "Try another username or send /cancel.",
                    parse_mode="HTML",
                )

        if action == "login_address":
            address = text.lower()
            if not valid_email_address(address):
                return await m.answer("Please send a valid Mail.tm email address, or /cancel.")
            await _set_temp_mail_flow(m.from_user.id, "login_password", address=address)
            return await m.answer(
                f"🔐 Email: <code>{html_escape(address)}</code>\n\n"
                "Now send the password. I will try to remove your password message after reading it.",
                parse_mode="HTML",
            )

        if action == "login_password":
            address = str(flow_data.get("address") or "").strip().lower()
            password = text
            if not address:
                await _clear_temp_mail_flow(m.from_user.id)
                return await m.answer("Login session expired. Tap 🔐 Login Old Mail again.")
            if not password:
                return await m.answer("Password cannot be empty. Send it again or /cancel.")
            try:
                try:
                    await m.delete()
                except Exception:
                    pass
                await _stop_temp_mail_watches(m.from_user.id)
                data = await temp_mail_api("/api/mail/login", {"user_id": int(m.from_user.id), "address": address, "password": password})
                verified_address = str(data.get("address") or address).strip().lower()
                _save_temp_mail_credentials(m.from_user.id, verified_address, password, "login")
                await _clear_temp_mail_flow(m.from_user.id)
                return await m.answer(
                    "✅ <b>Old Mail.tm inbox connected</b>\n\n"
                    f"📧 <code>{html_escape(verified_address)}</code>\n\n"
                    "The credentials are encrypted in MongoDB and this inbox is now your current Temp Mail.",
                    parse_mode="HTML",
                    reply_markup=temp_mail_keyboard(m.from_user.id),
                )
            except Exception as exc:
                log.exception("Old temp mail login failed")
                return await m.answer(
                    f"❌ Login failed: {html_escape(str(exc))}\n\n"
                    "Check the password and send it again, or /cancel.",
                    parse_mode="HTML",
                )

    # Customer activation-code submission flow. The raw code is forwarded to the admin
    # and is not persisted in the order record.
    customer_flow = get_customer_activation_flow(int(m.from_user.id))
    if customer_flow:
        text = str(m.text or "").strip()
        if text.lower() in {"/cancel", "cancel"}:
            clear_customer_activation_flow(int(m.from_user.id))
            return await m.answer("❌ Activation-code submission cancelled.")
        if not text:
            return await m.answer("Please send the activation code as text, or /cancel to stop.")
        if len(text) > 300:
            return await m.answer("Activation code is limited to 300 characters.")
        code = str(customer_flow.get("order_code") or "")
        idx = int(customer_flow.get("fulfillment_index") or 0)
        order = orders_col.find_one({"order_code": code, "user_id": int(m.from_user.id)})
        if not order:
            clear_customer_activation_flow(int(m.from_user.id))
            return await m.answer("❌ Order not found. Please contact support.")
        entries = list(order.get("manual_fulfillment") or [])
        if idx < 0 or idx >= len(entries) or not bool(entries[idx].get("login_assistance")):
            clear_customer_activation_flow(int(m.from_user.id))
            return await m.answer("❌ Activation request not found. Please contact support.")
        entry = entries[idx]
        if entry.get("activation_code_submitted"):
            clear_customer_activation_flow(int(m.from_user.id))
            return await m.answer("✅ Your activation code has already been sent to the admin.")

        # Store only a one-way hash for audit/deduplication; do not persist the raw code.
        code_hash = hashlib.sha256(text.encode()).hexdigest()
        now = utcnow()
        result = orders_col.update_one(
            {"_id": order["_id"], f"manual_fulfillment.{idx}.activation_code_submitted": {"$ne": True}},
            {"$set": {
                f"manual_fulfillment.{idx}.activation_code_submitted": True,
                f"manual_fulfillment.{idx}.activation_code_hash": code_hash,
                f"manual_fulfillment.{idx}.activation_code_submitted_at": now,
                "updated_at": now,
            }},
        )
        clear_customer_activation_flow(int(m.from_user.id))
        if result.modified_count != 1:
            return await m.answer("✅ Your activation code has already been sent to the admin.")

        product_name = str(entry.get("name") or "Product")
        customer_name = str(m.from_user.full_name or "Customer")
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔐 <b>ACTIVATION CODE RECEIVED</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"Order: <code>#{html_escape(code)}</code>\n"
                f"Product: <b>{html_escape(product_name)}</b>\n"
                f"Quantity: <b>{int(entry.get('qty') or 1)}</b>\n"
                f"Customer: <b>{html_escape(customer_name)}</b>\n"
                f"Customer ID: <code>{int(m.from_user.id)}</code>\n\n"
                f"🔑 <b>Activation code:</b> <code>{html_escape(text)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                "Use the order details to activate/fulfill the customer's purchase.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🧾 Open order", callback_data=f"tgo:{code}")
                ]]),
            )
        except Exception:
            log.exception("Could not forward activation code to admin for %s", code)
            # Keep the submitted state so the customer is not prompted repeatedly.
        await m.answer(
            "✅ <b>Code sent to admin.</b>\n\n"
            f"Product: <b>{html_escape(product_name)}</b>\n"
            "The admin will activate your order and notify you here in Telegram.",
            parse_mode="HTML",
        )
        return

    if m.from_user.id != ADMIN_ID:
        return
    flow = get_admin_flow(m.from_user.id)
    if not flow:
        return
    text = str(m.text or "").strip()
    if text.lower() in {"/cancel", "cancel", "❌ cancel"}:
        clear_admin_flow(m.from_user.id)
        return await m.answer("❌ Admin action cancelled.", reply_markup=admin_back_markup("admin_features"))

    action = str(flow.get("action"))
    data = dict(flow.get("data") or {})

    # Operational admin flows (bounded notes/templates; no growing audit trail).
    if action == "tg_customer_note":
        uid=int(data.get("user_id") or 0)
        if not users_col.find_one({"user_id":uid}):
            clear_admin_flow(m.from_user.id);return await m.answer("Customer not found.")
        note="" if text.lower()=="clear" else text
        if len(note)>MAX_INTERNAL_NOTE_LENGTH:return await m.answer(f"Note is limited to {MAX_INTERNAL_NOTE_LENGTH} characters.")
        users_col.update_one({"user_id":uid},{"$set":{"admin_note":note,"admin_note_updated_at":utcnow()}});clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Customer note updated.",reply_markup=admin_back_markup(f"tgc:{uid}"))

    if action == "tg_order_note":
        code=str(data.get("order_code") or "")
        if not orders_col.find_one({"order_code":code}):
            clear_admin_flow(m.from_user.id);return await m.answer("Order not found.")
        note="" if text.lower()=="clear" else text
        if len(note)>MAX_INTERNAL_NOTE_LENGTH:return await m.answer(f"Note is limited to {MAX_INTERNAL_NOTE_LENGTH} characters.")
        orders_col.update_one({"order_code":code},{"$set":{"admin_note":note,"admin_note_updated_at":utcnow()}});clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Order note updated.",reply_markup=admin_back_markup(f"tgo:{code}"))

    if action == "tg_template_name":
        if not text or len(text)>60:return await m.answer("Template name must be 1–60 characters.")
        products=list(products_col.find({},{"_id":0,"id":1,"name":1}).sort("name",1).limit(40))
        choices=[str(x.get("id") or "") for x in products]
        set_admin_flow(m.from_user.id,"tg_template_choose_product",name=text,product_choices=choices)
        rows=[[InlineKeyboardButton(text="🌐 Global / any product",callback_data="tgtplp:g")]]+[[InlineKeyboardButton(text=f"🛍 {str(x.get('name') or x.get('id'))[:36]}",callback_data=f"tgtplp:{i}")] for i,x in enumerate(products)]
        return await m.answer("Step 2/3: choose which product this template belongs to.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    if action == "tg_template_body":
        if not text or len(text)>3000:return await m.answer("Template body must be 1–3000 characters.")
        if fulfillment_templates_col.count_documents({})>=MAX_FULFILLMENT_TEMPLATES:return await m.answer("Template limit reached.")
        tid=f"tpl-{secrets.token_hex(6)}";now=utcnow();fulfillment_templates_col.insert_one({"id":tid,"name":str(data.get('name') or 'Template')[:60],"product_id":str(data.get('product_id') or ''),"body":text,"active":True,"created_at":now,"updated_at":now});clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Delivery template saved.",reply_markup=admin_back_markup("tgtpl"))

    if action == "tg_template_edit_body":
        tid=str(data.get("template_id") or "")
        if not text or len(text)>3000:return await m.answer("Template body must be 1–3000 characters.")
        result=fulfillment_templates_col.update_one({"id":tid},{"$set":{"body":text,"updated_at":utcnow()}});clear_admin_flow(m.from_user.id)
        if not result.matched_count:return await m.answer("Template not found.")
        return await m.answer("✅ Template body updated.",reply_markup=admin_back_markup(f"tgtplv:{tid}"))

    # Full Telegram admin parity flows.
    if action == "tg_product_new_name":
        if len(text) < 2 or len(text) > 120:
            return await m.answer("Product name must be 2–120 characters.")
        set_admin_flow(m.from_user.id, "tg_product_new_price", name=text)
        return await m.answer("Step 2/2: send the base price in credits (0 or higher).")

    if action == "tg_product_new_price":
        try:
            price = int(text)
        except ValueError:
            return await m.answer("Send a whole-number price, e.g. 100.")
        if price < 0 or price > 1000000000:
            return await m.answer("Price must be between 0 and 1,000,000,000 credits.")
        name = str(data.get("name") or "Product").strip()
        pid = slugify(name) + "-" + secrets.token_hex(2)
        products_col.insert_one({
            "id": pid, "name": name, "price": price, "emoji": "🔑", "description": "",
            "instructions": "", "warranty": "", "support_note": "", "delivery_note": "",
            "category": "General", "active": True, "featured": False, "bestseller": False,
            "badge_new": False, "variants": [{"id": "default", "label": "Default", "price": price, "low_stock": DEFAULT_LOW_STOCK, "subscription_days": 0}],
            "delivery_type": "digital", "fulfillment_mode": "instant", "subscription_days": 0,
            "reminder_note": "", "purchase_key_required": False, "purchase_key_hash": "",
            "otp_enabled": False, "otp_price": OTP_PRICE, "image": "", "created_at": utcnow(), "updated_at": utcnow(),
        })
        clear_admin_flow(m.from_user.id)
        return await m.answer(
            f"✅ Product created: <b>{html_escape(name)}</b>\nID: <code>{html_escape(pid)}</code>\n\nOpen it to configure every other field.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Open product", callback_data=f"tgp:{pid}")],[InlineKeyboardButton(text="⬅️ Products", callback_data="tgadm_products:0")]])
        )

    if action == "tg_product_field":
        pid = str(data.get("product_id") or "")
        code = str(data.get("field_code") or "")
        spec = TG_PRODUCT_FIELD_CODES.get(code)
        product = products_col.find_one({"id": pid})
        if not product or not spec:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product or field no longer exists.")
        field, label = spec
        if field in {"price", "otp_price", "subscription_days"}:
            try:
                value = int(text)
            except ValueError:
                return await m.answer("Send a whole number.")
            if field == "price" and not (0 <= value <= 1000000000):
                return await m.answer("Price must be 0–1,000,000,000.")
            if field == "otp_price" and not (1 <= value <= 1000000000):
                return await m.answer("OTP price must be at least 1.")
            if field == "subscription_days" and not (0 <= value <= 36500):
                return await m.answer("Subscription days must be 0–36,500.")
            update = {field: value, "updated_at": utcnow()}
            if field == "price":
                variants = list(product.get("variants") or [])
                if len(variants) == 1 and str(variants[0].get("id")) == "default":
                    variants[0]["price"] = value
                    update["variants"] = variants
            if field == "subscription_days":
                variants = list(product.get("variants") or [])
                for v in variants:
                    if int(v.get("subscription_days") or 0) == int(product.get("subscription_days") or 0):
                        v["subscription_days"] = value
                update["variants"] = variants
        else:
            value = "" if text.lower() == "clear" else text
            if field == "name" and not (2 <= len(value) <= 120):
                return await m.answer("Name must be 2–120 characters.")
            if field == "emoji" and len(value) > 16:
                return await m.answer("Emoji/short icon field is too long.")
            max_len = 4000 if field in {"description", "instructions"} else 2000
            if len(value) > max_len:
                return await m.answer(f"Value is too long (max {max_len} characters).")
            update = {field: value, "updated_at": utcnow()}
        products_col.update_one({"id": pid}, {"$set": update})
        clear_admin_flow(m.from_user.id)
        return await m.answer(f"✅ {html_escape(label)} updated.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Open product", callback_data=f"tgp:{pid}")]]))

    if action == "tg_product_variants":
        pid = str(data.get("product_id") or "")
        product = products_col.find_one({"id": pid})
        if not product:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        try:
            variants = parse_variants(text, int(product.get("price", 0)), int(product.get("subscription_days", 0)))
        except Exception as exc:
            return await m.answer(f"❌ Invalid variants: {html_escape(str(exc))}", parse_mode="HTML")
        if not variants:
            return await m.answer("At least one variant is required.")
        old_first = ((product.get("variants") or [{}])[0].get("id") or "default")
        new_first = variants[0]["id"]
        products_col.update_one({"id": pid}, {"$set": {"variants": variants, "updated_at": utcnow()}})
        if old_first == "default" and new_first != "default":
            digital_inventory_col.update_many({"product_id": pid, "variant_id": {"$in": ["default", None]}}, {"$set": {"variant_id": new_first}})
        clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Variants replaced.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Open product", callback_data=f"tgp:{pid}")]]))

    if action == "tg_product_inventory":
        pid = str(data.get("product_id") or "")
        product = products_col.find_one({"id": pid})
        if not product:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        if str(product.get("fulfillment_mode") or "instant") != "instant":
            clear_admin_flow(m.from_user.id)
            return await m.answer("Only instant-delivery products use digital inventory.")
        variants = list(product.get("variants") or [])
        before = product_total_stock(pid)
        try:
            items = parse_inventory_lines(text, variants)
        except Exception as exc:
            return await m.answer(f"❌ Inventory format error: {html_escape(str(exc))}", parse_mode="HTML")
        if not items:
            return await m.answer("No valid inventory lines were found.")
        digital_inventory_col.insert_many([{"product_id": pid, "variant_id": vid, "payload_enc": encrypt_payload(payload), "sold": False, "created_at": utcnow()} for vid, payload in items])
        after = product_total_stock(pid)
        await notify_restock(pid, before, after)
        await maybe_low_stock_alert([pid])
        clear_admin_flow(m.from_user.id)
        return await m.answer(f"✅ Added <b>{len(items)}</b> inventory item(s). Stock: <b>{after}</b>.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 View inventory", callback_data=f"tginvp:{pid}:0")],[InlineKeyboardButton(text="↩️ Product", callback_data=f"tgp:{pid}")]]))

    if action == "tg_product_image":
        pid = str(data.get("product_id") or "")
        if not products_col.find_one({"id": pid}):
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        if text.lower() == "clear":
            products_col.update_one({"id": pid}, {"$set": {"image": "", "updated_at": utcnow()}})
            product_images_col.delete_one({"product_id": pid})
        elif text.startswith(("https://", "http://")):
            products_col.update_one({"id": pid}, {"$set": {"image": text, "updated_at": utcnow()}})
        else:
            return await m.answer("Send an http/https URL, a Telegram photo, or 'clear'.")
        clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Product image setting updated.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Product", callback_data=f"tgp:{pid}")]]))

    if action == "tg_method_new_title":
        if not (2 <= len(text) <= 160):
            return await m.answer("Method title must be 2–160 characters.")
        mid = slugify(text) + "-" + secrets.token_hex(2)
        methods_col.insert_one({"id": mid, "title": text, "summary": "", "body": "", "price": 0, "is_free": False, "sort_order": 0, "active": True, "image": "", "gallery": [], "created_at": utcnow(), "updated_at": utcnow()}); invalidate_method_catalog_cache()
        clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Method created with safe defaults. Open it to edit all fields.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ Open method", callback_data=f"tgm:{mid}")]]))

    if action == "tg_method_field":
        mid = str(data.get("method_id") or "")
        code = str(data.get("field_code") or "")
        method = methods_col.find_one({"id": mid})
        spec = TG_METHOD_FIELDS.get(code)
        if not method or not spec:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Method or field not found.")
        field, label = spec
        if field in {"price", "sort_order"}:
            try: value = int(text)
            except ValueError: return await m.answer("Send a whole number.")
            if field == "price" and value < 0: return await m.answer("Price cannot be negative.")
        else:
            value = "" if text.lower() == "clear" else text
            if field == "title" and not (2 <= len(value) <= 160): return await m.answer("Title must be 2–160 characters.")
            if len(value) > 12000: return await m.answer("Text is too long (max 12,000 characters).")
        methods_col.update_one({"id": mid}, {"$set": {field: value, "updated_at": utcnow()}}); invalidate_method_catalog_cache()
        clear_admin_flow(m.from_user.id)
        return await m.answer(f"✅ {html_escape(label)} updated.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Open method", callback_data=f"tgm:{mid}")]]))

    if action == "tg_method_image":
        mid = str(data.get("method_id") or "")
        if not methods_col.find_one({"id": mid}):
            clear_admin_flow(m.from_user.id); return await m.answer("Method not found.")
        if text.lower() == "clear":
            methods_col.update_one({"id": mid}, {"$set": {"image": "", "updated_at": utcnow()}}); method_images_col.delete_one({"method_id": mid})
        elif text.startswith(("http://", "https://")):
            methods_col.update_one({"id": mid}, {"$set": {"image": text, "updated_at": utcnow()}})
        else:
            return await m.answer("Send an http/https URL, Telegram photo, or 'clear'.")
        invalidate_method_catalog_cache(); clear_admin_flow(m.from_user.id)
        return await m.answer("✅ Method image updated.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Method", callback_data=f"tgm:{mid}")]]))

    if action == "tg_method_gallery":
        mid = str(data.get("method_id") or "")
        method = methods_col.find_one({"id": mid}, {"_id": 0})
        if not method:
            clear_admin_flow(m.from_user.id); return await m.answer("Method not found.")
        lower = text.lower()
        if lower in {"done", "/done", "finish", "finished"}:
            clear_admin_flow(m.from_user.id)
            return await m.answer("✅ Method gallery finished.", reply_markup=admin_back_markup(f"tgm:{mid}"))
        if lower == "clear":
            method_gallery_col.delete_many({"method_id": mid})
            methods_col.update_one({"id": mid}, {"$set": {"gallery": [], "updated_at": utcnow()}})
            invalidate_method_catalog_cache(); clear_admin_flow(m.from_user.id)
            return await m.answer("✅ Method gallery cleared.", reply_markup=admin_back_markup(f"tgm:{mid}"))
        if not text.startswith(("http://", "https://")):
            return await m.answer("Send an http/https image URL, a Telegram photo, <code>done</code>, or <code>clear</code>.", parse_mode="HTML")
        gallery = method_gallery_urls(method)
        if len(gallery) >= MAX_METHOD_GALLERY_IMAGES:
            return await m.answer(f"Gallery is full ({MAX_METHOD_GALLERY_IMAGES} images). Send <code>done</code> or <code>clear</code>.", parse_mode="HTML")
        try:
            url = safe_image_url(text)
        except HTTPException:
            return await m.answer("Invalid image URL.")
        methods_col.update_one({"id": mid}, {"$addToSet": {"gallery": url}, "$set": {"updated_at": utcnow()}})
        invalidate_method_catalog_cache()
        count = len(gallery) + (0 if url in gallery else 1)
        return await m.answer(f"✅ Gallery image added • {count}/{MAX_METHOD_GALLERY_IMAGES}\nSend another photo/URL, or <code>done</code>.", parse_mode="HTML")

    if action == "tg_customer_search":
        query = text.strip().lstrip("@")
        docs = []
        if query.lstrip("-").isdigit():
            doc = users_col.find_one({"user_id": int(query)}, {"_id": 0})
            if doc: docs = [doc]
        if not docs:
            rx = re.compile(re.escape(query), re.I)
            docs = list(users_col.find({"$or": [{"username": rx}, {"full_name": rx}]}, {"_id": 0}).sort("last_seen", -1).limit(10))
        clear_admin_flow(m.from_user.id)
        if not docs: return await m.answer("No matching customer found.", reply_markup=admin_back_markup("tgadm_customers:0"))
        kb = [[InlineKeyboardButton(text=f"👤 {str(u.get('full_name') or u.get('username') or u['user_id'])[:30]}", callback_data=f"tgc:{u['user_id']}")] for u in docs]
        kb.append([InlineKeyboardButton(text="⬅️ Customers", callback_data="tgadm_customers:0")])
        return await m.answer(f"🔎 Found <b>{len(docs)}</b> customer(s).", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    if action == "tg_customer_credit":
        uid = int(data.get("user_id")); mode = str(data.get("mode"))
        try: amount = int(text)
        except ValueError: return await m.answer("Send a whole number.")
        try: new = adjust_credit(uid, amount, ADMIN_ID, set_to=amount if mode == "set" else None)
        except Exception as exc: return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")
        try: await bot.send_message(uid, f"💳 Your new balance is <b>{money(new)}</b>", parse_mode="HTML")
        except Exception: pass
        clear_admin_flow(m.from_user.id)
        return await m.answer(f"✅ Customer <code>{uid}</code> balance: <b>{money(new)}</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Customer", callback_data=f"tgc:{uid}")]]))

    if action == "tg_broadcast_message":
        if not text or len(text) > 3900: return await m.answer("Message must be 1–3900 characters.")
        set_admin_flow(m.from_user.id, "tg_broadcast_image", message=text)
        return await m.answer("Step 2/4: send an optional image URL, or <code>skip</code>.", parse_mode="HTML")

    if action == "tg_broadcast_image":
        image = "" if text.lower() in {"skip", "none", "-"} else text
        if image and not image.startswith(("http://", "https://")): return await m.answer("Image URL must start with http:// or https://, or send skip.")
        set_admin_flow(m.from_user.id, "tg_broadcast_button_text", message=data.get("message", ""), image_url=image)
        return await m.answer("Step 3/4: send optional button text, or <code>skip</code>.", parse_mode="HTML")

    if action == "tg_broadcast_button_text":
        button_text = "" if text.lower() in {"skip", "none", "-"} else text[:64]
        set_admin_flow(m.from_user.id, "tg_broadcast_button_url", message=data.get("message", ""), image_url=data.get("image_url", ""), button_text=button_text)
        return await m.answer("Step 4/4: send the button URL (<code>http://</code>, <code>https://</code>, or <code>tg://</code>), or <code>skip</code>. If you set button text, a URL is required.", parse_mode="HTML")

    if action == "tg_broadcast_button_url":
        url = "" if text.lower() in {"skip", "none", "-"} else text
        button_text = str(data.get("button_text") or "")
        if button_text and not url: return await m.answer("You set button text, so send a button URL or /cancel.")
        if url and not url.startswith(("http://", "https://", "tg://")): return await m.answer("Button URL must start with http://, https:// or tg://.")
        token = secrets.token_hex(5)
        draft = {"message": str(data.get("message") or ""), "image_url": str(data.get("image_url") or ""), "button_text": button_text, "button_url": url, "cursor": 0, "sent": 0, "failed": 0, "created_at": utcnow().isoformat()}
        set_setting(f"tg_broadcast:{token}", draft)
        clear_admin_flow(m.from_user.id)
        preview = html_escape(tg_trim(draft["message"], 700))
        return await m.answer(f"📣 <b>Broadcast ready</b>\n\n{preview}\n\nRecipients: <b>{users_col.count_documents({'broadcast_opt_out': {'$ne': True}, 'broadcast_blocked': {'$ne': True}})}</b> eligible. Sending happens in safe batches of 30.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Send first batch", callback_data=f"tgbc_send:{token}")],[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_broadcast")]]))

    if action == "set_purchase_key":
        pid = str(data.get("product_id") or "")
        product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
        if not product:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        if len(text) < 4 or len(text) > 128:
            return await m.answer("Key must be 4–128 characters. Send another key or /cancel.")
        products_col.update_one({"id": pid}, {"$set": {
            "purchase_key_required": True,
            "purchase_key_hash": purchase_key_hash(pid, text),
            "updated_at": utcnow(),
        }})
        clear_admin_flow(m.from_user.id)
        try:
            await m.delete()
        except Exception:
            pass
        return await m.answer(
            f"✅ Purchase key rotated and enabled for <b>{html_escape(product.get('name', pid))}</b>.\n"
            "The plaintext key was not stored.", parse_mode="HTML", reply_markup=admin_back_markup("adm_keys"),
        )

    if action == "set_subscription_days":
        pid = str(data.get("product_id") or "")
        try:
            days = int(text)
        except ValueError:
            return await m.answer("Send a whole number of days, e.g. 30, 90, 365, or 0 to disable.")
        if days < 0 or days > 36500:
            return await m.answer("Days must be between 0 and 36,500.")
        product = products_col.find_one({"id": pid})
        if not product:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        variants = list(product.get("variants") or [])
        for variant in variants:
            variant["subscription_days"] = days
        products_col.update_one({"id": pid}, {"$set": {
            "subscription_days": days,
            "variants": variants,
            "updated_at": utcnow(),
        }})
        clear_admin_flow(m.from_user.id)
        return await m.answer(
            f"✅ Subscription duration updated to <b>{days} days</b> for all variants of <b>{html_escape(str(product.get('name') or pid))}</b>."
            + ("\nAutomatic reminders are disabled for future purchases." if days == 0 else "\nFuture purchases will remind you one day before expiry."),
            parse_mode="HTML", reply_markup=admin_back_markup("adm_reminders"),
        )

    if action == "set_reminder_note":
        pid = str(data.get("product_id") or "")
        product = products_col.find_one({"id": pid}, {"_id": 0, "name": 1})
        if not product:
            clear_admin_flow(m.from_user.id)
            return await m.answer("Product not found.")
        note = "" if text.lower() == "clear" else text[:2000]
        products_col.update_one({"id": pid}, {"$set": {"reminder_note": note, "updated_at": utcnow()}})
        clear_admin_flow(m.from_user.id)
        return await m.answer(
            f"✅ Reminder note {'cleared' if not note else 'updated'} for <b>{html_escape(product.get('name', pid))}</b>.",
            parse_mode="HTML", reply_markup=admin_back_markup("adm_reminders"),
        )

    if action == "manual_reminder_title":
        if len(text) < 2 or len(text) > 200:
            return await m.answer("Title must be 2–200 characters.")
        set_admin_flow(m.from_user.id, "manual_reminder_expiry", title=text)
        return await m.answer(
            f"Step 2/4: Send the <b>expiry date/time</b>.\n\n"
            f"Format: <code>DD-MM-YYYY HH:MM</code> ({html_escape(ADMIN_TIMEZONE_LABEL)}), e.g. <code>30-09-2026 18:00</code>.\n"
            "ISO dates with an explicit timezone are also accepted.", parse_mode="HTML",
        )

    if action == "manual_reminder_expiry":
        try:
            expiry = parse_admin_datetime_text(text)
        except ValueError as exc:
            return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")
        if expiry <= utcnow():
            return await m.answer("Expiry must be in the future.")
        set_admin_flow(m.from_user.id, "manual_reminder_contact", title=data.get("title", "Subscription"), expires_at=expiry.isoformat())
        return await m.answer(
            "Step 3/4: Send an optional <b>email</b> and/or <b>Telegram customer ID</b>.\n\n"
            "Examples:\n<code>person@example.com</code>\n<code>123456789</code>\n<code>person@example.com 123456789</code>\n\n"
            "Send <code>skip</code> if neither is needed.", parse_mode="HTML",
        )

    if action == "manual_reminder_contact":
        email = ""
        user_id = None
        if text.lower() not in {"skip", "-", "none"}:
            for token in text.split():
                if "@" in token and not email:
                    email = token.strip()
                elif token.lstrip("-").isdigit() and user_id is None:
                    user_id = int(token)
                else:
                    return await m.answer("Use an email, Telegram numeric ID, both separated by a space, or 'skip'.")
            if email and not valid_email_address(email):
                return await m.answer("That email address is invalid. Try again or send 'skip'.")
        set_admin_flow(
            m.from_user.id, "manual_reminder_note",
            title=data.get("title", "Subscription"), expires_at=data.get("expires_at"),
            email=email, user_id=user_id,
        )
        return await m.answer(
            "Step 4/4: Send your private reminder note, or send <code>skip</code> for no note.", parse_mode="HTML",
        )

    if action == "manual_reminder_note":
        note = "" if text.lower() in {"skip", "-", "none"} else text[:2000]
        try:
            expiry = parse_datetime_value(data.get("expires_at"), "expiry date")
        except ValueError:
            clear_admin_flow(m.from_user.id)
            return await m.answer("The saved expiry became invalid. Please create the reminder again.")
        rid = "manual:" + secrets.token_hex(8)
        doc = reminder_document(
            reminder_id=rid,
            title=str(data.get("title") or "Subscription"),
            expires_at=expiry,
            source="manual-telegram",
            custom_message=note,
            user_id=data.get("user_id"),
            email=str(data.get("email") or ""),
        )
        subscription_reminders_col.insert_one(doc)
        clear_admin_flow(m.from_user.id)
        return await m.answer(
            f"✅ <b>Manual reminder created</b>\n\n"
            f"Title: <b>{html_escape(doc['title'])}</b>\n"
            f"Expiry: <b>{html_escape(format_admin_datetime(doc['expires_at']))}</b>\n"
            f"Reminder time: <b>{html_escape(format_admin_datetime(doc['remind_at']))}</b>",
            parse_mode="HTML", reply_markup=admin_back_markup("adm_reminders"),
        )

    if action == "manual_order_delivery":
        code = str(data.get("order_code") or "")
        idx = int(data.get("fulfillment_index", -1))
        if not text or len(text) > 3000:
            return await m.answer("Prepared delivery must be 1–3000 characters. Send it again or /cancel.")
        try:
            result = await fulfill_manual_order(code, idx, text)
        except (ValueError, LookupError) as exc:
            clear_admin_flow(m.from_user.id)
            return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")
        clear_admin_flow(m.from_user.id)
        expiry = result.get("expires_at")
        return await m.answer(
            f"✅ <b>Prepared order delivered</b>\nOrder: <code>#{html_escape(code)}</code>"
            + (f"\nExpiry: <b>{html_escape(format_admin_datetime(expiry))}</b>\nOne-day-before reminder scheduled." if expiry else "\nNo expiry reminder was scheduled."),
            parse_mode="HTML", reply_markup=admin_back_markup("am_pending"),
        )

    if action == "fulfill_custom_expiry":
        try:
            expiry = parse_admin_datetime_text(text)
        except ValueError as exc:
            return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")
        if expiry <= utcnow():
            return await m.answer("Expiry must be in the future.")
        code = str(data.get("order_code") or "")
        idx = int(data.get("fulfillment_index", -1))
        try:
            result = await fulfill_email_order(code, idx, expiry_at=expiry)
        except (ValueError, LookupError) as exc:
            clear_admin_flow(m.from_user.id)
            return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")
        clear_admin_flow(m.from_user.id)
        return await m.answer(
            f"✅ <b>Subscription fulfilled</b>\nExpiry: <b>{html_escape(format_admin_datetime(result.get('expires_at')))}</b>\n"
            "The one-day-before reminder has been scheduled.",
            parse_mode="HTML", reply_markup=admin_back_markup("adm_email"),
        )

    clear_admin_flow(m.from_user.id)
    await m.answer("The admin action expired. Open /admin and try again.")


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "broadcast")
    if q.from_user.id != ADMIN_ID:
        return await q.answer("Admin only", show_alert=True)
    await q.answer()
    eligible = users_col.count_documents({"broadcast_opt_out": {"$ne": True}, "broadcast_blocked": {"$ne": True}})
    opted = users_col.count_documents({"broadcast_opt_out": True})
    blocked = users_col.count_documents({"broadcast_blocked": True})
    recent = list(broadcasts_col.find({}, {"_id": 0, "message": 0}).sort("created_at", -1).limit(5))
    hist = "\n".join(
        f"• {html_escape(str(x.get('preview') or 'Broadcast')[:42])} — {int(x.get('sent',0))} sent / {int(x.get('failed',0))} failed"
        for x in recent
    ) or "No broadcasts yet."
    await q.message.answer(
        f"📣 <b>Broadcast Center</b>\n\nEligible: <b>{eligible}</b> • Opted out: <b>{opted}</b> • Unavailable: <b>{blocked}</b>\n\n"
        f"<b>Recent</b>\n{hist}\n\nUse the <b>bottom keyboard</b> to create or refresh broadcasts.",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_credit_help")
async def admin_credit_help(q: CallbackQuery):
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    await q.message.answer("💳 <b>Credit commands</b>\n\n<code>/credit_add USER_ID 100</code>\n<code>/credit_set USER_ID 500</code>", parse_mode="HTML")


@dp.callback_query(F.data == "admin_stock")
async def admin_stock(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "inventory")
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    lines = []
    for p in get_products(False)[:30]:
        state = "🔴" if p["stock"] == 0 else ("🟠" if p["stock"] <= DEFAULT_LOW_STOCK else "🟢")
        lines.append(f"{state} <b>{p['name']}</b> — {p['stock']}")
    await q.message.answer("📦 <b>Inventory</b>\n\n" + ("\n".join(lines) or "No products"), parse_mode="HTML")


def analytics_data():
    now = utcnow()
    all_orders = list(orders_col.find({}, {"_id": 0, "digital_delivery": 0}))
    def within(days):
        cutoff = now - timedelta(days=days)
        rows = [o for o in all_orders if isinstance(o.get("created_at"), datetime) and o["created_at"].replace(tzinfo=o["created_at"].tzinfo or timezone.utc) >= cutoff]
        revenue = sum(int(o.get("total_credits", 0)) for o in rows)
        return {"orders": len(rows), "revenue": revenue, "aov": round(revenue / len(rows), 1) if rows else 0}
    today = within(1)
    week = within(7)
    month = within(30)
    counts = {}
    for o in all_orders:
        for item in o.get("items", []):
            key = item.get("id", "unknown")
            counts[key] = counts.get(key, 0) + int(item.get("qty", 0))
    pnames = {p["id"]: p["name"] for p in get_products(False)}
    best = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:5]
    return {"today": today, "week": week, "month": month, "best": [{"id": k, "name": pnames.get(k, k), "qty": v} for k, v in best]}


@dp.callback_query(F.data == "admin_sales")
async def admin_sales(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "analytics")
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    a = analytics_data()
    best = "\n".join(f"• {html_escape(str(x.get('name') or x.get('id')))} — <b>{int(x.get('qty', 0))} sold</b>" for x in a.get("best", [])) or "No sales yet."
    await q.message.answer(
        "📊 <b>Sales analytics</b>\n\n"
        f"Today: {a['today']['orders']} orders • {money(a['today']['revenue'])} • AOV {a['today']['aov']:,}\n"
        f"7 days: {a['week']['orders']} orders • {money(a['week']['revenue'])} • AOV {a['week']['aov']:,}\n"
        f"30 days: {a['month']['orders']} orders • {money(a['month']['revenue'])} • AOV {a['month']['aov']:,} credits\n\n"
        f"<b>Best sellers</b>\n{best}",
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "admin_customers")
async def admin_customers_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "customers")
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    rows = list(users_col.find({}, {"_id": 0}).sort("last_seen", -1).limit(20))
    text = "\n".join(f"<code>{u['user_id']}</code> — {html_escape(str(u.get('full_name') or '-'))} — <b>{money(u.get('credits', 0))}</b>" for u in rows)
    await q.message.answer("👥 <b>Recent customers</b>\n\n" + (text or "None"), parse_mode="HTML")


@dp.callback_query(F.data == "admin_referrals")
async def admin_referrals_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "referrals")
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    awarded = referrals_col.count_documents({"status": "awarded"})
    pending = referrals_col.count_documents({"status": "pending_join"})
    await q.message.answer(f"🔗 <b>Referrals</b>\n\nAwarded: <b>{awarded}</b>\nPending join: <b>{pending}</b>\nReward: <b>{REFERRAL_CREDIT} credits</b>", parse_mode="HTML")


@dp.callback_query(F.data == "admin_orders")
async def admin_orders_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "orders")
    if q.from_user.id != ADMIN_ID:
        return
    await q.answer()
    rows = list(orders_col.find({}, {"_id": 0, "digital_delivery": 0}).sort("created_at", -1).limit(8))
    if not rows:
        return await q.message.answer("No orders yet.")
    kb = []
    text = []
    for o in rows:
        code = o["order_code"]
        text.append(f"#{code} • <code>{o['user_id']}</code> • {money(o.get('total_credits', 0))} • {html_escape(str(o.get('status') or 'delivered'))}")
        kb.append([
            InlineKeyboardButton(text=f"🧾 View #{code}", callback_data=f"tgo:{code}"),
            InlineKeyboardButton(text="♻️ Resend", callback_data=f"admin_resend:{code}"),
        ])
    kb.append([InlineKeyboardButton(text="🏠 Admin Dashboard", callback_data="admin_menu")])
    await q.message.answer("🧾 <b>Recent orders</b>\n\n" + "\n".join(text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data.startswith("admin_resend:"))
async def admin_resend_cb(q: CallbackQuery):
    await sync_admin_reply_keyboard(q, "orders")
    if q.from_user.id != ADMIN_ID:
        return
    code = q.data.split(":", 1)[1]
    ok, msg = await resend_delivery(code)
    await q.answer(msg, show_alert=not ok)


def build_receipt(order, uid):
    created = order.get("created_at")
    ts = created.astimezone().strftime("%d %b %Y • %I:%M %p") if isinstance(created, datetime) else "Saved order"
    item_lines = []
    pmap = {p["id"]: p for p in get_products(False)}
    for item in order.get("items", []):
        p = pmap.get(item.get("id"), {})
        name = item.get("name") or p.get("name") or item.get("id")
        variant = item.get("variant_label")
        label = f" — {variant}" if variant else ""
        line = f"• {p.get('emoji', '🔑')} <b>{html_escape(str(name))}</b>{html_escape(label)} × {item.get('qty', 1)}"
        if item.get("requested_email"):
            line += f"\n  📧 Subscription email: <code>{html_escape(str(item['requested_email']))}</code>"
        item_lines.append(line)
    return (
        f"🎉 <b>PAYMENT RECEIPT</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>{SHOP_NAME}</b>\nReceipt ID: <code>{order['order_code']}</code>\nDate: <code>{ts}</code>\nCustomer: <code>{uid}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n" + ("\n".join(item_lines) or "Digital order") + "\n"
        f"━━━━━━━━━━━━━━━━━━\n💸 Total: <b>{money(order.get('total_credits', 0))}</b>\n"
        f"Status: <b>{str(order.get('status', 'Delivered')).replace('_', ' ').title()}</b> "
        f"{'✅' if str(order.get('status', 'delivered')) == 'delivered' else '⏳'}"
    )


def order_delivery_plain(order):
    result = []
    for d in order.get("digital_delivery", []):
        items = []
        if d.get("items_enc"):
            items = [decrypt_payload(x) for x in d.get("items_enc", [])]
        elif d.get("items"):
            items = [str(x) for x in d.get("items", [])]
        items = [x for x in items if x]
        result.append({**d, "items": items})
    return result


def build_delivery(order):
    deliveries = order_delivery_plain(order)
    sections = []
    for d in deliveries:
        rendered_items = []
        for i, value in enumerate(d.get("items", [])):
            account = parse_account_inventory_payload(value)
            if account:
                otp_note = ""
                if d.get("otp_enabled"):
                    if account.get("totp_secret"):
                        otp_note = "\n\n🔐 <b>OTP</b>\nUse the button below whenever you need a current OTP."
                    else:
                        otp_note = "\n\n⚠️ OTP is enabled for this product but this item has no valid TOTP secret."
                rendered_items.append(
                    f"<b>Account #{i+1}</b>\n━━━━━━━━━━━━━━━━━━\n"
                    f"{format_visible_credentials(account)}"
                    f"{otp_note}"
                )
            else:
                rendered_items.append(f"{i+1}. <code>{html_escape(str(value))}</code>")
        item_lines = "\n\n".join(rendered_items)
        instructions = (d.get("instructions") or "").strip()
        warranty = (d.get("warranty") or "").strip()
        support_note = (d.get("support_note") or "").strip()
        delivery_note = (d.get("delivery_note") or "").strip()
        extras = []
        if instructions:
            extras.append(f"📘 <b>Instructions</b>\n{html_escape(instructions)}")
        if warranty:
            extras.append(f"🛡 <b>Warranty</b>\n{html_escape(warranty)}")
        if delivery_note:
            extras.append(f"📦 <b>Delivery note</b>\n{html_escape(delivery_note)}")
        if support_note:
            extras.append(f"💬 <b>Support note</b>\n{html_escape(support_note)}")
        if d.get("otp_enabled"):
            extras.append(
                f"🔐 <b>OTP service</b>\n"
                f"Each OTP costs <b>{money(int(d.get('otp_price') or OTP_PRICE))}</b>. "
                f"You are charged only when a valid OTP is generated."
            )
        sections.append(
            f"🎁 <b>{html_escape(d.get('name', 'Digital product'))}</b>\n{item_lines}"
            + (("\n\n" + "\n\n".join(extras)) if extras else "")
        )
    return (
        f"🎊 <b>Your digital order is ready!</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Receipt ID: <code>{html_escape(str(order['order_code']))}</code>\n\n"
        + "\n\n".join(sections)
        + f"\n\n━━━━━━━━━━━━━━━━━━\n🔒 Keep delivery details private."
    )


def build_email_fulfillment_message(order):
    entries = order.get("email_fulfillment") or []
    lines = []
    for d in entries:
        status = str(d.get("status") or "pending")
        status_text = "✅ Fulfilled" if status == "fulfilled" else "⏳ Awaiting setup"
        line = (
            f"📦 <b>{html_escape(str(d.get('name') or 'Subscription'))}</b>\n"
            f"📧 Email: <code>{html_escape(str(d.get('email') or ''))}</code>\n"
            f"Status: <b>{status_text}</b>"
        )
        if d.get("expires_at"):
            expiry = d.get("expires_at")
            if isinstance(expiry, datetime):
                expiry = expiry.astimezone(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
            line += f"\n📅 Expiry: <b>{html_escape(str(expiry))}</b>"
        lines.append(line)
    return (
        f"📧 <b>SUBSCRIPTION SETUP REQUEST</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Receipt ID: <code>{html_escape(str(order.get('order_code','')))}</code>\n\n"
        + "\n\n".join(lines)
        + "\n\n━━━━━━━━━━━━━━━━━━\n"
        + "Your payment is complete. The admin will set up the subscription on the email shown above."
    )



def manual_delivery_plain(entry: dict) -> str:
    enc = entry.get("delivery_enc")
    if enc:
        return decrypt_payload(enc)
    # Legacy compatibility only; new records are always encrypted.
    return str(entry.get("delivery_text") or "")


def build_login_assistance_message(order):
    entries = [x for x in (order.get("manual_fulfillment") or []) if bool(x.get("login_assistance"))]
    if not entries:
        return ""
    lines = []
    for d in entries:
        submitted = bool(d.get("activation_code_submitted"))
        status_text = "✅ Code sent to admin" if submitted else "⏳ Waiting for activation code"
        prompt = str(d.get("activation_prompt") or "Please send the activation code shown by the service.").strip()
        line = (
            f"🔐 <b>{html_escape(str(d.get('name') or 'Product'))}</b> × {int(d.get('qty') or 1)}\n"
            f"Status: <b>{status_text}</b>\n\n"
            f"{html_escape(prompt)}"
        )
        lines.append(line)
    code = str(order.get("order_code") or "")
    rows = []
    if any(not bool(d.get("activation_code_submitted")) for d in entries):
        rows.append([InlineKeyboardButton(text="🔐 Send activation code", callback_data=f"lac:{code}")])
    rows.append([InlineKeyboardButton(text="💬 Contact support", url=f"https://t.me/{OWNER_USERNAME}?text={quote('Hello, I need support for order #'+code)}")]) if OWNER_USERNAME else None
    return (
        f"🔐 <b>ACTIVATION REQUIRED</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Receipt ID: <code>{html_escape(code)}</code>\n\n"
        + "\n\n".join(lines)
        + "\n\n━━━━━━━━━━━━━━━━━━\n"
        + ("Tap <b>Send activation code</b> when you are ready." if any(not bool(d.get("activation_code_submitted")) for d in entries) else "Your activation code has been sent to the admin. Please wait for activation.")
    ), InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_login_assistance_message(target, order):
    text, markup = build_login_assistance_message(order)
    if text:
        await target.answer(text, parse_mode="HTML", reply_markup=markup)


def build_manual_fulfillment_message(order):
    entries = order.get("manual_fulfillment") or []
    lines = []
    for d in entries:
        status = str(d.get("status") or "pending")
        fulfilled = status == "fulfilled"
        status_text = "✅ Fulfilled" if fulfilled else "⏳ Will be fulfilled by request"
        line = (
            f"🛠 <b>{html_escape(str(d.get('name') or 'Requested product'))}</b>"
            f" × {int(d.get('qty') or 1)}\n"
            f"Status: <b>{status_text}</b>"
        )
        if d.get("expires_at"):
            expiry = d.get("expires_at")
            if isinstance(expiry, datetime):
                expiry = expiry.astimezone(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
            line += f"\n📅 Expiry: <b>{html_escape(str(expiry))}</b>"
        if not fulfilled:
            line += "\nThe admin has received your paid request and will prepare and deliver it to you here in Telegram."
        lines.append(line)
    return (
        f"🛠 <b>FULFILLED BY REQUEST</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Receipt ID: <code>{html_escape(str(order.get('order_code','')))}</code>\n\n"
        + "\n\n".join(lines)
        + "\n\n━━━━━━━━━━━━━━━━━━\n"
        + ("All requested items are fulfilled." if entries and all(str(x.get('status')) == 'fulfilled' for x in entries) else "Your payment is complete. This order will be fulfilled by request.")
    )


def build_manual_delivery_message(order: dict, entry: dict) -> str:
    plain = manual_delivery_plain(entry).strip()
    expiry_line = ""
    if entry.get("expires_at"):
        expiry = entry.get("expires_at")
        if isinstance(expiry, datetime):
            expiry = expiry.astimezone(timezone.utc).strftime("%d %b %Y • %H:%M UTC")
        expiry_line = f"\n📅 Expiry: <b>{html_escape(str(expiry))}</b>"
    return (
        f"🎁 <b>YOUR REQUESTED ORDER IS READY</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Receipt: <code>#{html_escape(str(order.get('order_code') or ''))}</code>\n"
        f"Product: <b>{html_escape(str(entry.get('name') or 'Requested product'))}</b>\n"
        f"Quantity: <b>{int(entry.get('qty') or 1)}</b>{expiry_line}\n\n"
        f"<b>Prepared delivery</b>\n<pre>{html_escape(plain)}</pre>\n"
        f"━━━━━━━━━━━━━━━━━━\n🔒 Keep these details private."
    )


METHOD_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

def split_method_text(text: str, limit: int = 3200):
    text = str(text or "").strip()
    if not text:
        return []
    limit = max(500, min(int(limit), 3500))
    chunks = []
    while len(text) > limit:
        cut = max(text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        if cut < max(250, limit // 3):
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks

def telegram_linkify_method_text(text: str):
    raw = str(text or "")
    out = []
    pos = 0
    for match in METHOD_URL_RE.finditer(raw):
        out.append(html_escape(raw[pos:match.start()]))
        token = match.group(0)
        trailing = ""
        while token and token[-1] in ".,;:!?":
            trailing = token[-1] + trailing
            token = token[:-1]
        safe = html_escape(token, quote=True)
        if token:
            out.append(f'<a href="{safe}">{safe}</a>')
        out.append(html_escape(trailing))
        pos = match.end()
    out.append(html_escape(raw[pos:]))
    return "".join(out)

def method_telegram_chunks(text: str):
    pending = split_method_text(text, 2400)
    out = []
    while pending:
        chunk = pending.pop(0)
        rendered = telegram_linkify_method_text(chunk)
        if len(rendered) <= 3300:
            out.append((chunk, rendered))
            continue
        if len(chunk) <= 400:
            # Pathological HTML-heavy input: keep reducing until Telegram's limit is safe.
            half = max(1, len(chunk) // 2)
            pending = [chunk[:half], chunk[half:]] + pending
            continue
        pieces = split_method_text(chunk, max(400, len(chunk) // 2))
        if len(pieces) <= 1:
            half = len(chunk) // 2
            pieces = [chunk[:half], chunk[half:]]
        pending = pieces + pending
    return out

def method_local_image_file(method_id: str, image_url: str):
    image_url = str(image_url or "")
    cover_path = f"/media/method/{method_id}"
    if image_url == cover_path:
        doc = method_images_col.find_one({"method_id": method_id}, {"data": 1, "content_type": 1})
        if doc and doc.get("data"):
            ext = {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(doc.get("content_type"), "jpg")
            return BufferedInputFile(bytes(doc["data"]), filename=f"method-{method_id}.{ext}")
        return None
    prefix = f"/media/method/{method_id}/gallery/"
    if image_url.startswith(prefix):
        gid = image_url[len(prefix):]
        if re.fullmatch(r"[A-Za-z0-9_-]{4,80}", gid or ""):
            doc = method_gallery_col.find_one({"method_id": method_id, "image_id": gid}, {"data": 1, "content_type": 1})
            if doc and doc.get("data"):
                ext = {"image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(doc.get("content_type"), "jpg")
                return BufferedInputFile(bytes(doc["data"]), filename=f"method-{method_id}-{gid}.{ext}")
    return None

async def send_method_delivery(uid: int, method: dict, paid_price: int = 0, balance: int | None = None):
    uid = int(uid)
    title = str(method.get("title") or method.get("id") or "Method")
    body = str(method.get("body") or method.get("summary") or "").strip()
    price_text = "FREE" if int(paid_price or 0) <= 0 else money(int(paid_price))
    header = (
        f"📘 <b>YOUR METHOD IS READY</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Method: <b>{html_escape(title)}</b>\n"
        f"Paid: <b>{html_escape(price_text)}</b>"
        + (f"\nBalance: <b>{money(int(balance))}</b>" if balance is not None else "")
        + "\n\n🔗 Links below are tappable. Long-press the message or URL if you want to copy it."
    )
    await bot.send_message(uid, header, parse_mode="HTML")

    media_values = []
    for image_url in method_all_images(method):
        try:
            media = await asyncio.to_thread(method_local_image_file, str(method.get("id") or ""), image_url)
            if media is None:
                media = image_url if image_url.startswith(("http://", "https://")) else (PUBLIC_URL + image_url if image_url.startswith("/") else image_url)
            if media:
                media_values.append(media)
        except Exception:
            log.exception("Method image preparation failed for %s", method.get("id"))
    if media_values:
        try:
            if len(media_values) == 1:
                await bot.send_photo(uid, media_values[0])
            else:
                await bot.send_media_group(uid, [InputMediaPhoto(media=x) for x in media_values[:10]])
        except Exception:
            # A single bad remote image should not block the Method delivery. Retry items separately.
            log.exception("Method media group delivery failed for %s; retrying separately", method.get("id"))
            for media in media_values:
                try:
                    await bot.send_photo(uid, media)
                except Exception:
                    log.exception("Method image delivery failed for %s", method.get("id"))

    rendered_chunks = method_telegram_chunks(body) if body else [("No method content was provided.", "No method content was provided.")]
    if len(rendered_chunks) <= 5:
        for index, (_plain, rendered) in enumerate(rendered_chunks, start=1):
            prefix = f"📖 <b>Method content{f' • {index}/{len(rendered_chunks)}' if len(rendered_chunks) > 1 else ''}</b>\n\n"
            await bot.send_message(uid, prefix + rendered, parse_mode="HTML")
    else:
        await bot.send_message(
            uid,
            "📄 <b>This Method is long.</b> The complete Method is attached as a text file below; its links are also sent separately for easy tapping/copying.",
            parse_mode="HTML",
        )
        filename = (slugify(title) or "method")[:70] + ".txt"
        await bot.send_document(
            uid,
            BufferedInputFile(body.encode("utf-8"), filename=filename),
            caption=f"📘 {title[:900]}",
        )

    urls = []
    for match in METHOD_URL_RE.finditer(body):
        url = match.group(0).rstrip(".,;:!?")
        if url and url not in urls:
            urls.append(url)
    if urls:
        link_messages = []
        current = []
        current_len = 0
        for number, url in enumerate(urls[:30], start=1):
            safe = html_escape(url, quote=True)
            line = f'{number}. <a href="{safe}">{safe}</a>'
            if current and current_len + len(line) + 1 > 3000:
                link_messages.append("\n".join(current)); current = []; current_len = 0
            current.append(line); current_len += len(line) + 1
        if current:
            link_messages.append("\n".join(current))
        for block in link_messages:
            await bot.send_message(uid, "🔗 <b>Method links</b>\n" + block, parse_mode="HTML")
        copy_block = "\n".join(urls[:30])
        for chunk in split_method_text(copy_block, 2800):
            await bot.send_message(uid, "📋 <b>Copyable links</b>\n<pre>" + html_escape(chunk) + "</pre>", parse_mode="HTML")

async def resend_delivery(code):
    order = orders_col.find_one({"order_code": code})
    if not order:
        return False, "Order not found"
    try:
        await bot.send_message(int(order["user_id"]), build_receipt(order, int(order["user_id"])), parse_mode="HTML", reply_markup=support_markup(code))
        if order.get("digital_delivery"):
            await bot.send_message(int(order["user_id"]), build_delivery(order), parse_mode="HTML", reply_markup=delivery_markup(order))
        if order.get("email_fulfillment"):
            await bot.send_message(int(order["user_id"]), build_email_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
        if order.get("manual_fulfillment"):
            await bot.send_message(int(order["user_id"]), build_manual_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
            for entry in order.get("manual_fulfillment") or []:
                if str(entry.get("status") or "pending") == "fulfilled" and manual_delivery_plain(entry).strip():
                    await bot.send_message(int(order["user_id"]), build_manual_delivery_message(order, entry), parse_mode="HTML", reply_markup=support_markup(code))
        orders_col.update_one({"_id": order["_id"]}, {"$set": {"last_resent_at": utcnow()}, "$inc": {"resend_count": 1}})
        return True, "Delivery resent ✅"
    except Exception as exc:
        return False, f"Telegram send failed: {exc}"


async def maybe_low_stock_alert(product_ids):
    for pid in set(product_ids):
        p = products_col.find_one({"id": pid})
        if not p:
            continue
        if str(p.get("fulfillment_mode") or "instant") != "instant":
            continue
        for v in normalize_variants(p):
            stock = digital_inventory_col.count_documents({"product_id": pid, "variant_id": v["id"], "sold": False})
            if v["id"] == "default":
                stock += digital_inventory_col.count_documents({"product_id": pid, "variant_id": {"$exists": False}, "sold": False})
            field = f"low_alert.{v['id']}"
            active = bool((p.get("low_alert") or {}).get(v["id"], False))
            if stock <= v["low_stock"] and not active:
                products_col.update_one({"id": pid}, {"$set": {field: True}})
                try:
                    await bot.send_message(ADMIN_ID, f"⚠️ <b>Low stock</b>\n{p['name']} — {v['label']}\nAvailable: <b>{stock}</b>\nThreshold: {v['low_stock']}", parse_mode="HTML")
                except Exception:
                    pass
            elif stock > v["low_stock"] and active:
                products_col.update_one({"id": pid}, {"$set": {field: False}})


async def notify_restock(product_id, before_stock, after_stock):
    if before_stock != 0 or after_stock <= 0:
        return
    p = products_col.find_one({"id": product_id}, {"_id": 0, "name": 1, "emoji": 1}) or {"name": product_id, "emoji": "🔑"}
    watchers = list(wishlists_col.find({"product_id": product_id}, {"_id": 0, "user_id": 1}).limit(500))
    for w in watchers:
        uid = int(w["user_id"])
        if not await user_is_member(uid):
            continue
        try:
            await bot.send_message(uid, f"🔔 <b>Back in stock!</b>\n\n{p.get('emoji','🔑')} <b>{p['name']}</b> is available again.", parse_mode="HTML", reply_markup=fresh_shop_markup(uid))
        except Exception:
            pass


class OrderValidationError(Exception):
    pass


MAX_CART_LINES = 50
MAX_PURCHASE_KEY_LENGTH = 128
PURCHASE_KEY_FAILURE_LIMIT = 8
PURCHASE_KEY_FAILURE_WINDOW_MINUTES = 15


def check_purchase_key_rate(uid: int, product_id: str):
    cutoff = utcnow() - timedelta(minutes=PURCHASE_KEY_FAILURE_WINDOW_MINUTES)
    failures = purchase_key_attempts_col.count_documents({
        "user_id": int(uid), "product_id": str(product_id), "created_at": {"$gte": cutoff}
    })
    if failures >= PURCHASE_KEY_FAILURE_LIMIT:
        raise OrderValidationError(
            f"Too many incorrect key attempts for this product. Try again in {PURCHASE_KEY_FAILURE_WINDOW_MINUTES} minutes."
        )


def record_purchase_key_failure(uid: int, product_id: str):
    now = utcnow()
    purchase_key_attempts_col.insert_one({
        "user_id": int(uid), "product_id": str(product_id), "created_at": now,
        "expires_at": now + timedelta(minutes=PURCHASE_KEY_FAILURE_WINDOW_MINUTES + 5),
    })


def clear_purchase_key_failures(uid: int, product_id: str):
    purchase_key_attempts_col.delete_many({"user_id": int(uid), "product_id": str(product_id)})


def prepare_order_payload(payload, uid: int | None = None):
    """Server-authoritative cart validation shared by Mini App preflight and Telegram checkout."""
    if not isinstance(payload, dict):
        raise OrderValidationError("Invalid order payload.")
    if uid is not None:
        restriction = purchase_restriction_message(int(uid))
        if restriction:
            raise OrderValidationError(restriction)
    purchase_keys = payload.get("purchase_keys") or {}
    requested_emails = payload.get("emails") or {}
    if not isinstance(purchase_keys, dict) or not isinstance(requested_emails, dict):
        raise OrderValidationError("Invalid checkout requirements.")

    raw_items = payload.get("items", [])
    if not isinstance(raw_items, list) or len(raw_items) > MAX_CART_LINES:
        raise OrderValidationError(f"Cart may contain at most {MAX_CART_LINES} product lines.")
    if not raw_items:
        raise OrderValidationError("Cart is empty or invalid.")

    # Load only products that are actually in this cart. The old path built the complete storefront
    # (including a full inventory aggregation) even for a one-item checkout.
    requested_ids = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise OrderValidationError("Invalid cart item.")
        pid = str(raw.get("id", ""))
        if pid and pid not in requested_ids:
            requested_ids.append(pid)
    pmap = {
        str(p.get("id")): p
        for p in products_col.find(
            {"id": {"$in": requested_ids}, "active": True, "delivery_type": "digital"},
            {"_id": 0},
        )
    }

    normalized = []
    total = 0
    seen_lines = set()

    for raw in raw_items:
        p = pmap.get(str(raw.get("id", "")))
        if not p:
            raise OrderValidationError("A product in your cart is no longer available.")
        qty = raw.get("qty", 0)
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise OrderValidationError("Quantity must be a whole number.")
        if qty < 1 or qty > 20:
            raise OrderValidationError(f"Invalid quantity for {p.get('name', 'product')}.")

        variant = variant_for(p, str(raw.get("variant_id") or "default"))
        if not variant:
            raise OrderValidationError(f"Variant not found for {p.get('name', 'product')}.")
        line_key = f"{p['id']}:{variant['id']}"
        if line_key in seen_lines:
            raise OrderValidationError("Duplicate cart line detected. Reopen the shop and try again.")
        seen_lines.add(line_key)

        if bool(p.get("purchase_key_required", False)):
            if not p.get("purchase_key_hash"):
                raise OrderValidationError(f"{p['name']} is locked but no purchase key is configured. Contact the admin.")
            supplied = str(purchase_keys.get(p["id"], ""))
            if len(supplied) > MAX_PURCHASE_KEY_LENGTH:
                raise OrderValidationError(f"Invalid purchase key for {p['name']}.")
            if not supplied.strip():
                raise OrderValidationError(f"Special purchase key required for {p['name']}.")
            if uid is not None:
                check_purchase_key_rate(uid, p["id"])
            if not purchase_key_matches(p, supplied):
                if uid is not None:
                    record_purchase_key_failure(uid, p["id"])
                raise OrderValidationError(f"Incorrect special purchase key for {p['name']}.")
            if uid is not None:
                clear_purchase_key_failures(uid, p["id"])

        fulfillment_mode = str(p.get("fulfillment_mode") or "instant")
        if fulfillment_mode not in {"instant", "email", "manual", "login_assist"}:
            raise OrderValidationError(f"Invalid fulfillment mode for {p.get('name', 'product')}. Contact the admin.")
        email = ""
        if fulfillment_mode == "login_assist" and qty != 1:
            raise OrderValidationError(f"{p['name']} can only be purchased one at a time.")
        if fulfillment_mode == "email":
            if qty != 1:
                raise OrderValidationError(f"{p['name']} can only be purchased one at a time because it requires an email setup.")
            email = str(requested_emails.get(line_key, "")).strip()
            if not valid_email_address(email):
                raise OrderValidationError(f"Enter a valid subscription email for {p['name']} — {variant['label']}.")

        unit_price = int(variant["price"])
        if unit_price < 0 or unit_price > 1_000_000_000:
            raise OrderValidationError(f"Invalid server price for {p.get('name', 'product')}. Contact the admin.")
        line = unit_price * qty
        normalized.append({
            "product": p,
            "variant": variant,
            "qty": qty,
            "line": line,
            "line_key": line_key,
            "fulfillment_mode": fulfillment_mode,
            "email": email,
        })
        total += line

    # One grouped inventory query checks every instant-delivery line, including legacy default stock.
    instant = [entry for entry in normalized if entry["fulfillment_mode"] == "instant"]
    if instant:
        ids = list({str(entry["product"]["id"]) for entry in instant})
        counts = {}
        for row in digital_inventory_col.aggregate([
            {"$match": {"sold": False, "product_id": {"$in": ids}}},
            {"$group": {
                "_id": {"product_id": "$product_id", "variant_id": {"$ifNull": ["$variant_id", "__legacy__"]}},
                "count": {"$sum": 1},
            }},
        ]):
            key = (str(row.get("_id", {}).get("product_id") or ""), str(row.get("_id", {}).get("variant_id") or "__legacy__"))
            counts[key] = int(row.get("count", 0))
        for entry in instant:
            p, variant, qty = entry["product"], entry["variant"], entry["qty"]
            available = counts.get((str(p["id"]), str(variant["id"])), 0)
            if variant["id"] == "default":
                available += counts.get((str(p["id"]), "__legacy__"), 0)
            if available < qty:
                raise OrderValidationError(f"Out of stock: {p['name']} — {variant['label']}.")

    return normalized, total


def charge_order(uid, code, normalized, total, telegram_event_id: str = ""):
    uid = int(uid)
    with mongo_client.start_session() as session:
        def txn(sess):
            user = users_col.find_one({"user_id": uid}, session=sess)
            if user and (bool(user.get("suspended", False)) or bool(user.get("purchase_blocked", False))):
                raise PermissionError("PURCHASE_BLOCKED")
            bal = int(user.get("credits", 0)) if user else 0
            if bal < total:
                raise ValueError("INSUFFICIENT")

            deliveries = []
            email_fulfillment = []
            manual_fulfillment = []
            items = []
            purchased_at = utcnow()

            for item_index, entry in enumerate(normalized):
                p = entry["product"]
                variant = entry["variant"]
                qty = entry["qty"]
                fulfillment_mode = entry["fulfillment_mode"]

                item_record = {
                    "id": p["id"], "name": p["name"], "variant_id": variant["id"],
                    "variant_label": variant["label"], "qty": qty,
                    "unit_price": variant["price"], "fulfillment_mode": fulfillment_mode,
                }

                if fulfillment_mode == "email":
                    email = entry["email"]
                    item_record["requested_email"] = email
                    email_fulfillment.append({
                        "item_index": item_index,
                        "product_id": p["id"],
                        "name": f"{p['name']} — {variant['label']}",
                        "variant_id": variant["id"],
                        "variant_label": variant["label"],
                        "email": email,
                        "status": "pending",
                        "subscription_days": max(0, int(variant.get("subscription_days", 0) or 0)),
                        "reminder_note": str(p.get("reminder_note") or ""),
                        "requested_at": purchased_at,
                    })
                    items.append(item_record)
                    continue

                if fulfillment_mode in {"manual", "login_assist"}:
                    item_record["fulfilled_by_request"] = True
                    item_record["login_assistance"] = fulfillment_mode == "login_assist"
                    manual_fulfillment.append({
                        "item_index": item_index,
                        "product_id": p["id"],
                        "name": f"{p['name']} — {variant['label']}",
                        "variant_id": variant["id"],
                        "variant_label": variant["label"],
                        "qty": qty,
                        "status": "pending",
                        "subscription_days": max(0, int(variant.get("subscription_days", 0) or 0)),
                        "reminder_note": str(p.get("reminder_note") or ""),
                        "instructions": str(p.get("instructions") or ""),
                        "activation_prompt": str(p.get("activation_prompt") or "Please send the activation code shown by the service.") if fulfillment_mode == "login_assist" else "",
                        "login_assistance": fulfillment_mode == "login_assist",
                        "warranty": str(p.get("warranty") or ""),
                        "support_note": str(p.get("support_note") or ""),
                        "delivery_note": str(p.get("delivery_note") or ""),
                        "requested_at": purchased_at,
                    })
                    items.append(item_record)
                    continue

                claimed_enc = []
                for _ in range(qty):
                    query = {"product_id": p["id"], "sold": False, "variant_id": variant["id"]}
                    stock_item = digital_inventory_col.find_one_and_update(
                        query,
                        {"$set": {"sold": True, "sold_to": uid, "order_code": code, "sold_at": purchased_at}},
                        session=sess,
                        return_document=ReturnDocument.AFTER,
                    )
                    if not stock_item and variant["id"] == "default":
                        stock_item = digital_inventory_col.find_one_and_update(
                            {"product_id": p["id"], "sold": False, "variant_id": {"$exists": False}},
                            {"$set": {"sold": True, "sold_to": uid, "order_code": code, "sold_at": purchased_at, "variant_id": "default"}},
                            session=sess,
                            return_document=ReturnDocument.AFTER,
                        )
                    if not stock_item:
                        raise RuntimeError(f"OUT_OF_STOCK:{p['name']} — {variant['label']}")
                    enc = stock_item.get("payload_enc") or encrypt_payload(str(stock_item.get("value", "")))
                    claimed_enc.append(enc)

                items.append(item_record)
                deliveries.append({
                    "product_id": p["id"], "name": f"{p['name']} — {variant['label']}", "items_enc": claimed_enc,
                    "instructions": p.get("instructions", ""), "warranty": p.get("warranty", ""),
                    "support_note": p.get("support_note", ""), "delivery_note": p.get("delivery_note", ""),
                    "otp_enabled": bool(p.get("otp_enabled", False)),
                    "otp_price": int(p.get("otp_price") or OTP_PRICE),
                })

                subscription_days = max(0, int(variant.get("subscription_days", 0) or 0))
                if subscription_days > 0:
                    expiry = purchased_at + timedelta(days=subscription_days)
                    reminder = reminder_document(
                        reminder_id=f"order:{code}:{item_index}",
                        title=f"{p['name']} — {variant['label']}",
                        expires_at=expiry,
                        source="order",
                        custom_message=str(p.get("reminder_note") or ""),
                        product_id=p["id"], product_name=p["name"],
                        order_code=code, item_index=item_index, user_id=uid,
                    )
                    subscription_reminders_col.update_one(
                        {"reminder_id": reminder["reminder_id"]},
                        {"$setOnInsert": reminder}, upsert=True, session=sess,
                    )

            result = users_col.update_one(
                {"user_id": uid, "credits": {"$gte": total}},
                {"$inc": {"credits": -int(total)}}, session=sess,
            )
            if result.modified_count != 1:
                raise ValueError("INSUFFICIENT")

            has_pending = bool(email_fulfillment or manual_fulfillment)
            order_status = "partially_delivered" if has_pending and deliveries else ("awaiting_fulfillment" if has_pending else "delivered")

            order = {
                "order_code": code, "user_id": uid, "items": items, "total_credits": int(total),
                "digital_delivery": deliveries, "email_fulfillment": email_fulfillment,
                "manual_fulfillment": manual_fulfillment,
                "status": order_status, "created_at": purchased_at, "resend_count": 0,
            }
            if telegram_event_id:
                order["telegram_event_id"] = str(telegram_event_id)[:120]
            orders_col.insert_one(order, session=sess)
            credit_log_col.insert_one({
                "user_id": uid, "amount": -int(total), "action": "purchase", "admin_id": None,
                "note": f"Order #{code}", "created_at": purchased_at,
            }, session=sess)
            return {"balance": bal - int(total), "order": order}
        return session.with_transaction(txn)


@dp.callback_query(F.data.startswith("paidotp:"))
async def paid_otp_callback(q: CallbackQuery):
    if not await gate_callback(q):
        return

    try:
        _, code, di_raw, ii_raw = q.data.split(":", 3)
        di = int(di_raw)
        ii = int(ii_raw)
    except Exception:
        return await q.answer("Invalid OTP request.", show_alert=True)

    order = orders_col.find_one({"order_code": code})
    if not order or int(order.get("user_id", 0)) != q.from_user.id:
        return await q.answer("This OTP does not belong to your account.", show_alert=True)

    deliveries = order.get("digital_delivery") or []
    if di < 0 or di >= len(deliveries):
        return await q.answer("OTP delivery not found.", show_alert=True)

    delivery = deliveries[di]
    if not delivery.get("otp_enabled"):
        return await q.answer("OTP is not enabled for this product.", show_alert=True)

    encrypted_items = delivery.get("items_enc") or []
    legacy_items = delivery.get("items") or []
    item_count = max(len(encrypted_items), len(legacy_items))
    if ii < 0 or ii >= item_count:
        return await q.answer("Account item not found.", show_alert=True)

    raw_payload = (
        decrypt_payload(encrypted_items[ii])
        if ii < len(encrypted_items)
        else str(legacy_items[ii])
    )
    parsed = split_otp_inventory_payload(raw_payload)
    if not parsed:
        return await q.answer("OTP is not configured correctly for this account.", show_alert=True)

    visible, secret = parsed
    price = max(1, int(delivery.get("otp_price") or OTP_PRICE))

    # Validate the TOTP secret before creating a pending request.
    try:
        generate_totp(secret)
    except ValueError:
        return await q.answer("OTP secret is invalid.", show_alert=True)

    # Prevent multiple clicks from creating multiple pending/charged OTP requests.
    pending = otp_events_col.find_one({
        "user_id": q.from_user.id,
        "order_code": code,
        "delivery_index": di,
        "item_index": ii,
        "status": "pending",
        "created_at": {"$gte": utcnow() - timedelta(seconds=40)},
    })
    if pending:
        return await q.answer(
            "A fresh OTP is already being prepared for this account.",
            show_alert=True,
        )

    request_id = secrets.token_hex(12)
    otp_events_col.insert_one({
        "request_id": request_id,
        "user_id": q.from_user.id,
        "order_code": code,
        "delivery_index": di,
        "item_index": ii,
        "price": price,
        "status": "pending",
        "created_at": utcnow(),
    })

    # A standard TOTP changes every 30 seconds. Wait for the NEXT boundary instead
    # of returning a code that may already have only a few seconds left.
    now_float = time.time()
    phase = now_float % 30.0
    wait_seconds = 30.0 - phase + 0.08

    await q.answer("Preparing a fresh OTP…", show_alert=False)

    countdown_msg = None
    try:
        # Show a visible countdown while waiting for the next fresh 30-second TOTP cycle.
        # Update every few seconds (and every second for the final 3 seconds) to avoid
        # excessive Telegram edit requests while still giving the customer a clear timer.
        total_wait = max(1, int(math.ceil(wait_seconds)))
        countdown_msg = await q.message.answer(
            f"⏳ <b>Fresh OTP timer</b>\n\n"
            f"Your OTP will arrive in approximately <b>{total_wait}s</b>.\n"
            f"We are waiting for a new 30-second OTP cycle so you receive a full-validity code.",
            parse_mode="HTML",
        )

        started = time.monotonic()
        last_shown = total_wait
        while True:
            elapsed = time.monotonic() - started
            left = max(0, int(math.ceil(wait_seconds - elapsed)))
            if left <= 0:
                break

            # Coarser updates above 3 seconds; live final 3-second countdown.
            if left <= 3 or left % 5 == 0:
                if left != last_shown:
                    try:
                        await countdown_msg.edit_text(
                            f"⏳ <b>Fresh OTP timer</b>\n\n"
                            f"OTP arrives in <b>{left}s</b>…",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                    last_shown = left

            await asyncio.sleep(min(1.0, max(0.05, wait_seconds - elapsed)))

        otp_code, remaining = generate_totp(secret)

        # Normally this will be 30 (or 29 if scheduler latency crosses a second).
        # If it somehow landed too late in the cycle, wait once more for a truly
        # fresh cycle rather than charging for a short-lived code.
        if remaining < 29:
            extra_wait = float(remaining) + 0.08
            await asyncio.sleep(extra_wait)
            otp_code, remaining = generate_totp(secret)

        with mongo_client.start_session() as session:
            def txn(sess):
                user = users_col.find_one(
                    {"user_id": q.from_user.id},
                    session=sess,
                ) or {}
                balance = int(user.get("credits", 0))
                if balance < price:
                    raise ValueError("INSUFFICIENT")

                result = users_col.update_one(
                    {"user_id": q.from_user.id, "credits": {"$gte": price}},
                    {"$inc": {"credits": -price}},
                    session=sess,
                )
                if result.modified_count != 1:
                    raise ValueError("INSUFFICIENT")

                otp_events_col.update_one(
                    {"request_id": request_id, "status": "pending"},
                    {"$set": {
                        "status": "generated",
                        "generated_at": utcnow(),
                        "remaining_seconds": int(remaining),
                    }},
                    session=sess,
                )

                credit_log_col.insert_one({
                    "user_id": q.from_user.id,
                    "amount": -price,
                    "action": "otp_generation",
                    "admin_id": None,
                    "note": f"OTP for order #{code}",
                    "created_at": utcnow(),
                }, session=sess)

                return balance - price

            try:
                new_balance = session.with_transaction(txn)
            except ValueError:
                otp_events_col.update_one(
                    {"request_id": request_id},
                    {"$set": {"status": "failed_insufficient", "finished_at": utcnow()}},
                )
                return await q.message.answer(
                    f"❌ Not enough credits. OTP costs <b>{money(price)}</b>.",
                    parse_mode="HTML",
                    reply_markup=buy_credit_markup(q.from_user.id),
                )

        repeat_markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔄 Get Fresh OTP — {price} credits",
                    callback_data=f"paidotp:{code}:{di}:{ii}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔐 Choose another order",
                    callback_data="menu_otp",
                )
            ],
        ])

        shown_remaining = 30 if remaining >= 29 else remaining
        if countdown_msg:
            try:
                await countdown_msg.edit_text(
                    "✅ <b>Fresh OTP ready!</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await q.message.answer(
            f"🔐 <b>Fresh OTP Generated</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Order: <code>#{html_escape(code)}</code>\n"
            f"{format_visible_credentials(visible)}\n\n"
            f"🔢 OTP: <code>{otp_code}</code>\n"
            f"⏳ Validity: about <b>{shown_remaining} seconds</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💳 Charged: <b>{money(price)}</b>\n"
            f"💰 Remaining: <b>{money(new_balance)}</b>\n\n"
            f"Each new OTP is charged separately.",
            parse_mode="HTML",
            reply_markup=repeat_markup,
        )

    except Exception:
        otp_events_col.update_one(
            {"request_id": request_id, "status": "pending"},
            {"$set": {"status": "failed", "finished_at": utcnow()}},
        )
        log.exception("Fresh OTP generation failed")
        await q.message.answer(
            "❌ OTP generation failed. You were not charged for this request."
        )


async def send_existing_order_result(m: Message, order):
    """Replay the receipt/delivery without charging when Telegram retries the same WebApp update."""
    code = str(order.get("order_code") or "")
    await m.answer(build_receipt(order, m.from_user.id), parse_mode="HTML", reply_markup=support_markup(code))
    if order.get("digital_delivery"):
        await m.answer(build_delivery(order), parse_mode="HTML", reply_markup=delivery_markup(order))
    if order.get("email_fulfillment"):
        await m.answer(build_email_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
    if order.get("manual_fulfillment"):
        await m.answer(build_manual_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
        if any(bool(x.get("login_assistance")) for x in (order.get("manual_fulfillment") or [])):
            await send_login_assistance_message(m, order)
        for entry in order.get("manual_fulfillment") or []:
            if str(entry.get("status") or "pending") == "fulfilled" and manual_delivery_plain(entry).strip():
                await m.answer(build_manual_delivery_message(order, entry), parse_mode="HTML", reply_markup=support_markup(code))


@dp.message(F.web_app_data)
async def web_order(m: Message):
    if not await gate_message(m):
        return
    telegram_event_id = f"{int(m.chat.id)}:{int(m.message_id)}"
    existing_order = orders_col.find_one({"telegram_event_id": telegram_event_id})
    if existing_order:
        return await send_existing_order_result(m, existing_order)
    try:
        payload = json.loads(m.web_app_data.data)
    except Exception:
        return await m.answer("❌ Invalid shop data.")
    if not isinstance(payload, dict) or payload.get("type") != "order":
        return

    try:
        normalized, total = prepare_order_payload(payload, m.from_user.id)
    except OrderValidationError as exc:
        return await m.answer(f"❌ {html_escape(str(exc))}", parse_mode="HTML")

    code = secrets.token_hex(6).upper()
    try:
        purchase = charge_order(m.from_user.id, code, normalized, total, telegram_event_id)
    except PermissionError:
        return await m.answer("🚫 Product purchases are currently disabled for your account. Contact support for help.")
    except ValueError:
        bal = get_balance(m.from_user.id)
        return await m.answer(
            f"❌ <b>Not enough credits</b>\nNeed: <b>{money(total)}</b>\nBalance: <b>{money(bal)}</b>",
            parse_mode="HTML",
        )
    except RuntimeError as exc:
        return await m.answer("❌ " + html_escape(str(exc).replace("OUT_OF_STOCK:", "Out of stock: ")), parse_mode="HTML")
    except DuplicateKeyError:
        existing_order = orders_col.find_one({"telegram_event_id": telegram_event_id})
        if existing_order:
            return await send_existing_order_result(m, existing_order)
        raise

    order = purchase["order"]
    await m.answer(build_receipt(order, m.from_user.id), parse_mode="HTML", reply_markup=support_markup(code))
    if order.get("digital_delivery"):
        await m.answer(build_delivery(order), parse_mode="HTML", reply_markup=delivery_markup(order))
    if order.get("email_fulfillment"):
        await m.answer(build_email_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
    if order.get("manual_fulfillment"):
        await m.answer(build_manual_fulfillment_message(order), parse_mode="HTML", reply_markup=support_markup(code))
    if any(bool(x.get("login_assistance")) for x in (order.get("manual_fulfillment") or [])):
        await send_login_assistance_message(m, order)

    await maybe_low_stock_alert([x["product"]["id"] for x in normalized if x["fulfillment_mode"] == "instant"])
    try:
        email_pending = order.get("email_fulfillment") or []
        manual_pending = order.get("manual_fulfillment") or []
        details = []
        details.extend(
            f"📧 {html_escape(d.get('name','Subscription'))}: <code>{html_escape(d.get('email',''))}</code>"
            for d in email_pending
        )
        details.extend(
            (f"🔐 ACTIVATION REQUEST: {html_escape(d.get('name','Product'))} × {int(d.get('qty') or 1)}"
             f" • Code submitted: {'YES' if d.get('activation_code_submitted') else 'NO'}")
            if d.get('login_assistance') else
            f"🛠 REQUESTED: {html_escape(d.get('name','Product'))} × {int(d.get('qty') or 1)}"
            for d in manual_pending
        )
        pending_text = ("\n" + "\n".join(details)) if details else ""
        buttons = []
        if manual_pending:
            buttons.append([InlineKeyboardButton(text="🛠 Prepare & deliver request", callback_data=f"amv:{code}:0")])
        if email_pending:
            buttons.append([InlineKeyboardButton(text="📧 Fulfill email subscription", callback_data=f"aev:{code}:0")])
        if buttons:
            buttons.append([InlineKeyboardButton(text="🧾 Open order", callback_data=f"tgo:{code}")])
        admin_order_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        await bot.send_message(
            ADMIN_ID,
            f"🛒 <b>NEW PAID ORDER #{code}</b>\n👤 {html_escape(m.from_user.full_name)}\n🆔 <code>{m.from_user.id}</code>\n💳 {money(total)}{pending_text}",
            parse_mode="HTML",
            reply_markup=admin_order_markup,
        )
    except Exception:
        pass


def admin_session_token():
    ts = int(time.time())
    nonce = secrets.token_hex(8)
    body = f"{ts}.{nonce}"
    sig = hmac.new((ADMIN_PASSWORD + "|" + WEBHOOK_SECRET).encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def admin_ok(request: Request):
    token = request.cookies.get("shop_admin", "")
    try:
        ts_s, nonce, sig = token.split(".", 2)
        ts = int(ts_s)
        if int(time.time()) - ts > ADMIN_SESSION_HOURS * 3600 or ts > int(time.time()) + 60:
            return False
        body = f"{ts}.{nonce}"
        expected = hmac.new((ADMIN_PASSWORD + "|" + WEBHOOK_SECRET).encode(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def require_admin(request):
    if not admin_ok(request):
        raise HTTPException(401, "Admin login required")
    # SameSite cookies already stop normal CSRF. These checks add defense-in-depth
    # without changing same-origin Admin Panel behavior.
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if str(request.headers.get("sec-fetch-site") or "").lower() == "cross-site":
            raise HTTPException(403, "Cross-site admin request blocked")
        origin = str(request.headers.get("origin") or "").strip().rstrip("/")
        if origin and PUBLIC_URL and origin != PUBLIC_URL:
            raise HTTPException(403, "Invalid admin request origin")


def client_ip(request):
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.client.host if request.client else "unknown")[:120]


def check_login_rate(request):
    ip = client_ip(request)
    cutoff = utcnow() - timedelta(minutes=15)
    attempts = login_attempts_col.count_documents({"ip": ip, "created_at": {"$gte": cutoff}})
    global_attempts = login_attempts_col.count_documents({"created_at": {"$gte": cutoff}})
    if attempts >= 5 or global_attempts >= 50:
        raise HTTPException(429, "Too many login attempts. Try again in 15 minutes.")
    return ip


def record_login_failure(ip):
    login_attempts_col.insert_one({"ip": ip, "created_at": utcnow(), "expires_at": utcnow() + timedelta(minutes=20)})


def parse_variants(text, base_price, default_subscription_days=0):
    out = []
    default_subscription_days = max(0, int(default_subscription_days or 0))
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [x.strip() for x in raw.split("|")]
        label = parts[0]
        try:
            price = int(parts[1]) if len(parts) > 1 and parts[1] else int(base_price)
            low = int(parts[2]) if len(parts) > 2 and parts[2] else DEFAULT_LOW_STOCK
            subscription_days = int(parts[3]) if len(parts) > 3 and parts[3] else default_subscription_days
        except Exception:
            raise HTTPException(400, f"Invalid variant line: {raw}. Use Label|Price|LowStock|SubscriptionDays")
        if not label or len(label) > 120:
            raise HTTPException(400, "Variant label must be 1–120 characters")
        if price < 0 or price > 1_000_000_000:
            raise HTTPException(400, f"Invalid price for variant: {label}")
        out.append({
            "id": slugify(label), "label": label, "price": price,
            "low_stock": max(0, low), "subscription_days": max(0, subscription_days),
        })
    if not out:
        out = [{
            "id": "default", "label": "Standard", "price": int(base_price),
            "low_stock": DEFAULT_LOW_STOCK, "subscription_days": default_subscription_days,
        }]
    # avoid duplicate IDs
    seen = set()
    for v in out:
        if v["id"] in seen:
            raise HTTPException(400, f"Duplicate variant: {v['label']}")
        seen.add(v["id"])
    return out


def parse_inventory_lines(text, variants):
    by_label = {v["label"].lower(): v["id"] for v in variants}
    by_id = {v["id"].lower(): v["id"] for v in variants}
    default_id = variants[0]["id"]
    items = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        variant_id = default_id
        payload = raw
        if "|" in raw and len(variants) > 1:
            left, rest = raw.split("|", 1)
            key = left.strip().lower()
            if key in by_label or key in by_id:
                variant_id = by_label.get(key) or by_id.get(key)
                payload = rest.strip()
        if payload:
            items.append((variant_id, payload))
    return items


def product_total_stock(pid):
    return digital_inventory_col.count_documents({"product_id": pid, "sold": False})


def customer_restrictions(uid: int) -> dict:
    doc = users_col.find_one(
        {"user_id": int(uid)},
        {"_id": 0, "purchase_blocked": 1, "methods_blocked": 1, "suspended": 1},
    ) or {}
    return {
        "purchase_blocked": bool(doc.get("purchase_blocked", False)),
        "methods_blocked": bool(doc.get("methods_blocked", False)),
        "suspended": bool(doc.get("suspended", False)),
    }


def purchase_restriction_message(uid: int) -> str:
    flags = customer_restrictions(uid)
    if flags["suspended"]:
        return "Your purchasing access is temporarily suspended. Contact support if you think this is a mistake."
    if flags["purchase_blocked"]:
        return "Product purchases are temporarily disabled for your account. Contact support for help."
    return ""


def methods_restriction_message(uid: int) -> str:
    flags = customer_restrictions(uid)
    if flags["suspended"]:
        return "Your purchasing access is temporarily suspended. Contact support if you think this is a mistake."
    if flags["methods_blocked"]:
        return "New Method purchases are temporarily disabled for your account."
    return ""


def _as_utc_datetime(value, fallback=None):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value:
        try:
            return parse_datetime_value(value)
        except Exception:
            pass
    return fallback


def fulfillment_requested_at(order: dict, entry: dict) -> datetime:
    fallback = _as_utc_datetime(order.get("created_at"), utcnow())
    return _as_utc_datetime(entry.get("requested_at"), fallback)


def fulfillment_wait_seconds(order: dict, entry: dict, now=None) -> int:
    now = now or utcnow()
    requested = fulfillment_requested_at(order, entry)
    return max(0, int((now - requested).total_seconds()))


def fulfillment_sla_level(order: dict, entry: dict, now=None) -> int:
    seconds = fulfillment_wait_seconds(order, entry, now)
    if seconds >= FULFILLMENT_URGENT_HOURS * 3600:
        return 2
    if seconds >= FULFILLMENT_WARNING_HOURS * 3600:
        return 1
    return 0


def format_wait_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours >= 24:
        days, rem_hours = divmod(hours, 24)
        return f"{days}d {rem_hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def pending_fulfillment_sla_counts(now=None):
    now = now or utcnow()
    warning = urgent = 0
    query = {"$or": [
        {"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
        {"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
    ]}
    for order in orders_col.find(query, {"created_at": 1, "email_fulfillment": 1, "manual_fulfillment": 1}):
        for entry in list(order.get("email_fulfillment") or []) + list(order.get("manual_fulfillment") or []):
            if str(entry.get("status") or "pending") == "fulfilled":
                continue
            level = fulfillment_sla_level(order, entry, now)
            urgent += int(level >= 2)
            warning += int(level == 1)
    return {"warning": warning, "urgent": urgent}


def template_public(doc):
    return {
        "id": str(doc.get("id") or ""),
        "name": str(doc.get("name") or ""),
        "product_id": str(doc.get("product_id") or ""),
        "body": str(doc.get("body") or ""),
        "active": bool(doc.get("active", True)),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def applicable_fulfillment_templates(product_id: str = ""):
    product_id = str(product_id or "")
    docs = fulfillment_templates_col.find(
        {"active": {"$ne": False}, "$or": [{"product_id": ""}, {"product_id": product_id}]},
        {"_id": 0},
    ).sort([("product_id", -1), ("name", 1)])
    return [template_public(x) for x in docs]


def render_fulfillment_template(body: str, order: dict, entry: dict):
    replacements = {
        "order_code": str(order.get("order_code") or ""),
        "customer_id": str(order.get("user_id") or ""),
        "product": str(entry.get("name") or entry.get("product_id") or ""),
        "variant": str(entry.get("variant_label") or ""),
        "email": str(entry.get("email") or ""),
        "qty": str(entry.get("qty") or 1),
    }
    text = str(body or "")
    for key, value in replacements.items():
        text = text.replace("{{" + key + "}}", value)
    return text[:3000]


BACKUP_COLLECTIONS = {
    "users": users_col,
    "products": products_col,
    "orders": orders_col,
    "credit_log": credit_log_col,
    "digital_inventory": digital_inventory_col,
    "settings": settings_col,
    "referrals": referrals_col,
    "wishlists": wishlists_col,
    "methods": methods_col,
    "method_purchases": method_purchases_col,
    "broadcasts": broadcasts_col,
    "subscription_reminders": subscription_reminders_col,
    "fulfillment_templates": fulfillment_templates_col,
}


def build_backup_zip(include_images: bool = False):
    """Compressed Mongo Extended-JSON export. Nothing is written back into MongoDB."""
    collections = dict(BACKUP_COLLECTIONS)
    if include_images:
        collections.update({"product_images": product_images_col, "method_images": method_images_col, "method_gallery": method_gallery_col})
    out = io.BytesIO()
    counts = {}
    created_at = utcnow()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, col in collections.items():
            count = 0
            with zf.open(f"{name}.json", "w") as fh:
                fh.write(b"[\n")
                first = True
                for doc in col.find({}):
                    if not first:
                        fh.write(b",\n")
                    first = False
                    fh.write(json_util.dumps(doc, ensure_ascii=False).encode("utf-8"))
                    count += 1
                fh.write(b"\n]\n")
            counts[name] = count
        manifest = {
            "shop": SHOP_NAME,
            "database": MONGODB_DB,
            "created_at": created_at,
            "format": "MongoDB Extended JSON",
            "encrypted_inventory_preserved": True,
            "includes_images": bool(include_images),
            "collections": counts,
            "note": "Transient login/rate-limit/OTP event collections are intentionally excluded.",
        }
        zf.writestr("MANIFEST.json", json_util.dumps(manifest, indent=2, ensure_ascii=False))
    return out.getvalue(), counts, created_at


def backup_schedule_config():
    value = str(get_setting("auto_backup_schedule", "off") or "off").lower()
    return value if value in {"off", "daily", "weekly"} else "off"


def backup_interval(schedule: str):
    return timedelta(days=1 if schedule == "daily" else 7)


def configure_backup_schedule(schedule: str):
    schedule = str(schedule or "off").lower()
    if schedule not in {"off", "daily", "weekly"}:
        raise ValueError("Backup schedule must be off, daily, or weekly")
    set_setting("auto_backup_schedule", schedule)
    state_value = {"schedule": schedule}
    if schedule != "off":
        # First automatic backup is eligible at the next maintenance/cron check.
        # Future runs advance by the selected interval.
        state_value["next_at"] = utcnow()
    settings_col.update_one(
        {"_id": "auto_backup_state"},
        {"$set": {"value": state_value, "updated_at": utcnow()}},
        upsert=True,
    )
    return schedule


async def send_backup_to_admin(label="manual"):
    data, counts, created_at = await asyncio.to_thread(build_backup_zip, False)
    if len(data) > TELEGRAM_BACKUP_MAX_BYTES:
        raise ValueError(
            f"Backup is {len(data)/(1024*1024):.1f} MB, above the safe Telegram bot limit. Download it from Web Admin instead."
        )
    filename = f"{slugify(SHOP_NAME)}-backup-{created_at.strftime('%Y%m%d-%H%M')}.zip"
    await bot.send_document(
        ADMIN_ID,
        BufferedInputFile(data, filename=filename),
        caption=(
            f"💾 <b>{html_escape(SHOP_NAME)} backup</b>\n"
            f"Type: <b>{html_escape(str(label))}</b>\n"
            f"Collections: <b>{len(counts)}</b>\n"
            f"Size: <b>{len(data)/(1024*1024):.2f} MB</b>\n\n"
            "Inventory remains encrypted inside the export. Keep this file private."
        ),
        parse_mode="HTML",
    )
    settings_col.update_one(
        {"_id": "auto_backup_state"},
        {"$set": {"last_sent_at": utcnow(), "last_size": len(data), "last_label": str(label), "updated_at": utcnow()}},
        upsert=True,
    )
    return {"bytes": len(data), "collections": counts, "created_at": created_at}


async def process_scheduled_backup():
    schedule = backup_schedule_config()
    if schedule == "off":
        return {"sent": False, "reason": "disabled"}
    now = utcnow()
    state = settings_col.find_one({"_id": "auto_backup_state"}) or {}
    value = dict(state.get("value") or {})
    next_at = _as_utc_datetime(value.get("next_at"))
    if not next_at:
        next_at = now + backup_interval(schedule)
        settings_col.update_one(
            {"_id": "auto_backup_state"},
            {"$set": {"value": {"schedule": schedule, "next_at": next_at}, "updated_at": now}},
            upsert=True,
        )
        return {"sent": False, "reason": "scheduled", "next_at": next_at}
    if next_at > now:
        return {"sent": False, "reason": "not_due", "next_at": next_at}
    future = now + backup_interval(schedule)
    claimed = settings_col.update_one(
        {"_id": "auto_backup_state", "value.next_at": {"$lte": now}},
        {"$set": {"value.schedule": schedule, "value.next_at": future, "last_attempt_at": now, "updated_at": now}},
    )
    if claimed.modified_count != 1:
        return {"sent": False, "reason": "already_claimed"}
    try:
        result = await send_backup_to_admin(f"automatic {schedule}")
        return {"sent": True, **result, "next_at": future}
    except Exception:
        settings_col.update_one(
            {"_id": "auto_backup_state"},
            {"$set": {"value.next_at": now + timedelta(hours=1), "last_error_at": now, "updated_at": now}},
        )
        log.exception("Scheduled backup failed")
        return {"sent": False, "reason": "failed"}


async def process_fulfillment_escalations(limit: int = 40):
    """Send threshold alerts while storing only the latest level on the existing order item."""
    now = utcnow()
    scanned = sent = failed = 0
    query = {"$or": [
        {"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
        {"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}},
    ]}
    orders = list(orders_col.find(query).sort("created_at", 1).limit(max(1, min(int(limit), 100))))
    for order in orders:
        code = str(order.get("order_code") or "")
        for field, icon, view_prefix in (("manual_fulfillment", "🛠", "amv"), ("email_fulfillment", "📧", "aev")):
            entries = list(order.get(field) or [])
            for idx, entry in enumerate(entries):
                if scanned >= limit:
                    return {"scanned": scanned, "sent": sent, "failed": failed}
                if str(entry.get("status") or "pending") == "fulfilled":
                    continue
                scanned += 1
                level = fulfillment_sla_level(order, entry, now)
                previous = max(0, int(entry.get("sla_alert_level", 0) or 0))
                if level <= previous or level <= 0:
                    continue
                path = f"{field}.{idx}.sla_alert_level"
                claim = orders_col.update_one(
                    {
                        "_id": order["_id"],
                        f"{field}.{idx}.status": {"$ne": "fulfilled"},
                        "$or": [{path: {"$exists": False}}, {path: {"$lt": level}}],
                    },
                    {"$set": {path: level, f"{field}.{idx}.sla_alerted_at": now, "updated_at": now}},
                )
                if claim.modified_count != 1:
                    continue
                wait = format_wait_duration(fulfillment_wait_seconds(order, entry, now))
                urgent = level >= 2
                label = "🔴 URGENT FULFILLMENT" if urgent else "🟠 FULFILLMENT WAITING"
                try:
                    await bot.send_message(
                        ADMIN_ID,
                        f"{label}\n\n"
                        f"{icon} <b>{html_escape(str(entry.get('name') or 'Pending order'))}</b>\n"
                        f"Order: <code>#{html_escape(code)}</code>\n"
                        f"Customer: <code>{int(order.get('user_id') or 0)}</code>\n"
                        f"Waiting: <b>{html_escape(wait)}</b>\n\n"
                        + ("This has passed the urgent fulfillment threshold." if urgent else "This has passed the normal fulfillment warning threshold."),
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="Open fulfillment", callback_data=f"{view_prefix}:{code}:{idx}")],
                            [InlineKeyboardButton(text="🧾 Open order", callback_data=f"tgo:{code}")],
                        ]),
                    )
                    sent += 1
                except Exception:
                    failed += 1
                    orders_col.update_one(
                        {"_id": order["_id"]},
                        {"$set": {path: previous, "updated_at": utcnow()}, "$unset": {f"{field}.{idx}.sla_alerted_at": ""}},
                    )
                    log.exception("Fulfillment escalation alert failed for order %s", code)
    return {"scanned": scanned, "sent": sent, "failed": failed}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PyMongo/index checks are synchronous, so keep them off the event loop. On Vercel, do not
    # start a five-minute background worker on every short-lived function instance; cron/webhook
    # housekeeping already covers those jobs.
    await asyncio.to_thread(init_db)
    reminder_task = None if IS_VERCEL else asyncio.create_task(reminder_worker())
    try:
        yield
    finally:
        if reminder_task:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
        await bot.session.close()


app = FastAPI(title="Fattle Shop Advanced", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

_last_webhook_housekeeping = time.monotonic()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    path = request.url.path
    if path == "/admin" or path.startswith("/api/admin/") or path.startswith("/admin/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
    elif path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.get("/")
async def storefront():
    return FileResponse(
        BASE_DIR / "static" / "index.html",
        headers={"Cache-Control": "private, max-age=60, stale-while-revalidate=300"},
    )


@app.get("/index.html")
async def storefront_index_fallback():
    # Vercel serves public/index.html directly from its CDN before FastAPI. This route keeps local
    # and non-Vercel deployments compatible with the same direct_shop_url.
    return FileResponse(
        BASE_DIR / "static" / "index.html",
        headers={"Cache-Control": "private, max-age=60, stale-while-revalidate=300"},
    )


_catalog_cache = {"products": None, "products_exp": 0.0, "methods": None, "methods_exp": 0.0}

def invalidate_method_catalog_cache():
    _catalog_cache["methods"] = None
    _catalog_cache["methods_exp"] = 0.0

def method_gallery_urls(method: dict | None):
    if not isinstance(method, dict):
        return []
    out = []
    for value in method.get("gallery") or []:
        try:
            url = safe_image_url(value)
        except HTTPException:
            continue
        if url and url not in out:
            out.append(url)
        if len(out) >= MAX_METHOD_GALLERY_IMAGES:
            break
    return out

def method_all_images(method: dict | None):
    if not isinstance(method, dict):
        return []
    out = []
    cover = str(method.get("image") or "").strip()
    if cover:
        try:
            cover = safe_image_url(cover)
        except HTTPException:
            cover = ""
        if cover:
            out.append(cover)
    for url in method_gallery_urls(method):
        if url not in out:
            out.append(url)
    return out[: 1 + MAX_METHOD_GALLERY_IMAGES]

def _cached_public_products():
    now = time.monotonic()
    if _catalog_cache["products"] is not None and _catalog_cache["products_exp"] > now:
        return _catalog_cache["products"]
    products = [public_product(p) for p in get_products(True)]
    _catalog_cache["products"] = products
    _catalog_cache["products_exp"] = now + SHOP_CATALOG_CACHE_SECONDS
    return products

def _cached_active_methods():
    now = time.monotonic()
    if _catalog_cache["methods"] is not None and _catalog_cache["methods_exp"] > now:
        return _catalog_cache["methods"]
    rows = list(methods_col.find(
        {"active": True},
        {"_id": 0, "id": 1, "title": 1, "summary": 1, "price": 1, "is_free": 1, "image": 1, "sort_order": 1},
    ).sort("sort_order", 1))
    _catalog_cache["methods"] = rows
    _catalog_cache["methods_exp"] = now + METHOD_CATALOG_CACHE_SECONDS
    return rows

def _shop_user_snapshot(uid: int):
    return users_col.find_one(
        {"user_id": int(uid)},
        {"_id": 0, "credits": 1, "language": 1, "purchase_blocked": 1, "methods_blocked": 1, "suspended": 1},
    ) or {}

def _wishlist_ids(uid: int):
    return [x["product_id"] for x in wishlists_col.find({"user_id": int(uid)}, {"_id": 0, "product_id": 1})]

def _owned_method_ids(uid: int):
    return {x["method_id"] for x in method_purchases_col.find({"user_id": int(uid)}, {"_id": 0, "method_id": 1})}

def _shop_user_state(uid: int):
    """Fetch customer snapshot + wishlist + Method ownership in one MongoDB round-trip."""
    uid = int(uid)
    rows = list(users_col.aggregate([
        {"$match": {"user_id": uid}},
        {"$limit": 1},
        {"$lookup": {
            "from": "wishlists",
            "let": {"uid": "$user_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$user_id", "$$uid"]}}},
                {"$project": {"_id": 0, "product_id": 1}},
            ],
            "as": "wishlist_rows",
        }},
        {"$lookup": {
            "from": "method_purchases",
            "let": {"uid": "$user_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$user_id", "$$uid"]}}},
                {"$project": {"_id": 0, "method_id": 1}},
            ],
            "as": "method_rows",
        }},
        {"$project": {
            "_id": 0, "credits": 1, "language": 1, "purchase_blocked": 1,
            "methods_blocked": 1, "suspended": 1,
            "wishlist": "$wishlist_rows.product_id",
            "owned_methods": "$method_rows.method_id",
        }},
    ]))
    if rows:
        row = rows[0]
        return {
            "user": row,
            "wishlist": list(row.get("wishlist") or []),
            "owned_methods": set(row.get("owned_methods") or []),
        }
    # Very old edge case: a related record may exist before the user document was created.
    return {
        "user": {},
        "wishlist": _wishlist_ids(uid),
        "owned_methods": _owned_method_ids(uid),
    }

async def _build_shop_payload(uid: int):
    # These reads are independent. Running the blocking PyMongo work in parallel worker threads
    # reduces Atlas network latency from several serial round-trips to roughly one round-trip group.
    products, method_rows, user_state = await asyncio.gather(
        asyncio.to_thread(_cached_public_products),
        asyncio.to_thread(_cached_active_methods),
        asyncio.to_thread(_shop_user_state, uid),
    )
    favorites = user_state["wishlist"]
    owned_ids = user_state["owned_methods"]
    user_doc = user_state["user"]
    methods = []
    for m in method_rows:
        is_free = bool(m.get("is_free", False)) or int(m.get("price", 0)) <= 0
        unlocked = is_free or m.get("id") in owned_ids
        # Method body is intentionally not included in initial shop data; openMethod() already
        # fetches it on demand. This can dramatically shrink the first payload for long methods.
        methods.append({
            "id": m.get("id"),
            "title": m.get("title"),
            "summary": m.get("summary", ""),
            "price": int(m.get("price", 0)),
            "is_free": is_free,
            "image": m.get("image", ""),
            "sort_order": int(m.get("sort_order", 0)),
            "unlocked": unlocked,
        })
    lang = user_doc.get("language", DEFAULT_LANGUAGE)
    if lang not in I18N:
        lang = DEFAULT_LANGUAGE
    restrictions = {
        "purchase_blocked": bool(user_doc.get("purchase_blocked", False)),
        "methods_blocked": bool(user_doc.get("methods_blocked", False)),
        "suspended": bool(user_doc.get("suspended", False)),
    }
    return {
        "shopName": SHOP_NAME,
        "products": products,
        "wishlist": favorites,
        "balance": int(user_doc.get("credits", 0)),
        "methods": methods,
        "creditRates": {"inr": CREDIT_RATE_INR, "usd": CREDIT_RATE_USD},
        "ownerUsername": OWNER_USERNAME,
        "language": lang,
        "restrictions": restrictions,
    }

@app.get("/api/shop-bootstrap")
async def shop_bootstrap(launch: str):
    """One network request for launcher exchange + membership verification + initial shop data."""
    uid = verify_shop_launch_token(launch)
    if not uid:
        raise HTTPException(401, "Invalid shop launcher. Return to Telegram and tap Shop / Methods again.")
    # Membership verification is a Telegram network call; catalog loading is MongoDB I/O. They are
    # independent, so overlap them and only return the payload after membership succeeds.
    payload_task = asyncio.create_task(_build_shop_payload(uid))
    if not await user_is_member(uid):
        payload_task.cancel()
        try:
            await payload_task
        except asyncio.CancelledError:
            pass
        raise HTTPException(403, "Join the required Telegram group first.")
    payload = await payload_task
    return {"uid": uid, "sig": shop_token(uid), "expires_in": 21600, **payload}

@app.get("/api/shop-session")
async def create_shop_session(launch: str):
    """Backward-compatible launcher exchange for older cached customer pages."""
    uid = verify_shop_launch_token(launch)
    if not uid:
        raise HTTPException(401, "Invalid shop launcher. Return to Telegram and tap Shop / Methods again.")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join the required Telegram group first.")
    return {"uid": uid, "sig": shop_token(uid), "expires_in": 21600}

@app.get("/api/shop-data")
async def shop_data(uid: int, sig: str):
    if not verify_shop_token(uid, sig):
        raise HTTPException(401, "Shop session expired or invalid. Return to Telegram and tap Shop / Methods again for a fresh secure session.")
    payload_task = asyncio.create_task(_build_shop_payload(uid))
    if not await user_is_member(uid):
        payload_task.cancel()
        try:
            await payload_task
        except asyncio.CancelledError:
            pass
        raise HTTPException(403, "Join the required Telegram group first.")
    return await payload_task


@app.post("/api/language")
async def api_language(request: Request):
    data = await request.json()
    uid = int(data.get("uid", 0))
    sig = str(data.get("sig", ""))
    lang = str(data.get("language", DEFAULT_LANGUAGE)).lower()
    if not verify_shop_token(uid, sig):
        raise HTTPException(401, "Invalid shop session")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join required")
    if lang not in {"en", "id"}:
        raise HTTPException(400, "Unsupported language")
    users_col.update_one(
        {"user_id": uid},
        {"$set": {"language": lang}, "$setOnInsert": {"credits": 0, "created_at": utcnow()}},
        upsert=True,
    )
    _invalidate_language_cache(uid)
    return {"ok": True, "language": lang}


@app.post("/api/wishlist/toggle")
async def wishlist_toggle(request: Request):
    data = await request.json()
    uid = int(data.get("uid"))
    if not verify_shop_token(uid, data.get("sig", "")):
        raise HTTPException(401, "Invalid shop session")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join required")
    pid = str(data.get("product_id", ""))
    if not products_col.find_one({"id": pid, "active": True}):
        raise HTTPException(404, "Product not found")
    existing = wishlists_col.find_one({"user_id": uid, "product_id": pid})
    if existing:
        wishlists_col.delete_one({"_id": existing["_id"]})
        return {"favorite": False}
    wishlists_col.insert_one({"user_id": uid, "product_id": pid, "created_at": utcnow()})
    return {"favorite": True}


@app.post("/api/order/validate")
async def validate_order(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError
        uid = int(data.get("uid") or 0)
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid checkout request")
    sig = str(data.get("sig") or "")
    if not uid or not verify_shop_token(uid, sig):
        raise HTTPException(401, "Invalid shop session")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join the required Telegram group first.")
    payload = data.get("order") or {}
    if not isinstance(payload, dict) or payload.get("type") != "order":
        raise HTTPException(400, "Invalid order payload")
    try:
        (_normalized, total), balance = await asyncio.gather(
            asyncio.to_thread(prepare_order_payload, payload, uid),
            asyncio.to_thread(get_balance, uid),
        )
    except OrderValidationError as exc:
        raise HTTPException(400, str(exc))
    if balance < total:
        raise HTTPException(402, f"Not enough credits. Need {money(total)}, balance {money(balance)}.")
    return {"ok": True, "total": total, "balance": balance, "remaining": balance - total}


@app.get("/admin")
async def admin_page(request: Request):
    return FileResponse(BASE_DIR / "static" / ("admin.html" if admin_ok(request) else "admin-login.html"))


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...), totp: str = Form("")):
    ip = check_login_rate(request)
    valid = hmac.compare_digest(password, ADMIN_PASSWORD)
    if valid and ADMIN_TOTP_SECRET:
        valid = verify_totp(ADMIN_TOTP_SECRET, totp.strip(), window=1)
    if not valid:
        record_login_failure(ip)
        return RedirectResponse("/admin?error=1", 303)
    login_attempts_col.delete_many({"ip": ip})
    r = RedirectResponse("/admin", 303)
    r.set_cookie("shop_admin", admin_session_token(), httponly=True, secure=True, samesite="strict", max_age=ADMIN_SESSION_HOURS * 3600)
    return r


@app.post("/admin/logout")
async def admin_logout():
    r = RedirectResponse("/admin", 303)
    r.delete_cookie("shop_admin")
    return r




@app.post("/api/method/{mid}/buy")
async def buy_method(mid: str, request: Request):
    data = await request.json()
    try:
        uid = int(data.get("user_id") or 0)
    except Exception:
        uid = 0
    sig = str(data.get("sig") or "")
    if not uid or not verify_shop_token(uid, sig):
        raise HTTPException(401, "Invalid shop session")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join the required Telegram group first.")

    # The unique index is the last line of defense against double-clicks/races.
    existing = method_purchases_col.find_one({"user_id": uid, "method_id": mid})
    if existing:
        return {"ok": True, "already_owned": True, "balance": get_balance(uid)}
    restriction = methods_restriction_message(uid)
    if restriction:
        raise HTTPException(403, restriction)

    with mongo_client.start_session() as session:
        def txn(sess):
            flags = users_col.find_one({"user_id": uid}, {"methods_blocked": 1, "suspended": 1}, session=sess) or {}
            if bool(flags.get("suspended", False)) or bool(flags.get("methods_blocked", False)):
                raise PermissionError("METHODS_BLOCKED")
            method = methods_col.find_one({"id": mid, "active": True}, session=sess)
            if not method:
                raise LookupError("METHOD_NOT_FOUND")
            price = max(0, int(method.get("price", 0)))
            is_free = bool(method.get("is_free", False)) or price <= 0

            # Re-check ownership inside the transaction in case two requests arrive together.
            if method_purchases_col.find_one({"user_id": uid, "method_id": mid}, session=sess):
                return {"already_owned": True, "balance": int((users_col.find_one({"user_id": uid}, session=sess) or {}).get("credits", 0))}

            if is_free:
                method_purchases_col.insert_one({
                    "user_id": uid, "method_id": mid, "price": 0,
                    "created_at": utcnow(), "source": "free_claim"
                }, session=sess)
                return {"free": True, "price": 0, "balance": int((users_col.find_one({"user_id": uid}, session=sess) or {}).get("credits", 0))}

            user = users_col.find_one({"user_id": uid}, session=sess)
            bal = int(user.get("credits", 0)) if user else 0
            if bal < price:
                raise ValueError("INSUFFICIENT")
            result = users_col.update_one(
                {"user_id": uid, "credits": {"$gte": price}},
                {"$inc": {"credits": -price}},
                session=sess,
            )
            if result.modified_count != 1:
                raise ValueError("INSUFFICIENT")
            method_purchases_col.insert_one({
                "user_id": uid, "method_id": mid, "price": price,
                "created_at": utcnow(), "source": "purchase"
            }, session=sess)
            credit_log_col.insert_one({
                "user_id": uid, "amount": -price, "action": "method_purchase",
                "admin_id": None, "note": f"Method: {method.get('title', mid)}",
                "created_at": utcnow(),
            }, session=sess)
            return {"price": price, "balance": bal - price}

        try:
            result = session.with_transaction(txn)
        except PermissionError:
            raise HTTPException(403, "New Method purchases are currently disabled for your account.")
        except LookupError:
            raise HTTPException(404, "Method not found")
        except ValueError:
            raise HTTPException(402, "Not enough credits")
        except DuplicateKeyError:
            # Another identical purchase won the race; no second charge can commit with it.
            return {"ok": True, "already_owned": True, "balance": get_balance(uid)}

    if result.get("already_owned"):
        return {"ok": True, **result}

    method_doc = methods_col.find_one({"id": mid, "active": True}, {"_id": 0}) or {}
    delivery_sent = False
    delivery_error = ""
    if method_doc:
        try:
            await send_method_delivery(uid, method_doc, int(result.get("price") or 0), int(result.get("balance") or 0))
            delivery_sent = True
            method_purchases_col.update_one(
                {"user_id": uid, "method_id": mid},
                {"$set": {"telegram_delivered_at": utcnow()}, "$unset": {"telegram_delivery_error": ""}},
            )
        except Exception as exc:
            delivery_error = str(exc)[:500]
            log.exception("Method Telegram delivery failed for user=%s method=%s", uid, mid)
            method_purchases_col.update_one(
                {"user_id": uid, "method_id": mid},
                {"$set": {"telegram_delivery_error": delivery_error, "telegram_delivery_failed_at": utcnow()}},
            )

    return {"ok": True, **result, "delivery_sent": delivery_sent, **({"delivery_warning": "Purchased successfully, but Telegram delivery could not be sent. You can still open the Method in the shop."} if delivery_error else {})}


@app.get("/api/method/{mid}")
async def read_method(mid: str, user_id: int, sig: str):
    uid = int(user_id)
    if not verify_shop_token(uid, sig):
        raise HTTPException(401, "Invalid shop session")
    if not await user_is_member(uid):
        raise HTTPException(403, "Join the required Telegram group first.")
    m = methods_col.find_one({"id": mid, "active": True}, {"_id": 0})
    if not m:
        raise HTTPException(404, "Method not found")
    is_free = bool(m.get("is_free", False)) or int(m.get("price", 0)) <= 0
    owned = is_free or bool(method_purchases_col.find_one({"user_id": uid, "method_id": mid}))
    if not owned:
        raise HTTPException(403, "Method not purchased")
    return {
        "id": m["id"],
        "title": m.get("title", ""),
        "summary": m.get("summary", ""),
        "body": m.get("body", ""),
        "image": m.get("image", ""),
        "gallery": method_gallery_urls(m),
        "price": int(m.get("price", 0)),
        "is_free": is_free,
    }


@app.get("/api/admin/cloudinary-status")
async def cloudinary_status(request: Request):
    require_admin(request)
    try:
        creds = cloudinary_credentials()
    except HTTPException as exc:
        return {"configured": False, "error": exc.detail}

    if not creds:
        return {"configured": False, "error": "Cloudinary is not configured"}

    cloud_name, api_key, _api_secret = creds
    masked_key = ("*" * max(0, len(api_key) - 4)) + api_key[-4:] if api_key else ""
    return {
        "configured": True,
        "cloud_name": cloud_name,
        "api_key_masked": masked_key,
        "source": "separate_env_vars"
        if (CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)
        else "CLOUDINARY_URL",
    }


@app.get("/api/admin/broadcast/stats")
async def broadcast_stats(request: Request):
    require_admin(request)
    eligible_query = {
        "broadcast_opt_out": {"$ne": True},
        "broadcast_blocked": {"$ne": True},
    }
    return {
        "eligible": users_col.count_documents(eligible_query),
        "opted_out": users_col.count_documents({"broadcast_opt_out": True}),
        "blocked": users_col.count_documents({"broadcast_blocked": True}),
        "recent": list(
            broadcasts_col.find(
                {},
                {"_id": 0, "message": 0},
            ).sort("created_at", -1).limit(10)
        ),
    }


@app.post("/api/admin/broadcast/send")
async def broadcast_send(request: Request):
    require_admin(request)
    payload = await request.json()

    message = str(payload.get("message") or "").strip()
    image_url = str(payload.get("image_url") or "").strip()
    button_text = str(payload.get("button_text") or "").strip()
    button_url = str(payload.get("button_url") or "").strip()
    cursor = int(payload.get("cursor") or 0)
    broadcast_id = str(payload.get("broadcast_id") or "").strip() or secrets.token_hex(8)

    if not message:
        raise HTTPException(400, "Broadcast message is required.")
    if len(message) > 3900:
        raise HTTPException(400, "Broadcast message is too long. Keep it under 3900 characters.")
    if image_url and not image_url.startswith(("https://", "http://")):
        raise HTTPException(400, "Image URL must start with http:// or https://")
    if button_text and not button_url:
        raise HTTPException(400, "Button URL is required when button text is set.")
    if button_url and not button_url.startswith(("https://", "http://", "tg://")):
        raise HTTPException(400, "Button URL must start with http://, https:// or tg://")

    batch_size = 30
    query = {
        "user_id": {"$gt": cursor},
        "broadcast_opt_out": {"$ne": True},
        "broadcast_blocked": {"$ne": True},
    }
    recipients = list(
        users_col.find(query, {"user_id": 1, "_id": 0})
        .sort("user_id", 1)
        .limit(batch_size)
    )

    if cursor == 0:
        broadcasts_col.update_one(
            {"broadcast_id": broadcast_id},
            {"$setOnInsert": {
                "broadcast_id": broadcast_id,
                "preview": message[:180],
                "image_url": image_url,
                "button_text": button_text,
                "button_url": button_url,
                "created_at": utcnow(),
                "sent": 0,
                "failed": 0,
                "status": "sending",
            }},
            upsert=True,
        )

    markup = None
    if button_text and button_url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=button_text[:64], url=button_url)]]
        )

    sent = 0
    failed = 0
    last_cursor = cursor

    for row in recipients:
        uid = int(row["user_id"])
        last_cursor = uid
        try:
            if image_url:
                await bot.send_photo(uid, photo=image_url)
            await bot.send_message(
                uid,
                message,
                reply_markup=markup,
                disable_web_page_preview=False,
            )
            sent += 1
        except Exception as exc:
            failed += 1
            err = str(exc).lower()
            if "bot was blocked" in err or "chat not found" in err or "user is deactivated" in err or "forbidden" in err:
                users_col.update_one(
                    {"user_id": uid},
                    {"$set": {"broadcast_blocked": True, "broadcast_blocked_at": utcnow()}}
                )
            log.warning("Broadcast failed for %s: %s", uid, exc)
        await asyncio.sleep(0.04)

    done = len(recipients) < batch_size

    broadcasts_col.update_one(
        {"broadcast_id": broadcast_id},
        {
            "$inc": {"sent": sent, "failed": failed},
            "$set": {
                "updated_at": utcnow(),
                "status": "completed" if done else "sending",
                **({"completed_at": utcnow()} if done else {}),
            },
        },
        upsert=True,
    )

    return {
        "ok": True,
        "broadcast_id": broadcast_id,
        "sent": sent,
        "failed": failed,
        "next_cursor": last_cursor,
        "done": done,
    }


@app.get("/api/admin/methods")
async def admin_methods(request: Request):
    require_admin(request)
    rows = list(methods_col.find({}, {"_id": 0}).sort("sort_order", 1))
    buyer_counts = {str(x["_id"]): int(x["count"]) for x in method_purchases_col.aggregate([
        {"$group": {"_id": "$method_id", "count": {"$sum": 1}}}
    ])}
    for m in rows:
        m["buyers"] = buyer_counts.get(str(m.get("id")), 0)
    return rows


@app.post("/api/admin/method")
async def save_method(
    request: Request,
    id: str = Form(""),
    title: str = Form(...),
    summary: str = Form(""),
    body: str = Form(""),
    price: int = Form(0),
    is_free: int = Form(0),
    sort_order: int = Form(0),
    active: int = Form(1),
    image_url: str = Form(""),
    image_file: UploadFile | None = File(None),
    gallery_urls: str = Form(""),
    gallery_files: list[UploadFile] = File(default=[]),
):
    require_admin(request)
    if not (2 <= len(title.strip()) <= 160):
        raise HTTPException(400, "Method title must be 2–160 characters")
    if int(price) < 0 or int(price) > 1_000_000_000:
        raise HTTPException(400, "Method price must be between 0 and 1,000,000,000 credits")
    if len(summary) > 4000 or len(body) > 50000:
        raise HTTPException(400, "Method text is too long")
    mid = id.strip() or slugify(title) + "-" + secrets.token_hex(2)
    if len(mid) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", mid):
        raise HTTPException(400, "Invalid method ID")
    existing_method = methods_col.find_one({"id": mid}, {"_id": 0}) or {}
    gallery = method_gallery_urls(existing_method)
    image = safe_image_url(image_url)
    cloudinary_public_id = None

    if image_file and image_file.filename:
        content = await image_file.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(400, "Image too large (max 5MB)")
        detected_type = detect_image_content_type(content)
        if not detected_type:
            raise HTTPException(400, "Unsupported or invalid image. Use JPEG, PNG, GIF or WebP.")

        if CLOUDINARY_URL:
            uploaded = await asyncio.to_thread(cloudinary_upload, content, image_file.filename, f"method-{mid}")
            image = uploaded["secure_url"]
            cloudinary_public_id = uploaded.get("public_id")
        else:
            method_images_col.update_one(
                {"method_id": mid},
                {"$set": {
                    "method_id": mid,
                    "content_type": detected_type,
                    "data": Binary(content),
                }},
                upsert=True,
            )
            image = f"/media/method/{mid}"

    new_urls = []
    for raw in str(gallery_urls or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        url = safe_image_url(raw)
        if url and url not in gallery and url not in new_urls:
            new_urls.append(url)
    incoming_files = [f for f in (gallery_files or []) if f and getattr(f, "filename", "")]
    if len(gallery) + len(new_urls) + len(incoming_files) > MAX_METHOD_GALLERY_IMAGES:
        raise HTTPException(400, f"Method gallery supports up to {MAX_METHOD_GALLERY_IMAGES} images")
    gallery.extend(new_urls)

    for upload in incoming_files:
        content = await upload.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(400, "Gallery image too large (max 5MB each)")
        detected_type = detect_image_content_type(content)
        if not detected_type:
            raise HTTPException(400, "Unsupported gallery image. Use JPEG, PNG, GIF or WebP.")
        if cloudinary_credentials():
            uploaded = await asyncio.to_thread(cloudinary_upload, content, upload.filename, f"method-{mid}-gallery-{secrets.token_hex(3)}")
            url = uploaded["secure_url"]
        else:
            if len(content) > MAX_METHOD_GALLERY_IMAGE_BYTES:
                raise HTTPException(400, "Gallery image is too large for MongoDB storage (max 2MB). Use a smaller image/URL or configure Cloudinary.")
            gid = secrets.token_hex(6)
            method_gallery_col.insert_one({
                "image_id": gid, "method_id": mid, "content_type": detected_type,
                "data": Binary(content), "created_at": utcnow(),
            })
            url = f"/media/method/{mid}/gallery/{gid}"
        if url not in gallery:
            gallery.append(url)

    update = {
        "title": title.strip(),
        "summary": summary.strip(),
        "body": body.strip(),
        "price": max(0, int(price)),
        "is_free": bool(int(is_free)),
        "sort_order": int(sort_order),
        "active": bool(int(active)),
        "gallery": gallery[:MAX_METHOD_GALLERY_IMAGES],
        "updated_at": utcnow(),
    }
    if image:
        update["image"] = image
    if cloudinary_public_id:
        update["cloudinary_public_id"] = cloudinary_public_id

    methods_col.update_one(
        {"id": mid},
        {"$set": update, "$setOnInsert": {"id": mid, "created_at": utcnow()}},
        upsert=True,
    )
    invalidate_method_catalog_cache()
    return {"ok": True, "id": mid, "gallery": gallery[:MAX_METHOD_GALLERY_IMAGES]}


@app.delete("/api/admin/method/{mid}")
async def delete_method(mid: str, request: Request):
    require_admin(request)
    methods_col.delete_one({"id": mid})
    method_images_col.delete_one({"method_id": mid})
    method_gallery_col.delete_many({"method_id": mid})
    invalidate_method_catalog_cache()
    return {"ok": True}


@app.post("/api/admin/method/{mid}/gallery/remove")
async def remove_method_gallery_image(mid: str, request: Request):
    require_admin(request)
    data = await request.json()
    image = str(data.get("image") or "").strip()
    method = methods_col.find_one({"id": mid}, {"_id": 0, "gallery": 1})
    if not method:
        raise HTTPException(404, "Method not found")
    gallery = method_gallery_urls(method)
    if image not in gallery:
        raise HTTPException(404, "Gallery image not found")
    methods_col.update_one({"id": mid}, {"$pull": {"gallery": image}, "$set": {"updated_at": utcnow()}})
    prefix = f"/media/method/{mid}/gallery/"
    if image.startswith(prefix):
        gid = image[len(prefix):]
        method_gallery_col.delete_one({"method_id": mid, "image_id": gid})
    invalidate_method_catalog_cache()
    return {"ok": True}


@app.get("/media/method/{mid}")
async def method_image(mid: str):
    doc = await asyncio.to_thread(
        method_images_col.find_one, {"method_id": mid}, {"data": 1, "content_type": 1}
    )
    if not doc:
        raise HTTPException(404, "Image not found")
    return Response(
        content=bytes(doc["data"]),
        media_type=doc.get("content_type") or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
    )


@app.get("/media/method/{mid}/gallery/{gid}")
async def method_gallery_image(mid: str, gid: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", gid or ""):
        raise HTTPException(404, "Image not found")
    doc = await asyncio.to_thread(
        method_gallery_col.find_one,
        {"method_id": mid, "image_id": gid},
        {"data": 1, "content_type": 1},
    )
    if not doc:
        raise HTTPException(404, "Image not found")
    return Response(
        content=bytes(doc["data"]),
        media_type=doc.get("content_type") or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
    )


@app.get("/api/admin/products")
async def admin_products(request: Request):
    require_admin(request)
    rows = get_products(False)
    sold = {str(x["_id"]): int(x["count"]) for x in orders_col.aggregate([
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.id", "count": {"$sum": {"$ifNull": ["$items.qty", 1]}}}},
    ])}
    wished = {str(x["_id"]): int(x["count"]) for x in wishlists_col.aggregate([
        {"$group": {"_id": "$product_id", "count": {"$sum": 1}}}
    ])}
    safe_rows = []
    for p in rows:
        p["sold_count"] = sold.get(str(p["id"]), 0)
        p["wishlist_count"] = wished.get(str(p["id"]), 0)
        safe_rows.append(public_product(p, include_admin_fields=True))
    return safe_rows


@app.get("/api/admin/inventory")
async def admin_inventory(request: Request, product_id: str = ""):
    require_admin(request)
    query = {"product_id": product_id} if product_id else {}
    rows = []
    for d in digital_inventory_col.find(query).sort("_id", -1).limit(500):
        plain = decrypt_payload(d)
        account = parse_account_inventory_payload(plain)
        otp_parsed = split_otp_inventory_payload(plain)
        rows.append({
            "id": str(d["_id"]),
            "product_id": d.get("product_id"),
            "variant_id": d.get("variant_id", "default"),
            "sold": bool(d.get("sold", False)),
            "plain": plain,
            "account": account or {},
            "masked": mask_secret(plain),
            "otp_enabled_item": bool(otp_parsed),
            "sold_to": d.get("sold_to"),
            "order_code": d.get("order_code"),
        })
    return rows


@app.delete("/api/admin/inventory/{item_id}")
async def delete_inventory(item_id: str, request: Request):
    require_admin(request)
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(400, "Invalid inventory id")
    doc = digital_inventory_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Inventory item not found")
    if doc.get("sold"):
        raise HTTPException(400, "Sold delivery records cannot be deleted")
    digital_inventory_col.delete_one({"_id": oid})
    return {"ok": True}


@app.get("/api/admin/orders")
async def admin_orders(request: Request):
    require_admin(request)
    rows = list(orders_col.find({}, {"_id": 0, "digital_delivery": 0}).sort("created_at", -1).limit(200))
    for order in rows:
        safe_manual = []
        for entry in order.get("manual_fulfillment") or []:
            item = dict(entry)
            item.pop("delivery_enc", None)
            item.pop("delivery_text", None)
            safe_manual.append(item)
        order["manual_fulfillment"] = safe_manual
        now = utcnow()
        for field in ("manual_fulfillment", "email_fulfillment"):
            for entry in order.get(field) or []:
                if str(entry.get("status") or "pending") != "fulfilled":
                    entry["wait_seconds"] = fulfillment_wait_seconds(order, entry, now)
                    entry["sla_level"] = fulfillment_sla_level(order, entry, now)
    return rows


@app.post("/api/admin/order/{code}/resend")
async def admin_resend(code: str, request: Request):
    require_admin(request)
    ok, message = await resend_delivery(code)
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message}



def derive_order_status(order: dict) -> str:
    email_entries = list(order.get("email_fulfillment") or [])
    manual_entries = list(order.get("manual_fulfillment") or [])
    pending = any(str(x.get("status") or "pending") != "fulfilled" for x in email_entries + manual_entries)
    fulfilled_async = any(str(x.get("status") or "pending") == "fulfilled" for x in email_entries + manual_entries)
    instant_delivered = bool(order.get("digital_delivery"))
    if pending:
        return "partially_delivered" if (instant_delivered or fulfilled_async) else "awaiting_fulfillment"
    return "delivered"


def set_derived_order_status(order: dict) -> str:
    status = derive_order_status(order)
    if str(order.get("status") or "") != status:
        orders_col.update_one({"_id": order["_id"]}, {"$set": {"status": status, "updated_at": utcnow()}})
        order["status"] = status
    return status


def repair_email_fulfillment_state(order: dict, fulfillment_index: int):
    """Repair derived order status/reminder after a retry or partial previous fulfillment."""
    entries = list(order.get("email_fulfillment") or [])
    if fulfillment_index < 0 or fulfillment_index >= len(entries):
        return order.get("status"), None
    entry = dict(entries[fulfillment_index])
    new_status = set_derived_order_status(order)

    expiry = entry.get("expires_at")
    if not expiry:
        return new_status, None
    try:
        expiry = parse_datetime_value(expiry, "expiry date")
    except ValueError:
        return new_status, None
    item_index = int(entry.get("item_index", fulfillment_index))
    code = str(order.get("order_code") or "")
    reminder_id = f"order:{code}:{item_index}"
    product_name = str(entry.get("name") or entry.get("product_id") or "Subscription")
    reminder = reminder_document(
        reminder_id=reminder_id, title=product_name, expires_at=expiry, source="order",
        custom_message=str(entry.get("reminder_note") or ""),
        product_id=str(entry.get("product_id") or ""), product_name=product_name,
        order_code=code, item_index=item_index, user_id=int(order.get("user_id")),
        email=str(entry.get("email") or ""),
    )
    # $set makes a retry repair a missing/incomplete reminder without creating duplicates.
    subscription_reminders_col.update_one({"reminder_id": reminder_id}, {"$set": reminder}, upsert=True)
    return new_status, reminder_id


async def fulfill_email_order(code: str, fulfillment_index: int, expiry_at=None, admin_note: str = ""):
    """Idempotently fulfill one email-subscription line and create/update its expiry reminder."""
    try:
        fulfillment_index = int(fulfillment_index)
    except Exception as exc:
        raise ValueError("Invalid fulfillment index") from exc

    order = orders_col.find_one({"order_code": str(code)})
    if not order:
        raise LookupError("Order not found")
    entries = list(order.get("email_fulfillment") or [])
    if fulfillment_index < 0 or fulfillment_index >= len(entries):
        raise LookupError("Email fulfillment item not found")

    existing_entry = dict(entries[fulfillment_index])
    if str(existing_entry.get("status")) == "fulfilled":
        repaired_status, reminder_id = repair_email_fulfillment_state(order, fulfillment_index)
        return {
            "ok": True,
            "already_fulfilled": True,
            "order_status": repaired_status,
            "expires_at": existing_entry.get("expires_at"),
            "reminder_id": reminder_id,
        }

    fulfilled_at = utcnow()
    expiry = None
    if expiry_at not in (None, ""):
        expiry = parse_datetime_value(expiry_at, "expiry date")
        if expiry <= fulfilled_at:
            raise ValueError("Expiry must be in the future")
    else:
        days = max(0, int(existing_entry.get("subscription_days", 0) or 0))
        if days > 0:
            expiry = fulfilled_at + timedelta(days=days)

    entry = dict(existing_entry)
    entry["status"] = "fulfilled"
    entry["fulfilled_at"] = fulfilled_at
    if expiry:
        entry["expires_at"] = expiry
    note = str(admin_note or "").strip()
    if note:
        entry["admin_note"] = note[:1000]

    # Conditional array replacement prevents a double-click/web+Telegram race from fulfilling twice.
    result = orders_col.update_one(
        {"_id": order["_id"], f"email_fulfillment.{fulfillment_index}.status": {"$ne": "fulfilled"}},
        {"$set": {f"email_fulfillment.{fulfillment_index}": entry, "updated_at": utcnow()}},
    )
    if result.modified_count != 1:
        fresh = orders_col.find_one({"_id": order["_id"]}) or order
        fresh_entries = list(fresh.get("email_fulfillment") or [])
        fresh_entry = fresh_entries[fulfillment_index] if fulfillment_index < len(fresh_entries) else entry
        repaired_status, reminder_id = repair_email_fulfillment_state(fresh, fulfillment_index)
        return {
            "ok": True,
            "already_fulfilled": True,
            "order_status": repaired_status,
            "expires_at": fresh_entry.get("expires_at"),
            "reminder_id": reminder_id,
        }

    fresh = orders_col.find_one({"_id": order["_id"]}) or order
    new_status = set_derived_order_status(fresh)

    reminder_id = None
    if expiry:
        item_index = int(entry.get("item_index", fulfillment_index))
        reminder_id = f"order:{code}:{item_index}"
        product_name = str(entry.get("name") or entry.get("product_id") or "Subscription")
        reminder = reminder_document(
            reminder_id=reminder_id,
            title=product_name,
            expires_at=expiry,
            source="order",
            custom_message=str(entry.get("reminder_note") or ""),
            product_id=str(entry.get("product_id") or ""),
            product_name=product_name,
            order_code=str(code),
            item_index=item_index,
            user_id=int(order.get("user_id")),
            email=str(entry.get("email") or ""),
        )
        subscription_reminders_col.update_one({"reminder_id": reminder_id}, {"$set": reminder}, upsert=True)

    try:
        expiry_line = ""
        if expiry:
            expiry_line = f"\n📅 Expiry: <b>{expiry.astimezone(timezone.utc).strftime('%d %b %Y • %H:%M UTC')}</b>"
        await bot.send_message(
            int(order["user_id"]),
            f"✅ <b>Subscription fulfilled</b>\n\n"
            f"{html_escape(str(entry.get('name') or 'Subscription'))}\n"
            f"📧 <code>{html_escape(str(entry.get('email') or ''))}</code>"
            f"{expiry_line}\n\nReceipt: <code>#{html_escape(str(code))}</code>",
            parse_mode="HTML",
            reply_markup=support_markup(str(code)),
        )
    except Exception:
        log.exception("Could not notify customer about email fulfillment for %s", code)

    return {"ok": True, "order_status": new_status, "expires_at": expiry, "reminder_id": reminder_id}



def repair_manual_fulfillment_state(order: dict, fulfillment_index: int):
    entries = list(order.get("manual_fulfillment") or [])
    if fulfillment_index < 0 or fulfillment_index >= len(entries):
        return order.get("status"), None
    entry = dict(entries[fulfillment_index])
    new_status = set_derived_order_status(order)
    expiry = entry.get("expires_at")
    if not expiry:
        return new_status, None
    try:
        expiry = parse_datetime_value(expiry, "expiry date")
    except ValueError:
        return new_status, None
    item_index = int(entry.get("item_index", fulfillment_index))
    code = str(order.get("order_code") or "")
    reminder_id = f"order:{code}:{item_index}"
    product_name = str(entry.get("name") or entry.get("product_id") or "Subscription")
    reminder = reminder_document(
        reminder_id=reminder_id, title=product_name, expires_at=expiry, source="order",
        custom_message=str(entry.get("reminder_note") or ""), product_id=str(entry.get("product_id") or ""),
        product_name=product_name, order_code=code, item_index=item_index, user_id=int(order.get("user_id")),
    )
    subscription_reminders_col.update_one({"reminder_id": reminder_id}, {"$set": reminder}, upsert=True)
    return new_status, reminder_id


async def fulfill_manual_order(code: str, fulfillment_index: int, delivery_text: str, expiry_at=None, admin_note: str = ""):
    """Idempotently deliver one admin-prepared order line. Delivery is encrypted at rest."""
    try:
        fulfillment_index = int(fulfillment_index)
    except Exception as exc:
        raise ValueError("Invalid fulfillment index") from exc
    delivery_text = str(delivery_text or "").strip()
    if not delivery_text:
        raise ValueError("Prepared delivery details are required")
    if len(delivery_text) > 3000 or len(html_escape(delivery_text)) > 2600:
        raise ValueError("Prepared delivery is too long for a safe Telegram message. Keep it concise and try again.")

    order = orders_col.find_one({"order_code": str(code)})
    if not order:
        raise LookupError("Order not found")
    entries = list(order.get("manual_fulfillment") or [])
    if fulfillment_index < 0 or fulfillment_index >= len(entries):
        raise LookupError("Manual fulfillment item not found")
    existing_entry = dict(entries[fulfillment_index])
    if str(existing_entry.get("status") or "pending") == "fulfilled":
        fresh = orders_col.find_one({"_id": order["_id"]}) or order
        repaired_status, reminder_id = repair_manual_fulfillment_state(fresh, fulfillment_index)
        fresh_entries = list(fresh.get("manual_fulfillment") or [])
        fresh_entry = fresh_entries[fulfillment_index] if fulfillment_index < len(fresh_entries) else existing_entry
        try:
            await bot.send_message(int(order["user_id"]), build_manual_delivery_message(fresh, fresh_entry), parse_mode="HTML", reply_markup=support_markup(str(code)))
        except Exception:
            log.exception("Could not resend already-fulfilled manual order %s", code)
        return {
            "ok": True,
            "already_fulfilled": True,
            "order_status": repaired_status,
            "expires_at": fresh_entry.get("expires_at"),
            "reminder_id": reminder_id,
        }

    fulfilled_at = utcnow()
    expiry = None
    if expiry_at not in (None, ""):
        expiry = parse_datetime_value(expiry_at, "expiry date")
        if expiry <= fulfilled_at:
            raise ValueError("Expiry must be in the future")
    else:
        days = max(0, int(existing_entry.get("subscription_days", 0) or 0))
        if days > 0:
            expiry = fulfilled_at + timedelta(days=days)

    entry = dict(existing_entry)
    entry["status"] = "fulfilled"
    entry["fulfilled_at"] = fulfilled_at
    entry["delivery_enc"] = encrypt_payload(delivery_text)
    entry.pop("delivery_text", None)
    if expiry:
        entry["expires_at"] = expiry
    note = str(admin_note or "").strip()
    if note:
        entry["admin_note"] = note[:1000]

    result = orders_col.update_one(
        {"_id": order["_id"], f"manual_fulfillment.{fulfillment_index}.status": {"$ne": "fulfilled"}},
        {"$set": {f"manual_fulfillment.{fulfillment_index}": entry, "updated_at": utcnow()}},
    )
    if result.modified_count != 1:
        fresh = orders_col.find_one({"_id": order["_id"]}) or order
        repaired_status, reminder_id = repair_manual_fulfillment_state(fresh, fulfillment_index)
        fresh_entries = list(fresh.get("manual_fulfillment") or [])
        fresh_entry = fresh_entries[fulfillment_index] if fulfillment_index < len(fresh_entries) else entry
        try:
            if str(fresh_entry.get("status") or "pending") == "fulfilled" and manual_delivery_plain(fresh_entry).strip():
                await bot.send_message(int(order["user_id"]), build_manual_delivery_message(fresh, fresh_entry), parse_mode="HTML", reply_markup=support_markup(str(code)))
        except Exception:
            log.exception("Could not resend raced manual fulfillment for %s", code)
        return {"ok": True, "already_fulfilled": True, "order_status": repaired_status, "expires_at": fresh_entry.get("expires_at"), "reminder_id": reminder_id}

    fresh = orders_col.find_one({"_id": order["_id"]}) or order
    new_status = set_derived_order_status(fresh)
    reminder_id = None
    if expiry:
        item_index = int(entry.get("item_index", fulfillment_index))
        reminder_id = f"order:{code}:{item_index}"
        product_name = str(entry.get("name") or entry.get("product_id") or "Subscription")
        reminder = reminder_document(
            reminder_id=reminder_id, title=product_name, expires_at=expiry, source="order",
            custom_message=str(entry.get("reminder_note") or ""), product_id=str(entry.get("product_id") or ""),
            product_name=product_name, order_code=str(code), item_index=item_index,
            user_id=int(order.get("user_id")),
        )
        subscription_reminders_col.update_one({"reminder_id": reminder_id}, {"$set": reminder}, upsert=True)

    try:
        delivered_order = orders_col.find_one({"_id": order["_id"]}) or fresh
        delivered_entries = list(delivered_order.get("manual_fulfillment") or [])
        delivered_entry = delivered_entries[fulfillment_index] if fulfillment_index < len(delivered_entries) else entry
        await bot.send_message(
            int(order["user_id"]), build_manual_delivery_message(delivered_order, delivered_entry),
            parse_mode="HTML", reply_markup=support_markup(str(code)),
        )
    except Exception:
        log.exception("Could not notify customer about manual fulfillment for %s", code)

    return {"ok": True, "order_status": new_status, "expires_at": expiry, "reminder_id": reminder_id}


@app.post("/api/admin/order/{code}/fulfill-email")
async def admin_fulfill_email(code: str, request: Request):
    require_admin(request)
    data = await request.json()
    try:
        result = await fulfill_email_order(
            code,
            int(data.get("fulfillment_index")),
            expiry_at=str(data.get("expiry_at") or "").strip() or None,
            admin_note=str(data.get("admin_note") or ""),
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(400 if isinstance(exc, ValueError) else 404, str(exc))
    return result


@app.post("/api/admin/order/{code}/fulfill-manual")
async def admin_fulfill_manual(code: str, request: Request):
    require_admin(request)
    data = await request.json()
    try:
        result = await fulfill_manual_order(
            code,
            int(data.get("fulfillment_index")),
            delivery_text=str(data.get("delivery_text") or ""),
            expiry_at=str(data.get("expiry_at") or "").strip() or None,
            admin_note=str(data.get("admin_note") or ""),
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(400 if isinstance(exc, ValueError) else 404, str(exc))
    return result


@app.get("/api/admin/reminders")
async def admin_reminders(request: Request):
    require_admin(request)
    rows = list(
        subscription_reminders_col.find(
            {"status": {"$ne": "cancelled"}}, {"_id": 0}
        ).sort("expires_at", 1).limit(500)
    )
    return rows


@app.post("/api/admin/reminder")
async def save_admin_reminder(request: Request):
    require_admin(request)
    data = await request.json()
    rid = str(data.get("reminder_id") or "").strip()
    existing = subscription_reminders_col.find_one({"reminder_id": rid}) if rid else None
    if not rid:
        rid = "manual:" + secrets.token_hex(8)

    title = str(data.get("title") or (existing or {}).get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Reminder title is required")
    try:
        expiry = parse_datetime_value(data.get("expires_at"), "expiry date")
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    product_id = str(data["product_id"] if "product_id" in data else (existing or {}).get("product_id") or "").strip()
    product = products_col.find_one({"id": product_id}, {"_id": 0, "name": 1}) if product_id else None
    product_name = str((product or {}).get("name") or title)

    raw_user_id = data.get("user_id")
    if raw_user_id in (None, ""):
        user_id = (existing or {}).get("user_id")
    else:
        try:
            user_id = int(raw_user_id)
        except Exception:
            raise HTTPException(400, "Customer Telegram ID must be a number")

    email = str(data["email"] if "email" in data else (existing or {}).get("email") or "").strip()
    if email and not valid_email_address(email):
        raise HTTPException(400, "Invalid email address")

    doc = reminder_document(
        reminder_id=rid,
        title=title,
        expires_at=expiry,
        source=str((existing or {}).get("source") or "manual"),
        custom_message=str(data.get("custom_message") if "custom_message" in data else (existing or {}).get("custom_message") or ""),
        product_id=product_id,
        product_name=product_name,
        order_code=str((existing or {}).get("order_code") or ""),
        item_index=(existing or {}).get("item_index"),
        user_id=user_id,
        email=email,
    )
    if existing and existing.get("created_at"):
        doc["created_at"] = existing["created_at"]
    subscription_reminders_col.update_one({"reminder_id": rid}, {"$set": doc}, upsert=True)
    return {"ok": True, "reminder": doc}


@app.delete("/api/admin/reminder/{rid}")
async def cancel_admin_reminder(rid: str, request: Request):
    require_admin(request)
    result = subscription_reminders_col.update_one(
        {"reminder_id": rid},
        {"$set": {"status": "cancelled", "cancelled_at": utcnow(), "updated_at": utcnow()}},
    )
    if result.matched_count != 1:
        raise HTTPException(404, "Reminder not found")
    return {"ok": True}


@app.post("/api/admin/reminders/process")
async def admin_process_reminders(request: Request):
    require_admin(request)
    return {"ok": True, **(await process_due_reminders(100))}


@app.get("/api/admin/customers")
async def admin_customers(request: Request):
    require_admin(request)
    rows = list(users_col.find({}, {"_id": 0}).sort("last_seen", -1).limit(300))
    user_ids = [int(u["user_id"]) for u in rows if u.get("user_id") is not None]
    aggregates = {int(x["_id"]): x for x in orders_col.aggregate([
        {"$match": {"user_id": {"$in": user_ids}}},
        {"$group": {"_id": "$user_id", "orders": {"$sum": 1}, "spent": {"$sum": "$total_credits"}, "last": {"$max": "$created_at"}}},
    ])} if user_ids else {}
    for u in rows:
        a = aggregates.get(int(u["user_id"]), {"orders": 0, "spent": 0, "last": None})
        u.update({"total_orders": int(a.get("orders", 0)), "total_spent": int(a.get("spent", 0)), "last_purchase": a.get("last")})
    return rows


@app.get("/api/admin/customer/{uid}")
async def admin_customer_profile(uid: int, request: Request):
    require_admin(request)
    user = users_col.find_one({"user_id": uid}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Customer not found")
    orders = list(orders_col.find({"user_id": uid}, {"_id": 0, "digital_delivery": 0}).sort("created_at", -1).limit(100))
    return {"user": user, "orders": orders, "total_orders": len(orders), "total_spent": sum(int(o.get("total_credits", 0)) for o in orders)}


@app.post("/api/admin/internal-note")
async def admin_internal_note(request: Request):
    require_admin(request)
    data = await request.json()
    target = str(data.get("target") or "").lower()
    note = str(data.get("note") or "").strip()
    if len(note) > MAX_INTERNAL_NOTE_LENGTH:
        raise HTTPException(400, f"Internal note is limited to {MAX_INTERNAL_NOTE_LENGTH} characters")
    if target == "customer":
        try:
            uid = int(data.get("user_id"))
        except Exception:
            raise HTTPException(400, "Invalid customer ID")
        result = users_col.update_one({"user_id": uid}, {"$set": {"admin_note": note, "admin_note_updated_at": utcnow()}})
        if not result.matched_count:
            raise HTTPException(404, "Customer not found")
        return {"ok": True, "target": "customer", "user_id": uid, "note": note}
    if target == "order":
        code = str(data.get("order_code") or "").strip()
        result = orders_col.update_one({"order_code": code}, {"$set": {"admin_note": note, "admin_note_updated_at": utcnow()}})
        if not result.matched_count:
            raise HTTPException(404, "Order not found")
        return {"ok": True, "target": "order", "order_code": code, "note": note}
    raise HTTPException(400, "Note target must be customer or order")


@app.post("/api/admin/customer-restrictions")
async def admin_customer_restrictions(request: Request):
    require_admin(request)
    data = await request.json()
    try:
        uid = int(data.get("user_id"))
    except Exception:
        raise HTTPException(400, "Invalid customer ID")
    field = str(data.get("field") or "")
    if field not in {"purchase_blocked", "methods_blocked", "suspended"}:
        raise HTTPException(400, "Invalid restriction")
    value = bool(data.get("value"))
    result = users_col.update_one({"user_id": uid}, {"$set": {field: value, "restriction_updated_at": utcnow()}})
    if not result.matched_count:
        raise HTTPException(404, "Customer not found")
    return {"ok": True, "user_id": uid, "restrictions": customer_restrictions(uid)}


@app.post("/api/admin/customer-credit")
async def admin_customer_credit(request: Request):
    require_admin(request)
    data = await request.json()
    try:
        uid = int(data["user_id"])
        amount = int(data["amount"])
    except Exception:
        raise HTTPException(400, "User ID and amount must be whole numbers")
    mode = str(data.get("mode", "add"))
    if mode not in {"add", "set"}:
        raise HTTPException(400, "Invalid credit operation")
    if abs(amount) > 1_000_000_000:
        raise HTTPException(400, "Credit change is too large")
    try:
        new = adjust_credit(uid, amount, ADMIN_ID, set_to=amount if mode == "set" else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        await bot.send_message(uid, f"💳 Your new balance is <b>{money(new)}</b>", parse_mode="HTML")
    except Exception:
        pass
    return {"ok": True, "balance": new}


@app.get("/api/admin/fulfillment-templates")
async def admin_fulfillment_templates(request: Request):
    require_admin(request)
    return [template_public(x) for x in fulfillment_templates_col.find({}, {"_id": 0}).sort("name", 1)]


@app.post("/api/admin/fulfillment-template")
async def admin_save_fulfillment_template(request: Request):
    require_admin(request)
    data = await request.json()
    tid = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    body = str(data.get("body") or "").strip()
    product_id = str(data.get("product_id") or "").strip()
    active = bool(data.get("active", True))
    if not name or len(name) > 60:
        raise HTTPException(400, "Template name must be 1–60 characters")
    if not body or len(body) > 3000:
        raise HTTPException(400, "Template body must be 1–3000 characters")
    if product_id and not products_col.find_one({"id": product_id}):
        raise HTTPException(400, "Linked product not found")
    existing = fulfillment_templates_col.find_one({"id": tid}) if tid else None
    if not existing and fulfillment_templates_col.count_documents({}) >= MAX_FULFILLMENT_TEMPLATES:
        raise HTTPException(400, f"Maximum {MAX_FULFILLMENT_TEMPLATES} templates reached")
    if not tid:
        tid = f"tpl-{secrets.token_hex(6)}"
    now = utcnow()
    fulfillment_templates_col.update_one(
        {"id": tid},
        {"$set": {"name": name, "body": body, "product_id": product_id, "active": active, "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return {"ok": True, "template": template_public(fulfillment_templates_col.find_one({"id": tid}) or {})}


@app.delete("/api/admin/fulfillment-template/{tid}")
async def admin_delete_fulfillment_template(tid: str, request: Request):
    require_admin(request)
    result = fulfillment_templates_col.delete_one({"id": str(tid)})
    if not result.deleted_count:
        raise HTTPException(404, "Template not found")
    return {"ok": True}


@app.get("/api/admin/backup-status")
async def admin_backup_status(request: Request):
    require_admin(request)
    state = settings_col.find_one({"_id": "auto_backup_state"}) or {}
    return {
        "schedule": backup_schedule_config(),
        "state": state.get("value") or {},
        "last_sent_at": state.get("last_sent_at"),
        "last_size": int(state.get("last_size") or 0),
        "sla_warning_hours": FULFILLMENT_WARNING_HOURS,
        "sla_urgent_hours": FULFILLMENT_URGENT_HOURS,
    }


@app.post("/api/admin/backup-settings")
async def admin_backup_settings(request: Request):
    require_admin(request)
    data = await request.json()
    try:
        schedule = configure_backup_schedule(str(data.get("schedule") or "off"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "schedule": schedule}


@app.post("/api/admin/backup/send-telegram")
async def admin_backup_send_telegram(request: Request):
    require_admin(request)
    try:
        result = await send_backup_to_admin("manual Web Admin export")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "bytes": result["bytes"], "created_at": result["created_at"]}


@app.get("/api/admin/backup.zip")
async def admin_backup_download(request: Request, include_images: int = 0):
    require_admin(request)
    data, counts, created_at = await asyncio.to_thread(build_backup_zip, bool(include_images))
    filename = f"{slugify(SHOP_NAME)}-backup-{created_at.strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Backup-Collections": str(len(counts)),
        },
    )


@app.post("/api/admin/fulfillment-escalations/process")
async def admin_process_fulfillment_escalations(request: Request):
    require_admin(request)
    return {"ok": True, **(await process_fulfillment_escalations(100))}


@app.get("/api/admin/analytics")
async def admin_analytics(request: Request):
    require_admin(request)
    return analytics_data()


@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    require_admin(request)
    inventory_available = digital_inventory_col.count_documents({"sold": False})
    inventory_sold = digital_inventory_col.count_documents({"sold": True})
    out = 0
    low = 0
    for p in get_products(False):
        if p["stock"] == 0:
            out += 1
        elif p["stock"] <= DEFAULT_LOW_STOCK:
            low += 1
    a = analytics_data()
    pending_email = orders_col.count_documents({"email_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    pending_manual = orders_col.count_documents({"manual_fulfillment": {"$elemMatch": {"status": {"$ne": "fulfilled"}}}})
    now = utcnow()
    due_reminders = subscription_reminders_col.count_documents({"status": "pending", "remind_at": {"$lte": now}})
    upcoming_reminders = subscription_reminders_col.count_documents({
        "status": "pending", "remind_at": {"$gt": now, "$lte": now + timedelta(hours=48)}
    })
    sla_counts = pending_fulfillment_sla_counts(now)
    return {
        "customers": users_col.count_documents({}), "orders": orders_col.count_documents({}),
        "revenue": int(next(iter(orders_col.aggregate([{"$group": {"_id": None, "total": {"$sum": "$total_credits"}}}])), {}).get("total", 0)),
        "available": inventory_available, "sold": inventory_sold, "low": low, "out": out,
        "pending_email": pending_email, "pending_manual": pending_manual,
        "due_reminders": due_reminders, "upcoming_reminders": upcoming_reminders,
        "sla_warning": sla_counts["warning"], "sla_urgent": sla_counts["urgent"],
        "sla_warning_hours": FULFILLMENT_WARNING_HOURS, "sla_urgent_hours": FULFILLMENT_URGENT_HOURS,
        "today": a["today"], "week": a["week"], "month": a["month"],
        "encryption": ENCRYPTION_KEY_SOURCE, "two_factor": bool(ADMIN_TOTP_SECRET), "cloudinary": bool(CLOUDINARY_URL),
    }


@app.post("/api/admin/product")
async def save_product(
    request: Request,
    id: str = Form(""), name: str = Form(...), price: int = Form(...), emoji: str = Form("🔑"),
    description: str = Form(""), instructions: str = Form(""), warranty: str = Form(""),
    support_note: str = Form(""), delivery_note: str = Form(""), activation_prompt: str = Form(""), category: str = Form("General"),
    active: int = Form(1), featured: int = Form(0), bestseller: int = Form(0), badge_new: int = Form(0),
    otp_enabled: int = Form(0), otp_price: int = Form(10),
    fulfillment_mode: str = Form("instant"), subscription_days: int = Form(0),
    reminder_note: str = Form(""), purchase_key_required: int = Form(0), purchase_key: str = Form(""),
    variants_text: str = Form(""), digital_inventory: str = Form(""),
    image_url: str = Form(""), image_file: UploadFile | None = File(None),
):
    require_admin(request)
    if not (2 <= len(name.strip()) <= 120):
        raise HTTPException(400, "Product name must be 2–120 characters")
    if int(price) < 0 or int(price) > 1_000_000_000:
        raise HTTPException(400, "Product price must be between 0 and 1,000,000,000 credits")
    pid = id.strip() or slugify(name) + "-" + secrets.token_hex(2)
    if len(pid) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
        raise HTTPException(400, "Invalid product ID")
    existing = products_col.find_one({"id": pid}) or {}
    before_stock = product_total_stock(pid)
    fulfillment_mode = str(fulfillment_mode or "instant").strip().lower()
    if fulfillment_mode not in {"instant", "email", "manual", "login_assist"}:
        raise HTTPException(400, "Invalid fulfillment mode")
    subscription_days = max(0, int(subscription_days or 0))
    variants = parse_variants(variants_text, price, subscription_days)

    key_required = bool(int(purchase_key_required or 0))
    new_key = str(purchase_key or "").strip()
    if new_key and not (4 <= len(new_key) <= MAX_PURCHASE_KEY_LENGTH):
        raise HTTPException(400, f"Purchase key must be 4–{MAX_PURCHASE_KEY_LENGTH} characters")
    if any(len(str(v)) > limit for v, limit in (
        (description, 8000), (instructions, 8000), (warranty, 2000),
        (support_note, 4000), (delivery_note, 4000), (activation_prompt, 4000), (reminder_note, 4000),
        (category, 120), (emoji, 32), (variants_text, 20000), (digital_inventory, 2_000_000),
    )):
        raise HTTPException(400, "One or more product fields are too long")
    if key_required:
        if new_key:
            key_hash = purchase_key_hash(pid, new_key)
        elif existing.get("purchase_key_hash"):
            key_hash = str(existing.get("purchase_key_hash"))
        else:
            raise HTTPException(400, "This product requires a purchase key. Enter a key before saving.")
    else:
        # Keep the existing hash while the requirement is disabled so Telegram and
        # Web Admin behave identically: OFF is temporary and can be re-enabled later.
        # A newly typed key still rotates the stored key even if the lock is currently off.
        key_hash = purchase_key_hash(pid, new_key) if new_key else str(existing.get("purchase_key_hash") or "")

    image = safe_image_url(image_url)
    cloudinary_public_id = existing.get("cloudinary_public_id")

    if image_file and image_file.filename:
        content = await image_file.read()
        if len(content) > 5 * 1024 * 1024:
            raise HTTPException(400, "Image too large (max 5MB)")
        detected_type = detect_image_content_type(content)
        if not detected_type:
            raise HTTPException(400, "Unsupported or invalid image. Use JPEG, PNG, GIF or WebP.")
        if CLOUDINARY_URL:
            result = await asyncio.to_thread(cloudinary_upload, content, image_file.filename, pid)
            image = result.get("secure_url")
            cloudinary_public_id = result.get("public_id")
        else:
            product_images_col.update_one(
                {"product_id": pid},
                {"$set": {"product_id": pid, "content_type": detected_type, "data": Binary(content)}},
                upsert=True,
            )
            image = f"/media/product/{pid}"

    update = {
        "name": name.strip(), "price": int(price), "emoji": emoji.strip() or "🔑", "description": description.strip(),
        "instructions": instructions.strip(), "warranty": warranty.strip(), "support_note": support_note.strip(),
        "delivery_note": delivery_note.strip(), "activation_prompt": activation_prompt.strip() or "Please send the activation code shown by the service.", "category": category.strip() or "General", "active": bool(int(active)),
        "featured": bool(int(featured)), "bestseller": bool(int(bestseller)), "badge_new": bool(int(badge_new)),
        "variants": variants, "delivery_type": "digital", "fulfillment_mode": fulfillment_mode,
        "subscription_days": subscription_days, "reminder_note": reminder_note.strip(),
        "purchase_key_required": key_required, "purchase_key_hash": key_hash,
        "otp_enabled": bool(int(otp_enabled)) if fulfillment_mode == "instant" else False,
        "otp_price": max(1, int(otp_price or OTP_PRICE)),
        "updated_at": utcnow(),
    }
    if image:
        update["image"] = image
    if cloudinary_public_id:
        update["cloudinary_public_id"] = cloudinary_public_id
    insert_defaults = {"id": pid, "created_at": utcnow()}
    if "image" not in update:
        insert_defaults["image"] = existing.get("image", "")
    products_col.update_one({"id": pid}, {"$set": update, "$setOnInsert": insert_defaults}, upsert=True)

    # Preserve legacy stock when a previously single-variant product is upgraded to named variants.
    first_variant_id = variants[0]["id"]
    digital_inventory_col.update_many({"product_id": pid, "variant_id": {"$exists": False}}, {"$set": {"variant_id": first_variant_id}})
    if first_variant_id != "default" and len(variants) > 1:
        digital_inventory_col.update_many({"product_id": pid, "variant_id": "default", "sold": False}, {"$set": {"variant_id": first_variant_id}})

    new_items = parse_inventory_lines(digital_inventory, variants) if fulfillment_mode == "instant" else []
    if new_items:
        digital_inventory_col.insert_many([
            {"product_id": pid, "variant_id": variant_id, "payload_enc": encrypt_payload(payload), "sold": False, "created_at": utcnow()}
            for variant_id, payload in new_items
        ])
    after_stock = product_total_stock(pid)
    if fulfillment_mode == "instant":
        await notify_restock(pid, before_stock, after_stock)
        await maybe_low_stock_alert([pid])
    return {"ok": True, "id": pid, "stock": after_stock, "fulfillment_mode": fulfillment_mode, "purchase_key_required": key_required}


@app.delete("/api/admin/product/{pid}")
async def delete_product(pid: str, request: Request):
    require_admin(request)
    if orders_col.count_documents({"items.id": pid}) > 0:
        products_col.update_one({"id": pid}, {"$set": {"active": False, "archived": True}})
        return {"ok": True, "archived": True}
    products_col.delete_one({"id": pid})
    digital_inventory_col.delete_many({"product_id": pid})
    product_images_col.delete_one({"product_id": pid})
    wishlists_col.delete_many({"product_id": pid})
    return {"ok": True, "deleted": True}


@app.get("/media/product/{pid}")
async def product_image(pid: str):
    doc = await asyncio.to_thread(
        product_images_col.find_one, {"product_id": pid}, {"data": 1, "content_type": 1}
    )
    if not doc:
        raise HTTPException(404, "Image not found")
    return Response(
        content=bytes(doc["data"]),
        media_type=doc.get("content_type") or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
    )


@app.post("/admin/setup-webhook")
async def setup_webhook(request: Request):
    require_admin(request)
    result = await bot.set_webhook(url=f"{PUBLIC_URL}/telegram/webhook", secret_token=WEBHOOK_SECRET_SAFE, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=False)
    info = await bot.get_webhook_info()
    return {"ok": bool(result), "webhook_url": info.url, "pending_update_count": info.pending_update_count, "last_error_message": info.last_error_message}


@app.get("/admin/webhook-status")
async def webhook_status(request: Request):
    require_admin(request)
    info = await bot.get_webhook_info()
    return {"url": info.url, "pending_update_count": info.pending_update_count, "last_error_message": info.last_error_message, "required_chat_id": required_chat_id(), "required_chat_invite_url": REQUIRED_CHAT_INVITE_URL}


@app.get("/api/cron/reminders")
async def cron_reminders(authorization: str | None = Header(default=None)):
    if not CRON_SECRET:
        raise HTTPException(503, "CRON_SECRET is not configured")
    expected = f"Bearer {CRON_SECRET}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Invalid cron authorization")
    reminders = await process_due_reminders(100)
    escalations = await process_fulfillment_escalations(100)
    backup = await process_scheduled_backup()
    return {"ok": True, "reminders": reminders, "fulfillment_escalations": escalations, "backup": backup}


@app.get("/health")
async def health():
    try:
        mongo_client.admin.command("ping")
        return {"status": "healthy", "ok": True, "shop": SHOP_NAME, "database": "mongodb-connected"}
    except PyMongoError:
        raise HTTPException(503, "MongoDB unavailable")


async def _run_webhook_housekeeping_background():
    """Run periodic maintenance after the webhook response has already been sent."""
    try:
        await process_due_reminders(5)
        await process_fulfillment_escalations(5)
    except Exception:
        log.exception("Webhook housekeeping check failed")


@app.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(x_telegram_bot_api_secret_token, WEBHOOK_SECRET_SAFE):
        raise HTTPException(403, "Invalid secret")
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    # Do not scan reminder/order collections after every Telegram update. On always-on hosts the
    # worker handles this; on Vercel, cron is primary and warm instances opportunistically run a
    # small check at most once per configured interval.
    background = None
    if IS_VERCEL:
        global _last_webhook_housekeeping
        now_mono = time.monotonic()
        if now_mono - _last_webhook_housekeeping >= WEBHOOK_HOUSEKEEPING_SECONDS:
            _last_webhook_housekeeping = now_mono
            # Starlette starts this after the response is sent, so Telegram gets its ACK immediately.
            background = BackgroundTask(_run_webhook_housekeeping_background)
    return JSONResponse({"ok": True}, background=background)


# Keep account/reporting additions separate from the Telegram fulfillment engine.
from shop_extensions import register_routes
register_routes(app, sys.modules[__name__])
app.mount("/assets", StaticFiles(directory=BASE_DIR / "static" / "assets"), name="shop-assets")
