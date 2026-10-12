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

from .config import MAAS_API_KEY, MAAS_BASE_URL, MAAS_MODEL, maas_ready, mock_active

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


# ============================================================
#  内置模拟诊断（MOCK）
# ------------------------------------------------------------
#  没有真实 API Key 也能把「巡检 → 诊断」整条链路跑通。
#  它不是随便编一段话：会读取真实巡检报告里的 issues，
#  按问题类别给出对应的根因判断和可执行处置建议，
#  输出的结构与真实模型完全一致，前端无需区别对待。
#
#  正式提交/录演示视频前，把 .env 里的 MAAS_MODE 设为 off，
#  确保走的是真实大模型。
# ============================================================

MOCK_PROVIDER = "mock-diagnosis"
MOCK_WARNING = "⚠️ 本结论由内置模拟诊断生成，未调用真实大模型（未配置 MaaS API Key）。正式提交前请接入真实模型。"

_LEVEL_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# 类别 -> (根因判断, 处置动作, 具体怎么做, 修复片段)
_MOCK_KNOWLEDGE: dict[str, tuple[str, str, str, str]] = {
    "availability": (
        "站点在超时时间内完全没有响应。常见原因是 Web 服务进程已退出、DNS 解析异常，"
        "或云上安全组 / 防火墙拦掉了 443 端口的入站流量。",
        "恢复站点可用性",
        "登录服务器执行 systemctl status nginx 确认进程状态；在服务器本机执行 curl -I http://127.0.0.1/ "
        "区分『服务挂了』还是『网络不通』；再检查云主机安全组的 80/443 入方向规则是否放行。",
        "# 三段式排查：进程 → 本机访问 → 外部网络\n"
        "systemctl status nginx\n"
        "curl -I http://127.0.0.1/\n"
        "curl -I https://你的域名",
    ),
    "server_error": (
        "服务端返回 5xx，说明请求已经到达后端但处理过程抛出了异常，"
        "通常是应用报错、上游依赖（数据库/缓存）不可用，或 PHP/Java 进程资源耗尽。",
        "定位后端异常并恢复服务",
        "查 Nginx 与应用的错误日志（/var/log/nginx/error.log、应用的 error log），"
        "重点看 5xx 前后 1 分钟内的堆栈；同时确认数据库连接数是否打满、磁盘是否写满。",
        "# 按时间窗口捞异常日志\n"
        "tail -n 200 /var/log/nginx/error.log\n"
        "df -h && free -m",
    ),
    "client_error": (
        "页面返回 4xx，多数是资源路径被改动后没做重定向，或权限配置把正常访客也挡在了外面。",
        "修正失效路径或权限规则",
        "在浏览器开发者工具的 Network 面板确认具体是哪个 URL 返回 4xx；"
        "如果是页面被改名，加一条 301 永久重定向；如果是 403，检查目录权限与 Nginx deny 规则。",
        "# 为已改名的旧路径补 301，保住既有搜索权重\n"
        "location = /old-page.html { return 301 /new-page.html; }",
    ),
    "redirect": (
        "存在 HTTP 跳转，单次跳转本身无害，但如果 HTTP→HTTPS 与 www→裸域各跳一次，"
        "移动端首屏会多出一个 RTT，也会分散搜索权重。",
        "合并跳转链路为一跳",
        "先用 curl -I 观察完整跳转链，再把 Nginx 里的 HTTP 与 www 规则合并，"
        "直接 301 到最终主域名，避免二次跳转。",
        "# 一次性跳到最终地址，不要中间再跳一次\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name 你的域名 www.你的域名;\n"
        "    return 301 https://你的域名$request_uri;\n"
        "}",
    ),
    "performance": (
        "首页响应耗时偏高。后端首字节时间长（TTFB 高）通常是数据库慢查询或未加缓存；"
        "如果 TTFB 正常但总时间长，则是图片、JS 体积过大且未启用压缩缓存。",
        "先压低首字节时间，再做静态资源优化",
        "在服务器上用 curl -o /dev/null -s -w '%{time_starttransfer}' 测 TTFB：超过 0.6s 就是后端问题，"
        "优先加 Redis 缓存和慢查询索引；TTFB 正常则开启 Nginx gzip 并为静态资源设置长缓存。",
        "# Nginx：开启 gzip + 静态资源长缓存\n"
        "gzip on;\n"
        "gzip_types text/css application/javascript application/json image/svg+xml;\n"
        "location ~* \\.(js|css|png|jpg|jpeg|webp|svg|woff2)$ {\n"
        "    expires 30d;\n"
        "    add_header Cache-Control \"public\";\n"
        "}",
    ),
    "ssl": (
        "HTTPS 证书临近到期。企业站点最典型的事故就是证书过期，"
        "一旦过期浏览器会直接弹出安全警告拦截访问，用户流失会非常明显。",
        "完成证书续期并配置自动续期",
        "登录域名服务商或 CA 控制台确认证书到期日，完成续期与重新部署；"
        "同时用 certbot 配置定时自动续期，避免下个周期重演。",
        "# 续期并开启自动续期（Let's Encrypt + Nginx）\n"
        "sudo certbot renew --dry-run\n"
        "sudo systemctl enable --now certbot.timer\n"
        "sudo nginx -t && sudo systemctl reload nginx",
    ),
    "broken_link": (
        "存在指向 404 的站内链接，通常是页面改版或文章下线后忘记同步更新链接，"
        "既影响访客体验，也会让搜索引擎判定站点质量下降。",
        "清理死链并补上重定向",
        "用爬虫工具导出全部 4xx 链接清单，逐条判断：有效内容就补 301 到新地址，"
        "已下线的就从页面里摘掉；同时在 CMS 里增加发布前链接检查。",
        "# 导出站内 4xx 链接清单\n"
        "wget --spider -r -nd -nv -o spider.log https://你的域名\n"
        "grep -E \" 40[0-9] | 50[0-9] \" spider.log",
    ),
    "seo": (
        "页面缺少 title / meta description / H1 等基础标签。"
        "这不影响用户访问，但会明显影响搜索引擎收录质量与点击率。",
        "补齐页面基础 SEO 标签",
        "为每个页面补一个独一无二的 title（品牌词 + 业务词，30 字以内）和 description"
        "（60–120 字，含地域与核心产品词），并保证每页有且仅有一个 H1。",
        "<!-- 补齐 <head> 内的基础 SEO 标签 -->\n"
        "<title>企业名称 - 主营业务一句话描述</title>\n"
        "<meta name=\"description\" content=\"用 60–120 字概括本站核心业务，包含关键地域与产品词。\">\n"
        "<!-- 正文中每页有且仅有一个 H1 -->\n"
        "<h1>页面主标题</h1>",
    ),
    "accessibility": (
        "部分内容图片缺少 alt 文本描述，使用读屏软件的视障用户无法获知图片承载的信息，"
        "这也是无障碍改造中最常见、最容易整改的一项。",
        "为内容图片补充 alt 描述",
        "区分图片性质：承载信息的图片写一句能说明其内容的 alt；纯装饰性图片写空 alt=\"\"，"
        "让读屏软件直接跳过，而不是把文件名念出来。",
        "<!-- 内容图写清楚，装饰图留空 -->\n"
        "<img src=\"banner.jpg\" alt=\"2026 年春季新品发布会现场\">\n"
        "<img src=\"divider.png\" alt=\"\">",
    ),
}


def _mock_diagnose(report: dict) -> dict:
    """基于规则问题清单生成一份结构化的模拟诊断结论。"""
    issues = sorted(
        report.get("issues") or [],
        key=lambda i: _LEVEL_ORDER.get(i.get("level", "P3"), 3),
    )
    url = report.get("final_url") or report.get("url") or "该站点"

    if not issues:
        return {
            "summary": "本次巡检未发现明显异常，站点可用性与基础质量指标均处于正常范围。",
            "severity": "P3",
            "root_causes": [],
            "actions": [
                {
                    "priority": 1,
                    "action": "保持日常巡检频率",
                    "how": "维持每 30 分钟一次的自动巡检，并关注响应耗时的趋势变化，先于故障发现劣化。",
                }
            ],
            "patch": "",
            "_meta": {"model": MOCK_PROVIDER, "provider": "mock", "total_tokens": 0, "note": MOCK_WARNING},
        }

    severity = issues[0].get("level", "P3")

    # 按类别去重，同类问题只保留最严重的那条
    picked: list[dict] = []
    seen: set[str] = set()
    for issue in issues:
        cat = issue.get("category", "other")
        if cat in seen:
            continue
        seen.add(cat)
        picked.append(issue)
        if len(picked) == 3:
            break

    root_causes = []
    actions = []
    for idx, issue in enumerate(picked):
        cat = issue.get("category", "other")
        reason, action, how, _patch = _MOCK_KNOWLEDGE.get(
            cat,
            (
                "该项需要结合业务上下文进一步判断。",
                f"跟进处理：{issue.get('message', '')}",
                "补充近期变更记录与访问日志后再做定位。",
                "",
            ),
        )
        root_causes.append({"issue": issue.get("message", ""), "reason": reason})
        actions.append({"priority": idx + 1, "action": action, "how": how})

    # 修复片段取第一个有现成代码的类别
    patch = ""
    for issue in picked:
        candidate = _MOCK_KNOWLEDGE.get(issue.get("category", ""), ("", "", "", ""))[3]
        if candidate:
            patch = candidate
            break

    top_msg = issues[0].get("message", "")
    levels = sorted({i.get("level", "P3") for i in issues}, key=lambda x: _LEVEL_ORDER.get(x, 3))
    summary = f"共发现 {len(issues)} 项问题，最高等级 {severity}（{'/'.join(levels)}）。首要问题是：{top_msg}"

    return {
        "summary": summary,
        "severity": severity,
        "root_causes": root_causes,
        "actions": actions,
        "patch": patch,
        "_meta": {"model": MOCK_PROVIDER, "provider": "mock", "total_tokens": 0, "note": MOCK_WARNING},
    }


def _mock_daily_report(report: dict, diagnosis: dict) -> str:
    """把模拟诊断整理成 Markdown 简报，结构与真实模型输出保持一致。"""
    url = report.get("final_url") or report.get("url") or "—"
    issues = sorted(
        report.get("issues") or [],
        key=lambda i: _LEVEL_ORDER.get(i.get("level", "P3"), 3),
    )
    ssl = report.get("ssl_days_left")

    lines = [
        "# 网站运维简报",
        "",
        f"> {MOCK_WARNING}",
        "",
        "## 一句话结论",
        "",
        diagnosis.get("summary", "—"),
        "",
        "## 关键指标",
        "",
        f"- 站点地址：{url}",
        f"- 巡检时间：{report.get('scanned_at') or '—'}",
        f"- 最高等级：{diagnosis.get('severity', '—')}",
        f"- 响应耗时：{report.get('response_ms') if report.get('response_ms') is not None else '—'} ms",
        f"- HTTP 状态码：{report.get('status_code') if report.get('status_code') is not None else '—'}",
        f"- SSL 剩余：{ssl if ssl is not None else '—'} 天",
        f"- 死链数量：{len(report.get('broken_links') or [])}",
        "",
        "## 发现的问题",
        "",
    ]

    if issues:
        for issue in issues:
            lines.append(f"- **[{issue.get('level', 'P3')}]** {issue.get('message', '')}")
    else:
        lines.append("- 本次巡检未发现问题。")

    lines += ["", "## 建议处置动作", ""]
    actions = diagnosis.get("actions") or []
    if actions:
        for act in actions:
            lines.append(f"{act.get('priority', '-')}. **{act.get('action', '')}** —— {act.get('how', '')}")
    else:
        lines.append("暂无需要立即处置的动作。")

    if diagnosis.get("patch"):
        lines += ["", "## 修复片段", "", "```", diagnosis["patch"], "```"]

    return "\n".join(lines) + "\n"


async def diagnose(report: dict) -> dict:
    """对一份体检报告做 AI 诊断。

    运行模式由 .env 的 MAAS_MODE 决定：
    auto（默认）——配了 Key 就调真实模型，没配则返回内置模拟诊断
    on           ——强制模拟，不发任何网络请求
    off          ——强制真实模型，没配好直接抛 RuntimeError
    """
    if mock_active():
        return _mock_diagnose(report)

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
    if mock_active():
        return _mock_daily_report(report, diagnosis)

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
    if mock_active():
        return "模拟模式已启用（未接入真实模型，不会产生任何费用）"

    if not maas_ready():
        raise RuntimeError("MAAS_NOT_CONFIGURED")
    resp = await get_client().chat.completions.create(
        model=MAAS_MODEL,
        messages=[{"role": "user", "content": "回复两个字：正常"}],
        temperature=0,
    )
    return resp.choices[0].message.content or ""
