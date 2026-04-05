from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import PollState, ProcessedItem, PdfTemplate
from . import cfe_legacy_engine


def _looks_like_cfe_xml(data: bytes) -> bool:
    """Filtro rápido para evitar intentar parsear XML que no es CFE."""
    if not data:
        return False
    head = data[:8192].lower()
    return (b"cfe.dgi.gub.uy" in head) or (b"<cfe" in head) or (b":cfe" in head)

from .layout_renderer import render_layout_pdf

def _configure_engine():
    cfe_legacy_engine.configure(current_app.config, root_path=current_app.root_path, logger=current_app.logger)

def poll_once() -> dict[str, Any]:
    """Ejecuta 1 ciclo de polling y genera PDFs nuevos (si hay)."""
    _configure_engine()

    if not current_app.config.get("CFE_POLL_ENABLED", False):
        return {"ok": False, "error": "poll_disabled"}

    st = PollState.query.get(1)
    if not st:
        st = PollState(id=1, last_poll_ts=0.0)
        db.session.add(st)
        db.session.commit()

    # rate-limit similar
    import time
    now = time.time()
    if (now - float(st.last_poll_ts or 0.0)) < float(current_app.config.get("CFE_POLL_SECONDS") or 5) * 0.5:
        return {"ok": True, "skipped": True, "reason": "rate_limited"}
    st.last_poll_ts = now
    db.session.commit()

    recent = cfe_legacy_engine._odoo_recent_cfe_xml_attachments(int(current_app.config.get("CFE_SCAN_LIMIT") or 200))
    # normalize sort newest first
    recent_sorted = sorted(recent, key=lambda x: (str(x.get("create_date") or ""), abs(int(x.get("att_id") or 0))), reverse=True)

    created = 0
    updated = 0
    errors = 0

    skipped_non_cfe = 0
    error_samples: list[dict[str, str]] = []
    out_dir = Path(current_app.root_path).parent / current_app.config["GENERATED_DIR"]
    out_dir.mkdir(parents=True, exist_ok=True)

    tpl_receipt = PdfTemplate.get_active("cfe_ticket")
    tpl_change = PdfTemplate.get_active("cfe_change")

    for att in recent_sorted:
        aid = int(att.get("att_id") or 0)
        if not aid:
            continue

        src_type = "attachment" if aid > 0 else "edi_doc"
        src_id = aid if aid > 0 else (-aid)

        row = ProcessedItem.query.filter_by(source_type=src_type, source_id=src_id).first()
        if row and row.status == "ok":
            continue

        if not row:
            row = ProcessedItem(source_type=src_type, source_id=src_id, status="error", attempts=0)
            db.session.add(row)
            try:
                db.session.commit()
                created += 1
            except IntegrityError:
                db.session.rollback()
                row = ProcessedItem.query.filter_by(source_type=src_type, source_id=src_id).first()
                if not row:
                    continue

        try:
            # get xml bytes
            if src_type == "attachment":
                name, data, _mime = cfe_legacy_engine._odoo_download_attachment(src_id)
                xml_bytes = data
            else:
                name, xml_bytes = cfe_legacy_engine._odoo_get_cfe_xml_from_edi_doc(src_id)

                if not _looks_like_cfe_xml(xml_bytes):
                    skipped_non_cfe += 1
                    row.status = "skipped"
                    row.last_error = "skip_not_cfe"
                    db.session.commit()
                    continue
            cfe = cfe_legacy_engine.parse_cfe_xml(xml_bytes, default_adenda="")
            if not (cfe.adenda or "").strip():
                try:
                    cfe.adenda = cfe_legacy_engine._default_adenda_for_emisor(cfe.emisor_razon_social, cfe.emisor_ruc)
                except Exception:
                    pass

            # render receipt
            if tpl_receipt and tpl_receipt.engine == "layout_json" and tpl_receipt.layout_json:
                layout = json.loads(tpl_receipt.layout_json)
                out_path = out_dir / f"cfe_{cfe.serie}{cfe.numero}_{src_type}{src_id}.pdf"
                ctx = {"cfe": cfe.__dict__, "items": [it.__dict__ for it in cfe.items]}
                render_layout_pdf(layout, ctx, str(out_path))
                receipt_path = str(out_path)
            else:
                receipt_path = cfe_legacy_engine.generate_receipt_pdf(cfe)

            change_path = None
            if tpl_change and tpl_change.engine == "layout_json" and tpl_change.layout_json:
                layout = json.loads(tpl_change.layout_json)
                out_path = out_dir / f"cambio_{cfe.serie}{cfe.numero}_{src_type}{src_id}.pdf"
                ctx = {"cfe": cfe.__dict__, "items": [it.__dict__ for it in cfe.items]}
                render_layout_pdf(layout, ctx, str(out_path))
                change_path = str(out_path)
            else:
                change_path = cfe_legacy_engine.generate_change_ticket_pdf(cfe)

            row.status = "ok"
            row.attempts = int(row.attempts or 0) + 1
            row.last_error = None

            row.cfe_serie = str(getattr(cfe, "serie", "") or "")
            row.cfe_numero = str(getattr(cfe, "numero", "") or "")
            row.receptor_nombre = str(getattr(cfe, "receptor_nombre", "") or "")

            # store relative paths
            row.pdf_receipt_path = os.path.basename(receipt_path)
            row.pdf_change_path = os.path.basename(change_path) if change_path else None

            db.session.commit()
            updated += 1

        except Exception as ex:
            row.status = "error"
            row.attempts = int(row.attempts or 0) + 1
            row.last_error = str(ex)
            db.session.commit()
            errors += 1

            if len(error_samples) < 10:
                error_samples.append({"src_type": src_type, "src_id": str(src_id), "error": str(ex)[:400]})
                current_app.logger.error("poll error %s/%s: %s", src_type, src_id, str(ex)[:400])
            continue
    return {"ok": True, "created": created, "updated": updated, "errors": errors, "skipped_non_cfe": skipped_non_cfe, "error_samples": error_samples}
