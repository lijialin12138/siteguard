"""AI 诊断层 —— 这是整个项目的灵魂。

输入：scanner.py 产出的结构化体检报告
输出：根因分析 + 严重等级 + 可执行的修复建议 + 修复补丁

模型走华为云 MaaS（ModelArts Studio），接口与 OpenAI 完全兼容，
所以直接复用 openai 这个库，只需要把 base_url 指过去。
"""

import json
import re
from typing import Any

from openai import AsyncOpenAI

from .config import MAAS_API_KEY, MAAS_BASE_URL, MAAS_MODEL, maas_ready

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """延迟创建客户端，避免没配 Key 时一 import 就崩。"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=MAAS_API_KEY, base_url=MAAS_BASE_URL, timeout=60)
    return _client


SYSTEM_PROMPT = """你是一名资深的企业级网站运维工程师（SRE），擅长从监控数据中快速定位故障根因。

你会收到一份由自动化巡检程序生成的「网站体检报告」JSON，里面可能包含：
站点地址、HTTP 状态码、响应耗时、SSL 证书剩余天数、
页面基础信息（标题/描述/H1 数量/图片 alt 缺失数）、死链列表，
以及程序依据规则初步标记的问题清单 issues。

你的任务：像一名真正的运维工程师那样分析这份报告，给出诊断结论。

严格遵守以下输出要求：
1. 只输出一个 JSON 对象。不要输出任何解释性文字，不要用 markdown 代码块包裹。
2. JSON 结构必须严格如下：
{
  "summary": "一句话总结该站点当前的健康状况，40 字以内",
  "severity": "P0 或 P1 或 P2 或 P3，P0 最严重",
  "root_causes": [
    {"issue": "表层现象", "reason": "你判断的根本原因"}
  ],
  "actions": [
    {"priority": 1, "action": "要做什么", "how": "具体怎么操作，必须可执行"}
  ],
  "patch": "如果有配置或代码层面的修复片段就写在这里（例如 Nginx 配置、HTML 标签修正、证书续期命令），没有则填空字符串"
}
3. root_causes 和 actions 都要按重要性从高到低排序，最多各 3 条。
4. 严禁编造报告中不存在的数据。信息不足以判断时，在 reason 里说明还需要补充哪些信息。
5. 全部用中文回答。
6. actions 里的 how 要具体到可操作，例如"登录域名服务商控制台，为该域名开启自动续期"，
   而不是"建议检查证书"这种空话。"""

REPORT_SYSTEM_PROMPT = """你是一名企业运维团队的技术负责人，负责向管理层汇报网站运行状况。
你会收到一份巡检报告和它的 AI 诊断结论，请把它们整理成一份简洁、专业、可直接发给团队的每日运维简报。

要求：
1. 输出 Markdown 格式。
2. 结构固定为：一句话结论 → 关键指标 → 发现的问题（按严重程度排序）→ 建议的处置动作。
3. 语言克制、专业，不要堆砌形容词，不要写"尊敬的领导"这类客套话。
4. 没有问题的项就不要写，不要为了凑字数而罗列正常指标。
5. 全部用中文。"""


def _extract_json(text: str) -> dict:
    """模型偶尔会用 ```json 包裹或加前后缀，这里做一次容错提取。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {"summary": "模型返回内容无法解析为 JSON", "raw": text}


def _slim_report(report: dict) -> dict:
    """只把关键字段送给模型，减少 token 消耗，也降低它被无关信息干扰的概率。"""
    broken = report.get("broken_links") or []
    return {
        "url": report.get("final_url") or report.get("url"),
        "status_code": report.get("status_code"),
        "response_ms": report.get("response_ms"),
        "ssl_days_left": report.get("ssl_days_left"),
        "title": report.get("title"),
        "has_meta_description": bool((report.get("description") or "").strip()),
        "h1_count": report.get("h1_count"),
        "images_total": report.get("images_total"),
        "images_without_alt": report.get("images_without_alt"),
        "broken_link_count": len(broken),
        "broken_link_samples": [b.get("url") for b in broken[:5]],
        "issues": report.get("issues") or [],
        "fetch_error": report.get("error"),
        "scanned_at": report.get("scanned_at"),
    }


async def diagnose(report: dict) -> dict:
    """对一份体检报告做 AI 诊断。未配置 MaaS 时抛出 RuntimeError。"""
    if not maas_ready():
        raise RuntimeError("MAAS_NOT_CONFIGURED")

    payload = json.dumps(_slim_report(report), ensure_ascii=False, indent=2)
    resp = await get_client().chat.completions.create(
        model=MAAS_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"以下是本次巡检报告：\n\n{payload}"},
        ],
        temperature=0.2,
    )
    content = resp.choices[0].message.content or ""
    result = _extract_json(content)
    result["_meta"] = {
        "model": MAAS_MODEL,
        "total_tokens": getattr(resp.usage, "total_tokens", None),
    }
    return result


async def write_daily_report(report: dict, diagnosis: dict) -> str:
    """把巡检报告和诊断结论整理成一份可读的每日运维简报。"""
    if not maas_ready():
        raise RuntimeError("MAAS_NOT_CONFIGURED")

    payload: dict[str, Any] = {
        "巡检报告": _slim_report(report),
        "AI 诊断结论": diagnosis,
    }
    resp = await get_client().chat.completions.create(
        model=MAAS_MODEL,
        messages=[
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


async def ping() -> str:
    """连通性自检：验证 MaaS 配置是否正确。"""
    if not maas_ready():
        raise RuntimeError("MAAS_NOT_CONFIGURED")
    resp = await get_client().chat.completions.create(
        model=MAAS_MODEL,
        messages=[{"role": "user", "content": "回复两个字：正常"}],
        temperature=0,
    )
    return resp.choices[0].message.content or ""
