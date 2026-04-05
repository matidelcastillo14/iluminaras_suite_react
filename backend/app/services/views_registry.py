from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewDef:
    key: str
    label: str
    group: str = "General"


VIEW_DEFS: list[ViewDef] = [
    # Legacy (wrappers + mounts)
    ViewDef(key="cfe_manual", label="CFE Manual", group="Legacy"),
    ViewDef(key="cfe_auto", label="CFE Auto", group="Legacy"),
    ViewDef(key="etiquetas", label="Etiquetas", group="Legacy"),

    # Inventario
    ViewDef(key="batch_pedidos", label="Pedidos por Batch", group="Inventario"),

    # Rastreo
    ViewDef(key="rastreo_deposito", label="Rastreo - Depósito", group="Rastreo"),
    ViewDef(key="cadete_flex", label="Cadete Flex", group="Rastreo"),
    ViewDef(key="rastreo_ventas", label="Administración de Tracking", group="Rastreo"),

    # RRHH
    ViewDef(key="admin_postulaciones", label="Admin Postulaciones", group="RRHH"),
    ViewDef(key="puerta", label="Apertura de Puerta", group="Seguridad"),
    ViewDef(key="reloj_home_office", label="Reloj Home Office", group="RRHH"),
]


DEFAULT_ROLE_VIEWS: dict[str, set[str]] = {
    # Mantener compatibilidad con usos existentes
    "operator": {"cfe_manual", "cfe_auto", "etiquetas"},
    "readonly": set(),
    "ventas": {"rastreo_ventas", "etiquetas"},
    "deposito": {"rastreo_deposito", "batch_pedidos"},
    # Cadetería: rastreo + nuevo módulo Flex
    "cadeteria": {"cadete_flex"},
}


def default_views_for_role(role: str) -> set[str]:
    if role == "admin":
        return set(all_view_keys())
    return set(DEFAULT_ROLE_VIEWS.get(role or "", set()))


def all_view_keys() -> list[str]:
    return [v.key for v in VIEW_DEFS]