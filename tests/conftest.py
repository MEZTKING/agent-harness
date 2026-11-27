import pytest


@pytest.fixture(autouse=True)
def _isolated_app_home(tmp_path_factory, monkeypatch):
    """Keep tests away from this computer's Roundtable Hold settings (saved hub, hook state)."""
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path_factory.mktemp("roundtable-home")))


@pytest.fixture(autouse=True)
def _empty_key_vault():
    """Every test starts with Roundtable's in-memory key vault empty (core/secrets.py)."""
    from roundtable.core import secrets as vault

    vault.clear()
    yield
    vault.clear()


@pytest.fixture(autouse=True)
def _discovery_on_a_free_port(monkeypatch):
    """A phone server started in a test answers the Wi-Fi probe on any free port, never this PC's real one."""
    from roundtable.phone import PhoneAccess

    monkeypatch.setattr(PhoneAccess, "discovery_port", 0)
