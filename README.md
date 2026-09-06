# 上海交通大学医学院课表同步

从本人正常登录的本科教务系统读取结构化课表，生成 JSON、课程变更记录和 `.ics` 日历。采用现有 Chrome 中手动安装的书签采集，Python 接收下载文件；日常使用不需要 Codex、浏览器扩展或服务器。

适用于 `jwstu.shsmu.edu.cn` 的本科教务系统。当前实现已用一个账号完成真实整学期采集和重复同步；其他账号首次使用需要自行核对课程，其他学校需要另行适配。默认示例为 **2026–2027 学年第 1 学期**，首次使用请先确认学期范围。

## 安装

1. 准备 Windows、Python 3.12+（含 `py` 启动器）和 Chrome。
2. 下载本仓库 ZIP 并解压，或克隆到一个固定目录。每人使用独立目录。
3. 双击 `setup.cmd`，等待依赖安装和书签页生成。
4. 在 Chrome 中打开生成的 `chrome-bookmark.html`，把“同步医学院课表”按钮拖到书签栏。

程序会创建 `.venv` 和 `config.local.json`，无需填写教务密码。不自动启动、关闭或重新配置 Chrome，也不更改扩展。

## 日常同步

1. **先双击 `同步课表.cmd`，保持窗口打开。**
2. 在现有 Chrome 正常打开 [教务首页](https://jwstu.shsmu.edu.cn/Home)，确认显示本人学号，再点击“同步医学院课表”书签。
3. 保持学校页面打开，等待采集完成，将 JSON 保存到同步窗口显示的下载目录。Python 会自动处理并生成日历。

请求顺序执行，至少间隔 1 秒；耗时随课程次数变化，已验证账号每次约 5 分钟。接收窗口最长等待 30 分钟。未配置 WebCal 时只生成本地文件。

若 Chrome 使用自定义下载目录，在 `config.local.json` 添加 `downloads_dir`，或运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 sync.py --downloads "你的下载目录"
```

如果已先下载文件，用以下命令明确导入：

```powershell
.\.venv\Scripts\python.exe -X utf8 sync.py --capture "采集文件完整路径.json"
```

处理同一文件会提示“已经处理”，不会当作新采集；旧于当前版本的文件会被拒绝。

## 输出

| 文件 | 用途 |
| --- | --- |
| `output/calendar.ics` | 日历文件，含课程及取消记录 |
| `output/changes.txt`、`output/changes.json` | 最近一次新增、删除和字段变化 |
| `data/schedule.json` | 标准化课表，含时间、地点、教师和稳定 UID |
| `data/previous.json` | 上一完整版本 |
| `data/runs/` | 历次清理后的原始响应、快照和输出 |
| `data/current.json` | 当前完整版本索引 |
| `output/wakeup.csv`、`output/wakeup导入说明.txt` | 独立导出的 WakeUp 手动导入文件及日期、作息设置说明 |

课程时间采用学校返回的明确日期和 `Asia/Shanghai` 时区，不按单双周猜测。保留源标识；课程改时间、地点或教师时，能够匹配身份的事件沿用 UID 并增加修订序号。

## 手机日历

可以把 `output/calendar.ics` 导入支持 iCalendar 的日历软件。文件导入是一次性操作，反复导入时的更新和删除行为取决于客户端。

需要持续订阅时，可以自行配置 HTTPS WebCal。仓库提供上传器、服务端和部署参考，详见 [deploy/README.md](deploy/README.md)。**本仓库不提供托管服务、共享订阅地址或上传密钥。** 每个使用者需要独立的日历存储和访问权限。

配置后，每次本地同步成功会自动上传并回读校验；上传失败可双击 `仅上传日历.cmd` 重试。手机按自身订阅刷新机制更新，并非即时推送。学校采集仍需本人登录和点击书签，尚无无人值守采集。

## iOS WakeUp 手动导入

完成一次完整同步后，双击 **`导出 WakeUp 课表.cmd`**。程序从当前已提交快照和对应原始教师详情生成 `output/wakeup.csv`、`output/wakeup导入说明.txt`，无需再次打开学校网页，也不会上传文件。命令行入口：

```powershell
.\.venv\Scripts\python.exe -X utf8 wakeup.py
```

1. 将 `wakeup.csv` 保存到 iPhone 的“文件”App。
2. 在 WakeUp 中选择 **导入课表 → Excel 导入 → 选取 CSV 文件**，导入到新课表。
3. 按配套说明设置学期开始日期、学期周数、一天节数和上课时间；CSV 本身不携带这些设置。
4. 核对首周、晚课和不连续周次。以后完成学校同步后，再点击独立导出入口，将新 CSV 手动导入到新课表，核对后自行移除旧课表。

CSV 采用官方七列，每次实际课程一行，保留实际周次、教师和地点，不导出取消记录、授课内容及备注。原“同步课表.cmd”不会自动生成 CSV，WakeUp 也不会自动跟随 CSV 更新。重复导入的覆盖和删除行为尚未验证。

当前支持的作息规则为：第 1–5 节从 08:00 起，第 6–14 节从 13:30 起，每节 40 分钟，相邻节次间隔 10 分钟。说明逐项区分原始课程已确认的起止边界与推算边界，这不是学校官方作息表。每次导出会检查所有实际课程起止时间；缺少详情、节次或周次冲突、时间不匹配时停止导出并保留旧 CSV，不强行套用其他校区或学期的作息。

已有一个账号完成 iOS WakeUp 实机导入并反馈可正常使用，其他使用者仍需自行核对。格式与操作依据：[官方 CSV 教程](https://www.wakeup.fun/doc/import_from_csv.html)、[课表设置](https://www.wakeup.fun/doc/settings/schedule_settings.html)。

## 学期和账号

默认范围是 `2026-09-07` 至 `2027-01-18`（结束日期不包含），对应 `2026-2027:1`，示例依据见 `config.example.json` 的 `calendar_source`。

下学期修改 `config.local.json` 中的 `semester`、`start`、`end_exclusive`，然后执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 sync.py --prepare
```

使用新安装页替换 Chrome 中旧书签的网址，再运行 `同步课表.cmd --new-term` 并点击书签。每个学期最多 240 天，旧完整版本仍保留。书签不会自动随磁盘文件更新。

每个账号使用独立项目目录；不要把别人的历史数据复制进自己的目录。程序检查账号摘要、学期和范围，发生变化时会停止，避免误报删除。

## 失败和恢复

登录失效时，在原 Chrome 走学校正常登录流程，再从教务首页重新采集。临时请求失败会有限重试，部分失败可在同一页面短时间内点击“继续采集”；刷新页面后需重新开始。诊断 JSON 不可作为完整课表导入。

不完整采集、异常字段、整个学期意外为空或身份匹配冲突，都不会替换最后完整版本。输出文件损坏时可从已提交快照恢复，不访问学校：

```powershell
.\.venv\Scripts\python.exe -X utf8 sync.py --repair
```

退出码：`0` 成功，`2` 数据或访问检查失败，`3` 需重新认证，`4` 上传未确认（本地版本已保留），`1` 本地异常，`130` 用户中断。

## 数据保护

登录由浏览器正常处理。采集器不读取或导出 Cookie、密码、会话存储，不记录认证请求；保存前去除教师电话、账号等非必要字段。

`.gitignore` 排除 `data/`、`output/`、`local/`、虚拟环境和本机配置。课表下载文件、诊断文件、私人订阅链接和密钥也应仅留本机，提交 Issue 时不要附带这些个人文件。克隆仓库没有个人历史，不能把这种缺失当成学校删除了课程。

## 开发验证

安装依赖并生成书签后运行（JavaScript 测试需要支持内置 Fetch 的 Node.js）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest -v test_sync test_webcal test_wakeup
node test_capture.mjs
node test_transport.mjs
```

模拟测试与真实验收分别记录在 [VERIFICATION.md](VERIFICATION.md)。接口说明见 [DISCOVERY.md](DISCOVERY.md)。仓库内测试数据为人工构造，不包含个人课表。
