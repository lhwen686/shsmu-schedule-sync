# 项目状态

更新：2026-09-07。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生使用见 [README](README.md)，实机验收见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

**rc11 新增自动执行记录和“导出排错日志”，保留 rc10 的累计课表修复。** 当日原有 3 个 bug 已由用户确认实测关闭；该反馈仍归属于 rc10，不能替代 rc11 新书签验收。

<a id="baseline"></a>
## 当前基线

| 对象 | 已确认的范围 |
| --- | --- |
| 修改前公开源码 | [29faebb](https://github.com/lhwen686/shsmu-schedule-sync/commit/29faebbfc252121c6cbbf1832cb7e70ef2edc274)，含 rc10 修复与当日实测收尾 |
| 本轮分支 | `codex/diagnostic-logs-rc11`，从干净公开副本建立；记录提交可用 `git log -1 --format=%H -- VERIFICATION.md` 定位 |
| 应用 / 采集书签 | `diagnostics.py:APP_VERSION = 1.0.0-rc11`；`browser_ui.mjs` 修订 `2026-09-07.10` |
| 当前维护 | [FEAT-20260907-01](VERIFICATION.md#diagnostics-rc11)：自动记录、脱敏结构重放、独立排错包及发布检查 |
| 发布状态 | 本地 EXE、HTML、ZIP 及 SHA-256 文件已验证；公开发布待执行 |

本仓库使用干净公开历史。个人同步目录单独保留全部配置和历史，经审查的源码按清单更新，不把私人历史、个人课表或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 当前行为与交付

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再由本人在平时登录教务的浏览器中点击书签。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认；电脑生成文件后仍需手工导入手机。桌面不上传 WebCal，原 CLI 仍可使用本人独立配置的服务。

rc11 默认在所选数据目录的 `local/diagnostics` 保留最近 30 天、总量最多 50 MB 的执行记录。遇到问题可选择本次或历史操作，导出一个 `shsmu-support-v1` ZIP。包内有中文摘要、阶段时间线、异常代码位置和必要的脱敏输入/处理前状态；日志写入失败不改变课表提交，当前记录尽力从内存补救导出。材料仍含日期与节次，仅由同学手动发给维护者。

升级后按已有引导手动替换一次书签；网页显示 `2026-09-07.10`。采集格式仍为 `shsmu-capture-v1`，新增可选浏览器诊断元数据，不参与内容哈希、UID 和变更判断。旧 JSON 继续可用，排错包会注明缺少浏览器记录。浏览器无法下载时可复制网页排错信息并粘贴进导出窗口。

桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；实际末次课程和 WakeUp 周数来自采集数据。未知学期或自定义范围不套用当前预设。合班分段和混合详情继续按明确排课关联，关联不完整或冲突时停止并保留旧版。

## 验证与后续

本轮 147 项 Python 检查、三组 JavaScript 检查、生成书签验证、开发机窗口检查及最终 EXE 包内自检通过；对象和限制见 [执行日志验证](VERIFICATION.md#diagnostics-rc11)。

新书签的学校短范围、完整范围、至少 10 条网页核对及独立重复采集均为 NOT RUN；各浏览器、手机、其他电脑与新手独立操作也不继承旧版本 PASS。具体待验和原因见 [rc11 验收表](STUDENT_ACCEPTANCE.md#acceptance-rc11)。

后续收到日志包，沿用 [修复流程](MAINTENANCE.md#fix-workflow) 登记、隔离复现、验证和审查。日志缺失或异常位置只能作为证据线索，不能自动判定根因。历史 [rc10 修复](VERIFICATION.md#bug-mixed-details-20260907)、[rc9 修复](VERIFICATION.md#bug-combined-classes-20260907) 及 [当日实测关闭](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout) 保留原版本归属。
