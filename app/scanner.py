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


async def _probe_link(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> dict | None:
    """探测单个链接是否可用。返回 None 表示正常，否则返回异常描述。"""
    async with sem:
        try:
            resp = await client.head(url, follow_redirects=True)
            # 不少服务器不支持 HEAD，用 GET 再试一次
            if resp.status_code in (405, 501):
                resp = await client.get(url, follow_redirects=True)
        except Exception as exc:
            return {"url": url, "status": None, "reason": type(exc).__name__}

    if resp.status_code >= 400:
        return {"url": url, "status": resp.status_code, "reason": "HTTP 错误"}
    return None


async def check_broken_links(client: httpx.AsyncClient, links: list[str]) -> list[dict]:
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    targets = links[:MAX_LINKS_PER_PAGE]
    results = await asyncio.gather(
        *(_probe_link(client, link, sem) for link in targets), return_exceptions=True
    )
    return [r for r in results if isinstance(r, dict)]


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
                "message": f"发现 {len(broken)} 个死链，例如 {broken[0]['url']}",
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

    return issues


async def scan_site(url: str, deep: bool = True) -> dict:
    """对一个站点做一次完整巡检。

    :param url:  站点地址，http/https 前缀可省略
    :param deep: 是否扫描页面内链（死链检测）。False 时只做基础可用性检查，速度快很多
    :return: 结构化体检报告

    返回字段：
        url / final_url / ok / status_code / response_ms / ssl_days_left /
        title / description / h1_count / images_* / broken_links /
        issues / error / scanned_at
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
            report["broken_links"] = await check_broken_links(client, info["links"])
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
