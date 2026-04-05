from __future__ import annotations

from typing import Any
from jinja2 import Environment, StrictUndefined
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm as MM
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

_jinja = Environment(undefined=StrictUndefined, autoescape=False)


def _render_value(template_str: str, ctx: dict[str, Any]) -> str:
    try:
        tpl = _jinja.from_string(template_str or "")
        return tpl.render(**ctx)
    except Exception:
        return str(template_str or "")


def render_layout_pdf(layout: dict[str, Any], ctx: dict[str, Any], out_path: str) -> str:
    """
    Renderiza un PDF usando un layout JSON (editor visual).

    Layout esperado:
      - page.width_mm (float)
      - page.min_height_mm (float, opcional)
      - elements: lista de elementos

    Elementos:
      - {type:'text', x_mm, y_mm, font, size, bold, align, value}
      - {type:'repeat', dataset:'items', x_mm, y_mm, row_height_mm, children:[text...]}

    Coordenadas: y_mm es distancia desde el TOP.
    """
    page = layout.get("page") or {}
    width_mm = float(page.get("width_mm") or 72.1)
    min_height_mm = float(page.get("min_height_mm") or 120)

    elements = layout.get("elements") or []

    # calcular alto necesario
    max_y = 0.0
    for el in elements:
        t = el.get("type")
        if t == "text":
            y = float(el.get("y_mm") or 0) + float(el.get("h_mm") or 4)
            max_y = max(max_y, y)
        elif t == "repeat":
            base_y = float(el.get("y_mm") or 0)
            rh = float(el.get("row_height_mm") or 4.5)
            dataset = ctx.get(el.get("dataset") or "") or []
            rows = len(dataset) if isinstance(dataset, list) else 0
            max_y = max(max_y, base_y + rows * rh + 5)

    height_mm = max(min_height_mm, max_y + 10)

    # ReportLab usa puntos; mm es un factor (NO una función)
    c = canvas.Canvas(out_path, pagesize=(width_mm * MM, height_mm * MM))

    def _draw_text(x_mm: float, y_mm_from_top: float, w_mm: float, txt: str, el: dict[str, Any]) -> None:
        size = float(el.get("size") or 9)
        bold = bool(el.get("bold"))
        font = el.get("font") or ("Helvetica-Bold" if bold else "Helvetica")
        align = (el.get("align") or "left").lower()

        c.setFont(font, size)

        x = x_mm * MM
        y = (height_mm - y_mm_from_top) * MM  # reportlab y desde abajo
        w = w_mm * MM

        if align == "center":
            c.drawCentredString(x + w / 2, y, txt)
        elif align == "right":
            c.drawRightString(x + w, y, txt)
        else:
            c.drawString(x, y, txt)

    for el in elements:
        t = el.get("type")
        if t == "text":
            x_mm0 = float(el.get("x_mm") or 0)
            y_mm_top = float(el.get("y_mm") or 0)
            w_mm0 = float(el.get("w_mm") or (width_mm - x_mm0))
            val = _render_value(str(el.get("value") or ""), ctx)
            _draw_text(x_mm0, y_mm_top, w_mm0, val, el)

        elif t == "qr":
            x_mm0 = float(el.get("x_mm") or 0)
            y_mm_top = float(el.get("y_mm") or 0)
            size_mm = float(el.get("size_mm") or el.get("w_mm") or 24)
            val = _render_value(str(el.get("value") or ""), ctx)
            if val.strip():
                qr = QrCodeWidget(val.strip())
                bounds = qr.getBounds()
                bw = bounds[2] - bounds[0]
                bh = bounds[3] - bounds[1]
                d = Drawing(size_mm * MM, size_mm * MM, transform=[(size_mm * MM) / bw, 0, 0, (size_mm * MM) / bh, 0, 0])
                d.add(qr)
                x = x_mm0 * MM
                y = (height_mm - y_mm_top - size_mm) * MM
                renderPDF.draw(d, c, x, y)

        elif t == "repeat":
            dataset_name = str(el.get("dataset") or "items")
            dataset = ctx.get(dataset_name) or []
            if not isinstance(dataset, list):
                continue

            base_x = float(el.get("x_mm") or 0)
            base_y = float(el.get("y_mm") or 0)
            row_h = float(el.get("row_height_mm") or 4.5)
            children = el.get("children") or []

            for i, item in enumerate(dataset):
                row_ctx = dict(ctx)
                row_ctx["item"] = item
                row_y = base_y + i * row_h

                for ch in children:
                    if (ch.get("type") or "text") != "text":
                        continue
                    x_mm0 = base_x + float(ch.get("x_mm") or 0)
                    y_mm_top = row_y + float(ch.get("y_mm") or 0)
                    w_mm0 = float(ch.get("w_mm") or (width_mm - x_mm0))
                    val = _render_value(str(ch.get("value") or ""), row_ctx)
                    _draw_text(x_mm0, y_mm_top, w_mm0, val, ch)

    c.showPage()
    c.save()
    return out_path