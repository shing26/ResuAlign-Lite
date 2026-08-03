import re

QUAL_RE = re.compile(r"(?:qualifications|requirements)", re.I)
RESP_RE = re.compile(r"(?:responsibilities|key duties)", re.I)
BEN_RE = re.compile(r"(?:benefits|what we offer)", re.I)
ABOUT_RE = re.compile(r"(?:about|company)", re.I)
BOILER_RE = re.compile(r"^(?:equal opportunity|we are proud|all qualified)", re.I)

HEADERS = {"qualifications": QUAL_RE, "responsibilities": RESP_RE, "benefits": BEN_RE, "about": ABOUT_RE}

def extract_sections(text):
    sections = {}
    current = "other"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        matched = False
        for key, pat in HEADERS.items():
            if pat.search(line) and len(line) < 80:
                current = key
                matched = True
                break
        if matched:
            continue
        if BOILER_RE.search(line):
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items() if v}

def extract_structured(text):
    """Two-stage extraction: regex pass → structured dict with section keys.

    Returns a dict with four keys (qualifications, responsibilities, benefits, about)
    each containing the joined section text or an empty string if absent.
    Boilerplate lines are filtered out. This is the lightweight stage-1 pass
    before optional LLM refinement (see CONTEXT.md Token Optimization Principle).
    """
    s = extract_sections(text)
    return {
        "qualifications": s.get("qualifications", ""),
        "responsibilities": s.get("responsibilities", ""),
        "benefits": s.get("benefits", ""),
        "about": s.get("about", ""),
    }
