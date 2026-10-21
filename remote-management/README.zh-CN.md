# CleanYourTV 云端壁纸控制

在上次 `remote-management` 原型上继续扩展，支持任意文件名的 JPG/PNG 附件上传、内容校验、
签名任务、HTTPS 持久队列、Android 9 私有壁纸存储和桌面 frame-ready 回执。

**私有任务仓库的 GitHub Actions → RSA 签名探针 → Issues 持久化 → 独立读回验签已实测成功。
Android 9 GitHub 状态版已构建，尚未核对真实已安装 APK 签名、安装配对或完成真机端到端验证。**
本地构建和模拟测试不代表家中投影仪已经受控。APK 安装/卸载、系统组件禁用、任意 Shell 和公网 ADB 均未实现。

- [签名更新、部署成本、权限修复、安装回退与集中手动清单](DEPLOYMENT.zh-CN.md)
- [实际验证结果与尚未完成的步骤](VERIFICATION.md)
- [未来聊天附件操作约定](CHAT-CONTROL.md)
- [零月费 GitHub 通道门槛、权限复测与安装功能设计](GITHUB-FREE-CHANNEL.zh-CN.md)（尚未实现安装）
- [已部署的私有状态通道、Android 9 配对与集中手动清单](GITHUB-PAIRING.zh-CN.md)

架构：`Codex 附件 → 固定上传脚本 → GitHub Actions 身份/授权/签名 → HTTPS 持久中继 → 投影仪主动拉取 → 带哈希与绘制证据的回执`。
一次性明确启用仅壁纸委托后，无须每次在投影仪确认换图；未启用时仍保留 GitHub 审核。

Python 3.12 / OpenSSL 的本地测试（需要 loopback socket 权限）：

```bash
python3 -m venv /private/remote-venv
/private/remote-venv/bin/python -m pip install -r remote-management/requirements.txt
/private/remote-venv/bin/python -m unittest discover -s remote-management -p 'test_*.py' -v
```

部署使用 `wsgi.py` + Gunicorn + `deploy/cleanyourtv.service` + `deploy/Caddyfile`。
`broker.py` 的内置 HTTPServer 仅用于 loopback 调试，不作为公网 HTTP 服务。
`configure.py` 在 checkout 之外生成私有材料；不得提交任何令牌、签名私钥、配对文件或 keystore。
有既有数据库/配对时应保留原 key/device token、备份数据并补充新增角色凭据；不要无意重新生成密钥导致设备失联。

Android 构建：默认 `release` 保留本地模式，`remote` 是可选远程版，`rescue` 是同包名和签名的前向停用远程回退版。
APK 是否能安全更新以实际 installed-base.apk 的签名 gate 为准；不要运行包含禁用原厂桌面步骤的旧安装脚本。
