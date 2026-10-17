# D5 · 码道 CodeArts 补丁生成证据包

> 角色 B（小甘）· 负责 `app/ai.py` 的 `patches` 升级
> 赛题要求：补丁须由「码道 CodeArts」生成 / 校对并留痕，作为答辩「用了华为技术」的证据链。

## 一、证据是怎么产生的（可复现）

本机码道 CodeArts Agent 已安装：

```
C:\Program Files\CodeArts Agent\codearts-agent.exe
```

通过官方 CLI 的 `chat` 子命令驱动，**在 `D:\xiangmucode\siteguard` 工作目录下**向码道会话发送 6 类补丁生成提示词：

```bash
cd D:\xiangmucode\siteguard
codearts-agent chat -r --mode agent "<某类别的提示词>"
```

参数说明：

| 参数 | 含义 |
| ---- | ---- |
| `chat` | 把提示词送入当前工作目录的码道会话 |
| `-r` | 复用当前已激活的码道窗口（避免开一堆新窗口） |
| `--mode agent` | 使用 agent 模式（可读写工作区文件，产出可落地片段） |

本次实际执行的 6 次调用均返回 `exit=0`（提示词已成功送达会话）：

```
ssl               -> exit=0
broken_link       -> exit=0
performance       -> exit=0
seo               -> exit=0
link_unverified   -> exit=0
link_server_error -> exit=0
```

> **为什么这里只记录了 exit code、没有贴出模型原文？**
> 码道 Agent 是一个 GUI 客户端，`chat` 子命令只负责「把提示词送进会话」，
> 生成结果在客户端窗口里渲染，**不回写到 stdout、也不落盘到可读日志**。
> 所以「模型原文」这一层证据必须以**客户端会话截图**为准 —— 见第三节。
>
> **补充说明（重要，避免答辩被问住）**：本次最终证据并非由 CLI 直接抓取。
> CLI 那条路实测只能把主窗口切到 siteguard 工作区，右侧「码道码智能体」面板仍显示
> 「暂未查询到对话历史」——即提示词没有真正落成可见会话。
> 因此最终 6 张证据截图是**在码道客户端右侧面板的输入框里逐条手动粘贴 `prompts.txt` 中的提示词生成**的，
> 这样每张截图都能同时看到「人工粘贴的提示词 + 码道返回的补丁 JSON」，证据链反而更硬。

## 二、6 类补丁：送入码道的提示词 + 基准补丁

下表每一类 = 一条真实送入码道的提示词 + 该项目认可的基准补丁（与 `app/ai.py` 的 `_MOCK_KNOWLEDGE` 一致，用于交叉校验码道产出是否落地可用）。

### 1. `ssl` —— 证书临期

**提示词**

```
你是华为云运维助手。场景：企业站点HTTPS证书将于15天内到期。请给出Linux(Nginx)下 certbot
证书续期与自动续期方案，含安装、申请、dry-run校验、crontab 定时续期与 nginx -s reload。
输出为JSON数组，元素含 category,title,language,code，category=ssl, language=bash。
```

**基准补丁**（category=ssl, language=bash）

```bash
# 安装 certbot（Debian/Ubuntu）
sudo apt install certbot python3-certbot-nginx
# 申请 / 续期证书（自动改写 Nginx 配置）
sudo certbot --nginx -d example.com -d www.example.com
# 校验自动续期定时任务是否生效
sudo certbot renew --dry-run
# 加入 crontab：每月 1 号 03:00 续期（失败时重载 Nginx）
0 3 1 * * certbot renew --quiet --post-hook "nginx -s reload"
```

### 2. `broken_link` —— 已确认 404 死链

**提示词**

```
你是华为云运维助手。场景：页面存在已确认404的链接 https://demo.test/old.html。
请给出修复：1)HTML里把a标签href改到正确地址；2)Nginx 301跳转示例。
输出JSON数组，元素含 category,title,language,code，category=broken_link, language=html。
```

**基准补丁**（category=broken_link, language=html）

```html
<!-- 失效链接（已确认 404/410，资源确不存在）：https://demo.test/old.html -->
<!-- 在页面源码里把失效的 a 标签改到正确地址 -->
<a href="https://正确地址">链接文本</a>
<!-- 推荐：在 Nginx 加 301 跳转到新地址 -->
<!-- location = /old-path { return 301 https://正确地址; } -->
```

### 3. `performance` —— 响应耗时过高

**提示词**

```
你是华为云运维助手。场景：站点首页响应1820ms偏慢。请给出Nginx性能优化片段：
开启gzip(限定类型)、静态资源长缓存(expires与Cache-Control immutable)。
输出JSON数组，元素含 category,title,language,code，category=performance, language=nginx。
```

**基准补丁**（category=performance, language=nginx）

```nginx
# /etc/nginx/conf.d/performance.conf
gzip on;
gzip_types text/css application/javascript application/json image/svg+xml;
gzip_min_length 1024;

# 静态资源长缓存（文件名带 hash 的可长期缓存）
location ~* \.(js|css|png|jpg|svg|woff2)$ {
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

### 4. `seo` —— 缺基础 SEO 标签

**提示词**

```
你是华为云运维助手。场景：页面缺少title标签、meta name=description、唯一h1。
请给出完整head补全片段。
输出JSON数组，元素含 category,title,language,code，category=seo, language=html。
```

**基准补丁**（category=seo, language=html）

```html
<head>
  <title>页面标题（建议 ≤ 60 字，含核心关键词）</title>
  <meta name="description" content="一句话描述本页内容，建议 ≤ 120 字">
  <!-- 页面正文需有且仅有 1 个 H1 -->
</head>
<!-- 正文示例：<h1>主标题</h1> -->
```

### 5. `link_unverified` —— 403/429/超时，无法验证 ⚠️ 控误报铁律

**提示词**

```
你是华为云运维助手。场景：某链接返回403无法自动验证(反爬或限流)，浏览器可正常打开。
请只给出复核命令，严禁给出删除链接的操作。
输出JSON数组，元素含 category,title,language,code，category=link_unverified, language=bash。
```

**基准补丁**（category=link_unverified, language=bash）

```bash
# 该链接无法验证（403/429/超时），多为反爬或限流，浏览器通常能正常打开。
# 先复核，不要当死链删：
curl -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" -s -o /dev/null -w "%{http_code}\n" "<链接地址>"
# 仅当浏览器也无法打开、确为死链时，才改 <a href> 或加 301。切勿直接删除链接。
```

> 铁律：这一类**只允许给复核命令**，绝不能出现删除链接的操作 —— 403/429 不等于死链，误删会烧掉客户真实链接。
> 校验码道产出时，重点看它有没有违规给删除命令。

### 6. `link_server_error` —— 5xx 出站链接

**提示词**

```
你是华为云运维助手。场景：某出站链接返回5xx，先给浏览器UA复测3次命令确认是否瞬时故障，
仅当确为死链才给替换或301示例，不要上来就删。
输出JSON数组，元素含 category,title,language,code，category=link_server_error, language=bash。
```

**基准补丁**（category=link_server_error, language=bash）

```bash
# 该链接返回 5xx，多为服务端瞬时故障。先用浏览器 UA 复测 3 次确认：
for i in 1 2 3; do
  curl -A "Mozilla/5.0" -s -o /dev/null -w "%{http_code}\n" "<链接地址>"
  sleep 5
done
# 若复测持续 5xx 且确为死链，再把页面 <a href="<链接地址>"> 改为可用地址，
# 或在 Nginx 加 301：location = /old { return 301 https://新地址; }
```

## 三、截图留痕清单（小甘在码道客户端完成）

6 类提示词已全部送入你当前打开的码道窗口，每类是一个独立会话。请逐类截图：
| # | category | 截图文件名 | 取证要点 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | ssl | `ssl.png` | 要同时看到提示词 + 返回的 certbot/crontab 补丁 | ✅ 已存（crontab 自动续期 + `--post-hook nginx -s reload` + dry-run 均覆盖） |
| 2 | broken_link | `broken_link.png` | 看到 `<a href>` 修正 + Nginx 301 | ✅ 已存（HTML 修 href + Nginx 301 两项均覆盖） |
| 3 | performance | `performance.png` | 看到 gzip + 静态资源缓存配置 | ✅ 已存（gzip 限定类型 + `expires 1y`/`immutable` + HTML 入口不缓存） |
| 4 | seo | `seo.png` | 看到 `<head>` 补全片段 | ✅ 已存（`<title>` + `meta description` + 全页唯一 `<h1>`，另附 charset/viewport/canonical） |
| 5 | link_unverified | `link_unverified.png` | **确认只有复核命令、无删除操作** | ✅ 已存（3 条均为 `curl` 只读复核；结论显式声明"不含任何删除操作，该链接应保留并标记人工复核"） |
| 6 | link_server_error | `link_server_error.png` | 看到 3 次复测命令、非上来就删 | ✅ 已存（复测 3 次 → 查响应头区分 503+Retry-After 维护与真死链 → 才给替换/301；瞬时故障一律保留） |

截图要求：**整段问答都要拍进去**（你发的提示词 + 它回的补丁代码），并保存到 `docs/codearts-evidence/` 目录。

截图后把文件一并 `git add docs/codearts-evidence/*.png` 提交，答辩时这 6 张图 + 本文件 = 完整的「用了华为技术」证据链。

## 四、交叉校验结论

码道产出的补丁，按下面三条标准核对是否合格（三条全过才算闭环）：

1. **可执行**：代码片段能直接复制到服务器跑 / 粘贴进 Nginx / HTML 里改。
2. **不编造**：没有出现报告里不存在的域名、文件路径、命令。
3. **守铁律**：`link_unverified` 只给复核命令，没有任何删除动作。

本项目 `app/ai.py` 的 `_MOCK_KNOWLEDGE` 已按同样标准沉淀了 11 个类别的补丁（`availability` / `server_error` / `client_error` / `redirect` 额外 5 类同理），
因此即便码道某次产出不合标准，也能立刻比对发现 —— 这正是「生成 / 校对」里**校对**的含义。

## 五、校对记录（已实际发现并修正的问题）

这一节是答辩加分项：它不是"码道万能"的证据，而是**"我们真的在校对，而不是照单全收"**的证据。

| 类别 | 校对发现 | 处置 |
| --- | --- | --- |
| `broken_link` | 码道返回的第二个补丁块是 Nginx `server{}` 配置，但 `language` 字段标成了 `html`（应标 `nginx`），且该块漏了 `category` 字段 | 不影响功能正确性（HTML 修 `href` + Nginx 301 两项诉求均已覆盖，解释文字也点明了"HTML 修源头 + Nginx 兜底收藏链接"的分工），截图保留原样作为真实留痕；该字段规范已由 `app/ai.py` 的 `SYSTEM_PROMPT` 第 2 条显式约束 |
| `ssl` | 码道额外说明了 Let's Encrypt「仅在剩余有效期 < 30 天才真正续期」、并给出 `--force-renew --dry-run` 手动触发场景 | 比基准补丁更细，无冲突，**吸收进知识库口径** |
| `performance` | 码道主动给出**风险边界**：若静态资源无文件名哈希指纹，`immutable` 长缓存会导致发版不生效，建议缩到 `expires 7d` 或做指纹化构建 | 基准补丁只写了"文件名带 hash 的可长期缓存"，没有点破这个坑。**已按此口径补强 `_MOCK_KNOWLEDGE` 的说明** |
| `seo` | 码道除了三项要求，还补齐了 `charset` / `viewport` / `canonical`，并给出 `<h2>/<h3>` 的标题层级约束与"多页站点需逐页定制 title/description，不可全站复用" | 基准补丁只给了最小可用片段；**已将"多页站点不可复用同一份 title/description"这一条补进 `_MOCK_KNOWLEDGE` 的 how 说明** |
| `link_unverified` | **铁律通过**：三条 patch 均为 `curl` 只读复核（带 UA/完整请求头重试 + 查看 `Server`/`X-RateLimit`/`Retry-After` 响应头判定反爬/限流），无任何删除动作；并显式声明"403+浏览器可打开属典型反爬/限流假设，非死链……该链接应保留并在报告中标记人工复核状态" | ✅ **合规**。轻微瑕疵：第 3 条把结论文字放在了 `code` 字段（本应是 `title`/`how` 类字段），属契约字段使用不规范，不影响安全性；截图保留原样作为真实留痕 |
| `link_server_error` | **铁律通过**：流程为「复测 3 次 → 持续 5xx 再查响应头 → 才确认死链 → 才给替换/301」，并区分 `503 + Retry-After`（服务维护）与 `502/504`（真死链）；瞬时故障与维护场景**一律保留链接不做改动**，全程无删除操作 | ✅ **合规**。轻微瑕疵：`code` 字段里混入了中文描述性文字（如 "curl -X 3 次，复测为 5xx 时…"），非纯命令；截图里部分长行被折叠显示。字段纯净度可由 `SYSTEM_PROMPT` 进一步约束 |

> 方法论：码道负责"生成候选补丁"，`_MOCK_KNOWLEDGE` + `SYSTEM_PROMPT` 的硬约束负责"验收与兜底"，
> 两者互相校验后才写入产品 —— 这就是 D5 的 patch 管线设计。
