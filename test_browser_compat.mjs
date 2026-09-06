import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {browserCapabilities} from './browser_compat.mjs';

function environment(changes = {}) {
  return {Promise, Map, Set, Object, Function, TextEncoder, crypto:webcrypto,
    fetch, AbortController, Blob, URL, URLSearchParams,
    document:{createElement: () => ({download:''})}, ...changes};
}
assert.deepEqual(browserCapabilities(environment(), true), {ok:true, missing:[], transport:'fetch'});
assert.equal(browserCapabilities(environment({AbortSignal:undefined}), true).ok, true);
assert.deepEqual(browserCapabilities(environment({fetch:undefined, AbortController:undefined,
  XMLHttpRequest:function () {}})), {ok:true, missing:[], transport:'xhr'});
for (const changes of [
  {document:{documentMode:11, createElement:()=>({download:''})}},
  {Object:{entries:Object.entries}},
  {crypto:{}}, {TextEncoder:undefined},
  {AbortController:undefined}, {fetch:undefined},
  {URL:{}}, {Blob:undefined}, {URLSearchParams:undefined},
  {document:{createElement:()=>({})}},
  {Function:function () {throw new SyntaxError('old JavaScript');}}
]) {
  const result = browserCapabilities(environment(changes), true);
  assert.equal(result.ok, false);
  assert(result.missing.length);
}
// A CSP that disallows dynamic code does not affect the actual school preflight.
assert.equal(browserCapabilities(environment({Function:()=>assert.fail('must not evaluate code on school page')})).ok, true);

// Execute the actual installation-page checker, including its disabled drag link.
const html = await fs.readFile(new URL('./chrome-bookmark.html', import.meta.url), 'utf8');
const installer = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function runInstaller(changes) {
  const nodes = Object.fromEntries(['browser-check','browser-check-detail','browser-check-more']
    .map(id => [id, {textContent:'',style:{},hidden:true}]));
  const attrs = {href:'javascript:synthetic'};
  const link = {removeAttribute: key => delete attrs[key], setAttribute:(key,value)=>attrs[key]=value};
  const env = environment(changes);
  env.document.getElementById = id => nodes[id];
  env.document.getElementsByClassName = name => name === 'bookmark' ? [link] : [];
  env.window = env;
  vm.runInNewContext(installer, env);
  return {nodes, attrs};
}
let result = runInstaller({});
assert.match(result.nodes['browser-check'].textContent, /基础功能检查通过/);
assert.equal(result.attrs.href,'javascript:synthetic');
result = runInstaller({document:{documentMode:11, createElement:()=>({download:''})}});
assert.match(result.nodes['browser-check'].textContent, /不要使用 IE 兼容模式/);
assert.equal(result.nodes['browser-check-more'].hidden,false);
assert.equal(result.attrs.href,undefined);
assert.equal(result.attrs.draggable,'false');
result = runInstaller({Function:function () {throw new SyntaxError();}});
assert.match(result.nodes['browser-check-detail'].textContent, /新版 JavaScript/);
assert.equal(result.attrs.href,undefined);
console.log('PASS (synthetic): capability and syntax checks, XHR-only mode, IE/missing-feature rejection, installer guidance and disabled unsupported bookmark. Browser E2E NOT RUN.');
