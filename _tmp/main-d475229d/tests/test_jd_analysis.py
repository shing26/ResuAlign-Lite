from resualign.jd_analysis import profile_and_gaps
from resualign.models import GapReport, JDProfile

from .conftest import _gap, _profile


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
