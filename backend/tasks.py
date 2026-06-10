"""
RecoverFlow AI — Block 5: Celery Worker & Automated Flow Engine
=================================================================
Background task system that orchestrates the multi-step WhatsApp
recovery campaign for abandoned checkouts.

Core responsibilities:
  • Schedule 3-step timed recovery reminders (30m, 6h, 24h)
  • Verify checkout hasn't been recovered before sending
  • Check merchant credit balance before dispatching
  • Generate AI-personalized messages via Gemini
  • Dispatch messages via Meta WhatsApp Cloud API
  • Deduct credits and log sent messages
  • Store Celery task IDs for revocation on recovery

Uses SYNCHRONOUS database access (psycopg2) since Celery
workers don't run in an async event loop.
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from celery import Celery
from sqlalchemy import update

from config import get_settings
from database import get_sync_db
from models import (
    Store,
    CreditLedger,
    AbandonedCheckout,
    RecoverySchedule,
    SentMessage,
    AbandonedCart,
    CartRecoverySchedule,
)

logger = logging.getLogger("recoverflow.tasks")
settings = get_settings()

# ═════════════════════════════════════════════════════════════
#  CELERY APPLICATION
# ═════════════════════════════════════════════════════════════

celery_app = Celery(
    "recoverflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,              # Re-deliver if worker crashes mid-task
    worker_prefetch_multiplier=1,     # Fair scheduling across workers
    task_default_queue="default",
    task_routes={
        "tasks.send_whatsapp_reminder_task": {"queue": "recovery"},
        "tasks.send_cart_reminder_task": {"queue": "recovery"},
    },
)


# ═════════════════════════════════════════════════════════════
#  STEP DELAY CONFIGURATION
# ═════════════════════════════════════════════════════════════

def _get_step_delay(step: int) -> int:
    """Returns the delay in seconds for each recovery step."""
    delays = {
        1: settings.RECOVERY_STEP_1_DELAY,   # 30 minutes
        2: settings.RECOVERY_STEP_2_DELAY,   # 6 hours
        3: settings.RECOVERY_STEP_3_DELAY,   # 24 hours
    }
    return delays.get(step, 86400)  # Default 24h for any extra steps


# ═════════════════════════════════════════════════════════════
#  SCHEDULE RECOVERY WORKFLOW
# ═════════════════════════════════════════════════════════════

def schedule_recovery_workflow(checkout_id: str, shop_domain: str):
    """
    Entry point called by the webhook handler after a new
    abandoned checkout is detected.

    Creates 3 recovery schedule entries and dispatches Celery
    tasks with appropriate countdown delays.

    Each task ID is stored in the recovery_schedules table so
    it can be revoked if the customer completes their purchase.
    """
    logger.info(
        f"[{shop_domain}] Scheduling 3-step recovery for checkout {checkout_id}"
    )

    with get_sync_db() as db:
        now = datetime.now(timezone.utc)
        # Mark the checkout as PROCESSING
        checkout = db.query(AbandonedCheckout).get(checkout_id)
        if not checkout:
            logger.error(f"Checkout {checkout_id} not found for scheduling")
            return

        checkout.recovery_status = "PROCESSING"

        # AI Classification & Segmentation
        try:
            store = db.query(Store).get(shop_domain)
            is_premium = store and store.subscription_plan in ("GROWTH", "SCALE")
            if is_premium:
                from ai_engine import classify_customer_segment
                cart_json = checkout.cart_json or {}
                customer = cart_json.get("customer", {}) or {}
                orders_count = int(customer.get("orders_count") or 0)
                total_spent = float(customer.get("total_spent") or 0.0)
                customer_tags = customer.get("tags", "")
                has_discounts = len(cart_json.get("discount_codes", [])) > 0
                cart_value = float(checkout.total_price or 0.0)

                segment = classify_customer_segment(
                    orders_count=orders_count,
                    total_spent=total_spent,
                    cart_value=cart_value,
                    has_discounts=has_discounts,
                    tags=customer_tags,
                )
                checkout.customer_segment = segment
                logger.info(f"[{shop_domain}] Classified checkout {checkout_id} as segment: {segment}")
            else:
                checkout.customer_segment = "STANDARD"
                logger.info(f"[{shop_domain}] Store on non-premium plan, defaulting to STANDARD segment")
        except Exception as e:
            logger.error(f"[{shop_domain}] Failed to classify segment for checkout {checkout_id}: {e}")

        is_scale = store and store.subscription_plan == "SCALE"
        target_queue = "priority" if is_scale else "recovery"

        for step in [1, 2, 3]:
            delay_seconds = _get_step_delay(step)
            scheduled_time = now + timedelta(seconds=delay_seconds)

            # Dispatch the Celery task with countdown
            task_result = send_whatsapp_reminder_task.apply_async(
                args=[checkout_id, shop_domain, step],
                countdown=delay_seconds,
                queue=target_queue,
            )

            # Record the schedule with the Celery task ID
            schedule = RecoverySchedule(
                checkout_id=checkout_id,
                step_number=step,
                scheduled_for=scheduled_time,
                status="QUEUED",
                celery_task_id=task_result.id,
            )
            db.add(schedule)

            logger.info(
                f"[{shop_domain}] Step {step}: scheduled for "
                f"{scheduled_time.isoformat()} (delay={delay_seconds}s, "
                f"task_id={task_result.id})"
            )

        db.commit()


# ═════════════════════════════════════════════════════════════
#  CORE TASK: Send WhatsApp Reminder
# ═════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="tasks.send_whatsapp_reminder_task",
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def send_whatsapp_reminder_task(self, checkout_id: str, shop_domain: str, step: int):
    """
    Executes a single recovery reminder step.

    Pre-flight checks (any failure stops execution):
      1. Checkout still exists and is recoverable (not RECOVERED)
      2. Store is active
      3. Store has WhatsApp credentials configured
      4. Merchant has credits remaining

    Execution:
      5. Generate personalized message via Gemini AI
      6. Dispatch via Meta WhatsApp Cloud API
      7. Deduct credit from merchant's ledger
      8. Log the sent message for analytics
      9. Update recovery schedule status
    """
    task_id = self.request.id
    logger.info(
        f"[{shop_domain}] Executing step {step} for checkout {checkout_id} "
        f"(task_id={task_id})"
    )

    with get_sync_db() as db:
        # ── 1. Verify checkout is still recoverable ──────────
        checkout = db.query(AbandonedCheckout).get(checkout_id)

        if not checkout:
            logger.warning(f"Checkout {checkout_id} no longer exists, aborting")
            _update_schedule_status(db, checkout_id, step, "CANCELLED")
            return {"status": "aborted", "reason": "checkout_not_found"}

        if not checkout.is_recoverable:
            logger.info(
                f"[{shop_domain}] Checkout {checkout_id} status is "
                f"{checkout.recovery_status}, skipping step {step}"
            )
            _update_schedule_status(db, checkout_id, step, "CANCELLED")
            return {"status": "skipped", "reason": f"status_{checkout.recovery_status}"}

        if not checkout.customer_phone:
            logger.warning(
                f"[{shop_domain}] Checkout {checkout_id} has no phone number"
            )
            _update_schedule_status(db, checkout_id, step, "FAILED")
            return {"status": "failed", "reason": "no_phone"}

        # ── 2. Verify store is active ────────────────────────
        store = db.query(Store).get(shop_domain)

        if not store or not store.is_active:
            logger.warning(f"[{shop_domain}] Store inactive or not found, aborting")
            _update_schedule_status(db, checkout_id, step, "CANCELLED")
            return {"status": "aborted", "reason": "store_inactive"}

        # ── 3. Verify WhatsApp credentials ───────────────────
        wa_phone_id = store.whatsapp_phone_number_id or settings.WHATSAPP_DEFAULT_PHONE_NUMBER_ID
        wa_token = store.whatsapp_access_token or settings.WHATSAPP_DEFAULT_ACCESS_TOKEN

        if not wa_phone_id or not wa_token:
            logger.error(
                f"[{shop_domain}] WhatsApp credentials not configured, aborting"
            )
            _update_schedule_status(db, checkout_id, step, "FAILED")
            return {"status": "failed", "reason": "whatsapp_not_configured"}

        # ── 4. Verify credit balance ─────────────────────────
        ledger = db.query(CreditLedger).get(shop_domain)

        if not ledger or not ledger.has_credits():
            logger.warning(
                f"[{shop_domain}] Credits exhausted "
                f"(remaining={ledger.credits_remaining if ledger else 0}), "
                f"stopping recovery for {checkout_id}"
            )
            checkout.recovery_status = "EXHAUSTED"
            _update_schedule_status(db, checkout_id, step, "FAILED")
            db.commit()
            return {"status": "failed", "reason": "credits_exhausted"}

        # ── 5. Generate AI message ───────────────────────────
        cart_items = checkout.cart_json.get("line_items", [])
        checkout_url = checkout.cart_json.get("checkout_url", "")
        store_name = store.store_name or shop_domain.split(".")[0].title()
        tone = store.brand_tone or "friendly"

        try:
            from ai_engine import generate_personalized_recovery_message
            message_body = generate_personalized_recovery_message(
                store_name=store_name,
                tone=tone,
                customer_name=checkout.customer_name or "there",
                items=cart_items,
                checkout_url=checkout_url,
                step=step,
                customer_segment=checkout.customer_segment,
            )
        except Exception as e:
            logger.error(
                f"[{shop_domain}] Gemini message generation failed: {e}"
            )
            # Fallback to a simple template
            items_text = ", ".join(
                [f"{item.get('quantity', 1)}x {item.get('title', 'item')}" for item in cart_items[:3]]
            )
            message_body = (
                f"Hi {checkout.customer_name or 'there'}! "
                f"You left some items in your cart at {store_name}: {items_text}. "
                f"Complete your order here: {checkout_url}"
            )

        # ── 6. Dispatch via WhatsApp ─────────────────────────
        whatsapp_message_id = None
        send_status = "SENT"
        error_message = None

        try:
            from whatsapp import dispatch_whatsapp_message
            result = dispatch_whatsapp_message(
                phone_number_id=wa_phone_id,
                access_token=wa_token,
                to_phone=checkout.customer_phone,
                message_body=message_body,
            )

            # Check Meta API response for success
            if "messages" in result and len(result["messages"]) > 0:
                whatsapp_message_id = result["messages"][0].get("id")
                logger.info(
                    f"[{shop_domain}] WhatsApp message sent successfully "
                    f"(wa_id={whatsapp_message_id})"
                )
            elif "error" in result:
                send_status = "FAILED"
                error_message = result["error"].get("message", str(result["error"]))
                logger.error(
                    f"[{shop_domain}] WhatsApp API error: {error_message}"
                )
            else:
                send_status = "FAILED"
                error_message = f"Unexpected response: {result}"
                logger.error(f"[{shop_domain}] {error_message}")

        except Exception as e:
            send_status = "FAILED"
            error_message = str(e)
            logger.error(
                f"[{shop_domain}] WhatsApp dispatch exception: {e}"
            )

        # ── 7. Deduct credit (only on successful send) ──────
        if send_status == "SENT":
            deducted = ledger.deduct(amount=1)
            if not deducted:
                logger.warning(f"[{shop_domain}] Credit deduction race condition")

        # ── 8. Log sent message ──────────────────────────────
        sent_msg = SentMessage(
            checkout_id=checkout_id,
            shopify_domain=shop_domain,
            step_number=step,
            message_body=message_body,
            template_variant=None,
            credits_used=1 if send_status == "SENT" else 0,
            status=send_status,
            error_message=error_message,
            whatsapp_message_id=whatsapp_message_id,
        )
        db.add(sent_msg)

        # ── 9. Update recovery schedule ──────────────────────
        _update_schedule_status(db, checkout_id, step, send_status)

        # If all 3 steps are done and checkout still not recovered,
        # mark as EXHAUSTED (no more automatic attempts)
        if step == 3 and checkout.recovery_status == "PROCESSING":
            checkout.recovery_status = "EXHAUSTED"
            logger.info(
                f"[{shop_domain}] All recovery steps exhausted for {checkout_id}"
            )

        db.commit()

    # ── Retry on failure ─────────────────────────────────────
    if send_status == "FAILED" and self.request.retries < self.max_retries:
        logger.info(
            f"[{shop_domain}] Retrying step {step} for {checkout_id} "
            f"(attempt {self.request.retries + 1}/{self.max_retries})"
        )
        raise self.retry(exc=Exception(error_message))

    return {
        "status": send_status.lower(),
        "checkout_id": checkout_id,
        "step": step,
        "whatsapp_message_id": whatsapp_message_id,
    }


# ═════════════════════════════════════════════════════════════
#  HELPER: Update Schedule Status
# ═════════════════════════════════════════════════════════════

def _update_schedule_status(db, checkout_id: str, step: int, status: str):
    """Updates the recovery_schedules row for the given checkout + step."""
    schedule = (
        db.query(RecoverySchedule)
        .filter(
            RecoverySchedule.checkout_id == checkout_id,
            RecoverySchedule.step_number == step,
        )
        .first()
    )
    if schedule:
        schedule.status = status


# ═════════════════════════════════════════════════════════════
#  SCHEDULE CART RECOVERY WORKFLOW
# ═════════════════════════════════════════════════════════════

def schedule_cart_recovery_workflow(cart_id: str, shop_domain: str):
    """
    Entry point called by the webhook handler after a new
    abandoned cart is detected.

    Creates a cart recovery schedule entry and dispatches Celery
    task with 12h delay countdown.
    """
    logger.info(
        f"[{shop_domain}] Scheduling cart recovery for cart {cart_id}"
    )

    with get_sync_db() as db:
        cart = db.query(AbandonedCart).get(cart_id)
        if not cart:
            logger.error(f"Cart {cart_id} not found for scheduling")
            return

        cart.recovery_status = "PROCESSING"

        # AI Classification & Segmentation
        try:
            store = db.query(Store).get(shop_domain)
            is_premium = store and store.subscription_plan in ("GROWTH", "SCALE")
            if is_premium:
                from ai_engine import classify_customer_segment
                cart_json = cart.cart_json or {}
                customer = cart_json.get("customer", {}) or {}
                orders_count = int(customer.get("orders_count") or 0)
                total_spent = float(customer.get("total_spent") or 0.0)
                customer_tags = customer.get("tags", "")
                has_discounts = len(cart_json.get("discount_codes", [])) > 0
                cart_value = float(cart.total_price or 0.0)

                segment = classify_customer_segment(
                    orders_count=orders_count,
                    total_spent=total_spent,
                    cart_value=cart_value,
                    has_discounts=has_discounts,
                    tags=customer_tags,
                )
                cart.customer_segment = segment
                logger.info(f"[{shop_domain}] Classified cart {cart_id} as segment: {segment}")
            else:
                cart.customer_segment = "STANDARD"
                logger.info(f"[{shop_domain}] Store on non-premium plan, defaulting to STANDARD segment")
        except Exception as e:
            logger.error(f"[{shop_domain}] Failed to classify segment for cart {cart_id}: {e}")

        now = datetime.now(timezone.utc)
        # 12 hours delay (43200 seconds)
        delay_seconds = 43200
        scheduled_time = now + timedelta(seconds=delay_seconds)

        is_scale = store and store.subscription_plan == "SCALE"
        target_queue = "priority" if is_scale else "recovery"

        # Dispatch the Celery task with countdown
        task_result = send_cart_reminder_task.apply_async(
            args=[cart_id, shop_domain],
            countdown=delay_seconds,
            queue=target_queue,
        )

        # Record the schedule
        schedule = CartRecoverySchedule(
            cart_id=cart_id,
            scheduled_for=scheduled_time,
            status="QUEUED",
            celery_task_id=task_result.id,
        )
        db.add(schedule)

        logger.info(
            f"[{shop_domain}] Cart recovery scheduled for "
            f"{scheduled_time.isoformat()} (delay={delay_seconds}s, "
            f"task_id={task_result.id})"
        )

        db.commit()


# ═════════════════════════════════════════════════════════════
#  CORE TASK: Send Cart Recovery Reminder
# ═════════════════════════════════════════════════════════════

@celery_app.task(
    bind=True,
    name="tasks.send_cart_reminder_task",
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def send_cart_reminder_task(self, cart_id: str, shop_domain: str):
    """
    Executes a single cart recovery reminder.
    """
    task_id = self.request.id
    logger.info(
        f"[{shop_domain}] Executing cart recovery for cart {cart_id} "
        f"(task_id={task_id})"
    )

    with get_sync_db() as db:
        # 1. Verify cart is still recoverable
        cart = db.query(AbandonedCart).get(cart_id)

        if not cart:
            logger.warning(f"Cart {cart_id} no longer exists, aborting")
            _update_cart_schedule_status(db, cart_id, "CANCELLED")
            return {"status": "aborted", "reason": "cart_not_found"}

        if not cart.is_recoverable:
            logger.info(
                f"[{shop_domain}] Cart {cart_id} status is "
                f"{cart.recovery_status}, skipping recovery"
            )
            _update_cart_schedule_status(db, cart_id, "CANCELLED")
            return {"status": "skipped", "reason": f"status_{cart.recovery_status}"}

        if not cart.customer_phone:
            logger.warning(
                f"[{shop_domain}] Cart {cart_id} has no phone number"
            )
            _update_cart_schedule_status(db, cart_id, "FAILED")
            return {"status": "failed", "reason": "no_phone"}

        # 2. Verify store is active and has premium subscription
        store = db.query(Store).get(shop_domain)

        if not store or not store.is_active or not store.cart_recovery_active:
            logger.warning(f"[{shop_domain}] Store or cart recovery inactive, aborting")
            _update_cart_schedule_status(db, cart_id, "CANCELLED")
            return {"status": "aborted", "reason": "store_inactive"}

        if store.subscription_plan not in ("GROWTH", "SCALE"):
            logger.warning(f"[{shop_domain}] Cart Abandonment requires premium subscription, aborting")
            _update_cart_schedule_status(db, cart_id, "CANCELLED")
            return {"status": "aborted", "reason": "premium_plan_required"}

        # 3. Verify WhatsApp credentials
        wa_phone_id = store.whatsapp_phone_number_id or settings.WHATSAPP_DEFAULT_PHONE_NUMBER_ID
        wa_token = store.whatsapp_access_token or settings.WHATSAPP_DEFAULT_ACCESS_TOKEN

        if not wa_phone_id or not wa_token:
            logger.error(
                f"[{shop_domain}] WhatsApp credentials not configured, aborting"
            )
            _update_cart_schedule_status(db, cart_id, "FAILED")
            return {"status": "failed", "reason": "whatsapp_not_configured"}

        # 4. Verify credit balance
        ledger = db.query(CreditLedger).get(shop_domain)

        if not ledger or not ledger.has_credits():
            logger.warning(
                f"[{shop_domain}] Credits exhausted, stopping recovery for cart {cart_id}"
            )
            cart.recovery_status = "EXHAUSTED"
            _update_cart_schedule_status(db, cart_id, "FAILED")
            db.commit()
            return {"status": "failed", "reason": "credits_exhausted"}

        # 5. Generate AI message
        cart_items = cart.cart_json.get("line_items", [])
        cart_url = cart.cart_json.get("cart_url", "")
        store_name = store.store_name or shop_domain.split(".")[0].title()
        tone = store.brand_tone or "friendly"

        try:
            from ai_engine import generate_personalized_recovery_message
            message_body = generate_personalized_recovery_message(
                store_name=store_name,
                tone=tone,
                customer_name=cart.customer_name or "there",
                items=cart_items,
                checkout_url=cart_url,
                step=1,
                is_cart_recovery=True,
                customer_segment=cart.customer_segment,
            )
        except Exception as e:
            logger.error(
                f"[{shop_domain}] Gemini message generation failed: {e}"
            )
            items_text = ", ".join(
                [f"{item.get('quantity', 1)}x {item.get('title', 'item')}" for item in cart_items[:3]]
            )
            message_body = (
                f"Hi {cart.customer_name or 'there'}! "
                f"You added some items to your cart at {store_name}: {items_text}. "
                f"They are waiting for you! Reopen your cart here: {cart_url}"
            )

        # 6. Dispatch via WhatsApp
        whatsapp_message_id = None
        send_status = "SENT"
        error_message = None

        try:
            from whatsapp import dispatch_whatsapp_message
            result = dispatch_whatsapp_message(
                phone_number_id=wa_phone_id,
                access_token=wa_token,
                to_phone=cart.customer_phone,
                message_body=message_body,
            )

            if "messages" in result and len(result["messages"]) > 0:
                whatsapp_message_id = result["messages"][0].get("id")
                logger.info(
                    f"[{shop_domain}] WhatsApp message sent successfully "
                    f"(wa_id={whatsapp_message_id})"
                )
            elif "error" in result:
                send_status = "FAILED"
                error_message = result["error"].get("message", str(result["error"]))
                logger.error(
                    f"[{shop_domain}] WhatsApp API error: {error_message}"
                )
            else:
                send_status = "FAILED"
                error_message = f"Unexpected response: {result}"
                logger.error(f"[{shop_domain}] {error_message}")

        except Exception as e:
            send_status = "FAILED"
            error_message = str(e)
            logger.error(
                f"[{shop_domain}] WhatsApp dispatch exception: {e}"
            )

        # 7. Deduct credit (only on successful send)
        if send_status == "SENT":
            deducted = ledger.deduct(amount=1)
            if not deducted:
                logger.warning(f"[{shop_domain}] Credit deduction race condition")

        # 8. Log sent message
        sent_msg = SentMessage(
            cart_id=cart_id,
            shopify_domain=shop_domain,
            step_number=1,
            message_body=message_body,
            template_variant=None,
            credits_used=1 if send_status == "SENT" else 0,
            status=send_status,
            error_message=error_message,
            whatsapp_message_id=whatsapp_message_id,
        )
        db.add(sent_msg)

        # 9. Update recovery schedule & cart recovery status
        _update_cart_schedule_status(db, cart_id, send_status)

        if send_status == "SENT":
            cart.recovery_status = "EXHAUSTED"
        else:
            cart.recovery_status = "FAILED"

        db.commit()

    # Retry on failure
    if send_status == "FAILED" and self.request.retries < self.max_retries:
        logger.info(
            f"[{shop_domain}] Retrying cart recovery for {cart_id} "
            f"(attempt {self.request.retries + 1}/{self.max_retries})"
        )
        raise self.retry(exc=Exception(error_message))

    return {
        "status": send_status.lower(),
        "cart_id": cart_id,
        "whatsapp_message_id": whatsapp_message_id,
    }


def _update_cart_schedule_status(db, cart_id: str, status: str):
    """Updates the cart_recovery_schedules row for the given cart."""
    schedule = (
        db.query(CartRecoverySchedule)
        .filter(
            CartRecoverySchedule.cart_id == cart_id,
        )
        .first()
    )
    if schedule:
        schedule.status = status
