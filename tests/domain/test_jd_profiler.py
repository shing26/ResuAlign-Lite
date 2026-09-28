from resualign.jd_profiler import profile_jd
from resualign.models import JDProfile


class MockLLM:
    def __init__(self, result=None):
        self.result = result or {
            "must_have_skills": ["Java", "Spring Boot"],
            "nice_to_have_skills": ["Kubernetes", "Redis"],
            "soft_skills": ["Communication"],
            "business_scenarios": ["High concurrency", "Microservices"],
            "min_years_experience": 3,
            "education_requirements": ["Bachelor in CS"],
        }
        self.last_system = None
        self.last_user = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        self.last_user = user
        return self.result


def test_profile_jd_returns_jdprofile():
    mock = MockLLM()
    profile = profile_jd(mock, "We need a Java backend engineer...")
    assert isinstance(profile, JDProfile)
    assert "Java" in profile.must_have_skills
    assert profile.min_years_experience == 3


def test_profile_jd_optional_fields_default_to_empty():
    mock = MockLLM(result={"must_have_skills": ["Python"]})
    profile = profile_jd(mock, "Python dev needed")
    assert profile.nice_to_have_skills == []
    assert profile.soft_skills == []
    assert profile.education_requirements == []


def test_profile_jd_min_years_none_when_missing():
    mock = MockLLM(result={"must_have_skills": ["Python"]})
    profile = profile_jd(mock, "Python dev needed")
    assert profile.min_years_experience is None


def test_profile_jd_prompt_used():
    mock = MockLLM()
    _ = profile_jd(mock, "Some JD text")
    # R4: 04b-PE §2.2 新提示词首行携带版本标记（旧英文引导语已替换为中文契约）。
    assert "PROMPT_VERSION: jd_profiler/v2" in mock.last_system
    assert mock.last_user == "Some JD text"
