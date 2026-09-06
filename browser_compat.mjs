// Keep this function ES5-compatible so the local installer can explain old modes.
// Test APIs, not browser brands. No network, user-agent or browser storage reads.
export function browserCapabilities(env, checkSyntax) {
  var missing = [];
  function need(available, label) { if (!available) missing.push(label); }
  var doc = env.document;
  need(doc && !doc.documentMode, '现代网页模式（不支持 IE 兼容模式）');
  if (checkSyntax) {
    // Only the local installation page checks syntax. The school bookmark never
    // uses Function/eval, which may be blocked by the school's security policy.
    try { new env.Function('async function probe(){const v={ok:1};return v?.ok ?? 0;}'); }
    catch (_) { missing.push('新版 JavaScript'); }
  }
  need(env.Promise && env.Map && env.Set && env.Object && env.Object.fromEntries,
       '课表数据处理');
  need(env.TextEncoder && env.crypto && env.crypto.subtle && env.crypto.subtle.digest,
       '本地账号校验');
  var fetchReady = typeof env.fetch === 'function' && typeof env.AbortController === 'function';
  var xhrReady = typeof env.XMLHttpRequest === 'function';
  need(fetchReady || xhrReady, '带超时的学校读取请求');
  var link = doc && doc.createElement('a');
  need(env.Blob && env.URL && env.URLSearchParams && env.URL.createObjectURL &&
       env.URL.revokeObjectURL && link && 'download' in link, '课表文件下载');
  return {ok: missing.length === 0, missing: missing, transport: fetchReady ? 'fetch' : xhrReady ? 'xhr' : null};
}
