# 项目状态

更新：2026-09-07。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生操作见 [README](README.md)，实机待验见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

<a id="baseline"></a>
## 当前基线

| 对象 | 已确认的范围 |
| --- | --- |
| 程序功能基线 | `v1.0.0-rc7`，源码提交 `8ffdaffd83d6bcd23c79bcf4a58dff8646718dce` |
| 应用 / 采集书签 | 本地修复候选 `desktop_service.py:APP_VERSION = 1.0.0-rc8`；采集版本 `2026-09-07.9` |
| 当前维护 | [BUG-20260907-01](VERIFICATION.md#bug-json-handoff-20260907)：只下载到 JSON 后的继续入口；分支 `codex/fix-json-handoff-20260907`，从已核实的 `a2fe2ebdacdb642ae46ab2f92d0cb59ee8827125` 起步；修复提交以 Git 记录为准 |
| Git 状态依据 | 2026-09-07 整理前本地 `main`、rc7 标签和缓存 `origin/main` 相同；本轮没有联网或推送，不据此断言远端最新版本 |
| 发布证据 | [rc7 历史记录](VERIFICATION.md#verification-rc7)；同版本修订通过源码提交和产物哈希区分 |

本仓库使用干净的公开历史。后续修复从实际核实的公开提交建立分支；个人同步目录单独保留配置和完整历史，经审查的源码按清单更新，不把私人历史或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 当前行为与交付

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再在本人正常登录的浏览器中点击书签；文件生成后手机仍需手工导入。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认。桌面不上传 WebCal，原 CLI 仍可选择自行配置的服务，本项目不提供托管多用户日历。

已核实的桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；这两个用途不同。实际末次课程与 WakeUp 周数来自采集数据。未知学期或显式自定义范围不套用当前预设，设置变化后需手动更新书签。

学生下载入口见 [README](README.md)。最近已记录的公开候选包是 rc7；rc8 EXE / ZIP 仅在本地生成，没有推送或更新公开附件。新书签提示需本人手动替换后生效；已下载的 JSON 可直接选择导入。

## 验证与下一步

[本轮修复记录](VERIFICATION.md#bug-json-handoff-20260907)：改前 2 个复现用例失败，改后均通过；完整 111 项 Python、三组 JavaScript、最终 EXE 包内自检及开发机当前缩放窗口核对通过。没有收到该同学原 JSON，未将合成结果当作其文件验收。[历史 rc7 记录](VERIFICATION.md#verification-rc7) 和 [文档整理](VERIFICATION.md#docs-maintenance-20260907) 保留原对象与日期。

当前候选版的学校实采、手机、另一台无 Python 电脑、Windows 实际缩放及学生独立操作仍有未验项目；以 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md) 为准。旧版 Chrome 实采和 WebCal 订阅不能替代本版浏览器及 Apple Mail 附件导入验收。

下一步按 [修复流程](MAINTENANCE.md#fix-workflow) 记录具体问题、复现、回归和审查。恢复、回滚和发布检查均复用 [维护说明](MAINTENANCE.md)，不新增第二套任务记录。
