# qc-contracts (`qc_contracts`)

Contrato compartilhado do PartQC: enums, schemas Pydantic v2, regra de defeito e rótulos PT-BR. Implementa `docs/architecture.md` §3. Borda, API, dashboard e ML importam daqui e **nunca** redefinem um payload localmente (R-04). A evolução segue a skill `contrato-api`.

Dependência única: `pydantic`. O pacote não faz I/O.

## Uso

```python
from datetime import datetime, timezone
from uuid import uuid4

from qc_contracts import (
    GRADE_LABELS_PT,
    Grade,
    InspectionCreate,
    __version__,
    is_defective,
)

payload = InspectionCreate.model_validate(
    {
        "inspection_id": str(uuid4()),
        "device_id": "edge-01",
        "lot_id": "L-001",
        "inspected_at": datetime.now(timezone.utc).isoformat(),
        "object_type": "screw",
        "grade": "fair",
        "grade_score": 2.1,
        "type_confidence": 0.97,
        "grade_confidence": 0.66,
        "needs_review": False,
        "model_version": "partqc-mnv3-v1",
        "model_sha256": "a" * 64,
        "latency_ms": 120,
        "source": "live",
    }
)
body = payload.model_dump(mode="json")      # JSON enviado pela borda à API

is_defective(Grade.POOR)                    # True  (regra única, ADR-013)
is_defective(None)                          # False (objeto unknown)
GRADE_LABELS_PT[Grade.UNUSABLE]             # "inutilizável"
```

## Conteúdo

| Módulo | O que expõe |
|---|---|
| `qc_contracts.enums` | `ObjectType`, `Grade`, `Source`, `CaptureMode` (`StrEnum`), `GRADE_ORDER`, `grade_index`, `grade_from_index` |
| `qc_contracts.defects` | `is_defective(grade)`: `True` só para `poor` e `unusable` |
| `qc_contracts.schemas` | `InspectionCreate`, `InspectionRead`, `InspectionCreated`, `BatchCreate`, `BatchResult`, `Page[T]`, `MetricsSummary`, `TimeseriesPoint`, `SpcPoint`, `SpcExcludedLot`, `SpcResponse`, `LotSummary`, `HealthResponse`; regexes `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN`, `SHA256_PATTERN` |
| `qc_contracts.labels` | `GRADE_LABELS_PT`, `OBJECT_TYPE_LABELS_PT`, `SOURCE_LABELS_PT`, `CAPTURE_MODE_LABELS_PT` (mapeamentos imutáveis) |

Tudo é reexportado na raiz (`from qc_contracts import ...`).

Regras principais:

- modelos de entrada (`InspectionCreate`, `BatchCreate`) rejeitam campos extras (`extra="forbid"`); modelos de resposta ignoram campos extras (`extra="ignore"`), para tolerar uma versão minor posterior;
- datas exigem fuso e são normalizadas para UTC; `InspectionCreate.inspected_at` não pode estar mais de 5 min no futuro;
- `grade` é nulo se e somente se `object_type == "unknown"`; `grade_score` e `grade_confidence` são nulos se e somente se `grade` é nulo.

## Histórico de versões

| Versão | Data | Mudança |
|---|---|---|
| 0.1.0 | 2026-10 | versão inicial (SPEC-002) |
