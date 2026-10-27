"""PT-BR labels for the user interface (ADR-012). Read-only mappings, one key per enum member."""

from collections.abc import Mapping
from types import MappingProxyType

from qc_contracts.enums import CaptureMode, Grade, ObjectType, Source

GRADE_LABELS_PT: Mapping[Grade, str] = MappingProxyType(
    {
        Grade.PERFECT: "perfeito",
        Grade.GOOD: "bom",
        Grade.FAIR: "mediano",
        Grade.POOR: "ruim",
        Grade.UNUSABLE: "inutilizável",
    }
)

OBJECT_TYPE_LABELS_PT: Mapping[ObjectType, str] = MappingProxyType(
    {
        ObjectType.SCREW: "parafuso",
        ObjectType.NUT: "porca",
        ObjectType.UNKNOWN: "desconhecido",
        ObjectType.PLIERS: "alicate",
        ObjectType.ADJUSTABLE_WRENCH: "chave inglesa",
        ObjectType.ALLEN_KEY: "chave Allen",
        ObjectType.FLAT_SCREWDRIVER: "chave de fenda",
        ObjectType.PHILLIPS_SCREWDRIVER: "chave Phillips",
        ObjectType.ANGLE_GRINDER: "esmerilhadeira",
        ObjectType.SAW: "serra",
        ObjectType.DRILL: "furadeira",
        ObjectType.CORDLESS_SCREWDRIVER: "parafusadeira",
    }
)

SOURCE_LABELS_PT: Mapping[Source, str] = MappingProxyType(
    {
        Source.LIVE: "real",
        Source.SIMULATED: "simulado",
    }
)

CAPTURE_MODE_LABELS_PT: Mapping[CaptureMode, str] = MappingProxyType(
    {
        CaptureMode.INSPECT: "inspeção",
        CaptureMode.COLLECT: "coleta",
    }
)
