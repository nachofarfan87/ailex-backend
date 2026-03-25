"""
Configuración de pytest para los tests de AILEX.

Requiere:
  pip install pytest pytest-asyncio httpx

Con asyncio_mode="auto", las funciones async y fixtures async se
manejan automáticamente sin necesidad de @pytest.mark.asyncio explícito.
"""
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.auth.dependencies import get_current_user
from app.main import app


# Fixture compartida disponible para todos los módulos de tests
@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: type(
        "TestUser",
        (),
        {
            "id": "test-user",
            "username": "tester",
            "email": "tester@example.com",
            "is_active": True,
        },
    )()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
