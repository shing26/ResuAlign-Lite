"""Tests for the LLM job classification stage."""

from resualign.classifier import classify_job, normalize_enum


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def chat_json(self, system, user, model=None):
        self.calls.append((system, user))
        return self.response


def test_classify_returns_controlled_vocabulary():
    client = _FakeClient(
        {
            "job_function": "后端开发",
            "seniority": "高级工程师",
            "tech_tags": ["Python", "FastAPI", "Kubernetes"],
        }
    )

    result = classify_job(client, "Python backend engineer.")

    assert result["job_function"] == "后端"
    assert result["seniority"] == "高级"
    assert result["tech_tags"] == ["Python", "FastAPI", "Kubernetes"]
    # R4: 04b-PE §2.7 新提示词中文化，首行版本标记作为稳定断言锚点。
    assert "PROMPT_VERSION: classifier/v2" in client.calls[0][0]


def test_classify_normalizes_unknown_values():
    client = _FakeClient(
        {
            "job_function": "mystery-role",
            "seniority": "chief wizard",
            "tech_tags": [],
        }
    )

    result = classify_job(client, "Some job.")

    assert result["job_function"] == "其他"
    assert result["seniority"] == "未知"
    assert result["tech_tags"] == []


def test_classify_uses_custom_vocabulary():
    client = _FakeClient(
        {
            "job_function": "AI 应用",
            "seniority": "P7",
            "tech_tags": ["PyTorch"],
        }
    )

    result = classify_job(
        client,
        "AI application engineer.",
        job_functions=["AI 应用"],
        seniorities=["P7"],
    )

    assert result["job_function"] == "AI 应用"
    assert result["seniority"] == "P7"
    assert "AI 应用" in client.calls[0][1]
    assert "P7" in client.calls[0][1]


def test_normalize_enum_substring_and_default():
    assert normalize_enum("前端开发", ("前端", "后端"), "其他") == "前端"
    assert normalize_enum("Frontend", ("前端", "后端"), "其他") == "其他"
    assert normalize_enum("高级", ("高级",), "未知") == "高级"
