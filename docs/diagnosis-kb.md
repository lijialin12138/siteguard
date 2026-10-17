# diagnosis‑kb.md 网站诊断知识库
## 一、系统提示词 SYSTEM_PROMPT 说明
### 现状
系统提示词规定AI需要接收网站扫描数据，识别网站故障类型，输出结构化诊断结果。
D5 起输出新增结构化补丁列表 `patches`：每个真实问题类别各一段可直接落地的修复片段
（字段 `{category, title, language, code}`），旧字段 `patch`（单段字符串）保留做兜底兼容。
AI 输出需包含：故障类别、风险根因、处置动作、详细操作步骤、可落地的代码/配置修复片段（patches）。

> 补充：提示词中特别区分三类链接异常，含义不可混用：
> 1.broken_link_count：404/410真正死链；
> 2.link_server_error_count：5xx服务端错误，多为瞬时故障；
> 3.link_unverified_count：无法验证，不等于链接失效，需要人工复核。

## 二、故障知识库对照表（_MOCK_KNOWLEDGE，D5 升级为 patches 数组）

> D5 起 `patch` 升级为结构化 `patches` 数组（见 `docs/patch契约提案.md`）：
> 每个真实问题类别各给一段「可直接复制落地」的补丁，字段为 `{category, title, language, code}`。
> 下表 `_MOCK_KNOWLEDGE` 已按 scanner 的 11 个 category 覆盖，code 用 `{url}`/`{host}` 占位，运行时按报告真实样本地址替换。

| category | 含义 | 补丁形态(language) | 补丁 title | 补丁内容要点 |
| ---- | ---- | ---- | ---- | ---- |
| availability | 站点无响应 | bash | 排查并恢复站点可用性 | ping/curl 排查网络层→HTTP 层→`systemctl status nginx`→`journalctl` 看错误 |
| server_error | 5xx | bash | 捞取服务端错误日志，定位 5xx 根因 | `journalctl -u nginx` / `tail /var/log/nginx/error.log` / 应用日志 |
| client_error | 4xx（非死链） | nginx | 补全 301 重定向 / 修正访问权限 | 旧路径 `return 301` 到新地址 |
| redirect | 多余跳转 | nginx | 合并多余跳转，减少 301 链 | http+www 一次性 `return 301 https` |
| performance | 响应慢 | nginx | 开启 gzip 压缩与静态资源缓存 | `gzip on` + 静态资源 `expires 30d`/`Cache-Control immutable` |
| ssl | 证书临期/过期 | bash | 证书续期并配置自动续期 | `certbot --nginx` + `certbot renew --dry-run` + crontab 自动续期 |
| broken_link | 404/410 死链 | html | 修正失效超链接 | 把 `<a href>` 改到正确地址；或 Nginx 301（注入真实失效 URL） |
| link_server_error | 链接 5xx（可能瞬时） | bash | 对 5xx 链接复测，确认是否瞬时故障 | 浏览器 UA 复测 3 次；仅确为死链才改/加 301（**先复测勿急删**） |
| link_unverified | 无法验证（403/429/超时） | bash | 对无法验证的链接复核（切勿急于删除） | 浏览器 UA 复核；**只复核、绝不给删除命令**（403/429≠死链） |
| seo | 缺 title/description/H1 | html | 补全页面 <head> 基础 SEO 标签 | `<title>` + `<meta name=description>` + 唯一 H1 |
| accessibility | 图片缺 alt | html | 为图片补全 alt 描述 | `<img alt="描述">`，装饰图用 `alt=""` |

> 硬约束（与 `ai.py` SYSTEM_PROMPT 一致）：禁止编造不存在的文件路径/命令/域名；
> 无法确定确定性补丁时该类别不进 `patches`，只在 action 的 how 里说明还需补充信息。


## 三、提示词改进提案
### 建议1
现状：当前提示词虽然要求输出JSON，但没有对JSON内部字段增加校验规则，缺少字段数据类型约束。
问题：极端情况下AI可能返回字段值类型错误（例如数字写成字符串），代码解析JSON时会抛出异常。
改法：在提示词内增加字段类型定义，明确每个key对应的数据类型，要求AI严格遵守类型输出。

### 建议2
现状：当前提示词定义了故障类别，但对风险优先级的判定规则描述简短。
问题：AI在多故障同时出现时，优先级判断不稳定，无法稳定区分P1链接失效和SSL证书过期的先后顺序。
改法：在提示词补充优先级判定规则：P1失效链接 > SSL证书即将过期；当多个故障同时存在，优先输出最高风险项。

### 建议3
现状：当前提示词要求只输出JSON，但未对超长文本做限制，故障描述字段可能出现过长文本。
问题：JSON字符串过长时，前端展示会溢出，不利于界面渲染查看。
改法：增加约束，每个字段内文字控制在限定长度内，故障描述精简，保留核心信息。

### 建议4
现状：提示词文字区分了三类链接异常，但没有强制AI输出时显式标注链接类别。
问题：模型容易混淆broken_link、link_server_error、link_unverified，把无法验证链接误判为死链。
改法：补充约束，输出根因时明确标注链接所属类别，禁止笼统描述“存在失效链接”。
