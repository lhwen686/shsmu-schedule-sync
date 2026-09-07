"""Read timetable responses downloaded by the user's already-open browser.

Python never opens browsers or reads browser profiles, cookies or credentials.
"""
import json
import re
from pathlib import Path

ORIGIN = "https://jwstu.shsmu.edu.cn"
ENDPOINTS = {"/Home/GetCurriculumTable", "/Home/GetCalendarTable"}
PRIVATE_FIELDS = {"tel", "telephone", "phone", "mobile", "email", "teacheraccount", "worknumber", "videolink"}
SECRET_FIELD = re.compile(r"password|passwd|cookie|token|authorization|secret|session|csrf|ticket", re.I)

class SourceError(Exception):
    pass

class LoginRequired(SourceError):
    pass

def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in PRIVATE_FIELDS and not SECRET_FIELD.search(k)}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value

def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def request_key(path, params):
    normalized = {k: str(v) for k, v in params.items()}
    if "MCSID" in normalized:
        normalized["MCSID"] = ",".join(sorted(set(re.findall(r"\d+", normalized["MCSID"])), key=int))
    return path + "?" + json.dumps(normalized, sort_keys=True, ensure_ascii=True)

class CaptureSource:
    def __init__(self, capture_path: Path, config):
        try:
            if capture_path.stat().st_size > 20_000_000:
                raise SourceError("采集文件超过预期大小。")
            self.capture = scrub(json.loads(capture_path.read_text(encoding="utf-8-sig")))
        except OSError:
            raise SourceError("无法读取采集文件，请确认已下载完成，或用“导入已下载课表.cmd”重新选择 JSON。") from None
        except (ValueError, UnicodeError):
            raise SourceError("采集文件不是完整的 UTF-8 JSON。请等待下载完成，或在采集完成面板点击“重新下载采集文件”。") from None
        if not isinstance(self.capture, dict):
            raise SourceError("文件不是课表 JSON 对象，请选择 shsmu-capture 开头的完整采集文件。")
        if self.capture.get('format') in ('shsmu-diagnostic-v1', 'shsmu-support-v1', 'shsmu-browser-support-v1', 'shsmu-support-capture-v1'):
            raise SourceError("这是失败诊断文件，不能导入课表；请按浏览器页面提示继续或重新采集，选择 shsmu-capture 开头的文件。")
        if self.capture.get("format") != "shsmu-capture-v1" or self.capture.get("complete") is not True:
            raise SourceError("文件不是已经完整采集的课表响应。")
        if self.capture.get("origin") != ORIGIN:
            raise SourceError("采集文件的来源不符。")
        if not isinstance(self.capture.get('config'), dict):
            raise SourceError("采集文件缺少有效学期配置，请重新采集。")
        for key in ("semester", "start", "end_exclusive"):
            if self.capture.get("config", {}).get(key) != config[key]:
                raise SourceError("采集文件日期或学期与本机配置不同。请运行 sync.py --prepare，刷新安装页并手动替换旧书签网址，再采集。")
        self.account_key = self.capture.get("account_key", "")
        if not isinstance(self.account_key, str) or not re.fullmatch(r"[a-f0-9]{64}", self.account_key):
            raise SourceError("缺少登录账号的本地匿名校验标识。")
        self.request_count = 0
        self.records = {}
        records = self.capture.get('responses')
        if not isinstance(records, list):
            raise SourceError("采集文件缺少完整响应列表，请重新采集。")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get('params'), dict) or 'response' not in record:
                raise SourceError("采集文件中的响应记录不完整，请重新采集。")
            if record.get("path") not in ENDPOINTS:
                raise SourceError("采集文件包含未核实的数据来源。")
            key = request_key(record["path"], record["params"])
            if key in self.records:
                raise SourceError("采集文件包含重复请求记录。")
            self.records[key] = record["response"]

    def request(self, path, params):
        key = request_key(path, params)
        if key not in self.records:
            raise SourceError("采集文件缺少所需日期范围或教学详情，未发布。请重新在教务页面点击书签。")
        self.request_count += 1
        return self.records[key]

    def timetable(self, start, end):
        data = self.request("/Home/GetCurriculumTable", {"Start": start, "End": end})
        if not isinstance(data, dict) or not isinstance(data.get("List"), list):
            raise SourceError("课表响应结构改变：缺少 List 数组。")
        return data

    def details(self, event, slot_ids=None):
        return self.request("/Home/GetCalendarTable", {
            "MCSID": str(event.get("MCSID") or "") if slot_ids is None else ",".join(slot_ids),
            "CSID": str(event.get("CSID") or ""), "CurriculumID": str(event.get("CurriculumID") or ""),
            "XXKMID": str(event.get("XXKMID") or ""), "CurriculumType": str(event.get("CurriculumType") or ""),
        })
