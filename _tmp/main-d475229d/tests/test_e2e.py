import json
import os
from pathlib import Path

import pytest

from resualign.cli import main
from resualign.config import (
    _STORED_LLM_PROVIDER,
    register_stored_llm_provider,
)

FIXTURES = Path(__file__).parent / "fixtures"

def setup_env():
    os.environ["DEEPSEEK_API_KEY"] = "test-key-e2e"
    os.environ["DEEPSEEK_MODEL"] = "test-model-e2e"

def cleanup_env():
    os.environ.pop("DEEPSEEK_API_KEY", "")
    os.environ.pop("DEEPSEEK_MODEL", "")

def cleanup_reports():
    for f in Path.cwd().glob("resualign-report-*.json"):
        f.unlink()

def test_e2e_diagnosis_only(httpx_mock, capsys):
    setup_env()
    cleanup_reports()
    httpx_mock.add_response(json={"choices":[{"message":{"content":'{"score":78,"skills":["Python"],"issues":["Too long"]}'}}]})
    main([str(FIXTURES / "sample.txt")])
    out = capsys.readouterr().out
    assert "/100" in out
    assert "78" in out
    data = json.loads(
        list(Path.cwd().glob("resualign-report-*.json"))[0].read_text(encoding="utf-8")
    )
    assert data["score"] == 78
    cleanup_reports()
    cleanup_env()

def test_e2e_with_alignment(httpx_mock, capsys):
    setup_env()
    cleanup_reports()
    rs = [
        '{"score":85,"skills":["Java","Spring"],"issues":[]}',
        '{"must_have_skills":["Java"],"nice_to_have_skills":[],"soft_skills":[],"business_scenarios":["Backend"],"min_years_experience":null,"education_requirements":[]}',
        '{"missing_keywords":[],"misaligned_emphasis":[],"strength_matches":[]}',
        '{"sections":{"exp":"Built services" },"diffs":[{"type":"modify","original":"Java, Spring Boot","proposed":"Java, Spring Boot, and backend services", "reason":"JD match","confidence":"high","provenance_quote":"Java, Spring Boot"}]}',
    ]
    for r in rs:
        httpx_mock.add_response(json={"choices":[{"message":{"content":r}}]})
    main([str(FIXTURES / "sample.txt"), "--jd", "Java backend engineer"])
    out = capsys.readouterr().out
    assert "/100" in out
    assert "85" in out
    data = json.loads(
        list(Path.cwd().glob("resualign-report-*.json"))[0].read_text(encoding="utf-8")
    )
    assert len(data["diffs"]) == 1
    cleanup_reports()
    cleanup_env()

def test_e2e_missing_api_key(capsys):
    saved_env = os.environ.pop("DEEPSEEK_API_KEY", "")
    saved_provider = _STORED_LLM_PROVIDER
    register_stored_llm_provider(None)
    env_file = Path("D:/ResuAlign-Lite/.env")
    renamed = None
    if env_file.exists():
        renamed = Path(str(env_file) + ".bak")
        env_file.rename(renamed)
    try:
        with pytest.raises(SystemExit):
            main([str(FIXTURES / "sample.txt")])
        assert "LLM not configured" in capsys.readouterr().err
    finally:
        if renamed is not None:
            renamed.rename(env_file)
        register_stored_llm_provider(saved_provider)
        if saved_env:
            os.environ["DEEPSEEK_API_KEY"] = saved_env
