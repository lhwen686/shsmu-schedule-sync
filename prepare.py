"""Generate a manually installed browser bookmark. Never launch a browser."""
import html
import json
import os
from pathlib import Path
from urllib.parse import quote

BROWSER_MODULES = ('browser_compat.mjs', 'browser_transport.mjs', 'browser_capture.mjs', 'browser_ui.mjs')


def browser_check_script(resources):
    checker = (resources / 'browser_compat.mjs').read_text(encoding='utf-8').replace('export ', '', 1)
    return '<script>\n' + checker + '''
(function () {
  var result = browserCapabilities(window, true);
  var status = document.getElementById('browser-check');
  if (result.ok) {
    status.textContent = '基础功能检查通过。请继续添加课表按钮；学校登录和实际下载仍以采集结果为准。';
  } else {
    status.textContent = '这个浏览器或网页模式暂时不能使用。请用更新后的 Edge、Chrome 或 Firefox 普通窗口打开本页；不要使用 IE 兼容模式。';
    status.style.color = '#923d27';
    document.getElementById('browser-check-detail').textContent = result.missing.join('、');
    document.getElementById('browser-check-more').hidden = false;
    var links = document.getElementsByClassName('bookmark');
    for (var i = 0; i < links.length; i++) {
      links[i].removeAttribute('href');
      links[i].setAttribute('draggable', 'false');
      links[i].setAttribute('aria-disabled', 'true');
      links[i].textContent = '请先更换浏览器或网页模式';
    }
  }
})();
</script>'''


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


def build_bookmark(root, config, *, resources=None, desktop=False, output=None):
    resources = resources or root
    body = '\n'.join((resources / name).read_text(encoding='utf-8').replace('export ', '', 1) for name in BROWSER_MODULES)
    public_config = {k: config[k] for k in ('semester', 'start', 'end_exclusive')}
    script = 'void(async()=>{\n' + body + '\nconst CONFIG=' + json.dumps(public_config, ensure_ascii=False) + ';\nawait runBookmark(CONFIG);\n})();'
    bookmark = 'javascript:' + quote(script, safe="~()*!.'")
    display = html.escape(bookmark, quote=True)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>课表同步书签与收藏夹按钮</title>
<style>body{{max-width:820px;margin:56px auto;padding:0 24px;font:17px/1.8 system-ui,sans-serif;color:#24363c;background:#f5f8f8}}main{{background:white;padding:32px;border-radius:18px}}h1{{font-size:30px;line-height:1.3}}a.bookmark{{display:inline-block;background:#125d63;color:white;border-radius:10px;padding:12px 24px;text-decoration:none;font-weight:600}}textarea{{box-sizing:border-box;width:100%;height:100px;font:12px monospace}}small{{color:#596b70}}code{{background:#edf2f3;padding:2px 6px}}</style>
<main><h1>用你平时的浏览器同步课表</h1><p>学期 {html.escape(config['semester'])} · {config['start']} 至 {config['end_exclusive']}（结束日期不含）</p>
<p><strong>2026-09-07 修正版 9 · JSON 下载后继续导出指引</strong> · 已安装过旧书签时，右键旧书签 → 编辑或修改，将网址替换为本页下方的完整内容。刷新本页后再复制。</p>
<ol><li>在平时登录教务的浏览器中打开本页，将下方按钮拖到顶部的书签或收藏夹栏。<br><small>Edge 叫“收藏夹栏”，Chrome 叫“书签栏”，Firefox 叫“书签工具栏”；这三种浏览器可按 Ctrl + Shift + B 显示。请在同一个浏览器完成添加和学校登录。</small></li>
<li>双击本地 <code>同步课表.cmd</code>，它会等待浏览器下载的课表。</li>
<li>在这个浏览器的 <a href="https://jwstu.shsmu.edu.cn/Home" target="_blank" rel="noopener">教务首页</a>正常登录后，留在显示本人学号的首页，点击刚才保存的课表按钮。等待页面提示采集完成，本地窗口会自动生成结果。</li></ol>
<p><a class="bookmark" href="{display}">同步医学院课表</a></p>
<p>已经下载 JSON 或保存到了其他目录？双击 <code>导入已下载课表.cmd</code> 选择文件，也可把 JSON 拖到 <code>同步课表.cmd</code> 上。无需重复采集。</p>
<p>如果拖动不便，可以手动新建书签，名称填“同步医学院课表”，网址粘贴下面的完整内容：</p><textarea readonly onclick="this.select()">{html.escape(bookmark)}</textarea>
<p><small>书签仅向学校发送正常的同源读取请求；认证由现有浏览器处理。下载只包含课表响应，不读取或导出 Cookie、密码、会话存储。不安装或更改扩展，不启动或重启浏览器。生成的 JSON 请保存在同步窗口显示的下载目录。</small></p></main></html>'''
    if desktop:
        page = desktop_bookmark_page(config, bookmark, display)
    status = '''<p id="browser-check" role="status">正在检查浏览器基础功能…</p>
<noscript><p>本页未能运行检查。请在支持 JavaScript 的普通浏览器窗口打开本页。</p></noscript>
<details id="browser-check-more" hidden><summary>查看检查详情</summary><p id="browser-check-detail"></p></details>'''
    page = page.replace('<ol>', status + '\n<ol>', 1).replace('</main>', browser_check_script(resources) + '</main>')
    destination = output or root / 'chrome-bookmark.html'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page, encoding='utf-8')
    return bookmark


def desktop_bookmark_page(config, bookmark, display):
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>给浏览器添加课表按钮</title>
<style>body{{font:18px/1.75 "Microsoft YaHei",system-ui,sans-serif;color:#213c40;background:#eef5f3;margin:0;padding:28px}}
main{{max-width:760px;margin:auto;background:#fff;border-radius:20px;padding:36px}}h1{{font-size:30px;margin-top:0}}
.bookmark{{display:inline-block;background:#12645a;color:white;text-decoration:none;border-radius:10px;padding:14px 28px;font-weight:bold}}
.hint{{background:#f0f6f5;padding:16px;border-radius:10px}}small{{color:#55706b}}textarea{{width:100%;height:90px;box-sizing:border-box}}
svg{{width:100%;height:auto}}li{{margin:14px 0}}button{{font:inherit}}</style>
<main><small>医学院课表助手 · 首次准备</small><h1>给你平时的浏览器添加课表按钮</h1>
<p>请在<b>平时登录教务的同一个浏览器</b>打开本页。这一步只需做一次，以后登录教务首页，点课表按钮即可。</p>
<ol><li>按 <b>Ctrl + Shift + B</b> 显示顶部的书签或收藏夹栏。<br><small>Edge：收藏夹栏 · Chrome：书签栏 · Firefox：书签工具栏。</small></li>
<li>按住下面的绿色按钮，<b>拖到地址栏下方的这一栏</b>，再松开鼠标。不要直接点击绿色按钮。</li></ol>
<p><a class="bookmark" href="{display}">同步医学院课表</a></p>
<svg viewBox="0 0 680 155" role="img" aria-label="示意：把绿色按钮拖到地址栏下方的书签栏">
<rect x="4" y="4" width="672" height="145" rx="12" fill="#f1f5f4" stroke="#bdceca"/>
<rect x="22" y="17" width="635" height="31" rx="6" fill="white"/><text x="38" y="39" font-size="15" fill="#62716d">浏览器地址栏</text>
<rect x="22" y="57" width="635" height="39" rx="6" fill="#d4eae3"/>
<text x="37" y="82" font-size="17" fill="#145e51">★ 同步医学院课表</text>
<path d="M390 133 Q380 75 260 77" fill="none" stroke="#12645a" stroke-width="3"/>
<path d="M272 70 L259 77 L272 85" fill="none" stroke="#12645a" stroke-width="3"/>
<text x="422" y="132" font-size="16" fill="#36584f">拖到这里</text></svg>
<p class="hint"><b>添加后回到“医学院课表助手”，点击“我已添加课表按钮”。</b><br>助手收到课表后才能确认按钮是否正常工作。</p>
<p class="hint"><b>点击书签后只下载到 JSON？还需回助手生成手机文件。</b><br>打开“医学院课表助手”，点“文件已经下载”，选择浏览器下载的 <code>shsmu-capture-…json</code>。检查通过后，点“导出 WakeUp 文件”获取 <code>wakeup.csv</code>，或“导出苹果日历”获取 <code>calendar.ics</code>，再在手机导入。无需重新采集，也不要把 JSON 改名为 CSV 或 ICS。旧版助手可从“遇到问题”找到选文件入口。</p>
<details><summary>已有旧书签，或拖动不成功</summary><p>在顶部的书签或收藏夹栏右键旧课表按钮 → 编辑或修改 → 把“网址 / URL / 地址”替换为下面全部内容。Firefox 可右键书签 → 编辑书签。新建书签也可以使用这段网址。点击文本框即可全选，再按 Ctrl+C 复制。</p>
<textarea readonly onclick="this.select()">{html.escape(bookmark)}</textarea></details>
<details><summary>QQ、360、搜狗浏览器，或找不到下载文件</summary><p>这些浏览器需按具体版本实测，不能仅凭名称保证可用。请先看本页检查结果；如果处于“兼容 / IE 模式”，本人切回普通 / 极速模式后重新打开本页。不要在微信、QQ 聊天中的内嵌网页里添加。</p><p>在浏览器的下载列表查找课表；可在助手点“文件已经下载”选择文件，或“选择下载文件夹”。不需要修改浏览器设置。</p></details>
<p><small>学期：{html.escape(config['semester'])} · 采集按钮版本：2026-09-07.9<br>
本人在同一个浏览器正常登录；课表按钮只读取学校课表，不读取密码、Cookie 或会话存储。Edge、Firefox 已加入通用流程，学校实采待验证。</small></p></main></html>'''
