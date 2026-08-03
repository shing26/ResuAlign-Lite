from pathlib import Path
import pytest
from resualign.parser import extract_text, FileParseError

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


def test_txt_parse():
    text = extract_text(FIXTURES / "sample.txt")
    assert "Python" in text
    assert "Java" in text
    assert len(text) > 50


def test_txt_invalid_utf8_raises(tmp_path):
    path = tmp_path / "gbk.txt"
    path.write_bytes("简历：Python 开发".encode("gbk"))
    with pytest.raises(FileParseError, match="UTF-8"):
        extract_text(path)


def test_pdf_parse():
    path = FIXTURES / "sample.pdf"
    if not path.exists():
        pytest.skip("sample.pdf fixture not available")
    text = extract_text(path)
    assert len(text) > 0


def test_docx_parse():
    path = FIXTURES / "sample.docx"
    if not path.exists():
        pytest.skip("sample.docx fixture not available")
    text = extract_text(path)
    assert len(text) > 0


def test_unsupported_extension():
    with pytest.raises(FileParseError, match=r"\.xyz"):
        extract_text(FIXTURES / "dummy.xyz")


def test_file_not_found():
    with pytest.raises(FileParseError, match="not found"):
        extract_text(FIXTURES / "nonexistent.pdf")
