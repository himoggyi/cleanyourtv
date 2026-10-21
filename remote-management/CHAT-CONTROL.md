# 云端聊天执行约定

这是给后续 Codex 会话的操作约定，不是宣称已安装的 MCP 工具或后台聊天监听器。
只有会话可访问附件文件、这个 checkout、出站 HTTPS 和已安全配置的凭据时才能执行。

收到“换成这张壁纸”且只有一张明确附件时：

1. 将用户明确选定的附件保存为本地文件；不把 URL/文件名当 Shell 代码。附件缺失或多张不明确时才澄清。
2. 使用 `exec_command` 运行参数数组等价的固定命令：
   `python3 remote-management/wallpaper.py --image /absolute/attachment.png --device x5pro`。
   路径必须正确进行 Shell 引号处理；不得读取/打印凭据值。
3. 工具会移除 EXIF/GPS、缩放大图、验证 JPG/PNG、上传、经 GitHub Actions 签名提交，并等待此 UUID 的设备回执。
4. `dispatch accepted` 或 `queued` 都不是执行成功。只有结果的哈希与本次归一化图片一致，
   `status=succeeded` 且 `display_confirmed=true` 才报告“启动器确认已解码并进入绘制”。
   `image_view_pre_draw` 不证明投影光学画面；必要时由用户看图确认。
5. 超时/403/证书不匹配/未部署/待 HOME 时照实报告；保留 task ID，不自动重发一个新任务。
6. 不卸载、不清数据、不修改 HOME、不执行任意 Shell、不安装其他 APK、不改变路由器。

如果本地私有目录已有已部署的状态，先阅读它的非秘密部署记录；不得根据上次聊天自行假定凭据或设备还有效。
GitHub Environment 的每任务审核尚开启时，聊天不能绕过审核自动执行。用户可明确授权创建仅限壁纸的
`projector-wallpaper` Environment，并设置 `PROJECTOR_AUTOMATIC_WALLPAPER=true`；工作流只把
`apply_wallpaper` 送入它，且签名前再次限制操作范围。其余任务仍进入需要审核的 `projector-control`。
不得自行启用这个委托开关或删除其他环境的审核保护。
