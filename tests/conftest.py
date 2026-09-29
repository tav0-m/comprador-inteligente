"""Configuracion aislada de pytest: sin red, Redis ni tiendas externas."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST_DB = ROOT / "test_comprador.db"
sys.path.insert(0, str(ROOT))

TEST_DB.unlink(missing_ok=True)
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["REDIS_URL"] = ""
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["APP_SECRET_KEY"] = "test-secret-key"
# Los tests nunca deben enviar emails reales aunque .env tenga credenciales SMTP.
os.environ["ALERT_EMAIL_FROM"] = ""
os.environ["ALERT_EMAIL_PASSWORD"] = ""
os.environ["MERCADOLIBRE_CLIENT_ID"] = ""
os.environ["MERCADOLIBRE_CLIENT_SECRET"] = ""
# Limites holgados para la suite; el limitador se prueba aparte con reglas propias.
os.environ["ALERT_CREATE_LIMIT_PER_HOUR"] = "1000"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["TRUSTED_HOSTS"] = '["localhost","127.0.0.1","testserver"]'
os.environ["ENABLE_SERPAPI"] = "false"
os.environ["ENABLE_MERCADOLIBRE"] = "false"
os.environ["ENABLE_LOCAL_CSV"] = "false"
os.environ["ENABLE_SODIMAC"] = "false"
os.environ["ENABLE_EASY"] = "false"
os.environ["ENABLE_FALABELLA"] = "false"
os.environ["ENABLE_PARIS"] = "false"
os.environ["ENABLE_CONSTRUMART"] = "false"


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    from app.database import init_db

    init_db()  # esquema disponible tambien para tests que usan la base sin levantar la app
    yield
    from app.database import engine

    engine.dispose()
    TEST_DB.unlink(missing_ok=True)
