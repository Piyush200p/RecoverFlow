"""
RecoverFlow AI — SQLAlchemy ORM Models
========================================
Complete model definitions for all 7 database entities.
Each model maps 1-to-1 with the tables defined in init.sql.

Relationships are configured for efficient eager/lazy loading
in dashboard queries and worker tasks.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    Text,
    Numeric,
    ForeignKey,
    DateTime,
    CheckConstraint,
    Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ─────────────────────────────────────────────────────────────
# 1. Store
# ─────────────────────────────────────────────────────────────
class Store(Base):
    """
    Represents a single Shopify merchant installation.
    Primary key is the canonical shop domain (e.g. 'my-shop.myshopify.com').
    """

    __tablename__ = "stores"

    shopify_domain: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )
    access_token: Mapped[str] = mapped_column(String(515), nullable=False)
    subscription_plan: Mapped[str] = mapped_column(
        String(50), default="FREE"
    )
    whatsapp_business_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    whatsapp_access_token: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    whatsapp_phone_number_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    store_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    brand_tone: Mapped[str] = mapped_column(
        String(50), default="friendly"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cart_recovery_active: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    credit_ledger: Mapped[Optional["CreditLedger"]] = relationship(
        back_populates="store", uselist=False, cascade="all, delete-orphan"
    )
    abandoned_checkouts: Mapped[List["AbandonedCheckout"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    abandoned_carts: Mapped[List["AbandonedCart"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    sent_messages: Mapped[List["SentMessage"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    recharge_history: Mapped[List["RechargeHistory"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )
    recovered_orders: Mapped[List["RecoveredOrder"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "subscription_plan IN ('FREE', 'STARTER', 'GROWTH', 'SCALE')",
            name="ck_stores_plan",
        ),
    )

    def __repr__(self) -> str:
        return f"<Store {self.shopify_domain} plan={self.subscription_plan}>"


# ─────────────────────────────────────────────────────────────
# 2. Credit Ledger
# ─────────────────────────────────────────────────────────────
class CreditLedger(Base):
    """
    Real-time credit balance for a store.
    One-to-one relationship with Store.
    credits_remaining is checked before every message dispatch.
    """

    __tablename__ = "credit_ledgers"

    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
        primary_key=True,
    )
    credits_remaining: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    store: Mapped["Store"] = relationship(back_populates="credit_ledger")

    def has_credits(self) -> bool:
        """Quick check used by Celery workers before dispatching."""
        return self.credits_remaining > 0

    def deduct(self, amount: int = 1) -> bool:
        """Atomically deduct credits. Returns False if insufficient."""
        if self.credits_remaining < amount:
            return False
        self.credits_remaining -= amount
        self.credits_used += amount
        return True

    def __repr__(self) -> str:
        return (
            f"<CreditLedger {self.shopify_domain} "
            f"remaining={self.credits_remaining} used={self.credits_used}>"
        )


# ─────────────────────────────────────────────────────────────
# 3. Abandoned Checkout
# ─────────────────────────────────────────────────────────────
class AbandonedCheckout(Base):
    """
    Each row represents one abandoned cart event ingested from
    Shopify's checkouts/create or checkouts/update webhook.
    """

    __tablename__ = "abandoned_checkouts"

    checkout_id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )
    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
    )
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    customer_phone: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    cart_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    recovery_status: Mapped[str] = mapped_column(
        String(50), default="PENDING"
    )
    customer_segment: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ────────────────────────────────────────
    store: Mapped["Store"] = relationship(back_populates="abandoned_checkouts")
    recovery_schedules: Mapped[List["RecoverySchedule"]] = relationship(
        back_populates="checkout", cascade="all, delete-orphan"
    )
    sent_messages: Mapped[List["SentMessage"]] = relationship(
        back_populates="checkout", cascade="all, delete-orphan"
    )
    recovered_order: Mapped[Optional["RecoveredOrder"]] = relationship(
        back_populates="checkout", uselist=False
    )

    __table_args__ = (
        CheckConstraint(
            "recovery_status IN ('PENDING','PROCESSING','RECOVERED','FAILED','EXHAUSTED')",
            name="ck_checkouts_status",
        ),
        Index("idx_checkouts_domain", "shopify_domain"),
        Index("idx_checkouts_status", "recovery_status"),
    )

    @property
    def is_recoverable(self) -> bool:
        """True if the checkout has not yet been recovered or exhausted."""
        return self.recovery_status in ("PENDING", "PROCESSING")

    def __repr__(self) -> str:
        return (
            f"<AbandonedCheckout {self.checkout_id} "
            f"status={self.recovery_status} total={self.total_price}>"
        )


# ─────────────────────────────────────────────────────────────
# 4. Recovery Schedule
# ─────────────────────────────────────────────────────────────
class RecoverySchedule(Base):
    """
    Tracks each step of the multi-step reminder sequence.
    step_number 1..5 maps to configurable delay intervals.
    celery_task_id is stored so tasks can be revoked on recovery.
    """

    __tablename__ = "recovery_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkout_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("abandoned_checkouts.checkout_id", ondelete="CASCADE"),
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="QUEUED")
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    checkout: Mapped["AbandonedCheckout"] = relationship(
        back_populates="recovery_schedules"
    )

    __table_args__ = (
        CheckConstraint(
            "step_number BETWEEN 1 AND 5",
            name="ck_schedules_step",
        ),
        CheckConstraint(
            "status IN ('QUEUED','SENT','FAILED','CANCELLED')",
            name="ck_schedules_status",
        ),
        Index("idx_schedules_checkout", "checkout_id"),
        Index("idx_schedules_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecoverySchedule step={self.step_number} "
            f"status={self.status} for={self.checkout_id}>"
        )


# ─────────────────────────────────────────────────────────────
# 5. Sent Message
# ─────────────────────────────────────────────────────────────
class SentMessage(Base):
    """
    Immutable audit log of every WhatsApp message dispatched.
    Used for analytics, A/B testing analysis, and billing verification.
    """

    __tablename__ = "sent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkout_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("abandoned_checkouts.checkout_id", ondelete="CASCADE"),
        nullable=True,
    )
    cart_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("abandoned_carts.cart_id", ondelete="CASCADE"),
        nullable=True,
    )
    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
    )
    step_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_variant: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )
    credits_used: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(50), default="PENDING")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    checkout: Mapped[Optional["AbandonedCheckout"]] = relationship(
        back_populates="sent_messages"
    )
    cart: Mapped[Optional["AbandonedCart"]] = relationship(
        back_populates="sent_messages"
    )
    store: Mapped["Store"] = relationship(back_populates="sent_messages")

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','SENT','FAILED')",
            name="ck_messages_status",
        ),
        Index("idx_messages_domain", "shopify_domain"),
    )

    def __repr__(self) -> str:
        return (
            f"<SentMessage id={self.id} step={self.step_number} "
            f"status={self.status}>"
        )


# ─────────────────────────────────────────────────────────────
# 6. Recharge History
# ─────────────────────────────────────────────────────────────
class RechargeHistory(Base):
    """
    Tracks every credit top-up purchase.
    Linked to Shopify one-time charges via shopify_charge_id.
    """

    __tablename__ = "recharge_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
    )
    credits_added: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    shopify_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    store: Mapped["Store"] = relationship(back_populates="recharge_history")

    def __repr__(self) -> str:
        return (
            f"<RechargeHistory +{self.credits_added} credits "
            f"₹{self.amount_paid} for {self.shopify_domain}>"
        )


# ─────────────────────────────────────────────────────────────
# 7. Recovered Order
# ─────────────────────────────────────────────────────────────
class RecoveredOrder(Base):
    """
    Links a completed Shopify order back to the abandoned checkout
    that triggered the recovery campaign.
    Powers the ROI dashboard (Recovered Revenue, Net Value, Recovery Rate).
    """

    __tablename__ = "recovered_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    checkout_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("abandoned_checkouts.checkout_id", ondelete="SET NULL"),
        nullable=True,
    )
    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
    )
    recovered_revenue: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    recovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    checkout: Mapped[Optional["AbandonedCheckout"]] = relationship(
        back_populates="recovered_order"
    )
    store: Mapped["Store"] = relationship(back_populates="recovered_orders")

    __table_args__ = (
        Index("idx_recovered_domain", "shopify_domain"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecoveredOrder order={self.order_id} "
            f"revenue=₹{self.recovered_revenue}>"
        )


# ─────────────────────────────────────────────────────────────
# 8. Abandoned Cart
# ─────────────────────────────────────────────────────────────
class AbandonedCart(Base):
    """
    Each row represents one abandoned cart event ingested from
    Shopify's carts/create or carts/update webhook.
    """

    __tablename__ = "abandoned_carts"

    cart_id: Mapped[str] = mapped_column(
        String(255), primary_key=True
    )
    shopify_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("stores.shopify_domain", ondelete="CASCADE"),
    )
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    customer_phone: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    cart_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    recovery_status: Mapped[str] = mapped_column(
        String(50), default="PENDING"
    )
    customer_segment: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ────────────────────────────────────────
    store: Mapped["Store"] = relationship(back_populates="abandoned_carts")
    recovery_schedules: Mapped[List["CartRecoverySchedule"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )
    sent_messages: Mapped[List["SentMessage"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "recovery_status IN ('PENDING','PROCESSING','RECOVERED','FAILED','EXHAUSTED')",
            name="ck_carts_status",
        ),
        Index("idx_carts_domain", "shopify_domain"),
        Index("idx_carts_status", "recovery_status"),
    )

    @property
    def is_recoverable(self) -> bool:
        """True if the cart has not yet been recovered or exhausted."""
        return self.recovery_status in ("PENDING", "PROCESSING")

    def __repr__(self) -> str:
        return (
            f"<AbandonedCart {self.cart_id} "
            f"status={self.recovery_status} total={self.total_price}>"
        )


# ─────────────────────────────────────────────────────────────
# 9. Cart Recovery Schedule
# ─────────────────────────────────────────────────────────────
class CartRecoverySchedule(Base):
    """
    Tracks the single reminder schedule for an abandoned cart.
    """

    __tablename__ = "cart_recovery_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cart_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("abandoned_carts.cart_id", ondelete="CASCADE"),
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="QUEUED")
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────────
    cart: Mapped["AbandonedCart"] = relationship(
        back_populates="recovery_schedules"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED','SENT','FAILED','CANCELLED')",
            name="ck_cart_schedules_status",
        ),
        Index("idx_cart_schedules_cart", "cart_id"),
        Index("idx_cart_schedules_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<CartRecoverySchedule status={self.status} for={self.cart_id}>"
        )
