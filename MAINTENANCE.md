# 维护说明

本文件保存维护流程和按需索引。学生操作见 [README](README.md)，当前版本见 [PROJECT_STATUS](PROJECT_STATUS.md)，历史证据见 [VERIFICATION](VERIFICATION.md)，实机待验见 [STUDENT_ACCEPTANCE](STUDENT_ACCEPTANCE.md)。命令只在本次任务授权允许时执行，不要求每次维护运行所有项目。

<a id="task-map"></a>
## 按问题读取

先确认当前仓库、HEAD 和未提交改动，再按下表读取；不通读所有历史。调查和旧体验记录中的“当前”“修正版”只表示当时状态。

| 问题或改动 | 先读源码 | 对应检查或资料 |
| --- | --- | --- |
| 书签、请求、下载、浏览器兼容 | [prepare.py](prepare.py)、[browser_ui.mjs](browser_ui.mjs)、[browser_capture.mjs](browser_capture.mjs)、[browser_transport.mjs](browser_transport.mjs)、[browser_compat.mjs](browser_compat.mjs) | [test_capture.mjs](test_capture.mjs)、[test_transport.mjs](test_transport.mjs)、[test_browser_compat.mjs](test_browser_compat.mjs)；接口问题再读 [DISCOVERY](DISCOVERY.md) 历史观察 |
| 来源、账号、范围、UID、提交及恢复 | [source.py](source.py)、[core.py](core.py)、[sync.py](sync.py) | [test_sync.py](test_sync.py)、[test_workflow.py](test_workflow.py)；涉及桌面调用时加相关桌面用例 |
| 桌面引导、取消、独立导出及手机确认 | [desktop.py](desktop.py)、[desktop_service.py](desktop_service.py) | [test_desktop.py](test_desktop.py)；对应 [学生验收](STUDENT_ACCEPTANCE.md) 项目 |
| WakeUp 作息、周次、CSV | [wakeup.py](wakeup.py) | [test_wakeup.py](test_wakeup.py)、相关 workflow / desktop 用例 |
| CMD、安装错误、已下载文件恢复 | 相应 CMD、[sync.py](sync.py)、[.gitattributes](.gitattributes) | [test_usability.py](test_usability.py)、相关 workflow 用例；[USABILITY](USABILITY.md) 是历史修补说明 |
| CLI WebCal、服务端 | [webcal.py](webcal.py)、[deploy/webcal_server.py](deploy/webcal_server.py) | [test_webcal.py](test_webcal.py)、[部署说明](deploy/README.md)；不因此调用真实服务 |
| 构建、资源或分发 | [build_desktop.py](build_desktop.py)、[desktop_smoke.py](desktop_smoke.py)、[requirements-build.txt](requirements-build.txt) | 完整检查、包内自检、产物审查及适用的学生实机验收 |
| 仅维护文档 | 本文件与相关文档章节 | 链接、事实归属、规则一致性、改动清单和保护文件哈希；不重跑程序矩阵 |

<a id="data-flow"></a>
## 入口与数据流

正常浏览器登录 → 手工书签顺序读取月课表及逐事件详情 → 脱敏 JSON 下载 → `source.py` 校验 → `sync.py` 检查完整性与账号范围 → `core.py` 标准化及身份匹配 → 保存完整运行 → 更新当前指针 → 导出。

`data/runs/<run_id>/` 保存原始业务响应、快照、差异及日历；`data/current.json` 指向完整版本，`data/schedule.json` 和 `data/previous.json` 是当前及上一标准化版本。故障排查不修改这些文件制造课程变化。

桌面入口由 `DesktopService` 在一次锁内处理等待、提交和输出。ICS 从完整快照生成；WakeUp 另需同次原始教师详情和作息校验。两种输出及手机确认独立，桌面不上传 WebCal。CLI 导入完成后可按本人配置上传，CSV 由独立入口导出。

学期预设及默认范围以 [当前状态](PROJECT_STATUS.md#baseline) 和配置来源为准；CLI 示例与桌面预设可以不同。学校修改字段或出现未核实的非空分支时停止并保留旧版，不从历史材料猜测新接口。

<a id="fix-workflow"></a>
## 一次修复如何完成

1. **登记与定界。** 在 VERIFICATION 的记录区追加一个问题编号，例如 `BUG-YYYYMMDD-01`；文档整理使用 `DOCS-YYYYMMDD-01`。记录症状、影响、基线提交和现有未提交改动。先检索这个编号及相关函数，确认问题没有已完成的修复。
2. **保留复现。** 写清触发步骤、预期和实际结果、运行环境及数据类型。程序缺陷优先用最小合成数据在改前版本复现，保留失败用例名称和输出；无法复现或不适合自动化时明确说明，不宣称已证实根因。
3. **限定改动。** 从已确认的公开源码提交建立 `codex/<问题简名>` 分支，只修改相关文件。个人同步目录的改前文档、文件哈希和未跟踪内容另行备份；不把私人历史或配置复制进公开源码，也不在两处分别重复修补业务逻辑。
4. **回归与审查。** 修复后执行同一复现及相关既有用例，再按下表补检查。单独检查最终 diff：是否解决触发条件、保留账号/UID/历史/提交边界、两种导出与上传隔离、CMD 换行、隐私和范围；记录审查方式、结论和剩余问题。未做独立审查就标 NOT RUN，不以测试通过代替审查。
5. **记录和提交。** 记录修复提交、测试证据和回滚依据。当前记录所在提交可用 `git log -1 --format=%H -- VERIFICATION.md` 定位，无需把尚未产生的提交哈希写回该提交。使用明确文件清单暂存，检查暂存 diff；不使用 `git add .` 收进无关变更。
6. **区分交付阶段。** 本地修复、公开源码提交、软件包发布、学校/手机验收分别记录。公开推送、发布和服务器操作必须在用户授权范围内；未完成适用验收时保留待验，不宣称学生版完整验收通过。批准的源码更新只按文件清单回到个人目录，保留其全部数据和设置。

最小记录字段见 [VERIFICATION 模板](VERIFICATION.md#record-template)。记录一个事实的位置保持唯一：长期规则在 AGENTS，流程在本文件，当前版本在 PROJECT_STATUS，修复证据在 VERIFICATION，设备验收在 STUDENT_ACCEPTANCE。

<a id="verification-gates"></a>
## 检查与完成标准

| 改动范围 | 必须取得的证据 | 完成边界 |
| --- | --- | --- |
| 文档、注释及链接整理 | 最终 diff、文件与锚点链接、版本事实和保护文件哈希 | 不执行安装、构建或业务测试；不把历史 PASS 变成本轮 PASS |
| 局部程序修复 | 改前复现、改后对应回归、影响路径的既有用例、diff 审查 | 不能复现或受环境限制的项目标 NOT RUN；界面改动补适用的实际窗口检查 |
| 账号、UID、范围、完整性、提交或导出逻辑 | 相关单元用例、workflow / desktop 路径和完整 `check.py` | 学校数据流受影响时补短范围、完整采集、至少 10 条网页核对和一次独立重复同步；未运行实采只算本地修复 |
| 采集器或浏览器资源 | 三组 JS 检查、重新生成安装页并检查实际生成书签、完整检查 | 用户手动替换书签；目标浏览器逐个进行短范围、全范围、10 条核对及重复同步，不能用同内核推定通过 |
| EXE、依赖、资源或候选版发布 | 对应源码完整检查、最终 EXE 包内自检及哈希、资源/隐私审查 | 包内自检不等于无 Python 电脑、Windows 实际缩放、学校或手机通过；逐项填写 STUDENT_ACCEPTANCE |
| WebCal 服务端或上传协议 | 本机临时服务回归、完整检查、授权后的实际服务校验与回滚依据 | 桌面仍不上传；模拟服务、已配置或已部署不等于真实订阅刷新已验收 |

PASS 必须注明对象、环境、时间、命令、退出码及证据；FAIL 保留错误和后续复查结果；NOT RUN 包括未执行、跳过、工具不可用或证据不足，并注明原因。无需执行的项目注明“不适用”及理由。记录实际执行/失败/跳过数量，不只抄“全部通过”横幅或安装元数据。

<a id="test-commands"></a>
## 已有检查命令

在**要验证的源码目录**执行，使用已经准备好的 Python 环境。统一入口是 `检查项目.cmd` 或：

```powershell
.\.venv\Scripts\python.exe -X utf8 check.py
```

[check.py](check.py) 调用 `unittest discover -s <源码目录> -p test_*.py -v`，随后顺序运行根目录的全部 `test_*.mjs`，任意一组失败返回非零。检查需要 Node.js；日常同步不依赖 Node.js。新克隆/工作树没有虚拟环境时，不据此宣称软件故障，也不未经授权安装依赖。

定向检查示例（模块按问题选择，不代替适用的完整检查）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest -v test_sync test_workflow
.\.venv\Scripts\python.exe -X utf8 -m unittest -v test_desktop
node test_capture.mjs
node test_transport.mjs
node test_browser_compat.mjs
```

测试使用合成数据和临时目录；WebCal 测试会启动仅监听回环地址的临时服务，桌面测试会创建 Tk 组件，Windows 使用体验用例会在临时目录执行 CMD 并创建不带 pip 的临时环境。它们仍是会运行程序、写临时文件的测试，不能在只读审计时执行。非 Windows 会跳过 CMD 场景，不算该场景通过。

<a id="local-operations"></a>
## 日常入口与恢复

学生操作以 [README](README.md) 为准。维护原 CLI 时，首次安装入口是 `setup.cmd`；日常先启动 `同步课表.cmd`，再在正常登录的教务首页点击本人已安装书签。程序等待本次下载，不自动导入启动前的旧文件。

| 情况 | 已有入口及边界 |
| --- | --- |
| 文件已下载或另存到其他目录 | `导入已下载课表.cmd` 选择完整 JSON，或拖到 `同步课表.cmd`；CLI 等待窗口应先关闭，桌面文件选择取消后继续等待 |
| 配置或学期改变 | 明确核对账号、学期和范围后，用 `sync.py --prepare` 生成安装页并由本人替换书签；CLI 显式 `--new-term` 不能切换账号 |
| 输出损坏 | `sync.py --repair` 从当前完整快照恢复标准化输出、ICS 和差异；会写文件，不会选择旧历史版本，也不恢复 WakeUp CSV |
| WakeUp 文件需要更新 | `导出 WakeUp 课表.cmd` 或 `wakeup.py`；原 CLI 同步不自动导出 CSV。可选作息文件遵循示例，仍检查全部实际起止时间 |
| 仅 CLI 上传失败 | 本地完整版本保留；明确需要重试本人已配置的 WebCal 时使用 `仅上传日历.cmd` / `sync.py --upload-only`，会访问真实服务 |
| 桌面两种文件部分失败 | 用界面的重新生成入口；WakeUp 作息失败不阻挡有效 ICS，旧 CSV 不作为本次成功输出 |
| 登录失效或学校返回异常 | 在既有浏览器正常登录，再采集；诊断文件不能充当完整课表，不改浏览器安全或网络设置迁就测试 |

CLI 退出码：0 成功；2 数据/访问检查失败；3 需重新认证；4 上传未确认、本地保留；1 本地异常；130 用户中断。重新处理同一下载不是新的学校采集；不完整采集不能当作停课或删除。

<a id="release"></a>
## 构建与发布

只在包含构建授权的任务中操作。开发窗口入口为 `desktop.py --data-root "独立验收目录"`；已有构建环境按 [requirements-build.txt](requirements-build.txt) 准备，构建命令为 `python -X utf8 build_desktop.py`。

构建脚本只生成 `dist/医学院课表助手.exe`、独立 HTML 和 EXE 校验文件；版本目录、ZIP 和所有下载附件的校验记录需单独整理核对，不能假定构建命令已经生成完整 Release。保留旧交付，不覆盖已分发的同版本附件；确需同版本说明修订时另存产物并记录修订日期及新哈希。

最终 EXE 的维护入口为 `医学院课表助手.exe --self-test "报告绝对路径.json"`。同时核对报告状态和进程退出码；它只用隔离合成数据，不能代替学校、手机、另一台电脑或真实浏览器验收。

发布记录关联：源码提交、应用版本、采集书签版本、构建环境、EXE/HTML/ZIP/附件 SHA-256、测试对象、人工审查和未验项目。生成书签后核对其与当前模块对应；CMD 在工作区、Git blob 及 ZIP 中都必须保持原始 CRLF，保留 `.gitattributes` 中的 `*.cmd -text`。

公开内容只来自干净历史和明确白名单；审查 Git 文件列表、暂存内容和最终包，不依赖 `.gitignore` 作为唯一隐私检查。通用文档可同步，本机目录、服务器细节、凭证及个人证据留在忽略目录中。发布后的附件回下载校验属于线上操作，需要相应授权。

<a id="rollback"></a>
## 安全回滚

改前保存目标文件原件、哈希、基线提交和已有工作区状态，包含未跟踪的目标文档。原件和个人证据仅留本机忽略目录；公开记录写脱敏结论和对应提交。

- 已提交的源码或文档：在适当分支用 `git revert <该次提交>` 形成可审查的反向提交；先检查后续改动和冲突，不重写已发布历史。
- 个人目录中的未提交更新：只逐个恢复本次备份的明确文件，核对哈希；不使用整仓库 `reset --hard`、`git clean` 或批量删除处理当前混有历史改动的目录。
- EXE：保留已核对的旧产物与哈希，先在独立数据副本验证旧程序能读取当前数据；兼容性未验时不能承诺直接降级安全。
- 数据：不重置 `data/current.json`、UID、修订号或历史运行。`--repair` 只是输出恢复；数据损坏或需要回到旧数据版本时另行定位和授权，不用代码回滚代替数据恢复。
- 服务器：仅在授权的服务端任务中按 [部署说明](deploy/README.md) 的备份和回滚边界操作，不连带修改其他服务。

<a id="client"></a>
## 客户端使用建议

先检查会话实际权限与当前工作目录，不仅看配置文件。审计选择只读，实现限制到工作区；线上与发布权限按任务授权。模型和全局插件无须为本项目重配，普通修复使用适当推理强度和一次明确的差异审查即可。默认单代理，不安装框架；旧聊天和记忆只帮助定位证据，不替代源码、提交或验收记录。
