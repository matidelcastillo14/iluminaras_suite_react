import json
import urllib.request
import urllib.error

from flask import abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.utils import can_view
from . import bp


def _esp_url(path: str) -> str:
    base = current_app.config.get("DOOR_ESP_BASE_URL", "http://192.168.0.144").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _esp_post(path: str, timeout: float = 3.0):
    api_key = current_app.config.get("DOOR_API_KEY", "")
    url = _esp_url(path)

    req = urllib.request.Request(
        url=url,
        method="POST",
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        data=b"{}",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {"raw": body}
        return resp.status, payload


def _esp_get(path: str, timeout: float = 3.0):
    url = _esp_url(path)
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {"raw": body}
        return resp.status, payload


@bp.get("/")
@login_required
def index():
    if not can_view(current_user, "door"):
        abort(403)

    status = None
    info = None
    try:
        code, payload = _esp_get("/health")
        status = code
        info = payload
    except Exception as e:
        current_app.logger.warning("DOOR health check failed: %s", e)
        status = 0
        info = {"ok": False, "msg": str(e)}

    return render_template("door/index.html", esp_status=status, esp_info=info)


@bp.post("/open")
@login_required
def open_door():
    if not can_view(current_user, "door"):
        abort(403)

    try:
        code, payload = _esp_post("/open")
        ok = bool(payload.get("ok")) and code == 200
        if ok:
            current_app.logger.info("DOOR opened via Suite (esp=%s)", current_app.config.get("DOOR_ESP_BASE_URL"))
            flash("Puerta: apertura enviada OK.", "success")
        else:
            current_app.logger.warning("DOOR open failed (code=%s payload=%s)", code, payload)
            flash(f"Puerta: fallo al abrir ({code}). {payload}", "error")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        current_app.logger.warning("DOOR open HTTPError: %s body=%s", e, body)
        flash(f"Puerta: error HTTP {e.code}. {body}", "error")
    except Exception as e:
        current_app.logger.exception("DOOR open exception")
        flash(f"Puerta: error de conexión. {e}", "error")

    return redirect(url_for("door.index"))
