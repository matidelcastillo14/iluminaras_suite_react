from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from flask import current_app

from ..extensions import db
from ..models import ImportedBatch, BatchOrder
from . import odoo_readonly


BASE_LINK = "https://iluimport.com/odoo/sales/"


def _parse_odoo_dt(v: Any) -> datetime | None:
    """Parsea datetime de Odoo.

    Odoo suele devolver strings "YYYY-MM-DD HH:MM:SS" (a veces con microsegundos).
    Guardamos naive UTC.
    """
    if not v:
        return None
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    # intento ISO
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


@dataclass
class PollResult:
    status: str  # ok | no_new | error | odoo_not_configured
    imported: bool = False
    batch_name: str | None = None
    odoo_batch_id: int | None = None
    picking_count: int = 0
    order_count: int = 0
    message: str | None = None


def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _make_invoice_status(n_factura: str, estado_factura: str) -> str:
    """
    Determina si un número de factura se considera definitivamente facturado.

    La regla de negocio vigente indica que solo se deben marcar como
    ``"Facturado"`` los comprobantes posteados cuya cadena de factura
    comienza con ``E-`` (o ``e-``), es decir, documentos que representan
    comprobantes fiscales emitidos (como e-TK o e-FC).  Cualquier otro
    número –por ejemplo aquellos que empiezan con ``*``– se considera
    pendiente y se debe mostrar un enlace de navegación en lugar del
    texto "Facturado".
    """
    nf = (n_factura or "").strip()
    st = (estado_factura or "").strip().lower()
    # Debe estar posteada
    if st != "posted":
        return ""
    # Número no puede ser vacío ni barra
    if not nf or nf == "/":
        return ""
    # Prefijo no válido (movimiento pendiente)
    if nf.startswith("*"):
        return ""
    # Solo se consideran facturados números que comienzan con "e-" (sin importar mayúsculas)
    if nf.lower().startswith("e-"):
        return "Facturado"
    return ""


def _is_facturado_move(m: dict[str, Any]) -> bool:
    """Define si un account.move se considera 'facturado'.

    Regla base:
      - state == 'posted'
      - name asignado y distinto de '/'
      - move_type permitido (out_invoice/out_receipt/out_refund)

    Nota: No usamos prefijos de CFE; la verificación debe ser la misma lógica
    que usa CFE Manual al decidir si ya existe factura desde Ventas o Contabilidad.
    """
    if not m:
        return False
    st = str(m.get("state") or "").strip().lower()
    if st != "posted":
        return False
    name = str(m.get("name") or "").strip()
    if not name or name == "/":
        return False
    mt = str(m.get("move_type") or "").strip()
    if mt and mt not in {"out_invoice", "out_receipt", "out_refund"}:
        return False
    return True


def _tokenize_refs(s: str) -> list[str]:
    """Tokeniza invoice_origin / payment_reference de forma conservadora."""
    if not s:
        return []
    raw = str(s)
    # separadores típicos: coma, punto y coma, salto de línea
    parts = re.split(r"[\n\r,;]+", raw)
    out: list[str] = []
    for p in parts:
        t = p.strip()
        if t:
            out.append(t)
    return out


def _split_invoice_origin(origin: str) -> list[str]:
    """invoice_origin puede venir como 'S12345, S12346'."""
    if not origin:
        return []
    return [x.strip() for x in str(origin).split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Helper functions for building invoice links
#
# The business rules for the "Ver" button link are as follows:
#   * If the invoice is considered fully facturado (i.e. ``_make_invoice_status``
#     returns ``"Facturado"``), we simply display the text "Facturado" in
#     place of a link.
#   * Otherwise, if there is an invoice number available, we append only the
#     numeric part of that number to the standard invoicing URL.  This allows
#     users to jump directly to the invoice in Odoo even when the invoice is
#     still in draft or is represented as a movement like "* 72089".
#   * If no invoice number is available at all, we fall back to the base
#     invoicing URL ending with ``/invoicing/``.  This behaves the same as the
#     original implementation while still allowing for later refreshes to
#     populate the digits when they become known.

def _make_link_factura(so_id: int, n_factura: str, estado_factura: str) -> str:
    """Compute the appropriate ``link_factura`` value for a sale order.

    :param so_id: the ``sale.order`` identifier
    :param n_factura: the raw invoice name/number
    :param estado_factura: the invoice state returned by Odoo
    :returns: either the literal string ``"Facturado"`` when the invoice is
      considered fully posted, or a URL to the invoicing screen for the
      associated order with the numeric invoice id appended when available.
    """
    # If posted and the invoice has a valid identifier then we mark as facturado
    if _make_invoice_status(n_factura or "", estado_factura or "") == "Facturado":
        return "Facturado"
    # Extract just the digits of the invoice number (e.g. "* 72089" -> "72089")
    digits = _digits_only(n_factura or "")
    base = f"{BASE_LINK}{so_id}/invoicing/"
    return base + digits if digits else base


def _refresh_pending_invoices(models, dbname, uid, key, max_rows: int = 250) -> int:
    """Actualiza en DB pedidos que aún no tienen factura pero ya fueron facturados en Odoo.

    Retorna cantidad de filas actualizadas.
    """
    updated = 0

    # 0) Backfill de fecha de pedido (sale.order.date_order) para registros ya importados.
    #    En la primera versión, la fecha solo se guardaba al insertar. Si ya existían filas,
    #    quedaban en NULL para siempre. Acá rellenamos de a tandas.
    missing_date = (
        BatchOrder.query.filter(BatchOrder.order_date.is_(None))
        .order_by(BatchOrder.created_at.desc(), BatchOrder.id.desc())
        .limit(max_rows)
        .all()
    )
    if missing_date:
        so_ids = [int(r.sale_order_id) for r in missing_date if r.sale_order_id]
        if so_ids:
            try:
                sale_rows = models.execute_kw(
                    dbname,
                    uid,
                    key,
                    "sale.order",
                    "search_read",
                    [[("id", "in", so_ids)]],
                    {"fields": ["id", "date_order"]},
                )
                date_by_id = {int(x["id"]): _parse_odoo_dt(x.get("date_order")) for x in sale_rows if x.get("id")}
                for r in missing_date:
                    dt = date_by_id.get(int(r.sale_order_id or 0))
                    if dt and r.order_date is None:
                        r.order_date = dt
                        updated += 1
            except Exception:
                # No romper el refresco de facturas por esto
                pass

    # 1) Normalizar: si ya tiene n_factura y está posteada, asegurar estado Facturado.
    #    Si NO está posteada, no marcar como facturado.
    fixed = (
        BatchOrder.query.filter(BatchOrder.n_factura.isnot(None))
        .filter(BatchOrder.n_factura != "")
        .limit(max_rows)
        .all()
    )
    for r in fixed:
        # Para registros ya facturados o con factura conocida, construir el link deseado.
        desired = _make_link_factura(int(r.sale_order_id or 0), r.n_factura or "", r.estado_factura or "")
        if (r.link_factura or "") != desired:
            r.link_factura = desired
            updated += 1

    # 2) Pedidos pendientes (no marcados como Facturado).
    #    Incluimos todos los pedidos cuyo ``link_factura`` no sea exactamente
    #    "Facturado" (esto cubre enlaces vacíos, enlaces base y enlaces con
    #    dígitos).  De este modo, los lotes antiguos también son revisados
    #    periódicamente en busca de una factura nueva.
    pending = (
        BatchOrder.query.filter((BatchOrder.link_factura.is_(None)) | (BatchOrder.link_factura != "Facturado"))
        .order_by(BatchOrder.created_at.desc(), BatchOrder.id.desc())
        .limit(max_rows)
        .all()
    )
    if not pending:
        return updated

    # 2.1) Leer sale.order (para usar invoice_ids cuando existan)
    so_ids = sorted({int(p.sale_order_id) for p in pending if p.sale_order_id})
    so_rows: list[dict[str, Any]] = []
    if so_ids:
        try:
            so_rows = models.execute_kw(
                dbname,
                uid,
                key,
                "sale.order",
                "read",
                [so_ids],
                {"fields": ["id", "name", "invoice_ids"]},
            ) or []
        except Exception:
            so_rows = []

    so_by_id = {int(so.get("id") or 0): so for so in so_rows if so.get("id")}

    # 2.2) Cache de moves por id (para invoice_ids)
    inv_ids_all: set[int] = set()
    for so in so_rows:
        inv_ids = so.get("invoice_ids") or []
        if isinstance(inv_ids, list):
            for x in inv_ids:
                try:
                    inv_ids_all.add(int(x))
                except Exception:
                    continue

    moves_by_id: dict[int, dict[str, Any]] = {}
    if inv_ids_all:
        try:
            moves = models.execute_kw(
                dbname,
                uid,
                key,
                "account.move",
                "read",
                [sorted(inv_ids_all)],
                {"fields": ["id", "name", "state", "move_type", "invoice_origin", "payment_reference"]},
            ) or []
            moves_by_id = {int(m.get("id") or 0): m for m in moves if m.get("id")}
        except Exception:
            moves_by_id = {}

    # 2.3) Fallback: traer moves posteados y mapear por tokens (invoice_origin / payment_reference)
    origins = sorted({(p.sale_order_ref or "").strip() for p in pending if (p.sale_order_ref or "").strip()})
    token_map: dict[str, list[dict[str, Any]]] = {}
    if origins:
        try:
            moves2 = models.execute_kw(
                dbname,
                uid,
                key,
                "account.move",
                "search_read",
                [[("state", "=", "posted"), ("move_type", "in", ["out_invoice", "out_receipt", "out_refund"]), "|", ("invoice_origin", "!=", False), ("payment_reference", "!=", False)]],
                {"fields": ["id", "name", "state", "move_type", "invoice_origin", "payment_reference"], "limit": 5000, "order": "id desc", "context": {"active_test": False}},
            ) or []
        except Exception:
            moves2 = []

        origin_set = set(origins)
        for m in moves2:
            if not _is_facturado_move(m):
                continue
            toks = _tokenize_refs(str(m.get("invoice_origin") or "")) + _tokenize_refs(str(m.get("payment_reference") or ""))
            for t in toks:
                if t in origin_set:
                    token_map.setdefault(t, []).append(m)

    # 2.4) Resolver y actualizar
    for r in pending:
        so = so_by_id.get(int(r.sale_order_id or 0)) or {"id": r.sale_order_id, "name": r.sale_order_ref or "", "invoice_ids": []}
        n_factura, estado = _resolve_invoice_for_order(models, dbname, uid, key, so, moves_by_id=moves_by_id)

        # si no resolvió por invoice_ids, intentar por token_map (evita reconsultar 3000 moves por pedido)
        if not n_factura:
            rel = token_map.get((r.sale_order_ref or "").strip()) or []
            n_factura, estado = _pick_best_invoice(rel)

        # Siempre que encontremos una factura asociada, actualizar el enlace.  Si
        # corresponde, el helper devolverá "Facturado"; de lo contrario, url+digits.
        if n_factura:
            desired = _make_link_factura(int(r.sale_order_id or 0), str(n_factura or ""), str(estado or ""))
            # Actualizar los campos solo si difieren para minimizar commits
            if (r.n_factura or "") != str(n_factura or ""):
                r.n_factura = str(n_factura or "")
                updated += 1
            if (r.estado_factura or "") != str(estado or ""):
                r.estado_factura = str(estado or "")
                updated += 1
            if (r.link_factura or "") != desired:
                r.link_factura = desired
                updated += 1

    return updated


def _pick_best_invoice(moves: list[dict[str, Any]]) -> tuple[str, str]:
    if not moves:
        return "", ""
    invs = [m for m in moves if m.get("move_type") == "out_invoice"] or moves

    def score(m: dict[str, Any]) -> int:
        s = 0
        if m.get("move_type") == "out_invoice":
            s += 10
        if m.get("state") == "posted":
            s += 10
        name = (m.get("name") or "").strip()
        if name and name != "/":
            s += 5
        return s

    best = sorted(invs, key=score, reverse=True)[0]
    return (best.get("name") or "", best.get("state") or "")


def _resolve_invoice_for_order(models, dbname: str, uid: int, key: str, so: dict[str, Any], moves_by_id: dict[int, dict[str, Any]] | None = None) -> tuple[str, str]:
    """Resuelve si una sale.order ya tiene factura, replicando el enfoque de CFE Manual:

    1) Primero por Ventas: sale.order.invoice_ids -> account.move.
    2) Fallback por Contabilidad: buscar account.move posteados por invoice_origin / payment_reference.

    Devuelve (n_factura, estado_factura). Si no hay factura, ('','').
    """
    so_id = int(so.get("id") or 0)
    so_name = str(so.get("name") or "").strip()

    # --- 1) Ventas: invoice_ids ---
    rel: list[dict[str, Any]] = []
    inv_ids = so.get("invoice_ids") or []
    if isinstance(inv_ids, list):
        for iid in inv_ids:
            try:
                ii = int(iid)
            except Exception:
                continue
            if moves_by_id and ii in moves_by_id:
                rel.append(moves_by_id[ii])
    if rel:
        n, st = _pick_best_invoice(rel)
        if _is_facturado_move({"name": n, "state": st, "move_type": "out_invoice"}):
            return (str(n or ""), str(st or ""))

    # --- 2) Contabilidad: invoice_origin / payment_reference ---
    if not so_name and not so_id:
        return ("", "")

    # Dominio posteado + tipos permitidos
    domain: list[Any] = [("state", "=", "posted")]
    domain.append(("move_type", "in", ["out_invoice", "out_receipt", "out_refund"]))
    # match por invoice_origin o payment_reference si existen
    # Usamos search_read amplio y filtramos por tokens, porque invoice_origin puede venir 'SO1, SO2'
    domain.append("|")
    domain.append(("invoice_origin", "!=", False))
    domain.append(("payment_reference", "!=", False))

    try:
        moves = models.execute_kw(
            dbname,
            uid,
            key,
            "account.move",
            "search_read",
            [domain],
            {
                "fields": ["id", "name", "state", "move_type", "invoice_origin", "payment_reference"],
                "limit": 3000,
                "order": "id desc",
                "context": {"active_test": False},
            },
        ) or []
    except Exception:
        moves = []

    candidates: list[dict[str, Any]] = []
    for m in moves:
        if not _is_facturado_move(m):
            continue
        # tokenizar origin y payment_ref y chequear si aparece el SO
        toks = set(_tokenize_refs(str(m.get("invoice_origin") or "")) + _tokenize_refs(str(m.get("payment_reference") or "")))
        if so_name and so_name in toks:
            candidates.append(m)

    n, st = _pick_best_invoice(candidates)
    if n and st:
        return (str(n), str(st))
    return ("", "")


def _odoo_models():
    """Return a fresh XML‑RPC models proxy along with DB credentials.

    The XML‑RPC ``ServerProxy`` object provided by ``xmlrpc.client`` is **not**
    thread safe. Sharing a single proxy across requests (for example when using
    waitress or any threaded WSGI server) leads to race conditions and
    unpredictable ``http.client`` errors such as ``CannotSendRequest`` or
    ``ResponseNotReady``. These errors appear in the logs whenever two threads
    attempt to reuse the same underlying HTTP connection at the same time.

    To avoid these issues we always create a new ``ServerProxy`` instance for
    each call. The authentication (uid) itself is cached by ``odoo_readonly``
    so there is minimal overhead in building a fresh proxy.  When the helper
    ``_odoo_models`` is available on ``odoo_readonly`` (newer versions) we
    delegate to it. Otherwise we fall back to manual construction.

    :returns: a tuple ``(models_proxy, dbname, uid, api_key)``
    :raises RuntimeError: if Odoo configuration is missing or authentication fails
    """
    # Preferred: delegate to helper from odoo_readonly if it exists.  This
    # helper returns a brand new ServerProxy along with db, uid and key.
    if hasattr(odoo_readonly, "_odoo_models"):
        try:
            return odoo_readonly._odoo_models()  # type: ignore[attr-defined]
        except Exception:
            # If the helper exists but fails, fall back to manual construction
            pass

    # Fallback: obtain (db, uid, key) from _odoo_uid().  _odoo_uid() returns
    # exactly three values, so do not attempt to unpack four.  We create a
    # fresh ServerProxy for the models endpoint on each call to ensure
    # thread safety.
    dbname, uid, key = odoo_readonly._odoo_uid()  # type: ignore[attr-defined]

    # Build a new ServerProxy using the configured URL.  The URL may have a
    # trailing slash which we strip off to avoid ``//xmlrpc/2/object``.
    url = str(current_app.config.get("ODOO_URL") or "").strip().rstrip("/")
    if not url:
        raise RuntimeError("odoo_not_configured")
    import xmlrpc.client  # imported here to avoid a hard dependency if unused
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
    return models, dbname, uid, key


def _import_batch_basic(models, dbname, uid, key, odoo_batch_id: int, batch_name: str, picking_ids: list[int]) -> int:
    """Importa 1 batch a DB (sin intentar resolver facturas en este paso).

    Motivo: el estado de facturación se refresca aparte y SOLO considera facturas posteadas.
    """
    if ImportedBatch.query.filter_by(odoo_batch_id=odoo_batch_id).first():
        return 0

    ib = ImportedBatch(
        odoo_batch_id=odoo_batch_id,
        batch_name=batch_name,
        imported_at=datetime.utcnow(),
        picking_count=len(picking_ids or []),
        order_count=0,
    )
    db.session.add(ib)
    db.session.flush()

    # pickings -> sale orders
    pickings = []
    if picking_ids:
        pickings = models.execute_kw(
            dbname,
            uid,
            key,
            "stock.picking",
            "read",
            [picking_ids],
            {"fields": ["id", "origin", "sale_id"]},
        )

    sale_ids: set[int] = set()
    origins: set[str] = set()
    for p in pickings or []:
        sid = (p.get("sale_id") or [None])[0]
        if sid:
            sale_ids.add(int(sid))
        o = p.get("origin")
        if isinstance(o, str) and o.strip():
            origins.add(o.strip())

    so_fields = [
        "id",
        "name",
        "date_order",
        "x_studio_id_web_pedidos",
        "x_meli_cart",
        "x_studio_meli",
        "partner_id",
        "partner_shipping_id",
        "amount_total",
    ]

    sale_orders: list[dict[str, Any]] = []
    if sale_ids:
        sale_orders.extend(models.execute_kw(dbname, uid, key, "sale.order", "read", [sorted(sale_ids)], {"fields": so_fields}))

    loaded_ids = {int(so.get("id") or 0) for so in sale_orders if so.get("id")}
    for o in sorted(origins):
        sos = models.execute_kw(
            dbname,
            uid,
            key,
            "sale.order",
            "search_read",
            [[("name", "=", o)]],
            {"fields": so_fields, "limit": 50, "order": "id desc"},
        )
        for so in sos:
            sid = int(so.get("id") or 0)
            if sid and sid not in loaded_ids:
                sale_orders.append(so)
                loaded_ids.add(sid)

    if not sale_orders:
        ib.order_count = 0
        return 0

    # partners
    partner_ids: set[int] = set()
    ship_ids: set[int] = set()
    for so in sale_orders:
        pid = (so.get("partner_id") or [None])[0]
        sid = (so.get("partner_shipping_id") or [None])[0]
        if pid:
            partner_ids.add(int(pid))
        if sid:
            ship_ids.add(int(sid))

    all_partner_ids = sorted(partner_ids | ship_ids)
    partners: list[dict[str, Any]] = []
    if all_partner_ids:
        partners = models.execute_kw(
            dbname,
            uid,
            key,
            "res.partner",
            "read",
            [all_partner_ids],
            {"fields": ["id", "name", "street", "street2", "city", "state_id", "zip", "country_id"]},
        )
    partners_by_id = {int(p["id"]): p for p in partners if p.get("id")}

    def fmt_addr(p: dict[str, Any] | None) -> str:
        if not p:
            return ""
        parts: list[str] = []
        for k in ("street", "street2", "city", "zip"):
            v = p.get(k)
            if v:
                parts.append(str(v))
        st = p.get("state_id")
        if isinstance(st, list) and len(st) >= 2 and st[1]:
            parts.append(str(st[1]))
        c = p.get("country_id")
        if isinstance(c, list) and len(c) >= 2 and c[1]:
            parts.append(str(c[1]))
        parts = [re.sub(r"\s+", " ", x).strip() for x in parts if x and str(x).strip()]
        return ", ".join(parts)

    now = datetime.utcnow()
    inserted = 0
    for so in sale_orders:
        so_id = int(so.get("id") or 0)
        if not so_id:
            continue

        cliente = ""
        if isinstance(so.get("partner_id"), list) and len(so["partner_id"]) >= 2:
            cliente = str(so["partner_id"][1] or "")

        addr_partner = None
        ship_id = (so.get("partner_shipping_id") or [None])[0]
        partner_id = (so.get("partner_id") or [None])[0]
        if ship_id:
            addr_partner = partners_by_id.get(int(ship_id))
        if addr_partner is None and partner_id:
            addr_partner = partners_by_id.get(int(partner_id))
        direccion = fmt_addr(addr_partner)

        id_meli = (
            odoo_readonly._clean_html_text(so.get("x_studio_meli"))
            if hasattr(odoo_readonly, "_clean_html_text")
            else str(so.get("x_studio_meli") or "")
        )

        bo = BatchOrder(
            imported_batch_id=ib.id,
            created_at=now,
            sale_order_id=so_id,
            sale_order_ref=str(so.get("name") or ""),
            order_date=_parse_odoo_dt(so.get("date_order")),
            id_web=str(so.get("x_studio_id_web_pedidos") or ""),
            id_melicart=str(so.get("x_meli_cart") or ""),
            id_meli=id_meli,
            cliente=cliente,
            direccion=direccion,
            monto_compra=so.get("amount_total"),
            n_factura="",
            estado_factura="",
            # Si no está facturado, el botón 'Ir' usa este link.
            link_factura=f"{BASE_LINK}{so_id}/invoicing/",
        )
        db.session.add(bo)
        inserted += 1

    ib.order_count = inserted
    return inserted


def ensure_min_rows(target_rows: int, max_batches: int = 5) -> dict[str, Any]:
    """Backfill: si en DB hay menos de target_rows pedidos, importa batches anteriores hasta llenar."""
    try:
        models, dbname, uid, key = _odoo_models()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    imported_batches = 0
    imported_orders = 0

    try:
        before_id: int | None = None
        while BatchOrder.query.count() < target_rows and imported_batches < max_batches:
            # Traer batches más recientes (y si hace falta, seguir hacia atrás)
            domain = [] if before_id is None else [("id", "<", before_id)]
            batch_rows = models.execute_kw(
                dbname,
                uid,
                key,
                "stock.picking.batch",
                "search_read",
                [domain],
                {"fields": ["id", "name", "picking_ids"], "limit": 50, "order": "id desc"},
            )
            if not batch_rows:
                break

            # preparar siguiente ventana (más viejo)
            try:
                before_id = min(int(x.get("id") or 0) for x in batch_rows if x.get("id"))
            except Exception:
                before_id = None

            imported_any = False
            for br in batch_rows:
                bid = int(br.get("id") or 0)
                bname = str(br.get("name") or "").strip()
                pids = br.get("picking_ids") or []
                if not bid or not bname:
                    continue
                if ImportedBatch.query.filter_by(odoo_batch_id=bid).first():
                    continue

                ins = _import_batch_basic(models, dbname, uid, key, bid, bname, pids)
                # refrescar facturas posteadas para lo nuevo
                try:
                    _refresh_pending_invoices(models, dbname, uid, key)
                except Exception:
                    pass
                db.session.commit()
                imported_batches += 1
                imported_any = True
                imported_orders += int(ins or 0)
                if BatchOrder.query.count() >= target_rows or imported_batches >= max_batches:
                    break

            if not imported_any:
                break

        return {"ok": True, "imported_batches": imported_batches, "imported_orders_hint": imported_orders}

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("batch_backfill_error")
        return {"ok": False, "error": str(e)}


def poll_once() -> dict[str, Any]:
    """Escanea el último batch de Odoo y lo importa si es nuevo."""
    try:
        models, dbname, uid, key = _odoo_models()
    except Exception as e:
        if str(e) in ("odoo_not_configured", "odoo_auth_failed"):
            return PollResult(status=str(e)).__dict__
        return PollResult(status="error", message=str(e)).__dict__

    try:
        # 1) último batch
        batch_rows = models.execute_kw(
            dbname,
            uid,
            key,
            "stock.picking.batch",
            "search_read",
            [[]],
            {"fields": ["id", "name", "picking_ids"], "limit": 1, "order": "id desc"},
        )
        if not batch_rows:
            return PollResult(status="ok", imported=False, message="no_batches").__dict__

        br = batch_rows[0]
        odoo_batch_id = int(br.get("id") or 0)
        batch_name = str(br.get("name") or "").strip()
        picking_ids = br.get("picking_ids") or []
        if not odoo_batch_id or not batch_name:
            return PollResult(status="error", message="invalid_batch").__dict__

        # 2) comparar contra último importado
        last = ImportedBatch.query.order_by(ImportedBatch.odoo_batch_id.desc()).first()
        if last and int(last.odoo_batch_id) >= odoo_batch_id:
            # Aunque no haya batch nuevo, refrescar facturas pendientes
            try:
                upd = _refresh_pending_invoices(models, dbname, uid, key)
                if upd:
                    db.session.commit()
            except Exception:
                db.session.rollback()
            return PollResult(status="no_new", imported=False, batch_name=batch_name, odoo_batch_id=odoo_batch_id).__dict__

        # 3) crear ImportedBatch
        ib = ImportedBatch(
            odoo_batch_id=odoo_batch_id,
            batch_name=batch_name,
            imported_at=datetime.utcnow(),
            picking_count=len(picking_ids),
            order_count=0,
        )
        db.session.add(ib)
        db.session.flush()  # get ib.id

        # 4) pickings -> sale orders
        pickings = []
        if picking_ids:
            pickings = models.execute_kw(
                dbname,
                uid,
                key,
                "stock.picking",
                "read",
                [picking_ids],
                {"fields": ["id", "origin", "sale_id"]},
            )

        sale_ids: set[int] = set()
        origins: set[str] = set()
        for p in pickings or []:
            sid = (p.get("sale_id") or [None])[0]
            if sid:
                sale_ids.add(int(sid))
            o = p.get("origin")
            if isinstance(o, str) and o.strip():
                origins.add(o.strip())

        # 5) leer sale orders (por id + fallback por origin)
        so_fields = [
            "id",
            "name",
            "date_order",
            "x_studio_id_web_pedidos",
            "x_meli_cart",
            "x_studio_meli",
            "partner_id",
            "partner_shipping_id",
            "amount_total",
            "invoice_ids",
        ]

        sale_orders: list[dict[str, Any]] = []
        if sale_ids:
            sale_orders.extend(
                models.execute_kw(dbname, uid, key, "sale.order", "read", [sorted(sale_ids)], {"fields": so_fields})
            )

        loaded_ids = {int(so.get("id") or 0) for so in sale_orders if so.get("id")}
        # fallback por origin (solo si no está ya)
        for o in sorted(origins):
            sos = models.execute_kw(
                dbname,
                uid,
                key,
                "sale.order",
                "search_read",
                [[("name", "=", o)]],
                {"fields": so_fields, "limit": 50, "order": "id desc"},
            )
            for so in sos:
                sid = int(so.get("id") or 0)
                if sid and sid not in loaded_ids:
                    sale_orders.append(so)
                    loaded_ids.add(sid)

        # si no hay sale orders, igual guardamos el batch para no re-importar en loop
        if not sale_orders:
            ib.order_count = 0
            db.session.commit()
            return PollResult(
                status="ok",
                imported=True,
                batch_name=batch_name,
                odoo_batch_id=odoo_batch_id,
                picking_count=len(picking_ids),
                order_count=0,
                message="no_sale_orders_resolved",
            ).__dict__

        # 6) partners
        partner_ids: set[int] = set()
        ship_ids: set[int] = set()
        for so in sale_orders:
            pid = (so.get("partner_id") or [None])[0]
            sid = (so.get("partner_shipping_id") or [None])[0]
            if pid:
                partner_ids.add(int(pid))
            if sid:
                ship_ids.add(int(sid))

        all_partner_ids = sorted(partner_ids | ship_ids)
        partners: list[dict[str, Any]] = []
        if all_partner_ids:
            partners = models.execute_kw(
                dbname,
                uid,
                key,
                "res.partner",
                "read",
                [all_partner_ids],
                {"fields": ["id", "name", "street", "street2", "city", "state_id", "zip", "country_id"]},
            )
        partners_by_id = {int(p["id"]): p for p in partners if p.get("id")}

        def fmt_addr(p: dict[str, Any] | None) -> str:
            if not p:
                return ""
            parts: list[str] = []
            for k in ("street", "street2", "city", "zip"):
                v = p.get(k)
                if v:
                    parts.append(str(v))
            st = p.get("state_id")
            if isinstance(st, list) and len(st) >= 2 and st[1]:
                parts.append(str(st[1]))
            c = p.get("country_id")
            if isinstance(c, list) and len(c) >= 2 and c[1]:
                parts.append(str(c[1]))
            parts = [re.sub(r"\s+", " ", x).strip() for x in parts if x and str(x).strip()]
            return ", ".join(parts)

        # 7) facturas (enfoque: Ventas por invoice_ids + Contabilidad por tokens)
        invoices_by_so_id: dict[int, tuple[str, str]] = {}
        can_read_moves = True
        try:
            # simple permission test
            models.execute_kw(dbname, uid, key, "account.move", "fields_get", [], {"attributes": ["type"]})
        except Exception:
            can_read_moves = False

        moves_by_id: dict[int, dict[str, Any]] = {}
        token_map: dict[str, list[dict[str, Any]]] = {}

        if can_read_moves:
            # Cache moves referenciados por invoice_ids
            inv_ids_all: set[int] = set()
            for so in sale_orders:
                inv_ids = so.get("invoice_ids") or []
                if isinstance(inv_ids, list):
                    for x in inv_ids:
                        try:
                            inv_ids_all.add(int(x))
                        except Exception:
                            continue
            inv_ids_all = {int(x) for x in inv_ids_all if int(x) > 0}
            if inv_ids_all:
                try:
                    moves = models.execute_kw(
                        dbname,
                        uid,
                        key,
                        "account.move",
                        "read",
                        [sorted(inv_ids_all)],
                        {"fields": ["id", "name", "state", "move_type", "invoice_origin", "payment_reference"]},
                    ) or []
                    moves_by_id = {int(m.get("id") or 0): m for m in moves if m.get("id")}
                except Exception:
                    moves_by_id = {}

            # Token-map (invoice_origin / payment_reference) para evitar falsos positivos + evitar N consultas
            origin_set = {str(so.get("name") or "").strip() for so in sale_orders if str(so.get("name") or "").strip()}
            if origin_set:
                try:
                    moves2 = models.execute_kw(
                        dbname,
                        uid,
                        key,
                        "account.move",
                        "search_read",
                        [[("state", "=", "posted"), ("move_type", "in", ["out_invoice", "out_receipt", "out_refund"]), "|", ("invoice_origin", "!=", False), ("payment_reference", "!=", False)]],
                        {"fields": ["id", "name", "state", "move_type", "invoice_origin", "payment_reference"], "limit": 5000, "order": "id desc", "context": {"active_test": False}},
                    ) or []
                except Exception:
                    moves2 = []
                for m in moves2:
                    if not _is_facturado_move(m):
                        continue
                    toks = _tokenize_refs(str(m.get("invoice_origin") or "")) + _tokenize_refs(str(m.get("payment_reference") or ""))
                    for t in toks:
                        if t in origin_set:
                            token_map.setdefault(t, []).append(m)

            # Resolver por pedido
            for so in sale_orders:
                so_id = int(so.get("id") or 0)
                so_name = str(so.get("name") or "").strip()
                n, st = "", ""

                # A) Ventas
                inv_ids = so.get("invoice_ids") or []
                rel: list[dict[str, Any]] = []
                if isinstance(inv_ids, list):
                    for iid in inv_ids:
                        try:
                            ii = int(iid)
                        except Exception:
                            continue
                        if ii in moves_by_id:
                            rel.append(moves_by_id[ii])
                if rel:
                    n, st = _pick_best_invoice(rel)

                # B) Contabilidad (solo si todavía no hay factura válida)
                if _make_invoice_status(n, st) != "Facturado" and so_name:
                    rel2 = token_map.get(so_name) or []
                    n2, st2 = _pick_best_invoice(rel2)
                    if _make_invoice_status(n2, st2) == "Facturado":
                        n, st = n2, st2

                invoices_by_so_id[so_id] = (str(n or ""), str(st or ""))
        else:
            for so in sale_orders:
                so_id = int(so.get("id") or 0)
                invoices_by_so_id[so_id] = ("", "")

        # 8) insertar BatchOrder rows
        now = datetime.utcnow()
        inserted = 0
        for so in sale_orders:
            so_id = int(so.get("id") or 0)
            if not so_id:
                continue

            # cliente
            cliente = ""
            if isinstance(so.get("partner_id"), list) and len(so["partner_id"]) >= 2:
                cliente = str(so["partner_id"][1] or "")

            # direccion (prefer ship)
            addr_partner = None
            ship_id = (so.get("partner_shipping_id") or [None])[0]
            partner_id = (so.get("partner_id") or [None])[0]
            if ship_id:
                addr_partner = partners_by_id.get(int(ship_id))
            if addr_partner is None and partner_id:
                addr_partner = partners_by_id.get(int(partner_id))
            direccion = fmt_addr(addr_partner)

            id_meli = odoo_readonly._clean_html_text(so.get("x_studio_meli")) if hasattr(odoo_readonly, "_clean_html_text") else str(so.get("x_studio_meli") or "")  # type: ignore[attr-defined]

            n_factura, estado_factura = invoices_by_so_id.get(so_id, ("", ""))
            # Construir link_factura según reglas de negocio: "Facturado" para
            # comprobantes posteados, de lo contrario base+digits si hay número.
            link_factura = _make_link_factura(so_id, n_factura, estado_factura)

            bo = BatchOrder(
                imported_batch_id=ib.id,
                created_at=now,
                sale_order_id=so_id,
                sale_order_ref=str(so.get("name") or ""),
                order_date=_parse_odoo_dt(so.get("date_order")),
                id_web=str(so.get("x_studio_id_web_pedidos") or ""),
                id_melicart=str(so.get("x_meli_cart") or ""),
                id_meli=id_meli,
                cliente=cliente,
                direccion=direccion,
                monto_compra=so.get("amount_total"),
                n_factura=str(n_factura or ""),
                estado_factura=str(estado_factura or ""),
                link_factura=str(link_factura or ""),
            )
            db.session.add(bo)
            inserted += 1

        ib.order_count = inserted

        # Refrescar facturas de pedidos pendientes (incluye los recién insertados)
        try:
            _refresh_pending_invoices(models, dbname, uid, key)
        except Exception:
            pass

        db.session.commit()

        return PollResult(
            status="ok",
            imported=True,
            batch_name=batch_name,
            odoo_batch_id=odoo_batch_id,
            picking_count=len(picking_ids),
            order_count=inserted,
        ).__dict__

    except Exception as e:
        current_app.logger.exception("batch_poller_error")
        # rollback this transaction
        try:
            db.session.rollback()
        except Exception:
            pass
        return PollResult(status="error", message=str(e)).__dict__
