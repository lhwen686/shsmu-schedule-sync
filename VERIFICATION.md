# 验证与修复记录

<a id="mac-update-tls-tabs-20260930"></a>
## MAC-UPDATE-TLS-TABS-20260930：Mac 更新证书（BUG-010）与设置页标签空白（BUG-011）（未发布）

2026-09-30，用户要求把 rc18 Mac 未测部分实测，并解决所有非本人操作的问题。基线公开 main `68e73f7729e5c8c9bb21aa92b6740d1b8d1f9144`（rc18 源码，main 在 tag 之后仅改验收文档），分支 `fix/mac-update-tls-and-tabs`，无既有未提交改动。本机：Apple 芯片、macOS 27.0，未安装 python.org Python。

**BUG-010 Mac 应用内更新全部失败。** 实机：rc17、rc18 APP（Tk 8.6.16、python.org 3.12.10 构建）启动后自动检查静默失败，诊断事件 `update_check_failed`；键盘触发“检查更新”弹出“暂时无法连接更新服务器，请检查网络后再试。（URLError）”。同机网络正常：源码 `updater` 分别经 COS、GitHub 读取签名清单并下载 rc18 Mac ZIP，均与附件 SHA-256 一致。根因：包内 `libcrypto` 的 `OPENSSLDIR` 为 `/Library/Frameworks/Python.framework/Versions/3.12/etc/openssl`，学生 Mac 没有该目录，APP 也不带 `certifi`，证书校验必然失败；发布机装有 python.org Python，所以冻结自检和发布门禁都没发现。对照：同一 rc17 仅加 `SSL_CERT_FILE=/etc/ssl/cert.pem` 启动即记录 `update_available`，确认后下载到“下载”文件夹，文件与 rc18 附件逐字节相同。源码复现：`SSL_CERT_FILE`/`SSL_CERT_DIR` 指向不存在路径后，`fetch_release()` 给出与 APP 相同的错误。

修复：`updater.https_context()` 在 macOS 额外加载系统自带的 `/etc/ssl/cert.pem`，证书与主机名校验保持开启；证书失败单独提示“无法验证更新服务器的安全证书……”，不再误导为网络问题。冻结自检记录 `update_ca_certificates`，Mac 为 0 时失败；`native_package_check` 在 Mac 上隐藏 OpenSSL 默认路径后运行自检，模拟学生 Mac。新增 `macos-checks.yml`：每个 PR 在 macOS 15、Python 3.12.10 上跑完整检查、原生构建和包检查，不发布。改后同条件读取到 rc18；expired / wrong.host / self-signed 测试站仍被拒绝。rc17、rc18 的 Mac 用户需手动下载修复版一次。

**BUG-011 设置页标签切换后内容空白（rc17 已存在）。** 实机：rc18 用键盘切换“作息时间 / 文件夹 / 学期”后标签内容整块空白，调整窗口大小才显示；rc17 同样按键既跳动也空白。源码在 Tk 8.6.14（uv Python 3.12.10）以真实按键复现；仅含 `ttk.Notebook` 的最小窗口同样空白，Tk 9.0.4 不空白，排除卡片 Canvas 与滚动容器。结论为 Tk 8.6 Aqua 映射新标签页时不绘制其子控件。修复：Mac 上 `<<NotebookTabChanged>>` 时把选中页内边距临时加 1 像素、下一轮恢复固定值，促使 Aqua 重绘；改后同条件多次往返切换均正常显示，页面不跳动。

**顺带修正。** 更新提示不再写“点击‘是’”：Mac Tk 8.6 的对话框按钮与应用菜单固定为英文（Info.plist 声明中文本地化无效，已在测试壳中验证），改为“确认后……”。对话框居中于助手窗口（原先落在屏幕左上角，更新进度窗口与主窗口重叠）。Tk 8.6 下以伪造版本和假下载走完 Mac 更新界面：进度窗口、访达定位与“新版本已下载”说明均正常；此前在真实 APP 上未看到后两者，属本机桌面状态问题，不是程序缺陷。Mac 说明补充：助手下载的 ZIP 已核对签名与哈希，替换后通常可直接打开。

| 检查 | 结果 |
| --- | --- |
| 本机完整检查（Python 3.12.14 / Tk 9.0.4） | `check.py` 退出 0：279 项，278 PASS、1 Windows CMD SKIP；三组 JS PASS |
| 新增回归 | `test_updater`：Mac 无默认路径仍载入系统根证书、上下文校验开启且复用、证书失败提示（检查与下载）、`_open` 使用该上下文；`test_desktop_theme`：Mac 绑定标签重绘、内边距恢复、离开页面不报错 |
| 源码冻结前自检 | PASS，`update_ca_certificates` = 128 |
| Tk 8.6 实机窗口（测试壳） | 标签切换 PASS；Mac 更新界面流程 PASS（伪造版本与下载，未联网） |
| 首次 Mac PR 检查 | FAIL：新用例最后一步（切换标签后同一轮拆掉页面再 `update()`）超时 10 分钟。本机 Tk 8.6.14 复现：只在同一进程第二个 `tk.Tk()` 中出现，去掉本次重绘处理（仅 `select` 后拆页）同样卡住；第一个 `Tk()` 与 Tk 9 均不卡。属测试进程多解释器下的 Tk 8.6 行为，助手只有一个 `Tk()`。用例改为截获待执行的恢复回调并模拟页面已关闭，不再拆页 |
| 本机 Tk 8.6.14 全部 Python 用例（PNG 替代 ImageTk） | 279 项：277 PASS、1 SKIP、1 FAIL；该 FAIL 为子进程未加载替代层导致 ImageTk 报错，未改动的 main 同样失败，属本机测试环境 |
| Mac 原生构建与冻结自检（Tk 8.6.16） | 由 `macos-checks.yml` 在 PR 上运行，结果见 PR |
| 学校采集、手机导入、鼠标点击标签 | NOT RUN（需本人；本机桌面拦截鼠标点击） |

回滚：还原本分支提交即可，不涉及数据格式、UID 或书签；书签仍为 `2026-09-29.19`。

<a id="release-rc16"></a>
## RELEASE-RC16：应用内更新、界面改版与逐条读取双平台附件

2026-09-29，用户要求发布并下载。基线为已合并 PR #11 的公开 main `b4c324f44e12b505a994582399a2e8af02e21e0e`，新建 `codex/release-rc16`，仅修改版本、发布工作流、打包版本断言及说明。候选 `1.0.0-rc16` / Mac 修订 10 / 构建号 `16.0` / 书签 `2026-09-29.19`。

首次[发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36539842428)：Windows PASS；Mac 两项 FAIL，发布前停止、未产生附件。`test_scrolling_does_not_rebuild_the_scroll_region`：Tk Aqua 移动内容框时向所有子控件发送 `<Configure>`，`_wrap_label` 被调用 36 次但宽度未变、直接返回；测试改为断言滚动时没有任何标签获得新的 `wraplength`（本机模拟逐次 `<Configure>`：现有处理 PASS，改成每次重排的处理 FAIL）。`test_mac_quit_routes_through_safe_close_and_is_idempotent`：审计修复后 `close()` 在无存活后台任务时清除遗留的运行标记，测试改为保持 `DesktopJob.busy` 为真。两项均为 rc15 之后界面改版/审计修复在 Mac 上首次运行暴露，产品代码未改。本机 Windows 完整检查 265 项：256 PASS、9 SKIP，退出 0。

[发布工作流 36541396692](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36541396692) 全部 PASS；[rc16 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc16) 对应源码 `ccbc72dcb33c9ec4b7c33c0686b36aabdf5da022`，七个附件；`update-channel` 预发布首次建立并上传同一 `latest.json`。旧 rc15 附件保留。

| 本轮检查 | 实际结果 |
| --- | --- |
| Windows 原生完整检查 | 265 项：258 PASS、7 Mac SKIP、0 FAIL/ERROR，Python 77.054 秒，三组 JS PASS |
| Mac arm64 原生完整检查 | 265 项：264 PASS、1 Windows CMD SKIP、0 FAIL/ERROR，Python 73.484 秒，三组 JS PASS |
| 原生构建、冻结自检、合包与线上回读 | PASS；两端生成书签哈希一致 |
| 本机独立回下载 | PASS：七个附件大小与发布页一致（经本机代理中断一次后逐个重下）；`SHA256SUMS.txt` 覆盖的六个附件哈希一致；`update-channel/latest.json` 与发布附件逐字节相同 |
| 更新清单 | PASS：`1.0.0-rc16`、书签 `.19`；Windows/Mac 包大小与 SHA-256、Windows 包内 EXE SHA-256 与清单一致；`updater.parse_manifest` 通过，rc15 判定为有更新、rc16 不提示自身 |
| 真实网络读取 | PASS：`updater.fetch_release()` 默认来源经 GitHub 读取到 rc16，下载地址指向 v1.0.0-rc16 附件 |
| ZIP 与隐私 | PASS：三个 ZIP CRC 完整；无课表数据、配置、`update_sources.py` 或审计报告 |
| 下载后的 Windows EXE | PASS，退出 0；`--self-test`：`frozen=true`、rc16、书签 `.19`、内置书签校验通过 |

两端源码指纹：`484c903826579aebc544f4a1b1bc565b1856d27733ee991aae35f48e43879a7e`。生成书签 SHA-256：`9d042a54b88f7d410d74b3c2fe97cc5efc7113d6160f23e109af645a95073260`。

| 公开产物 | SHA-256 |
| --- | --- |
| SHSMU-Schedule-Assistant-1.0.0-rc16-Mac-arm64.zip | `7c24059d99c53b400ecd1da0751ea726c0364c6e0724e9e4ebd3beb85ce4aa71` |
| SHSMU-Schedule-Assistant-1.0.0-rc16-Windows-x64-Mac-arm64.zip | `fc531d8598089758f451e32eebd160acf77b3f82da4a7b5200c04b63504d35aa` |
| SHSMU-Schedule-Assistant-1.0.0-rc16-Windows-x64.zip | `6ef5c0381fd66d22b664669dcb0233593fb9a7c1ea682f2bb72fc5e6e6d6830a` |
| User-Guide.html | `3923525844a1af2d0f627abdd2bc3c7ad32ac9202fe594d490d101e74068c507` |
| build-verification.json | `73b75c4c9da7a1c1ac594e22fb874ca0b167228521c81a8bb61aef955d1b604f` |
| latest.json | `b35ddf42b482ba2a4611a5158cf58328a3750893a1fdee33cd94863c06ab4ac4` |
| Windows EXE | `6ef4338f7077d24d5c4483ff2874d765e0c0f2f403e1a3880b01eae9d418f879` |

NOT RUN：打包程序之间经网络的实际自动更新（需下一版本发布后验证）、Mac 更新下载流程实机、下载后的 Mac APP、学校采集/耗时、手机导入、最终包人工窗口和实际缩放。

<a id="rollback-sequential-20260929"></a>
## ROLLBACK-SEQUENTIAL-20260929：回到最初逐条读取（未发布）

**编号 / 日期：** ROLLBACK-SEQUENTIAL-20260929，2026-09-29。分支 `codex/ui-refresh-20260929`。用户用 `.18` 书签首次（全量）读取时，第 1 条详情即提示第 2/3 次尝试、第 9 条提示第 3/3 次尝试，要求回到最初读取方式：虽慢但不出现错误提示；并选择不保留增量读取。

**依据：** 本机三次原版逐条全量实采（`.10` 9-07、`.14` 9-27，各 134 次请求）均 0 次失败、0 次重试，耗时 4:55 与 5:12；并发版本（`.16`–`.18`）在同一学校接口上出现 15–45 秒超时、空详情和重试。

**改动：** `browser_transport.mjs`、`browser_capture.mjs`、`browser_ui.mjs` 及 `test_transport.mjs`、`test_capture.mjs` 以 `git restore --source=2c77b71~1` 恢复为并发改动前的版本；与 `2c77b71~1` 的差异只有修订号 `2026-09-26.14` → `2026-09-29.19`（`git diff` 核对）。撤回 `.16` 起的并发、`.17` 分档超时与失败降级、`.18` 增量缓存与空详情重读。另外两个浏览器模块在此期间未改。AGENTS 采集规则恢复为逐条读取，并保留今日实站验证结论（不带 MCSID 的按课程请求返回空）。安装页、发布脚本与使用说明中的修订号同步为 `.19`。

**遗留：** 用过 `.18` 的浏览器在教务页 localStorage 留有 `shsmu-sync-detail-cache-v1`（脱敏详情与账号摘要），`.19` 不读取也不写入；需要时可在浏览器中清除该站点数据。

**检查（Windows 11，Python 3.12.6 既有虚拟环境，Node 24.19.0）：** `check.py --python-timeout 1200` 退出 0；Python 248 项 239 PASS、9 SKIP；三组 JS PASS。书签 55,441 字符。本地测试 EXE 构建于本机隔离输出目录，冻结自检 PASS、frozen=true、书签 `.19`，SHA-256 `deb860699bf5c73dee21f73550b81ad7cada8d0061dac6e405748b8e1e45223d`。**NOT RUN：** `.19` 学校实采、手机导入、Mac 构建。应用版本仍为 `1.0.0-rc15`。

<a id="incremental-read-20260929"></a>
## INCREMENTAL-READ-20260929：空详情中止与详情增量读取（未发布，已撤回）

**编号 / 日期：** INCREMENTAL-READ-20260929，2026-09-29。分支 `codex/ui-refresh-20260929`。用户用 `.17` 书签实采失败（“学校未返回课程详情”，74/128），要求必要时重构读取逻辑，参考常见抓取做法。

**失败根因（本机诊断记录，`.17`，Chrome）：** 当日学校详情接口明显变慢：3 路并发时多数 5–8 秒，6 次 15 秒超时（重试后成功）。第 131 秒一条详情 4 秒内返回 `[]`，按原规则 `EMPTY_DETAILS` 立即中止。同次月表逐条读取为 0.3–1.4 秒，与以往一致，说明慢的是并发下的详情接口。

**吞吐上限：** 两次实采每 20 秒完成详情数分别为 10/13/15/10/8… 与 11/17/15/10/0/14/8/0；单请求约 1.2 秒，3 路时中位升到 1.4–2.5 秒并伴随 12–45 秒卡顿。最好情况约 0.8 条/秒，128 条至少约 2.5 分钟，客户端调度无法稳定达到 1–2 分钟。

**实站只读验证（用户授权，其已登录的 Chrome，Claude in Chrome；18 次串行 GET，间隔 1 秒）：** 6 个月表共 128 次课、11 门课程（CSID/CurriculumID/XXKMID/CurriculumType 组合）。对每门课以 `MCSID=''` 请求 `GetCalendarTable` 均返回 `[]`（100–260 ms）；首门课省略 MCSID 同样为 `[]`。接口只按排课 ID 返回，不存在按课程批量读取。首页脚本中未发现其他教学日历或教师详情接口（部分脚本片段被浏览器工具的输出过滤拦截，未绕过）。本地另比对三次采集：9-07→9-27 有 125/128 条详情完全相同，9-27→9-29 为 128/128。

**修复（书签 `2026-09-29.18`）：**

- `browser_capture.mjs`：详情增量读取。可选 `io.openDetailCache(account)` 提供本账号本学期此前已校验的回复；缓存中没有或无效的课次、未来 14 天内的课次，以及到期完整刷新时的全部课次都会重读，其余沿用并在记录上标 `cached_at`。采集文件新增 `detail_reads:{full,read,reused,refresh_days}`。空详情先按 3 秒、6 秒重读两次，仍为空才 `EMPTY_DETAILS`。请求仍逐事件、不合并 MCSID；记录顺序与配对不变。
- `browser_ui.mjs`：缓存存于教务页 `localStorage`（`shsmu-sync-detail-cache-v1`），只含脱敏回复和账号 SHA-256 摘要；账号、学期或范围不同即整体替换，损坏或不可用时全量读取。每 14 天自动完整读取；完成面板在沿用时显示条数并提供“完整重新读取”。每条新读回复即写入缓存，失败后下一次只需补读剩余部分。
- Python 导入未改：只校验每条记录的 `path/params/response`，额外字段忽略；完整性、身份和提交规则不变。书签压缩后 61,905 字符（上限 62,000）。
- AGENTS 采集规则同步更新。

**权衡：** 14 天以外课次的教师或内容变化，要等其进入 14 天窗口或下一次完整读取才会发现。共用电脑上，下一位同学登录并点书签会整体替换缓存，不会混用。

**测试：** `test_capture.mjs` 新增：空详情持续为空时读三次后停止、暂时为空时重读成功（等待 3000/6000 ms）；增量读取只读 14 天内与缓存无效的课次、沿用记录带 `cached_at` 且顺序和配对不变、空缓存全量读；真实生成书签在模拟 `localStorage` 与平移时钟下：首次全量、第二次 0 条详情请求、“完整重新读取”重读全部、换账号不沿用、缓存损坏时全量，缓存中不含电话等字段和明文学号。

**检查（Windows 11，Python 3.12.6 既有虚拟环境，Node 24.19.0）：** `check.py --python-timeout 1200` 退出 0；Python 248 项 239 PASS、9 SKIP；三组 JS PASS。另用生产采集器生成同一合成学期的全量与增量（1 读 3 沿用）采集，经 `CaptureSource` + `fetch_complete` + `normalize` 导入，标准化事件完全相同。本地测试 EXE 构建于本机隔离输出目录，冻结自检 PASS、frozen=true、书签 `.18`，SHA-256 `9925c9809a6b0f5bf81079a6dd361328662d22a3d34a5b13d2fc389e78281819`。

**NOT RUN：** `.18` 书签学校实采（首次全量与后续增量耗时）、Safari/Firefox/Edge 下 localStorage 行为、手机导入、Mac 构建。应用版本仍为 `1.0.0-rc15`。回滚：还原三个浏览器模块与修订号；缓存键 `shsmu-sync-detail-cache-v1` 残留无害，数据格式与 UID 不变。

<a id="fast-read-20260929"></a>
## FAST-READ-20260929：单次请求卡住导致整次读取退回慢速（未发布，已撤回）

**编号 / 日期：** FAST-READ-20260929，2026-09-29。分支 `codex/ui-refresh-20260929`。用户反馈：新版从教务网站读取仍需约 4 分 30 秒，要求优化到 1–2 分钟。

**根因（本人 2026-09-29 13:32 `.16` 书签实采记录，仅本机读取）：** 书签确为 `.16`，3 路并发生效。前 65 秒完成 41 条详情，并发下单条响应中位约 1.3 秒，学校未串行化请求。第 65 秒一条详情请求 45 秒无响应（TIMEOUT）；此时其他通道仍约 1.2 秒返回。按原规则“任何失败都永久退回单请求 + 1 秒间隔”，剩余 87 条每条约 2.6 秒，共 4 分 51 秒。同次还有 12、14、20、28 秒的单条卡顿。

**修复（`browser_transport.mjs`，书签修订 `2026-09-29.17`）：**

- 每次尝试的等待依次为 15/30/45 秒（原每次 45 秒）；卡住的读取 15 秒后单独重试，学校整体变慢时第三次仍等 45 秒。
- HTTP 408/429/5xx 仍立即退回单请求 + 1 秒间隔；429/401/403 仍停止排队请求。
- 单次超时或网络错误只重试该条，不再降低其余通道；同一次读取累计 5 次超时/网络错误后仍退回逐条读取。
- 并发上限 3、开始间隔 250 ms、逐事件请求、不合并 MCSID 均不变。AGENTS 采集规则同步更新。

**回放（虚拟时钟，按本次实采 6 个月表 + 128 条详情的首次响应耗时逐条回放，卡住请求视为不返回，重试按 1.3 秒）：** 旧传输 290.4 秒（实采 291 秒，模型吻合）；新传输 101.0 秒。对比：首次等待 8 秒/阈值 8 次为 93.1 秒；10 秒/阈值 5 次因 12–14 秒卡顿计为失败而退回慢速，274.1 秒，故选 15 秒/5 次。回放脚本与耗时数据留在本机，不提交。

**测试：** `test_transport.mjs` 新增 15/30/45 秒逐次等待、XHR 回退为第二次尝试（30 秒）、单次网络失败后仍并发、连续 5 次失败后逐条、503/408 立即逐条；原“任意失败即逐条”用例改为 503。新用例在旧传输上失败。`test_capture.mjs` 计时器改为识别三档等待。

**检查（Windows 11，Python 3.12.6 既有虚拟环境，Node 24.19.0）：** `check.py --python-timeout 1200` 退出 0；Python 248 项 239 PASS、9 SKIP；三组 JS PASS。本地测试 EXE 构建于本机隔离输出目录，冻结自检 PASS、frozen=true、书签 `.17`，SHA-256 `c0b19f75d3433531ef7b451d930902d988355c448b44a63cef1f7fc951a083f2`。

**NOT RUN：** `.17` 书签学校实采耗时、手机导入、Mac 构建。回放只证明本次记录下的调度结果，不代表学校其他时段的响应。应用版本仍为 `1.0.0-rc15`。回滚：还原 `browser_transport.mjs` 与修订号即可，数据格式与 UID 不变。

<a id="ui-refresh-20260929"></a>
## UI-REFRESH-20260929：界面改版、拖动缩放卡顿（BUG-009）与切页/启动提速（未发布）

**编号 / 日期：** UI-REFRESH-20260929，2026-09-29。分支 `codex/ui-refresh-20260929`，基于审计修复提交 `ff6b1f4`。用户要求：较大幅度优化界面；修复拖动改变窗口大小时的卡顿；降低打开和切换页面时的卡顿；首次引导简洁、重点突出。

**根因（Windows 11 / 200% DPI 实测，一次性内存基准）：**

- ttk 控件每次重绘都按控件面积分配离屏 pixmap。在 2160×1374 尺寸下，一个空 `ttk.Frame` 每步约 25 ms，`tk.Frame` 约 6 ms。整页大小的 ttk 容器和 Canvas 是缩放开销的主体；贴图主题不是主因（换成平面样式后仍需约 85 ms）。
- 内容列宽随窗口逐像素变化，所有标签随之重新换行、重排。
- ttk 滚动条单独每步约 10 ms。
- 每个原生子窗口的创建和映射约 1 ms，所以卡片的四个圆角标签（6 个窗口）每张约 7 ms。
- 启动时 `icalendar` 导入约 1.2 s（它只用于生成 ICS），`Theme()` 生成 LANCZOS 贴图约 315 ms。每次渲染首页都会完整重建 ICS，并多次读取、校验快照。

**改动：**

- `desktop_theme.py`：
  - 浅灰绿页面底色配白色圆角卡片。卡片是 Canvas 容器：边框和四个抗锯齿圆角作为画布项，代价接近普通方框。
  - 用 `place` 视口代替 Canvas 滚动。内容列最宽 720，更窄时按 60 取整（最小 420），拖动时只平移、不重排。
  - 用 frame 细滚动条代替 ttk 滚动条，保留拖动、点击翻页和滚轮。
  - 大面积区域用经典 Tk 控件；按钮、复选框、输入框、Notebook、Treeview 仍为 ttk。
  - 贴图按"样式 + 外围底色"懒生成，只对圆角超采样。
- `desktop.py`：
  - 新侧栏和页面骨架。
  - 引导精简：选择学期为一张卡；安装书签为三步，内嵌截取标注区域的安装图示（点击看未裁剪原图）；首次获取为两步。
  - 安全警告与隐私说明移到"帮助与排错"。
  - 等待、结果、手机导入、设置页迁移到卡片布局；逻辑与确认不变量不变。
- `desktop_service.py`：
  - `current()` 按 pointer 字节和快照 stat 复用已校验的快照。
  - 浏览器模块哈希每实例只算一次。
  - ICS 就绪快速路径：`local/desktop-apple.json` 记录已校验字节的哈希、run_id、schedule_hash、学期和应用版本。任何一项不符，或快照校验失败，都回到完整重建比对，仍按精确字节校验。
- `core.py`：`icalendar` 改为在 `export_ics()` 内导入。
- 测试：
  - 滚动和缩放用例改用新滚动区。
  - 新增：细滚动条跟随视图；拖动窗口边缘时列宽与换行不变；圆角颜色与底色一致；ICS 快速路径不重建且篡改、版本或学期变化时回退；快照缓存在新提交后失效；首页渲染不导入 `icalendar`（子进程）。

**性能对照（同机背靠背，旧 = `ff6b1f4` 临时 worktree，隔离合成数据，200% DPI，2162×1375）：**

| 指标 | 旧 | 新 |
| --- | --- | --- |
| 拖动缩放每步中位数（首页 / 帮助 / 结果 / 设置 / 设置详情 / WakeUp 指引） | 93–122 ms | 25–54 ms |
| 滚动每步中位数 | 8–47 ms | 0–18 ms |
| `AssistantWindow` 构造（已有课表首页） | 635 ms | 206–228 ms |
| 首页切换 | 177–201 ms | 72–99 ms |
| 设置 / 结果页切换 | 183–249 ms | 94–195 ms |
| 设置详情 / WakeUp 指引切换 | 188–254 ms | 191–229 ms（控件数量多，基本持平） |
| `import desktop` | 800–850 ms | 550–580 ms |

冻结 EXE 从启动到窗口出现约 2.6–2.8 s，新旧相同，主要是 PyInstaller 单文件解包和 Python 启动，界面改动不影响；本轮未改打包方式。

**验证：**

- `python -B -X utf8 check.py --python-timeout 900` 退出 0：Python 246 项，237 PASS、9 SKIP（Mac 专属与符号链接权限），三组 JS PASS。
- 源码 `desktop.py --self-test` PASS。
- 本地 Windows EXE（`build_desktop.py`）冻结自检 PASS（`frozen=true`，书签 57,507 字符）。
- 各页面截图人工核对：引导三页、等待、结果、帮助、设置、设置详情、WakeUp 指引、窄窗口。
- NOT RUN：学校实采、手机导入、Mac 构建与原生窗口、Windows 其他实际缩放、物理鼠标拖动验收。

**首页步骤清单（同日追加）：** 用户在 Chrome 删除书签后，已完成引导的首页没有明显的重新安装入口。

- 首页顶部改为"学期 / 课表书签 / 手机导入"三步清单。每一步显示状态，并可点击"更改""重新安装""查看文件与导入步骤"重新进入对应流程。
- 从清单进入书签页时，页首提供"跳过，回到首页"；首次使用、尚无已保存课表时不提供跳过。
- 等待页加入"复制书签安装页地址"，不离开等待即可重装书签。
- 不读取浏览器配置来判断书签是否存在（隐私边界，且跨浏览器不可靠）；书签是否可用，仍以成功收到课表为准。
- 新增用例 2 项。完整检查 248 项：239 PASS、9 SKIP；三组 JS PASS。

**已知限制：** Tk 只在 ASCII 空格处断行，中英混排的长句可能提前换行（改版前即如此）。

**回滚：** 丢弃本分支或逆向应用其提交。`local/desktop-apple.json` 只是可再生的校验缓存，删除后会自动回到完整校验。

<a id="audit-fixes-20260929"></a>
## AUDIT-FIXES-20260929：rc15 缺陷审计中已确认问题的源码修复（未发布）

**编号 / 日期 / 问题：** AUDIT-FIXES-20260929，2026-09-29。修复 rc15 全仓缺陷审计中已确认的问题：

- 诊断记录每条事件都全量落盘并扫描目录，导入耗时随保留日志数线性增长；
- 界面事件轮询一次出错即永久停止，窗口无法关闭；
- 同学期缩小或平移读取范围时，历史被丢弃、SEQUENCE 回退、摘要显示全部新增；
- `clean()` 删除 `<` 与其后 `>` 之间的课程文字；
- 输出文件被其他程序占用时遗留 `.tmp`，并给出“磁盘空间”提示；
- 选择文件期间等待到期，所选文件被静默丢弃；
- 已保存的未来采集时间（电脑时钟偏快）永久阻断之后的采集；
- 错误分类误导（空学期、新数据分支、已保存记录损坏）；
- 记录接近上限时，异常被挂到无关事件上。

**权限与改动范围：** 用户要求修复已明确的问题，并以 GitHub 最新发布为准。改动包括：

- `core.py`、`sync.py`、`desktop.py`、`desktop_service.py`、`diagnostics.py` 及对应测试；
- 本条记录、PROJECT_STATUS、AGENTS 说明；
- 书签缩短时另改 `prepare.py`、`desktop_smoke.py` 和重新生成的 `chrome-bookmark.html`（见下文）。

浏览器采集模块未改。

**基线：** GitHub 最新发布 `v1.0.0-rc15`（`4501d8e`）。公开 main `0812031` 在其后只改了三份文档，产品源码与发布标签一致。从 `origin/main` `0812031` 建立本地分支 `codex/audit-fixes-20260929`，已有工作区干净（仅未跟踪的审计报告）。

**复现：** Windows 11 / Python 3.12.6 / Node 24，合成数据和隔离临时目录。10 个新增回归用例在未修改的 `0812031` 源码上全部失败：8 FAIL、3 ERROR，其中一个 GUI 用例同时报告清理失败。诊断实验（128 事件，保留 0 / 50 / 100 / 200 个日志文件）：导入+导出 2.83 / 14.34 / 27.26 / 43.46 s。

**修复内容：**

| 问题 | 修复 | 回归用例 |
| --- | --- | --- |
| 诊断拖慢导入 | 普通事件最多每 1 s 落盘一次；开始、结束、失败、异常、取消、关窗立即落盘；目录清理只在估算超出上限或每小时执行；记录大小增量估算；不再逐文件 `resolve()` | `test_diagnostics.test_routine_events_do_not_rewrite_or_rescan_retained_history_each_time` |
| 异常挂错事件 | `event()` 返回是否已记录；未记录时只标 `EVENT_LIMIT` | `test_diagnostics.test_exception_is_never_attached_to_an_unrelated_event` |
| 轮询停止/无法关闭 | 每个事件单独捕获异常并显示错误页；`finally` 中重新调度；工作线程已结束时 `close()` 直接关闭 | `test_desktop.DesktopWidgetTests.test_page_render_failure_keeps_queue_running_and_window_closable` |
| 缩小范围丢历史 | 同学期范围变化：范围内事件正常协调，范围外的有效事件保存为不导出的 `retained_events`（保留 UID、修订、别名），范围恢复时按原 UID 匹配 | `test_desktop.DesktopTests.test_narrowed_same_semester_range_keeps_uid_revision_and_history` |
| `clean()` 删文字 | 只删除白名单 HTML 标签且不跨行；真实标签输出不变 | `test_sync.TimetableTests.test_clean_keeps_comparison_text_and_removes_only_markup` |
| 遗留 `.tmp` / 占用提示 | `atomic_write` 在 `finally` 中清理临时文件；PermissionError / winerror 5、32、33 提示关闭 Excel、WPS 等程序 | `test_failed_output_replace_leaves_no_temporary_file`、`test_error_copy_*` |
| 选文件时等待到期 | 对话框打开期间不计入等待期限；`submit_file` 失败时排队导入或明确提示 | `test_file_dialog_time_does_not_expire_the_waiter` |
| 未来采集时间阻断 | 已保存时间晚于当前时间 10 分钟以上时，允许导入并在变化提示中警告；正常的旧文件仍拒绝 | `test_saved_future_capture_time_does_not_block_a_later_capture` |
| 错误分类 | 空学期→“没有读取到任何课程”；新数据分支单独提示；非下载文件的 JSON/Key 错误→“已保存的课表记录无法读取” | `test_error_copy_does_not_misdirect_login_saved_record_or_open_file_failures` |

**改后回归：**

- `python -B -X utf8 check.py --python-timeout 900`（借用同机已有 `.venv`，依赖与 `requirements.txt` 一致；未安装依赖），退出 0：Python 240 项，231 PASS、9 SKIP（7 项 Mac 专属，2 项符号链接权限），0 FAIL/ERROR，160.3 s；三组 JS PASS。
- 加入书签缩短后再次完整检查，退出 0：Python 241 项，232 PASS、9 SKIP、0 FAIL/ERROR，165.6 s；三组 JS PASS。
- 同一诊断实验改后为 0.64 / 0.63 / 1.03 / 1.17 s。
- 审计复现脚本改后均显示预期行为；ICS/CSV 被占用时无遗留 `.tmp`。

**差异审查：** 本人逐行审查最终 diff，未做独立审查。

未修改的已知问题：

- 拖动改变窗口宽度时，每步 90–118 ms：剖析显示超过 97% 的时间在 Tk 内部重排/重绘，Python 回调约 2.5%，去抖无效，需另行调整主题贴图或布局，本轮不改。
- 并发采集遇到 429 即失败且不可续读：属于设计风险，缺少学校限流证据。

**书签缩短（同一分支的后续修改）：** 用户要求缩短书签以适配 Firefox。rc15 生成的书签为 71,583 字符，超过 Firefox 书签 URL 上限 65,536（`DB_URL_LENGTH_MAX`，出自源码记忆，Firefox 实测 NOT RUN）。

- **改法：** 采集模块一行未改。`prepare.compact_script()` 只在生成书签时去掉行首缩进、空行和整行 `//` 注释，并把中文写成 `\uXXXX` 转义，保留换行，因此自动分号插入不变。事先检查过，模块中没有跨行的字符串或模板字符串，也没有反斜杠紧跟中文的写法。反斜杠仍按原规则做百分号编码。
- **结果：** 书签长度降为 **57,507**（rc15 配置），生成时若超过 `BOOKMARK_LIMIT = 62000` 直接报错。
- **更新的文件：** 已跟踪的 `chrome-bookmark.html` 用原配置重新生成，只有书签地址变化；`desktop_smoke` 包内自检改为比对压缩后的模块内容。
- **验证：**
  - `test_capture.mjs` 从安装页取出生成的书签并实际执行完整采集流程，PASS；
  - 新增 `test_generated_bookmark_fits_firefox_and_contains_every_module`；
  - 源码模式 `desktop.py --self-test` PASS，报告 `generated_bookmark_length=57507`。
- **对现有用户：** 书签修订号仍为 `2026-09-28.16`，执行的代码语义不变，桌面“书签确认”指纹（按模块文件哈希计算）也不变。已安装 `.16` 书签的 Chrome/Edge 用户无需替换；Firefox 用户可安装新生成的书签。Firefox/Safari 实际添加书签和采集仍为 NOT RUN。

**兼容性：**

- 快照新增可选键 `retained_events`，仅在缩小范围后出现。旧程序读取时会忽略，但它的协调不会使用这些保留记录。
- `clean()` 改后，只有原本被误删文字的课程会在下一次采集时出现一次 CHANGED。这类课程在重新采集前，“重新生成导入文件”的 WakeUp 一致性检查会报告不一致；重新获取课表后恢复。

**实机验收：** 学校实采、Firefox/Safari 书签、手机导入、EXE/APP 人工窗口均 NOT RUN。本条只是本地源码修复，未提交、未推送、未发布，应用版本仍标 `1.0.0-rc15`。

**回滚：** 丢弃本分支，或逆向应用本分支的 diff。数据方面，只有缩小范围后的快照会包含 `retained_events`，不涉及删除或重置历史。

<a id="release-rc15"></a>
## RELEASE-RC15：滚动性能与读取修复双平台附件

2026-09-28，用户授权更新下载附件。基线为已合并 PR #9 的公开 main `2c77b711b9390e87b66c0771468af06d6fb481a4`，干净公开 checkout，新建 `codex/release-rc15`。仅修改版本、发布工作流、打包版本断言和维护/用户说明，保留产品修复、CMD 字节及个人目录。

候选 `1.0.0-rc15` / Mac 修订 9 / 构建号 `15.0` / 书签 `2026-09-28.16`。同一提交分别在 Windows 与 Mac 运行完整检查、原生构建和冻结自检，合包核对源码清单、书签、ZIP 及 Mac 符号链接；全部通过后发布新的预发布，保留旧 rc14 附件。本地发布准备检查：Windows / Python 3.12.6，`python -X utf8 -m unittest -v test_packaging test_platform_support test_diagnostics`，59 项：51 PASS、8 SKIP、0 FAIL/ERROR（24.361 秒，退出 0）。8 项跳过为 6 项 Mac 专属及 2 项符号链接权限场景；CMD 和清单外跟踪文件哈希未改变。两端完整检查和最终包证据待发布工作流执行。

真实学校采集/耗时、手机导入、最终 EXE/APP 人工窗口与实际缩放验收为 NOT RUN。源码和包内合成检查不能替代实机验收，也不宣称学校采集达到一分钟。

以上为发布准备记录。以下为本轮实际结果，未完成的实机验收仍保留 NOT RUN。

[发布工作流 36444937755](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36444937755) 全部 PASS；[rc15 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc15) 对应源码 `4501d8e5d63e9c2dd1b10919b38260193495d178`，提供六个附件。旧 rc14 附件保留，发布标签未重写。

| 本轮检查 | 实际结果 |
| --- | --- |
| Windows 原生完整检查 | 231 项：224 PASS、7 Mac SKIP、0 FAIL/ERROR，Python 114.273 秒，三组 JS PASS |
| Mac arm64 原生完整检查 | 231 项：230 PASS、1 Windows CMD SKIP、0 FAIL/ERROR，Python 90.962 秒，三组 JS PASS |
| 原生构建与冻结自检 | 两端 PASS；`frozen=true`、`python_on_path=false`、依赖和生成书签核对通过；Mac standalone ZIP 经中文空格路径 ditto 重解压，codesign 结构与再次冻结自检 PASS；不等于 Developer ID 签名或 Apple 公证 |
| 合包及线上回读 | PASS：两端源码和书签一致、ZIP 校验通过；六个附件名称及字节与待发布产物完全相同 |
| 本机独立回下载 | PASS：六个附件齐全、SHA-256、三个 ZIP CRC/成员、包间文件字节及 64 个 Mac 符号链接一致；25 项源码哈希与发布提交 Git blob 完全一致 |
| 下载后的 Windows EXE | PASS，退出 0；中文空格路径，隔离 HOME/用户/临时/课表目录，PATH 仅系统目录；`frozen=true`、`python_on_path=false`、rc15、书签 `.16` |

两端源码指纹：`e12547a6b70cb20dd0fdd7192580ce17dac16e85c7ebb3c120d0e3e358813452`。生成书签 SHA-256：`009c0d6d27ff9caa899a81fc8d584ff53140641f1b25eb853b185350a1a5bcb0`。

| 公开产物 | SHA-256 |
| --- | --- |
| SHSMU-Schedule-Assistant-1.0.0-rc15-Mac-arm64.zip | `f6b822afa0281db46dbbd7d1c711c69ff1fdd32ec89f234045842a79e848418e` |
| SHSMU-Schedule-Assistant-1.0.0-rc15-Windows-x64-Mac-arm64.zip | `99c36a25e33dab1a9153254d1bbc4ade5db8609ee586c998322b4353c5663aac` |
| SHSMU-Schedule-Assistant-1.0.0-rc15-Windows-x64.zip | `ed7d635902d0fe3046ecf599f52af575199eb080bdf240821444d25cb78f947c` |
| User-Guide.html | `608f066e24b77f403589a2cb40c59864d9fc907d6f76c1f1991ec6b35b0dede3` |
| build-verification.json | `bfa7c8d5b26685dae81cb3d02df003c22d529216479d2a802f9c7bb8f9233ee1` |
| Windows EXE | `fa3a10790b5141c2e26c5488b038b6b9095945ac0024feb514f333edf3c42be2` |

原始工作流日志、附件、审查脚本与 EXE 报告留在维护工作区忽略目录 `local/release-rc15/`。仅发布允许清单内的源码、通用说明和构建产物；不含个人课表、配置或原始学校数据。真实学校采集/耗时、手机导入、最终包人工窗口和所有实际缩放验收仍为 NOT RUN。

<a id="perf-ui-20260928"></a>
## PERF-UI-20260928：读取提速、Windows 滚动卡顿、Mac 字号与滚动条

- 问题（用户反馈）：128 次课程读取约 4 分钟；Windows EXE 滚动掉帧、先出边框后出内容、底部残影；Mac 字小留白多；滚动条样式陈旧。
- 基线：公开 `main` `8368647`，独立公开源码 checkout，分支 `codex/perf-ui-20260928`，改前无未提交改动。个人目录未修改。
- 用户在对话中明确授权详情读取最多 3 个并发，并相应修改 AGENTS 采集规则。

**读取速度。** 本人两次完整采集的本机执行记录（仅本地读取，未外传）显示 128 条详情响应中位约 1.16 秒，月表约 0.7 秒；原实现逐条串行且每次完成后固定等待 1 秒，估算 128 × (1.2 + 1.0) ≈ 4.7 分钟，与反馈一致。修复：`browser_transport.mjs` 增加上限 3 的在途请求计数、请求开始至少间隔 250 ms；任何失败或重试后本次读取器永久回到单请求、1 秒间隔。`browser_capture.mjs` 月表仍逐月顺序读取；详情先按原键去重，再由最多 3 个工作者读取，记录与请求一一绑定，按原行顺序写入 `responses`（Python 按请求键索引，与顺序无关）。出错后不再发起新请求，已发出的请求完成并进入续读检查点。未合并 MCSID。书签修订 `2026-09-28.16`，仓库示例安装页已重新生成。虚拟时钟下 128 条 1.2 秒请求在 60 秒内完成（测试断言；理论约 52 秒，另有月表和本地处理时间）；真实学校耗时 NOT RUN。

**Windows 卡顿根因。** 真实 Tk 窗口测量（合成课表，4 次滚轮为一组，48 组）：原版 100% 缩放 p90 1047 ms，150% p90 2224 ms、最长 2.3 s；Python 回调合计仅约 3 ms，时间全部在 Tk 绘制。对照实验排除图标透明度；将圆角背景图的平铺中心从 2–3 px 加大后 150% p90 降至 22–27 ms、总耗时 22.3 s → 0.8 s。原因：ttk 图像元素以**平铺**而非拉伸填充中心，卡片/按钮每次重绘需数万次贴图。修复：`desktop_theme.tile` 中心加至 200 px，并以 `width/height` 保持原 24 px 最小尺寸。另外，滚动移动内容框也会触发 `<Configure>`，原实现每步重设滚动区域并遍历换行标签（40 次滚轮触发 24 次）；现仅在尺寸变化时处理。改前改后 1.0 / 1.5 缩放下六个页面所有控件尺寸一致，仅因滚动条变窄，居中内容左移 2–3 px。

**Mac 字号与留白。** Aqua Tk 报告 72 dpi，原 `max(.75, dpi/96)` 使 Mac 所有字号与尺寸按 0.75 缩小（正文 14→11），而窗口仍按 1080 宽创建，导致字小、留白多。Mac 下限改为 1；内容列 746→860、内边距 58→40（Windows 不变）。仅静态推导，Mac 原生窗口 NOT RUN。

**滚动条。** 无箭头、无凸起边框；轨道与页面同色，约 8 px 中性灰圆角滑块位于 14 px 可拖动列，悬停/拖动加深；仍为真实 `ttk.Scrollbar`。已核对拖动区域识别与滑块长度随视图变化。

**检查（Windows 11，Python 3.12.6 既有虚拟环境，Node 24.19.0，2026-09-28）：** `check.py --python-timeout 900`：Python 230 项，220 PASS、9 SKIP、1 FAIL（`test_setup_cmd_real_exit_status_and_success_message` 的 2 个子场景）；三组 JS PASS。该 FAIL 为本机运行 CMD 时报 “not recognized”；在未修改的 `8368647` 工作树单独运行同样失败，属本机环境问题，本轮未改任何 CMD。新增：传输并发上限/间隔/失败降级/约 1 分钟模拟、采集乱序完成仍保持顺序与配对、失败后不再发起新请求、背景图最小尺寸与平铺中心、滚动条无箭头及滑块定位、滚动不重建滚动区域、Mac 字号（Windows 跳过）。

**复审修正（同日，书签改为 `2026-09-28.16`）：** 外部审查提出 3 项。(1) 已修：不可重试失败（429/401/403 等）后，排队中尚未发出的读取仍会发出；现以轮次标记取消，排队读取返回 `CANCELLED` 且不访问学校，之后的新读取正常。可重试失败耗尽后仍让已排队读取完成，以便“继续读取”保留进度。新增 429/401/403 用例，移除修复时该用例失败。(2) 已修：Windows 精细滚轮/触控板的 -30 等增量原被逐次截为 0；现累积余数，满 120 滚动一单位；Mac 不变。(3) 未改：整套主题均为固定配色，应用各处都未适配 Windows 高对比度，原滚动条同为浅色；仅改滚动条不能提供一致的高对比度体验，需要时应作为主题整体改动。复审后 `check.py`：Python 231 项，221 PASS、9 SKIP、1 FAIL（同上 CMD 环境问题）；修正后三组 JS PASS（采集组连续 3 次）。独立复核：(1)(2) 通过、可关闭；429/401/403 探针失败后发出 0 次请求；重建 EXE 的 25 个源码哈希与清单一致，自检 PASS、frozen=true、书签 `.16`。该 CMD 用例在复核环境单独运行 PASS，在本会话环境单独重跑仍 FAIL，判断为本会话执行 CMD 的环境差异；复核方未重跑全量。

**提交前全量复核（同日，Windows 11，Python 3.12.6，Node 24.19.0）：** 对上述复审修正后的源码运行 `python -X utf8 check.py --python-timeout 1200`，退出 0；Python 231 项：222 PASS、9 SKIP、0 FAIL/ERROR，耗时 219.466 秒；三组 JS PASS。9 项 SKIP 为 7 项 Mac 专属检查及 2 项当前 Windows 用户缺少符号链接权限的场景。本轮 `test_setup_cmd_real_exit_status_and_success_message` 在全量检查中 PASS；前述其他执行环境的 FAIL 记录保留，不据此宣称其环境问题已修复。仅补充维护记录，复核前后产品和测试源码字节未改变；18 文件提交清单已审查，CMD 原始字节与基线一致。原始日志留在本地忽略的维护证据目录。

**NOT RUN：** 学校短范围/完整范围实采与 10 条网页核对、真实读取耗时、各浏览器书签替换、Mac APP 构建与包内自检、Mac 原生窗口、实际显示器缩放下的肉眼滚动体验、手机导入。Windows 本地测试 EXE 已构建并冻结自检 PASS；源码独立复核范围见上，不能替代实机或学校验收。应用版本仍为 `1.0.0-rc14`，未发布。回滚：`git revert` 本分支提交；数据格式与 UID 无变化。

<a id="release-rc14"></a>
## RELEASE-RC14：医学绿界面双平台安装包

2026-09-27，用户授权合并与发布新安装包。PR #7 两次 Windows CI 均通过后合入 `main`（`ce218b9856af46460c5a68bdd313480e8418e5e6`）。在公开干净历史建立 `codex/release-rc14`；仅更新应用/Mac 版本、原有发布工作流和必要说明，保留采集器、服务层、CMD 原始字节及个人目录。

候选为 `1.0.0-rc14` / Mac 修订 8 / 构建号 `14.0` / 书签 `2026-09-26.14`。Windows 与 Mac 必须从同一提交分别完成完整检查、原生构建及 `frozen=true` 自检；合包核对源码清单、版本、书签和 Mac 符号链接，全部通过后创建新的预发布，不覆盖 rc13 附件。

本地已有 Windows Python 3.12.6 环境，在导入产品前隔离 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、TEMP、TMP 和 Downloads；`python -X utf8 -m unittest -v test_packaging test_platform_support test_diagnostics` 实际 58 项，50 PASS、8 SKIP、0 FAIL/ERROR（23.169 秒，退出 0）。8 项 SKIP 为 6 项 Mac 专属及 2 项缺少符号链接权限的场景。新版源码自检 PASS、退出 0、frozen=false（13.860 秒），不能替代安装包自检。

以上为准备阶段记录。以下为同日实际发布结果，不以准备状态替代最终证据。

[发布工作流 36317148883](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36317148883) 在源码 `b020baef05ae1456fa04a395d3e59780e52b3971` 上全部 PASS；[PR #8](https://github.com/lhwen686/shsmu-schedule-sync/pull/8) 合入 `main` 的提交为 `433087de22d96428bc2d38824696eca1596fa594`。[rc14 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc14) 提供六个附件，旧 rc13 附件保留。

| 最终检查 | 实际结果 |
| --- | --- |
| Windows 原生完整检查 | 226 项：220 PASS、6 Mac SKIP、0 FAIL/ERROR；Python 210.973 秒，三组 JS PASS |
| Mac arm64 原生完整检查 | 226 项：225 PASS、1 Windows CMD SKIP、0 FAIL/ERROR；Python 82.624 秒，三组 JS PASS |
| 两端原生构建与冻结自检 | PASS；`frozen=true`、`python_on_path=false`、依赖位于包内、生成书签一致。Mac standalone ZIP 在中文空格路径用 ditto 重解压，codesign 结构验证和再次冻结自检 PASS；这不等于 Developer ID 签名或 Apple 公证 |
| 合包及线上回读 | PASS；两端源码清单/指纹一致、ZIP CRC 与重复成员检查通过，六个公开附件名称及字节与待发布文件完全一致 |
| 本机独立下载审查 | PASS；六个附件齐全、SHA-256 一致、三个 ZIP CRC 和预期成员一致、单平台/双平台文件字节一致；64 个 Mac 符号链接类型和目标一致；包内每项源码哈希与发布标签 Git blob 一致 |
| 下载后的 Windows EXE | PASS、退出 0；中文空格路径，隔离默认数据/临时目录，PATH 仅系统目录，`frozen=true`、`python_on_path=false`；无真实学校/个人数据 |

两端源码指纹：`5cca1844f1a5d2a021596d6b3ef0cfb21542b8d2e91935b7b5bc02ff126c6649`。生成书签 SHA-256：`c1e53f85ad19f87c82e0b5850f2e183f80686846f1a54ed790df792493ac154f`。

| 公开产物 | SHA-256 |
| --- | --- |
| 双平台 ZIP | `751daa68ef1fc877e96a368903ac0f8767f361f227064277a987194a87d3ac4f` |
| Windows x64 ZIP | `c14f4f2edbfb1c063e12784419220b0c76565b284f50b0c92331e74b1fada689` |
| Mac arm64 ZIP | `61a1d7f42101d137d29faa7fb39e598b1fe2fc7c12c3215309a166330bbcbbed` |
| Windows EXE | `06d4b34feed9645b9f27acbbcf4a1e9593e7dc2eea1701c3a0e9c70801305659` |
| User-Guide.html | `56e132d8f9a5d1b3d6177160534d8fbe49cc41e1b5970c987cbb536ee8b778a1` |
| build-verification.json | `58fc793b47a59e08f7734aa30f3c07aa75ebc6a4d433d516599a25304b7b87e0` |

原始工作流日志、回下载附件、审查脚本及本机 EXE 报告留在维护工作区忽略目录 `local/release-rc14/`。本轮仅公开版本源码、通用文档和明确附件；CMD 与基线原始 CRLF 字节一致。学校实采、手机导入、其他电脑、最终安装包完整原生窗口及全部缩放验收仍为 NOT RUN，见学生验收表；本轮未改浏览器、个人课表、配置或服务器。

<a id="source-sync-20260927"></a>
## SOURCE-SYNC-20260927：桌面主题与测试生命周期源码整理

基线为公开 `main` / `b7abbbfa0de8ec7d911622e29ff336ed2abaa90c`。将已完成的 UI、Mac 适配、等待线程和 Tk 窗口测试修订整理为源码提交；本次没有继续修改产品或测试实现。提交清单限定为 `desktop.py`、`desktop_theme.py`、`build_desktop.py`、`desktop_smoke.py`、`test_desktop.py`、`test_desktop_theme.py`、本记录和 `PROJECT_STATUS.md`。

本轮在 Windows / Python 3.12.6、Tk 8.6.13、Pillow 12.3.0、icalendar 7.3.0 的已有环境中运行。导入产品前隔离 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、TEMP、TMP、Downloads，使用合成数据。

| 本轮检查 | 实际结果 |
| --- | --- |
| `python -X utf8 check.py --python-timeout 1200` | 226 项：218 PASS、8 SKIP、0 FAIL/ERROR；Python 275.412 秒，完整命令 278.079 秒，退出 0；三组 JS PASS |
| `python -X utf8 desktop.py --data-root ISOLATED --self-test REPORT` | PASS、退出 0、22.593 秒、frozen=false |
| 测试前后文件哈希 | 公开跟踪文件和新增源码字节无漂移；文档在测试结束后补记 |
| 冻结记录比对 | 71 个源码及配套文件与最终 Windows 冻结记录一致；历史验证文档另行保留 |
| 提交审查 | 明确文件清单；新增内容凭证/私人绝对路径模式扫描无命中；6 个 CMD 与基线字节相同且保持 CRLF；`git diff --check` PASS |

8 项 SKIP 为 6 项 Mac 专属检查、2 项当前 Windows 用户缺少符号链接权限的检查，不计为 PASS。
差异审查覆盖独立格式确认、显示哈希失效、忙碌状态保护、构建指纹、线程实际退出和临时目录清理，并对照服务层校验与本轮回归结果。

此前最终 Mac 回传材料的本机核验记录为 PASS：归档 SHA-256 `5f4510aebc1df218c62176bf3fbc37b571b70c01dc70d5adb7eb660747d440bc`，45 个成员、44 项校验和一致；25 项产品和 48 项测试依赖的安全文本规范化指纹与 Windows 对应集合一致。Mac 最终全量为 226 项：225 PASS、1 Windows CMD SKIP、3 组 JS PASS、源码自检 PASS；首轮非零退出保留在原记录中。本次仅复核现有记录及本地冻结身份，没有执行新的 Mac 运行，也不声称完整仓库 raw 字节一致或重建缺失的 Mac 执行器。

旧 UI-FINAL / WAIT-STABILITY 的 FAIL、BLOCKED 记录保留其原版本归属；最终修订已通过 Windows 本轮与上述 Mac 对应源码检查。底层 Windows I/O 原因仍为 UNKNOWN，有限回归不证明性能问题已修复。
本轮原始日志、文件备份和清单保留在维护工作区忽略目录 `local/source-sync-20260927/`。本次没有学校实采、真实 WebCal、书签安装、手机导入、原生窗口人工复验、EXE/APP 构建或新 Release；这些项目为 NOT RUN。现有 rc13 附件和版本保持原发布状态。

<a id="ui-windows-20260927"></a>
## UI-WINDOWS-20260927：医学绿桌面源码候选（未发布）

2026-09-27，在现场核对的公开 main `b7abbbfa0de8ec7d911622e29ff336ed2abaa90c` 干净副本上实施。保留 Tkinter/ttk、Pillow 和原服务层；新增 `desktop_theme.py`，统一侧栏、有限宽度内容区、步骤/学期/结果卡与焦点。覆盖首次引导、更新、等待/处理、双导出结果、设置概览及原编辑器、帮助、导入说明、作息表和错误/诊断对话框。

两张结果卡保存独立展示哈希，确认前重新核对相应就绪状态与精确文件哈希；已确认方框是只读回执。没有完整课表时回到引导，双导出失败不显示成功文案。首页的重新生成仍走 export_only。业务/采集器、版本、CMD 字节和参考资料未变；新展示模块已进入 BUILD_INPUTS，通过静态导入随原打包入口收集，Mac spec 不需要新增资源。

所有测试在导入产品模块之前隔离 HOME、USERPROFILE、LOCALAPPDATA、APPDATA、TEMP、TMP、Downloads 和诊断根。现有 Python 3.12.6 / Pillow 12.3.0 / icalendar 7.3.0 / Tk 8.6.13 环境，无新增依赖。

| 实际检查 | 结果 |
| --- | --- |
| 改前 test_desktop + test_platform_support | 78 项：72 PASS、6 Mac SKIP；退出 0。此前系统 Python 缺 icalendar 的 2 项导入错误单独保留 |
| 最终 `python -X utf8 -m unittest -v test_desktop test_platform_support test_desktop_theme` | 90 项：84 PASS、6 SKIP、0 FAIL/ERROR；退出 0 |
| `python -X utf8 check.py` 默认 180 秒 | Python 组超时，退出 1；三组 JS PASS；保留原日志 |
| `python -X utf8 check.py --python-timeout 600` | 218 项：210 PASS、8 SKIP、0 FAIL/ERROR；三组 JS PASS；退出 0 |
| 源码 `python -X utf8 desktop.py --self-test <隔离报告路径>` | PASS、退出 0、frozen=false；不代表 EXE/APP 验收 |

完整检查的 8 项 SKIP 分别为 6 项 Mac 专属检查、2 项当前 Windows 用户缺少符号链接权限的检查；未把 SKIP 计入 PASS。

最终三项检查的测试对象 SHA-256 均为 `548d9997e41f73f90be91ea58d8eaf94f560dc63ae389751925008fb8a140329`，每次运行前后相同；它涵盖实际产品/测试文件字节，不以 HEAD 代替未提交源码身份。产品 BUILD_INPUTS 指纹、逐文件前后哈希、未修改依赖及设计哈希另见本轮交接 manifest。

原生 Windows 11 / 200%（DPI 192，Tk scaling 2.668768）已核对主要页面、正常双卡/窄窗口堆叠、Tab/Shift+Tab、Enter/Space、滚动及焦点余量、选文件取消后继续原等待、CSV 与 ICS 各自 Explorer 定位、长设置页和诊断保存/隐私文字。客户区常规 2162×1375、窄窗口 1601×1041。诊断布局另有 100%/125%/150%/200% Tk **模拟**测试；真实 100%/125%/150% **NOT RUN**，没有改系统缩放。

原生截图、失败迭代、隔离启动器、原始日志和源码快照在维护工作区忽略目录 `local/ui-windows-20260927/`；交接包含简短对照图和必要原图。保留定稿文案、真实范围/数量/时间/差异和安全/恢复信息，因此部分页面需要正常滚动；Tk 字体、图标与禁用态有已说明的渲染差异。浏览器 file:// 被工具策略拒绝，computed style / DOM 边界实测 **NOT RUN**，未用其他通道绕过。原型与 PNG 字节未改。

本轮 Mac 原生、学校实采、真实书签安装、手机导入、其他电脑、EXE/APP 构建与安装包验收全部 **NOT RUN**。没有提交、推送、改远端、改版本或发布。Windows 共享源码冻结，等待 Mac 交接；此前发布与历史 PASS 仅代表其原来的版本。


<a id="release-rc13"></a>
## RELEASE-RC13：双平台预发布及回下载验收

2026-09-26，[PR #4](https://github.com/lhwen686/shsmu-schedule-sync/pull/4) 合入 `main`（`cee1b98de6e2d898ef161608006f527838d38233`），从该基线创建 `codex/release-rc13`。最终源码经 [PR #5](https://github.com/lhwen686/shsmu-schedule-sync/pull/5) 合入 `main`（`801e5023d2112106c869426661a929248468e9ea`）。[v1.0.0-rc13](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc13) 为预发布，标签指向 `bb0e97d1175509fe28d5eff78ff9907a0d4653a5`；应用版本 `1.0.0-rc13`、Mac 修订 7 / 构建号 `13.0`、两端书签版本 `2026-09-26.14`。只用公开源码与说明构建，个人目录、配置、课表和日志未进入发布包。

Windows 本地源码预检使用现有 Python 3.12.6、Node 24.19.0 与隔离合成数据。首轮 206 项 Python 中 1 FAIL、8 SKIP，原因是 Mac ZIP 用例仍硬编码“修订 6”；更正为当前 `MAC_PACKAGE_LABEL` 后，完整检查为 198 PASS、8 SKIP、0 FAIL/ERROR，三组 JS PASS，退出 0。源码 `desktop.py --self-test` PASS，报告 `frozen=false`，不冒充冻结程序验收。

首轮[原生工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36243131557)在 `6325d89` 上：Windows 完整检查、构建和自检 PASS；Mac 206 项中 1 FAIL、1 SKIP，构建、合包和发布被门禁跳过。FAIL 是新增文件定位测试只断言 `explorer.exe`，Mac 实际正确调用 `/usr/bin/open -R`。测试改为分别核对两端命令，修正后本机完整检查为 198 PASS、8 SKIP，三组 JS PASS，退出 0；产品文件定位实现未修改。

最终[原生发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36243606122)在固定源码 `bb0e97d1175509fe28d5eff78ff9907a0d4653a5` 上全部成功：Windows 206 项为 200 PASS、6 SKIP；macOS arm64 206 项为 205 PASS、1 SKIP。两端三组 JavaScript、适用 CMD 检查、原生构建和冻结程序自检 PASS；报告均为 `status=PASS`、`frozen=true`、`python_on_path=false`。合包门禁核对相同源码指纹 `2da46e038c2e9392a6eca18231d2b74049aeea37a40295f0d0802b745973feb2` 和相同书签 SHA-256 `c1e53f85ad19f87c82e0b5850f2e183f80686846f1a54ed790df792493ac154f`。发布步骤检查六个附件名称和字节，未替换 rc12 附件。

维护者再从公开 Release 独立回下载六个附件：全部与 `SHA256SUMS.txt` 和 GitHub 附件摘要一致；ZIP CRC、重复文件名、单平台与双平台成员逐字节相同，包内版本、书签、构建输入源码哈希、清单逐文件哈希及 54 个 Mac 符号链接目标均核对通过。Windows ZIP 再次解压至中文空格路径，限制 PATH 仅含 Windows System32，直接运行回下载 EXE 自检，退出 0 / PASS：`app_version=1.0.0-rc13`、`collector_revision=2026-09-26.14`、`frozen=true`、`python_on_path=false`、依赖与书签包内核对通过。本机原始日志和审计脚本仅留在忽略目录 `local/release-rc13/`。

| 公开附件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `SHSMU-Schedule-Assistant-1.0.0-rc13-Windows-x64-Mac-arm64.zip` | 42756222 | `9026ae01a6fdf577c8451c1be744dc71a120be4c525571e803a477e7b4e01761` |
| `SHSMU-Schedule-Assistant-1.0.0-rc13-Windows-x64.zip` | 24605525 | `f247c850b3d04149bd0c2f66258b99d14743a9ad20b90dfe3507f9bf9fab1412` |
| `SHSMU-Schedule-Assistant-1.0.0-rc13-Mac-arm64.zip` | 21228426 | `23332e9752f8fc7830b046c2bb184af3ee38bb7f5bec17238e8a12ca9a2fb0b6` |
| `User-Guide.html` | 4016101 | `78e11f2f481c58706c102bb3612230c503ca56efa44ea035fcfe5813062ee119` |
| `build-verification.json` | 2913 | `3ea51843092a5743d1a5e8ceea39d0279886786dc219bd3e6aad013a487eee8b` |
| `SHA256SUMS.txt` | 534 | `6315d2f648880be8256e409f299e9d287d14c11bce9a6b4f42d3939298a4f13b` |

当前版本真实教务短/全范围、至少 10 条网页核对、独立重复采集、iPhone 导入、其他电脑和完整原生窗口验收均为 **NOT RUN**。旧源码在 Windows 200% 缩放下的排错日志窗口裁切是已知问题，本次版本更新未宣称修复；参见 [rc13 学生验收](STUDENT_ACCEPTANCE.md#acceptance-rc13)。

<a id="ui-copy-public-20260926"></a>
## UI-COPY-PUBLIC-20260926：个人目录文案合入公开源码候选

公开 `main` 基线 `3145dcbb77224be46c2c44cc9f9e1fd206af7b50`；
集成分支从已推送的可靠性候选 `cdd52f9` 建立，保留该分支的参数契约与提交/输出边界修复。
个人目录 `main` 仍为独立历史 `6854e06` 且没有远端，故只用 9 月 26 日改前文件快照做三方合并，
没有提交或推送个人目录历史、部署脚本、配置、课表、诊断材料及本机视觉截图。

移植范围为桌面和浏览器显示文案、两类安装页、WakeUp 可读说明及相应测试断言；
适配 rc12 的 Safari/Mac 路径和分区采集面板，保留错误码、原始阶段、账号/范围检查、提交与输出状态、
诊断数据及独立双导出。书签模块变化后修订为 `2026-09-26.14`，重新生成示例安装页。
同步了项目协作约定和维护流程的个人目录新增约束；Windows CI 对完整 Python 组显式使用 600 秒诊断限时。
已发布的 rc12 软件包和用户现有书签没有改变。

本机 Windows / Python 3.12.6 / Node 24.19.0，全部使用合成输入及隔离目录：

| 检查 | 实际结果 |
| --- | --- |
| `python -X utf8 -m unittest -v test_desktop test_wakeup` | 68 PASS，退出 0 |
| 首轮 `python -X utf8 check.py --python-timeout 600` | 206 项中 1 FAIL、8 SKIP；失败是 Mac 下载目录用例仍断言旧按钮名，三组 JS PASS |
| 修正后定向 `test_platform_support.PlatformTests.test_unreadable_download_folder_has_actionable_error` | 1 PASS，退出 0 |
| 最终同一完整检查 | 206 项：198 PASS、8 SKIP、0 FAIL/ERROR，137.711 秒；三组 JS PASS，退出 0 |
| `desktop.py --data-root <隔离目录> --self-test <报告>` | 首次因旧首页标题断言 FAIL；更新断言后 PASS、退出 0，`frozen=false` |
| 静态生成书签核对 | 5 个模块均与 `.14` 安装页内嵌源码一致；公开示例配置仅含学期和日期范围，CMD 未修改 |

源码自检覆盖合班/分段课表的双导出、重复导入 UID/ICS 稳定、排错包脱敏、首次引导、
已有 JSON 重新打开及不可用数据目录拦截。首次失败的陈旧断言均已保留本机日志并修正，
最终测试和源码自检使用当前公开候选源码。`git diff --check` 及明确文件清单审查通过；
独立第二审查者 NOT RUN。

当前候选的 Windows 真实窗口、Mac 原生窗口、冻结 EXE/APP、新书签学校短/全范围采集、
至少 10 条网页核对、独立重复采集及手机导入均为 NOT RUN，不继承以前版本的 PASS。
9 月 26 日旧源码的 Windows 200% 缩放证据显示固定排错日志窗口裁切说明和保存按钮，
改前亦存在；当前公开候选没有重做该原生视觉验收，不能声称此问题已修复。
本机原始日志、三方合并预览和回滚快照只留在忽略目录。

<a id="reliability-mac-20260922"></a>
## VERIFY-20260922-MAC：固定可靠性提交的原生源码验收

验收源码固定为 `c9e196bfa2abfb8b38f90ebb081dda8468e5176f`，包含
`b157f9be4cfdadb57af82c23e23cb0da06fa243c` 参数契约修复及随后提交/输出边界修复。
执行前远端可靠性分支与此 SHA 相同，main 仍为 `3145dcbb77224be46c2c44cc9f9e1fd206af7b50`。
保留原 main 工作树，在独立临时工作树验证固定 SHA；本节仅记录验收，不重新实施修复。
下方 Windows 记录中的“原生 Mac 未验”和“未推送”属于当时状态。

环境：2026-09-22，macOS 27.0（26A428）、Apple M4 / arm64；已有 CPython 3.12.14、
Node v24.15.0、Tcl/Tk 9.0.4 / Aqua。经用户授权，仅在独立临时目录补齐
requirements.txt 依赖：icalendar 7.3.0、Pillow 12.3.0、tzdata 2026.3。
未安装或更换 Python/Tk，未修改全局环境。所有运行使用合成数据。

| 检查 | 本机实际结果 | 退出码 | 本地原始证据文件 |
| --- | --- | --- | --- |
| 初始定向检查 | 环境阻塞：缺少 icalendar，2 个模块未能加载 | 1 | `initial-targeted.log` |
| 初始完整 check.py | 环境失败：12 个包装用例通过、10 个模块加载错误；三组 JS 通过 | 1 | `initial-full-check.log` |
| 初始源码 self-test | 环境阻塞：导入错误触发启动对话框，未生成报告，终止本轮进程 | 1 | `initial-self-test-note.json`、`initial-self-test-startup.record.json` |
| 补齐依赖后的定向检查 | 夹具失败：15 个方法中 24 个错误子例，临时目录路径别名不一致 | 1 | `targeted.log` |
| 规范 TMPDIR 后定向检查 | 15 PASS：test_capture_contract 5 项、test_commit_boundary 10 项 | 0 | `targeted-canonical-tmp.log` |
| 完整 check.py --python-timeout 600 | 202 项：201 PASS、1 SKIP、0 FAIL/ERROR；Python 22.369 秒；三组 JS PASS | 0 | `full-check.log` |
| 源码 desktop.py --data-root <临时目录> --self-test <报告路径> | PASS；报告 status=PASS、frozen=false | 0 | `source-self-test.json`、`source-self-test.meta.json` |
| 原生补充矩阵 | 11 PASS：8 个已有用例复核、3 个额外用例，不加到完整套件数量上 | 0 | `native-supplement.log`、`native-supplement-results.json` |
| 真实写入中退出 | current.json 提交、wakeup.csv 导出两个阻塞点 PASS | 0 | `midwrite-quit.log`、`midwrite-quit-results.json` |

唯一 SKIP 为 `test_usability.UsabilityTests.test_setup_cmd_real_exit_status_and_success_message`，
原因 `Windows CMD entrypoint`，本机不能原生执行，不记通过。没有套用 Windows 的通过/跳过数量。

Windows 跳过的 6 项 Mac 场景均在原生 Aqua 执行：
`test_mac_quit_routes_through_safe_close_and_is_idempotent`、
`test_dock_reopen_keeps_the_same_service`、
`test_finder_failure_has_retry_and_keeps_export_state`、
`test_finder_timeout_is_nonblocking_and_does_not_invalidate_files`、
`test_command_w_closes_only_the_dialog`、
`test_safe_quit_cancels_before_commit_and_finishes_after_commit`。
两项包装场景也实际创建了符号链接并通过：
`test_mac_component_preserves_symlink_without_copying_target_bytes`、
`test_inventory_covers_both_files_and_symlinks_without_external_targets`。

原生窗口重开、已有 JSON 恢复、保存目录恢复、文件选择取消由完整套件覆盖。
额外调用 ShowPreferences / ShowHelp 系统回调，验证页面、service 身份和配置保持；
向已显示子窗口生成 Command-W 事件，验证仅目标窗口关闭，另一个子窗口和主窗口保留。
保存目录及下载目录选择取消也验证配置不变。Finder 非零退出与超时为合成故障注入，
验证反馈、非阻塞和输出状态保持，不代表实际制造了 Finder 故障。

安全退出使用真实 DesktopJob 非守护后台线程，并在 waiting、processing、committing、
exporting 四阶段分别阻塞，重复调用原生 Quit 回调。提交前取消保持旧指针；提交开始后等待完成。
另外在真实 `os.replace` 的 `data/current.json` 与 `output/wakeup.csv` 目标处阻塞，
验证锁仍被持有、退出没有销毁窗口或设置取消标志；解除阻塞后提交和两种导出完成，
重开可用，锁可重新获取。补充脚本保留在本地验收材料中，未写入产品或共享测试文件。

首轮问题分为环境与夹具两类，均保留失败原文：

- 环境缺少 icalendar。仅按本轮授权补齐临时目录依赖后复查。
- `test_commit_boundary.py` 对未 resolve 的 tempfile root 与已经 resolve 的
  DesktopService 路径直接执行 `relative_to`；Mac 的 `/var` 与 `/private/var` 别名
  导致故障注入器先于预期写入失败点抛出 ValueError。只把 TMPDIR 设为同一目录的真实路径，
  原样测试即通过。未修改共享文件；后续由共享测试负责人统一评估规范化场景 root。

初次 self-test 未传 data-root，启动异常曾生成一个默认目录诊断文件；仅将该次生成的文件
移入本地证据，后续入口使用显式临时目录。其他文件未修改。
本轮未发现已覆盖场景中的可确认产品缺陷，没有另开产品修复分支。

源码身份：APP_VERSION `1.0.0-rc12`，collector `2026-09-22.13`，frozen=false。
构建输入指纹 `f4cee301bbf3e00f8786404a9216be322c9eaf0f3e6e349d0c2a5d4f2458da4d`。
实际生成书签长度 55632，SHA-256
`04ad67a9c137b23b9d05d9351ac9b8ec44f0663c20aad9a5e1fe35be7f67bd79`。
现存历史 APP 仅核对 plist 与可执行文件哈希，未认定属于此 SHA，也未运行冻结自检。

验收边界：最终 APP/EXE、签名/首次打开、实际 Dock 点击、物理 Command-Q/W、菜单点击、
原生选择器取消按钮、真实外置盘/系统权限提示仍为 NOT RUN。
学校短/全范围采集、网页核对、真实浏览器与手机导入分别 NOT RUN，不继承历史 PASS。
本地套件的 WebCal 测试只使用临时回环服务，不代表线上上传。
审查由当前代理完成；独立第二审查者 NOT RUN。产品文件及共享测试在本轮保持不变。

完整验收表、原始日志、每次命令/时间/退出码、self-test、环境/冻结身份、文件哈希及补充脚本
仅保留在本地证据包 `Mac-native-c9e196b-20260922.zip`，不上传本机路径和诊断原文。
证据包 SHA-256：`ee9c2f091f2ead727f73fd08a3403c1e7f53e6b075c375d7b252986b7dd67d1b`。
本次文档提交可单独 revert，不回退可靠性修复，也不改变任何课表指针或历史。

<a id="reliability-commit-20260922"></a>
## BUG-20260922-02：提交与派生输出分别报告、分别恢复

基线为 BUG-20260922-01 的提交 `b157f9be4cfdadb57af82c23e23cb0da06fa243c`；
此次独立提交只处理保存/输出边界及相应验证。提交可用
`git log -1 --format=%H --grep='Separate committed snapshots'` 定位。

根因：`publish` 在原子替换 `data/current.json` 后调用 `repair_exports`，
任何派生写入异常会越过桌面的两种独立导出；导入开始时的修复同样会阻止重复文件或新文件恢复。
现在先完成不可变运行和当前指针，再逐文件尝试派生输出，返回原异常映射。
`ImportResult.committed` 表示返回的快照已提交，`duplicate` 区分同一文件，
`output_errors` 保留输出失败；提交前异常仍抛出，不能宣称新课表已保存。
当前指针和快照哈希验证不进入容错捕获，不回滚已确认的提交。

桌面始终分别尝试 Apple 与 WakeUp。结果中的 `committed`、`apple_report/apple_issue`、
`report/issue` 和 `output_issues` 分别表示课表、两种文件和辅助输出状态。
提交后 collector_revision 状态写失败也不能截断独立导出。
UI 仅补充必要的失败/恢复提示，诊断记录标记 partial 并保存原异常；未做视觉重构。
Apple 的短暂写失败如在独立重试中恢复，最终可用状态和原始诊断分别保留。
CLI 输出失败退出 1 并明确“已保存、未上传、可 --repair”，不把旧输出当成功结果。
桌面重新生成及 CLI --repair 都从当前完整快照恢复，桌面仍不上传 WebCal。

最小复现：`python -X utf8 -m unittest -v test_commit_boundary`。
实际进入 `import_capture_unlocked` / `DesktopService.run`，在 `os.replace` 注入定点失败：
首次/更新、运行目录或当前指针替换前、四个提交后派生文件、WakeUp CSV/说明/清单、
桌面状态、重复文件、提交前取消、提交中取消、重开和无新采集恢复。
保留锁、账号拒绝、UID/别名/sequence、取消历史和文件哈希的断言。
改前 7 个方法中出现 22 个错误子例，退出 1：16 个为真实后置写失败越过返回路径，
6 个为旧结果缺少新增 committed 字段，后者不单独作为根因证据。
改后首轮 7/7 PASS；补充 CLI/账号/状态写失败后 10/10 PASS，退出 0。
原始日志为 `local/reliability-20260922/commit-red.log`、`commit-green.log`、`commit-final.log`。

原生 Windows 源码验证（Python 3.12.6、Node 24.19.0；合成数据、临时目录）：

| 检查 | 实际结果 | 原始记录 |
| --- | --- | --- |
| 未修改基线 `check.py` | FAIL，退出 1；Python 180 秒限时，三组 JS PASS | `baseline-check.log` |
| 未修改基线 unittest discover | 187 项：178 PASS / 1 FAIL / 8 SKIP，退出 1 | `baseline-unittest.log` |
| 基线等待下载用例单独复查 | 1 PASS，退出 0；全套时 5 秒后台等待失败，未改该用例 | `baseline-waiter-recheck.log` |
| 首次完整 `check.py --python-timeout 600` | 202 项：193 PASS / 1 FAIL / 8 SKIP；三组 JS PASS，退出 1 | `final-check.log` |
| 旧 Apple 故障测试修正后复查 | 1 PASS，退出 0 | `apple-fault-recheck.log` |
| 最终 `check.py --python-timeout 600` | PASS，202 项：194 PASS / 0 FAIL / 8 SKIP，118.975 秒；三组 JS PASS，退出 0 | `final-check-r2.log` |
| 源码 `desktop.py --self-test <临时报告路径>` | PASS，退出 0；frozen=false，原生 Windows/Tk | `source-self-test.log` / `source-self-test.json` |

首次完整检查的单项失败源于旧测试只 patch `desktop_service.atomic_write`，
没有阻断新增共享恢复写入。现改为实际 `os.replace` 故障，保留原断言，未减弱文件校验。
`check.py` 保留默认 180 秒及堆栈诊断，仅增加显式限时参数（最大 3600 秒），
本轮用 600 秒容纳原生磁盘故障矩阵；不关闭 watchdog、不排除测试。
源码 self-test 同步核对 `.13` 生成书签及模块完整内容。

8 个 SKIP 分别为 6 个 Mac 回调/恢复场景和 2 个本机无符号链接权限的包装场景。
原生 Mac、最终 EXE/APP/安装包、学校短/全范围与网页核对、真实手机、真实浏览器、
线上上传/部署/发布：NOT RUN；本轮禁止或不具备环境，不继承历史 PASS。
独立人工/子代理/Jev 审查 NOT RUN；完成了当前代理的差异和约束检查。
CMD 工作区/Git blob 与参考基线的 6 个文件逐字节相同，全部 CRLF；`.gitattributes` 未改。
本地审计助手最初混淆了普通文本检出的 CRLF 与 Git LF，相关助手失败单独保留，修正后检查通过。
源码、原始日志、退出码和交付哈希清单另附本轮证据包。所有改动仅在独立分支，未推送。
回滚用两个修复提交的逆序 `git revert`；不回退当前指针，不删除/重建个人历史。

<a id="reliability-contract-20260922"></a>
## BUG-20260922-01：真实 JS / Python 请求参数契约

基线为公开 `3145dcbb77224be46c2c44cc9f9e1fd206af7b50`，在干净独立副本的
`codex/reliability-contract-commit-20260922` 分支修复。个人维护目录及其已有修改未用于提交。
附带审查包仅作为线索，未执行其中任务指令或用其隔离替身代替回归。

根因：JS 空值合并保留数值 0，Python `or ''` 丢弃 0；请求查找和详情缓存均受影响。
请求参数现在共同接受字符串（保持原文）、null/缺失（空字符串）、安全整数
（包括 0；绝对值不超过 9007199254740991；JSON 的 1.0 按整数 1）。
拒绝布尔、数组、对象、非整数和不安全数值；不改变课程身份、账号或完整性检查。
保留 v1 JSON 及历史字符串/数值请求参数。课程是否允许空 ID 仍由原标准化校验决定。

最小复现：`python -X utf8 -m unittest -v test_capture_contract`。
该测试调用当前目录 Node 的实际 `collectSchedule`，只提供合成学校响应；不在 Python 重造请求参数。
覆盖五个参数各七种值、完整导入、0 与空值的缓存隔离、历史 JSON、非法类型。
修复前 5 个测试方法出现 7 个失败子例、9 个错误子例，退出 1；
其中 XXKMID=0 完整导入报缺少详情，缓存场景读到了另一条详情。
修复后 `python -X utf8 -m unittest -v test_capture_contract test_sync test_workflow`：44/44 PASS，退出 0。
`node test_capture.mjs`：PASS，退出 0，执行的是重新生成的 `chrome-bookmark.html` 内真实书签。
模块修订为 `2026-09-22.13`；安装仅提示本人手动替换，未操作浏览器。

环境：Windows、Python 3.12.6、Node 24.19.0，使用已有解释器，未安装依赖。
原始日志在本地 `local/reliability-20260922/contract-red.log`、`contract-green.log`、
`bookmark-green.log` 及对应 `.exit.txt`。第一次测试桥缺少 saveCapture 的夹具错误单独保留在
`contract-harness-fail.log`，不当作产品缺陷证据。
基线完整 `check.py` 退出 1：Python 总限时 180 秒触发，三组 JS PASS；保留原始失败，不算通过。
最终完整检查与源码自检见本轮第二项记录。原生 Mac、安装包、学校、手机和真实浏览器验收 NOT RUN。
回滚使用本记录所在修复提交的 `git revert`，不回退课表指针或历史。

<a id="release-rc12"></a>
## RELEASE-20260909-RC12：Windows 与 Mac 同步分发

症状：Mac 修订 5 已包含 `.12`，此前交付的 Windows 修订 3 仍内置 `.10`；更新应用也不会自动替换浏览器保存的旧书签。
用户授权完整同步后上传 GitHub。基线 HEAD `9122ba7f7ed30bcf6627a5162e993c51eedb2b1c`，保留原有未提交修复，按明确文件清单整合 Safari、采集面板和 Mac 包装修复。

版本：两端统一 `1.0.0-rc12`；Mac 修订 6、构建号 `12.0`；浏览器模块保持 `2026-09-08.12`，本轮不改变采集范围、请求、UID 或导出协议。
包内自检读取实际生成的安装页，校验全部浏览器模块、`.12` 标识及书签完整地址。合包必须匹配两端全部源码哈希和应用版本。
新增工作流只在 `codex/release-rc12` 的受授权推送触发，两端通过后合包校验并创建新的 rc12 预发布；不覆盖旧版附件。发布 job 单独取得 contents:write，构建 job 只读且不保留 checkout 凭据。

本机 Python 3.12.14 完整检查退出码 0：187 项中 186 通过、1 项 Windows CMD 跳过；三组 JavaScript 通过。源码自检退出码 0，实际生成的 `.12` 安装页包含全部浏览器模块。
本机新 Mac APP 已通过隔离冻结程序自检（PATH 无 Python、依赖位于包内），独立 ZIP 在中文及空格路径重新解压后，严格深度签名结构检查和冻结程序自检再次通过。生成书签长度 54857，SHA-256 `01b838f324f0ca6999f56f729ab4f5ffa1ed2ce9b2ad215d503adaf8a3d211fb`。
发布前 27 项源码/测试/说明/工作流白名单检查通过；990 个个人及旧交付文件未变，6 个 CMD 的工作区和 Git blob 均保持 CRLF，说明配图与既有公开版本相同。远端树与已审查的本机暂存内容逐字节一致。
首次云端运行 `34256671110` 在 setup-python 阶段失败：官方清单的 Python 3.12.14 仅有 Linux/RHEL 预编译包，Windows 与 Mac 均未进入项目检查或发布。根据官方 versions-manifest 核对，云端构建固定改为两端均提供的 Python 3.12.10；本机 3.12.14 结果保留原归属。
发布前用隔离 checkout 复现 Windows 的换行转换；两次 Windows EXE 组件回读均确认 requirements、config、spec 与 HTML 共 5 个输入因换行而与本机不同。仅关闭 autocrlf 仍会让 text=auto 使用平台默认 eol，故发布工作流对临时 runner 的 Git 子进程同时指定 core.autocrlf=false 和 core.eol=lf；保留仓库 `.gitattributes` 和 CMD 的 -text 原始 CRLF，不改变用户电脑的 Git 设置。
云端 Mac/Tk 8.6 检查在原生窗口用例停滞，首次 Windows 源码完整检查、EXE 构建及包内 `.12` 自检已通过。统一检查入口增加 180 秒限时堆栈诊断；运行 `34258231428` 定位到 `test_reopened_setup_imports_existing_json_and_exposes_both_exports` 的 `window.update()`，堆栈显示处理线程已结束、主线程仍在 Tk 的全队列处理。测试现先关闭旧窗口，再用与应用一致的 mainloop 和 Tk 定时器执行重开验证，保留 5 秒期限与所有导入、双导出、书签确认及历史断言；不跳过用例或放宽发布门禁。中间逐事件尝试的本机断言失败亦保留在本机证据中。
最终 [原生构建/合包/发布 34259584284](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/34259584284) 四个 job 全部 PASS；发布源码 `91fd600adf3ac263c76e9bb7667211ff5d4bbd1c`。
Windows Server 2025 / Python 3.12.10：187 项 Python 中 181 通过、6 项 Mac 专用用例跳过，真实 CMD、三组 JS、EXE 冻结运行时与生成书签自检通过。
macOS 15 arm64 / Python 3.12.10：187 项 Python 中 186 通过、1 项 Windows CMD 跳过，三组 JS、原生 APP 构建、包内自检、中文空格路径重解压及严格深度签名结构检查通过。
同一提交的 [Windows push 检查](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/34259584255) 与 [PR 检查](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/34259590609) 也通过。

[rc12 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc12) 包含双平台 ZIP、两个单平台 ZIP、User-Guide.html、build-verification.json 和 SHA256SUMS.txt。
六个附件回下载后核对 SHA-256、ZIP CRC、平台清单、所有构建源码、1046 个 Mac 文件及 54 个符号链接，Windows PE x64 及 EXE 内嵌 browser_ui.mjs 与源码完全一致。
统一源码指纹为 `098cbc1c5345bdf92ea6fa06183983918be2e8814402cbfbceb7f481e393cb77`；两端实际生成的 `.12` 书签长度及哈希与上方本机记录完全一致。
最终 CI Mac ZIP 在本机 macOS 26.6.2 arm64 的独立中文/空格路径重新解压，严格深度签名结构检查及 PATH 无 Python 的冻结程序自检再次 PASS，使用临时合成数据，不触碰原课表目录。

首次上传时 GitHub 将外置中文使用说明规范化为 default.html，导致校验清单中的文件名无法直接匹配。已将该附件改名为 User-Guide.html，仅替换对应 SHA256SUMS.txt；说明内容和三个软件 ZIP 字节未变，旧版本附件未动。修正后的六个公开附件已再次回读通过。合包脚本改用 ASCII 外置附件名，ZIP 内中文说明名保持，发布工作流新增上传后附件名称与全部字节回下载核对。用最终原生附件回放修改后的合包脚本，外置名称、校验清单和全部 ZIP 条目内容核对通过；工作流 YAML 与 Python 语法检查通过。

| 公开软件附件 | SHA-256 |
| --- | --- |
| Windows x64 + Mac arm64 | `d311e613a79a30b9bcf7608454fe4f77fa511df61cc08748c95ba8ef18bf9fb1` |
| Windows x64 | `a9f3ced7c8574bb03f077a0040ef417d2fc9088f4b4c4078022af8fbe3e4efcd` |
| Mac arm64 | `77750a4dd129eeb1b38b011ecfecb18d859c493163a9b45d52998ef532ceaab7` |

[PR #3](https://github.com/lhwen686/shsmu-schedule-sync/pull/3) 已合入 main，合并提交 `af3c9cd0d9cdcd6925cf45835a9e78e9f052241f`。发布标签保持指向原生构建源码，后续交付记录与附件命名/回读门禁修正不改动软件构建输入。
个人数据、配置、原始响应和本机证据保留本机，没有重新采集学校或操作个人日历。
审查方式：维护助手阅读最终差异并执行白名单、敏感内容、CMD CRLF 和保护文件哈希检查；独立第二审查者 NOT RUN。
实机边界见 [rc12 验收](STUDENT_ACCEPTANCE.md#acceptance-rc12)。此前 Safari `.11` 及旧包的学校或本人确认不转记到 rc12。
回滚依据：保留旧 Windows/Mac 交付 ZIP 和改前源码备份，使用新的版本号与新附件；源码恢复用反向提交，不重写公开历史，不重置个人 UID 或数据目录。

本页用于按问题和版本查证据，不要求每次维护通读。当前程序基线见 [PROJECT_STATUS](PROJECT_STATUS.md#baseline)，检查命令与适用条件见 [MAINTENANCE](MAINTENANCE.md#verification-gates)，学校、手机及设备验收见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

<a id="evidence-index"></a>
## 证据索引

| 要核对的事项 | 阅读位置 | 适用边界 |
| --- | --- | --- |
| Mac 源码适配与本机真实采集 | [FEAT-20260907-MAC](#macos-local-trial) | Apple 芯片、Chrome、原生窗口；手机和发行包另验 |
| rc11 执行日志与排错包 | [FEAT-20260907-01](#diagnostics-rc11) | 自动记录、脱敏重放、浏览器元数据、包自检与发布证据 |
| GitHub 源码同步 | [2026-09-07 同步](#verification-github-sync-20260907) | 今日修复与实测收尾已推送 main 并回读确认；Release 附件未更新 |
| 当日 bug 收尾与实测 | [2026-09-07 收尾](#verification-bugs-closed-20260907) | 当日 3 个 bug 已关闭；实测 PASS（用户确认） |
| 混合排课详情响应 | [BUG-20260907-03](#bug-mixed-details-20260907) | 已关闭；rc10 修复、离线回放及用户当日实测确认 |
| 合班及分段排课兼容 | [BUG-20260907-02](#bug-combined-classes-20260907) | 已关闭；rc9 修复由 rc10 保留，用户当日实测确认 |
| 只下载到 JSON 的继续入口 | [BUG-20260907-01](#bug-json-handoff-20260907) | 已关闭；rc8 修复由 rc10 保留，用户当日实测确认 |
| 本次维护文档整理 | [DOCS-20260907-01](#docs-maintenance-20260907) | 仅文档；应用与实机测试未运行 |
| rc7 候选版检查和发布 | [rc7 记录](#verification-rc7) | 对应历史源码和产物，不等于当前实机验收 |
| 首次启动 / 双导出 | [rc6 记录](#verification-rc6) | 本地与包内检查；手机另验 |
| 书签修正版 8 / 浏览器兼容 | [采集器记录](#verification-collector) | 合成检查不替代目标浏览器学校实采 |
| 旧书签修正版 5 的实采闭环 | [真实重复采集](#verification-live) | 原账号、原范围、原书签版本 |
| 最初接口和完整性验收 | [核心记录](#verification-core) | 原始观察日期及环境 |

<a id="record-template"></a>
## 新修复记录模板

后续在本页“维护记录”区域按编号追加，PROJECT_STATUS 只保留当前事项链接。复用现有 test 文件和忽略的证据目录；不另建一套任务台账。

```text
编号 / 日期 / 问题：
权限与改动范围：
基线仓库 / 分支 / HEAD / 已有未提交改动：
复现环境与数据类型（合成、既有快照回放、真实采集、用户反馈）：
步骤 / 预期 / 实际 / 改前失败证据：
修复内容 / 对应测试文件及用例：
改后回归：命令、环境、时间、退出码、实际通过/失败/跳过数、证据：
差异审查：方式、检查对象、结果、未解决事项（独立审查未做须注明）：
实机验收：对象版本及文件哈希、对应 STUDENT_ACCEPTANCE 项目、PASS/FAIL/NOT RUN：
提交 / 应用版本 / 书签版本 / 产物哈希 / 发布状态：
回滚文件或提交 / 数据兼容性 / 未运行及限制：
```

PASS、FAIL、NOT RUN 和不适用的含义以 MAINTENANCE 为准。原始个人课表、账号、凭证或私人配置不写入记录；敏感证据只在本人忽略目录保管，公开版本只写脱敏摘要。当前记录提交由 `git log -1 --format=%H -- VERIFICATION.md` 定位；后续存在更多记录时按问题编号查历史。

## 维护记录

<a id="mac-r5"></a>
### BUILD-20260909-MAC-R5：交付包含 Safari 与新面板的 Mac 软件

- 用户要求打开助手软件；本轮授权为本地构建与文件交付，未重新采集学校或公开发布。
  基线 `codex/dual-platform-package-local` / `9122ba7f7ed30bcf6627a5162e993c51eedb2b1c`，
  保留全部既有未提交工作；改前 63 个源码文件及 973 个个人/旧包文件已记录哈希。
- 产物包含已有 Safari `.11` 适配与 `.12` 面板源码；本轮仅把 Mac 标签/构建号更新为
  `Mac 修订 5` / `11.5`，同步包内说明、使用说明、包装测试及包内自检版本断言。
- 初查 FAIL：包装测试仍断言“修订 4”；初次包内自检仍断言构建号 `11.4`。
  更新对应断言后重新完整检查、构建和打包。初次失败日志和中间 ZIP 单独保留，不作为交付文件。
- 最终完整检查 PASS：Python 3.12.14 / macOS 26.6.2 arm64，执行 `python -X utf8 check.py`，
  187 项 Python 中 186 通过、1 项 Windows CMD 跳过，三组 JavaScript 通过，退出 0。
- 构建和打包 PASS：PyInstaller 6.22.2，使用 `build_desktop.py` 的独立输出/工作目录和
  `package_desktop.py --mac-only`；应用、说明、清单、ZIP 校验值相互一致。
  ZIP SHA-256：`b90041515d4ba62d4d69d35b8b0a1704f6d1d9e9f187dc119e3cff567be4a680`；源码指纹：`3e4924723a4cd7b9d0adf410bb69ba05e530539fe6431e454577f4efd0fa4f6c`。
- 最终 ZIP 回读 PASS：954 条记录，854 个 APP 普通文件、47 个符号链接；CRC、白名单、
  UTF-8 文件名、可执行模式和全部校验值通过。24 个原生二进制最低版本均为 11.0.0。
  在新的中文及空格路径解压，移除 Python 环境变量并隔离 PATH；包内自检退出 0，
  `frozen=true`、`python_on_path=false`、依赖均位于应用包内；深度严格签名结构检查通过。
- 普通启动 PASS：从最终 ZIP 解压 APP 使用独立数据目录，原生窗口显示学期选择页；
  Tab/Space 可进入书签引导，实际生成的安装页包含 Safari 和 `2026-09-08.12`；Command+Q 退出。
  自动化坐标点击未切页，改用键盘完成；本人鼠标/触控板验收 NOT RUN，不继承修订 4 的确认。
  窗口工具退出后读取状态触发重新打开，已再次关闭并核对无测试进程。
- 差异审查 PASS（单代理）：版本和说明为本轮变动，业务算法、学校请求、CMD 及图示数据未变；
  973 个保护文件和文件清单保持不变。独立审查 NOT RUN。
- 新包学校短/全范围、详情交叉核对、独立重复同步、手机及其他系统 NOT RUN；
  先前 `.11` 的实采与 `.12` 的 Safari 本地示例各保留原对象归属。
  本次签名检查仅为结构检查，不是 Developer ID 或 Apple 公证。
- 未提交或发布；旧 Mac 修订 4 ZIP 保留。回滚只恢复本轮改前备份的明确文件，
  不恢复整个仓库或个人课表目录。最终源码、日志、原生截图、包内报告与 ZIP 位于本机交付目录。

<a id="collector-ui-20260909"></a>
### FEAT-20260909-UI：采集面板信息层级与布局

- 用户截图反馈：标题把“课表采集”、完整修订号和原始学期标识排列在同一行。
  本轮限定为界面优化；不重新采集学校，不重打包、提交或发布。
- 基线仍为 `codex/dual-platform-package-local` / `9122ba7f7ed30bcf6627a5162e993c51eedb2b1c`；
  原有 Mac 与 Safari 未提交修改已保留。改前 63 个源码文件、差异与哈希已在本机备份。
  视觉问题由用户截图和 Safari 中旧 `.11` 面板确认，不为纯样式编写改前失败断言。
- 改动：`browser_ui.mjs` 使用独立标题、中文学期、状态标记和按钮区域；版本号置底；
  完成后突出下一步，原有下载与导入说明可展开；窄窗口按钮换行。
  继续采集清空旧操作区，重复复制复用排错区域；内容使用 `textContent`，不注入响应 HTML。
  `test_capture.mjs` 的现有 DOM 模拟改为递归查找，保留下载、失败、恢复和账号校验断言。
- PASS：macOS arm64 / Python 3.12.14，执行 `python -X utf8 check.py`，退出 0；
  187 项 Python 中 186 通过、1 项 Windows CMD 跳过，三组 JavaScript 通过。
  生成的仓库书签及本机全学期安装页均逐字核对当前五个浏览器模块，版本为 `2026-09-08.12`；
  本机安装页 SHA-256 为 `54bfbaa08e9ac3686d683ea7f8e8c19207cec4ea400b05d199305982168944cd`。
- PASS（Safari 本地示例）：标准宽度与 360px 窄窗口；采集中、完成、失败、下载受阻、登录提示；
  说明展开/收起、失败后继续采集不重复按钮、关闭提示。示例不访问学校，下载调用被拦截，
  不生成可导入个人课表的文件。截图、检查输出和本轮差异仅留本机证据目录。
- 差异审查 PASS：单代理逐段审阅本轮差异，学校请求、采集内容、身份/UID、导出和 CMD 未修改。
  独立审查 NOT RUN；内置浏览器连接失败，已改用原生 Safari 验证，不以其他浏览器推定 Safari 通过。
- NOT RUN：`.12` 用户手动书签替换及学校短/全范围、网页核对、重复同步，当前 UI 请求未扩展到实采。
  `.11` 的真实学校结果保留原版本归属；现有 APP 包不含本次 UI，未重新构建。
- 回滚：仅从本轮改前备份逐项恢复 `browser_ui.mjs`、`test_capture.mjs`、`chrome-bookmark.html`
  及本轮维护文档；不得用 Git HEAD 或旧包覆盖其他未提交修改，也不重置个人数据。

<a id="safari-adaptation"></a>
### FEAT-20260908-SAFARI：Safari 安装、诊断与本机采集

- 2026-09-08；用户要求适配 Safari，并提供已正常登录的教务首页。
- 基线 `codex/dual-platform-package-local` / `9122ba7f7ed30bcf6627a5162e993c51eedb2b1c`；
  保留 Mac 修订 4 和既有全部未提交修改。改前源码、差异和个人文件哈希在本机单独备份。
- 合成复现：生成书签在 Safari UA 下把 `diagnostics.browser` 记录为 `unknown`；
  `test_capture.mjs` 新场景改前退出 1。浏览器和 Python 脱敏白名单也未包含 Safari。
- 修复：识别 Safari 并仅记录浏览器类别；补齐个人收藏栏、编辑地址、本地文件打开和
  下载恢复引导。安装页版本从采集器读取，避免旧版 `.9` 文案与实际 `.10` 不一致。
  学校请求、采集格式、账号哈希、UID 和导出算法保持原样。
- 完整检查：已有 Python 3.12.14 / macOS arm64 环境运行 `python -X utf8 check.py`，
  退出 0；187 项 Python 中 186 通过、1 项 Windows CMD 跳过；三组 JS 通过。
  新用例覆盖 Safari 与 Chrome/Edge/Firefox/unknown 标签、完整 UA 不落盘及重新下载不重采。
- 书签版本 `2026-09-08.11`；重新生成仓库安装页和本机短/全范围安装页。
  Safari 26.6.2（21624.5.1.11.3）已显示本地安装页及正常登录的教务首页。
- 本人确认手工添加短/全范围书签。首次短采 FAIL：HTTP 200、67 字节 JSON，
  `Title/List/List2/StuExam` 均为 null；采集器拒绝完整下载，保留诊断和旧课表。
  正常从首页打开“我的课表”、看到课程后回首页，同一 `.11` 书签短采 PASS。
  观察支持“先进入学校课表页”这一恢复步骤，未检查服务器或凭据，不能断言底层会话原因。
- 学校验收 PASS：短范围 17 次/18 响应；完整与独立重复均为 128 次/134 响应；
  27 张 Safari 月课表卡片、12 条打开的详情以及全部 CSV/ICS 回读核对通过。
  重复文件时间和哈希不同，duplicate=false，差异 0/0/0；原 UID/别名/时间/sequence 保留，
  双导出字节一致。多段内容按组成部分和教师集合核对，展示顺序不作为课表变更。
- 最终完整检查退出 0：187 项 Python、186 通过、1 项 Windows CMD 跳过；三组 JS 通过。
  最终实际生成安装页在 Safari 显示基础功能检查通过，`.11` 书签字节与当前模块对应。
  323 个原个人文件哈希保持，改前 Mac 修订 4 桌面源码服务导入 `.11` 也得到相同双导出。
  本机证据为 Safari 适配验收目录的最终检查、源码自检、改动与保护核对、旧源码兼容记录，
  及独立 Safari 验收目录的三次 capture/result、网页观察和回读验证；个人材料不公开。
  实机边界见 [Safari 验收](STUDENT_ACCEPTANCE.md#acceptance-safari)。
- 本轮未构建、提交、推送或发布；旧 Mac 修订 4 ZIP 保留。独立第二人审查 NOT RUN。
  回滚只依据本轮改前副本恢复本轮修改，不能用 Git HEAD 覆盖前轮未提交工作。


<a id="mac-r4"></a>
## BUG-20260908-MAC-R4：Mac 恢复、退出与独立包

权限：按用户确认的 Mac 修复计划执行，仅本地源码与独立 Mac 验收包，不提交、推送或发布。
基线分支 `codex/dual-platform-package-local`，HEAD `9122ba7f7ed30bcf6627a5162e993c51eedb2b1c`。
原有修改为 build_desktop.py、desktop_service.py、desktop_smoke.py、test_desktop.py、使用说明.html，
另有未跟踪 package_desktop.py、test_packaging.py；全部先备份再增量修改。

改前复现：合成偏好 `[]` 导致启动钩子 AttributeError；原数据目录失联后保存设置仍会创建目录；
Mac 系统 Quit / Dock 回调缺失；Finder 子进程失败未检查；现有包版本字段为 0.0.0。
新增首轮 6 项回归均未通过（2 FAIL、4 ERROR，其中缺失新接口的 ERROR 为待实现项）。

修复：统一启动位置校验及只读恢复状态；明确重新选择原目录或确认新建独立空目录，备份原偏好；
系统退出接入取消/提交边界；Dock 恢复和窗口关闭快捷键；Finder 非阻塞状态检查、5 秒超时及路径重试；
Mac spec 在签名前写入版本、构建号、最低系统要求；增加独立 Mac ZIP 与一致的使用说明。
课表协议、账号、UID、数据格式、浏览器模块和 CMD 不变。

最终复核另补一个已复现边界：默认数据目录在运行中失联，若备用日志仍在该目录下，
后台操作前的日志会重建目录。新增回归的同目录/子目录两个分支均先 FAIL；
改为内存日志后 PASS，仍能导出排错 ZIP。首次完整检查为 185 项，补充后以以下最终结果为准。

- PASS：`python -B -X utf8 check.py`，186 项 Python：185 通过、0 失败、1 项 Windows CMD 跳过；三组 JavaScript 检查通过。源码自检 PASS。
- PASS：偏好数组/标量/损坏 JSON、目录失联/拒绝访问、恢复前禁止写入、重新选择原目录保留历史、空目录确认、重复退出、Finder 失败/超时等定向回归。
- PASS：等待/处理阶段取消不改旧课表；提交/导出阶段退出等待保存及独立双导出结束。测试使用真实工作线程和合成阶段阻塞。
- PASS：最终 ZIP 从独立中文空格路径解压；CRC、精确白名单、UTF-8、执行权限、符号链接、全部 SHA-256 和源码指纹一致。
- PASS：最终 APP 包内自检，清除 PYTHONHOME/PYTHONPATH 并设 PATH=/usr/bin:/bin；frozen=true，python_on_path=false，数据在包外、依赖在包内。直接 JSON 导入后重开、重复导入、两种独立导出及 UID 保留通过。
- PASS：版本字段 1.0.0、构建号 11.4、最低系统声明 11.0；24 个原生二进制均要求 11.0.0。独立目录解压、自检后及原生操作结束后 codesign strict 均通过。
- PASS：最终包原生文件选择/取消/重复导入、应用菜单退出、子窗口 Command+W、CSV/ICS/排错 ZIP Finder 定位。旧源码创建的独立示例在升级重开后保留 20 个课表、历史及输出文件的哈希。
- PASS：用户本轮确认触控板和鼠标“滚动和点击都正常”，Dock“恢复原窗口，没有新增窗口”。确认与最终包的构建归属见 [验收表](STUDENT_ACCEPTANCE.md#acceptance-mac-r4)。
- FAIL → PASS：首次构建在 FileProvider 管理的工作区解压后，APP 根目录出现 FinderInfo 导致签名结构检查失败；同一 ZIP 在独立本地目录重新解压后通过。最终交付包也在独立目录通过。没有移除下载隔离或关闭系统安全检查，保留原失败记录。
- NOT RUN：本轮实际系统权限提示、下载隔离后的首次打开、Dock 菜单逐阶段退出、其他系统/设备及正式签名公证；不能由自动测试或旧包人工验收代替。

交付：`课表助手-Mac-arm64-验收包-修订4.zip`，22,642,092 字节；954 条 ZIP 记录，
APP 内 854 个文件、47 个符号链接。SHA-256：`060488fcbd4352b9428be498dad0e93330183a20065b63279416b50d0f5e04bf`。
源码指纹：`36e9559fcc60e4f8ec7e061ca7790bd6a294bd60aeed6a05360d8f41b9140c93`。
应用仍为 1.0.0-rc11，候选区分为 Mac 修订 4；原修订 3 双平台包哈希保持
`5f658ce3e0d986ed5b55733b7e1f6b417a7d0861b12144ec282354f6fe07f704`，没有混合合包。
独立第二人审查 NOT RUN；本轮由实现者审查最终差异。学校与个人日历操作不适用。
备份和原始日志仅留本机；可逐文件恢复本次改前副本，不回滚已有未提交改动或个人历史。


<a id="macos-local-trial"></a>
## FEAT-20260907-MAC：macOS 源码本机试用

用户授权在 Apple 芯片 Mac 上建立隔离环境、修复平台边界并用合成课表试用，不打包、不发布、不访问学校或个人日历。基线公开提交 `3dd9f07bc4b77670594fff649885c3c54d049b29`，干净工作区建立 `codex/macos-local-trial`；应用版本与采集书签版本保持 rc11 原值。

改前：macOS 26.6.2 arm64、Python 3.12.14、Tcl/Tk 9.0.4；锁定运行依赖安装在独立虚拟环境。完整检查退出 0：147 项 Python 中 146 通过、1 项 Windows CMD 跳过，三组 JS 通过；源码自检退出 0 / PASS，`frozen=false`。新增平台检查 6 项中 5 FAIL、1 PASS，复现 Mac 数据路径、Finder 定位、小幅滚动、安装页快捷键及下载目录拒绝访问错误提示。证据留在本机试用目录。

修改：标准库平台辅助模块统一默认目录和主程序/启动日志路径；Finder 文件定位、系统字体、Aqua 滚动、Mac 安装提示和可恢复的目录访问错误。课表算法、数据格式、浏览器采集模块及 CMD 保留原件。

- PASS：改后 `python -X utf8 check.py` 退出 0，153 项 Python 中 152 通过、0 失败、1 项 Windows CMD 跳过，三组 JS 通过；新增 6 项平台边界检查全部通过。源码 `desktop.py --data-root <隔离目录> --self-test <报告>` 退出 0 / PASS，未冻结打包。目录访问测试同时模拟 `listdir` 与 `scandir` 被拒，覆盖不同 Python 版本的 pathlib 实现。
- PASS：独立示例数据合并普通课程、合班分段和混合详情，共 5 次课程；CSV 与 ICS 数量核对一致，重复导入不改变 UID、当前指针及双导出字节。排错 ZIP 完整可读；示例目录未记录手机已导入。
- PASS：源码窗口使用 Aqua 和 PingFang SC，运行时报告可见；用户明确确认屏幕上能看到窗口。Finder 实际选中示例排错 ZIP，原生工具取得截图。Dock 显示解释器 `python3.12` 属于本次源码启动方式，未制作应用图标或 `.app`。
- PASS：用户实机确认“滚动正常”及原生排错 ZIP “保存成功，Finder 已选中”；原生工具再次确认新保存 ZIP 处于选中状态并截图。详细归属见 [本机验收表](STUDENT_ACCEPTANCE.md#acceptance-macos-local)。
- NOT RUN：原生工具无法识别未注册为应用包的独立 Python 窗口，故未取得该窗口本身截图；原生 JSON 选择对话框、窗口缩放和逐页视觉检查不以组件测试替代。学校、手机、其他设备及 Windows 实机均未运行。
- 审查：实现者检查平台分支、文件路径参数、默认目录、错误恢复和最终 diff；`git diff --check` 通过。独立第二人/代理审查 NOT RUN。无公开推送、服务器操作或发布；回滚仅涉及本次源码与维护文档，不回退任何课表历史。

### 2026-09-08 补充验收与源码提交

用户扩大授权：完成检查，解决原生工具不能操作 Python 窗口，并以本人的已登录 Chrome 真实采集，合理推送回同一 GitHub 仓库。前述“未访问学校、未推送”描述 9 月 7 日阶段，现由本节补充；个人日历、服务器、发布版本及安装包不在本次范围。

- **FAIL → PASS：** 目录本身的 `is_dir()` 被拒时，手动 JSON 选择框也会失败。改前新增平台检查 10 项中 9 通过、1 错误，错误为 `PermissionError`；`desktop.py` 在目录探测失败时不指定初始目录，仍允许系统选择其他 JSON。改后 10 项全部通过。
- **FAIL → PASS：** 在 Mac 默认临时目录执行完整检查，两个原有测试把 `/var` 与 `/private/var` 当成不同目录，导致写盘故障注入未命中和相对目录断言失败。仅将这两个测试的临时根目录规范化，不修改产品提交或路径规则。保留首次 157 项中 154 通过、2 失败、1 跳过的记录。
- **PASS：** 最终本机 `python -X utf8 check.py` 退出 0：157 项 Python 中 156 通过、0 失败、1 项 Windows CMD 跳过，三组 JavaScript 通过。源码自检退出 0 / PASS，`frozen=false`。原版 147 项和第一次改后 153 项记录仍保留，不混算执行次数。
- **PASS：** 本地创建仅调用现有虚拟环境与源码的 `.app` 入口，用户允许任务目录访问后，原生工具可识别与操作窗口。完成首次引导、原生选文件/取消/重复导入、CSV 与 ICS Finder 定位、设置、帮助、两种导入指引、缩放、关闭重开及原生排错 ZIP 保存；合成截图及哈希证据保留本机。物理触控板使用用户直接确认，不冒充自动鼠标验证。
- **PASS：** 真实学校 .10 采集器短范围 17 次课程、完整范围 128 次课程，随后独立重复完整采集 0/0/0。实际 CSV 与 ICS 全部 128 条回读核对；学校网页 27 条课程卡和其中 12 条详情核对一致。原短范围 UID 和三次采集的完整历史均保留；重复采集 CSV/ICS 字节一致。对应环境与界限见 [Mac 验收表](STUDENT_ACCEPTANCE.md#acceptance-macos-local)。
- **PASS：** 源码提交 `eb44124b121d563c67df7111dc06aa3ad35f049a` 的 [Windows Actions](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/34186882493) 在 Windows Server 2025 / Python 3.12.10 / Node 22.23.2 上执行 157 项 Python，157 通过、0 失败、0 跳过，真实 CMD 用例通过；三组 JS 与源码自检 PASS。源码自检 `frozen=false`、`elevated=true`、`python_on_path=true`，不是无 Python 学生电脑或发行包验收；未构建 EXE、未发布附件。
- 实现者审查源码 diff、手动恢复、平台路径和明确文件清单；采集器五个模块、课程算法、UID 规则、依赖、CMD、发布资源保持基线字节。公开内容只含源码、合成测试、工作流和汇总文档；个人课表、配置、网页详情、启动入口与截图不提交。独立审查 NOT RUN。
- 源码已通过独立 `codex/macos-local-trial` 分支提交并建立 [PR #2](https://github.com/lhwen686/shsmu-schedule-sync/pull/2)；远端树与本机明确暂存清单一致，17 个修改文件，20 个保护文件保持原始 SHA-256；不合并 main、不调整应用或书签版本、不发布软件包。当前记录提交可由 `git log -1 --format=%H -- VERIFICATION.md` 定位；回滚只撤销该分支源码修改，个人数据目录不参与回滚。

<a id="diagnostics-rc11"></a>
## FEAT-20260907-01：rc11 执行日志与一键排错包

2026-09-07，用户明确授权实现所列 rc11 计划、构建本地 EXE / ZIP、更新 GitHub main 并发布预发布。基于干净公开源码 `29faebbfc252121c6cbbf1832cb7e70ef2edc274` 建立 `codex/diagnostic-logs-rc11`；个人维护目录已有未提交历史，不从该目录发布。原件、检查输出和保护哈希留在忽略的本机证据目录。

**实现范围：** 标准库 `diagnostics.py` 在写文件前按允许字段脱敏，记录启动、设置、等待、选择、校验、标准化、提交、独立双导出、取消、异常和退出。异常仅保留错误码、类型、文件名、函数及行号，不保存消息正文、局部变量或完整路径。每次操作使用一致的替身映射，保留合班、分段和混合详情依赖的 ID 关联、日期、节次、分隔符及空值。诊断包与业务采集使用不同格式，正常导入入口拒绝诊断材料。

三处桌面入口提供历史选择、时间/结果、可选浏览器补充文本及 ZIP 定位。记录按数据目录隔离，30 天 / 50 MB 限制只逐个轮换自身文件；写盘失败保留有限内存补救，材料缺失、损坏、超限和中断均在摘要说明。导出后校验 ZIP 字节，失败不报告成功。

`browser_ui.mjs` 修订为 `2026-09-07.10`，记录请求时间、耗时、重试、状态和阶段，保留当前失败响应的脱敏结构；下载不能完成时可复制排错信息。正常采集保持 `shsmu-capture-v1`，诊断元数据不参与内容哈希、UID 和变更判断。共享同步接口只增加可选观察回调，观察异常不会改变业务结果。安装页已从本次五个浏览器模块重新生成；用户需手动替换一次书签。

### 检查与失败修复

- **PASS：** Windows / Python 3.12.6 / Node.js 24.19.0，最终 `python -X utf8 check.py` 退出 0，147 项 Python 实际通过、0 失败、0 跳过，三组 JavaScript 均通过。证据 `check-release-final.txt`。三组包含实际生成书签执行、失败/下载/登录/重试以及 XHR/能力限制的合成检查。
- **PASS：** 20 个诊断用例及相关桌面用例验证普通课程、合班分段和混合详情匿名重放，异常输入保持校验结果，前后状态重放无虚假新增/删除；仅改诊断元数据仍为重复导入、UID/ICS 字节不变。覆盖部分导出失败、损坏 JSON、旧采集、取消、重启、中断、线程/回调异常、写盘失败、轮换、目录隔离、补充超限和损坏记录。
- **PASS：** 合成敏感标记检查扫描日志文件及 ZIP 全部成员，课程/教师/地点/账号、未知字段、凭证字段、异常消息、完整本地路径及伪装为日期的手机号不进入分享材料；保留的日期/节次仍属个人课表结构，需由同学手动发送。
- **FAIL → PASS：** 早期完整检查暴露 Tk 对象被工作线程垃圾回收的问题；在启动线程前由界面线程回收，并在窗口释放时解除引用，后续完整检查通过。首次构建使用运行环境失败（缺少 PyInstaller），改用项目既有构建环境。首次 EXE 自检选中了重复导入记录却要求首次提交事件；修正为明确选择首次成功操作后重建，并验证分享包不含合成原文字段。
- **PASS：** 最终 EXE `--self-test` 退出 0，报告 `status=PASS`、`frozen=true`、`python_on_path=false`、`elevated=false`。验证包内依赖/资源、初始引导、重复导入、普通/合班/混合详情双导出、独立手机确认逻辑、历史排错 ZIP 和诊断窗口。证据 `exe-final-self-test.json`。这不等于另一台无 Python 电脑或真实手机通过。
- **PASS：** 开发机实际原生窗口核对诊断历史选择、中文说明、补充文本框和保存按钮，无截断；点击后出现 Windows 保存对话框。实际文件名输入/保存为 **NOT RUN**（原生工具不能稳定定位系统模态窗口，停止重试）。自动组件用例通过真实 ZIP 写入与定位调用，但其文件选择对话框使用模拟返回值。
- **PASS：** 本次实现者逐项审查最终 diff、共享接口/提交边界、公开文件白名单、包资源和 CMD 原始 CRLF；HTML 内嵌图片不变，包只含明确资源。没有新增依赖，也没有修改浏览器、扩展、网络设置、上传或个人课表。独立第二人/第二代理审查为 **NOT RUN**。

### 构建与附件

构建环境为 Python 3.12.6、PyInstaller 6.22.2、icalendar 7.3.0、Pillow 12.3.0；命令 `python -X utf8 build_desktop.py` 退出 0。公开源码白名单为原有 53 个文件加 3 个诊断模块/测试文件，共 56 个。EXE 资源逐个与源码字节核对；Windows ZIP 只含中文 EXE、HTML 说明及内部 SHA-256 文件，外部校验文件列出三个下载附件。

| 附件 | SHA-256 |
| --- | --- |
| `SHSMU-Schedule-Assistant.exe` | `6944ffefff6d8f1088a79e42bd8f263faf5e85014a6058c549fa8b69ea6fc4ff` |
| `User-Guide.html` | `c6aa86250cc053ba3b34433a831714d0e6046b8dacabc208901c72f13e98a000` |
| `SHSMU-Schedule-Assistant-1.0.0-rc11-Windows-x64.zip` | `9395e0b8d60c3b0905fa4130945095162fd909fbbf0c3ed2c40fcaf5ef5a3487` |
| `SHA256SUMS.txt` | `d229fd3ec9b14143ddcb668e492b1e5dc00f7ea2f6940c97fae6cb81de9b7b3b` |

包审查证据：`package-audit.json`。**发布与回下载 PASS：** 源码提交 [b20abf6](https://github.com/lhwen686/shsmu-schedule-sync/commit/b20abf6e536ef388ca40dd4f78aefe421a275bf8) 已推送 `codex/diagnostic-logs-rc11` 和 main；2026-09-07 20:47（北京时间）发布 [v1.0.0-rc11 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc11)。`git ls-remote` 回读 main / tag 均指向该源码提交；GitHub 发布 API 回读为非草稿、预发布、四个附件。全部附件重新下载到独立目录，与本地逐字节及 SHA-256 一致，ZIP 成员再次核对通过；公开源码 ZIP 的 56 个文件与白名单一致，6 个 CMD 保留原始 CRLF。证据 `publication-rc11.json`。旧 Release 保留；本段随后作为文档补记提交，不改变已验收 EXE 或版本标签。

学校新书签短范围、完整范围、至少 10 条网页核对和独立重复采集，各目标浏览器、iPhone、其他 Windows 电脑及两名新手均为 **NOT RUN**，需要本人正常登录、手动替换书签或相应设备。具体范围见 [rc11 学生验收](STUDENT_ACCEPTANCE.md#acceptance-rc11)。历史 rc10 的用户实测反馈不升级为本次 PASS。

回滚依照 [现有流程](MAINTENANCE.md#rollback)：从公开基线逐个恢复本次源码或反向提交；个人数据、UID、历史和配置不迁移/重置，旧软件包保留。新日志是附加诊断文件，不作为课表历史导入。Python 启动前的系统拦截、浏览器未运行书签、手机实际状态等仍可能需要补充证据，日志不能保证单独证明所有根因。

<a id="verification-github-sync-20260907"></a>
## 2026-09-07：GitHub 源码同步

用户授权“然后提交github”。从干净公开源码副本向 [GitHub main](https://github.com/lhwen686/shsmu-schedule-sync/tree/main) 快进提交，远端由 `8ffdaffd83d6bcd23c79bcf4a58dff8646718dce` 更新到 [75d6ac1](https://github.com/lhwen686/shsmu-schedule-sync/commit/75d6ac1fa1acf7ee4f475536260ac71f1c6e220b)；共 6 个提交，包含维护文档整理、今天的 3 项 bug 修复、补充回放记录和用户实测收尾确认。

推送与回读 PASS：`git push --porcelain origin HEAD:refs/heads/main` 退出码 0；`git ls-remote origin refs/heads/main` 和 GitHub 提交 API 均回读到 `75d6ac1fa1acf7ee4f475536260ac71f1c6e220b`。本段记录该次已完成的源码推送，随后仅补记同步状态。

范围检查 PASS：逐个核对这 6 个提交，文件树保持原有 53 个公开文件，累计修改限定为 21 个目标文件；检查 44 份变动文件内容，程序及资源与既有受验副本一致。CMD 的 Git 内容与基线相同并保持 CRLF；个人数据、配置及私人历史未进入推送。`git diff --check` 通过；本机证据为 `prepush-audit.json` 与 `publication.json`。

本次没有程序改动，保留 rc10 已有 124 项 Python、三组 JavaScript 及用户实测反馈的原始归属；新应用测试、构建和代理现场验收为 NOT RUN（源码同步无需重跑）。本次未创建 Release 或修改下载附件，已在线核对的公开下载包仍为 rc7。

<a id="verification-bugs-closed-20260907"></a>
## 2026-09-07：当日 bug 关闭与实测确认

结论：当日登记的 **BUG-20260907-01、BUG-20260907-02、BUG-20260907-03 均已处理完毕并关闭；实测 PASS（用户反馈）**。用户已确认给大家实测全部 OK，原话与验收范围见 [学生实测收尾记录](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout)。

登记时本地修复版为 `1.0.0-rc10`，采集书签为 `2026-09-07.9`。下列修复记录保留各自的复现、检查、产物与历史未验项目；其中“未运行”是收尾反馈前的记录，当前 bug 关闭状态以本段和学生实测收尾记录为准。

本次仅标注状态并同步维护文档；程序、版本和安装包未改动。应用测试、构建与代理现场验收为 NOT RUN（仅记录用户已完成的实测，无程序改动）；公开发布状态未变。

<a id="bug-mixed-details-20260907"></a>
## BUG-20260907-03：同一详情响应夹带其他排课

**状态：已关闭；实测 PASS（2026-09-07 用户确认，见 [当日收尾](#verification-bugs-closed-20260907)）。**

- 日期与授权：2026-09-07；用户提供视频及完整采集 JSON，要求查明并修复。本地修复、回归和候选包；未推送、发布或调用真实服务。
- 基线：rc9，公开源码提交 `85b854de83a93698331c7610df4eebd4a4c87bb6`，工作区干净；分支 `codex/fix-mixed-calendar-details-20260907`。个人目录已有改动，10 个目标文件的两份原件、Git 状态和非目标哈希保存在忽略目录。
- 复现：视频中 rc6 已读取 131 次详情，报“教学日历无法对应到该课程的排课 ID”。真实旧采集含 131 个主事件、137 次完整请求；两次详情响应分别夹带 2 条和 4 条其他排课记录。rc9 离线也报错，误入合班关联校验。文件完整，不需要删除历史或重新采集。
- 改前失败：Windows x64 / Python 3.12.6，3 个新合成复现用例 ERROR，退出码 1；对应 `test_sync.TimetableTests.test_mixed_details_select_exact_slots_without_mutating_raw`、`test_wakeup.WakeUpTests.test_mixed_details_use_only_selected_periods_and_teachers`、`test_desktop.DesktopTests.test_mixed_details_both_exports_reopen_and_repeat_without_upload`。证据 `before-repro.txt`。
- 修复：`core.py` 在混合响应中先按主排课 ID 选择详情；要求同课程、同日期、同管理编号、同教学日历、无合班标志或删除标记、主排课 ID 完整覆盖、节次数量和授课覆盖一致、详情身份不冲突。仅匹配部分或证据不足继续停止。原始完整响应不修改，标准化身份、教师、内容和 WakeUp 共同使用所选详情。没有直接匹配的响应继续走既有合班证据校验；浏览器、账号、范围、提交和上传逻辑未改变。
- 定向回归：`python -X utf8 -m unittest -v test_sync test_wakeup test_workflow test_desktop`，98 PASS、0 FAIL、0 SKIP，退出码 0。新增完整筛选、全部匹配教师、UID 保留、顺序不变、缺失/冲突拒绝、CLI 原始记录保留与失败不提交、桌面双导出和重复导入检查。
- 完整回归：同一源码目录、既有 Python 3.12.6 / Node 环境，`python -X utf8 check.py`，124 Python PASS、0 FAIL、0 SKIP，三组 JavaScript PASS，退出码 0，证据 `full-check.txt`。包内检查脚本的最终描述断言另由最终 EXE 自检执行。
- 真实旧采集离线回放：131 个唯一 UID、131 个 ICS 事件、131 条 CSV 全部通过；逐条核对主时间、源 ID、教师、内容、节次及周次。两次混合响应各保留 4 条、2 条本人详情，6 条其他排课记录仅从导出选择中排除，原始采集完整保留。相同文件重选不修改提交指针；只更换采集时间外壳的同响应回放零变化，CSV / ICS 字节相同。另存交付文件使用原始采集时间；首次跨两个新目录比较 ICS 整体哈希因创建时间不同失败，改为逐事件检查 UID、内容及时间后通过，记录在 `delivery-report.json`，不属于应用失败。
- 旧课表对照：维护者 128 次普通课程、此前 132 次合班课程的新旧标准化结果完全一致，与已有历史协调后零误报、ICS 字节相同；未写入原数据目录。证据 `real-replay-report.json`。
- 构建与包内自检：既有 Windows x64 / Python 3.12.6 / PyInstaller 6.22.2，`python -X utf8 build_desktop.py` 退出码 0；最终 rc10 EXE `--self-test <独立报告路径>` 退出码 0 / PASS。普通用户、PATH 仅 Windows System32、冻结依赖位于包内，10 项原检查及合班分段/混合详情双导出通过；自检只使用隔离合成数据。
- 产物审查：EXE 1655 条归档记录，6 项资源与源码逐字节一致；core、wakeup、desktop_service、desktop_smoke 的冻结代码与受验源码一致，无私人 data / output / local / 配置路径。ZIP 仅 EXE、独立 HTML、更新说明和校验文件，逐文件字节及 CRC 通过。项目依赖未改变；视频解码器仅装在忽略的诊断目录，首次下载超时后重试成功，不进入安装包。
- 差异审查：同一代理在测试以外重新审查最终 core、四组测试、桌面版本和包内用例的 diff，核对完整性、身份、原始响应、两种导出及保护边界；未做独立第二人/子代理审查（NOT RUN）。最终范围、隐私、CMD CRLF 及保护哈希见本机 `final-audit.json`。
- 交付与回滚：应用 `1.0.0-rc10`，书签仍为 `2026-09-07.9`；已有完整 JSON 可直接选择处理。只按清单同步本次源码和维护文档，保留 rc9 原包及构建前备份。修复提交由本记录的 Git 历史定位；可反向提交或按目标原件逐个恢复，不重置个人历史。实际降级/数据回滚演练 NOT RUN。
- 尚未运行：学校短范围/全范围新实采、至少 10 条页面现场核对、独立重复实采、手机实际导入、另一台无 Python 电脑、系统其他缩放和学生独立操作；本地回放和旧视频不能替代新版实机验收。真实 WebCal 和线上发布不在本次范围。

| rc10 本地产物 | 字节 | SHA-256 |
| --- | ---: | --- |
| 医学院课表助手.exe | 21846236 | `2124569698e8379f04de9735602e0ee06892b67adc1219e2a985e3d2cbf95a05` |
| 使用说明.html | 4012844 | `8c0862b4bfa3c315eb00c60674e11acaff8c9749e42f8c959f569c9d28276f77` |
| 本次更新说明.txt | 792 | `f22f51e7c8d735646ba52c53a26671eca9e6e2d7777823d192f5facd30ee23b2` |
| SHA256SUMS.txt | 268 | `71b0c2bd5dca42ceb5bbb4fbb808b28ba43031b4f3e8c197c48dc68bd1eb569c` |
| SHSMU-Schedule-Assistant-1.0.0-rc10-Windows-x64.zip | 24515842 | `d5bb024476824e44f5687273d092911646d3a3a427748509863403030175f637` |

原始视频、采集、个人导出及回放报告仅留本机忽略目录，公开源码与安装包不含个人文件。

<a id="verification-rc10-additional-capture"></a>
### rc10 补充核对：另一位同学的旧版反馈（2026-09-07）

用户确认使用旧版（rc6 / rc7 / rc8 范围，未提供精确版本）。另一份完整旧采集包含 157 次课程、184 条详情，其中 5 次合班课程在保留的 rc8 源码中均报排课 ID 错误；rc9 标准化通过，当前 rc10 桌面服务双导出通过。属于已有 [合班修复](#bug-combined-classes-20260907) 的适用情形，本次未改程序或提升版本。

PASS：使用当前 rc10 源码，在独立目录处理提供的真实旧采集，157 个唯一 UID、157 个 ICS 事件、157 条 CSV；逐条核对源时间、教师、内容、节次及周次。重选相同文件不改变提交指针；同一响应只更新采集时间外壳的回放零变更，两种输出字节不变。交付文件保留原始采集时间；按数据得到第一周周一 2026-09-07、18 周。原文件哈希不变，现有 rc10 EXE / ZIP 哈希与构建记录一致。Windows / 既有 Python 环境，本机 `verify_capture.py` 退出码 0，证据仅在忽略目录 `verification.json`。

NOT RUN：学校新采集、手机实际导入和这位同学电脑上的新版操作；用户应运行 rc10 后选择原完整 JSON。程序未改，本次不重复完整自动测试矩阵或构建；此前 124 项检查与 EXE 自检仍属原修复记录。未发布、上传个人文件或改动维护者课表历史。

<a id="bug-combined-classes-20260907"></a>
## BUG-20260907-02：合班详情及分段排课兼容

**状态：已关闭；实测 PASS（2026-09-07 用户确认，见 [当日收尾](#verification-bugs-closed-20260907)）。**

- 日期与授权：2026-09-07；用户要求修复已提供同学的采集文件，更新程序并回归原有功能。本地实现、验证和构建；发布状态另记。
- 基线：干净公开副本 `7a10b3e253779c06b6f0ee28b6d77ff9e40eebbf`，新分支 `codex/fix-combined-classes-20260907`；个人目录有既有改动，目标文件原件及哈希保留在忽略目录。
- 复现：既有真实采集离线分析，132 个主事件、174 条详情；详情带合班标识，课程及日期一致，但使用另一排课管理编号，全部被排课 ID 校验拒绝。其中 5 个分段主事件共用整段详情。原始文件和个人证据不进入源码或包。
- 改前失败：现有 Windows / Python 3.12.6 环境，3 个新合成复现用例均 ERROR（排课 ID 不匹配），退出码 1；证据 `before-repro.txt`。用例覆盖合班身份、分段教师和节次导出。
- 修复范围：`core.py` 只在精确事件详情请求具有合班标识、多班级代码、跨排课管理编号、同课程/日期和完整节次证据时接受不同排课 ID。分段事件按不重复的主排课 ID 数量及明确时间先后完整分配教学节次，并按授课节次筛选教师和内容。主课表的时间、地点和源 ID 保留，共用详情 ID 留作溯源但不成为分段事件的独立身份。`wakeup.py` 使用已关联分段节次，继续校验所选作息的每个实际端点；ICS 不依赖 WakeUp 作息。原有直接关联的标准化和身份规则不变。
- 定向及完整回归：定向 core / WakeUp 37 PASS；最终 `python -X utf8 check.py`：118 Python PASS、0 FAIL、0 SKIP，三组 JavaScript PASS，退出码 0。新增 CLI / desktop 混合普通和合班课程的提交、重复处理、失败保留及不上传用例。覆盖原有账号、学期、UID、取消、完整性、两种导出、WebCal 本机回归、CMD 和 JSON 恢复入口。
- 真实旧采集离线回放：PASS。在独立数据目录通过桌面服务处理用户文件，132 个主事件、132 个唯一 UID、132 个 ICS 事件和 132 条 CSV；逐条核对主时间与源标识、ICS 时间和 CSV 分段节次。同一文件重选不修改提交指针；只更换采集时间外壳、重放同一学校响应，零字段变化，CSV / ICS 字节一致。原下载文件哈希不变。维护者原有 128 次课程的新旧标准化结果完全一致，无虚假变更、ICS 字节一致；未写入维护者数据。离线校验脚本首次误用数组顺序对应 ICS，改为按实际 UID 关联后通过，此次断言不属于导出故障。
- 构建与包内自检：PASS。既有 Windows x64 / Python 3.12.6 / PyInstaller 6.22.2 环境，`python -X utf8 build_desktop.py` 退出码 0。最终 EXE `--self-test` 退出码 0 / PASS；普通用户，PATH 仅含 Windows System32，10 个原检查项和新增合班分段双导出检查通过，冻结依赖与包外数据目录检查通过。没有安装或升级依赖。
- 产物审查：PASS。EXE 1655 条归档记录，6 个明确资源逐字节匹配；核心、WakeUp、桌面服务及包内自检模块的冻结代码与受验源码一致；无私人 data / output / local / 配置条目。ZIP 仅下列 4 个明确文件，CRC、成员清单及逐文件字节检查通过。
- 差异审查：PASS。同一代理在测试以外另行重读最终业务 diff，检查合班接受条件、完整覆盖与冲突拒绝、来源身份、教师筛选、直接关联兼容、WakeUp / ICS 独立性及不更改浏览器和上传链路；`git diff --check` 通过。独立第二审查者 NOT RUN，未委派代理。
- 交付与版本：`1.0.0-rc9`；书签仍为 `2026-09-07.9`，无浏览器模块变化，已有完整 JSON 可直接处理。本地 EXE / ZIP 已生成；分支 `codex/fix-combined-classes-20260907`，修复提交由本记录的 Git 历史定位。没有推送、发布或改动已有公开附件。
- 保护与回滚：目标源码、文档及旧构建产物已另存原件和哈希；只按审查清单更新个人维护目录，原课表及配置不迁移、不重置。已有记录适用历史保持。新合班快照保留原有存储结构并增加来源关联元数据；旧版重新处理这些采集仍会拒绝，程序降级及数据回滚演练 NOT RUN，应保留新版和原始采集。
- 尚未运行：学校短范围 / 全范围新采集、10 条网页现场核对及独立重复实采、另一位同学的文件、另一台无 Python 电脑、Windows 其他实际缩放、手机导入、学生独立操作和真实 WebCal 上传/订阅；离线回放与包内自检不替代这些验收。

| rc9 本地产物 | 字节 | SHA-256 |
| --- | ---: | --- |
| 医学院课表助手.exe | 21844123 | `bf0e93180ea7db705e5d13dc654ac373ed781cf5d407138756133b66ae8927e5` |
| 使用说明.html | 4012844 | `8c0862b4bfa3c315eb00c60674e11acaff8c9749e42f8c959f569c9d28276f77` |
| 本次更新说明.txt | 713 | `b6a636b7c1956d0341b3b3e3d995c32beacb2f2116c2f7b13be100e824b5e6c2` |
| SHA256SUMS.txt | 268 | `7e4924aae67ff85c467a4fd5956f86382beec6bc5d412039b714e1331a65a7be` |
| SHSMU-Schedule-Assistant-1.0.0-rc9-Windows-x64.zip | 24513341 | `c0d6b530a9b4c9c3c82d707f9e10da4cfc0e5fbf590ad31627162744417b6633` |

原始同学数据、离线输出、校验脚本及报告仅保存在维护者忽略目录。通用证据包括 `before-repro.txt`、`targeted-check.txt`、`full-check.txt`、`real-replay-report.json`、`build.txt`、`packaged-self-test.json`、`package-audit.json` 和源码同步保护核对报告。

<a id="bug-json-handoff-20260907"></a>
## BUG-20260907-01：只下载到 JSON 后缺少继续入口

**状态：已关闭；实测 PASS（2026-09-07 用户确认，见 [当日收尾](#verification-bugs-closed-20260907)）。**

| 字段 | 记录 |
| --- | --- |
| 日期与授权 | 2026-09-07；解决同学只得到采集 JSON、找不到 WakeUp / 日历文件的反馈；本地修复及验证 |
| 基线 | 公开源码分支 `codex/maintenance-docs-20260907`，HEAD `a2fe2ebdacdb642ae46ab2f92d0cb59ee8827125`，工作区干净；程序基线为 rc7。个人目录已有修改与未跟踪文件，原件和哈希另行保存在忽略目录 |
| 反馈边界 | 用户提供下载文件名截图，没有提供 JSON 内容、助手提示或同学所用版本；不能据此断定其采集完整或已证实具体导出失败原因 |
| 复现 | 已确认书签但首次课表尚未提交，先在浏览器下载 JSON 再重开助手；预期可直接选择该文件并生成两个导出，实际重回书签引导且本页没有“文件已经下载”入口，只能绕到帮助或重新确认书签 |
| 改前失败 | Windows 64 位，Python 3.12.6；`python -X utf8 -m unittest -v test_desktop.DesktopWidgetTests.test_reopened_setup_imports_existing_json_and_exposes_both_exports test_desktop.DesktopWidgetTests.test_setup_file_picker_cancel_keeps_setup_and_does_not_import`：2 FAIL，退出码 1，均为引导页找不到“文件已经下载”；隔离合成课表与真实 Tk 组件 |
| 修复 | 首次书签引导页直接选择已有 JSON；首页、等待页、帮助、采集结束提示和学生说明明确 JSON → 助手 → CSV / ICS；复用既有导入服务，不改变账号、范围、UID、完整性、锁、提交、导出或上传逻辑。书签升至 `2026-09-07.9` 并重新生成安装页，需本人手动替换；旧完整 JSON 仍可直接导入 |
| 定向回归 | 2026-09-07，改前相同命令：2 PASS、0 FAIL、0 SKIP，退出码 0；验证重开引导后选择原 JSON 能生成并定位两种文件，取消不写入课表或更改设置，原下载及书签确认不变 |
| 完整回归 | 同日，现有 Python 3.12.6 运行环境及 Node v24.19.0，`python -X utf8 check.py`：111 Python PASS、0 FAIL、0 SKIP；3 组 JavaScript PASS，退出码 0；包含生成后的实际书签在合成环境执行，保留单个 JSON 下载及诊断边界 |
| 开发机窗口 | PASS：按应用入口启用 DPI awareness，当前 Tk 约 192 DPI（200%），1801 × 1521 窗口；重开引导页无需滚动即可看到选文件入口，选择隔离合成 JSON 后结果页两种文件就绪；保留窗口截图。首次截图使用未启用 DPI awareness 的坐标而裁取不准，已改为应用同等设置和窗口句柄重新核对；不算其他系统缩放验收 |
| 构建与包内自检 | Windows x64、Python 3.12.6、既有 PyInstaller 6.22.2 构建环境，`python -X utf8 build_desktop.py` 退出码 0；最终 EXE `--self-test` 退出码 0 / PASS，10 个检查项，普通用户、PATH 仅含 Windows System32、依赖在冻结包内、临时数据在包外。运行环境无 PyInstaller，探测后改用既有构建环境，没有安装依赖 |
| 产物审查 | PASS：EXE 1655 个条目，6 个明确资源逐字节匹配源码，包内版本为 rc8；无 data / output / local / 虚拟环境 / 私人配置条目。ZIP 仅 EXE、使用说明、SHA256SUMS，逐文件字节与 CRC 验证通过，哈希见下表 |
| 差异审查 | PASS：同一代理独立于测试另行重读最终程序 diff，核对修复触发路径、取消和导出独立性、单个 JSON 下载、只更新相关文件以及 CMD 未改；独立第二审查者 NOT RUN，未委派代理 |
| 提交与交付 | 分支 `codex/fix-json-handoff-20260907`，本记录所在修复提交由 `git log -1 --format=%H -- VERIFICATION.md` 定位；应用 rc8 / 书签 `2026-09-07.9`。本地修复包已生成，未推送、未发布或回下载，公开 rc7 附件未修改 |
| 回滚与保护 | 14 个目标文件在个人/公开目录的 28 份原件与哈希、个人目录原 Git 状态及旧构建产物均在本机忽略目录保留；仅按清单同步，核对 585 个个人数据/配置文件哈希不变，41 个非目标项目文件在同步前后不变；个人课表及设置不作迁移或重置。源码可反向提交，个人目录可按备份逐个恢复；数据降级兼容性和实际回滚演练 NOT RUN |
| 实机未验 | 该同学的 JSON 内容及原导出错误、学校短/全范围采集、10 条网页核对、独立重复采集、各目标浏览器、手机导入、另一台电脑、100% / 125% / 150% 系统缩放及两名学生独立恢复操作均 NOT RUN；没有以新测试替代历史或实机验收 |

| 本地候选产物 | 字节数 | SHA-256 |
| --- | --- | --- |
| 医学院课表助手.exe | 21836873 | `e070f73963cfcfc2128e2d250d9ef90337be7fd19ef70e919cc88b39f361b120` |
| 使用说明.html | 4012844 | `8c0862b4bfa3c315eb00c60674e11acaff8c9749e42f8c959f569c9d28276f77` |
| SHA256SUMS.txt | 178 | `c571972cd27200b11464ab0631c5549ec3cc6a92dc9eabb42f8de21ddf0e6eb1` |
| SHSMU-Schedule-Assistant-1.0.0-rc8-Windows-x64.zip | 24505370 | `8b57c20613db622bced129babf7cd8232501b85972cabae4506a168cd93e2e44` |

原始证据文件在维护者忽略目录保存：`before-repro.txt`、`after-repro.txt`、`full-check.txt`、`window-qa.json`、两张窗口截图、`build.txt`、`packaged-self-test.json`、`package-audit.json` 及保护文件核对报告。公开记录不含个人课表或本机路径。


<a id="docs-maintenance-20260907"></a>
## DOCS-20260907-01：维护文档整理

| 字段 | 记录 |
| --- | --- |
| 日期与授权 | 2026-09-07；用户批准既有文档整理方案，范围为五类维护文档；不修改业务、全局配置或线上状态 |
| 问题与复现 | AGENTS 要求反复通读历史；当前版本、旧验收与维护流程混用，缺少统一修复记录和回滚定义 |
| 基线 | 公开程序提交 `8ffdaffd83d6bcd23c79bcf4a58dff8646718dce`；根目录与公开副本保持独立历史，先备份目标原件和现有改动 |
| 改动 | AGENTS 保留约束并按需路由；MAINTENANCE 统一流程；PROJECT_STATUS 只保留当前状态；本页保留历史并加索引；STUDENT_ACCEPTANCE 绑定实际验收对象 |
| 回归与证据 | PASS：离线文档核对退出码 0，144 个本地文件/锚点链接有效，10 份备份匹配；仅 10 个目标文档改变，98 个其他项目文件和 593 个个人数据/配置保护文件哈希不变；原验证正文及学生状态表保留 |
| 审查 | PASS：同一维护代理另行重读最终 diff，复核长期约束、版本归属、数据流、真实命令、变更范围及公开内容；独立第二审查者 NOT RUN。git diff --check 通过 |
| 提交与发布 | 文档分支 `codex/maintenance-docs-20260907`；记录所在提交由 Git 定位，程序版本、rc7 标签及 Release 附件不变；未推送或发布 |
| 回滚依据 | 已保存 10 份目标文档原件和哈希；已提交文档可反向提交，个人目录按备份逐个恢复，不重置课表索引或 UID 历史 |
| 本轮未运行 | 应用测试、构建、学校或线上服务、手机及另一台电脑验收、实际回滚演练；文档整理不改变候选版实机待验状态 |

改前原件及哈希清单由维护者在本机忽略目录保管，不随公开源码发布；本记录只给出脱敏结论。


## 历史验收原文

下面保留原验收事实，仅增加索引锚点。原文中的“当前”“本轮”“最终”“已通过”“未发布”等均指各章节当时的版本、环境和阶段；不能沿用为新提交、新书签或另一台设备的结果。原文中的历史测试数量不代表现在执行数量，旧范围也不覆盖当前桌面预设。

<!-- BEGIN PRESERVED VERIFICATION HISTORY -->
<a id="verification-core"></a>
## 发布前的真实验证

2026-09-05，原维护环境的一个账号完成短范围核对、两次独立的完整学期 Chrome 采集、标准化及 ICS 导出。至少 10 条真实页面事件逐项核对课程、日期、时间、地点与教师；第二次新增、删除和修改均为 0，UID 与 ICS 字节保持一致。

2026-09-06，原维护环境完成 HTTPS 上传、回读一致性、访问权限分离、损坏与旧版本拒绝、重复上传验证。用户确认首次 iPhone 订阅后课程正常显示。

这些是原环境的历史验收记录，个人原始响应、日历和页面证据没有随源码发布；不是对其他账号或其他服务器的验证承诺。

2026-09-06，原维护环境使用已提交的完整快照导出 WakeUp CSV，逐条反向核对日期、起止时间、课程名称、教师及地点；重复导出字节相同，原快照、UID 和 ICS 未变。用户随后明确反馈 iOS WakeUp“可以正常使用”。这属于单账号实机反馈，不代表重复导入覆盖、删除行为或其他设备均已验证。

## 自动化验证范围

- `test_sync.py`：13 项模拟测试，覆盖日期、时区、中文、稳定 UID、去重、字段变化、删除与恢复、身份歧义、完整性检查、输出恢复及字段清理。
- `test_webcal.py`：11 项本机 HTTP / 模拟上传测试，覆盖读写权限分离、损坏和旧版本拒绝、原子提交、重复上传、回读一致性及失败保留本地版本。
- `test_wakeup.py`：10 项模拟测试，覆盖 CSV 转义、空字段、实际周次、多段节次及晚课、取消和重叠课程、异常数据拒绝、重复导出及失败保留旧文件。
- `test_capture.mjs`：模拟接口及生成后的完整书签，覆盖空月份、学期、逐事件详情、账号摘要、诊断与续传。
- `test_transport.mjs`：模拟顺序请求、有限重试、退避、超时、重定向和 Fetch/XHR 回退。

2026-09-06 已在干净发布副本中重新生成书签，使用原维护环境的 Python 3.12 虚拟环境执行全部 24 项 Python 测试，均通过；Node.js 的完整书签和传输测试均通过。测试数据全部为人工构造或本机临时 HTTP 服务，没有访问学校或现有日历服务器。这次未在另一台 Windows 电脑重新安装依赖。

本次 WakeUp 发布已在发布副本执行全部 34 项 Python 测试，均通过。新增导出程序、测试及双击入口与本地维护版本逐字节核对一致；未上传个人 CSV、原始数据或本机证据，未重新访问学校或日历服务器。

## 未运行或尚待实际发生

- 其他账号、其他学校及其他操作系统的真实全流程。
- 学校实际调课后的源 ID 长期稳定性，以及手机的刷新延迟、停课与删除行为。
- 本仓库部署模板在新服务器上的安装及证书续期实际发生。
- WakeUp 重复导入的覆盖和删除行为，以及其他账号或设备的实际效果。
- 无人值守学校采集、Windows 定时任务和消息通知。

本次发布整理不重新访问学校、不上传个人日历，也不部署新服务器。

## 2026-09-06 审查修复回归

当前统一检查发现 50 项 Python 测试及两组 JavaScript 测试。新增覆盖历史源 ID、课程类型与编号更正、空详情失败保留当前版本、异常删课提示、同步 CLI 到 WakeUp 的完整模拟流程，以及 18 种重新计算哈希的非法日历上传。发布副本已实际执行统一入口：50 项 Python 测试、两组 JavaScript 测试全部通过，退出码 0。

<a id="verification-live"></a>
## 修复版本的原维护环境实测

2026-09-06，原维护环境已更新后端，服务器程序哈希与已测试源码一致。通过正常证书校验的真实 HTTPS 完成 18 种异常上传拒绝、5 项权限与旧版本检查、HEAD/ETag 缓存检查、正常上传及订阅回读。异常测试保留真实课程；升级脚本留有旧程序备份，并核对未改动既有服务进程和监听。

使用者手动更新修正版 5 书签后，完成两次独立全学期学校采集并自动上传；两轮新增、删除、修改均为 0，UID 和 ICS 保持一致。全部 ICS 事件和 WakeUp CSV 逐条复核，重复导出一致。使用者确认本轮 10 条网页抽查及手机当前显示一致；该页面和手机结果属于使用者手工确认，自动浏览器核对因连接故障未运行。

本轮没有发生真实调课，手机在未来调课后的刷新延迟和删除行为仍待实际发生。以上验收属于原维护环境，不代表其他账号或部署自动通过；个人采集文件、服务器资料和本机证据未公开。

## 修正版 6 使用体验修补

原维护环境和干净发布副本均已通过全部 69 项 Python 测试及两组 JavaScript 测试。新增场景涵盖 BOM / 非法配置、同名下载覆盖、分段写入、失败诊断、文件选择结果及取消、拖入路径、旧版本拒绝、账号保护、重复新学期参数保持历史、显式进入下一学期、上传配置错误、本地处理提示、自定义 WakeUp 作息及旧 CSV 提醒。

真实 Windows CMD 在中文和空格目录中运行，复现旧 LF 入口错误；改为 CRLF 后通过。安装流程用临时 Python 环境和本地 pip 替身验证失败 / 成功的退出码及提示，不联网安装依赖。完整书签模拟验证学期错误可见、下载失败后可重下载、重下载结果不变且不额外请求学校、关闭面板清除结果。

原维护环境既有 128 次课程离线回放为零变化，UID、ICS、WakeUp CSV 及说明一致，586 个个人状态文件哈希不变。本轮没有重新访问学校、上传日历、部署服务器或操作手机。

修正版 6 学校实采、其他账号和另一台电脑实机使用、真实文件选择框的人工操作、手机刷新及 WakeUp 重复导入仍未运行。上述历史修正版 5 的真实验收与本轮模拟验证分别保留。

发布候选 Git 归档审计为 40 个白名单文件，未发现私人环境或凭证字面量；6 个 CMD 在归档内均保持 CRLF。实际解压到中文和空格目录后，重新执行 Windows 安装退出码、拖入文件、文件选择入口及完整书签模拟均通过。

## 2026-09-06 学生桌面候选版 1.0.0-rc1

本节对应 Tkinter / ttk 桌面界面、共用同步服务与书签修正版 7（2026-09-06.7），不把以前的学校或手机验收沿用为本版本结果。

- 干净发布副本执行完整 `check.py`：**88 项 Python 测试及两组 JavaScript 测试通过，退出码 0**。新增 19 项桌面服务、线程控制及 Tk 组件检查，覆盖自动接收、明确选择旧下载文件、选文件取消后保留等待基线、错误文件、账号不符、过期文件、重复点击、取消与提交边界、同步锁、导出失败保留完整课表且隐藏旧 CSV、重新导出、配置校验与重新打开后历史保留。桌面流程没有调用上传。
- Tk 组件在 100% / 125% / 150% 对应字体缩放下检查设置与 14 节作息表，行高大于字体高度。实际操作发现长指引页初始位置偏下，已修复并增加页面切换回归测试；最终 EXE 已复核标题从顶部显示。组件检查不代表 Windows 实际切换系统缩放的完整验收。
- 在开发机以普通用户运行最终 EXE，从中文及空格路径启动，使用仅含 Windows System32 的 PATH。隐藏运行自检通过：运行时为冻结包、PATH 无 Python、非管理员、所需依赖来自包内、数据写在 EXE 外。使用临时合成课表验证本地导入、WakeUp 输出、重复导入 UID 不变和 Tk 窗口创建。没有可用的另一台无 Python 电脑或 Windows Sandbox，因此该真实环境项目仍为未运行。
- 通过官方 Windows UI 工具实际点击最终 EXE，使用隔离合成课表验证首页、接收准备状态、Windows 原生文件选择框、取消选择后继续等待、取消接收提示、随后选择文件并自动导出、变化摘要 0 / 0 / 0 和 iPhone 设置卡。点击“找到要发到手机的文件”实际打开对应 output 文件夹，并选中 wakeup CSV；没有启动表格编辑器。结果截图和操作记录仅留在忽略的维护证据目录。
- 对现有真实课表做只读离线回放：128 次课程，新增 / 删除 / 修改 0 / 0 / 0，UID、ICS、WakeUp CSV 和说明字节一致；修改前记录的 587 个个人数据、输出和配置文件哈希不变。此项没有产生新的学校采集。
- 采用 PyInstaller 6.22.2 在 Windows 64 位构建单文件无控制台 EXE，最终体积 14,131,083 字节。包内 1646 个条目，Windows GUI 子系统为 2，x64 标识为 0x8664；未包含 data、output、local、虚拟环境或本机配置文件，项目模块中未发现已知私人环境字面量。EXE SHA-256：`5163e6dd34cd4aedd6bd47cd10663e7f8dc1e22808fdd58978d937bf90212be8`。

公开候选源码从既有干净发布副本整理；维护命令从学生首页移至 MAINTENANCE.md，交付包含 EXE、独立图文说明及校验值。没有提交或推送本次候选代码。构建方式依据 [PyInstaller 官方说明](https://pyinstaller.org/en/stable/operating-mode.html)，iPhone 操作依据 [WakeUp 官方 CSV 说明](https://www.wakeup.fun/doc/import_from_csv.html)；官方流程仍需要手机端自行核对日期与作息。

**本版本未运行：** 新书签的短范围和完整学期实采、至少 10 条新网页核对及一次无误报重复采集；另一台无 Python 电脑、Windows 系统实际切换常见缩放；iPhone 实际接收、导入及逐项日期和作息核对；两名不熟悉电脑的同学独立操作。本轮浏览器控制的站点状态读取超时，一次只读复核仍失败；未继续重试或修改 Chrome。验收记录表见 STUDENT_ACCEPTANCE.md。

维护证据目录 `local/desktop-v1-20260906/` 保持忽略，不随公开源码或软件包发布。核心记录：`release-tests.txt`、`packaged-runtime.json`、`offline-verification.json`、`native-ui-verification.json`、`candidate-release-audit.json` 和 `exe-result.jpg`。

## 2026-09-06 结课日期改进：1.0.0-rc2

首次引导改为只选择学期，不要求同学查找或填写个人结课日期。已核对学校 2026–2027 校历原始 PDF：秋季教学活动 19 周，寒假 2027-01-18 至 02-21，春季从 02-22 开始。当前桌面预设采集覆盖 2026-09-07（含）至 2027-02-22（不含），加入寒假，避免以 1 月 17 日作为个人课表的硬截止。这里采用校历的下一学期边界作为有界查询范围，不宣称已从教务自动识别所有人的未来结课日。来源：[学校公布页面](https://www.shsmu.edu.cn/jwc/info/1066/5704.htm)。

结果与手机设置卡显示“本次已公布课程”的实际首末日期；WakeUp 所需周数取实际课程最大教学周。未安排课程的日期不补造课程，未来新增课程仍需重新采集。未知学期、显式自定义范围与跨学期实习不自动套用当前秋季预设。

- 完整检查 **94 项 Python 测试及两组 JavaScript 模拟测试通过，退出码 0**。新增场景覆盖提前结课、1 月 25 日和 2 月 21 日仍有课、多个空月份后才出现课程、旧范围升级前保持原配置、仅确认学期后扩大、未知和自定义范围不改写、缺少新增月份或学期不符时保留完整版本，以及旧导出设置失效后的重新生成。
- 同账号同学期的范围超集只有完整重采后才合并到原历史；测试验证原 UID、修订号、身份别名、取消记录均保留，新增晚课仅报 1 项新增，再次独立导入为 0 / 0 / 0。账号检查和其他学期检查保留。
- 读取已有 128 次真实课程做只读回放，0 / 0 / 0，CSV 与 ICS 字节不变；新的说明和周数按实际课程生成，不再要求说明与旧的固定周数版本相同。修改前 587 个个人文件哈希不变，没有更新个人课表或上传。
- 从既有干净发布副本构建 Windows x64 EXE。普通用户、PATH 不含 Python 的打包自检通过；实际新 EXE 的首次窗口不再显示需要确认的日期，点击学期即可进入书签引导。上述 GUI 操作使用隔离空目录，没有替用户确认学期或更改其 Chrome 书签。
- EXE SHA-256：`0caabde8cb262b4329b7a1a376c728960ccc4277970d06d395ff4411b4a56614`。运行环境自检、构建和完整测试记录在忽略目录 `local/end-date-20260906/`，核心文件为 `full-tests.txt`、`packaged-runtime.json`、`native-ui-verification.json`、`offline-verification.json`、`release-audit.json`。

**未运行：** 扩大后范围的真实学校采集、寒假课程返回的实际学期与教学周字段验证、手机导入以及其他学生的实机验收。特殊实习或跨学期课程如不在当前已核实范围内，需要先核实范围与源字段，不能把模拟晚课通过写成已支持所有安排。1.0.0-rc1 中记录的其他实机待验项目继续有效。

<a id="verification-collector"></a>
## 2026-09-06 浏览器兼容性：1.0.0-rc3

界面、安装页及恢复步骤改为使用同一个日常浏览器，说明 Edge 收藏夹栏、Chrome 书签栏、Firefox 书签工具栏及 Ctrl + Shift + B。保留旧安装页文件名 `chrome-bookmark.html` 供命令行使用。已安装的课表按钮需要本人手动更新到修正版 8（2026-09-06.8），助手不会安装书签或更改浏览器配置。

采集器改用 AbortController 和可清理定时器，不再依赖较新的 AbortSignal.timeout；缺少 Fetch 或 AbortController 时直接使用自带 45 秒超时的 XHR。请求正文也受超时约束。原同源来源、跳转、身份、学期与完整性校验不变；失败不提交不完整课表。

安装页以本地 ES5 脚本检查必要功能与 JavaScript 语法，失败时解释下一步并禁用拖动按钮。实际书签在请求前检查所需功能，不在学校页面执行动态代码探测，也不读取浏览器品牌、凭证或存储。IE / IE 兼容模式不支持；其他独立浏览器需按具体版本验收。

- 干净发布副本完整检查：**95 项 Python 测试及三组 JavaScript 模拟测试通过，退出码 0**。首次完整检查因命令行测试临时目录未复制新增模块出现 11 项失败，已统一资源清单并完整重跑通过。新场景包含缺失 AbortSignal / Fetch / AbortController、XHR 独立及回退请求、正文超时与定时器清理、IE 和缺失 API 时零请求停止、安装页禁用不支持的按钮、生成书签在 XHR 模式完成合成采集，以及升级资源后重新引导且保持配置与课表历史。
- 从既有干净发布副本构建 Windows x64 单文件 EXE，普通用户在中文及空格路径、PATH 不含 Python 的环境中通过包内导入、WakeUp CSV、重复 UID 保留和 Tk 组件运行检查。这是开发机隔离验证，不能替代另一台无 Python 电脑。
- 实际新 EXE 的首次引导和第二步窗口已操作核对，三种浏览器栏名称与按钮显示完整。仅使用隔离数据目录；原用户窗口未关闭，也未替用户添加书签。
- 包内 1647 个条目，5 个采集 / 配置资源与已测试源码字节一致；x64 标识 0x8664、Windows GUI 子系统 2。未发现个人数据目录、配置或已知私人字面量。个人课表、配置及历史共 587 个文件哈希保持不变。
- EXE SHA-256：`c3b4970697531dc993029f75eaba5e907e8d3262976e7b90fa59b6808a05326c`。本地候选版交付含 EXE、图文说明和校验值；源代码仅在既有干净发布副本整理，未提交或推送。

**未运行：** 本版本在 Edge、Chrome、Firefox 的实际书签安装、学校短范围 / 完整范围采集、10 条网页核对和无误报重复采集；QQ / 360 / 搜狗具体版本验证；另一台无 Python 电脑、系统实际缩放切换、iPhone 导入及两名同学独立操作。当前浏览器工具仅列出 Chrome 和内置浏览器，学校站点控制的既有连接故障仍未解决；没有新浏览器实采证据。基础功能检查通过不代表学校登录、书签执行、实际下载与手机导入通过。

官方依据：[Edge 快捷键](https://support.microsoft.com/en-us/edge/keyboard-shortcuts-in-microsoft-edge)、[Firefox 书签](https://support.mozilla.org/en-US/kb/bookmarks-firefox)、[AbortSignal.timeout 兼容性](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static)。维护证据位于忽略目录 `local/browser-compat-20260906/`：`full-tests.txt`、`packaged-runtime.json`、`native-ui-verification.json`、`bundle-audit.json` 和 `release-audit.json`。

## 2026-09-06 引导图片替换：1.0.0-rc4

按用户指定，用其提供的 1672 × 941 PNG 替换桌面首次准备第二步中的简易 Canvas 示意图。原图作为 `assets/bookmark-install.png` 内置，显示时等比缩放，不裁剪或改写原图；原文件、项目资源及最终 EXE 内图片 SHA-256 一致。下方继续说明 Edge / Chrome / Firefox 栏位对应关系。复制安装页按钮移至图片前，并在图片首次完成布局后回到页首，避免大图加载把标题挤出视野。

- 图片 SHA-256：`27930a40b83ce0d885a14b0c720ab80740ffa02bd1e4fd17e459c4838db68a6b`。
- 初次替换后完整 95 项 Python 测试及三组 JavaScript 测试通过；修正滚动和按钮位置后，受影响的三项现有桌面控件检查重跑通过，最终包内自检及原生窗口验证通过。未新增业务测试矩阵。
- 使用 [Pillow 12.3.0](https://pypi.org/project/pillow/12.3.0/) 进行运行时显示缩放。EXE 已包含依赖和图片；普通用户、PATH 不含 Python 的本机运行检查通过。原生窗口实查标题、复制按钮、图片和下方确认按钮；测试仅使用隔离数据目录。
- EXE SHA-256：`61a8084ede976ca2039f4c7861ff6d1a4e453d36632415a38038a1aaa73b1f6c`，大小 21,825,049 字节。原个人文件检查及发布包审计见 `local/guide-image-20260906/release-audit.json`；窗口效果记录见同目录 `updated-guide.jpg`。

本轮不改变采集逻辑或书签修正版 8。学校实采、另一台无 Python 电脑、其他浏览器与手机验收没有在本轮运行，前版标记的未验证环节继续保留。候选代码从既有干净发布副本整理，未提交或推送。

### 同日补正：使用说明中的引导图

补换 `使用说明.html` 中遗漏的旧 SVG，内嵌与 EXE 相同的原始 PNG；单独复制 HTML 无需携带额外图片。源码、干净发布副本、构建输出及 `dist/1.0.0-rc4/使用说明.html` 四份一致，分享 ZIP 已重建并更新校验值。核对内嵌图片字节、旧 SVG 移除、ZIP 内容及未改变 EXE；本轮仅修改说明资源，未重新运行采集和业务测试。证据见 `local/guide-html-image-20260906/verification.json`。

## 2026-09-06 GitHub 预发布检查

本次提交用于 `v1.0.0-rc4` 预发布，以上各阶段的“未提交或推送”描述其当时状态。已从既有干净发布副本重新运行完整检查，95 项 Python 测试和三组 JavaScript 模拟测试通过；源码文件限定为 52 个既有白名单文件，业务代码和资源与已测试的 rc4 构建一致，没有加入个人课表、配置或维护证据。CMD 的 Git 文件内容保持 CRLF。

交付包括单独 EXE、已补正图片的独立使用说明、包含软件和说明的 Windows x64 ZIP，以及各下载文件的 SHA-256 校验值。ZIP 内的 EXE、说明和校验文件与本地交付一致。该发布检查未重新采集学校或验证手机，STUDENT_ACCEPTANCE.md 中的实机待验项目继续有效。

<a id="verification-rc6"></a>
## 2026-09-06 rc6 预发布：双日历导出与首次引导修复

相对 rc4，首页和结果页增加独立的苹果日历 ICS 文件与邮件导入指引；WakeUp CSV 与 ICS 分别判断就绪、失败和手机确认。未保存过完整课表时，不再只凭旧书签确认跳过首次引导；同次运行确认后可继续获取，成功保存完整课表后重启进入更新页。使用说明的两种手机路线并列展示，附带已遮盖账号信息的书签位置图，四个官方链接放入对应步骤并保留页底内容。

本版 108 项 Python 测试和三组 JavaScript 模拟测试通过。最终 Windows x64 单文件 EXE SHA-256 为 `411af05242e21a0e80cd385eca7b54c3e751a68199eba11812861d62c3bec018`，与已经执行包内自检、首次引导和重启窗口验证的文件一致。自检采用隔离合成数据，开发机普通用户、PATH 不含 Python；不代表另一台无 Python 电脑已经验收。独立说明仅更新链接位置和发布文案，图片字节与对应资源一致。

发布源码限定为 52 个既有白名单文件及新增的 `assets/school-bookmark-location.png`，业务模块与已测试 rc6 构建一致。下载附件为 EXE、独立 HTML、内含中文文件名的 Windows x64 ZIP 和 SHA-256 校验值；未包含个人课表、配置、认证材料、维护证据或私人 Git 历史。

**未运行：** 本版学校短范围及完整采集、至少 10 条网页核对和无误报重复采集、浏览器实际安装、另一台电脑、iPhone 邮件附件导入与重复导入、两名同学独立操作。说明页桌面与手机宽度的浏览器视觉检查受本地文件 URL 策略限制未运行。此前 WebCal 订阅验收不能替代 ICS 邮件附件导入，详细清单见 STUDENT_ACCEPTANCE.md。

此前各阶段的“未提交或推送”描述当时状态。本节对应 `v1.0.0-rc6` 预发布，旧 rc4 版本继续保留。

<a id="verification-rc7"></a>
## 2026-09-07 rc7 预发布：重点操作提醒与大白话说明

等待浏览器文件时，醒目提醒在教务首页点击“同步医学院课表”书签；开始本地处理后收起这条提示。首页、结果页和 WakeUp 手机指引按当前导出报告显示每节课时长与学期第一天，当前秋季模板为 40 分钟、2026-09-07。其他学期、自定义时长或各节时长不同时以对应设置卡为准，不固定套用秋季数值。启动时的安全软件提示已改为大白话，提示使用作者提供的文件或链接，拿不准时截图联系作者确认。

从既有公开源码副本重新执行完整检查：**109 项 Python 测试和三组 JavaScript 模拟测试通过，退出码 0**。新增回归检查覆盖其他学期、45 分钟和各节时长不同的提醒。最终 EXE SHA-256 为 `75bf95ef079cc0eedc2eef61825aab8482cae4e6ee7bad06eb1645779fe8658f`，使用隔离合成数据通过打包自检，确认内置资源、两种日历导出、重复导入和 Tk 窗口正常；该次运行在开发机普通用户环境，PATH 含 Python。

RC7 的原生窗口核对覆盖初次启动、已有课表时启动、等待书签操作、自动接收隔离示例文件、结果页及 WakeUp 设置指引。9 月 7 日最后修订仅替换一处安全提示字符串，已重新构建、自检并查看启动窗口，随后在本次发布前对对应源码重跑完整测试。说明页保留两张原始图片、布局和步骤链接，本次发布整理仅进一步更新版本页链接和“候选版”字样。

发布仍限定为原有 53 个公开源码与资源文件。ZIP 内是中文命名的软件、图文说明和文件校验记录；Release 同时提供单独软件与说明。EXE 与已验证文件一致，源码模块与构建副本对应。个人课表、配置、认证材料、维护证据和私人 Git 历史不进入发布内容；原 rc7 本地包及旧 GitHub 版本保留。

**未运行：** 本版学校实采、手机导入、另一台无 Python 电脑、Windows 系统实际切换缩放、安全软件真实拦截流程及两名同学独立操作。包内自检和开发机窗口核对不替代这些验收。使用说明的浏览器视觉检查未在本次重跑，完整实机待验清单见 STUDENT_ACCEPTANCE.md。
<!-- END PRESERVED VERIFICATION HISTORY -->


## 2026-09-27 UI-FINAL：接回 Mac r3 与 Windows 最终回归

状态：源码限定接回 PASS；Windows 最终回归 FAIL，验收门禁 BLOCKED。不是发布验收通过。

- 对象为公开源码副本 main / HEAD `b7abbbfa0de8ec7d911622e29ff336ed2abaa90c` 加既有 Windows 未提交 UI 改动。核对 Windows/Mac handoff、逐文件 before/after 和依赖后，仅接回 desktop.py、desktop_theme.py、test_desktop.py、test_desktop_theme.py；本记录另行追加。原有未提交改动、CMD 和二进制原字节保留。
- Windows 11 10.0.26200 / Python 3.12.6 AMD64 / Tk 8.6.13 / Node 24.19.0，沿用已有解释器。每个子进程在导入产品前隔离 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、临时目录、下载目录、preferences 和启动/fallback diagnostics，全部使用合成数据。
- 定向 `-m unittest -v test_desktop test_desktop_theme test_platform_support`：exit 1，93 项中 85 PASS、2 FAIL、6 Mac SKIP。`check.py --python-timeout 1200`：exit 1，221 项中 212 PASS、1 FAIL、8 SKIP，另 3 组 JS PASS；Windows CMD 用例 PASS，额外 2 项 SKIP 为符号链接权限不足。未放宽单项断言。
- 全量失败为 `test_waiter_accepts_new_download_but_not_old_file_after_picker_cancel` 的 5 秒 join 后 busy 断言；定向另有 `test_worker_duplicate_start_and_manual_file_while_waiting` 同类失败。独立对照曾前后各 2 PASS；保留原 5 秒断言的后续观察中，接回前测试原件也复现失败。失败堆栈位于未改动的诊断文件替换或导出说明读取路径；底层耗时原因 UNKNOWN，未扩展修改业务逻辑。
- 源码 `desktop.py --data-root ISOLATED --self-test EVIDENCE/self-test.json`：exit 0 / PASS / frozen=false。各组测试前后产品与测试源码哈希稳定。
- 真实 Windows GUI、实际系统 200% DPI：完整页面、默认/窄窗口双卡、等待中取消选文件继续等待、合成处理、部分/全部导出失败、Explorer 双格式定位、作息滚动、详情默认/最小尺寸、Tab/Enter 进入诊断、200% 默认诊断保存按钮/隐私提示均有截图或状态证据。场景切换和错误注入属于测试夹具；OS 输入自动化不等于物理鼠标。诊断最小窗口实机缩小未成功验证，实际 100/125/150% DPI 为 NOT RUN；四档模拟缩放用例 PASS，不能替代实机。
- Windows 25 项产品 raw 指纹 `a3513d5079724703b11e40ffb1946d08607c75a514a182209f50ac5b04f681b8`；安全文本 CRLF→LF 后与 Mac r3 同为 `417c19a445e821d1bb448a7c432f4c42a1ef025682d1307428bb7f34c88ca88a`。48 项测试依赖 raw 为 `584ed75e98a2f421c460977f81aee7472ac32671eecdf7a1b907f236d1ff4a80`；两端 portable 同为 `eb8a1bfce9b6d03cb6c94d527106b286402c35977a504b2a037672ae7514f437`。CMD/二进制不做规范化；不宣称完整 raw 快照相同。
- Mac r3 所提供证据：最终源码定向 93 PASS；全量 220 PASS、1 Windows CMD SKIP、3 组 JS PASS；源码自检 PASS。Mac 实机截图按其 r1/r2 原始身份归属，本轮未重跑 Mac；r3 仅新增原型证据。未在接回后修改影响 Mac 的公共源码/资源，因此无 FINAL_TO_MAC 增量；本记录是唯一新增文档内容差异。
- 原始字节、限定 diff、逐文件指纹、完整命令/退出码、截图和原型对照存于维护者忽略目录 `local/ui-final-windows-20260927/`。学校实采、真实 WebCal、手机导入、书签安装验证、EXE/APP 构建、签名和发布均 NOT RUN；无 Git 写入或系统缩放/安全/网络改动。


## 2026-09-27 WAIT-STABILITY-FIX：等待线程测试同步与清理

Windows 本轮等待稳定性门禁：BLOCKED。只修改共享 test_desktop.py；产品源码、资源、UI、版本、DesktopJob/Service、sync 和 diagnostics 均未变。HEAD `b7abbbfa0de8ec7d911622e29ff336ed2abaa90c` / main 加已有未提交 UI 成果；旧失败记录保留。

- 改前原 5 秒断言矩阵：10 次，6 PASS、4 FAIL。新文件已被接收后仍处理，最长接收后样本约 12.2 秒；独立自然完成观察约 14.4 秒，旧断言仍 FAIL。os.replace 单次调用观察到约 8.45 秒；其底层原因 UNKNOWN，不据此归因磁盘或安全软件。瞬间 picker set/clear 在改前 10 次中均未被 worker 观察到。
- 修复以 Condition 确认 waiting、完整扫描和 picker 实际暂停；保留真实稳定检测、旧文件忽略与明确手选、新文件身份、一次提交、独立 CSV/ICS 字节与哈希、无错误、实际线程退出及锁释放。集成完成固定 30 秒预算；原取消检查仍为 3 秒。三个登记的 DesktopTests worker 使用有限 cleanup，活线程目录保留且报告失败；负向门闩验证 finished 不等于退出。
- 候选 1 的新增报告比较因 JSON 持久化类型表示差异失败 2 项；候选 2 只规范该比较表示，完整字段与输出校验保留。没有第三轮修复、自动重试至成功或改业务校验。
- 候选 2 小范围 5 PASS；A/B 交替 10 轮 20 PASS，再各 3 个独立子进程 6 PASS。定向 95 项：88 PASS、6 SKIP；同一个剩余用例产生 1 FAIL 和 1 清理 ERROR，两者不能当作两个独立失败用例相加；exit 1。
- `check.py --python-timeout 1200`：主动中断；已输出 31 个 PASS，但没有整组统计，剩余 Python 与 JS 为 NOT RUN；exit 1。源码 self-test exit 0。定向剩余阻断为未修改的 `test_reopened_setup_imports_existing_json_and_exposes_both_exports`：5 秒 Tk 截止后 running 仍为真，随后目录清理 WinError 145。按两次候选修正上限停止代码修复；仅终止本轮隔离全量进程树以避免重复已知清理风险。中断后 A/B 各独立 3 次另外记录，不能冒称完成全量后的顺序验证。实际 SKIP 不算 PASS。
- 所有进程在导入前隔离默认路径、preferences、临时与下载目录、启动/fallback diagnostics；实际模块来自内层公开源码副本，使用合成数据与已有 Windows Python 3.12.6。正式矩阵与观察性探针分别记录，没有并行运行回归或截图。
- 产品 25 项 raw 指纹仍为 `a3513d5079724703b11e40ffb1946d08607c75a514a182209f50ac5b04f681b8`；安全 portable 仍为 `417c19a445e821d1bb448a7c432f4c42a1ef025682d1307428bb7f34c88ca88a`。48 项测试依赖 raw 为 `9a0bc705ce13c42a4a7133f5a39aed46f1a9a120ccf781e5558ca2aac4daf174`，portable 为 `5feafffb113236e7b479dde02dd2c2a34108b75fe038b3d7a6a3a7d587f7b041`。CMD/PNG 保留 raw 字节，desktop.py 混合换行不动。
- 本轮证据在维护者忽略目录 `waiter-stability-20260927-162247`。生成 WAIT_FIX_TO_MAC 仅测试增量；产品快照未变，Mac 对新测试修订 NOT RUN，需定向复验，不要求无关页面重拍。底层 I/O 性能没有声称修复；有限次数通过不证明永不偶发。
- 学校、真实 WebCal、浏览器/手机、产品构建、签名、发布、Git 写入与系统设置操作均 NOT RUN；本轮不重做 UI。回滚按本轮 before/after 原字节哈希保护执行，本轮未自动回滚。


<a id="tk-widget-lifecycle-20260927"></a>
## TK-WIDGET-LIFECYCLE-FIX-20260927 — Windows 源码门禁 PASS

基线 main / b7abbbfa0de8ec7d911622e29ff336ed2abaa90c。只修共享窗口测试生命周期，产品字节未变；保留已有 UI 和 candidate2 的 WorkerObservation、核心测试与取消契约。
`test_desktop.py` before `43379ccbb66afb96f48f6e1b13dbdc4872bb43a06a95281d3ffb5f3f47e11d54` → after `01e0c13705fa7ae55c322ec28122fc63da1068deffe17dc2575c0eb7bab9a10f`。

旧 Windows targeted-final 的 1 FAIL + 1 cleanup ERROR 是同一 reopened 用例；原 5 秒截止后 running 仍真，dispose 后临时目录删除 WinError145。该原失败仍保留，本轮一次自然观察未复现；未将其他核心用例的 I/O 原因移植为本窗口根因，底层 I/O UNKNOWN。
现在保留 mainloop + 短 after，以固定集成预算同时确认真实 UI 已消费终态、线程已退出，并传播回调异常；相关 fixture 单一清理入口管理初始/重开窗口、额外后台线程、mock 和目录。提交前请求既有取消，提交后等待；清理超时保留活动目录，不撤销 worker 依赖的 mock，不以 dispose 替代线程退出。保留真实按钮、JSON、CSV/ICS、准确文件定位、输入字节、bookmark_ack、更新首页及锁重取断言。

三项新增回归（含门闩/心跳与预期超时、predicate/Tk 回调错误）PASS；目标新进程三次、三用例正反序、整个窗口类及六模块定向 PASS。受控 setUp 部分失败/提前断言失败保留原始预期失败，清理通过，单独计数。完整 `check.py --python-timeout 1200`（外层1560秒）实际结束：Ran 226 tests in 506.593s; OK (skipped=8)；全部根目录 JS 在该次执行。完整全量结束后目标及原两核心各一次 PASS，随后源码 self-test PASS。各批退出码、耗时、SKIP、PID和原始日志见本轮证据；最终批次无残留窗口测试线程/目录/poll。此前一次合并定向1200秒被外层监督中断，堆栈停在本轮逐用例重写审计JSON的取证代码；移除该额外同步I/O、改成结束时一次写出后重跑，旧中断不改写为PASS。
候选1负向测量把堆栈取证 I/O 算入2秒限制而 FAIL；候选2修正堆栈计时边界后，在整个窗口类又发现Tk调度3.56秒超出额外2秒断言；候选3按after不可抢占契约验证固定deadline及实际到期失败，保留0.08秒负向期限、30秒集成期限和取消期限，外层watchdog有界监督，所有失败日志不改写。

只读登记 `MAC_WAIT_FIX_RECORDS_TO_WINDOWS.zip`（SHA256 `8a9bf6ede1179dec8aa94597a6d9be14c9272de2925177e9802743baa4398330`）：包内59项校验一致；Mac candidate2 的170次限定 PASS 仅属于 before 测试哈希。不应用其中审计patch，不覆盖旧 Windows BLOCKED。本轮 after 在 Mac 为 NOT RUN。
Windows 本轮源码门禁 PASS 不代表性能已修复、安装包可发布；EXE/APP构建、学校实采、手机、其他电脑及新 Mac 修订均 NOT RUN。未提交/推送/拉取/合并/切分支/安装依赖/修改浏览器或系统。
本机忽略证据：`local/widget-lifecycle-20260927-174407`，含 FINAL_REPORT、COVERAGE_REVIEW、FROZEN_IDENTITY、限定diff及before原始备份；最终通过后仅生成一次最小 WIDGET_FIX_TO_MAC 测试增量。
