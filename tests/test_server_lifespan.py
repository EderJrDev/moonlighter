import pytest
from moonlighter.core.config import ConfigError
from moonlighter.server import AppContext, lifespan, mcp


async def test_lifespan_yields_populated_appcontext(temporary_database):
    async with lifespan(mcp) as app_context:
        assert isinstance(app_context, AppContext)
        assert isinstance(app_context.config, dict)
        assert app_context.llm_caller is not None
        assert isinstance(app_context.startup_warnings, list)


async def test_lifespan_rejects_invalid_config(temporary_database, monkeypatch):
    import moonlighter.server as server

    bad = {"scan_concurrency": "five"}  # will fail validate_config
    monkeypatch.setattr(server, "load_config", lambda: bad)
    with pytest.raises(ConfigError):
        async with lifespan(mcp):
            pass  # must raise before yielding


async def test_lifespan_prints_permission_warnings(temporary_database, monkeypatch, capsys):
    import moonlighter.server as server

    monkeypatch.setattr(server, "harden_permissions", lambda: ["could not chmod ~/.moonlighter"])
    async with lifespan(mcp) as app_context:
        assert app_context.permission_warnings == ["could not chmod ~/.moonlighter"]
    assert "could not chmod ~/.moonlighter" in capsys.readouterr().err


def test_importing_server_has_no_side_effects(monkeypatch):
    import importlib
    import sys

    calls: list[str] = []
    import moonlighter.core.config as cfg
    import moonlighter.core.db as db
    import moonlighter.core.log as log_mod

    monkeypatch.setattr(
        cfg,
        "load_config",
        lambda *positional_arguments, **keyword_arguments: calls.append("load_config") or {},
    )
    monkeypatch.setattr(
        db, "init_db", lambda *positional_arguments, **keyword_arguments: calls.append("init_db")
    )
    monkeypatch.setattr(
        cfg,
        "harden_permissions",
        lambda *positional_arguments, **keyword_arguments: calls.append("harden") or [],
    )
    monkeypatch.setattr(
        log_mod,
        "setup",
        lambda *positional_arguments, **keyword_arguments: calls.append("setup_logging"),
    )
    sys.modules.pop("moonlighter.server", None)
    importlib.import_module("moonlighter.server")
    assert calls == []  # importing the server must not load config / init db / harden perms
