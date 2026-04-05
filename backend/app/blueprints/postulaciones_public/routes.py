from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Tuple
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename
from sqlalchemy import text

from ...extensions import db
from ...models import JobApplication, JobApplicationFile, JobPosition
from ...models.setting import Setting
from ...services.modules_registry import is_module_public_enabled


bp = Blueprint("postulaciones_public", __name__)


@bp.before_request
def _module_gate():
    if not is_module_public_enabled("postulaciones", default=True):
        abort(404)


_PHONE_SCHEMA_OK: bool = False


def _ensure_phone_column() -> None:
    """Ensures job_applications.phone exists.

    This project ships without migrations in production updates, so we add the
    column opportunistically. If permissions are insufficient, we silently
    continue (the app will still run, but phone won't be stored).
    """
    global _PHONE_SCHEMA_OK
    if _PHONE_SCHEMA_OK:
        return
    try:
        db.session.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS phone VARCHAR(40);"))
        db.session.commit()
        _PHONE_SCHEMA_OK = True
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


_RL_BUCKET: dict[str, list[float]] = {}


def _client_ip() -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    now = time.time()
    arr = _RL_BUCKET.get(key) or []
    cutoff = now - float(window_seconds)
    arr = [t for t in arr if t >= cutoff]
    if len(arr) >= int(limit):
        _RL_BUCKET[key] = arr
        return False
    arr.append(now)
    _RL_BUCKET[key] = arr
    return True


def _recaptcha_site_key() -> str:
    key = (os.environ.get("RECAPTCHA_SITE_KEY") or os.environ.get("RECAPTCHA_SITEKEY") or "").strip()
    if key:
        return key
    try:
        return (
            Setting.get("RECAPTCHA_SITE_KEY", "")
            or Setting.get("RECAPTCHA_SITEKEY", "")
            or Setting.get("recaptcha_site_key", "")
        ).strip()
    except Exception:
        return ""


def _recaptcha_secret_key() -> str:
    secret = (os.environ.get("RECAPTCHA_SECRET_KEY") or os.environ.get("RECAPTCHA_SECRET") or "").strip()
    if secret:
        return secret
    try:
        return (
            Setting.get("RECAPTCHA_SECRET_KEY", "")
            or Setting.get("RECAPTCHA_SECRET", "")
            or Setting.get("recaptcha_secret_key", "")
        ).strip()
    except Exception:
        return ""


def _recaptcha_render() -> bool:
    return bool(_recaptcha_site_key())


def _recaptcha_enabled() -> bool:
    return bool(_recaptcha_site_key() and _recaptcha_secret_key())


def _verify_recaptcha(token: str) -> bool:
    secret = _recaptcha_secret_key()
    if not secret:
        return True
    if not token:
        return False

    data = urllib.parse.urlencode({"secret": secret, "response": token, "remoteip": _client_ip()}).encode("utf-8")
    req = urllib.request.Request(
        "https://www.google.com/recaptcha/api/siteverify",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return bool(payload.get("success"))
    except Exception:
        return False


def _is_postulaciones_host() -> bool:
    """Restringe el acceso público a hosts permitidos.

    - Permite override total para test: ALLOW_POSTULACIONES_ANY_HOST=1
    - Soporta reverse proxy (Cloudflare Tunnel) leyendo X-Forwarded-Host.
    - Lista configurable por env/Setting: POSTULACIONES_ALLOWED_HOSTS
      (separado por coma), además de defaults seguros.
    """
    # Permite override para test local: ALLOW_POSTULACIONES_ANY_HOST=1
    if (os.environ.get("ALLOW_POSTULACIONES_ANY_HOST") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return True

    # Detrás de proxies (ej. cloudflared) el Host puede venir reescrito;
    # priorizamos X-Forwarded-Host si existe.
    forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",", 1)[0].strip()
    host_raw = forwarded_host or (request.host or "")

    # Normalizar: quitar puerto y bajar a minúsculas.
    # - 'example.com:443' -> 'example.com'
    # - '[::1]:5802' -> '::1'
    host = host_raw.strip()
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    else:
        host = host.split(":", 1)[0]
    host = host.strip().lower()

    # Defaults:
    # - canonical: https://suite.iluminaras.cloud/postulaciones/
    # - subdominio público: https://postulaciones.iluminaras.cloud/
    # - pruebas locales (no expuesto si binds a 127.0.0.1)
    allowed = {"suite.iluminaras.cloud", "postulaciones.iluminaras.cloud", "localhost", "127.0.0.1"}

    # Env overrides/additions
    extra_env = (os.environ.get("POSTULACIONES_ALLOWED_HOSTS") or "").strip()
    if extra_env:
        allowed.update({h.strip().lower() for h in extra_env.replace(";", ",").split(",") if h.strip()})

    # Setting overrides/additions (si DB está disponible)
    try:
        extra_setting = (Setting.get("POSTULACIONES_ALLOWED_HOSTS", "") or "").strip()
        if extra_setting:
            allowed.update({h.strip().lower() for h in extra_setting.replace(";", ",").split(",") if h.strip()})
    except Exception:
        pass

    return host in allowed



def _allowed_file(filename: str) -> bool:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return ext in {"pdf", "doc", "docx", "png", "jpg", "jpeg"}


def _uploads_base() -> Path:
    return Path(current_app.root_path).parent / current_app.config.get("GENERATED_DIR", "generated") / "postulaciones_files"


def _list_static_images() -> set[str]:
    """Imágenes disponibles en app/static (recursivo), como paths relativos a /static."""
    static_dir = Path(current_app.static_folder or "")
    if not static_dir.exists():
        return set()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
    out: set[str] = set()
    try:
        for p in static_dir.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in allowed:
                continue
            rel = p.relative_to(static_dir).as_posix()
            if rel.startswith(".") or "/." in rel:
                continue
            out.add(rel)
    except Exception:
        return set()
    return out


def _postulaciones_hero_image() -> str:
    """Devuelve el filename (relativo a /static) de la imagen hero configurable."""
    default_img = "logo_estilo_home2.png"
    try:
        chosen = (Setting.get("POSTULACIONES_HERO_IMAGE", "") or "").strip()
    except Exception:
        chosen = ""
    if not chosen:
        return default_img
    # Validar contra archivos realmente presentes en static para evitar traversal.
    if chosen in _list_static_images():
        return chosen
    return default_img


def get_public_form_context() -> dict:
    # Puestos activos
    puestos = JobPosition.query.filter_by(is_active=True).order_by(JobPosition.sort_order.asc(), JobPosition.name.asc()).all()
    return {
        "puestos": puestos,
        "recaptcha_render": _recaptcha_render(),
        "recaptcha_sitekey": _recaptcha_site_key(),
        "hero_image": _postulaciones_hero_image(),
    }


@bp.get("/", strict_slashes=False)
def public_form():
    """Formulario público: /postulaciones/"""
    if not _is_postulaciones_host():
        abort(404)
    return render_template("postulaciones/public_form.html", **get_public_form_context())


@bp.post("/submit")
def submit():
    if not _is_postulaciones_host():
        abort(404)

    # Rate limit simple: 10 intentos cada 10 minutos por IP
    ip = _client_ip()
    if not _rate_limit(f"apply:{ip}", limit=10, window_seconds=600):
        return render_template(
            "postulaciones/public_form.html",
            error="Demasiados intentos. Probá de nuevo en unos minutos.",
            **get_public_form_context(),
        ), 429

    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    position_id_raw = (request.form.get("position_id") or "").strip()

    # reCAPTCHA
    if _recaptcha_enabled():
        token = (request.form.get("g-recaptcha-response") or "").strip()
        if not _verify_recaptcha(token):
            return render_template(
                "postulaciones/public_form.html",
                error="Verificación reCAPTCHA inválida.",
                **get_public_form_context(),
            ), 400

    # Validaciones básicas
    if not first_name or not last_name or not email or not phone or not position_id_raw:
        return render_template(
            "postulaciones/public_form.html",
            error="Faltan datos obligatorios.",
            **get_public_form_context(),
        ), 400

    try:
        position_id = int(position_id_raw)
    except Exception:
        return render_template(
            "postulaciones/public_form.html",
            error="Puesto inválido.",
            **get_public_form_context(),
        ), 400

    pos = JobPosition.query.get(position_id)
    if not pos or not pos.is_active:
        return render_template(
            "postulaciones/public_form.html",
            error="Puesto inválido.",
            **get_public_form_context(),
        ), 400

    files = request.files.getlist("files")
    files = [f for f in files if f and getattr(f, "filename", "")]
    if not files:
        return render_template(
            "postulaciones/public_form.html",
            error="Tenés que adjuntar al menos un archivo (CV).",
            **get_public_form_context(),
        ), 400

    max_files = int(os.environ.get("POSTULACIONES_MAX_FILES", "6"))
    if len(files) > max_files:
        return render_template(
            "postulaciones/public_form.html",
            error=f"Máximo {max_files} archivos.",
            **get_public_form_context(),
        ), 400

    max_size = int(os.environ.get("POSTULACIONES_MAX_FILE_BYTES", str(15 * 1024 * 1024)))

    # Ensure DB column exists (best-effort)
    _ensure_phone_column()

    app_row = JobApplication(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        position_id=position_id,
        ip=ip,
        user_agent=(request.headers.get("User-Agent") or "")[:300],
    )
    db.session.add(app_row)
    db.session.flush()  # obtener ID

    base_dir = _uploads_base() / str(app_row.id)
    base_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    for f in files:
        original = (f.filename or "").strip()
        if not original:
            continue
        if not _allowed_file(original):
            continue

        # tamaño (si el server envía content_length, usamos eso; si no, lo medimos guardando)
        # Guardamos con nombre seguro.
        ext = (original.rsplit(".", 1)[-1] if "." in original else "").lower()
        safe_original = secure_filename(original) or f"archivo.{ext or 'bin'}"
        stored_name = f"{uuid4().hex}.{ext}" if ext else uuid4().hex
        out_path = base_dir / stored_name

        # Guardar a disco
        f.save(str(out_path))
        try:
            size_bytes = out_path.stat().st_size
        except Exception:
            size_bytes = 0

        if size_bytes and size_bytes > max_size:
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass
            continue

        # sha256
        sha256 = None
        try:
            h = hashlib.sha256()
            with out_path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            sha256 = h.hexdigest()
        except Exception:
            sha256 = None

        rel_path = os.path.relpath(out_path, str(Path(current_app.root_path).parent / current_app.config.get("GENERATED_DIR", "generated")))

        db.session.add(
            JobApplicationFile(
                application_id=app_row.id,
                original_filename=safe_original,
                stored_filename=stored_name,
                mime_type=(f.mimetype or "")[:160],
                size_bytes=int(size_bytes or 0),
                sha256=sha256,
                rel_path=rel_path,
            )
        )
        saved += 1

    if saved <= 0:
        db.session.rollback()
        return render_template(
            "postulaciones/public_form.html",
            error="No se pudo guardar ningún archivo. Verificá formato/tamaño.",
            **get_public_form_context(),
        ), 400

    db.session.commit()
    return render_template("postulaciones/success.html")
