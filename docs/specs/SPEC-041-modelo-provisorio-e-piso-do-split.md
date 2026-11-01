# SPEC-041: Modelo provisório para o ensaio, separado do oficial, e piso do `split_v1`

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer (Parte A: `ml/`), depois developer (Parte B: `edge/`), na mesma rodada |
| Tags | security |
| Depende de | ADR-024 `Aceito`; SPECs 008, 011, 012, 035, 036 e 040 mergeadas |
| Semana alvo | S4 (02–08/11), para o ensaio do fluxo sair antes do M2 |
| Requisitos cobertos | RF-03, RF-04, RF-13, RNF-02 (só indicativo), RNF-07; R-02, R-06, R-11, R-12, R-14; PRD §7 (protege, não muda) |
| ADRs relevantes | ADR-024, ADR-004, ADR-014, ADR-020, ADR-021 |

> **Reaprovada pelo orquestrador sob o ADR-019 em 2026-11-01:** SPEC_ISSUE-01, 02, 03 e 05. Ver o Histórico.
>
> **Reaprovada pelo humano em 2026-11-01:** SPEC_ISSUE-04 (§4.9 e CA-28). Ver o Histórico.

## 1. Contexto

O dataset próprio tem zero fotos, e o pipeline oficial não roda só com imagens externas (ADR-024, Contexto). O ADR-024 cria duas trilhas: um modelo **provisório**, só para ensaiar o fluxo, e o modelo **oficial**, único com métricas, que só nasce com o piso do `split_v1`.

Esta SPEC faz as guardas valerem no código. Seções de `docs/architecture.md`: §6.2 (fluxo da inspeção, `source`), §6.3 (importação) e §7 (artefatos). O número do piso e o que ele permite afirmar estão no Anexo do ADR-024.

## 2. Objetivo

`python -m qc_ml.provisional` gera, só com imagens externas, um diretório de modelo que a borda carrega e cujas inspeções saem `source=simulated`, sem nenhum caminho até `metrics.json`, CHANGELOG, Release ou a carta `live`; um grau sugerido por agente (`labeler=agent-suggestion`) não chega a nenhum dataset oficial; e `python -m qc_ml.split` recusa um `split_v1` abaixo do piso.

## 3. Escopo

### 3.1 Dentro

**Parte A (ml-engineer):**

- `ml/src/qc_ml/provisional.py` e a CLI (§4.2 a §4.4), importável sem torch;
- `ml/src/qc_ml/config.py`: `is_provisional_version` e a recusa no `TrainConfig` (§4.1 e §4.5);
- `ml/src/qc_ml/report.py`: recusa de versão provisória (§4.5);
- `ml/src/qc_ml/split.py`: piso do `split_v1` e `--allow-below-floor` (§4.6);
- `ml/src/qc_ml/data.py`: `AGENT_SUGGESTION_LABELER` e a recusa no `load_manifest` (§4.9);
- `ml/src/qc_ml/synthetic.py`: `items_per_stratum=0` aceito quando `external_items_per_stratum > 0`, e o parâmetro `labeler: str = LABELER`, aplicado a todas as linhas, para os testes. Sem passar esses valores, os arquivos gerados continuam iguais byte a byte;
- `ml/README.md` e os testes em `ml/tests/`.

**Parte B (developer):**

- `edge/src/qc_edge/inference.py`, `app.py` e `cli.py` (§4.7);
- `edge/src/qc_edge/importer.py`: `--provisional-set` (§4.9);
- `edge/README.md` e os testes em `edge/tests/`.

**Documentação pelo architect, junto com esta SPEC:** `docs/dataset-protocol.md` (§4, §7, §10.1, §11 e histórico), `docs/architecture.md` (§6.2 e §7), `docs/professor-questions.md` (pergunta 10) e `docs/plan.md`.

### 3.2 Fora

- Sugerir os graus, conferir a privacidade, importar, treinar, ensaiar e coletar as fotos: operação depois do merge, fora do código (§4.8).
- O treino oficial e o Release: CA-28 da SPEC-012, sem mudança.
- A latência oficial: CA-16 da SPEC-008, sem mudança.
- Filtro por `model_version` na API ou no painel, e mudanças de contrato: não entram (ADR-024, pergunta 6). O painel já mostra a coluna `Modelo` e o selo de simulado.
- Publicar o modelo provisório: proibido (ADR-024).
- `POST /api/live/frame` (SPEC-019, ainda não implementada): quando for feita, ela usa a mesma regra do §4.7 (SPEC-019 §4.4).

## 4. Requisitos detalhados

### 4.1 O nome decide

Uma versão é provisória se, e somente se, contém a substring `-provisional-`. Duas funções, sem dependências e com a mesma regra, porque `qc_ml` não importa `qc_edge` nem o contrário, e o contrato não muda (R-04):

```python
qc_ml.config.is_provisional_version(model_version: str) -> bool
qc_edge.inference.is_provisional_version(model_version: str) -> bool
```

### 4.2 `python -m qc_ml.provisional`

```text
python -m qc_ml.provisional --dataset-dir <D> --models-root <M>
    [--external-sources <R>] [--model-version partqc-mnv3-provisional-v1]
    [--epochs 8] [--seed 42] [--smoke]
```

- Sai com 0 no sucesso e 2 em qualquer erro, com a mensagem na stderr, sem gravar nada.
- Sem `--smoke`: backbone `mobilenetv3_large_100` (N-01), `pretrained=True`, `epochs` de 5 a 10.
- Com `--smoke` (só para testes): `mobilenetv3_small_050`, `pretrained=False`, 1 época, `num_workers=0`.
- **Treino:** só a fase A do `qc_ml.train` (`set_trainable(model, None)`, AdamW com `lr=1e-3` e `weight_decay=1e-4`, `batch_size=32`), com a loss, o label smoothing e os pesos de classe de sempre (`compute_loss`, `grade_class_weights`, `graded_training_counts`). Sem validação, sem early stopping e sem checkpoints. O modelo final é o da última época.
- **Reuso obrigatório:** `load_manifest` (com `allow_agent_suggestion=True`, a única chamada que passa esse valor), `derive_model_labels` com `check_labels`, `PartsDataset`, `build_model`, `set_trainable`, `write_model_dir` (com a paridade) e `write_decision`. Um helper privado pode ser tornado público sem mudar o comportamento.
- **Proibido:** chamar `qc_ml.split.load_split` ou `rows_for`, ler ou gravar `split_v*`, `thresholds` ou `evaluate`.
- `decision.json`: fixo em `type_threshold=0.50`, `unusable_threshold=0.50` e `grade_review_threshold=0.60`, porque não há validação.
- Saída em `<M>/<model_version>/`, com **exatamente**: `model.onnx`, `model.sha256`, `labels.json`, `preprocessing.json`, `decision.json`, `parity_fixture.npz` e `provisional_report.json`.

### 4.3 Recusas, nesta ordem

| Condição | Mensagem na stderr (saída 2) |
|---|---|
| `--model-version` sem `-provisional-`, ou fora de `VERSION_NAME_PATTERN` e do padrão do contrato | `not a provisional model version` |
| `--dataset-dir` ou `--models-root` (depois de `realpath`) dentro de um repositório Git, pela mesma regra de `qc_edge.importer.inside_git_repository` | `provisional paths must be outside a Git repository` |
| `<M>/<model_version>/` já existe e não está vazio | `model directory already exists` |
| manifest inválido (`ManifestError`) | a lista de problemas, com `print_problems(exc.problems, sys.stderr)`, como `qc_ml.split` |
| alguma linha com `item_id` não externo | `provisional dataset has own images: <n>` |
| alguma linha mantida do manifest, ou de `labels_overrides.csv` de imagem não excluída, com `labeler` diferente de `agent-suggestion` (§4.9) | `provisional dataset has other labelers: <n>` |
| algum `object_type` fora de `screw`, `nut`, `other` | `provisional dataset has other types: <lista>` |
| falta um de `screw`, `nut`, `other` | `provisional dataset needs the types: <lista>` |
| um grau sem imagem | o `TrainError` já existente: `no training image with grade <grau>…` |
| `epochs` fora de 5 a 10, sem `--smoke` | `epochs must be in [5, 10]` |
| sem torch | o `TrainError` já existente: `training needs the train extra…` |

O `<n>` de `other labelers` soma as linhas dos dois arquivos. O `load_manifest` não muda por isso: depois de ele validar o conjunto, o `qc_ml.provisional` lê `labels_overrides.csv` com `parse_csv` e pula as imagens de `df.attrs["excluded_items"]`.

Em caso de erro depois de começar a gravar (treino ou paridade), o diretório do modelo é apagado.

### 4.4 `provisional_report.json`

Chaves **exatamente**: `model_version`, `model_sha256`, `provisional` (`true`), `created_at` (UTC), `manifest_sha256`, `n_images`, `n_items`, `images_by_type_grade` (tipo → grau ou `none` → int), `by_source` (`source_id` → int), `epochs`, `seed`, `smoke`, `train_loss_by_epoch`, `decision_source` (`"fixed_defaults"`), `versions` (como no `training_config.json`), `git_commit` (ou `null`) e `notice`, com o texto exato:

`Provisional model for rehearsal only (ADR-024). Grades are agent suggestions, not human labels. No validation or test split; no quality metric exists for this model.`

Do `qc_ml.evaluate.METRIC_KEYS`, só entram as três chaves de identidade, que não medem qualidade: `model_version`, `model_sha256` e `manifest_sha256`. Nenhuma outra chave desse conjunto entra, e nenhuma chave começa com `val_`.

### 4.5 Guardas no caminho oficial

- `TrainConfig`: `model_version` provisória dá `ConfigError` com `provisional model versions are not allowed in the official pipeline`. Com isso, `qc_ml.train`, `export`, `thresholds`, `evaluate` e `pipeline` saem com 2, sem mudança neles.
- `qc_ml.report changelog` e `release-notes`: `--model-dir` cujo nome é provisório sai com 2 e `provisional model: no official report`, sem gravar nada, antes de ler o `metrics.json`.

### 4.6 Piso do `split_v1`

Só em `qc_ml.split.main`, quando não há nenhum `split_v*` anterior; `make_split` não muda de comportamento.

- Depois de `make_split` e antes de gravar, a função pública `floor_problems(df, frame) -> list[str]` devolve os estratos que faltam no teste, em ordem lexicográfica. Os estratos exigidos são os 10 de `screw`/`nut` × grau e `other/none`, contando só as peças não externas. Exemplo: `nut/fair`.
- Com problemas e sem a flag: uma linha `split_v1 below the floor: <estrato>` por estrato, saída 2, nada gravado.
- `--allow-below-floor`: grava mesmo assim e acrescenta a `warnings` do `split_v1.json` um `{"code": "below_floor", "stratum": <estrato>}` por estrato. Uso só com decisão registrada (ADR-024).
- A partir do `split_v2`, nem a recusa nem a flag têm efeito (a flag é aceita e ignorada, com um aviso no log).
- O piso de 3 fotos por peça é do protocolo e **não** é conferido aqui. O `data_report` já mostra `images_per_item`.

### 4.7 Borda

- `inspect` em `app.py`: `source=Source.SIMULATED` quando `is_provisional_version(model.model_version)`; senão, `Source.LIVE`, como hoje.
- Na resposta da captura, com versão provisória, `labels_pt.verdict` recebe o sufixo `" (modelo provisório)"` em todos os casos, inclusive `desconhecido`. Nenhuma mudança em `capture.js` (que está no teto de 200 linhas): ele já mostra `labels.verdict`. `approved` não muda.
- `_model_state`, no console: acrescenta ` — PROVISÓRIO: resultados publicados como simulados (ADR-024)`.
- Na subida (`cli.py`): `WARNING provisional model loaded: results are published as source=simulated (ADR-024)`.
- `/api/status`, o heartbeat, o outbox, o publisher, o contrato e a API não mudam. O `--stub-model` também não muda.

### 4.8 Procedimento de operação, depois do merge (vai para `ml/README.md`)

1. **Dupla ou orquestrador:** criar `~/partqc-provisorio/data` e `~/partqc-provisorio/models`.
2. **Agente (`ml-engineer`, a pedido do orquestrador, sem commit):** em `~/partqc-entrada/candidatos/`, aplicar a rubrica (`docs/dataset-protocol.md` §1) a cada recorte e preencher o plano, fora do repositório, com `grade` e `labeler=agent-suggestion`. O `sugestoes.csv` e o rótulo da fonte são só pistas. Recorte sem decisão sai do plano. Só recortes das fontes registradas, nunca foto da dupla ou de conhecidos. Tamanho sugerido: as 46 `unusable` candidatas, cerca de 50 `perfect`, poucas `?`, os recortes da SDNET para `good`, `fair`, `poor` e **porca** (hoje, a única fonte de `nut`), e os 104 YCB.
3. **Agente, no mesmo pedido (ADR-024, decisões 4 e 6; `docs/dataset-protocol.md` §11):** conferir as folhas de contato de todos os recortes do plano, com os da SDNET já recortados, e apagar a linha e o arquivo de qualquer recorte com pessoa, placa ou documento. As folhas que faltarem são geradas em `~/partqc-provisorio/folhas`. Um recorte de uma original da SDNET com moldura `PRIV` ou `PRIV?` nas folhas existentes (`LEIAME.md`) também sai do plano. O humano assume essa conferência ao aprovar, sem outro passo. Só depois disso, `--privacy-checked` é verdadeiro; a opção e a mensagem da SPEC-036 não mudam. Fora deste conjunto, a conferência continua humana (§10.5).
4. `uv run --package qc-edge python -m qc_edge.importer --dataset-dir ~/partqc-provisorio/data --inbox ~/partqc-entrada/candidatos --plan <plano> --privacy-checked --provisional-set --dry-run`; conferir as linhas `failed`; rodar sem `--dry-run`.
5. `uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ~/partqc-provisorio/data` (`0 with private data`). Não rode `qc_ml.data validate` nessa pasta: ele recusa `agent-suggestion` de propósito (§4.9), e o passo 6 valida o manifest antes de treinar.
6. `uv sync --all-packages --extra train` e `uv run --package qc-ml python -m qc_ml.provisional --dataset-dir ~/partqc-provisorio/data --models-root ~/partqc-provisorio/models`. Treino no notebook, sem Drive nem Colab.
7. `MODEL_DIR=~/partqc-provisorio/models/partqc-mnv3-provisional-v1` na borda; lotes `ENSAIO-…`.
8. Depois da entrega, apagar `~/partqc-provisorio/` e as pastas de entrada (§10.6).

### 4.9 `labeler` de sugestão e proibição no dataset oficial

O valor fixo é `agent-suggestion`, em duas constantes iguais, porque `qc_ml` não importa `qc_edge` nem o contrário:

```python
qc_ml.data.AGENT_SUGGESTION_LABELER = "agent-suggestion"
qc_edge.importer.AGENT_SUGGESTION_LABELER = "agent-suggestion"
```

`qc_edge.collect.LABELERS` continua `{"a", "b"}`: o modo coleta nunca aceita esse valor.

**No ML (`qc_ml.data`):**

```python
load_manifest(dataset_dir, *, apply_overrides=True, verify_images=True, external_sources=None,
              allow_agent_suggestion: bool = False) -> pd.DataFrame
```

- Com `allow_agent_suggestion=False` (padrão), cada linha **mantida** do manifest (fora de `exclusions.csv`) com `labeler == "agent-suggestion"` gera o problema `agent_suggestion_label` (`file=manifest.csv`). O mesmo código vale para uma linha de `labels_overrides.csv`, de imagem não excluída, com esse `labeler` (`file=labels_overrides.csv`). A mensagem é fixa: `agent-suggested labels are only allowed in the provisional set (ADR-024)`.
- Linha excluída não gera problema, para a §8.1 do protocolo continuar servindo de saída.
- Nenhuma chamada existente muda: `qc_ml.data`, `split`, `train`, `thresholds`, `evaluate` e `pipeline` usam o padrão e, portanto, recusam, em qualquer `DATASET_DIR`. Eles já convertem `ManifestError` em saída 2. O `export` também usa o padrão, mas só lê o dataset sintético da paridade, nunca o `DATASET_DIR`, e por isso não tem essa recusa.

**Na importação (`qc_edge.importer`), nova opção `--provisional-set`:**

| Situação | Resultado (saída 2, nada gravado) |
|---|---|
| Sem a opção, linha com `labeler=agent-suggestion` | `invalid_labeler`, como qualquer valor fora de `LABELERS` |
| Com a opção, `--dataset-dir` (depois de `realpath`) dentro de um repositório Git, pela `inside_git_repository` | `provisional set must be outside any git repository`, na primeira verificação do `load_plan`: antes das recusas da pasta de entrada e do plano (SPEC-038 §4.7) e de ler o dataset e o plano |
| Com a opção, manifest existente com alguma linha cujo `labeler` não é `agent-suggestion` | `dataset is not a provisional set` |
| Com a opção, linha com `labeler` diferente de `agent-suggestion` | `invalid_labeler` |
| Com a opção, linha com `origin` diferente de `external` | `invalid_origin` |

Sem a opção, o comportamento da SPEC-036 não muda. `--privacy-checked` continua obrigatório nos dois casos, e `ManifestEntry` e `read_manifest_entries` não mudam: a leitura do `labeler` fica no `load_plan`, só com a opção.

**Limite conhecido (ADR-024):** a guarda é pelo `labeler`. Um recorte reimportado à mão com `labeler` `a` ou `b` não é detectado; aí a proibição é só a regra de `docs/dataset-protocol.md` §11.

## 5. Critérios de aceite

**Piso (os números do ADR-024):**

- **CA-01** — *Dado* `make_synthetic_dataset(items_per_stratum=3, images_per_item=3)` (33 peças, 99 imagens) e nenhum split anterior, *quando* `python -m qc_ml.split` roda, *então* sai com 0, grava `split_v1`, cada split tem 11 peças e 33 imagens, e `warnings` é `[]`.
- **CA-02** — *Dado* o dataset do CA-01 sem as imagens de uma peça `nut`/`fair` (32 peças), *quando* a CLI roda sem flag, *então* sai com 2, a stderr tem a linha `split_v1 below the floor: nut/fair` e nenhum arquivo `split_v1.*` existe.
- **CA-03** — *Dado* o dataset do CA-02, *quando* a CLI roda com `--allow-below-floor`, *então* sai com 0 e o `split_v1.json` tem `{"code": "below_floor", "stratum": "nut/fair"}` e o `small_stratum` de `nut/fair`. *Dado* um `split_v1` já existente e peças novas abaixo do piso, *quando* a CLI roda sem flag, *então* sai com 0, sem `below_floor`.
- **CA-04** — *Dado* o dataset do CA-01 com `external_items_per_stratum=1` (11 externas de 1 imagem), *quando* a CLI roda, *então* sai com 0 e `external_fraction_train = 0.25`; com `external_items_per_stratum=2`, sai com 2, a stderr contém `external fraction in train 22/55`, e nada é gravado.
- **CA-05 (CI, sem torch)** — *Dado* o CA-01 e a fixture `tiny_model`, *quando* `thresholds` e `evaluate` rodam, *então* `n_items_test_by_grade` vale 2 nos 5 graus, `grade_qwk`, `grade_off_by_one_accuracy`, `type_accuracy`, `unusable_recall`, `defective_recall`, `unknown_rate_on_other` e `false_unknown_rate` não são `null`, `warnings` contém `few test items for other: 1` e nenhum `grade <g> has`. *Dado* o mesmo dataset com `other` em 10 objetos, *então* `few test items for other` não aparece.
- **CA-06 (slow)** — *Dado* o CA-01 e uma config `smoke` (1 época por fase, `batch_size` 32, em que o último lote do treino tem 1 imagem), *quando* `python -m qc_ml.pipeline` roda em `tmp_path`, *então* sai com 0 e `metrics.json` existe.

**Modelo provisório (Parte A).** Nos CAs 07 a 14, o dataset usa `labeler="agent-suggestion"`, salvo o que o próprio CA disser.

- **CA-07 (slow)** — *Dado* um dataset só com externas (`items_per_stratum=0`, `external_items_per_stratum=4`, `labeler="agent-suggestion"`, tipos `screw`, `nut`, `other`), *quando* `python -m qc_ml.provisional --smoke` roda, *então* sai com 0, o diretório tem **exatamente** os 7 arquivos do §4.2, `decision.json` é `0.50/0.50/0.60`, `check_parity` dá `ok = True` e o `OnnxInferencer` (`importorskip`) carrega o diretório.
- **CA-08 (slow, R-11)** — *Dado* o CA-07 com espiões em `qc_ml.split.load_split`, `rows_for` e `make_split`, *quando* roda, *então* nenhum é chamado e nenhum `split_v*` é criado.
- **CA-09 (slow)** — *Dado* o `provisional_report.json` do CA-07, *quando* lido, *então* tem exatamente as chaves do §4.4, `provisional = true`, `notice` com o texto exato, nenhuma chave de `METRIC_KEYS` além de `model_version`, `model_sha256` e `manifest_sha256`, e nenhuma começando com `val_`.
- **CA-10** — *Dado* um dataset com uma peça própria (`S-001`) e externas, *quando* a CLI roda, *então* sai com 2, a stderr contém `provisional dataset has own images: <n>` e nada é gravado.
- **CA-11** — *Dado* `--dataset-dir` ou `--models-root` dentro de um repositório Git (`git init` em `tmp_path`, incluindo o caso de uma subpasta), *quando* a CLI roda, *então* sai com 2 e `provisional paths must be outside a Git repository`.
- **CA-12** — *Dado* `--model-version partqc-mnv3-v1`, *então* sai com 2 e `not a provisional model version`; *dado* um diretório de modelo existente e não vazio, *então* sai com 2 e `model directory already exists`, sem alterar o que havia nele.
- **CA-13** — *Dado* um dataset externo sem nenhuma imagem `nut`, *então* sai com 2 e `provisional dataset needs the types: nut`; *dado* um sem imagem `unusable`, *então* sai com 2 e a mensagem contém `no training image with grade unusable`; *dado* `XT-` no dataset, *então* sai com 2 e `provisional dataset has other types`; *dado* `--epochs 12` sem `--smoke`, *então* sai com 2 e `epochs must be in [5, 10]`.
- **CA-14 (CI sem torch)** — *Dado* um subprocesso com `sys.modules["torch"] = None`, *quando* importa `qc_ml.provisional` e roda a CLI com um dataset válido, *então* o import não falha e a saída é 2, com `training needs the train extra`.

**Guardas do caminho oficial (Parte A):**

- **CA-15** — *Dado* uma config com `model_version = "partqc-mnv3-provisional-v1"`, *quando* `load_config` roda, *então* levanta `ConfigError` com `provisional model versions are not allowed`; e `python -m qc_ml.pipeline`, `thresholds` e `evaluate` com essa config saem com 2.
- **CA-16** — *Dado* um diretório `partqc-mnv3-provisional-v1` com um `metrics.json` válido plantado, *quando* `qc_ml.report changelog` e `release-notes` rodam, *então* saem com 2 e `provisional model: no official report`, e nenhum arquivo é escrito nem alterado.

**Borda (Parte B, R-06):**

- **CA-17** — *Dado* um modelo dummy (o dos testes da SPEC-008) num diretório `partqc-mnv3-provisional-v1`, com o outbox real em `tmp_path`, *quando* `POST /api/capture` roda no modo `inspect`, *então* responde 200, `inspection.source = "simulated"`, a linha do outbox tem `source = simulated`, `labels_pt.verdict` termina em ` (modelo provisório)` e a página não recebe nenhum campo novo.
- **CA-18** — *Dado* o mesmo modelo num diretório `partqc-mnv3-v1`, *quando* a mesma requisição roda, *então* `inspection.source = "live"` e `labels_pt.verdict` é um dos rótulos atuais, sem sufixo.
- **CA-19** — *Dado* o modelo do CA-17, *quando* o console é lido (loopback) e a borda sobe pela CLI, *então* a página contém `PROVISÓRIO` e o log tem `provisional model loaded`; com o modelo do CA-18, nenhum dos dois.
- **CA-20** — *Dado* as versões `partqc-mnv3-provisional-v1`, `partqc-provisional-v1`, `partqc-mnv3-v1`, `partqc-mnv3-corn-v2`, `stub-v0` e `provisional`, *quando* as duas funções do §4.1 (com `importorskip("qc_edge")` no lado do ML) são chamadas, *então* dão `True`, `True`, `False`, `False`, `False`, `False`, iguais nos dois pacotes.
- **CA-21 (R-02)** — *Dado* o `InspectionCreate` gerado no CA-17, *quando* serializado, *então* tem só os campos do contrato (`extra="forbid"`) e nenhum dado de imagem.

**Ensaio:**

- **CA-22 (manual)** — Ensaio de ponta a ponta com o provisório. A dupla não rotula nem confere a privacidade dos recortes: os graus e a conferência vêm do agente (§4.8, passos 2 e 3). 1. seguir o §4.8 até o passo 7; 2. fotografar pelo celular, sem intervenção, 20 peças em lotes `ENSAIO-…`; 3. confirmar que cada resposta traz `(modelo provisório)`; 4. no painel, com a origem "Simulado", confirmar as 20 inspeções, o selo e `partqc-mnv3-provisional-v1` na coluna `Modelo`; 5. na carta p com a origem padrão, confirmar que nenhum lote `ENSAIO-…` aparece; 6. em "Sobre o modelo", confirmar que continua `Nenhum modelo avaliado ainda` ou as métricas do modelo oficial, se já existir; 7. confirmar `git status` sem nenhum arquivo do conjunto provisório. **Passa** com os passos 2 a 7 cumpridos, qualquer que seja o acerto do modelo. A qualidade do resultado não é critério, e nenhum número deste ensaio vai para o PRD §7.

**`labeler` de sugestão e proibição no dataset oficial (§4.9):**

- **CA-23 (CI, Parte A)** — *Dado* o dataset do CA-01 com uma linha do manifest com `labeler=agent-suggestion`, *quando* `load_manifest` roda sem argumentos novos, *então* levanta `ManifestError` com o problema `agent_suggestion_label`; e `python -m qc_ml.data validate` e `python -m qc_ml.split` saem com 2, `agent_suggestion_label` aparece na stdout do `validate` e na stderr do `split`, e nenhum `split_v*` é criado. *Dado* o manifest só com `labeler=a` e uma linha de `labels_overrides.csv` com `labeler=agent-suggestion`, *então* o mesmo problema aparece, com `file=labels_overrides.csv`. *Dado* essa imagem seguindo a §8.1 (arquivo apagado e linha em `exclusions.csv`), *quando* `validate` roda, *então* sai com 0.
- **CA-24 (CI, Parte A)** — *Dado* uma config cujo `dataset_dir` tem uma linha com `labeler=agent-suggestion`, um split válido e a fixture `tiny_model`, *quando* `python -m qc_ml.thresholds` e `python -m qc_ml.evaluate` rodam, *então* saem com 2, a stderr contém `agent_suggestion_label` e nenhum `metrics.json` é gravado. *Dado* o mesmo dataset em `python -m qc_ml.pipeline` (slow), *então* sai com 2.
- **CA-25 (CI, Parte A)** — *Dado* um dataset só com externas e **uma** linha com `labeler=a`, *quando* `python -m qc_ml.provisional` roda, *então* sai com 2, a stderr contém `provisional dataset has other labelers: 1` e nada é gravado. *Dado* o manifest só com `agent-suggestion` e uma linha de `labels_overrides.csv` com `labeler=a`, *então* o resultado é o mesmo, com `other labelers: 1`. *Dado* essa imagem seguindo a §8.1 (arquivo apagado e linha em `exclusions.csv`) e `--epochs 12`, *então* sai com 2 e `epochs must be in [5, 10]`, sem `other labelers`. *Dado* o manifest válido de `agent-suggestion` e o subprocesso do CA-14, *então* o erro é o do CA-14, e não um problema de `labeler`.
- **CA-26 (CI, Partes A e B)** — *Dado* `importorskip("qc_edge")`, *quando* as constantes são lidas, *então* `qc_ml.data.AGENT_SUGGESTION_LABELER == qc_edge.importer.AGENT_SUGGESTION_LABELER == "agent-suggestion"` e o valor não está em `qc_edge.collect.LABELERS`. *Dado* `POST /api/capture` no modo `collect` com `labeler=agent-suggestion`, *então* responde 422 e nada é gravado.
- **CA-27 (Parte B)** — *Dado* um dataset em `tmp_path`, fora de repositório Git, e um plano externo válido com `labeler=agent-suggestion`, *quando* `qc_edge.importer` roda **sem** `--provisional-set`, *então* sai com 2, a stderr contém `invalid_labeler` e nada é gravado.
- **CA-28 (Parte B)** — *Dado* `--provisional-set`, `--privacy-checked` e `--dataset-dir` dentro de um repositório (`git init` em `tmp_path`, incluindo a subpasta `ml/data`, ainda inexistente), com a pasta de entrada e o plano fora desse repositório e, em outro caso, dentro dele, *quando* o importador roda, *então*, nos dois casos, sai com 2, a stderr contém `provisional set must be outside any git repository` e não contém `inbox must be outside any git repository`, e `ml/data` não é criada.
- **CA-29 (Parte B)** — *Dado* `--provisional-set`, um dataset fora de repositório Git e um plano externo válido com `labeler=agent-suggestion`, *quando* o importador roda, *então* sai com 0, toda linha do `manifest.csv` tem `labeler=agent-suggestion`, toda linha do `sources.csv` tem `origin=external`, e uma segunda execução com arquivos novos também sai com 0.
- **CA-30 (Parte B)** — *Dado* `--provisional-set`, *quando* o plano tem uma linha com `labeler=a`, *então* sai com 2 e `invalid_labeler`; *quando* tem uma linha com `origin=contributor`, *então* sai com 2 e `invalid_origin`; *quando* o manifest existente tem uma linha com `labeler=a`, *então* sai com 2 e `dataset is not a provisional set`. Em todos os casos, o dataset fica igual byte a byte.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `is_provisional_version`, recusas, `floor_problems`, sufixo do veredito, `agent_suggestion_label`, `--provisional-set` | `ml/tests/test_provisional.py`, `ml/tests/test_split_floor.py`, `ml/tests/test_agent_suggestion.py`, `edge/tests/test_provisional_model.py`, `edge/tests/test_importer_provisional.py` |
| Aceite (tester) | CAs 01 a 16, 20 e 23 a 26, e os slow com `@pytest.mark.slow` e `importorskip("torch")` | `ml/tests/acceptance/test_spec_041.py` |
| Aceite (tester) | CAs 17 a 21 e 26 a 30 | `edge/tests/acceptance/test_spec_041.py` |
| Manual (dupla) | CA-22 | notebook e celular, antes do M2 |

Sem internet nos testes (`--smoke`, `pretrained=False`). Dados sempre sintéticos em `tmp_path`. Nada de banco nem de serviço externo: o que é mockado é só o envio à nuvem. Os CAs slow são rodados localmente com o extra `train` e registrados no relatório.

**Portão de segurança** (tag `security`): o security-devops confere as duas partes, em especial a isolação (CAs 10, 11, 15 a 18 e 23 a 30).

## 7. Riscos e notas para o implementador

- **Testes existentes abaixo do piso.** Um teste que chama a CLI do split sem split anterior e com menos de 3 peças por estrato passa a sair com 2. Esta SPEC autoriza acrescentar `--allow-below-floor` **só nessa chamada**, sem mudar nenhuma asserção: em testes do autor, pelo ml-engineer, e nos de aceite, pelo tester. A lista vai no dev-report. Se a flag não bastar, registre `SPEC_ISSUE`.
- **Lote de 1 imagem (CA-06).** Com 33 imagens no treino e `batch_size=32`, o último lote tem 1 imagem, e a fase B roda com BatchNorm em modo de treino. Pela leitura, isso não quebra, porque os mapas são 2D. O CA-06 existe para confirmar. Se quebrar, registre `SPEC_ISSUE`: não acrescente `drop_last` por conta própria, porque isso muda o treino oficial.
- **Dados de ML nos testes.** Toda a suíte atual usa `labeler=a` (`synthetic.LABELER`), então a recusa do §4.9 não muda nenhum teste. Se mudar, registre `SPEC_ISSUE`.
- **Assinatura interna da importação.** `load_plan` e `_row_problems` ganham um argumento com padrão falso, para os testes atuais da SPEC-036 continuarem iguais.
- **Grau dominante.** `floor_problems` usa `item_strata`, a mesma função da alocação. Uma peça em vários estágios conta só no estrato dominante.
- **Nomes de módulo.** `qc_ml.provisional` importa torch só dentro da função que treina, e `sklearn`/`scipy` seguem a nota do CA-27 da SPEC-012.
- **Sufixo do veredito.** O `.verdict` da página usa `text-transform: uppercase` (`capture.css`), e o texto mais longo quebra a linha. Isso é aceitável e não exige mudança de CSS.
- **R-12:** nenhuma dependência nova em nenhum pacote. **R-13:** os textos não citam fornecedores além das fontes já registradas.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); os slow rodados localmente e registrados
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `ml/README.md` (§4.8) e `edge/README.md` atualizados
- [ ] CA-22 manual registrado (pode ficar pendente no merge, como os outros CAs manuais, marcado no quadro)
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## 9. Respostas do humano

As decisões de fundo estão no ADR-024. Estas são próprias da SPEC. Respostas de 2026-11-01, como relatadas pelo orquestrador ("Aprovar tudo", com todas as recomendações):

1. **A flag `--allow-below-floor` deve existir?** Sim. Sem ela, um `split_v1` abaixo do piso só seria possível mudando o código, e os testes antigos de CLI precisariam de reescrita. Ela só serve com uma decisão registrada.
2. **O treino provisório fica só no notebook, sem Colab?** Sim. Só a fase A em algumas centenas de imagens deve caber na CPU (estimativa, não medida), e assim nada passa pelo Drive. Se ficar lento demais, o caminho é voltar a esta decisão, com o checklist do `docs/dataset-protocol.md` §8.
3. **O CA-22 pode ficar pendente no merge?** Sim. Ele depende da operação do §4.8 (graus e conferência de privacidade pelo agente e fotos pelo celular), e o merge só libera o código, sem impedir a coleta.

O grau por sugestão de agente (ADR-024, decisão 4) veio depois do texto a que o "Aprovar tudo" se referia. Por isso, o §4.9 e os CAs 23 a 30 são texto novo do architect. Eles foram apresentados ao humano por resumo e aprovados em 2026-11-01 (ADR-024, resposta 8). A conferência de privacidade por agente e o que um agente pode ver são as respostas 9 e 10 do ADR-024.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-31 | SPEC criada como `Draft`, com o ADR-024 (`Proposto`). | Zero fotos próprias, sem modelo, com o ensaio em 29/11; decisão de fundo no ADR-024 | Orquestrador, a pedido do humano |
| 2026-11-01 | Alinhada à resposta "Sugestão do agente": `labeler` fixo `agent-suggestion`; `--provisional-set` na importação; recusa no `load_manifest` e no `qc_ml.provisional`; §4.8 refeito (graus pelo agente, privacidade pela dupla, sem `qc_ml.data validate` na pasta provisória); `notice` com a origem dos graus; CA-22 sem rotulagem pela dupla; CAs 23 a 30 novos; §9 com as respostas. Sem mudar o piso, o `source=simulated` e as guardas do caminho oficial já escritos. O status continua `Draft`. | Respostas do humano de 2026-11-01, relatadas pelo orquestrador (ADR-024, decisão 4) | Orquestrador, a pedido do humano |
| 2026-11-01 | Os textos do §4.9 e os CAs 23 a 30 foram apresentados ao humano por resumo e aprovados. §4.8, passo 3: a conferência de privacidade passa a ser de um agente, nas folhas de contato, com a regra das molduras `PRIV` da SDNET acrescentada pelo architect; CA-22 e §9 alinhados. Nenhum código, CA automatizado ou valor muda. O status continua `Draft`. | Respostas do humano de 2026-11-01, relatadas pelo orquestrador (ADR-024, respostas 8 a 10) | Orquestrador, a pedido do humano |
| 2026-11-01 | Aprovada pelo humano (`Draft` → `Ready`), com o ADR-024 `Aceito` e as respostas do §9. | Respostas do humano de 2026-11-01, nesta sessão | Orquestrador, a pedido do humano |
| 2026-11-01 | Correção do SPEC_ISSUE-01 (§4.4, última frase, e CA-09). §4.4, antigo: "Nenhuma chave de métrica do `qc_ml.evaluate.METRIC_KEYS` além de `model_version` e `model_sha256`, e nenhuma começando com `val_`." Novo: "Do `qc_ml.evaluate.METRIC_KEYS`, só entram as três chaves de identidade, que não medem qualidade: `model_version`, `model_sha256` e `manifest_sha256`. Nenhuma outra chave desse conjunto entra, e nenhuma chave começa com `val_`." CA-09, antigo: "nenhuma outra chave de `METRIC_KEYS` e nenhuma começando com `val_`". Novo: "nenhuma chave de `METRIC_KEYS` além de `model_version`, `model_sha256` e `manifest_sha256`, e nenhuma começando com `val_`". A lista das 17 chaves do §4.4 não muda. Evidência: `manifest_sha256` está em `METRIC_KEYS` (`ml/src/qc_ml/evaluate.py:73`), então a chave era exigida e proibida ao mesmo tempo; a interseção das 17 chaves com `METRIC_KEYS` são só essas três, sem nenhuma métrica de qualidade. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-1: SPEC_ISSUE-01. E-2: toca só este arquivo. E-3: aprovada e `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 2: esclarece o §4.4 e ajusta a forma de verificação do CA-09, preservando a intenção (nenhuma métrica de qualidade, decisão 2 do ADR-024). E-5: só os trechos citados. X-1 a X-4: nada de SPEC nova, ADR, outro documento ou contrato. X-5: nenhuma chave nova. X-6: o CA-09 continua exigindo as chaves exatas e recusando as demais. X-7: o CA-09 não verifica regra inegociável (o CA da R-11 é o CA-08, e o ADR-024 registra que a R-11 fica intacta). X-9: primeira correção deste trecho, sem marcação de "exige humano" nem dependência do professor. | SPEC_ISSUE-01 de `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (loop da SPEC-041) |
| 2026-11-01 | Correção do SPEC_ISSUE-02 (CA-23 e §4.3, linha do manifest inválido). CA-23, antigo: "saem com 2, a stderr contém `agent_suggestion_label` e nenhum `split_v*` é criado". Novo: "saem com 2, `agent_suggestion_label` aparece na stdout do `validate` e na stderr do `split`, e nenhum `split_v*` é criado". §4.3, antigo: "a lista de problemas, como `qc_ml.data validate`". Novo: "a lista de problemas, com `print_problems(exc.problems, sys.stderr)`, como `qc_ml.split`". O §4.3 tem a mesma causa: a coluna é "Mensagem na stderr", e o `validate` escreve na stdout. Evidência: `ml/src/qc_ml/data.py:1392` chama `print_problems` sem destino, e o padrão é a stdout (`data.py:1346`); `ml/tests/test_data.py:107`, `:188` e `:359` exigem isso; `ml/src/qc_ml/split.py:1015` já usa a stderr. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-1: SPEC_ISSUE-02. E-2: toca só este arquivo. E-3: aprovada e `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 2: forma de verificação do CA-23 ajustada, preservando a intenção, e esclarecimento do §4.3. E-5: os dois trechos têm a mesma causa. X-1 a X-4: nada de SPEC nova, ADR, outro documento ou contrato. X-5: nenhum comportamento novo; a stdout do `validate` fica como está (§4.9). X-6: o CA-23 continua exigindo a saída 2, o código `agent_suggestion_label` e nenhum `split_v*`; só muda o fluxo em que o `validate` já escreve. X-7: o CA-23 verifica a proibição da decisão 4 do ADR-024, e não uma regra inegociável, e a guarda não muda. X-9: primeira correção destes trechos, sem marcação de "exige humano" nem dependência do professor. | SPEC_ISSUE-02 de `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (loop da SPEC-041) |
| 2026-11-01 | Correção do SPEC_ISSUE-03 (§4.3 e CA-25), pela opção (b) do relatório. §4.3, antigo: "alguma linha com `labeler` diferente de `agent-suggestion` (§4.9)". Novo: "alguma linha mantida do manifest, ou de `labels_overrides.csv` de imagem não excluída, com `labeler` diferente de `agent-suggestion` (§4.9)", mais o parágrafo depois da tabela (o `<n>` soma os dois arquivos; o `load_manifest` não muda, e o `qc_ml.provisional` lê o arquivo com `parse_csv` e pula `df.attrs["excluded_items"]`). CA-25, antigo: sem caso de `labels_overrides.csv`. Novo: um caso com `labeler=a` (`other labelers: 1`) e um com essa imagem excluída, sem `other labelers`. Por que não a opção (a), a recomendada pelo ml-engineer: "linha mantida do manifest" deixaria passar um conjunto com outro `labeler`, contra "recusa um conjunto com qualquer outro" (ADR-024, decisão 4) e contra o `notice` do §4.4 ("not human labels"). Evidência: `ml/src/qc_ml/data.py:433-481` lê o `labeler` de `labels_overrides.csv` só para validar a coluna, e o grau é trocado sem deixar rastro no `DataFrame`. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-1: SPEC_ISSUE-03. E-2: toca só este arquivo. E-3: aprovada e `Blocked` por este `SPEC_ISSUE`. E-4 tipos 1 e 3: esclarece um pedido que já existia (o §4.3 remete ao §4.9, que trata dos dois arquivos, e o ADR-024 fala do conjunto), e os casos novos do CA-25 cobrem só isso. E-5: só os trechos citados. X-1 a X-4: nada de SPEC nova, ADR, outro documento ou contrato. X-5: nenhuma assinatura, comando ou arquivo de produção novos (`provisional.py` já está no escopo e `parse_csv` já é público), e a recusa já era pedida pelo ADR-024. X-6: a guarda fica mais estrita, e nenhum caso sai. X-7: a linha não verifica regra inegociável. X-9: primeira correção destes trechos, sem marcação de "exige humano" nem dependência do professor. | SPEC_ISSUE-03 de `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (loop da SPEC-041) |
| 2026-11-01 | Correção do SPEC_ISSUE-04 (§4.9, linha do `--dataset-dir` em repositório Git, e CA-28). §4.9, antigo: "`provisional set must be outside any git repository`, antes de ler o dataset e o plano". Novo: "`provisional set must be outside any git repository`, na primeira verificação do `load_plan`: antes das recusas da pasta de entrada e do plano (SPEC-038 §4.7) e de ler o dataset e o plano". CA-28, antigo: "*Dado* `--provisional-set` e `--dataset-dir` dentro de um repositório (…), *quando* o importador roda, *então* sai com 2, a stderr contém `provisional set must be outside any git repository`, e `ml/data` não é criada". Novo: "*Dado* `--provisional-set`, `--privacy-checked` e `--dataset-dir` dentro de um repositório (…), com a pasta de entrada e o plano fora desse repositório e, em outro caso, dentro dele, *quando* o importador roda, *então*, nos dois casos, sai com 2, a stderr contém `provisional set must be outside any git repository` e não contém `inbox must be outside any git repository`, e `ml/data` não é criada". Sem a opção, a ordem da SPEC-038 §4.7 não muda. O `--privacy-checked` entra no CA porque o `main` o confere antes do `load_plan`. Evidência: `edge/src/qc_edge/importer.py:692-704` testa a pasta de entrada e o plano antes de ler o dataset, e `:1090` testa o `--privacy-checked` antes disso. Classificação ADR-019: exige humano (X-7: o trecho e o CA-28 são a guarda que mantém imagens fora de um repositório Git público, e essa guarda pode ser lida como verificação da R-02 e da R-14; o alcance dado à R-02 pela decisão 6 do ADR-024 trata de imagens vistas por agente, não do Git; na dúvida, a classificação é esta). A correção não afrouxa a guarda: nenhum caso sai, e o CA-28 fica mais estrito. E-1 a E-5 cumpridos (E-4 tipos 1 e 2); X-1 a X-6 e X-9 não se aplicam. | SPEC_ISSUE-04 de `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (loop da SPEC-041) |
| 2026-11-01 | Correção do SPEC_ISSUE-05 (§4.9, "Nenhuma chamada existente muda"). Antigo: "`qc_ml.data`, `split`, `train`, `thresholds`, `evaluate`, `pipeline` e `export` usam o padrão e, portanto, recusam, em qualquer `DATASET_DIR`. Eles já convertem `ManifestError` em saída 2." Novo: "`qc_ml.data`, `split`, `train`, `thresholds`, `evaluate` e `pipeline` usam o padrão e, portanto, recusam, em qualquer `DATASET_DIR`. Eles já convertem `ManifestError` em saída 2. O `export` também usa o padrão, mas só lê o dataset sintético da paridade, nunca o `DATASET_DIR`, e por isso não tem essa recusa." Evidência: a única chamada a `load_manifest` no `export` é `ml/src/qc_ml/export.py:144`, sobre o dataset de `make_synthetic_dataset`; a decisão 4 do ADR-024 lista os mesmos seis comandos, sem o `export`. Nenhum CA cita o `export` nessa recusa, e a recusa de versão provisória do §4.5 não muda. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-1: SPEC_ISSUE-05. E-2: toca só este arquivo. E-3: aprovada e `Blocked` por este `SPEC_ISSUE`. E-4 tipo 1: esclarece o texto sem mudar o comportamento, porque nenhuma chamada muda. E-5: só a frase citada. X-1 a X-4: nada de SPEC nova, ADR, outro documento ou contrato. X-5: nada novo. X-6: nenhum CA muda. X-7: a frase descreve a proibição da decisão 4 do ADR-024, e não uma regra inegociável, e a guarda não muda. X-9: primeira correção deste trecho, sem marcação de "exige humano" nem dependência do professor. | SPEC_ISSUE-05 de `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (loop da SPEC-041) |
| 2026-11-01 | Correção dos SPEC_ISSUE-01, 02 e 03 (§4.3, §4.4, CA-09, CA-23, CA-25) e do SPEC_ISSUE-05 (§4.9) aprovada pelo orquestrador sob o ADR-019 (commits do architect 111d2be e 35f2c2d). | `reviews/SPEC-041/r1-dev-report.md` | Orquestrador (ADR-019) |
| 2026-11-01 | Correção do SPEC_ISSUE-04 (§4.9 e CA-28) reaprovada pelo humano (commit do architect 35f2c2d). | Resposta do humano de 2026-11-01, nesta sessão | Orquestrador, a pedido do humano |
