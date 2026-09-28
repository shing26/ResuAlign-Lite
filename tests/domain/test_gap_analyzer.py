from resualign.gap_analyzer import analyze_gaps
from resualign.models import GapReport


class MockLLM:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "missing_keywords": ["Kubernetes", "Redis"],
            "misaligned_emphasis": ["Focus on frontend instead of backend"],
            "strength_matches": ["Java experience aligns well"],
        }
        self.last_system = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        return self.result


def test_analyze_gaps_returns_gapreport():
    mock = MockLLM()
    report = analyze_gaps(mock, "Resume text...", "JD profile...")
    assert isinstance(report, GapReport)
    assert "Kubernetes" in report.missing_keywords


def test_analyze_gaps_empty_results():
    mock = MockLLM(result={})
    report = analyze_gaps(mock, "Resume", "JD")
    assert report.missing_keywords == []


def test_analyze_gaps_prompt_mentions_gap():
    mock = MockLLM()
    _ = analyze_gaps(mock, "Resume", "JD")
    # R4: 04b-PE §2.3 新提示词已中文化，首行版本标记作为稳定断言锚点。
    assert "PROMPT_VERSION: gap_analyzer/v2" in mock.last_system


def test_analyze_gaps_cache_hit_skips_llm(tmp_path):
    """P3（2026-09-07）：同简历同画像重跑命中内容缓存，不再付一次 LLM 往返。
    缓存键覆盖两个输入：换画像（换岗位）必须 miss。"""
    from resualign.cache import ContentCache

    class CountingLLM(MockLLM):
        def __init__(self, result):
            super().__init__(result)
            self.call_count = 0

        def chat_json(self, system, user, model=None):
            self.call_count += 1
            return super().chat_json(system, user, model)

    client = CountingLLM({
        "missing_keywords": ["Kubernetes"],
        "misaligned_emphasis": [],
        "strength_matches": ["Java"],
    })
    with ContentCache(tmp_path / "gap.sqlite3") as cache:
        first = analyze_gaps(client, "Resume text", "Profile A",
                             cache=cache, tenant="t")
        second = analyze_gaps(client, "Resume text", "Profile A",
                              cache=cache, tenant="t")
        other = analyze_gaps(client, "Resume text", "Profile B",
                             cache=cache, tenant="t")
    assert first == second
    assert other.missing_keywords == ["Kubernetes"]
    assert client.call_count == 2  # hit + miss; the second same-input call was cached
