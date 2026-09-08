# 项目状态

更新：2026-09-08。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生使用见 [README](README.md)，实机验收见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

**rc11 新增自动执行记录和“导出排错日志”，保留 rc10 的累计课表修复。** 当日原有 3 个 bug 已由用户确认实测关闭；该反馈仍归属于 rc10，不能替代 rc11 新书签验收。

<a id="baseline"></a>
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
