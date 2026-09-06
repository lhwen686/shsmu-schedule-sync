"""Generate a manually installed Chrome bookmark. Never launch a browser."""
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def downloads_folder():
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                value, _ = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')
                return Path(os.path.expandvars(value))
        except OSError:
            pass
    return Path.home() / 'Downloads'


def build_bookmark(root, config):
    modules = ('browser_transport.mjs', 'browser_capture.mjs', 'browser_ui.mjs')
    body = '\n'.join((root / name).read_text(encoding='utf-8').replace('export ', '', 1) for name in modules)
    public_config = {k: config[k] for k in ('semester', 'start', 'end_exclusive')}
    script = 'void(async()=>{\n' + body + '\nconst CONFIG=' + json.dumps(public_config, ensure_ascii=False) + ';\nawait runBookmark(CONFIG);\n})();'
    bookmark = 'javascript:' + quote(script, safe="~()*!.'")
    display = html.escape(bookmark, quote=True)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Chrome 课表同步书签</title>
<style>body{{max-width:820px;margin:56px auto;padding:0 24px;font:17px/1.8 system-ui,sans-serif;color:#24363c;background:#f5f8f8}}main{{background:white;padding:32px;border-radius:18px}}h1{{font-size:30px;line-height:1.3}}a.bookmark{{display:inline-block;background:#125d63;color:white;border-radius:10px;padding:12px 24px;text-decoration:none;font-weight:600}}textarea{{box-sizing:border-box;width:100%;height:100px;font:12px monospace}}small{{color:#596b70}}code{{background:#edf2f3;padding:2px 6px}}</style>
<main><h1>用现有 Chrome 同步课表</h1><p>学期 {html.escape(config['semester'])} · {config['start']} 至 {config['end_exclusive']}（结束日期不含）</p>
<p><strong>2026-09-06 修正版 5 · 空详情保护</strong> · 已安装过旧书签时，右键旧书签 → 修改，将网址替换为本页下方的完整内容。刷新本页后再复制。</p>
<ol><li>在你已经打开的 Chrome 中打开本页，将下方按钮拖到 Chrome 书签栏。<br><small>如果书签栏隐藏，按 Ctrl+Shift+B。只需安装一次。</small></li>
<li>双击本地 <code>同步课表.cmd</code>，它会等待 Chrome 下载的课表。</li>
<li>在 Chrome <a href="https://jwstu.shsmu.edu.cn/Home" target="_blank" rel="noopener">教务首页</a>正常登录后，留在显示本人学号的首页，点击刚才保存的书签。等待页面提示采集完成，本地窗口会自动生成结果。</li></ol>
<p><a class="bookmark" href="{display}">同步医学院课表</a></p>
<p>如果拖动不便，可以手动新建书签，名称填“同步医学院课表”，网址粘贴下面的完整内容：</p><textarea readonly onclick="this.select()">{html.escape(bookmark)}</textarea>
<p><small>书签仅向学校发送正常的同源读取请求；认证由现有浏览器处理。下载只包含课表响应，不读取或导出 Cookie、密码、会话存储。不安装或更改扩展，不启动或重启 Chrome。生成的 JSON 请保存在同步窗口显示的下载目录。</small></p></main></html>'''
    (root / 'chrome-bookmark.html').write_text(page, encoding='utf-8')
    return bookmark
