from resualign.jd_analysis import jd_context_summary, profile_and_gaps
from resualign.models import GapReport, JDProfile
from tests.conftest import _gap, _profile


class FakeClient:
    def __init__(self):
        self.calls = []

    def chat_json(self, system, user, model=None):
        self.calls.append((system, user))
        return {"jd_profile": _profile(), "gap_report": _gap()}


def test_profile_and_gaps_parses_both_models():
    client = FakeClient()
    profile, gap = profile_and_gaps(client, "Resume text", "JD text")
    assert isinstance(profile, JDProfile)
    assert profile.must_have_skills == ["Java"]
    assert isinstance(gap, GapReport)
    assert gap.missing_keywords == ["Redis"]


def test_combined_prompt_mentions_both_outputs():
    client = FakeClient()
    profile_and_gaps(client, "Resume text", "JD text")
    system, user = client.calls[0]
    assert "jd_profile" in system
    assert "gap_report" in system
    assert "Resume:" in user
    assert "Job Description:" in user


def test_profile_and_gaps_keeps_only_resume_backed_supported_keywords():
    class EvidenceClient:
        def chat_json(self, system, user, model=None):
            return {
                "jd_profile": _profile(),
                "gap_report": {
                    "supported_keywords": ["Redis caching", "Kubernetes"],
                    "supported_keyword_evidence": {
                        "Redis caching": "使用 Redis 做缓存",
                        "Kubernetes": "使用 Kubernetes 部署服务",
                    },
                    "missing_keywords": [],
                    "misaligned_emphasis": [],
                    "strength_matches": ["Java"],
                },
            }

    _, gap = profile_and_gaps(
        EvidenceClient(),
        "使用 Redis 做缓存",
        "JD asks for Redis and Kubernetes",
    )

    assert gap.supported_keywords == ["Redis caching"]
    assert gap.supported_keyword_evidence == {
        "Redis caching": "使用 Redis 做缓存"
    }


def test_jd_context_summary_is_structured_bounded_and_ignores_raw_context():
    profile = JDProfile(
        must_have_skills=["Java", "Spring Boot"],
        nice_to_have_skills=["Redis"],
        business_scenarios=["trade settlement"],
        min_years_experience=3,
    )
    gap = GapReport(
        supported_keywords=["Redis caching"],
        missing_keywords=["Kubernetes"],
    )
    summary = jd_context_summary(profile, gap)
    assert "Java" in summary
    assert "Redis caching" in summary
    assert "Kubernetes" not in summary
    assert "jd_context" not in summary
    assert len(summary) <= 300
    assert "\n" not in summary

    assert jd_context_summary({"jd_context": "raw JD sentinel"}) == ""
