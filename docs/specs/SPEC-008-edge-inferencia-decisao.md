# SPEC-008: Inferência ONNX e decisão na borda

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r2 |
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
6. **Faixas do contrato.** Depois de todas as comparações dos itens 3 a 5, os valores devolvidos em `Decision` são limitados às faixas de `docs/architecture.md` §3.2:
   - `type_confidence = min(1.0, max(0.0, type_probs[t]))`;
   - `grade_confidence = min(1.0, max(0.0, grade_probs[índice de grade]))`, quando não é `None`;
   - `grade_score = min(4.0, max(0.0, Σ i·grade_probs[i]))`, quando não é `None`.

   As comparações dos itens 3 a 5 usam sempre os valores **sem limite** (brutos). Por isso o limite não muda nenhuma decisão (`object_type`, `grade`, `needs_review`), só os números devolvidos. O motivo é que o item 1 aceita valores um pouco fora de `[0, 1]` (tolerância de 1e-6 por valor e de 1e-3 na soma), e o `Softmax` em float32 gera esses casos sozinho. Exemplo real do `onnxruntime` travado no `uv.lock`, para um grau `unusable` muito confiante: `p4 = 1.0` exato com `p3 ≈ 5,9e-8`, o que dá `Σ i·p_i ≈ 4,00000018`. Sem o limite, o `InspectionCreate` (`GradeScore` ≤ 4, `Probability` ≤ 1) recusaria a inspeção. Pelos limites do item 1, o valor cortado difere do bruto em no máximo ~4e-3 no `grade_score` e 1e-6 nas confianças, uma diferença que a tolerância do item 1 já aceita.

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
3. `model_version` = nome do diretório `MODEL_DIR` **depois de resolver** os links simbólicos e os componentes `.` e `..` (`Path(model_dir).resolve(strict=True).name`; a barra final não conta), validado contra `^[a-z0-9.-]{3,40}$` (contrato §3.2) com `re.fullmatch`. Com um link `atual → partqc-mnv3-v1`, o `model_version` é `partqc-mnv3-v1`, e não `atual`. A resolução é feita no início da construção, antes do item 1 (caminho inexistente ou que não é diretório → `ModelLoadError` citando `MODEL_DIR`), e todos os arquivos são lidos do diretório resolvido; a validação do nome fica neste item. Motivo: trocar o modelo por um link de nome fixo (`atual`, `current`) mandaria para a nuvem a mesma versão para modelos diferentes, e o `architecture.md` §7 diz que o nome do diretório do modelo é o `model_version`.
4. `labels.json`: `grades` exatamente `["perfect","good","fair","poor","unusable"]`; `object_types` sem repetição, cada um igual a `"other"` ou a um valor de `ObjectType` diferente de `unknown`. Rótulo fora disso (ex.: `"pliers"` com o contrato 0.1.0, ou `"unknown"`) → erro.
5. `preprocessing.json` → `qc_preprocess.PreprocessParams.from_json` (SPEC-002); `ValueError` → erro.
6. `decision.json` com as 3 chaves numéricas em `[0, 1]`; depois, overrides de `TYPE_THRESHOLD`, `UNUSABLE_THRESHOLD`, `GRADE_REVIEW_THRESHOLD` (lidos pelo `EdgeSettings`; valor fora de `[0, 1]` ou não numérico → erro na subida citando a variável). `threshold_sources` registra a origem de cada um.
7. `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])`; entrada `image`, saídas `type_probs` e `grade_probs`; uma inferência de aquecimento com zeros `[1, 3, crop, crop]`, com o `crop` do `preprocessing.json` (item 5), confirma as formas `[1, len(object_types)]` e `[1, 5]`. É a mesma forma que o `infer` vai mandar (`[1,3,224,224]` com o `crop` padrão, `architecture.md` §7). Assim, um `crop` incompatível com a entrada do modelo falha **na carga** (`ModelLoadError` citando `model.onnx`, saída com código 2), e não em todo `infer`. Um modelo com dimensões espaciais dinâmicas aceita o `crop` que vier.

### 4.3 Inferência

`infer(img)`: `t0 = perf_counter()`; `x = qc_preprocess.preprocess(img, params)`; `session.run(["type_probs","grade_probs"], {"image": x})`; `decide(...)`; `latency_ms = round((perf_counter() - t0) * 1000)` (pré-processamento + modelo, sem a decodificação da imagem). Erro do `onnxruntime` → `InferenceError`. Deve ser seguro chamar de várias threads.

### 4.4 Integração

- `MODEL_DIR` definido → `OnnxInferencer`; ausente ou vazio → `inferencer=None`: a borda sobe sem modelo (SPEC-007 responde 503 no modo inspeção; o modo coleta segue funcionando); definido mas inválido → `ModelLoadError` e saída com código 2. "Vazio" é só a string vazia (`""`): o valor **não** é aparado, então um `MODEL_DIR` só com espaços conta como definido e, por não ser um diretório, sai com código 2 com uma mensagem no log que cita `MODEL_DIR`. Subir sem modelo por causa de um `.env` mal escrito esconderia o erro até a primeira captura. `--stub-model` tem precedência, com aviso no log.
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
- **CA-19 (faixas do contrato, §4.1 item 6)** — *Dado* os limiares e labels acima, *quando* chamo `decide` com cada um dos três pares abaixo, *então* recebo o resultado indicado, e um `InspectionCreate` montado com os campos da `Decision` (mais um payload base válido) é aceito sem `ValidationError`:
  - (a) `type_probs=[0.98,0.01,0.01]` e `grade_probs=[2.506e-10, 2.235e-10, 7.39e-11, 5.899e-08, 1.0]` (saída real de um `Softmax` float32, `Σ i·p_i > 4`) → `object_type=screw`, `grade=unusable`, `grade_score == 4.0` e `grade_confidence == 1.0` (igualdade exata), `needs_review=false`;
  - (b) `type_probs=[1.0000009, 0.0, 0.0]` e `grade_probs=[0.05,0.8,0.05,0.05,0.05]` → `object_type=screw`, `type_confidence == 1.0` (exato), `grade=good`;
  - (c) `type_probs=[0.9,0.05,0.05]` e `grade_probs=[1.0000005, -5e-7, 0.0, 0.0, 0.0]` → `grade=perfect`, `grade_confidence == 1.0` e `grade_score == 0.0` (exatos).
- **CA-20 (faixas do contrato pela rota)** — *Dado* um modelo dummy com saídas constantes `type_probs=[0.98,0.01,0.01]` e `grade_probs` do caso (a) do CA-19, *quando* faço `POST /api/capture` com uma foto válida em `mode=inspect`, *então* recebo 200 com `inspection.grade == "unusable"` e `inspection.grade_score == 4.0`, o sink tem exatamente 1 item com `grade_score == 4.0` e há 1 foto em `captures/`.
- **CA-21 (link simbólico, §4.2 item 3)** — *Dado* um diretório de modelo dummy válido `dummy-v1` e um link simbólico `atual` → `dummy-v1`, *quando* construo `OnnxInferencer(<caminho de atual>)`, *então* `model_info.model_version == "dummy-v1"`; e *dado* um link `atual` → um diretório de modelo válido chamado `Dummy_V1` (nome fora da regex), *então* `ModelLoadError` na construção.
- **CA-22 (`crop` na carga, §4.2 item 7)** — *Dado* um modelo dummy com a entrada declarada `[N,3,224,224]` (dimensões espaciais fixas) e um `preprocessing.json` com `resize_shorter=288` e `crop=256`, *quando* `OnnxInferencer` é construído, *então* recebo `ModelLoadError` cuja mensagem contém `model.onnx`; e *dado* o mesmo `preprocessing.json` com um modelo dummy de entrada `[N,3,H,W]` (dimensões espaciais dinâmicas), *então* a construção funciona e `infer` com um JPEG 1280×960 devolve as classes das saídas constantes.
- **CA-23 (`MODEL_DIR` só com espaços, §4.4)** — *Dado* `MODEL_DIR="   "` (3 espaços), *quando* `main()` é chamado com `uvicorn.run` substituído por um espião, *então* o código de saída é 2, o espião não é chamado e a saída de log contém `MODEL_DIR`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `decide` (tabela de casos), carga, sha, labels, overrides | `edge/tests/` |
| Aceite (tester) | Um por CA; modelos dummy em `tmp_path` (o tester pode usar o helper do autor ou o próprio, em `edge/tests/acceptance/`) | `edge/tests/acceptance/test_spec_008.py` |
| Manual (dupla) | CA-16 com o modelo real | notebook da demo |

O modelo dummy é montado com `onnx.helper` (opset 17): `ReduceMean` da entrada → `Reshape [N,1]` → `Mul` por 0 → `Add` de constantes `[1,T]` e `[1,5]`. Nada de torch. Mock só do relógio, quando preciso.

- **Forma da entrada:** por padrão, o dummy declara a entrada `[N,3,224,224]`. O CA-22 precisa também de uma variante com dimensões espaciais dinâmicas (`["N", 3, "H", "W"]`); o `ReduceMean` funciona com qualquer `H`×`W`.
- **CA-20:** as constantes do `Add` ficam em float32. O caso (a) do CA-19 continua com `p4 = 1.0` exato e `p3 > 0` em float32, então o `Σ i·p_i` bruto continua acima de 4.
- **CA-21:** usa `Path.symlink_to(..., target_is_directory=True)` em `tmp_path`.
- **Testes da r1 afetados pela correção do SPEC_ISSUE-01** (mesmo arquivo de aceite, então não se aplica a regra de SPECs anteriores de `architecture.md` §10):
  - `test_bug_t01_*` continuam válidos e passam com o §4.1 item 6, porque aceitam uma `Decision` dentro das faixas. O tester decide se os mantém como extras ou se os troca pelos testes do CA-19 e do CA-20;
  - `test_extra_symlinked_model_dir_uses_the_link_name` fica **invalidado** pelo §4.2 item 3 e pelo CA-21, porque agora vale o nome do alvo. O tester o remove ou o reescreve para o comportamento novo e registra isso no test-report da r2.

## 7. Riscos e notas para o implementador

- Fixe `ir_version` do modelo dummy num valor suportado pelo `onnxruntime` travado no `uv.lock`; versões novas do `onnx` geram `ir_version` que runtimes mais antigos recusam.
- `0.5 + 0.10 == 0.6` em ponto flutuante; os CAs de limite foram escolhidos para não depender de arredondamento. Não arredonde nem limite as probabilidades antes de comparar: o limite às faixas do contrato (§4.1 item 6) vem **depois** das comparações e só afeta os valores devolvidos.
- `model_version` sai do nome do diretório (resolvido, §4.2 item 3) porque `architecture.md` §7 não tem campo próprio para ele; ao copiar o modelo para o notebook, preserve o nome `ml/models/<model_version>/`. Trocar o modelo por um link simbólico funciona, e a inspeção leva o nome do diretório alvo.
- `decide` conhece do contrato só `ObjectType`/`Grade` e as faixas numéricas de §3.2 (§4.1 item 6). Com o limite, toda saída aceita pelo item 1 gera valores que o `InspectionCreate` aceita, e a invariante `grade is None ⇔ unknown` continua revalidada por ele.
- A regra do §4.1 item 6 também está em `architecture.md` §6.2 passo 4. A `qc_ml.decision.apply_decision` da SPEC-012 reproduz esse passo por referência, então aplica o mesmo limite sem mudança no texto dela. Vetores aleatórios quase nunca caem no caso, então o teste cruzado dela (`qc_ml` × `qc_edge`) não garante sozinho que os dois limitam.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); CA-16 registrado quando o modelo real existir
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo; cobertura de `qc_edge.decision` ≥ 80%
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-18 | Correção do SPEC_ISSUE-01 da r1 com a opção (a): (a) §4.1, item 6 novo: depois das comparações, `type_confidence` e `grade_confidence` são limitados a `[0, 1]` e `grade_score` a `[0, 4]`, e as comparações continuam com os valores brutos; (b) §4.2, item 3: `model_version` = nome do diretório **resolvido** (link simbólico → nome do alvo), e os arquivos são lidos do diretório resolvido; (c) §4.2, item 7: aquecimento com `[1, 3, crop, crop]` do `preprocessing.json`, em vez de `[1,3,224,224]` fixo; (d) §4.4: `MODEL_DIR` não é aparado, e só com espaços sai com código 2; (e) CAs novos CA-19 a CA-23; §6 e §7 atualizadas. Nenhum CA anterior muda. `docs/architecture.md` §6.2 passo 4 recebe o limite. Opção (b) do relatório (recusar a saída) descartada: em 34% das saídas `Softmax` com `unusable` dominante, a peça claramente inutilizável viraria 500. Sem ADR, porque o contrato, as regras negociáveis e as tecnologias não mudam: a decisão só faz a borda cumprir as faixas que o contrato 0.3.0 já define. SPEC marcada como "Aguardando reaprovação humana". | SPEC_ISSUE-01 e T-01 de `reviews/SPEC-008/r1-test-report.md` (itens b a d: observações sem bloqueio do mesmo relatório e do dev-report) | Orquestrador |
| 2026-10-18 | Correção do SPEC_ISSUE-01 (opção a, mais os itens b a d) reaprovada; `Blocked` → `In Dev` na r2. | Fluxo do loop (§4 da skill `features`) | Humano (Carlos) |
