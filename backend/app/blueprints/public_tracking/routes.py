from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from flask import Blueprint, abort, current_app, redirect, render_template, request, send_file, url_for

from ...models import TrackingEvent, TrackingShipment
from ...models.setting import Setting
from ...services.tracking_labels import label_status
from ...services.modules_registry import is_module_public_enabled


bp = Blueprint("public_tracking", __name__, url_prefix="/t")


@bp.before_request
def _module_gate():
    # Si el módulo público está apagado, responder 404 (no filtra info)
    if not is_module_public_enabled("admin_tracking", default=True):
        abort(404)


# ---------------------------
# Rate limit (simple, in-memory)
# ---------------------------

_RL_BUCKET: dict[str, list[float]] = {}


def _client_ip() -> str:
    # Si estás detrás de Cloudflare, CF-Connecting-IP es lo ideal.
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
    # Preferimos entorno, pero permitimos configuración desde la tabla settings
    # para no depender de variables de entorno en deployments existentes.
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
        # Si la BD todavía no está lista, simplemente no activamos el widget.
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
    # Mostrar el checkbox depende solo del SITE KEY.
    return bool(_recaptcha_site_key())


def _recaptcha_enabled() -> bool:
    # Enforzar validación requiere ambas claves.
    return bool(_recaptcha_site_key() and _recaptcha_secret_key())


def _verify_recaptcha(token: str) -> bool:
    secret = _recaptcha_secret_key()
    if not secret:
        return True
    if not token:
        return False

    data = urllib.parse.urlencode(
        {
            "secret": secret,
            "response": token,
            "remoteip": _client_ip(),
        }
    ).encode("utf-8")
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
        # Si el verificador falla por red, tratamos como inválido.
        return False


# ---------------------------
# Public status mapping
# ---------------------------


@dataclass(frozen=True)
class PublicStatus:
    event_label: str
    fixed_comment: str = ""


PUBLIC_STATUS_MAP: dict[str, PublicStatus] = {
    "READY_FOR_DISPATCH": PublicStatus("Listo para despachar", "Aguardando asignación de cadete"),
    "OUT_FOR_DELIVERY": PublicStatus("En reparto", ""),
    "ON_ROUTE_TO_DELIVERY": PublicStatus("El cadete está en camino", ""),
    "DELIVERY_FAILED": PublicStatus(
        "Entrega fallida",
        "No entregado, reintentaremos la entrega en el siguiente turno",
    ),
    "RETURNED": PublicStatus("Devuelto", "El pedido fue devuelto al remitente"),
    "DELIVERED": PublicStatus("Entregado", ""),
}


# ---------------------------
# Public view filters + timezone
# ---------------------------


def _public_tz_name() -> str:
    # Uruguay / Montevideo
    return (os.environ.get("PUBLIC_TRACKING_TZ") or "America/Montevideo").strip() or "America/Montevideo"


def _to_public_tz(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    # created_at suele venir naive desde Postgres; asumimos UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        if ZoneInfo is None:
            return dt
        return dt.astimezone(ZoneInfo(_public_tz_name()))
    except Exception:
        return dt


def _event_payload_dict(ev) -> dict:
    """Devuelve el payload del evento como dict.

    `TrackingEvent.payload_json` puede venir como dict (columna JSON) o como str (texto JSON).
    Esta función es tolerante a errores y nunca lanza excepción.
    """
    raw = getattr(ev, "payload_json", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", errors="ignore")
        except Exception:
            return {}
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    # fallback (por si viniera como objeto serializable)
    try:
        return dict(raw)
    except Exception:
        return {}


_HIDE_PREFIXES = (
    "LABEL_",
    "SALES_OVERRIDE",
)


_HIDE_EXACT_DEFAULT = {
    "ETIQUETA_GENERADA",
    "LABEL_CREATED",
    "LABEL_GENERATED",
    "RETURNED_TO_DEPOT",
    "RETURNED_TO_DEPOT_PENDING_CONFIRMATION",
    "RETURNED_TO_WAREHOUSE",
    "RETURNED_TO_WAREHOUSE_PENDING_CONFIRMATION",
    "PENDING_CONFIRMATION",
    "PENDING",
    # Si querés mostrar 'Devuelto' al cliente, podés sacarlo del hide list con env.
    "RETURNED",
}


def _extra_hidden_types() -> set[str]:
    raw = (os.environ.get("PUBLIC_TRACKING_HIDE_TYPES") or "").strip()
    if not raw:
        return set()
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def _is_hidden_public_event_type(event_type: str) -> bool:
    et = (event_type or "").upper().strip()
    if not et:
        return True

    # Permitir mostrar Devuelto si se configura explícitamente.
    if et == "RETURNED":
        show_returned = (os.environ.get("PUBLIC_TRACKING_SHOW_RETURNED") or "").strip().lower()
        if show_returned in {"1", "true", "yes", "y", "on"}:
            return False
    if any(et.startswith(p) for p in _HIDE_PREFIXES):
        return True
    if et in (_HIDE_EXACT_DEFAULT | _extra_hidden_types()):
        return True
    # Si no está en el mapa público, por defecto es interno.
    return et not in PUBLIC_STATUS_MAP


# ---------------------------
# Helpers: code parsing + lookup
# ---------------------------


def _parse_scanned_code(raw: str) -> str:
    code = (raw or "").strip()
    if not code:
        return ""
    # si el QR contiene URL /rastreo/go/<code>, extraer último segmento
    if "/rastreo/go/" in code:
        try:
            code = code.split("/rastreo/go/")[-1].split("?")[0].strip("/")
        except Exception:
            pass
    if "/t/" in code:
        try:
            code = code.split("/t/")[-1].split("?")[0].strip("/")
        except Exception:
            pass
    return (code or "").strip()


def _find_shipment_by_any_code(raw_code: str) -> TrackingShipment | None:
    code = _parse_scanned_code(raw_code)
    code = (code or "").strip()
    if not code:
        return None
    sh = TrackingShipment.query.filter_by(tracking_code=code).first()
    if sh:
        return sh
    sh = TrackingShipment.query.filter_by(order_name=code).first()
    if sh:
        return sh
    return TrackingShipment.query.filter_by(id_web=code).first()


# ---------------------------
# Helpers: sanitization
# ---------------------------


_re_ci = re.compile(r"\bC\.?I\.?\b|\bCI\b", re.IGNORECASE)
_re_digits = re.compile(r"\d+")


def _mask_words_keep_first(name: str) -> str:
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    masked = [parts[0]]
    for w in parts[1:]:
        masked.append("*" * max(3, len(w)))
    return " ".join(masked)


def _mask_ci_in_text(text: str) -> str:
    if not text:
        return ""

    # Solo en segmentos donde aparece CI/C.I.
    def repl(m: re.Match) -> str:
        chunk = m.group(0)
        digits = "".join(_re_digits.findall(chunk))
        if not digits:
            return chunk
        last4 = digits[-4:]
        masked = "*" * max(0, len(digits) - 4) + last4
        # reemplaza la primera secuencia de dígitos por masked (si hay múltiples, igual se vuelve a aplicar)
        return re.sub(r"\d{4,}", masked, chunk, count=1)

    # Buscar ventanas pequeñas alrededor de CI, para no mascar números ajenos.
    out = text
    # Patrón: desde 'CI' hasta 25 chars después.
    out = re.sub(r"(CI|C\.?I\.?)([^\n]{0,25})", lambda m: repl(m), out, flags=re.IGNORECASE)
    return out




def _mask_receiver_name(name: str) -> str:
    """Muestra solo la primera palabra y enmascara el resto por palabra con asteriscos."""
    n = (name or "").strip()
    if not n:
        return ""
    parts = [p for p in re.split(r"\s+", n) if p]
    if not parts:
        return ""
    first = parts[0]
    if len(parts) == 1:
        return first
    masked_rest = ["*" * len(p) if len(p) > 0 else "" for p in parts[1:]]
    return " ".join([first] + masked_rest)


def _mask_ci_value(ci_raw: str) -> str:
    """Enmascara CI dejando visibles los últimos 4 dígitos numéricos."""
    raw = (ci_raw or "").strip()
    if not raw:
        return ""
    digits = "".join(_re_digits.findall(raw))
    if not digits:
        return ""
    last4 = digits[-4:]
    masked = "*" * max(0, len(digits) - 4) + last4
    return masked



def _clean_receiver_relation(rel: str) -> str:
    r = (rel or "").strip()
    if not r:
        return ""
    r = re.sub(r"^Receptor:\s*", "", r, flags=re.IGNORECASE).strip()
    # Evitar textos excesivos o con saltos
    r = re.sub(r"\s+", " ", r).strip()
    return r[:60]


def _extract_delivered_receiver(ev) -> tuple[str, str, str]:
    """Extrae relación, receptor (nombre) y CI de payload o nota y devuelve valores enmascarados.

    Soporta payload estándar:
      - receiver_relation, receiver_name, receiver_id
    y también variaciones/compatibilidad hacia atrás.
    """
    pld = _event_payload_dict(ev)

    raw_rel = (
        (pld.get("receiver_relation") if isinstance(pld, dict) else None)
        or (pld.get("relation") if isinstance(pld, dict) else None)
        or (pld.get("receiver_relationship") if isinstance(pld, dict) else None)
        or ""
    )

    raw_name = (
        (pld.get("receiver_name") if isinstance(pld, dict) else None)
        or (pld.get("receiver") if isinstance(pld, dict) else None)
        or (pld.get("received_by") if isinstance(pld, dict) else None)
        or (pld.get("delivered_to") if isinstance(pld, dict) else None)
        or ""
    )

    raw_ci = (
        (pld.get("receiver_id") if isinstance(pld, dict) else None)
        or (pld.get("receiver_ci") if isinstance(pld, dict) else None)
        or (pld.get("receiver_document") if isinstance(pld, dict) else None)
        or (pld.get("ci") if isinstance(pld, dict) else None)
        or (pld.get("cedula") if isinstance(pld, dict) else None)
        or ""
    )

    # Compatibilidad: si viene como nota tipo "Receptor: Amigo/a - Matias del Castillo (CI 5.164.775-2)"
    note = (getattr(ev, "note", None) or "").strip()
    if (not raw_name or not raw_ci or not raw_rel) and note:
        m = re.search(
            r"Receptor:\s*([^\-·\(]+?)\s*[-·]\s*([^\(]+?)\s*\((?:CI|C\.?I\.?)[^0-9]*([0-9\.\-\s]+)\)",
            note,
            flags=re.IGNORECASE,
        )
        if m:
            if not raw_rel:
                raw_rel = (m.group(1) or "").strip()
            if not raw_name:
                raw_name = (m.group(2) or "").strip()
            if not raw_ci:
                raw_ci = (m.group(3) or "").strip()

    # Fallbacks adicionales desde nota
    if note:
        if not raw_ci:
            mci = re.search(r"\((?:CI|C\.?I\.?)[^0-9]*([0-9\.\-\s]+)\)", note, flags=re.IGNORECASE)
            if mci:
                raw_ci = (mci.group(1) or "").strip()
        if not raw_name:
            # intenta capturar nombre al final antes del (CI ...)
            mn = re.search(r"[-·]\s*([^\(]+?)\s*\((?:CI|C\.?I\.?)[^)]*\)", note, flags=re.IGNORECASE)
            if mn:
                raw_name = (mn.group(1) or "").strip()
        if not raw_rel:
            mrel = re.search(r"Receptor:\s*([^\-·\(]+?)\s*[-·]", note, flags=re.IGNORECASE)
            if mrel:
                raw_rel = (mrel.group(1) or "").strip()

    return (
        _clean_receiver_relation(str(raw_rel or "")),
        _mask_receiver_name(str(raw_name or "")),
        _mask_ci_value(str(raw_ci or "")),
    )


def _sanitize_detail_public(event_type: str, detail: str) -> str:
    d = (detail or "").strip()
    if not d:
        return ""

    et = (event_type or "").upper().strip()

    # No exponer razones internas en fallos de entrega (ya hay un comentario fijo público).
    if et == "DELIVERY_FAILED":
        return ""

    # Normalizar separadores comunes
    d = d.replace("·", " · ")
    d = re.sub(r"\s+", " ", d).strip()

    # Limpiar etiquetas internas frecuentes en notas (auto/Flex/override)
    d = re.sub(r"\((?:auto|flex)\)", "", d, flags=re.IGNORECASE).strip()
    d = re.sub(r"\bSALES_OVERRIDE\b", "", d, flags=re.IGNORECASE).strip()
    d = re.sub(r"\s+", " ", d).strip()

    # Caso Entregado: enmascarar nombre y CI
    if et == "DELIVERED" or "Receptor" in d:
        # Intento de extraer nombre del receptor: último token antes de (CI ...)
        # Ej: "Receptor: Titular (comprador) · Natalia (CI 12345678)"
        name_match = re.search(r"·\s*([^()]+?)\s*\((?:CI|C\.?I\.?)[^)]*\)", d, flags=re.IGNORECASE)
        if name_match:
            raw_name = (name_match.group(1) or "").strip()
            masked_name = _mask_words_keep_first(raw_name)
            d = d[: name_match.start(1)] + masked_name + d[name_match.end(1) :]
        else:
            # fallback: si hay "Receptor:" y luego un nombre sin CI
            nm2 = re.search(r"Receptor:\s*([^·\n]+)$", d, flags=re.IGNORECASE)
            if nm2:
                raw_name = nm2.group(1).strip()
                d = d[: nm2.start(1)] + _mask_words_keep_first(raw_name)

        d = _mask_ci_in_text(d)

    return d


def _public_event_label(event_type: str) -> str:
    et = (event_type or "").upper()
    if et in PUBLIC_STATUS_MAP:
        return PUBLIC_STATUS_MAP[et].event_label
    # fallback a label_status del sistema si no está mapeado
    try:
        return label_status(et)
    except Exception:
        return et


def _public_fixed_comment(event_type: str) -> str:
    et = (event_type or "").upper()
    if et in PUBLIC_STATUS_MAP:
        return PUBLIC_STATUS_MAP[et].fixed_comment
    return ""


# ---------------------------
# Routes
# ---------------------------


@bp.get("/")
def search():
    return render_template(
        "public_tracking/search.html",
        title="Rastreo",
        recaptcha_sitekey=_recaptcha_site_key(),
        recaptcha_render=_recaptcha_render(),
        recaptcha_enabled=_recaptcha_enabled(),
        error=None,
    )


@bp.post("/")
def search_post():
    ip = _client_ip()
    if not _rate_limit(f"search:{ip}", limit=12, window_seconds=300):
        return render_template(
            "public_tracking/search.html",
            title="Rastreo",
            recaptcha_sitekey=_recaptcha_site_key(),
            recaptcha_render=_recaptcha_render(),
            recaptcha_enabled=_recaptcha_enabled(),
            error="Demasiados intentos. Probá de nuevo en unos minutos.",
        ), 429

    code = (request.form.get("code") or "").strip()
    code = _parse_scanned_code(code)

    token = (request.form.get("g-recaptcha-response") or "").strip()
    if _recaptcha_enabled() and not _verify_recaptcha(token):
        return render_template(
            "public_tracking/search.html",
            title="Rastreo",
            recaptcha_sitekey=_recaptcha_site_key(),
            recaptcha_render=_recaptcha_render(),
            recaptcha_enabled=_recaptcha_enabled(),
            error="Verificación inválida. Intentá nuevamente.",
        ), 400

    if not code:
        return redirect(url_for("public_tracking.search"))

    # Buscar
    sh = _find_shipment_by_any_code(code)
    if not sh:
        return render_template(
            "public_tracking/search.html",
            title="Rastreo",
            recaptcha_sitekey=_recaptcha_site_key(),
            recaptcha_render=_recaptcha_render(),
            recaptcha_enabled=_recaptcha_enabled(),
            error="No encontramos ese número de rastreo.",
        ), 404

    return redirect(url_for("public_tracking.detail", tracking_code=sh.tracking_code))


@bp.get("/<tracking_code>")
def detail(tracking_code: str):
    sh = _find_shipment_by_any_code(tracking_code)
    if not sh:
        abort(404)
    events = (
        TrackingEvent.query.filter_by(shipment_id=sh.id)
        .order_by(TrackingEvent.created_at.desc())
        .all()
    )

    # construir vista pública
    pub_events = []
    for e in events:
        et = (e.event_type or "").upper().strip()
        if _is_hidden_public_event_type(et):
            continue
        receiver_relation = ""
        receiver_name = ""
        receiver_ci = ""
        if et == "DELIVERED":
            receiver_relation, receiver_name, receiver_ci = _extract_delivered_receiver(e)

        pub_events.append(
            {
                "id": e.id,
                "created_at": _to_public_tz(e.created_at),
                "event_label": _public_event_label(et),
                "receiver_relation": receiver_relation,
                "receiver_name": receiver_name,
                "receiver_ci": receiver_ci,
                "detail": _sanitize_detail_public(et, e.note or ""),
                "fixed_comment": _public_fixed_comment(et),
                "has_photo": bool(e.image_path),
            }
        )

    # Pedido visible: preferir id_web si existe (más parecido a tus imágenes), sino order_name
    pedido = (sh.id_web or "").strip() or sh.order_name

    return render_template(
        "public_tracking/detail.html",
        title="Rastreo",
        shipment=sh,
        shipment_created_at=_to_public_tz(getattr(sh, "created_at", None)),
        pedido=pedido,
        pub_events=pub_events,
    )


@bp.get("/<tracking_code>/photo/<int:event_id>")
def photo(tracking_code: str, event_id: int):
    sh = _find_shipment_by_any_code(tracking_code)
    if not sh:
        abort(404)
    ev = TrackingEvent.query.get(int(event_id))
    if not ev or int(ev.shipment_id) != int(sh.id):
        abort(404)
    if not ev.image_path:
        abort(404)

    # Sólo servir desde generated/tracking_photos/<shipment_id>/<file>
    rel = (ev.image_path or "").strip().lstrip("/\\")
    if ".." in rel or rel.startswith("/") or rel.startswith("\\"):
        abort(400)

    base = Path(current_app.root_path).parent / current_app.config.get("GENERATED_DIR", "generated") / "tracking_photos"
    fpath = base / rel
    if not fpath.exists() or not fpath.is_file():
        abort(404)
    return send_file(str(fpath))
