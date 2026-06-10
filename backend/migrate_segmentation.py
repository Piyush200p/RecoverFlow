# backend/migrate_segmentation.py
import sys
import os
from sqlalchemy import text

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from database import sync_engine

def run_migrations():
    print("Running database migrations for AI Segmentation...")
    queries = [
        "ALTER TABLE abandoned_checkouts ADD COLUMN IF NOT EXISTS customer_segment VARCHAR(50);",
        "ALTER TABLE abandoned_carts ADD COLUMN IF NOT EXISTS customer_segment VARCHAR(50);"
    ]

    with sync_engine.begin() as conn:
        for q in queries:
            try:
                print(f"Executing: {q}")
                conn.execute(text(q))
            except Exception as e:
                print(f"Error executing query: {e}")
    print("Migrations applied successfully!")

if __name__ == "__main__":
    run_migrations()
