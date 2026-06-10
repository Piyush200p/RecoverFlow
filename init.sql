-- ============================================================
-- RecoverFlow AI — PostgreSQL Schema v1.1.0
-- Executed once on first container startup via docker-entrypoint
-- ============================================================

-- Enable UUID generation (optional future use)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------
-- 1. Stores
-- Core merchant record. One row per Shopify installation.
-- -----------------------------------------------------------
CREATE TABLE stores (
    shopify_domain      VARCHAR(255) PRIMARY KEY,
    access_token        VARCHAR(515) NOT NULL,
    subscription_plan   VARCHAR(50)  DEFAULT 'FREE'
        CHECK (subscription_plan IN ('FREE', 'STARTER', 'GROWTH', 'SCALE')),
    whatsapp_business_id    VARCHAR(255),
    whatsapp_access_token   TEXT,
    whatsapp_phone_number_id VARCHAR(255),
    store_name          VARCHAR(255),
    brand_tone          VARCHAR(50) DEFAULT 'friendly',
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 2. Credit Ledgers
-- Real-time credit balance for each store. 1-to-1 with stores.
-- -----------------------------------------------------------
CREATE TABLE credit_ledgers (
    shopify_domain      VARCHAR(255) PRIMARY KEY
        REFERENCES stores(shopify_domain) ON DELETE CASCADE,
    credits_remaining   INTEGER DEFAULT 0,
    credits_used        INTEGER DEFAULT 0,
    updated_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 3. Abandoned Checkouts
-- Each row = one abandoned cart event from Shopify webhooks.
-- -----------------------------------------------------------
CREATE TABLE abandoned_checkouts (
    checkout_id         VARCHAR(255) PRIMARY KEY,
    shopify_domain      VARCHAR(255)
        REFERENCES stores(shopify_domain) ON DELETE CASCADE,
    customer_name       VARCHAR(255),
    customer_phone      VARCHAR(50),          -- E.164 format required
    cart_json           JSONB NOT NULL,
    total_price         DECIMAL(10, 2),
    currency            VARCHAR(10) DEFAULT 'INR',
    recovery_status     VARCHAR(50) DEFAULT 'PENDING'
        CHECK (recovery_status IN (
            'PENDING', 'PROCESSING', 'RECOVERED', 'FAILED', 'EXHAUSTED'
        )),
    customer_segment    VARCHAR(50),
    created_at          TIMESTAMP WITH TIME ZONE,
    recovered_at        TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_checkouts_domain ON abandoned_checkouts(shopify_domain);
CREATE INDEX idx_checkouts_status ON abandoned_checkouts(recovery_status);

-- -----------------------------------------------------------
-- 4. Recovery Schedules
-- Tracks the 3-step reminder sequence for each checkout.
-- -----------------------------------------------------------
CREATE TABLE recovery_schedules (
    id                  SERIAL PRIMARY KEY,
    checkout_id         VARCHAR(255)
        REFERENCES abandoned_checkouts(checkout_id) ON DELETE CASCADE,
    step_number         INT NOT NULL CHECK (step_number BETWEEN 1 AND 5),
    scheduled_for       TIMESTAMP WITH TIME ZONE NOT NULL,
    status              VARCHAR(50) DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'SENT', 'FAILED', 'CANCELLED')),
    celery_task_id      VARCHAR(255),
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_schedules_checkout ON recovery_schedules(checkout_id);
CREATE INDEX idx_schedules_status   ON recovery_schedules(status);

-- -----------------------------------------------------------
-- 5. Sent Messages
-- Immutable audit log of every WhatsApp message dispatched.
-- -----------------------------------------------------------
CREATE TABLE sent_messages (
    id                  SERIAL PRIMARY KEY,
    checkout_id         VARCHAR(255)
        REFERENCES abandoned_checkouts(checkout_id) ON DELETE CASCADE,
    shopify_domain      VARCHAR(255)
        REFERENCES stores(shopify_domain) ON DELETE CASCADE,
    step_number         INT,
    message_body        TEXT,
    template_variant    VARCHAR(10),           -- 'A' or 'B' for A/B testing
    credits_used        INT DEFAULT 1,
    status              VARCHAR(50) DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'SENT', 'FAILED')),
    error_message       TEXT,
    whatsapp_message_id VARCHAR(255),          -- Meta API message ID
    sent_at             TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_messages_domain ON sent_messages(shopify_domain);

-- -----------------------------------------------------------
-- 6. Recharge History
-- Tracks credit top-up purchases.
-- -----------------------------------------------------------
CREATE TABLE recharge_history (
    id                  SERIAL PRIMARY KEY,
    shopify_domain      VARCHAR(255)
        REFERENCES stores(shopify_domain) ON DELETE CASCADE,
    credits_added       INTEGER NOT NULL,
    amount_paid         DECIMAL(10, 2) NOT NULL,
    currency            VARCHAR(10) DEFAULT 'INR',
    shopify_charge_id   VARCHAR(255),          -- Shopify one-time charge ID
    paid_at             TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------
-- 7. Recovered Orders
-- Links a Shopify order back to the abandoned checkout it recovered.
-- Drives the ROI dashboard metrics.
-- -----------------------------------------------------------
CREATE TABLE recovered_orders (
    id                  SERIAL PRIMARY KEY,
    order_id            VARCHAR(255) UNIQUE NOT NULL,
    checkout_id         VARCHAR(255)
        REFERENCES abandoned_checkouts(checkout_id) ON DELETE SET NULL,
    shopify_domain      VARCHAR(255)
        REFERENCES stores(shopify_domain) ON DELETE CASCADE,
    recovered_revenue   DECIMAL(10, 2) NOT NULL,
    currency            VARCHAR(10) DEFAULT 'INR',
    recovered_at        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_recovered_domain ON recovered_orders(shopify_domain);
