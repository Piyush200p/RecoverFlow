"""
RecoverFlow AI — End-to-End Integration Test Suite
===================================================
Simulates the entire checkout recovery lifecycle:
  1. Store onboarding & credit seeding
  2. Configuration updates (settings, tones)
  3. WhatsApp connection credentials validation handshake
  4. Checkout abandonment ingestion webhook
  5. Recovery task execution (Gemini generation + WhatsApp dispatch)
  6. Order completion webhook (recovery matching, task revocation)
  7. Billing recharge link generation & idempotency confirmation

Uses SQLite in-memory database to execute 100% locally.
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch, MagicMock

# 1. Setup local python import path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 2. Patch database engines before imports to use SQLite
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session

TestAsyncSession = async_sessionmaker(class_=AsyncSession, expire_on_commit=False)
TestSyncSession = sessionmaker(class_=Session, expire_on_commit=False)

# Custom compilation rule: Compile PostgreSQL JSONB to SQLite JSON
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

async_engine = None
sync_engine = None

import database
database.async_session_factory = TestAsyncSession
database.sync_session_factory = TestSyncSession

# Helper dependencies
async def get_test_db():
    async with TestAsyncSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

database.get_db = get_test_db

from contextlib import contextmanager
@contextmanager
def get_test_sync_db():
    session = TestSyncSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

database.get_sync_db = get_test_sync_db

# Delete old test DB if exists
import os
for f in ["test_recoverflow.db", "test_recoverflow.db-journal"]:
    if os.path.exists(f):
        try:
            os.remove(f)
        except Exception:
            pass

from models import Base

# 4. Import FastAPI app & webhooks
from fastapi.testclient import TestClient
from main import app
from models import Store, CreditLedger, AbandonedCheckout, SentMessage, RecoverySchedule, RecoveredOrder, RechargeHistory, AbandonedCart, CartRecoverySchedule

client = TestClient(app)

from main import verify_shopify_token
app.dependency_overrides[verify_shopify_token] = lambda: {
    "iss": "https://test-merchant.myshopify.com/admin",
    "dest": "https://test-merchant.myshopify.com",
    "aud": "test_api_key",
    "sub": "user_123",
    "exp": 9999999999,
}

from webhooks import verify_secret
app.dependency_overrides[verify_secret] = lambda: None


class TestRecoverFlowE2EPipeline(unittest.TestCase):

    def setUp(self):
        import uuid
        self.db_filename = f"test_recoverflow_{uuid.uuid4().hex}.db"
        self.test_db_url = f"sqlite+aiosqlite:///{self.db_filename}"
        self.test_sync_db_url = f"sqlite:///{self.db_filename}"
        
        from sqlalchemy.pool import NullPool
        global async_engine, sync_engine
        async_engine = create_async_engine(self.test_db_url, echo=False, poolclass=NullPool, connect_args={"timeout": 30})
        sync_engine = create_engine(self.test_sync_db_url, echo=False, poolclass=NullPool, connect_args={"timeout": 30})
        
        TestAsyncSession.configure(bind=async_engine)
        TestSyncSession.configure(bind=sync_engine)
        
        database.engine = async_engine
        database.sync_engine = sync_engine
        
        Base.metadata.create_all(sync_engine)
        
        self.shop = "test-merchant.myshopify.com"
        self.mock_jwt_payload = {
            "iss": f"https://{self.shop}/admin",
            "dest": f"https://{self.shop}",
            "aud": "test_api_key",
            "sub": "user_123",
            "exp": 9999999999,
        }

    def tearDown(self):
        global async_engine, sync_engine
        if sync_engine:
            sync_engine.dispose()
        if async_engine:
            async_engine.sync_engine.dispose()
        import os
        for f in [self.db_filename, f"{self.db_filename}-journal", f"{self.db_filename}-wal", f"{self.db_filename}-shm"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    @patch("main.verify_shopify_token")
    def test_complete_e2e_lifecycle(self, mock_verify_token):
        mock_verify_token.return_value = self.mock_jwt_payload
        headers = {
            "Authorization": "Bearer fake_token",
            "X-Shopify-Shop-Domain": self.shop,
        }

        # ─────────────────────────────────────────────────────────────
        # STEP 1: Store Installation & Credit Seeding
        # ─────────────────────────────────────────────────────────────
        # Initialize store in DB synchronously
        with TestSyncSession() as session:
            store = Store(
                shopify_domain=self.shop,
                access_token="shp_offline_token_12345",
                subscription_plan="FREE",
                store_name="Test Store",
                brand_tone="friendly",
                is_active=True,
            )
            ledger = CreditLedger(
                shopify_domain=self.shop,
                credits_remaining=50, # 50 free seed credits
            )
            session.add(store)
            session.add(ledger)
            session.commit()

        # Verify initial onboarding query
        response = client.get("/api/v1/store", headers=headers)
        self.assertEqual(response.status_code, 200)
        res_data = response.json()
        self.assertEqual(res_data["store"]["shopify_domain"], self.shop)
        self.assertEqual(res_data["store"]["credits_remaining"], 50)
        self.assertEqual(res_data["store"]["brand_tone"], "friendly")

        # ─────────────────────────────────────────────────────────────
        # STEP 2: Configure Brand voice tone
        # ─────────────────────────────────────────────────────────────
        settings_payload = {
            "store_name": "Gourmet Chocolates Inc.",
            "brand_tone": "casual",
            "is_active": True,
            "reminder_count": 2,
            "step_1_delay": 180,
            "step_2_delay": 3600,
            "step_3_delay": 7200
        }
        response = client.post("/api/v1/store/settings", json=settings_payload, headers=headers)
        self.assertEqual(response.status_code, 200)

        # Check DB update
        with TestSyncSession() as session:
            db_store = session.query(Store).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(db_store.store_name, "Gourmet Chocolates Inc.")
            self.assertEqual(db_store.brand_tone, "casual")
            self.assertEqual(db_store.reminder_count, 2)
            self.assertEqual(db_store.step_1_delay, 180)
            self.assertEqual(db_store.step_2_delay, 3600)
            self.assertEqual(db_store.step_3_delay, 7200)

        # ─────────────────────────────────────────────────────────────
        # STEP 3: Verify & Save Meta WhatsApp Cloud API configuration
        # ─────────────────────────────────────────────────────────────
        whatsapp_payload = {
            "whatsapp_phone_number_id": "phone_id_9988",
            "whatsapp_access_token": "token_secret_123456",
            "whatsapp_business_id": "business_id_7766"
        }

        # Mock Meta API credentials handshake validation
        with patch("main.verify_whatsapp_credentials") as mock_wa_verify:
            mock_wa_verify.return_value = {
                "verified": True,
                "phone_number": "+1234567890",
                "display_name": "Gourmet Chocolates"
            }
            response = client.post("/api/v1/whatsapp/config", json=whatsapp_payload, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["verified_details"]["verified"])

        # Check DB updated values
        with TestSyncSession() as session:
            db_store = session.query(Store).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(db_store.whatsapp_phone_number_id, "phone_id_9988")
            self.assertEqual(db_store.whatsapp_access_token, "token_secret_123456")
            self.assertEqual(db_store.whatsapp_business_id, "business_id_7766")

        # ─────────────────────────────────────────────────────────────
        # STEP 4: Ingest Checkout Abandonment Webhook
        # ─────────────────────────────────────────────────────────────
        webhook_headers = {
            "X-Shopify-Shop-Domain": self.shop,
            "X-Webhook-Topic": "checkouts/create",
        }
        checkout_payload = {
            "id": 998811,
            "email": "customer@gmail.com",
            "total_price": "1499.50",
            "currency": "INR",
            "abandoned_checkout_url": "https://test-merchant.myshopify.com/checkouts/ac/998811",
            "customer": {
                "first_name": "Alice",
                "last_name": "Smith",
                "phone": "+919876543210"
            },
            "line_items": [
                {"title": "Dark Chocolate Box", "quantity": 1, "price": "1499.50"}
            ]
        }

        # Mock Celery workflow schedule to avoid triggering async worker process
        with patch("webhooks._trigger_recovery_workflow") as mock_schedule:
            response = client.post("/webhooks/checkout-abandonment", json=checkout_payload, headers=webhook_headers)
            self.assertEqual(response.status_code, 200)
            mock_schedule.assert_called_once_with("998811", self.shop)

        # Check checkout details in DB
        with TestSyncSession() as session:
            chk = session.query(AbandonedCheckout).filter_by(checkout_id="998811").first()
            self.assertIsNotNone(chk)
            self.assertEqual(chk.customer_name, "Alice Smith")
            self.assertEqual(chk.customer_phone, "+919876543210")
            self.assertEqual(chk.recovery_status, "PENDING")
            self.assertEqual(float(chk.total_price), 1499.50)

        # ─────────────────────────────────────────────────────────────
        # STEP 5: Run Recovery Task (Simulate Celery Background Worker)
        # ─────────────────────────────────────────────────────────────
        # We invoke the actual code inside the tasks.py methods synchronously
        # We need to mock:
        #   1. Gemini AI Copywriting generation
        #   2. Meta API WhatsApp message dispatcher
        # Let's import tasks
        import tasks

        mock_message_text = "Hi Alice, we saved Gourmet Chocolates Inc. Dark Chocolate Box for you! Complete checkout here: https://test-merchant.myshopify.com/checkouts/ac/998811"

        # Mock Gemini generation
        with patch("ai_engine.generate_personalized_recovery_message") as mock_gemini:
            mock_gemini.return_value = mock_message_text
            
            # Mock WhatsApp send
            with patch("whatsapp.dispatch_whatsapp_message") as mock_wa_send:
                mock_wa_send.return_value = {
                    "messaging_product": "whatsapp",
                    "messages": [{"id": "wamid.ABC123XYZ", "message_status": "accepted"}]
                }

                # Trigger step 1 recovery workflow task synchronously
                # Create recovery schedules first
                with TestSyncSession() as session:
                    schedule = RecoverySchedule(
                        checkout_id="998811",
                        step_number=1,
                        scheduled_for=datetime.now(timezone.utc),
                        status="QUEUED",
                        celery_task_id="task_step_1_abc"
                    )
                    session.add(schedule)
                    session.commit()

                # Call the worker method synchronously via Celery apply
                tasks.send_whatsapp_reminder_task.apply(args=["998811", self.shop, 1])

        # Verify DB results after worker execution
        with TestSyncSession() as session:
            # 1. Check ledger credit deduction
            ledger = session.query(CreditLedger).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(ledger.credits_remaining, 49) # Deducted 1 credit
            self.assertEqual(ledger.credits_used, 1)

            # 2. Check message logs
            msg = session.query(SentMessage).filter_by(checkout_id="998811").first()
            self.assertIsNotNone(msg)
            self.assertEqual(msg.status, "SENT")
            self.assertEqual(msg.whatsapp_message_id, "wamid.ABC123XYZ")
            self.assertEqual(msg.message_body, mock_message_text)

            # 3. Check schedule status updated
            schedule = session.query(RecoverySchedule).filter_by(checkout_id="998811", step_number=1).first()
            self.assertEqual(schedule.status, "SENT")

        # ─────────────────────────────────────────────────────────────
        # STEP 6: Ingest Order Completed Webhook (Recovery Success)
        # ─────────────────────────────────────────────────────────────
        order_payload = {
            "id": 554422,
            "checkout_id": "998811",
            "total_price": "1499.50",
            "currency": "INR"
        }
        order_headers = {
            "X-Shopify-Shop-Domain": self.shop,
            "X-Webhook-Topic": "orders/create",
        }

        # Create a pending step 2 schedule to verify task revocation
        with TestSyncSession() as session:
            schedule2 = RecoverySchedule(
                checkout_id="998811",
                step_number=2,
                scheduled_for=datetime.now(timezone.utc),
                status="QUEUED",
                celery_task_id="task_step_2_xyz"
            )
            session.add(schedule2)
            session.commit()

        # Mock celery control revoke to verify cancellation behavior
        with patch("tasks.celery_app.control.revoke") as mock_revoke:
            response = client.post("/webhooks/order-created", json=order_payload, headers=order_headers)
            self.assertEqual(response.status_code, 200)
            mock_revoke.assert_called_once_with("task_step_2_xyz", terminate=True)

        # Check DB states
        with TestSyncSession() as session:
            # 1. Checkout status must be RECOVERED
            chk = session.query(AbandonedCheckout).filter_by(checkout_id="998811").first()
            self.assertEqual(chk.recovery_status, "RECOVERED")
            self.assertIsNotNone(chk.recovered_at)

            # 2. Step 2 schedule must be CANCELLED
            sch2 = session.query(RecoverySchedule).filter_by(checkout_id="998811", step_number=2).first()
            self.assertEqual(sch2.status, "CANCELLED")

            # 3. RecoveredOrder record exists
            rec_order = session.query(RecoveredOrder).filter_by(order_id="554422").first()
            self.assertIsNotNone(rec_order)
            self.assertEqual(float(rec_order.recovered_revenue), 1499.50)

        # ─────────────────────────────────────────────────────────────
        # STEP 7: Billing Recharge link generation & Idempotent Confirmation
        # ─────────────────────────────────────────────────────────────
        # A. Recharge link generation request
        recharge_req_payload = {
            "pack": "starter",
            "app_url": "https://recoverflow-app.com"
        }
        # Mock Shopify GraphQL mutation response
        with patch("httpx.AsyncClient.post") as mock_graphql_post:
            mock_graphql_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "data": {
                        "appPurchaseOneTimeCreate": {
                            "appPurchaseOneTime": {
                                "id": "gid://shopify/AppPurchaseOneTime/998877",
                                "confirmationUrl": "https://admin.shopify.com/store/charge-approval-url"
                            },
                            "userErrors": []
                        }
                    }
                }
            )
            response = client.post("/api/v1/billing/recharge-url", json=recharge_req_payload, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["confirmationUrl"], "https://admin.shopify.com/store/charge-approval-url")

        # B. Credit Ledger recharge confirmation
        confirm_payload = {
            "shopify_charge_id": "charge_id_554433",
            "amount": 499.0,
            "credits": 500
        }
        # Perform recharge POST
        response = client.post("/api/v1/billing/credit-recharge", json=confirm_payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["credits_remaining"], 549) # 49 remaining + 500 added
        self.assertTrue(response.json()["recharged"])

        # Check DB states
        with TestSyncSession() as session:
            ledger = session.query(CreditLedger).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(ledger.credits_remaining, 549)
            
            rech_history = session.query(RechargeHistory).filter_by(shopify_charge_id="charge_id_554433").first()
            self.assertIsNotNone(rech_history)
            self.assertEqual(float(rech_history.amount_paid), 499.0)

        # C. Idempotency Check: Verify duplicate request does NOT add credits
        response = client.post("/api/v1/billing/credit-recharge", json=confirm_payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["recharged"])

        # Verify ledger balance is unchanged
        with TestSyncSession() as session:
            ledger = session.query(CreditLedger).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(ledger.credits_remaining, 549)

    @patch("main.verify_shopify_token")
    def test_cart_abandonment_lifecycle(self, mock_verify_token):
        mock_verify_token.return_value = self.mock_jwt_payload
        headers = {
            "Authorization": "Bearer fake_token",
            "X-Shopify-Shop-Domain": self.shop,
        }

        # Setup store and premium subscription plan GROWTH
        with TestSyncSession() as session:
            store = Store(
                shopify_domain=self.shop,
                access_token="shp_offline_token_12345",
                subscription_plan="GROWTH", # Premium plan needed!
                store_name="Premium Store",
                brand_tone="luxury",
                is_active=True,
                cart_recovery_active=True, # Active toggle
                whatsapp_phone_number_id="phone_id_9988",
                whatsapp_access_token="token_secret_123456",
                whatsapp_business_id="business_id_7766",
            )
            ledger = CreditLedger(
                shopify_domain=self.shop,
                credits_remaining=50,
            )
            session.add(store)
            session.add(ledger)
            session.commit()

        # 1. Ingest Cart Webhook
        webhook_headers = {
            "X-Shopify-Shop-Domain": self.shop,
            "X-Webhook-Topic": "carts/create",
        }
        cart_payload = {
            "id": "cart_token_abc_123",
            "token": "cart_token_abc_123",
            "note": None,
            "attributes": {},
            "original_total_price": 50000,
            "total_price": 50000,
            "currency": "INR",
            "items": [
                {
                    "id": 445566,
                    "variant_id": 445566,
                    "title": "Luxury Silk Robe",
                    "quantity": 1,
                    "price": "50000",
                    "image": "https://cdn.shopify.com/silk_robe.jpg"
                }
            ],
            "customer": {
                "first_name": "John",
                "last_name": "Doe",
                "phone": "+919999999999"
            }
        }

        with patch("webhooks._trigger_cart_recovery_workflow") as mock_schedule:
            response = client.post("/webhooks/cart-abandonment", json=cart_payload, headers=webhook_headers)
            self.assertEqual(response.status_code, 200)
            mock_schedule.assert_called_once_with("cart_token_abc_123", self.shop)

        # Check cart details in DB
        with TestSyncSession() as session:
            cart = session.query(AbandonedCart).filter_by(cart_id="cart_token_abc_123").first()
            self.assertIsNotNone(cart)
            self.assertEqual(cart.customer_name, "John Doe")
            self.assertEqual(cart.customer_phone, "+919999999999")
            self.assertEqual(cart.recovery_status, "PENDING")
            self.assertEqual(float(cart.total_price), 500.0)

        # 2. Run Cart Recovery Task
        import tasks
        mock_message_text = "Hi John, Luxury Silk Robe is waiting for you! Reopen your cart here: https://test-merchant.myshopify.com/cart/445566:1"

        # Mock Gemini generation
        with patch("ai_engine.generate_personalized_recovery_message") as mock_gemini:
            mock_gemini.return_value = mock_message_text
            
            # Mock WhatsApp send
            with patch("whatsapp.dispatch_whatsapp_message") as mock_wa_send:
                mock_wa_send.return_value = {
                    "messaging_product": "whatsapp",
                    "messages": [{"id": "wamid.CART123XYZ", "message_status": "accepted"}]
                }

                # Create cart recovery schedules first
                with TestSyncSession() as session:
                    schedule = CartRecoverySchedule(
                        cart_id="cart_token_abc_123",
                        scheduled_for=datetime.now(timezone.utc),
                        status="QUEUED",
                        celery_task_id="task_cart_abc"
                    )
                    session.add(schedule)
                    session.commit()

                # Call the worker method synchronously
                tasks.send_cart_reminder_task.apply(args=["cart_token_abc_123", self.shop])

        # Verify DB results after worker execution
        with TestSyncSession() as session:
            # Check ledger credit deduction
            ledger = session.query(CreditLedger).filter_by(shopify_domain=self.shop).first()
            self.assertEqual(ledger.credits_remaining, 49) # Deducted 1 credit

            # Check message logs
            msg = session.query(SentMessage).filter_by(cart_id="cart_token_abc_123").first()
            self.assertIsNotNone(msg)
            self.assertEqual(msg.status, "SENT")
            self.assertEqual(msg.whatsapp_message_id, "wamid.CART123XYZ")

            # Check schedule status updated
            schedule = session.query(CartRecoverySchedule).filter_by(cart_id="cart_token_abc_123").first()
            self.assertEqual(schedule.status, "SENT")

            # Cart status should be EXHAUSTED
            cart = session.query(AbandonedCart).filter_by(cart_id="cart_token_abc_123").first()
            self.assertEqual(cart.recovery_status, "EXHAUSTED")

        # 3. Test Cart Recovery Cancellation on Checkout Ingestion
        # Re-register a new cart that is active
        with TestSyncSession() as session:
            cart2 = AbandonedCart(
                cart_id="cart_token_cancel",
                shopify_domain=self.shop,
                customer_name="John Cancel",
                customer_phone="+919999999999",
                cart_json={},
                total_price=Decimal("100.00"),
                currency="INR",
                recovery_status="PENDING",
            )
            schedule2 = CartRecoverySchedule(
                cart_id="cart_token_cancel",
                scheduled_for=datetime.now(timezone.utc),
                status="QUEUED",
                celery_task_id="task_cart_cancel"
            )
            session.add(cart2)
            session.add(schedule2)
            session.commit()

        # Ingest Checkout for the same phone number
        webhook_headers = {
            "X-Shopify-Shop-Domain": self.shop,
            "X-Webhook-Topic": "checkouts/create",
        }
        checkout_payload = {
            "id": 11223344,
            "email": "john@gmail.com",
            "total_price": "100.00",
            "currency": "INR",
            "abandoned_checkout_url": "https://test-merchant.myshopify.com/checkouts/ac/11223344",
            "customer": {
                "first_name": "John",
                "last_name": "Cancel",
                "phone": "+919999999999"
            },
            "line_items": []
        }

        with patch("tasks.celery_app.control.revoke") as mock_revoke:
            response = client.post("/webhooks/checkout-abandonment", json=checkout_payload, headers=webhook_headers)
            self.assertEqual(response.status_code, 200)
            mock_revoke.assert_any_call("task_cart_cancel", terminate=True)

        # Verify cart was cancelled/recovered
        with TestSyncSession() as session:
            c2 = session.query(AbandonedCart).filter_by(cart_id="cart_token_cancel").first()
            self.assertEqual(c2.recovery_status, "RECOVERED")
            s2 = session.query(CartRecoverySchedule).filter_by(cart_id="cart_token_cancel").first()
            self.assertEqual(s2.status, "CANCELLED")

    def test_ai_segmentation_workflow(self):
        """Test rule-based AI customer segmentation fallbacks and DB schema persistence."""
        import tasks
        from ai_engine import classify_customer_segment, generate_personalized_recovery_message

        # Initialize store in DB synchronously for this test case
        with TestSyncSession() as session:
            store = Store(
                shopify_domain=self.shop,
                access_token="shp_offline_token_12345",
                subscription_plan="GROWTH",
                store_name="Test Store",
                brand_tone="friendly",
                is_active=True,
            )
            ledger = CreditLedger(
                shopify_domain=self.shop,
                credits_remaining=50,
            )
            session.add(store)
            session.add(ledger)
            session.commit()

        # Test rule-based classification directly
        # 1. VIP Customer (large total spent or orders count >= 5)
        vip_seg = classify_customer_segment(orders_count=6, total_spent=12000.0, cart_value=2000.0, has_discounts=False)
        self.assertEqual(vip_seg, "VIP")

        # 2. High Cart Value
        high_val_seg = classify_customer_segment(orders_count=1, total_spent=1500.0, cart_value=6000.0, has_discounts=False)
        self.assertEqual(high_val_seg, "HIGH_VALUE")

        # 3. Discount Oriented
        discount_seg = classify_customer_segment(orders_count=1, total_spent=1500.0, cart_value=1200.0, has_discounts=True)
        self.assertEqual(discount_seg, "DISCOUNT_ORIENTED")

        # 4. First-Time
        first_time_seg = classify_customer_segment(orders_count=0, total_spent=0.0, cart_value=1200.0, has_discounts=False)
        self.assertEqual(first_time_seg, "FIRST_TIME")

        # 5. Returning
        returning_seg = classify_customer_segment(orders_count=2, total_spent=2500.0, cart_value=1200.0, has_discounts=False)
        self.assertEqual(returning_seg, "RETURNING")

        # Verify message generation uses segment fallback without breaking
        msg = generate_personalized_recovery_message(
            store_name="TestStore",
            tone="luxury",
            customer_name="Alice VIP",
            items=[{"title": "Diamond Ring", "quantity": 1, "price": 10000}],
            checkout_url="https://checkout.link",
            step=1,
            customer_segment="VIP"
        )
        self.assertIn("Alice VIP", msg)

        # Ingest a VIP Checkout Webhook and check DB persistence
        webhook_headers = {
            "X-Shopify-Shop-Domain": self.shop,
            "X-Webhook-Topic": "checkouts/create",
        }
        checkout_payload = {
            "id": 998877,
            "email": "vip-alice@gmail.com",
            "total_price": "15000.00",
            "currency": "INR",
            "abandoned_checkout_url": "https://test-merchant.myshopify.com/checkouts/ac/998877",
            "customer": {
                "first_name": "Alice",
                "last_name": "VIP",
                "phone": "+918888888888",
                "orders_count": 6,
                "total_spent": "15000.00"
            },
            "line_items": [{"variant_id": 999, "title": "Golden Rolex", "price": "15000.00", "quantity": 1}]
        }

        # Simulate checkout ingestion
        response = client.post("/webhooks/checkout-abandonment", json=checkout_payload, headers=webhook_headers)
        self.assertEqual(response.status_code, 200)

        # Trigger recovery scheduling synchronously to test classification inside scheduler
        tasks.schedule_recovery_workflow("998877", self.shop)

        # Check checkout segment in DB
        with TestSyncSession() as session:
            db_checkout = session.query(AbandonedCheckout).get("998877")
            self.assertIsNotNone(db_checkout)
            self.assertEqual(db_checkout.customer_segment, "VIP")

        # Test REST API lists checkout segment
        response = client.get("/api/v1/dashboard/checkouts?limit=10", headers={"Authorization": "Bearer fake_token", "X-Shopify-Shop-Domain": self.shop})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(c.get("checkout_id") == "998877" and c.get("customer_segment") == "VIP" for c in data.get("checkouts", [])))


if __name__ == "__main__":
    unittest.main()
