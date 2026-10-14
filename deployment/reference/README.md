# 原始部署脚本参考

这里保存初次建设过程中实际使用过的部署脚本，已脱敏。它们展示网页上传、systemd 配置、浏览器身份接入、提醒部署、恢复入口和隔离读写验收的完整实现。当前运行版本在仓库根部 `gateway-runtime/`、`gateway-ui/`，最终服务配置在 `deployment/systemd/`。

这些文件是按阶段执行的历史工具，**不能整目录顺序执行，也不能拿旧版覆盖当前服务**。例如 `install-health.py` 安装的早期每日两次检查随后被通知部署替换为每15分钟；早期 shell reconnect 被最终 Python reconnect 替换；`portable_sync.py` 是早期版本，日常同步使用根目录 `scripts/portable_sync.py`。通知安装器内的二进制摘要属于当时构建，重新编译后必须核对自己的可信摘要。

从仓库根目录运行。远程包装器使用 Workbench，需预先在自己的终端配置，设置 `ECS_INSTANCE_ID`；含 profile 参数的脚本还需 `WORKBENCH_PROFILE`。没有 `REFERENCE_DEPLOY_ALLOWED=1` 时拒绝执行。创建 `work/deployment-evidence/` 后才运行需要记录证据的工具。所有实例、域名都必须替换为自己的配置；不要把私钥或 token 放进参数。公开时新增的参数读取/防误执行门禁经过语法检查，未重新对生产服务器运行整套历史安装器。

`deploy-ui.py gateway-ui` 包含 HTML/CSP 部署和旧版备份逻辑；页面脚本或样式发生变化时必须先更新对应 CSP 摘要。`deploy-browser-login.py` 默认只做预检，`--apply` 才改变鉴权路径。其他脚本可能直接安装、重启或替换服务，使用前逐行审查。

`isolated-test.py` 和 `webdav-isolated-test.py` 会实际创建 UUID 隔离测试文件，并把该文件移动到 iCloud 废纸篓。仅在明确授权这次写入和精确文件清理后运行。Trash 语义仅对本项目锁定并核对过的 iCloud backend 有证据，不能推广到任意 WebDAV 后端。不要递归清理父目录。
