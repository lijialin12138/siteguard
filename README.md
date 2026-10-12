# SiteGuard · AI 自动化企业网站维护助手

> 第十一届华为ICT大赛 · 创新赛 · 赛题一：基于华为云产品打造 AI 创新应用

企业网站常年存在一类"没人管"的问题：证书快过期没人知道、页面挂了没人发现、外链死了没人清理。
SiteGuard 用**自动巡检 + AI 诊断 + 修复建议生成**，把这件事从"人工定期抽查"变成"系统自动闭环"。

## 它做什么

```
配置站点 → 定时自动巡检 → 发现异常并落库 → AI 诊断根因 → 生成修复建议与补丁 → 控制台展示
```

巡检项：

| 类别 | 检查内容 |
|---|---|
| 可用性 | HTTP 状态码、是否可访问、fetch 错误 |
| 性能 | 响应耗时（≥2s 预警，≥5s 告警） |
| 安全 | SSL 证书剩余有效天数（≤15 天预警，已过期告警） |
| 内容 | 死链扫描（页面内链逐个探测） |
| SEO / 无障碍 | title、meta description、H1 数量、图片 alt 缺失数 |

问题按 P0–P3 分级，再把结构化问题交给大模型分析根因和处置方案。

## 技术栈

| 层 | 选型 |
|---|---|
| 开发工具 | 华为云码道 CodeArts 代码智能体 |
| 语言 / 框架 | Python 3.13 + FastAPI + Uvicorn |
| 巡检 | httpx + BeautifulSoup4 |
| 定时任务 | APScheduler |
| 存储 | SQLite（原型阶段）→ 华为云 RDS（后续） |
| 大模型 | 华为云 MaaS（ModelArts Studio），OpenAI 兼容接口 |
| 前端 | 原生 HTML + JS（无构建工具） |

## 快速开始

### 1. 装依赖

```bash
cd siteguard
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

> **两件事必须注意：**
>
> 1. 如果 `pip` 提示找不到命令，一律改用 `python -m pip`。
> 2. **国内一定要加 `-i` 指定镜像源**，直连 pypi.org 大概率超时。首选清华源
>    `https://pypi.tuna.tsinghua.edu.cn/simple`；如果它返回 `from versions: none`
>    （限流时会这样），换阿里云源即可正常安装。

### 2. 配置华为云 MaaS

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
```

然后编辑 `.env`，填入三个值：

1. **区域选「西南-贵阳一」** —— 只有这个区域可能领到免费 Token 额度
2. 控制台 → ModelArts Studio → 模型推理 → 在线推理 → 免费服务 → **领取额度** → 调用说明
3. 复制 **API 地址**（删掉末尾的 `/chat/completions`，只留到 `/v1`）和 **API Key**（只显示一次）

### 3. 自检连通性

```bash
python scripts/smoke_maas.py
```

看到模型回话就说明配好了。

### 4. 启动

```bash
uvicorn app.main:app --reload
```

- 控制台：<http://127.0.0.1:8000/>
- 接口文档：<http://127.0.0.1:8000/docs>

加一个站点（比如你学校官网），点「巡检」，再点「AI 诊断」看效果。

## 目录结构

```
siteguard/
├── app/
│   ├── config.py       配置集中管理，业务代码不直接读环境变量
│   ├── db.py           SQLite 数据访问层，SQL 全部集中在此（便于迁 RDS）
│   ├── scanner.py      巡检引擎：只负责"发现问题"
│   ├── ai.py           AI 诊断：只负责"分析原因、给方案"
│   ├── service.py      业务编排：把巡检与落库串起来，API 和定时任务共用
│   ├── scheduler.py    定时巡检调度
│   ├── main.py         FastAPI 入口与路由
│   └── static/         控制台前端
├── scripts/
│   └── smoke_maas.py   第一天用的连通性自检
├── .env.example        环境变量模板（.env 已被 git 忽略）
└── requirements.txt
```

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/api/status` | MaaS 与调度器状态 |
| POST | `/api/status/maas-ping` | 大模型连通性自检 |
| GET | `/api/sites` | 站点列表 |
| POST | `/api/sites` | 添加站点 |
| DELETE | `/api/sites/{id}` | 删除站点 |
| GET | `/api/overview` | 各站点最近一次巡检（控制台首页数据） |
| POST | `/api/sites/{id}/scan` | 手动巡检单个站点（`?deep=false` 跳过死链扫描） |
| POST | `/api/scan/all` | 立即巡检全部站点 |
| GET | `/api/scans` | 巡检历史 |
| GET | `/api/scans/{id}` | 巡检明细 |
| POST | `/api/scans/{id}/diagnose` | AI 诊断 |
| GET | `/api/scans/{id}/report` | 生成每日运维简报（Markdown） |

## 常见问题

**MaaS 调不通？** 依次检查：区域是不是「西南-贵阳一」、有没有在控制台领取额度并开通预置服务、
模型 ID 是否与控制台「调用说明」完全一致、API 地址是否已删掉 `/chat/completions` 后缀。

**巡检很慢？** 死链扫描会逐个探测页面内链。调试时用 `?deep=false`，或在 `.env` 里调小
`MAX_LINKS_PER_PAGE`。

**`.env` 会不会被提交上去？** 不会，`.gitignore` 已排除。**但请务必不要手动删掉那条规则**——
API Key 泄露是安全事故。

## 后续路线

- [ ] 迁移到华为云 RDS，替换 SQLite
- [ ] 接入码道 CodeArts 的 Skills / MCP，实现"AI 生成修复补丁并提交"的完整闭环
- [ ] 告警推送（邮件 / 企业微信）
- [ ] 响应时间趋势图与多站点对比
- [ ] Docker 化并部署到华为云
