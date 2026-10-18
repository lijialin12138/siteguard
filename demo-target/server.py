"""SiteGuard 演示靶站（仅本地，绝不对外）。

用途：在「自己电脑」上造一个故意有缺陷的网站，用来安全演示
「扫描 → 诊断 → 出补丁 → 修改 → 复扫对比」的完整修复闭环。
它不属于任何真实网站，可以随意修改，没有合规风险。

    启动：
    cd siteguard
    .venv/Scripts/python.exe demo-target/server.py

然后在 SiteGuard（http://127.0.0.1:8000/）里添加站点：
    http://127.0.0.1:8001/

人为缺陷清单（扫描后应当被 SiteGuard 报出来）：
    1. 首页缺少 <meta name="description">      → SEO 缺陷 (P3)
    2. 首页有 1 张 <img> 没有 alt 属性          → 无障碍缺陷 (P3)
    3. /missing-page.html 不存在（返回 404）     → 失效链接 broken_link (P1)
    4. /boom 返回 500                          → 服务端错误 link_server_error (P2)

/about.html 是健康对照页（有 meta、有 alt），其链接不会被报缺陷。
"""

import os
import socketserver
from http.server import SimpleHTTPRequestHandler

PORT = 8001
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def _boom(self):
        # 故意返回 500，演示「服务端错误」类链接（不会被误判成死链）
        self.send_response(500)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = "<h1>500 Internal Server Error</h1><p>这是演示用的异常接口。</p>"
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        if self.path.split("?")[0] == "/boom":
            self._boom()
            return
        super().do_GET()

    def do_HEAD(self):
        if self.path.split("?")[0] == "/boom":
            self._boom()
            return
        super().do_HEAD()

    def log_message(self, fmt, *args):
        pass  # 安静模式，避免刷屏


if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), DemoHandler) as httpd:
        print(f"演示靶站已启动：http://127.0.0.1:{PORT}/")
        print("按 Ctrl+C 停止。注意：只允许本机访问，不对外部网络开放。")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n演示靶站已停止。")
