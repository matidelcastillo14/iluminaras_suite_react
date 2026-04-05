from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask

from ..models import Setting


# Keys exposed in Admin > Configuración.
# Mantener esta lista como única fuente de verdad.
SETTINGS_KEYS: list[str] = [
    # Sistema
    "APP_TIMEZONE",

    # Odoo (solo lectura)
    "ODOO_URL",
    "ODOO_DB",
    "ODOO_USERNAME",
    "ODOO_API_KEY",
    "ENABLE_ODOO_LOOKUP",
    "ODOO_SEARCH_LIMIT",
    "ODOO_ENVIO_FIELD",
    "ODOO_SHIPPING_CODE_FIELD",
    "ODOO_ZONE_FIELD",
    "ODOO_ORDER_SEARCH_EXTRA_FIELDS",
    "ODOO_PARTNER_SEARCH_EXTRA_FIELDS",

    # PDFs / tickets
    "RECEIPT_WIDTH_MM",
    "PRINT_PDF_WIDTH_MM",
    "RECEIPT_MIN_HEIGHT_MM",
    "CHANGE_VALID_DAYS",
    "CHANGE_TICKET_VALID_DAYS",
    "CHANGE_TICKET_FOOTER_TEXT",
    "CHANGE_TICKET_POLICY_URL",
    "CHANGE_TICKET_POLICY_URL_LUMINARAS",
    "CHANGE_TICKET_POLICY_URL_ESTILO_HOME",
    "CHANGE_TICKET_POLICY_URL_MAYORISTAS_URUGUAY",

    # Adendas
    "DEFAULT_ADENDA_LUMINARAS",
    "DEFAULT_ADENDA_ESTILO_HOME",
    "DEFAULT_ADENDA_MAYORISTAS_URUGUAY",
    "DEFAULT_ADENDA",

    # Logos
    "LOGO_PATH",
    "LOGO_LUMINARAS_PATH",
    "LOGO_ESTILO_HOME_PATH",
    "LOGO_MAYORISTAS_URUGUAY_PATH",

    # Postulaciones (UI pública)
    "POSTULACIONES_HERO_IMAGE",

    # Auto poll
    "CFE_POLL_ENABLED",
    "CFE_POLL_SECONDS",
    "CFE_SCAN_LIMIT",

    # Inventario - Pedidos por Batch
    "BATCH_PEDIDOS_ROWS_LIMIT",

    # Etiquetas
    "LABEL_WIDTH_MM",
    "LABEL_HEIGHT_MM",

    # Rastreo
    "TRACKING_SECRET",

    # Mail
    "MAIL_SERVER",
    "MAIL_PORT",
    "MAIL_USE_TLS",
    "MAIL_USE_SSL",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_DEFAULT_SENDER",

    # Cleanup
    "KEEP_PDFS_HOURS",
]


def _cast_like(base: Any, raw: Any) -> Any:
    """Casteo básico: respeta el tipo que ya tiene el valor base en app.config."""
    if base is None:
        return raw

    try:
        if isinstance(base, bool):
            return str(raw).strip() in {"1", "true", "True", "yes", "YES", "on", "ON"}
        if isinstance(base, int) and not isinstance(base, bool):
            return int(str(raw).strip() or "0")
        if isinstance(base, float):
            return float(str(raw).strip() or "0")
    except Exception:
        return raw

    return raw


def apply_db_settings(flask_app: Flask) -> None:
    """Aplica settings de DB sobre flask_app.config (en caliente)."""
    rows = Setting.query.all()
    for r in rows:
        key = r.key
        val = r.value
        if key in flask_app.config:
            flask_app.config[key] = _cast_like(flask_app.config.get(key), val)
        else:
            flask_app.config[key] = val


def _resolve_from_suite_root(suite_app: Flask, p: str) -> str:
    """Resuelve paths configurados desde el root del proyecto Suite.

    - Si p es absoluto, se usa tal cual.
    - Si es relativo, se resuelve respecto a <suite_root>/ (parent de app.root_path).
    """
    p = (p or "").strip()
    if not p:
        return ""
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    base = Path(suite_app.root_path).parent
    return str((base / pp).resolve())


def sync_settings_to_legacy_app(suite_app: Flask, legacy_app: Flask) -> None:
    """Copia la configuración visible en Admin hacia una app legacy montada.

    Nota: para keys *_PATH, resolvemos el path desde el root de Suite para que los
    legacy engines puedan encontrar los archivos aunque su root_path sea distinto.
    """
    for k in SETTINGS_KEYS:
        if k not in suite_app.config:
            continue

        v = suite_app.config.get(k)
        # Paths
        if k.endswith("_PATH"):
            # Si no está configurado, no pisar el default del legacy.
            if not str(v or "").strip():
                continue
            legacy_app.config[k] = _resolve_from_suite_root(suite_app, str(v or ""))
            continue

        # Otras keys (tipadas ya en suite_app.config)
        legacy_app.config[k] = v
