# SPEC-046: Falso desconhecido do teste no mesmo escopo do limiar de tipo (`false_unknown_rate_all_types`)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | ml-engineer (código do §3.1 e operação do §4.6, depois do merge). O texto da skill `ml-pipeline` (§4.5) fica com o orquestrador, se o humano aprovar a pergunta 4 do §9 |
| Tags | — (sem autenticação, rede, banco, segredo ou contrato; o `metrics.json` é artefato do pipeline revisado por PR. A operação do §4.6 lê `ml/data/` só pelas CLIs, como na SPEC-045, e não publica nada) |
| Depende de | SPEC-045 mergeada (código: PR #76; modelo `partqc-mnv3-v1`: PR #78). SPEC-012 e SPEC-016 `Done` (já estão). Para a operação do §4.6: `model.onnx` da v1 local, com o `model.sha256` versionado, e o `ml/data/` da reimportação da SPEC-045 sem mudança |
| Semana alvo | S5 (antes do congelamento do modelo, M3, 22/11) |
| Requisitos cobertos | RF-12 (`metrics.json`); PRD §7 (relato honesto das métricas); R-11 |
| ADRs relevantes | ADR-014 (integridade de ML), ADR-022 (comparabilidade entre versões), ADR-025 (decisão 7: limitações declaradas), ADR-021 |

## 1. Contexto

O limiar de tipo e a métrica de falso desconhecido do teste medem coisas diferentes desde a SPEC-016:

- **Validação (escolha do limiar).** O `type_threshold` é o maior `t` em [0,50; 0,85] com `FU(t) ≤ 0,05`, e `FU(t)` conta as imagens de validação de **todos os tipos menos `other`** (SPEC-016 §4.8; `ml/src/qc_ml/thresholds.py`, `_choose_type`, máscara `true_type_idx != other`).
- **Teste (relato).** O `false_unknown_rate` do `metrics.json` conta **só `screw`/`nut`** (SPEC-012 §4.7; `ml/src/qc_ml/evaluate.py`, `compute_metrics`, máscara `is_screw_nut`). Isso foi decisão registrada em `reviews/SPEC-016/r1-dev-report.md` (item 13), aceita no review (`reviews/SPEC-016/r1-review-report.md`, Parte B, 13) e repetida na SPEC-021 (`reviews/SPEC-021/r1-dev-report.md`, item 8).

Nos dados do MVP (só `screw`, `nut` e `other`), os dois escopos coincidem. No `partqc-mnv3-v1` (12 tipos, 10 sem grau), não:

- validação: `FU(0,50) = 0,5000` em 24 imagens, nota `type_target_not_met` (`ml/reports/partqc-mnv3-v1/thresholds_report.json`);
- teste: `false_unknown_rate = 0,0000` em 10 imagens de parafuso. A `type_confusion` do mesmo `metrics.json` mostra 3 imagens de `hammer` previstas como `other` (logo, `unknown`), que essa métrica não conta. Pela `type_confusion`, pelo menos 3 das 27 imagens de teste que não são `other` viram `unknown` (3/27 ≈ 0,1111, sem contar as que ficam abaixo do limiar).

O ml-engineer registrou a divergência na entrada do `partqc-mnv3-v1` em `ml/models/CHANGELOG.md` (Limitações, "Escopo do `false_unknown_rate`"). Além disso, a skill `.claude/skills/ml-pipeline/SKILL.md` §6 ainda diz que o `type_threshold` é escolhido em `screw`/`nut`, texto vencido pela SPEC-016, e a linha da §5 diz que o `false_unknown_rate` vale para "todos".

`docs/architecture.md` §7 (artefatos, `metrics.json`, "Exibição das métricas"); skill `ml-pipeline` §5 e §6.

**Por que SPEC e não ADR.** Nenhuma regra negociável (N-xx), nenhum contrato (`packages/contracts` não muda), nenhuma tecnologia e nenhuma regra de escolha de limiar mudam. A métrica existente continua igual. Acrescentar uma chave ao `metrics.json` já foi feito por SPEC, sem ADR: `tool_grade_metrics` (SPEC-016 §4.8) e `counts.<split>.by_origin`/`by_source` (SPEC-035). A R-11 fica mais bem servida: o teste passa a relatar a mesma medida que a validação usou para escolher.

## 2. Objetivo

O `metrics.json` passa a ter `false_unknown_rate_all_types`, medido no teste com os limiares do `decision.json` e no mesmo escopo do `FU(t)` da validação, sem mudar nenhuma métrica existente. A entrada do CHANGELOG mostra a métrica nova. A skill `ml-pipeline` descreve o escopo vigente. O `partqc-mnv3-v1` é reavaliado só pelo `evaluate`, sem re-treinar e sem reescolher limiar.

## 3. Escopo

### 3.1 Dentro

**Código (ml-engineer):**

- `ml/src/qc_ml/evaluate.py`: chave nova `false_unknown_rate_all_types` em `METRIC_KEYS`, logo depois de `false_unknown_rate`; cálculo em `compute_metrics`; aviso quando indefinida; docstring do módulo (§4.1).
- `ml/src/qc_ml/report.py`: linha nova na tabela do CHANGELOG, descrição da linha de `false_unknown_rate`, `LOWER_IS_BETTER` e a checagem do valor da chave nova (§4.2); docstring do módulo.
- `ml/README.md`, item "`metrics.json`" da seção de avaliação: uma frase com o escopo de `false_unknown_rate` (`screw`/`nut`) e de `false_unknown_rate_all_types` (todos os tipos menos `other`, o mesmo do `FU(t)`).
- Testes do autor em `ml/tests/` (fora de `acceptance/`), incluindo `ml/tests/test_evaluate.py` (`len(METRIC_KEYS) == 34`).

**Skill (orquestrador, se o humano aprovar a pergunta 4 do §9):** `.claude/skills/ml-pipeline/SKILL.md`, só a linha da tabela da §5 e os três itens da §6, com o texto exato do §4.5. Commit separado, com `Agent: orchestrator`.

**Operação depois do merge (ml-engineer executa; tester confere; §4.6):** reavaliação do `partqc-mnv3-v1` e atualização da entrada dele no CHANGELOG, por PR.

**Tester:** `ml/tests/acceptance/test_spec_046.py` (CA-01 a CA-09 e CA-11) e `dashboard/tests/acceptance/test_spec_046.py` (CA-10); conferência da operação (CA-12 e CA-13).

**Tester, ajustes de aceite antigos** (aplicação explícita de `docs/architecture.md` §10, "Testes de aceite de SPECs anteriores"; só as asserções do conjunto exato de chaves de topo do `metrics.json`, que ganham `false_unknown_rate_all_types`; a intenção, "as chaves são exatamente as da especificação vigente", não muda):

- `ml/tests/acceptance/test_spec_012.py`: as três asserções de conjunto exato `METRIC_KEYS | {"tool_grade_metrics"}` (uma delas só no modo *slow*);
- `ml/tests/acceptance/test_spec_016.py`: a asserção do CA-18 (`METRIC_KEYS_012 | {"tool_grade_metrics"}`);
- `ml/tests/acceptance/test_spec_021.py`: a asserção com `METRIC_KEYS_016`;
- `ml/tests/acceptance/test_spec_035.py`: a asserção do CA-12 (`METRIC_KEYS | {"tool_grade_metrics"}`).

Não mudam: `ml/tests/acceptance/test_spec_041.py` (a interseção do `provisional_report.json` com `METRIC_KEYS` continua `{"model_version", "model_sha256", "manifest_sha256"}`, porque o relatório provisório não ganha a chave), o CA-24 da SPEC-012 (só as 4 chaves de latência mudam com `--latency-only`) e os aceites do dashboard.

### 3.2 Fora

- Mudar o `false_unknown_rate` (escopo, nome, valor ou posição): não é feito. Ele continua em `screw`/`nut`, para a comparação entre versões (ADR-022).
- Mudar a regra do `type_threshold` ou de qualquer limiar (`thresholds.py`, `decision.py`), o treino, o export ou a predição: não é feito.
- Mostrar a métrica nova na página "Sobre o modelo" do dashboard: fora, salvo resposta diferente à pergunta 2 do §9 (nesse caso, numa SPEC curta do developer, sobre a SPEC-028).
- `provisional_report.json` (SPEC-041): não ganha a chave.
- Re-treinar o `partqc-mnv3-v1`, rodar de novo o `qc_ml.thresholds` nele ou mudar o `decision.json`: proibido (R-11).
- Publicar de novo o Release `model-partqc-mnv3-v1`: não é preciso. O `model.onnx`, o `model.sha256` e as notas do Release (`release-notes.md`, que não trazem métricas) não mudam.
- `docs/architecture.md` §7 e o Histórico das SPECs 012 e 016: pelo architect, depois da aprovação (§8).

## 4. Requisitos detalhados

### 4.1 Métrica nova no `evaluate`

- **Definição.** `false_unknown_rate_all_types` = (nº de imagens de teste cujo tipo verdadeiro não é `other` e que a decisão marca como `unknown`) / (nº de imagens de teste cujo tipo verdadeiro não é `other`). `unknown` é o `Decisions.unknown` de `qc_ml.decision.apply_decision` com os limiares do `decision.json` (argmax `other` ou `max(type_probs) < type_threshold`), o mesmo usado em `false_unknown_rate` e `unknown_rate_on_other`. É a mesma máscara do `FU(t)` do `_choose_type` (`true_type_idx != other`), aplicada ao teste com `t = type_threshold`.
- **Escopo.** Todos os tipos do `labels.object_types` menos `other`: `screw`, `nut`, as ferramentas manuais (graduadas ou não), as elétricas e as só identificadas (SPEC-044). Com dados só de `screw`, `nut` e `other`, o valor é igual ao de `false_unknown_rate`.
- **Valor.** `float` bruto em [0, 1], nunca arredondado; `null` quando o denominador é 0 (nunca omitido, R-11).
- **Posição.** Em `METRIC_KEYS`, logo depois de `false_unknown_rate`. O `metrics.json` passa a ter 34 chaves de topo: as 32 da SPEC-012 §4.7, `tool_grade_metrics` (SPEC-016 §4.8) e esta, na ordem de `METRIC_KEYS`.
- **Aviso.** Quando o valor é `null`, `warnings` ganha `false_unknown_rate_all_types is undefined on the test split (null)`, depois do aviso equivalente de `false_unknown_rate`, se houver (o mesmo laço de `type_accuracy`, `unknown_rate_on_other` e `false_unknown_rate`).
- **Integridade (R-11).** O `evaluate` continua pedindo `rows_for(..., "test")` exatamente uma vez, depois do `decision.json`. A métrica é calculada sobre as mesmas `Predictions` das outras; nenhuma leitura nova do teste.
- `--latency-only` não muda: reescreve só as 4 chaves de latência. Num `metrics.json` sem a chave nova (gravado antes desta SPEC), ele não a acrescenta.
- `thresholds.py`, `decision.py`, `predict.py`, `train.py`, `export.py` e `provisional.py` não mudam.

### 4.2 CHANGELOG (`qc_ml.report changelog`)

- `TABLE_ROWS`, na posição de `false_unknown_rate`, passa a ter estas duas linhas, nesta ordem:
  - `("false_unknown_rate", "taxa de falso desconhecido em parafusos e porcas")`;
  - `("false_unknown_rate_all_types", "taxa de falso desconhecido em todos os tipos, exceto outros objetos")`.
- Sem meta do PRD §7: as colunas de meta e status mostram `—`.
- `LOWER_IS_BETTER` ganha `false_unknown_rate_all_types` (exibição arredondada para cima, `docs/architecture.md` §7).
- **`metrics.json` sem a chave** (versões anteriores): a linha aparece com `—` na coluna "Valor" (versão atual sem a chave) ou na coluna "Anterior" (`--previous` sem a chave), como já acontece com `format_metric(None)`. Nenhum erro.
- **Valor inválido** (entrada externa): no `metrics.json` da versão e no do `--previous`, a chave, se presente, tem de ser `null` ou um número finito em [0, 1] que não seja `bool`. Senão, `changelog` sai com 2 antes de montar qualquer linha, sem escrever no `--append`, com a linha `report failed: invalid metric in metrics.json: false_unknown_rate_all_types` (ou `… in previous metrics.json: …` para o `--previous`) na stderr. O valor nunca é ecoado (mesmo princípio da SPEC-037 §4.1 e da SPEC-040 §4.6).
- `release-notes` não muda.

### 4.3 Compatibilidade com o `metrics.json` antigo

| Leitor | Com a chave | Sem a chave (antes desta SPEC) |
|---|---|---|
| `qc_ml.report changelog` | linha com o valor | linha com `—`, saída 0 |
| `qc_ml.report release-notes` | não lê | não lê |
| `qc_ml.evaluate --latency-only` | preserva | não acrescenta |
| Dashboard (`qc_dashboard.model_info.load_metrics`) | aceita (confere só as chaves exigidas, `REQUIRED_KEYS`) | aceita |

O único `metrics.json` oficial versionado hoje é o do `partqc-mnv3-v1`, que ganha a chave pela operação do §4.6. As fixtures de `ml/tests/fixtures/` não têm `metrics.json`.

### 4.4 Testes do autor

Unitários de `compute_metrics` (o caso do CA-01, um caso sem ferramentas e o caso indefinido), da linha do CHANGELOG, da checagem de valor inválido e o ajuste de `len(METRIC_KEYS)` em `ml/tests/test_evaluate.py`. Os testes do autor que comparam com `list(METRIC_KEYS)` passam sem ajuste.

### 4.5 Texto da skill `ml-pipeline` (texto exato)

Em `.claude/skills/ml-pipeline/SKILL.md`, nada além disto muda:

- §5, a linha ``| `unknown_rate_on_other` e `false_unknown_rate` (com os limiares do `decision.json`) | todos |`` é trocada por três linhas:

  ```markdown
  | `unknown_rate_on_other` (com os limiares do `decision.json`) | `other` |
  | `false_unknown_rate` (idem) | `screw`/`nut` |
  | `false_unknown_rate_all_types` (idem; mesmo escopo do `FU(t)` da §6) | todos os tipos menos `other` |
  ```

- §6, os três itens passam a ser:

  ```markdown
  - `type_threshold`: o **maior** valor, em [0,50; 0,85], com `FU(t) ≤ 5%` na validação, em que `FU(t)` é a fração das imagens de validação de todos os tipos menos `other` que viram `unknown` (SPEC-016 §4.8; antes dela, só `screw`/`nut`). O teto de 0,85 evita que `needs_review` (confiança < limiar + 0,10) marque quase tudo. No teste, a mesma medida é o `false_unknown_rate_all_types` (SPEC-046).
  - `unusable_threshold`: o maior valor que garante `unusable_recall ≥ 0,90` nas imagens de validação de `screw`/`nut` com grau. Se for impossível, use o que maximiza o recall e registre isso.
  - `grade_review_threshold`: padrão 0,60, ou um ajuste para que cerca de 10% das imagens de validação de `screw`, `nut` e `other` fiquem `needs_review` (SPEC-016 §4.8).
  ```

### 4.6 Operação depois do merge: reavaliação do `partqc-mnv3-v1`

Ordem: CA-12 → CA-13. Cada passo para no primeiro erro. Nenhum agente abre, converte ou descreve foto de `ml/data/` (ADR-025, decisão 3): só as CLIs leem as imagens.

1. **Pré-condições (ml-engineer):** a `main` com o código desta SPEC; `ml/models/partqc-mnv3-v1/model.onnx` local, com `sha256sum` igual ao `model.sha256` versionado; `ml/data/` igual ao da avaliação de 2026-11-05 (nenhuma importação ou exclusão depois do PR #78). Guarde uma cópia do `metrics.json` versionado fora do repositório, para a comparação do CA-12.
2. **Reavaliação (ml-engineer):** numa branch nova a partir da `main`, `uv run --package qc-ml python -m qc_ml.evaluate --config ml/configs/partqc-mnv3-v1.json --latency-machine "notebook-borda"`, no mesmo notebook da avaliação de 2026-11-05. **Não** rodar `qc_ml.thresholds`, `qc_ml.train`, `qc_ml.export` nem `qc_ml.pipeline`. A latência é medida de novo e entra como medida.
3. **CHANGELOG (ml-engineer):** `uv run --package qc-ml python -m qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v1` (sem `--append`). Na entrada existente do `partqc-mnv3-v1`, troque só a parte gerada (título, itens de cabeçalho, "Tipos do modelo", tabela, "Peças no teste por grau" e `### Dados`) pela saída nova. Nas seções escritas à mão:
   - "Peças de teste de cada métrica `atingida`": atualizar os números de latência;
   - "Limitações", item "Escopo do `false_unknown_rate`": reescrito com os dois valores do teste (4 casas, pela regra de exibição) e os denominadores (imagens de `screw`/`nut` e imagens que não são `other`, de `counts.test.by_class`), ao lado do `FU` de validação (0,5000 em 24 imagens);
   - "O que mudou": um item novo com a data da reavaliação (UTC), a SPEC-046, a frase "modelo, `decision.json`, split e manifest iguais" e as latências anteriores (p50 19,1863 ms, p95 21,3143 ms).
   As demais seções não mudam.
4. **Conferência (tester):** as do CA-12 e do CA-13, registradas em `reviews/SPEC-046/r<N>-operacao-test-report.md`.
5. **PR (orquestrador):** só com os arquivos do CA-12, item 6.

**Por que a reavaliação não fere a R-11.** Os limiares, o modelo e o split são os mesmos; a nova leitura do teste só mede (o `decision.json` nem é regravado). O valor medido não pode motivar mudança no `decision.json` da v1. A regra de escolha das próximas versões continua a da SPEC-016 §4.8; mudá-la exige SPEC nova, com a decisão justificada pela validação, nunca pelo teste.

## 5. Critérios de aceite

Contexto comum: sem torch; `labels` = `ModelLabels` com `object_types = ("screw", "nut", "other", "pliers")`, os 5 graus e `ungraded_object_types = ("pliers",)`; `thresholds` = `Thresholds(type_threshold=0.70, unusable_threshold=0.50, grade_review_threshold=0.60)`; imagens `screw`/`nut` com grau verdadeiro `good` e `grade_probs = [0.05, 0.90, 0.02, 0.02, 0.01]`; imagens `pliers`/`other` com grau verdadeiro ausente (`-1`) e o mesmo `grade_probs`. **Conjunto A** (12 imagens, uma peça por imagem):

| Tipo verdadeiro | Qtd. | `type_probs` | Decisão |
|---|---|---|---|
| `screw` | 2 | `[0.95, 0.02, 0.02, 0.01]` | `screw` |
| `screw` | 1 | `[0.10, 0.05, 0.80, 0.05]` | `unknown` (argmax `other`) |
| `screw` | 1 | `[0.60, 0.20, 0.10, 0.10]` | `unknown` (0,60 < 0,70) |
| `nut` | 2 | `[0.02, 0.95, 0.02, 0.01]` | `nut` |
| `pliers` | 1 | `[0.03, 0.03, 0.90, 0.04]` | `unknown` (argmax `other`) |
| `pliers` | 3 | `[0.01, 0.02, 0.02, 0.95]` | `pliers` |
| `other` | 2 | `[0.02, 0.02, 0.95, 0.01]` | `unknown` |

### Código

- **CA-01 (definição)** — *Dado* o conjunto A como `Predictions` com `split="test"`, *quando* `compute_metrics(predictions, item_ids, labels, thresholds)` é chamado, *então* `false_unknown_rate_all_types == 0.3` (3/10, ±1e-12), `false_unknown_rate == 1/3` (2/6, ±1e-12, escopo `screw`/`nut` inalterado) e `unknown_rate_on_other == 1.0`.
- **CA-02 (mesmo escopo do `FU(t)`)** — *Dado* o conjunto A com `split="val"`, *quando* `choose_thresholds(val, labels)` roda, *então* o ponto de `report["type_threshold"]["curve"]` com `threshold == 0.7` tem `n_unknown == 3` e `false_unknown_rate == 0.3` (±1e-12), igual ao `false_unknown_rate_all_types` do CA-01, e `report["type_threshold"]["n_images"] == 10`.
- **CA-03 (chaves e dados do MVP)** — *Dado* a fixture `ml/tests/fixtures/tiny_model/`, um `make_synthetic_dataset` padrão com split e uma config apontando para eles (como no CA-22 da SPEC-012), *quando* `python -m qc_ml.thresholds` e `python -m qc_ml.evaluate` rodam, *então* os dois saem com 0, o `metrics.json` tem exatamente 34 chaves de topo, na ordem de `qc_ml.evaluate.METRIC_KEYS`, `false_unknown_rate_all_types` vem logo depois de `false_unknown_rate`, e os dois valores são iguais e não nulos (o modelo só tem `screw`, `nut` e `other`).
- **CA-04 (ferramentas)** — *Dado* a fixture `tiny_model_tools`, um dataset com ferramentas e o split estendido (como no CA-18 da SPEC-016), *quando* `thresholds` e `evaluate` rodam, *então* saem com 0; `false_unknown_rate_all_types` está em [0, 1]; e o valor é igual ao recalculado no teste a partir de `Predictions` do mesmo modelo no split de teste e de `apply_decision` com o `decision.json` gravado, com o denominador igual ao nº de imagens de teste cujo tipo não é `other`.
- **CA-05 (indefinida)** — *Dado* `Predictions` de teste só com 3 imagens `other` (`type_probs = [0.02, 0.02, 0.95, 0.01]`), *quando* `compute_metrics` é chamado, *então* `false_unknown_rate` e `false_unknown_rate_all_types` são `None`, e `warnings` contém `false_unknown_rate is undefined on the test split (null)` seguido, em alguma posição posterior, de `false_unknown_rate_all_types is undefined on the test split (null)`.
- **CA-06 (CHANGELOG)** — *Dado* um `metrics.json` válido com `false_unknown_rate = 0.0` e `false_unknown_rate_all_types = 1/9` (`0.1111111111111111`), *quando* `python -m qc_ml.report changelog --model-dir <dir>` roda, *então* sai com 0, a tabela tem a linha ``| `false_unknown_rate` (taxa de falso desconhecido em parafusos e porcas) | 0,0000 | — | — |`` e, logo abaixo, ``| `false_unknown_rate_all_types` (taxa de falso desconhecido em todos os tipos, exceto outros objetos) | 0,1112 | — | — |`` (arredondado para cima, `docs/architecture.md` §7).
- **CA-07 (versão anterior sem a chave)** — *Dado* o `metrics.json` do CA-06 e um `--previous` igual, mas sem a chave `false_unknown_rate_all_types`, *quando* `changelog` roda, *então* sai com 0 e a linha da chave nova termina com `| 0,1112 | — | — | — |` (coluna "Anterior" com `—`); *dado* o `metrics.json` da versão sem a chave, *então* sai com 0 e a linha da chave nova é ``| `false_unknown_rate_all_types` (taxa de falso desconhecido em todos os tipos, exceto outros objetos) | — | — | — |``.
- **CA-08 (erro: valor inválido)** — *Dado* o `metrics.json` do CA-06 com `false_unknown_rate_all_types` igual, em casos separados, a `"0,1\n| x |"`, `1.5`, `-0.1`, `true` e `[0.1]`, e um arquivo `CHANGELOG.md` existente, *quando* `changelog --append <CHANGELOG.md>` roda, *então* sai com 2, a stderr tem a linha `report failed: invalid metric in metrics.json: false_unknown_rate_all_types`, não contém o texto `| x |`, e o `CHANGELOG.md` fica igual byte a byte; *dado* o mesmo valor `1.5` só no `--previous`, *então* sai com 2 com a linha `report failed: invalid metric in previous metrics.json: false_unknown_rate_all_types`; *dado* `null`, sai com 0.
- **CA-09 (R-11 e `--latency-only`)** — *Dado* o espião em `qc_ml.split.rows_for` do CA-20 da SPEC-012 e o ambiente do CA-03, *quando* `thresholds` e depois `evaluate` rodam, *então* `"test"` é pedido exatamente uma vez, pelo `evaluate`, com o `decision.json` já existente. *Dado* o `metrics.json` do CA-03, *quando* `evaluate --latency-only --latency-machine "notebook-borda"` roda, *então* só `latency_ms_p50`, `latency_ms_p95`, `latency_machine` e `latency_runs` mudam; *dado* o mesmo arquivo sem a chave `false_unknown_rate_all_types` (mesmo `model_sha256`), *então* sai com 0 e o arquivo continua sem a chave.
- **CA-10 (dashboard inalterado)** — *Dado* um `metrics.json` com todas as `REQUIRED_KEYS` do `qc_dashboard.model_info` mais `false_unknown_rate_all_types = 0.25`, *quando* `load_metrics` o lê, *então* não levanta erro; e `other_metric_rows` do documento lido dá as mesmas linhas que dá para o mesmo documento sem a chave nova.
- **CA-11 (skill e README)** — *Dado* o repositório, *quando* `.claude/skills/ml-pipeline/SKILL.md` é lido, *então* a linha da §6 que começa com ``- `type_threshold`:`` contém `todos os tipos menos` e `false_unknown_rate_all_types`; o arquivo não contém o texto ``` `false_unknown_rate ≤ 5%` em `screw`/`nut` ``` (o trecho vencido da §6); a tabela da §5 tem uma linha que começa com ``| `false_unknown_rate_all_types` ``; e `ml/README.md` contém `false_unknown_rate_all_types`.

### Operação (depois do merge)

- **CA-12 (operação: reavaliação; ml-engineer executa, tester confere)** — Passos 1 e 2 do §4.6. Conferências, cada uma com a saída registrada no test-report da operação:
  1. o `evaluate` saiu com 0, e o log da sessão não tem `qc_ml.thresholds`, `qc_ml.train`, `qc_ml.export` nem `qc_ml.pipeline`;
  2. `git diff main -- ml/models/partqc-mnv3-v1/decision.json ml/models/partqc-mnv3-v1/model.sha256 ml/models/partqc-mnv3-v1/labels.json ml/models/partqc-mnv3-v1/training_config.json ml/models/partqc-mnv3-v1/preprocessing.json ml/models/partqc-mnv3-v1/parity_fixture.npz ml/models/partqc-mnv3-v1/release-notes.md ml/reports/partqc-mnv3-v1/thresholds_report.json` é vazio;
  3. o `metrics.json` novo tem as 34 chaves na ordem de `METRIC_KEYS`; toda chave, exceto `evaluated_at`, `latency_ms_p50`, `latency_ms_p95` e `false_unknown_rate_all_types`, tem o mesmo valor da cópia do passo 1 (inteiros, textos e listas de inteiros iguais; `float` com diferença absoluta ≤ 1e-12, inclusive dentro de listas e objetos); `latency_machine == "notebook-borda"` e `latency_runs == 100`. Qualquer outra diferença → `SPEC_ISSUE`, nada é commitado;
  4. `false_unknown_rate_all_types` é um número em [0, 1] e é ≥ (soma da coluna `other` da `type_confusion` fora da linha `other`) / (soma das linhas fora de `other`), calculado no mesmo arquivo (3/27 com os dados do PR #78);
  5. nenhum agente abriu foto (ADR-025, decisão 3): os comandos da sessão são só as CLIs do §4.6, `git`, `sha256sum` e leitura de JSON e CSV;
  6. o PR da operação traz só `ml/models/partqc-mnv3-v1/metrics.json`, `ml/models/CHANGELOG.md` e, se os bytes mudarem, `ml/reports/partqc-mnv3-v1/type_confusion.png` e `grade_confusion.png`; nenhum `.onnx`, `.pt` ou arquivo de `ml/data/`.
- **CA-13 (operação: CHANGELOG; tester confere)** — Passo 3 do §4.6: (1) a tabela da entrada `partqc-mnv3-v1` (do cabeçalho `| Métrica |` até a primeira linha vazia) é igual, linha a linha, à impressa por `python -m qc_ml.report changelog --model-dir ml/models/partqc-mnv3-v1`; (2) o item "Escopo do `false_unknown_rate`" das Limitações tem os valores de `false_unknown_rate` e `false_unknown_rate_all_types` exibidos como na tabela e os dois denominadores, iguais a `counts.test.by_class` do `metrics.json`; (3) "O que mudou" tem o item da reavaliação com a data, `SPEC-046`, a frase do §4.6 e as latências anteriores; (4) os números de latência do item "Peças de teste de cada métrica `atingida`" são os do `metrics.json` novo, exibidos pela regra; (5) fora disso e da parte gerada, o texto da entrada é igual ao da `main`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (ml-engineer) | `compute_metrics` (conjunto A, sem ferramentas, indefinida), linha do CHANGELOG, valor inválido, `len(METRIC_KEYS) == 34` | `ml/tests/` |
| Aceite (tester) | CA-01 a CA-09 e CA-11 | `ml/tests/acceptance/test_spec_046.py` |
| Aceite (tester) | CA-10 | `dashboard/tests/acceptance/test_spec_046.py` |
| Aceite antigo (tester) | Conjunto exato de chaves, lista do §3.1 | os 4 arquivos do §3.1 |
| Operação (ml-engineer; conferência do tester) | CA-12 e CA-13 | `reviews/SPEC-046/r<N>-operacao-test-report.md` |

- **Ordem da rodada:** ml-engineer (código e testes do autor) → orquestrador (texto da skill, §4.5, commit separado) → tester → reviewer. Sem tags `security`/`deploy`: sem portão de segurança.
- Nada é mockado além do que os testes do `qc-ml` já mockam; `Predictions` construídas à mão nos CAs 01, 02 e 05; fixtures ONNX existentes e `make_synthetic_dataset` em `tmp_path` nos CAs 03, 04 e 09. Nenhum teste lê `ml/data/`. O CA-10 monta o JSON à mão e não importa `qc_ml` (R-12).
- O reviewer confere no diff que `thresholds.py`, `decision.py`, `predict.py`, `train.py`, `export.py` e `provisional.py` não mudaram e que nenhuma dependência nova entrou.

## 7. Riscos e notas para o implementador

- **Não mexa no `false_unknown_rate`.** A divergência de escopo é intencional desde a SPEC-016 (comparabilidade de parafusos e porcas). A métrica nova se soma a ela.
- **A métrica nova não é comparável entre modelos com tipos diferentes**, como a `type_accuracy` (ADR-022): o escopo muda com os tipos do modelo. A nota de comparabilidade já impressa pelo `changelog` para modelos com ferramentas (SPEC-016 §4.8) vale também para ela; não é preciso texto novo.
- **Latência da reavaliação:** mudará um pouco em relação a 2026-11-05. É o valor medido (R-11). As anteriores ficam registradas em "O que mudou".
- **`docs/architecture.md` §7** diz que uma métrica nova de "menor é melhor" entra também no `model_info` do dashboard. Com a resposta recomendada à pergunta 2 do §9, o dashboard não mostra a métrica, e o architect ajusta a frase para valer para as métricas que o dashboard exibe (§8).
- **Se a comparação do CA-12, item 3, divergir** (por exemplo, `manifest_sha256` ou `counts` diferentes), o `ml/data/` mudou depois do PR #78: pare e registre `SPEC_ISSUE`; não recomponha o dataset sem o architect.

## 8. Definição de pronto

- [ ] CA-01 a CA-11 com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED
- [ ] CI verde; `ruff` limpo
- [ ] `ml/README.md` atualizado (§3.1); skill `ml-pipeline` com o texto do §4.5 (orquestrador)
- [ ] `docs/architecture.md` §7 (tabela de artefatos, lista de "menor é melhor" e a frase sobre o dashboard) e uma linha "só texto, depois do `Done`" no Histórico das SPECs 012 e 016, pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09
- [ ] Depois do merge: CA-12 e CA-13 (test-report da operação) e o PR da operação mergeado

## 9. Perguntas para a aprovação (humano)

1. **Nome da chave:** `false_unknown_rate_all_types` (o da proposta) ou `false_unknown_rate_non_other`? **Recomendação:** `false_unknown_rate_all_types`. O `other` é a classe que deve virar `unknown`, então não existe "falso desconhecido" nela, e o escopo exato fica na SPEC, na skill e na descrição do CHANGELOG ("todos os tipos, exceto outros objetos").
2. **Dashboard:** mostrar a métrica nova em "Sobre o modelo"? **Recomendação:** não nesta SPEC. A proposta pede o CHANGELOG ou o relatório, e incluir o dashboard traz o developer, testes de interface e um deploy. Se a dupla quiser mostrá-la na apresentação, uma SPEC curta sobre a SPEC-028 resolve (a página já tolera a chave a mais, CA-10).
3. **Reavaliar o `partqc-mnv3-v1`?** **Recomendação:** sim, só o `evaluate` (§4.6). É o modelo oficial da apresentação, e o CHANGELOG passa a mostrar o número do teste em vez de só a ressalva. Sem re-treinar e sem rodar o `thresholds`, nenhuma escolha é feita com o teste (R-11). O custo é a latência medida de novo. A alternativa é deixar a v1 como está, com a ressalva atual, e a métrica aparecer só na próxima versão.
4. **Quem edita a skill** (`.claude/`, fora do caminho do ml-engineer e do architect)? **Recomendação:** o orquestrador, com o texto exato do §4.5, num commit separado com `Agent: orchestrator`, como na atualização de `.claude/agents/security-devops.md` prevista na SPEC-015. Alternativa: o humano faz a edição.
5. **Descrição da linha antiga no CHANGELOG:** passar de "taxa de falso desconhecido" para "taxa de falso desconhecido em parafusos e porcas"? **Recomendação:** sim. Muda só o texto da tabela, nunca o valor nem a chave, e deixa os dois escopos lado a lado. O dashboard continua com o rótulo atual (pergunta 2).

Sem ADR: ver §1, "Por que SPEC e não ADR".

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-11-05 | SPEC criada como `Draft`: chave `false_unknown_rate_all_types` no `metrics.json` (escopo do `FU(t)` da SPEC-016 §4.8), linha no CHANGELOG com checagem de valor inválido, texto da skill `ml-pipeline` §5 e §6, ajustes de 4 aceites antigos (conjunto exato de chaves) e reavaliação do `partqc-mnv3-v1` só pelo `evaluate`; CAs 01 a 11 automatizados, CAs 12 e 13 de operação; 5 perguntas ao humano; sem ADR | Achado do ml-engineer ao fechar o CA-16 da SPEC-045 (`ml/models/CHANGELOG.md`, entrada `partqc-mnv3-v1`, Limitações) | Orquestrador, a pedido do humano |
