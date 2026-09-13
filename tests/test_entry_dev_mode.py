"""Entry-point dev switch tests (ticket #99 / plan §5).

The delivered default must not carry uvicorn's file-watch reload; dev mode is
explicit via --dev or RESUALIGN_DEV=1. Only the parameter-parsing seam is
unit-tested here; actual uvicorn startup is verified out-of-band.
"""

from __future__ import annotations

import pytest

from resualign.api import parse_entry_args


class TestDevModeDefault:
    def test_default_is_no_reload(self):
        assert parse_entry_args([], {})["dev"] is False

    def test_dev_flag_enables(self):
        assert parse_entry_args(["--dev"], {})["dev"] is True

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_env_enables(self, value):
        assert parse_entry_args([], {"RESUALIGN_DEV": value})["dev"] is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "nonsense"])
    def test_env_other_values_do_not_enable(self, value):
        assert parse_entry_args([], {"RESUALIGN_DEV": value})["dev"] is False

    def test_flag_wins_over_disabled_env(self):
        assert parse_entry_args(["--dev"], {"RESUALIGN_DEV": "0"})["dev"] is True


class TestHostPort:
    def test_defaults(self):
        entry = parse_entry_args([], {})
        assert entry["host"] == "127.0.0.1"
        assert entry["port"] == 8000

    def test_env_then_flag_precedence(self):
        entry = parse_entry_args(
            ["--port", "8001"], {"RESUALIGN_HOST": "0.0.0.0", "RESUALIGN_PORT": "9000"}
        )
        assert entry["host"] == "0.0.0.0"  # flag absent → env
        assert entry["port"] == 8001  # flag present → wins

    def test_invalid_port_exits(self):
        with pytest.raises(SystemExit):
            parse_entry_args(["--port", "http"], {})


class TestMainWiring:
    """main() must hand uvicorn the #99 contract: no reload by default,
    project-owned logging (log_config=None)."""

    def _capture_run(self, monkeypatch):
        import uvicorn

        captured: dict = {}
        monkeypatch.setattr(
            uvicorn, "run", lambda *a, **k: captured.update(args=a, kwargs=k)
        )
        for var in ("RESUALIGN_DEV", "RESUALIGN_HOST", "RESUALIGN_PORT"):
            monkeypatch.delenv(var, raising=False)
        return captured

    def test_default_kwargs(self, monkeypatch):
        from resualign.api import main

        captured = self._capture_run(monkeypatch)
        main([])
        assert captured["args"] == ("resualign.api:app",)
        assert captured["kwargs"]["reload"] is False
        assert captured["kwargs"]["log_config"] is None
        assert captured["kwargs"]["host"] == "127.0.0.1"
        assert captured["kwargs"]["port"] == 8000

    def test_dev_flag_flows_to_reload(self, monkeypatch):
        from resualign.api import main

        captured = self._capture_run(monkeypatch)
        main(["--dev"])
        assert captured["kwargs"]["reload"] is True
