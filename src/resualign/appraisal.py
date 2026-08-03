"""Deterministic worth appraisal for library jobs."""

from __future__ import annotations

import re
from typing import Any, Optional

DEFAULT_WEIGHTS = {
    "match": 40,
    "salary": 30,
    "hard_conditions": 20,
    "quality": 10,
}

VERDICT_APPLY = "投递"
VERDICT_CONSIDER = "考虑"
VERDICT_SKIP = "放弃"

_CITY_NAMES = (
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "苏州",
    "西安", "重庆", "天津", "长沙", "郑州", "青岛", "大连", "宁波", "厦门",
    "合肥", "福州", "济南", "沈阳", "昆明", "哈尔滨", "长春", "石家庄",
    "太原", "南昌", "贵阳", "南宁", "兰州", "海口", "三亚", "无锡", "东莞",
    "佛山", "珠海", "惠州", "中山", "温州", "嘉兴", "绍兴", "金华", "台州",
    "泉州", "烟台", "潍坊", "常州", "南通", "徐州", "扬州",
)

_CITY_ALIASES = {
    "北京": {"beijing"},
    "上海": {"shanghai"},
    "广州": {"guangzhou"},
    "深圳": {"shenzhen"},
    "杭州": {"hangzhou"},
    "成都": {"chengdu"},
    "武汉": {"wuhan"},
    "南京": {"nanjing"},
    "苏州": {"suzhou"},
    "西安": {"xian"},
    "重庆": {"chongqing"},
    "天津": {"tianjin"},
    "长沙": {"changsha"},
    "郑州": {"zhengzhou"},
    "青岛": {"qingdao"},
    "大连": {"dalian"},
    "宁波": {"ningbo"},
    "厦门": {"xiamen"},
    "合肥": {"hefei"},
    "福州": {"fuzhou"},
    "济南": {"jinan"},
    "沈阳": {"shenyang"},
    "昆明": {"kunming"},
    "哈尔滨": {"haerbin", "harbin"},
    "长春": {"changchun"},
    "石家庄": {"shijiazhuang"},
    "太原": {"taiyuan"},
    "南昌": {"nanchang"},
    "贵阳": {"guiyang"},
    "南宁": {"nanning"},
    "兰州": {"lanzhou"},
    "海口": {"haikou"},
    "三亚": {"sanya"},
    "无锡": {"wuxi"},
    "东莞": {"dongguan"},
    "佛山": {"foshan"},
    "珠海": {"zhuhai"},
    "惠州": {"huizhou"},
    "中山": {"zhongshan"},
    "温州": {"wenzhou"},
    "嘉兴": {"jiaxing"},
    "绍兴": {"shaoxing"},
    "金华": {"jinhua"},
    "台州": {"taizhou"},
    "泉州": {"quanzhou"},
    "烟台": {"yantai"},
    "潍坊": {"weifang"},
    "常州": {"changzhou"},
    "南通": {"nantong"},
    "徐州": {"xuzhou"},
    "扬州": {"yangzhou"},
}

_COMMON_DISTRICTS = {
    "朝阳", "海淀", "东城", "西城", "丰台", "石景山", "通州", "昌平",
    "大兴", "顺义", "房山", "浦东", "徐汇", "静安", "黄浦", "长宁",
    "普陀", "虹口", "杨浦", "闵行", "宝山", "嘉定", "松江", "南山",
    "福田", "罗湖", "宝安", "龙岗", "龙华", "光明", "天河", "越秀",
    "海珠", "荔湾", "白云", "番禺", "西湖", "滨江", "余杭", "萧山",
    "武侯", "锦江", "渝北", "武昌", "洪山", "秦淮", "鼓楼", "姑苏",
    "雁塔",
}

_YEARS_RE = re.compile(
    r"(?:^|[^\d])(\d+(?:\.\d+)?)\s*(?:年|years?|yrs?)", re.IGNORECASE
)


def normalize_city(city: str) -> str:
    """Normalize a city label to a stable canonical form.

    Covers municipality suffixes, common district/county suffixes, and
    built-in aliases. Unknown values are cleaned and returned as-is.
    """
    if not city:
        return ""
    value = re.sub(r"\s+", "", str(city)).strip()
    if not value:
        return ""
    lowered = value.lower()
    for canonical, aliases in _CITY_ALIASES.items():
        if lowered in aliases:
            return canonical
    if value in _CITY_NAMES:
        return value
    for city_name in _CITY_NAMES:
        if not value.startswith(city_name):
            continue
        rest = value[len(city_name):]
        if (
            rest == "市"
            or rest.endswith(("区", "县"))
            or rest in _COMMON_DISTRICTS
        ):
            return city_name
    cleaned = re.sub(r"(市|区|县)$", "", value)
    return cleaned or value


def resolve_salary_benchmark(
    settings: Optional[dict[str, Any]],
    job: dict[str, Any],
    library_median: Optional[float],
) -> tuple[Optional[float], str]:
    """Resolve the salary benchmark and its source via the fallback chain.

    Priority is the settings salary reference matched on job function and
    normalized city, then the library median for the same function, then a
    neutral missing benchmark.
    """
    settings = settings or {}
    job_function = str(job.get("job_function") or "").strip().casefold()
    job_city = normalize_city(job.get("location"))
    for row in settings.get("salary_reference") or []:
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get("p50"), (int, float)):
            continue
        row_function = str(row.get("job_function") or "").strip().casefold()
        row_city = normalize_city(row.get("city"))
        if (
            job_city
            and row_city == job_city
            and row_function == job_function
        ):
            return (float(row["p50"]), "设置表（城市）")
    if library_median is not None:
        return (float(library_median), "库内同类中位")
    return (None, "暂无基准")


def resume_profile(text: str) -> dict[str, Any]:
    """Best-effort deterministic years/education extraction from free text."""
    if not text:
        return {"years": None, "education": None}
    years = None
    match = _YEARS_RE.search(text)
    if match and float(match.group(1)) <= 50:
        years = float(match.group(1))
    education = None
    if "博士" in text:
        education = "博士"
    elif "硕士" in text:
        education = "硕士"
    elif "本科" in text:
        education = "本科"
    return {"years": years, "education": education}


def _job_salary_mid(job: dict[str, Any]) -> Optional[float]:
    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")
    if salary_min is not None and salary_max is not None:
        return (float(salary_min) + float(salary_max)) / 2
    if salary_min is not None:
        return float(salary_min)
    if salary_max is not None:
        return float(salary_max)
    return None


def _salary_score(job: dict[str, Any], benchmark: Optional[float]) -> float:
    job_salary = _job_salary_mid(job)
    if job_salary is None or benchmark is None:
        return 50.0
    if job_salary >= benchmark:
        return 100.0
    return round(100.0 * job_salary / benchmark, 2)


def _hard_conditions_score(
    job: dict[str, Any],
    resume_years: Optional[float],
    resume_education: Optional[str],
) -> float:
    score = 100.0
    required_years = None
    if "资深" in str(job.get("seniority") or ""):
        required_years = 6
    elif "高级" in str(job.get("seniority") or ""):
        required_years = 4
    elif "中级" in str(job.get("seniority") or ""):
        required_years = 2
    if required_years is not None and resume_years is not None:
        shortfall = max(0, required_years - resume_years)
        score -= min(50.0, shortfall * 10.0)
    if (
        "硕士" in str(job.get("education_requirement") or "")
        and resume_education not in ("硕士", "博士")
    ):
        score -= 20.0
    if "博士" in str(job.get("education_requirement") or "") and not (
        resume_education and "博士" in resume_education
    ):
        score -= 20.0
    return max(0.0, round(score, 2))


def _quality_score(job: dict[str, Any]) -> float:
    score = 40.0
    if job.get("company"):
        score += 15.0
    if job.get("location"):
        score += 10.0
    if job.get("salary_min") or job.get("salary_max"):
        score += 20.0
    tags = job.get("tech_tags") or []
    if len(tags) >= 2:
        score += 15.0
    return min(100.0, round(score, 2))


def compute_appraisal(
    job: dict[str, Any],
    resume_match_score: Optional[float] = None,
    salary_benchmark: Optional[float] = None,
    weights: Optional[dict[str, float]] = None,
    resume_years: Optional[float] = None,
    resume_education: Optional[str] = None,
    settings: Optional[dict[str, Any]] = None,
    library_median: Optional[float] = None,
) -> dict[str, Any]:
    """Score a job 0-100 and return a verdict with transparent reasons.

    When *settings* is provided, the salary benchmark follows the fallback
    chain: settings reference (function x city), library same-function
    median, then a neutral missing benchmark.
    """
    resolved_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        missing = set(DEFAULT_WEIGHTS) - set(weights)
        if missing:
            raise ValueError(f"Missing weights: {sorted(missing)}")
        resolved_weights.update(weights)
        if sum(resolved_weights.values()) != 100:
            raise ValueError("Weights must sum to 100")

    if settings is not None:
        salary_benchmark, benchmark_source = resolve_salary_benchmark(
            settings, job, library_median
        )
    else:
        benchmark_source = (
            "库内同类中位" if salary_benchmark is not None else "暂无基准"
        )

    match = (
        float(resume_match_score)
        if resume_match_score is not None
        else 50.0
    )
    salary = _salary_score(job, salary_benchmark)
    hard = _hard_conditions_score(job, resume_years, resume_education)
    quality = _quality_score(job)
    score = round(
        match * resolved_weights["match"]
        + salary * resolved_weights["salary"]
        + hard * resolved_weights["hard_conditions"]
        + quality * resolved_weights["quality"],
        2,
    ) / 100

    if score >= 75:
        verdict = VERDICT_APPLY
    elif score >= 55:
        verdict = VERDICT_CONSIDER
    else:
        verdict = VERDICT_SKIP

    reasons = []
    reasons.append(f"简历匹配度 {match:.0f}/100")
    if job.get("salary_min") or job.get("salary_max"):
        if salary_benchmark is not None:
            if benchmark_source == "设置表（城市）":
                reasons.append(
                    f"薪资中位 {salary:.0f}/100（岗位对照设置表（城市）"
                    f"基准 {salary_benchmark:.0f}）"
                )
            else:
                reasons.append(
                    f"薪资中位 {salary:.0f}/100（岗位对照库内同类中位 "
                    f"{salary_benchmark:.0f}）"
                )
        else:
            reasons.append(f"薪资分 {salary:.0f}/100（暂无基准）")
    else:
        if benchmark_source == "暂无基准":
            reasons.append("岗位未提供薪资，按中性处理（暂无基准）")
        else:
            reasons.append("岗位未提供薪资，按中性处理")
    reasons.append(f"硬性条件 {hard:.0f}/100，岗位质量 {quality:.0f}/100")

    city_normalized = normalize_city(job.get("location")) or None
    return {
        "score": score,
        "verdict": verdict,
        "components": {
            "match": round(match, 2),
            "salary": salary,
            "hard_conditions": hard,
            "quality": quality,
        },
        "reasons": reasons,
        "weights": resolved_weights,
        "salary_benchmark": salary_benchmark,
        "benchmark_source": benchmark_source,
        "city_normalized": city_normalized,
    }
