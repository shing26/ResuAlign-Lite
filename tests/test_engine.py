import pytest

from resualign.engine import run, truncate_text
from resualign.models import ResuAlignConfig

from .conftest import (
    MockLLMClient,
    _diag,
    _eval,
    _gap_only,
    _jd_profile_only,
    _tailor,
)


def test_engine_diagnosis_only():
    mock = MockLLMClient([_diag()])
    report = run(ResuAlignConfig(model="m"), "Python dev resume", llm_client=mock)
    assert report.score == 80
    assert mock.call_count == 1


def test_engine_full_pipeline():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
    report = run(ResuAlignConfig(model="m"), "Python dev resume",
                 jd_text="Java backend", llm_client=mock)
    assert report.jd_profile is not None
    assert report.gap_report is not None
    assert report.tailored_resume is not None
    assert len(report.diffs) == 1
    assert mock.call_count == 4


def test_engine_jd_and_tailoring_use_extended_timeouts(monkeypatch):
    seen_timeouts = []
    seen_retries = []
    shared = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor()])

    class Factory:
        def __init__(self, config, timeout=None, max_retries=None):
            seen_timeouts.append(timeout)
            seen_retries.append(max_retries)

        def __enter__(self):
            return shared

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            pass

        def chat_json(self, system, user, model=None):
            return shared.chat_json(system, user, model=model)

        def chat_structured(self, system, user, schema_model, model=None):
            return shared.chat_structured(
                system, user, schema_model, model=model
            )

    monkeypatch.setattr("resualign.engine.OpenAIClient", Factory)
    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
    )
    assert seen_timeouts == [45.0, 30.0, 90.0]
    assert seen_retries == [None, None, 1]


def test_engine_no_jd_no_extra_stages():
    mock = MockLLMClient([_diag()])
    report = run(ResuAlignConfig(model="m"), "Python dev", llm_client=mock)
    assert report.jd_profile is None
    assert report.gap_report is None
    assert report.tailored_resume is None
    assert mock.call_count == 1


def test_engine_with_eval():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor(), _eval()])
    report = run(ResuAlignConfig(model="m"), "Python dev resume",
                 jd_text="Java backend", llm_client=mock, run_eval=True)
    assert report.eval_score is not None
    assert report.eval_score.jd_match_score == 82
    assert mock.call_count == 5


def test_engine_eval_defaults_to_false():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
    report = run(ResuAlignConfig(model="m"), "Python dev resume",
                 jd_text="Java backend", llm_client=mock)
    assert report.eval_score is None
    assert mock.call_count == 4


def test_engine_passes_business_scenarios_to_tailor():
    class CaptureClient(MockLLMClient):
        def __init__(self):
            super().__init__([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
            self.tailor_user = ""

        def chat_json(self, system, user, model=None):
            if "precise resume editor" in system.lower():
                self.tailor_user = user
            return super().chat_json(system, user, model)

    mock = CaptureClient()
    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
    )
    assert "Java" in mock.tailor_user
    assert "Java backend" in mock.tailor_user


def test_engine_passes_custom_prompt_to_tailor():
    class CaptureClient(MockLLMClient):
        def __init__(self):
            super().__init__([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
            self.tailor_system = ""

        def chat_json(self, system, user, model=None):
            if "precise resume editor" in system.lower():
                self.tailor_system = system
            return super().chat_json(system, user, model)

    mock = CaptureClient()
    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        custom_prompt="强调高并发缓存场景",
    )
    assert "USER REQUIREMENTS" in mock.tailor_system
    assert "强调高并发缓存场景" in mock.tailor_system


def test_engine_stage_progress_full_pipeline():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
    stages = []

    def on_stage(stage, message):
        assert message.strip()
        stages.append(stage)

    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        on_stage=on_stage,
    )

    assert stages == [
        "diagnose",
        "jd_analysis",
        "jd_profiled",
        "jd_analysis",
        "gap_analyzed",
        "tailoring",
    ]


def test_engine_stage_progress_diagnosis_only():
    mock = MockLLMClient([_diag()])
    stages = []

    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        llm_client=mock,
        on_stage=lambda stage, message: stages.append(stage),
    )

    assert stages == ["diagnose"]


def test_engine_stage_progress_with_eval():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor(), _eval()])
    stages = []

    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        run_eval=True,
        on_stage=lambda stage, message: stages.append(stage),
    )

    assert stages == [
        "diagnose",
        "jd_analysis",
        "jd_profiled",
        "jd_analysis",
        "gap_analyzed",
        "tailoring",
        "evaluation",
    ]


def test_engine_passes_granularity_to_tailor():
    class CaptureClient(MockLLMClient):
        def __init__(self):
            super().__init__([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
            self.tailor_system = ""

        def chat_json(self, system, user, model=None):
            if "precise resume editor" in system.lower():
                self.tailor_system = system
            return super().chat_json(system, user, model)

    mock = CaptureClient()
    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        granularity="coarse",
    )
    assert "coarse" in mock.tailor_system.lower()
    assert "restructure" in mock.tailor_system.lower()


def test_engine_rejects_invalid_granularity():
    mock = MockLLMClient([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
    with pytest.raises(ValueError, match="granularity"):
        run(
            ResuAlignConfig(model="m"),
            "Python dev resume",
            jd_text="Java backend",
            llm_client=mock,
            granularity="ultra",
        )


def test_engine_passes_prompt_focus_to_tailor():
    class CaptureClient(MockLLMClient):
        def __init__(self):
            super().__init__([_diag(), _jd_profile_only(), _gap_only(), _tailor()])
            self.tailor_system = ""

        def chat_json(self, system, user, model=None):
            if "precise resume editor" in system.lower():
                self.tailor_system = system
            return super().chat_json(system, user, model)

    mock = CaptureClient()
    run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        prompt_focus="quantified",
    )
    assert "quantified" in mock.tailor_system.lower()
    assert "never invent or inflate" in mock.tailor_system.lower()


def test_engine_reuses_provided_diagnosis():
    mock = MockLLMClient([_jd_profile_only(), _gap_only(), _tailor()])
    report = run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        jd_text="Java backend",
        llm_client=mock,
        diagnosis={"score": 91, "skills": ["Python"], "issues": []},
    )
    assert report.score == 91
    assert report.jd_profile is not None
    assert report.tailored_resume is not None
    assert mock.call_count == 3


def test_truncate_text_keeps_prefix_and_line_boundary():
    text = "line one\n" + "x" * 2000 + "\nline two"
    cut = truncate_text(text, 1000)
    assert len(cut) <= 1000
    assert cut.startswith("line one")
    assert "line two" not in cut


def test_truncate_text_cuts_long_line():
    cut = truncate_text("a" * 5000, 2000)
    assert len(cut) == 2000
def test_engine_local_diagnosis_fallback_on_llm_failure():
    class FailingDiagClient(MockLLMClient):
        def chat_structured(self, system, user, schema_model, model=None):
            if getattr(schema_model, "__name__", "") == "Analysis":
                raise RuntimeError("simulated diagnose failure")
            return super().chat_structured(system, user, schema_model, model=model)

    mock = FailingDiagClient(
        [_jd_profile_only(), _gap_only(), _tailor()]
    )
    resume = (
        "张三\n"
        "13800138000\n"
        "zhangsan@example.com\n"
        "\n"
        "教育背景\n"
        "2015-2019 某某大学 计算机科学与技术 本科\n"
        "\n"
        "技能\n"
        "Python, Redis, Docker, Kubernetes\n"
        "\n"
        "项目经历\n"
        "- 负责订单服务模块开发，使用 Redis 缓存热点数据，QPS 提升 30%，接口耗时降低 40%\n"
        "- 使用 Docker 部署服务，通过 CI/CD 流水线发布\n"
        "- 参与数据库索引优化，慢查询数量下降 50%\n"
    )
    report = run(
        ResuAlignConfig(model="m"),
        resume,
        jd_text="Java backend",
        llm_client=mock,
    )
    assert report.score == 75
    assert report.issues == []
    assert report.jd_profile is not None
    assert report.gap_report is not None
    assert report.tailored_resume is not None
    assert mock.call_count == 3
