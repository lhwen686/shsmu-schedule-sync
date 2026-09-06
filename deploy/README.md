# 可选的私人 WebCal 部署参考

本地生成 `.ics` 不需要部署服务器。本目录提供单个私人日历的后端和 Linux/systemd/Caddy 配置参考；不包含托管服务或自动安装器。原维护环境专用的服务器安装脚本未公开。

每个使用者需要独立存储、密钥和发布目标。当前后端只有一个日历槽位，不支持多个账号共用一个上传地址。

## 文件和运行布局

| 文件 | 用途 |
| --- | --- |
| `webcal_server.py` | 仅监听 `127.0.0.1:18443` 的 Python 后端 |
| `Caddyfile` | 示例域名 `calendar.example.com`，HTTPS 8443，HTTP-01 证书验证使用 80 |
| `shsmu-calendar.service` | 后端 systemd 模板 |
| `shsmu-calendar-https.service` | 独立 Caddy systemd 模板 |

部署前由服务器管理员准备自己的域名、有效 HTTPS、可用端口、Python 3.12+ 与兼容的 Caddy；替换 `Caddyfile` 的示例域名。模板不监听 443。需要自行检查 80、8443、18443 是否与现有服务冲突。

systemd 模板假定：程序和 Caddy 位于 `/opt/shsmu-calendar`，配置位于 `/etc/shsmu-calendar`，服务账号和组均为 `shsmu-calendar`，数据在 `/var/lib/shsmu-calendar/feed`，证书状态在 `/var/lib/shsmu-calendar/tls`。模板不会创建这些目录或账号，需管理员配置权限；服务账号仅需读取程序和配置、写入数据和证书目录。

## 本机配置和服务器凭证

在项目的 `local/webcal.json` 保存以下结构。尖括号内容必须替换，示例不能直接运行：

```json
{
  "enabled": true,
  "origin": "https://calendar.example.com:8443",
  "read_token": "<独立生成的只读密钥>",
  "write_token": "<独立生成的上传密钥>"
}
```

两个密钥应分别使用 Python `secrets.token_urlsafe(32)` 生成，长度均为 43 字符且不同，仅写入被忽略的本机配置，不打印到共享日志或提交到仓库。

服务器 `/etc/shsmu-calendar/auth.json` 只保存这两个密钥的 SHA-256 十六进制摘要：字段名为 `read_sha256` 与 `write_sha256`。可使用 `hashlib.sha256(token.encode()).hexdigest()` 计算。限制配置文件权限，不共享原始密钥。

后端命令（由服务模板执行）：

```sh
python3 /opt/shsmu-calendar/webcal_server.py --config /etc/shsmu-calendar/auth.json --data /var/lib/shsmu-calendar/feed
```

管理员验证自己的配置与权限后再启用对应服务。本仓库发布时未在新服务器安装；这些模板不是一键部署承诺。

## 使用与维护

完成配置后运行 `仅上传日历.cmd`。首次需已有本地完整课表。看到“线上日历已更新并回读校验”后，使用 `https://你的域名:8443/<read_token>/calendar.ics` 作为私人订阅地址。持有该链接的人可以读取课表，上传使用另一把密钥。

后端验证完整性、哈希、事件数、唯一 UID 和源时间，然后原子替换版本。旧版本或同时间冲突上传被拒绝，相同版本重复上传不会重写。上传器从实际订阅地址回读并核对哈希。

上传失败时本地完整版本保留，重新运行仅上传入口即可。`local/webcal-last-success.json` 保存最近一次回读确认；服务器 `current.json` 与 `previous.json` 保存当前和上一版。不要把这些私人数据放进仓库。

只暂停本机上传：将 `enabled` 改为 `false`；线上仍提供最后发布的版本。只读检查使用 `systemctl status shsmu-calendar.service shsmu-calendar-https.service --no-pager`。管理员停用时仅停用这两个专用服务，保留配置与数据；不要修改其他业务服务。

客户端使用正常 HTTPS 证书校验并拒绝重定向。后端不记录访问路径，Caddy 模板关闭可能记录路径的 HTTP 错误日志；若接入其他反向代理，应避免在日志中保存含密钥的订阅路径。
