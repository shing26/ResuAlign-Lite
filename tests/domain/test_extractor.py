"""Tests for the extractor module — section extraction and boilerplate filtering."""

from resualign.extractor import extract_sections, extract_structured

SAMPLE_JD = """
Senior Backend Engineer

About Us
We are a fast-growing fintech company building the next generation of payment infrastructure.

Qualifications
- 5+ years of experience in backend development
- Strong proficiency in Python and Go
- Experience with distributed systems (Kafka, Redis)
- Bachelor's degree in Computer Science or related field

Responsibilities
- Design and implement scalable microservices
- Mentor junior engineers and conduct code reviews
- Collaborate with cross-functional teams on architecture decisions

Benefits
- Competitive salary and equity package
- Remote-first work culture
- Health, dental, and vision insurance
- Annual learning budget of $5,000

Equal opportunity employer. We are proud to be an inclusive workplace.
All qualified applicants will receive consideration.
"""


def test_extract_sections_qualifications():
    sections = extract_sections(SAMPLE_JD)
    quals = sections.get("qualifications", "")
    assert "Python" in quals
    assert "Go" in quals
    assert "distributed systems" in quals
    assert "5+ years" in quals


def test_extract_sections_responsibilities():
    sections = extract_sections(SAMPLE_JD)
    resp = sections.get("responsibilities", "")
    assert "microservices" in resp
    assert "code reviews" in resp
    assert "Mentor" in resp or "mentor" in resp


def test_extract_sections_benefits():
    sections = extract_sections(SAMPLE_JD)
    benefits = sections.get("benefits", "")
    assert "equity" in benefits
    assert "insurance" in benefits
    assert "learning budget" in benefits


def test_extract_sections_about():
    sections = extract_sections(SAMPLE_JD)
    about = sections.get("about", "")
    assert "fintech" in about
    assert "payment infrastructure" in about


def test_boilerplate_filtered():
    """Boilerplate lines like 'Equal opportunity employer' are removed entirely."""
    sections = extract_sections(SAMPLE_JD)
    all_text = "\n".join(sections.values())
    assert "Equal opportunity" not in all_text
    assert "we are proud" not in all_text.lower()
    assert "all qualified" not in all_text.lower()


def test_empty_input_returns_empty():
    assert extract_sections("") == {}
    assert extract_sections("   ") == {}


def test_only_boilerplate_returns_empty():
    text = "Equal opportunity employer. We are proud to be an inclusive workplace."
    assert extract_sections(text) == {}


def test_unmatched_content_goes_to_other():
    """Text without a recognized header should land in the 'other' bucket."""
    sections = extract_sections("Some random text with no section headers.")
    assert "other" in sections
    assert "random text" in sections["other"]


def test_extract_structured_keys():
    result = extract_structured(SAMPLE_JD)
    assert isinstance(result, dict)
    assert "qualifications" in result
    assert "responsibilities" in result
    assert "benefits" in result
    assert "about" in result


def test_extract_structured_populates_sections():
    result = extract_structured(SAMPLE_JD)
    assert "Python" in result["qualifications"]
    assert "microservices" in result["responsibilities"]
    assert "equity" in result["benefits"]
    assert "fintech" in result["about"]


def test_extract_structured_empty_input():
    result = extract_structured("")
    assert all(v == "" for v in result.values())


def test_extract_structured_missing_section_defaults_to_empty():
    """If a section is absent from the JD, its key maps to an empty string."""
    text = "About Us\nOur team builds cloud infrastructure."
    result = extract_structured(text)
    assert result["qualifications"] == ""
    assert result["responsibilities"] == ""
    assert result["benefits"] == ""
    assert "cloud infrastructure" in result["about"]
