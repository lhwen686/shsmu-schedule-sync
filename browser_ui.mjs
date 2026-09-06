// Bundled with browser_transport.mjs and browser_capture.mjs by prepare.py.
export async function runBookmark(config) {
  const revision = '2026-09-06.6';
  if (location.origin !== 'https://jwstu.shsmu.edu.cn') {
    alert('请先在现有 Chrome 打开并正常登录 https://jwstu.shsmu.edu.cn/Home，再点击书签。');
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
  const heading = `课表采集 ${revision} · ${config.semester}\n`;
  const status = message => { stage = message; panel.textContent = heading + message; };
  const read = createSchoolReader(location.origin, {observe:entry => {
    trace.push(entry);
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
        saveCapture:async capture => {
          completed = {...capture, collector_revision:revision, started_at:new Date(started).toISOString()};
          try { download('shsmu-capture-', completed); } catch { downloadFailed = true; }
          checkpoint.clear();
          checkpointAccount = '';
        }
      });
      if (downloadFailed) status('采集完成，但下载未能发起。请点击“重新下载采集文件”，并查看 Chrome 下载提示。无需重新采集。');
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
        return;
      }
      const request = error?.request ?? null;
      const message = error?.code ? error.message : '课表响应未通过数据校验';
      const diagnostic = {format:'shsmu-diagnostic-v1', collector_revision:revision,
        origin:location.origin, config, complete:false, observed_at:new Date().toISOString(),
        failure:{stage, code, request}, request_log:trace, responses:[...checkpoint.values()]};
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
          catch { alert('下载未能发起，请保留本页并检查 Chrome 下载提示后重试。'); }
        });
      }
      button('关闭提示', () => { checkpoint.clear(); completed = null; panel.remove(); });
    }
  }
  await run();
}
