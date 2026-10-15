# 官方 Cloud 与私有 Skills 同步

服务器准备完成后，再配置官方 Codex Cloud。本仓库的公开源码与个人运行仓库必须分开：前者便于学习与审查，后者保存部署参数和自己的可移植快照，必须是私有仓库。

## 1. 准备自己的私有运行仓库

在自己的 GitHub 新建 private 仓库，将公开源码放入一个独立 checkout（原部署目录名为 `codex-portable`，因此安装/启动文档沿用 `/workspace/codex-portable`）。不要直接往本公开仓库提交个人 snapshot。

配置并审阅以下非秘密值，保持 Mac 服务 checkout 与 Cloud 来源一致：

| 占位符/固定项 | 替换或核对位置 |
|---|---|
| `https://github.com/OWNER/PRIVATE-PORTABLE-REPO[.git]` | `scripts/cloud_refresh.py`、`cloud_doctor.py`、`install_skills_autosync.py` 的固定可信源 |
| `gateway.example.ts.net` | UI 两处 ORIGIN、通知页面、邮件正文、Go Subscriber、历史凭据 helper |
| `org.example.codex.portable-skills-sync` | LaunchAgent Label，可保留但不要与已有作业冲突 |
| `/workspace/codex-portable` | Cloud checkout 位置和安装/启动文本；换位置需全部对应修改 |
| `icloud-gateway` UID/GID 1000 | 服务器专用账户、peer credential 检查和两个交互式工具 |

在发布任何个人 snapshot 前，用 `gh api repos/OWNER/PRIVATE-PORTABLE-REPO --jq .private` 实际确认返回 `true`，检查 `git remote get-url origin` 是自己的 HTTPS 私有目的地。自动发布程序仍会重复核对；失败就停止。

用 Python 3.11+ 导出。初次运行建议调用与后台同步相同的排除策略，防止家目录的旧网关 Skill 覆盖仓库版本：

```python
from pathlib import Path
import sys
sys.path.insert(0, 'scripts')
import portable_sync
bundle = portable_sync.export(Path.home(), Path('work/exports').resolve(),
    exclude_skills={'icloud-codex-gateway'})
print(bundle)
```

只在已核对 private 的运行 checkout 中，将这份 bundle 复制到首次创建的 `snapshot/`。如果 snapshot 已存在，先校验/备份，不直接覆盖。公开源码的 `.gitignore` 故意排除了 snapshot；在私有运行仓库中审阅并移除这一条后，再提交自己的 snapshot。必须阅读 `manifest.json` 中的遗漏项，运行哈希验证、秘密扫描及人工检查。公开前缀不是自动脱敏器，不会删除正文中的个人隐私。

```bash
python3 scripts/portable_sync.py verify --bundle snapshot
gitleaks dir snapshot --redact --no-banner
```

导出内容：用户管理的 Skills、AGENTS、允许的模型偏好、可移植 MCP 定义。不会复制登录、会话历史、SSH/Apple/VPN 密钥、插件缓存、node_modules、数据库。`config.portable.toml` 供目标端审阅，不能自动覆盖 active `config.toml`。远程 MCP 的密钥按环境变量名引用，目标环境自行供给；平台/网络依赖需重新安装。

如果源机没有 `.codex/AGENTS.md`，请在自己的私有快照流程中明确提供要使用的主人指引，或相应调整启动文本，不能把不存在的文件当已加载。

## 2. Mac 后台同步

运行服务使用独立的私有 checkout，建议放 `~/Library/Application Support/CodexPortableSync/repository`，与人工编辑目录分开，避免后台作业受 Documents 权限或未提交修改影响。相应的 `state/` 和可信 `gitleaks` 可执行文件也放在自己的 Application Support 目录。保留实际使用的 Python 和 gh 绝对路径。

从私有运行 checkout 生成 LaunchAgent 预览：

```bash
python3 scripts/install_skills_autosync.py \
  --service-repo '/absolute/private/service/checkout' \
  --runtime '/absolute/private/state' \
  --scanner '/absolute/path/to/gitleaks' --gh '/absolute/path/to/gh'
```

检查 plist 中源目录、目的地和日志位置，再对同样参数添加 `--apply`。不要把本文中的 `/absolute/...` 当真实路径。已有不同 plist 不会直接覆盖；迁移需要先保留、审查并停止原注册作业。

该作业每60秒及源目录变更时检查，流程为：导出 → 哈希校验 → 确认目的地仍 private → 扫描 → 仅提交 snapshot → 推送。上游删除不传播；新遗漏、分支分叉、本地修改、扫描异常都停止。推送失败只重试记录过的同一提交。`status.json=ok` 才说明最近检查成功；旧提交存在不证明后台仍运行。

验收要改一个无敏感信息的测试 Skill，让后台自己发布，再在普通 Cloud 请求中确认新 SHA；不要替后台手动 push 后声称自动链路成功。实际运行中的聊天不保证即时获得新的上下文，刷新发生在任务开始。

## 3. 新建官方 Cloud 环境

按 [Cloud environments 官方流程](https://learn.chatgpt.com/docs/environments/cloud-environments)创建/编辑环境，使用自己的 private 运行仓库。Cloud 的 prepared filesystem、保存的设置、当前 executor 和普通新任务是不同对象，逐项核对。

1. 在官方 VPN 控件配置自己的 Tailscale，使用适合重复创建任务的 enrollment 配置；控制访问范围并记录密钥到期时间。复用/临时节点选项不等于永久有效，也不能证明某个旧 executor 已收到最新 VPN 配置。
2. 允许实际网关 `.ts.net` 域名及构建必需的目的地，保留平台代理、CA 和网络策略。
3. 配置 `ICLOUD_GATEWAY_URL=https://你的实际域名/`。
4. 将完整 `Basic …` 作为 **Network secret** `ICLOUD_GATEWAY_AUTHORIZATION`，严格限定实际网关 hostname。秘密值由本人在受信任终端取出，直接录入官方秘密控件；不经过聊天、Git、日志。占位符原样作为 Authorization 头传递，不能再 Base64 编码。可选的直接用户/密码环境变量仅适用于平台明确支持的安全供给方式。
5. 在 `/workspace/codex-portable` 准备可信 checkout 和已验证 snapshot。首次克隆通过平台支持的 GitHub 认证完成，不能把 PAT 拼进 clone URL。

环境需要 Python 3.11+、XeLaTeX 和 Noto CJK 字体。`environment/install.sh` **检查**这些依赖，不安装系统 TeX；在准备阶段按实际基础镜像安装。例如 Debian/Ubuntu 且有包管理权限时，相关包为 `texlive-xetex`、`texlive-lang-chinese`、`fonts-noto-cjk`。原部署已验证 Cloud Linux 能用它们编译中文，不能将 Skill 文本当作已安装依赖。

首次准备：

```bash
cd /workspace/codex-portable
python3 scripts/cloud_bootstrap.py --cloud-root /workspace
bash environment/install.sh
```

bootstrap 校验 snapshot、物化 Skills、写根 AGENTS 的受管理块与元数据索引。原运行时 `/workspace/.agents` 是平台只读目录，因此强制 guidance-index；不改挂载或 chmod。它让普通任务按描述读取真实 SKILL.md，不等于原生 Skill selector 注册。

安装字段采用稳定入口：

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /workspace/codex-portable
python3 scripts/cloud_refresh.py
bash environment/install.sh
```

启动字段使用 `environment/start.md` 完整文本。安装脚本校验固定 Go 归档、运行测试和预检，保留旧二进制；普通目录问题只刷新源码/Skills，不重复跑全部测试。

## 4. 发布与普通新聊天验收

准备完成后检查：

```bash
python3 scripts/cloud_doctor.py --publication --dependencies
python3 scripts/cloud_doctor.py --gateway
```

第一项不是联网证明；第二项只是认证读取，不代表写回。基线不能包含 `work/icloud-active`、已下载用户文件、聊天绑定或未经审查的临时资料。该预检不是全盘隐私扫描，仍需审阅准备目录。

所有命令结束且环境空闲后，在官方 UI 审阅、保存、发布一次。等实际“环境已发布”，再使用该环境创建普通新聊天，第一句直接问“你好，有什么文件？”。预期自动运行 refresh、gateway check、activate，返回网页选中目录的远程条目且不批量下载。再核对实际 HEAD 与依赖。

网页选中目录只影响尚未绑定的聊天。旧聊天保留原目录与未上传编辑；不同聊天之间只共享已写回 iCloud 的远程结果。

## 5. 日常处理与维护

网关 Skill 里有真实 CLI 用法。默认工作流为 activate → list → fetch 所需文件 → 自动登记任务文件并启动保存队列 → Linux 工具处理 → 校验生成文件并标记 ready → 等待哈希验证完成。普通编辑、新建和生成请求就包含对应文件的写回，不需要另说“保存”；明确不保存的要求优先。人工 `plan` / `push` 保留用于审阅和恢复。下载和写入大小限制见 README。明确要求全盘搜索时可扩大只读范围，不把默认目录误当永久权限上限。新增协议的部署顺序及队列边界见[自动保存说明](07-automatic-save.md)。

不要把已发布 setup 聊天当长期维护终端。后续工具/安装字段/VPN/凭据变更用同一保存环境的 Edit 流程；Skills 内容更新通过可信 Git refresh 获取。完成后再发布并验收普通任务。旧失败环境和文件保留；新环境通过不意味着旧实例恢复。

更细的恢复、版本备份和发布边界在 [environment/maintenance.md](../environment/maintenance.md)。
