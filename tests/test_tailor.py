import pytest

from resualign.models import TailoredResume
from resualign.tailor import tailor_resume


class MockLLM:
    def __init__(self, result=None):
        self.result = result or {
            "sections": {
                "experience": "Built high-throughput backend services using Java."
            },
            "diffs": [{
                "type": "modify",
                "original": "Worked on backend",
                "proposed": "Built high-throughput backend services",
                "reason": "JD emphasizes performance",
                "confidence": "high",
                "provenance": "Worked on backend",
            }],
        }
        self.last_system = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        return self.result


def test_tailor_resume_returns_tailoredresume():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume text...", "Gap report...")
    assert isinstance(result, TailoredResume)
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance == "Worked on backend"


def test_tailor_resume_empty_diffs():
    mock = MockLLM(result={"sections": {}, "diffs": []})
    result = tailor_resume(mock, "Resume", "Gap")
    assert len(result.diffs) == 0
    assert result.sections == {}


def test_tailor_resume_provenance_tracked():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume", "Gap")
    assert all(d.provenance != "" for d in result.diffs)


def test_tailor_resume_normalizes_enum_values():
    mock = MockLLM(result={
        "sections": {},
        "diffs": [{
            "type": "rephrase",
            "original": "old",
            "proposed": "new",
            "reason": "JD match",
            "confidence": 0.7,
            "provenance": "old",
        }],
    })
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].type == "modify"
    assert result.diffs[0].confidence == "medium"


def test_tailor_diff_section_filled_from_llm():
    mock = MockLLM(result={
        "sections": {"项目经历": "Built FastAPI services with Redis caching"},
        "diffs": [{
            "type": "modify",
            "section": "项目经历",
            "original": "Worked on backend",
            "proposed": "Built FastAPI services with Redis caching",
            "reason": "JD emphasizes performance",
            "confidence": "high",
            "provenance": "Worked on backend",
        }],
    })
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].section == "项目经历"


def test_tailor_diff_section_defaults_empty_when_absent():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].section == ""


def test_tailor_prompt_instructs_section_per_diff():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "section" in mock.last_system
    assert "项目经历" in mock.last_system


def test_tailor_prompt_caps_diff_output():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "at most 15 diffs" in mock.last_system
    assert "80 characters" in mock.last_system


def test_tailor_granularity_fine_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", granularity="fine")
    assert "fine" in mock.last_system.lower()
    assert "preserve" in mock.last_system.lower()


def test_tailor_granularity_coarse_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", granularity="coarse")
    assert "coarse" in mock.last_system.lower()
    assert "restructure" in mock.last_system.lower()


def test_tailor_granularity_default_is_medium():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "medium" in mock.last_system.lower()


def test_tailor_rejects_invalid_granularity():
    mock = MockLLM()
    with pytest.raises(ValueError, match="granularity"):
        tailor_resume(mock, "Resume", "Gap", granularity="ultra")


def test_tailor_prompt_focus_default_is_balanced():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "balanced" in mock.last_system.lower()


def test_tailor_prompt_focus_quantified_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", prompt_focus="quantified")
    assert "quantified" in mock.last_system.lower()
    assert "never invent or inflate" in mock.last_system.lower()


def test_tailor_prompt_focus_skills_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", prompt_focus="skills")
    assert "exact jd skill and scenario phrases" in mock.last_system.lower()


def test_tailor_custom_prompt_appended():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", custom_prompt="强调高并发缓存场景")
    assert "USER REQUIREMENTS" in mock.last_system
    assert "强调高并发缓存场景" in mock.last_system
    assert "never instruct you to invent, infer, or fabricate" in mock.last_system


def test_tailor_rejects_invalid_prompt_focus():
    mock = MockLLM()
    with pytest.raises(ValueError, match="prompt_focus"):
        tailor_resume(mock, "Resume", "Gap", prompt_focus="wild")
