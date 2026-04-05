from __future__ import annotations

import os


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() in ("1", "true", "True", "yes", "on", "ON", "YES")


class Config:
    # Core
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-change-me")
    # Control puerta/persiana ESP32
    DOOR_CTRL_BASE_URL = os.getenv('DOOR_CTRL_BASE_URL', 'http://192.168.0.155')
    DOOR_CTRL_API_KEY = os.getenv('DOOR_CTRL_API_KEY', 'ILUMINARAS_API_M098706612')
    DOOR_CTRL_TIMEOUT_S = float(os.getenv('DOOR_CTRL_TIMEOUT_S', '2.5'))

    # DB (toma DATABASE_URL; cae a SQLite solo si no existe)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI") or "sqlite:///instance/app.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # DB bootstrap: crea tablas si faltan (solo para despliegues sin migraciones)
    AUTO_CREATE_SCHEMA = _bool("AUTO_CREATE_SCHEMA", "1")

    PORT = int(os.getenv("PORT", "5500"))

    # Timezone (IANA). Se usa para mostrar fechas/horas en la UI.
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Montevideo")

    # PDFs
    GENERATED_DIR = os.getenv("GENERATED_DIR", "generated")
    KEEP_PDFS_HOURS = float(os.getenv("KEEP_PDFS_HOURS", "178"))

    # Odoo (SOLO LECTURA)
    ENABLE_ODOO_LOOKUP = _bool("ENABLE_ODOO_LOOKUP", "1")
    ODOO_URL = os.getenv("ODOO_URL", "")
    ODOO_DB = os.getenv("ODOO_DB", "")
    ODOO_USERNAME = os.getenv("ODOO_USERNAME", "")
    ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

    # Ticket settings (72.1mm práctico)
    RECEIPT_WIDTH_MM = float(os.getenv("RECEIPT_WIDTH_MM", "72.1"))
    RECEIPT_MIN_HEIGHT_MM = float(os.getenv("RECEIPT_MIN_HEIGHT_MM", "220"))
    CHANGE_VALID_DAYS = int(os.getenv("CHANGE_VALID_DAYS", "15"))

    # Adendas
    DEFAULT_ADENDA_LUMINARAS = os.getenv("DEFAULT_ADENDA_LUMINARAS", "")
    DEFAULT_ADENDA_ESTILO_HOME = os.getenv("DEFAULT_ADENDA_ESTILO_HOME", "")
    DEFAULT_ADENDA_MAYORISTAS_URUGUAY = os.getenv("DEFAULT_ADENDA_MAYORISTAS_URUGUAY", "")
    DEFAULT_ADENDA = os.getenv("DEFAULT_ADENDA", "")

    # Logos
    LOGO_LUMINARAS_PATH = os.getenv("LOGO_LUMINARAS_PATH", "app/static/logo.png")
    LOGO_ESTILO_HOME_PATH = os.getenv("LOGO_ESTILO_HOME_PATH", "app/static/logo_estilo_home.png")
    LOGO_MAYORISTAS_URUGUAY_PATH = os.getenv("LOGO_MAYORISTAS_URUGUAY_PATH", "app/static/logo_mayoristas_uy.png")

    # Auto poll
    CFE_POLL_ENABLED = _bool("CFE_POLL_ENABLED", "0")
    CFE_POLL_SECONDS = float(os.getenv("CFE_POLL_SECONDS", "5"))
    CFE_SCAN_LIMIT = int(os.getenv("CFE_SCAN_LIMIT", "200"))

    BATCH_PEDIDOS_ROWS_LIMIT = int(os.getenv("BATCH_PEDIDOS_ROWS_LIMIT", "80"))

    LABEL_WIDTH_MM = float(os.getenv("LABEL_WIDTH_MM", "150"))
    LABEL_HEIGHT_MM = float(os.getenv("LABEL_HEIGHT_MM", "100"))

    TRACKING_SECRET = os.getenv("TRACKING_SECRET", "")

    TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
    TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

    MAIL_SERVER = os.getenv("MAIL_SERVER", "")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", "1")
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", "0")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")

    PRINT_PDF_WIDTH_MM = float(os.getenv("PRINT_PDF_WIDTH_MM", os.getenv("RECEIPT_WIDTH_MM", "72.1")))
    CHANGE_TICKET_VALID_DAYS = int(os.getenv("CHANGE_TICKET_VALID_DAYS", os.getenv("CHANGE_VALID_DAYS", "15")))
    CHANGE_TICKET_FOOTER_TEXT = os.getenv("CHANGE_TICKET_FOOTER_TEXT", "")
    CHANGE_TICKET_POLICY_URL = os.getenv("CHANGE_TICKET_POLICY_URL", "")
    CHANGE_TICKET_POLICY_URL_LUMINARAS = os.getenv("CHANGE_TICKET_POLICY_URL_LUMINARAS", os.getenv("CHANGE_TICKET_POLICY_URL", ""))
    CHANGE_TICKET_POLICY_URL_ESTILO_HOME = os.getenv("CHANGE_TICKET_POLICY_URL_ESTILO_HOME", "")
    CHANGE_TICKET_POLICY_URL_MAYORISTAS_URUGUAY = os.getenv("CHANGE_TICKET_POLICY_URL_MAYORISTAS_URUGUAY", os.getenv("CHANGE_TICKET_POLICY_URL", ""))

    LOGO_PATH = os.getenv("LOGO_PATH", os.getenv("LOGO_LUMINARAS_PATH", "app/static/logo.png"))

    ODOO_SEARCH_LIMIT = int(os.getenv("ODOO_SEARCH_LIMIT", "20"))
    ODOO_ENVIO_FIELD = os.getenv("ODOO_ENVIO_FIELD", "x_studio_envio")
    ODOO_SHIPPING_CODE_FIELD = os.getenv("ODOO_SHIPPING_CODE_FIELD", "x_studio_ship_code")
    ODOO_ZONE_FIELD = os.getenv("ODOO_ZONE_FIELD", "x_studio_zona")

    ODOO_ORDER_SEARCH_EXTRA_FIELDS = os.getenv("ODOO_ORDER_SEARCH_EXTRA_FIELDS", "")
    ODOO_PARTNER_SEARCH_EXTRA_FIELDS = os.getenv("ODOO_PARTNER_SEARCH_EXTRA_FIELDS", "")
