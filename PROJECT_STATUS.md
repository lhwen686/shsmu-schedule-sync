# 项目状态

<a id="baseline"></a>
## rc19 双平台预发布（2026-09-30）

发布分支 `codex/release-rc19` 基于合并 PR #17 后的 main。应用 `1.0.0-rc19`、Mac 修订 13 / 构建号 `19.0`，书签仍为 `2026-09-29.19`。
包含 BUG-010（Mac 检查更新找不到根证书）与 BUG-011（Tk 8.6 设置页标签空白）修复；Mac 的 rc16–rc18 均需手动下载本版一次（rc16 实测同样失败）。结果见 [rc19 验收](STUDENT_ACCEPTANCE.md#acceptance-rc19)。

## rc18 双平台预发布（2026-09-29）

发布分支 `codex/release-rc18` 基于 `codex/release-rc17`。应用 `1.0.0-rc18`、Mac 修订 12 / 构建号 `18.0`，书签仍为 `2026-09-29.19`。
rc17 实机发现：切换设置页标签时整页跳动。根因是 Tk 向焦点控件的每个祖先容器也发送 FocusIn，`_focus_visible` 把整张卡片滚入视野；本版只处理真正获得焦点的控件。点击标签时由助手自己切换页面，不再让 Tk 把焦点移入第一个输入框并选中文字（首次 rc18 工作流在 Mac 上由新测试发现仅靠 `focus_set` 不足，未发布）。
rc16 → rc17 实机自动更新已通过；rc17 → rc18 用于验证经 COS 下载的更新。结果见 [rc18 验收](STUDENT_ACCEPTANCE.md#acceptance-rc18)。

## 2026-09-30 Mac 更新证书与标签空白修复（未发布）

rc18 Mac 实测发现两处缺陷并在源码修复：BUG-010 包内 OpenSSL 找不到根证书，rc16–rc18 在学生 Mac 上检查更新全部失败（提示误导为网络问题）；BUG-011 Tk 8.6 下设置页标签切换后内容空白。新增 Mac PR 检查工作流，发布门禁模拟无 python.org Python 的 Mac。已随 rc19 发布；rc16–rc18 的 Mac 用户需手动下载一次。详见 [本次记录](VERIFICATION.md#mac-update-tls-tabs-20260930)。

## rc17 双平台预发布（2026-09-29）

发布分支 `codex/release-rc17` 基于 main `64527c1`（PR #14 签名更新清单、PR #15 腾讯云 COS 同步）。应用 `1.0.0-rc17`、Mac 修订 11 / 构建号 `17.0`，书签仍为 `2026-09-29.19`。
本版首次读取 `latest-signed.json`，下载源为 COS 优先、GitHub 备用；修复 clam 主题把选中标签页内边距改为 `6 4 6 2` 导致设置页标签点击后缩小错位的问题。
发布与更新流程的验证结果见 [rc17 验收](STUDENT_ACCEPTANCE.md#acceptance-rc17)。

## rc16 双平台预发布（2026-09-29）

基于已合并的公开 main `b4c324f`（PR #11），发布分支 `codex/release-rc16`。应用 `1.0.0-rc16`、Mac 修订 10 / 构建号 `16.0`，书签 `2026-09-29.19`；首次包含应用内更新（GitHub `update-channel` 的 `latest.json`）、界面改版和逐条读取。
[rc16 下载页](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc16) 已发布七个附件（含 `latest.json`），对应源码 `ccbc72dcb33c9ec4b7c33c0686b36aabdf5da022`；`update-channel` 预发布同时建立。首次[发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36539842428)因两个 Mac 专属测试与改版后行为不符而在发布前停止，修正测试后[重新运行](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36541396692)全部通过：两端各 265 项，Windows 258 PASS、7 SKIP，Mac 264 PASS、1 SKIP；三组 JS、原生构建、冻结自检、合包和线上回读 PASS。
本机回下载七个附件及更新通道清单，SHA-256、清单大小/哈希/包内 EXE 哈希、ZIP 完整性与隐私检查通过；程序更新模块经真实 GitHub 读取到 rc16；下载后的 Windows EXE 自检 PASS。
升级后需手动替换 `.19` 书签。rc15 没有更新功能，需手动安装本版一次。打包程序经网络的实际自动更新（需下一版本）、学校实采/耗时、手机导入、最终 EXE/APP 人工窗口及实际缩放仍为 NOT RUN；旧 rc15 附件保留。详见 [rc16 记录](VERIFICATION.md#release-rc16) 与 [验收表](STUDENT_ACCEPTANCE.md#acceptance-rc16)。

## 2026-09-29 更新清单签名源码更新（未发布）

分支 `codex/signed-update-manifest` 基于 `main` `dc8d443`。发布时另生成 `latest-signed.json`：原 `latest.json` 字节加 Ed25519 签名（内置纯 Python 实现，未增加依赖）。新版程序只接受由内置公钥（发布密钥 + 离线备份密钥）签名的清单，因此清单和安装包都可以放在任意镜像、代理或网盘直链；某一来源被篡改或内容过期时换下一个来源，不会停在旧版本。rc16 仍读取未签名的 `latest.json`，发布时两者同时上传。
发布前需在仓库 Secrets 设置 `UPDATE_SIGNING_KEY`，未设置时发布工作流会在打包阶段停止。私钥只保存在本机被忽略的 `local/update-signing/` 目录，需另行离线备份。
本地完整检查：Python 272 项 263 PASS、9 SKIP、0 FAIL；三组 JS PASS；签名实现通过 RFC 8032 测试向量，并与 `cryptography` 交叉比对。原生构建、带签名的 CI 发布、镜像实际下载为 NOT RUN。

## rc15 双平台预发布（2026-09-28）

基于已合并的公开 main `2c77b71`，发布分支 `codex/release-rc15`。应用 `1.0.0-rc15`、Mac 修订 9 / 构建号 `15.0`，书签 `2026-09-28.16`；保留现有设计及 PR #9 修复，仅更新发布版本、工作流和说明。
[rc15 下载页](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc15) 已发布六个附件，对应源码 `4501d8e5d63e9c2dd1b10919b38260193495d178`。[发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36444937755) 全部通过：Windows 224 PASS、7 SKIP，Mac 230 PASS、1 SKIP；两端三组 JS、原生构建、冻结自检、合包和线上回读 PASS。
本机回下载核对六个附件、25 项源码哈希和 64 个 Mac 符号链接通过；下载后的 Windows EXE 在中文空格路径、隔离数据及无 Python PATH 下自检 PASS。
升级后需手动替换 `.16` 书签。学校实采/耗时、手机导入、最终 EXE/APP 人工窗口及实际缩放仍为 NOT RUN；旧 rc14 附件保留。详见 [rc15 记录](VERIFICATION.md#release-rc15) 与 [验收表](STUDENT_ACCEPTANCE.md#acceptance-rc15)。

## 2026-09-29 回到逐条读取（已随 rc16 发布）

同分支。`.18` 首次（全量）实采在第 1、9 条详情即出现重试提示，用户要求完全回到最初读取方式。书签 `2026-09-29.19`：三个浏览器模块及对应 JS 测试恢复为并发改动前（`2c77b71~1`，即 `.14`）的逐条读取——一次一个请求、间隔 1 秒、每次最多等 45 秒，每次重读全部详情；与原版逐字节一致，仅修订号不同。`.16`–`.18` 的并发、分档超时、增量缓存与空详情重读均已撤回。预计约 4.5–5 分钟（此前三次原版全量实采 4:55–5:13、0 次重试）。需手动替换为 `.19` 书签；学校实采 NOT RUN。详见 [本次记录](VERIFICATION.md#rollback-sequential-20260929)。

## 2026-09-29 增量读取（未发布，已撤回）

同分支。`.17` 实采失败：学校当日详情 5–8 秒/条并出现一次 `[]` 空详情，按规则停止。实站只读验证：按课程（不带 MCSID）读取 11 门课均返回空，学校页面脚本中也没有批量接口；逐条读取的吞吐上限约 0.8 条/秒，每次全量读 128 条无法稳定在 1–2 分钟。书签 `2026-09-29.18`：详情增量读取（按账号摘要和学期把已校验的脱敏详情缓存在教务页 localStorage，未来 14 天内、缺失或无效的课次每次重读，每 14 天或手动完整重读），空详情先重读两次。首次仍为全量；之后预计 20–40 秒，学校实采 NOT RUN。需手动替换为 `.18` 书签。详见 [本次记录](VERIFICATION.md#incremental-read-20260929)。

## 2026-09-29 教务读取提速（未发布，已撤回）

同分支。实采记录显示 `.16` 书签 3 路并发有效，但一次 45 秒超时使其余 87 条退回单请求 + 1 秒间隔，整次 4 分 51 秒。书签 `2026-09-29.17`：每次尝试等待 15/30/45 秒，单次超时或网络错误只重试该条；HTTP 408/429/5xx 或累计 5 次超时/网络错误仍退回逐条。按该次实采耗时回放由 290 秒降至 101 秒。需手动替换为 `.17` 书签；学校实采耗时 NOT RUN。详见 [本次记录](VERIFICATION.md#fast-read-20260929)。

## 2026-09-29 界面改版与流畅度（未发布）

分支 `codex/ui-refresh-20260929`（基于审计修复 `ff6b1f4`）。界面改为浅色底加白色圆角卡片，首次引导精简为学期、书签、首次获取三步，书签页内嵌安装图示。修复 BUG-009 拖动缩放卡顿：同机对照每步中位数从 93–122 ms 降到 25–54 ms。启动构造从约 635 ms 降到约 210 ms，首页切换从约 190 ms 降到约 85 ms。

本地完整检查 246 项，237 PASS、9 SKIP；三组 JS PASS；本地 EXE 冻结自检 PASS。学校、手机、Mac 及实机缩放验收 NOT RUN。详见 [本次记录](VERIFICATION.md#ui-refresh-20260929)。

## 2026-09-29 缺陷审计修复（未提交、未发布）

本地分支 `codex/audit-fixes-20260929` 基于 `origin/main` `0812031`（产品源码与 rc15 发布标签一致）。修复内容：诊断拖慢导入、界面轮询停止后无法关闭、同学期缩小范围丢历史、`clean()` 删文字、临时文件遗留与占用提示、选文件期间等待到期、未来采集时间阻断、错误分类误导。

书签生成时压缩为 57,507 字符（原 71,583，Firefox 上限为 65,536）。采集代码和修订号 `.16` 不变，已安装 `.16` 书签的 Chrome/Edge 用户无需替换。

本地完整检查：Python 241 项 232 PASS、9 SKIP、0 FAIL；三组 JS PASS。学校、手机、Firefox/Safari 书签及人工窗口验收 NOT RUN。详见 [修复记录](VERIFICATION.md#audit-fixes-20260929)。

## 2026-09-28 读取提速与界面性能源码更新（未发布）

分支 `codex/perf-ui-20260928` 基于 `main` `8368647`。书签源码修订 `2026-09-28.16`：课程详情最多 3 个请求同时进行，失败后自动回到逐条读取；
Windows 滚动卡顿的主因（圆角背景图中心过小导致 ttk 平铺数万次）已修复；Mac 字号不再被缩至 0.75，并加宽内容列；两端滚动条改为无箭头圆角样式。
应用仍为 `1.0.0-rc14`，下方 rc14 附件不含本次改动；用户需在新版发布后手动替换书签。
已有本地 Windows 测试 EXE 构建及冻结自检 PASS；尚未发布。学校实采耗时、Mac APP 构建/原生窗口和手机导入为 NOT RUN，详见 [本次记录](VERIFICATION.md#perf-ui-20260928)。

## rc14 双平台预发布（2026-09-27）

[PR #7](https://github.com/lhwen686/shsmu-schedule-sync/pull/7) 已合入 `main`，合并提交
`ce218b9856af46460c5a68bdd313480e8418e5e6`。[PR #8](https://github.com/lhwen686/shsmu-schedule-sync/pull/8)
已合入 `main`（`433087de22d96428bc2d38824696eca1596fa594`）。
[v1.0.0-rc14 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc14)
对应源码 `b020baef05ae1456fa04a395d3e59780e52b3971`，提供 Windows x64 / Apple 芯片 Mac 安装包，
应用 `1.0.0-rc14`、Mac 修订 8、构建号 `14.0`。
书签仍为 `2026-09-26.14`；本轮不修改采集器、个人历史或配置。

[发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36317148883) 全部通过：
Windows 220 PASS、6 SKIP，Mac 225 PASS、1 SKIP；两端三组 JS、原生构建、冻结自检和合包校验 PASS。
六个附件经线上回读及本机独立回下载核对，64 个 Mac 符号链接、源码/书签指纹与包成员一致。
下载后的 Windows EXE 在中文空格路径且 PATH 不含 Python 时自检 PASS。
学校、手机及最终包完整原生窗口/全部缩放仍为 NOT RUN，见 [rc14 验收表](STUDENT_ACCEPTANCE.md#acceptance-rc14)。
哈希和执行记录见 [rc14 发布记录](VERIFICATION.md#release-rc14)。下方 rc13 和源码整理记录保留原时间归属。

## 2026-09-27 桌面界面与测试稳定性源码更新

基于公开 `main` 的 `b7abbbfa0de8ec7d911622e29ff336ed2abaa90c` 整理，包含医学绿主题、
侧栏与设置概览、随窗口宽度排列的 WakeUp / 苹果日历结果卡，以及 Windows / Mac 的滚动、焦点和对话框布局调整。
两种格式各自绑定展示文件的哈希记录手机导入确认；线程和窗口测试等待真实结束后再清理临时目录。
主题模块纳入构建源码指纹，包内自检同步覆盖新的设置入口。

本次 Windows 隔离源码检查为 226 项：218 PASS、8 SKIP、0 FAIL，三组 JavaScript 和源码自检 PASS。
最终 Mac 回传证据对应的限定源码集合一致，全量为 225 PASS、1 Windows CMD SKIP；本次没有重新运行 Mac。
验证对象、历史失败与限制见 [源码整理记录](VERIFICATION.md#source-sync-20260927)。

本次仅更新源码。应用仍为 `1.0.0-rc13`，书签仍为 `2026-09-26.14`；
下方 rc13 下载附件保留发布时的界面，不包含本次改动。新 EXE/APP 构建、学校实采和手机导入为 NOT RUN。

## rc13 双平台预发布（2026-09-26）

[PR #4](https://github.com/lhwen686/shsmu-schedule-sync/pull/4) 已合入 `main`（`cee1b98de6e2d898ef161608006f527838d38233`）；
[PR #5](https://github.com/lhwen686/shsmu-schedule-sync/pull/5) 已合入 `main`（`801e5023d2112106c869426661a929248468e9ea`）。
[v1.0.0-rc13 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc13)
对应源码 `bb0e97d1175509fe28d5eff78ff9907a0d4653a5`，提供 Windows x64 和 Apple 芯片 Mac 安装包。
应用版本为 `1.0.0-rc13`，Mac 修订 7、构建号 `13.0`，书签版本为 `2026-09-26.14`。

[发布工作流](https://github.com/lhwen686/shsmu-schedule-sync/actions/runs/36243606122)
通过两端完整检查、原生构建、冻结程序自检、合包与线上附件回读。
从 Release 独立回下载的六个附件通过校验和、源码指纹、书签、ZIP 内容和 Mac 符号链接核对；
下载后的 Windows EXE 在中文空格路径且 PATH 不含 Python 时自检 PASS。
细节和 SHA-256 见 [rc13 发布记录](VERIFICATION.md#release-rc13)。
升级后需在实际使用的浏览器中手动更新书签，并保留原课表目录、UID 与历史。
新版学校采集、手机导入、其他电脑及完整原生窗口验收仍需按
[rc13 学生验收](STUDENT_ACCEPTANCE.md#acceptance-rc13) 单独进行。

## 2026-09-26 公开源码合并记录

`codex/sync-local-work-20260926` 基于已推送的可靠性修复分支 `cdd52f9` 整理，
连同 9 月 26 日的界面文案经 PR #4 合入 `main`；审查时 `main` 的对比基线为 `3145dcb`。
个人维护目录仍保留独立 Git 历史、配置和课表；公开候选只包含审查过的源码与文档。

应用版本仍为 `1.0.0-rc12`，书签源码修订为 `2026-09-26.14`；
两类安装页和仓库中的示例书签页已由当前浏览器模块重新生成。
Windows 源码完整检查为 198 PASS、8 SKIP、0 FAIL，三组 JavaScript 检查与隔离源码自检 PASS。
具体命令、修复过的陈旧断言和限制见 [本次集成记录](VERIFICATION.md#ui-copy-public-20260926)。
本候选没有重新构建 EXE/APP、发布软件、安装用户书签、采集学校课表或验证手机导入；
当时 [rc12 下载包](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc12)仍使用 `.12` 书签和发布当时的界面。
若以后分发本候选，用户须在正常登录的浏览器中手动替换完整书签地址。

2026-09-22 可靠性修复候选已推送至 `codex/reliability-contract-commit-20260922`，
源码对象为 `c9e196bfa2abfb8b38f90ebb081dda8468e5176f`，包含跨语言参数契约和提交/输出边界修复。
书签源码修订为 `2026-09-22.13`，应用版本未改，未重新打包或发布；已有浏览器书签只由本人手动替换。
Windows 源码完整检查为 194 PASS、8 SKIP、0 FAIL，三组 JS 和源码 self-test PASS。
同一 SHA 的原生 Apple 芯片 Mac 检查为 201 PASS、1 项 Windows CMD SKIP、0 FAIL，
三组 JS 和源码 self-test PASS；Windows 跳过的 6 项 Mac 和 2 项符号链接场景均实际通过。
Mac 首轮依赖缺失及临时路径别名夹具错误保留记录；补齐临时依赖并规范 TMPDIR 后复查通过，未改产品或测试代码。
最终软件包、学校和手机验收仍为 NOT RUN；详见 [Mac 原生验收](VERIFICATION.md#reliability-mac-20260922)
及 [Windows 修复证据](VERIFICATION.md#reliability-commit-20260922)。
下方 rc12 分发和实采结果保留原日期、版本归属。

更新：2026-09-09。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生使用见 [README](README.md)，实机验收见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

## rc12 双平台同步与发布

Windows x64 与 Apple 芯片 Mac 使用同一份源码及 `2026-09-08.12` 采集面板。
应用版本统一为 `1.0.0-rc12`；Mac 为修订 6、构建号 `12.0`。
发布流程分别执行两端完整检查、原生构建、冻结程序自检和实际生成的书签校验，
再核对源码指纹与书签地址一致性，生成双平台 ZIP、单平台 ZIP、使用说明及 SHA-256。
[rc12 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc12)已发布，源码经 [PR #3](https://github.com/lhwen686/shsmu-schedule-sync/pull/3) 合入 main。
Windows 与 Mac 原生检查、合包、六个公开附件回下载及最终 Mac ZIP 本机隔离自检均通过；
发布源码为 `91fd600adf3ac263c76e9bb7667211ff5d4bbd1c`，后续提交仅补充交付记录和附件命名/回读门禁。
具体结果见 [rc12 记录](VERIFICATION.md#release-rc12)。
个人数据、配置、学校原始响应和本机证据不上传。

更新 APP/EXE 不会自动修改浏览器中已有的书签，需在实际采集的浏览器中手动替换；
新版面板底部应显示 `.12`。Mac Chrome 中由本人替换的书签完整地址已核对，
与 `.12` 安装页一致；这不是 Windows 那台电脑的书签安装证据。
学校、手机与其他个人电脑状态见 [rc12 验收](STUDENT_ACCEPTANCE.md#acceptance-rc12)。

下列 Mac 修订 5、UI 优化、Safari `.11` 与旧公开基线均为历史记录。

## Mac 修订 5 已生成软件包

用户要求交付助手软件，已把 Safari 引导与 `.12` 采集面板打入独立 Mac APP。
应用版本 `1.0.0-rc11 · Mac 修订 5`，构建号 `11.5`；内置运行环境，目标为 Apple 芯片 Mac。
完整回归、最终 ZIP 校验、独立环境包内自检及普通启动/键盘引导/安全退出通过。
本人鼠标与触控板操作、新包学校实采及手机导入仍待验；详细结果见
[Mac 修订 5](VERIFICATION.md#mac-r5) 和 [验收边界](STUDENT_ACCEPTANCE.md#acceptance-mac-r5)。
本轮仅本地交付，保留 Mac 修订 4 和个人数据，未提交或发布。

## 采集面板 UI 已优化（本地候选）

当前源码书签为 `2026-09-08.12`：标题、中文学期、状态和操作分区，版本放到底部，
完成后的长说明可展开。Safari 本地示例已检查标准宽度、360px 窄窗口和五种状态；
完整检查及生成书签核对通过，详见 [界面优化记录](VERIFICATION.md#collector-ui-20260909)。
本轮只优化 UI，未重新采集学校、重打包或发布；用户现有 `.11` 书签仍需手动替换才能应用新版。
以下 Safari 学校验收属于 `.11`，不作为 `.12` 的实采结果。

## Safari 本机适配已验证

上一轮源码新增 Safari 安装/下载指引和诊断识别，验收采集按钮为 `2026-09-08.11`。
Safari 26.6.2 已完成 17 次短范围、128 次全学期、27 张网页卡片和 12 条详情核对；
独立重复采集变化为 0/0/0，CSV 与 ICS 字节一致，沿用原 UID 和历史。
首次仅登录首页时返回空结构；打开学校“我的课表”再回首页后恢复，此准备步骤已加入引导。
187 项 Python 中 186 通过、1 项 Windows CMD 跳过，三组 JS、源码自检通过。
详见 [Safari 验收](STUDENT_ACCEPTANCE.md#acceptance-safari)。本轮未重打包 APP、提交或发布，
保留 Mac 修订 4 ZIP；旧 Mac 修订 4 源码服务也已验证能导入 `.11` JSON 并得到相同双导出。

## 历史：本地 Mac 修订 4

当前工作分支为 `codex/dual-platform-package-local`，在保留原有未提交修改的基础上，
按用户授权修复 Mac 启动位置恢复、安全退出、Finder 反馈及独立打包。
应用版本仍为 `1.0.0-rc11`，候选标识为 **Mac 修订 4**；本轮不更新公开附件。
源码修复与独立 Mac ZIP 已完成；186 项 Python 中 185 通过、1 项 Windows CMD 跳过，
三组 JavaScript、源码和最终包自检通过。用户已确认本轮滚动、点击及 Dock 恢复正常。
系统权限提示与下载后的首次打开仍待验，尚无 Developer ID 和公证。现有修改均未提交。
修复证据见 [Mac 修订 4](VERIFICATION.md#mac-r4)，设备验收见
[本轮验收](STUDENT_ACCEPTANCE.md#acceptance-mac-r4)，学生使用见 [Mac 说明](MACOS.md)。
下方记录此前公开基线和源码适配历史，不能作为新包的验收结果。

## 历史：rc11 与 Mac 源码试用基线

| 对象 | 已确认的范围 |
| --- | --- |
| 本轮修改前公开源码 | [3dd9f07](https://github.com/lhwen686/shsmu-schedule-sync/commit/3dd9f07bc4b77670594fff649885c3c54d049b29)，含 rc11 与其发布记录 |
| 本轮分支 | `codex/macos-local-trial`，从干净公开副本建立；记录提交可用 `git log -1 --format=%H -- VERIFICATION.md` 定位 |
| 应用 / 采集书签 | `diagnostics.py:APP_VERSION = 1.0.0-rc11`；`browser_ui.mjs` 修订 `2026-09-07.10` |
| 当前维护 | [FEAT-20260907-MAC](VERIFICATION.md#macos-local-trial)：Mac 源码适配、原生窗口、真实学校采集与 Windows 自动回归 |
| 发布状态 | [v1.0.0-rc11 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc11)已发布；源码 `b20abf6e536ef388ca40dd4f78aefe421a275bf8`；四个附件回下载逐字节及 SHA-256 核对 PASS，随后仅补记发布文档 |

本仓库使用干净公开历史。个人同步目录单独保留全部配置和历史，经审查的源码按清单更新，不把私人历史、个人课表或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 历史：rc11 行为与交付

`codex/macos-local-trial` 增加 Apple 芯片 Mac 源码运行支持，使用方式见 [MACOS.md](MACOS.md)。本机 156 项 Python 通过、1 项 Windows CMD 跳过，三组 JS 与源码自检通过；原生窗口流程、Chrome 真实短/全范围与独立重复采集完成，128 次课程的双导出和网页抽查一致。Windows Server 2025 runner 的 157 项 Python（含 CMD）、三组 JS 与源码自检也已通过；[PR #2](https://github.com/lhwen686/shsmu-schedule-sync/pull/2)保留完整检查。源码分支供审查，不改变 Windows rc11 发布附件；详细证据和未验设备见 [Mac 本机验收](STUDENT_ACCEPTANCE.md#acceptance-macos-local)。

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再由本人在平时登录教务的浏览器中点击书签。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认；电脑生成文件后仍需手工导入手机。桌面不上传 WebCal，原 CLI 仍可使用本人独立配置的服务。

rc11 默认在所选数据目录的 `local/diagnostics` 保留最近 30 天、总量最多 50 MB 的执行记录。遇到问题可选择本次或历史操作，导出一个 `shsmu-support-v1` ZIP。包内有中文摘要、阶段时间线、异常代码位置和必要的脱敏输入/处理前状态；日志写入失败不改变课表提交，当前记录尽力从内存补救导出。材料仍含日期与节次，仅由同学手动发给维护者。

升级后按已有引导手动替换一次书签；网页显示 `2026-09-07.10`。采集格式仍为 `shsmu-capture-v1`，新增可选浏览器诊断元数据，不参与内容哈希、UID 和变更判断。旧 JSON 继续可用，排错包会注明缺少浏览器记录。浏览器无法下载时可复制网页排错信息并粘贴进导出窗口。

桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；实际末次课程和 WakeUp 周数来自采集数据。未知学期或自定义范围不套用当前预设。合班分段和混合详情继续按明确排课关联，关联不完整或冲突时停止并保留旧版。

## 验证与后续

公开 Windows rc11 发布时的 147 项 Python 检查、三组 JavaScript 检查、生成书签验证、开发机窗口检查及最终 EXE 包内自检通过；对象和限制见 [执行日志验证](VERIFICATION.md#diagnostics-rc11)。

9 月 8 日已在本台 Mac / Chrome 补齐 .10 书签短范围、完整范围、12 条详情网页核对及独立重复采集。其他浏览器、手机、其他电脑与新手独立操作仍未验；不将本机结果套用于公开 EXE。9 月 7 日 [rc11 验收表](STUDENT_ACCEPTANCE.md#acceptance-rc11)保留历史，新增结果见上方 Mac 验收。

后续收到日志包，沿用 [修复流程](MAINTENANCE.md#fix-workflow) 登记、隔离复现、验证和审查。日志缺失或异常位置只能作为证据线索，不能自动判定根因。历史 [rc10 修复](VERIFICATION.md#bug-mixed-details-20260907)、[rc9 修复](VERIFICATION.md#bug-combined-classes-20260907) 及 [当日实测关闭](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout) 保留原版本归属。
