# SPEC-002: Pacotes compartilhados v0 (`qc-contracts` e `qc-preprocess`)

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r2 |
| Autor da implementação | developer |
| Tags | contrato |
| Depende de | SPEC-001 |
| Semana alvo | S1 |
| Requisitos cobertos | RF-04, RF-06 (contrato), RF-09…RF-11 (schemas de leitura), RNF-07 (pré-processamento determinístico), R-04, R-06 |
| ADRs relevantes | ADR-001 (domínio e graus), ADR-004 (pré-processamento compartilhado), ADR-012 (idioma e rótulos), ADR-013 (regra de defeito e SPC) |

## 1. Contexto

Borda, API, dashboard e ML trocam dados pelo contrato descrito em `docs/architecture.md` §3 e usam o mesmo pré-processamento descrito em §6.2 (passo 2) e §7 (`preprocessing.json`). Esta SPEC implementa os dois pacotes que todos importam. A skill `contrato-api` rege a evolução do contrato; esta é a versão inicial `0.1.0`.

## 2. Objetivo

`qc_contracts` 0.1.0 implementa exatamente o §3 de `architecture.md` (enums, schemas, invariantes, `is_defective`, rótulos PT-BR) e `qc_preprocess` 0.1.0 transforma bytes de imagem em um tensor `float32[1,3,224,224]` de forma determinística, sem torch.

## 3. Escopo

### 3.1 Dentro

- `packages/contracts/src/qc_contracts/`: `__init__.py` (reexporta a API pública e define `__version__ = "0.1.0"`), `enums.py`, `defects.py`, `schemas.py`, `labels.py`.
- `packages/contracts/README.md` com uso e a tabela "Histórico de versões" (linha `0.1.0 — 2026-10 — versão inicial (SPEC-002)`).
- `packages/preprocess/src/qc_preprocess/`: `__init__.py` (`__version__ = "0.1.0"`), `params.py`, `image.py`, `transform.py`, `errors.py`.
- Versão `0.1.0` nos dois `pyproject.toml`. Dependências: `qc-contracts` → só `pydantic>=2.7`; `qc-preprocess` → só `numpy` e `pillow`.
- Testes unitários em `packages/contracts/tests/` e `packages/preprocess/tests/`.

### 3.2 Fora

- Persistência e coluna gerada `is_defective` (SPEC-003); uso dos schemas nas rotas (SPEC-004/005/006).
- Decisão `unknown`/`needs_review` e inferência ONNX (SPEC-008); augmentations de treino (SPEC-011).
- Geração do `preprocessing.json` de cada modelo (SPEC-012).
- Novos tipos de objeto da Fase 2/3 (SPEC-016/021, com aumento de versão).

## 4. Requisitos detalhados

### 4.1 Enums (`qc_contracts.enums`)

- `ObjectType`, `Grade`, `Source`, `CaptureMode` são `enum.StrEnum` com os valores de §3.1 (membros em maiúsculas: `Grade.PERFECT = "perfect"`, …). A ordem de definição de `Grade` é a ordem de severidade.
- `GRADE_ORDER: tuple[Grade, ...] = (PERFECT, GOOD, FAIR, POOR, UNUSABLE)`.
- `grade_index(grade: Grade) -> int` (0…4) e `grade_from_index(i: int) -> Grade`; índice fora de 0…4 → `ValueError`.

### 4.2 Regra de defeito (`qc_contracts.defects`)

- `is_defective(grade: Grade | None) -> bool`: `True` só para `POOR` e `UNUSABLE`; `None` → `False`. Uma `str` igual a um valor de `Grade` é aceita (o enum é `StrEnum`); qualquer outra string → `ValueError`. Única implementação da regra no projeto (ADR-013).

### 4.3 Schemas (`qc_contracts.schemas`, Pydantic v2)

- `InspectionCreate`: campos e regras de §3.2, com `model_config = ConfigDict(extra="forbid")` e:
  - `inspection_id`: `UUID4` (UUID de outra versão → erro);
  - `inspected_at`: datetime **com** fuso (naive → erro), normalizado para UTC (`tzinfo == timezone.utc`); rejeitado se `inspected_at > agora_utc + 5 min`;
  - `grade is None` **se e somente se** `object_type == ObjectType.UNKNOWN`;
  - `grade_score is None` e `grade_confidence is None` **se e somente se** `grade is None`;
  - faixas fechadas: `grade_score` 0…4, `type_confidence` e `grade_confidence` 0…1; `NaN` e `±inf` rejeitados; `latency_ms` inteiro ≥ 0;
  - regexes de `device_id`, `lot_id` e `model_version` de §3.2; `model_sha256` = `^[0-9a-f]{64}$` (hex **minúsculo**, como `hashlib.hexdigest()` e `sha256sum`);
  - as quatro regexes ficam em constantes públicas `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN` e `SHA256_PATTERN` (strings), reutilizadas pela API e pelos scripts sem redefinição.
- `InspectionRead`: mesmos campos e invariantes, mais `received_at` (datetime com fuso, UTC) e `is_defective: bool`; **sem** a regra dos 5 min no futuro e com `extra="ignore"` (o leitor tolera campos novos de uma versão minor posterior).
- `InspectionCreated`: `inspection_id: UUID`, `status: Literal["created", "duplicate"]`.
- `BatchCreate`: `items: list[InspectionCreate]` com 1…100 itens, `extra="forbid"`. `BatchResult`: `results: list[InspectionCreated]`.
- `Page[T]` (genérico): `items: list[T]`, `total: int ≥ 0`, `limit: int ≥ 1`, `offset: int ≥ 0`.
- `MetricsSummary`: campos de §3.3; `defect_rate`, `mean_type_confidence` e `mean_grade_score` são `float | None`; `by_grade: dict[Grade, int]`; `by_object_type: dict[ObjectType, int]`. A semântica dos valores é da SPEC-005.
- `TimeseriesPoint`: `bucket_start` (datetime UTC), `total`, `defective`, `defect_rate: float | None`.
- `SpcPoint` (`lot_id`, `started_at`, `ended_at`, `n`, `defects`, `p`, `cl`, `ucl`, `lcl`, `out_of_control`), `SpcExcludedLot` (`lot_id`, `n`) e `SpcResponse` (`baseline_lots`, `min_lot_size`, `source: Source`, `p_bar: float | None`, `points`, `excluded_lots`, `message: str | None`), conforme o JSON de §3.4.
- `LotSummary`: `lot_id`, `n` (inspeções do lote, incluindo `unknown`), `defects`, `unknown_count`, `started_at`, `ended_at`, `sources: list[Source]` (valores distintos, na ordem do enum). A semântica é da SPEC-005.
- `HealthResponse`: `status: Literal["ok", "degraded"]`, `db: Literal["ok", "error"]`, `api_version: str`, `contract_version: str` (`status == "ok"` ⇔ `db == "ok"`; comportamento HTTP na SPEC-004).
- Modelos de resposta usam `extra="ignore"`; modelos de entrada (`InspectionCreate`, `BatchCreate`) usam `extra="forbid"`.

### 4.4 Rótulos (`qc_contracts.labels`)

- `GRADE_LABELS_PT` (`perfeito`, `bom`, `mediano`, `ruim`, `inutilizável`), `OBJECT_TYPE_LABELS_PT` (`parafuso`, `porca`, `desconhecido`), `SOURCE_LABELS_PT` (`real`, `simulado`), `CAPTURE_MODE_LABELS_PT` (`inspeção`, `coleta`). Cada um é um mapeamento **imutável** (`types.MappingProxyType`) com uma chave para cada membro do enum.

### 4.5 `qc_preprocess`

- `PreprocessParams` (`@dataclass(frozen=True)`): `resize_shorter: int = 256`, `crop: int = 224`, `mean: tuple[float, float, float] = (0.485, 0.456, 0.406)`, `std: tuple[float, float, float] = (0.229, 0.224, 0.225)`. Validação em `__post_init__` (→ `ValueError`): inteiros > 0, `crop <= resize_shorter`, `mean`/`std` com 3 valores, `std` > 0.
- `PreprocessParams.from_json(path: Path) -> PreprocessParams` e `to_json(path: Path) -> None`. Formato: `{"resize_shorter": 256, "crop": 224, "mean": [...], "std": [...]}`; chave ausente ou desconhecida → `ValueError`.
- `InvalidImageError(ValueError)`.
- `load_image(data: bytes | Path) -> PIL.Image.Image`:
  - `Path` inexistente → `FileNotFoundError`;
  - valida o **conteúdo** com Pillow (não a extensão); formatos aceitos: JPEG e PNG (§6.1); outro formato, bytes vazios, conteúdo que não é imagem ou arquivo truncado (decodificação completa com `.load()`) → `InvalidImageError`;
  - mais de 40 000 000 pixels (checado pelo cabeçalho, antes de decodificar) ou `DecompressionBombError` → `InvalidImageError`;
  - aplica `ImageOps.exif_transpose` e devolve a imagem em modo `RGB`.
- `preprocess(img: PIL.Image.Image, params: PreprocessParams = PreprocessParams()) -> np.ndarray`:
  1. exige modo `RGB` (outro modo → `ValueError`);
  2. redimensiona o lado menor para `resize_shorter` com `Image.Resampling.BILINEAR`; o lado maior vira `int(maior * resize_shorter / menor)` (truncamento); se o tamanho já for o alvo, não reamostra;
  3. crop central `crop × crop` com origem `((w - crop) // 2, (h - crop) // 2)`;
  4. `float32`, divide por 255, normaliza por canal `(x - mean) / std` em `float32`;
  5. HWC → CHW e eixo de batch: retorna array C-contíguo `float32` com shape `(1, 3, crop, crop)`.
- **Determinismo:** a mesma entrada (bytes ou imagem) e os mesmos parâmetros produzem saída idêntica bit a bit, na mesma versão do Pillow travada no `uv.lock`.
- Proibido importar torch, torchvision ou timm (R-12 e `architecture.md` §2).

## 5. Critérios de aceite

Payload base válido (`P`) usado nos CAs de `InspectionCreate`: `inspection_id` = UUID4 fixo, `device_id="edge-01"`, `lot_id="L-001"`, `inspected_at` = agora − 1 min com fuso `-03:00`, `object_type="screw"`, `grade="fair"`, `grade_score=2.1`, `type_confidence=0.97`, `grade_confidence=0.66`, `needs_review=false`, `model_version="partqc-mnv3-v1"`, `model_sha256="a"*64`, `latency_ms=120`, `source="live"`.

- **CA-01** — Dado o pacote, quando se lê `qc_contracts.__version__` e `importlib.metadata.version("qc-contracts")`, então ambos valem `"0.1.0"`; o mesmo vale para `qc_preprocess` e `qc-preprocess`.
- **CA-02** — Dado os enums, quando se listam os valores, então `ObjectType` = `["screw","nut","unknown"]`, `Grade` = `["perfect","good","fair","poor","unusable"]`, `Source` = `["live","simulated"]`, `CaptureMode` = `["inspect","collect"]`, e `GRADE_ORDER` tem os 5 graus nessa ordem; e `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN` e `SHA256_PATTERN` valem `^[a-z0-9-]{3,32}$`, `^[A-Za-z0-9_-]{1,40}$`, `^[a-z0-9.-]{3,40}$` e `^[0-9a-f]{64}$`.
- **CA-03** — Dado `grade_index`/`grade_from_index`, quando se chama `grade_index(Grade.FAIR)` e `grade_from_index(4)`, então retornam `2` e `Grade.UNUSABLE`; `grade_from_index(5)` e `grade_from_index(-1)` levantam `ValueError`.
- **CA-04** — Dado `is_defective`, quando chamado com cada grau e `None`, então retorna `False, False, False, True, True` para `perfect…unusable` e `False` para `None`; `is_defective("poor")` retorna `True` e `is_defective("bogus")` levanta `ValueError`.
- **CA-05** — Dado `P`, quando validado com `InspectionCreate.model_validate`, então não há erro, `inspected_at.tzinfo == timezone.utc` e o instante é o mesmo (ex.: `12:00-03:00` → `15:00Z`); e `InspectionCreate.model_validate(m.model_dump(mode="json"))` reproduz o mesmo modelo (ida e volta).
- **CA-06** — Dado `P` com `inspected_at` sem fuso (`"2026-10-20T12:00:00"`), quando validado, então levanta `ValidationError`.
- **CA-07** — Dado `P` com `inspected_at` = agora + 10 min, quando validado, então levanta `ValidationError`; com agora + 4 min, é aceito.
- **CA-08** — Dado `P` com `object_type="unknown"` e `grade="fair"`, quando validado, então levanta `ValidationError`; e dado `P` com `object_type="screw"`, `grade=null`, `grade_score=null` e `grade_confidence=null`, também levanta `ValidationError`.
- **CA-09** — Dado `P` com `object_type="unknown"` e `grade`, `grade_score` e `grade_confidence` nulos, quando validado, então é aceito; e com `grade=null` mas `grade_score=1.0` (ou `grade_confidence=0.5`), levanta `ValidationError`; e com `grade="fair"` mas `grade_score=null`, levanta `ValidationError`.
- **CA-10** — Dado `P`, quando cada campo abaixo recebe o valor indicado, então cada caso levanta `ValidationError`: `type_confidence=1.01`; `type_confidence=-0.01`; `grade_confidence=1.5`; `grade_score=4.01`; `grade_score=NaN`; `latency_ms=-1`; `device_id="Edge_01"`; `device_id="ab"`; `lot_id=""`; `lot_id="L 001"`; `lot_id` com 41 caracteres; `model_version="PartQC-V1"`; `model_sha256` com 63 caracteres; `model_sha256="A"*64`; `inspection_id` = UUID versão 1; `source="test"`; `object_type="bolt"`.
- **CA-11** — Dado `P` com `type_confidence=0.0`, `grade_confidence=1.0`, `grade_score=0.0` e `latency_ms=0`, quando validado, então é aceito (limites inclusivos).
- **CA-12** — Dado `P` acrescido de `"image": "..."` (ou qualquer campo extra), quando validado como `InspectionCreate`, então levanta `ValidationError` do tipo `extra_forbidden` (R-02, R-04).
- **CA-13** — Dado `BatchCreate`, quando `items` tem 0 itens ou 101 itens, então levanta `ValidationError`; com 1 e com 100 itens válidos, é aceito; com 100 itens em que o 57º é inválido, levanta `ValidationError` que aponta `items.56`.
- **CA-14** — Dado um `InspectionRead` montado a partir de `P` com `received_at` e `is_defective=False`, quando acrescido de um campo desconhecido `"foo": 1` e de `inspected_at` = agora + 1 h, então a validação é aceita e o campo extra é descartado.
- **CA-15** — Dado `InspectionCreated`, quando `status="created"` ou `"duplicate"`, então é aceito; com `status="ok"`, levanta `ValidationError`.
- **CA-16** — Dado `Page[InspectionRead]`, `MetricsSummary`, `TimeseriesPoint`, `SpcResponse` (com o JSON de exemplo de `architecture.md` §3.4), `LotSummary` e `HealthResponse`, quando cada um é validado a partir de JSON e reserializado com `model_dump(mode="json")`, então o resultado é igual à entrada; `HealthResponse` com `status="up"` levanta `ValidationError`.
- **CA-17** — Dado `qc_contracts.labels`, quando comparado aos enums, então cada mapeamento tem exatamente uma chave por membro, os valores são os de `architecture.md` §3.1 (ex.: `GRADE_LABELS_PT[Grade.UNUSABLE] == "inutilizável"`), e `GRADE_LABELS_PT[Grade.FAIR] = "x"` levanta `TypeError`.
- **CA-18** — Dado o código de `qc_contracts`, quando se analisam os `import` via `ast`, então só aparecem módulos da biblioteca padrão sem I/O (`enum`, `datetime`, `uuid`, `re`, `math`, `types`, `typing`, `collections.abc`, `__future__`), `pydantic`/`annotated_types` e o próprio `qc_contracts`; e os metadados do pacote declaram só `pydantic` como dependência.
- **CA-19** — Dado `PreprocessParams()`, quando lido, então vale `256, 224, (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)`; `PreprocessParams(resize_shorter=200, crop=224)` e `PreprocessParams(std=(0.2, 0.0, 0.2))` levantam `ValueError`; `to_json` seguido de `from_json` devolve parâmetros iguais; um JSON sem `crop` ou com a chave extra `"resize"` levanta `ValueError`.
- **CA-20** — Dado uma imagem RGB sólida de 300×400 (largura×altura) com cor `(255, 0, 51)`, quando `preprocess` roda com os parâmetros padrão, então o resultado tem `shape == (1, 3, 224, 224)`, `dtype == float32`, é C-contíguo, e os canais valem `2.2489083`, `-2.0357143` e `-0.9155556` com tolerância absoluta de `0.02` em todos os pixels.
- **CA-21** — Dado a imagem 4×4 RGB em que o pixel `(x, y)` tem cor `(16·(4y+x), 255 − 16·(4y+x), 128)` e `PreprocessParams(resize_shorter=4, crop=2, mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))`, quando `preprocess` roda, então o canal R da saída é exatamente (tolerância `1e-6`) `[[80/255·2−1, 96/255·2−1], [144/255·2−1, 160/255·2−1]]` (crop dos pixels `x, y ∈ {1, 2}`, sem reamostragem).
- **CA-22** — Dado uma imagem de teste 64×48 gerada por fórmula fixa no teste, quando `preprocess` roda duas vezes (e também a partir dos mesmos bytes PNG via `load_image`), então as saídas são idênticas bit a bit (`tobytes()` iguais).
- **CA-23** — Dado um JPEG 40×20 com a tag EXIF `Orientation = 6`, quando passa por `load_image`, então a imagem resultante tem tamanho `(20, 40)` e modo `RGB`; um PNG RGBA e um PNG em tons de cinza (`L`) também saem em modo `RGB`.
- **CA-24** — Dado `load_image`, quando recebe `b""`, `b"not an image"`, um JPEG válido truncado na metade, um GIF válido de 10×10 ou um PNG cujo cabeçalho declara 8000×8000 pixels, então levanta `InvalidImageError` em cada caso; com `Path("nao_existe.jpg")`, levanta `FileNotFoundError`.
- **CA-25** — Dado `preprocess` com uma imagem em modo `L`, então levanta `ValueError`.
- **CA-26** — Dado um processo Python novo, quando executa `import qc_preprocess, qc_contracts`, então `"torch"` não está em `sys.modules`; e os metadados de `qc-preprocess` declaram só `numpy` e `pillow` como dependências (R-12).
- **CA-27** — Dado `packages/contracts/README.md`, quando lido, então contém a tabela "Histórico de versões" com a linha da versão `0.1.0`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Enums, `is_defective`, cada validador e invariante, ida e volta JSON de todos os schemas, rótulos; parâmetros, `load_image` (formatos, EXIF, corrompidos), `preprocess` (shape, valores, determinismo) | `packages/contracts/tests/`, `packages/preprocess/tests/` |
| Aceite (tester) | Um teste por CA | `packages/contracts/tests/acceptance/test_spec_002.py` (CA-01…18, 27) e `packages/preprocess/tests/acceptance/test_spec_002.py` (CA-01, 19…26) |

Imagens de teste são geradas em memória pelo próprio teste (Pillow/numpy); nenhum arquivo binário entra no Git (`.gitignore` ignora `*.jpg`/`*.png`). O "agora" dos CAs de tempo usa `datetime.now(timezone.utc)` com margens de minutos (sem mock de relógio).

## 7. Riscos e notas para o implementador

- Pillow com `BILINEAR` aplica antialias na redução; isso é intencional e igual no treino e na borda, porque os dois usam esta função.
- Use `model_validator(mode="after")` para as invariantes entre campos e uma base comum para `InspectionCreate`/`InspectionRead`, sem duplicar regras.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo
- [ ] `packages/contracts/README.md` com o histórico de versões; `uv.lock` atualizado
- [ ] PR aberto com os relatórios; merge humano
