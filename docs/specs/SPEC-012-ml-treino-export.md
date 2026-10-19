# SPEC-012: ML — treino, avaliação, limiares, export ONNX e paridade

| Campo | Valor |
|---|---|
| Status | In Test |
| Rodada atual | r2 |
| Autor da implementação | ml-engineer |
| Tags | — |
| Depende de | SPEC-011 (e SPEC-002, pelo `qc_preprocess` e `qc_contracts`) |
| Semana alvo | S3 (baseline v1); ablações na S5 |
| Requisitos cobertos | RF-03, RF-04, RF-05 (artefatos usados pela borda), RF-12 (`metrics.json`), RNF-02, RNF-07; metas do PRD §7; R-11 |
| ADRs relevantes | ADR-004, ADR-005, ADR-014, ADR-001 |

> **Reaprovada em 2026-10-19 pelo orquestrador, sob delegação do humano**: correção do SPEC_ISSUE-01 da r2 (texto do CA-13 frágil em float32 quebrou o CI da `main`). Ver o Histórico.

## 1. Contexto

A borda (SPEC-008) carrega um diretório de modelo com `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json` e `decision.json` (`docs/architecture.md` §6.2 e §7). Esta SPEC produz esses artefatos a partir do manifest e do split da SPEC-011, seguindo **exatamente** a skill `ml-pipeline` (§4 a §8). O dashboard (SPEC-013) lê o `metrics.json`. O treino real roda no Colab (GPU gratuita); avaliação, limiares e paridade rodam sem torch, só com onnxruntime.

## 2. Objetivo

`python -m qc_ml.pipeline --config ml/configs/partqc-mnv3-v1.json` gera `ml/models/partqc-mnv3-v1/` completo, com limiares escolhidos só na validação e métricas medidas só no teste, honestamente reportadas.

## 3. Escopo

### 3.1 Dentro

- `ml/src/qc_ml/model.py` (torch): backbone timm + duas cabeças; opção CORN; `ProbabilityWrapper`.
- `ml/src/qc_ml/train.py` (torch): treino em 2 fases, loss mascarada, pesos de classe, early stopping, seeds, checkpoints.
- `ml/src/qc_ml/export.py` (torch): ONNX, `onnx.checker`, `model.sha256`, `labels.json`, `preprocessing.json`, `parity_fixture.npz`.
- Sem torch: `predict.py` (onnxruntime), `decision.py` (regra de decisão de `architecture.md` §6.2), `thresholds.py`, `evaluate.py`, `parity.py`, `report.py` (entrada do CHANGELOG), `pipeline.py` (encadeia tudo).
- `ml/configs/partqc-mnv3-v1.json`, `ml/models/CHANGELOG.md`, `ml/notebooks/train_colab.ipynb`.
- `ml/scripts/make_tiny_fixture.py` e a fixture versionada `ml/tests/fixtures/tiny_model/`.
- Testes em `ml/tests/` e `ml/tests/acceptance/test_spec_012.py`.

### 3.2 Fora

- Manifest, split, augmentations e `PartsDataset`: SPEC-011.
- Carregar o modelo e decidir em produção: SPEC-008 (a borda tem a sua própria `qc_edge.decision`).
- Página "Sobre o modelo": SPEC-013. Ferramentas (Fase 2): SPEC-016.
- Publicar o GitHub Release e copiar o `.onnx` para a borda: tarefa humana (§4.9).

## 4. Requisitos detalhados

### 4.1 Modelo (`qc_ml.model`)

- `build_model(backbone: str, n_types: int, grade_head: Literal["ce", "corn"], pretrained: bool) -> PartQCNet`. Backbone `timm.create_model(backbone, pretrained=pretrained, num_classes=0)`; cabeças lineares `type` (`n_types`, inclui `other`) e `grade` (5 logits; 4 com CORN). `forward(x) -> (type_logits, grade_logits)`.
- Backbones permitidos fora do modo smoke: `mobilenetv3_large_100` (padrão, sigla `mnv3`) e `efficientnet_b0` (sigla `effb0`) — N-01.
- `ProbabilityWrapper(model).forward(image) -> (type_probs, grade_probs)`: softmax nas duas cabeças; com CORN, `s = sigmoid(logits)`, `c = cumprod(s)` (= P(y > k)) e `grade_probs = [1−c0, c0−c1, c1−c2, c2−c3, c3]`. Este wrapper é o que vai para o ONNX.

### 4.2 Treino (`qc_ml.train`)

- `TrainConfig` (dataclass, JSON em `ml/configs/`): `model_version`, `backbone`, `pretrained` (true), `grade_head` (`ce`), `seed` (42), `batch_size` (32), `epochs_a` (8), `lr_a` (1e-3), `epochs_b_max` (30), `lr_b` (1e-4), `unfreeze_last_blocks` (2), `patience` (5), `min_delta` (1e-4), `label_smoothing` (0.1), `lambda_grade` (1.0), `weight_decay` (1e-4), `num_workers` (2), `dataset_dir`, `split_file`, `models_root` (`ml/models`), `reports_root` (`ml/reports`), `checkpoints_root` (`ml/checkpoints`), `smoke` (false).
- Validação (`ConfigError`): `model_version` casa `^partqc-[a-z0-9]+(-[a-z0-9]+)*-v\d+$` e `^[a-z0-9.-]{3,40}$`; sem `smoke`, `epochs_a` ∈ [5, 10] e backbone na lista de §4.1. Valores diferentes dos padrões da skill são permitidos, mas listados em `deviations_from_defaults`.
- **Fase A:** backbone congelado, AdamW com `lr_a`, `epochs_a` épocas. **Fase B:** descongela os últimos `unfreeze_last_blocks` estágios de `blocks` e tudo depois deles (`conv_head` etc.), AdamW com `lr_b`, até `epochs_b_max` épocas, com `EarlyStopper(patience, min_delta)` sobre o **QWK de grau da validação** (argmax de `grade_probs` nas imagens de val com grau).
- **Melhor checkpoint:** maior `val_grade_qwk` entre todas as épocas (A e B); empate → menor `val_loss` → época mais antiga. QWK indefinido (uma só classe) conta como −1.
- **Loss:** `CE(type, label_smoothing) + lambda_grade · CE_masked(grade, label_smoothing, weight)`; a máscara é `grade_idx >= 0`; sem nenhuma linha com grau no batch, o termo de grau é 0 (nunca NaN). Com CORN: `coral_pytorch.losses.corn_loss` nas linhas mascaradas (sem label smoothing nem pesos).
- **Pesos de classe** (`grade_class_weights(counts: dict[str, int]) -> list[float] | None`, sem torch): contagens de imagens com grau no **treino**; `mean = total / 5`; se algum grau tiver `count < 0.6 · mean`, `w_g = mean / count_g` para os 5 graus; senão `None`. Grau com 0 imagens no treino → `TrainError`.
- **Seeds:** `random`, `numpy`, `torch` (e CUDA); `torch.use_deterministic_algorithms(True, warn_only=True)`; `DataLoader` com `generator` semeado e `worker_init_fn`.
- **Checkpoints:** `ml/checkpoints/<versão>/last.pt` (a cada época) e `best.pt`; `--resume` continua do `last.pt` (config diferente → `ConfigError`).
- **`training_config.json`** em `ml/models/<versão>/`: `model_version`, `config`, `deviations_from_defaults`, `labels`, `split_file`, `split_sha256`, `manifest_sha256`, `grade_class_weights`, `history` (lista de `{epoch, phase, train_loss, val_loss, val_type_accuracy, val_grade_qwk}`), `best_epoch`, `best_val_grade_qwk`, `stopped_early`, `versions` (`python`, `torch`, `torchvision`, `timm`, `numpy`, `scikit-learn`, `onnx`, `onnxruntime`, `coral-pytorch`, `qc-preprocess`, `qc-ml`), `device`, `git_commit` (ou `null`), `started_at`, `finished_at`, `smoke`.
- O treino obtém linhas **só** via `qc_ml.split.rows_for(..., "train")` e `rows_for(..., "val")`.

### 4.3 Export (`qc_ml.export`)

- `export_onnx(model, out_path, opset=17)`: `torch.onnx.export` do `ProbabilityWrapper` em `eval()`, entrada `image` float32 `[N,3,224,224]`, saídas `type_probs` `[N,T]` e `grade_probs` `[N,5]`, eixo 0 dinâmico nas três; `onnx.checker.check_model`.
- Grava em `ml/models/<versão>/`: `model.onnx`; `model.sha256` (64 hex minúsculos + `\n`); `labels.json` (`{"object_types": ["screw","nut","other"], "grades": [...5 graus...]}`); `preprocessing.json` (`PreprocessParams().to_json(path)`, SPEC-002); `parity_fixture.npz`.
- **`parity_fixture.npz`** (`np.savez_compressed`): `inputs` float32 `[8,3,224,224]`, `type_probs`, `grade_probs` (saídas do torch) e `model_sha256`. As 8 entradas vêm de `make_synthetic_dataset(seed=0)` pré-processadas por `qc_preprocess` — **nenhuma foto real vai para o Git** (R-02/R-14). Amostra cuja diferença entre as duas maiores probabilidades de qualquer cabeça seja < 1e-3 é trocada pela próxima candidata.
- Após exportar, roda `parity.check_parity(model_dir)`; falha → exit 2 e o `model.onnx` é apagado.

### 4.4 Paridade (`qc_ml.parity`, sem torch)

`check_parity(model_dir) -> ParityResult(ok, max_abs_diff, argmax_equal)`: roda o `model.onnx` no onnxruntime (CPU) com `inputs`; `ok` = `max |onnx − torch| < 1e-4` **e** argmax idêntico nas duas saídas **e** `model_sha256` da fixture = `model.sha256`.

### 4.5 Predição e decisão (sem torch)

- `predict.OnnxModel(model_dir)` confere o `model.sha256` (divergente → erro) e expõe `predict(frame, dataset_dir, split: Literal["train","val","test"]) -> Predictions` (`split`, `image_paths`, `type_probs`, `grade_probs`, `true_type_idx`, `true_grade_idx`), usando `qc_preprocess`.
- `decision.apply_decision(type_probs, grade_probs, labels, thresholds)` reproduz `architecture.md` §6.2 passo 4 (unknown, `unusable_threshold`, `grade_confidence`, `grade_score`, `needs_review`).

### 4.6 Limiares (`qc_ml.thresholds`) — só validação (R-11)

`choose_thresholds(val: Predictions, labels) -> ThresholdResult(decision, report)`. Se `val.split != "val"` → `SplitIntegrityError`. Valores com 2 casas decimais.

- **`type_threshold`:** grade `t ∈ {0,50; 0,51; …; 0,85}` (passo 0,01). `FU(t)` = fração das imagens de val `screw`/`nut` que viram `unknown` (argmax `other` ou `max < t`). Escolhe o **maior** `t` com `FU(t) ≤ 0,05`; se nenhum, 0,50 e nota `type_target_not_met`. (O teto 0,85 segue a skill `ml-pipeline` §6.)
- **`unusable_threshold`:** grade `u ∈ {0,05; 0,06; …; 0,95}` (passo 0,01), nas imagens de val com grau; grau previsto = `unusable` se `p_unusable ≥ u`, senão argmax. Escolhe o **maior** `u` com `recall_unusable ≥ 0,90`; se impossível, o `u` de maior recall (empate → maior `u`) e nota `unusable_target_not_met`; sem `unusable` na val → 0,50 e nota `no_unusable_in_val`.
- **`grade_review_threshold`:** com os dois limiares acima e `r = 0,60`, calcula a fração de val com `needs_review`. Em [5%, 15%] → 0,60. Fora → `r ∈ {0,30; 0,31; …; 0,95}` (passo 0,01) que minimiza `|fração − 10%|` (empate → mais próximo de 0,60) e nota `review_adjusted`.
- CLI `python -m qc_ml.thresholds --config <json>` grava `ml/models/<v>/decision.json` com **exatamente** `type_threshold`, `unusable_threshold`, `grade_review_threshold`, e `ml/reports/<v>/thresholds_report.json` (curvas, notas, `n_val_images`, `split_sha256`).

### 4.7 Avaliação (`qc_ml.evaluate`) — único consumidor do teste

- `python -m qc_ml.evaluate --config <json> [--latency-machine "<texto>"] [--latency-only]`. Sem `model.onnx`, sem `model.sha256` válido ou sem `decision.json` → exit 2 com `decision.json not found: run qc_ml.thresholds first` (ou equivalente) e nada é gravado.
- É o **único** módulo que chama `rows_for(..., "test")`. Todos os módulos chamam `split.rows_for` pelo atributo do módulo (`from qc_ml import split`), para permitir o teste de integridade.
- **`metrics.json`** — chaves de topo **exatamente**: `model_version`, `model_sha256`, `evaluated_at`, `split_file`, `split_sha256`, `manifest_sha256`, `labels`, `decision`, `type_accuracy`, `type_confusion`, `grade_qwk`, `grade_mae`, `grade_off_by_one_accuracy`, `grade_confusion`, `grade_per_class`, `unusable_recall`, `unusable_precision`, `defective_recall`, `defective_precision`, `unknown_rate_on_other`, `false_unknown_rate`, `needs_review_rate`, `latency_ms_p50`, `latency_ms_p95`, `latency_machine`, `latency_runs`, `counts`, `grade_qwk_ci95`, `unusable_recall_ci95`, `defective_recall_ci95`, `n_items_test_by_grade`, `warnings`.
- Regras: tipo pelo argmax em todas as imagens de teste (`type_confusion` T×T, linhas = verdade); métricas de grau nas imagens de teste `screw`/`nut` com grau, com o grau decidido pelo `unusable_threshold` + argmax (independente do tipo previsto); `grade_per_class` sempre com os 5 graus (`precision`, `recall`, `f1`, `support`); defeito via `qc_contracts.is_defective`; `unknown_rate_on_other`, `false_unknown_rate` e `needs_review_rate` com `decision.json`; `counts` = por split → `n_images`, `n_items`, `by_class` (tipo → `n_images`, `n_items`, `by_grade`). Métrica indefinida → `null`, **nunca omitida nem arredondada**.
- **Incerteza e avisos:** `grade_qwk_ci95`, `unusable_recall_ci95` e `defective_recall_ci95` são IC 95% bootstrap (1.000 reamostragens por `item_id`, seed fixa), cada um como `[low, high]` (ou `null` se indefinido); `n_items_test_by_grade` = grau → nº de `item_id` distintos no teste; `warnings` = lista de strings (vazia se não houver aviso).
- **Latência:** onnxruntime `CPUExecutionProvider`, batch 1, `load_image` + `preprocess` + `run`, 10 aquecimentos + 100 medições (`latency_runs = 100`), percentis do numpy. `--latency-only` remede e reescreve só `latency_*` e `latency_machine` (a medição oficial da RNF-02 é no notebook da borda).
- PNGs `ml/reports/<v>/type_confusion.png` e `grade_confusion.png`, desenhados com Pillow (sem matplotlib), rótulos PT-BR.

### 4.8 Pipeline, CHANGELOG e notebook

- `python -m qc_ml.pipeline --config <json>`: train → export → thresholds → evaluate; para no primeiro erro (exit 2).
- `python -m qc_ml.report changelog --model-dir ml/models/<v> [--previous ml/models/<v-1>] [--append ml/models/CHANGELOG.md]`: gera a entrada `## <versão> — AAAA-MM-DD` com a tabela métrica × valor (lido do `metrics.json` e exibido com 4 casas e vírgula decimal pela regra única de `docs/architecture.md` §7, "Exibição das métricas": nunca a favor da meta; o status usa o valor bruto) × meta do PRD §7 (`type_accuracy` ≥ 0,95; `grade_qwk` ≥ 0,75; `grade_off_by_one_accuracy` ≥ 0,90; `unusable_recall` ≥ 0,90; `defective_recall` ≥ 0,90; `latency_ms_p95` ≤ 300) × status (`atingida` / `abaixo da meta` / `n/d`), a coluna da versão anterior (se houver) e as seções "O que mudou" e "Problemas conhecidos" a preencher.
- `ml/models/CHANGELOG.md`: cabeçalho explicando o formato; a 1ª entrada vem do treino real.
- `ml/notebooks/train_colab.ipynb` (fino, **sem saídas** salvas): (1) checar `sys.version_info[:2] == (3, 12)` e GPU; (2) montar o Drive; (3) clonar o repositório com um token **somente leitura** lido de `google.colab.userdata` (nunca escrito no notebook), ou descompactar um snapshot do Drive; (4) `pip install -e packages/contracts -e packages/preprocess -e "ml[train]"`; (5) descompactar o dataset do Drive em `/content/data`; (6) `!python -m qc_ml.data validate`, `!python -m qc_ml.pipeline --config ...`; (7) copiar `ml/models/<v>/` e `ml/reports/<v>/` para o Drive. Nenhuma função ou classe definida no notebook.

### 4.9 Versionamento e distribuição (humano)

- Nome `partqc-<sigla>-v<N>` (`partqc-mnv3-v1`); ablação CORN ou outro backbone recebe o próximo N.
- Vão para o Git: os JSONs, `parity_fixture.npz`, `model.sha256`, os PNGs de `ml/reports/` e o CHANGELOG. **Não** vão: `model.onnx` e checkpoints (`.gitignore`).
- Release (dupla): `gh release create model-partqc-mnv3-v1 ml/models/partqc-mnv3-v1/model.onnx --title "Modelo partqc-mnv3-v1" --notes "sha256: <conteúdo do model.sha256>"`. Na borda: `gh release download model-partqc-mnv3-v1 -p model.onnx -D ml/models/partqc-mnv3-v1` e conferir com `sha256sum`.

### 4.10 Fixture mínima para o CI

`ml/scripts/make_tiny_fixture.py` (roda uma vez, com torch) cria `ml/tests/fixtures/tiny_model/` com uma rede mínima (conv 3→8, pooling global, duas cabeças) passada pelo **mesmo** `ProbabilityWrapper` e `export_onnx`: `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json`, `decision.json` (0,70 / 0,50 / 0,60) e `parity_fixture.npz`; total < 1 MB. Hoje o `.gitignore` só ignora `ml/models/**/*.onnx`, então o caminho já é versionável; se uma regra futura o ignorar, esta SPEC autoriza acrescentar a negação `!ml/tests/fixtures/**/*.onnx`. Como o hook da SPEC-001 (§4.6) limita o ml-engineer a `ml/**`, essa linha seria aplicada pelo humano (ou com o hook ampliado); o ml-engineer registra a necessidade no dev-report.

## 5. Critérios de aceite

- **CA-01** — *Dado* `build_model("mobilenetv3_large_100", 3, "ce", pretrained=False)` (com `importorskip("torch")`), *quando* recebe um tensor `[2,3,224,224]`, *então* devolve `[2,3]` e `[2,5]`; com `"corn"`, `[2,3]` e `[2,4]`; pelo `ProbabilityWrapper`, cada linha soma 1 (±1e-5) e não há valor negativo.
- **CA-02** — *Dado* logits CORN `[0, 0, 0, 0]`, *quando* convertidos, *então* `grade_probs = [0.5, 0.25, 0.125, 0.0625, 0.0625]` (±1e-6).
- **CA-03** — *Dado* um batch com todos os `grade_idx = -1`, *quando* a loss é calculada, *então* é finita e igual à CE de tipo; *dado* um batch misto, o termo de grau é igual à CE só das linhas com `grade_idx >= 0`.
- **CA-04** — *Dado* contagens de treino `{perfect: 100, good: 100, fair: 100, poor: 100, unusable: 40}`, *quando* `grade_class_weights` é chamado, *então* retorna `[0.88, 0.88, 0.88, 0.88, 2.2]` (±1e-9); com `unusable: 55`, retorna `None`; com `unusable: 0`, levanta `TrainError`.
- **CA-05** — *Dado* `EarlyStopper(patience=5, min_delta=1e-4)` e QWKs `[0.50, 0.60, 0.60, 0.60, 0.60, 0.60, 0.60]`, *quando* alimentado época a época, *então* pede a parada na 7ª época e `best_epoch = 2`.
- **CA-06** — *Dado* uma config com `epochs_a = 12` e `smoke = false`, *quando* carregada, *então* levanta `ConfigError`; com `smoke = true`, carrega; com `model_version = "PartQC v1"`, levanta `ConfigError`.
- **CA-07 (slow)** — *Dado* um dataset sintético (SPEC-011, `items_per_stratum=4`) com split e uma config `smoke` (`mobilenetv3_small_050`, `pretrained=false`, 1 época em cada fase, `num_workers=0`), *quando* `python -m qc_ml.pipeline` roda com raízes em `tmp_path`, *então* existem `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json`, `decision.json`, `metrics.json`, `training_config.json`, `parity_fixture.npz`, `thresholds_report.json` e os 2 PNGs.
- **CA-08 (slow)** — *Dado* o resultado do CA-07, *quando* os artefatos são inspecionados, *então* o `training_config.json` tem todas as chaves de §4.2, `versions` inclui `torch`, `timm` e `onnxruntime`, e `split_sha256` é igual ao do arquivo `.sha256` do split.
- **CA-09 (slow)** — *Dado* duas execuções smoke com a mesma seed em CPU, *quando* comparadas, *então* os `history` têm `val_grade_qwk`, `train_loss` e `val_loss` iguais (±1e-6).
- **CA-10 (slow)** — *Dado* o `model.onnx` do CA-07, *quando* inspecionado, *então* `onnx.checker` passa, o opset é ≥ 17, a entrada chama `image`, as saídas `type_probs` e `grade_probs`, e o onnxruntime aceita batches de 1 e de 3 (`[1,3]`/`[1,5]` e `[3,3]`/`[3,5]`), com linhas somando 1 (±1e-5).
- **CA-11** — *Dado* qualquer diretório de modelo gerado (incluindo a fixture), *quando* lido, *então* `model.sha256` tem 64 hex + `\n` e é igual ao `hashlib.sha256` do `model.onnx`.
- **CA-12 (CI, sem torch)** — *Dado* `ml/tests/fixtures/tiny_model/`, *quando* `check_parity` roda só com onnxruntime, *então* `ok = True`, `max_abs_diff < 1e-4` e argmax idêntico; o teste também roda para cada `ml/models/*/` que tenha `model.onnx` local (senão, `skip`).
- **CA-13** — *Dado* uma cópia da fixture com `type_probs[0, 0] += 1e-3` (no array float32 da fixture), *quando* `check_parity` roda, *então* `ok = False` e `9e-4 < max_abs_diff < 1.1e-3`. (Os limites são `1e-3 ∓ 1e-4`: pela desigualdade triangular, a diferença medida fica a no máximo `|onnx − torch|` da perturbação, e o CA-12 garante `|onnx − torch| < 1e-4`; o ruído real é ~1e-8, e o arredondamento float32 da soma, ≤ 6e-8. Nunca comparar com `1e-3` exato.)
- **CA-14** — *Dado* o repositório, *quando* `ml/tests/fixtures/tiny_model/` é inspecionado, *então* tem os 6 arquivos de §4.10, soma < 1 MB e `git check-ignore` não ignora nenhum deles.
- **CA-15 (R-11)** — *Dado* `Predictions` com `split="test"` (ou `"train"`), *quando* `choose_thresholds` é chamado, *então* levanta `SplitIntegrityError` e nada é gravado.
- **CA-16** — *Dado* 100 imagens de val `screw` com argmax correto e `max(type_probs) = 0.503 + 0.005·i` (i = 0…99), *quando* os limiares são escolhidos, *então* `type_threshold = 0.52`; *dado* 6 dessas imagens com argmax `other`, *então* `type_threshold = 0.50` e a nota `type_target_not_met`.
- **CA-17** — *Dado* 10 imagens de val `unusable` com `p_poor = 0.55`, `p_unusable` = `[0.45, 0.40, 0.35, 0.30, 0.25, 0.22, 0.18, 0.15, 0.125, 0.05]` e o resto em `fair`, *quando* os limiares são escolhidos, *então* `unusable_threshold = 0.12` e o recall de `unusable` na val é 0,9; *dado* `p_unusable = 0.01` em todas, *então* a nota `unusable_target_not_met` aparece.
- **CA-18** — *Dado* 100 imagens de val `screw` com `type_probs = [0.99, 0.005, 0.005]` e confiança de grau `0.3025 + 0.005·i`, *quando* os limiares são escolhidos, *então* `type_threshold = 0.85`, `grade_review_threshold = 0.35` e a fração `needs_review` resultante é 10%; com confiança `0.5525 + 0.005·i`, `grade_review_threshold = 0.60`.
- **CA-19** — *Dado* a fixture e um dataset sintético com split, *quando* `python -m qc_ml.thresholds` roda, *então* o `decision.json` tem exatamente as 3 chaves, com valores de 2 casas nas grades de §4.6, e o `thresholds_report.json` existe.
- **CA-20 (R-11)** — *Dado* um espião em `qc_ml.split.rows_for` que registra o `which` e se o `decision.json` já existe, *quando* `thresholds` e depois `evaluate` rodam (CI, com a fixture) e quando o pipeline smoke roda (slow), *então* `"test"` é pedido exatamente uma vez, pelo `evaluate`, com o `decision.json` já existente; treino, export e limiares só pedem `"train"`/`"val"`.
- **CA-21** — *Dado* um diretório de modelo sem `decision.json`, *quando* `python -m qc_ml.evaluate` roda, *então* sai com código 2, a mensagem contém `run qc_ml.thresholds first` e nenhum `metrics.json` é criado.
- **CA-22** — *Dado* a fixture e um dataset sintético, *quando* `evaluate` roda (CI), *então* as chaves de topo do `metrics.json` são exatamente as de §4.7 (incluindo `grade_qwk_ci95`, `unusable_recall_ci95`, `defective_recall_ci95`, `n_items_test_by_grade` e `warnings`), cada `*_ci95` é `[low, high]` com `low ≤ high` (ou `null`), `warnings` é lista de strings, `type_confusion` é 3×3, `grade_confusion` é 5×5, `grade_per_class` tem os 5 graus (com `null` onde `support = 0`), a soma da `grade_confusion` é o nº de imagens de teste com grau, toda métrica de taxa está em [0, 1] ou é `null`, e os 2 PNGs existem.
- **CA-23** — *Dado* graus verdadeiros `[0,1,2,3,4,0,1,2,3,4]` e previstos `[0,1,2,4,4,0,2,2,3,4]`, *quando* as métricas de grau são calculadas, *então* `grade_qwk` = 0,9524 (20/21, ±1e-4), `grade_mae = 0.2`, `grade_off_by_one_accuracy = 1.0`, `unusable_recall = 1.0`, `unusable_precision` = 0,6667, `defective_recall = 1.0` e `defective_precision = 1.0`.
- **CA-24** — *Dado* um `metrics.json` existente, *quando* `evaluate --latency-only --latency-machine "notebook-borda"` roda, *então* só `latency_ms_p50`, `latency_ms_p95`, `latency_machine` e `latency_runs` mudam, com `latency_runs = 100`.
- **CA-25** — *Dado* um `metrics.json` com `type_accuracy = 0.93127`, `grade_qwk = 0.75` e `latency_ms_p95 = 120.00001`, *quando* `python -m qc_ml.report changelog` roda, *então* a linha de acurácia mostra `0,9312` (corte para baixo: maior é melhor), meta `≥ 0,95` e status `abaixo da meta`; a de QWK mostra `0,7500` e `atingida`; e a de latência mostra `120,0001` (arredondado para cima: menor é melhor) e `atingida` (`docs/architecture.md` §7, "Exibição das métricas").
- **CA-26 (R-03)** — *Dado* `ml/notebooks/train_colab.ipynb`, *quando* lido como JSON, *então* toda célula de código tem `outputs = []` e `execution_count = null`, nenhuma contém `def ` ou `class `, alguma contém `python -m qc_ml.pipeline`, e nenhuma casa `ghp_|github_pat_|token\s*=\s*["']`.
- **CA-27 (CI sem torch)** — *Dado* um subprocesso com `sys.modules["torch"] = None`, *quando* importa `qc_ml.predict`, `decision`, `thresholds`, `evaluate`, `parity` e `report`, *então* não ocorre `ImportError`.
- **CA-28 (manual)** — Treino real v1: 1. no Colab, rodar o notebook com o dataset real e `split_v1`; 2. conferir que o pipeline terminou com exit 0; 3. copiar os artefatos para `ml/models/partqc-mnv3-v1/` e `ml/reports/partqc-mnv3-v1/`; 4. rodar `evaluate --latency-only` no notebook da borda; 5. gerar a entrada do CHANGELOG e conferir que cada número é igual ao do `metrics.json`; 6. rodar o teste de paridade localmente com o `model.onnx` real (passa); 7. publicar o Release. **Passa** se os passos 2, 5 e 6 forem cumpridos, independentemente de as metas do PRD serem atingidas.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Funções puras (pesos, early stopping, CORN, decisão, métricas, limiares); export e treino com `importorskip("torch")` | `ml/tests/` |
| Aceite (tester) | Um por CA; os marcados *slow* usam `@pytest.mark.slow` + `importorskip("torch")` | `ml/tests/acceptance/test_spec_012.py` |
| Manual (dupla) | CA-28 | Colab + notebook da borda |

**Rodada r2 (SPEC_ISSUE-01):** a r2 só ajusta os dois testes do CA-13 ao novo texto: `ml/tests/test_parity.py::test_ca13_perturbed_fixture_fails` (autor, ml-engineer) e `ml/tests/acceptance/test_spec_012.py::test_ca13_perturbed_fixture_fails_parity` (tester). Nenhum código de `ml/src/`, fixture ou outro teste muda.

Sem internet nos testes (`pretrained=False`). Dados sempre do `make_synthetic_dataset` em `tmp_path`. Unitário extra: se `qc_edge` estiver instalado (`importorskip`), `qc_ml.decision` e `qc_edge.decision` dão o mesmo resultado em 1.000 vetores aleatórios.

## 7. Riscos e notas para o implementador

- **Metas do PRD §7 são alvos, não critério desta SPEC.** A SPEC passa se o pipeline está correto e as métricas são reportadas como medidas. A comparação com as metas vai no `ml/models/CHANGELOG.md`, inclusive quando abaixo.
- O `decision.json` tem só as 3 chaves de `architecture.md` §7; os metadados ficam no `thresholds_report.json`.
- A regra de decisão existe em `qc_edge.decision` (SPEC-008) e em `qc_ml.decision`; o teste cruzado acima reduz o risco de divergência.
- Colab: a versão do Python pode mudar; o notebook falha cedo se não for 3.12 (R-12). Desconexões: use `--resume`.
- `parity_fixture.npz` com 8 entradas ocupa alguns MB por versão; aceitável (só JSON/NPZ no Git).
- **CA-27 e `sklearn`/`scipy`:** com `sys.modules["torch"] = None`, o próprio `import sklearn.metrics` quebra, com `AttributeError: 'NoneType' object has no attribute 'Tensor'` vindo do scipy, mesmo que o módulo do `qc_ml` não importe torch. O reviewer da SPEC-011 reproduziu isso na r1 (`reviews/SPEC-011/r1-review-report.md`, "Avaliação das decisões do dev-report r1"). Por isso, nos módulos do CA-27 (`predict`, `decision`, `thresholds`, `evaluate`, `parity`, `report`), `sklearn` e `scipy` são importados **dentro** da função que os usa, nunca no nível do módulo, como o `qc_ml.agreement` da SPEC-011 faz com o `cohen_kappa_score`. O import adiado leva um comentário com o motivo. O CA-27 não muda e continua com `sys.modules["torch"] = None`. No CI real, sem torch instalado, os dois jeitos funcionam; o adiamento existe para o CA, que simula a ausência do torch.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); os *slow* rodados localmente com torch e registrados no relatório
- [ ] review-report APPROVED
- [ ] CI verde (sem torch); `ruff` limpo
- [ ] README de `ml/` com o fluxo Colab → artefatos → Release
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | §4.8: o valor da tabela do CHANGELOG segue a regra única de exibição de `docs/architecture.md` §7 (4 casas, nunca a favor da meta: corte para baixo quando maior é melhor, arredondamento para cima quando menor é melhor, IC alargado; status pelo valor bruto), a mesma do dashboard (SPEC-028). CA-25 alterado: `0,9313` → `0,9312`, com casos novos de QWK (`0,7500`, `atingida`) e de latência (`120,0001`). Nenhum outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | RV-07 de `reviews/SPEC-013/r1-review-report.md` (o CHANGELOG arredondava ao mais próximo e o painel cortava, e cortar uma métrica em que menor é melhor a deixava melhor que a medida, contra a intenção do R-11) | Orquestrador, a pedido do humano |
| 2026-10-18 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
| 2026-10-18 | Só texto: §7 ganha a nota de que, nos módulos do CA-27, `sklearn` e `scipy` são importados dentro da função, porque `sys.modules["torch"] = None` quebra o import do scipy. Nenhum requisito, assinatura ou CA muda, por isso a SPEC **não** volta para reaprovação. A SPEC-011 passou a ter `item_history` e o parâmetro `history` em `make_split` (SPEC_ISSUE-01 da r2), sem efeito nesta SPEC: `load_split`, `rows_for` e o formato do `split_v<N>.*` não mudaram. | Observação do reviewer em `reviews/SPEC-011/r1-review-report.md` ("Avaliação das decisões do dev-report r1": `sklearn` dentro de `compute_agreement`) | Orquestrador |
| 2026-10-19 | Correção do SPEC_ISSUE-01 (r2). CA-13: `max_abs_diff ≥ 1e-3` → `9e-4 < max_abs_diff < 1.1e-3`, com a perturbação explicitamente no array float32 e a justificativa dos limites (`1e-3 ∓ 1e-4`, pela desigualdade triangular e pelo `< 1e-4` do CA-12). A intenção não muda: uma perturbação 10 vezes acima da tolerância é detectada (`ok = False`), e o `max_abs_diff` a reflete; o limite superior novo confirma que a medida é a diferença absoluta da entrada perturbada. §6: a r2 só ajusta os dois testes do CA-13. Nenhum requisito, assinatura ou outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | CI da `main` (GitHub Actions, run 39191665982): `ml/tests/test_parity.py::test_ca13_perturbed_fixture_fails` e `ml/tests/acceptance/test_spec_012.py::test_ca13_perturbed_fixture_fails_parity` falharam com `max_abs_diff = 0.0009999759495258331`. A fixture é float32 e a saída do onnxruntime no runner difere da gravada em ~1e-8, então a diferença após a perturbação pode ficar um pouco abaixo de `1e-3` conforme a CPU (passou localmente e no CI do PR #31) | Orquestrador |
| 2026-10-19 | Correção do SPEC_ISSUE-01 (CA-13) aprovada pelo orquestrador, sob a delegação explícita do humano em 2026-10-19 ("total autonomia para prosseguir com o projeto"); `Blocked` → `In Dev` na r2. | Fluxo do loop (§4 da skill `features`) | Orquestrador (delegação do humano) |
