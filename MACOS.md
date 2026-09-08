# Mac 源码试用

本分支支持在 Mac 上运行 Tkinter 源码界面，生成 WakeUp CSV、苹果日历 ICS 和排错 ZIP。
目前没有可独立分发的 Mac 安装包。具体设备、检查结果和未验范围见
[Mac 本机验收](STUDENT_ACCEPTANCE.md#acceptance-macos-local)。

## 准备环境

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
定位窗口。本机验收使用一个仅调用已有 Python 和源码的本地 `.app` 启动入口，
并由用户允许任务目录访问后进行原生操作；它没有内置 Python，也不是发布安装包。

## 开发检查

完整检查还需要 Node.js。所有用例使用合成课表；不需要学校登录或个人日历：

```sh
.venv/bin/python -X utf8 check.py
.venv/bin/python -X utf8 desktop.py --data-root "$PWD/local/mac-trial-data" --self-test "$PWD/local/mac-self-test.json"
```

Mac 会明确跳过 Windows CMD 场景。分支配置了 GitHub Windows runner 检查，
运行同一测试入口及源码自检；其结果仍不等于 Windows 学生电脑、手机或学校实采验收。
该工作流只运行检查，不构建或发布软件。
