from __future__ import annotations

import os
import uuid
import time
import glob
import re
import html as _html
import xmlrpc.client
import logging
from logging.handlers import TimedRotatingFileHandler
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for, g
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF



def mm(x: float) -> float:
    # millimeters -> points
    return x * 72.0 / 25.4


@dataclass
class LabelData:
    nombre: str = ""
    direccion: str = ""
    telefono: str = ""
    pedido: str = ""
    # Preferido para imprimir debajo del nombre (ID Web del pedido)
    id_web: str = ""
    zona: str = ""
    envio: str = ""
    codigo_envio: str = ""
    observaciones: str = ""

    # Rastreo
    tracking_code: str = ""
    tracking_url: str = ""

    # Marca/tienda para seleccionar logo
    brand: str = ""
    # Logo resuelto (si se desea forzar)
    logo_path: str = ""



def _clean_html_text(s: Any) -> str:
    """Best-effort conversion of Odoo HTML notes into plain text."""
    if s is None:
        return ""
    t = str(s)
    if not t:
        return ""

    # Normalize common HTML blocks into separators
    t = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", t)
    t = re.sub(r"(?is)</\s*p\s*>", "\n", t)
    t = re.sub(r"(?is)<\s*p[^>]*>", "", t)

    # Strip remaining tags
    t = re.sub(r"(?is)<[^>]+>", "", t)
    t = _html.unescape(t)
    t = t.replace("\xa0", " ")

    # Clean whitespace
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()



def _clean_plain_text(s: Any) -> str:
    """Plain single-line text (no tags, no newlines)."""
    t = _clean_html_text(s)
    return " ".join(t.splitlines()).strip()


def _digits_only(s: Any) -> str:
    """Extract only digits from a possibly-HTML value."""
    t = _clean_plain_text(s)
    return "".join(re.findall(r"\d+", t))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default

# ------------------------------------------------------------
# Adaptación para "Iluminaras Suite": motor legacy de etiquetas
# (reportlab) sin rutas Flask.
# ------------------------------------------------------------
from types import SimpleNamespace

app = SimpleNamespace(config={}, root_path=os.getcwd())
app_log = logging.getLogger("etiquetas_legacy_engine")

_odoo_cache: dict[str, Any] = {}
_fields_cache: dict[str, set[str]] = {}

def configure(config: dict[str, Any], root_path: str | None = None, logger: logging.Logger | None = None) -> None:
    app.config = config
    if root_path:
        app.root_path = root_path
    if logger:
        global app_log
        app_log = logger

    # Normalizar paths (muchas configs vienen relativas al proyecto).
    try:
        gen = str(app.config.get("GENERATED_DIR", "") or "").strip()
        if gen and not os.path.isabs(gen):
            app.config["GENERATED_DIR"] = os.path.join(app.root_path, gen)
    except Exception:
        pass

    try:
        lp = str(app.config.get("LOGO_PATH", "") or "").strip()
        if lp and not os.path.isabs(lp):
            app.config["LOGO_PATH"] = os.path.join(app.root_path, lp)
    except Exception:
        pass

    # Normalizar paths de logos por marca (si están configurados)
    for k in ("LOGO_LUMINARAS_PATH", "LOGO_ESTILO_HOME_PATH"):
        try:
            v = str(app.config.get(k, "") or "").strip()
            if v and not os.path.isabs(v):
                app.config[k] = os.path.join(app.root_path, v)
        except Exception:
            pass

def _odoo_is_configured() -> bool:
    if not app.config.get("ENABLE_ODOO_LOOKUP"):
        return False
    return bool(app.config.get("ODOO_URL") and app.config.get("ODOO_DB") and app.config.get("ODOO_USERNAME") and app.config.get("ODOO_API_KEY"))



def _odoo_client() -> tuple[Any, str, int, str]:
    """Return (models_proxy, db, uid, api_key). Raises on failure."""
    if not _odoo_is_configured():
        raise RuntimeError("odoo_not_configured")

    cache_key = "client"
    if cache_key in _odoo_cache:
        return _odoo_cache[cache_key]

    url = app.config["ODOO_URL"]
    db = app.config["ODOO_DB"]
    user = app.config["ODOO_USERNAME"]
    key = app.config["ODOO_API_KEY"]

    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, key, {})
    if not uid:
        raise RuntimeError("odoo_auth_failed")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    _odoo_cache[cache_key] = (models, db, uid, key)
    return models, db, uid, key


def _coerce_m2o(m2o: Any) -> tuple[int | None, str]:
    """Odoo many2one suele venir como [id, 'Nombre']."""
    try:
        if isinstance(m2o, (list, tuple)) and len(m2o) >= 2:
            return int(m2o[0] or 0) or None, str(m2o[1] or "")
    except Exception:
        pass
    return None, ""


def _brand_from_company(company_id: Any, warehouse_id: Any = None, team_id: Any = None) -> str:
    """
    Decide la marca/tienda para la etiqueta.
    Prioridad:
      1) Config explícita: ESTILO_HOME_COMPANY_ID / ESTILO_HOME_COMPANY_NAME
      2) Heurística por nombre (reine / estilo home)
      3) Heurística por warehouse/team (si contienen 'estilo home')
    """
    cid, cname = _coerce_m2o(company_id)

    # Configurable por env (inyectado en config.py -> current_app.config)
    try:
        cfg_id = str(app.config.get("ESTILO_HOME_COMPANY_ID", "") or "").strip()
        if cfg_id:
            try:
                if cid is not None and cid == int(cfg_id):
                    return "ESTILO_HOME"
            except Exception:
                pass
        cfg_name = str(app.config.get("ESTILO_HOME_COMPANY_NAME", "") or "").strip().lower()
        if cfg_name and cname and cname.strip().lower() == cfg_name:
            return "ESTILO_HOME"
    except Exception:
        pass

    low = (cname or "").strip().lower()
    if "reine" in low or "estilo home" in low:
        return "ESTILO_HOME"

    # Fallback por warehouse/team
    _, wname = _coerce_m2o(warehouse_id)
    _, tname = _coerce_m2o(team_id)
    if "estilo home" in (wname or "").lower() or "estilo home" in (tname or "").lower():
        return "ESTILO_HOME"

    return "LUMINARAS"


def resolve_logo_path(brand: str | None) -> str:
    """Devuelve el path del logo a usar según marca."""
    b = (brand or "").strip().upper()
    if b == "ESTILO_HOME":
        p = str(app.config.get("LOGO_ESTILO_HOME_PATH", "") or "").strip()
        if p and os.path.exists(p):
            return p
    if b in {"MAYORISTAS_URUGUAY", "MAYORISTAS URUGUAY"}:
        p = str(app.config.get("LOGO_MAYORISTAS_URUGUAY_PATH", "") or "").strip()
        if p and os.path.exists(p):
            return p
    # default Iluminaras
    p = str(app.config.get("LOGO_LUMINARAS_PATH", "") or "").strip()
    if p and os.path.exists(p):
        return p
    # compat
    p = str(app.config.get("LOGO_PATH", "") or "").strip()
    return p


def _model_fields(model_name: str) -> set[str]:
    if model_name in _fields_cache:
        return _fields_cache[model_name]
    models, db, uid, key = _odoo_client()
    info = models.execute_kw(db, uid, key, model_name, "fields_get", [], {"attributes": ["type"]})
    fields = set(info.keys()) if isinstance(info, dict) else set()
    _fields_cache[model_name] = fields
    return fields



def _parse_mapping(expr: str) -> tuple[str, str]:
    """Returns (source, field). source in {'order','partner'}"""
    expr = (expr or "").strip()
    if not expr:
        return ("", "")
    if ":" in expr:
        src, fld = expr.split(":", 1)
        src = src.strip().lower()
        fld = fld.strip()
        if src in ("order", "partner", "picking") and fld:
            return (src, fld)
    # default to order
    return ("order", expr)



def _format_addr(p: dict[str, Any]) -> str:
    parts = [p.get("street"), p.get("street2"), p.get("city")]
    parts = [x for x in parts if x]
    tail = " ".join([x for x in [p.get("zip")] if x])
    if tail:
        parts.append(tail)
    return ", ".join(parts)



def _csv_fields(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]





def _shipcode_mapping(order_fields: set[str], picking_fields: set[str]) -> tuple[str, str]:
    """Return (source, field) for shipping code.
    source in {'order','picking'}.
    """
    expr = (app.config.get("ODOO_SHIPPING_CODE_FIELD") or "").strip()
    if expr:
        src, fld = _parse_mapping(expr)
        if src == "order" and fld in order_fields:
            return (src, fld)
        if src == "picking" and fld in picking_fields:
            return (src, fld)

    # Auto-detect common custom fields on sale.order
    for cand in (
        "x_studio_codigo_de_envio",
        "x_studio_codigo_envio",
        "x_codigo_envio",
        "x_shipping_code",
        "x_studio_codigo_de_envio_ml",
        "x_studio_cod_envio",
    ):
        if cand in order_fields:
            return ("order", cand)

    # Prefer picking tracking ref
    for cand in ("carrier_tracking_ref", "tracking_reference"):
        if cand in picking_fields:
            return ("picking", cand)

    if "name" in picking_fields:
        return ("picking", "name")
    return ("", "")




def _odoo_pickings_shipcode_map(order_ids: list[int], order_names: list[str], picking_field: str) -> dict[int, str]:
    """Map sale.order id -> shipping code from stock.picking (best-effort)."""
    if not order_ids:
        return {}
    models, db, uid, key = _odoo_client()
    picking_fields = _model_fields("stock.picking")
    if picking_field not in picking_fields:
        return {}

    name_to_id = {n: oid for oid, n in zip(order_ids, order_names) if n}

    fields = ["id", picking_field]
    domain = None
    if "sale_id" in picking_fields:
        fields.append("sale_id")
        domain = [("sale_id", "in", order_ids)]
    elif "origin" in picking_fields:
        fields.append("origin")
        domain = [("origin", "in", [n for n in order_names if n])]
    else:
        return {}

    # Add dates for ranking if present
    for f in ("date_done", "scheduled_date", "create_date"):
        if f in picking_fields:
            fields.append(f)

    rows = models.execute_kw(
        db, uid, key,
        "stock.picking", "search_read",
        [domain],
        {"fields": list(dict.fromkeys(fields)), "limit": 500, "order": "id desc"}
    )

    def rank_key(r: dict) -> str:
        for f in ("date_done", "scheduled_date", "create_date"):
            v = r.get(f)
            if v:
                return str(v)
        return ""

    best: dict[int, tuple[str, str]] = {}
    if not isinstance(rows, list):
        return {}

    for r in rows:
        val = _clean_plain_text(r.get(picking_field) or "")
        if not val:
            continue

        oid = None
        if r.get("sale_id"):
            try:
                oid = int(r["sale_id"][0])
            except Exception:
                oid = None
        elif r.get("origin"):
            oid = name_to_id.get(str(r.get("origin")))

        if not oid:
            continue

        rk = rank_key(r) + f"#{r.get('id','')}"
        if (oid not in best) or (rk > best[oid][0]):
            best[oid] = (rk, val)

    return {oid: v for oid, (rk, v) in best.items()}



def _odoo_search_orders(q: str) -> list[dict[str, Any]]:
    models, db, uid, key = _odoo_client()

    order_fields = _model_fields("sale.order")
    partner_fields = _model_fields("res.partner")
    picking_fields = _model_fields("stock.picking")

    ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)

    # Conservative base domain (fields exist in standard Odoo)
    base_terms = [
        ("name", "ilike", q),
        ("client_order_ref", "ilike", q),
        ("partner_id.name", "ilike", q),
        ("partner_id.phone", "ilike", q),
        ("partner_id.mobile", "ilike", q),
        ("partner_shipping_id.name", "ilike", q),
        ("partner_shipping_id.phone", "ilike", q),
        ("partner_shipping_id.mobile", "ilike", q),
    ]

    # Common integration fields (added only if they exist in this Odoo)
    if "x_studio_id_web_pedidos" in order_fields:
        base_terms.append(("x_studio_id_web_pedidos", "ilike", q))
    if "x_meli_cart" in order_fields:
        base_terms.append(("x_meli_cart", "ilike", q))
    if "x_studio_meli" in order_fields:
        base_terms.append(("x_studio_meli", "ilike", q))

    # Shipping code / tracking ref
    if ship_src == "order" and ship_fld in order_fields:
        base_terms.append((ship_fld, "ilike", q))
    if "picking_ids" in order_fields:
        if "carrier_tracking_ref" in picking_fields:
            base_terms.append(("picking_ids.carrier_tracking_ref", "ilike", q))
        if "tracking_reference" in picking_fields:
            base_terms.append(("picking_ids.tracking_reference", "ilike", q))
        if "name" in picking_fields:
            base_terms.append(("picking_ids.name", "ilike", q))
        if ship_src == "picking" and ship_fld in picking_fields:
            base_terms.append((f"picking_ids.{ship_fld}", "ilike", q))

    # Optional extra terms (safe-filtered by fields_get)
    extra_order = [f for f in _csv_fields(app.config.get("ODOO_ORDER_SEARCH_EXTRA_FIELDS", "")) if f in order_fields]
    extra_partner = [f for f in _csv_fields(app.config.get("ODOO_PARTNER_SEARCH_EXTRA_FIELDS", "")) if f in partner_fields]

    extra_terms: list[tuple[str, str, str]] = []
    for f in extra_order:
        extra_terms.append((f, "ilike", q))
    for f in extra_partner:
        # search on both billing and shipping partner
        extra_terms.append((f"partner_id.{f}", "ilike", q))
        extra_terms.append((f"partner_shipping_id.{f}", "ilike", q))

    terms = base_terms + extra_terms
    # OR all terms: prepend enough '|' operators
    domain: list[Any] = []
    if terms:
        domain = ["|"] * (len(terms) - 1)
        for t in terms:
            domain.append(t)

    fields = ["id", "name", "partner_id", "partner_shipping_id", "state", "date_order", "client_order_ref"]
    for f in ("x_studio_id_web_pedidos", "x_meli_cart", "x_studio_meli"):
        if f in order_fields:
            fields.append(f)

    if ship_src == "order" and ship_fld in order_fields:
        fields.append(ship_fld)
    fields = list(dict.fromkeys(fields))

    rows = models.execute_kw(
        db, uid, key,
        "sale.order", "search_read",
        [domain],
        {"fields": fields, "limit": int(app.config["ODOO_SEARCH_LIMIT"]), "order": "id desc"}
    )
    return rows if isinstance(rows, list) else []



def _odoo_order_detail(order_id: int) -> dict[str, Any]:
    models, db, uid, key = _odoo_client()

    # sale.order fields
    order_fields = _model_fields("sale.order")
    picking_fields = _model_fields("stock.picking")
    ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)
    want = ["id", "name", "company_id", "warehouse_id", "team_id", "partner_id", "partner_shipping_id", "note", "carrier_id", "client_order_ref"]
    # Solo pedir campos que existen en este Odoo
    want = [f for f in want if (f in ("id","name") or f in order_fields)]
    # Common integration fields (if present)
    for f in ("x_studio_id_web_pedidos", "x_meli_cart", "x_studio_meli"):
        if f in order_fields:
            want.append(f)

    if ship_src == "order" and ship_fld in order_fields:
        want.append(ship_fld)
    # optional mapping fields
    z_src, z_fld = _parse_mapping(app.config.get("ODOO_ZONE_FIELD", ""))
    e_src, e_fld = _parse_mapping(app.config.get("ODOO_ENVIO_FIELD", ""))
    if z_src == "order" and z_fld in order_fields:
        want.append(z_fld)
    if e_src == "order" and e_fld in order_fields:
        want.append(e_fld)

    orders = models.execute_kw(db, uid, key, "sale.order", "read", [[order_id]], {"fields": list(dict.fromkeys(want))})
    if not orders:
        raise KeyError("not_found")
    o = orders[0]

    company_id = o.get("company_id")
    warehouse_id = o.get("warehouse_id")
    team_id = o.get("team_id")
    brand = _brand_from_company(company_id, warehouse_id=warehouse_id, team_id=team_id)

    ship_id = (o.get("partner_shipping_id") or [None])[0]
    partner_id = (o.get("partner_id") or [None])[0]
    pid = ship_id or partner_id

    partner: dict[str, Any] = {}
    if pid:
        partner_fields = _model_fields("res.partner")
        p_want = ["name", "street", "street2", "city", "zip", "phone", "mobile"]
        if z_src == "partner" and z_fld in partner_fields:
            p_want.append(z_fld)
        if e_src == "partner" and e_fld in partner_fields:
            p_want.append(e_fld)
        ps = models.execute_kw(db, uid, key, "res.partner", "read", [[pid]], {"fields": list(dict.fromkeys(p_want))})
        partner = ps[0] if ps else {}

    telefono = partner.get("mobile") or partner.get("phone") or ""
    direccion = _format_addr(partner)

    zona = ""
    envio = ""
    if z_src == "order" and z_fld and z_fld in o:
        zona = o.get(z_fld) or ""
    elif z_src == "partner" and z_fld and z_fld in partner:
        zona = partner.get(z_fld) or ""

    if e_src == "order" and e_fld and e_fld in o:
        envio = o.get(e_fld) or ""
    elif e_src == "partner" and e_fld and e_fld in partner:
        envio = partner.get(e_fld) or ""
    else:
        # fallback to carrier
        envio = (o.get("carrier_id") or [None, ""])[1] if o.get("carrier_id") else ""

    # Odoo notes are often HTML (e.g. <p>...</p>)
    obs = _clean_html_text(o.get("note") or "")

    codigo_envio = ""
    if ship_src == "order" and ship_fld and ship_fld in o:
        codigo_envio = _clean_plain_text(o.get(ship_fld) or "")

    if not codigo_envio:
        # Fallback to pickings tracking ref
        pick_field = ship_fld if (ship_src == "picking" and ship_fld) else (
            "carrier_tracking_ref" if "carrier_tracking_ref" in picking_fields else (
                "tracking_reference" if "tracking_reference" in picking_fields else (
                    "name" if "name" in picking_fields else ""
                )
            )
        )
        if pick_field:
            try:
                codigo_envio = _odoo_pickings_shipcode_map([order_id], [o.get('name','') or ''], pick_field).get(order_id, "")
            except Exception:
                codigo_envio = ""

    return {
        "pedido": o.get("name", ""),
        "company_id": company_id,
        "brand": brand,
        "nombre": partner.get("name", ""),
        "direccion": direccion,
        "telefono": telefono,
        "observaciones": obs,
        "envio": envio,
        "zona": zona,
        "client_order_ref": _clean_plain_text(o.get("client_order_ref") or ""),
        "id_web": _digits_only(o.get("x_studio_id_web_pedidos") or ""),
        "meli_cart": _digits_only(o.get("x_meli_cart") or ""),
        "id_meli": _digits_only(o.get("x_studio_meli") or ""),
        "codigo_envio": _clean_plain_text(codigo_envio),
    }



def cleanup_old_pdfs() -> None:
    hours = float(app.config["KEEP_PDFS_HOURS"])
    cutoff = time.time() - hours * 3600.0
    for p in glob.glob(os.path.join(app.config["GENERATED_DIR"], "*.pdf")):
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
        except Exception:
            pass



def wrap_text(c: canvas.Canvas, text: str, max_width_pt: float, font_name: str, font_size: float) -> list[str]:
    c.setFont(font_name, font_size)
    words = (text or "").replace("\r", " ").split()
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = cur + " " + w
        if c.stringWidth(trial, font_name, font_size) <= max_width_pt:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines



def _generate_pdf_classic(data: LabelData) -> str:
    """Layout anterior (con labels) por compatibilidad."""
    cleanup_old_pdfs()

    w = mm(float(app.config["LABEL_WIDTH_MM"]))
    h = mm(float(app.config["LABEL_HEIGHT_MM"]))
    filename = f"etiqueta_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    out_path = os.path.join(app.config["GENERATED_DIR"], filename)

    c = canvas.Canvas(out_path, pagesize=(w, h))

    pad = mm(6)
    line_w = 0.6  # points
    gap = mm(6)

    # Banda inferior reservada para QR + logo + tracking (evita superposición)
    bottom_band_h = mm(34)
    content_bottom_y = pad + bottom_band_h

    # dashed top & bottom border like sample
    c.setLineWidth(line_w)
    c.setDash(3, 2)
    c.line(pad, h - pad, w - pad, h - pad)
    c.line(pad, pad, w - pad, pad)
    c.setDash()  # reset

    # layout columns
    inner_w = w - 2 * pad
    left_w = inner_w * 0.56
    right_w = inner_w - left_w - gap

    x0 = pad
    y_top = h - pad

    # fonts
    font_label = "Helvetica-Bold"
    font_value = "Helvetica"
    fs = 10.5
    fs_small = 9.0
    fs_tiny = 5.5  # N° de Pedido a < 1/2 tamaño

    def ellipsize_to_width(s: str, max_w: float, font_name: str, font_size: float) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if c.stringWidth(s, font_name, font_size) <= max_w:
            return s
        ell = "…"
        if c.stringWidth(ell, font_name, font_size) > max_w:
            return ""
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi) // 2
            cand = s[:mid].rstrip() + ell
            if c.stringWidth(cand, font_name, font_size) <= max_w:
                lo = mid + 1
            else:
                hi = mid
        cut = max(lo - 1, 0)
        return s[:cut].rstrip() + ell

    def wrap_ellipsis(text: str, max_w: float, font_name: str, font_size: float, max_lines: int) -> list[str]:
        base = wrap_text(c, (text or "").replace("\n", " ").replace("\r", " "), max_w, font_name, font_size)
        if not base:
            return [""]
        if len(base) <= max_lines:
            return [ellipsize_to_width(ln, max_w, font_name, font_size) for ln in base]
        keep = base[:max_lines]
        keep[-1] = ellipsize_to_width(keep[-1] + " …", max_w, font_name, font_size)
        return keep

    def draw_labeled_field(
        x: float,
        y: float,
        label: str,
        value: str,
        total_width: float,
        *,
        max_lines: int = 1,
        line_height: float = mm(9.5),
        value_fs: float = fs,
        label_fs: float = fs,
    ) -> float:
        """Dibuja un campo con label + líneas. Devuelve el nuevo Y (debajo del campo)."""
        c.setFont(font_label, label_fs)
        c.drawString(x, y, label)
        lw = c.stringWidth(label, font_label, label_fs)
        start_x = x + lw + mm(3)
        avail_w = (x + total_width) - start_x - mm(1)
        if avail_w < mm(8):
            avail_w = mm(8)

        lines = wrap_ellipsis(value, avail_w, font_value, value_fs, max_lines)

        c.setLineWidth(0.8)
        for i in range(max_lines):
            ly = y - i * line_height
            line_y = ly - mm(1.1)
            c.line(start_x, line_y, x + total_width, line_y)
            c.setFont(font_value, value_fs)
            txt = lines[i] if i < len(lines) else ""
            txt = ellipsize_to_width(txt, avail_w, font_value, value_fs)
            c.drawString(start_x + mm(1), ly, txt)

        return y - max_lines * line_height

    # Línea separadora (contenido vs banda inferior)
    c.setLineWidth(0.8)
    c.line(pad, content_bottom_y, w - pad, content_bottom_y)

    # ----------------------------
    # Columna izquierda (cliente)
    # ----------------------------
    cur_y = y_top - mm(12)

    cur_y = draw_labeled_field(x0, cur_y, "Nombre", data.nombre, left_w, max_lines=1, line_height=mm(10), value_fs=fs)
    cur_y -= mm(2)

    # Dirección: hasta 2 líneas (salto de línea implícito) + sin invadir la derecha
    cur_y = draw_labeled_field(x0, cur_y, "Dirección", data.direccion, left_w, max_lines=2, line_height=mm(9), value_fs=fs_small)
    cur_y -= mm(3)

    cur_y = draw_labeled_field(x0, cur_y, "Teléfono", data.telefono, left_w, max_lines=1, line_height=mm(10), value_fs=fs)
    cur_y -= mm(2)

    # N° de Pedido: reducido a menos de la mitad
    cur_y = draw_labeled_field(x0, cur_y, "N° de Pedido", data.pedido, left_w, max_lines=1, line_height=mm(7), value_fs=fs_tiny, label_fs=fs)

    # ----------------------------
    # Columna derecha (envío)
    # ----------------------------
    rx = x0 + left_w + gap
    ry = y_top - mm(12)

    # Envío: más espacio (2 líneas + ancho completo)
    ry = draw_labeled_field(rx, ry, "Envío", data.envio, right_w, max_lines=2, line_height=mm(9), value_fs=fs_small)
    ry -= mm(3)

    ry = draw_labeled_field(rx, ry, "Zona", data.zona, right_w, max_lines=1, line_height=mm(10), value_fs=fs)
    ry -= mm(3)

    ry = draw_labeled_field(rx, ry, "Cód. envío", data.codigo_envio, right_w, max_lines=1, line_height=mm(10), value_fs=fs)
    ry -= mm(4)

    # Observaciones (2 líneas para no invadir la banda inferior)
    c.setFont(font_label, fs)
    c.drawString(rx, ry, "Observaciones")
    ry -= mm(5)

    obs_lines_y = [ry - i * mm(10) for i in range(2)]
    c.setLineWidth(0.8)
    for ly in obs_lines_y:
        c.line(rx, ly, rx + right_w, ly)

    max_text_w = right_w - mm(2)
    wrapped = wrap_ellipsis(data.observaciones, max_text_w, font_value, fs_small, 2)
    c.setFont(font_value, fs_small)
    text_y = obs_lines_y[0] + mm(2.5)
    for i, line in enumerate(wrapped[:2]):
        c.drawString(rx + mm(1), text_y - i * mm(10), line)

    # ----------------------------
    # Banda inferior: QR + tracking + logo
    # ----------------------------
    band_y0 = pad
    band_y1 = content_bottom_y

    # QR del pedido (order_name / "S...") (más grande, con mayor corrección de error)
    try:
        qr_value = (data.pedido or "").strip()
        if qr_value:
            qr_size = mm(30)
            qx = pad + mm(4)
            qy = band_y0 + mm(4)

            qr = QrCodeWidget(qr_value)
            # Mejor tolerancia a impresión / baja luz
            try:
                qr.barLevel = "H"
                qr.barBorder = 6  # quiet zone más amplio
            except Exception:
                pass

            bounds = qr.getBounds()
            bw = bounds[2] - bounds[0]
            bh = bounds[3] - bounds[1]
            d = Drawing(qr_size, qr_size, transform=[qr_size / bw, 0, 0, qr_size / bh, 0, 0])
            d.add(qr)
            renderPDF.draw(d, c, qx, qy)

            # Texto de rastreo a la derecha del QR
            tx = qx + qr_size + mm(6)
            c.setFont(font_label, 10)
            c.drawString(tx, band_y1 - mm(10), "Escaneá para rastrear")
            if (data.tracking_code or "").strip():
                c.setFont(font_label, 11)
                c.drawString(tx, band_y1 - mm(20), f"TRK: {data.tracking_code.strip()}")
    except Exception:
        pass

    # Logo a la derecha, dentro de la banda inferior
    try:
        logo_path = (str(getattr(data, "logo_path", "") or "").strip() or resolve_logo_path(getattr(data, "brand", "") or ""))
        if logo_path and os.path.exists(logo_path):
            img = ImageReader(logo_path)
            box_w = mm(50)
            box_h = mm(18)
            lx = w - pad - box_w
            ly = band_y0 + (bottom_band_h - box_h) / 2.0
            c.drawImage(img, lx, ly, width=box_w, height=box_h, mask='auto', preserveAspectRatio=True, anchor='sw')
    except Exception:
        pass

    c.showPage()
    c.save()
    return out_path


def _generate_pdf_ra(data: LabelData) -> str:
    """Layout nuevo (formato RA / etiqueta sin nombres de campos).

    Objetivo principal: que nunca se superponga nada.
    """
    cleanup_old_pdfs()

    w = mm(float(app.config["LABEL_WIDTH_MM"]))
    h = mm(float(app.config["LABEL_HEIGHT_MM"]))
    filename = f"etiqueta_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
    out_path = os.path.join(app.config["GENERATED_DIR"], filename)

    c = canvas.Canvas(out_path, pagesize=(w, h))

    border = mm(2)
    pad = mm(6)

    x_l = border + pad
    x_r = w - border - pad
    inner_w = x_r - x_l

    # Helpers -------------------------------------------------
    def ellipsize_to_width(s: str, max_w: float, font_name: str, font_size: float) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if c.stringWidth(s, font_name, font_size) <= max_w:
            return s
        ell = "…"
        if c.stringWidth(ell, font_name, font_size) > max_w:
            return ""
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi) // 2
            cand = s[:mid].rstrip() + ell
            if c.stringWidth(cand, font_name, font_size) <= max_w:
                lo = mid + 1
            else:
                hi = mid
        cut = max(lo - 1, 0)
        return s[:cut].rstrip() + ell

    def wrap_ellipsis(text: str, max_w: float, font_name: str, font_size: float, max_lines: int) -> list[str]:
        base = wrap_text(c, (text or "").replace('\n', ' ').replace('\r', ' '), max_w, font_name, font_size)
        if not base:
            return []
        if len(base) <= max_lines:
            return [ellipsize_to_width(ln, max_w, font_name, font_size) for ln in base]
        keep = base[:max_lines]
        keep[-1] = ellipsize_to_width(keep[-1] + " …", max_w, font_name, font_size)
        return keep

    # Border --------------------------------------------------
    c.setLineWidth(1.2)
    c.rect(border, border, w - 2 * border, h - 2 * border)

    # Layout guides ------------------------------------------
    header_h = mm(20)
    name_h = mm(18)
    # Banda inferior: damos más altura para agrandar el QR y hacerlo más escaneable.
    # El cuerpo ajusta dinámicamente (wrap/ellipsis y reducción de fuente) para que no haya solapes.
    bottom_band_h = mm(44)

    y_header_line = h - border - header_h
    y_name_line = y_header_line - name_h
    y_sep = border + bottom_band_h

    # Separator lines
    c.setLineWidth(0.9)
    c.line(border, y_header_line, w - border, y_header_line)
    c.line(border, y_name_line, w - border, y_name_line)
    c.line(border, y_sep, w - border, y_sep)

    # Header: logo left (PNG) + envio right ------------------
    try:
        logo_path = (str(getattr(data, "logo_path", "") or "").strip() or resolve_logo_path(getattr(data, "brand", "") or ""))
        if logo_path and os.path.exists(logo_path):
            img = ImageReader(logo_path)
            box_w = mm(85)
            box_h = mm(16)
            lx = x_l
            ly = y_header_line + (header_h - box_h) / 2.0
            c.drawImage(img, lx, ly, width=box_w, height=box_h, mask='auto', preserveAspectRatio=True, anchor='sw')
    except Exception:
        pass

    envio_txt = (data.envio or '').strip()
    c.setFont('Helvetica-Bold', 28)
    envio_txt = ellipsize_to_width(envio_txt, mm(35), 'Helvetica-Bold', 28)
    c.drawRightString(w - border - pad, y_header_line + mm(6), envio_txt)

    # Nombre --------------------------------------------------
    name_txt = (data.nombre or '').strip()
    c.setFont('Helvetica-Bold', 28)
    name_txt = ellipsize_to_width(name_txt, inner_w, 'Helvetica-Bold', 28)
    c.drawString(x_l, y_name_line + mm(6), name_txt)

    # Body columns -------------------------------------------
    gap = mm(8)
    left_w = inner_w * 0.64
    right_w = inner_w - left_w - gap
    rx = x_l + left_w + gap

    # Cuerpo: mantener siempre por arriba del separador
    body_min_y = y_sep + mm(3.0)

    # ID Web (debajo de la línea del nombre)
    id_web_txt = (data.id_web or data.pedido or '').strip()
    id_fs = 14
    c.setFont('Helvetica', id_fs)
    id_web_txt = ellipsize_to_width(id_web_txt, left_w, 'Helvetica', id_fs)
    y_id = y_name_line - mm(5.5)
    c.drawString(x_l, y_id, id_web_txt)

    # Dirección + teléfono (ajusta si no entra)
    addr_txt = (data.direccion or '').strip()
    phone_txt = (data.telefono or '').strip()

    addr_fs = 17
    phone_fs = 18
    line_h = mm(5.3)
    addr_max_lines = 2

    # Intentos de encaje vertical (sin invadir banda inferior)
    y_addr1 = y_id - mm(4.2)
    for _ in range(4):
        addr_lines = wrap_ellipsis(addr_txt, left_w, 'Helvetica', addr_fs, addr_max_lines)
        y_phone = y_addr1 - (len(addr_lines) * line_h) - mm(1.2)
        if y_phone >= body_min_y:
            break
        if addr_max_lines > 1:
            addr_max_lines = 1
            continue
        if addr_fs > 15:
            addr_fs = 15
            line_h = mm(4.8)
            phone_fs = 16
            continue
        y_addr1 = y_id - mm(3.6)
        break

    # Dibujar dirección
    if addr_txt:
        c.setFont('Helvetica', addr_fs)
        for i, ln in enumerate(addr_lines[:addr_max_lines]):
            c.drawString(x_l, y_addr1 - i * line_h, ln)

    # Dibujar teléfono
    if phone_txt:
        c.setFont('Helvetica', phone_fs)
        phone_txt = ellipsize_to_width(phone_txt, left_w, 'Helvetica', phone_fs)
        y_phone = y_addr1 - (len(addr_lines) * line_h) - mm(1.2)
        if y_phone < body_min_y:
            y_phone = body_min_y
        c.drawString(x_l, y_phone, phone_txt)

    # Zona (derecha, negrita) --------------------------------
    zona_txt = (data.zona or '').strip()
    if zona_txt:
        zona_fs = 24
        c.setFont('Helvetica-Bold', zona_fs)
        zona_txt = ellipsize_to_width(zona_txt, right_w, 'Helvetica-Bold', zona_fs)
        y_zona = y_addr1 - mm(0.8)
        if y_zona < body_min_y + mm(6):
            y_zona = body_min_y + mm(6)
        c.drawString(rx, y_zona, zona_txt)

    # Bottom: QR centrado (order_name "S...") + tracking centrado debajo ----------
    try:
        qr_value = (data.pedido or '').strip()
        if qr_value:
            # Tamaño objetivo del QR (más grande para impresión térmica).
            # Si por algún motivo no entra, luego se clampa por altura disponible.
            qr_size = mm(34)
            qr = QrCodeWidget(qr_value)
            try:
                qr.barLevel = 'H'
                # Quiet zone suficiente sin achicar demasiado los módulos.
                qr.barBorder = 4
            except Exception:
                pass
            bounds = qr.getBounds()
            bw = bounds[2] - bounds[0]
            bh = bounds[3] - bounds[1]
            d = Drawing(qr_size, qr_size, transform=[qr_size / bw, 0, 0, qr_size / bh, 0, 0])
            d.add(qr)

            # Texto (código) más pequeño para priorizar escaneabilidad del QR.
            # Además ajustamos el tamaño para que nunca se corte.
            code_fs = 10
            code_y = border + mm(3.0)

            # Posición base del QR (encima del código)
            qr_y = code_y + mm(6.5)

            max_qr_y = y_sep - mm(2.5) - qr_size
            if qr_y > max_qr_y:
                qr_y = max_qr_y
            # Evitar que el QR se acerque demasiado al texto inferior
            min_qr_y = code_y + mm(5.2)
            if qr_y < min_qr_y:
                qr_y = min_qr_y

            # Log para verificar que se está usando este layout (útil para depuración)
            try:
                app_log.info("label_ra_layout v2 qr_size_mm=34 code_base_fs=10")
            except Exception:
                pass

            qr_x = (w - qr_size) / 2.0
            renderPDF.draw(d, c, qr_x, qr_y)

            trk = (data.tracking_code or '').strip()
            if trk:
                # Fit-to-width del código de tracking (sin superposición/corte)
                fs_try = code_fs
                while fs_try > 8 and c.stringWidth(trk, 'Helvetica-Bold', fs_try) > inner_w:
                    fs_try -= 1
                c.setFont('Helvetica-Bold', fs_try)
                trk2 = ellipsize_to_width(trk, inner_w, 'Helvetica-Bold', fs_try)
                c.drawCentredString(w / 2.0, code_y, trk2)
    except Exception:
        pass

    c.showPage()
    c.save()
    return out_path


def generate_pdf(data: LabelData) -> str:
    """Genera el PDF de la etiqueta.

    Por defecto se usa el layout nuevo (RA). Para volver al anterior:
      LABEL_STYLE=classic
    """
    style = (os.environ.get("LABEL_STYLE", "ra") or "ra").strip().lower()
    if style in ("classic", "legacy", "old"):
        return _generate_pdf_classic(data)
    return _generate_pdf_ra(data)
