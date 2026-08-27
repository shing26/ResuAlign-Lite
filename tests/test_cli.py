from pathlib import Path
from unittest.mock import patch

import pytest

from resualign.cli import _parse_args, main
from resualign.config import _STORED_LLM_PROVIDER, build_config
from resualign.models import Report, ResuAlignConfig


@pytest.fixture(autouse=True)
def _hermetic_stored_llm():
    """Keep build_config tests deterministic when the API layer registered a
    stored-settings provider (settings router registration is process-wide,
    so CLI tests must not observe persisted UI settings)."""
    saved = _STORED_LLM_PROVIDER
    import resualign.config as config_module

    config_module._STORED_LLM_PROVIDER = None
    yield
    config_module._STORED_LLM_PROVIDER = saved


def test_parse_args_minimal():
    args = _parse_args(["resume.pdf"])
    assert str(args.resume) == "resume.pdf"
    assert args.jd is None
    assert args.jd_file is None
    assert args.api_key is None


def test_parse_args_jd_inline():
    args = _parse_args(["resume.pdf", "--jd", "Java engineer"])
    assert args.jd == "Java engineer"


def test_parse_args_jd_file():
    args = _parse_args(["resume.pdf", "--jd-file", "jd.txt"])
    assert args.jd_file == Path("jd.txt")


def test_parse_args_jd_url():
    args = _parse_args(["resume.pdf", "--jd-url", "https://example.com/job"])
    assert args.jd_url == "https://example.com/job"


def test_parse_args_mutual_exclusive():
    with pytest.raises(SystemExit):
        _parse_args(["resume.pdf", "--jd", "a", "--jd-file", "b"])


def test_parse_args_jd_url_mutually_exclusive_with_jd():
    with pytest.raises(SystemExit):
        _parse_args(
            ["resume.pdf", "--jd-url", "https://example.com/job", "--jd", "inline"]
        )


def test_parse_args_jd_url_mutually_exclusive_with_jd_file():
    with pytest.raises(SystemExit):
        _parse_args(
            ["resume.pdf", "--jd-url", "https://example.com/job", "--jd-file", "jd.txt"]
        )


def test_parse_args_quiet_flag():
    args = _parse_args(["resume.pdf", "--quiet"])
    assert args.quiet is True


def test_parse_args_quiet_flag_short():
    args = _parse_args(["resume.pdf", "-q"])
    assert args.quiet is True


def test_parse_args_quiet_default():
    args = _parse_args(["resume.pdf"])
    assert args.quiet is False


def test_parse_args_model_flag():
    args = _parse_args(["r.pdf", "--model", "gpt-4"])
    assert args.model == "gpt-4"


def test_parse_args_output_dir():
    args = _parse_args(["r.pdf", "--output-dir", "reports"])
    assert args.output_dir == Path("reports")


def test_build_config_cli_overrides_env():
    cfg = build_config(
        provider="deepseek",
        api_key="cli-key",
        model="cli-model",
    )
    assert cfg.api_key == "cli-key"
    assert cfg.model == "cli-model"
    assert cfg.provider == "deepseek"


def test_build_config_falls_back_to_env():
    from unittest.mock import patch as _patch
    with _patch("resualign.config.EnvSettings") as mock_env:
        mock_env.return_value.llm_provider = "deepseek"
        mock_env.return_value.deepseek_api_key = "env-key"
        mock_env.return_value.deepseek_model = "env-model"
        cfg = build_config()
    assert cfg.api_key == "env-key"
    assert cfg.model == "env-model"


def test_build_config_provider_from_cli():
    cfg = build_config(provider="openrouter")
    assert cfg.provider == "openrouter"


def test_main_jd_url_retired_with_pointer(tmp_path, capsys):
    """De-bloat: backend crawling retired; --jd-url exits with a pointer to
    paste / userscript ingestion instead of fetching."""
    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    with patch("resualign.cli.build_config") as mock_build, patch(
        "resualign.cli.run"
    ) as mock_run:
        mock_build.return_value = ResuAlignConfig(
            provider="deepseek", api_key="test-key", model="test-model"
        )

        with pytest.raises(SystemExit):
            main([str(fixture), "--jd-url", "https://example.com/job"])

        mock_run.assert_not_called()

    err = capsys.readouterr().err
    assert "--jd-url was retired" in err


def test_main_prints_stage_progress_to_stderr(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    with patch("resualign.cli.build_config") as mock_build, patch(
        "resualign.cli.run"
    ) as mock_run:
        mock_build.return_value = ResuAlignConfig(
            provider="deepseek", api_key="test-key", model="test-model"
        )

        def fake_run(config, resume_text, jd_text, **kwargs):
            kwargs["on_stage"]("diagnose", "Analyzing resume...")
            kwargs["on_stage"]("tailoring", "Tailoring resume to JD...")
            return Report(score=75, skills=[], issues=[], model="test-model")

        mock_run.side_effect = fake_run

        main(
            [
                str(fixture),
                "--jd",
                "Java backend engineer",
                "--output-dir",
                str(tmp_path),
            ]
        )

    err = capsys.readouterr().err
    assert "[diagnose]" in err
    assert "Analyzing resume..." in err
    assert "[tailoring]" in err


def test_main_quiet_suppresses_stage_progress(tmp_path, capsys):
    fixture = Path(__file__).parent / "fixtures" / "sample.txt"
    with patch("resualign.cli.build_config") as mock_build, patch(
        "resualign.cli.run"
    ) as mock_run:
        mock_build.return_value = ResuAlignConfig(
            provider="deepseek", api_key="test-key", model="test-model"
        )

        def fake_run(config, resume_text, jd_text, **kwargs):
            kwargs["on_stage"]("diagnose", "Analyzing resume...")
            return Report(score=75, skills=[], issues=[], model="test-model")

        mock_run.side_effect = fake_run

        main(
            [
                str(fixture),
                "--quiet",
                "--output-dir",
                str(tmp_path),
            ]
        )

    captured = capsys.readouterr()
    assert "diagnose" not in captured.err
    assert "Score:" in captured.out
