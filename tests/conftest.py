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


@pytest.fixture(autouse=True)
def _no_build_tools(monkeypatch, tmp_path_factory):
    """The ship step sees a made-up computer with no build tools (no Java, no Android SDK), so no test runs a
    real Gradle or npm build because this machine happens to have one. A test about shipping brings its own."""
    from roundtable import prereq
    from roundtable.harness.shipstage import ShipStage

    home = tmp_path_factory.mktemp("no-build-tools")
    bare = prereq.System(os=prereq._os_name(), path=[], env={}, home=home, root=home,
                         run=lambda argv, timeout: (1, ""))
    monkeypatch.setattr(ShipStage, "ship_system", bare)


@pytest.fixture(autouse=True)
def _no_real_browser_in_runs(monkeypatch):
    """A run's finishing step and play-test never drive a real browser in the tests, whatever this machine has
    installed: their checks read as "couldn't be checked here". Tests that walk or play bring a fake one
    (``journey_walker``, ``play_driver``); tests/test_journeys.py still tries a real browser directly."""
    from roundtable.harness import journeys, playtest
    from roundtable.harness.finishstage import FinishStage

    def no_browser(jobs):
        raise journeys.NoWalker("there's no browser in the tests")

    class NoDriver:
        def __init__(self):
            raise playtest.NoDriver("there's no browser in the tests")

    monkeypatch.setattr(FinishStage, "journey_walker", staticmethod(no_browser))
    monkeypatch.setattr(playtest, "PlaywrightDriver", NoDriver)
