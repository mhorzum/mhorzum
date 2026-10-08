import os

# Ayarlar import sırasında okunduğu için app'ten önce ayarlanmalı
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:5433/borsa_test"
)
os.environ["DATA_PROVIDER"] = "demo"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AUTO_BOOTSTRAP"] = "false"
os.environ["FETCH_WORKERS"] = "2"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)

import pytest  # noqa: E402

from app import db  # noqa: E402
from app.providers.demo import DemoProvider  # noqa: E402

TEST_TICKERS = {"THYAO", "GARAN", "AAPL", "JPM"}


@pytest.fixture()
def fresh_db():
    """Boş şema + migration'lar."""
    db.init_pool()
    with db.connection() as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    db.migrate()
    yield
    db.close_pool()


class SmallDemo(DemoProvider):
    def universe(self):
        return [s for s in super().universe() if s.ticker in TEST_TICKERS]


@pytest.fixture()
def provider(monkeypatch):
    p = SmallDemo()
    import app.ingest
    import app.jobs

    monkeypatch.setattr(app.ingest, "get_provider", lambda: p)
    monkeypatch.setattr(app.jobs, "get_provider", lambda: p)
    return p
