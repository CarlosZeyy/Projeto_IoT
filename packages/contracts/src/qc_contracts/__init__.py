"""Shared enums and Pydantic schemas (contract v0, docs/architecture.md section 3).

The contract version is ``__version__`` (semver). Changes follow the ``contrato-api`` skill (R-04).
"""

from qc_contracts.defects import is_defective
from qc_contracts.enums import (
    GRADE_ORDER,
    CaptureMode,
    Grade,
    ObjectType,
    Source,
    grade_from_index,
    grade_index,
)
from qc_contracts.labels import (
    CAPTURE_MODE_LABELS_PT,
    GRADE_LABELS_PT,
    OBJECT_TYPE_LABELS_PT,
    SOURCE_LABELS_PT,
)
from qc_contracts.schemas import (
    DEVICE_ID_PATTERN,
    LOT_ID_PATTERN,
    MAX_BATCH_SIZE,
    MAX_FUTURE_SKEW,
    MAX_LATENCY_MS,
    MODEL_VERSION_PATTERN,
    SHA256_PATTERN,
    BatchCreate,
    BatchResult,
    HealthResponse,
    InspectionCreate,
    InspectionCreated,
    InspectionRead,
    LotSummary,
    MetricsSummary,
    Page,
    SpcExcludedLot,
    SpcPoint,
    SpcResponse,
    TimeseriesPoint,
)

__version__ = "0.2.0"

__all__ = [
    "CAPTURE_MODE_LABELS_PT",
    "DEVICE_ID_PATTERN",
    "GRADE_LABELS_PT",
    "GRADE_ORDER",
    "LOT_ID_PATTERN",
    "MAX_BATCH_SIZE",
    "MAX_FUTURE_SKEW",
    "MAX_LATENCY_MS",
    "MODEL_VERSION_PATTERN",
    "OBJECT_TYPE_LABELS_PT",
    "SHA256_PATTERN",
    "SOURCE_LABELS_PT",
    "BatchCreate",
    "BatchResult",
    "CaptureMode",
    "Grade",
    "HealthResponse",
    "InspectionCreate",
    "InspectionCreated",
    "InspectionRead",
    "LotSummary",
    "MetricsSummary",
    "ObjectType",
    "Page",
    "Source",
    "SpcExcludedLot",
    "SpcPoint",
    "SpcResponse",
    "TimeseriesPoint",
    "__version__",
    "grade_from_index",
    "grade_index",
    "is_defective",
]
