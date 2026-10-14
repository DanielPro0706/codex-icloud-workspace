# 参考仓库与链接

本清单来自实际源码依赖、构建记录和原交接文档。核对日期 2026-10-14。区分采用、改编、运行依赖与曾评估但未采用，不将调研对象写成部署组件。

## 实际采用或改编

| 项目 / 链接 | 本项目用途 | 版本与归属 |
|---|---|---|
| [rclone/rclone](https://github.com/rclone/rclone) | iCloud backend、文件传输和 WebDAV 服务 | 基线 v1.75.2，MIT；未将整份源码混入本仓库 |
| [xz-dev 提交的 rclone PR #9399](https://github.com/rclone/rclone/pull/9399) | 中国大陆 region/endpoints 支持的直接代码来源 | 参考 head `f56bd5bcc98b37cf91edce99ad95e8ec07e4faab`；另有本地 OAuth redirect 修正及地区测试；截至核对仍 Open，非官方合并发布 |
| [SherClockHolmes/webpush-go](https://github.com/SherClockHolmes/webpush-go) | helper 调用 VAPID 密钥生成和 Web Push 发送 | v1.4.0，MIT，go.mod/go.sum 锁定 |
| [golang-jwt/jwt](https://github.com/golang-jwt/jwt) | Web Push 间接依赖 | v5.2.1，MIT |
| [golang/crypto](https://github.com/golang/crypto) | Web Push 间接密码学依赖 | v0.31.0，BSD-style |

rclone 原许可证在 [licenses/rclone-MIT.txt](../licenses/rclone-MIT.txt)，其它归属见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。补丁是对上游工作的改编，不宣称中国区能力全部为本项目原创。

## 使用的工具与平台

- [tailscale/tailscale](https://github.com/tailscale/tailscale)：私网连通、Serve TLS 和受控身份传递；原部署版本 1.104.1。属于运行依赖，未复制其实现代码。
- [gitleaks/gitleaks](https://github.com/gitleaks/gitleaks)：snapshot 发布前的秘密扫描；扫描通过不等于没有个人隐私。
- [golang/go](https://github.com/golang/go)：构建工具；rclone 原构建 Go 1.26.9，Cloud helper 安装脚本固定 Go 1.23.12。
- [cli/cli](https://github.com/cli/cli)：确认 GitHub private 状态和仓库操作。
- [@tencent-qqmail/agently-cli](https://www.npmjs.com/package/@tencent-qqmail/agently-cli)：邮件 CLI；原 Linux 平台包 v1.0.18。未确认可引用的官方 GitHub 源码仓库，所以给 npm 包链接，不编造源码地址。
- 阿里云 Workbench CLI：原始远程部署脚本的管理通道。它不是 iCloud 数据面依赖，也不需把云账户密钥给 Cloud 文件任务。
- 官方 Codex Cloud：Linux 执行和环境准备/发布平台。未复制 Codex 的闭源云执行服务，也未自行实现替代聊天后端。

## 以前调研过、但没有部署/集成的项目

- [tiann/hapi](https://github.com/tiann/hapi)：远程控制编码代理的另一种方案。
- [slopus/happy](https://github.com/slopus/happy)：移动端/远程代理交互方案。
- [0xcaff/codex-web](https://github.com/0xcaff/codex-web)：运行在自有机器上的 Codex Desktop 浏览器前端。

它们在原交接中作为不同架构的候选记录。本仓库没有采用这些项目的代码，也没有把它们部署成所谓“无服务器版”；当前目标仍是官方 Cloud Linux 经 ECS 访问 iCloud。

## 官方文档与故障线索

- [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments)：准备文件系统、VPN/秘密配置、发布与复用环境。
- [rclone iCloud backend](https://rclone.org/iclouddrive/)：认证、授权期限和网页访问条件。
- [rclone config reconnect](https://rclone.org/commands/rclone_config_reconnect/)：交互式重新认证命令。
- [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)：私网服务和反向代理。
- [openai/codex #51028](https://github.com/openai/codex/issues/51028)：executor handshake 与 runtime 状态不一致的相关报告；不能证明本例根因。
- [openai/codex #53239](https://github.com/openai/codex/issues/53239)：环境设置保存与发布失败的相关报告。以 Issue 当前正文为准，旧交接中的概括不是通用诊断。

上述 Issue 仅辅助排查，没有从中得出“应删除环境”“应轮换密钥”或“已确认平台根因”的结论。
