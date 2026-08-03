from resualign.models import DiffItem, Analysis, Report, ResuAlignConfig


def test_diffitem_defaults():
    d = DiffItem()
    assert d.type == "modify"
    assert d.original == ""
    assert d.proposed == ""
    assert d.reason == ""
    assert d.confidence == "medium"
    assert d.provenance == ""


def test_diffitem_full():
    d = DiffItem(
        type="add", original="", proposed="New line",
        reason="JD match", confidence="high",
    )
    assert d.type == "add"
    assert d.proposed == "New line"


def test_analysis_defaults():
    a = Analysis()
    assert a.score == 0
    assert a.issues == []
    assert a.skills == []


def test_analysis_with_data():
    a = Analysis(score=85, issues=["Too long"], skills=["Python", "Java"])
    assert a.score == 85
    assert "Python" in a.skills


def test_report_defaults():
    r = Report()
    assert r.score == 0
    assert r.diffs == []
    assert r.model == ""


def test_report_with_diff():
    d = DiffItem(
        type="modify", original="old", proposed="new", reason="better"
    )
    r = Report(
        score=80, diffs=[d], model="deepseek-v4", elapsed_seconds=5.2
    )
    assert r.score == 80
    assert len(r.diffs) == 1
    assert r.diffs[0].original == "old"
    assert r.model == "deepseek-v4"


def test_resualign_config_defaults():
    c = ResuAlignConfig()
    assert c.provider == "deepseek"
    assert c.api_key == ""
    assert c.model == "deepseek-chat"
    assert c.base_url == ""
