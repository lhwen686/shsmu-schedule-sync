// Normal same-origin GETs only; never read authentication headers or storage.
export function createSchoolReader(origin, io = {}) {
  const send = io.fetch ?? fetch;
  const sleep = io.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const now = io.now ?? Date.now;
  const observe = io.observe ?? (() => {});
  const makeXHR = io.xhrFactory ?? (typeof XMLHttpRequest === 'function' ? () => new XMLHttpRequest() : null);
  const allowed = new Set(['/Home', '/Home/GetCurriculumTable', '/Home/GetCalendarTable']);
  let lastFinished = 0, transport = 'fetch';
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
    const url = new URL(path, origin);
    if (params) url.search = new URLSearchParams(params);
    for (let attempt = 1; attempt <= 3; attempt++) {
      const gap = 1000 - (now() - lastFinished);
      if (gap > 0) await sleep(gap);
      observe({path, params, attempt, state:'start', transport});
      let failure;
      try {
        const options = {
          credentials:'same-origin', cache:'no-store', redirect:'manual',
          headers:json ? {Accept:'application/json', 'X-Requested-With':'XMLHttpRequest'} : {},
          signal:AbortSignal.timeout(45000)
        };
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
          content_type:(response.headers.get('content-type') ?? '').slice(0,128), body_length:body.length});
        return value;
      } catch (error) {
        failure = error?.school_read_error === true ? error : problem(
          ['TimeoutError','AbortError'].includes(error?.name) ? 'TIMEOUT' : 'NETWORK',
          ['TimeoutError','AbortError'].includes(error?.name) ? '学校请求超过 45 秒未完成' : '浏览器未能完成学校请求',
          true);
      } finally {
        lastFinished = now();
      }
      observe({path, params, attempt, state:'failure', transport, code:failure.code, status:failure.status});
      if (!failure.retryable || attempt === 3) {
        failure.request = {path, params, attempt, transport};
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
