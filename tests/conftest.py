import pytest


@pytest.fixture(autouse=True)
def _isolated_app_home(tmp_path_factory, monkeypatch):
    """Keep tests away from this computer's Roundtable Hold settings (saved hub, hook state)."""
    monkeypatch.setenv("ROUNDTABLE_HOME", str(tmp_path_factory.mktemp("roundtable-home")))
