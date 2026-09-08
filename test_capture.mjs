import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import {collectSchedule} from './browser_capture.mjs';
import {browserDiagnostic} from './browser_diagnostics.mjs';

const config={semester:'2026-2027:1',start:'2026-09-07',end_exclusive:'2027-01-18'};
const row={ID:12,Curriculum:'测试课',CurriculumID:99,CSID:100,XXKMID:null,MCSID:'11,12',
  CurriculumType:'必修课',Start:'2026-09-07T08:00:00',End:'2026-09-07T09:30:00',ClassroomAcademy:'测试楼',AllDay:false};
const detail={ID:2001,DetailID:1001,TeachingCalendarID:3000,CurriculumID:99,CurriculumScheduleIDs:'|11||12|',
  ClassTime:'2026-09-07T00:00:00',Teacher:'测试教师',Tel:'must-be-omitted',TeacherAccount:'must-be-omitted',Content:'测试内容',IsDel:false};
const row2={...row,ID:22,MCSID:'21,22',Start:'2026-09-08T10:00:00',End:'2026-09-08T11:30:00'};
const detail2={...detail,ID:2002,DetailID:1002,CurriculumScheduleIDs:'|21||22|',ClassTime:'2026-09-08T00:00:00',Teacher:'第二位教师'};
function response(path,params) {
  if(path==='/Home/GetCurriculumTable')return {Title:params.Start==='2026-09-07'?'上海交通大学 2026-2027 学年 第1 学期':null,List:params.Start==='2026-09-07'?[row,row2]:[],List2:null,StuExam:null};
  if(path==='/Home/GetCalendarTable') {
    assert(['11,12','21,22'].includes(params.MCSID),'must request each event exactly as the page does');
    return params.MCSID==='11,12'?[detail]:[detail2];
  }
  throw new Error('Unexpected test endpoint');
}
const record=await collectSchedule(config,{fetchJSON:async(p,q)=>response(p,q),accountKey:async()=> 'a'.repeat(64),saveCapture:async()=>{},status:()=>{}});
// A winter course after the former Jan 17 cutoff must survive empty months.
const extended={...config,end_exclusive:'2027-02-22'}, extendedCalls=[];
const winter={...row,Start:'2027-01-25T08:00:00',End:'2027-01-25T09:30:00'};
const extendedRecord=await collectSchedule(extended,{
  fetchJSON:async(path,params)=>{
    extendedCalls.push({path,params});
    return path==='/Home/GetCalendarTable'?[{...detail,ClassTime:'2027-01-25T00:00:00'}]:
      {Title:params.Start==='2027-01-01'?'2026-2027 学年 第1 学期':null,
       List:params.Start==='2027-01-01'?[winter]:[]};
  },accountKey:async()=> 'a'.repeat(64),saveCapture:async()=>{},status:()=>{}
});
assert.equal(extendedCalls.filter(c=>c.path==='/Home/GetCurriculumTable').length,6);
assert.deepEqual(extendedCalls[5].params,{Start:'2027-02-01',End:'2027-02-22'});
assert.equal(extendedRecord.responses[4].response.List[0].Start,winter.Start);
assert.equal(extendedRecord.responses.at(-1).response[0].ClassTime,'2027-01-25T00:00:00');
assert.equal(record.responses.length,7);
assert.equal(record.responses[5].response[0].Tel,undefined);
assert.equal(record.responses[5].response[0].Teacher,'测试教师');
assert.equal(record.responses[6].response[0].Teacher,'第二位教师');
await assert.rejects(()=>collectSchedule(config,{fetchJSON:async(p,q)=>p==='/Home/GetCalendarTable'?[]:response(p,q),accountKey:async()=> 'a'.repeat(64),saveCapture:async()=>assert.fail('empty details must not produce a complete capture'),status:()=>{}}),error=>error.code==='EMPTY_DETAILS');
await assert.rejects(()=>collectSchedule(config,{fetchJSON:async()=>{throw new Error('expired');},accountKey:async()=> 'a'.repeat(64),saveCapture:async()=>assert.fail('partial download'),status:()=>{}}));
for (const title of [null,'2026-2027 学年 第2 学期']) {
  await assert.rejects(()=>collectSchedule(config,{fetchJSON:async()=>({Title:title,List:[row]}),accountKey:async()=> 'a'.repeat(64),saveCapture:async()=>assert.fail('invalid term download'),status:()=>{}}),/返回学期/);
}

const html=await fs.readFile(new URL('./chrome-bookmark.html',import.meta.url),'utf8');
const href=html.match(/class="bookmark" href="([^"]+)"/)[1].replaceAll('&amp;','&').replaceAll('&#x27;',"'");
const script=decodeURIComponent(href.slice('javascript:'.length));
new vm.Script(script);
function descendants(element) {
  return element.children.flatMap(child => [child, ...descendants(child)]);
}
async function executeBookmark(contentType, malformed=false, redirect=false, resume=false, wrongPage=false, changeAccount=false, emptyDetails=false, options={}) {
const blobs=[],panels=[],calls=[],alerts=[];
let failures=resume?3:0;
let downloadBlocked=options.blockDownload;
function element() {
  let value='';
  return {dataset:{},style:{},children:[],download:'',
    get textContent(){return value + this.children.map(child=>child.textContent).join('');},
    set textContent(text){value=text;this.children=[];},
    append(child){this.children.push(child);},
    setAttribute(name,value){this[name]=value;},
    click(){return this.onclick?.();},remove(){}};
}
class TestURL extends URL {static createObjectURL(b){if(downloadBlocked){downloadBlocked=false;throw new Error('synthetic download failure');}blobs.push(b);return 'blob:test';} static revokeObjectURL(){}}
const sandbox={location:{origin:'https://jwstu.shsmu.edu.cn',pathname:wrongPage?'/Home/Timetable':'/Home'},URL:TestURL,URLSearchParams,TextEncoder,Blob,crypto:webcrypto,
  AbortSignal:undefined,AbortController,Date,Map,Set,Promise,Error,JSON,Number,String,Array,Object,alert:message=>alerts.push(message),
  setTimeout:(fn,ms)=>{if(ms!==45000)fn();return 1;},clearTimeout:()=>{},
  document:{getElementById:()=>null,body:{innerText:'学号： 000000000001\n我的课表',append:el=>panels.push(el)},createElement:element},
  DOMParser:class {parseFromString(){return {body:{textContent:'学号： 000000000001\n我的课表'}};}},
  fetch:async input=>{
    const url=new URL(input),path=url.pathname;
    calls.push({path,params:Object.fromEntries(url.searchParams)});
    if(url.searchParams.get('MCSID')==='21,22'&&failures-->0)throw new TypeError('Failed to fetch');
    const data=response(path,Object.fromEntries(url.searchParams));
    if(options.wrongSemester&&data.List?.length)data.Title='2026-2027 学年 第2 学期';
    return {ok:true,status:200,type:'basic',url:redirect&&path!=='/Home'?'https://auth2.shsmu.edu.cn/cas/login':String(url),headers:{get:()=>contentType},text:async()=>path==='/Home'?'<html>synthetic account page</html>':malformed?'<html>Login required</html>':JSON.stringify(emptyDetails&&path==='/Home/GetCalendarTable'?[]:data)};
  }
};
sandbox.window=sandbox;
if(options.userAgent)sandbox.navigator={userAgent:options.userAgent};
if(options.xhrOnly) {
  const send=sandbox.fetch;
  sandbox.fetch=undefined;
  sandbox.AbortController=undefined;
  sandbox.XMLHttpRequest=class {
    open(method,url,async){assert.equal(method,'GET');assert.equal(async,true);this.url=url;}
    setRequestHeader(){}
    getResponseHeader(){return contentType;}
    send(){
      assert.equal(this.timeout,45000);
      send(this.url).then(async response=>{
        this.status=response.status;this.responseURL=response.url;
        this.responseText=await response.text();this.onload();
      },()=>this.onerror());
    }
  };
}
if(options.unsupported==='crypto')sandbox.crypto={};
if(options.unsupported==='ie')sandbox.document.documentMode=11;
if(options.unsupported==='download')sandbox.URL={};
vm.createContext(sandbox);
await vm.runInContext(script.replace(/^void/,''),sandbox);
if(options.unsupported) {
  assert.equal(calls.length,0);
  assert.equal(blobs.length,0);
  assert.equal(panels.length,0);
  assert.equal(alerts.length,1);
  assert.match(alerts[0],/尚未读取课表/);
  return;
}
assert.equal(alerts.length,0,'unexpected alert: '+alerts.join('\n'));
if(options.wrongSemester) {
  assert.match(panels[0].textContent,/返回学期 2026-2027:2/);
  assert.match(panels[0].textContent,/手动替换旧书签/);
  assert.equal(JSON.parse(await blobs[0].text()).format,'shsmu-diagnostic-v1');
  assert.equal(calls.length,1);
  return;
}
if(options.blockDownload) {
  assert.equal(blobs.length,0);
  assert.match(panels[0].textContent,/下载未能发起/);
  const count=calls.length;
  await descendants(panels[0]).find(child=>child.textContent==='重新下载采集文件').click();
  assert.equal(calls.length,count,'retry download must not contact school');
}
if(wrongPage) {
  assert.equal(calls.length,0,'guide to the normal homepage without subrequesting it');
  assert.equal(blobs.length,0);
  assert(descendants(panels[0]).some(child=>child.href==='https://jwstu.shsmu.edu.cn/Home'));
  return;
}
if(malformed||redirect||resume||emptyDetails) {
  assert.equal(blobs.length,1,'failure produces a diagnostic, never a complete capture');
  const diagnostic=JSON.parse(await blobs[0].text());
  assert.equal(diagnostic.format,'shsmu-diagnostic-v1');
  assert.equal(diagnostic.complete,false);
  if(emptyDetails) assert.equal(diagnostic.failure.code,'EMPTY_DETAILS');
  assert(!JSON.stringify(diagnostic).includes('must-be-omitted'));
  assert(!JSON.stringify(diagnostic).includes('000000000001'));
  assert(!JSON.stringify(diagnostic).includes('synthetic account page'));
  assert.match(panels[0].textContent,/采集未完成/);
  if(resume) {
    assert.equal(diagnostic.responses.length,6);
    const pseudonyms=diagnostic.failure.request.params.MCSID.split(',').map(Number);
    assert.equal(pseudonyms[1]-pseudonyms[0],1);
    assert.notEqual(pseudonyms[0],21);
    assert.equal(diagnostic.failure.request.attempt,3);
    const retry=descendants(panels[0]).find(child=>child.textContent==='继续采集');
    assert(retry);
    if(changeAccount)sandbox.document.body.innerText='学号： 000000000002\n我的课表';
    await retry.click();
    assert.equal(calls.filter(call=>call.path==='/Home/GetCurriculumTable').length,changeAccount?10:5,'resume must retain completed months only for the same account');
    assert.equal(calls.filter(call=>call.params.MCSID==='11,12').length,changeAccount?2:1,'account changes must discard previously completed details');
  } else {
    assert(!descendants(panels[0]).some(child=>child.textContent==='继续采集'),'authentication or schema failures must not offer cached resume');
    return;
  }
}
assert.equal(blobs.length,resume?2:1,panels[0]?.textContent);
const downloaded=JSON.parse(await blobs[blobs.length-1].text());
assert.equal(downloaded.format,'shsmu-capture-v1');
assert.equal(downloaded.complete,true);
assert.equal(downloaded.collector_revision,'2026-09-08.12');
assert(downloaded.diagnostics.request_log.length > 0);
assert(downloaded.diagnostics.request_log.every(entry => typeof entry.recorded_at === 'string'));
assert(downloaded.diagnostics.request_log.filter(entry => entry.state==='success').every(entry => entry.duration_ms >= 0));
assert.equal(downloaded.diagnostics.download_observed,false);
if(options.browser) {
  assert.equal(downloaded.diagnostics.browser,options.browser);
  assert.equal(browserDiagnostic({diagnostics:downloaded.diagnostics}).diagnostics.browser,options.browser);
  assert(!JSON.stringify(downloaded).includes(options.userAgent),'never retain the full user agent');
}
if(!options.blockDownload) {
  assert.match(panels[0].textContent,/JSON.*下载/);
  assert.match(panels[0].textContent,/文件已经下载/);
  assert.match(panels[0].textContent,/wakeup\.csv/);
  assert.match(panels[0].textContent,/calendar\.ics/);
}
assert.equal(downloaded.responses.length,7);
assert.match(downloaded.account_key,/^[a-f0-9]{64}$/);
assert.equal(calls.filter(call=>call.path==='/Home').length,0,'identity must come from the normal visible homepage, with no extra Home request');
assert(!JSON.stringify(downloaded).includes('must-be-omitted'));
if(options.repeatDownload) {
  const count=calls.length;
  const retry=descendants(panels[0]).find(child=>child.textContent==='重新下载采集文件');
  assert(retry);
  await retry.click();
  assert.equal(await blobs.at(-1).text(),await blobs.at(-2).text(),'same capture and fetched_at, not a new sync');
  assert.equal(calls.length,count);
  await descendants(panels[0]).find(child=>child.textContent==='关闭提示').click();
  const blobCount=blobs.length;
  await retry.click();
  assert.equal(blobs.length,blobCount,'closing panel discards retained capture');
}
return downloaded;
}
let downloaded;
const shared=browserDiagnostic({format:'shsmu-diagnostic-v1', responses:[{path:'/Home/GetCalendarTable',
  params:{MCSID:'11,12',CSID:'100'}, response:[{...detail, ClassCode:'CLASS-A CLASS-B', Content:'<div>FIRST<br>SECOND</div>',
    StudentName:'PRIVATE_STUDENT', Cookie:'PRIVATE_COOKIE', UnknownField:'PRIVATE_UNKNOWN'}]}]});
assert(!JSON.stringify(shared).includes('测试教师'));
assert(!JSON.stringify(shared).includes('PRIVATE_'));
assert.equal(shared.responses[0].response[0].ClassCode.split(' ').length,2);
assert.match(shared.responses[0].response[0].Content, /^<div>[^<]+<br>[^<]+<\/div>$/);
assert.equal(shared.responses[0].params.MCSID.replace(/,/g,'|'),
  shared.responses[0].response[0].CurriculumScheduleIDs.match(/\d+/g).join('|'));
for(const contentType of ['application/json','text/html; charset=utf-8','text/plain','']) downloaded=await executeBookmark(contentType);
for(const [browser,userAgent] of [
  ['Safari','Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15'],
  ['Chrome','Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36'],
  ['Edge','Mozilla/5.0 Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0'],
  ['Firefox','Mozilla/5.0 Firefox/142.0'],
  ['unknown','Unrecognized/1.0']
]) await executeBookmark('application/json',false,false,false,false,false,false,{browser,userAgent,repeatDownload:true});
await executeBookmark('text/html',true);
await executeBookmark('application/json',false,false,false,false,false,true);
await executeBookmark('text/html',false,true);
await executeBookmark('text/html',false,false,true);
await executeBookmark('text/html',false,false,false,true);
await executeBookmark('text/html',false,false,true,false,true);
await executeBookmark('application/json',false,false,false,false,false,false,{wrongSemester:true});
await executeBookmark('application/json',false,false,false,false,false,false,{blockDownload:true});
await executeBookmark('application/json',false,false,false,false,false,false,{repeatDownload:true});
await executeBookmark('application/json',false,false,false,false,false,false,{xhrOnly:true});
for(const unsupported of ['crypto','ie','download'])
  await executeBookmark('application/json',false,false,false,false,false,false,{unsupported});
if(process.argv[2])await fs.writeFile(process.argv[2],JSON.stringify(downloaded));
console.log('PASS (synthetic): generated bookmark execution, exact details, privacy, empty months, JSON content types, diagnostic-only failures, bounded retries and resumed complete capture without rereading completed requests.');
