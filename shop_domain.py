"""Dependency-free reporting rules and safe customer serialization."""
import re
from datetime import datetime, timedelta, timezone


def utc_iso(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def order_query(q="", status="all", date_from="", date_to=""):
    """Literal search, inclusive UTC dates, and legacy-safe fulfillment filters."""
    clauses = []
    pending = {"$or": [
        {field: {"$elemMatch": {"status": {"$ne": "fulfilled"}}}}
        for field in ("email_fulfillment", "manual_fulfillment")
    ]}
    if status == "action":
        clauses.append(pending)
    elif status == "done":
        clauses.append({"$nor": [pending]})
    elif status != "all":
        raise ValueError("Unknown order filter")
    if q.strip():
        term = q.strip()
        match = {"$regex": re.escape(term), "$options": "i"}
        choices = [{field: match} for field in (
            "order_code", "items.name", "items.variant_label",
            "items.requested_email", "admin_note",
        )]
        if term.isascii() and term.isdigit() and len(term) <= 18:
            choices.append({"user_id": int(term)})
        clauses.append({"$or": choices})
    dates = {}
    try:
        for value, operator in ((date_from, "$gte"), (date_to, "$lt")):
            if value:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError
                parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                dates[operator] = parsed + (timedelta(days=1) if operator == "$lt" else timedelta())
        if "$gte" in dates and "$lt" in dates and dates["$gte"] >= dates["$lt"]:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError("Use a valid date range in YYYY-MM-DD format")
    if dates:
        clauses.append({"created_at": dates})
    return {"$and": clauses} if clauses else {}


def customer_order(row):
    """Allowlist fields; never return deliveries, emails, or internal notes."""
    return {
        "order_code": str(row.get("order_code", "")),
        "created_at": utc_iso(row.get("created_at")),
        "status": str(row.get("status") or "delivered"),
        "total_credits": int(row.get("total_credits", 0)),
        "items": [{key: item.get(key) for key in (
            "id", "name", "variant_id", "variant_label", "qty", "unit_price", "fulfillment_mode"
        )} for item in row.get("items", [])],
    }


def csv_cell(value):
    """Prevent spreadsheet programs interpreting untrusted text as formulas."""
    text = str(value if value is not None else "")
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text

