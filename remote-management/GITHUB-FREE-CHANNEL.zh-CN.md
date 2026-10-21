# GitHub 免费通道：权限实测与下一阶段设计

**后续进展：私有任务仓库已创建并实测 Issues 读写，签名 status 探针经真实 Actions 持久化，
独立进程已读回验签。新的 Android GitHub 状态适配已构建但未安装配对。
请先看 [最新配对说明](GITHUB-PAIRING.zh-CN.md)；以下 403/410 及未部署描述均为阶段历史。**

## 重新授权后的实际结果（2026-10-21 20:02 UTC）

- Connector 和 gh 均可读取仓库，当前调用者为 himoggyi（143339177）。
- 实际 git push 成功，远端 `codex/projector-remote-prototype` 已核对为
  `389c251ddb4166ff77bd5a44cbf2bce14f18e643`（下列文档更新会继续推进此分支）。
- 实际 workflow_dispatch 被接受，产生 [CI 运行 39666817604](https://github.com/himoggyi/cleanyourtv/actions/runs/39666817604)。
  这是工作流触发证据，不是设备任务或真机执行证据。
- 之前代码推送和 Actions dispatch 的 403 已解决，不再要求用户重复修复这两项权限。
- 继续验证 Issues 持久账本时，创建明确标为不可执行、不含设备信息的探针请求返回
  **410：Issues has been disabled in this repository**。没有创建探针 Issue；
  Issues 写权限尚不能由此证明。此阻塞不同于 403，不能通过重新发送任务解决。
- 当前仓库公开；没有自行开启 Issues、修改仓库可见性、写入秘密或操作投影仪。
- 已创建 [草稿 PR #1](https://github.com/himoggyi/cleanyourtv/pull/1) 供审查现有代码，尚未合并。

下一步由所有者建立专用私有任务仓库（例如 `himoggyi/cleanyourtv-tasks`），启用 Issues，
并把它加入 Connector 授权。云端发布者需该仓库 Actions write；发布工作流需一次性
Contents/Workflows 写入权限。专用工作流的运行令牌只需 Contents read、Issues write。
设备令牌后续单独配置为该任务仓库 Issues write、取制品所需 Actions read，不能拿云端令牌配对设备。
先复测私有账本创建/持久读取/关闭及 Actions 任务发布，再配置签名和进入设备验证。
不要把任何 PAT、私钥或配对内容发到聊天中。

以下为重新授权前的历史记录及尚未实施的设计；其中 403 不再代表当前状态。

2026-10-21 重新授权前：云端身份为 himoggyi（143339177），可读 Actions；向线上现有
`ci.yml` 的 `workflow_dispatch` 发出真实 POST，GitHub 返回 HTTP 403，
`Resource not accessible by integration`。线上工作流列表只有 CI，没有 projector-relay。
所以“云端可以发送设备任务”尚未成立。现有代码依赖外部 HTTPS broker，不符合本次零月费要求；
本文件是替换传输层的设计，**不是已经部署的队列或安装功能**。

## 先通过真实通道门槛

执行 `python3 remote-management/github_access.py --dispatch-ci`，通过当前 gh 身份真正触发 main 的 CI。
该命令不发送设备任务；只读成功、CI 接受、CI 完成、设备收到任务、设备执行成功是不同证据。
20 秒超时后禁止自动重发 POST，先检查 GitHub 运行记录。
`--dispatch-status` 仍使用另行配置的 PROJECTOR_GITHUB_TOKEN 发送旧版 status 任务，
它要求旧版 relay/broker 已部署，不能用作免费通道验证。

需要仓库所有者在 GitHub App 的授权配置中核查是否支持该仓库的 Actions write。
若当前集成不能提供该权限，在安全凭据存储中另配仅限任务仓库的 fine-grained PAT：
Metadata read、Actions write。不要把令牌放进聊天、仓库、工作流输入或构建产物。
专用 PAT 不会自动替换 gh 当前身份；需要在云环境的受支持安全配置中将其绑定给发送工具，
或对使用 PROJECTOR_GITHUB_TOKEN 的发送脚本单独验证。修改 workflow 的 `permissions` 不会给云端调用方提权。
一次性发布受审查工作流所需的 Contents/Workflows 写权限，与日常发送令牌分开。

## 零月费候选架构（尚未实现）

复用现有签名、任务 ID/有效期、原子执行日志、结果 outbox、壁纸处理和恢复机制，
仅增加 GitHub 传输适配层。使用所有者专用私有任务仓库，防止任务历史、设备信息和壁纸公开。
需要另外发布最小工作流；当前带外部 broker 的示例不能原样部署后声称免费通道已完成。

1. Codex 在本地解析明确请求，生成严格结构任务；任意文本、评论和文件名均不能变成命令。
2. Actions 校验 owner 数字 ID、事件、白名单、任务及制品大小，通过受保护 Environment 中的
   私钥签名。工作流只授予该任务仓库的 contents read、issues write，固定依赖提交和运行时限。
3. 签名任务保存在专用 Issue 的结构化账本中，形成跨 runner 生命周期的待处理记录。
   GitHub Actions runner 本身不是持久队列。任务不得仅存 runner 工作盘。
   评论作者或标签不是授权凭据；执行端必须验证签名、设备绑定、有效期和防重放日志。
4. 设备主动 HTTPS 拉取，绝不需要公网 ADB 或家中入站端口。
   设备凭据仅限独立任务仓库 Issues write，以及取壁纸制品所需 Actions read；
   不授予 Actions write、Contents write 或访问项目代码仓库的权限。
   Issues write 允许篡改账本造成拒绝服务，因此必须有签名、防重放、限额和审计；
   不应把这个 token 放进包含其他重要 Issue 的项目仓库。
5. 壁纸用有保留期的 Actions artifact，任务绑定 artifact ID、成员名、大小及 SHA-256。
   下载时限制 ZIP 成员和解压尺寸，验证现有 JPG/PNG 描述符，不接受任意 URL。
   超出制品保留期后明确失败，不悄悄替换图片或重新执行。
6. APK 由设备从已审核官方源直接下载，避免把大 APK 持续存入 GitHub 制品。
   回执作为签名任务 ID 对应的结果记录，区分设备声明与人工目视确认。
   本地显示逐字节进度，仅把阶段变化与最终结果写入 GitHub，避免每个进度百分比触发 Actions。

设备正常运行时可每 60–120 秒检查任务，使用条件请求、指数退避并处理 403/429/Retry-After。
总体延迟是 Actions 排队/启动时间加拉取间隔，可能从几十秒到数分钟，没有实时 SLA。
Android 9 OEM 杀后台、强制停止、断网和待机可以让延迟无上限；保留前台通知、开机启动与
15 分钟 JobScheduler 看门狗，首次需要遥控器开启远程服务及厂商允许的自启动/电池豁免。
不能承诺自动恢复被强制停止的应用。

GitHub Free 有私有仓库 Actions 分钟、制品存储与 API 限额，以该账户当前账单页面为准。
只用标准 Linux runner、按请求启动、短保留期、小图片、清理过期制品；不轮询启动工作流，
不使用付费 runner。设置 Actions/存储预算或平台提供的超额停止控制，不配置自动付费扩容。
若额度不足则停止接收并明确失败，不能承诺无限任务、永久制品保存或永久零成本服务。
本方案无需租 VPS，但仍需所有者确认 GitHub 私有仓库额度和成本控制。

## 通道通过后的 APK 实现范围（尚未实现）

先通过实际 dispatch、持久任务发布、设备拉取及匹配真实 status 回执，才进入安装实现。
使用新的显式 APK 任务类型，不能把下载地址塞进旧壁纸操作或复用任意 Shell。

- 应用目录绑定 packageName、官方发布源、允许重定向的主机、Android 9/CPU ABI 兼容性、
  versionCode、字节上限、SHA-256 和独立可信的签名证书 SHA-256。
  “下载后自己算 SHA-256”只能校验传输一致性，不能证明发布者可信；
  首次证书信任必须来自独立官方证据或所有者明确核准，不能信任同一可疑 APK 自报证书。
  找不到可信签名基线时拒绝进入安装队列，不能把非官方聚合站当官方源。
- 更新前核对设备实际已安装应用的包名、签名/有效签名轮换链及版本；禁止降级、
  禁止包名替换和自动卸载。保留当前桌面配置和原有同签名升级/前向 rescue 流程。
- APK 流式下载到应用私有暂存区，固定 HTTPS 信任、禁止凭据跨主机转发、可取消、
  校验长度/哈希/包信息和签名后才创建 Android PackageInstaller 会话。
- 仅声明 REQUEST_INSTALL_PACKAGES；Android 9 首次由用户在设置中允许此来源，
  使用系统安装确认界面，处理 STATUS_PENDING_USER_ACTION，绝不请求静默安装或绕过遥控器确认。
  用户说“安装 VLC”可作为对具体匹配的可信 VLC 包的安装请求，系统确认仍保留；
  若版本、来源或签名不明确，先展示具体候选及证据再授权。
- 持久化 queued/downloading/verifying/awaiting_user/installing/succeeded/failed/unknown，
  用明确的安装结果回调、失败码与实际已安装包版本核对成功；
  启动安装界面不算成功，进程重启后核对会话和包状态，不盲目重复安装。

## 需要用户手动完成的步骤

1. 原项目的代码推送与 Actions write 已实际通过，不必再为它创建额外 PAT。
   为新的私有任务仓库启用 Issues 并授权 Connector，复测该仓库的读写和触发权限。
2. 发布后续受审查工作流，配置任务签名密钥与授权规则；
   检查免费额度及超额停止机制。这不是修改原厂设备或开放公网端口。
3. 提供实际已安装 CleanYourTV APK 的只读签名核对材料，或在已授权局域网 ADB 下导出；
   若签名不同，找到原签名 keystore，不能卸载现有桌面来绕过校验。
4. 通道和安装代码完成并通过自动测试后，手动同签名升级、在本机配对及开启服务，
   允许本来源安装应用，并用遥控器确认首次安装。最后采集真实 task ID 和安装结果回执。

当前未升级设备、未安装 VLC、未部署 GitHub 免费队列，也未完成真机端到端测试。

## 本次自动验证

`/workspace/remote-venv/bin/python -m unittest discover -s remote-management -p 'test_*.py' -v`
共 34 项通过（原有 27 项加权限诊断 7 项）。包括拒绝把只读权限或 CI 接受升级为设备成功证据、
错误 owner 不发任务、工作流缺失不发任务、超时/服务器错误结果不明且不重发。
首次在不允许 socket 的沙箱运行时有 3 项网络测试被阻止；提供网络权限后完整重跑通过。
本次仅更改 Python 诊断和文档，没有修改 Android 或新增 APK 安装实现，因此没有重新构建 APK。
真实探针记录位于工作区 `artifacts/github-free-channel-probe.json`，其中无令牌或密钥。
