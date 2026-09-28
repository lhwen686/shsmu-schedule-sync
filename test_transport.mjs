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

// Virtual clock: overlapping reads, start spacing and failure degradation.
function simulation(latency, fail=()=>false, status=()=>200) {
  let now = 0, active = 0, peak = 0;
  const timers = [], starts = [], finishes = [];
  const at = (ms, fn) => timers.push({time:now + Math.max(0, ms), fn});
  const io = {
    concurrency:3, now:() => now, sleep:ms => new Promise(resolve => at(ms, resolve)),
    setTimeout:() => 0, clearTimeout:() => {},
    fetch:url => new Promise((resolve, reject) => {
      const index = starts.length;
      starts.push(now);
      peak = Math.max(peak, ++active);
      at(latency(index), () => {
        active--;
        finishes.push(now);
        if (fail(index)) reject(new TypeError('Failed to fetch'));
        else resolve(ok(url, {ok:status(index) < 300, status:status(index), text:async () => '[{"ID":' + index + '}]'}));
      });
    })
  };
  async function drive(work) {
    let settled = false, error;
    work.then(() => { settled = true; }, e => { error = e; settled = true; });
    for (let turn = 0; turn < 100000; turn++) {
      await new Promise(resolve => setImmediate(resolve));
      if (settled) break;
      timers.sort((a, b) => a.time - b.time);
      const timer = timers.shift();
      assert(timer, 'simulation stalled');
      now = timer.time;
      timer.fn();
    }
    if (error) throw error;
  }
  return {io, drive, starts, finishes, get peak() { return peak; }, get now() { return now; }};
}
const detailPath = '/Home/GetCalendarTable';
const many = (read, count) => Promise.all(Array.from({length:count}, (_, i) => read(detailPath, {MCSID:String(i)})));
let sim = simulation(() => 1200);
await sim.drive(many(createSchoolReader(origin, sim.io), 128));
assert.equal(sim.peak, 3, 'never more than three school reads in flight');
assert(sim.starts.every((time, i) => i === 0 || time - sim.starts[i - 1] >= 250), 'request starts stay spaced');
assert(sim.now <= 60000, `128 reads of 1.2 s should finish near one minute, took ${sim.now} ms`);

sim = simulation(() => 1200, index => index === 4);
await sim.drive(many(createSchoolReader(origin, sim.io), 20));
const later = sim.starts.filter(time => time > sim.finishes[4]);
assert(later.length > 10);
for (let i = 1; i < later.length; i++)
  assert(later[i] - later[i - 1] >= 2200, 'after a failure reads return to one at a time with a 1 s gap');

for (const code of [429, 401, 403]) {
  sim = simulation(index => index === 0 ? 10 : 1200, () => false, index => index === 0 ? code : 200);
  const outcomes = [];
  const reader = createSchoolReader(origin, sim.io);
  await sim.drive(Promise.all(Array.from({length:6}, (_, i) =>
    reader(detailPath, {MCSID:String(i)}).then(() => 'ok', error => error.code))).then(list => outcomes.push(...list)));
  assert.equal(sim.starts.length, 1, `after ${code} no queued read may reach the school`);
  assert.equal(outcomes[0], code === 429 ? 'RATE_LIMIT' : 'ACCESS');
  assert(outcomes.slice(1).every(code => code === 'CANCELLED'));
  await sim.drive(reader(detailPath, {MCSID:'later'}));
  assert.equal(sim.starts.length, 2, 'a later read (continue button) still runs');
}

sim = simulation(() => 1200);
await sim.drive(many(createSchoolReader(origin, {...sim.io, concurrency:undefined}), 4));
assert.equal(sim.peak, 1, 'readers without an explicit bound stay sequential');
sim = simulation(() => 1200);
await sim.drive(many(createSchoolReader(origin, {...sim.io, concurrency:50}), 8));
assert.equal(sim.peak, 3, 'the bound cannot be raised above three');
console.log('PASS (synthetic): bounded requests and body timeouts, timer cleanup, missing AbortSignal/fetch/AbortController, direct and fallback XHR, retries, redirects, sanitized failures, at most three spaced reads and sequential fallback after failure.');
