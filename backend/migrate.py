# backend/migrate.py
import sys
import os
from sqlalchemy import text

# Setup import path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from database import sync_engine

def run_migrations():
    print("Running database migrations...")
    queries = [
        # 1. Add cart_recovery_active to stores
        """
        ALTER TABLE stores 
        ADD COLUMN IF NOT EXISTS cart_recovery_active BOOLEAN DEFAULT FALSE;
        """,
        # 2. Create abandoned_carts table
        """
        CREATE TABLE IF NOT EXISTS abandoned_carts (
            cart_id         VARCHAR(255) PRIMARY KEY,
            shopify_domain  VARCHAR(255) REFERENCES stores(shopify_domain) ON DELETE CASCADE,
            customer_name   VARCHAR(255),
            customer_phone  VARCHAR(50),
            cart_json       JSONB NOT NULL,
            total_price     DECIMAL(10, 2),
            currency        VARCHAR(10) DEFAULT 'INR',
            recovery_status VARCHAR(50) DEFAULT 'PENDING'
                CHECK (recovery_status IN ('PENDING', 'PROCESSING', 'RECOVERED', 'FAILED', 'EXHAUSTED')),
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            recovered_at    TIMESTAMP WITH TIME ZONE
        );
        """,
        # 3. Create cart_recovery_schedules table
        """
        CREATE TABLE IF NOT EXISTS cart_recovery_schedules (
            id              SERIAL PRIMARY KEY,
            cart_id         VARCHAR(255) REFERENCES abandoned_carts(cart_id) ON DELETE CASCADE,
            scheduled_for   TIMESTAMP WITH TIME ZONE NOT NULL,
            status          VARCHAR(50) DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED', 'SENT', 'FAILED', 'CANCELLED')),
            celery_task_id  VARCHAR(255),
            created_at      TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        # 4. Update sent_messages table to make checkout_id nullable and add cart_id
        """
        ALTER TABLE sent_messages 
        ALTER COLUMN checkout_id DROP NOT NULL;
        """,
        """
        ALTER TABLE sent_messages 
        ADD COLUMN IF NOT EXISTS cart_id VARCHAR(255) REFERENCES abandoned_carts(cart_id) ON DELETE CASCADE;
        """,
        # 5. Add reminder settings to stores table
        """
        ALTER TABLE stores 
        ADD COLUMN IF NOT EXISTS reminder_count INTEGER DEFAULT 3;
        """,
        """
        ALTER TABLE stores 
        ADD COLUMN IF NOT EXISTS step_1_delay INTEGER DEFAULT 1800;
        """,
        """
        ALTER TABLE stores 
        ADD COLUMN IF NOT EXISTS step_2_delay INTEGER DEFAULT 21600;
        """,
        """
        ALTER TABLE stores 
        ADD COLUMN IF NOT EXISTS step_3_delay INTEGER DEFAULT 86400;
        """
    ]

    with sync_engine.begin() as conn:
        for q in queries:
            try:
                print(f"Executing: {q.strip().splitlines()[0]}...")
                conn.execute(text(q))
            except Exception as e:
                print(f"Error executing query: {e}")
                # Don't fail the whole script if it's already modified
                continue
    print("Database migrations applied successfully!")

if __name__ == "__main__":
    run_migrations()
