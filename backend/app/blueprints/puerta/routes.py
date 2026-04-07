from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import current_app, render_template

from ...utils import view_required
from . import bp


def _ctrl_url(path: str) -> str:
    base = current_app.config.get("DOOR_CTRL_BASE_URL", "http://192.168.0.155").rstrip("/")
    return f"{base}{path}"


def _api_key() -> str:
    return current_app.config.get("DOOR_CTRL_API_KEY", "")


def _timeout_s() -> float:
    return float(current_app.config.get("DOOR_CTRL_TIMEOUT_S", 2.5))


def _request_json(path: str, method: str = "GET") -> tuple[int, dict]:
    url = _ctrl_url(path)
    req = urllib.request.Request(url, method=method)
    req.add_header("X-API-Key", _api_key())
    req.add_header("Content-Type", "application/json")

    data = b"{}" if method != "GET" else None

    try:
        with urllib.request.urlopen(req, data=data, timeout=_timeout_s()) as resp:
            body = resp.read().decode("utf-8", errors="replace") or "{}"
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, {"ok": resp.status == 200, "raw": body}
    except urllib.error.HTTPError as e:
        body = (e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else "")
        try:
            payload = json.loads(body) if body else {"ok": False, "msg": "http_error"}
        except Exception:
            payload = {"ok": False, "msg": "http_error", "raw": body}
        return e.code, payload
    except Exception as e:
        return 503, {"ok": False, "msg": "unreachable", "detail": str(e)}


@bp.get("/")
@view_required("puerta")
def index():
    code, health = _request_json("/api/health", "GET")
    return render_template("puerta/index.html", health_code=code, health=health)


@bp.post("/open")
@view_required("puerta")
def open_door():
    code, payload = _request_json("/api/open", "POST")
    return current_app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=code,
        mimetype="application/json",
    )


@bp.post("/shutter/up")
@view_required("puerta")
def shutter_up():
    code, payload = _request_json("/api/shutter/up", "POST")
    return current_app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=code,
        mimetype="application/json",
    )


@bp.post("/shutter/down")
@view_required("puerta")
def shutter_down():
    code, payload = _request_json("/api/shutter/down", "POST")
    return current_app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=code,
        mimetype="application/json",
    )


@bp.post("/shutter/stop")
@view_required("puerta")
def shutter_stop():
    code, payload = _request_json("/api/shutter/stop", "POST")
    return current_app.response_class(
        response=json.dumps(payload, ensure_ascii=False),
        status=code,
        mimetype="application/json",
    )
