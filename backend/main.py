"""
RecoverFlow AI — FastAPI Gateway & Session Validation
=======================================================
Core application entry point.
Handles:
  • CORS configuration
  • Shopify App Bridge JWT verification
  • Dashboard metrics API
  • Router mounting for webhooks
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import httpx
import jwt
from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from whatsapp import verify_whatsapp_credentials
from models import (
    Store,
    CreditLedger,
    AbandonedCheckout,
    SentMessage,
    RecoveredOrder,
)

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("recoverflow")

# ── Settings ─────────────────────────────────────────────────
settings = get_settings()

# ── FastAPI Application ──────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Shopify abandoned cart recovery engine powered by WhatsApp & Gemini AI.",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# ── CORS Middleware ──────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═════════════════════════════════════════════════════════════
#  SECURITY: Shopify App Bridge JWT Verification
# ═════════════════════════════════════════════════════════════
async def verify_shopify_token(
    authorization: Optional[str] = Header(None),
    x_shopify_shop_domain: Optional[str] = Header(None),
) -> dict:
    """
    Validates the short-lived JWT issued by Shopify App Bridge.

    Token structure (decoded):
      iss: https://{shop-domain}/admin
      dest: https://{shop-domain}
      aud: {SHOPIFY_API_KEY}
      sub: {user-id}
      exp: unix timestamp
      iat: unix timestamp
      jti: unique token id

    Verification steps:
      1. Extract Bearer token from Authorization header
      2. Decode with SHOPIFY_API_SECRET (HS256)
      3. Validate audience matches SHOPIFY_API_KEY
      4. Validate dest domain matches x-shopify-shop-domain header
      5. PyJWT auto-validates exp (expiration)
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.split(" ", 1)[1]

    try:
        # Check if Shopify API Secret or Key is not set or has placeholder values
        bypass_signature = (
            not settings.SHOPIFY_API_SECRET 
            or "secret" in settings.SHOPIFY_API_SECRET.lower()
            or not settings.SHOPIFY_API_KEY
            or "key" in settings.SHOPIFY_API_KEY.lower()
        )
        
        if bypass_signature:
            logger.warning("Bypassing Shopify JWT signature verification for local development.")
            payload = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False}
            )
        else:
            payload = jwt.decode(
                token,
                settings.SHOPIFY_API_SECRET,
                algorithms=["HS256"],
                audience=settings.SHOPIFY_API_KEY,
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Please reload the app.",
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token audience does not match this application.",
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid Shopify token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )

    # Cross-check the destination domain
    token_dest = payload.get("dest", "")
    expected_dest = f"https://{x_shopify_shop_domain}"
    if x_shopify_shop_domain and token_dest != expected_dest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Domain mismatch: token dest={token_dest}, header={expected_dest}",
        )

    return payload


def _extract_shop_domain(token_payload: dict) -> str:
    """Extract the bare shop domain from the JWT dest claim."""
    return token_payload.get("dest", "").replace("https://", "")


# ═════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ═════════════════════════════════════════════════════════════
@app.get("/health", tags=["Health"])
async def health_check():
    """Simple liveness probe for container orchestration."""
    return {"status": "healthy", "service": settings.APP_NAME, "version": settings.APP_VERSION}


# ═════════════════════════════════════════════════════════════
#  DASHBOARD METRICS API
# ═════════════════════════════════════════════════════════════
@app.get("/api/v1/dashboard", tags=["Dashboard"])
async def get_dashboard_metrics(
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the primary dashboard metrics for the authenticated store.

    Metrics returned:
      • Recovered Revenue (total)
      • Recovered Orders (count)
      • Recovery Rate (%)
      • Messages Sent (count)
      • Credits Remaining
      • Revenue Per Message
      • Potential Revenue Lost (abandoned but not recovered)
      • Revenue Opportunity Score
    """
    shop = _extract_shop_domain(token_payload)

    # ── Recovered Revenue & Order Count ──────────────────────
    recovered_result = await db.execute(
        select(
            sqlfunc.coalesce(sqlfunc.sum(RecoveredOrder.recovered_revenue), 0),
            sqlfunc.count(RecoveredOrder.id),
        ).where(RecoveredOrder.shopify_domain == shop)
    )
    recovered_revenue, recovered_orders = recovered_result.one()

    # ── Total Abandoned Checkouts ────────────────────────────
    total_abandoned = await db.execute(
        select(sqlfunc.count(AbandonedCheckout.checkout_id)).where(
            AbandonedCheckout.shopify_domain == shop
        )
    )
    total_abandoned_count = total_abandoned.scalar_one()

    # ── Messages Sent ────────────────────────────────────────
    messages_result = await db.execute(
        select(sqlfunc.count(SentMessage.id)).where(
            SentMessage.shopify_domain == shop,
            SentMessage.status == "SENT",
        )
    )
    messages_sent = messages_result.scalar_one()

    # ── Credits Remaining ────────────────────────────────────
    ledger = await db.execute(
        select(CreditLedger).where(CreditLedger.shopify_domain == shop)
    )
    ledger_row = ledger.scalar_one_or_none()
    credits_remaining = ledger_row.credits_remaining if ledger_row else 0

    # ── Potential Revenue Lost (not recovered) ───────────────
    lost_result = await db.execute(
        select(
            sqlfunc.coalesce(sqlfunc.sum(AbandonedCheckout.total_price), 0)
        ).where(
            AbandonedCheckout.shopify_domain == shop,
            AbandonedCheckout.recovery_status.in_(["PENDING", "PROCESSING", "FAILED", "EXHAUSTED"]),
        )
    )
    potential_lost = lost_result.scalar_one()

    # ── Derived Metrics ──────────────────────────────────────
    recovery_rate = (
        round((recovered_orders / total_abandoned_count) * 100, 1)
        if total_abandoned_count > 0
        else 0.0
    )
    revenue_per_message = (
        round(float(recovered_revenue) / messages_sent, 2)
        if messages_sent > 0
        else 0.0
    )
    # Opportunity Score: % of lost revenue that is potentially recoverable
    # (uses industry average ~43% recovery ceiling)
    recoverable_estimate = round(float(potential_lost) * 0.43, 2)

    return {
        "status": "success",
        "shop": shop,
        "metrics": {
            "recovered_revenue": float(recovered_revenue),
            "recovered_orders": recovered_orders,
            "recovery_rate": recovery_rate,
            "messages_sent": messages_sent,
            "credits_remaining": credits_remaining,
            "revenue_per_message": revenue_per_message,
            "potential_revenue_lost": float(potential_lost),
            "recoverable_revenue_estimate": recoverable_estimate,
            "total_abandoned_carts": total_abandoned_count,
        },
    }



# ═════════════════════════════════════════════════════════════
#  STORE INFO & SETTINGS API
# ═════════════════════════════════════════════════════════════
from pydantic import BaseModel, Field

class StoreSettingsUpdate(BaseModel):
    store_name: Optional[str] = Field(None, max_length=255)
    brand_tone: Optional[str] = Field(None, max_length=50)
    whatsapp_phone_number_id: Optional[str] = Field(None, max_length=100)
    whatsapp_access_token: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None
    cart_recovery_active: Optional[bool] = None
    reminder_count: Optional[int] = Field(None, ge=1, le=3)
    step_1_delay: Optional[int] = Field(None, ge=1)
    step_2_delay: Optional[int] = Field(None, ge=1)
    step_3_delay: Optional[int] = Field(None, ge=1)

@app.get("/api/v1/store", tags=["Store"])
async def get_store_info(
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """Returns the authenticated store's profile and plan details."""
    shop = _extract_shop_domain(token_payload)

    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar_one_or_none()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Store {shop} not found. Has the app been installed?",
        )

    # Fetch credit ledger too
    ledger_result = await db.execute(
        select(CreditLedger).where(CreditLedger.shopify_domain == shop)
    )
    ledger = ledger_result.scalar_one_or_none()
    credits_remaining = ledger.credits_remaining if ledger else 0

    return {
        "status": "success",
        "store": {
            "shopify_domain": store.shopify_domain,
            "store_name": store.store_name,
            "subscription_plan": store.subscription_plan,
            "brand_tone": store.brand_tone,
            "whatsapp_phone_number_id": store.whatsapp_phone_number_id,
            "whatsapp_access_token": store.whatsapp_access_token,
            "is_active": store.is_active,
            "cart_recovery_active": store.cart_recovery_active,
            "reminder_count": store.reminder_count,
            "step_1_delay": store.step_1_delay,
            "step_2_delay": store.step_2_delay,
            "step_3_delay": store.step_3_delay,
            "credits_remaining": credits_remaining,
            "created_at": store.created_at.isoformat() if store.created_at else None,
        },
    }

@app.post("/api/v1/store/settings", tags=["Store"])
async def update_store_settings(
    payload: StoreSettingsUpdate,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """Updates settings for the authenticated store."""
    shop = _extract_shop_domain(token_payload)

    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar_one_or_none()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        )

    # Update fields if provided
    if payload.store_name is not None:
        store.store_name = payload.store_name
    if payload.brand_tone is not None:
        store.brand_tone = payload.brand_tone
    if payload.whatsapp_phone_number_id is not None:
        store.whatsapp_phone_number_id = payload.whatsapp_phone_number_id
    if payload.whatsapp_access_token is not None:
        store.whatsapp_access_token = payload.whatsapp_access_token
    if payload.is_active is not None:
        store.is_active = payload.is_active
    if payload.cart_recovery_active is not None:
        store.cart_recovery_active = payload.cart_recovery_active
    if payload.reminder_count is not None:
        store.reminder_count = payload.reminder_count
    if payload.step_1_delay is not None:
        store.step_1_delay = payload.step_1_delay
    if payload.step_2_delay is not None:
        store.step_2_delay = payload.step_2_delay
    if payload.step_3_delay is not None:
        store.step_3_delay = payload.step_3_delay

    await db.commit()
    return {"status": "success", "message": "Settings updated successfully"}


class WhatsAppConfigVerify(BaseModel):
    whatsapp_phone_number_id: str = Field(..., max_length=100)
    whatsapp_access_token: str = Field(..., max_length=512)
    whatsapp_business_id: str = Field(..., max_length=100)


@app.post("/api/v1/whatsapp/config", tags=["WhatsApp"])
async def verify_and_save_whatsapp_config(
    payload: WhatsAppConfigVerify,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Verifies Meta WhatsApp Cloud API credentials.
    If valid, saves them to the store settings in PostgreSQL.
    """
    shop = _extract_shop_domain(token_payload)

    # 1. Verify credentials with Meta API
    verification = verify_whatsapp_credentials(
        phone_number_id=payload.whatsapp_phone_number_id,
        access_token=payload.whatsapp_access_token,
    )

    if not verification.get("verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verification.get("error", "Failed to verify credentials with Meta"),
        )

    # 2. Retrieve store and save
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar_one_or_none()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        )

    store.whatsapp_phone_number_id = payload.whatsapp_phone_number_id
    store.whatsapp_access_token = payload.whatsapp_access_token
    store.whatsapp_business_id = payload.whatsapp_business_id

    await db.commit()

    return {
        "status": "success",
        "message": "Connection verified and saved successfully",
        "verified_details": verification,
    }


# ═════════════════════════════════════════════════════════════
#  DASHBOARD LISTS API
# ═════════════════════════════════════════════════════════════

@app.get("/api/v1/dashboard/checkouts", tags=["Dashboard"])
async def get_dashboard_checkouts(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """Returns a list of recently abandoned checkouts for the store."""
    shop = _extract_shop_domain(token_payload)

    query = select(AbandonedCheckout).where(AbandonedCheckout.shopify_domain == shop)
    if status_filter:
        query = query.where(AbandonedCheckout.recovery_status == status_filter.upper())
    
    query = query.order_by(AbandonedCheckout.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    checkouts = result.scalars().all()

    return {
        "status": "success",
        "checkouts": [
            {
                "checkout_id": c.checkout_id,
                "customer_name": c.customer_name,
                "customer_phone": c.customer_phone,
                "cart_json": c.cart_json,
                "total_price": float(c.total_price),
                "currency": c.currency,
                "recovery_status": c.recovery_status,
                "customer_segment": c.customer_segment,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "recovered_at": c.recovered_at.isoformat() if c.recovered_at else None,
            }
            for c in checkouts
        ]
    }

@app.get("/api/v1/dashboard/messages", tags=["Dashboard"])
async def get_dashboard_messages(
    limit: int = 50,
    offset: int = 0,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """Returns a list of sent recovery messages for the store."""
    shop = _extract_shop_domain(token_payload)

    query = (
        select(SentMessage, AbandonedCheckout.customer_name)
        .join(AbandonedCheckout, SentMessage.checkout_id == AbandonedCheckout.checkout_id)
        .where(SentMessage.shopify_domain == shop)
        .order_by(SentMessage.sent_at.desc())
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(query)
    rows = result.all()

    return {
        "status": "success",
        "messages": [
            {
                "id": m.SentMessage.id,
                "checkout_id": m.SentMessage.checkout_id,
                "customer_name": m.customer_name,
                "step_number": m.SentMessage.step_number,
                "message_body": m.SentMessage.message_body,
                "credits_used": m.SentMessage.credits_used,
                "status": m.SentMessage.status,
                "error_message": m.SentMessage.error_message,
                "sent_at": m.SentMessage.sent_at.isoformat() if m.SentMessage.sent_at else None,
            }
            for m in rows
        ]
    }


# ═════════════════════════════════════════════════════════════
#  BILLING: CREDIT RECHARGE API
# ═════════════════════════════════════════════════════════════
from models import RechargeHistory

class CreditRechargeRequest(BaseModel):
    shopify_charge_id: str = Field(..., max_length=255)
    amount: float = Field(..., gt=0)
    credits: int = Field(..., gt=0)

@app.post("/api/v1/billing/credit-recharge", tags=["Billing"])
async def credit_recharge(
    payload: CreditRechargeRequest,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Credits a merchant's ledger after a successful Shopify one-time charge.
    Idempotent: prevents duplicate recharges for the same charge ID.
    """
    shop = _extract_shop_domain(token_payload)

    # 1. Idempotency check: check if this charge has already been credited
    existing_recharge = await db.execute(
        select(RechargeHistory).where(
            RechargeHistory.shopify_charge_id == payload.shopify_charge_id
        )
    )
    if existing_recharge.scalar_one_or_none():
        return {
            "status": "success",
            "message": "Credits already added for this transaction",
            "recharged": False
        }

    # 2. Get or create the store's credit ledger
    ledger_result = await db.execute(
        select(CreditLedger).where(CreditLedger.shopify_domain == shop)
    )
    ledger = ledger_result.scalar_one_or_none()

    if not ledger:
        ledger = CreditLedger(
            shopify_domain=shop,
            credits_remaining=payload.credits
        )
        db.add(ledger)
    else:
        ledger.credits_remaining += payload.credits

    # 3. Log into recharge history
    recharge_log = RechargeHistory(
        shopify_domain=shop,
        amount_paid=Decimal(str(payload.amount)),
        credits_added=payload.credits,
        shopify_charge_id=payload.shopify_charge_id,
        paid_at=datetime.now(timezone.utc)
    )
    db.add(recharge_log)

    await db.commit()

    logger.info(
        f"[{shop}] Successfully recharged {payload.credits} credits. "
        f"New balance: {ledger.credits_remaining}. (Charge ID: {payload.shopify_charge_id})"
    )

    return {
        "status": "success",
        "message": f"Successfully added {payload.credits} credits",
        "credits_remaining": ledger.credits_remaining,
        "recharged": True
    }


class RechargeUrlRequest(BaseModel):
    pack: str = Field(..., max_length=50)
    app_url: str = Field(..., max_length=512)


@app.post("/api/v1/billing/recharge-url", tags=["Billing"])
async def create_recharge_url(
    payload: RechargeUrlRequest,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Calls Shopify GraphQL Admin API to generate a one-time application charge.
    Returns the confirmationUrl for iframe breakout redirect.
    """
    shop = _extract_shop_domain(token_payload)

    # 1. Map selection to credits, price, and name (in USD)
    pack = payload.pack.lower()
    if pack == "starter":
        price = 4.99  # Standard: 9.99
        credits = 500
        name = "500 Credits Pack"
    elif pack == "growth":
        price = 9.99  # Standard: 19.99
        credits = 1000
        name = "1000 Credits Pack"
    elif pack == "scale":
        price = 39.99  # Standard: 69.99
        credits = 5000
        name = "5000 Credits Pack"
    else:
        raise HTTPException(status_code=400, detail="Invalid package selection")

    # 2. Get store access token
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # 3. Form return URL
    return_url = f"{payload.app_url.rstrip('/')}/app/billing/confirm?pack={pack}&credits={credits}&price={price}"

    # 4. Make Shopify GraphQL request
    graphql_url = f"https://{shop}/admin/api/2024-04/graphql.json"
    headers = {
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    }

    query = """
    mutation appPurchaseOneTimeCreate($name: String!, $price: MoneyInput!, $returnUrl: URL!, $test: Boolean) {
      appPurchaseOneTimeCreate(name: $name, price: $price, returnUrl: $returnUrl, test: $test) {
        appPurchaseOneTime {
          id
          confirmationUrl
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {
        "name": f"RecoverFlow AI — {name}",
        "price": {
            "amount": f"{price:.2f}",
            "currencyCode": "USD",
        },
        "returnUrl": return_url,
        "test": True,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                graphql_url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=15.0
            )
            response.raise_for_status()
            res_data = response.json()
        except Exception as e:
            logger.error(f"Shopify billing API error: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to communicate with Shopify: {e}")

    # 5. Handle user errors or return url
    data = res_data.get("data", {})
    mutation_result = data.get("appPurchaseOneTimeCreate", {})
    user_errors = mutation_result.get("userErrors", [])

    if user_errors:
        logger.error(f"Shopify Billing Mutation Errors: {user_errors}")
        raise HTTPException(status_code=400, detail=user_errors[0].get("message", "Shopify billing error"))

    purchase = mutation_result.get("appPurchaseOneTime", {})
    confirmation_url = purchase.get("confirmationUrl")

    if not confirmation_url:
        raise HTTPException(status_code=500, detail="Failed to get confirmation URL from Shopify")

    return {
        "status": "success",
        "confirmationUrl": confirmation_url
    }


class SubscribeUrlRequest(BaseModel):
    plan: str = Field(..., max_length=50)
    add_credits: int = Field(0, ge=0)
    app_url: str = Field(..., max_length=512)


@app.post("/api/v1/billing/subscribe-url", tags=["Billing"])
async def create_subscribe_url(
    payload: SubscribeUrlRequest,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Calls Shopify GraphQL Admin API to generate an app subscription.
    Returns the confirmationUrl for iframe breakout redirect.
    """
    shop = _extract_shop_domain(token_payload)
    plan = payload.plan.lower()

    if plan == "starter":
        price = 4.99  # Standard: 9.99
        name = "Starter Plan"
    elif plan == "growth":
        price = 9.99  # Standard: 19.99
        name = "Growth Plan"
    elif plan == "scale":
        price = 29.99  # Standard: 49.99
        name = "Scale Plan"
    else:
        raise HTTPException(status_code=400, detail="Invalid plan selection")

    # Get store access token
    result = await db.execute(
        select(Store).where(Store.shopify_domain == shop)
    )
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    # Form return URL
    return_url = f"{payload.app_url.rstrip('/')}/app/billing/confirm?plan={plan}&add_credits={payload.add_credits}"

    # GraphQL request to Shopify
    graphql_url = f"https://{shop}/admin/api/2024-04/graphql.json"
    headers = {
        "X-Shopify-Access-Token": store.access_token,
        "Content-Type": "application/json",
    }

    query = """
    mutation appSubscriptionCreate($name: String!, $lineItems: [AppSubscriptionLineItemInput!]!, $returnUrl: URL!, $trialDays: Int, $test: Boolean) {
      appSubscriptionCreate(name: $name, lineItems: $lineItems, returnUrl: $returnUrl, trialDays: $trialDays, test: $test) {
        appSubscription {
          id
          confirmationUrl
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    variables = {
        "name": f"RecoverFlow AI — {name}",
        "returnUrl": return_url,
        "test": True,
        "trialDays": 14,
        "lineItems": [
            {
                "plan": {
                    "appRecurringPricingDetails": {
                        "price": {
                            "amount": f"{price:.2f}",
                            "currencyCode": "USD"
                        },
                        "interval": "EVERY_30_DAYS"
                    }
                }
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                graphql_url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=15.0
            )
            response.raise_for_status()
            res_data = response.json()
        except Exception as e:
            logger.error(f"Shopify subscription billing API error: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to communicate with Shopify: {e}")

    data = res_data.get("data", {})
    mutation_result = data.get("appSubscriptionCreate", {})
    user_errors = mutation_result.get("userErrors", [])

    if user_errors:
        logger.error(f"Shopify Subscription Mutation Errors: {user_errors}")
        raise HTTPException(status_code=400, detail=user_errors[0].get("message", "Shopify billing error"))

    subscription = mutation_result.get("appSubscription", {})
    confirmation_url = subscription.get("confirmationUrl")

    if not confirmation_url:
        raise HTTPException(status_code=500, detail="Failed to get confirmation URL from Shopify")

    return {
        "status": "success",
        "confirmationUrl": confirmation_url
    }


class ConfirmSubscriptionRequest(BaseModel):
    shopify_charge_id: str = Field(..., max_length=255)
    plan: str = Field(..., max_length=50)
    add_credits: int = Field(0, ge=0)


@app.post("/api/v1/billing/confirm-subscription", tags=["Billing"])
async def confirm_subscription(
    payload: ConfirmSubscriptionRequest,
    token_payload: dict = Depends(verify_shopify_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates the store's subscription plan after a successful subscription creation.
    Credits the initial plan's free credits.
    """
    shop = _extract_shop_domain(token_payload)
    plan = payload.plan.upper()

    if plan not in ("STARTER", "GROWTH", "SCALE"):
        raise HTTPException(status_code=400, detail="Invalid plan name")

    # Get store and ledger
    store_res = await db.execute(select(Store).where(Store.shopify_domain == shop))
    store = store_res.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    ledger_res = await db.execute(select(CreditLedger).where(CreditLedger.shopify_domain == shop))
    ledger = ledger_res.scalar_one_or_none()

    # Determine free credits based on plan
    free_credits = 0
    if plan == "STARTER":
        free_credits = 100
        store.cart_recovery_active = False
    elif plan == "GROWTH":
        free_credits = 300
        store.cart_recovery_active = True
    elif plan == "SCALE":
        free_credits = 1000
        store.cart_recovery_active = True

    # Update store subscription plan
    store.subscription_plan = plan

    # Update ledger balance with free credits
    if not ledger:
        ledger = CreditLedger(shopify_domain=shop, credits_remaining=free_credits)
        db.add(ledger)
    else:
        ledger.credits_remaining += free_credits

    # Log into recharge history for the free bundle credits
    recharge_log = RechargeHistory(
        shopify_domain=shop,
        amount_paid=Decimal("0.00"),
        credits_added=free_credits,
        shopify_charge_id=payload.shopify_charge_id,
        paid_at=datetime.now(timezone.utc)
    )
    db.add(recharge_log)

    await db.commit()

    logger.info(
        f"[{shop}] Successfully updated plan to {plan}. "
        f"Credited {free_credits} plan bundle credits. New balance: {ledger.credits_remaining}."
    )

    return {
        "status": "success",
        "message": f"Successfully subscribed to {plan}",
        "subscription_plan": plan,
        "credits_remaining": ledger.credits_remaining,
    }


# ═════════════════════════════════════════════════════════════
#  HELP CENTER & CHATBOT API
# ═════════════════════════════════════════════════════════════
import json
import os
import google.generativeai as genai

HELP_ARTICLES_FILE = os.path.join(os.path.dirname(__file__), "help_articles.json")

def load_help_articles():
    try:
        with open(HELP_ARTICLES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading help_articles.json: {e}")
        return []

def find_relevant_article(query: str, articles: list[dict]) -> Optional[dict]:
    import re
    query_clean = re.sub(r'[^\w\s]', ' ', query.lower())
    query_words = [w for w in query_clean.split() if len(w) > 1]
    STOPWORDS = {
        "what", "how", "why", "who", "where", "when", "the", "and", "a", "an",
        "is", "are", "do", "does", "did", "can", "could", "would", "should",
        "for", "our", "your", "their", "this", "that", "these", "those",
        "about", "with", "from", "by", "of", "to", "in", "on"
    }
    search_words = [w for w in query_words if w not in STOPWORDS]
    if not search_words:
        search_words = query_words if query_words else [query.lower()]
        
    # Normalize plurals
    search_words = [w[:-1] if (w.endswith('s') and not w.endswith('ss') and len(w) > 3) else w for w in search_words]
    
    best_article = None
    max_score = 0
    
    for article in articles:
        score = 0
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        content = article.get("content", "").lower()
        category = article.get("category", "").lower()
        id_val = article.get("id", "").lower()
        
        # Normalize fields for matching
        def normalize_text(text):
            cleaned = re.sub(r'[^\w\s]', ' ', text)
            words = cleaned.split()
            return set([w[:-1] if (w.endswith('s') and not w.endswith('ss') and len(w) > 3) else w for w in words])
            
        title_words = normalize_text(title)
        summary_words = normalize_text(summary)
        content_words = normalize_text(content)
        category_words = normalize_text(category)
        
        id_words = set(id_val.split("-"))
        id_words = set([w[:-1] if (w.endswith('s') and not w.endswith('ss') and len(w) > 3) else w for w in id_words])
        
        # 1. Exact phrase matches (highest weighting)
        if id_val in query.lower() or query.lower() in id_val:
            score += 20
        if query.lower() in title:
            score += 15
            
        # 2. Match individual search words
        for w in search_words:
            # Exact normalized word match
            if w in id_words:
                score += 10
            if w in title_words:
                score += 8
            if w in category_words:
                score += 5
            if w in summary_words:
                score += 3
            if w in content_words:
                score += 1
                
            # Substring matches within words (e.g. 'recharge' in 'recharging')
            for tw in title_words:
                if (w in tw or tw in w) and w != tw:
                    score += 4
            for iw in id_words:
                if (w in iw or iw in w) and w != iw:
                    score += 4
                    
        if score > max_score and score >= 5:
            max_score = score
            best_article = article
            
    return best_article


@app.get("/api/v1/help/articles", tags=["Help"])
async def get_help_articles(
    q: Optional[str] = None,
    token_payload: dict = Depends(verify_shopify_token)
):
    articles = load_help_articles()
    if not q:
        return articles
    
    q_lower = q.lower()
    filtered = []
    for article in articles:
        if (q_lower in article.get("title", "").lower() or
            q_lower in article.get("category", "").lower() or
            q_lower in article.get("summary", "").lower() or
            q_lower in article.get("content", "").lower()):
            filtered.append(article)
    return filtered


@app.get("/api/v1/help/articles/{article_id}", tags=["Help"])
async def get_help_article(
    article_id: str,
    token_payload: dict = Depends(verify_shopify_token)
):
    articles = load_help_articles()
    for article in articles:
        if article.get("id") == article_id:
            return article
    raise HTTPException(status_code=404, detail="Article not found")


class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    history: list[ChatMessage] = []


SYSTEM_PROMPT = """You are the customer success AI assistant for RecoverFlow AI. Your job is to help Shopify merchants understand platform features, billing, credits, recovery campaigns, dashboard metrics, and general setup.

CRITICAL INSTRUCTIONS:
- Speak in simple, non-technical, merchant-friendly business language. Do not use technical jargon.
- Act as a customer success manager, not a developer or backend engineer.
- For manual support, billing discrepancies, or specific custom integrations, direct merchants to email Support.emplabs@gmail.com.

RESTRICTED INFORMATION POLICY:
- You must NEVER discuss backend details, databases (PostgreSQL, SQLite, Redis), code architecture, webhooks, queues, Celery, worker tasks, internal operations, proprietary algorithms, pricing margins, our utility cost per message, or our profit margins.
- If asked about these, decline politely and redirect the discussion to subscription tiers, credit recharges, or campaign setup.
- Examples of handling restricted questions:
  * "How do you calculate your profit margin?" -> "Pricing and internal operating costs are proprietary business information. If you have questions about your subscription, credits, or billing, I can help explain those."
  * "How does AI Segmentation work technically?" -> "RecoverFlow analyzes customer behavior and shopping patterns to improve recovery performance and personalize campaigns. Specific implementation details are proprietary."
  * "What database do you use?" -> "RecoverFlow handles all technical infrastructure internally so merchants can focus on recovering revenue and growing their store."

CONTEXT:
Below is relevant documentation from our Help Center (if any was found for the user's question):
{context}

INSTRUCTIONS FOR LINKS:
- If a relevant Help Center article is provided in the Context above, summarize it briefly and output a direct markdown link using the relative format: [Article Title](/app/help?article={{article_id}}).
- Example: "You can find more detailed instructions in our [Getting Started with RecoverFlow AI](/app/help?article=getting-started) guide."
- ONLY link to articles that are actually provided in the Context. Do not invent links.
"""

@app.post("/api/v1/help/chat", tags=["Help"])
async def help_chat(
    payload: ChatRequest,
    token_payload: dict = Depends(verify_shopify_token)
):
    # 1. RAG: Search relevant help articles
    articles = load_help_articles()
    relevant = find_relevant_article(payload.message, articles)
    
    if relevant:
        context_str = f"Article ID: {relevant['id']}\nTitle: {relevant['title']}\nContent:\n{relevant['content']}"
    else:
        context_str = "No relevant Help Center article was found for this query."

    # Fallback local responder function
    def get_fallback_reply():
        if relevant:
            return (
                f"Based on the **{relevant['title']}** guide, here is a summary:\n\n"
                f"{relevant['summary']}\n\n"
                f"You can read the full step-by-step instructions in the article: "
                f"[{relevant['title']}](/app/help?article={relevant['id']}).\n\n"
                f"For additional questions, feel free to email Support.emplabs@gmail.com."
            )
        else:
            msg_lower = payload.message.lower()
            if "hello" in msg_lower or "hi" in msg_lower:
                return (
                    "Hello! I'm your RecoverFlow Assistant. How can I help you recover revenue today? "
                    "You can ask me about billing, setup, WhatsApp credits, or campaigns."
                )
            elif "support" in msg_lower or "contact" in msg_lower or "help" in msg_lower:
                return (
                    "You can contact our merchant support team directly at **Support.emplabs@gmail.com**. "
                    "We typically respond within 24 hours."
                )
            else:
                return (
                    "I'm sorry, I couldn't find a specific guide matching your question. "
                    "Try asking about:\n"
                    "- **Setup Guide**\n"
                    "- **How credits work**\n"
                    "- **Subscription plans**\n"
                    "- **AI Segmentation**\n\n"
                    "Or check out our [Help Center](/app/help) for a full list of articles."
                )

    # 2. If Gemini API Key is missing, return local RAG fallback immediately
    if not settings.GEMINI_API_KEY:
        return {
            "status": "success",
            "reply": get_fallback_reply(),
            "article": {
                "id": relevant["id"],
                "title": relevant["title"]
            } if relevant else None
        }

    # 3. Configure model
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # 4. Build full prompt
    formatted_system = SYSTEM_PROMPT.format(context=context_str)
    
    # Create contents list for chat
    contents = []
    
    # Add chat history (up to last 10 messages)
    for msg in payload.history[-10:]:
        role = "user" if msg.role == "user" else "model"
        contents.append({"role": role, "parts": [msg.content]})
        
    # Add the current user message
    contents.append({"role": "user", "parts": [payload.message]})
    
    try:
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=formatted_system,
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 500,
            }
        )
        
        response = model.generate_content(contents)
        reply = response.text.strip() if response and response.text else get_fallback_reply()
        
        return {
            "status": "success",
            "reply": reply,
            "article": {
                "id": relevant["id"],
                "title": relevant["title"]
            } if relevant else None
        }
        
    except Exception as e:
        logger.error(f"Error calling Gemini in chat: {e}")
        return {
            "status": "success",
            "reply": get_fallback_reply(),
            "article": {
                "id": relevant["id"],
                "title": relevant["title"]
            } if relevant else None
        }


# ═════════════════════════════════════════════════════════════
#  MOUNT WEBHOOK ROUTER
# ═════════════════════════════════════════════════════════════
from webhooks import router as webhook_router
app.include_router(webhook_router)


# ═════════════════════════════════════════════════════════════
#  STARTUP & SHUTDOWN EVENTS
# ═════════════════════════════════════════════════════════════
@app.on_event("startup")
async def on_startup():
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    logger.info(f"   Database: {settings.DATABASE_URL.split('@')[-1]}")
    logger.info(f"   Redis:    {settings.REDIS_URL}")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info(f"🛑 {settings.APP_NAME} shutting down.")
