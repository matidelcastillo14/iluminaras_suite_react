from __future__ import annotations
from flask_cors import CORS

import os
import json
import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import urllib.parse
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Request, Response
from werkzeug.utils import redirect
from flask import Flask, redirect, url_for, request
from flask_login import current_user

from .extensions import db, login_manager, mail, migrate
from .models import User, PdfTemplate, Setting, PollState, ViewPermission
from .blueprints.main import bp as main_bp
from .blueprints.auth import bp as auth_bp
from .blueprints.admin import bp as admin_bp
from .blueprints.cfe_manual import bp as cfe_manual_bp
from .blueprints.cfe_auto import bp as cfe_auto_bp
from .blueprints.etiquetas import bp as etiquetas_bp
from .blueprints.rastreo import bp as rastreo_bp
from .blueprints.public_tracking import bp as public_tracking_bp
from .blueprints.cadete_flex import bp as cadete_flex_bp
from .blueprints.puerta import bp as puerta_bp
from .blueprints.batch_pedidos import bp as batch_pedidos_bp
from .blueprints.reloj_home_office import bp as reloj_home_office_bp
from .blueprints.postulaciones_public import bp as postulaciones_public_bp
from .blueprints.postulaciones_admin import bp as postulaciones_admin_bp
from .services.scheduler import start as start_scheduler
from .services.settings_sync import apply_db_settings, sync_settings_to_legacy_app
from .services.views_registry import all_view_keys, default_views_for_role
from .services.modules_registry import seed_module_flags
from .utils import can_view


def _register_static_version(app: Flask) -> None:
    """Injects a static version token for cache-busting.

    - If STATIC_VERSION env is set, uses that.
    - Otherwise, uses process start timestamp.

    Templates can use: {{ static_v }} and append it as '?v={{ static_v }}'.
    """

    v = (os.environ.get("STATIC_VERSION") or "").strip()
    if not v:
        v = str(int(time.time()))
    app.config["STATIC_VERSION"] = v

    @app.context_processor
    def _inject_static_v():
        return {"static_v": app.config.get("STATIC_VERSION")}


def _setup_logging(app: Flask) -> None:
    log_dir = os.path.join(app.root_path, "..", "logs")
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(fmt)
    handler.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    wz = logging.getLogger("werkzeug")
    wz.setLevel(logging.INFO)
    wz.addHandler(handler)


@login_manager.user_loader
def load_user(user_id: str):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None


def _seed_admin(app: Flask) -> None:
    seed_path = Path(app.root_path).parent / "instance" / "seed_admin.json"
    if not seed_path.exists():
        return
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if User.query.filter_by(username=seed.get("username")).first():
        return

    u = User(
        username=seed.get("username") or "Admin",
        email=seed.get("email") or "admin@local",
        first_name=seed.get("first_name") or "",
        last_name=seed.get("last_name") or "",
        phone=seed.get("phone"),
        role=seed.get("role") or "admin",
        must_change_password=bool(seed.get("must_change_password")),
        is_active=True,
    )
    u.set_password(seed.get("password") or "ChangeMe12345!")
    db.session.add(u)
    db.session.commit()


def _seed_templates() -> None:
    defaults = [
        ("cfe_ticket", "Ticket CFE (Legacy)", "legacy", None, True),
        ("cfe_change", "Ticket de Cambio (Legacy)", "legacy", None, True),
        ("shipping_label", "Etiqueta Envío (Legacy)", "legacy", None, True),
        (
            "cfe_ticket",
            "Ticket CFE (Editable)",
            "layout_json",
            json.dumps(
                {
                    "page": {"width_mm": 72.1, "min_height_mm": 220},
                    "elements": [
                        {
                            "type": "text",
                            "x_mm": 3,
                            "y_mm": 8,
                            "w_mm": 66,
                            "size": 10,
                            "bold": True,
                            "align": "center",
                            "value": "{{ cfe.emisor_razon_social }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 3,
                            "y_mm": 18,
                            "w_mm": 66,
                            "size": 9,
                            "align": "center",
                            "value": "RUC {{ cfe.emisor_ruc }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 3,
                            "y_mm": 28,
                            "w_mm": 66,
                            "size": 9,
                            "align": "center",
                            "value": "{{ cfe.tipo_texto }} {{ cfe.serie }}{{ cfe.numero }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 3,
                            "y_mm": 38,
                            "w_mm": 66,
                            "size": 9,
                            "align": "center",
                            "value": "{{ cfe.fecha_emision }}",
                        },
                        {
                            "type": "repeat",
                            "dataset": "items",
                            "x_mm": 3,
                            "y_mm": 54,
                            "row_height_mm": 4.5,
                            "children": [
                                {
                                    "type": "text",
                                    "x_mm": 0,
                                    "y_mm": 0,
                                    "w_mm": 44,
                                    "size": 8,
                                    "value": "{{ item.descripcion|default('') }}",
                                },
                                {
                                    "type": "text",
                                    "x_mm": 44,
                                    "y_mm": 0,
                                    "w_mm": 8,
                                    "size": 8,
                                    "align": "right",
                                    "value": "{{ item.cantidad }}",
                                },
                                {
                                    "type": "text",
                                    "x_mm": 52,
                                    "y_mm": 0,
                                    "w_mm": 14,
                                    "size": 8,
                                    "align": "right",
                                    "value": "{{ item.total_linea }}",
                                },
                            ],
                        },
                        {
                            "type": "text",
                            "x_mm": 3,
                            "y_mm": 190,
                            "w_mm": 66,
                            "size": 9,
                            "bold": True,
                            "align": "right",
                            "value": "TOTAL {{ cfe.total }}",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            False,
        ),
        (
            "shipping_label",
            "Etiqueta Envío (Editable)",
            "layout_json",
            json.dumps(
                {
                    "page": {"width_mm": 100, "min_height_mm": 150},
                    "elements": [
                        {
                            "type": "text",
                            "x_mm": 6,
                            "y_mm": 14,
                            "w_mm": 88,
                            "size": 14,
                            "bold": True,
                            "value": "{{ label.nombre }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 6,
                            "y_mm": 32,
                            "w_mm": 88,
                            "size": 11,
                            "value": "{{ label.direccion }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 6,
                            "y_mm": 54,
                            "w_mm": 88,
                            "size": 11,
                            "value": "Tel: {{ label.telefono }}",
                        },
                        {
                            "type": "text",
                            "x_mm": 6,
                            "y_mm": 72,
                            "w_mm": 88,
                            "size": 11,
                            "bold": True,
                            "value": "Pedido: {{ label.pedido }}",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            False,
        ),
    ]

    for ttype, name, engine, layout, active in defaults:
        exists = PdfTemplate.query.filter_by(template_type=ttype, name=name).first()
        if exists:
            continue
        pt = PdfTemplate(
            template_type=ttype,
            name=name,
            engine=engine,
            layout_json=layout,
            is_active=active,
        )
        db.session.add(pt)
    db.session.commit()

    for ttype in {"cfe_ticket", "cfe_change", "shipping_label"}:
        actives = PdfTemplate.query.filter_by(template_type=ttype, is_active=True).all()
        if len(actives) > 1:
            for r in actives[1:]:
                r.is_active = False
            db.session.commit()


def _ensure_schema() -> None:
    """Crea tablas faltantes en DB."""
    try:
        db.create_all()
        try:
            from sqlalchemy import inspect, text

            insp = inspect(db.engine)
            cols = {c.get("name") for c in (insp.get_columns("batch_orders") or [])}
            if "order_date" not in cols:
                db.session.execute(text("ALTER TABLE batch_orders ADD COLUMN order_date TIMESTAMP NULL"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_batch_orders_order_date ON batch_orders (order_date)"))
                db.session.commit()

            user_cols = {c.get("name") for c in (insp.get_columns("users") or [])}
            if "attendance_ref_code" not in user_cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN attendance_ref_code VARCHAR(64) NULL"))
                db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_users_attendance_ref_code ON users (attendance_ref_code)"))
                db.session.commit()
            if "home_office_clock_enabled" not in user_cols:
                db.session.execute(text("ALTER TABLE users ADD COLUMN home_office_clock_enabled BOOLEAN NOT NULL DEFAULT FALSE"))
                db.session.commit()

            zk_cols = {c.get("name") for c in (insp.get_columns("zk_events") or [])} if "zk_events" in insp.get_table_names() else set()
            if zk_cols and "event_source" not in zk_cols:
                db.session.execute(text("ALTER TABLE zk_events ADD COLUMN event_source VARCHAR(32) NULL DEFAULT 'zk_device'"))
                db.session.execute(text("UPDATE zk_events SET event_source='zk_device' WHERE event_source IS NULL"))
                db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
    except Exception:
        pass


def _seed_view_permissions() -> None:
    keys = all_view_keys()
    if not keys:
        return

    roles: set[str] = set(["admin", "operator", "readonly", "ventas", "deposito", "cadeteria"])
    for r in db.session.query(User.role).distinct().all():
        if r and r[0]:
            roles.add(str(r[0]))

    for role in roles:
        defaults = default_views_for_role(role)
        for k in keys:
            exists = ViewPermission.query.filter_by(role=role, view_key=k).first()
            if exists:
                continue
            enabled = k in defaults
            db.session.add(ViewPermission(role=role, view_key=k, enabled=enabled))
    db.session.commit()


class SuiteLoginGate:
    """WSGI middleware: require Suite authenticated session for legacy apps."""

    def __init__(self, suite_app: Flask, wsgi_app, view_key: str | None = None):
        self.suite_app = suite_app
        self.wsgi_app = wsgi_app
        self.si = suite_app.session_interface
        self.view_key = view_key

    def __call__(self, environ, start_response):
        path = (environ.get("PATH_INFO") or "")
        if path.startswith("/static"):
            return self.wsgi_app(environ, start_response)

        req = Request(environ)
        sess = self.si.open_session(self.suite_app, req)
        user_id = None
        try:
            user_id = sess.get("_user_id") if sess else None
        except Exception:
            user_id = None

        if user_id:
            if self.view_key:
                try:
                    with self.suite_app.app_context():
                        u = User.query.get(int(user_id))
                        if not u or not getattr(u, "is_active", True):
                            raise RuntimeError("inactive")
                        if not can_view(self.view_key, user=u):
                            return Response("Acceso denegado", status=403)(environ, start_response)
                except Exception:
                    return Response("Acceso denegado", status=403)(environ, start_response)

            return self.wsgi_app(environ, start_response)

        full = (environ.get("SCRIPT_NAME") or "") + path
        qs = (environ.get("QUERY_STRING") or "")
        if qs:
            full = full + "?" + qs
        target = "/auth/login?next=" + urllib.parse.quote(full)
        return redirect(target)(environ, start_response)


def _mount_legacy_apps(app: Flask) -> None:
    """Mount the three legacy apps under /_legacy/* without altering their behavior/UI."""
    try:
        from legacy_apps.cfe_manual.app import create_app as create_cfe_manual_app
        from legacy_apps.etiquetas.app import create_app as create_etiquetas_app
        from legacy_apps.cfe_auto.app import create_app as create_cfe_auto_app
    except Exception as ex:
        app.logger.error("legacy_import_error: %s", ex)
        return

    cfe_manual = create_cfe_manual_app()
    etiquetas = create_etiquetas_app()
    cfe_auto = create_cfe_auto_app()

    for legacy in (cfe_manual, etiquetas, cfe_auto):
        legacy.config["SECRET_KEY"] = app.config.get("SECRET_KEY")
        legacy.secret_key = app.config.get("SECRET_KEY")
        legacy.config["SESSION_COOKIE_NAME"] = app.config.get("SESSION_COOKIE_NAME", "session")

        legacy.config["SQLALCHEMY_DATABASE_URI"] = app.config.get("SQLALCHEMY_DATABASE_URI")
        legacy.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        try:
            db.init_app(legacy)
        except Exception:
            pass

        try:
            sync_settings_to_legacy_app(app, legacy)
        except Exception:
            pass

    app.extensions.setdefault("legacy_apps", {})
    app.extensions["legacy_apps"].update({
        "cfe_manual": cfe_manual,
        "etiquetas": etiquetas,
        "cfe_auto": cfe_auto,
    })

    mounts = {
        "/_legacy/cfe_manual": SuiteLoginGate(app, cfe_manual.wsgi_app, view_key="cfe_manual"),
        "/_legacy/etiquetas": SuiteLoginGate(app, etiquetas.wsgi_app, view_key="etiquetas"),
        "/_legacy/cfe_auto": SuiteLoginGate(app, cfe_auto.wsgi_app, view_key="cfe_auto"),
    }

    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, mounts)


def create_app() -> Flask:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    from .config import Config

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    origins = app.config.get("FRONTEND_ORIGINS") or ["http://localhost:3000", "http://127.0.0.1:3000"]

    CORS(
        app,
        supports_credentials=True,
        resources={
            r"/auth/api/*": {"origins": origins},
            r"/etiquetas/*": {"origins": origins},
            r"/rastreo/*": {"origins": origins},
            r"/cfe/auto/*": {"origins": origins},
        },
    )

    _register_static_version(app)
    _setup_logging(app)

    gen_dir = Path(app.root_path).parent / app.config["GENERATED_DIR"]
    gen_dir.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"

    with app.app_context():
        if app.config.get("AUTO_CREATE_SCHEMA", True):
            _ensure_schema()

        if not PollState.query.get(1):
            db.session.add(PollState(id=1, last_poll_ts=0.0))
            db.session.commit()

        _seed_admin(app)
        _seed_templates()
        _seed_view_permissions()
        apply_db_settings(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(cfe_manual_bp)
    app.register_blueprint(cfe_auto_bp)
    app.register_blueprint(etiquetas_bp)
    app.register_blueprint(rastreo_bp)
    app.register_blueprint(public_tracking_bp)
    app.register_blueprint(cadete_flex_bp)
    app.register_blueprint(puerta_bp)
    app.register_blueprint(batch_pedidos_bp)
    app.register_blueprint(reloj_home_office_bp)
    app.register_blueprint(postulaciones_public_bp, url_prefix="/postulaciones")
    app.register_blueprint(postulaciones_admin_bp)

    _mount_legacy_apps(app)

    @app.before_request
    def _force_password_change():
        if not current_user.is_authenticated:
            return None
        if getattr(current_user, "must_change_password", False):
            p = request.path or ""
            allowed = (
                p.startswith("/auth/change-password")
                or p.startswith("/auth/logout")
                or p.startswith("/static")
                or p.startswith("/auth/request-reset")
                or p.startswith("/auth/reset")
            )
            if not allowed:
                return redirect(url_for("auth.change_password"))
        return None

    @app.context_processor
    def _inject_acl_helpers():
        from .utils import can_view
        from .services.tracking_labels import label_event, label_status
        from .services.timezone import format_dt
        return {
            "can_view": can_view,
            "label_event": label_event,
            "label_status": label_status,
            "format_dt": format_dt,
        }

    return app


# -----------------------------------------------------------------------------
# Public-only app factories (isolated ports / hostnames)
# -----------------------------------------------------------------------------


def _create_core_app() -> Flask:
    """Create a Flask app with core config + extensions + DB bootstrap."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    from .config import Config

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    origins = app.config.get("FRONTEND_ORIGINS") or ["http://localhost:3000", "http://127.0.0.1:3000"]

    CORS(
        app,
        supports_credentials=True,
        resources={
            r"/auth/api/*": {"origins": origins},
            r"/etiquetas/*": {"origins": origins},
            r"/rastreo/*": {"origins": origins},
            r"/cfe/auto/*": {"origins": origins},
        },
    )

    _register_static_version(app)
    _setup_logging(app)

    gen_dir = Path(app.root_path).parent / app.config["GENERATED_DIR"]
    gen_dir.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"

    with app.app_context():
        if app.config.get("AUTO_CREATE_SCHEMA", True):
            _ensure_schema()

        if not PollState.query.get(1):
            db.session.add(PollState(id=1, last_poll_ts=0.0))
            db.session.commit()

        _seed_admin(app)
        _seed_templates()
        _seed_view_permissions()
        try:
            from .services.modules_registry import seed_module_flags
            seed_module_flags()
        except Exception:
            pass
        apply_db_settings(app)

    return app


def create_public_tracking_app() -> Flask:
    """Public-only app exposing ONLY Public Tracking at '/'."""
    app = _create_core_app()
    app.config["PORT"] = int(os.environ.get("PUBLIC_TRACKING_PORT", "5801"))
    app.register_blueprint(public_tracking_bp, url_prefix="/")

    try:
        from flask import abort
        from .services.modules_registry import is_module_public_enabled

        @app.before_request
        def _public_tracking_module_gate():
            if not is_module_public_enabled("admin_tracking", default=True):
                abort(404)
    except Exception:
        pass

    return app


def create_postulaciones_public_app() -> Flask:
    """Public-only app exposing ONLY Postulaciones public form at '/'."""
    app = _create_core_app()
    app.config["PORT"] = int(os.environ.get("POSTULACIONES_PUBLIC_PORT", "5802"))
    app.register_blueprint(postulaciones_public_bp, url_prefix="/")

    try:
        from flask import abort
        from .services.modules_registry import is_module_public_enabled

        @app.before_request
        def _postulaciones_public_module_gate():
            if not is_module_public_enabled("postulaciones", default=True):
                abort(404)
    except Exception:
        pass

    return app