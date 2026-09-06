// Collection uses normal same-origin GET requests in the existing browser.
export async function collectSchedule(config, io) {
  const omit = new Set(['tel','telephone','phone','mobile','email','teacheraccount','worknumber','videolink']);
  const secret = /password|passwd|cookie|token|authorization|secret|session|csrf|ticket/i;
  function scrub(v) {
    if (Array.isArray(v)) return v.map(scrub);
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).filter(([k])=>!omit.has(k.toLowerCase())&&!secret.test(k)).map(([k,val])=>[k,scrub(val)]));
    return v;
  }
  const ids = value => [...new Set(String(value ?? '').match(/\d+/g) ?? [])].sort((a,b)=>Number(a)-Number(b));
  function validDay(day) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || new Date(day+'T00:00:00Z').toISOString().slice(0,10)!==day) throw new Error('日期配置无效');
    return day;
  }
  const start=validDay(config.start), end=validDay(config.end_exclusive);
  const days=(Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000;
  if (days<=0 || days>240) throw new Error('只支持不超过 240 天的一个学期');
  const responses=[], rows=[];
  async function request(path,params) {
    const response=scrub(await io.fetchJSON(path,params));
    responses.push({path,params,response});
    return response;
  }
  const account_key=await io.accountKey();
  let cursor=start;
  while (cursor<end) {
    const [year,month]=cursor.split('-').map(Number);
    const next=month===12?`${year+1}-01-01`:`${year}-${String(month+1).padStart(2,'0')}-01`;
    const stop=next<end?next:end;
    io.status(`读取 ${cursor} 至 ${stop}`);
    const raw=await request('/Home/GetCurriculumTable',{Start:cursor,End:stop});
    if (!raw || !Array.isArray(raw.List)) throw new Error(`${cursor} 返回的课表缺少 List 数组`);
    const term=String(raw?.Title??'').match(/(\d{4}-\d{4})\s*学年\s*第\s*(\d+)\s*学期/);
    // A verified empty January response has Title:null and List:[].
    // Nonempty ranges must still identify the expected semester.
    if ((raw.List.length || String(raw.Title??'').trim()) && (!term || `${term[1]}:${term[2]}`!==config.semester))
      throw new Error(`${cursor} 返回学期 ${term?term[1]+':'+term[2]:'未注明'}，配置为 ${config.semester}`);
    if ((raw.List2?.length??0)||(raw.StuExam?.length??0)) throw new Error('出现新的数据分支，需要核实后再同步');
    for (const row of raw.List) {
      const day=String(row.Start??'').slice(0,10);
      validDay(day);
      if (day<cursor || day>stop) throw new Error('接口未按日期范围返回数据');
      if (day<stop) rows.push(row);
    }
    io.onResponse?.(responses[responses.length-1]);
    cursor=stop;
  }
  if (!rows.length) throw new Error('整个学期返回空课表，已停止，避免误删旧课程');
  // Match the real event-click request exactly. Combining several events'
  // MCSIDs can silently return only one event from this endpoint.
  const parameters=row=>({MCSID:String(row.MCSID??''),CSID:String(row.CSID??''),CurriculumID:String(row.CurriculumID??''),XXKMID:String(row.XXKMID??''),CurriculumType:String(row.CurriculumType??'')});
  const requested=new Set();
  for (const [index,row] of rows.entries()) {
    io.status(`读取教师详情 ${index+1}/${rows.length}，请保持页面打开…`);
    const params=parameters(row);
    const key=JSON.stringify({...params,MCSID:ids(params.MCSID).join(',')});
    if (requested.has(key)) continue;
    const result=await request('/Home/GetCalendarTable',params);
    if (!Array.isArray(result) || result.some(d=>!d||typeof d!=='object'||Array.isArray(d))) throw new Error('教学日历结构改变');
    if (!result.length) throw Object.assign(new Error('教学日历详情为空，请重新采集；旧课表保留'), {code:'EMPTY_DETAILS'});
    io.onResponse?.(responses[responses.length-1]);
    requested.add(key);
  }
  const capture={format:'shsmu-capture-v1',origin:'https://jwstu.shsmu.edu.cn',config,account_key,
    fetched_at:new Date().toISOString(),complete:true,responses};
  await io.saveCapture(capture);
  io.status(`采集完成：${rows.length} 个事件；已下载 JSON，请查看本地同步窗口。`);
  return capture;
}
