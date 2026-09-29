// Bundled with the capability check, transport and collector by prepare.py.
export async function runBookmark(config) {
  const revision = '2026-09-29.19';
  if (location.origin !== 'https://jwstu.shsmu.edu.cn') {
    alert('请先在安装书签的浏览器中打开教务首页并登录，再点击“同步医学院课表”。\n教务首页：https://jwstu.shsmu.edu.cn/Home');
    return;
  }
  const capabilities = browserCapabilities(window);
  if (!capabilities.ok) {
    alert('当前浏览器或模式不支持，尚未读取课表。\n请使用更新后的 Safari、Edge、Chrome 或 Firefox 普通窗口，重新安装书签并登录教务。不要使用 IE 兼容模式。\n缺少的功能：' + capabilities.missing.join('、'));
    return;
  }
  let panel = document.getElementById('shsmu-sync-status');
  if (panel?.dataset.busy === 'true') { alert('正在读取课表，请等待完成，不要重复点击书签。'); return; }
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'shsmu-sync-status';
    document.body.append(panel);
  }
  panel.textContent = '';
  panel.style.cssText = 'position:fixed;right:16px;top:16px;z-index:2147483647;display:block;background:#fff;border:1px solid #dce7e5;border-radius:18px;padding:24px;width:460px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);box-sizing:border-box;overflow:auto;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;text-align:left;color:#233b3c;box-shadow:0 12px 48px #173b3826;white-space:normal;overflow-wrap:anywhere;color-scheme:light';
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', '教务课表读取');
  function part(tag, text, css, parent = panel) {
    const element = document.createElement(tag);
    element.textContent = text;
    element.style.cssText = 'box-sizing:border-box;font:inherit;color:inherit;' + css;
    parent.append(element);
    return element;
  }
  const header = part('div', '', 'display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap');
  part('h2', '读取教务课表', 'margin:0;font-size:22px;line-height:1.4;font-weight:650;letter-spacing:.02em', header);
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
  part('summary', '查看下载与导入步骤', 'cursor:pointer;color:#426c65;font-size:13px', instructions);
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
  function visibleStage(message) {
    if (message === '读取教务首页显示的账号…') return '正在确认教务首页的登录账号…';
    let match = /^读取 (\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})$/.exec(message);
    if (match) return `正在读取 ${match[1]} 起、${match[2]} 前的课程…`;
    match = /^读取教师详情 (\d+)\/(\d+)，请保持页面打开…$/.exec(message);
    if (match) return `正在读取课程详情：${match[1]}/${match[2]}\n请保持教务网页打开。`;
    return message;
  }
  function visibleError(error) {
    const messages = {
      NETWORK: '未能完成教务读取，请检查网络后重试。',
      TIMEOUT: '教务读取超过 45 秒未完成，请稍后重试。',
      SOURCE: '读取地址不在允许范围内，已停止。请复制排错信息供维护者核对。',
      BROWSER_UNSUPPORTED: '浏览器不支持读取课表。请更新浏览器，重新安装书签后再试。',
      REDIRECT: '教务页面发生跳转。请刷新教务首页并确认登录，再重新读取。',
      RATE_LIMIT: '教务系统要求稍后重试。请稍等，不要连续点击书签。',
      ACCESS: '教务系统拒绝读取。请确认已登录，且能正常查看本人课表。',
      SIZE: '学校返回的数据量超出预期，已停止读取。请复制排错信息供维护者核对。',
      NON_JSON: '学校返回的数据无法识别。请刷新教务首页并确认登录后重试。',
      EMPTY_DETAILS: '学校未返回课程详情。请重新读取；不完整结果不会替换已保存课表。'
    };
    if (error?.code === 'TIMEOUT' && error.message === '学校请求被中断') return '读取已中断，请重试。';
    if (messages[error?.code]) return messages[error.code];
    if (error?.code === 'HTTP' && Number.isInteger(error.status))
      return `教务系统返回错误（HTTP ${error.status}）。请稍后重试；仍有问题时复制排错信息。`;
    const original = error?.message ?? '';
    const validation = {
      '日期无效，请核对本机配置并重新生成书签': '书签中的日期无效。请在助手中检查学期设置，再更新书签。',
      '只支持不超过 240 天的一个学期': '读取范围需为 1—240 天。请在助手中调整日期范围并更新书签。',
      '出现新的数据分支，需要核实后再同步': '学校返回了尚未支持的数据类型，已停止读取。请复制排错信息供维护者核对。',
      '接口未按日期范围返回数据': '学校返回的课程超出请求范围，已停止读取。请复制排错信息供维护者核对。',
      '整个学期返回空课表，已停止；请核对登录账号和书签学期，旧课表保留': '未读取到课程，已停止。请核对登录账号、学期和日期范围；本次空结果不会清空已保存课表。',
      '教学日历结构改变': '学校返回的课程详情格式发生变化，已停止读取。请复制排错信息供维护者核对。'
    };
    if (validation[original]) return validation[original];
    let match = /^(\d{4}-\d{2}-\d{2}) 返回的课表缺少 List 数组$/.exec(original);
    if (match) return `学校返回的课表结构异常（${match[1]}）。请先打开学校“我的课表”确认能看到课程，再回首页重试。`;
    match = /^(\d{4}-\d{2}-\d{2}) 返回学期 (未注明|\d{4}-\d{4}:\d+)，书签配置为 (\d{4}-\d{4}:\d+)；请核对学期设置，重新生成安装页并手动替换旧书签网址$/.exec(original);
    if (match) return `学校返回的学期与书签不一致。\n学校返回：${match[2]}；书签设置：${match[3]}。\n请核对助手中的学期设置，再更新书签。`;
    return '学校返回的数据未通过检查，请复制排错信息供维护者核对。';
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
  const status = message => { stage = message; showMessage(visibleStage(message)); };
  const read = createSchoolReader(location.origin, {observe:entry => {
    if (trace.length < 2000) trace.push(entry); else { truncated = true; trace[1999] = entry; }
    if (entry.state === 'retry')
      showMessage(visibleStage(stage) + '\n暂未收到响应，即将进行第 ' + (entry.attempt + 1) + '/3 次尝试…');
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
    state('正在读取');
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
        state('下载未开始', true);
        showMessage('课表已读取，但未能开始下载\n请点击“重新下载课表文件”，并查看浏览器下载提示。无需再次读取课表。');
      } else if (completed) {
        state('读取完成');
        const count = /^采集完成：(\d+) 次课程；/.exec(stage)?.[1];
        messageTitle.textContent = count ? `已读取 ${count} 条课程记录` : '课表已读取';
        messageText.textContent = '已发起课表文件下载。请查看浏览器下载列表。\n返回助手继续处理；若未自动接收，点击“选择已下载的课表”并选中刚下载的 JSON。';
        instructionText.textContent = '1. 返回助手；若未自动接收，点击“选择已下载的课表”，选择 shsmu-capture-…json。\n2. 等待助手生成 wakeup.csv 或 calendar.ics。\n3. 将所需文件发到手机，按助手中的说明手动导入。\n\nJSON 是供助手处理的课表文件，不能直接导入手机，也不要修改扩展名。\n没有找到下载文件时，点击“重新下载课表文件”，无需再次读取。\n使用命令行版时，请返回本地同步窗口，或运行“导入已下载课表.cmd”。';
        instructions.hidden = false;
      }
    } catch (error) {
      const code = error?.code ?? 'DATA_VALIDATION';
      if (code === 'HOMEPAGE_REQUIRED') {
        checkpoint.clear();
        checkpointAccount = '';
        state('需要登录', true);
        showMessage('请在教务首页读取课表\n打开教务首页，确认已登录且显示本人学号，再点击“同步医学院课表”。');
        const home = part('a', '打开教务首页', 'display:inline-block;padding:9px 13px;border-radius:9px;background:#176856;color:#fff;text-decoration:none;font-size:13px', actions);
        home.href = 'https://jwstu.shsmu.edu.cn/Home';
        lastDiagnostic = browserDiagnostic({format:'shsmu-diagnostic-v1', collector_revision:revision,
          config, complete:false, failure:{stage:'homepage',code}, observed_at:new Date().toISOString()});
        return;
      }
      const request = error?.request ?? null;
      const message = visibleError(error);
      const diagnostic = browserDiagnostic({format:'shsmu-diagnostic-v1', collector_revision:revision,
        origin:location.origin, config, complete:false, observed_at:new Date().toISOString(),
        failure:{stage:stageCode(), code, request}, request_log:trace, responses:[...checkpoint.values()],
        current_response:currentResponse, diagnostics:metadata()});
      lastDiagnostic = diagnostic;
      state('读取未完成', true);
      showMessage('课表读取未完成\n' + message + '\n当前步骤：' + visibleStage(stage) +
        (request ? '\n排错信息：' + request.path + '（已尝试 ' + request.attempt + ' 次）' : '') +
        '\n已保留 ' + checkpoint.size + ' 份读取记录；本次未完成的结果不会替换已保存课表。');
      try {
        download('shsmu-diagnostic-', diagnostic);
        messageText.textContent += '\n\n已发起排错文件下载，可发给维护者；此文件不能导入为课表。';
      } catch {
        messageText.textContent += '\n\n未能下载排错文件。请保留本页，可使用“复制排错信息”。';
      }
      if (error?.retryable) {
        messageText.textContent += '\n\n可在本页继续读取；当前账号的进度最多保留 15 分钟，刷新页面会清除。';
        button('继续读取', run, true);
      } else {
        checkpoint.clear();
        checkpointAccount = '';
      }
    } finally {
      panel.dataset.busy = 'false';
      if (completed) {
        button('重新下载课表文件', () => {
          if (!completed) return;
          try { download('shsmu-capture-', completed); }
          catch { alert('未能开始下载。请保留本页，检查浏览器下载提示后重试。'); }
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
        part('div', '若未自动复制，请手动复制上方已选中的内容，再粘贴到助手的“导出排错日志”窗口。信息仍含日期和节次，请仅发给维护者。', 'margin-top:8px;color:#617775;font-size:12px', support);
      });
      button('关闭提示', () => { checkpoint.clear(); completed = null; panel.remove(); });
    }
  }
  await run();
}
