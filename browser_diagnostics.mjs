// Sharing policy, separate from the business capture used to build a timetable.
export function browserDiagnostic(value) {
  const ids = new Set('ID DetailID TeachingCalendarID CurriculumID CSID XXKMID ScheduleManagerID HeBanID MCSID CurriculumScheduleIDs'.split(' '));
  const texts = new Set('Curriculum CurriculumType CourseCode ClassroomAcademy Classroom Teacher Content Bz ClassCode GroupName'.split(' '));
  const dates = new Set('Start End ClassTime start end_exclusive fetched_at started_at observed_at recorded_at'.split(' '));
  const counts = new Set('CourseCount ClassHour WeekNum request_count attempt duration_ms body_length index count schema_version'.split(' '));
  const containers = new Set('config responses response params List failure request request_log current_response diagnostics'.split(' '));
  const codes = new Set('DATA_VALIDATION EMPTY_DETAILS HOMEPAGE_REQUIRED BROWSER_UNSUPPORTED SOURCE NETWORK TIMEOUT REDIRECT RATE_LIMIT ACCESS HTTP SIZE NON_JSON DOWNLOAD_FAILED'.split(' '));
  const names = new Map();
  const offset = 100000000 + Math.floor(Math.random() * 800000000);
  const shape = v => ({omitted_type:v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v,
    count:Array.isArray(v) || typeof v === 'string' ? v.length : v && typeof v === 'object' ? Object.keys(v).length : 1});
  const text = v => String(v).split(/(<br\s*\/?>|<\/?(?:p|div)>|<<|>>)/i).map(fragment =>
    /^(?:<br\s*\/?>|<\/?(?:p|div)>|<<|>>)$/i.test(fragment) ? fragment :
      fragment.replace(/[\p{L}\p{N}_]+/gu, word => {
        if (!names.has(word)) names.set(word, '文' + (names.size + 1).toString(26).replace(/[0-9a-p]/g, c => String.fromCharCode(97 + parseInt(c, 26))));
        return names.get(word);
      })).join('');
  const identifier = v => typeof v === 'number' ? (v > 0 ? v + offset : v) : typeof v === 'string'
    ? v.replace(/\d+|[^\d,|\s-]+/g, part => /^\d+$/.test(part) ? (Number(part) > 0 ? (part.match(/^0*/)[0] + String(Number(part) + offset)) : part) : text(part)) : v === null ? null : shape(v);
  function clean(v, key = '', depth = 0) {
    if (depth > 30) return {omitted_type:'depth_limit'};
    if (ids.has(key)) return identifier(v);
    if (texts.has(key)) return typeof v === 'string' ? text(v) : v === null ? null : shape(v);
    if (dates.has(key)) return v === null || v === '' || typeof v === 'string' && /^(?:\d{4}-\d{2}-\d{2}(?:(?:T| )\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?)?|\d{2}:\d{2}(?::\d{2})?)$/.test(v) ? v : shape(v);
    if (counts.has(key)) return v === null || typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 100000000 ? v : shape(v);
    if (['AllDay','IsDel','complete','truncated','download_attempted','download_observed'].includes(key)) return typeof v === 'boolean' || v === null ? v : shape(v);
    if (['PKCIndex','KCIndex'].includes(key)) return typeof v === 'string' && /^[0-9|, \t-]{0,200}$/.test(v) ? v : shape(v);
    if (key === 'semester') return typeof v === 'string' && /^\d{4}-\d{4}:\d$/.test(v) ? v : 'invalid-semester';
    if (key === 'Title') {
      if (v === null || v === '') return v;
      const match = String(v).match(/(\d{4}-\d{4})\s*学年\s*第\s*(\d+)\s*学期/);
      return match ? `${match[1]} 学年 第${match[2]} 学期` : 'invalid-title';
    }
    if (key === 'path') return ['/Home/GetCurriculumTable','/Home/GetCalendarTable','/Home'].includes(v) ? v : 'unverified-endpoint';
    if (key === 'code') return codes.has(v) ? v : 'UNKNOWN';
    if (key === 'format') return ['shsmu-diagnostic-v1','shsmu-browser-support-v1'].includes(v) ? v : 'unknown';
    if (key === 'collector_revision') return typeof v === 'string' && /^[0-9.-]{1,30}$/.test(v) ? v : 'unknown';
    if (key === 'status') return Number.isInteger(v) && v >= 0 && v <= 599 ? v : null;
    if (key === 'state') return ['start','success','failure','retry'].includes(v) ? v : 'unknown';
    if (key === 'transport') return ['fetch','xhr'].includes(v) ? v : 'unknown';
    if (key === 'stage') return ['homepage','month','details','download','collect'].includes(v) ? v : 'collect';
    if (key === 'origin') return v === 'https://jwstu.shsmu.edu.cn' ? v : 'unverified-origin';
    if (key === 'browser') return ['Chrome','Edge','Firefox','Safari'].includes(v) ? v : 'unknown';
    if (key === 'content_type') return ['application/json','text/html','text/plain'].includes(String(v).split(';')[0]) ? String(v).split(';')[0] : 'other';
    if (['List2','StuExam'].includes(key)) return v === null ? null : Array.isArray(v) && !v.length ? [] : shape(v);
    if (Array.isArray(v)) return v.slice(0, 10000).map(item => clean(item, '', depth + 1));
    if (!v || typeof v !== 'object') return v === null ? null : shape(v);
    const result = {}; let omitted = 0;
    for (const [field,item] of Object.entries(v)) {
      if (ids.has(field) || texts.has(field) || dates.has(field) || counts.has(field) || containers.has(field) ||
          ['AllDay','IsDel','complete','truncated','download_attempted','download_observed','PKCIndex','KCIndex','semester','Title','path','code','format',
           'collector_revision','status','state','stage','transport','origin','browser','content_type','List2','StuExam'].includes(field))
        result[field] = clean(item, field, depth + 1);
      else omitted++;
    }
    if (omitted) result.omitted_fields = omitted;
    return result;
  }
  return clean(value);
}
