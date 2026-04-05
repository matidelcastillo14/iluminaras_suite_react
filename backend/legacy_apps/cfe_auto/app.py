from __future__ import annotations
import json
import threading

import os
import uuid
import time
import glob
import re
import html as _html
import xmlrpc.client
import base64
import zlib
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.lib import colors


def mm(x: float) -> float:
    # millimeters -> points
    return x * 72.0 / 25.4


@dataclass
class LabelData:
    nombre: str = ""
    direccion: str = ""
    telefono: str = ""
    pedido: str = ""
    zona: str = ""
    envio: str = ""
    codigo_envio: str = ""
    observaciones: str = ""


@dataclass
class CFEItem:
    descripcion: str
    cantidad: float
    unidad: str
    precio_unitario: float
    monto: float


@dataclass
class CFEData:
    tipo_cfe: int
    tipo_texto: str
    serie: str
    numero: str
    fecha_emision: str  # YYYY-MM-DD
    forma_pago: str
    moneda: str

    emisor_ruc: str
    emisor_razon_social: str
    emisor_dom_fiscal: str
    emisor_ciudad: str
    emisor_depto: str

    receptor_doc: str
    receptor_nombre: str
    receptor_direccion: str
    receptor_ciudad: str
    receptor_depto: str

    neto_22: float
    iva_22: float
    total: float

    cae_id: str
    cae_desde: str
    cae_hasta: str
    cae_venc: str

    tmst_firma: str
    digest_b64: str
    codigo_seguridad_corto: str
    qr_url: str

    adenda: str

    items: list[CFEItem]


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

def _is_ruc_doc(doc: Any, tipo_doc: Any = "") -> bool:
    """Return True when the receiver document should be treated as a RUC.

    Uruguay RUC is typically 12 digits (may include separators). Some XMLs also include TipoDocRecep.
    Anything else (CI, passport, etc.) is treated as consumer final for the buyer box.
    """
    d = _digits_only(doc)
    if len(d) == 12:
        return True

    td = _clean_plain_text(tipo_doc).upper()
    # Be permissive with common representations
    if td in {"RUC", "RUT", "2"}:
        return True

    return False


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _localname(tag: str) -> str:
    if not tag:
        return ""
    return tag.split("}", 1)[-1]


def _brand_from_emisor(razon_social: str, ruc: str | None = None) -> str:
    """Brand selection based on issuer identity.

    Prefer issuer RUC (stable), fallback to corporate name (razón social).
    """

    # Primary: RUC based routing (REINE SRL / Estilo Home)
    try:
        r = "".join(re.findall(r"\d+", str(ruc or "")))
    except Exception:
        r = ""
    if r == "218959840015":
        return "ESTILO_HOME"

    # Fallback: name based routing
    rs = (razon_social or "").strip().upper()
    rs = re.sub(r"[^A-Z0-9]+", " ", rs)
    rs = re.sub(r"\s+", " ", rs).strip()
    if re.search(r"\bREINE\b", rs) or re.search(r"\bESTILO\b\s+\bHOME\b", rs) or re.search(r"\bESTILOHOME\b", rs):
        return "ESTILO_HOME"

    return "LUMINARAS"


def _resolve_path(root_path: str, p: str) -> str:
    """Resolve env/config paths.

    - Absolute paths are used as-is.
    - Relative paths are considered relative to the Flask app root_path.
    """
    p = (p or "").strip()
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return os.path.join(root_path, p)


from pathlib import Path as _Path

def _pick_logo_path(app_root: str, env_value: str, default_rel: str) -> str:
    """Resolve logo path with sensible fallbacks.

    Supports three cases:
      1) Absolute path in env_value.
      2) Relative to this legacy app root.
      3) Relative to Suite root (one level above legacy_apps/) when env_value looks like 'app/...'.

    Always falls back to default_rel under this legacy app.
    """
    env_value = (env_value or '').strip()
    candidates: list[str] = []

    if env_value:
        # 1) relative/abs under legacy app root
        candidates.append(_resolve_path(app_root, env_value))

        # 2) If suite-wide .env provides paths like 'app/static/logo.png', try them relative to suite root
        try:
            if (not os.path.isabs(env_value)) and (env_value.startswith('app/') or env_value.startswith('app\\')):
                suite_root = str(_Path(app_root).parents[1])  # .../iluminaras_suite
                candidates.append(os.path.join(suite_root, env_value))
        except Exception:
            pass

    # 3) default within legacy app
    candidates.append(_resolve_path(app_root, default_rel))

    for p in candidates:
        try:
            if p and os.path.exists(p):
                return p
        except Exception:
            continue

    # last resort
    return candidates[-1]


def _find_text(el: ET.Element, path: str, ns: dict[str, str]) -> str:
    n = el.find(path, ns)
    if n is None or n.text is None:
        return ""
    return n.text.strip()

UY_LATAM_DOCUMENT_TYPE_NAME_BY_CODE: dict[int, str] = {
    101: "e-Ticket",
    102: "Nota de Crédito de e-Ticket",
    103: "Nota de Débito de e-Ticket",
    111: "e-Factura",
    112: "Nota de Crédito de e-Factura",
    113: "Nota de Débito de e-Factura",
    121: "e-Factura Exportación",
    122: "Nota de Crédito de e-Factura Exportación",
    123: "Nota de Débito de e-Factura Exportación",
    124: "e-Remito Exportación",
    131: "e-Ticket Venta por Cuenta Ajena",
    132: "Nota de Crédito e-Ticket Venta por Cuenta Ajena",
    133: "Nota de Débito e-Ticket Venta por Cuenta Ajena",
    141: "e-Factura Venta por Cuenta Ajena",
    142: "Nota de Crédito e-Factura Venta por Cuenta Ajena",
    143: "Nota de Débito e-Factura Venta por Cuenta Ajena",
    151: "e-Boleta",
    152: "Nota de Crédito e-Boleta",
    153: "Nota de Débito e-Boleta",
    181: "e-Remito",
    182: "e-Resguardo",
    201: "e-Ticket Contingencia",
    202: "Nota de Credito de e-Ticket Contingencia",
    203: "Nota de Debito de e-Ticket Contingencia",
    211: "e-Factura Contingencia",
    212: "Nota de Crédito de e-Factura Contingencia",
    213: "Nota de Débito de e-Factura Contingencia",
    221: "e-Factura Exportación Contingencia",
    222: "Nota de Crédito de e-Factura Exportación Contingencia",
    223: "Nota de Débito de e-Factura Exportación Contingencia",
    224: "e-Remito de Exportación Contingencia",
    231: "e-Ticket Venta por Cuenta Ajena Contingencia",
    232: "Nota de Crédito de e-Ticket Venta por Cuenta Ajena Contingencia",
    233: "Nota de Débito de e-Ticket Venta por Cuenta Ajena Contingencia",
    241: "e-Factura Venta por Cuenta Ajena Contingencia",
    242: "Nota de Crédito de e-Factura Venta por Cuenta Ajena Contingencia",
    243: "Nota de Débito de e-Factura Venta por Cuenta Ajena Contingencia",
    251: "e-Boleta Contingencia",
    252: "Nota de Crédito e-Boleta Contingencia",
    253: "Nota de Débito e-Boleta Contingencia",
    281: "e-Remito Contingencia",
    282: "e-Resguardo Contingencia",
}

def _doc_type_label_from_code(tipo_cfe: int, fallback: str = "") -> str:
    """Return a human label for the document type based on Uruguay CFE code.

    We map DGI CFE codes (e.g. 101 e-Ticket, 102 NC e-Ticket, etc.) using the same catalog
    as Odoo l10n_latam.document.type for Uruguay.

    The returned value is ONLY the document type name (no numeric code), e.g. "e-Ticket".
    """
    try:
        t = int(tipo_cfe or 0)
    except Exception:
        t = 0

    name = UY_LATAM_DOCUMENT_TYPE_NAME_BY_CODE.get(t, "")
    base = (name or fallback or "").strip()

    # Some upstream sources (or legacy stored state) may include " (101)" style suffixes.
    # Always remove any trailing numeric code in parenthesis.
    if base:
        base = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", base).strip()

    if base:
        return base
    return str(t) if t else ""


def _sanitize_doc_type_label(label: Any) -> str:
    """Remove trailing numeric code in parentheses, e.g. 'e-Ticket (101)' -> 'e-Ticket'."""
    s = ("%s" % (label or "")).strip()
    if not s:
        return ""
    s = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", s).strip()
    return s



def parse_cfe_xml(xml_bytes: bytes, default_adenda: str = "") -> CFEData:
    """Parse minimal CFE data from the XML.

    The structure is based on DGI CFE XML (namespace http://cfe.dgi.gub.uy)
    and what Odoo l10n_uy_edi typically produces.
    """

    root = ET.fromstring(xml_bytes)
    ns = {
        "cfe": "http://cfe.dgi.gub.uy",
        "ds": "http://www.w3.org/2000/09/xmldsig#",
    }

    # Find the first comprobante node under <CFE> (eTck, eFact, iFact, etc.)
    comprobante = None
    for ch in list(root):
        if _localname(ch.tag) == "Signature":
            continue
        comprobante = ch
        break
    if comprobante is None:
        raise ValueError("xml_sin_comprobante")

    tipo_node_name = _localname(comprobante.tag)
    tipo_texto_map = {
        "eTck": "e-Ticket",
        "eFact": "e-Factura",
        "eRem": "e-Remito",
        "iFact": "i-Factura",
        "iTck": "i-Ticket",
    }
    tipo_texto = tipo_texto_map.get(tipo_node_name, tipo_node_name)

    tipo_cfe = int(_find_text(comprobante, "cfe:Encabezado/cfe:IdDoc/cfe:TipoCFE", ns) or "0")
    tipo_texto = _doc_type_label_from_code(tipo_cfe, tipo_texto)
    serie = _find_text(comprobante, "cfe:Encabezado/cfe:IdDoc/cfe:Serie", ns)
    numero = _find_text(comprobante, "cfe:Encabezado/cfe:IdDoc/cfe:Nro", ns)
    fecha_emision = _find_text(comprobante, "cfe:Encabezado/cfe:IdDoc/cfe:FchEmis", ns)

    fma_pago = _find_text(comprobante, "cfe:Encabezado/cfe:IdDoc/cfe:FmaPago", ns)
    forma_pago = "Contado" if fma_pago == "1" else ("Crédito" if fma_pago == "2" else (fma_pago or ""))

    emisor_ruc = _find_text(comprobante, "cfe:Encabezado/cfe:Emisor/cfe:RUCEmisor", ns)
    emisor_razon = _find_text(comprobante, "cfe:Encabezado/cfe:Emisor/cfe:RznSoc", ns)
    emisor_dom = _find_text(comprobante, "cfe:Encabezado/cfe:Emisor/cfe:DomFiscal", ns)
    emisor_ciudad = _find_text(comprobante, "cfe:Encabezado/cfe:Emisor/cfe:Ciudad", ns)
    emisor_depto = _find_text(comprobante, "cfe:Encabezado/cfe:Emisor/cfe:Departamento", ns)

    receptor_doc = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:DocRecep", ns)
    receptor_nombre = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:RznSocRecep", ns)
    receptor_dir = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:DirRecep", ns)
    receptor_ciudad = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:CiudadRecep", ns)
    receptor_depto = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:DeptoRecep", ns)

    moneda = _find_text(comprobante, "cfe:Encabezado/cfe:Totales/cfe:TpoMoneda", ns) or "UYU"
    neto_22 = float(_find_text(comprobante, "cfe:Encabezado/cfe:Totales/cfe:MntNetoIVATasaBasica", ns) or _find_text(comprobante, "cfe:Encabezado/cfe:Totales/cfe:MntNetoIVATasaBasica", ns) or "0")
    iva_22 = float(_find_text(comprobante, "cfe:Encabezado/cfe:Totales/cfe:MntIVATasaBasica", ns) or "0")
    total = float(_find_text(comprobante, "cfe:Encabezado/cfe:Totales/cfe:MntTotal", ns) or "0")

    cae_id = _find_text(comprobante, "cfe:CAEData/cfe:CAE_ID", ns)
    cae_desde = _find_text(comprobante, "cfe:CAEData/cfe:DNro", ns)
    cae_hasta = _find_text(comprobante, "cfe:CAEData/cfe:HNro", ns)
    cae_venc = _find_text(comprobante, "cfe:CAEData/cfe:FecVenc", ns)

    # Fallbacks for CAE fields (vendors sometimes vary tag names slightly)
    if not cae_id or not cae_desde or not cae_hasta or not cae_venc:
        try:
            for node in comprobante.iter():
                ln = _localname(node.tag)
                if not ln:
                    continue
                val = ("".join(node.itertext()) if node is not None else "") or ""
                val = val.strip()
                if not val:
                    continue
                low = ln.lower()
                if (not cae_id) and low in ("cae_id", "caeid", "cae"):
                    cae_id = val
                if (not cae_desde) and low in ("dnro", "desde", "nrodesde", "inicio"):
                    cae_desde = val
                if (not cae_hasta) and low in ("hnro", "hasta", "nrohasta", "fin"):
                    cae_hasta = val
                if (not cae_venc) and low in ("fecvenc", "fechavenc", "vencimiento", "fechadevencimiento"):
                    cae_venc = val
        except Exception:
            pass

    tmst_firma = _find_text(comprobante, "cfe:TmstFirma", ns)
    digest_b64 = ""
    try:
        digest_b64 = _find_text(root, ".//ds:DigestValue", ns)
    except Exception:
        digest_b64 = ""

    # Código de seguridad (corto) - best-effort deterministic
    codigo_seguridad_corto = ""
    if digest_b64:
        try:
            codigo_seguridad_corto = (digest_b64 or "").strip()[:6]
        except Exception:
            codigo_seguridad_corto = ""

    # QR URL (best-effort)
    fecha_qr = ""
    if tmst_firma and len(tmst_firma) >= 10:
        fecha_qr = tmst_firma[:10].replace("-", "")
    elif fecha_emision and len(fecha_emision) >= 10:
        fecha_qr = fecha_emision[:10].replace("-", "")

    total_qr = f"{total:.2f}"
    digest_enc = urllib.parse.quote(digest_b64, safe="") if digest_b64 else ""
    qr_url = ""
    if emisor_ruc and tipo_cfe and serie and numero and fecha_qr and total_qr and digest_enc:
        qr_url = (
            "https://www.efactura.dgi.gub.uy/consultaQR/cfe?"
            f"{emisor_ruc},{tipo_cfe},{serie},{numero},{total_qr},{fecha_qr},{digest_enc}"
        )

    items: list[CFEItem] = []
    for it in comprobante.findall("cfe:Detalle/cfe:Item", ns):
        desc = _find_text(it, "cfe:NomItem", ns)
        cant = float(_find_text(it, "cfe:Cantidad", ns) or "0")
        uni = _find_text(it, "cfe:UniMed", ns)
        pu = float(_find_text(it, "cfe:PrecioUnitario", ns) or "0")
        monto = float(_find_text(it, "cfe:MontoItem", ns) or "0")
        items.append(CFEItem(descripcion=desc, cantidad=cant, unidad=uni, precio_unitario=pu, monto=monto))

    # Adenda (best-effort): some XMLs include <Adenda> as a free-text node.

    adenda_xml = ""

    try:

        for node in root.iter():

            if _localname(node.tag).lower() == "adenda":

                txt = "".join(node.itertext()).strip()

                if txt:

                    adenda_xml = _clean_html_text(txt)

                    break

    except Exception:

        adenda_xml = ""


    adenda_final = (adenda_xml or "").strip() or (default_adenda or "").strip()



    return CFEData(
        tipo_cfe=tipo_cfe,
        tipo_texto=tipo_texto,
        serie=serie,
        numero=numero,
        fecha_emision=fecha_emision,
        forma_pago=forma_pago,
        moneda=moneda,
        emisor_ruc=emisor_ruc,
        emisor_razon_social=emisor_razon,
        emisor_dom_fiscal=emisor_dom,
        emisor_ciudad=emisor_ciudad,
        emisor_depto=emisor_depto,
        receptor_doc=receptor_doc,
        receptor_nombre=receptor_nombre,
        receptor_direccion=receptor_dir,
        receptor_ciudad=receptor_ciudad,
        receptor_depto=receptor_depto,
        neto_22=neto_22,
        iva_22=iva_22,
        total=total,
        cae_id=cae_id,
        cae_desde=cae_desde,
        cae_hasta=cae_hasta,
        cae_venc=cae_venc,
        tmst_firma=tmst_firma,
        digest_b64=digest_b64,
        codigo_seguridad_corto=codigo_seguridad_corto,
        qr_url=qr_url,
        adenda=adenda_final,
        items=items,
    )


def create_app() -> Flask:
    # Optional .env support (won't override real environment variables)
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except Exception:
        pass

    app = Flask(__name__)

    # --- Config ---
    # PDF ticket / comprobante (default: 80mm thermal roll)
    app.config["RECEIPT_WIDTH_MM"] = _env_float("RECEIPT_WIDTH_MM", 80.0)
    # The height is calculated dynamically (based on items). This is just a minimum.
    app.config["RECEIPT_MIN_HEIGHT_MM"] = _env_float("RECEIPT_MIN_HEIGHT_MM", 220.0)
    app.config["GENERATED_DIR"] = os.path.join(app.root_path, "generated")
    # Logos (two brands)
    # - LUMINARAS: default static/logo.png
    # - ESTILO_HOME: default static/logo_estilo_home.PNG
    # Notes:
    #   * This legacy app may be embedded inside Iluminaras Suite. In that case, Suite's .env can define
    #     LOGO_* paths like 'app/static/...'. We accept them but also fall back to this legacy app's static/.
    lum_env = os.environ.get("LOGO_LUMINARAS_PATH", "")
    est_env = os.environ.get("LOGO_ESTILO_HOME_PATH", "")
    app.config["LOGO_LUMINARAS_PATH"] = _pick_logo_path(app.root_path, lum_env, "static/logo.png")
    app.config["LOGO_ESTILO_HOME_PATH"] = _pick_logo_path(app.root_path, est_env, "static/logo_estilo_home.PNG")
    # Backwards compatible single-logo setting
    app.config["LOGO_PATH"] = _pick_logo_path(app.root_path, os.environ.get("LOGO_PATH", ""), "static/logo.png")
    app.config["OPEN_PDF"] = os.environ.get("OPEN_PDF", "0") == "1"   # only meaningful when running locally
    app.config["KEEP_PDFS_HOURS"] = _env_float("KEEP_PDFS_HOURS", 24.0)

    # Ticket de cambio (regalos): PDF 80mm sin precios
    app.config["CHANGE_TICKET_ENABLED"] = os.environ.get("CHANGE_TICKET_ENABLED", "1") == "1"
    try:
        # Días corridos (calendario). Se permite compatibilidad con CHANGE_DAYS.
        _days_raw = (os.environ.get("CHANGE_VALID_DAYS") or os.environ.get("CHANGE_DAYS") or "30").strip()
        app.config["CHANGE_VALID_DAYS"] = int(_days_raw)
    except Exception:
        app.config["CHANGE_VALID_DAYS"] = 30

    # Texto legal/política (se imprime al final)
    app.config["CHANGE_TICKET_FOOTER_TEXT"] = (
        os.environ.get("CHANGE_TICKET_FOOTER_TEXT")
        or "Deberás presentar el producto en perfecto estado, su empaque original y componentes también en perfecto estado, sin uso."
    ).strip()
    app.config["CHANGE_TICKET_POLICY_URL"] = (
        os.environ.get("CHANGE_TICKET_POLICY_URL")
        or "www.iluminaras.com/politica-de-cambios/"
    ).strip()

    # Adendas (two brands)
    # Backwards compatible: DEFAULT_ADENDA is used as a fallback for both brands.
    app.config["DEFAULT_ADENDA"] = os.environ.get("DEFAULT_ADENDA", "").strip()
    app.config["DEFAULT_ADENDA_LUMINARAS"] = (
        os.environ.get("DEFAULT_ADENDA_LUMINARAS")
        or os.environ.get("ADENDA_LUMINARAS")
        or ""
    ).strip() or app.config["DEFAULT_ADENDA"]
    app.config["DEFAULT_ADENDA_ESTILO_HOME"] = (
        os.environ.get("DEFAULT_ADENDA_ESTILO_HOME")
        or os.environ.get("ADENDA_ESTILO_HOME")
        or ""
    ).strip() or app.config["DEFAULT_ADENDA"]

    # --- Odoo lookup (optional) ---
    app.config["ENABLE_ODOO_LOOKUP"] = os.environ.get("ENABLE_ODOO_LOOKUP", "1") == "1"
    app.config["ODOO_URL"] = (os.environ.get("ODOO_URL") or "").rstrip("/")
    app.config["ODOO_DB"] = os.environ.get("ODOO_DB") or ""
    # Backwards-compatible naming (the project uses ODOO_USERNAME in .env)
    app.config["ODOO_USERNAME"] = os.environ.get("ODOO_USERNAME") or os.environ.get("ODOO_USER") or ""
    app.config["ODOO_API_KEY"] = os.environ.get("ODOO_API_KEY") or os.environ.get("ODOO_PASSWORD") or ""
    app.config["ODOO_SEARCH_LIMIT"] = int(os.environ.get("ODOO_SEARCH_LIMIT", "20"))

    # Optional mapping for zona/envio from Odoo.
    # Syntax:
    #   ODOO_ZONE_FIELD=order:x_studio_zona   (reads from sale.order)
    #   ODOO_ZONE_FIELD=partner:x_studio_zona (reads from res.partner)
    # Same for ODOO_ENVIO_FIELD.
    app.config["ODOO_ZONE_FIELD"] = os.environ.get("ODOO_ZONE_FIELD", "").strip()
    app.config["ODOO_ENVIO_FIELD"] = os.environ.get("ODOO_ENVIO_FIELD", "").strip()

    # Shipping code / tracking reference (configurable)
    # ODOO_SHIPPING_CODE_FIELD examples:
    #   order:x_studio_codigo_de_envio   (read from sale.order)
    #   picking:carrier_tracking_ref     (read from related stock picking)
    # If empty, auto-detect (prefers common custom fields, then picking tracking ref).
    app.config["ODOO_SHIPPING_CODE_FIELD"] = os.environ.get("ODOO_SHIPPING_CODE_FIELD", "").strip()

    # Extra fields to include in the search domain (comma-separated). Use with care.
    # Example: ODOO_ORDER_SEARCH_EXTRA_FIELDS=client_order_ref,x_studio_id_web_pedidos
    app.config["ODOO_ORDER_SEARCH_EXTRA_FIELDS"] = os.environ.get("ODOO_ORDER_SEARCH_EXTRA_FIELDS", "").strip()
    # Example: ODOO_PARTNER_SEARCH_EXTRA_FIELDS=street,city,zip,x_studio_barrio
    app.config["ODOO_PARTNER_SEARCH_EXTRA_FIELDS"] = os.environ.get("ODOO_PARTNER_SEARCH_EXTRA_FIELDS", "").strip()

    os.makedirs(app.config["GENERATED_DIR"], exist_ok=True)
    # --- CFE Auto-poll (new UI) ---
    app.config["CFE_POLL_ENABLED"] = os.environ.get("CFE_POLL_ENABLED", "1") == "1"
    app.config["CFE_POLL_SECONDS"] = _env_float("CFE_POLL_SECONDS", 5.0)

    # Reintentos para CFEs con estado "error" (para regenerar PDFs que quedaron sin generar)
    app.config["CFE_RETRY_ERRORS_ENABLED"] = os.environ.get("CFE_RETRY_ERRORS_ENABLED", "1") == "1"
    app.config["CFE_RETRY_AFTER_SECONDS"] = _env_float("CFE_RETRY_AFTER_SECONDS", 300.0)  # 5 min
    try:
        app.config["CFE_RETRY_MAX_ATTEMPTS"] = int(os.environ.get("CFE_RETRY_MAX_ATTEMPTS", "5"))
    except Exception:
        app.config["CFE_RETRY_MAX_ATTEMPTS"] = 5

    # Cantidad de CFEs a escanear en Odoo en cada ciclo (y por ende máximo en memoria para paginar).
    # Compatibilidad: si no existe CFE_SCAN_LIMIT usa CFE_POLL_LOOKBACK (viejo).
    _scan_limit = int(os.environ.get("CFE_SCAN_LIMIT", os.environ.get("CFE_POLL_LOOKBACK", "200")))
    app.config["CFE_SCAN_LIMIT"] = max(1, _scan_limit)

    # Paginación UI
    _max_page_size = int(os.environ.get("CFE_MAX_PAGE_SIZE", "80"))
    _page_size = int(os.environ.get("CFE_PAGE_SIZE", os.environ.get("CFE_LIST_LIMIT", "80")))
    app.config["CFE_MAX_PAGE_SIZE"] = max(1, _max_page_size)
    app.config["CFE_PAGE_SIZE"] = min(max(1, _page_size), int(app.config["CFE_MAX_PAGE_SIZE"]))

    # Legacy: algunos templates usan list_limit
    app.config["CFE_LIST_LIMIT"] = int(app.config["CFE_PAGE_SIZE"])

    app.config["CFE_STATE_PATH"] = os.path.join(app.config["GENERATED_DIR"], "cfe_state.json")

    _cfe_lock = threading.Lock()
    _cfe_state: dict[str, Any] = {"processed": {}, "last_poll_ts": 0.0, "snapshot": []}

    def _load_cfe_state() -> None:
        nonlocal _cfe_state
        try:
            if os.path.exists(app.config["CFE_STATE_PATH"]):
                with open(app.config["CFE_STATE_PATH"], "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                if isinstance(data, dict):
                    _cfe_state.update(data)
                    if "processed" not in _cfe_state or not isinstance(_cfe_state.get("processed"), dict):
                        _cfe_state["processed"] = {}
                    if "snapshot" not in _cfe_state or not isinstance(_cfe_state.get("snapshot"), list):
                        _cfe_state["snapshot"] = []

                # Backward-compatible cleanup: older states stored "e-Ticket (101)".
                # Keep the numeric code out of the UI and out of newly generated PDFs.
                changed = False
                try:
                    processed = _cfe_state.get("processed") or {}
                    if isinstance(processed, dict):
                        for _k, v in processed.items():
                            if not isinstance(v, dict):
                                continue
                            cfe = v.get("cfe")
                            if isinstance(cfe, dict) and "tipo_texto" in cfe:
                                old = cfe.get("tipo_texto")
                                new = _sanitize_doc_type_label(old)
                                if new != (old or ""):
                                    cfe["tipo_texto"] = new
                                    changed = True

                    snap = _cfe_state.get("snapshot") or []
                    if isinstance(snap, list):
                        for it in snap:
                            if not isinstance(it, dict):
                                continue
                            if "tipo_texto" in it:
                                old = it.get("tipo_texto")
                                new = _sanitize_doc_type_label(old)
                                if new != (old or ""):
                                    it["tipo_texto"] = new
                                    changed = True
                            cfe = it.get("cfe")
                            if isinstance(cfe, dict) and "tipo_texto" in cfe:
                                old = cfe.get("tipo_texto")
                                new = _sanitize_doc_type_label(old)
                                if new != (old or ""):
                                    cfe["tipo_texto"] = new
                                    changed = True
                except Exception:
                    changed = False

                if changed:
                    # Persist the cleaned state so it doesn't reappear after restart.
                    try:
                        tmp = app.config["CFE_STATE_PATH"] + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as f:
                            json.dump(_cfe_state, f, ensure_ascii=False, indent=2)
                        os.replace(tmp, app.config["CFE_STATE_PATH"])
                    except Exception:
                        pass
        except Exception:
            # If corrupted, ignore and start fresh
            _cfe_state = {"processed": {}, "last_poll_ts": 0.0, "snapshot": []}

    def _save_cfe_state() -> None:
        try:
            tmp = app.config["CFE_STATE_PATH"] + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_cfe_state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, app.config["CFE_STATE_PATH"])
        except Exception:
            pass

    def _odoo_recent_cfe_xml_attachments(limit: int) -> list[dict[str, Any]]:
        """Return recent XML-ish sources (best-effort).

        Primary source is *Accounting/Invoicing* (account.move), so we also include
        invoices created from POS that may not appear in Sales.

        Output is normalized as a list of dicts with:
          - att_id: int (positive => ir.attachment id, negative => -l10n_uy_edi.document id)
          - name, create_date, mimetype, res_model, res_id

        We prefer account.move.l10n_uy_edi_xml_attachment_id when present, else
        fall back to account.move.l10n_uy_edi_document_id.
        """

        models, db, uid, api_key = _odoo_client()

        out: list[dict[str, Any]] = []
        seen: set[int] = set()

        def _append(item: dict[str, Any]) -> None:
            try:
                aid = int(item.get("att_id") or 0)
            except Exception:
                return
            if not aid or aid in seen:
                return
            out.append(item)
            seen.add(aid)

                # --- Strategy 0: account.move (Accounting > Invoicing) --- (DISABLED)
        # Disabled to avoid Odoo error: Non-stored field account.move.l10n_uy_edi_xml_attachment_id cannot be searched.
        # Fallback strategies (ir.attachment / l10n_uy_edi.document) remain enabled.
        if False:
            try:
                move_fields = _model_fields("account.move")
            except Exception:
                move_fields = set()
    
            xml_field = "l10n_uy_edi_xml_attachment_id" if "l10n_uy_edi_xml_attachment_id" in move_fields else ""
            doc_field = "l10n_uy_edi_document_id" if "l10n_uy_edi_document_id" in move_fields else ""
    
            if xml_field or doc_field:
                want = [
                    f for f in [
                        "id", "name", "create_date", "write_date", "invoice_date",
                        "state", "move_type", "partner_id", xml_field, doc_field,
                    ]
                    if f and f in move_fields
                ]
    
                if "id" not in want:
                    want = ["id"] + want
    
                if "id" not in want:
                    want = ["id"] + want
    
                domain: list[Any] = []
                if "state" in move_fields:
                    domain.append(("state", "=", "posted"))
                if "move_type" in move_fields:
                    domain.append(("move_type", "in", ["out_invoice", "out_receipt", "out_refund"]))
    
                # Require at least one EDI XML source.
                # NOTE:
                #   account.move.l10n_uy_edi_xml_attachment_id is often a computed/non-stored field in Odoo
                #   (depends on localization/EDI version). Non-stored fields cannot be used in domains.
                #   We therefore ONLY filter by the stored EDI relation (l10n_uy_edi_document_id) when present.
                #   Direct XML presence is validated later when reading the record / downloading attachments.
                if doc_field:
                    domain.append((doc_field, "!=", False))
    
                try:
                    moves = models.execute_kw(
                        db, uid, api_key,
                        "account.move", "search_read",
                        [domain],
                        {
                            "fields": want,
                            "limit": int(limit),
                            "order": "id desc",
                            "context": {"active_test": False},
                        },
                    ) or []
                except Exception as ex:
                    # Loguear Fault real de Odoo (ej: "Non-stored field ...")
                    try:
                        if isinstance(ex, xmlrpc.client.Fault):
                            app.logger.warning(
                                "odoo_fault account.move.search_read faultCode=%s faultString=%s domain=%s fields=%s",
                                ex.faultCode, ex.faultString, domain, want
                            )
                        else:
                            app.logger.warning(
                                "odoo_error account.move.search_read ex=%s domain=%s fields=%s",
                                ex, domain, want
                            )
                    except Exception:
                        pass
                    moves = []
    
                for mv in moves:
                    move_id = int(mv.get("id") or 0)
                    if not move_id:
                        continue
    
                    label = str(mv.get("name") or f"MOVE {move_id}")
                    partner = ""
                    pv = mv.get("partner_id")
                    if isinstance(pv, list) and len(pv) == 2:
                        partner = str(pv[1] or "")
                    display = f"{label} {partner}".strip()
    
                    create_date = str(mv.get("invoice_date") or mv.get("create_date") or mv.get("write_date") or "")
    
                    # Prefer direct XML attachment field (common in POS flows).
                    if xml_field:
                        aids = _value_to_ids(mv.get(xml_field))
                        if aids:
                            _append({
                                "att_id": int(aids[0]),
                                "name": display,
                                "create_date": create_date,
                                "mimetype": "text/xml",
                                "res_model": "account.move",
                                "res_id": move_id,
                            })
                            continue
    
                    # Fallback: EDI document relation.
                    if doc_field:
                        edi_val = mv.get(doc_field)
                        edi_id = None
                        if isinstance(edi_val, list) and edi_val:
                            try:
                                edi_id = int(edi_val[0])
                            except Exception:
                                edi_id = None
                        elif isinstance(edi_val, int):
                            edi_id = int(edi_val)
                        if edi_id:
                            _append({
                                "att_id": -int(edi_id),
                                "name": display,
                                "create_date": create_date,
                                "mimetype": "text/xml",
                                "res_model": "l10n_uy_edi.document",
                                "res_id": int(edi_id),
                            })
    
            if len(out) >= int(limit):
                return out[: int(limit)]
    
            

# --- Strategy A: ir.attachment (fast path, broad) ---
        try:
            att_fields = _model_fields("ir.attachment")
        except Exception:
            att_fields = set()

        fields = [f for f in ["id", "name", "create_date", "mimetype", "res_model", "res_id"] if f in att_fields]
        if not fields:
            fields = ["id", "name"]

        domain: list[Any] = []
        if "res_model" in att_fields and "res_id" in att_fields:
            candidate_models = [
                "l10n_uy_edi.document",
                "account.move",
                "sale.order",
                "pos.order",
            ]
            if "mimetype" in att_fields and "name" in att_fields:
                domain = ["&", ("res_model", "in", candidate_models), "|", ("mimetype", "ilike", "xml"), ("name", "ilike", ".xml")]
            elif "mimetype" in att_fields:
                domain = [("res_model", "in", candidate_models), ("mimetype", "ilike", "xml")]
            else:
                domain = [("res_model", "in", candidate_models)]

        remaining = max(0, int(limit) - len(out))
        if remaining > 0:
            try:
                rows = models.execute_kw(
                    db, uid, api_key,
                    "ir.attachment", "search_read",
                    [domain],
                    {
                        "fields": fields,
                        "limit": int(remaining),
                        "order": "id desc",
                        "context": {"active_test": False},
                    }
                ) or []
            except Exception:
                rows = []

            for r in rows:
                try:
                    aid = int(r.get("id") or 0)
                except Exception:
                    continue
                if not aid or aid in seen:
                    continue
                _append({
                    "att_id": aid,
                    "name": str(r.get("name") or ""),
                    "create_date": str(r.get("create_date") or ""),
                    "mimetype": str(r.get("mimetype") or ""),
                    "res_model": str(r.get("res_model") or ""),
                    "res_id": int(r.get("res_id") or 0),
                })

        if len(out) >= int(limit):
            return out[: int(limit)]

        # --- Strategy B: l10n_uy_edi.document list (covers binary-field XML) ---
        try:
            edi_fields = _model_fields("l10n_uy_edi.document")
        except Exception:
            edi_fields = set()

        base_fields: list[str] = []
        for f in ["id", "name", "display_name", "create_date", "write_date"]:
            if f in edi_fields:
                base_fields.append(f)
        if "id" not in base_fields:
            base_fields = ["id"]

        cand_fields, meta = _edi_attachment_candidate_fields()
        bin_candidates = [f for f in cand_fields if (meta.get(f) or {}).get("type") == "binary"]
        m2o_candidates = [f for f in cand_fields if (meta.get(f) or {}).get("relation") == "ir.attachment"]
        want_fields = sorted(set(base_fields + bin_candidates + m2o_candidates))

        def _maybe_has_xml_binary(v: Any) -> bool:
            if v is None:
                return False
            if isinstance(v, xmlrpc.client.Binary):
                return bool(v.data)
            if isinstance(v, (bytes, bytearray)):
                return len(v) > 0
            if isinstance(v, str):
                return len(v.strip()) > 0
            return False

        remaining = max(0, int(limit) - len(out))
        if remaining > 0:
            try:
                docs = models.execute_kw(
                    db, uid, api_key,
                    "l10n_uy_edi.document", "search_read",
                    [[]],
                    {
                        "fields": want_fields,
                        "limit": int(remaining),
                        "order": "id desc",
                        "context": {"active_test": False},
                    }
                ) or []
            except Exception:
                docs = []

            for d in docs:
                edi_id = int(d.get("id") or 0)
                if not edi_id:
                    continue

                # Only include docs that appear to have *some* XML storage (binary or attachment ref).
                has_any = False
                for f in bin_candidates:
                    if _maybe_has_xml_binary(d.get(f)):
                        has_any = True
                        break
                if not has_any:
                    for f in m2o_candidates:
                        if _value_to_ids(d.get(f)):
                            has_any = True
                            break
                if not has_any:
                    continue

                label = str(d.get("display_name") or d.get("name") or f"EDI {edi_id}")
                create_date = str(d.get("create_date") or d.get("write_date") or "")

                _append({
                    "att_id": -edi_id,
                    "name": label,
                    "create_date": create_date,
                    "mimetype": "text/xml",
                    "res_model": "l10n_uy_edi.document",
                    "res_id": edi_id,
                })

        return out[: int(limit)]

    def _odoo_get_cfe_xml_from_edi_doc(edi_id: int) -> tuple[str, bytes]:
        """Extract CFE XML bytes from l10n_uy_edi.document.

        Tries, in order:
        1) binary fields that look like xml/cfe
        2) ir.attachment relation fields on the document
        3) fallback: ir.attachment search by (res_model,res_id)
        """
        models, db, uid, api_key = _odoo_client()
        cand_fields, meta = _edi_attachment_candidate_fields()
        if not cand_fields:
            raise RuntimeError("edi_no_candidate_fields")

        recs = models.execute_kw(
            db, uid, api_key,
            "l10n_uy_edi.document", "read",
            [[int(edi_id)]],
            {"fields": cand_fields, "context": {"active_test": False}},
        ) or []
        if not recs:
            raise RuntimeError("edi_not_found")
        rec = recs[0]

        def _is_xml_bytes(data: bytes) -> bool:
            if not data:
                return False
            b = data.lstrip()
            if b.startswith(b"<?xml"):
                return True
            if b.startswith(b"<CFE"):
                return True
            if b"http://cfe.dgi.gub.uy" in b[:600]:
                return True
            return False

        def _decode_binary(v: Any) -> bytes:
            if v is None:
                return b""
            if isinstance(v, xmlrpc.client.Binary):
                return bytes(v.data or b"")
            if isinstance(v, (bytes, bytearray)):
                return bytes(v)
            if isinstance(v, str):
                # Odoo xmlrpc usually returns base64 string for binary fields
                s = v.strip()
                if not s:
                    return b""
                try:
                    return base64.b64decode(s)
                except Exception:
                    # maybe already plain xml
                    return s.encode("utf-8", errors="ignore")
            return b""

        # 1) binary fields
        bin_fields = [f for f in cand_fields if (meta.get(f) or {}).get("type") == "binary"]
        # prefer names with xml/cfe
        bin_fields.sort(key=lambda f: ("xml" in str(f).lower(), "cfe" in str(f).lower()), reverse=True)
        for f in bin_fields:
            data = _decode_binary(rec.get(f))
            if _is_xml_bytes(data):
                return f"edi_{edi_id}_{f}.xml", data

        # 2) attachment relation fields
        att_ids: list[int] = []
        for f in cand_fields:
            m = meta.get(f) or {}
            if m.get("relation") == "ir.attachment":
                att_ids.extend(_value_to_ids(rec.get(f)))
        att_ids = sorted(set(att_ids))
        if att_ids:
            candidates: list[tuple[str, bytes, str]] = []
            for aid in att_ids:
                try:
                    candidates.append(_odoo_download_attachment(int(aid)))
                except Exception:
                    continue
            for name, data, mime in candidates:
                n = (name or "").lower()
                if n.endswith(".xml") or ("xml" in (mime or "").lower()) or _is_xml_bytes(data):
                    return name or f"edi_{edi_id}.xml", data

        # 3) fallback: search attachments by res_model/res_id
        try:
            rows = models.execute_kw(
                db, uid, api_key,
                "ir.attachment", "search_read",
                [[("res_model", "=", "l10n_uy_edi.document"), ("res_id", "=", int(edi_id))]],
                {"fields": ["id", "name", "mimetype"], "order": "id desc", "limit": 10, "context": {"active_test": False}},
            ) or []
            for r in rows:
                aid = int(r.get("id") or 0)
                if not aid:
                    continue
                try:
                    name, data, mime = _odoo_download_attachment(aid)
                except Exception:
                    continue
                n = (name or "").lower()
                if n.endswith(".xml") or ("xml" in (mime or "").lower()) or _is_xml_bytes(data):
                    return name or f"edi_{edi_id}.xml", data
        except Exception:
            pass

        raise RuntimeError("edi_no_xml")

    def _poll_and_generate_new_cfes() -> None:
        """Poll Odoo for new XML attachments and generate PDFs for unseen ones."""
        if not app.config["CFE_POLL_ENABLED"]:
            return
        if not _odoo_is_configured():
            return

        with _cfe_lock:
            now = time.time()
            # simple rate limit
            if (now - float(_cfe_state.get("last_poll_ts") or 0.0)) < float(app.config["CFE_POLL_SECONDS"]) * 0.5:
                return
            _cfe_state["last_poll_ts"] = now

        try:
            recent = _odoo_recent_cfe_xml_attachments(int(app.config["CFE_SCAN_LIMIT"]))
        except Exception:
            return

        # Process oldest-first so the list ordering stays natural.
        # create_date is ISO "YYYY-MM-DD HH:MM:SS" so lexicographic order is OK.
        recent_sorted = sorted(
            recent,
            key=lambda x: (str(x.get("create_date") or ""), abs(int(x.get("att_id") or 0)))
        )

        with _cfe_lock:
            processed: dict[str, Any] = _cfe_state.get("processed") or {}
            # Solo tratamos como "visto" definitivo lo que ya está OK.
            ok_keys = set(
                str(k) for (k, v) in processed.items()
                if isinstance(v, dict) and str(v.get("status") or "") == "ok"
            )

        retry_enabled = bool(app.config.get("CFE_RETRY_ERRORS_ENABLED"))
        retry_after = float(app.config.get("CFE_RETRY_AFTER_SECONDS") or 0.0)
        try:
            retry_max = int(app.config.get("CFE_RETRY_MAX_ATTEMPTS") or 0)
        except Exception:
            retry_max = 0

        for att in recent_sorted:
            aid = int(att.get("att_id") or 0)
            if not aid:
                continue

            # Si ya está OK, no reprocesar.
            if str(aid) in ok_keys:
                continue

            # Si está en error, solo reintentar con backoff y un máximo de intentos.
            prev = processed.get(str(aid)) if isinstance(processed.get(str(aid)), dict) else {}
            prev_status = str(prev.get("status") or "")
            if prev_status == "error":
                if not retry_enabled:
                    continue
                try:
                    prev_attempts = int(prev.get("attempts") or 0)
                except Exception:
                    prev_attempts = 0
                try:
                    last_ts = float(prev.get("last_attempt_ts") or 0.0)
                except Exception:
                    last_ts = 0.0

                if retry_max and prev_attempts >= retry_max:
                    continue
                if retry_after and (time.time() - last_ts) < retry_after:
                    continue

            attempt_ts = time.time()
            try:
                attempts = int(prev.get("attempts") or 0) + 1
            except Exception:
                attempts = 1

            # Download
            try:
                if aid > 0:
                    name, xml_bytes, mime = _odoo_download_attachment(aid)
                else:
                    name, xml_bytes = _odoo_get_cfe_xml_from_edi_doc(-aid)
                    mime = "text/xml"
            except Exception as ex:
                with _cfe_lock:
                    _cfe_state["processed"][str(aid)] = {
                        "status": "error",
                        "error": f"download: {ex}",
                        "att": att,
                        "attempts": int(attempts),
                        "last_attempt_ts": float(attempt_ts),
                    }
                    _save_cfe_state()
                continue

            # Parse
            try:
                # Parse XML. If XML has no <Adenda>, apply the brand-specific default from .env.
                cfe = parse_cfe_xml(xml_bytes, default_adenda="")
                if not (cfe.adenda or "").strip():
                    cfe.adenda = _default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
            except Exception as ex:
                with _cfe_lock:
                    _cfe_state["processed"][str(aid)] = {
                        "status": "error",
                        "error": f"parse: {ex}",
                        "att": att,
                        "attempts": int(attempts),
                        "last_attempt_ts": float(attempt_ts),
                    }
                    _save_cfe_state()
                continue

            # Generate deterministic PDF name per attachment
            safe_serie = re.sub(r"[^A-Za-z0-9]", "", (cfe.serie or ""))[:6] or "S"
            safe_num = re.sub(r"[^0-9]", "", (cfe.numero or ""))[:12] or str(aid)
            filename = f"att_{aid}_cfe_{safe_serie}{safe_num}.pdf"
            out_path = os.path.join(app.config["GENERATED_DIR"], filename)

            change_filename = ""
            change_err = ""
            try:
                if not os.path.exists(out_path):
                    # reuse existing generator but write to our deterministic filename
                    _ = generate_receipt_pdf(cfe, override_path=out_path)
                status = "ok"
                err = ""

                # Ticket de cambio (sin precios), se genera junto al PDF principal
                if bool(app.config.get("CHANGE_TICKET_ENABLED")):
                    change_filename = f"att_{aid}_cfe_{safe_serie}{safe_num}_CAMBIO.pdf"
                    change_path = os.path.join(app.config["GENERATED_DIR"], change_filename)
                    try:
                        if not os.path.exists(change_path):
                            _ = generate_change_ticket_pdf(cfe, override_path=change_path)
                    except Exception as ex2:
                        change_filename = ""
                        change_err = f"cambio: {ex2}"
            except Exception as ex:
                status = "error"
                err = f"pdf: {ex}"

            with _cfe_lock:
                _cfe_state["processed"][str(aid)] = {
                    "status": status,
                    "error": err,
                    "attempts": int(attempts),
                    "last_attempt_ts": float(attempt_ts),
                    "pdf": filename if status == "ok" else "",
                    "change_pdf": change_filename if status == "ok" else "",
                    "change_error": change_err if (status == "ok" and change_err) else "",
                    "att": att,
                    "cfe": {
                        "tipo_cfe": int(getattr(cfe, "tipo_cfe", 0) or 0),
                        "tipo_texto": _sanitize_doc_type_label(getattr(cfe, "tipo_texto", "") or ""),
                        "serie": str(getattr(cfe, "serie", "") or ""),
                        "numero": str(getattr(cfe, "numero", "") or ""),
                        "fecha_em": str(getattr(cfe, "fecha_emision", "") or ""),
                        "receptor_doc": str(getattr(cfe, "receptor_doc", "") or ""),
                        "receptor_nombre": str(getattr(cfe, "receptor_nombre", "") or ""),
                    },
                }
                _save_cfe_state()

        with _cfe_lock:
            # Keep a snapshot of the most recent items (for UI)
            _cfe_state["snapshot"] = sorted(
                recent,
                key=lambda x: (str(x.get("create_date") or ""), abs(int(x.get("att_id") or 0))),
                reverse=True,
            )[: int(app.config["CFE_SCAN_LIMIT"])]
            _save_cfe_state()

    def _poll_thread_loop() -> None:
        # One loop per process
        while True:
            try:
                _poll_and_generate_new_cfes()
            except Exception:
                pass
            time.sleep(float(app.config["CFE_POLL_SECONDS"]))

    _load_cfe_state()
    if app.config["CFE_POLL_ENABLED"]:
        t = threading.Thread(target=_poll_thread_loop, daemon=True)
        t.start()

    # --- Odoo helpers ---
    _odoo_cache: dict[str, Any] = {}
    _fields_cache: dict[str, set[str]] = {}
    _edi_fields_cache: dict[str, Any] = {}

    def _value_to_ids(val: Any) -> list[int]:
        if not val:
            return []
        if isinstance(val, int):
            return [val]
        if isinstance(val, list):
            # many2one [id, name] or x2many [id,id,...]
            if len(val) == 2 and isinstance(val[0], int):
                return [val[0]]
            if all(isinstance(x, int) for x in val):
                return list(val)
        return []

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

    def _odoo_reset_client() -> None:
        """Clear cached XML-RPC client (helps after transient ProtocolError like Idle/Request-sent)."""
        try:
            _odoo_cache.pop("client", None)
        except Exception:
            pass


    def _model_fields(model_name: str) -> set[str]:
        if model_name in _fields_cache:
            return _fields_cache[model_name]
        models, db, uid, key = _odoo_client()
        info = models.execute_kw(db, uid, key, model_name, "fields_get", [], {"attributes": ["type"]})
        fields = set(info.keys()) if isinstance(info, dict) else set()
        _fields_cache[model_name] = fields
        return fields

    def _edi_attachment_candidate_fields() -> tuple[list[str], dict[str, Any]]:
        """Return (field_names, fields_get_info) for l10n_uy_edi.document.

        The strategy matches dump_cfe_from_edi_doc.py: pick fields that either
        relate to ir.attachment or look like attachment/xml/cfe fields.
        """
        key = "l10n_uy_edi.document"
        if key in _edi_fields_cache:
            return _edi_fields_cache[key]

        models, db, uid, api_key = _odoo_client()
        info = models.execute_kw(db, uid, api_key, "l10n_uy_edi.document", "fields_get", [], {"attributes": ["type", "relation", "string"]})
        if not isinstance(info, dict):
            info = {}
        cand: list[str] = []
        for fname, meta in info.items():
            fn = str(fname).lower()
            rel = (meta or {}).get("relation") or ""
            if rel == "ir.attachment" or ("attach" in fn) or ("xml" in fn) or ("cfe" in fn):
                cand.append(fname)
        cand = sorted(set(cand))
        _edi_fields_cache[key] = (cand, info)
        return cand, info

    def _odoo_download_attachment(att_id: int) -> tuple[str, bytes, str]:
        """Return (filename, bytes, mimetype) for an ir.attachment."""
        models, db, uid, api_key = _odoo_client()

        def _read() -> list[dict[str, Any]]:
            return models.execute_kw(
                db, uid, api_key,
                "ir.attachment", "read",
                [[att_id]],
                {"fields": ["id", "name", "datas", "type", "url", "mimetype"], "context": {"active_test": False}},
            )

        try:
            recs = _read()
        except Exception as ex:
            # Error típico transitorio de xmlrpc (por ejemplo: "Idle", "Request-sent")
            msg = str(ex)
            if ("Idle" in msg) or ("Request-sent" in msg) or ("timed out" in msg) or ("timeout" in msg):
                _odoo_reset_client()
                models, db, uid, api_key = _odoo_client()
                recs = _read()
            else:
                raise
        if not recs:
            raise RuntimeError(f"attachment_not_found:{att_id}")
        r = recs[0]
        if r.get("type") == "url":
            raise RuntimeError(f"attachment_is_url:{att_id}")
        data_b64 = r.get("datas")
        if not data_b64:
            raise RuntimeError(f"attachment_no_datas:{att_id}")
        name = str(r.get("name") or f"attachment_{att_id}")
        mime = str(r.get("mimetype") or "")
        try:
            data = base64.b64decode(data_b64)
        except Exception as ex:
            raise RuntimeError(f"attachment_decode_failed:{att_id}:{ex}")
        return name, data, mime

    def _odoo_get_cfe_xml_from_order(order_id: int) -> tuple[str, bytes]:
        """Resolve sale.order -> account.move -> l10n_uy_edi.document -> attachment XML."""
        models, db, uid, api_key = _odoo_client()

        # 1) sale.order.invoice_ids
        so = models.execute_kw(db, uid, api_key, "sale.order", "read", [[order_id]], {"fields": ["id", "name", "invoice_ids"]})
        if not so:
            raise RuntimeError("sale_not_found")
        inv_ids = so[0].get("invoice_ids") or []
        if not inv_ids:
            raise RuntimeError("sale_no_invoices")

        # 2) choose invoice best-effort
        move_fields = _model_fields("account.move")
        want = ["id", "name", "state", "create_date", "invoice_date", "l10n_uy_edi_document_id", "payment_reference"]
        want = [f for f in want if f in move_fields] or ["id", "name"]
        invs = models.execute_kw(db, uid, api_key, "account.move", "read", [inv_ids], {"fields": want})
        if not invs:
            raise RuntimeError("invoice_not_found")

        def score(inv: dict[str, Any]) -> tuple[int, int, str, int]:
            edi = inv.get("l10n_uy_edi_document_id")
            has_edi = 1 if edi else 0
            posted = 1 if inv.get("state") == "posted" else 0
            date = str(inv.get("invoice_date") or inv.get("create_date") or "")
            return (has_edi, posted, date, int(inv.get("id") or 0))

        invs_sorted = sorted(invs, key=score, reverse=True)
        inv = invs_sorted[0]
        edi_val = inv.get("l10n_uy_edi_document_id")
        edi_id = None
        if isinstance(edi_val, list) and edi_val:
            edi_id = int(edi_val[0])
        elif isinstance(edi_val, int):
            edi_id = edi_val
        if not edi_id:
            raise RuntimeError("invoice_no_edi")

        # 3) collect attachment ids from l10n_uy_edi.document
        cand_fields, meta = _edi_attachment_candidate_fields()
        if not cand_fields:
            raise RuntimeError("edi_no_candidate_fields")
        recs = models.execute_kw(db, uid, api_key, "l10n_uy_edi.document", "read", [[edi_id]], {"fields": cand_fields})
        if not recs:
            raise RuntimeError("edi_not_found")
        rec = recs[0]
        att_ids: list[int] = []
        for fname in cand_fields:
            m = meta.get(fname) or {}
            if m.get("relation") == "ir.attachment":
                att_ids.extend(_value_to_ids(rec.get(fname)))
        att_ids = sorted(set(att_ids))
        if not att_ids:
            raise RuntimeError("edi_no_attachments")

        # 4) download and pick XML
        candidates: list[tuple[str, bytes, str]] = []
        for aid in att_ids:
            try:
                candidates.append(_odoo_download_attachment(aid))
            except Exception:
                continue
        if not candidates:
            raise RuntimeError("edi_download_failed")

        def is_xml(name: str, data: bytes, mime: str) -> bool:
            n = (name or "").lower()
            if n.endswith(".xml"):
                return True
            if "xml" in (mime or "").lower():
                return True
            if data.lstrip().startswith(b"<?xml"):
                return True
            if data.lstrip().startswith(b"<CFE") or b"http://cfe.dgi.gub.uy" in data[:400]:
                return True
            return False

        xmls = [c for c in candidates if is_xml(*c)]
        if not xmls:
            raise RuntimeError("edi_no_xml")

        # prefer names with cfe
        xmls.sort(key=lambda t: ("cfe" in (t[0] or "").lower(), (t[0] or "").lower().endswith(".xml")), reverse=True)
        name, data, _mime = xmls[0]
        return name, data

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
        want = ["id", "name", "partner_id", "partner_shipping_id", "note", "carrier_id", "client_order_ref"]
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
            """Wrap text to max width while preserving explicit line breaks.

            - Treats literal '\\n' sequences as newlines so values coming from .env can contain '\n'.
            - Preserves blank lines.
            """
            c.setFont(font_name, font_size)

            raw = (text or "")
            raw = raw.replace("\r", "")
            # Allow .env to express line breaks as \n
            raw = raw.replace("\\n", "\n")

            lines_out: list[str] = []
            for para in raw.split("\n"):
                para = para.strip()
                if para == "":
                    lines_out.append("")  # blank line
                    continue

                words = para.split()
                if not words:
                    lines_out.append("")
                    continue

                cur = words[0]
                for w in words[1:]:
                    trial = cur + " " + w
                    if c.stringWidth(trial, font_name, font_size) <= max_width_pt:
                        cur = trial
                    else:
                        lines_out.append(cur)
                        cur = w
                lines_out.append(cur)

            # Remove trailing blank lines (keeps internal blanks)
            while lines_out and lines_out[-1] == "":
                lines_out.pop()

            return lines_out
    def _default_adenda_for_emisor(razon_social: str, ruc: str | None = None) -> str:
        brand = _brand_from_emisor(razon_social, ruc)
        if brand == "ESTILO_HOME":
            return str(app.config.get("DEFAULT_ADENDA_ESTILO_HOME", "") or "").strip()
        return str(app.config.get("DEFAULT_ADENDA_LUMINARAS", "") or "").strip()

    def _logo_path_for_emisor(razon_social: str) -> str:
        brand = _brand_from_emisor(razon_social)
        if brand == "ESTILO_HOME":
            p = str(app.config.get("LOGO_ESTILO_HOME_PATH", "") or "").strip()
        else:
            p = str(app.config.get("LOGO_LUMINARAS_PATH", "") or "").strip()
        # Backwards compatible fallback
        return p or str(app.config.get("LOGO_PATH", "") or "").strip()

    def _estimate_receipt_height_pt(cfe: CFEData, w_pt: float) -> float:
            # Conservative estimation to avoid clipping (thermal roll layout).
            pad = mm(5)
            inner_w = w_pt - 2 * pad
            amount_col_w = mm(24)
            text_w = inner_w - amount_col_w

            tmp = canvas.Canvas(os.devnull, pagesize=(w_pt, mm(2000)))

            # Header / issuer / meta blocks (approx, matches draw steps)
            fixed = 0.0
            fixed += mm(5)   # top pad
            fixed += mm(26)  # logo + spacing (best-effort even if logo missing)
            fixed += mm(20)  # issuer lines + gaps
            # Doc type / number / payment + spacing. The doc type line can wrap.
            fixed += mm(25)
            try:
                doc_label = _sanitize_doc_type_label(cfe.tipo_texto)
                doc_lines = wrap_text(tmp, doc_label, inner_w, "Helvetica-Bold", 12) if doc_label else []
                if doc_lines and len(doc_lines) > 1:
                    fixed += (len(doc_lines) - 1) * mm(5.2)
            except Exception:
                pass
            fixed += mm(26)  # buyer box + spacing

            # Buyer details: wrap values like in render so paper height matches.
            ciudad = " ".join([p for p in [cfe.receptor_ciudad, cfe.receptor_depto] if p]).strip()
            details_h = 0.0
            value_w = inner_w - mm(20)
            fs_val = 8.8
            leading = fs_val * 1.2  # points
            for v in (cfe.receptor_nombre, cfe.receptor_direccion, ciudad):
                v = (v or "").strip()
                if not v:
                    continue
                n = len(wrap_text(tmp, v, value_w, "Helvetica", fs_val) or [""])
                details_h += mm(4.8)  # first line of field
                if n > 1:
                    details_h += (n - 1) * leading
            fixed += details_h + mm(8)

            fixed += mm(12)  # date/currency + spacing

            # Items block (computed using the same wrap logic as render)
            items_h = 0.0
            fs_desc = 9.2
            for it in cfe.items:
                desc_lines = wrap_text(tmp, it.descripcion, text_w, "Helvetica", fs_desc) or [""]
                items_h += mm(5.2)  # first desc line
                if len(desc_lines) > 1:
                    items_h += (len(desc_lines) - 1) * mm(4.6)
                items_h += mm(5.0)  # qty line
                items_h += mm(6.5)  # gap after item

            # Totals block (line + 2 lines + total + spacing)
            fixed += mm(32)

            # Adenda block (optional)
            adenda_h = 0.0
            if (cfe.adenda or "").strip():
                ad_lines = wrap_text(tmp, cfe.adenda, inner_w - mm(8), "Helvetica", 8.0)
                if ad_lines:
                    title_h = mm(7)
                    content_h = len(ad_lines) * mm(4.3) + mm(4)
                    box_h = title_h + content_h
                    adenda_h = box_h + mm(10)

            # QR + spacing
            qr_h = (mm(40) + mm(8)) if (cfe.qr_url or "").strip() else 0.0

            # Footer (security + verify + IVA + DGI)
            footer_h = mm(42)

            # CAE blocks
            cae_h = 0.0
            if (cfe.cae_id or cfe.cae_desde or cfe.cae_hasta):
                cae_h += mm(16) + mm(8)
            if (cfe.cae_venc or "").strip():
                cae_h += mm(11) + mm(6)

            # Safety margin at bottom
            safety = mm(25)

            h = fixed + items_h + adenda_h + qr_h + footer_h + cae_h + safety
            h = max(h, mm(float(app.config["RECEIPT_MIN_HEIGHT_MM"])))
            return h

    def generate_receipt_pdf(cfe: CFEData, override_path: Optional[str] = None) -> str:
            cleanup_old_pdfs()

            w = mm(float(app.config["RECEIPT_WIDTH_MM"]))
            h = _estimate_receipt_height_pt(cfe, w)

            if override_path:
                out_path = override_path
            else:
                filename = f"cfe_{cfe.serie}{cfe.numero}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
                out_path = os.path.join(app.config["GENERATED_DIR"], filename)
            c = canvas.Canvas(out_path, pagesize=(w, h))
            pad = mm(5)
            x0 = pad
            y = h - pad
            inner_w = w - 2 * pad

            def money(v: float) -> str:
                return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

            def qtyfmt(v: float) -> str:
                return f"{v:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")

            def fmt_date_uy(s: str) -> str:
                s = (s or "").strip()
                if not s:
                    return ""
                try:
                    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                        dt = datetime.strptime(s[:10], "%Y-%m-%d")
                        return dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
                return s

            # --- Header (logo + issuer) ---
            try:
                logo_path = _logo_path_for_emisor(cfe.emisor_razon_social)
                if logo_path and os.path.exists(logo_path):
                    img = ImageReader(logo_path)
                    box_w = inner_w * 0.92
                    box_h = mm(18)
                    y -= box_h
                    c.drawImage(
                        img,
                        x0 + (inner_w - box_w) / 2,
                        y,
                        width=box_w,
                        height=box_h,
                        mask="auto",
                        preserveAspectRatio=True,
                        anchor="sw",
                    )
                    y -= mm(4)
            except Exception:
                pass

            c.setFont("Helvetica", 9.6)
            if cfe.emisor_razon_social:
                y -= mm(4.8)
                c.drawCentredString(x0 + inner_w / 2, y, cfe.emisor_razon_social[:90])

            emisor_dom = (cfe.emisor_dom_fiscal or "").strip()
            emisor_city = (cfe.emisor_ciudad or "").strip()
            emisor_depto = (cfe.emisor_depto or "").strip()

            # Avoid duplicates like "MONTEVIDEO Montevideo Montevideo"
            parts = []
            if emisor_dom:
                parts.append(emisor_dom)
            dom_low = emisor_dom.lower()
            if emisor_city and (emisor_city.lower() not in dom_low):
                parts.append(emisor_city)
            if emisor_depto and (emisor_depto.lower() not in dom_low) and (emisor_depto.lower() != emisor_city.lower()):
                parts.append(emisor_depto)

            emisor_line = " ".join([p for p in parts if p]).strip()
            if emisor_line:
                y -= mm(4.4)
                c.drawCentredString(x0 + inner_w / 2, y, emisor_line[:90])

            if cfe.emisor_ruc:
                y -= mm(4.4)
                c.drawCentredString(x0 + inner_w / 2, y, f"RUC {cfe.emisor_ruc}")

            y -= mm(6)

            # --- Document type / number (left) + payment (right) ---
            c.setFont("Helvetica-Bold", 12)
            y -= mm(6)

            # Documento fiscal: si el nombre del tipo es más largo que el ancho del ticket,
            # hacer saltos de línea para que no se corte.
            doc_label = _sanitize_doc_type_label(cfe.tipo_texto)
            doc_lines = wrap_text(c, doc_label, inner_w, "Helvetica-Bold", 12) if doc_label else []
            if not doc_lines:
                doc_lines = [doc_label] if doc_label else [""]

            for i, ln in enumerate(doc_lines):
                if i > 0:
                    y -= mm(5.2)
                c.drawString(x0, y, ln)

            y -= mm(6)
            nro = " ".join([p for p in [cfe.serie, cfe.numero] if p]).strip()
            c.drawString(x0, y, nro)

            if cfe.forma_pago:
                c.setFont("Helvetica", 9.2)
                c.drawRightString(x0 + inner_w, y, f"Pago: {cfe.forma_pago}")

            y -= mm(5)

            # --- Buyer block (doc in box) ---


            box_h = mm(18)


            c.setLineWidth(0.8)


            c.rect(x0, y - box_h, inner_w, box_h, stroke=1, fill=0)



            buyer_doc = (cfe.receptor_doc or "").strip()



            # Solo mostrar "RUC COMPRADOR" en Facturas (e-Factura / i-Factura) y solo si el documento es un RUC.


            tipo_txt_l = (cfe.tipo_texto or "").lower()


            is_factura = (110 <= int(cfe.tipo_cfe or 0) <= 119) or ("factura" in tipo_txt_l)



            if is_factura and buyer_doc and _is_ruc_doc(buyer_doc):


                c.setFont("Helvetica-Bold", 10)


                c.drawCentredString(x0 + inner_w / 2, y - mm(6), "RUC COMPRADOR")


                c.setFont("Helvetica-Bold", 10.5)


                c.drawCentredString(x0 + inner_w / 2, y - mm(13), buyer_doc)


            else:


                c.setFont("Helvetica-Bold", 11)


                # Centrar verticalmente dentro del recuadro


                c.drawCentredString(x0 + inner_w / 2, y - box_h / 2 - mm(1), "CONSUMIDOR FINAL")



            y -= box_h + mm(6)

            # --- Buyer details ---
            def draw_lv(label: str, value: str) -> None:
                nonlocal y
                v = (value or "").strip()
                if not v:
                    return

                # Wrap value so it never gets cut off (e.g., long addresses).
                value_x = x0 + mm(20)
                value_w = inner_w - mm(20)
                fs_val = 8.8
                leading = fs_val * 1.2  # points
                val_lines = wrap_text(c, v, value_w, "Helvetica", fs_val) or [""]

                y -= mm(4.8)
                c.setFont("Helvetica-Bold", fs_val)
                c.drawString(x0, y, f"{label}:")
                c.setFont("Helvetica", fs_val)
                c.drawString(value_x, y, val_lines[0])
                for ln in val_lines[1:]:
                    y -= leading
                    c.drawString(value_x, y, ln)

            draw_lv("Nombre", cfe.receptor_nombre)
            draw_lv("Dirección", cfe.receptor_direccion)
            ciudad = " ".join([p for p in [cfe.receptor_ciudad, cfe.receptor_depto] if p]).strip()
            draw_lv("Ciudad", ciudad)

            y -= mm(4)

            # --- Meta: date / currency ---
            c.setFont("Helvetica", 8.6)
            y -= mm(5)
            c.drawString(x0, y, f"Fecha: {fmt_date_uy(cfe.fecha_emision)}")
            c.drawRightString(x0 + inner_w, y, f"Moneda: {cfe.moneda}")

            y -= mm(7)

            # --- Items ---
            amount_col_w = mm(24)
            text_w = inner_w - amount_col_w
            fs_desc = 9.2
            fs_qty = 8.6

            for it in cfe.items:
                desc_lines = wrap_text(c, it.descripcion, text_w, "Helvetica", fs_desc)
                if not desc_lines:
                    desc_lines = [""]

                c.setFont("Helvetica", fs_desc)
                y -= mm(5.2)
                c.drawString(x0, y, desc_lines[0])
                c.drawRightString(x0 + inner_w, y, money(it.monto))

                for ln in desc_lines[1:]:
                    y -= mm(4.6)
                    c.drawString(x0, y, ln)

                y -= mm(5.0)
                c.setFont("Helvetica", fs_qty)
                unit = (it.unidad or "").strip() or "N/A"
                c.drawString(x0, y, f"{qtyfmt(it.cantidad)} {unit} x {money(it.precio_unitario)}")

                y -= mm(6.5)

            # --- Totals ---
            c.setLineWidth(0.6)
            c.line(x0, y, x0 + inner_w, y)
            y -= mm(6)

            c.setFont("Helvetica", 8.8)
            c.drawString(x0, y, "Subtotal Gravado 22%")
            c.drawRightString(x0 + inner_w, y, money(cfe.neto_22))
            y -= mm(5.2)
            c.drawString(x0, y, "IVA 22%")
            c.drawRightString(x0 + inner_w, y, money(cfe.iva_22))
            y -= mm(6.2)

            c.setFont("Helvetica-Bold", 10.2)
            c.drawString(x0, y, "TOTAL")
            c.drawRightString(x0 + inner_w, y, money(cfe.total))
            y -= mm(10)

            # --- Adenda (box with title) ---
            ad_lines: list[str] = []
            if cfe.adenda:
                ad_lines = wrap_text(c, cfe.adenda, inner_w - mm(8), "Helvetica", 8.0)

            if ad_lines:
                title_h = mm(7)
                content_h = len(ad_lines) * mm(4.3) + mm(4)
                box_h = title_h + content_h
                c.setLineWidth(0.8)
                c.rect(x0, y - box_h, inner_w, box_h, stroke=1, fill=0)

                c.setFont("Helvetica-Bold", 9)
                c.drawCentredString(x0 + inner_w / 2, y - mm(5), "ADENDA")

                c.setLineWidth(0.6)
                c.line(x0, y - title_h, x0 + inner_w, y - title_h)

                c.setFont("Helvetica", 8.0)
                ty = y - title_h - mm(4)
                for ln in ad_lines[:22]:
                    c.drawString(x0 + mm(3), ty, ln)
                    ty -= mm(4.3)

                y -= box_h + mm(10)

            # --- QR ---
            if cfe.qr_url:
                qr_size = mm(40)
                qr = QrCodeWidget(cfe.qr_url)
                bounds = qr.getBounds()
                wqr = bounds[2] - bounds[0]
                hqr = bounds[3] - bounds[1]
                d = Drawing(qr_size, qr_size, transform=[qr_size / wqr, 0, 0, qr_size / hqr, 0, 0])
                d.add(qr)
                renderPDF.draw(d, c, x0 + (inner_w - qr_size) / 2, y - qr_size)
                y -= qr_size + mm(8)

            # --- Footer ---
            c.setFont("Helvetica", 8.6)
            if cfe.codigo_seguridad_corto:
                c.drawCentredString(x0 + inner_w / 2, y, f"Código de Seguridad: {cfe.codigo_seguridad_corto}")
                y -= mm(5)

            c.drawCentredString(x0 + inner_w / 2, y, "Puede verificar comprobante en:")
            y -= mm(4.6)
            c.setFont("Helvetica-Bold", 8.6)
            c.drawCentredString(x0 + inner_w / 2, y, "www.dgi.gub.uy")
            y -= mm(6)

            c.setFont("Helvetica", 8.2)
            c.drawCentredString(x0 + inner_w / 2, y, "IVA al día")
            y -= mm(5.0)

            c.setFont("Helvetica-Bold", 12.5)
            c.drawCentredString(x0 + inner_w / 2, y, "DGI")
            y -= mm(10)

            # --- CAE blocks (table + vencimiento) ---
            if cfe.cae_id or cfe.cae_desde or cfe.cae_hasta:
                table_h = mm(16)
                hdr_h = mm(7)
                c.setLineWidth(0.8)
                c.rect(x0, y - table_h, inner_w, table_h, stroke=1, fill=0)
                c.setLineWidth(0.6)
                c.line(x0, y - hdr_h, x0 + inner_w, y - hdr_h)

                col1 = inner_w * 0.40
                col2 = inner_w * 0.30
                x1 = x0 + col1
                x2 = x0 + col1 + col2
                c.line(x1, y, x1, y - table_h)
                c.line(x2, y, x2, y - table_h)

                c.setFont("Helvetica-Bold", 8.4)
                c.drawCentredString(x0 + col1 / 2, y - mm(5), "CAE")
                c.drawCentredString(x1 + col2 / 2, y - mm(5), "Inicio")
                c.drawCentredString(x2 + (inner_w - col1 - col2) / 2, y - mm(5), "Fin")

                vy = y - hdr_h - mm(5)
                c.setFont("Helvetica", 8.4)
                c.drawCentredString(x0 + col1 / 2, vy, (cfe.cae_id or "")[:40])
                c.drawCentredString(x1 + col2 / 2, vy, (cfe.cae_desde or "")[:40])
                c.drawCentredString(x2 + (inner_w - col1 - col2) / 2, vy, (cfe.cae_hasta or "")[:40])

                y -= table_h + mm(8)

            if cfe.cae_venc:
                venc_h = mm(11)
                c.setLineWidth(0.8)
                c.rect(x0, y - venc_h, inner_w, venc_h, stroke=1, fill=0)
                c.setFont("Helvetica", 8.6)
                c.drawCentredString(x0 + inner_w / 2, y - mm(7), f"Fecha de vencimiento: {fmt_date_uy(cfe.cae_venc)}")
                y -= venc_h + mm(6)

            c.showPage()
            c.save()
            return out_path


    def _estimate_change_ticket_height_pt(cfe: CFEData, w_pt: float) -> float:
            pad = mm(5)
            inner_w = w_pt - 2 * pad
            tmp = canvas.Canvas(os.devnull, pagesize=(w_pt, mm(2000)))

            fixed = 0.0
            fixed += mm(5)   # top pad
            fixed += mm(24)  # logo area + spacing
            fixed += mm(10)  # title
            fixed += mm(22)  # date/valid/ref fields + spacing
            fixed += mm(6)   # separator gap

            items_h = 0.0
            fs_desc = 9.2
            for it in cfe.items:
                desc_lines = wrap_text(tmp, it.descripcion, inner_w, "Helvetica", fs_desc) or [""]
                items_h += mm(5.2)
                if len(desc_lines) > 1:
                    items_h += (len(desc_lines) - 1) * mm(4.6)
                items_h += mm(5.0)  # qty line
                items_h += mm(4.8)  # gap

            footer_h = 0.0
            footer_txt = (app.config.get("CHANGE_TICKET_FOOTER_TEXT") or "").strip()
            policy_url = (app.config.get("CHANGE_TICKET_POLICY_URL") or "").strip()
            if _brand_from_emisor(cfe.emisor_razon_social, cfe.emisor_ruc) == "ESTILO_HOME":
                # Estilo Home (REINE): no imprimir el link de política de cambios de Iluminaras
                policy_url = ""
            if footer_txt:
                footer_lines = wrap_text(tmp, footer_txt, inner_w, "Helvetica", 8.6)
                footer_h += len(footer_lines) * mm(4.4) + mm(6)
            if policy_url:
                footer_h += mm(10.5)

            safety = mm(18)
            h = fixed + items_h + footer_h + safety
            h = max(h, mm(120))
            return h

    def generate_change_ticket_pdf(cfe: CFEData, override_path: Optional[str] = None) -> str:
            """Genera un ticket de cambio (sin precios ni totales)."""
            cleanup_old_pdfs()

            w = mm(float(app.config["RECEIPT_WIDTH_MM"]))
            h = _estimate_change_ticket_height_pt(cfe, w)

            if override_path:
                out_path = override_path
            else:
                filename = f"cambio_{cfe.serie}{cfe.numero}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.pdf"
                out_path = os.path.join(app.config["GENERATED_DIR"], filename)

            c = canvas.Canvas(out_path, pagesize=(w, h))
            pad = mm(5)
            x0 = pad
            y = h - pad
            inner_w = w - 2 * pad

            def qtyfmt(v: float) -> str:
                return f"{v:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")

            def fmt_date_uy(s: str) -> str:
                s = (s or "").strip()
                if not s:
                    return ""
                try:
                    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                        dt = datetime.strptime(s[:10], "%Y-%m-%d")
                        return dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
                return s

            def add_days_uy(s: str, days: int) -> str:
                try:
                    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                        dt = datetime.strptime(s[:10], "%Y-%m-%d") + timedelta(days=int(days))
                        return dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
                return ""

            # Borde externo (similar al ticket manual)
            try:
                c.setLineWidth(0.9)
                c.rect(mm(3), mm(3), w - mm(6), h - mm(6), stroke=1, fill=0)
            except Exception:
                pass

            # Logo
            try:
                logo_path = _logo_path_for_emisor(cfe.emisor_razon_social)
                if logo_path and os.path.exists(logo_path):
                    img = ImageReader(logo_path)
                    box_w = inner_w * 0.85
                    box_h = mm(16)
                    y -= box_h
                    c.drawImage(
                        img,
                        x0 + (inner_w - box_w) / 2,
                        y,
                        width=box_w,
                        height=box_h,
                        mask="auto",
                        preserveAspectRatio=True,
                        anchor="sw",
                    )
                    y -= mm(4)
            except Exception:
                pass

            # Título + emisor
            c.setFont("Helvetica-Bold", 12.2)
            y -= mm(6.2)
            c.drawCentredString(x0 + inner_w / 2, y, "TICKET DE CAMBIO")

            emisor_rs = (cfe.emisor_razon_social or "").strip()
            if emisor_rs:
                c.setFont("Helvetica-Bold", 10.0)
                y -= mm(5.2)
                c.drawCentredString(x0 + inner_w / 2, y, emisor_rs[:60])

            policy_url = (app.config.get("CHANGE_TICKET_POLICY_URL") or "").strip()
            if _brand_from_emisor(cfe.emisor_razon_social, cfe.emisor_ruc) == "ESTILO_HOME":
                # Estilo Home (REINE): no imprimir el link de política de cambios de Iluminaras
                policy_url = ""
            if policy_url:
                c.setFont("Helvetica", 8.6)
                y -= mm(4.6)
                c.drawCentredString(x0 + inner_w / 2, y, policy_url[:80])

            y -= mm(7)

            compra = fmt_date_uy(cfe.fecha_emision)
            valido = add_days_uy(cfe.fecha_emision, int(app.config.get("CHANGE_VALID_DAYS") or 30))
            referencia = " ".join([p for p in [cfe.serie, cfe.numero] if (p or "").strip()]).strip()

            c.setFont("Helvetica", 9.2)
            y -= mm(5.2); c.drawString(x0, y, f"Fecha de compra: {compra}")
            y -= mm(5.2); c.drawString(x0, y, f"Cambio válido hasta: {valido}")
            y -= mm(5.2); c.drawString(x0, y, f"Referencia: {referencia}")

            y -= mm(6)
            c.setLineWidth(0.6)
            c.line(x0, y, x0 + inner_w, y)
            y -= mm(6)

            # Ítems (sin precios)
            c.setFont("Helvetica", 9.2)
            for it in cfe.items:
                desc_lines = wrap_text(c, it.descripcion, inner_w, "Helvetica", 9.2) or [""]
                y -= mm(5.2)
                c.drawString(x0, y, desc_lines[0])

                for ln in desc_lines[1:]:
                    y -= mm(4.6)
                    c.drawString(x0, y, ln)

                y -= mm(5.0)
                c.setFont("Helvetica", 8.6)
                unit = (it.unidad or "").strip() or "N/A"
                c.drawString(x0, y, f"Cant.: {qtyfmt(it.cantidad)} {unit}")
                c.setFont("Helvetica", 9.2)
                y -= mm(4.8)

            footer_txt = (app.config.get("CHANGE_TICKET_FOOTER_TEXT") or "").strip()
            if footer_txt:
                c.setFont("Helvetica", 8.6)
                lines = wrap_text(c, footer_txt, inner_w, "Helvetica", 8.6)
                for ln in lines[:10]:
                    y -= mm(4.4)
                    c.drawString(x0, y, ln)

            if policy_url:
                y -= mm(5.0)
                c.setFont("Helvetica-Bold", 8.8)
                c.drawString(x0, y, "Política completa en:")
                y -= mm(4.6)
                c.setFont("Helvetica", 8.8)
                c.drawString(x0, y, policy_url[:90])

            c.showPage()
            c.save()
            return out_path
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            poll_seconds=float(app.config["CFE_POLL_SECONDS"]),
            list_limit=int(app.config["CFE_LIST_LIMIT"]),
            page_size=int(app.config["CFE_PAGE_SIZE"]),
            max_page_size=int(app.config["CFE_MAX_PAGE_SIZE"]),
            scan_limit=int(app.config["CFE_SCAN_LIMIT"]),
        )
    @app.get("/api/cfes")
    def api_cfes():
        """Lista CFEs recientes (paginado) con URL del PDF generado (si existe)."""
        if not _odoo_is_configured():
            return jsonify({"ok": False, "error": "odoo_not_configured"}), 501

        # Asegurar un poll reciente (best-effort)
        try:
            _poll_and_generate_new_cfes()
        except Exception:
            pass

        try:
            page = int(request.args.get("page") or "1")
        except Exception:
            page = 1
        try:
            page_size = int(request.args.get("page_size") or str(app.config["CFE_PAGE_SIZE"]))
        except Exception:
            page_size = int(app.config["CFE_PAGE_SIZE"])

        page = max(1, page)
        page_size = max(1, page_size)
        page_size = min(page_size, int(app.config["CFE_MAX_PAGE_SIZE"]))

        with _cfe_lock:
            snapshot = list(_cfe_state.get("snapshot") or [])
            processed = dict(_cfe_state.get("processed") or {})

        total = len(snapshot)
        total_pages = max(1, int((total + page_size - 1) // page_size))
        if page > total_pages:
            page = total_pages

        start = (page - 1) * page_size
        end = start + page_size

        items: list[dict[str, Any]] = []
        for att in snapshot[start:end]:
            aid = int(att.get("att_id") or 0)
            p = processed.get(str(aid)) or {}
            pdf = str(p.get("pdf") or "")
            pdf_url = url_for("get_pdf", filename=pdf, _external=False) if pdf else ""

            # Backfill: si ya existe el PDF principal pero falta el ticket de cambio, generarlo on-demand (por página).
            if bool(app.config.get("CHANGE_TICKET_ENABLED")) and (str(p.get("status") or "") == "ok") and not str(p.get("change_pdf") or ""):
                try:
                    if aid > 0:
                        _n, xml_bytes, _m = _odoo_download_attachment(aid)
                    else:
                        _n, xml_bytes = _odoo_get_cfe_xml_from_edi_doc(-aid)

                    cfe_full = parse_cfe_xml(xml_bytes, default_adenda="")
                    if not (cfe_full.adenda or "").strip():
                        cfe_full.adenda = _default_adenda_for_emisor(cfe_full.emisor_razon_social)

                    safe_serie = re.sub(r"[^A-Za-z0-9]", "", (cfe_full.serie or ""))[:6] or "S"
                    safe_num = re.sub(r"[^0-9]", "", (cfe_full.numero or ""))[:12] or str(aid)
                    change_filename = f"att_{aid}_cfe_{safe_serie}{safe_num}_CAMBIO.pdf"
                    change_path = os.path.join(app.config["GENERATED_DIR"], change_filename)
                    if not os.path.exists(change_path):
                        _ = generate_change_ticket_pdf(cfe_full, override_path=change_path)

                    with _cfe_lock:
                        rec = (_cfe_state.get("processed") or {}).get(str(aid)) or {}
                        if isinstance(rec, dict):
                            rec["change_pdf"] = change_filename
                            rec["change_error"] = ""
                            (_cfe_state.get("processed") or {})[str(aid)] = rec
                            _save_cfe_state()

                    p = dict(p)
                    p["change_pdf"] = change_filename
                except Exception:
                    pass

            change_pdf = str(p.get("change_pdf") or "")
            change_pdf_url = url_for("get_pdf", filename=change_pdf, _external=False) if change_pdf else ""
            cfe = p.get("cfe") or {}
            items.append({
                "att_id": aid,
                "att_name": str(att.get("name") or ""),
                "create_date": str(att.get("create_date") or ""),
                "status": str(p.get("status") or "pending"),
                "error": str(p.get("error") or ""),
                "pdf_url": pdf_url,
                "change_pdf_url": change_pdf_url,
                "tipo_texto": _sanitize_doc_type_label(cfe.get("tipo_texto") or ""),
                "serie": str(cfe.get("serie") or ""),
                "numero": str(cfe.get("numero") or ""),
                "fecha_em": str(cfe.get("fecha_em") or ""),
                "receptor": str(cfe.get("receptor_nombre") or ""),
                "receptor_doc": str(cfe.get("receptor_doc") or ""),
            })

        return jsonify({
            "ok": True,
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "max_page_size": int(app.config["CFE_MAX_PAGE_SIZE"]),
        })

    @app.post("/api/cfes/poll_now")
    def api_cfes_poll_now():
        if not _odoo_is_configured():
            return jsonify({"ok": False, "error": "odoo_not_configured"}), 501
        try:
            _poll_and_generate_new_cfes()
            return jsonify({"ok": True})
        except Exception as ex:
            return jsonify({"ok": False, "error": "poll_error", "detail": str(ex)}), 500
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
        # Preload pickings codes (best-effort)
        ship_map: dict[int, str] = {}
        try:
            pick_field = (ship_fld if (ship_src == "picking" and ship_fld and ship_fld in picking_fields) else (
                "carrier_tracking_ref" if "carrier_tracking_ref" in picking_fields else (
                    "tracking_reference" if "tracking_reference" in picking_fields else (
                        "name" if "name" in picking_fields else ""
                    )
                )
            ))
            if pick_field:
                ids = [int(x.get("id")) for x in rows if x.get("id")]
                names = [str(x.get("name") or "") for x in rows if x.get("id")]
                ship_map = _odoo_pickings_shipcode_map(ids, names, pick_field)
        except Exception:
            ship_map = {}

        out: list[dict[str, Any]] = []
        for r in rows:
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
                "codigo_envio": _clean_plain_text(((r.get(ship_fld) if (ship_src == "order" and ship_fld) else "") or ship_map.get(int(r.get("id") or 0), "") or "")), 
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
        if not _odoo_is_configured():
            return jsonify({"ok": False, "error": "odoo_not_configured"}), 501

        try:
            order_id = int(request.form.get("order_id") or "0")
        except Exception:
            order_id = 0
        if not order_id:
            return jsonify({"ok": False, "error": "order_id_required"}), 400

        # 1) Download XML from Odoo
        try:
            _xml_name, xml_bytes = _odoo_get_cfe_xml_from_order(order_id)
        except Exception as ex:
            return jsonify({"ok": False, "error": "odoo_cfe_error", "detail": str(ex)}), 409

        # 2) Parse XML
        try:
            cfe = parse_cfe_xml(xml_bytes, default_adenda="")
            if not (cfe.adenda or "").strip():
                cfe.adenda = _default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
        except Exception as ex:
            return jsonify({"ok": False, "error": "xml_parse_error", "detail": str(ex)}), 422

        # 3) Generate PDF (factura) + ticket de cambio (opcional)
        out_path = generate_receipt_pdf(cfe)
        token = os.path.basename(out_path)

        change_token = ""
        if bool(app.config.get("CHANGE_TICKET_ENABLED")):
            try:
                change_path = generate_change_ticket_pdf(cfe)
                change_token = os.path.basename(change_path)
            except Exception:
                change_token = ""

        # Optional: open locally on server machine (Windows/macOS/Linux desktop)
        if app.config["OPEN_PDF"]:
            try:
                if os.name == "nt":
                    os.startfile(out_path)  # type: ignore[attr-defined]
                elif os.name == "posix":
                    # best-effort for Linux/macOS
                    import subprocess
                    subprocess.Popen(["xdg-open", out_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        pdf_url = url_for("get_pdf", filename=token, _external=False)
        change_pdf_url = url_for("get_pdf", filename=change_token, _external=False) if change_token else ""
        return jsonify({"ok": True, "pdf_url": pdf_url, "change_pdf_url": change_pdf_url})

    @app.get("/pdf/<path:filename>")
    def get_pdf(filename: str):
        safe_dir = os.path.abspath(app.config["GENERATED_DIR"])
        path = os.path.abspath(os.path.join(safe_dir, filename))
        if not path.startswith(safe_dir):
            abort(404)
        if not os.path.exists(path):
            abort(404)
        return send_file(path, mimetype="application/pdf", as_attachment=False, download_name=filename)
    
    app.logger.warning("LOG_TEST: app.logger is working (startup)")


    return app


app = create_app()

if __name__ == "__main__":
    # For local runs: python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5500")), debug=True)