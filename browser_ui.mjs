// Bundled with the capability check, transport and collector by prepare.py.
export async function runBookmark(config) {
  const revision = '2026-09-08.12';
  if (location.origin !== 'https://jwstu.shsmu.edu.cn') {
    alert('请先在添加课表按钮的同一个浏览器中打开并正常登录 https://jwstu.shsmu.edu.cn/Home，再点击书签或收藏夹里的课表按钮。');
    return;
  }
  const capabilities = browserCapabilities(window);
  if (!capabilities.ok) {
    alert('当前浏览器或网页模式缺少课表助手需要的功能，尚未读取课表。\n请使用更新后的 Safari、Edge、Chrome 或 Firefox 普通窗口，避开 IE 兼容模式。\n请在所用浏览器重新添加课表按钮并正常登录。\n缺少：' + capabilities.missing.join('、'));
    return;
  }
  let panel = document.getElementById('shsmu-sync-status');
  if (panel?.dataset.busy === 'true') { alert('课表正在采集，请等待完成。'); return; }
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'shsmu-sync-status';
    document.body.append(panel);
  }
  panel.textContent = '';
  panel.style.cssText = 'position:fixed;right:16px;top:16px;z-index:2147483647;display:block;background:#fff;border:1px solid #dce7e5;border-radius:18px;padding:24px;width:460px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);box-sizing:border-box;overflow:auto;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-align:left;color:#233b3c;box-shadow:0 12px 48px #173b3826;white-space:normal;overflow-wrap:anywhere;color-scheme:light';
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', '课表采集');
  function part(tag, text, css, parent = panel) {
    const element = document.createElement(tag);
    element.textContent = text;
    element.style.cssText = 'box-sizing:border-box;font:inherit;color:inherit;' + css;
    parent.append(element);
    return element;
  }
  const header = part('div', '', 'display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap');
  part('h2', '课表采集', 'margin:0;font-size:22px;line-height:1.4;font-weight:650;letter-spacing:.02em', header);
  const badge = part('span', '', 'display:inline-block;flex-shrink:0;border-radius:20px;padding:4px 10px;font-size:12px;font-weight:600', header);
  const term = /^(\d{4})-(\d{4}):([12])$/.exec(config.semester);
  part('div', term ? `${term[1]}–${term[2]} 学年 · 第 ${term[3]} 学期` : `学期：${config.semester}`, 'margin-top:6px;color:#617775;font-size:13px');
  const content = part('div', '', 'margin-top:20px;padding:18px;background:#f3f8f7;border:1px solid #e3eeeb;border-radius:12px');
  content.setAttribute('role', 'status');
  content.setAttribute('aria-live', 'polite');
  content.setAttribute('aria-atomic', 'true');
  const messageTitle = part('div', '', 'font-size:16px;font-weight:600;line-height:1.5', content);
  const messageText = part('div', '', 'margin-top:8px;color:#536c69;white-space:pre-line', content);
  const instructions = part('details', '', 'margin-top:16px');
  instructions.hidden = true;
  part('summary', '查看下载与导入说明', 'cursor:pointer;color:#426c65;font-size:13px', instructions);
  const instructionText = part('div', '', 'margin-top:10px;color:#617775;font-size:13px;white-space:pre-line', instructions);
  const actions = part('div', '', 'display:flex;gap:8px;flex-wrap:wrap;margin-top:18px');
  const support = part('div', '', '');
  part('div', `课表助手 · v${revision}`, 'margin-top:18px;padding-top:12px;border-top:1px solid #edf1f0;color:#6d807d;font-size:11px');
  function state(label, warning = false) {
    badge.textContent = label;
    badge.style.color = warning ? '#8a5013' : '#176856';
    badge.style.background = warning ? '#fff2dc' : '#e8f4ed';
  }
  function showMessage(message) {
    const [first, ...rest] = message.split('\n');
    messageTitle.textContent = first;
    messageText.textContent = rest.join('\n\n');
  }
  const checkpoint = new Map();
  const keyFor = (path, params) => path + JSON.stringify(Object.fromEntries(Object.entries(params).sort(([a],[b])=>a.localeCompare(b))));
  let checkpointAccount = '', started = 0, stage = '', trace = [], completed = null, downloadFailed = false;
  let currentResponse = null, lastDiagnostic = null, truncated = false;
  const agent = window.navigator?.userAgent ?? '';
  const browser = /Edg\//.test(agent) ? 'Edge' : /Firefox\//.test(agent) ? 'Firefox' : /Chrome\//.test(agent) ? 'Chrome' : /Version\/[\d.]+.*Safari\//.test(agent) ? 'Safari' : 'unknown';
  const stageCode = () => stage.includes('教师详情') ? 'details' : stage.startsWith('读取 ') ? 'month' : stage.includes('账号') ? 'homepage' : 'collect';
  const metadata = () => ({schema_version:1, browser, request_log:trace, truncated,
    download_attempted:true, download_observed:false});
  const status = message => { stage = message; showMessage(message); };
  const read = createSchoolReader(location.origin, {observe:entry => {
    if (trace.length < 2000) trace.push(entry); else { truncated = true; trace[1999] = entry; }
    if (entry.state === 'retry')
      showMessage(stage + '\n请求暂未完成，稍后进行第 ' + (entry.attempt + 1) + '/3 次尝试…');
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
  function button(label, action, primary = false) {
    const element = part('button', label, 'appearance:none;display:inline-block;min-height:40px;max-width:100%;margin:0;padding:9px 13px;border:1px solid ' + (primary ? '#176856' : '#d9e3e0') + ';border-radius:9px;background:' + (primary ? '#176856' : '#fff') + ';color:' + (primary ? '#fff' : '#42625c') + ';font-size:13px;font-weight:500;line-height:1.5;text-align:center;cursor:pointer', actions);
    element.type = 'button';
    element.onclick = action;
  }
  async function run() {
    if (panel.dataset.busy === 'true') return;
    panel.dataset.busy = 'true';
    actions.textContent = '';
    support.textContent = '';
    instructions.hidden = true;
    instructions.open = false;
    state('正在采集');
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
      if (downloadFailed) {
        state('等待下载', true);
        showMessage('课表已采集，下载未能发起\n请点击“重新下载采集文件”，并查看浏览器下载提示。无需重新采集。');
      } else if (completed) {
        state('采集完成');
        messageTitle.textContent = stage.split('；')[0];
        messageText.textContent = '已发起课表 JSON 下载。\n回到“医学院课表助手”继续处理；若未自动处理，点击“文件已经下载”选择刚下载的 JSON。';
        instructionText.textContent = stage.split('\n').slice(1).join('\n\n');
        instructions.hidden = false;
      }
    } catch (error) {
      const code = error?.code ?? 'DATA_VALIDATION';
      if (code === 'HOMEPAGE_REQUIRED') {
        checkpoint.clear();
        checkpointAccount = '';
        state('需要登录', true);
        showMessage('请先打开教务首页\n完成正常登录后，在首页再次点击“同步医学院课表”书签。');
        const home = part('a', '前往教务首页', 'display:inline-block;padding:9px 13px;border-radius:9px;background:#176856;color:#fff;text-decoration:none;font-size:13px', actions);
        home.href = 'https://jwstu.shsmu.edu.cn/Home';
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
      state('采集未完成', true);
      showMessage('采集未完成：' + message + '\n位置：' + stage +
        (request ? '\n接口：' + request.path + '（尝试 ' + request.attempt + ' 次）' : '') +
        '\n已读取 ' + checkpoint.size + ' 份课表响应；本地旧课表保留。');
      try {
        download('shsmu-diagnostic-', diagnostic);
        messageText.textContent += '\n\n已发起诊断 JSON 下载，可用于定位问题；它不能用于导入课表。';
      } catch {
        messageText.textContent += '\n\n诊断文件未能下载，请保留此提示。';
      }
      if (error?.retryable) {
        messageText.textContent += '\n\n可在本页继续采集，15 分钟内保留已读取进度；刷新页面会清除进度。';
        button('继续采集', run, true);
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
        }, true);
      }
      button('复制排错信息', () => {
        const report = lastDiagnostic ?? browserDiagnostic({format:'shsmu-browser-support-v1',
          collector_revision:revision, config, complete:false, observed_at:new Date().toISOString(),
          failure:downloadFailed ? {stage:'download',code:'DOWNLOAD_FAILED'} : null,
          diagnostics:metadata(), responses:completed?.responses ?? [...checkpoint.values()]});
        const text = JSON.stringify(report);
        support.textContent = '';
        const area = part('textarea', '', 'display:block;width:100%;height:120px;margin-top:12px;padding:10px;border:1px solid #d9e3e0;border-radius:8px;font-size:12px', support);
        area.setAttribute('aria-label', '排错信息');
        area.value = text; area.readOnly = true;
        area.select?.();
        window.navigator?.clipboard?.writeText(text).catch(() => {});
        part('div', '若未自动复制，请选中上方文本后复制。在助手“导出排错日志”中粘贴；含日期和节次，请仅发给维护者。', 'margin-top:8px;color:#617775;font-size:12px', support);
      });
      button('关闭提示', () => { checkpoint.clear(); completed = null; panel.remove(); });
    }
  }
  await run();
}
