"""Offline unit defaults: no production credentials or database connection."""
import os
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://unit:unit@127.0.0.1/unit_tests')
os.environ.setdefault('SESSION_SECRET','unit-tests-only-not-for-a-server')
os.environ.setdefault('BOOTSTRAP_ADMIN_PASSWORD','unit-tests-only-not-a-login')
