from __future__ import annotations


STATUS_LABELS_ES: dict[str, str] = {
    "LABEL_CREATED": "Etiqueta generada",
    "PICKING_STARTED": "Preparación iniciada",
    "READY_FOR_DISPATCH": "Listo para despacho",
    "STOCK_MISSING": "Falta de stock (a resolver)",
    "STOCK_RESOLVED": "Stock resuelto",
    "IN_TRANSIT": "En tránsito (cadetería)",
    "OUT_FOR_DELIVERY": "En reparto",
    "ON_ROUTE_TO_DELIVERY": "En camino a tu entrega",
    "DELIVERY_FAILED": "Entrega fallida",
    "DEFERRED_NEXT_SHIFT": "Pendiente (siguiente turno)",
    "RETURN_TO_DEPOT_REQUESTED": "Devuelto a depósito (pendiente confirmación)",
    "RETURNED": "Devuelto a depósito",
    "DELIVERED": "Entregado",
}


EVENT_LABELS_ES: dict[str, str] = {
    "LABEL_CREATED": "Etiqueta generada",
    "PICKING_STARTED": "Inicio de preparación",
    "READY_FOR_DISPATCH": "Listo para despacho",
    "STOCK_MISSING": "Falta de stock",
    "SALES_DECISION": "Decisión de ventas",
    "IN_TRANSIT": "En tránsito (cadetería)",
    "OUT_FOR_DELIVERY": "Inicio de reparto",
    "ON_ROUTE_TO_DELIVERY": "En camino a entregar",
    "BACK_TO_OUT_FOR_DELIVERY": "Vuelve a reparto",
    "DELIVERED": "Entregado",
    "DELIVERY_FAILED": "No entregado",
    "DEFERRED_NEXT_SHIFT": "Siguiente turno",
    "RETURN_TO_DEPOT_REQUESTED": "Devuelto a depósito (pendiente)",
    "RETURNED": "Devuelto a depósito",
    "SALES_OVERRIDE": "Cambio de estado (Ventas)",
    "SALES_RESET": "Reset (Ventas)",
}


def label_status(code: str | None) -> str:
    c = (code or "").strip()
    return STATUS_LABELS_ES.get(c, c or "-")


def label_event(code: str | None) -> str:
    c = (code or "").strip()
    return EVENT_LABELS_ES.get(c, c or "-")
