# GitHub 零服务器状态通道与 Android 9 配对

当前已部署的云端入口是私有 `himoggyi/cleanyourtv-tasks` 仓库的
`.github/workflows/projector-queue.yml`。调用者必须是 owner 数字 ID 143339177，
只接收 main 上的 workflow_dispatch。运行时权限限 Contents read、Issues write，
使用标准 Linux runner，3 分钟超时，无定时触发、付费服务器或制品存储。

云端和设备均核对仓库 ID、所有者、私有状态及 Issues 开关。签名采用既有
`protocol.py` 的 RSA-SHA256，包含任务 ID、设备、有效期和结构白名单。
GitHub 访问权限保障账本私密性，Base64 不提供加密；拥有仓库权限的人员仍能读取内容。
不能阻止仓库管理员改为公开或删除记录，必须保持仓库私有并谨慎授权。
私钥、设备令牌、配对 JSON 不进入源码、Issues、工作流输入或日志。

## 已实际验证

- 私有仓库 Issue 创建、独立读取、更新及关闭成功。
- 新部署工作流真实触发成功，将 RSA 签名 cloud_probe 保存到私有 Issue。
- runner 结束后，新 Python 进程从 GitHub 读回并验签成功，证明持久记录不依赖 runner。
- 未配置设备开关的 authorized-status 负向测试按预期失败，没有增加设备任务记录。

具体私有 Issue、运行 ID 和配对准备信息保存在本地验证报告/私有仓库；不复制任务内容到公开 PR。
探针使用一次性 RSA 测试密钥；其中的公钥只用于测试读回，绝不作为设备信任根。
设备端拒绝 cloud_probe，生产任务必须使用本机明确配对的固定公钥。

## 已构建但未安装的设备端

新的 remote v9 支持 `github-issues` 配对，首版仅接收 `status`；壁纸、安装、布局等仍被
GitHub 传输层禁止，旧 broker 模式保留既有功能。rescue v10 是同包名、同签名的前向停用远程版。
Android 9 兼容性由 minSdk 26 与针对 SDK 28 的 APK 签名检查支持，仍需真实设备验证。

设备主动 HTTPS 拉取，API 主机和仓库固定，拒绝重定向。前台服务、开机启动、15 分钟
JobScheduler 与本地停用逻辑沿用；OEM 限制和强制停止仍可能需要遥控器手动恢复。
正常空闲轮询 60 秒，失败指数退避最多 15 分钟，另有 Actions 排队时间，无实时 SLA。

设备逐个验证签名、有效期、目标和 status 白名单，先 SQLite claim 再读取状态。
GitHub 与 broker 使用分开的执行日志/回执 outbox，进程中断记 unknown，不重复执行。
回执写到私有 Issue 评论并关闭该条 Issue；网络中断可能重复发送同一回执，不重复执行任务。
Issue 的关闭不是执行凭据或取消保证，评论也不是任务输入。
回执是持有设备凭据的一方声明，并非独立硬件证明；没有真机回执时不得报告真机成功。

每次最多扫描 50 个最早的 open Issues；过期/错误签名记录会被跳过但不自动修改。
所有者需清理已过期和测试条目，防止堵塞扫描范围。GitHub Issues 不是无限吞吐消息服务。

## 配对准备：先检查 APK，后授权

1. 只读取得投影仪实际安装的 `com.gathin.tvhome` base.apk，使用 `apk_guard.py` 与 remote v9
   核对包名、签名、Android 9 及严格递增版本。不要运行旧 `build-and-install.sh`。
   当前 v9/v10 的本地签名并不证明与投影仪相同；不同就用原 keystore 重建，不能卸载绕过。
   实际已安装版本过高时重新选择更高 remote/rescue versionCode，不能强制降级。
2. 使用 `configure_github.py --out /private/fresh-directory --device x5pro` 生成全新 3072-bit RSA
   控制器材料。路径不得在真实 Git checkout 内，已有目录拒绝覆盖。
   当前准备包在工作区的 `cleanyourtv-private/github-pairing-v1`，未写入生产 Secret。
   不要对旧控制器材料运行覆盖或把云端探针密钥用于配对。
3. 用户在 GitHub 创建仅限私有任务仓库的设备 fine-grained PAT：Metadata read、Issues write；
   此 status-only 版本不需要 Actions read/write 或 Contents write。
   它不能代替云端的发送凭据；到期或撤销后设备会停止拉取和回传。
   通过安全环境绑定设置 PROJECTOR_DEVICE_GITHUB_TOKEN，绝不在聊天发送令牌。
   如需要重新运行生成器，选择新的私有目录；不要覆盖已配对控制器。
   无令牌时仅生成 `pairing-template.INVALID.json`，它不可导入，不能声称已完成配对。
4. 在私有任务仓库 Secrets 安全设置 `PROJECTOR_TASK_SIGNING_KEY` 为同一控制器的 RSA 私钥。
   配对文件只包含公钥和设备 PAT；它属于秘密，应通过本地可信介质传入设备。
   离线备份私钥；不要上传到聊天，也不把 APK 签名 keystore 当成任务签名密钥。
5. 仅在实际 APK 签名匹配后，由用户在 Android 系统界面同签名更新，不卸载、不清数据、
   不改变默认 HOME。私有首选项和恢复快照保留，前向回退使用同签名 rescue。
6. 遥控器打开 Remote 配对页，导入有效 `pairing.json`，核对设备名、私有仓库及
   RSA SPKI SHA-256 指纹，明确授权，开启前台服务及厂商允许的自启动/电池豁免。
7. 最后才设置私有仓库变量 PROJECTOR_DEVICE_ID=x5pro 与 PROJECTOR_ENABLE_DEVICE_TASKS=true。
   手动触发 authorized-status，严格匹配本次任务 ID 与设备回执，确认 SDK 28。
   超时先查询原任务，不重复创建新任务；这才是设备端到端验证。

## 自动测试与费用边界

42 项 Python 测试通过。remote 130 项 JVM 测试通过（124 既有测试加 6 项实际 RSA/配对/协议检查），
rescue 124 项通过；remote/rescue 构建和 lint 通过，分别保留 73/62 条 warning，0 error。
JVM 测试不涵盖真机 HTTPS、Keystore、SQLite 进程恢复、系统后台策略或遥控器操作。
云端真实运行通过并不等于上述 Android 路径已在设备成功。

不租服务器，不启用付费 runner、定时工作流或持续制品存储。运行消耗账户包含的 Actions
分钟数；请在账单界面确认免费额度及预算/超额停止控制，额度耗尽就停，不能自动付费扩容。
代理尚未验证或修改账户级计费设置，不能保证无限任务永久免费。
