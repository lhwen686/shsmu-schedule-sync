"""Publish only the committed, verified local calendar over authenticated HTTPS."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from core import export_ics


class UploadError(Exception):
    pass


def load_config(root):
    path = root / "local/webcal.json"
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        raise UploadError("无法读取 local/webcal.json；请检查 UTF-8 JSON 格式和文件权限，不需要重新采集学校。") from None
    if not isinstance(config, dict) or type(config.get('enabled', False)) is not bool:
        raise UploadError("local/webcal.json 必须是 JSON 对象，enabled 必须为 true 或 false。")
    if not config.get("enabled", False):
        return None
    try:
        if not isinstance(config.get('origin'), str):
            raise ValueError
        url = urlsplit(config['origin'])
        url.port
    except ValueError:
        raise UploadError("日历发布 origin 或端口无效；请对照部署说明修正 local/webcal.json。") from None
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment):
        raise UploadError("日历发布地址必须为不含凭证的 HTTPS 源站地址。")
    if not all(isinstance(config.get(key), str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", config[key]) for key in ("read_token", "write_token")):
        raise UploadError("日历发布密钥配置无效。")
    if config["read_token"] == config["write_token"]:
        raise UploadError("订阅密钥与上传密钥必须不同。")
    return config


def make_payload(root):
    from sync import load_current
    snapshot = load_current(root)
    if snapshot is None:
        raise UploadError("尚无完整课表，未上传。")
    expected = export_ics(snapshot)
    if (root / "output/calendar.ics").read_bytes() != expected:
        raise UploadError("本地日历与完整快照不一致，未上传；请先运行 --repair。")
    pointer = json.loads((root / "data/current.json").read_text(encoding="utf-8"))
    return {"schema": 1, "run_id": pointer["run_id"],
            "source_fetched_at": snapshot["capture_fetched_at"],
            "sha256": hashlib.sha256(expected).hexdigest(),
            "event_count": expected.count(b"BEGIN:VEVENT\r\n"),
            "ics_base64": base64.b64encode(expected).decode("ascii")}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward read/write capabilities to a redirect destination.
        return None


def request(config, method, path, body=None, writer=False):
    # Standard library networking respects the user's existing system settings.
    # Nothing changes proxy, resolver, trust store, or browser configuration.
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    headers = {"Content-Type": "application/json", "User-Agent": "SHSMU-Calendar-Sync/1"}
    if writer:
        headers["Authorization"] = "Bearer " + config["write_token"]
    req = Request(config["origin"].rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        response = opener.open(req, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise UploadError("线上日历响应过大，未确认发布成功。")
        return response.code, data


def publish_current(root, required=False):
    config = load_config(root)
    if config is None:
        if required:
            raise UploadError("尚未启用 WebCal，请先完成 local/webcal.json 配置。")
        print("未启用 WebCal，已完成本地处理；可使用 output/calendar.ics，手机订阅不会自动更新。", flush=True)
        return None
    payload = make_payload(root)
    body = json.dumps(payload, separators=(",", ":")).encode()
    # Retry the exact same version after an uncertain response; server commits are idempotent.
    for attempt in range(2):
        try:
            status, data = request(config, "PUT", "/upload", body, writer=True)
            if status == 409:
                raise UploadError("线上已有更新版本或同时间冲突版本，拒绝覆盖。")
            if status in (400, 404, 413, 415):
                raise UploadError("线上拒绝上传，请检查日历发布配置；本地完整版本已保留。")
            if status != 200:
                raise OSError("upload failed")
            acknowledged = json.loads(data)
            if any(acknowledged.get(k) != payload[k] for k in ("sha256", "source_fetched_at", "run_id", "event_count")):
                raise UploadError("线上返回的版本与本次上传不符，未确认发布成功。")
            status, downloaded = request(config, "GET", "/" + config["read_token"] + "/calendar.ics")
            if status != 200 or hashlib.sha256(downloaded).hexdigest() != payload["sha256"]:
                raise OSError("readback failed")
            from sync import atomic_write, json_bytes
            evidence = {"verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "origin": config["origin"], **acknowledged}
            atomic_write(root / "local/webcal-last-success.json", json_bytes(evidence))
            print(f"线上日历已更新并回读校验：{payload['event_count']} 个日历事件。", flush=True)
            return evidence
        except UploadError:
            raise
        except Exception:
            if attempt == 0:
                time.sleep(2)
    raise UploadError("本地课表已保存，但线上上传或回读未确认成功。请运行 --upload-only 重试，无需重新采集。")
