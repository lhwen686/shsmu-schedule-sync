# 学校接口与数据依据

以下来自 2026-09-05 正常登录后的页面脚本和结构化响应。学校未来改变接口时需要重新核实。

| 用途 | GET 路径 | 参数 |
| --- | --- | --- |
| 主课表 | `/Home/GetCurriculumTable` | `Start`、`End`，格式 `YYYY-MM-DD` |
| 单事件教师详情 | `/Home/GetCalendarTable` | `MCSID`、`CSID`、`CurriculumID`、`XXKMID`、`CurriculumType` |

- 从本人正常打开的 `/Home` 页面读取可见账号标识的摘要，不额外请求首页。额外首页请求曾触发认证重定向。
- 服务器可用 `text/html` Content-Type 返回合法 JSON，必须核对正文结构。登录 HTML 和认证跳转仍然失败。
- 合法空月份可返回 `Title:null, List:[]`；非空月份必须匹配学期。
- 合并多个事件的 MCSID 请求会漏详情，应逐事件顺序读取。
- 主表 `Start`、`End` 是明确本地日期时间；`Curriculum` 是课程名，`ClassroomAcademy` 是完整地点。
- 保留事件、排课节次及详情标识。主表 `CSID` 对应详情 `ScheduleManagerID`，不擅自认定为教学班 ID。
- 详情 `Teacher`、`Content`、`Bz` 提供教师、内容与备注；检查 `CurriculumScheduleIDs`、课程 ID 和 `ClassTime` 的对应关系。
- `TeachingCalendarID` 是课程级标识，不能单独作为事件身份。`gid`、`RowNumber` 不参与语义差异。
- 若学校同时重建全部源 ID，无法只凭名称和时间证明新旧事件相同；程序停止并提示身份问题。
- 清理电话、邮箱、教师账号、工号、视频链接及认证相关字段。真实业务响应和页面证据仅保存在本机忽略目录中。
