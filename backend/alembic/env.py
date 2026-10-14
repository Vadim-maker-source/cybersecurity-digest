import asyncio
from alembic import context
from app.models import Base, engine

def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction(): context.run_migrations()

async def main():
    async with engine.connect() as connection: await connection.run_sync(migrate)
    await engine.dispose()

asyncio.run(main())
