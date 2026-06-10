import asyncio
import os
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Setup import path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from models import Store, CreditLedger
from config import get_settings

async def main():
    # Detect if we should use localhost (from host machine) or db (within docker)
    # Check if we can connect to localhost:5432 first, fallback to setting host
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

    async with async_session_factory() as session:
        # Check if store already exists
        shop_domain = "recoverflow-dev.myshopify.com"
        result = await session.execute(select(Store).where(Store.shopify_domain == shop_domain))
        store = result.scalar_one_or_none()

        if store:
            print(f"Store {shop_domain} already exists in database. Updating plan to GROWTH...")
            store.subscription_plan = "GROWTH"
            await session.commit()
        else:
            print(f"Creating dev store {shop_domain}...")
            store = Store(
                shopify_domain=shop_domain,
                access_token="shp_offline_token_dev_12345",
                subscription_plan="GROWTH",
                store_name="RecoverFlow Dev Store",
                brand_tone="friendly",
                is_active=True,
            )
            session.add(store)
            
            ledger = CreditLedger(
                shopify_domain=shop_domain,
                credits_remaining=50,
            )
            session.add(ledger)
            
            await session.commit()
            print(f"Dev store {shop_domain} successfully registered with GROWTH plan and 50 seed credits!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
