import pytest

from backend.config import settings
from backend.routers.insights import router as insights_router

from .conftest import make_client


@pytest.fixture
async def client(db_and_sessionmaker):
    _, Session = db_and_sessionmaker
    async with make_client(insights_router, "/api/insights", Session) as c:
        yield c


async def test_models_lists_dashboard_picker_models(client):
    resp = await client.get("/api/insights/models")

    assert resp.status_code == 200
    assert resp.json() == {"models": settings.llm.available_dashboard_models()}
