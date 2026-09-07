// Bundled with the capability check, transport and collector by prepare.py.
export async function runBookmark(config) {
  const revision = '2026-09-07.10';
  if (location.origin !== 'https://jwstu.shsmu.edu.cn') {
    alert('请先在添加课表按钮的同一个浏览器中打开并正常登录 https://jwstu.shsmu.edu.cn/Home，再点击书签或收藏夹里的课表按钮。');
    return;
  }
  const capabilities = browserCapabilities(window);
  if (!capabilities.ok) {
    alert('当前浏览器或网页模式缺少课表助手需要的功能，尚未读取课表。\n请使用更新后的 Edge、Chrome 或 Firefox 普通窗口，避开 IE 兼容模式。\n请在所用浏览器重新添加课表按钮并正常登录。\n缺少：' + capabilities.missing.join('、'));
    return;
  }
  let panel = document.getElementById('shsmu-sync-status');
  if (panel?.dataset.busy === 'true') { alert('课表正在采集，请等待完成。'); return; }
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'shsmu-sync-status';
    document.body.append(panel);
  }
  panel.style.cssText = 'position:fixed;right:18px;top:18px;z-index:2147483647;background:#fff;border:2px solid #12636a;border-radius:12px;padding:18px;width:520px;max-width:calc(100vw - 36px);max-height:calc(100vh - 36px);box-sizing:border-box;overflow:auto;font:16px/1.6 sans-serif;color:#123;box-shadow:0 4px 30px #0003;white-space:pre-line';
  const checkpoint = new Map();
  const keyFor = (path, params) => path + JSON.stringify(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));
  let checkpointAccount = '', started = 0, stage = '', trace = [], completed = null, downloadFailed = false;
  let currentResponse = null, lastDiagnostic = null, truncated = false;
  const browser = /Edg\//.test(window.navigator?.userAgent ?? '') ? 'Edge' : /Firefox\//.test(window.navigator?.userAgent ?? '') ? 'Firefox' : /Chrome\//.test(window.navigator?.userAgent ?? '') ? 'Chrome' : 'unknown';
  const stageCode = () => stage.includes('教师详情') ? 'details' : stage.startsWith('读取 ') ? 'month' : stage.includes('账号') ? 'homepage' : 'collect';
  const metadata = () => ({schema_version:1, browser, request_log:trace, truncated,
    download_attempted:true, download_observed:false});
  const heading = `课表采集 ${revision} · ${config.semester}\n`;
  const status = message => { stage = message; panel.textContent = heading + message; };
  const read = createSchoolReader(location.origin, {observe:entry => {
    if (trace.length < 2000) trace.push(entry); else { truncated = true; trace[1999] = entry; }
    if (entry.state === 'retry')
      panel.textContent = heading + stage + '\n请求暂未完成，稍后进行第 ' + (entry.attempt + 1) + '/3 次尝试…';
  }});
  function download(prefix, value) {
    const blob = new Blob([JSON.stringify(value)], {type:'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url;
    link.download = prefix + new Date().toISOString().replace(/[:.]/g,'-') + '.json';
    link.style.display = 'none';
    try {
      document.body.append(link);
      link.click();
    } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  }
  function button(label, action) {
    const element = document.createElement('button');
    element.textContent = label;
    element.style.cssText = 'display:block;margin-top:12px';
    element.onclick = action;
    panel.append(element);
  }
  async function run() {
    if (panel.dataset.busy === 'true') return;
    panel.dataset.busy = 'true';
    completed = null;
    downloadFailed = false;
    trace = [];
    truncated = false;
    currentResponse = lastDiagnostic = null;
    try {
      await collectSchedule(config, {
        status,
        accountKey:async () => {
          status('读取教务首页显示的账号…');
          // The normal /Home document visibly contains the student label.
          // Fetching /Home as a subrequest can redirect even when the timetable
          // page opens normally. Read the user's normal page instead.
          const onHomepage = /^\/Home\/?$/i.test(location.pathname);
          const match = onHomepage && (document.body.innerText ?? '').match(/学号\s*[:：]\s*([A-Za-z0-9-]+)/);
          if (!match) throw Object.assign(new Error('请在正常登录的教务首页点击书签采集'), {code:'HOMEPAGE_REQUIRED'});
          const bytes = new TextEncoder().encode(location.origin + ':' + match[1]);
          const account = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b=>b.toString(16).padStart(2,'0')).join('');
          if (account !== checkpointAccount || Date.now() - started > 15 * 60 * 1000) {
            checkpoint.clear();
            started = Date.now();
          }
          checkpointAccount = account;
          return account;
        },
        fetchJSON:async (path, params) => {
          const existing = checkpoint.get(keyFor(path, params));
          return existing ? existing.response : read(path, params);
        },
        // Only schema-validated, scrubbed timetable responses are retained.
        onResponse:record => checkpoint.set(keyFor(record.path, record.params), record),
        onResponseRead:record => { currentResponse = record; },
        saveCapture:async capture => {
          completed = {...capture, collector_revision:revision, started_at:new Date(started).toISOString(), diagnostics:metadata()};
          try { download('shsmu-capture-', completed); } catch { downloadFailed = true; }
          checkpoint.clear();
          checkpointAccount = '';
        }
      });
      if (downloadFailed) status('采集完成，但下载未能发起。请点击“重新下载采集文件”，并查看 浏览器下载提示。无需重新采集。');
    } catch (error) {
      const code = error?.code ?? 'DATA_VALIDATION';
      if (code === 'HOMEPAGE_REQUIRED') {
        checkpoint.clear();
        checkpointAccount = '';
        panel.textContent = heading + '请先打开教务首页，完成正常登录后，在首页再次点击“同步医学院课表”书签。';
        const home = document.createElement('a');
        home.href = 'https://jwstu.shsmu.edu.cn/Home';
        home.textContent = '前往教务首页';
        home.style.cssText = 'display:block;margin-top:12px;color:#12636a;font-weight:bold';
        panel.append(home);
        lastDiagnostic = browserDiagnostic({format:'shsmu-diagnostic-v1', collector_revision:revision,
          config, complete:false, failure:{stage:'homepage',code}, observed_at:new Date().toISOString()});
        return;
      }
      const request = error?.request ?? null;
      const message = error?.code ? error.message : '课表响应未通过数据校验';
      const diagnostic = browserDiagnostic({format:'shsmu-diagnostic-v1', collector_revision:revision,
        origin:location.origin, config, complete:false, observed_at:new Date().toISOString(),
        failure:{stage:stageCode(), code, request}, request_log:trace, responses:[...checkpoint.values()],
        current_response:currentResponse, diagnostics:metadata()});
      lastDiagnostic = diagnostic;
      panel.textContent = heading + '采集未完成：' + message + '\n位置：' + stage +
        (request ? '\n接口：' + request.path + '（尝试 ' + request.attempt + ' 次）' : '') +
        '\n已读取 ' + checkpoint.size + ' 份课表响应；本地旧课表保留。';
      try {
        download('shsmu-diagnostic-', diagnostic);
        panel.textContent += '\n已发起诊断 JSON 下载，可用于定位问题；它不能用于导入课表。';
      } catch {
        panel.textContent += '\n诊断文件未能下载，请保留此提示。';
      }
      if (error?.retryable) {
        panel.textContent += '\n可在本页继续采集，15 分钟内保留已读取进度；刷新页面会清除进度。';
        button('继续采集', run);
      } else {
        checkpoint.clear();
        checkpointAccount = '';
      }
    } finally {
      panel.dataset.busy = 'false';
      if (completed) {
        button('重新下载采集文件', () => {
          if (!completed) return;
          try { download('shsmu-capture-', completed); }
          catch { alert('下载未能发起，请保留本页并检查 浏览器下载提示后重试。'); }
        });
      }
      button('复制排错信息', () => {
        const report = lastDiagnostic ?? browserDiagnostic({format:'shsmu-browser-support-v1',
          collector_revision:revision, config, complete:false, observed_at:new Date().toISOString(),
          failure:downloadFailed ? {stage:'download',code:'DOWNLOAD_FAILED'} : null,
          diagnostics:metadata(), responses:completed?.responses ?? [...checkpoint.values()]});
        const text = JSON.stringify(report);
        const area = document.createElement('textarea');
        area.value = text; area.readOnly = true; area.style.cssText = 'display:block;width:100%;height:120px;margin-top:12px';
        panel.append(area); area.select?.();
        window.navigator?.clipboard?.writeText(text).catch(() => {});
        const help = document.createElement('div');
        help.textContent = '若未自动复制，请选中上方文本后复制。在助手“导出排错日志”中粘贴；含日期和节次，请仅发给维护者。';
        panel.append(help);
      });
      button('关闭提示', () => { checkpoint.clear(); completed = null; panel.remove(); });
    }
  }
  await run();
}
