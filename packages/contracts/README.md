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
| `qc_contracts.enums` | `ObjectType`, `Grade`, `Source`, `CaptureMode` (`StrEnum`), `GRADE_ORDER`, `grade_index`, `grade_from_index`; grupos de grau do ADR-021 `GRADE_REQUIRED_OBJECT_TYPES`, `GRADE_FORBIDDEN_OBJECT_TYPES` e `GRADE_OPTIONAL_OBJECT_TYPES` (`frozenset[ObjectType]`) |
| `qc_contracts.defects` | `is_defective(grade)`: `True` só para `poor` e `unusable` |
| `qc_contracts.schemas` | `InspectionCreate`, `InspectionRead`, `InspectionCreated`, `BatchCreate`, `BatchResult`, `Page[T]`, `MetricsSummary`, `TimeseriesPoint`, `SpcPoint`, `SpcExcludedLot`, `SpcResponse`, `LotSummary`, `HealthResponse`; regexes `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN`, `SHA256_PATTERN`; limites `MAX_LATENCY_MS`, `MAX_BATCH_SIZE`, `MAX_FUTURE_SKEW` |
| `qc_contracts.labels` | `GRADE_LABELS_PT`, `OBJECT_TYPE_LABELS_PT`, `SOURCE_LABELS_PT`, `CAPTURE_MODE_LABELS_PT` (mapeamentos imutáveis) |

Tudo é reexportado na raiz (`from qc_contracts import ...`).

Ao reusar as regexes públicas (`DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN`, `SHA256_PATTERN`) fora dos schemas, valide com `re.fullmatch` (ou pelo próprio schema / `pydantic.TypeAdapter`), **nunca** com `re.match` ou `re.search`: no módulo `re`, o `$` casa antes de um `\n` final, e `re.match(DEVICE_ID_PATTERN, "edge-01\n")` aceitaria o valor que o schema rejeita.

Regras principais:

- modelos de entrada (`InspectionCreate`, `BatchCreate`) rejeitam campos extras (`extra="forbid"`); modelos de resposta ignoram campos extras (`extra="ignore"`), para tolerar uma versão minor posterior;
- datas exigem fuso e são normalizadas para UTC; uma data que sai da faixa de `datetime` ao ser convertida para UTC (ex.: `0001-01-01T00:00:00+05:00`) é rejeitada com `ValidationError`; `InspectionCreate.inspected_at` não pode estar mais de 5 min no futuro;
- `ObjectType` tem `screw`, `nut`, `unknown` e, a partir da 0.4.0, as 5 ferramentas manuais (`pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver`), nessa ordem;
- grupos de grau (ADR-021): cada `ObjectType` está em exatamente um grupo. `grade` é obrigatório nos tipos de `GRADE_REQUIRED_OBJECT_TYPES` (`screw`, `nut`), nulo nos de `GRADE_FORBIDDEN_OBJECT_TYPES` (`unknown`) e opcional nos de `GRADE_OPTIONAL_OBJECT_TYPES` (as ferramentas manuais); `grade_score` e `grade_confidence` são nulos se e somente se `grade` é nulo. Vale para `InspectionCreate` e `InspectionRead`, e as mensagens de erro citam a regra, sem os valores;
- `latency_ms` é inteiro de `0` a `MAX_LATENCY_MS` (2 147 483 647, o limite da coluna `integer` do banco); acima disso, `ValidationError` (`less_than_equal`), e não erro no `insert`;
- os modelos usam o modo padrão (lax) do Pydantic, sem `strict` (decisão da SPEC-023 §4.4).

## Histórico de versões

| Versão | Data | Mudança |
|---|---|---|
| 0.1.0 | 2026-10 | versão inicial (SPEC-002) |
| 0.2.0 | 2026-10 | teto de latency_ms (MAX_LATENCY_MS = 2³¹ − 1, coluna integer do banco) (SPEC-023) |
| 0.3.0 | 2026-10 | `SpcResponse` ganha os campos opcionais `max_points`, `valid_lots_total` e `excluded_lots_total` (corte da carta p, ADR-017) (SPEC-026) |
| 0.4.0 | 2026-10 | `ObjectType` ganha as 5 ferramentas manuais (`pliers`, `adjustable_wrench`, `allen_key`, `flat_screwdriver`, `phillips_screwdriver`) com rótulos PT-BR; grupos de grau `GRADE_REQUIRED_OBJECT_TYPES`, `GRADE_FORBIDDEN_OBJECT_TYPES` e `GRADE_OPTIONAL_OBJECT_TYPES`; a invariante de grau segue os grupos (ferramenta com ou sem grau). Mudança minor: todo payload válido na 0.3.0 continua válido, com o mesmo significado (ADR-021) (SPEC-016) |
