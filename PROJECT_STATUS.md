# 项目状态

更新：2026-09-09。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生使用见 [README](README.md)，实机验收见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

## rc12 双平台同步与发布

Windows x64 与 Apple 芯片 Mac 使用同一份源码及 `2026-09-08.12` 采集面板。
应用版本统一为 `1.0.0-rc12`；Mac 为修订 6、构建号 `12.0`。
发布流程分别执行两端完整检查、原生构建、冻结程序自检和实际生成的书签校验，
再核对源码指纹与书签地址一致性，生成双平台 ZIP、单平台 ZIP、使用说明及 SHA-256。
当前正在完成发布门禁，具体结果见 [rc12 记录](VERIFICATION.md#release-rc12)。
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

<a id="baseline"></a>
## 本地 Mac 修订 4

当前工作分支为 `codex/dual-platform-package-local`，在保留原有未提交修改的基础上，
按用户授权修复 Mac 启动位置恢复、安全退出、Finder 反馈及独立打包。
应用版本仍为 `1.0.0-rc11`，候选标识为 **Mac 修订 4**；本轮不更新公开附件。
源码修复与独立 Mac ZIP 已完成；186 项 Python 中 185 通过、1 项 Windows CMD 跳过，
三组 JavaScript、源码和最终包自检通过。用户已确认本轮滚动、点击及 Dock 恢复正常。
系统权限提示与下载后的首次打开仍待验，尚无 Developer ID 和公证。现有修改均未提交。
修复证据见 [Mac 修订 4](VERIFICATION.md#mac-r4)，设备验收见
[本轮验收](STUDENT_ACCEPTANCE.md#acceptance-mac-r4)，学生使用见 [Mac 说明](MACOS.md)。
下方记录此前公开基线和源码适配历史，不能作为新包的验收结果。

## 当前基线

| 对象 | 已确认的范围 |
| --- | --- |
| 本轮修改前公开源码 | [3dd9f07](https://github.com/lhwen686/shsmu-schedule-sync/commit/3dd9f07bc4b77670594fff649885c3c54d049b29)，含 rc11 与其发布记录 |
| 本轮分支 | `codex/macos-local-trial`，从干净公开副本建立；记录提交可用 `git log -1 --format=%H -- VERIFICATION.md` 定位 |
| 应用 / 采集书签 | `diagnostics.py:APP_VERSION = 1.0.0-rc11`；`browser_ui.mjs` 修订 `2026-09-07.10` |
| 当前维护 | [FEAT-20260907-MAC](VERIFICATION.md#macos-local-trial)：Mac 源码适配、原生窗口、真实学校采集与 Windows 自动回归 |
| 发布状态 | [v1.0.0-rc11 预发布](https://github.com/lhwen686/shsmu-schedule-sync/releases/tag/v1.0.0-rc11)已发布；源码 `b20abf6e536ef388ca40dd4f78aefe421a275bf8`；四个附件回下载逐字节及 SHA-256 核对 PASS，随后仅补记发布文档 |

本仓库使用干净公开历史。个人同步目录单独保留全部配置和历史，经审查的源码按清单更新，不把私人历史、个人课表或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 当前行为与交付

`codex/macos-local-trial` 增加 Apple 芯片 Mac 源码运行支持，使用方式见 [MACOS.md](MACOS.md)。本机 156 项 Python 通过、1 项 Windows CMD 跳过，三组 JS 与源码自检通过；原生窗口流程、Chrome 真实短/全范围与独立重复采集完成，128 次课程的双导出和网页抽查一致。Windows Server 2025 runner 的 157 项 Python（含 CMD）、三组 JS 与源码自检也已通过；[PR #2](https://github.com/lhwen686/shsmu-schedule-sync/pull/2)保留完整检查。源码分支供审查，不改变 Windows rc11 发布附件；详细证据和未验设备见 [Mac 本机验收](STUDENT_ACCEPTANCE.md#acceptance-macos-local)。

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再由本人在平时登录教务的浏览器中点击书签。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认；电脑生成文件后仍需手工导入手机。桌面不上传 WebCal，原 CLI 仍可使用本人独立配置的服务。

rc11 默认在所选数据目录的 `local/diagnostics` 保留最近 30 天、总量最多 50 MB 的执行记录。遇到问题可选择本次或历史操作，导出一个 `shsmu-support-v1` ZIP。包内有中文摘要、阶段时间线、异常代码位置和必要的脱敏输入/处理前状态；日志写入失败不改变课表提交，当前记录尽力从内存补救导出。材料仍含日期与节次，仅由同学手动发给维护者。

升级后按已有引导手动替换一次书签；网页显示 `2026-09-07.10`。采集格式仍为 `shsmu-capture-v1`，新增可选浏览器诊断元数据，不参与内容哈希、UID 和变更判断。旧 JSON 继续可用，排错包会注明缺少浏览器记录。浏览器无法下载时可复制网页排错信息并粘贴进导出窗口。

桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；实际末次课程和 WakeUp 周数来自采集数据。未知学期或自定义范围不套用当前预设。合班分段和混合详情继续按明确排课关联，关联不完整或冲突时停止并保留旧版。

## 验证与后续

公开 Windows rc11 发布时的 147 项 Python 检查、三组 JavaScript 检查、生成书签验证、开发机窗口检查及最终 EXE 包内自检通过；对象和限制见 [执行日志验证](VERIFICATION.md#diagnostics-rc11)。

9 月 8 日已在本台 Mac / Chrome 补齐 .10 书签短范围、完整范围、12 条详情网页核对及独立重复采集。其他浏览器、手机、其他电脑与新手独立操作仍未验；不将本机结果套用于公开 EXE。9 月 7 日 [rc11 验收表](STUDENT_ACCEPTANCE.md#acceptance-rc11)保留历史，新增结果见上方 Mac 验收。

后续收到日志包，沿用 [修复流程](MAINTENANCE.md#fix-workflow) 登记、隔离复现、验证和审查。日志缺失或异常位置只能作为证据线索，不能自动判定根因。历史 [rc10 修复](VERIFICATION.md#bug-mixed-details-20260907)、[rc9 修复](VERIFICATION.md#bug-combined-classes-20260907) 及 [当日实测关闭](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout) 保留原版本归属。
