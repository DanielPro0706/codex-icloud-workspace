# Codex iCloud Workspace

通过私有 ECS 网关，把 iCloud Drive 用作官方 Codex Cloud 的文件工作区。手机选择目录，Cloud 按需下载、处理并经授权写回；Mac、iPhone、iPad 继续使用原生 iCloud 同步。服务器负责 Apple 授权健康检查与网页/邮件提醒，Mac 无需充当文件中转服务器。

**本仓库只发布已经走通过的服务器版。** 没有无服务器实现，也没有以自建聊天网页替代官方 Cloud。这里公开实现、网页部署代码、构建补丁、测试、从零搭建流程及实际踩坑记录；个人数据、凭据、私有 Skills 快照和原私有仓库历史不公开。

这是一个经过单用户部署验证的参考实现，仍含需要替换的部署参数。公开模板已做代码测试和脱敏检查，尚未在第二套全新账户/服务器上重新走完部署。请按文档逐阶段验收，不要把 clone 成功当作已连通 iCloud。

## 入口

- [从零搭建服务器和网页](docs/01-server-setup.md)
- [配置、发布和维护 Codex Cloud](docs/02-cloud-and-skills.md)
- [构建过程、踩坑与排障](docs/03-build-history-and-troubleshooting.md)
- [五项能力及验收边界](docs/04-verification.md)
- [参考仓库、PR、Issue 与官方文档](docs/05-sources.md)
- [公开代码范围与隐私边界](docs/06-publication-scope.md)

## 工作链路

```text
手机 / Mac 浏览器 ── Tailscale HTTPS ── 网页与目录选择 API
                                           │
官方 Codex Cloud ── VPN + 独立 WebDAV 密钥 ── ECS ── rclone ── iCloud Drive
        │                                  │                    │
        ├─ 按需取文件 → Linux 工具处理 → 授权写回                  └─ 原生 Apple 设备
        │                                  └─ 健康检查 → Web Push / 邮件
Mac Skills ── 扫描 + 私有 Git ── Cloud 启动刷新
```

网页免密码只对受信任的本人 Tailscale 身份开放读取、目录选择和通知操作。文件写入始终要求独立 WebDAV 密钥。文件端口不公开到互联网，不启用 Funnel。

## 代码目录

| 目录 | 内容 |
|---|---|
| `gateway-ui/` | 文件网页、通知页、Service Worker、清单、图标、选择 API、Unix socket 鉴权代理、Go Web Push helper |
| `gateway-runtime/` | Apple 健康检查、固定邮件通知、交互式重授权、手机公钥登记 |
| `.agents/skills/icloud-codex-gateway/` | 网关 Skill、WebDAV 客户端、按需工作区、写回计划、备份与冲突检查 |
| `scripts/` | 可移植快照、Mac 后台同步、安全快进、Cloud bootstrap/refresh/doctor |
| `environment/` | 已验证的 Cloud 安装、启动和维护入口 |
| `deployment/scripts/` | ECS 账户准备、rclone 中国区构建、私网 Tailscale 与 WebDAV 准备 |
| `deployment/systemd/` | 最终服务与健康检查定时器 |
| `deployment/reference/` | 原始阶段性部署代码，包括网页部署；保留历史用途说明和执行门禁 |
| `deployment/patches/` | rclone 中国区补丁及地区回归测试 |
| `tests/` | 合成数据测试，不要求 Apple 密码或真实云盘 |

## 本地验证

Python 3.11+；Go helper 声明 Go 1.23。完整同步测试还需要 `gitleaks`：

```bash
python3 -m unittest discover -s tests
# gitleaks 不在 PATH 时，给出本机实际路径，避免静默跳过8项同步测试：
GITLEAKS_BIN=/path/to/gitleaks python3 -m unittest discover -s tests
cd gateway-ui/webpush-helper
go mod verify
go test -mod=readonly ./...
```

公开准备时 67 项 Python 测试全部通过；Go 测试通过。自动测试使用合成数据，不证明真实 Apple 授权、通知送达或跨设备同步；这些证据单独列在[验收记录](docs/04-verification.md)。

当前限制：非 POSIX 实时挂载；单文件上传上限 32 MiB；每次 fetch 默认上限 1,000 文件/256 MiB；写前 hash 检查不构成分布式原子锁；Cloud Linux 不运行 Xcode。Skills 通过指引和索引发现，不宣称注册进平台原生选择器。

## 许可证与来源

原创代码采用 [MIT](LICENSE)。rclone 衍生补丁和外部依赖保留各自来源与许可证，见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。

主要依赖：[rclone](https://github.com/rclone/rclone)、[中国区 PR #9399](https://github.com/rclone/rclone/pull/9399)、[Tailscale](https://github.com/tailscale/tailscale)、[webpush-go](https://github.com/SherClockHolmes/webpush-go)。完整参考及曾评估但未采用的项目见[来源清单](docs/05-sources.md)。
