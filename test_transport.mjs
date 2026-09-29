import assert from 'node:assert/strict';
import {createSchoolReader} from './browser_transport.mjs';

const origin = 'https://jwstu.shsmu.edu.cn';
const path = '/Home/GetCurriculumTable';
const params = {Start:'2026-09-07',End:'2026-10-01'};
const ok = (url, changes={}) => ({ok:true,status:200,type:'basic',url:String(url),headers:{get:()=>'text/html'},text:async()=>'{"List":[]}',...changes});
function fixture(plan, extra={}) {
  const calls=[], log=[], delays=[];
  let now=1000000;
  const read=createSchoolReader(origin,{
    fetch:async(url,options)=>{calls.push({url:String(url),options});const step=plan[Math.min(calls.length-1,plan.length-1)];return typeof step==='function'?step(url):ok(url,step);},
    sleep:async ms=>{delays.push(ms);now+=ms;},now:()=>now,observe:entry=>log.push(entry),...extra});
  return {read,calls,log,delays};
}
const failure=()=>{throw new TypeError('Failed to fetch: ticket=must-not-log');};
let trial=fixture([failure,{}]);
assert.deepEqual(await trial.read(path,params),{List:[]});
assert.equal(trial.calls.length,2);
assert(trial.delays.includes(3000));
assert(!JSON.stringify(trial.log).includes('must-not-log'));
assert(trial.log.every(entry=>typeof entry.recorded_at==='string'));
assert(trial.log.filter(entry=>['success','failure'].includes(entry.state)).every(entry=>entry.duration_ms>=0));
assert.equal(trial.calls[0].options.redirect,'manual');

trial=fixture([failure]);
await assert.rejects(()=>trial.read(path,params),error=>error.code==='NETWORK'&&error.request.attempt===3&&!error.message.includes('must-not-log'));
assert.equal(trial.calls.length,3);
assert(trial.delays.includes(6000));

trial=fixture([()=>{throw new DOMException('private abort details','AbortError');}]);
await assert.rejects(()=>trial.read(path,params),error=>error.code==='TIMEOUT'&&error.request.attempt===3);
assert.equal(trial.calls.length,3);

for (const [response,code] of [
  [{ok:false,status:0,url:'',type:'opaqueredirect'},'REDIRECT'],
  [{ok:false,status:429},'RATE_LIMIT'],
  [{ok:false,status:403},'ACCESS'],
  [{text:async()=>'<html>Login secret must-not-log</html>'},'NON_JSON']
]) {
  trial=fixture([response]);
  await assert.rejects(()=>trial.read(path,params),error=>error.code===code);
  assert.equal(trial.calls.length,1);
  assert(!JSON.stringify(trial.log).includes('must-not-log'));
}
trial=fixture([{ok:false,status:503},{}]);
await trial.read(path,params);
assert.equal(trial.calls.length,2);

const xhrCalls=[];
class TestXHR {
  open(method,url,async){this.method=method;this.url=url;assert.equal(async,true);}
  setRequestHeader(key,value){(this.headers??={})[key]=value;}
  getResponseHeader(){return 'text/html';}
  send(){
    xhrCalls.push(this);
    this.status=200;this.responseURL=this.url;this.responseText='{"List":[]}';
    queueMicrotask(()=>this.onload());
  }
}
trial=fixture([failure],{xhrFactory:()=>new TestXHR()});
await trial.read(path,params);
await trial.read(path,{...params,End:'2026-11-01'});
assert.equal(trial.calls.length,1,'successful XHR fallback must remain selected');
assert.equal(xhrCalls.length,2);
assert.equal(xhrCalls[0].method,'GET');
assert.equal(xhrCalls[0].headers['Cache-Control'],'no-cache');
assert.equal(xhrCalls[0].timeout,45000);
assert(!Object.keys(xhrCalls[0].headers).some(key=>/cookie|authorization/i.test(key)));

// Regression: missing AbortSignal.timeout used to fail even the XHR fallback.
const originalAbortSignal = globalThis.AbortSignal;
try {
  globalThis.AbortSignal = undefined;
  trial = fixture([{}]);
  await trial.read(path, params);
  assert.equal(trial.calls.length, 1);
  assert(trial.calls[0].options.signal instanceof originalAbortSignal);
  trial = fixture([failure], {xhrFactory: () => new TestXHR()});
  await trial.read(path, params);
  assert.equal(trial.calls.length, 1);
} finally { globalThis.AbortSignal = originalAbortSignal; }

for (const missing of [{controllerFactory:null}, {fetch:null}]) {
  const count = xhrCalls.length;
  trial = fixture([], {...missing, xhrFactory: () => new TestXHR()});
  await trial.read(path, params);
  assert.equal(trial.calls.length, 0, 'use XHR directly when fetch cannot be bounded');
  assert.equal(xhrCalls.length, count + 1);
}
const originalFetch = globalThis.fetch;
const loggingFailure = fixture([{}], {observe:()=>{throw new Error('logging failure');}});
assert.deepEqual(await loggingFailure.read(path,params),{List:[]});
try {
  globalThis.fetch = undefined;
  const read = createSchoolReader(origin, {xhrFactory: () => new TestXHR()});
  assert.deepEqual(await read(path, params), {List:[]});
} finally { globalThis.fetch = originalFetch; }
trial = fixture([], {fetch:null, xhrFactory:null, controllerFactory:null});
await assert.rejects(() => trial.read(path, params), e => e.code === 'BROWSER_UNSUPPORTED' && !e.retryable);
assert.equal(trial.log.length, 0, 'missing browser APIs must stop before a request');

// The 45-second limit covers the body too; every success/failure clears its timer.
let timers = 0, cleared = 0;
const pending = new Map();
const timeoutIO = {
  setTimeout: (fn, ms) => {assert.equal(ms,45000); const id=++timers; pending.set(id,fn); return id;},
  clearTimeout: id => {assert(pending.delete(id)); cleared++;}
};
trial = fixture([{}, {text: async () => '<html>login</html>'}], timeoutIO);
await trial.read(path,params);
await assert.rejects(() => trial.read(path,params), e => e.code === 'NON_JSON');
assert.equal(pending.size,0);
assert.equal(cleared,2);
const timeoutRead = createSchoolReader(origin, {
  ...timeoutIO, xhrFactory:null, sleep:async()=>{},
  fetch: async (url, options) => ok(url, {text: () => new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('private', 'AbortError')));
    [...pending.values()].at(-1)();
  })})
});
await assert.rejects(() => timeoutRead(path,params), e => e.code === 'TIMEOUT' && e.request.attempt === 3);
assert.equal(pending.size,0);
assert.equal(cleared,5);
console.log('PASS (synthetic): bounded requests and body timeouts, timer cleanup, missing AbortSignal/fetch/AbortController, direct and fallback XHR, retries, redirects and sanitized failures.');
