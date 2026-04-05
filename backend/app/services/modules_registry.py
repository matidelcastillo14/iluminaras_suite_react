from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..models.setting import Setting


@dataclass(frozen=True)
class ModuleDef:
    key: str
    label: str
    internal_view_keys: tuple[str, ...]
    has_public: bool = False
    public_label: str | None = None  # optional label for UI column


MODULE_DEFS: tuple[ModuleDef, ...] = (
    ModuleDef(key="cfe_manual", label="CFE Manual", internal_view_keys=("cfe_manual",)),
    ModuleDef(key="cfe_auto", label="CFE Auto", internal_view_keys=("cfe_auto",)),
    ModuleDef(key="etiquetas", label="Etiquetas", internal_view_keys=("etiquetas",)),
    ModuleDef(key="rastreo_deposito", label="Rastreo Depósito", internal_view_keys=("rastreo_deposito",)),
    ModuleDef(key="batch_pedidos", label="Pedidos por Batch", internal_view_keys=("batch_pedidos",)),
    ModuleDef(key="cadete_flex", label="Cadete Flex", internal_view_keys=("cadete_flex",)),
    ModuleDef(
        key="admin_tracking",
        label="Administración de Tracking",
        internal_view_keys=("rastreo_ventas",),
        has_public=True,
        public_label="Tracking Público",
    ),
    ModuleDef(key="puerta", label="Apertura de Puerta", internal_view_keys=("puerta",)),
    ModuleDef(key="reloj_home_office", label="Reloj Home Office", internal_view_keys=("reloj_home_office",)),
    ModuleDef(
        key="postulaciones",
        label="Postulaciones",
        internal_view_keys=("admin_postulaciones",),
        has_public=True,
        public_label="Postulaciones Públicas",
    ),
)


def all_modules() -> tuple[ModuleDef, ...]:
    return MODULE_DEFS


def module_for_view(view_key: str) -> ModuleDef | None:
    vk = (view_key or "").strip()
    if not vk:
        return None
    for m in MODULE_DEFS:
        if vk in m.internal_view_keys:
            return m
    return None


def _key(module_key: str, kind: str) -> str:
    mk = (module_key or "").strip().upper()
    kd = (kind or "").strip().upper()
    return f"MODULE_{mk}_{kd}_ENABLED"


def internal_setting_key(module_key: str) -> str:
    return _key(module_key, "INTERNAL")


def public_setting_key(module_key: str) -> str:
    return _key(module_key, "PUBLIC")


def is_module_internal_enabled(module_key: str, default: bool = True) -> bool:
    try:
        v = (Setting.get(internal_setting_key(module_key), "1" if default else "0") or "").strip()
        return v in ("1", "true", "True", "YES", "yes", "on", "ON")
    except Exception:
        return bool(default)


def is_module_public_enabled(module_key: str, default: bool = True) -> bool:
    try:
        v = (Setting.get(public_setting_key(module_key), "1" if default else "0") or "").strip()
        return v in ("1", "true", "True", "YES", "yes", "on", "ON")
    except Exception:
        return bool(default)


def seed_module_flags() -> None:
    """Creates missing module flags in settings, with defaults ON.

    Defaults:
      - internal: ON
      - public: ON (only for modules that have_public)
    """
    for m in MODULE_DEFS:
        ik = internal_setting_key(m.key)
        if Setting.query.get(ik) is None:
            Setting.set(ik, "1")
        if m.has_public:
            pk = public_setting_key(m.key)
            if Setting.query.get(pk) is None:
                Setting.set(pk, "1")
