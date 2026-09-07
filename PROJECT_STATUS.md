# 项目状态

更新：2026-09-07。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生操作见 [README](README.md)，实机验收记录见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

**2026-09-07 收尾：当日 3 个 bug 已全部处理并关闭；用户确认已给大家实测，全部 OK。** 证据见 [实测收尾记录](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout)。

<a id="baseline"></a>
## 当前基线

| 对象 | 已确认的范围 |
| --- | --- |
| 程序功能基线 | `v1.0.0-rc7`，源码提交 `8ffdaffd83d6bcd23c79bcf4a58dff8646718dce` |
| 应用 / 采集书签 | 本地修复候选 `desktop_service.py:APP_VERSION = 1.0.0-rc10`；采集版本仍为 `2026-09-07.9` |
| 当前维护 | 2026-09-07 当日 [3 个 bug](VERIFICATION.md#verification-bugs-closed-20260907) 均已关闭；实测 PASS（用户确认）；修复源码分支 `codex/fix-mixed-calendar-details-20260907`，收尾前 HEAD `da0b58974e1a9a01ab15b10b415706f81bf82504`；未推送 |
| Git 状态依据 | 2026-09-07 整理前本地 `main`、rc7 标签和缓存 `origin/main` 相同；本轮未联网核对 GitHub，也未推送；不据此断言远端最新版本 |
| 发布证据 | [rc7 历史记录](VERIFICATION.md#verification-rc7)；同版本修订通过源码提交和产物哈希区分 |

本仓库使用干净的公开历史。后续修复从实际核实的公开提交建立分支；个人同步目录单独保留配置和完整历史，经审查的源码按清单更新，不把私人历史或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 当前行为与交付

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再在本人正常登录的浏览器中点击书签；文件生成后手机仍需手工导入。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认。桌面不上传 WebCal，原 CLI 仍可选择自行配置的服务，本项目不提供托管多用户日历。

已核实的桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；这两个用途不同。实际末次课程与 WakeUp 周数来自采集数据。未知学期或显式自定义范围不套用当前预设，设置变化后需手动更新书签。

学生下载入口见 [README](README.md)。最近已记录的公开候选包仍是 rc7；rc8、rc9 和 rc10 属于本地修复候选，没有推送或更新公开附件。本次兼容修复不改采集器，原有完整 JSON 可直接选择处理，不需要为此重新安装书签。

部分同日详情响应夹带其他排课；只有精确排课 ID 能完整覆盖主事件、课程/日期/管理编号一致且节次无冲突时才筛选。原始响应完整保留，教师、内容、身份及 WakeUp 节次共同使用筛选结果。

合班课程通过原事件的精确详情请求、合班标识、课程/日期及完整节次关联；保留主课表实际起止时间和源排课 ID。共用整段详情的分段事件按已覆盖的主排课节数分配节次及教师内容；不把共用详情 ID 当作每段课的独立身份。不完整或冲突的关联仍停止并保留旧版。

## 验证与下一步

[本轮修复记录](VERIFICATION.md#bug-mixed-details-20260907)：改前 3 个合成复现用例失败；改后完整 124 项 Python 与三组 JavaScript 通过。用户视频显示 rc6 的排课 ID 错误，rc9 也可离线复现。所提供真实采集的 131 次课程全部生成 CSV / ICS，逐条核对主时间、源标识、教师、节次和周次；重复处理同一响应无误报、输出字节不变。维护者原有 128 次普通课程及此前 132 次合班课程与 rc9 标准化和 ICS 完全一致。最终 EXE 自检、包审计和哈希以该修复记录为准，未推送或发布。历史 [rc9 修复](VERIFICATION.md#bug-combined-classes-20260907)、[rc8 修复](VERIFICATION.md#bug-json-handoff-20260907) 和 [rc7 发布](VERIFICATION.md#verification-rc7) 保留原对象与日期。

当日 bug 的同学实测已获用户总体确认（PASS）；原有逐项记录与本次反馈的范围见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md#acceptance-20260907-closeout)。

下一步按 [修复流程](MAINTENANCE.md#fix-workflow) 记录具体问题、复现、回归和审查。恢复、回滚和发布检查均复用 [维护说明](MAINTENANCE.md)，不新增第二套任务记录。
