"""
RecoverFlow AI — Block 4: Webhook Ingestion Engine
=====================================================
Receives checkout and order webhooks forwarded from the
Shopify React Router app, validates them, persists to
PostgreSQL, and triggers Celery recovery workflows.

Endpoints:
  POST /webhooks/checkout-abandonment
    ← checkouts/create & checkouts/update from Shopify

  POST /webhooks/order-created
    ← orders/create from Shopify (marks recovery, revokes tasks)
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, status, BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_factory
from models import (
    Store,
    CreditLedger,
    AbandonedCheckout,
    RecoverySchedule,
    RecoveredOrder,
    AbandonedCart,
    CartRecoverySchedule,
)
from config import get_settings

logger = logging.getLogger("recoverflow.webhooks")
settings = get_settings()

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ═════════════════════════════════════════════════════════════
#  HELPERS: Shopify Payload Parsing
# ═════════════════════════════════════════════════════════════

def _extract_customer_phone(payload: dict) -> Optional[str]:
    """
    Extracts customer phone from Shopify checkout payload.
    Checks multiple locations in priority order:
      1. shipping_address.phone
      2. billing_address.phone
      3. customer.phone
      4. phone (top-level)
    Returns E.164 formatted phone or None.
    """
    phone = None

    # Try shipping address first (most reliable for delivery contact)
    shipping = payload.get("shipping_address") or {}
    phone = phone or shipping.get("phone")

    # Then billing address
    billing = payload.get("billing_address") or {}
    phone = phone or billing.get("phone")

    # Then customer object
    customer = payload.get("customer") or {}
    phone = phone or customer.get("phone")

    # Top-level phone
    phone = phone or payload.get("phone")

    if phone:
        # Basic E.164 normalization: ensure starts with +
        phone = phone.strip()
        if not phone.startswith("+"):
            phone = f"+{phone}"

    return phone


def _extract_customer_name(payload: dict) -> Optional[str]:
    """Extracts customer full name from Shopify checkout payload."""
    customer = payload.get("customer") or {}
    first = customer.get("first_name") or ""
    last = customer.get("last_name") or ""
    full = f"{first} {last}".strip()

    if not full:
        # Fallback to shipping address
        shipping = payload.get("shipping_address") or {}
        first = shipping.get("first_name") or ""
        last = shipping.get("last_name") or ""
        full = f"{first} {last}".strip()

    return full.title() if full else None


def _extract_line_items(payload: dict) -> list:
    """Extracts cart line items into a clean list for storage."""
    items = payload.get("line_items") or []
    return [
        {
            "title": item.get("title", "Unknown Product"),
            "variant_title": item.get("variant_title"),
            "quantity": item.get("quantity", 1),
            "price": item.get("price", "0.00"),
            "sku": item.get("sku"),
            "image_url": (item.get("image") or {}).get("src") if isinstance(item.get("image"), dict) else None,
        }
        for item in items
    ]


def _extract_checkout_url(payload: dict) -> Optional[str]:
    """Extracts the abandoned checkout recovery URL."""
    return payload.get("abandoned_checkout_url") or payload.get("recovery_url")


def _extract_cart_customer_phone(payload: dict) -> Optional[str]:
    """Extracts customer phone from Shopify cart payload."""
    customer = payload.get("customer") or {}
    phone = customer.get("phone")
    if not phone:
        # Check default address
        default_address = customer.get("default_address") or {}
        phone = default_address.get("phone")
    
    if phone:
        phone = phone.strip()
        if not phone.startswith("+"):
            phone = f"+{phone}"
    return phone


def _extract_cart_customer_name(payload: dict) -> Optional[str]:
    """Extracts customer full name from Shopify cart payload."""
    customer = payload.get("customer") or {}
    first = customer.get("first_name") or ""
    last = customer.get("last_name") or ""
    full = f"{first} {last}".strip()
    if not full:
        default_address = customer.get("default_address") or {}
        first = default_address.get("first_name") or ""
        last = default_address.get("last_name") or ""
        full = f"{first} {last}".strip()
    return full.title() if full else None


def _extract_cart_line_items(payload: dict) -> list:
    """Extracts line items from Shopify cart payload."""
    items = payload.get("items") or payload.get("line_items") or []
    return [
        {
            "title": item.get("title", "Unknown Product"),
            "variant_id": item.get("variant_id") or item.get("id"),
            "quantity": item.get("quantity", 1),
            "price": item.get("price", "0.00"),
            "sku": item.get("sku"),
            "image_url": item.get("image"),
        }
        for item in items
    ]


def _construct_cart_permalink(shop_domain: str, line_items: list) -> str:
    """Constructs a Shopify Cart Permalink from line items."""
    valid_items = [item for item in line_items if item.get("variant_id")]
    if not valid_items:
        return f"https://{shop_domain}/cart"
    
    item_slugs = [f"{item['variant_id']}:{item['quantity']}" for item in valid_items]
    permalink = f"https://{shop_domain}/cart/{','.join(item_slugs)}"
    return permalink


async def _cancel_pending_cart_recovery(db: AsyncSession, cart_id: Optional[str], customer_phone: Optional[str]):
    """Cancels any pending cart schedules for the given cart_id or customer_phone."""
    if not cart_id and not customer_phone:
        return
    
    # Select pending schedules
    query = select(CartRecoverySchedule).where(CartRecoverySchedule.status == "QUEUED")
    if cart_id and customer_phone:
        query = query.join(AbandonedCart).where(
            (AbandonedCart.cart_id == cart_id) | (AbandonedCart.customer_phone == customer_phone)
        )
    elif cart_id:
        query = query.where(CartRecoverySchedule.cart_id == cart_id)
    else:
        query = query.join(AbandonedCart).where(AbandonedCart.customer_phone == customer_phone)
        
    result = await db.execute(query)
    schedules = result.scalars().all()
    
    revoked_count = 0
    for s in schedules:
        s.status = "CANCELLED"
        # Update recovery_status on the cart
        cart_res = await db.execute(select(AbandonedCart).where(AbandonedCart.cart_id == s.cart_id))
        cart = cart_res.scalar_one_or_none()
        if cart and cart.recovery_status not in ("RECOVERED", "FAILED", "EXHAUSTED"):
            cart.recovery_status = "RECOVERED"
            cart.recovered_at = datetime.now(timezone.utc)
            
        if s.celery_task_id:
            try:
                from tasks import celery_app
                celery_app.control.revoke(s.celery_task_id, terminate=True)
                revoked_count += 1
            except Exception as e:
                logger.warning(f"Failed to revoke celery task {s.celery_task_id}: {e}")
                
    if revoked_count > 0:
        logger.info(f"Revoked {revoked_count} pending cart recovery tasks.")


# ═════════════════════════════════════════════════════════════
#  ENDPOINT: Checkout Abandonment
# ═════════════════════════════════════════════════════════════

@router.post("/checkout-abandonment")
async def receive_checkout_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_shop_domain: Optional[str] = Header(None),
    x_webhook_topic: Optional[str] = Header(None),
):
    """
    Ingests checkouts/create and checkouts/update webhooks.

    Flow:
      1. Parse the Shopify checkout payload
      2. Extract customer phone, name, cart items
      3. Upsert into abandoned_checkouts table
      4. If new checkout with valid phone → trigger recovery workflow
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    shop_domain = x_shopify_shop_domain
    if not shop_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Shopify-Shop-Domain header",
        )

    # ── Parse Shopify Fields ─────────────────────────────────
    checkout_id = str(payload.get("id") or payload.get("token") or payload.get("cart_token") or "")
    if not checkout_id:
        logger.warning(f"[{shop_domain}] Checkout webhook missing ID, skipping")
        return {"status": "skipped", "reason": "no_checkout_id"}

    customer_phone = _extract_customer_phone(payload)
    customer_name = _extract_customer_name(payload)
    line_items = _extract_line_items(payload)
    checkout_url = _extract_checkout_url(payload)
    total_price = Decimal(payload.get("total_price", "0.00"))
    currency = payload.get("currency", "INR")
    created_at_str = payload.get("created_at")

    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            created_at = datetime.now(timezone.utc)

    # Build the cart JSON blob with the recovery URL included
    cart_data = {
        "line_items": line_items,
        "checkout_url": checkout_url,
        "email": payload.get("email"),
        "customer": payload.get("customer", {}),
        "discount_codes": payload.get("discount_codes", []),
    }

    logger.info(
        f"[{shop_domain}] Checkout {checkout_id}: "
        f"customer={customer_name}, phone={customer_phone}, "
        f"total={total_price} {currency}, items={len(line_items)}"
    )

    # ── Database Upsert ──────────────────────────────────────
    is_new_checkout = False

    async with async_session_factory() as db:
        # Check if store exists
        store_result = await db.execute(
            select(Store).where(Store.shopify_domain == shop_domain)
        )
        store = store_result.scalar_one_or_none()

        if not store:
            logger.warning(f"[{shop_domain}] Store not found, skipping webhook")
            return {"status": "skipped", "reason": "store_not_found"}

        if not store.is_active:
            logger.info(f"[{shop_domain}] Store is inactive, skipping")
            return {"status": "skipped", "reason": "store_inactive"}

        # Check if checkout already exists
        existing = await db.execute(
            select(AbandonedCheckout).where(
                AbandonedCheckout.checkout_id == checkout_id
            )
        )
        checkout = existing.scalar_one_or_none()

        trigger_recovery = False

        if checkout:
            # If checkout was previously FAILED due to no phone, and now has a phone number,
            # transition back to PENDING and trigger recovery.
            if checkout.recovery_status == "FAILED" and not checkout.customer_phone and customer_phone:
                checkout.recovery_status = "PENDING"
                trigger_recovery = True
                logger.info(f"[{shop_domain}] Checkout {checkout_id} got phone number, transitioning to PENDING")

            # Update existing checkout (cart may have changed)
            checkout.customer_phone = customer_phone or checkout.customer_phone
            checkout.customer_name = customer_name or checkout.customer_name
            checkout.cart_json = cart_data
            checkout.total_price = total_price
            checkout.currency = currency
            logger.info(f"[{shop_domain}] Updated existing checkout {checkout_id}")
        else:
            # Insert new abandoned checkout
            initial_status = "PENDING" if customer_phone else "FAILED"
            checkout = AbandonedCheckout(
                checkout_id=checkout_id,
                shopify_domain=shop_domain,
                customer_name=customer_name,
                customer_phone=customer_phone,
                cart_json=cart_data,
                total_price=total_price,
                currency=currency,
                recovery_status=initial_status,
                created_at=created_at or datetime.now(timezone.utc),
            )
            db.add(checkout)
            if customer_phone:
                trigger_recovery = True
            logger.info(f"[{shop_domain}] Created new checkout {checkout_id} with status {initial_status}")

        # Cancel any pending cart recovery since customer started checkout
        cart_token = payload.get("cart_token")
        await _cancel_pending_cart_recovery(db, cart_token, customer_phone)

        await db.commit()

    # ── Trigger Recovery Workflow ─────────────────────────────
    if trigger_recovery and customer_phone:
        # Import here to avoid circular imports with Celery
        background_tasks.add_task(
            _trigger_recovery_workflow, checkout_id, shop_domain
        )
        logger.info(
            f"[{shop_domain}] Recovery workflow queued for checkout {checkout_id}"
        )

    return {"status": "received", "checkout_id": checkout_id}


async def _trigger_recovery_workflow(checkout_id: str, shop_domain: str):
    """
    Dispatches the Celery recovery workflow.
    This runs in a background thread to avoid blocking the webhook response.
    """
    try:
        from tasks import schedule_recovery_workflow
        schedule_recovery_workflow(checkout_id, shop_domain)
    except Exception as e:
        logger.error(
            f"[{shop_domain}] Failed to schedule recovery for {checkout_id}: {e}"
        )


# ═════════════════════════════════════════════════════════════
#  ENDPOINT: Order Created (Recovery Tracking)
# ═════════════════════════════════════════════════════════════

@router.post("/order-created")
async def receive_order_webhook(
    request: Request,
    x_shopify_shop_domain: Optional[str] = Header(None),
    x_webhook_topic: Optional[str] = Header(None),
):
    """
    Ingests orders/create webhooks from Shopify.

    When an order is placed, we check if it corresponds to an
    abandoned checkout we were tracking. If so:
      1. Mark the checkout as RECOVERED
      2. Cancel all pending Celery tasks for that checkout
      3. Log the recovered revenue in recovered_orders table
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    shop_domain = x_shopify_shop_domain
    if not shop_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Shopify-Shop-Domain header",
        )

    order_id = str(payload.get("id", ""))
    checkout_token = str(payload.get("checkout_id") or payload.get("checkout_token") or "")
    total_price = Decimal(payload.get("total_price", "0.00"))
    currency = payload.get("currency", "INR")

    if not order_id:
        return {"status": "skipped", "reason": "no_order_id"}

    logger.info(
        f"[{shop_domain}] Order {order_id} created, "
        f"checkout_token={checkout_token}, total={total_price} {currency}"
    )

    async with async_session_factory() as db:
        # Cancel any pending cart recovery since customer completed purchase
        customer_phone = _extract_customer_phone(payload)
        cart_token = payload.get("cart_token")
        await _cancel_pending_cart_recovery(db, cart_token, customer_phone)

        # ── Find matching abandoned checkout ─────────────────
        matching_checkout = None

        if checkout_token:
            result = await db.execute(
                select(AbandonedCheckout).where(
                    AbandonedCheckout.checkout_id == checkout_token,
                    AbandonedCheckout.shopify_domain == shop_domain,
                )
            )
            matching_checkout = result.scalar_one_or_none()

        if not matching_checkout:
            # No abandoned checkout matched — this is a normal order, not a recovery
            logger.info(f"[{shop_domain}] Order {order_id} has no matching abandoned checkout")
            return {"status": "received", "recovery": False}

        # ── Mark as RECOVERED ────────────────────────────────
        if matching_checkout.recovery_status != "RECOVERED":
            matching_checkout.recovery_status = "RECOVERED"
            matching_checkout.recovered_at = datetime.now(timezone.utc)

            logger.info(
                f"[{shop_domain}] Checkout {checkout_token} marked as RECOVERED "
                f"(order {order_id}, revenue ₹{total_price})"
            )

        # ── Cancel pending recovery tasks ────────────────────
        schedules_result = await db.execute(
            select(RecoverySchedule).where(
                RecoverySchedule.checkout_id == checkout_token,
                RecoverySchedule.status == "QUEUED",
            )
        )
        pending_schedules = schedules_result.scalars().all()

        revoked_count = 0
        for schedule in pending_schedules:
            schedule.status = "CANCELLED"

            # Revoke the Celery task if we have its ID
            if schedule.celery_task_id:
                try:
                    from tasks import celery_app
                    celery_app.control.revoke(
                        schedule.celery_task_id, terminate=True
                    )
                    revoked_count += 1
                except Exception as e:
                    logger.warning(
                        f"[{shop_domain}] Failed to revoke Celery task "
                        f"{schedule.celery_task_id}: {e}"
                    )

        if revoked_count > 0:
            logger.info(
                f"[{shop_domain}] Revoked {revoked_count} pending recovery tasks "
                f"for checkout {checkout_token}"
            )

        # ── Log recovered revenue ────────────────────────────
        # Check if we already logged this order (idempotency)
        existing_order = await db.execute(
            select(RecoveredOrder).where(RecoveredOrder.order_id == order_id)
        )
        if not existing_order.scalar_one_or_none():
            recovered_order = RecoveredOrder(
                order_id=order_id,
                checkout_id=checkout_token,
                shopify_domain=shop_domain,
                recovered_revenue=total_price,
                currency=currency,
                recovered_at=datetime.now(timezone.utc),
            )
            db.add(recovered_order)
            logger.info(
                f"[{shop_domain}] Logged recovered revenue: "
                f"₹{total_price} from order {order_id}"
            )

        await db.commit()

    return {
        "status": "received",
        "recovery": True,
        "order_id": order_id,
        "checkout_id": checkout_token,
        "recovered_revenue": float(total_price),
    }


# ═════════════════════════════════════════════════════════════
#  ENDPOINT: Cart Abandonment (Premium Feature)
# ═════════════════════════════════════════════════════════════

@router.post("/cart-abandonment")
async def receive_cart_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_shopify_shop_domain: Optional[str] = Header(None),
    x_webhook_topic: Optional[str] = Header(None),
):
    """
    Ingests carts/create and carts/update webhooks from Shopify.
    Fires recovery only if premium subscription (GROWTH/SCALE) is active and customer
    details (phone) are available.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    shop_domain = x_shopify_shop_domain
    if not shop_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Shopify-Shop-Domain header",
        )

    cart_id = str(payload.get("token") or payload.get("id") or "")
    if not cart_id:
        logger.warning(f"[{shop_domain}] Cart webhook missing token/id, skipping")
        return {"status": "skipped", "reason": "no_cart_id"}

    # Extract customer phone & name
    customer_phone = _extract_cart_customer_phone(payload)
    customer_name = _extract_cart_customer_name(payload)
    line_items = _extract_cart_line_items(payload)
    total_price = Decimal("0.00")
    # Calculate total price of cart items (Shopify cart items are priced in cents/paise)
    for item in line_items:
        try:
            raw_price = Decimal(str(item.get("price", "0.00")))
            price_val = raw_price / 100
            item["price"] = str(price_val)
            total_price += price_val * item.get("quantity", 1)
        except Exception:
            pass

    currency = payload.get("currency", "INR")

    # Construct checkout / cart permalink
    cart_url = _construct_cart_permalink(shop_domain, line_items)

    cart_data = {
        "line_items": line_items,
        "cart_url": cart_url,
        "customer": payload.get("customer", {}),
    }

    logger.info(
        f"[{shop_domain}] Cart {cart_id}: "
        f"customer={customer_name}, phone={customer_phone}, "
        f"total={total_price} {currency}, items={len(line_items)}"
    )

    is_new_cart = False

    async with async_session_factory() as db:
        # Check store
        store_result = await db.execute(
            select(Store).where(Store.shopify_domain == shop_domain)
        )
        store = store_result.scalar_one_or_none()

        if not store:
            logger.warning(f"[{shop_domain}] Store not found, skipping webhook")
            return {"status": "skipped", "reason": "store_not_found"}

        if not store.is_active or not store.cart_recovery_active:
            logger.info(f"[{shop_domain}] Store or cart recovery is inactive, skipping")
            return {"status": "skipped", "reason": "cart_recovery_inactive"}

        # PREMIUM PLAN CHECK
        if store.subscription_plan not in ("GROWTH", "SCALE"):
            logger.info(
                f"[{shop_domain}] Cart Abandonment requires a premium plan (GROWTH/SCALE). "
                f"Store plan is {store.subscription_plan}. Skipping."
            )
            return {"status": "skipped", "reason": "premium_plan_required"}

        # Check if cart already exists
        existing = await db.execute(
            select(AbandonedCart).where(
                AbandonedCart.cart_id == cart_id
            )
        )
        cart = existing.scalar_one_or_none()

        if cart:
            # Update existing cart
            cart.customer_phone = customer_phone or cart.customer_phone
            cart.customer_name = customer_name or cart.customer_name
            cart.cart_json = cart_data
            cart.total_price = total_price
            cart.currency = currency
            logger.info(f"[{shop_domain}] Updated existing cart {cart_id}")
        else:
            # Insert new abandoned cart
            cart = AbandonedCart(
                cart_id=cart_id,
                shopify_domain=shop_domain,
                customer_name=customer_name,
                customer_phone=customer_phone,
                cart_json=cart_data,
                total_price=total_price,
                currency=currency,
                recovery_status="PENDING",
                created_at=datetime.now(timezone.utc),
            )
            db.add(cart)
            is_new_cart = True
            logger.info(f"[{shop_domain}] Created new cart {cart_id}")

        await db.commit()

    # Trigger recovery task
    if is_new_cart and customer_phone:
        background_tasks.add_task(
            _trigger_cart_recovery_workflow, cart_id, shop_domain
        )
        logger.info(
            f"[{shop_domain}] Cart recovery workflow queued for cart {cart_id}"
        )
    elif is_new_cart and not customer_phone:
        logger.info(
            f"[{shop_domain}] Cart {cart_id} has no phone (not logged in) — "
            f"cannot send WhatsApp, marking as FAILED"
        )
        async with async_session_factory() as db:
            await db.execute(
                update(AbandonedCart)
                .where(AbandonedCart.cart_id == cart_id)
                .values(recovery_status="FAILED")
            )
            await db.commit()

    return {"status": "received", "cart_id": cart_id}


async def _trigger_cart_recovery_workflow(cart_id: str, shop_domain: str):
    """
    Dispatches the Celery cart recovery workflow.
    This runs in a background thread to avoid blocking the webhook response.
    """
    try:
        from tasks import schedule_cart_recovery_workflow
        schedule_cart_recovery_workflow(cart_id, shop_domain)
    except Exception as e:
        logger.error(
            f"[{shop_domain}] Failed to schedule cart recovery for {cart_id}: {e}"
        )

