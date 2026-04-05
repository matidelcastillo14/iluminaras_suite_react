from __future__ import annotations

import html as _html
import re
import xmlrpc.client
import threading
from functools import lru_cache

# xmlrpc.client.ServerProxy no es thread-safe en multi-thread (waitress).
_ODOO_XMLRPC_LOCK = threading.Lock()
from typing import Any

from flask import current_app


def _clean_html_text(s: Any) -> str:
    if s is None:
        return ""
    t = str(s or "")
    if not t:
        return ""
    t = re.sub(r"(?is)<\s*br\s*/?\s*>", "\n", t)
    t = re.sub(r"(?is)</\s*p\s*>", "\n", t)
    t = re.sub(r"(?is)<\s*p[^>]*>", "", t)
    t = re.sub(r"(?is)<[^>]+>", "", t)
    t = _html.unescape(t)
    t = t.replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def _odoo_cfg() -> tuple[str, str, str, str]:
    url = str(current_app.config.get("ODOO_URL") or "").strip()
    db = str(current_app.config.get("ODOO_DB") or "").strip()
    user = str(current_app.config.get("ODOO_USERNAME") or "").strip()
    key = str(current_app.config.get("ODOO_API_KEY") or "").strip()
    if not (url and db and user and key) or not current_app.config.get("ENABLE_ODOO_LOOKUP", True):
        raise RuntimeError("odoo_not_configured")
    return url, db, user, key


@lru_cache(maxsize=1)
def _odoo_uid() -> tuple[str, int, str]:
    """Devuelve (db, uid, key). Cachea solo el uid (auth)."""
    url, db, user, key = _odoo_cfg()
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, key, {})
    if not uid:
        raise RuntimeError("odoo_auth_failed")
    return db, int(uid), key

def _odoo_models() -> tuple[Any, str, int, str]:
    """Devuelve (models_proxy, db, uid, key). Proxy NUEVO por llamada."""
    url, _, _, _ = _odoo_cfg()
    db, uid, key = _odoo_uid()
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, db, uid, key


def _execute_kw(models, db, uid, key, *args, **kwargs):
    import os, json, datetime, traceback

    # args normalmente: (model, method, args_list, kwargs_dict)
    model = args[0] if len(args) > 0 else "?"
    method = args[1] if len(args) > 1 else "?"
    call_args = args[2] if len(args) > 2 else None
    call_kwargs = args[3] if len(args) > 3 else None

    def _safe(obj):
        # evita romper el log con objetos raros de xmlrpc
        try:
            return obj
        except Exception:
            return str(obj)

    def _scrub(obj):
        # oculta tokens/keys si aparecen en kwargs
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if "key" in lk or "token" in lk or "password" in lk:
                    out[k] = "***"
                else:
                    out[k] = _scrub(v)
            return out
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return _safe(obj)

    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "odoo_xmlrpc_trace.log")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "ts": stamp,
        "model": model,
        "method": method,
        "args": _scrub(call_args),
        "kwargs": _scrub(call_kwargs),
    }

    with _ODOO_XMLRPC_LOCK:
        try:
            res = models.execute_kw(db, uid, key, *args, **kwargs)
            # log de OK (solo metadata del resultado para no explotar tamaño)
            meta = {"ts": stamp, "ok": True, "model": model, "method": method, "res_type": type(res).__name__}
            if isinstance(res, list):
                meta["res_len"] = len(res)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            return res
        except Exception as e:
            err = {
                "ts": stamp,
                "ok": False,
                "model": model,
                "method": method,
                "payload": payload,
                "error": repr(e),
                "traceback": traceback.format_exc(),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(err, ensure_ascii=False) + "\n")
            raise


def get_order_full(order_id: int) -> dict[str, Any]:
    """Vista extendida del sale.order para pantalla 'Ver pedido' (solo lectura)."""
    models, db, uid, key = _odoo_models()
    order_fields = [
        "id", "name", "date_order", "partner_id", "partner_shipping_id",
        "client_order_ref", "note", "amount_total", "currency_id", "order_line",
    ]
    orders = _execute_kw(models, db, uid, key, "sale.order", "read", [[int(order_id)]], {"fields": order_fields})
    if not orders:
        raise KeyError("not_found")
    o = orders[0]

    ship_id = (o.get("partner_shipping_id") or [None])[0]
    partner_id = (o.get("partner_id") or [None])[0]
    pid = ship_id or partner_id

    partner: dict[str, Any] = {}
    if pid:
        p_fields = ["name", "street", "street2", "city", "zip", "phone", "mobile", "email"]
        ps = _execute_kw(models, db, uid, key, "res.partner", "read", [[pid]], {"fields": p_fields})
        partner = ps[0] if ps else {}

    lines: list[dict[str, Any]] = []
    line_ids = o.get("order_line") or []
    if line_ids:
        l_fields = ["name", "product_uom_qty", "price_total", "price_unit", "product_id"]
        ls = _execute_kw(models, db, uid, key, "sale.order.line", "read", [line_ids], {"fields": l_fields})
        for ln in ls:
            lines.append({
                "name": _clean_html_text(ln.get("name") or ""),
                "qty": ln.get("product_uom_qty"),
                "price_total": ln.get("price_total"),
                "price_unit": ln.get("price_unit"),
                "product": (ln.get("product_id") or [None, ""])[1] if ln.get("product_id") else "",
            })

    cur = (o.get("currency_id") or [None, ""])[1] if o.get("currency_id") else ""

    return {
        "id": o.get("id"),
        "name": o.get("name"),
        "date_order": o.get("date_order"),
        "client_order_ref": o.get("client_order_ref"),
        "note": _clean_html_text(o.get("note") or ""),
        "amount_total": o.get("amount_total"),
        "currency": cur,
        "partner": {
            "name": partner.get("name"),
            "street": partner.get("street"),
            "street2": partner.get("street2"),
            "city": partner.get("city"),
            "zip": partner.get("zip"),
            "phone": partner.get("phone") or partner.get("mobile"),
            "email": partner.get("email"),
        },
        "lines": lines,
    }