from .user import User
from .setting import Setting
from .template import PdfTemplate
from .poll import PollState, ProcessedItem

# Acceso por vistas (configurable)
from .view_permission import ViewPermission

# Rastreo
from .tracking import TrackingShipment, TrackingEvent, TrackingScan

# Cadete Flex (nuevo módulo)
from .flex import (
    FlexCommunity,
    FlexAssignment,
    FlexRoute,
    FlexStop,
    FlexStopShipment,
    FlexShipmentSnapshot,
)

# Postulaciones (RRHH)
from .postulaciones import JobPosition, JobApplication, JobApplicationFile

# Inventario - Pedidos por Batch
from .batch_orders import ImportedBatch, BatchOrder
