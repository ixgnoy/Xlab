import httpx
import pytest

from crest_graph import store


@pytest.fixture(autouse=True)
def isolated_instagram(tmp_path, monkeypatch):
    """Every test uses a temp DB and DRY-RUN Instagram unless it injects a live client."""
    monkeypatch.setenv("PERSONALAB_DB", str(tmp_path / "personalab.db"))
    monkeypatch.setenv("IG_ACCESS_TOKEN", "")
    monkeypatch.setenv("IG_USER_ID", "")
    yield
    if store._store is not None:
        store._store.close()
        store._store = None


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never touch the network: real transports fail; httpx.MockTransport clients still work."""

    def refuse(self, request):
        raise httpx.ConnectError("network disabled in tests", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
