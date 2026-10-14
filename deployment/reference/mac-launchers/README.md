# 原始 macOS 交互入口（脱敏参考）

这些 .command 文件是原部署中给本人使用的 SSH 入口。`ICLOUD_SSH_HOST` 必须设为自己的可信服务器，`ssh-known-hosts` 由本人先通过可信通道核对 SSH host key 后建立；本仓库不携带服务器指纹或 SSH 密钥。密钥默认路径可改为自己的路径，不能关闭 StrictHostKeyChecking。

标为官方 rclone 的早期认证入口不适用于已选用中国区候选版的当前配置。日常恢复优先使用已安装的 `icloud-reconnect`。原部署的手机公钥 helper 位于用户目录；主搭建文档安装到 `/usr/local/bin` 时需对应修改该 launcher。`icloud-browser-credentials` 是早期本人查看密码的入口，当前浏览器身份方案不需要它；不要假定该 helper 已由主文档安装。

仅本人在自己的终端执行可能显示凭据的入口，不录屏、不重定向日志，也不让 AI 读取其输出。
