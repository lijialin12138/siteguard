"""网站巡检引擎。

职责单一：给一个 URL，返回一份结构化的「网站体检报告」。
这里只做「发现问题」，不做「分析原因」——分析交给 ai.py。

报告结构见 scan_site() 的 docstring，这是整个系统的数据契约，
后面的存储、AI 诊断、前端展示都依赖它，改动前先想清楚。
"""

import asyncio
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .config import MAX_CONCURRENCY, MAX_LINKS_PER_PAGE, REQUEST_TIMEOUT

USER_AGENT = "SiteGuard/0.1 (AI website maintenance assistant; Huawei ICT Competition)"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

# lxml 更快，但不是所有 Python 版本都有预编译包；装不上就用标准库兜底。
try:
    import lxml  # noqa: F401

    HTML_PARSER = "lxml"
except ImportError:  # pragma: no cover
    HTML_PARSER = "html.parser"


def normalize_url(url: str) -> str:
    """补全协议头，去掉首尾空格。用户经常只填 example.com。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL 不能为空")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _ssl_days_left_sync(host: str, port: int = 443, timeout: float = 8.0) -> int | None:
    """同步获取 SSL 证书剩余有效天数。证书过期是企业站点最常见的事故之一。"""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
    except Exception:
        return None

    not_after = cert.get("notAfter")
    if not not_after:
        return None
    try:
        expire = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    return (expire - datetime.now(timezone.utc)).days


async def check_ssl_days(url: str) -> int | None:
    """把阻塞的证书检查丢到线程里跑，避免卡住事件循环。"""
    parsed = urlparse(normalize_url(url))
    if parsed.scheme != "https":
        return None
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or 443
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ssl_days_left_sync, host, port)


def _extract_page_info(html: str, base_url: str) -> dict:
    """从 HTML 里提取页面基础健康信息与所有链接。"""
    soup = BeautifulSoup(html, HTML_PARSER)

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = (meta_desc.get("content") or "").strip() if meta_desc else ""

    h1_count = len(soup.find_all("h1"))

    imgs = soup.find_all("img")
    imgs_without_alt = len([i for i in imgs if not (i.get("alt") or "").strip()])

    links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if absolute.startswith(("http://", "https://")):
            links.add(absolute.split("#")[0])

    return {
        "title": title,
        "description": description,
        "h1_count": h1_count,
        "images_total": len(imgs),
        "images_without_alt": imgs_without_alt,
        "links": sorted(links),
    }


# 链接探测的三种结论。分开统计是控制误报的关键：
#   broken       —— 确认失效（404/410），可以直接去修
#   server_error —— 服务端异常（5xx），可能是瞬时的，未必是链接本身的问题
#   unverified   —— 无法验证（连接异常/超时/被拒绝/被限流），**不等于失效**，只提示人工确认
VERDICT_BROKEN = "broken"
VERDICT_SERVER_ERROR = "server_error"
VERDICT_UNVERIFIED = "unverified"

# 只有这两个状态码能证明「资源确实不存在」，可以直接判定失效。
# 注意不要把 403/429 混进来：它们表示「拒绝服务」而不是「不存在」。
# 实测某高校官网的 6 个子站链接被连续巡检触发限流返回 403，
# 隔几分钟再用完全相同的请求复测，全部恢复 200（http 还会正常跳转到 https）。
# 如果把它们当死链报出去，用户会去修一堆本来好好的链接。
DEFINITIVE_GONE = frozenset({404, 410})


async def _request_status(
    client: httpx.AsyncClient, method: str, url: str
) -> tuple[int | None, str | None]:
    """发一次请求，返回 (状态码, 异常类名)。异常时状态码为 None。"""
    try:
        resp = await client.request(method, url, follow_redirects=True)
        return resp.status_code, None
    except Exception as exc:
        return None, type(exc).__name__


async def _probe_link(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> dict | None:
    """探测单个链接。返回 None 表示确认可用，否则返回异常描述（含 verdict）。

    探测策略上有个容易踩的坑：HEAD 请求最快，但**很多站点对 HEAD 的响应不可信**——
    部分服务器不支持 HEAD，部分反爬策略（例如微信公众号文章）收到 HEAD 会直接断连，
    于是链接被误判成死链。实测某高校官网上 20 个「死链」里有 18 个是这种误报。

    所以这里统一做二次复核：HEAD 失败或返回 4xx/5xx 时改用 GET 再确认一次。
    只有 GET 也失败，才认定链接有问题（且还要区分是 404、5xx 还是压根连不上）。

    另一类误报来自状态码本身：403/429 是「拒绝服务」（反爬、限流、需登录），
    不是「资源不存在」。只有 404/410 才判失效，其余 4xx 一律归入待人工确认。
    """
    async with sem:
        status, reason = await _request_status(client, "HEAD", url)
        if status is None or status >= 400:
            retry_status, retry_reason = await _request_status(client, "GET", url)
            if retry_status is not None:
                status, reason = retry_status, retry_reason

    if status is None:
        return {"url": url, "status": None, "reason": reason, "verdict": VERDICT_UNVERIFIED}
    if status in DEFINITIVE_GONE:
        return {
            "url": url,
            "status": status,
            "reason": "资源不存在",
            "verdict": VERDICT_BROKEN,
        }
    if status >= 500:
        return {
            "url": url,
            "status": status,
            "reason": "服务端错误",
            "verdict": VERDICT_SERVER_ERROR,
        }
    if status >= 400:
        # 401/403/429 及其他 4xx：拒绝访问、限流或方法不被接受，
        # 浏览器往往能正常打开，不能算失效。
        return {
            "url": url,
            "status": status,
            "reason": f"拒绝自动化访问（HTTP {status}）",
            "verdict": VERDICT_UNVERIFIED,
        }
    return None


async def probe_links(client: httpx.AsyncClient, links: list[str]) -> list[dict]:
    """并发探测页面内链。返回的全是「有异常」的条目，每条带 verdict 供调用方分桶。"""
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    targets = links[:MAX_LINKS_PER_PAGE]
    results = await asyncio.gather(
        *(_probe_link(client, link, sem) for link in targets), return_exceptions=True
    )
    return [r for r in results if isinstance(r, dict)]


def split_probes(probes: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """把探测结果分成 (确认失效, 服务端异常, 无法验证) 三桶。"""
    broken = [p for p in probes if p.get("verdict") == VERDICT_BROKEN]
    server_error = [p for p in probes if p.get("verdict") == VERDICT_SERVER_ERROR]
    unverified = [p for p in probes if p.get("verdict") == VERDICT_UNVERIFIED]
    return broken, server_error, unverified


def build_issues(report: dict) -> list[dict]:
    """把体检数据翻译成一条条「问题」。这是规则层，AI 拿到的是这些结构化问题。"""
    issues: list[dict] = []

    if report.get("error"):
        issues.append(
            {
                "level": "P0",
                "category": "availability",
                "message": f"站点无法访问：{report['error']}",
            }
        )
        return issues

    code = report.get("status_code")
    if code is None:
        issues.append({"level": "P0", "category": "availability", "message": "未获得有效响应"})
    elif code >= 500:
        issues.append(
            {"level": "P0", "category": "server_error", "message": f"服务端错误 HTTP {code}"}
        )
    elif code >= 400:
        issues.append(
            {"level": "P0", "category": "client_error", "message": f"页面返回 HTTP {code}"}
        )
    elif code >= 300:
        issues.append(
            {"level": "P3", "category": "redirect", "message": f"存在重定向 HTTP {code}"}
        )

    ms = report.get("response_ms")
    if isinstance(ms, int):
        if ms >= 5000:
            issues.append(
                {"level": "P1", "category": "performance", "message": f"响应极慢：{ms} ms"}
            )
        elif ms >= 2000:
            issues.append(
                {"level": "P2", "category": "performance", "message": f"响应偏慢：{ms} ms"}
            )

    days = report.get("ssl_days_left")
    if isinstance(days, int):
        if days <= 0:
            issues.append(
                {"level": "P0", "category": "ssl", "message": "SSL 证书已过期，浏览器会直接拦截"}
            )
        elif days <= 15:
            issues.append(
                {"level": "P1", "category": "ssl", "message": f"SSL 证书仅剩 {days} 天到期"}
            )

    broken = report.get("broken_links") or []
    if broken:
        issues.append(
            {
                "level": "P1",
                "category": "broken_link",
                "message": (
                    f"发现 {len(broken)} 个失效链接（HTTP 404/410，资源确实不存在），"
                    f"例如 {broken[0]['url']}"
                ),
            }
        )

    link_5xx = report.get("server_error_links") or []
    if link_5xx:
        issues.append(
            {
                "level": "P2",
                "category": "link_server_error",
                "message": (
                    f"{len(link_5xx)} 个链接返回服务端错误（5xx），"
                    f"例如 {link_5xx[0]['url']}"
                ),
            }
        )

    if not (report.get("title") or "").strip():
        issues.append({"level": "P2", "category": "seo", "message": "页面缺少 title 标签"})

    if not (report.get("description") or "").strip():
        issues.append(
            {"level": "P3", "category": "seo", "message": "缺少 meta description，影响搜索收录"}
        )

    if report.get("h1_count") == 0:
        issues.append({"level": "P3", "category": "seo", "message": "页面没有 H1 标题"})

    if report.get("images_without_alt", 0) > 0:
        issues.append(
            {
                "level": "P3",
                "category": "accessibility",
                "message": f"{report['images_without_alt']} 张图片缺少 alt 描述",
            }
        )

    # 「无法验证」放最后：它只是提示人工确认，优先级低于其他确定性问题，
    # 免得它把真正该修的问题挤出诊断结论。
    unverified = report.get("unverified_links") or []
    if unverified:
        denied = [u for u in unverified if u.get("status") is not None]
        unreachable = [u for u in unverified if u.get("status") is None]
        parts = []
        if denied:
            parts.append(f"{len(denied)} 个拒绝自动化访问（403/429 等，通常是反爬或限流）")
        if unreachable:
            parts.append(f"{len(unreachable)} 个连接失败（超时或不可达）")
        issues.append(
            {
                "level": "P3",
                "category": "link_unverified",
                "message": "；".join(parts) + "。以上均不等于链接失效，建议人工抽查确认",
            }
        )

    return issues


async def scan_site(url: str, deep: bool = True) -> dict:
    """对一个站点做一次完整巡检。

    :param url:  站点地址，http/https 前缀可省略
    :param deep: 是否扫描页面内链（死链检测）。False 时只做基础可用性检查，速度快很多
    :return: 结构化体检报告

    返回字段：
        url / final_url / ok / status_code / response_ms / ssl_days_left /
        title / description / h1_count / images_* /
        broken_links / server_error_links / unverified_links /
        issues / error / scanned_at

    链接相关的三个字段是刻意分开的，不要合并成一个「死链数」：
        broken_links       确认失效（404/410），可直接定位修复
        server_error_links 服务端异常（5xx），可能是瞬时的
        unverified_links   连不上 / 被拒绝 / 被限流，**不能当作失效**
    """
    target = normalize_url(url)
    report: dict = {
        "url": target,
        "final_url": target,
        "ok": False,
        "status_code": None,
        "response_ms": None,
        "ssl_days_left": None,
        "title": "",
        "description": "",
        "h1_count": 0,
        "images_total": 0,
        "images_without_alt": 0,
        "broken_links": [],
        "server_error_links": [],
        "unverified_links": [],
        "issues": [],
        "error": None,
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    timeout = httpx.Timeout(REQUEST_TIMEOUT)
    async with httpx.AsyncClient(headers=HEADERS, timeout=timeout, verify=True) as client:
        # 1) 可用性与性能
        try:
            started = datetime.now()
            resp = await client.get(target, follow_redirects=True)
            elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
            report.update(
                {
                    "status_code": resp.status_code,
                    "response_ms": elapsed_ms,
                    "final_url": str(resp.url),
                    "ok": resp.status_code < 400,
                }
            )
            html = resp.text if "text/html" in resp.headers.get("content-type", "") else ""
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            report["issues"] = build_issues(report)
            return report

        # 2) SSL 证书
        report["ssl_days_left"] = await check_ssl_days(report["final_url"])

        # 3) 页面信息 + 死链
        if html and deep:
            info = _extract_page_info(html, report["final_url"])
            report.update(
                {
                    "title": info["title"],
                    "description": info["description"],
                    "h1_count": info["h1_count"],
                    "images_total": info["images_total"],
                    "images_without_alt": info["images_without_alt"],
                }
            )
            probes = await probe_links(client, info["links"])
            (
                report["broken_links"],
                report["server_error_links"],
                report["unverified_links"],
            ) = split_probes(probes)
        elif html:
            info = _extract_page_info(html, report["final_url"])
            report.update(
                {
                    "title": info["title"],
                    "description": info["description"],
                    "h1_count": info["h1_count"],
                    "images_total": info["images_total"],
                    "images_without_alt": info["images_without_alt"],
                }
            )

    report["issues"] = build_issues(report)
    return report
