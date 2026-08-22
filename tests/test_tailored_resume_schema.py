"""Tests for the TailoredResume schema normalisation (Round5 Bug-01).

The LLM may nest section values as objects/arrays in its JSON response; the
strict ``dict[str, str]`` declaration used to reject those with a confusing
pydantic ``Input should be a valid string`` error and the caller then failed
with "模型返回了空内容或无法解析的 JSON". The before-validator flattens
nested values into Markdown text so alignment runs succeed.
"""

from resualign.schema_registry import TailoredResumeSchema


def _payload(sections):
    return {"sections": sections, "diffs": [], "invalid_diffs": []}


def test_nested_object_sections_are_flattened():
    result = TailoredResumeSchema.model_validate(
        _payload(
            {
                "工作经历": {
                    "公司": "某科技",
                    "职位": "后端工程师",
                },
            }
        )
    ).model_dump()
    assert result["sections"]["工作经历"] == "公司: 某科技\n职位: 后端工程师"


def test_nested_list_sections_are_flattened():
    result = TailoredResumeSchema.model_validate(
        _payload(
            {
                "项目经历": [
                    {"名称": "订单系统", "成果": "QPS+30%"},
                    {"名称": "数据平台", "成果": "成本-20%"},
                ],
            }
        )
    ).model_dump()
    text = result["sections"]["项目经历"]
    assert "名称: 订单系统" in text
    assert "成果: QPS+30%" in text


def test_plain_string_sections_are_preserved():
    result = TailoredResumeSchema.model_validate(
        _payload({"工作经历": "公司：X\n职位：Y"})
    ).model_dump()
    assert result["sections"]["工作经历"] == "公司：X\n职位：Y"


def test_non_string_scalar_section_values_are_coerced():
    result = TailoredResumeSchema.model_validate(
        _payload({"工作经历": 123, "项目经历": None})
    ).model_dump()
    assert result["sections"]["工作经历"] == "123"
    assert result["sections"]["项目经历"] == ""


def test_malformed_sections_default_to_empty():
    # Absent sections fall back to an empty dict (default_factory).
    result = TailoredResumeSchema.model_validate(
        {"diffs": [], "invalid_diffs": []}
    ).model_dump()
    assert result["sections"] == {}