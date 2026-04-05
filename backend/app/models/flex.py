from __future__ import annotations

from datetime import datetime

from ..extensions import db


class FlexCommunity(db.Model):
    __tablename__ = "flex_communities"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), nullable=False, unique=True, index=True)
    name = db.Column(db.String(128), nullable=False, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)

    # Branding / UI (optional)
    color_hex = db.Column(db.String(16), nullable=True, default="#49C8C4")

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FlexAssignment(db.Model):
    """Bloqueo de "este shipment lo tiene este cadete".

    No reemplaza el tracking core; es sólo para evitar doble toma.
    """

    __tablename__ = "flex_assignments"

    id = db.Column(db.Integer, primary_key=True)

    # Un (1) registro por shipment. Se reutiliza: state RELEASED => puede reasignarse.
    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), nullable=False, unique=True, index=True)
    cadete_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey("flex_communities.id"), nullable=True, index=True)

    # IN_CART | IN_ROUTE | RELEASED
    state = db.Column(db.String(16), nullable=False, default="IN_CART", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    released_at = db.Column(db.DateTime, nullable=True)




class FlexRoute(db.Model):
    __tablename__ = "flex_routes"

    id = db.Column(db.Integer, primary_key=True)
    cadete_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey("flex_communities.id"), nullable=True, index=True)

    # DRAFT | EN_ROUTE | FINISHED | CANCELLED
    state = db.Column(db.String(16), nullable=False, default="DRAFT", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    meta_json = db.Column(db.Text, nullable=True)


class FlexStop(db.Model):
    __tablename__ = "flex_stops"

    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey("flex_routes.id"), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False, default=0, index=True)

    address_text = db.Column(db.String(256), nullable=False)
    city = db.Column(db.String(64), nullable=True)
    zip = db.Column(db.String(16), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # PENDING | ARRIVING | DONE | ISSUE
    state = db.Column(db.String(16), nullable=False, default="PENDING", index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class FlexStopShipment(db.Model):
    __tablename__ = "flex_stop_shipments"

    stop_id = db.Column(db.Integer, db.ForeignKey("flex_stops.id"), primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), primary_key=True)


class FlexShipmentSnapshot(db.Model):
    __tablename__ = "flex_shipment_snapshot"

    shipment_id = db.Column(db.Integer, db.ForeignKey("tracking_shipments.id"), primary_key=True)

    recipient_name = db.Column(db.String(128), nullable=True)
    phone = db.Column(db.String(64), nullable=True)

    street = db.Column(db.String(128), nullable=True)
    street2 = db.Column(db.String(128), nullable=True)
    city = db.Column(db.String(64), nullable=True)
    zip = db.Column(db.String(16), nullable=True)

    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    raw_json = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
