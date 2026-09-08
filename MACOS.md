# Mac 使用与源码维护

## 独立 Mac 应用

当前候选版为 **1.0.0-rc12 · Mac 修订 6**，仅面向 Apple 芯片（M 系列）Mac。
程序内置运行环境，使用 APP 不需要安装 Python。正式签名和 Apple 公证尚未完成。
本次状态见 [rc12 验收](STUDENT_ACCEPTANCE.md#acceptance-rc12)。
Windows 与 Mac 软件从同一份源码分别构建；旧修订包仍保留，不与新版混合合包。

1. 在 Finder 完整解压验收 ZIP，将 `Mac` 文件夹中的“医学院课表助手.app”拖入“应用程序”。
2. 双击打开。若提示“Apple 无法验证”，先确认来源与校验值，再由本人按
   [Apple 官方说明](https://support.apple.com/zh-cn/102445)在“系统设置 → 隐私与安全性”
   为该应用选择“仍要打开”。若提示损坏或将损坏电脑，停止打开并联系维护者。
3. 阅读包内 `使用说明.html`，在平时正常登录教务的浏览器中安装课表书签。
   Safari 使用下方引导；rc12 两端均生成 `.12` 新版书签。
   已有完整 JSON 时可直接点“文件已经下载”，无需重新采集。

拒绝下载文件夹权限后，可手动选择完整 JSON，或在助手中选择其他可读的下载文件夹。
不需要授予完整磁盘访问权限，也不要关闭系统安全检查或删除隔离属性。

Mac 默认课表与日志位于 `~/Library/Application Support/SHSMUScheduleAssistant`。
曾选过其他保存位置时，助手继续使用该位置。磁盘断开、位置记录损坏或权限不足时，
先连接磁盘、恢复权限并选择原目录；恢复前不能导入、导出或保存设置。
选择新的空目录须明确确认，原目录不迁移、不重置。恢复选择时损坏的偏好文件另行备份。

导出按钮在 Finder 选中 `wakeup.csv` 或 `calendar.ics`。定位失败时仍保留文件，
窗口提供路径和重试按钮，无需重新采集；排错 ZIP 的保存位置使用同一反馈方式。
Command+Q、应用菜单和 Dock“退出”均安全结束，保存开始后会等待保存及导出完成。
Command+W 关闭当前窗口；关闭主窗口会退出助手。点击 Dock 恢复已有窗口。

更新时先安全退出旧助手，再替换 APP。课表保存在 APP 外，不要删除保存目录。
Mac 系统版本字段为 `1.0.0`、构建号 `12.0`，“关于”显示完整版本及修订号。
包内原生程序最低要求 macOS 11.0；这不是对所有后续系统已完成实测的声明。
Intel Mac、其他系统实机和手机导入仍待独立验收。
Safari `.11` 的学校实采历史单独记在 [Safari 验收](STUDENT_ACCEPTANCE.md#acceptance-safari)。

## Safari 课表按钮

rc12 软件生成的采集按钮版本为 `2026-09-08.12`。更新软件后，请在实际采集的
浏览器中手动替换一次旧书签；软件更新不会自动修改浏览器已经保存的按钮。

1. 在 Safari 打开新版安装页。输入本地文件地址后若出现“确认要载入的文件”，
   核对所选 HTML 文件并点“打开”。
2. 选 **显示 → 显示个人收藏栏**，把绿色 **同步医学院课表** 按钮拖入该栏。
   不要只把本安装页收藏起来，也不要把书签代码贴进智能搜索栏执行。
3. 已有旧按钮时，按住 Control 点按它，选 **编辑地址**，粘贴安装页文本框中的
   全部网址，保留 `javascript:` 开头。也可用 **书签 → 编辑书签**。
4. 首次使用 Safari 时，先从教务首页打开一次 **我的课表**，看到课程后回首页。
   本机实测仅登录首页时接口返回空结构，打开学校课表页后恢复。
   在助手开始接收，再在显示本人学号的首页点击个人收藏栏里的课表按钮。
   采集面板底部应显示 `2026-09-08.12`。
5. 首次提示是否允许教务网站下载时，确认站点为 `jwstu.shsmu.edu.cn` 后允许下载。
   查看 Safari 工具栏的下载列表；若没有 JSON，在教务页点 **重新下载采集文件**。
   此操作只保存本次结果，不会再读取学校。回助手生成 `wakeup.csv` 和 `calendar.ics`；
   如果文件保存到别处，点 **文件已经下载** 选择本次 JSON。

本轮仍使用顺序、限量的学校同源 GET 和一个脱敏 JSON；无需启用开发者菜单、
允许 Apple 事件执行 JavaScript、安装扩展或修改安全设置。

操作名称依据 [Apple 个人收藏栏说明](https://support.apple.com/zh-cn/guide/safari/ibrwde09262e/26.0/mac/26)
和 [Apple 编辑书签说明](https://support.apple.com/zh-cn/guide/safari/ibrw1039/26.0/mac/26)。
具体设备与真实采集结果见 [Safari 验收](STUDENT_ACCEPTANCE.md#acceptance-safari)。

## 源码环境

以下仅适用于开发维护。使用独立 APP 的同学无需执行这些命令。

使用带 Tkinter 的 Python 3.12。验证过的开发机组合为 Apple 芯片、Python 3.12.14、
Tcl/Tk 9.0.4；不是对所有 Python 发行方式的保证。在仓库目录执行：

```sh
python3 -m tkinter
```

出现测试窗口后关闭它，再创建独立环境并安装仓库锁定的依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

如果第一步缺少 `_tkinter` 或无法打开窗口，先修复所用 Python 的 Tk 支持；
不要向共享 Python 环境反复安装课表依赖来解决图形库问题。

## 启动

下面的路径用于独立源码试用，首次会进入学期与书签引导。此目录已被 Git 忽略：

```sh
.venv/bin/python desktop.py --data-root "$PWD/local/mac-trial-data"
```

关闭后使用同一命令重开，保留原数据目录及全部 UID 和历史。不要用新的空目录
替代个人同步历史。省略 `--data-root` 时，Mac 默认数据和启动日志位于
`~/Library/Application Support/SHSMUScheduleAssistant`。

Mac 界面使用系统可用中文字体；书签栏提示为 **Command + Shift + B**，复制为
**Command+C**。两种导出按钮分别在 Finder 中选中文件。目录访问被拒时，
可以在“遇到问题”选择“文件已经下载”，手动选择其他位置的完整 JSON。

直接运行 Python 时，Dock 可能显示解释器名称，部分原生自动化工具也无法按应用名
定位窗口。早期源码验收曾使用依赖本机 Python 的启动入口；该历史对象不等于当前内置运行环境的独立 APP。

## 开发检查

完整检查还需要 Node.js。所有用例使用合成课表；不需要学校登录或个人日历：

```sh
.venv/bin/python -X utf8 check.py
.venv/bin/python -X utf8 desktop.py --data-root "$PWD/local/mac-trial-data" --self-test "$PWD/local/mac-self-test.json"
```

Mac 会明确跳过 Windows CMD 场景。分支配置了 GitHub Windows runner 检查，
运行同一测试入口及源码自检；其结果仍不等于 Windows 学生电脑、手机或学校实采验收。
双平台发布工作流还会分别构建、检查包内资源，并在两端通过及合包校验后生成候选版附件。

## 构建与独立 Mac ZIP

在已有构建环境的 Apple 芯片 Mac 上执行：

```sh
python -X utf8 build_desktop.py --output-dir dist/mac-rc12 --work-dir build/mac-rc12
python -X utf8 package_desktop.py --mac-dir dist/mac-rc12 --mac-only --output dist/mac-rc12.zip
```

构建使用仓库内的 Mac spec，在签名前写入版本与系统声明，并检查全部包内原生二进制的
arm64 最低系统要求。目录内的 `build-manifest.json` 记录源码指纹、依赖要求和文件清单。
独立 ZIP 附使用说明、首次打开说明和 `SHA256SUMS.txt`，保留中文路径、执行权限及符号链接。
省略 `--mac-only` 时仍创建供后续双平台合包使用的 Mac 组件。
