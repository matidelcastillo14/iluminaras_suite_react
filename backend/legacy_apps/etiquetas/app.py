from __future__ import annotations

import os
import uuid
import time
import glob
import re
import html as _html
import xmlrpc.client
import logging
import json
import pathlib
from logging.handlers import TimedRotatingFileHandler
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for, g
from werkzeug.utils import secure_filename
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from jinja2 import Environment, StrictUndefined
from app.services import cfe_legacy_engine


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


def create_app() -> Flask:
    # Optional .env support (won't override real environment variables)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass

    app = Flask(__name__)

    def _env_or_static(env_name: str, *static_filenames: str) -> str:
        """Return env path if provided, else first existing static file (case-safe)."""
        envp = (os.environ.get(env_name) or "").strip()
        if envp:
            return envp
        for fn in static_filenames:
            cand = os.path.join(app.root_path, "static", fn)
            if os.path.exists(cand):
                return cand
        if static_filenames:
            return os.path.join(app.root_path, "static", static_filenames[0])
        return ""

    # --- Config ---
    app.config["LABEL_WIDTH_MM"] = _env_float("LABEL_WIDTH_MM", 150.0)
    app.config["LABEL_HEIGHT_MM"] = _env_float("LABEL_HEIGHT_MM", 100.0)
    app.config["GENERATED_DIR"] = os.path.join(app.root_path, "generated")
    # Logos (compatible con Iluminaras Suite)
    app.config["LOGO_LUMINARAS_PATH"] = _env_or_static("LOGO_LUMINARAS_PATH", "logo.png")
    app.config["LOGO_ESTILO_HOME_PATH"] = _env_or_static("LOGO_ESTILO_HOME_PATH", "logo_estilo_home.png", "logo_estilo_home.PNG")
    # Backwards compatible
    app.config["LOGO_PATH"] = os.environ.get("LOGO_PATH", app.config["LOGO_LUMINARAS_PATH"])

    # Template editable (JSON)
    app.config["LABEL_TEMPLATE_PATH"] = os.environ.get(
        "LABEL_TEMPLATE_PATH",
        os.path.join(app.root_path, "label_template.json"),
    )
    app.config["UPLOADS_DIR"] = os.environ.get(
        "LABEL_UPLOADS_DIR",
        os.path.join(app.root_path, "static", "uploads"),
    )
    app.config["OPEN_PDF"] = os.environ.get("OPEN_PDF", "0") == "1"   # only meaningful when running locally
    app.config["KEEP_PDFS_HOURS"] = _env_float("KEEP_PDFS_HOURS", 1024.0)

    # --- Odoo lookup (optional) ---
    app.config["ENABLE_ODOO_LOOKUP"] = os.environ.get("ENABLE_ODOO_LOOKUP", "1") == "1"
    app.config["ODOO_URL"] = (os.environ.get("ODOO_URL") or "").rstrip("/")
    app.config["ODOO_DB"] = os.environ.get("ODOO_DB") or ""
    # Backwards-compatible naming (the project uses ODOO_USERNAME in .env)
    app.config["ODOO_USERNAME"] = os.environ.get("ODOO_USERNAME") or os.environ.get("ODOO_USER") or ""
    app.config["ODOO_API_KEY"] = os.environ.get("ODOO_API_KEY") or os.environ.get("ODOO_PASSWORD") or ""
    app.config["ODOO_SEARCH_LIMIT"] = int(os.environ.get("ODOO_SEARCH_LIMIT", "20"))

    # Optional mapping for zona/envio from Odoo.
    app.config["ODOO_ZONE_FIELD"] = os.environ.get("ODOO_ZONE_FIELD", "").strip()
    app.config["ODOO_ENVIO_FIELD"] = os.environ.get("ODOO_ENVIO_FIELD", "").strip()

    # Shipping code / tracking reference (configurable)
    app.config["ODOO_SHIPPING_CODE_FIELD"] = os.environ.get("ODOO_SHIPPING_CODE_FIELD", "").strip()

    # Extra fields to include in the search domain (comma-separated). Use with care.
    app.config["ODOO_ORDER_SEARCH_EXTRA_FIELDS"] = os.environ.get("ODOO_ORDER_SEARCH_EXTRA_FIELDS", "").strip()
    app.config["ODOO_PARTNER_SEARCH_EXTRA_FIELDS"] = os.environ.get("ODOO_PARTNER_SEARCH_EXTRA_FIELDS", "").strip()

    os.makedirs(app.config["GENERATED_DIR"], exist_ok=True)
    os.makedirs(app.config["UPLOADS_DIR"], exist_ok=True)

    # --- Odoo helpers ---
    _odoo_cache: dict[str, Any] = {}
    _fields_cache: dict[str, set[str]] = {}

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
        """Return (source, field) for shipping code. source in {'order','picking'}."""
        expr = (app.config.get("ODOO_SHIPPING_CODE_FIELD") or "").strip()
        if expr:
            src, fld = _parse_mapping(expr)
            if src == "order" and fld in order_fields:
                return (src, fld)
            if src == "picking" and fld in picking_fields:
                return (src, fld)

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

        if "x_studio_id_web_pedidos" in order_fields:
            base_terms.append(("x_studio_id_web_pedidos", "ilike", q))
        if "x_meli_cart" in order_fields:
            base_terms.append(("x_meli_cart", "ilike", q))
        if "x_studio_meli" in order_fields:
            base_terms.append(("x_studio_meli", "ilike", q))

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

        extra_order = [f for f in _csv_fields(app.config.get("ODOO_ORDER_SEARCH_EXTRA_FIELDS", "")) if f in order_fields]
        extra_partner = [f for f in _csv_fields(app.config.get("ODOO_PARTNER_SEARCH_EXTRA_FIELDS", "")) if f in partner_fields]

        extra_terms: list[tuple[str, str, str]] = []
        for f in extra_order:
            extra_terms.append((f, "ilike", q))
        for f in extra_partner:
            extra_terms.append((f"partner_id.{f}", "ilike", q))
            extra_terms.append((f"partner_shipping_id.{f}", "ilike", q))

        terms = base_terms + extra_terms
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

        order_fields = _model_fields("sale.order")
        picking_fields = _model_fields("stock.picking")
        ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)

        want = ["id", "name", "partner_id", "partner_shipping_id", "note", "carrier_id", "client_order_ref"]
        for f in ("x_studio_id_web_pedidos", "x_meli_cart", "x_studio_meli"):
            if f in order_fields:
                want.append(f)

        if ship_src == "order" and ship_fld in order_fields:
            want.append(ship_fld)

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
            envio = (o.get("carrier_id") or [None, ""])[1] if o.get("carrier_id") else ""

        obs = _clean_html_text(o.get("note") or "")

        codigo_envio = ""
        if ship_src == "order" and ship_fld and ship_fld in o:
            codigo_envio = _clean_plain_text(o.get(ship_fld) or "")

        if not codigo_envio:
            pick_field = ship_fld if (ship_src == "picking" and ship_fld) else (
                "carrier_tracking_ref" if "carrier_tracking_ref" in picking_fields else (
                    "tracking_reference" if "tracking_reference" in picking_fields else (
                        "name" if "name" in picking_fields else ""
                    )
                )
            )
            if pick_field:
                try:
                    codigo_envio = _odoo_pickings_shipcode_map([order_id], [o.get("name", "") or ""], pick_field).get(order_id, "")
                except Exception:
                    codigo_envio = ""

        return {
            "pedido": o.get("name", ""),
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
        for w_ in words[1:]:
            trial = cur + " " + w_
            if c.stringWidth(trial, font_name, font_size) <= max_width_pt:
                cur = trial
            else:
                lines.append(cur)
                cur = w_
        lines.append(cur)
        return lines

    # -------------------------
    # Template editable (JSON)
    # -------------------------
    _jinja = Environment(undefined=StrictUndefined, autoescape=False)

    def _brace_to_jinja(s: str) -> str:
        """Convierte placeholders {campo} -> {{ campo }} para compatibilidad."""
        if not s:
            return ""
        # evita convertir dobles llaves ya existentes
        def repl(m: re.Match[str]) -> str:
            key = m.group(1).strip()
            if not key:
                return m.group(0)
            return "{{ " + key + " }}"
        return re.sub(r"\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}", repl, s)

    def _render_value(template_str: str, ctx: dict[str, Any]) -> str:
        try:
            tpl = _jinja.from_string(_brace_to_jinja(template_str or ""))
            return tpl.render(**ctx)
        except Exception:
            return str(template_str or "")

    def _ensure_dirs() -> None:
        os.makedirs(app.config["GENERATED_DIR"], exist_ok=True)
        os.makedirs(app.config["UPLOADS_DIR"], exist_ok=True)

    def _default_template() -> dict[str, Any]:
        """Template base similar al layout RA, con líneas/editables y logo dinámico."""
        return {
            "page": {
                "width_mm": float(app.config["LABEL_WIDTH_MM"]),
                "height_mm": float(app.config["LABEL_HEIGHT_MM"]),
            },
            "elements": [
                # Borde exterior
                {"id": "border", "type": "rect", "x_mm": 2, "y_mm": 2, "w_mm": 146, "h_mm": 96, "stroke": 1.2},

                # Líneas guía (header / nombre / separador inferior)
                {"id": "line_header", "type": "line", "x1_mm": 2, "y1_mm": 22, "x2_mm": 148, "y2_mm": 22, "stroke": 0.9},
                {"id": "line_name", "type": "line", "x1_mm": 2, "y1_mm": 40, "x2_mm": 148, "y2_mm": 40, "stroke": 0.9},
                {"id": "line_bottom", "type": "line", "x1_mm": 2, "y1_mm": 56, "x2_mm": 148, "y2_mm": 56, "stroke": 0.9},

                # Logo dinámico: por defecto auto según pedido
                {"id": "logo", "type": "image", "x_mm": 8, "y_mm": 6, "w_mm": 85, "h_mm": 16, "src": "logo:auto", "fit": "contain"},

                # Envío (arriba derecha)
                {"id": "envio", "type": "text", "x_mm": 95, "y_mm": 7, "w_mm": 50, "h_mm": 14, "value": "{envio}", "font": "Helvetica", "size": 28, "bold": True, "align": "right", "wrap": False, "autofit": True},

                # Nombre
                {"id": "nombre", "type": "text", "x_mm": 8, "y_mm": 28, "w_mm": 140, "h_mm": 10, "value": "{nombre}", "font": "Helvetica", "size": 20, "bold": True, "align": "left", "wrap": False, "autofit": True},

                # ID web / pedido
                {"id": "id_web", "type": "text", "x_mm": 8, "y_mm": 44, "w_mm": 90, "h_mm": 6, "value": "{id_web}", "font": "Helvetica", "size": 12, "bold": False, "align": "left", "wrap": False, "autofit": True},

                # Dirección
                {"id": "direccion", "type": "text", "x_mm": 8, "y_mm": 52, "w_mm": 92, "h_mm": 16, "value": "{direccion}", "font": "Helvetica", "size": 13, "bold": False, "align": "left", "wrap": True, "autofit": True},

                # Teléfono
                {"id": "telefono", "type": "text", "x_mm": 8, "y_mm": 70, "w_mm": 92, "h_mm": 6, "value": "{telefono}", "font": "Helvetica", "size": 13, "bold": False, "align": "left", "wrap": False, "autofit": True},

                # Zona (columna derecha)
                {"id": "zona", "type": "text", "x_mm": 102, "y_mm": 52, "w_mm": 46, "h_mm": 8, "value": "{zona}", "font": "Helvetica", "size": 15, "bold": True, "align": "right", "wrap": False, "autofit": True},

                # QR (centrado abajo)
                {"id": "qr", "type": "qr", "x_mm": 58, "y_mm": 60, "size_mm": 34, "value": "{tracking_url}"},
                {"id": "tracking", "type": "text", "x_mm": 8, "y_mm": 92, "w_mm": 140, "h_mm": 6, "value": "{tracking_code}", "font": "Helvetica", "size": 10, "bold": True, "align": "center", "wrap": False, "autofit": True},
            ],
        }

    def _read_template() -> dict[str, Any]:
        p = str(app.config.get("LABEL_TEMPLATE_PATH") or "").strip()
        try:
            if p and os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict) and obj.get("elements"):
                    return obj
        except Exception:
            pass
        return _default_template()

    def _write_template(obj: dict[str, Any]) -> None:
        p = str(app.config.get("LABEL_TEMPLATE_PATH") or "").strip()
        if not p:
            raise RuntimeError("template_path_missing")
        pathlib.Path(os.path.dirname(p) or ".").mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

        # Cache: evita pegarle a Odoo varias veces por la misma orden
    _odoo_company_cache: dict[str, str] = {}

    def _odoo_company_name_for_order(order_name: str) -> str:
        """Devuelve el nombre de empresa (company_id[1]) de sale.order por name exacto. Cacheado."""
        key = (order_name or "").strip()
        if not key:
            return ""
        if key in _odoo_company_cache:
            return _odoo_company_cache[key]

        try:
            models, db, uid, api_key = _odoo_client()
            ids = models.execute_kw(
                db, uid, api_key,
                "sale.order", "search",
                [[("name", "=", key)]],
                {"limit": 1}
            )
            if ids:
                recs = models.execute_kw(
                    db, uid, api_key,
                    "sale.order", "read",
                    [ids],
                    {"fields": ["company_id"]}
                )
                if recs and recs[0].get("company_id"):
                    cid = recs[0]["company_id"]
                    cname = cid[1] if isinstance(cid, list) and len(cid) >= 2 else ""
                    cname = str(cname or "").strip()
                    _odoo_company_cache[key] = cname
                    return cname
        except Exception:
            pass

        _odoo_company_cache[key] = ""
        return ""


    def _brand_for_order(data: LabelData) -> str:
        
        """Brand para logo. Regla simple + configurable por regex."""
        s = " ".join([
            (data.pedido or ""),
            (data.id_web or ""),
            (data.envio or ""),
            (data.codigo_envio or ""),
            (data.nombre or ""),
            (data.observaciones or ""),
        ]).lower()
        # Overrides por env
        rx_eh = (os.environ.get("LABEL_ESTILO_HOME_REGEX") or "").strip()
        rx_lu = (os.environ.get("LABEL_LUMINARAS_REGEX") or "").strip()
        try:
            if rx_eh and re.search(rx_eh, s, re.I):
                return "ESTILO_HOME"
            if rx_lu and re.search(rx_lu, s, re.I):
                return "LUMINARAS"
        except Exception:
            pass

        # Heurística base
        if any(k in s for k in ("reine", "rainer", "estilo home", "estilohome", "estilo-home")):
            return "ESTILO_HOME"
        # Fallback por Empresa de Odoo (sale.order.company_id)
        try:
            cname = _odoo_company_name_for_order(data.pedido or "")
            cn = (cname or "").lower()
            if "reine" in cn or "estilo home" in cn:
                return "ESTILO_HOME"
        except Exception:
            pass
        return "LUMINARAS"

    def _logo_path_for_brand(brand: str) -> str:
        b = (brand or "").strip().upper()
        if b == "ESTILO_HOME":
            p = str(app.config.get("LOGO_ESTILO_HOME_PATH", "") or "").strip()
        else:
            p = str(app.config.get("LOGO_LUMINARAS_PATH", "") or "").strip()
        return p or str(app.config.get("LOGO_PATH", "") or "").strip()

    def _resolve_image_path(src: str, data: LabelData) -> str:
        src = (src or "").strip()
        if not src:
            return ""
        # logo:auto / logo:luminarias / logo:estilo_home
        if src.lower().startswith("logo:"):
            mode = src.split(":", 1)[1].strip().lower() if ":" in src else "auto"
            if mode in ("auto", ""):
                brand = _brand_for_order(data)
            elif mode in ("estilo", "estilo_home", "home", "reine", "rainer"):
                brand = "ESTILO_HOME"
            else:
                brand = "LUMINARAS"
            return _logo_path_for_brand(brand)

        # upload:filename.png
        if src.lower().startswith("upload:"):
            fn = src.split(":", 1)[1].strip()
            fn = secure_filename(fn)
            return os.path.join(app.config["UPLOADS_DIR"], fn)

        # ruta absoluta o relativa al root_path
        if os.path.isabs(src) and os.path.exists(src):
            return src
        cand = os.path.join(app.root_path, src.lstrip("/"))
        if os.path.exists(cand):
            return cand
        return ""

    def _draw_text_box(c: canvas.Canvas, page_w_pt: float, page_h_pt: float, el: dict[str, Any], ctx: dict[str, Any]) -> None:
        x_mm = float(el.get("x_mm") or 0)
        y_mm = float(el.get("y_mm") or 0)
        w_mm = float(el.get("w_mm") or 10)
        h_mm = float(el.get("h_mm") or 5)

        font_base = str(el.get("font") or "Helvetica")
        bold = bool(el.get("bold"))
        font = font_base
        if bold and not font_base.endswith("-Bold") and font_base in ("Helvetica", "Times-Roman", "Courier"):
            font = font_base + "-Bold"

        size = float(el.get("size") or 10)
        align = str(el.get("align") or "left").lower()
        wrap = bool(el.get("wrap"))
        autofit = bool(el.get("autofit"))

        raw = str(el.get("value") or "")
        txt = _render_value(raw, ctx)
        txt = (txt or "").strip()

        x = mm(x_mm)
        y_top = mm(y_mm)
        w = mm(w_mm)
        h = mm(h_mm)

        # reportlab y desde abajo
        y = page_h_pt - y_top - h

        def fits(fs: float) -> tuple[bool, list[str]]:
            if fs <= 1:
                return True, [""]
            c.setFont(font, fs)
            if not wrap:
                return (c.stringWidth(txt, font, fs) <= w), [txt]
            lines = []
            for paragraph in (txt.split("\n") if txt else [""]):
                lines.extend(wrap_text(c, paragraph, w, font, fs) or [""])
            # altura aproximada: 1.15 * fs por línea
            return (len(lines) * (fs * 1.15) <= h), lines

        lines: list[str]
        if autofit:
            fs_try = size
            ok, lines = fits(fs_try)
            while not ok and fs_try > 4:
                fs_try -= 0.5
                ok, lines = fits(fs_try)
            size = fs_try
        else:
            _, lines = fits(size)

        c.setFont(font, size)
        line_h = size * 1.15
        # baseline: dibujar desde arriba hacia abajo dentro de la caja
        cur_y = y + h - size  # primer baseline
        for ln in lines:
            if cur_y < y:
                break
            if align == "center":
                c.drawCentredString(x + w / 2.0, cur_y, ln)
            elif align == "right":
                c.drawRightString(x + w, cur_y, ln)
            else:
                c.drawString(x, cur_y, ln)
            cur_y -= line_h

    def _generate_pdf_template(data: LabelData) -> str:
        cleanup_old_pdfs()
        _ensure_dirs()

        tpl = _read_template()
        page = tpl.get("page") or {}
        w_mm = float(page.get("width_mm") or app.config["LABEL_WIDTH_MM"])
        h_mm = float(page.get("height_mm") or app.config["LABEL_HEIGHT_MM"])

        w = mm(w_mm)
        h = mm(h_mm)
        filename = f"etiqueta_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
        out_path = os.path.join(app.config["GENERATED_DIR"], filename)

        c = canvas.Canvas(out_path, pagesize=(w, h))

        # contexto para placeholders
        ctx: dict[str, Any] = {
            "nombre": data.nombre,
            "direccion": data.direccion,
            "telefono": data.telefono,
            "pedido": data.pedido,
            "id_web": data.id_web,
            "zona": data.zona,
            "envio": data.envio,
            "codigo_envio": data.codigo_envio,
            "observaciones": data.observaciones,
            "tracking_code": data.tracking_code,
            "tracking_url": data.tracking_url,
            "brand": _brand_for_order(data),
        }

        for el in (tpl.get("elements") or []):
            t = str(el.get("type") or "").lower()

            if t == "text":
                _draw_text_box(c, w, h, el, ctx)

            elif t == "line":
                x1 = mm(float(el.get("x1_mm") or 0))
                y1 = h - mm(float(el.get("y1_mm") or 0))
                x2 = mm(float(el.get("x2_mm") or 0))
                y2 = h - mm(float(el.get("y2_mm") or 0))
                sw = float(el.get("stroke") or 0.8)
                dash = el.get("dash")
                c.setLineWidth(sw)
                if isinstance(dash, list) and len(dash) >= 2:
                    try:
                        c.setDash(float(dash[0]), float(dash[1]))
                    except Exception:
                        c.setDash()
                else:
                    c.setDash()
                c.line(x1, y1, x2, y2)
                c.setDash()

            elif t == "rect":
                x = mm(float(el.get("x_mm") or 0))
                y_top = mm(float(el.get("y_mm") or 0))
                ww = mm(float(el.get("w_mm") or 0))
                hh = mm(float(el.get("h_mm") or 0))
                sw = float(el.get("stroke") or 0.8)
                fill = bool(el.get("fill"))
                c.setLineWidth(sw)
                # y desde abajo
                yy = h - y_top - hh
                c.rect(x, yy, ww, hh, stroke=1, fill=1 if fill else 0)

            elif t == "image":
                x = mm(float(el.get("x_mm") or 0))
                y_top = mm(float(el.get("y_mm") or 0))
                ww = mm(float(el.get("w_mm") or 0))
                hh = mm(float(el.get("h_mm") or 0))
                src_raw = str(el.get("src") or "")
                src_resolved = _render_value(src_raw, ctx)
                path = _resolve_image_path(src_resolved, data)
                if path and os.path.exists(path):
                    try:
                        img = ImageReader(path)
                        yy = h - y_top - hh
                        c.drawImage(img, x, yy, width=ww, height=hh, mask="auto", preserveAspectRatio=True, anchor="sw")
                    except Exception:
                        pass

            elif t == "qr":
                try:
                    x_mm0 = float(el.get("x_mm") or 0)
                    y_mm_top = float(el.get("y_mm") or 0)
                    size_mm = float(el.get("size_mm") or el.get("w_mm") or 24)
                    val = _render_value(str(el.get("value") or ""), ctx).strip()
                    if val:
                        qr = QrCodeWidget(val)
                        bounds = qr.getBounds()
                        bw = bounds[2] - bounds[0]
                        bh = bounds[3] - bounds[1]
                        d = Drawing(mm(size_mm), mm(size_mm), transform=[mm(size_mm) / bw, 0, 0, mm(size_mm) / bh, 0, 0])
                        d.add(qr)
                        x = mm(x_mm0)
                        yy = h - mm(y_mm_top) - mm(size_mm)
                        renderPDF.draw(d, c, x, yy)
                except Exception:
                    pass

        c.showPage()
        c.save()
        return out_path

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

        bottom_band_h = mm(34)
        content_bottom_y = pad + bottom_band_h

        c.setLineWidth(line_w)
        c.setDash(3, 2)
        c.line(pad, h - pad, w - pad, h - pad)
        c.line(pad, pad, w - pad, pad)
        c.setDash()

        inner_w = w - 2 * pad
        left_w = inner_w * 0.56
        right_w = inner_w - left_w - gap

        x0 = pad
        y_top = h - pad

        font_label = "Helvetica-Bold"
        font_value = "Helvetica"
        fs = 10.5
        fs_small = 9.0
        fs_tiny = 5.5

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

        c.setLineWidth(0.8)
        c.line(pad, content_bottom_y, w - pad, content_bottom_y)

        cur_y = y_top - mm(12)
        cur_y = draw_labeled_field(x0, cur_y, "Nombre", data.nombre, left_w, max_lines=1, line_height=mm(10), value_fs=fs)
        cur_y -= mm(2)
        cur_y = draw_labeled_field(x0, cur_y, "Dirección", data.direccion, left_w, max_lines=2, line_height=mm(9), value_fs=fs_small)
        cur_y -= mm(3)
        cur_y = draw_labeled_field(x0, cur_y, "Teléfono", data.telefono, left_w, max_lines=1, line_height=mm(10), value_fs=fs)
        cur_y -= mm(2)
        cur_y = draw_labeled_field(x0, cur_y, "N° de Pedido", data.pedido, left_w, max_lines=1, line_height=mm(7), value_fs=fs_tiny, label_fs=fs)

        rx = x0 + left_w + gap
        ry = y_top - mm(12)
        ry = draw_labeled_field(rx, ry, "Envío", data.envio, right_w, max_lines=2, line_height=mm(9), value_fs=fs_small)
        ry -= mm(3)
        ry = draw_labeled_field(rx, ry, "Zona", data.zona, right_w, max_lines=1, line_height=mm(10), value_fs=fs)
        ry -= mm(3)
        ry = draw_labeled_field(rx, ry, "Cód. envío", data.codigo_envio, right_w, max_lines=1, line_height=mm(10), value_fs=fs)
        ry -= mm(4)

        c.setFont(font_label, fs)
        c.drawString(rx, ry, "Observaciones")
        ry -= mm(5)

        obs_lines_y = [ry - i * mm(10) for i in range(2)]
        c.setLineWidth(0.8)
        for ly_ in obs_lines_y:
            c.line(rx, ly_, rx + right_w, ly_)

        max_text_w = right_w - mm(2)
        wrapped = wrap_ellipsis(data.observaciones, max_text_w, font_value, fs_small, 2)
        c.setFont(font_value, fs_small)
        text_y = obs_lines_y[0] + mm(2.5)
        for i, line in enumerate(wrapped[:2]):
            c.drawString(rx + mm(1), text_y - i * mm(10), line)

        band_y0 = pad
        band_y1 = content_bottom_y

        try:
            qr_value = (data.pedido or "").strip()
            if qr_value:
                qr_size = mm(30)
                qx = pad + mm(4)
                qy = band_y0 + mm(4)

                qr = QrCodeWidget(qr_value)
                try:
                    qr.barLevel = "H"
                    qr.barBorder = 6
                except Exception:
                    pass

                bounds = qr.getBounds()
                bw = bounds[2] - bounds[0]
                bh = bounds[3] - bounds[1]
                d = Drawing(qr_size, qr_size, transform=[qr_size / bw, 0, 0, qr_size / bh, 0, 0])
                d.add(qr)
                renderPDF.draw(d, c, qx, qy)

                tx = qx + qr_size + mm(6)
                c.setFont(font_label, 10)
                c.drawString(tx, band_y1 - mm(10), "Escaneá para rastrear")
                if (data.tracking_code or "").strip():
                    c.setFont(font_label, 11)
                    c.drawString(tx, band_y1 - mm(20), f"TRK: {data.tracking_code.strip()}")
        except Exception:
            pass

        try:
            if os.path.exists(app.config["LOGO_PATH"]):
                img = ImageReader(app.config["LOGO_PATH"])
                box_w = mm(50)
                box_h = mm(18)
                lx = w - pad - box_w
                ly = band_y0 + (bottom_band_h - box_h) / 2.0
                c.drawImage(img, lx, ly, width=box_w, height=box_h, mask="auto", preserveAspectRatio=True, anchor="sw")
        except Exception:
            pass

        c.showPage()
        c.save()
        return out_path

    # =========================
    # RA (CORREGIDO) - v3
    # =========================
    def _generate_pdf_ra(data: LabelData) -> str:
        """Layout RA / etiqueta sin nombres de campos.

        Correcciones:
        - Evita que la línea y_name_line "tache" dirección/zona (ancla el body a y_name_line).
        - Evita que el envío se corte arriba (baseline centrado en header).
        - Zona alineada como columna derecha real.
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
                return []
            if len(base) <= max_lines:
                return [ellipsize_to_width(ln, max_w, font_name, font_size) for ln in base]
            keep = base[:max_lines]
            keep[-1] = ellipsize_to_width(keep[-1] + " …", max_w, font_name, font_size)
            return keep

        # Border
        c.setLineWidth(1.2)
        c.rect(border, border, w - 2 * border, h - 2 * border)

        # Guides
        header_h = mm(20)
        name_h = mm(18)
        bottom_band_h = mm(44)

        y_header_line = h - border - header_h
        y_name_line = y_header_line - name_h
        y_sep = border + bottom_band_h

        # Separator lines
        c.setLineWidth(0.9)
        c.line(border, y_header_line, w - border, y_header_line)
        c.line(border, y_name_line, w - border, y_name_line)
        c.line(border, y_sep, w - border, y_sep)

        # Header: logo left
        try:
            logo_path = str(app.config.get("LOGO_PATH", "") or "").strip()
            if logo_path and os.path.exists(logo_path):
                img = ImageReader(logo_path)
                box_w = mm(85)
                box_h = mm(16)
                lx = x_l
                ly = y_header_line + (header_h - box_h) / 2.0
                c.drawImage(img, lx, ly, width=box_w, height=box_h, mask="auto", preserveAspectRatio=True, anchor="sw")
        except Exception:
            pass

        # Envío: arriba derecha, sin corte
        envio_txt = (data.envio or "").strip()
        if envio_txt:
            envio_font_size = 28
            c.setFont("Helvetica-Bold", envio_font_size)
            envio_txt = ellipsize_to_width(envio_txt, mm(55), "Helvetica-Bold", envio_font_size)

            header_center_y = y_header_line + (header_h / 2.0)
            envio_y = header_center_y - (envio_font_size * 0.35)  # baseline correction
            c.drawRightString(x_r, envio_y, envio_txt)

        # Nombre
        name_txt = (data.nombre or "").strip()
        name_y = y_name_line + mm(11)
        if name_txt:
            name_font_size = 20
            c.setFont("Helvetica-Bold", name_font_size)
            name_txt = ellipsize_to_width(name_txt, inner_w, "Helvetica-Bold", name_font_size)
            c.drawString(x_l, name_y, name_txt)

        # Body columns
        gap = mm(8)
        left_w = inner_w * 0.64
        right_w = inner_w - left_w - gap
        rx = x_l + left_w + gap

        body_min_y = y_sep + mm(3.0)

        # IMPORTANTE: anclar el body a la línea del nombre (no al baseline del nombre)
        y_body_top = y_name_line - mm(8.0)

        # ID Web / pedido
        id_web_txt = (data.id_web or data.pedido or "").strip()
        id_fs = 12
        y_id = y_body_top
        if id_web_txt:
            c.setFont("Helvetica", id_fs)
            id_web_txt = ellipsize_to_width(id_web_txt, left_w, "Helvetica", id_fs)
            c.drawString(x_l, y_id, id_web_txt)

        # Dirección + teléfono
        addr_txt = (data.direccion or "").strip()
        phone_txt = (data.telefono or "").strip()

        addr_fs = 13
        phone_fs = 13
        line_h = mm(5.0)
        addr_max_lines = 2

        y_addr1 = y_id - mm(7.5)

        for _ in range(6):
            addr_lines = wrap_ellipsis(addr_txt, left_w, "Helvetica", addr_fs, addr_max_lines) if addr_txt else []
            y_phone = y_addr1 - (len(addr_lines) * line_h) - mm(3.0)

            if (not phone_txt) or (y_phone >= body_min_y):
                break

            if addr_max_lines > 1:
                addr_max_lines = 1
                continue

            if addr_fs > 10:
                addr_fs -= 1
                phone_fs = max(phone_fs - 1, 10)
                line_h = max(mm(4.3), line_h - mm(0.2))
                continue

            break

        if addr_txt:
            c.setFont("Helvetica", addr_fs)
            for i, ln in enumerate(addr_lines[:addr_max_lines]):
                c.drawString(x_l, y_addr1 - i * line_h, ln)

        if phone_txt:
            c.setFont("Helvetica", phone_fs)
            phone_txt2 = ellipsize_to_width(phone_txt, left_w, "Helvetica", phone_fs)
            y_phone = y_addr1 - (len(addr_lines) * line_h) - mm(3.0)
            if y_phone < body_min_y:
                y_phone = body_min_y
            c.drawString(x_l, y_phone, phone_txt2)

        # Zona: columna derecha real (alineada a derecha)
        zona_txt = (data.zona or "").strip()
        if zona_txt:
            zona_fs = 15
            c.setFont("Helvetica-Bold", zona_fs)
            zona_txt2 = ellipsize_to_width(zona_txt, right_w, "Helvetica-Bold", zona_fs)
            y_zona = y_addr1  # alineada con la 1ra línea de dirección
            if y_zona < body_min_y + mm(10):
                y_zona = body_min_y + mm(10)
            c.drawRightString(x_r, y_zona, zona_txt2)

        # Bottom: QR + tracking
        try:
            qr_value = (data.pedido or "").strip()
            if qr_value:
                qr_size = mm(34)
                qr = QrCodeWidget(qr_value)
                try:
                    qr.barLevel = "H"
                    qr.barBorder = 4
                except Exception:
                    pass

                bounds = qr.getBounds()
                bw = bounds[2] - bounds[0]
                bh = bounds[3] - bounds[1]
                d = Drawing(qr_size, qr_size, transform=[qr_size / bw, 0, 0, qr_size / bh, 0, 0])
                d.add(qr)

                code_y = border + mm(4.5)
                qr_y = code_y + mm(7.0)

                max_qr_y = y_sep - mm(3.0) - qr_size
                if qr_y > max_qr_y:
                    qr_y = max_qr_y
                if qr_y < (code_y + mm(5.0)):
                    qr_y = code_y + mm(5.0)

                qr_x = (w - qr_size) / 2.0
                renderPDF.draw(d, c, qr_x, qr_y)

                trk = (data.tracking_code or "").strip()
                if trk:
                    fs_try = 10
                    while fs_try > 8 and c.stringWidth(trk, "Helvetica-Bold", fs_try) > inner_w:
                        fs_try -= 1
                    c.setFont("Helvetica-Bold", fs_try)
                    trk2 = ellipsize_to_width(trk, inner_w, "Helvetica-Bold", fs_try)
                    c.drawCentredString(w / 2.0, code_y, trk2)
        except Exception:
            pass

        c.showPage()
        c.save()
        return out_path

    def generate_pdf(data: LabelData) -> str:
        style = (os.environ.get("LABEL_STYLE", "template") or "template").strip().lower()
        if style in ("template", "designer", "json"):
            return _generate_pdf_template(data)
        if style in ("classic", "legacy", "old"):
            return _generate_pdf_classic(data)
        return _generate_pdf_ra(data)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            label_width_mm=app.config["LABEL_WIDTH_MM"],
            label_height_mm=app.config["LABEL_HEIGHT_MM"],
        )

    @app.get("/designer")
    def designer():
        _ensure_dirs()
        return render_template(
            "designer.html",
            label_width_mm=app.config["LABEL_WIDTH_MM"],
            label_height_mm=app.config["LABEL_HEIGHT_MM"],
        )

    @app.get("/api/template")
    def api_template_get():
        _ensure_dirs()
        return jsonify(_read_template())

    @app.post("/api/template")
    def api_template_set():
        _ensure_dirs()
        obj = request.get_json(silent=True) or {}
        if not isinstance(obj, dict):
            return jsonify({"error": "invalid_json"}), 400
        if not isinstance(obj.get("elements"), list):
            return jsonify({"error": "elements_required"}), 400
        # normalizar page
        page = obj.get("page") if isinstance(obj.get("page"), dict) else {}
        page.setdefault("width_mm", float(app.config["LABEL_WIDTH_MM"]))
        page.setdefault("height_mm", float(app.config["LABEL_HEIGHT_MM"]))
        obj["page"] = page
        _write_template(obj)
        return jsonify({"ok": True})

    @app.post("/api/template/reset")
    def api_template_reset():
        _ensure_dirs()
        _write_template(_default_template())
        return jsonify({"ok": True})

    @app.post("/api/assets/upload")
    def api_assets_upload():
        _ensure_dirs()
        if "file" not in request.files:
            return jsonify({"error": "file_required"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"error": "file_required"}), 400
        fn = secure_filename(f.filename)
        if not fn:
            return jsonify({"error": "invalid_filename"}), 400
        ext = (os.path.splitext(fn)[1] or "").lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            return jsonify({"error": "unsupported_type", "allowed": ["png", "jpg", "jpeg", "webp"]}), 400
        # evitar colisiones
        base, ext2 = os.path.splitext(fn)
        out_fn = fn
        out_path = os.path.join(app.config["UPLOADS_DIR"], out_fn)
        if os.path.exists(out_path):
            out_fn = f"{base}_{uuid.uuid4().hex[:6]}{ext2}"
            out_path = os.path.join(app.config["UPLOADS_DIR"], out_fn)

        f.save(out_path)
        return jsonify({
            "ok": True,
            "src": f"upload:{out_fn}",
            "url": url_for("static", filename=f"uploads/{out_fn}"),
        })

    @app.get("/api/logo_preview")
    def api_logo_preview():
        """Devuelve un logo (para previsualización en el diseñador)."""
        _ensure_dirs()
        brand = (request.args.get("brand") or "auto").strip()
        dummy = LabelData(pedido="", id_web="", envio=brand)
        # Si brand == auto, usar luminarias por defecto en preview
        if brand.lower() in ("auto", ""):
            p = _logo_path_for_brand("LUMINARAS")
        elif brand.lower() in ("estilo", "estilo_home", "home", "reine", "rainer"):
            p = _logo_path_for_brand("ESTILO_HOME")
        else:
            p = _logo_path_for_brand("LUMINARAS")
        if not p or not os.path.exists(p):
            abort(404)
        return send_file(p)

    @app.get("/api/orders/search")
    def api_orders_search():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify([])
        if not _odoo_is_configured():
            return jsonify({"error": "odoo_not_configured"}), 501

        try:
            rows = _odoo_search_orders(q)
        except Exception as ex:
            return jsonify({"error": "odoo_error", "detail": str(ex)}), 503

        order_fields = _model_fields("sale.order")
        picking_fields = _model_fields("stock.picking")
        ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)

        ship_map: dict[int, str] = {}
        try:
            pick_field = (
                ship_fld if (ship_src == "picking" and ship_fld and ship_fld in picking_fields) else
                ("carrier_tracking_ref" if "carrier_tracking_ref" in picking_fields else
                 ("tracking_reference" if "tracking_reference" in picking_fields else
                  ("name" if "name" in picking_fields else "")))
            )
            if pick_field:
                ids = [int(x.get("id")) for x in rows if x.get("id")]
                names = [str(x.get("name") or "") for x in rows if x.get("id")]
                ship_map = _odoo_pickings_shipcode_map(ids, names, pick_field)
        except Exception:
            ship_map = {}

        out: list[dict[str, Any]] = []
        for r in rows:
            oid = int(r.get("id") or 0)

            codigo_envio_raw = ""
            if ship_src == "order" and ship_fld:
                codigo_envio_raw = str(r.get(ship_fld) or "")
            codigo_envio_final = _clean_plain_text(codigo_envio_raw or ship_map.get(oid, "") or "")

            out.append({
                "id": r.get("id"),
                "pedido": r.get("name", ""),
                "cliente": (r.get("partner_id") or [None, ""])[1] if r.get("partner_id") else "",
                "estado": r.get("state", ""),
                "fecha": r.get("date_order", ""),
                "ref": _clean_plain_text(r.get("client_order_ref") or ""),
                "id_web": _digits_only(r.get("x_studio_id_web_pedidos") or ""),
                "meli_cart": _digits_only(r.get("x_meli_cart") or ""),
                "id_meli": _digits_only(r.get("x_studio_meli") or ""),
                "codigo_envio": codigo_envio_final,
            })
        return jsonify(out)

    @app.get("/api/orders/<int:order_id>")
    def api_order_detail(order_id: int):
        if not _odoo_is_configured():
            return jsonify({"error": "odoo_not_configured"}), 501
        try:
            d = _odoo_order_detail(order_id)
            return jsonify(d)
        except KeyError:
            return jsonify({"error": "not_found"}), 404
        except Exception as ex:
            return jsonify({"error": "odoo_error", "detail": str(ex)}), 503

    @app.post("/generate")
    def generate():
        """Genera el PDF de etiqueta y opcionalmente el CFE de la misma orden."""
        pedido = request.form.get("pedido", "")
        id_web = request.form.get("id_web", "")
        try:
            odoo_order_id = int(request.form.get("odoo_order_id") or 0)
        except Exception:
            odoo_order_id = 0

        generate_cfe = (request.form.get("generate_cfe") or "").strip().lower() in {"1", "true", "yes", "on", "si", "sí"}

        tracking_code = ""
        tracking_url = ""
        if odoo_order_id:
            try:
                from app.services.tracking_service import ensure_tracking_for_order  # type: ignore
                tracking_code = ensure_tracking_for_order(
                    odoo_order_id=odoo_order_id,
                    order_name=str(pedido or ""),
                    id_web=str(id_web or ""),
                )
                if tracking_code:
                    tracking_url = f"/rastreo/go/{tracking_code}"
            except Exception as ex:
                try:
                    app.logger.exception("tracking_error: %s", ex)
                except Exception:
                    pass

        data = LabelData(
            nombre=request.form.get("nombre", ""),
            direccion=request.form.get("direccion", ""),
            telefono=request.form.get("telefono", ""),
            pedido=pedido,
            id_web=str(id_web or ""),
            zona=request.form.get("zona", ""),
            envio=request.form.get("envio", ""),
            codigo_envio=request.form.get("codigo_envio", ""),
            observaciones=request.form.get("observaciones", ""),
            tracking_code=tracking_code,
            tracking_url=tracking_url,
        )
        out_path = generate_pdf(data)
        token = os.path.basename(out_path)

        pdf_url = url_for("get_pdf", filename=token, _external=False)
        response = {"ok": True, "pdf_url": pdf_url}

        if generate_cfe:
            if not odoo_order_id:
                return jsonify({"ok": False, "error": "order_id_required_for_cfe"}), 400
            try:
                cfe_legacy_engine.configure(app.config, root_path=os.path.abspath(os.path.join(app.root_path, "..", "..")), logger=app.logger)
                # El engine de CFE usa wrap_text como helper global pero en este módulo
                # no viene definido dentro de cfe_legacy_engine. Se lo inyectamos desde
                # Etiquetas antes de generar para evitar NameError.
                cfe_legacy_engine.wrap_text = wrap_text
                _xml_name, xml_bytes = cfe_legacy_engine._odoo_get_cfe_xml_from_order(odoo_order_id)
                cfe = cfe_legacy_engine.parse_cfe_xml(xml_bytes, default_adenda="")
                if not (cfe.adenda or "").strip():
                    try:
                        cfe.adenda = cfe_legacy_engine._default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
                    except Exception:
                        pass
                cfe_out_path = cfe_legacy_engine.generate_receipt_pdf(cfe)
                cfe_token = os.path.basename(cfe_out_path)
                # El CFE se genera usando GENERATED_DIR de esta app de Etiquetas,
                # por eso debe servirse desde /etiquetas/pdf/<archivo> y no desde
                # /cfe_manual/pdf/<archivo>.
                response["cfe_pdf_url"] = url_for("get_pdf", filename=cfe_token, _external=False)
            except Exception as ex:
                try:
                    app.logger.exception("generate_cfe_error: %s", ex)
                except Exception:
                    pass
                return jsonify({"ok": False, "error": "cfe_error", "detail": str(ex)}), 409

        return jsonify(response)

    @app.get("/pdf/<path:filename>")
    def get_pdf(filename: str):
        safe_dir = os.path.abspath(app.config["GENERATED_DIR"])
        path = os.path.abspath(os.path.join(safe_dir, filename))
        if not path.startswith(safe_dir):
            abort(404)
        if not os.path.exists(path):
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=False, download_name=filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5400")), debug=True)
