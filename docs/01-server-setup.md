# 从零搭建：服务器、网页和通知

本文把原交接记录、实际部署脚本和最终服务配置合并成可复核的顺序。命令中的域名和仓库是占位符；不要原样拿去连接他人的服务。初始部署在 AliLinux 3、Linux amd64、systemd、`icloud-gateway` 用户 UID/GID 1000 上验证。其他发行版、架构或 UID 需要单独适配验证。

## 1. 准备范围

准备一台自己有管理权限、能访问 Apple/GitHub/Tailscale 的 Linux 服务器，以及 iCloud 账户、可接收 Apple 验证的设备、Tailscale 账户。服务器与 Mac/手机使用同一受控 tailnet。保留已有代理、VPN 和其他服务，不开放公网文件端口。

需要 Python（Cloud/同步代码 3.11+）、Git、curl、systemd；构建 rclone 使用原验证的 Go 1.26.9，Web Push helper 使用 Go 1.23+。服务器运行的网关 Python 代码保留了旧系统兼容写法。不要因为某个包缺失而直接替换系统 Python。

下载源码，在独立目录操作：

```bash
git clone https://github.com/DanielPro0706/codex-icloud-workspace.git
cd codex-icloud-workspace
```

先检查系统中 `icloud-gateway` 账户和 UID 1000 是否冲突。`browser_proxy.py` 的 Linux peer-credential 检查、`reconnect.py` 和 `register_phone_key.py` 当前按 UID 1000 固定；不要为了适配而修改已有用户 UID。推荐使用与记录一致的干净服务器。若不同，先做明确的代码适配和针对性测试，不可只改一处。

以下 `sudo` 操作由服务器管理员执行；账户内 Apple 登录由本人操作。

```bash
sudo bash deployment/scripts/prepare-ecs.sh
id icloud-gateway
```

此脚本创建专用目录，下载并校验官方 rclone v1.75.2，同时保留官方程序。它尚未建立 Apple 登录或文件服务。

## 2. 中国区 rclone：锁定补丁并自行构建

原部署中官方 v1.75.2 遇到 `HTTP 302 / domainToUse / iCloud.com.cn`。最终使用 PR #9399 加本地 OAuth 地区重定向修正；并非官方发布版。截至 2026-10-14 核对，该 PR 仍未合并。来源、版本和许可证见[来源清单](05-sources.md)。

在具备 Go 1.26.9 的构建机：

```bash
bash deployment/scripts/build-rclone-cn.sh /path/to/new-rclone-source
```

脚本核对 v1.75.2 基线和现有 diff，应用仓库补丁，运行 `go test ./backend/iclouddrive/... -count=1`，再交叉编译 Linux amd64。它不会覆盖另一份未知修改的源码。原验证候选版标识：`v1.75.2-cn9399-local.1`。原二进制 SHA-256 为 `95962424f4645019390651f72fd18affc72feeb3763529797cf0cf65b3527266`；该值记录旧构建产物，不保证不同路径/工具链重编译仍逐字节相同。

用自己的 SSH/Workbench 传输构建产物并核对传输前后 SHA，然后安装为：

```text
/home/icloud-gateway/.local/bin/rclone-cn9399
```

归属 `icloud-gateway:icloud-gateway`，权限 `0700`。不要覆盖官方 `rclone`。本流程仅对已测试的中国区分支给出证据，没有声称所有地区账户都已测试。

## 3. 本人完成 Apple 授权

在自己的交互式 SSH 终端切换专用用户：

```bash
sudo -iu icloud-gateway
umask 077
~/.local/bin/rclone-cn9399 --config ~/.config/rclone/rclone-cn.conf config
```

创建 `Codex` remote，backend 选择 `iclouddrive`，中国大陆账户选择补丁提供的 `region=chinamainland`；输入自己的 Apple 账户信息，完成 2FA/设备批准。密码、验证码、session 只留在本人终端和受保护的服务器配置中。不要发到聊天或提交 Git。

[rclone 官方说明](https://rclone.org/iclouddrive/)要求普通 Apple 密码及双重认证，而非应用专用密码；授权会失效，不能承诺永久免登录。遇到 412 网页数据访问问题，检查账户网页访问设置并完成受信任设备批准；不要把关闭高级数据保护作为通用步骤。

```bash
chmod 600 ~/.config/rclone/rclone-cn.conf
~/.local/bin/rclone-cn9399 --config ~/.config/rclone/rclone-cn.conf lsf Codex: --max-depth 1 --dirs-only
```

这一步必须实际读出目录。出现错误就停在认证层，不先部署网页来掩盖它。

## 4. 私网网络与 WebDAV

管理员执行：

```bash
sudo bash deployment/scripts/prepare-tailscale.sh
sudo bash deployment/scripts/prepare-gateway.sh
```

Tailscale 1.104.1 使用独立的 userspace daemon、状态目录和 socket，不改系统现有 VPN。用该实例的 CLI 在本人终端登录：

```bash
sudo -u icloud-gateway /opt/icloud-gateway/tailscale/1.104.1/tailscale \
  --socket=/run/icloud-gateway-tailscale/tailscaled.sock up --hostname=icloud-gateway --accept-dns=false --accept-routes=false --netfilter-mode=off
```

按 CLI 返回的本人授权流程完成登录，并在 Tailscale 管理面启用必要的 HTTPS/MagicDNS。查看本节点实际 `.ts.net` 名称，用它替换公开源码中的 `gateway.example.ts.net`。必须保持 `browser_proxy.py` 与 `selection_api.py` 的 ORIGIN 完全一致，Web Push Subscriber 和通知页面链接也一并替换。

网关只监听 `127.0.0.1:18765`，使用随机生成的独立用户名/密码文件，权限 `0600`。Apple 密码不是 WebDAV 密码。ACL 只给所需节点访问网关 HTTPS；Cloud 节点没有手机的 owner 身份，不授予 SSH。手机号/邮箱不是授权依据。

## 5. 部署网页与选择 API

网页源码全部在 `gateway-ui/`。这是 rclone 渲染目录的 Go HTML 模板，不能只把 `index.html` 丢到公共静态托管站点：目录数据、私网身份和 API 都由服务器提供。

先构建 helper（在构建机执行；上传前后自行比对 SHA）：

```bash
cd gateway-ui/webpush-helper
go mod verify
go test -mod=readonly ./...
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -mod=readonly -o ../../work/webpush-helper-linux-amd64 .
cd ../..
```

服务器安装下列映射；有旧文件时先把它们复制到仅管理员可读的唯一备份目录，再替换：

| 源 | 服务器目的地 |
|---|---|
| `gateway-ui/*` 的 Python/HTML/JSON/SVG/JS/webmanifest 文件 | `/opt/icloud-gateway/ui/` |
| 编译的 `webpush-helper-linux-amd64` | `/opt/icloud-gateway/ui/webpush-helper`，0755 |
| `gateway-runtime/health.py` | `/usr/local/libexec/icloud-gateway-health.py` |
| `gateway-runtime/mail_notify.py` | `/usr/local/libexec/icloud_gateway_mail.py` |
| `gateway-runtime/reconnect.py` | `/usr/local/bin/icloud-reconnect`，0755 |
| `gateway-runtime/register_phone_key.py` | `/usr/local/bin/icloud-register-phone-key`，0755 |
| `deployment/systemd/*` | `/etc/systemd/system/` |

普通 UI 源文件权限 0644，目录 0755。最终 WebDAV unit 已带模板和 CSP 响应头；修改内联脚本/样式后，重新计算对应 SHA-256 Base64 并同步 `response-headers.json`、`notification-headers.json` 及 unit。不要为省事关闭 CSP。可参考已使用过的[网页部署代码](../deployment/reference/deploy-ui.py)，它包含备份、替换和 service 校验逻辑。

首次建立 picker 的状态目录时，先将其 unit 中 `Environment=ICLOUD_BROWSER_IDENTITY=1` 暂时设为 `0`，再 `daemon-reload`、启动 picker。确认 `/var/lib/icloud-gateway-picker` 存在后，建立 `browser-owner.json`：

```json
{"login":"YOUR_EXACT_TAILSCALE_LOGIN"}
```

这里填本人 Tailscale `status --json` 对应 Self.UserID 的 LoginName，不是任意网页登录字符串。文件权限 0600、owner 与状态目录一致、group 为 icloud-gateway。只在自己的服务器上核对，不把实际文件公开。最终把 identity 设回 `1`，校验并重启。Unix socket 应为 `0660`、group `icloud-gateway`：

```bash
sudo systemd-analyze verify /etc/systemd/system/icloud-gateway-{webdav,picker,health}.service /etc/systemd/system/icloud-gateway-health.timer
sudo systemctl daemon-reload
sudo systemctl enable --now icloud-gateway-picker.service
sudo systemctl restart icloud-gateway-picker.service icloud-gateway-webdav.service
sudo stat /run/icloud-gateway-picker/browser.sock
sudo -u icloud-gateway /opt/icloud-gateway/tailscale/1.104.1/tailscale \
  --socket=/run/icloud-gateway-tailscale/tailscaled.sock serve --bg --https=443 unix:/run/icloud-gateway-picker/browser.sock
```

历史上曾给选择 API 单独设置 `/__codex_gateway_v1__` Serve 路由。迁移到最终 Unix 代理时只关闭这条旧路由，不能让它绕过身份策略。新部署无需创建它。保留其他已有 Serve 配置。[Serve 官方说明](https://tailscale.com/docs/features/tailscale-serve)解释了 tailnet 访问边界；不要改用 Funnel。

验收：本人手机打开实际私网域名，看到目录并选择一个文件夹；刷新后选择仍在；其他身份不能获得本人读取权限；Cloud 带独立 Basic 认证执行 PROPFIND 应通过。浏览器打开成功不能代替写权限测试。

## 6. 健康检查、邮件和手机通知

健康检查每15分钟一次，附最多60秒随机延迟；正常保持安静，异常/恢复按事件去重。它不是即时离线检测。一次 Apple 临时超时不会被直接标为授权过期。

Web Push 的 VAPID 私钥和订阅只存服务器状态目录。iPhone 在 Safari 添加通知页面到主屏幕，从主屏幕打开后点启用；测试必须由本人实际确认手机通知，HTTP 2xx 只表示推送服务接受。

邮件使用原方案的 `@tencent-qqmail/agently-cli`（原部署平台包 v1.0.18）。在专用用户下安装/授权，使可执行文件位于 `/home/icloud-gateway/.local/bin/agently-cli`，并用 `agently-cli +me` 验证。账号授权在本人终端完成。代码不会附加附件或发送任意正文。

公开版默认不发邮件。本人决定启用后，在 health 服务专用的受保护 EnvironmentFile 中配置：

```text
ICLOUD_ALERT_EMAIL=your-own-recipient@example.com
ICLOUD_ALERT_EMAIL_ENABLED=1
```

将该文件作为 health unit 的 `EnvironmentFile=`，只由管理员/服务按需读取。未配置时返回 `not_configured`；`accepted` 仍不等于终端送达。只有已明确选择接收固定提醒的邮箱才能启用自动确认流程。

先确保 `/home/icloud-gateway/.local/share/agently-cli` 和 health 状态目录存在且归专用用户，再启用定时器：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now icloud-gateway-health.timer
sudo systemctl start icloud-gateway-health.service
sudo systemctl is-active icloud-gateway-webdav.service icloud-gateway-picker.service icloud-gateway-tailscale.service icloud-gateway-health.timer
```

首次检查可能产生通知，应在本人启用提醒后执行。查看脱敏 `health.json`；不要粘贴 rclone 配置或原始错误响应。

## 7. 手机 SSH 恢复

手机生成 ED25519 密钥，私钥不离开手机。在已有可信的本人 SSH 会话运行 `icloud-register-phone-key`，粘贴公钥、核对指纹、输入 REGISTER。工具保留 authorized_keys 的旧版备份。

userspace Tailscale 下私网 SSH 必须显式转发到服务器 SSH；按原部署使用 Serve TCP 22→127.0.0.1:22，并用 ACL 限定本人设备。先核对当前 Serve 配置、SSH host key 和目标监听，避免覆盖其他 TCP 服务。不要为手机 SSH 开公网安全组。原部署手机使用 Termius，其他客户端未经本项目验收。

管理员用 `visudo -f /etc/sudoers.d/icloud-gateway-reconnect` 添加且校验最小权限：

```text
icloud-gateway ALL=(root) NOPASSWD: /usr/bin/systemctl restart icloud-gateway-webdav.service
```

本人手机随后运行 `icloud-reconnect`。它先备份认证文件，进行交互式 Apple reconnect，根目录读成功才重启 WebDAV，再立即检查健康。失败保留备份，不声称原登录状态必然未变。`icloud-status` 和凭据展示/轮换 helper 的原始安装实现见 `deployment/reference/`；先审查再安装。轮换还需 picker 精确重启权限，并同步官方 Cloud 的 Network secret。

最后按[完整验收步骤](04-verification.md)检查读取、隔离写入、通知、恢复、普通新聊天、自然同步；不要清理已有用户目录。
