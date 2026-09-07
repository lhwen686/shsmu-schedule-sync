# 项目状态

更新：2026-09-07。默认只读本页，再按 [维护索引](MAINTENANCE.md#task-map) 选择资料。学生操作见 [README](README.md)，实机待验见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。

<a id="baseline"></a>
## 当前基线

| 对象 | 已确认的范围 |
| --- | --- |
| 程序功能基线 | `v1.0.0-rc7`，源码提交 `8ffdaffd83d6bcd23c79bcf4a58dff8646718dce` |
| 应用 / 采集书签 | `desktop_service.py:APP_VERSION = 1.0.0-rc7`；采集版本 `2026-09-06.8` |
| 当前维护 | `DOCS-20260907-01`：仅五类维护文档，分支 `codex/maintenance-docs-20260907`；文档提交以 Git 记录为准，程序版本不变 |
| Git 状态依据 | 2026-09-07 整理前本地 `main`、rc7 标签和缓存 `origin/main` 相同；本轮没有联网或推送，不据此断言远端最新版本 |
| 发布证据 | [rc7 历史记录](VERIFICATION.md#verification-rc7)；同版本修订通过源码提交和产物哈希区分 |

本仓库使用干净的公开历史。后续修复从实际核实的公开提交建立分支；个人同步目录单独保留配置和完整历史，经审查的源码按清单更新，不把私人历史或服务器配置合入本仓库。新克隆缺少个人数据与虚拟环境属于正常情况。

## 当前行为与交付

学生入口为 `医学院课表助手.exe`，源码入口为 `desktop.py`。先开始接收，再在本人正常登录的浏览器中点击书签；文件生成后手机仍需手工导入。WakeUp CSV 和 Apple ICS 分别判断就绪、失败及手机确认。桌面不上传 WebCal，原 CLI 仍可选择自行配置的服务，本项目不提供托管多用户日历。

已核实的桌面秋季预设为 `[2026-09-07, 2027-02-22)`，CLI 示例仍为 `[2026-09-07, 2027-01-18)`；这两个用途不同。实际末次课程与 WakeUp 周数来自采集数据。未知学期或显式自定义范围不套用当前预设，设置变化后需手动更新书签。

学生下载入口见 [README](README.md)。最近已记录的公开候选包是 rc7；本次只整理维护文档，没有改变软件、书签或发布附件。

## 验证与下一步

[历史 rc7 记录](VERIFICATION.md#verification-rc7) 有 109 项 Python、三组 JavaScript 检查、包内自检及开发机窗口核对；这些结果只适用于记录中的源码和产物。本轮文档检查见 [DOCS-20260907-01](VERIFICATION.md#docs-maintenance-20260907)。

当前候选版的学校实采、手机、另一台无 Python 电脑、Windows 实际缩放及学生独立操作仍有未验项目；以 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md) 为准。旧版 Chrome 实采和 WebCal 订阅不能替代本版浏览器及 Apple Mail 附件导入验收。

下一步按 [修复流程](MAINTENANCE.md#fix-workflow) 记录具体问题、复现、回归和审查。恢复、回滚和发布检查均复用 [维护说明](MAINTENANCE.md)，不新增第二套任务记录。
