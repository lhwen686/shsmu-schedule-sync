// Normal same-origin GETs only; never read authentication headers or storage.
export function createSchoolReader(origin, io = {}) {
  const send = io.fetch !== undefined ? io.fetch : (typeof fetch === 'function' ? fetch : null);
  const sleep = io.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const now = io.now ?? Date.now;
  const observe = entry => { try { io.observe?.({...entry, recorded_at:new Date(now()).toISOString()}); } catch {} };
  const makeXHR = io.xhrFactory !== undefined ? io.xhrFactory : (typeof XMLHttpRequest === 'function' ? () => new XMLHttpRequest() : null);
  const makeController = io.controllerFactory !== undefined ? io.controllerFactory :
    (typeof AbortController === 'function' ? () => new AbortController() : null);
  const scheduleTimeout = io.setTimeout ?? setTimeout;
  const cancelTimeout = io.clearTimeout ?? clearTimeout;
  const allowed = new Set(['/Home', '/Home/GetCurriculumTable', '/Home/GetCalendarTable']);
  // Detail reads may overlap, but never beyond this bound. Starts stay spaced;
  // the first failure returns this capture to one request with a 1 s gap.
  const limit = Math.max(1, Math.min(3, Math.floor(Number(io.concurrency) || 1)));
  let lastFinished = -Infinity, lastStarted = -Infinity, active = 0, degraded = false, epoch = 0;
  let transport = send && makeController ? 'fetch' : 'xhr';
  const waiting = [];
  // A non-retryable failure (429/401/403, redirect, bad body) ends the epoch:
  // reads still queued from before it never reach the school. Later reads run.
  async function acquire(ticket) {
    for (;;) {
      if (ticket !== epoch) throw problem('CANCELLED', '另一条学校请求失败，已停止排队中的读取');
      if (active < (degraded ? 1 : limit)) {
        const gap = degraded ? 1000 - (now() - lastFinished) : 250 - (now() - lastStarted);
        if (gap <= 0) { active++; lastStarted = now(); return; }
        await sleep(gap);
      } else await new Promise(resolve => waiting.push(resolve));
    }
  }
  function release() {
    active--;
    lastFinished = now();
    for (const resolve of waiting.splice(0)) resolve();
  }
  const problem = (code, message, retryable = false, status = null) =>
    Object.assign(new Error(message), {code, retryable, status, school_read_error:true});
  async function sendXHR(url, headers) {
    return new Promise((resolve, reject) => {
      const xhr = makeXHR();
      xhr.open('GET', String(url), true);
      xhr.timeout = 45000;
      for (const [key,value] of Object.entries({...headers, 'Cache-Control':'no-cache'})) xhr.setRequestHeader(key, value);
      xhr.onload = () => resolve({ok:xhr.status >= 200 && xhr.status < 300, status:xhr.status,
        url:xhr.responseURL, type:'basic', redirected:false,
        headers:{get:name=>xhr.getResponseHeader(name)}, text:async()=>xhr.responseText});
      xhr.onerror = () => reject(problem('NETWORK', '浏览器未能完成学校请求', true));
      xhr.ontimeout = () => reject(problem('TIMEOUT', '学校请求超过 45 秒未完成', true));
      xhr.onabort = () => reject(problem('TIMEOUT', '学校请求被中断', true));
      xhr.send();
    });
  }
  return async function read(path, params, json = true) {
    if (origin !== 'https://jwstu.shsmu.edu.cn' || !allowed.has(path))
      throw problem('SOURCE', '请求来源不在已核实范围内');
    if (transport === 'xhr' && !makeXHR)
      throw problem('BROWSER_UNSUPPORTED', '当前浏览器缺少读取课表所需功能，请更新浏览器并重新打开教务首页');
    const url = new URL(path, origin), ticket = epoch;
    if (params) url.search = new URLSearchParams(params);
    for (let attempt = 1; attempt <= 3; attempt++) {
      await acquire(ticket);
      const began = now();
      observe({path, params, attempt, state:'start', transport});
      let failure, timeout = null;
      try {
        const options = {
          credentials:'same-origin', cache:'no-store', redirect:'manual',
          headers:json ? {Accept:'application/json', 'X-Requested-With':'XMLHttpRequest'} : {}
        };
        // Older supported browsers lack AbortSignal.timeout. XHR has its own
        // timeout and must never depend on fetch's cancellation APIs.
        if (transport === 'fetch') {
          const controller = makeController();
          options.signal = controller.signal;
          timeout = scheduleTimeout(() => controller.abort(), 45000);
        }
        const response = transport === 'xhr' ? await sendXHR(url, options.headers) : await send(url, options);
        // Manual redirects expose no destination or authentication parameters.
        if (response.type === 'opaqueredirect' || response.redirected)
          throw problem('REDIRECT', '学校请求发生跳转，请刷新教务页并完成正常登录');
        const final = new URL(response.url);
        if (final.origin !== origin || final.pathname !== path)
          throw problem('REDIRECT', '学校响应地址改变，请刷新教务页确认登录');
        if (!response.ok) {
          const status = response.status;
          if (status === 429) throw problem('RATE_LIMIT', '学校服务器要求稍后再试', false, status);
          if (status === 401 || status === 403)
            throw problem('ACCESS', '学校拒绝了读取请求，请刷新教务页确认登录与访问权限', false, status);
          throw problem('HTTP', '学校返回 HTTP ' + status, [408,502,503,504].includes(status), status);
        }
        const body = await response.text();
        if (body.length > 8000000) throw problem('SIZE', '响应超出预期大小');
        let value = body;
        if (json) {
          try { value = JSON.parse(body.replace(/^\uFEFF/, '')); }
          catch { throw problem('NON_JSON', '学校返回的正文不是有效 JSON，请刷新教务页确认登录'); }
        }
        observe({path, params, attempt, state:'success', transport, status:response.status,
          content_type:(response.headers.get('content-type') ?? '').slice(0,128), body_length:body.length,
          duration_ms:Math.max(0, now() - began)});
        return value;
      } catch (error) {
        failure = error?.school_read_error === true ? error : problem(
          ['TimeoutError','AbortError'].includes(error?.name) ? 'TIMEOUT' : 'NETWORK',
          ['TimeoutError','AbortError'].includes(error?.name) ? '学校请求超过 45 秒未完成' : '浏览器未能完成学校请求',
          true);
      } finally {
        if (timeout !== null) cancelTimeout(timeout);
        if (failure) degraded = true;
        release();
      }
      observe({path, params, attempt, state:'failure', transport, code:failure.code, status:failure.status,
        duration_ms:Math.max(0, now() - began)});
      if (!failure.retryable || attempt === 3) {
        failure.request = {path, params, attempt, transport};
        if (!failure.retryable && ticket === epoch) epoch++;
        throw failure;
      }
      // The live timetable uses XMLHttpRequest. A successful fallback remains
      // selected for this capture; all requests still obey browser security.
      if (transport === 'fetch' && failure.code === 'NETWORK' && makeXHR) transport = 'xhr';
      observe({path, params, attempt, state:'retry', transport, code:failure.code});
      await sleep(attempt === 1 ? 3000 : 6000);
    }
  };
}
