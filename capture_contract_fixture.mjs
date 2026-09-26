// Offline bridge for Python regression tests: use the production collector.
import {readFileSync} from 'node:fs';
import {collectSchedule} from './browser_capture.mjs';

const scenarios = JSON.parse(readFileSync(0, 'utf8'));
const results = [];
for (const {config, items} of scenarios) {
  let detail = 0;
  try {
    const capture = await collectSchedule(config, {
      accountKey: async () => 'a'.repeat(64),
      status() {},
      async saveCapture() {},
      async fetchJSON(path, params) {
        if (path === '/Home/GetCurriculumTable') {
          const rows = items.map(item => item.event).filter(row =>
            row.Start.slice(0, 10) >= params.Start && row.Start.slice(0, 10) < params.End);
          return {Title: '2026-2027 学年 第1 学期', List: rows};
        }
        if (path === '/Home/GetCalendarTable') return items[detail++].details;
        throw new Error('Unexpected endpoint');
      },
    });
    results.push({capture});
  } catch (error) {
    results.push({error: error.message, code: error.code});
  }
}
process.stdout.write(JSON.stringify(results));
