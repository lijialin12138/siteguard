"""AI 诊断层 —— 这是整个项目的灵魂。

输入：scanner.py 产出的结构化体检报告
输出：根因分析 + 严重等级 + 可执行的修复建议 + 可落地的修复补丁（patches）

模型走华为云 MaaS（ModelArts Studio），接口与 OpenAI 完全兼容，
所以直接复用 openai 这个库，只需要把 base_url 指过去。

D5 升级点（见 docs/patch契约提案.md）：
- 诊断结果新增结构化补丁列表 `patches`（按问题类别各一段），旧字段 `patch` 保留做兜底。
- 补丁按 issue.category 给出对应类型的、可直接复制落地的 bash/nginx/html 片段。
- SYSTEM_PROMPT 增加硬约束：禁止编造不存在的文件路径/命令；link_unverified 只给复核命令、绝不给删除。
"""

import json
import re
from typing import Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from .config import MAAS_API_KEY, MAAS_BASE_URL, MAAS_MODEL, maas_ready, mock_active

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """延迟创建客户端，避免没配 Key 时一 import 就崩。"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=MAAS_API_KEY, base_url=MAAS_BASE_URL, timeout=60)
    return _client


SYSTEM_PROMPT = """你是一名资深的企业级网站运维工程师（SRE），擅长从监控数据中快速定位故障根因，并给出能直接落地的修复补丁。

你会收到一份由自动化巡检程序生成的「网站体检报告」JSON，里面可能包含：
站点地址、HTTP 状态码、响应耗时、SSL 证书剩余天数、
页面基础信息（标题/描述/H1 数量/图片 alt 缺失数）、链接异常清单，
以及程序依据规则初步标记的问题清单 issues（每条带 level 与 category）。

关于链接异常，报告里会分三类给出，含义严格不同，**不要混用**：
- broken_link：对方明确返回 404/410（资源不存在）的失效链接，这才是真正需要修的「死链」；
- link_server_error：返回 5xx 的链接，多为服务端瞬时故障，未必是链接本身的问题；
- link_unverified：连不上、被反爬拦截或被限流而无法验证的链接（403/429/超时属于这一类）。
  它们**不代表链接失效**——403/429 表示「拒绝服务」而非「不存在」，浏览器往往能正常打开。
  不要在结论里把它们说成死链，只能提示人工确认或稍后复测。

你的任务：像一名真正的运维工程师那样分析这份报告，给出诊断结论，并产出可执行的修复补丁。

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
  "patches": [
    {
      "category": "必须与 issues 中真实出现的 category 一致，如 ssl / performance / broken_link / seo",
      "title": "一句话说明这段补丁在干什么",
      "language": "代码高亮语言：bash / nginx / html / json，纯文本留空串",
      "code": "可直接复制粘贴到服务器执行的代码/配置片段，不要带多余解释"
    }
  ],
  "patch": "兼容字段：把上面 patches 里的关键段合并成一段纯文本，方便老前端兜底渲染"
}
3. root_causes 和 actions 都要按重要性从高到低排序，最多各 3 条。
4. patches 为每个真实存在的问题类别各给一段补丁，按 severity 从高到低排列；
   只有报告里确实存在的问题类别才给补丁，**禁止编造报告里不存在的问题或配置**。
5. 严禁编造报告中不存在的数据，也严禁编造不存在的文件路径 / 命令 / 域名。
   无法确定确定性补丁时（例如需要业务上下文才能决定的改动），该类别就不放入 patches，
   并在对应 action 的 how 里说明还需补充哪些信息，绝不瞎编一段看似可用的代码。
6. 特别约束：
   - link_unverified 类的补丁只能是「复核 / 人工确认」类命令，**绝不能给「删除链接」**，
     因为 403/429/超时不等于死链，误删会烧掉客户的真实链接。
   - link_server_error 类先给「复测」命令，确认是瞬时故障；只有复测仍 5xx 且确为死链，
     才在说明里给出替换 / 301 示例，不要上来就删。
7. 全部用中文回答（代码注释可用中文）。"""

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
    link_5xx = report.get("server_error_links") or []
    unverified = report.get("unverified_links") or []
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
        # 链接问题分三类给出，含义不同，不要混为一谈：
        # broken = 确认 4xx 失效；server_error = 5xx（可能瞬时）；unverified = 无法验证，不等于失效
        "broken_link_count": len(broken),
        "broken_link_samples": [b.get("url") for b in broken[:5]],
        "link_server_error_count": len(link_5xx),
        "link_server_error_samples": [b.get("url") for b in link_5xx[:5]],
        "link_unverified_count": len(unverified),
        "link_unverified_samples": [b.get("url") for b in unverified[:5]],
        "issues": report.get("issues") or [],
        "fetch_error": report.get("error"),
        "scanned_at": report.get("scanned_at"),
    }


# ============================================================
#  内置模拟诊断（MOCK）
# ------------------------------------------------------------
#  没有真实 API Key 也能把「巡检 → 诊断 → 修复补丁」整条链路跑通。
#  它不是随便编一段话：会读取真实巡检报告里的 issues，按 11 个问题类别给出
#  对应的根因判断、可执行处置建议、以及可落地（复制即用）的修复补丁片段。
#  输出的结构与真实模型完全一致（含 patches 数组），前端无需区别对待。
#
#  正式提交/录演示视频前，把 .env 里的 MAAS_MODE 设为 off，确保走的是真实大模型。
# ============================================================

MOCK_PROVIDER = "mock-diagnosis"
MOCK_WARNING = "⚠️ 本结论由内置模拟诊断生成，未调用真实大模型（未配置 MaaS API Key）。正式提交前请接入真实模型。"

_LEVEL_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# 每个问题类别对应的「根因 / 处置动作 / 操作步骤 / 补丁片段」。
# patch 是一个 dict：{title, language, code}，其中 code 用 {url}/{host} 占位，
# 运行时按真实报告里的样本地址替换，保证补丁可落地、不编造路径。
# 这些片段是确定性的运维/前端常识（certbot、nginx gzip、html head 等），非凭空捏造。
_MOCK_KNOWLEDGE: dict[str, dict] = {
    "availability": {
        "root_cause": "站点无响应，通常是 Web 服务进程挂掉、端口未监听或网络/DNS 不通。",
        "action": "按网络层→HTTP 层→服务层顺序排查并恢复可用性",
        "how": "1．ping 域名确认网络连通；2．curl -I 看 HTTP 返回；3．登录服务器 systemctl status 看服务是否在跑；4．拉起服务并看错误日志定位根因。",
        "patch": {
            "title": "排查并恢复站点可用性",
            "language": "bash",
            "code": (
                "# 1) 网络层连通性\n"
                "ping -c 4 {host}\n"
                "# 2) HTTP 层返回（绕过本地缓存）\n"
                "curl -I https://{host}\n"
                "# 3) 登录服务器后看 Web 服务状态\n"
                "systemctl status nginx --no-pager\n"
                "# 4) 拉起服务并看最近报错\n"
                "journalctl -u nginx -n 50 --no-pager"
            ),
        },
    },
    "server_error": {
        "root_cause": "服务端返回 5xx，多为后端异常、依赖超时、或资源耗尽（CPU/内存/连接数）。",
        "action": "捞取服务端错误日志，定位 5xx 根因",
        "how": "1．看 Nginx/应用错误日志最近 50 条；2．确认是否有近期发布或依赖故障；3．按日志里的堆栈/报错修复后复测。",
        "patch": {
            "title": "捞取服务端错误日志，定位 5xx 根因",
            "language": "bash",
            "code": (
                "# Nginx 错误日志\n"
                "journalctl -u nginx -n 50 --no-pager\n"
                "# 或\n"
                "tail -n 50 /var/log/nginx/error.log\n"
                "# 应用层日志（以 systemd 托管的 Python/Node 服务为例）\n"
                "journalctl -u myapp -n 50 --no-pager"
            ),
        },
    },
    "client_error": {
        "root_cause": "页面返回 4xx（非 404 死链），常见于旧路径未做 301、或静态资源权限/路由配置问题。",
        "action": "补全 301 重定向 / 修正访问权限",
        "how": "1．确认是否旧路径迁移；2．在 Nginx 给旧路径加 301 到新地址；3．若是权限问题，修正文件/目录权限与 location 规则。",
        "patch": {
            "title": "补全 301 重定向 / 修正访问权限",
            "language": "nginx",
            "code": (
                "# 把旧路径 301 到新路径（避免 404 影响 SEO 与用户）\n"
                "server {\n"
                "    listen 80;\n"
                "    server_name example.com;\n"
                "    location = /old-path {\n"
                "        return 301 https://example.com/new-path;\n"
                "    }\n"
                "}"
            ),
        },
    },
    "redirect": {
        "root_cause": "存在多余跳转（如 http→https 与 www/非 www 分两步），延长首字节时间、不利 SEO。",
        "action": "合并多余跳转，减少 301 链",
        "how": "1．确认目标域名（带不带 www）；2．在 Nginx 把 http 与 www 跳转合并成一次 301。",
        "patch": {
            "title": "合并多余跳转，减少 301 链",
            "language": "nginx",
            "code": (
                "# http + www 一次性跳到 https 裸域\n"
                "server {\n"
                "    listen 80;\n"
                "    server_name www.example.com;\n"
                "    return 301 https://example.com$request_uri;\n"
                "}"
            ),
        },
    },
    "performance": {
        "root_cause": "响应偏慢，常见于未启用 gzip 压缩、静态资源无缓存、或后端未做查询/缓存优化。",
        "action": "开启 gzip 压缩与静态资源长缓存",
        "how": "1．在 Nginx 开启 gzip 并限定类型；2．给带 hash 的静态资源设长缓存；3．必要时接入 CDN 或优化后端慢查询。",
        "patch": {
            "title": "开启 gzip 压缩与静态资源缓存",
            "language": "nginx",
            "code": (
                "# /etc/nginx/conf.d/performance.conf\n"
                "gzip on;\n"
                "gzip_types text/css application/javascript application/json image/svg+xml;\n"
                "gzip_min_length 1024;\n"
                "\n"
                "# 静态资源长缓存（文件名带 hash 的可长期缓存）\n"
                "location ~* \\.(js|css|png|jpg|svg|woff2)$ {\n"
                "    expires 30d;\n"
                "    add_header Cache-Control \"public, immutable\";\n"
                "}"
            ),
        },
    },
    "ssl": {
        "root_cause": "SSL 证书临近到期或已过期，多为自动续期未配置 / 手动续期漏执行。",
        "action": "续期证书并配置自动续期",
        "how": "1．服务器安装 certbot；2．执行证书申请/续期命令（自动改写 Nginx 配置）；3．配置定时任务自动续期并 dry-run 校验。",
        "patch": {
            "title": "证书续期并配置自动续期",
            "language": "bash",
            "code": (
                "# 安装 certbot（Debian/Ubuntu）\n"
                "sudo apt install certbot python3-certbot-nginx\n"
                "# 申请 / 续期证书（自动改写 Nginx 配置）\n"
                "sudo certbot --nginx -d example.com -d www.example.com\n"
                "# 校验自动续期定时任务是否生效\n"
                "sudo certbot renew --dry-run\n"
                "# 加入 crontab：每月 1 号 03:00 续期（失败时重载 Nginx）\n"
                "0 3 1 * * certbot renew --quiet --post-hook \"nginx -s reload\""
            ),
        },
    },
    "broken_link": {
        "root_cause": "页面内存在高优先级失效链接（已确认 404/410，资源确实不存在），用户点击无法访问。",
        "action": "修正失效超链接",
        "how": "1．定位网页中失效的 a 标签；2．把 href 改为正确地址，或在新地址部署 301；3．重新发布页面后复测。",
        "patch": {
            "title": "修正失效超链接",
            "language": "html",
            "code": (
                "<!-- 失效链接（已确认 404/410，资源确不存在）：{url} -->\n"
                "<!-- 在页面源码里把失效的 a 标签改到正确地址 -->\n"
                '<a href="https://正确地址">链接文本</a>\n'
                "<!-- 推荐：在 Nginx 加 301 跳转到新地址 -->\n"
                "<!-- location = /old-path { return 301 https://正确地址; } -->"
            ),
        },
    },
    "link_server_error": {
        "root_cause": "有链接返回 5xx，绝大多数是目标服务端瞬时故障，未必是链接本身失效。",
        "action": "先复测确认是否瞬时故障，确为死链再修",
        "how": "1．用浏览器 UA 复测 3 次；2．若持续 5xx 且确为死链，再把页面 a 标签改到可用地址或加 301；3．短暂 5xx 不必动。",
        "patch": {
            "title": "对 5xx 链接复测，确认是否瞬时故障",
            "language": "bash",
            "code": (
                "# 该链接返回 5xx，多为服务端瞬时故障。先用浏览器 UA 复测 3 次确认：\n"
                'for i in 1 2 3; do\n'
                '  curl -A "Mozilla/5.0" -s -o /dev/null -w "%{http_code}\\n" "{url}"\n'
                "  sleep 5\n"
                "done\n"
                "# 若复测持续 5xx 且确为死链，再把页面 <a href=\"{url}\"> 改为可用地址，\n"
                "# 或在 Nginx 加 301：location = /old { return 301 https://新地址; }"
            ),
        },
    },
    "link_unverified": {
        "root_cause": "链接无法验证（403/429/超时），通常是反爬或限流，浏览器往往能正常打开，不等于链接失效。",
        "action": "先复核确认，切勿急于删除链接",
        "how": "1．用浏览器 UA 复核该链接；2．若浏览器也能正常打开则无需处理；3．仅当确为死链才改 a 标签或加 301，严禁直接删除。",
        "patch": {
            "title": "对无法验证的链接复核（切勿急于删除）",
            "language": "bash",
            "code": (
                "# 该链接无法验证（403/429/超时），多为反爬或限流，浏览器通常能正常打开。\n"
                "# 先复核，不要当死链删：\n"
                'curl -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -s -o /dev/null -w "%{http_code}\\n" "{url}"\n'
                "# 仅当浏览器也无法打开、确为死链时，才改 <a href> 或加 301。切勿直接删除链接。"
            ),
        },
    },
    "seo": {
        "root_cause": "页面缺少 title / meta description / H1 等基础 SEO 标签，影响搜索引擎收录与排名。",
        "action": "补全页面 <head> 基础 SEO 标签",
        "how": "1．在 <head> 补 title 与 meta description；2．正文确保有且仅有 1 个 H1；3．发布后复测。",
        "patch": {
            "title": "补全页面 <head> 基础 SEO 标签",
            "language": "html",
            "code": (
                "<head>\n"
                '  <title>页面标题（建议 ≤ 60 字，含核心关键词）</title>\n'
                '  <meta name="description" content="一句话描述本页内容，建议 ≤ 120 字">\n'
                "  <!-- 页面正文需有且仅有 1 个 H1 -->\n"
                "</head>\n"
                "<!-- 正文示例：<h1>主标题</h1> -->"
            ),
        },
    },
    "accessibility": {
        "root_cause": "部分图片缺少 alt 描述，屏幕阅读器无法识别，影响无障碍合规与 SEO。",
        "action": "为图片补全 alt 描述",
        "how": "1．给每张内容图加 alt 描述其含义；2．纯装饰性图片用 alt=\"\"；3．发布后复测。",
        "patch": {
            "title": "为图片补全 alt 描述",
            "language": "html",
            "code": (
                '<!-- 给每张图加 alt，描述图片内容（装饰性图片用 alt=""） -->\n'
                '<img src="/img/banner.png" alt="产品主视觉横幅">'
            ),
        },
    },
}


def _host_of(report: dict) -> str:
    """从报告 URL 取出 host，用于 availability 类补丁占位。"""
    url = report.get("final_url") or report.get("url") or ""
    try:
        host = urlparse(url).netloc or urlparse("//" + url).netloc
    except Exception:
        host = ""
    return host or "example.com"


def _sample_url(report: dict, category: str) -> str:
    """取该类别第一个样本链接地址，用于 broken_link / link_server_error / link_unverified 的补丁占位。"""
    mapping = {
        "broken_link": report.get("broken_links") or [],
        "link_server_error": report.get("server_error_links") or [],
        "link_unverified": report.get("unverified_links") or [],
    }
    items = mapping.get(category)
    if items:
        return items[0].get("url", "")
    return ""


def _fill_patch(code: str, report: dict, category: str) -> str:
    """把补丁模板里的 {url}/{host} 占位替换成报告里的真实样本地址。"""
    code = code.replace("{url}", _sample_url(report, category) or "<链接地址>")
    code = code.replace("{host}", _host_of(report))
    return code


def _mock_diagnose(report: dict) -> dict:
    """基于规则问题清单给出一份模拟诊断结论（含结构化 patches 补丁）。"""
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
            "patches": [],
            "patch": "",
            "_meta": {"model": MOCK_PROVIDER, "provider": "mock", "total_tokens": 0, "note": MOCK_WARNING},
        }

    severity = issues[0].get("level", "P3")

    # 按类别去重，同类问题只保留最严重的那条（最多 3 条，已按 severity 排序）
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

    root_causes: list[dict] = []
    actions: list[dict] = []
    patches: list[dict] = []

    for idx, issue in enumerate(picked):
        cat = issue.get("category", "other")
        kn = _MOCK_KNOWLEDGE.get(cat)
        if kn:
            root_causes.append({"issue": issue.get("message", ""), "reason": kn["root_cause"]})
            actions.append({"priority": idx + 1, "action": kn["action"], "how": kn["how"]})
            patches.append(
                {
                    "category": cat,
                    "title": kn["patch"]["title"],
                    "language": kn["patch"]["language"],
                    "code": _fill_patch(kn["patch"]["code"], report, cat),
                }
            )
        else:
            root_causes.append(
                {"issue": issue.get("message", ""), "reason": "该项需要结合业务上下文进一步判断。"}
            )
            actions.append(
                {
                    "priority": idx + 1,
                    "action": f"跟进处理：{issue.get('message', '')}",
                    "how": "补充近期变更记录与访问日志后再做定位。",
                }
            )

    # 兼容字段：把 patches 合并成一段纯文本，方便老前端兜底渲染
    patch_single = "\n\n".join(p["code"] for p in patches)

    top_msg = issues[0].get("message", "")
    levels = sorted({i.get("level", "P3") for i in issues}, key=lambda x: _LEVEL_ORDER.get(x, 3))
    summary = f"共发现 {len(issues)} 项问题，最高等级 {severity}（{'/'.join(levels)}）。首要问题是：{top_msg}"

    return {
        "summary": summary,
        "severity": severity,
        "root_causes": root_causes,
        "actions": actions,
        "patches": patches,
        "patch": patch_single,
        "_meta": {"model": MOCK_PROVIDER, "provider": "mock", "total_tokens": 0, "note": MOCK_WARNING},
    }


def _mock_daily_report(report: dict, diagnosis: dict) -> str:
    """把模拟诊断整理成 Markdown 简报，优先渲染 patches 多段补丁。"""
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
        f"- 失效链接（4xx）：{len(report.get('broken_links') or [])}",
        f"- 服务端错误链接（5xx）：{len(report.get('server_error_links') or [])}",
        f"- 无法验证链接：{len(report.get('unverified_links') or [])}",
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

    # 优先渲染 patches 多段补丁，回退到旧 patch 单段
    patches = diagnosis.get("patches") or []
    if patches:
        lines += ["", "## 修复片段", ""]
        for p in patches:
            lang = p.get("language") or ""
            lines.append(f"### [{p.get('category', '')}] {p.get('title', '')}")
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(p.get("code", ""))
            lines.append("```")
            lines.append("")
    elif diagnosis.get("patch"):
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
    # 真实模型可能直接给 patches 数组；若只给了旧 patch 字段，保持原样交给后端 extract_patches 统一
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
