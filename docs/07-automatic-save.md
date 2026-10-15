# 分块续传、自动保存与已有部署升级

本页说明已经在原服务器架构验证的增量能力，不引入 SSH 远程编译或无服务器方案。部署到另一套账户/服务器仍需单独验收。

## 使用行为

绑定 iCloud 目录后，普通编辑、新建或生成请求就包含对应任务文件的自动写回。无需额外说“保存”“写回”。代理负责获取原文件、登记精确文件范围、启动监听、验证生成文件并等待写回确认。只读任务不产生新修改；明确“不要保存”“只预览”“先别改”时，先暂停相关队列，再遵守限定范围。

源文件在五秒内不再变化后生成不可变快照并入队。上传期间再次编辑不会修改正在发送的快照，后一版本留待下一轮。生成的 PDF、图片和压缩包必须先完成相应校验，再标记当前哈希 ready；后续改动会使该标记失效。不是用户再点一次“保存”，而是代理承担生成质量检查。

以下是代理使用的命令；`<controller>` 是 `workspace.py activate` 或 `open` 返回的控制目录，示例文件名必须替换为当前任务实际路径：

```bash
python3 .agents/skills/icloud-codex-gateway/scripts/autosave.py enable <controller> --authorized --path notes.tex --generated notes.pdf
# 完成编译及适当校验后：
python3 .agents/skills/icloud-codex-gateway/scripts/autosave.py ready <controller> notes.pdf
python3 .agents/skills/icloud-codex-gateway/scripts/autosave.py wait <controller> --timeout 600
python3 .agents/skills/icloud-codex-gateway/scripts/autosave.py status <controller>
```

`pause` 停止后续文件传输，已在途的文件可能完成；`start` 只恢复已启用队列；`enable` 可重新启用已暂停的范围。故障处理后 `retry <controller> <path>` 重新核对原先的预期版本，不强行覆盖冲突。单独运行 `workspace.py push` 仍可用于人工审阅后的写回，必须避免与队列同时写同一控制目录。

## 上传协议

协议位于既有私网服务的 `/__codex_gateway_v1__/uploads`，始终需要独立 Basic 认证，浏览器 owner 身份不能代替它。

| 请求 | 用途 |
|---|---|
| `GET /uploads` | 获取协议、分块大小及单文件上限 |
| `POST /uploads` | 固定上传 UUID、相对路径、大小、完整 SHA-256、预期旧版 SHA |
| `PUT /uploads/<uuid>/chunks/<index>` | 上传最多 32 KiB 的不可变分块；同一分块重传必须完全一致 |
| `POST /uploads/<uuid>/commit` | 校验完整文件、核对并备份远端旧版，开始写入与回读校验 |
| `GET /uploads/<uuid>` | 查询实际进度；queued/committing 不等于成功 |

客户端保持原代理、TLS、VPN 和认证路径。普通手动上传超过 64 KiB 时使用分块协议；自动队列的小文件也使用该协议。最多四个分块并发，任一分块失败时不开始提交；重试复用相同意图的持久分块。

Cloud 保存待发快照与任务记录，ECS 保存收到的分块和备份。回执丢失后，先核对远端完整哈希：已一致则采用结果，不重复 PUT；零字节、前缀或其他内容均停下核查。

## 已有部署升级顺序

1. 保留当前代码、服务配置及状态目录；不要复制公开占位符覆盖实际域名、通知设置或私有仓库配置。
2. 在暂存目录准备 `gateway-ui/uploads.py`、`selection_api.py`、`browser_proxy.py`。后两者的 `ORIGIN` 保留部署者自己的同一私网域名；先用服务器实际 Python 做语法检查。服务端代码兼容原部署 Python 3.6，Cloud 客户端依旧使用 3.11+。
3. 备份并更新这三个文件到现有 UI 目录。`selection_api.py` 会导入 `uploads.py`，不能只更新其中一份。沿用现有 picker 的 Basic 凭据和 StateDirectory，无需新端口、权限或公网暴露。
4. 管理员在允许短暂网关中断的时间，仅重启 picker。确认原相关服务恢复 active，无认证请求仍返回 401，正确认证可读取上传能力。不要因上传升级重启整台 ECS、改 VPN 或轮换 Apple/网关凭据。
5. 再把新的客户端、队列、Skill、根指引和启动指引合入自己的私有运行仓库，保留可信 origin 等部署值。普通 Cloud 任务通过已有 `cloud_refresh.py` 获取；纯客户端/指引更新不需要重发环境基线。
6. 用新的唯一测试目录做小文件/大文件上传、断点恢复、生成文件门槛和冲突测试。核对 Cloud 真实 GET 哈希后，再在原生 iCloud 端单独确认。

`deployment/reference/` 保存历史建设步骤，不会自动部署新增文件，不要将历史脚本批量重放到现网。

## 限制与恢复

- 每个文件最多 32 MiB；队列最多 1000 个精确文件路径。
- Cloud 队列保留空间上限 256 MiB，ECS 上传会话保留配额 1 GiB。达到限制就停止并报告，不自动删除旧文件或备份；维护删除必须进入废纸篓。
- 队列串行处理文件、进行受限分块并发；ECS 复用现有服务，不增加常驻编译服务。
- 超时及选定临时 HTTP 错误按指数退避，最长间隔五分钟；认证、冲突、校验和存储问题需要处理后再试。
- Cloud 休眠或执行环境失效时，监听不能继续。恢复同一保留目录可恢复队列；新 VM 不会自动获得旧 VM 未发出的内容。
- ECS 到 iCloud 的最后一次 PUT 仍受上游影响，未证明正式文件替换具备原子性。遇到远端半成品会阻止盲目重试，不能宣称永远不会出现半成品。
- 这是逐文件发布，没有跨文件原子提交、自动冲突合并或本次新增的手机失败推送。

## 隔离验收

常规 Python 测试只使用合成后端。`tests/live_autosave_acceptance.py` 则会实际写入当前配置的 iCloud 网关，必须先审阅并授权：

```bash
python3 tests/live_autosave_acceptance.py --authorized
```

它需要已配置网关、XeLaTeX 与 PyMuPDF，在新的 UUID 测试目录创建三个合成文件，检查后台首次/再次保存、PDF ready 门槛、暂停恢复、一次本地注入临时失败后的真实重试，以及远端冲突拒绝覆盖。最后暂停测试监听，保留所有文件、队列和日志；不删除用户文件。它不模拟整个 VPN 断开，也不代替手机端检查。
