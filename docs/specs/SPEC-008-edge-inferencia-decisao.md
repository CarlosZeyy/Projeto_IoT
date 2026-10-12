# SPEC-008: Inferência ONNX e decisão na borda

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | — |
| Depende de | SPEC-002, SPEC-007 |
| Semana alvo | S3 |
| Requisitos cobertos | RF-03, RF-04, RF-05, RNF-02, RNF-09 |
| ADRs relevantes | ADR-004, ADR-005, ADR-012, ADR-014 |

## 1. Contexto

Implementa os passos 2 a 4 de `docs/architecture.md` §6.2 sobre os artefatos de `docs/architecture.md` §7, como a implementação real do Protocol `Inferencer` da SPEC-007. A SPEC é desenvolvida com um **modelo dummy** gerado nos testes (`docs/plan.md` §3); o modelo real da SPEC-012 é só um diretório trocado via `MODEL_DIR`. Os limiares seguem N-04 (`decision.json` com override por env).

## 2. Objetivo

Com `MODEL_DIR` apontando para um diretório de modelo íntegro, `qc-edge` classifica cada foto com `onnxruntime` (CPU) e aplica a regra de decisão de §6.2 passo 4, com p95 de latência ≤ 300 ms.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/decision.py`: `Thresholds`, `ModelLabels`, `Decision`, `decide()`, `InvalidModelOutputError`.
- `edge/src/qc_edge/onnx_inferencer.py`: `OnnxInferencer`, `ModelLoadError`, `ModelIntegrityError`.
- Integração no `qc-edge` (`cli.py`): `MODEL_DIR` definido → `OnnxInferencer`; status do modelo e limiares efetivos no console e em `/api/status`.
- Helper de teste `edge/tests/dummy_model.py` (pacote `onnx` como dependência **de desenvolvimento** do `qc-edge`; sem torch).
- `edge/README.md`: seção "Trocar o modelo" e variáveis de limiar; `.env.example`.

### 3.2 Fora

- Treino, export, `decision.json` real e teste de paridade → SPEC-012.
- Rota `/api/capture`, token e página → SPEC-007. Outbox → SPEC-009.
- Novos tipos de objeto (ferramentas) → SPEC-016 (exige aumento de versão do contrato).

## 4. Requisitos detalhados

### 4.1 Decisão (`qc_edge.decision`, função pura)

```python
REVIEW_MARGIN = 0.10
@dataclass(frozen=True)
class Thresholds: type_threshold: float; unusable_threshold: float; grade_review_threshold: float  # cada um em [0, 1]
@dataclass(frozen=True)
class ModelLabels: object_types: tuple[str, ...]; grades: tuple[str, ...]
@dataclass(frozen=True)
class Decision:
    object_type: ObjectType; grade: Grade | None; grade_score: float | None
    type_confidence: float; grade_confidence: float | None; needs_review: bool
class InvalidModelOutputError(InferenceError): ...   # InferenceError da SPEC-007
def decide(type_probs: Sequence[float], grade_probs: Sequence[float],
           labels: ModelLabels, thresholds: Thresholds) -> Decision
```

1. **Validação** (senão `InvalidModelOutputError`): `len(type_probs) == len(labels.object_types)` e `len(grade_probs) == 5`; todos os valores finitos e em `[0, 1]` (tolerância 1e-6); cada vetor soma `1 ± 1e-3`.
2. `t = argmax(type_probs)` (empate → menor índice); `type_confidence = type_probs[t]` (sempre, inclusive quando o resultado é `unknown`).
3. Se `labels.object_types[t] == "other"` **ou** `type_confidence < type_threshold` → `object_type = unknown`; `grade`, `grade_score` e `grade_confidence` = `None`.
4. Caso contrário, `object_type = ObjectType(labels.object_types[t])`; se `grade_probs[4] >= unusable_threshold`, `grade = unusable`; senão `grade = Grade(labels.grades[argmax(grade_probs)])`. `grade_confidence = grade_probs[índice de grade]`; `grade_score = Σ i·grade_probs[i]`, i = 0..4.
5. `needs_review = type_confidence < type_threshold + REVIEW_MARGIN or (grade_confidence is not None and grade_confidence < grade_review_threshold)`.

Comparações exatamente como escritas (`<` estrito para `type_threshold`, `>=` para `unusable_threshold`).

### 4.2 Carga do modelo (`OnnxInferencer`)

```python
class ModelLoadError(Exception): ...
class ModelIntegrityError(ModelLoadError): ...
class OnnxInferencer:  # implementa qc_edge.inference.Inferencer (SPEC-007)
    def __init__(self, model_dir: Path, overrides: dict[str, float] | None = None) -> None: ...
    model_info: ModelInfo; labels: ModelLabels; thresholds: Thresholds
    threshold_sources: dict[str, Literal["decision.json", "env"]]
    def infer(self, image: PIL.Image.Image) -> InferenceResult: ...
```

Na construção, nesta ordem (qualquer falha → `ModelLoadError` com mensagem que cita o arquivo; o `qc-edge` registra a mensagem e sai com código 2):

1. Existem `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json` e `decision.json`.
2. **Integridade:** SHA-256 de `model.onnx` (leitura em blocos) igual ao primeiro token hexadecimal de `model.sha256` (aceita o formato `<hash>  model.onnx`, sem diferenciar maiúsculas; `model_info.model_sha256` é guardado em minúsculas, como exige o contrato). Divergência → `ModelIntegrityError` com os 12 primeiros caracteres do esperado e do obtido.
3. `model_version` = nome do diretório `MODEL_DIR`, validado contra `^[a-z0-9.-]{3,40}$` (contrato §3.2).
4. `labels.json`: `grades` exatamente `["perfect","good","fair","poor","unusable"]`; `object_types` sem repetição, cada um igual a `"other"` ou a um valor de `ObjectType` diferente de `unknown`. Rótulo fora disso (ex.: `"pliers"` com o contrato 0.1.0, ou `"unknown"`) → erro.
5. `preprocessing.json` → `qc_preprocess.PreprocessParams.from_json` (SPEC-002); `ValueError` → erro.
6. `decision.json` com as 3 chaves numéricas em `[0, 1]`; depois, overrides de `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` (lidos pelo `EdgeSettings`; valor fora de `[0, 1]` ou não numérico → erro na subida citando a variável). `threshold_sources` registra a origem de cada um.
7. `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])`; entrada `image`, saídas `type_probs` e `grade_probs`; uma inferência de aquecimento com zeros `[1,3,224,224]` confirma as formas `[1, len(object_types)]` e `[1, 5]`.

### 4.3 Inferência

`infer(img)`: `t0 = perf_counter()`; `x = qc_preprocess.preprocess(img, params)`; `session.run(["type_probs","grade_probs"], {"image": x})`; `decide(...)`; `latency_ms = round((perf_counter() - t0) * 1000)` (pré-processamento + modelo, sem a decodificação da imagem). Erro do `onnxruntime` → `InferenceError`. Deve ser seguro chamar de várias threads.

### 4.4 Integração

- `MODEL_DIR` definido → `OnnxInferencer`; ausente ou vazio → `inferencer=None`: a borda sobe sem modelo (SPEC-007 responde 503 no modo inspeção; o modo coleta segue funcionando); definido mas inválido → `ModelLoadError` e saída com código 2. `--stub-model` tem precedência, com aviso no log.
- Console e `/api/status` passam a mostrar `model_version`, os 12 primeiros caracteres do sha e os três limiares com a origem (o formato do `/api/status` é o da SPEC-007, acrescido de `model.thresholds: {nome: {"value", "source"}}`).

## 5. Critérios de aceite

Valores de limiar nos CAs: `type_threshold=0.5`, `unusable_threshold=0.4`, `grade_review_threshold=0.6`, labels `["screw","nut","other"]`.

- **CA-01** — *Dado* `type_probs=[0.1,0.1,0.8]`, *quando* chamo `decide`, *então* `object_type=unknown`, `grade`, `grade_score` e `grade_confidence` são `None`, `type_confidence=0.8` e `needs_review=false`.
- **CA-02** — *Dado* `type_probs=[0.45,0.30,0.25]`, *então* `object_type=unknown` e `needs_review=true`.
- **CA-03 (limite)** — *Dado* `type_probs=[0.5,0.3,0.2]` (exatamente no limiar), *então* `object_type=screw` (não é `unknown`) e `needs_review=true` (0,5 < 0,6).
- **CA-04 (limite)** — *Dado* `type_probs=[0.6,0.3,0.1]` e `grade_probs=[0.0,0.7,0.1,0.1,0.1]`, *então* `needs_review=false` (0,6 não é < 0,5 + 0,10), `grade=good`, `grade_confidence=0.7` e `grade_score=1.6` (±1e-9).
- **CA-05 (limite)** — *Dado* tipo `nut` com 0,9 e `grade_probs=[0.45,0.05,0.05,0.05,0.4]`, *então* `grade=unusable` (0,4 ≥ 0,4) e `grade_confidence=0.4`; com `[0.46,0.05,0.05,0.05,0.39]`, *então* `grade=perfect`.
- **CA-06 (limite)** — *Dado* tipo `screw` com 0,9 e `grade_confidence` exatamente 0,6, *então* `needs_review=false`; com 0,59, `needs_review=true`.
- **CA-07** — *Dado* `type_probs=[0.5,0.5,0.5]`, ou um `NaN`, ou um valor negativo, ou 4 graus, *quando* chamo `decide`, *então* recebo `InvalidModelOutputError`.
- **CA-08** — *Dado* um diretório com modelo dummy (saídas constantes `type_probs=[0.9,0.05,0.05]`, `grade_probs=[0.05,0.8,0.05,0.05,0.05]`) chamado `dummy-v1`, *quando* `infer` recebe um JPEG 1280×960, *então* o resultado é `screw`/`good`, `latency_ms` ≥ 0 inteiro e `model_info == ModelInfo("dummy-v1", <sha do arquivo>)`; e via `POST /api/capture` (SPEC-007) a inspeção no sink tem `model_version="dummy-v1"`.
- **CA-09** — *Dado* `model.sha256` com um hash diferente do arquivo, *quando* `OnnxInferencer` é construído (e quando `qc-edge` sobe com esse `MODEL_DIR`), *então* recebo `ModelIntegrityError` com os 12 primeiros caracteres do esperado e do obtido, e o processo sai com código 2.
- **CA-10** — *Dado* `labels.json` com `object_types=["screw","pliers","other"]`, ou `["screw","unknown"]`, ou graus fora da ordem, *então* `ModelLoadError` na construção.
- **CA-11** — *Dado* um diretório sem `decision.json` (e, em outro caso, com `type_threshold=1.2`), *então* `ModelLoadError` citando o arquivo.
- **CA-12** — *Dado* `decision.json` com `type_threshold=0.7` e env `TYPE_THRESHOLD=0.55`, *então* `thresholds.type_threshold == 0.55` e a origem é `env`; *dado* `TYPE_THRESHOLD=1.5` ou `abc`, *então* a subida falha com código 2 citando `TYPE_THRESHOLD`.
- **CA-13** — *Dado* um modelo dummy cuja saída `type_probs` tem forma `[N,4]` com `labels.json` de 3 tipos, ou cuja entrada não se chama `image`, *então* `ModelLoadError` na construção.
- **CA-14** — *Dado* um modelo dummy que emite `type_probs=[0.5,0.5,0.5]`, *quando* faço `POST /api/capture`, *então* recebo 500 `{"detail": "inference failed"}` e nada vai ao sink.
- **CA-15** — *Dado* o modelo dummy, *quando* rodo `infer` 50 vezes com um JPEG 1280×960, *então* o p95 de `latency_ms` é ≤ 300.
- **CA-16 (manual, marcador `slow`)** — 1. definir `QC_REAL_MODEL_DIR` com o modelo real da SPEC-012 no notebook da demo; 2. rodar `uv run pytest -m slow edge/tests/acceptance/test_spec_008.py`; 3. o teste roda `infer` 50 vezes (após 1 aquecimento) com fotos de `edge/tests/fixtures/` e exige p95 ≤ 300 ms; 4. registrar p50/p95 e a CPU no test-report. Sem `QC_REAL_MODEL_DIR`, o teste é pulado.
- **CA-17** — *Dado* a suíte do autor e a de aceite, *quando* rodo `pytest --cov=qc_edge.decision`, *então* a cobertura de `qc_edge.decision` é ≥ 80%.
- **CA-18** — *Dado* `MODEL_DIR` válido, *quando* `GET /` (loopback) e `GET /api/status`, *então* ambos mostram `model_version`, os 12 primeiros caracteres do sha e os três limiares com a origem.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `decide` (tabela de casos), carga, sha, labels, overrides | `edge/tests/` |
| Aceite (tester) | Um por CA; modelos dummy em `tmp_path` (o tester pode usar o helper do autor ou o próprio, em `edge/tests/acceptance/`) | `edge/tests/acceptance/test_spec_008.py` |
| Manual (dupla) | CA-16 com o modelo real | notebook da demo |

O modelo dummy é montado com `onnx.helper` (opset 17): `ReduceMean` da entrada → `Reshape [N,1]` → `Mul` por 0 → `Add` de constantes `[1,T]` e `[1,5]`. Nada de torch. Mock só do relógio, quando preciso.

## 7. Riscos e notas para o implementador

- Fixe `ir_version` do modelo dummy num valor suportado pelo `onnxruntime` travado no `uv.lock`; versões novas do `onnx` geram `ir_version` que runtimes mais antigos recusam.
- `0.5 + 0.10 == 0.6` em ponto flutuante; os CAs de limite foram escolhidos para não depender de arredondamento. Não arredonde probabilidades antes de comparar.
- `model_version` sai do nome do diretório porque `architecture.md` §7 não tem campo próprio para ele; ao copiar o modelo para o notebook, preserve o nome `ml/models/<model_version>/`.
- `decide` não conhece o contrato além de `ObjectType`/`Grade`; a invariante `grade is None ⇔ unknown` é revalidada pelo `InspectionCreate`.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); CA-16 registrado quando o modelo real existir
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo; cobertura de `qc_edge.decision` ≥ 80%
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano
