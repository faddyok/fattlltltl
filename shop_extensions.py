"""Read-only account history and scalable order management.

No migrations of customer balances, inventory, or existing order records.
"""
import asyncio
import csv
import io
from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId
from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import Response
from shop_domain import order_query, customer_order, csv_cell, utc_iso


ORDER_PROJECTION = {
    "order_code": 1, "user_id": 1, "created_at": 1, "status": 1,
    "total_credits": 1, "items.id": 1, "items.name": 1,
    "items.variant_id": 1, "items.variant_label": 1, "items.qty": 1,
    "items.unit_price": 1, "items.fulfillment_mode": 1,
}
ADMIN_PROJECTION = {
    "digital_delivery": 0, "manual_fulfillment.delivery_enc": 0,
    "manual_fulfillment.delivery_text": 0,
}


def validated_order_query(q, status, date_from, date_to):
    try:
        return order_query(q, status, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def page_query(uid, before):
    query = {"user_id": uid}
    if before:
        if not ObjectId.is_valid(before):
            raise HTTPException(422, "Invalid history cursor")
        query["_id"] = {"$lt": ObjectId(before)}
    return query


def register_routes(app, backend):
    async def authenticate(uid, authorization):
        sig = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if not backend.verify_shop_token(uid, sig):
            raise HTTPException(401, "Shop session expired. Reopen the shop from Telegram.")
        if not await backend.user_is_member(uid):
            raise HTTPException(403, "Join the required Telegram group first.")
        flags = await asyncio.to_thread(backend.customer_restrictions, uid)
        if flags.get("suspended"):
            raise HTTPException(403, "This account is suspended. Contact the shop owner.")

    @app.get("/api/account/orders")
    async def account_orders(uid: int = Query(gt=0), authorization: str = Header("", max_length=300),
                             before: str = Query("", max_length=24), limit: int = Query(20, ge=1, le=50)):
        await authenticate(uid, authorization)
        query = page_query(uid, before)
        rows = await asyncio.to_thread(lambda: list(
            backend.orders_col.find(query, ORDER_PROJECTION).sort("_id", -1).limit(limit + 1)
        ))
        return {
            "items": [customer_order(row) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["_id"]) if len(rows) > limit else None,
        }

    @app.get("/api/account/wallet")
    async def account_wallet(uid: int = Query(gt=0), authorization: str = Header("", max_length=300),
                             before: str = Query("", max_length=24), limit: int = Query(20, ge=1, le=50)):
        await authenticate(uid, authorization)
        query = page_query(uid, before)
        rows, balance = await asyncio.gather(
            asyncio.to_thread(lambda: list(backend.credit_log_col.find(query, {
                "amount": 1, "action": 1, "created_at": 1,
            }).sort("_id", -1).limit(limit + 1))),
            asyncio.to_thread(backend.get_balance, uid),
        )
        return {
            "balance": balance,
            "items": [{"id": str(row["_id"]), "amount": int(row.get("amount", 0)),
                       "action": str(row.get("action", "adjust")), "created_at": utc_iso(row.get("created_at"))}
                      for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["_id"]) if len(rows) > limit else None,
        }

    def admin_rows(query, skip, limit, oldest=False):
        rows = list(backend.orders_col.find(query, ADMIN_PROJECTION)
                    .sort([("created_at", 1 if oldest else -1), ("_id", 1 if oldest else -1)])
                    .skip(skip).limit(limit))
        now = backend.utcnow()
        for row in rows:
            row.pop("_id", None)
            row["created_at"] = utc_iso(row.get("created_at"))
            for field in ("manual_fulfillment", "email_fulfillment"):
                for entry in row.get(field) or []:
                    if entry.get("status", "pending") != "fulfilled":
                        entry["wait_seconds"] = backend.fulfillment_wait_seconds(row, entry, now)
                        entry["sla_level"] = backend.fulfillment_sla_level(row, entry, now)
        return rows

    @app.get("/api/admin/orders/search")
    async def search_orders(request: Request, q: str = Query("", max_length=100),
                            status: Literal["all", "action", "done"] = "all",
                            date_from: str = Query("", max_length=10), date_to: str = Query("", max_length=10),
                            page: int = Query(1, ge=1, le=2000), page_size: int = Query(50, ge=1, le=100)):
        backend.require_admin(request)
        query = validated_order_query(q, status, date_from, date_to)
        rows, count = await asyncio.gather(
            asyncio.to_thread(admin_rows, query, (page - 1) * page_size, page_size, status == "action"),
            asyncio.to_thread(backend.orders_col.count_documents, query),
        )
        return {"items": rows, "total": count, "page": page, "page_size": page_size,
                "pages": max(1, (count + page_size - 1) // page_size)}

    @app.get("/api/admin/orders/export.csv")
    async def export_orders(request: Request, q: str = Query("", max_length=100),
                            status: Literal["all", "action", "done"] = "all",
                            date_from: str = Query("", max_length=10), date_to: str = Query("", max_length=10)):
        backend.require_admin(request)
        query = validated_order_query(q, status, date_from, date_to)

        def build_csv():
            # Bound memory and refuse an incomplete export instead of silently truncating.
            rows = list(backend.orders_col.find(query, ORDER_PROJECTION)
                        .sort([("created_at", -1), ("_id", -1)]).limit(5001))
            if len(rows) > 5000:
                raise HTTPException(413, "More than 5,000 orders match. Narrow the date range before exporting.")
            out = io.StringIO(newline="")
            writer = csv.writer(out)
            writer.writerow(["Order", "Customer ID", "Created (UTC)", "Status", "Credits", "Items"])
            for row in rows:
                stamp = row.get("created_at")
                if isinstance(stamp, datetime):
                    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
                    stamp = stamp.isoformat()
                items = "; ".join(f"{x.get('name', '')} / {x.get('variant_label', '')} x{x.get('qty', 1)}"
                                  for x in row.get("items", []))
                writer.writerow([csv_cell(value) for value in (
                    row.get("order_code"), row.get("user_id"), stamp,
                    row.get("status", "delivered"), row.get("total_credits", 0), items,
                )])
            return "\ufeff" + out.getvalue()

        content = await asyncio.to_thread(build_csv)
        return Response(content, media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="fattle-orders.csv"',
            "Cache-Control": "private, no-store",
        })
