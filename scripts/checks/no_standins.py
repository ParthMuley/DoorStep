"""pytest plugin (Developer B): switch off the stand-in routes in A's test backend
(`tests/integration/fake_v2_backend.py`: /link, /register, /organizations/{org}/invites)
so A's agent tests run against B's REAL routes. Used by scripts/check_integration.sh.
If A has already deleted the stand-ins, this does nothing."""

from fastapi import APIRouter

DISABLED: list[str] = []


def pytest_configure(config):
    import importlib

    try:
        module = importlib.import_module("tests.integration.fake_v2_backend")
    except ImportError:
        return
    if not hasattr(module, "build_link_standin"):
        return

    def no_routes(*_args, **_kwargs):
        DISABLED.append("build_link_standin")
        return APIRouter()

    module.build_link_standin = no_routes


def pytest_terminal_summary(terminalreporter):
    used = "disabled" if DISABLED else "none found (already removed, or not used by these tests)"
    terminalreporter.write_line(f"[no_standins] A's stand-in routes: {used}")
