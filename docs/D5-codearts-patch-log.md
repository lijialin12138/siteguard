# D5 · 码道 CodeArts 补丁生成留痕

> 角色 B（小甘）· `app/ai.py` 的 `patches` 升级
> 赛题硬性要求：补丁须由「码道 CodeArts」生成/校对并保留会话日志，作为「用了华为技术」的证据链。

## 状态说明（重要）

- 码道 CodeArts Agent **已安装**：`C:\Program Files\CodeArts Agent\codearts-agent.exe`
  （启动入口；文档早期写的 `D:\CodeArts Agent\` 路径有误，以此为准）。
- 除了手动粘贴，也可以用**官方 CLI** 把提示词直接送进已打开的码道窗口（已验证可用）：
  ```bash
  cd D:\xiangmucode\siteguard
  codearts-agent chat -r --mode agent "<提示词>"
  ```
  6 类提示词已全部这样驱动过，均返回 `exit=0`。注意：`chat` 只负责把提示词送进会话，
  **生成结果只在客户端窗口渲染**，不回写 stdout、也不落盘可读日志，所以「模型原文」必须以**会话截图**为证。
- 本文件给出**可直接粘贴进码道 CodeArts 的提示词**，在码道客户端里逐类跑一遍并**保留会话/日志截图**，
  即可补齐「用了华为技术」证据链。下面每一类的「CodeArts 提示词」粘贴后，应要求其产出与 `app/ai.py` 中 `_MOCK_KNOWLEDGE` 等价的补丁片段，
  用于交叉验证「AI 给出的补丁是否真能指导修复」。
- 完整的 6 类「提示词 + 基准补丁 + 截图清单」证据包见：`docs/codearts-evidence/README.md`。

## 操作步骤（小甘照做）

1. 双击 `C:\Program Files\CodeArts Agent\codearts-agent.exe` 打开码道（首次需登录华为云账号）。
2. 新建一个会话（建议命名「SiteGuard D5 补丁生成留痕」）。
3. **（已代跑）** 6 类提示词已通过 CLI 全部送入你打开的码道窗口，直接去窗口里逐个看结果即可；
   若窗口里没找到某类，再从下方「码道 CodeArts 提示词」里复制该条手动粘贴发送。
4. 每类生成后，**对整段问答截图**（要同时看到你发的提示词 + 它回的补丁 `code`）。
5. 截图存到 `docs/codearts-evidence/`（如 `ssl.png`、`broken_link.png` …），并在本文件末尾追加一行记录「类别 - 截图文件 - 日期」。
6. 6 类全部跑完，把 `docs/codearts-evidence/` 截图随 PR 一并提交/展示，即完成证据链。

## 已落地的 patches（MOCK 侧，已由 `scripts/diagnose_demo.py` 验证）

| category | language | title | 是否可执行 | 校验结果 |
| ---- | ---- | ---- | ---- | ---- |
| ssl | bash | 证书续期并配置自动续期 | ✅ certbot 续期 + 自动续期 | 通过 |
| broken_link | html | 修正失效超链接 | ✅ `<a>` 修正 + Nginx 301（已注入真实 URL） | 通过 |
| performance | nginx | 开启 gzip 压缩与静态资源缓存 | ✅ | 通过 |
| seo | html | 补全页面 `<head>` 基础 SEO 标签 | ✅ | 通过 |
| link_unverified | bash | 对无法验证的链接复核（切勿急于删除） | ✅ 仅复核命令、无删除 | 通过（硬约束） |
| link_server_error | bash | 对 5xx 链接复测，确认是否瞬时故障 | ✅ 先复测勿急删 | 通过 |
| availability / server_error / client_error / redirect / accessibility | bash/nginx/html | 对应排查/配置片段 | ✅ | 通过 |

## 码道 CodeArts 提示词（逐类粘贴，保留日志）

> 通用前缀：你是华为云运维助手，请针对「企业网站自动化维护」场景，给出**可直接复制执行**的修复片段，
> 禁止编造不存在的文件路径/命令/域名。输出格式：`{title, language, code}`。

### ssl（证书临期）
```
针对企业站点 HTTPS 证书即将到期，给出 Linux(Nginx) 下的证书续期与自动续期方案，
使用 certbot，包含安装、申请、dry-run 校验、crontab 自动续期。语言：bash。
```

### broken_link（404/410 死链）
```
页面存在一个已确认 404 的链接 https://demo.test/old.html，请给出修复方案：
1) HTML 里把 <a href> 改到正确地址；2) Nginx 301 跳转示例。语言：html。
```

### performance（响应慢）
```
站点首页响应 1820ms 偏慢，请给出 Nginx 性能优化片段：开启 gzip（限定类型）、
静态资源长缓存（expires/Cache-Control immutable）。语言：nginx。
```

### seo（缺 meta/title/H1）
```
页面缺少 <title>、<meta name=description>、唯一 <h1>，请给出完整 <head> 补全片段。语言：html。
```

### link_unverified（403/429/超时，无法验证）
```
某链接返回 403 无法自动验证（反爬/限流），浏览器可正常打开。请只给出「复核」命令，
严禁给出删除链接的操作。语言：bash。
```

### link_server_error（5xx 链接，可能瞬时）
```
某出站链接返回 5xx，请先给出浏览器 UA 复测 3 次的命令确认是否瞬时故障，
仅当确为死链才给替换/301 示例，不要上来就删。语言：bash。
```

## 验收勾选（D5 收尾自查，见 patch契约提案.md 八）

- [x] MOCK 模式返回合法 `patches`（无 Key 也能演示闭环）—— `diagnose_demo.py` 已验证
- [x] `patches[].code` 非空、`category` 在 11 类之内
- [x] `link_unverified` 仅为复核命令、无删除（控误报铁律）
- [x] 真实模型（MAAS_MODE=off，deepseek-v4-flash）跑一次，对比 patch 质量差异——已跑通，见 `docs/D5-真实模型脱敏样例.md`
- [x] 码道 CodeArts 会话留档——**6 类证据截图全部完成**（`docs/codearts-evidence/`：ssl / broken_link / performance / seo / link_unverified / link_server_error）；
      两条铁律类别（`link_unverified` / `link_server_error`）已逐行放大校验，均**只给复核/复测命令、无删除动作**。
      提示词 + 基准补丁 + 校对记录见 `docs/codearts-evidence/README.md`，提示词纯文本版 `docs/codearts-evidence/prompts.txt`。
- [ ] 复扫前后对比：应用补丁→复扫→对应 issue 消失/降级（队长端到端联调）
