from __future__ import annotations

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

import logging
from logging.handlers import TimedRotatingFileHandler

from flask import Flask, render_template, request, jsonify, send_file, abort, url_for, g
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




# --- Uruguay CFE TipoCFE mapping (from l10n_latam.document.type) ---
# Used to display the correct document type on the PDF based on Encabezado/IdDoc/TipoCFE.
UY_TIPOCFE_MAP = {101: {'name': 'e-Ticket', 'prefix': 'e-TK', 'internal_type': 'Facturas'},
 102: {'name': 'Nota de Crédito de e-Ticket', 'prefix': 'e-NCTK', 'internal_type': 'Notas de Crédito'},
 103: {'name': 'Nota de Débito de e-Ticket', 'prefix': 'e-NDTK', 'internal_type': 'Notas de Débito'},
 111: {'name': 'e-Factura', 'prefix': 'e-FC', 'internal_type': 'Facturas'},
 112: {'name': 'Nota de Crédito de e-Factura', 'prefix': 'e-NC', 'internal_type': 'Notas de Crédito'},
 113: {'name': 'Nota de Débito de e-Factura', 'prefix': 'e-ND', 'internal_type': 'Notas de Débito'},
 121: {'name': 'e-Factura Exportación', 'prefix': 'e-FCE', 'internal_type': 'Facturas'},
 122: {'name': 'Nota de Crédito de e-Factura Exportación', 'prefix': 'e-NCE', 'internal_type': 'Notas de Crédito'},
 123: {'name': 'Nota de Débito de e-Factura Exportación', 'prefix': 'e-NDE', 'internal_type': 'Notas de Débito'},
 124: {'name': 'e-Remito Exportación', 'prefix': 'e-REME', 'internal_type': ''},
 131: {'name': 'e-Ticket Venta por Cuenta Ajena', 'prefix': 'e-TK-CA', 'internal_type': 'Facturas'},
 132: {'name': 'Nota de Crédito e-Ticket Venta por Cuenta Ajena',
       'prefix': 'e-NCTK-CA',
       'internal_type': 'Notas de Crédito'},
 133: {'name': 'Nota de Débito e-Ticket Venta por Cuenta Ajena',
       'prefix': 'e-NDTK-CA',
       'internal_type': 'Notas de Débito'},
 141: {'name': 'e-Factura Venta por Cuenta Ajena', 'prefix': 'e-FC-CA', 'internal_type': 'Facturas'},
 142: {'name': 'Nota de Crédito e-Factura Venta por Cuenta Ajena',
       'prefix': 'e-NC-CA',
       'internal_type': 'Notas de Crédito'},
 143: {'name': 'Nota de Débito e-Factura Venta por Cuenta Ajena',
       'prefix': 'e-ND-CA',
       'internal_type': 'Notas de Débito'},
 151: {'name': 'e-Boleta', 'prefix': 'e-BO', 'internal_type': 'Facturas'},
 152: {'name': 'Nota de Crédito e-Boleta', 'prefix': 'e-BO-NC', 'internal_type': 'Notas de Crédito'},
 153: {'name': 'Nota de Débito e-Boleta', 'prefix': 'e-BO-ND', 'internal_type': 'Notas de Débito'},
 181: {'name': 'e-Remito', 'prefix': 'e-REM', 'internal_type': ''},
 182: {'name': 'e-Resguardo', 'prefix': 'e-RES', 'internal_type': ''},
 201: {'name': 'e-Ticket Contingencia', 'prefix': 'e-TK-C', 'internal_type': 'Facturas'},
 202: {'name': 'Nota de Credito de e-Ticket Contingencia', 'prefix': 'e-NCTK-C', 'internal_type': 'Notas de Crédito'},
 203: {'name': 'Nota de Debito de e-Ticket Contingencia', 'prefix': 'e-NDTK-C', 'internal_type': 'Notas de Débito'},
 211: {'name': 'e-Factura Contingencia', 'prefix': 'e-FC-C', 'internal_type': 'Facturas'},
 212: {'name': 'Nota de Crédito de e-Factura Contingencia', 'prefix': 'e-NC-C', 'internal_type': 'Notas de Crédito'},
 213: {'name': 'Nota de Débito de e-Factura Contingencia', 'prefix': 'e-ND-C', 'internal_type': 'Notas de Débito'},
 221: {'name': 'e-Factura Exportación Contingencia', 'prefix': 'e-FCE-C', 'internal_type': 'Facturas'},
 222: {'name': 'Nota de Crédito de e-Factura Exportación Contingencia',
       'prefix': 'e-NCE-C',
       'internal_type': 'Notas de Crédito'},
 223: {'name': 'Nota de Débito de e-Factura Exportación Contingencia',
       'prefix': 'e-NDE-C',
       'internal_type': 'Notas de Débito'},
 224: {'name': 'e-Remito de Exportación Contingencia', 'prefix': 'e-REME-C', 'internal_type': ''},
 231: {'name': 'e-Ticket Venta por Cuenta Ajena Contingencia', 'prefix': 'e-TK-CAC', 'internal_type': 'Facturas'},
 232: {'name': 'Nota de Crédito de e-Ticket Venta por Cuenta Ajena Contingencia',
       'prefix': 'e-NCTK-CAC',
       'internal_type': 'Notas de Crédito'},
 233: {'name': 'Nota de Débito de e-Ticket Venta por Cuenta Ajena Contingencia',
       'prefix': 'e-NDTK-CAC',
       'internal_type': 'Notas de Débito'},
 241: {'name': 'e-Factura Venta por Cuenta Ajena Contingencia', 'prefix': 'e-FC-CAC', 'internal_type': 'Facturas'},
 242: {'name': 'Nota de Crédito de e-Factura Venta por Cuenta Ajena Contingencia',
       'prefix': 'e-NC-CAC',
       'internal_type': 'Notas de Crédito'},
 243: {'name': 'Nota de Débito de e-Factura Venta por Cuenta Ajena Contingencia',
       'prefix': 'e-ND-CAC',
       'internal_type': 'Notas de Débito'},
 251: {'name': 'e-Boleta Contingencia', 'prefix': 'e-BO-C', 'internal_type': 'Facturas'},
 252: {'name': 'Nota de Crédito e-Boleta Contingencia', 'prefix': 'e-BO-NC-C', 'internal_type': 'Notas de Crédito'},
 253: {'name': 'Nota de Débito e-Boleta Contingencia', 'prefix': 'e-BO-ND-C', 'internal_type': 'Notas de Débito'},
 281: {'name': 'e-Remito Contingencia', 'prefix': 'e-REM-C', 'internal_type': ''},
 282: {'name': 'e-Resguardo Contingencia', 'prefix': 'e-RES-C', 'internal_type': ''}}


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


def _sanitize_doc_type_label(label: Any) -> str:
    """Normalize document type labels for printing (remove legacy '(123)' suffixes)."""
    base = ""
    try:
        if isinstance(label, dict):
            base = str(label.get("name") or label.get("display_name") or "")
        elif label is None:
            base = ""
        else:
            base = str(label)
    except Exception:
        base = ""
    base = (base or "").strip()
    if base:
        base = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", base).strip()
    return base

def _find_text(el: ET.Element, path: str, ns: dict[str, str]) -> str:
    n = el.find(path, ns)
    if n is None or n.text is None:
        return ""
    return n.text.strip()


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

    # Prefer TipoCFE mapping over tag name (covers tickets, invoices, notes, contingency, export, etc.)
    tipo_info = UY_TIPOCFE_MAP.get(tipo_cfe)
    if tipo_info and tipo_info.get("name"):
        tipo_texto = tipo_info["name"]

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

    receptor_tipo_doc = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:TipoDocRecep", ns)
    receptor_doc_raw = _find_text(comprobante, "cfe:Encabezado/cfe:Receptor/cfe:DocRecep", ns)

    # Buyer document display rule:
    # - For e-Ticket / i-Ticket: always treat as "Consumidor Final" (do not show CI/other docs in the buyer box)
    # - For e-Factura / i-Factura: show buyer document ONLY when it is a RUC
    tipo_l = (tipo_node_name or "").lower()
    tipo_nombre = (tipo_texto or "").lower()
    # Ticket-like documents: e-Ticket, e-Boleta, and their notes (including contingency/CA)
    is_ticket = (
        ("tck" in tipo_l)
        or (100 <= tipo_cfe <= 109)
        or (130 <= tipo_cfe <= 139)
        or (150 <= tipo_cfe <= 159)
        or (200 <= tipo_cfe <= 209)
        or ("ticket" in tipo_nombre)
        or ("boleta" in tipo_nombre)
    )
    # Factura-like documents: e-Factura and variants (export/CA/contingency) + their notes
    is_factura = (
        ("fact" in tipo_l)
        or (110 <= tipo_cfe <= 129)
        or (140 <= tipo_cfe <= 149)
        or (210 <= tipo_cfe <= 219)
        or ("factura" in tipo_nombre)
    )

    receptor_doc = receptor_doc_raw if (is_factura and _is_ruc_doc(receptor_doc_raw, receptor_tipo_doc)) else ""
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
        codigo_seguridad_corto = digest_b64.strip()[:6]

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

    # --- Logging (production) ---
    # Writes to: <app_root>\logs\app.log (rotates daily, keeps 30 days)
    # Also logs to stdout/stderr so NSSM can capture it.
    log_dir = os.path.join(app.root_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    def _setup_logging() -> None:
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s pid=%(process)d %(message)s"
        )

        file_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "app.log"),
            when="midnight",
            backupCount=30,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(fmt)

        root = logging.getLogger()
        root.setLevel(logging.INFO)

        # Avoid duplicate handlers if the module is reloaded / run twice.
        def _has_same_handler(h: logging.Handler) -> bool:
            if isinstance(h, TimedRotatingFileHandler):
                return getattr(h, "baseFilename", "").lower() == os.path.join(log_dir, "app.log").lower()
            return False

        if not any(_has_same_handler(h) for h in root.handlers):
            root.addHandler(file_handler)
            root.addHandler(console_handler)

        # Reduce noisy logs from some libraries if needed
        logging.getLogger("waitress").setLevel(logging.INFO)
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

    _setup_logging()

    access_log = logging.getLogger("access")
    app_log = logging.getLogger("app")

    @app.before_request
    def _log_request_start() -> None:
        g._start_ts = time.monotonic()
        g.rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        access_log.info(
            'rid=%s start %s %s ip=%s ua="%s"',
            g.rid,
            request.method,
            request.full_path,
            request.headers.get("X-Forwarded-For", request.remote_addr),
            request.headers.get("User-Agent", "-"),
        )

    @app.after_request
    def _log_request_end(resp):
        try:
            ms = int((time.monotonic() - getattr(g, "_start_ts", time.monotonic())) * 1000)
        except Exception:
            ms = -1
        try:
            size = resp.calculate_content_length() or "-"
        except Exception:
            size = "-"
        access_log.info(
            "rid=%s end status=%s ms=%s bytes=%s",
            getattr(g, "rid", "-"),
            getattr(resp, "status_code", "-"),
            ms,
            size,
        )
        # Propagate request id for correlation
        try:
            resp.headers["X-Request-ID"] = getattr(g, "rid", "")
        except Exception:
            pass
        return resp

    @app.teardown_request
    def _log_teardown(exc):
        if exc is not None:
            logging.getLogger("error").exception("rid=%s unhandled_exception", getattr(g, "rid", "-"))
        return None


    # --- Config ---
    # PDF ticket / comprobante (default: 80mm thermal roll)
    app.config["RECEIPT_WIDTH_MM"] = _env_float("RECEIPT_WIDTH_MM", 80.0)
    # The height is calculated dynamically (based on items). This is just a minimum.
    app.config["RECEIPT_MIN_HEIGHT_MM"] = _env_float("RECEIPT_MIN_HEIGHT_MM", 220.0)
    app.config["GENERATED_DIR"] = os.path.join(app.root_path, "generated")
    app.config["LOGO_PATH"] = os.environ.get("LOGO_PATH", os.path.join(app.root_path, "static", "logo.png"))
    app.config["LOGO_LUMINARAS_PATH"] = os.environ.get(
        "LOGO_LUMINARAS_PATH",
        os.path.join(app.root_path, "static", "logo.png"),
    )
    app.config["LOGO_ESTILO_HOME_PATH"] = os.environ.get(
        "LOGO_ESTILO_HOME_PATH",
        os.path.join(app.root_path, "static", "logo_estilo_home.PNG"),
    )
    app.config["OPEN_PDF"] = os.environ.get("OPEN_PDF", "0") == "1"   # only meaningful when running locally
    app.config["KEEP_PDFS_HOURS"] = _env_float("KEEP_PDFS_HOURS", 24.0)
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
        recs = models.execute_kw(
            db, uid, api_key,
            "ir.attachment", "read",
            [[att_id]],
            {"fields": ["id", "name", "datas", "type", "url", "mimetype"], "context": {"active_test": False}},
        )
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
        so_fields = _model_fields("sale.order")
        so_want = ["id", "name", "invoice_ids", "client_order_ref", "reference", "origin",
                   "x_studio_id_web_pedidos", "x_meli_cart", "x_studio_codigo_de_envio", "x_studio_id_rastreo"]
        so_read = [f for f in so_want if f in so_fields]

        so = models.execute_kw(
            db, uid, api_key,
            "sale.order", "read",
            [[order_id]],
            {"fields": so_read},
        )
        if not so:
            raise RuntimeError("sale_not_found")
        inv_ids = so[0].get("invoice_ids") or []
        if not inv_ids:
            # Fallback: some flows leave invoice_ids empty but the CFE is in Contabilidad.
            # We search account.move using common references from the order.
            so_ref_candidates = []
            for k in ("name", "client_order_ref", "reference", "origin",
                      "x_studio_id_web_pedidos", "x_meli_cart", "x_studio_codigo_de_envio", "x_studio_id_rastreo"):
                v = so[0].get(k)
                if v:
                    so_ref_candidates.append(str(v).strip())
            # de-dup / filter tiny tokens
            seen = set()
            terms = []
            for t in so_ref_candidates:
                if len(t) < 3:
                    continue
                if t in seen:
                    continue
                seen.add(t)
                terms.append(t)

            move_fields_fb = _model_fields("account.move")
            fb_fields = []
            for f in ("invoice_origin", "ref", "payment_reference", "name",
                      "x_studio_pedido_meli", "x_studio_x_studio_pedido_web", "x_studio_x_studio_codigo_de_envio"):
                if f in move_fields_fb:
                    fb_fields.append(f)

            conds = []
            for t in terms:
                for f in fb_fields:
                    conds.append((f, "ilike", t))

            if conds:
                domain = ["|"] * (len(conds) - 1) + conds
                moves_fb = models.execute_kw(
                    db, uid, api_key,
                    "account.move", "search_read",
                    [domain],
                    {"fields": ["id", "name", "state", "create_date", "invoice_date", "l10n_uy_edi_document_id", "payment_reference"],
                     "limit": 10,
                     "order": "id desc"},
                )
                # prefer posted
                moves_fb_sorted = sorted(
                    moves_fb,
                    key=lambda r: (0 if r.get("state") == "posted" else 1, r.get("invoice_date") or r.get("create_date") or ""),
                )
                inv_ids = [r["id"] for r in moves_fb_sorted if r.get("id")]

            if not inv_ids:
                raise RuntimeError("sale_no_invoices")# 2) choose invoice best-effort
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

    def _odoo_get_cfe_xml_from_move(move_id: int) -> tuple[str, bytes]:
        """Resolve account.move -> (CFE XML attachment name, bytes).

        Strategy:
        - Prefer account.move.l10n_uy_edi_xml_attachment_id if present.
        - Fallback to account.move.l10n_uy_edi_document_id and scan candidate fields for attachments.
        """
        models, db, uid, api_key = _odoo_client()

        move_fields = _model_fields("account.move")
        want = ["id", "name", "l10n_uy_edi_xml_attachment_id", "l10n_uy_edi_document_id"]
        want = [f for f in want if f in move_fields] or ["id", "name"]

        recs = models.execute_kw(
            db, uid, api_key,
            "account.move", "read",
            [[move_id]],
            {"fields": want, "context": {"active_test": False}},
        )
        if not recs:
            raise RuntimeError("move_not_found")

        mv = recs[0]

        # 1) Direct XML attachment on account.move (newer implementations)
        att = mv.get("l10n_uy_edi_xml_attachment_id")
        att_ids = _value_to_ids(att)
        if att_ids:
            name, data, _mime = _odoo_download_attachment(att_ids[0])
            return name, data

        # 2) EDI document (older implementations)
        edi = mv.get("l10n_uy_edi_document_id")
        edi_ids = _value_to_ids(edi)
        if not edi_ids:
            raise RuntimeError("move_no_edi")

        edi_id = edi_ids[0]
        cand_fields, _fields_info = _edi_attachment_candidate_fields()

        recs = models.execute_kw(
            db, uid, api_key,
            "l10n_uy_edi.document", "read",
            [[edi_id]],
            {"fields": ["id"] + cand_fields, "context": {"active_test": False}},
        )
        if not recs:
            raise RuntimeError("edi_not_found")

        r = recs[0]
        candidates: list[tuple[str, bytes, str]] = []
        for fname in cand_fields:
            for att_id in _value_to_ids(r.get(fname)):
                try:
                    name, data, mime = _odoo_download_attachment(att_id)
                    candidates.append((name, data, mime))
                except Exception:
                    continue

        if not candidates:
            raise RuntimeError("edi_no_attachments")

        def is_xml(name: str, data: bytes, mime: str) -> bool:
            if (mime or "").lower() in ("application/xml", "text/xml"):
                return True
            if (name or "").lower().endswith(".xml"):
                return True
            head = (data or b"")[:600].lstrip()
            if head.startswith(b"<?xml"):
                return True
            if head.startswith(b"<CFE") or b"http://cfe.dgi.gub.uy" in head[:400]:
                return True
            return False

        xmls = [c for c in candidates if is_xml(*c)]
        if not xmls:
            raise RuntimeError("edi_no_xml")

        # Prefer names with 'cfe' or explicit .xml extension
        xmls.sort(key=lambda t: ("cfe" in (t[0] or "").lower(), (t[0] or "").lower().endswith(".xml")), reverse=True)
        name, data, _mime = xmls[0]
        return name, data

    def _odoo_get_cfe_xml_from_doc(doc_type: str, doc_id: int) -> tuple[str, bytes]:
        """Entry point used by /generate: always fetch CFE XML from Contabilidad (account.move)."""
        t = (doc_type or "sale").strip().lower()

        if t == "sale":
            return _odoo_get_cfe_xml_from_order(doc_id)

        if t == "pos":
            models, db, uid, api_key = _odoo_client()
            pos_fields = _model_fields("pos.order")
            fld = "account_move" if "account_move" in pos_fields else ("account_move_id" if "account_move_id" in pos_fields else "")
            if not fld:
                raise RuntimeError("pos_no_account_move_field")

            recs = models.execute_kw(
                db, uid, api_key,
                "pos.order", "read",
                [[doc_id]],
                {"fields": ["id", "name", fld], "context": {"active_test": False}},
            )
            if not recs:
                raise RuntimeError("pos_not_found")

            mv_ids = _value_to_ids(recs[0].get(fld))
            if not mv_ids:
                raise RuntimeError("pos_no_invoice")

            return _odoo_get_cfe_xml_from_move(mv_ids[0])

        if t == "move":
            return _odoo_get_cfe_xml_from_move(doc_id)

        raise RuntimeError(f"unknown_doc_type:{t}")
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

    def _build_or_domain(terms: list[tuple[str, str, Any]]) -> list[Any]:
        """Build a prefix-OR domain: (t1 OR t2 OR ...)."""
        ts = [t for t in terms if t]
        if not ts:
            return []
        dom: list[Any] = [ts[0]]
        for t in ts[1:]:
            dom = ["|", t] + dom
        return dom

    def _odoo_search_sale_orders_v2(q: str) -> list[dict[str, Any]]:
        """Search sale.order by multiple references (pedido/cliente/teléfono/dirección/id web/meli/cart/id meli/código envío)."""
        models, db, uid, key = _odoo_client()

        order_fields = _model_fields("sale.order")
        partner_fields = _model_fields("res.partner")
        picking_fields = _model_fields("stock.picking")

        ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)

        # OR terms
        terms: list[tuple[str, str, Any]] = []

        def add_term(field_path: str) -> None:
            terms.append((field_path, "ilike", q))

        # pedido / referencias
        add_term("name")
        if "client_order_ref" in order_fields:
            add_term("client_order_ref")
        if "reference" in order_fields:
            add_term("reference")
        if "origin" in order_fields:
            add_term("origin")

        # cliente / contacto
        add_term("partner_id.name")
        if "phone" in partner_fields:
            add_term("partner_id.phone")
        if "mobile" in partner_fields:
            add_term("partner_id.mobile")
        if "phone_mobile_search" in partner_fields:
            add_term("partner_id.phone_mobile_search")
        if "email" in partner_fields:
            add_term("partner_id.email")
        if "street" in partner_fields:
            add_term("partner_id.street")
            add_term("partner_shipping_id.street")
        if "city" in partner_fields:
            add_term("partner_id.city")
            add_term("partner_shipping_id.city")

        # Integraciones (si existen)
        for f in ("x_studio_id_web_pedidos", "x_meli_cart", "x_studio_meli", "x_studio_codigo_de_envio", "x_studio_id_rastreo"):
            if f in order_fields:
                add_term(f)

        # Código de envío en sale.order (si está ahí)
        if ship_src == "order" and ship_fld and ship_fld in order_fields:
            add_term(ship_fld)

        domain: list[Any] = _build_or_domain(terms)

        fields = ["id", "name", "partner_id", "state", "date_order", "client_order_ref"]
        # common integration fields for UI
        for f in ("x_studio_id_web_pedidos", "x_meli_cart", "x_studio_meli"):
            if f in order_fields:
                fields.append(f)
        if "x_studio_codigo_de_envio" in order_fields:
            fields.append("x_studio_codigo_de_envio")

        if ship_src == "order" and ship_fld in order_fields:
            fields.append(ship_fld)
        fields = list(dict.fromkeys([f for f in fields if (("." in f) or (f in order_fields) or (f in ("id","name","partner_id","state","date_order","client_order_ref")))]))

        rows = models.execute_kw(
            db, uid, key,
            "sale.order", "search_read",
            [domain],
            {"fields": fields, "limit": int(app.config["ODOO_SEARCH_LIMIT"]), "order": "id desc"},
        )
        rows = rows if isinstance(rows, list) else []

        # If the shipping code is stored in stock.picking, also search there (best-effort) and union results.
        if ship_src == "picking" and ship_fld and ship_fld in picking_fields:
            try:
                pick_want = ["id", ship_fld]
                link_field = "sale_id" if "sale_id" in picking_fields else ""
                if link_field:
                    pick_want.append(link_field)
                if "origin" in picking_fields:
                    pick_want.append("origin")

                pick_rows = models.execute_kw(
                    db, uid, key,
                    "stock.picking", "search_read",
                    [[(ship_fld, "ilike", q)]],
                    {"fields": pick_want, "limit": 30, "order": "id desc"},
                )
                pick_rows = pick_rows if isinstance(pick_rows, list) else []
                sale_ids: set[int] = set()
                origins: set[str] = set()
                for pr in pick_rows:
                    if link_field:
                        for sid in _value_to_ids(pr.get(link_field)):
                            sale_ids.add(int(sid))
                    if pr.get("origin"):
                        origins.add(str(pr.get("origin")))

                extra_ids: set[int] = set()
                if sale_ids:
                    extra_ids |= sale_ids
                if origins:
                    # match by name
                    extra = models.execute_kw(
                        db, uid, key,
                        "sale.order", "search_read",
                        [[("name", "in", list(origins))]],
                        {"fields": fields, "limit": 50, "order": "id desc"},
                    )
                    extra = extra if isinstance(extra, list) else []
                    for er in extra:
                        rows.append(er)

                if extra_ids:
                    extra = models.execute_kw(
                        db, uid, key,
                        "sale.order", "search_read",
                        [[("id", "in", list(extra_ids))]],
                        {"fields": fields, "limit": 50, "order": "id desc"},
                    )
                    extra = extra if isinstance(extra, list) else []
                    rows.extend(extra)
            except Exception:
                pass

        # Deduplicate by id
        seen: set[int] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            rid = int(r.get("id") or 0)
            if not rid or rid in seen:
                continue
            seen.add(rid)
            out.append(r)
        return out

    def _odoo_search_pos_orders(q: str) -> list[dict[str, Any]]:
        models, db, uid, key = _odoo_client()

        pos_fields = _model_fields("pos.order")
        partner_fields = _model_fields("res.partner")

        terms: list[tuple[str, str, Any]] = []
        def add(field_path: str) -> None:
            terms.append((field_path, "ilike", q))

        add("name")
        if "pos_reference" in pos_fields:
            add("pos_reference")
        if "ticket_code" in pos_fields:
            add("ticket_code")
        if "tracking_number" in pos_fields:
            add("tracking_number")

        add("partner_id.name")
        if "mobile" in partner_fields:
            add("partner_id.mobile")
        if "phone" in partner_fields:
            add("partner_id.phone")
        if "phone_mobile_search" in partner_fields:
            add("partner_id.phone_mobile_search")
        if "email" in partner_fields:
            add("partner_id.email")
        if "street" in partner_fields:
            add("partner_id.street")

        domain: list[Any] = _build_or_domain(terms)

        fields = ["id", "name", "partner_id", "state"]
        for f in ("pos_reference", "ticket_code", "tracking_number", "date_order"):
            if f in pos_fields:
                fields.append(f)
        if "date_order" not in fields and "create_date" in pos_fields:
            fields.append("create_date")

        rows = models.execute_kw(
            db, uid, key,
            "pos.order", "search_read",
            [domain],
            {"fields": fields, "limit": int(app.config["ODOO_SEARCH_LIMIT"]), "order": "id desc"},
        )
        return rows if isinstance(rows, list) else []

    def _odoo_search_account_moves(q: str) -> list[dict[str, Any]]:
        models, db, uid, key = _odoo_client()

        move_fields = _model_fields("account.move")
        partner_fields = _model_fields("res.partner")

        # Restrict to customer invoices / refunds if possible
        base: list[Any] = []
        if "move_type" in move_fields:
            base.append(("move_type", "in", ["out_invoice", "out_refund"]))
        if "state" in move_fields:
            base.append(("state", "in", ["posted", "draft"]))

        terms: list[tuple[str, str, Any]] = []
        def add(field_path: str) -> None:
            terms.append((field_path, "ilike", q))

        add("name")  # invoice number
        if "payment_reference" in move_fields:
            add("payment_reference")
        if "ref" in move_fields:
            add("ref")
        if "invoice_origin" in move_fields:
            add("invoice_origin")

        # Custom cross refs if present
        for f in ("x_studio_x_studio_pedido_web", "x_studio_pedido_meli", "x_studio_x_studio_pedido_meli"):
            if f in move_fields:
                add(f)

        add("partner_id.name")
        if "phone_mobile_search" in partner_fields:
            add("partner_id.phone_mobile_search")
        if "phone" in partner_fields:
            add("partner_id.phone")
        if "mobile" in partner_fields:
            add("partner_id.mobile")

        domain: list[Any] = base + _build_or_domain(terms)

        fields = ["id", "name", "partner_id"]
        for f in ("state", "invoice_date", "create_date", "invoice_origin", "payment_reference", "ref"):
            if f in move_fields:
                fields.append(f)

        rows = models.execute_kw(
            db, uid, key,
            "account.move", "search_read",
            [domain],
            {"fields": fields, "limit": int(app.config["ODOO_SEARCH_LIMIT"]), "order": "id desc"},
        )
        return rows if isinstance(rows, list) else []

    def _odoo_search_documents(q: str) -> list[dict[str, Any]]:
        """Return a unified, UI-ready list of matches across Sale, POS, and Facturas."""
        sale_rows = _odoo_search_sale_orders_v2(q)
        pos_rows = _odoo_search_pos_orders(q)
        move_rows = _odoo_search_account_moves(q)

        # Preload sale shipping codes (best-effort)
        order_fields = _model_fields("sale.order")
        picking_fields = _model_fields("stock.picking")
        ship_src, ship_fld = _shipcode_mapping(order_fields, picking_fields)
        ship_map: dict[int, str] = {}
        if ship_src == "picking":
            try:
                pick_field = ship_fld if (ship_fld and ship_fld in picking_fields) else (
                    "carrier_tracking_ref" if "carrier_tracking_ref" in picking_fields else (
                        "tracking_reference" if "tracking_reference" in picking_fields else (
                            "name" if "name" in picking_fields else ""
                        )
                    )
                )
                if pick_field and sale_rows:
                    ids = [int(x.get("id")) for x in sale_rows if x.get("id")]
                    names = [str(x.get("name") or "") for x in sale_rows if x.get("id")]
                    ship_map = _odoo_pickings_shipcode_map(ids, names, pick_field)
            except Exception:
                ship_map = {}

        out: list[dict[str, Any]] = []

        # Sale orders
        for r in sale_rows:
            oid = int(r.get("id") or 0)
            codigo = ""
            if ship_src == "order" and ship_fld and r.get(ship_fld):
                codigo = str(r.get(ship_fld) or "")
            elif oid in ship_map:
                codigo = str(ship_map.get(oid) or "")
            # also allow studio field as fallback
            if not codigo and r.get("x_studio_codigo_de_envio"):
                codigo = str(r.get("x_studio_codigo_de_envio") or "")

            out.append({
                "id": oid,
                "doc_type": "sale",
                "pedido": r.get("name", ""),
                "cliente": (r.get("partner_id") or [None, ""])[1] if r.get("partner_id") else "",
                "estado": r.get("state", ""),
                "fecha": r.get("date_order", ""),
                "ref": _clean_plain_text(r.get("client_order_ref") or ""),
                "id_web": _digits_only(r.get("x_studio_id_web_pedidos") or ""),
                "meli_cart": _digits_only(r.get("x_meli_cart") or ""),
                "id_meli": _digits_only(r.get("x_studio_meli") or ""),
                "codigo_envio": _clean_plain_text(codigo),
                "factura": "",
            })

        # POS orders
        for r in pos_rows:
            pid = int(r.get("id") or 0)
            codigo = ""
            for f in ("tracking_number", "ticket_code", "pos_reference"):
                if r.get(f):
                    codigo = str(r.get(f) or "")
                    break
            fecha = r.get("date_order") or r.get("create_date") or ""
            out.append({
                "id": pid,
                "doc_type": "pos",
                "pedido": r.get("name", ""),
                "cliente": (r.get("partner_id") or [None, ""])[1] if r.get("partner_id") else "",
                "estado": r.get("state", ""),
                "fecha": fecha,
                "ref": _clean_plain_text(r.get("pos_reference") or ""),
                "id_web": "",
                "meli_cart": "",
                "id_meli": "",
                "codigo_envio": _clean_plain_text(codigo),
                "factura": "",
            })

        # Invoices / moves
        for r in move_rows:
            mid = int(r.get("id") or 0)
            fecha = r.get("invoice_date") or r.get("create_date") or ""
            out.append({
                "id": mid,
                "doc_type": "move",
                "pedido": str(r.get("invoice_origin") or r.get("name") or ""),
                "cliente": (r.get("partner_id") or [None, ""])[1] if r.get("partner_id") else "",
                "estado": r.get("state", ""),
                "fecha": fecha,
                "ref": _clean_plain_text(r.get("payment_reference") or r.get("ref") or ""),
                "id_web": "",
                "meli_cart": "",
                "id_meli": "",
                "codigo_envio": "",
                "factura": str(r.get("name") or ""),
            })

        # Sort: newest first (best-effort: by fecha string then id)
        def sort_key(x: dict[str, Any]) -> tuple[str, int]:
            return (str(x.get("fecha") or ""), int(x.get("id") or 0))

        out.sort(key=sort_key, reverse=True)
        return out[: int(app.config["ODOO_SEARCH_LIMIT"]) * 3]

    def _to_float(v: Any) -> float:
        try:
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            try:
                return float(str(v).replace(",", "."))
            except Exception:
                return 0.0

    def _pick_fields(model: str, candidates: list[str]) -> list[str]:
        try:
            flds = _model_fields(model)
        except Exception:
            flds = {}
        return [f for f in candidates if f in flds]

    def _odoo_sale_lines(order_id: int) -> tuple[list[dict[str, Any]], float, str]:
        """Return (lines, total, fecha_doc) for sale.order."""
        models, db, uid, key = _odoo_client()

        order_want = ["order_line"] + _pick_fields("sale.order", ["amount_total", "date_order"])
        orec = models.execute_kw(
            db, uid, key,
            "sale.order", "read",
            [[order_id]],
            {"fields": order_want, "context": {"active_test": False}},
        )
        if not orec:
            return ([], 0.0, "")

        o = orec[0]
        line_ids = [int(x) for x in (o.get("order_line") or []) if x]
        fecha_doc = str(o.get("date_order") or "")

        if not line_ids:
            return ([], _to_float(o.get("amount_total")), fecha_doc)

        lwant = _pick_fields(
            "sale.order.line",
            ["name", "display_type", "product_uom_qty", "price_unit", "discount", "price_subtotal", "price_total"],
        )
        if not lwant:
            lwant = ["name"]
        lrecs = models.execute_kw(
            db, uid, key,
            "sale.order.line", "read",
            [line_ids],
            {"fields": lwant, "context": {"active_test": False}},
        )

        out: list[dict[str, Any]] = []
        total = 0.0
        for ln in (lrecs or []):
            if ln.get("display_type"):
                continue
            desc = _clean_plain_text(ln.get("name") or "")
            qty = _to_float(ln.get("product_uom_qty"))
            pu = _to_float(ln.get("price_unit"))
            disc = _to_float(ln.get("discount"))
            sub = _to_float(ln.get("price_subtotal"))
            if not sub and qty and pu:
                sub = qty * pu * (1.0 - (disc / 100.0 if disc else 0.0))
            total += sub
            out.append({"descripcion": desc, "cantidad": qty, "precio_unitario": pu, "subtotal": sub})

        if not total:
            total = _to_float(o.get("amount_total"))

        return (out, total, fecha_doc)

    def _odoo_pos_lines(pos_id: int) -> tuple[list[dict[str, Any]], float, str, str]:
        """Return (lines, total, fecha_doc, etiqueta) for pos.order."""
        models, db, uid, key = _odoo_client()

        pwant = _pick_fields(
            "pos.order",
            ["lines", "amount_total", "date_order", "create_date", "tracking_number", "ticket_code", "pos_reference"],
        )
        if "lines" not in pwant:
            pwant = ["lines"] + pwant
        recs = models.execute_kw(
            db, uid, key,
            "pos.order", "read",
            [[pos_id]],
            {"fields": list(dict.fromkeys(pwant)), "context": {"active_test": False}},
        )
        if not recs:
            return ([], 0.0, "", "")

        o = recs[0]
        fecha_doc = str(o.get("date_order") or o.get("create_date") or "")

        etiqueta = ""
        for f in ("tracking_number", "ticket_code", "pos_reference"):
            if o.get(f):
                etiqueta = _clean_plain_text(o.get(f) or "")
                break

        line_ids = [int(x) for x in (o.get("lines") or []) if x]
        if not line_ids:
            return ([], _to_float(o.get("amount_total")), fecha_doc, etiqueta)

        lwant = _pick_fields(
            "pos.order.line",
            ["full_product_name", "name", "qty", "price_unit", "price_subtotal", "price_subtotal_incl"],
        )
        if not lwant:
            lwant = ["name"]
        lrecs = models.execute_kw(
            db, uid, key,
            "pos.order.line", "read",
            [line_ids],
            {"fields": lwant, "context": {"active_test": False}},
        )

        out: list[dict[str, Any]] = []
        total = 0.0
        for ln in (lrecs or []):
            desc = _clean_plain_text(ln.get("full_product_name") or ln.get("name") or "")
            qty = _to_float(ln.get("qty"))
            pu = _to_float(ln.get("price_unit"))
            sub = _to_float(ln.get("price_subtotal"))
            if not sub:
                sub = _to_float(ln.get("price_subtotal_incl"))
            if not sub and qty and pu:
                sub = qty * pu
            total += sub
            out.append({"descripcion": desc, "cantidad": qty, "precio_unitario": pu, "subtotal": sub})

        if not total:
            total = _to_float(o.get("amount_total"))

        return (out, total, fecha_doc, etiqueta)

    def _odoo_move_lines(move_id: int) -> tuple[list[dict[str, Any]], float, str]:
        """Return (lines, total, fecha_doc) for account.move."""
        models, db, uid, key = _odoo_client()

        mwant = _pick_fields("account.move", ["invoice_line_ids", "line_ids", "amount_total", "invoice_date", "create_date"])
        if not mwant:
            mwant = ["invoice_line_ids", "amount_total"]
        recs = models.execute_kw(
            db, uid, key,
            "account.move", "read",
            [[move_id]],
            {"fields": mwant, "context": {"active_test": False}},
        )
        if not recs:
            return ([], 0.0, "")

        mv = recs[0]
        fecha_doc = str(mv.get("invoice_date") or mv.get("create_date") or "")

        line_ids = mv.get("invoice_line_ids") or mv.get("line_ids") or []
        line_ids = [int(x) for x in (line_ids or []) if x]
        if not line_ids:
            return ([], _to_float(mv.get("amount_total")), fecha_doc)

        lwant = _pick_fields(
            "account.move.line",
            ["display_type", "name", "quantity", "price_unit", "price_subtotal", "price_total"],
        )
        if not lwant:
            lwant = ["name", "quantity", "price_unit"]

        lrecs = models.execute_kw(
            db, uid, key,
            "account.move.line", "read",
            [line_ids],
            {"fields": lwant, "context": {"active_test": False}},
        )

        out: list[dict[str, Any]] = []
        total = 0.0
        for ln in (lrecs or []):
            if ln.get("display_type"):
                continue
            desc = _clean_plain_text(ln.get("name") or "")
            qty = _to_float(ln.get("quantity"))
            pu = _to_float(ln.get("price_unit"))
            sub = _to_float(ln.get("price_subtotal"))
            if not sub and qty and pu:
                sub = qty * pu
            total += sub
            out.append({"descripcion": desc, "cantidad": qty, "precio_unitario": pu, "subtotal": sub})

        if not total:
            total = _to_float(mv.get("amount_total"))

        return (out, total, fecha_doc)
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

        lines, total, fecha_doc = _odoo_sale_lines(order_id)
        etiqueta = _clean_plain_text(codigo_envio)
        doc_label = str(o.get("name") or "")

        return {
            "doc_label": doc_label,
            "etiqueta": etiqueta,
            "fecha_doc": fecha_doc,
            "lines": lines,
            "total": total,

            "pedido": doc_label,
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
            "codigo_envio": etiqueta,
        }

    def _odoo_pos_order_detail(pos_id: int) -> dict[str, Any]:
        models, db, uid, key = _odoo_client()

        pos_fields = _model_fields("pos.order")
        want = ["id", "name", "partner_id"]
        for f in ("note", "pos_reference", "ticket_code", "tracking_number", "date_order", "create_date"):
            if f in pos_fields:
                want.append(f)
        want = list(dict.fromkeys(want))

        recs = models.execute_kw(
            db, uid, key,
            "pos.order", "read",
            [[pos_id]],
            {"fields": want, "context": {"active_test": False}},
        )
        if not recs:
            raise KeyError("pos_not_found")

        o = recs[0]
        partner_id = _value_to_ids(o.get("partner_id"))[0] if o.get("partner_id") else 0

        partner: dict[str, Any] = {}
        if partner_id:
            pfields = _model_fields("res.partner")
            pwant = ["id", "name", "phone", "mobile", "email", "street", "street2", "city", "zip"]
            pwant = [f for f in pwant if f in pfields] or ["id", "name"]
            precs = models.execute_kw(
                db, uid, key,
                "res.partner", "read",
                [[partner_id]],
                {"fields": pwant, "context": {"active_test": False}},
            )
            partner = precs[0] if precs else {}

        direccion_parts = [partner.get("street") or "", partner.get("street2") or ""]
        direccion = " ".join([p for p in direccion_parts if p]).strip()
        if partner.get("city"):
            direccion = (direccion + ", " if direccion else "") + str(partner.get("city"))
        if partner.get("zip"):
            direccion = (direccion + " " if direccion else "") + str(partner.get("zip"))

        telefono = str(partner.get("mobile") or partner.get("phone") or "")

        codigo = ""
        for f in ("tracking_number", "ticket_code", "pos_reference"):
            if o.get(f):
                codigo = str(o.get(f) or "")
                break

        obs = _clean_plain_text(o.get("note") or "")

        lines, total, fecha_doc, etiqueta = _odoo_pos_lines(pos_id)
        doc_label = str(o.get("name") or "")

        return {
            "doc_label": doc_label,
            "etiqueta": etiqueta,
            "fecha_doc": fecha_doc,
            "lines": lines,
            "total": total,

            "pedido": doc_label,
            "nombre": partner.get("name", "") if partner else (o.get("partner_id") or [None, ""])[1] if o.get("partner_id") else "",
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": obs,
            "envio": "",
            "zona": "",
            "client_order_ref": _clean_plain_text(o.get("pos_reference") or ""),
            "id_web": "",
            "meli_cart": "",
            "id_meli": "",
            "codigo_envio": etiqueta,
        }

    def _odoo_move_detail(move_id: int) -> dict[str, Any]:
        models, db, uid, key = _odoo_client()

        move_fields = _model_fields("account.move")
        want = ["id", "name", "partner_id"]
        for f in ("invoice_origin", "payment_reference", "ref", "narration", "invoice_date", "create_date", "state"):
            if f in move_fields:
                want.append(f)
        for f in ("x_studio_x_studio_pedido_web", "x_studio_pedido_meli", "x_studio_x_studio_pedido_meli"):
            if f in move_fields:
                want.append(f)

        want = list(dict.fromkeys(want))

        recs = models.execute_kw(
            db, uid, key,
            "account.move", "read",
            [[move_id]],
            {"fields": want, "context": {"active_test": False}},
        )
        if not recs:
            raise KeyError("move_not_found")

        mv = recs[0]
        partner_id = _value_to_ids(mv.get("partner_id"))[0] if mv.get("partner_id") else 0

        partner: dict[str, Any] = {}
        if partner_id:
            pfields = _model_fields("res.partner")
            pwant = ["id", "name", "phone", "mobile", "email", "street", "street2", "city", "zip"]
            pwant = [f for f in pwant if f in pfields] or ["id", "name"]
            precs = models.execute_kw(
                db, uid, key,
                "res.partner", "read",
                [[partner_id]],
                {"fields": pwant, "context": {"active_test": False}},
            )
            partner = precs[0] if precs else {}

        direccion_parts = [partner.get("street") or "", partner.get("street2") or ""]
        direccion = " ".join([p for p in direccion_parts if p]).strip()
        if partner.get("city"):
            direccion = (direccion + ", " if direccion else "") + str(partner.get("city"))
        if partner.get("zip"):
            direccion = (direccion + " " if direccion else "") + str(partner.get("zip"))

        telefono = str(partner.get("mobile") or partner.get("phone") or "")

        obs = _clean_plain_text(mv.get("narration") or "")

        inv_no = str(mv.get("name") or "")
        origin = str(mv.get("invoice_origin") or "")
        pedido = origin or inv_no

        lines, total, fecha_doc = _odoo_move_lines(move_id)

        doc_label = inv_no or origin
        if inv_no and origin and origin != inv_no:
            doc_label = f"{inv_no} ({origin})"

        return {
            "doc_label": doc_label,
            "etiqueta": "",
            "fecha_doc": fecha_doc,
            "lines": lines,
            "total": total,

            "pedido": pedido,
            "nombre": partner.get("name", "") if partner else (mv.get("partner_id") or [None, ""])[1] if mv.get("partner_id") else "",
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": obs,
            "envio": "",
            "zona": "",
            "client_order_ref": _clean_plain_text(mv.get("payment_reference") or mv.get("ref") or ""),
            "id_web": _digits_only(mv.get("x_studio_x_studio_pedido_web") or ""),
            "meli_cart": "",
            "id_meli": _digits_only(mv.get("x_studio_pedido_meli") or mv.get("x_studio_x_studio_pedido_meli") or ""),
            "codigo_envio": "",
        }

    def _odoo_doc_detail(doc_type: str, doc_id: int) -> dict[str, Any]:
        t = (doc_type or "sale").strip().lower()
        if t == "sale":
            return _odoo_order_detail(doc_id)
        if t == "pos":
            return _odoo_pos_order_detail(doc_id)
        if t == "move":
            return _odoo_move_detail(doc_id)
        raise KeyError("unknown_doc_type")
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

    def _logo_path_for_emisor(razon_social: str, ruc: str | None = None) -> str:
        brand = _brand_from_emisor(razon_social, ruc)
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

            app_log.info("pdf_start tipo=%s serie=%s nro=%s total=%s", cfe.tipo_texto, cfe.serie, cfe.numero, cfe.total)

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
                logo_path = _logo_path_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
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

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            receipt_width_mm=app.config["RECEIPT_WIDTH_MM"],
        )

    @app.get("/api/orders/search")
    def api_orders_search():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify([])
        if not _odoo_is_configured():
            return jsonify({"error": "odoo_not_configured"}), 501

        try:
            rows = _odoo_search_documents(q)
            return jsonify(rows)
        except Exception as ex:
            return jsonify({"error": "odoo_error", "detail": str(ex)}), 503
    @app.get("/api/orders/<int:order_id>")
    def api_order_detail(order_id: int):
        if not _odoo_is_configured():
            return jsonify({"error": "odoo_not_configured"}), 501

        doc_type = (request.args.get("type") or request.args.get("doc_type") or "sale").strip().lower()
        try:
            d = _odoo_doc_detail(doc_type, order_id)
            d["doc_type"] = doc_type
            return jsonify(d)
        except KeyError:
            return jsonify({"error": "not_found"}), 404
        except Exception as ex:
            return jsonify({"error": "odoo_error", "detail": str(ex)}), 503
    @app.post("/generate")
    def generate():
        if not _odoo_is_configured():
            return jsonify({"ok": False, "error": "odoo_not_configured"}), 501

        order_id = int((request.form.get("order_id") or "0") or 0)
        doc_type = (request.form.get("doc_type") or "sale").strip().lower()

        if not order_id:
            return jsonify({"ok": False, "error": "order_id_required"}), 400

        app_log.info("generate_start doc_type=%s doc_id=%s", doc_type, order_id)

        # 1) Download XML from Odoo (always from Contabilidad / account.move)
        try:
            _xml_name, xml_bytes = _odoo_get_cfe_xml_from_doc(doc_type, order_id)
        except Exception as ex:
            app_log.warning("generate_odoo_cfe_error doc_type=%s doc_id=%s err=%s", doc_type, order_id, ex)
            return jsonify({"ok": False, "error": "odoo_cfe_error", "detail": str(ex)}), 409

        # 2) Parse XML
        try:
            cfe = parse_cfe_xml(xml_bytes, default_adenda="")
            if not (cfe.adenda or "").strip():
                cfe.adenda = _default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
        except Exception as ex:
            app_log.warning("generate_parse_error doc_type=%s doc_id=%s err=%s", doc_type, order_id, ex)
            return jsonify({"ok": False, "error": "parse_error", "detail": str(ex)}), 422

        # 3) Render PDF
        try:
            out_path = generate_receipt_pdf(cfe)
            token = os.path.basename(out_path)
        except Exception as ex:
            app_log.error("pdf_error doc_type=%s doc_id=%s err=%s", doc_type, order_id, ex)
            return jsonify({"ok": False, "error": "pdf_error", "detail": str(ex)}), 500

        # Optional: open in local environment

        if app.config.get("OPEN_PDF"):
            try:
                import webbrowser
                webbrowser.open_new_tab("file://" + os.path.abspath(out_path))
            except Exception:
                pass

        pdf_url = url_for("get_pdf", filename=token, _external=False)
        app_log.info("generate_ok doc_type=%s doc_id=%s pdf=%s", doc_type, order_id, token)
        return jsonify({"ok": True, "pdf_url": pdf_url})
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
    # For local runs: python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5600")), debug=False)
