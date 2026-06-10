import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Setup import path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from models import Store, CreditLedger, AbandonedCheckout, SentMessage, RecoveredOrder
from config import get_settings

async def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_url = "postgresql+asyncpg://recoverflow:recoverflow@localhost:5432/recoverflow"
    
    print(f"Connecting to database: {db_url}")
    engine = create_async_engine(db_url, echo=True)
    async_session_factory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    shop_domain = "recoverflow-dev.myshopify.com"

    async with async_session_factory() as session:
        # 1. Clean existing mock checkouts/orders/messages to prevent duplicates
        await session.execute(delete(RecoveredOrder).where(RecoveredOrder.shopify_domain == shop_domain))
        await session.execute(delete(SentMessage).where(SentMessage.shopify_domain == shop_domain))
        await session.execute(delete(AbandonedCheckout).where(AbandonedCheckout.shopify_domain == shop_domain))

        # 2. Get or create store
        result = await session.execute(select(Store).where(Store.shopify_domain == shop_domain))
        store = result.scalar_one_or_none()

        if not store:
            store = Store(
                shopify_domain=shop_domain,
                access_token="shp_offline_token_dev_12345",
                subscription_plan="GROWTH",
                store_name="RecoverFlow Dev Store",
                brand_tone="friendly",
                is_active=True,
                cart_recovery_active=True
            )
            session.add(store)
        else:
            store.subscription_plan = "GROWTH"
            store.cart_recovery_active = True

        # 3. Update Credit Ledger
        result_ledger = await session.execute(select(CreditLedger).where(CreditLedger.shopify_domain == shop_domain))
        ledger = result_ledger.scalar_one_or_none()
        if not ledger:
            ledger = CreditLedger(
                shopify_domain=shop_domain,
                credits_remaining=850,
                credits_used=150
            )
            session.add(ledger)
        else:
            ledger.credits_remaining = 850
            ledger.credits_used = 150

        # 4. Add Abandoned Checkouts
        now = datetime.now(timezone.utc)

        # Checkout 1: Recovered
        chk1 = AbandonedCheckout(
            checkout_id="chk_rec_01",
            shopify_domain=shop_domain,
            customer_name="John Doe",
            customer_phone="+919876543210",
            cart_json={
                "line_items": [{"title": "Premium Coffee Beans Blend", "quantity": 2, "price": "1499.50"}]
            },
            total_price=Decimal("2999.00"),
            currency="INR",
            recovery_status="RECOVERED",
            customer_segment="VIP Customer",
            created_at=now - timedelta(hours=4),
            recovered_at=now - timedelta(hours=2)
        )

        # Checkout 2: Recovered
        chk2 = AbandonedCheckout(
            checkout_id="chk_rec_02",
            shopify_domain=shop_domain,
            customer_name="Alice Smith",
            customer_phone="+919999988888",
            cart_json={
                "line_items": [{"title": "Ergonomic Office Chair", "quantity": 1, "price": "7999.00"}]
            },
            total_price=Decimal("7999.00"),
            currency="INR",
            recovery_status="RECOVERED",
            customer_segment="High Cart Value",
            created_at=now - timedelta(hours=8),
            recovered_at=now - timedelta(hours=6)
        )

        # Checkout 3: Pending step 1
        chk3 = AbandonedCheckout(
            checkout_id="chk_pend_01",
            shopify_domain=shop_domain,
            customer_name="Bob Johnson",
            customer_phone="+918888877777",
            cart_json={
                "line_items": [{"title": "Wireless Earbuds Max", "quantity": 1, "price": "2499.00"}]
            },
            total_price=Decimal("2499.00"),
            currency="INR",
            recovery_status="PENDING",
            customer_segment="Window Shopper",
            created_at=now - timedelta(minutes=15)
        )

        # Checkout 4: Exhausted (Failed to recover)
        chk4 = AbandonedCheckout(
            checkout_id="chk_exh_01",
            shopify_domain=shop_domain,
            customer_name="Emma Brown",
            customer_phone="+917777766666",
            cart_json={
                "line_items": [{"title": "Leather Travel Duffel Bag", "quantity": 1, "price": "4500.00"}]
            },
            total_price=Decimal("4500.00"),
            currency="INR",
            recovery_status="EXHAUSTED",
            customer_segment="Regular Customer",
            created_at=now - timedelta(days=2)
        )

        session.add_all([chk1, chk2, chk3, chk4])

        # 5. Add Recovered Orders matching checkout 1 & 2
        order1 = RecoveredOrder(
            order_id="ord_shopify_1001",
            checkout_id="chk_rec_01",
            shopify_domain=shop_domain,
            recovered_revenue=Decimal("2999.00"),
            currency="INR",
            recovered_at=now - timedelta(hours=2)
        )

        order2 = RecoveredOrder(
            order_id="ord_shopify_1002",
            checkout_id="chk_rec_02",
            shopify_domain=shop_domain,
            recovered_revenue=Decimal("7999.00"),
            currency="INR",
            recovered_at=now - timedelta(hours=6)
        )

        session.add_all([order1, order2])

        # 6. Add Sent Messages logs
        msg1 = SentMessage(
            checkout_id="chk_rec_01",
            shopify_domain=shop_domain,
            step_number=1,
            message_body="Hey John Doe, you left the Premium Coffee Beans Blend in your cart. Check out now!",
            template_variant="A",
            credits_used=1,
            status="SENT",
            sent_at=now - timedelta(hours=3, minutes=30)
        )

        msg2 = SentMessage(
            checkout_id="chk_rec_02",
            shopify_domain=shop_domain,
            step_number=1,
            message_body="Hey Alice, we saved your Ergonomic Office Chair. Get it before stock runs out!",
            template_variant="A",
            credits_used=1,
            status="SENT",
            sent_at=now - timedelta(hours=7, minutes=30)
        )

        msg3 = SentMessage(
            checkout_id="chk_exh_01",
            shopify_domain=shop_domain,
            step_number=1,
            message_body="Hi Emma, complete your checkout for the Leather Travel Duffel Bag.",
            template_variant="A",
            credits_used=1,
            status="SENT",
            sent_at=now - timedelta(days=1, hours=23)
        )

        msg4 = SentMessage(
            checkout_id="chk_exh_01",
            shopify_domain=shop_domain,
            step_number=2,
            message_body="Emma, items are selling out fast. Complete your purchase now!",
            template_variant="B",
            credits_used=1,
            status="SENT",
            sent_at=now - timedelta(days=1, hours=18)
        )

        session.add_all([msg1, msg2, msg3, msg4])

        await session.commit()
        print("Successfully seeded dashboard mock data!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
