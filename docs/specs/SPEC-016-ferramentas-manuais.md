# SPEC-016: Fase 2 — ferramentas manuais (identificação e grau quando houver dados)

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r1 |
| Autor da implementação | developer (Parte A: contrato, banco, API, borda e dashboard) e depois ml-engineer (Parte B: `qc-ml`), na mesma rodada (§6) |
| Tags | contrato, security |
| Depende de | SPEC-034 (`Done` antes de esta entrar em `In Dev`: primeira mudança de contrato com a borda em operação), SPEC-035, SPEC-036, SPEC-037, SPEC-026, SPEC-028 (e SPEC-008, SPEC-010, SPEC-011, SPEC-012, SPEC-013) |
| Semana alvo | S5–S6. O modelo com ferramentas precisa estar treinado até o congelamento do modelo (M3, 22/11), então a Parte A tem de estar mergeada cedo o bastante para a coleta humana (§3.3) |
| Requisitos cobertos | RF-16; PRD §4.2; R-04, R-06, R-11, R-12, R-14 |
| ADRs relevantes | ADR-021 (`Aceito`: tipos sem grau), ADR-022 (`Aceito`: teste estendido para tipos novos), ADR-020, ADR-014, ADR-013, ADR-001, ADR-004, ADR-005 |

> **Aprovada pelo humano em 2026-10-24** (PR #45), com os ADRs 021 e 022 `Aceito`. **Reaprovada pelo humano em 2026-10-24** (correções do SPEC_ISSUE-1 e do SPEC_ISSUE-2 da r1, §4.7, §4.8, CA-22 e CA-23; ver o Histórico).

## 1. Contexto

O PRD §4.2 pede a **identificação** de 5 ferramentas manuais (alicate, chave inglesa, chave Allen, chave de fenda e chave Phillips), com grau de estado só quando houver dados suficientes. `docs/architecture.md` §3.1 já reserva os valores de `ObjectType`. Duas decisões destravam a SPEC:

- **ADR-021:** o contrato passa a ter três grupos de tipos (grau obrigatório, sem grau e grau opcional). As ferramentas manuais têm grau opcional; o modelo diz no `labels.json` quais tipos ele não gradua. O SPC e a taxa de defeito passam a contar só as inspeções com grau, o que não muda nada nos dados do MVP.
- **ADR-022:** o teste, congelado no `split_v1`, ganha uma extensão única para cada tipo novo, pedida pela dupla quando a coleta do tipo estiver completa.

As imagens públicas de ferramentas seguem o ADR-020: `item_id` `XT-NNNN`, só treino, licença da lista fechada e fonte no registro `ml/external_sources.csv`.

**O que é código e o que é humano.** O código (Partes A e B) é todo testável com dados sintéticos e não depende das fotos. As fotos, os rótulos e o treino real são trabalho da dupla (§3.3), e o treino real com as ferramentas é um CA manual (CA-21), como o CA-28 da SPEC-012.

## 2. Objetivo

O contrato 0.4.0, o banco, a API, a borda e o dashboard aceitam e mostram as 5 ferramentas, com ou sem grau; a coleta e a importação aceitam fotos de ferramentas (`T-`, `XT-`); e o `qc-ml` treina e avalia um modelo que identifica as ferramentas, gradua só as que cumprem o critério de dados e mede cada tipo novo num teste próprio.

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `packages/contracts`: `qc-contracts` **0.4.0** (§4.1); `README.md` com a versão no histórico.
- `infra/migrations/NNN_tool_object_types.sql` (próximo número livre) (§4.2).
- `api/`: SPC e taxa de defeito pelas inspeções com grau, `SpcObjectType` declarado (§4.3).
- `edge/`: `labels.json.ungraded_object_types` no carregamento do modelo, decisão sem grau, resposta da captura, modo coleta e importação com ferramentas (§4.4).
- `dashboard/`: rótulos, cores e "sem grau" (§4.5).
- Testes do autor em `packages/contracts/tests/`, `api/tests/`, `edge/tests/` e `dashboard/tests/` (fora de `acceptance/`).

**Parte B (ml-engineer):**

- `ml/src/qc_ml/data.py`: tipos de ferramenta, prefixos `T-`/`XT-`, critério de grau e `tool_grade_coverage` no relatório de dados (§4.6).
- `ml/src/qc_ml/split.py`: `--extend-test-types` e `--defer-types` (ADR-022) (§4.7).
- Treino, limiares, avaliação e export: tipos do modelo, grau mascarado, `ungraded_object_types` e `tool_grade_metrics` (§4.8).
- `ml/src/qc_ml/synthetic.py`: ferramentas no gerador (§4.9).
- `ml/tests/fixtures/tiny_model_tools/` (fixture nova, gerada pelo script da fixture existente com os 8 tipos) e `ml/README.md` (§4.10).
- Testes do autor em `ml/tests/` (fora de `acceptance/`).

**Tester:** `packages/contracts/tests/acceptance/test_spec_016.py`, `api/tests/acceptance/test_spec_016.py`, `edge/tests/acceptance/test_spec_016.py`, `dashboard/tests/acceptance/test_spec_016.py` e `ml/tests/acceptance/test_spec_016.py`.

**Tester, ajustes de aceite antigos** (aplicação explícita da regra "Testes de aceite de SPECs anteriores" e das "Expectativas de versão" de `docs/architecture.md` §10). Só as asserções afetadas, com a tabela no test-report:

- `packages/contracts/tests/acceptance/test_spec_026.py`: as asserções exatas de `0.3.0` viram a forma de piso da §10; o par do `qc-contracts` no `ALLOWED_EXACT` do CA-28 da SPEC-004 (`api/tests/acceptance/test_spec_004.py`) passa a apontar para `test_spec_016.py` com `0.4.0`, no mesmo commit (precedente: SPEC-026);
- `edge/tests/acceptance/test_spec_008.py`: o caso `pliers` do CA-10 (rótulo inválido no `labels.json`) passa a usar um valor que continua fora do contrato (por exemplo, `"hammer"`);
- `edge/tests/acceptance/test_spec_010.py`: os casos em que `T-001` com `pliers` era recusado só porque `pliers` não existia;
- `ml/tests/acceptance/test_spec_011.py` e `ml/tests/acceptance/test_spec_035.py`: os casos que esperavam recusa de `T-`/`XT-` com um tipo de ferramenta; os casos de `T-`/`XT-` com `screw`, `nut` ou `other` continuam recusados (`item_prefix_mismatch`);
- `ml/tests/acceptance/test_spec_012.py` e `ml/tests/acceptance/test_spec_035.py` (CA-12): o conjunto exato de chaves de topo do `metrics.json` ganha `tool_grade_metrics` (§4.8);
- `api/tests/acceptance/test_spec_006.py`: se algum teste fixar os membros do enum do filtro `object_type` do SPC em `screw` e `nut`.

### 3.2 Fora

- Ferramentas elétricas: SPEC-021 (usa o grupo "sem grau" do ADR-021).
- Corrigir o **tipo** de uma imagem por `labels_overrides.csv` (pergunta 4 do rascunho): fora. Uma imagem com tipo errado sai por `exclusions.csv` (`docs/dataset-protocol.md` §8.1) e é refotografada ou reimportada.
- Detecção com caixas na inferência (PRD §4.4). Recortar caixas de datasets de detecção é trabalho humano, fora de `ml/data/` (`docs/dataset-protocol.md` §10.4).
- Cartas p separadas por tipo como padrão: fora. O filtro `object_type` do SPC já permite a carta de um tipo (ADR-021).
- Métricas de grau das ferramentas no dashboard ("Sobre o modelo" continua lendo o que lê hoje, SPEC-028).

### 3.3 Trabalho humano (fora do loop de agentes)

| Quando | Tarefa |
|---|---|
| Na aprovação (respondida em 2026-10-24, §9) | Conferir quantas unidades de cada ferramenta a dupla tem ou consegue com conhecidos (pergunta do §9). Um tipo com menos de 3 peças físicas não pode ter teste (ADR-022) e fica fora do modelo |
| Depois do merge da Parte A (o merge da SPEC) | Fotografar as ferramentas pelo modo coleta (`T-001`…), com a rubrica do §4.11 para o grau e o protocolo do §4.11 para a captura; importar fotos de conhecidos (`T-501`…) e imagens públicas (`XT-0001`…) pela importação da SPEC-036, depois de registrar a fonte |
| Antes de pedir a extensão | Piloto de concordância do grau das ferramentas (20 fotos, QWK ≥ 0,6), **só** se algum tipo cumprir o critério de grau. O `python -m qc_ml.agreement` de hoje só forma pares de `screw`/`nut` (SPEC-011 §4.3); se algum tipo cumprir o critério, a inclusão das ferramentas nele vem numa SPEC curta, antes do piloto. Antes de treinar, conferir no `split_v<N>.json` que cada tipo estendido tem peças em `test` |
| Coleta completa | Gerar o split com `--extend-test-types` (ADR-022), treinar no Colab e registrar o CA-21 |

**Metas por ferramenta** (só fotos da página e de conhecidos; as externas não contam, ADR-020):

| Para | Meta | Mínimo |
|---|---|---|
| Identificação | 6 peças físicas e 90 imagens por tipo (por exemplo, 6 peças × 5 ângulos × 3 situações de luz e fundo) | 3 peças físicas por tipo (abaixo disso o tipo não entra no modelo) |
| Grau (opcional) | critério do §4.6: ≥ 60 imagens por grau, vindas de ≥ 5 peças físicas, nos 5 graus | — |

Cada chave Allen de um jogo é uma peça física. Ferramentas novas cobrem `perfect`; ferramentas velhas e enferrujadas dão `good` a `poor`; o dano funcional (`unusable`) só vale se a ferramenta já estiver danificada: não danifique ferramenta para fotografar.

**Fontes públicas candidatas** (`XT-`, só treino; a dupla confere a licença e o conteúdo na página oficial antes de registrar a fonte, `docs/dataset-protocol.md` §10.4):

- I3D-Tools (<https://huggingface.co/datasets/i3dlabiisc/I3D-Tools-Dataset>): a página mostra a licença `mit` (consultada pelo architect em 2026-10-24), cerca de 36,8 mil linhas em parquet com anotação YOLO. A página não lista as classes, e as linhas visíveis têm "conditioning image" e legenda, o que sugere imagens **geradas**: confirmar que há fotos reais das ferramentas antes de usar;
- Workshop Tools (<https://universe.roboflow.com/long-oybdw/workshop-tools-swpfs>): CC BY 4.0 segundo o rascunho de 2026-10-12, não verificado (o Roboflow recusa a consulta direta); exige atribuição.

## 4. Requisitos detalhados

### 4.1 Contrato `qc-contracts` 0.4.0 (developer)

- `ObjectType` ganha, **depois** dos membros atuais e nesta ordem: `PLIERS = "pliers"`, `ADJUSTABLE_WRENCH = "adjustable_wrench"`, `ALLEN_KEY = "allen_key"`, `FLAT_SCREWDRIVER = "flat_screwdriver"`, `PHILLIPS_SCREWDRIVER = "phillips_screwdriver"`.
- `OBJECT_TYPE_LABELS_PT`: `alicate`, `chave inglesa`, `chave Allen`, `chave de fenda`, `chave Phillips`.
- Grupos do ADR-021, exportados na raiz como `frozenset[ObjectType]`: `GRADE_REQUIRED_OBJECT_TYPES = {screw, nut}`, `GRADE_FORBIDDEN_OBJECT_TYPES = {unknown}`, `GRADE_OPTIONAL_OBJECT_TYPES` = as 5 ferramentas. Os três são disjuntos e a união é igual a `set(ObjectType)`.
- Invariante de `_InspectionBase` (vale para `InspectionCreate` e `InspectionRead`): tipo de grau obrigatório com `grade` nulo → `ValueError`; tipo sem grau com `grade` não nulo → `ValueError`; tipo de grau opcional aceita os dois. `grade_score` e `grade_confidence` continuam nulos se e somente se `grade` é nulo. As mensagens citam a regra, sem valores.
- `__version__ = "0.4.0"`, a versão do `pyproject.toml` e o histórico do `README.md`.
- Nenhum campo, schema ou regra de `is_defective` muda. É uma mudança **minor** (ADR-021, decisão 2).

### 4.2 Banco (developer)

- Migração `infra/migrations/NNN_tool_object_types.sql`, que pode rodar de novo sem erro (`docs/architecture.md` §5):
  - o `check` de `object_type` passa a aceitar os 8 valores do `ObjectType` 0.4.0;
  - o `check ((object_type = 'unknown') = (grade is null))` é trocado pelo equivalente da invariante do §4.1: `(object_type in ('screw','nut') and grade is not null) or (object_type = 'unknown' and grade is null) or object_type in (<as 5 ferramentas>)`;
  - toda linha válida antes continua válida (a migração não precisa conferir linhas; se o `alter` falhar, a transação inteira volta).
- `is_defective` (coluna gerada) não muda.
- O teste de equivalência contrato × banco (padrão da SPEC-003) cobre todos os pares (tipo, grau ou nulo).

### 4.3 API (developer)

- **SPC** (`lot_selection`, `docs/architecture.md` §3.4): os registros considerados passam a ser `grade is not null` (antes, `object_type <> 'unknown'`), mais o filtro opcional `object_type`.
- **Taxa de defeito** (`MetricsSummary.defect_rate`, `TimeseriesPoint.defect_rate`): denominador = inspeções com `grade is not null`, e `null` quando ele é 0. `unknown_count` continua contando só `object_type = 'unknown'`. Com os dados do MVP, nada muda de valor.
- **`SpcObjectType`** (rota `GET /api/v1/metrics/spc`): classe declarada `class SpcObjectType(StrEnum)` com `screw`, `nut` e as 5 ferramentas, nessa ordem, e não mais derivada do `ObjectType`. `unknown` e qualquer outro valor → 422.
- As rotas de escrita aceitam as ferramentas pelo contrato, sem código novo. A ordem de deploy segue a skill `contrato-api` (contracts → banco → API → dashboard → borda); a API 0.4.0 aceita toda borda 0.3.0.

### 4.4 Borda (developer)

- **Carregamento do modelo** (SPEC-008 §4.2): `labels.json` pode ter `ungraded_object_types` (lista de strings, padrão `[]`). Erro de carregamento (`ModelLoadError`) se: não for lista de strings; tiver repetição; tiver um valor fora de `object_types`; tiver `other`, `screw` ou `nut`; ou faltar nela um tipo de `GRADE_FORBIDDEN_OBJECT_TYPES` presente em `object_types` (nenhum na 0.4.0; vale para a SPEC-021).
- **Decisão** (`docs/architecture.md` §6.2, passo 4): se o tipo decidido está em `ungraded_object_types`, `grade`, `grade_score` e `grade_confidence` são `None`, e `needs_review = type_confidence < type_threshold + 0.10`. Os demais casos não mudam.
- **Resposta da captura:** para uma ferramenta sem grau, `approved = null`, `labels_pt.grade = null` e `labels_pt.verdict = "sem grau"`. O `unknown` continua com `desconhecido`.
- **Modo coleta** (SPEC-010): os 5 tipos de ferramenta entram no seletor e na validação; o prefixo `T` do `item_id` exige um tipo de ferramenta; o grau é obrigatório para as ferramentas (a rubrica do §4.11), como para parafuso e porca; o caminho segue `raw/<object_type>/<grade>/…`. A tabela de cobertura do console ganha as linhas das ferramentas (5 graus cada).
- **Importação** (SPEC-036): o plano aceita os tipos de ferramenta com `T-` (origem `contributor`) e `XT-` (origem `external`), com as mesmas regras de grau da coleta.
- Nenhuma dependência nova. O `httpx` continua só no módulo do publisher (SPEC-009 §4.2).

### 4.5 Dashboard (developer)

- `formatting.object_type_label` cobre os 8 tipos pelo `OBJECT_TYPE_LABELS_PT`.
- `formatting.history_rows`: coluna `Grau` = `sem grau` quando o tipo não é `unknown` e `grade` é nulo; `—` para `unknown`, como hoje.
- `charts.OBJECT_TYPE_ORDER` e as cores incluem as 5 ferramentas, depois de parafuso e porca e antes de desconhecido.
- A página de controle estatístico oferece no filtro de tipo os membros de `SpcObjectType`, com os rótulos PT-BR.

### 4.6 Dados no `qc-ml` (ml-engineer)

- `KNOWN_OBJECT_TYPES` = `screw`, `nut`, `other` e as 5 ferramentas (valores do `ObjectType`). `TOOL_OBJECT_TYPES` = as 5 ferramentas.
- `item_prefix_mismatch`: o prefixo `T` (e `XT`) exige um tipo de `TOOL_OBJECT_TYPES`; `S`, `N` e `O` continuam como hoje.
- Grau: obrigatório e válido para `screw`, `nut` e as ferramentas (o mesmo problema de hoje para `screw` sem grau); vazio para `other`.
- **Critério de grau por tipo de ferramenta:** um tipo é **graduado** se, contando só as imagens **não externas** e **não excluídas** do manifest, cada um dos 5 graus tem ≥ 60 imagens vindas de ≥ 5 `item_id` distintos. Senão, é **sem grau**. Constantes `TOOL_GRADE_MIN_IMAGES = 60` e `TOOL_GRADE_MIN_ITEMS = 5`. O critério conta volume de dados, não resultado de modelo, e não usa o split.
- Relatório de dados: chave nova `tool_grade_coverage`: tipo de ferramenta → `{"graded": bool, "by_grade": {grau: {"n_images", "n_items"}}}`, sempre com os 5 tipos e os 5 graus (contagens 0 quando não há imagens).

### 4.7 Split (ml-engineer; ADR-022)

- `python -m qc_ml.split … [--extend-test-types <t1,…>] [--defer-types <t1,…>]`. Cada valor tem de estar em `KNOWN_OBJECT_TYPES`; senão, saída 2.
- **Tipo novo** = tipo com imagens no dataset e nenhuma linha em nenhuma versão anterior do split. Com split anterior, todo tipo novo tem de estar em exatamente uma das duas listas; senão, saída 2 com `new object type without decision: <tipo>` (um por linha), sem gravar nada. Um tipo listado que não é novo → saída 2. No `split_v1` (sem versão anterior), as listas não são usadas: todos os tipos presentes entram na divisão normal.
- **Extensão:** as peças não externas de cada tipo estendido são divididas 70/15/15 com o procedimento do `split_v1`, com a mesma seed, sem mudar nenhuma atribuição anterior. O estrato segue o ADR-022, decisão 3, lendo "tipo com grau" como tipo graduado: estrato = (tipo, grau dominante) se o tipo é **graduado** pelo critério do §4.6, calculado no `df` que a CLI do split leu; estrato = só o tipo se ele é **sem grau** por esse critério. Um tipo estendido que ficaria sem nenhuma peça no teste (em particular, com menos de 3 peças não externas) → saída 2 com `too few items to extend the test: <tipo>`, sem gravar nada. As imagens externas do tipo vão para o treino (ADR-020).
- **Adiamento:** as imagens dos tipos adiados não entram no `split_v<N>.csv`.
- `split_v<N>.json` ganha `test_extended_types` e `deferred_types` (listas, vazias quando não usadas).
- **Leitura do split:** imagens de um tipo **sem nenhuma linha** no split vigente são ignoradas por `rows_for` e pela checagem de split desatualizado (SPEC-011 §4.4), com um aviso `deferred type images: <tipo>: <n>` no log. Para os tipos presentes no split, a checagem continua igual.

### 4.8 Treino, limiares, avaliação e export (ml-engineer)

- **Tipos do modelo:** `derive_model_labels(df, train_rows) -> ModelLabels`, função pura (`df` = resultado do `load_manifest`, usado no critério do §4.6; `train_rows` = linhas de treino): `object_types` = os tipos de `KNOWN_OBJECT_TYPES` com pelo menos uma imagem em `train_rows`, na ordem `screw`, `nut`, `other` e depois as ferramentas na ordem do `ObjectType`; `ungraded_object_types` = as ferramentas do modelo que são "sem grau" pelo critério do §4.6, na mesma ordem. Para os dados do MVP, o resultado é igual ao `DEFAULT_LABELS` de hoje, com `ungraded_object_types = ()`.
- **Grau mascarado:** `grade_target(object_type, grade, labels) -> int | None`, função pura: `None` para `other` e para os tipos de `ungraded_object_types`; o índice do grau nos demais. A loss de grau ignora os `None` (skill `ml-pipeline` §4).
- `labels.json` (export) e `training_config.json` passam a ter `ungraded_object_types` (lista).
- **Limiares** (SPEC-012 §4.6): `FU(t)` passa a contar as imagens de validação de todos os tipos diferentes de `other` (antes, `screw`/`nut`; igual nos dados do MVP). As imagens de validação das ferramentas (tipo verdadeiro em `TOOL_OBJECT_TYPES`) não entram nos outros dois limiares, que mantêm a regra da SPEC-012 §4.6 nas demais imagens: `unusable_threshold` nas imagens de validação de `screw`/`nut` (as "imagens de val com grau" do MVP); `grade_review_threshold` pela fração de `needs_review` entre as imagens de validação de `screw`, `nut` e `other` (numerador e denominador). Nos dados do MVP, os dois limiares dão o mesmo valor da regra da SPEC-012.
- **Avaliação** (SPEC-012 §4.7): `type_confusion` com todos os tipos do modelo; métricas `grade_*` continuam só em `screw`/`nut` (ADR-022, decisão 6); chave de topo nova `tool_grade_metrics`: ferramenta graduada do modelo → `{"grade_qwk", "grade_mae", "grade_off_by_one_accuracy", "n_images_test", "n_items_test"}` (métrica indefinida = `null`), `{}` sem ferramenta graduada. `warnings` ganha `few test items for <tipo>: <n>` para cada tipo do modelo com menos de 2 peças no teste.
- **CHANGELOG** (`report changelog`): quando o modelo tem ferramentas, uma linha `- Tipos do modelo: <lista>; sem grau: <lista ou "nenhum">.` antes da tabela, e a observação de que `type_accuracy` não é comparável com um modelo sem esses tipos (ADR-022).

### 4.9 Gerador sintético (ml-engineer)

`make_synthetic_dataset(…, tool_items_per_stratum=0, external_tool_items_per_type=0)`:

- `tool_items_per_stratum = k`: para cada ferramenta × grau, `k` peças `T-NNN` numeradas a partir de `T-001`, em sequência entre todos os estratos de ferramenta, cada uma com `images_per_item` imagens;
- `external_tool_items_per_type = e`: para cada ferramenta, `e` peças `XT-NNNN` a partir de `XT-0001` (sequência única), com 1 imagem, graus em rodízio, e linhas `external` com a fonte `synthetic` (como a SPEC-035 §4.7);
- com os dois em 0 (padrão), os arquivos são iguais, byte a byte, aos de hoje (CA-15 da SPEC-035).

### 4.10 Fixture e README (ml-engineer)

- `ml/tests/fixtures/tiny_model_tools/`: mesma estrutura da `tiny_model`, com `labels.json` de 8 tipos (`screw`, `nut`, `other` e as 5 ferramentas) e `ungraded_object_types` com `allen_key`, gerada pelo `ml/scripts/make_tiny_fixture.py` (opção nova `--with-tools`), para os CAs sem torch.
- `ml/README.md`: seção "Ferramentas (Fase 2)": prefixos, critério de grau, extensão e adiamento do teste (ADR-022) e o passo a passo do §3.3.

### 4.11 Rubrica e protocolo de captura das ferramentas (texto vigente; copiado pelo architect para `docs/dataset-protocol.md` §1.1 e §3 em 2026-10-24, depois de esta SPEC virar `Ready`)

| Grau | Critério para ferramentas manuais |
|---|---|
| `perfect` | sem oxidação nem desgaste visível |
| `good` | oxidação em pontos isolados (< 5% da área) ou marcas leves de uso; tudo funciona |
| `fair` | oxidação superficial em 5–25% da área, sem crosta; tudo funciona |
| `poor` | oxidação em > 25% da área, crosta ou pitting; ainda funciona |
| `unusable` | dano funcional: ponta de chave de fenda ou Phillips gasta ou arredondada; mordente do alicate quebrado ou desalinhado; rosca sem-fim da chave inglesa travada ou espanada; chave Allen com ponta arredondada |

Mesma precedência do §1 do protocolo (dano funcional primeiro). Captura: fundo liso maior que a ferramenta (cartolina ou A3), a ferramenta ocupando 40–70% da foto (cerca de 30 a 50 cm), de 3 a 5 ângulos, sem mãos nem pessoas no quadro (R-14).

## 5. Critérios de aceite

Contexto comum: banco de teste do marcador `db` (`TEST_DATABASE_URL`) nos CAs de API e banco; borda com o modelo dummy da SPEC-008; datasets do `make_synthetic_dataset` em `tmp_path`.

### Parte A

- **CA-01 (contrato)** — *Dado* `qc_contracts` instalado, *então* `qc_contracts.__version__ == importlib.metadata.version("qc-contracts") == "0.4.0"`; `[m.value for m in ObjectType]` é `["screw", "nut", "unknown", "pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"]`; `OBJECT_TYPE_LABELS_PT[ObjectType.PLIERS] == "alicate"`, `[ADJUSTABLE_WRENCH] == "chave inglesa"`, `[ALLEN_KEY] == "chave Allen"`, `[FLAT_SCREWDRIVER] == "chave de fenda"`, `[PHILLIPS_SCREWDRIVER] == "chave Phillips"`; e os três grupos do §4.1 são disjuntos e somam os 8 membros.
- **CA-02 (invariante, R-04)** — *Dado* um `InspectionCreate` válido, *quando* validado com, em casos separados, (a) `object_type="pliers"` e `grade`, `grade_score` e `grade_confidence` nulos, (b) `pliers` com `grade="fair"`, `grade_score=2.0` e `grade_confidence=0.7`, (c) `screw` com os três nulos, (d) `unknown` com `grade="good"` (e os outros dois preenchidos), (e) `pliers` com `grade="fair"` e `grade_score` nulo, *então* (a) e (b) são aceitos e (c), (d) e (e) levantam `ValidationError`; e um `InspectionRead` com (a) mais `received_at` e `is_defective=false` é aceito.
- **CA-03 (banco)** — *Dado* as migrações aplicadas no banco de teste, *quando* o teste insere direto no banco, para cada um dos 8 tipos e cada valor de grau (os 5 e `null`), uma linha com os demais campos válidos, *então* o banco aceita exatamente os pares que o `InspectionCreate` 0.4.0 aceita e recusa os demais com SQLSTATE `23514`; e `object_type='hammer'` é recusado com `23514`.
- **CA-04 (API, escrita e leitura)** — *Dado* um dispositivo registrado, *quando* faz `POST /api/v1/inspections` com o caso (a) do CA-02, *então* a resposta é 201; `GET /api/v1/inspections?object_type=pliers` (chave de leitura) devolve o item com `grade` nulo e `is_defective=false`; e `GET /api/v1/inspections?object_type=hammer` responde 422.
- **CA-05 (SPC, ADR-021)** — *Dado* no banco, com `source=live`, os lotes `L-01` a `L-03` com 10 `screw` cada (2, 3 e 1 `poor`) e o lote `L-04` com 10 `pliers` sem grau, mais 4 `pliers` sem grau dentro de `L-01`, *quando* `GET /api/v1/metrics/spc?source=live` é chamado, *então* `points` tem 3 itens (`L-01`, `L-02`, `L-03`), cada um com `n == 10`, `L-04` não está em `points` nem em `excluded_lots`, e `p_bar == 0.2`. *Quando* chamado com `object_type=pliers`, *então* 200 com `points == []`; com `object_type=unknown`, 422; e o `openapi.json` da app mostra o enum `SpcObjectType` igual a `["screw", "nut", "pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver"]`.
- **CA-06 (taxa de defeito)** — *Dado* no banco 10 `screw` (2 `poor`), 5 `pliers` sem grau e 3 `unknown`, todos `live`, *quando* `GET /api/v1/metrics/summary` é chamado, *então* `total == 18`, `defective == 2`, `unknown_count == 3` e `defect_rate == 0.2`.
- **CA-07 (borda, `labels.json`)** — *Dado* um modelo dummy com `object_types = ["screw", "nut", "other", "pliers"]`, *quando* o `labels.json` tem, em casos separados, `ungraded_object_types` ausente, `["pliers"]`, `["screw"]`, `["other"]`, `["allen_key"]` (fora de `object_types`), `["pliers", "pliers"]` e `"pliers"` (texto, não lista), *então* os dois primeiros carregam e os outros cinco levantam `ModelLoadError`.
- **CA-08 (borda, decisão)** — *Dado* `labels` com `object_types = ["screw", "nut", "other", "pliers"]`, `ungraded_object_types = ["pliers"]` e os limiares dos CAs da SPEC-008, *quando* a decisão recebe `type_probs = [0.05, 0.03, 0.02, 0.90]` e qualquer `grade_probs` válido, *então* `object_type == ObjectType.PLIERS`, `grade`, `grade_score` e `grade_confidence` são `None` e `needs_review is False`; com `type_probs = [0.2, 0.1, 0.15, 0.55]`, `needs_review is True`; e, com `ungraded_object_types = []`, o mesmo `[0.05, 0.03, 0.02, 0.90]` dá `grade` igual ao argmax de `grade_probs`.
- **CA-09 (borda, captura e outbox)** — *Dado* a borda com o modelo dummy do CA-08 configurado para devolver `pliers` sem grau, *quando* o celular faz uma captura no modo `inspect`, *então* a resposta tem `approved` nulo e `labels_pt.verdict == "sem grau"`, e o `payload` gravado no outbox valida como `InspectionCreate` com `object_type == "pliers"` e `grade` nulo.
- **CA-10 (modo coleta)** — *Dado* a borda no modo `collect`, *quando* envia, em casos separados, `item_id=T-001` com `pliers` e `good`, `T-001` com `screw` e `good`, `T-002` com `allen_key` e grau vazio, e `S-001` com `pliers` e `good`, *então* o primeiro é gravado em `raw/pliers/good/` com a linha no manifest, e os outros três são recusados com 422 sem gravar arquivo nem linha.
- **CA-11 (importação)** — *Dado* um plano com, em linhas separadas, `T-501` `flat_screwdriver` `good` `contributor` `c01`, `XT-0001` `pliers` `fair` `external` com a fonte registrada, e `XT-0002` `screw` `good` `external`, *quando* `python -m qc_edge.importer … --privacy-checked` roda, *então* as duas primeiras linhas entram no manifest e no `sources.csv`, e a terceira é recusada com o problema de prefixo da SPEC-036, sem gravar nada dela.
- **CA-12 (dashboard)** — *Dado* `formatting.history_rows` com três `InspectionRead`, um `pliers` sem grau, um `unknown` e um `screw` `poor`, *então* a coluna `Tipo` é `alicate`, `desconhecido` e `parafuso`, e a coluna `Grau` é `sem grau`, `—` e `ruim`; e `formatting.object_type_label` devolve o rótulo PT-BR do CA-01 para cada ferramenta.

### Parte B

- **CA-13 (dados)** — *Dado* `make_synthetic_dataset(<root>, tool_items_per_stratum=1)`, *quando* `load_manifest` é chamado, *então* não há erro e há 25 peças `T-` (5 ferramentas × 5 graus). *Dado* o dataset com uma linha editada para `T-001` com `object_type=screw`, ou uma linha de ferramenta com grau vazio, *então* `ManifestError` com `item_prefix_mismatch` no primeiro caso e o problema de grau ausente da SPEC-011 no segundo.
- **CA-14 (critério de grau)** — *Dado* um dataset com `pliers` em 5 peças por grau e 12 imagens por peça (60 por grau), `allen_key` igual mas com uma imagem a menos num grau (59), e 30 imagens `XT-` de `flat_screwdriver`, *quando* o relatório de dados roda, *então* `tool_grade_coverage["pliers"]["graded"] is True`, `tool_grade_coverage["allen_key"]["graded"] is False`, `tool_grade_coverage["flat_screwdriver"]["by_grade"]` só tem zeros, e as 5 ferramentas aparecem com os 5 graus.
- **CA-15 (split, ADR-022)** — *Dado* o `split_v1` de `make_synthetic_dataset(items_per_stratum=20, images_per_item=3)` gerado pela CLI e, depois, as ferramentas acrescentadas com `tool_items_per_stratum=4` (20 peças por ferramenta), *quando* a CLI de split roda: (a) sem as opções novas, *então* sai com 2, a saída de erro tem uma linha `new object type without decision: <tipo>` para cada uma das 5 ferramentas e nada é gravado; (b) com `--defer-types` com as 5, *então* sai com 0, o `split_v2.csv` não tem nenhuma imagem `T-` e o `split_v2.json` tem as 5 em `deferred_types`; (c) a partir de (b), com `--extend-test-types` com as 5, *então* sai com 0, cada ferramenta tem peças em `train`, `val` e `test`, todas as linhas do `split_v1` mantêm o split, e o `split_v3.json` tem as 5 em `test_extended_types`; (d) a partir de (c), com uma peça nova de `pliers` acrescentada, *então* a peça nova não está em `test`; e (e) com um dataset em que `allen_key` tem só 2 peças, `--extend-test-types allen_key` sai com 2 e a saída de erro contém `too few items to extend the test: allen_key`.
- **CA-23 (estrato da extensão, ADR-022)** — *Dado* o `split_v1` de `make_synthetic_dataset(<root>)` (parâmetros padrão) gerado pela CLI e, depois, as ferramentas acrescentadas com `tool_items_per_stratum=1` (5 peças por ferramenta, uma por grau; nenhuma ferramenta é graduada pelo §4.6), *quando* a CLI de split roda com `--extend-test-types` com as 5, *então* sai com 0 e cada ferramenta tem exatamente 3 peças em `train`, 1 em `val` e 1 em `test`. *Dado* o `split_v1` de `make_synthetic_dataset(<root>, images_per_item=12)` e, depois, as ferramentas acrescentadas com `tool_items_per_stratum=5` (60 imagens de 5 peças em cada grau: as 5 ferramentas são graduadas), *quando* a mesma CLI roda, *então* sai com 0 e cada ferramenta tem, em cada um dos 5 graus, exatamente 3 peças em `train`, 1 em `val` e 1 em `test`.
- **CA-16 (tipos do modelo e grau mascarado)** — *Dado* `make_synthetic_dataset(<root>, tool_items_per_stratum=5, images_per_item=12)` (60 imagens por grau, de 5 peças, em cada ferramenta) com uma imagem de `allen_key` apagada do disco e registrada em `exclusions.csv`, lido com `load_manifest` (`df`), *quando* `derive_model_labels(df, df)` é chamado, *então* `object_types == ("screw", "nut", "other", "pliers", "adjustable_wrench", "allen_key", "flat_screwdriver", "phillips_screwdriver")` e `ungraded_object_types == ("allen_key",)`; com o `df` de `make_synthetic_dataset` padrão (sem ferramentas), o resultado tem os `object_types` e os `grades` de `DEFAULT_LABELS` e `ungraded_object_types == ()`. E `grade_target("allen_key", "good", labels) is None`, `grade_target("other", None, labels) is None` e `grade_target("pliers", "fair", labels) == 2`.
- **CA-17 (limiares)** — *Dado* `Predictions` de validação com 10 `pliers` e 10 `screw`, em que 2 `pliers` têm `max(type_probs) = 0.55` e as demais imagens têm 0,95, *quando* `choose_thresholds` roda, *então* o `type_threshold` escolhido é o maior `t` da grade com `FU(t) <= 0.05`, contando as 20 imagens (logo, `type_threshold <= 0.55`).
- **CA-22 (limiar de revisão de grau)** — *Dado* `labels` com `object_types = ("screw", "nut", "other", "pliers")` e `ungraded_object_types = ()`, e `Predictions` de validação com 10 `screw` (`type_probs = [0.97, 0.01, 0.01, 0.01]`, nenhum com grau verdadeiro `unusable`; 2 com `grade_probs = [0.50, 0.20, 0.10, 0.10, 0.10]` e 8 com `[0.95, 0.02, 0.01, 0.01, 0.01]`), 10 `other` (`type_probs = [0.01, 0.01, 0.97, 0.01]`, qualquer `grade_probs` válido) e 20 `pliers` (`type_probs = [0.01, 0.01, 0.01, 0.97]`, todos com `grade_probs = [0.50, 0.20, 0.10, 0.10, 0.10]`), *quando* `choose_thresholds` roda, *então* `type_threshold == 0.85`, `grade_review_threshold == 0.60` e as notas do relatório não têm `review_adjusted`. (A fração de `needs_review` é 2/20 = 10%, contando `screw` e `other`; contando só `screw`/`nut`, seria 2/10 e, contando também as ferramentas, 22/40, as duas fora de [5%, 15%].)
- **CA-18 (avaliação)** — *Dado* a fixture `ml/tests/fixtures/tiny_model_tools/`, um dataset com ferramentas e o split estendido, e uma config apontando para eles, *quando* `thresholds` e `evaluate` rodam (sem torch), *então* as chaves de topo do `metrics.json` são as da SPEC-012 §4.7 mais `tool_grade_metrics`; `type_confusion` é 8×8; `labels.ungraded_object_types == ["allen_key"]`; `tool_grade_metrics` não tem a chave `allen_key` e, para cada ferramenta graduada do modelo, tem as 5 chaves do §4.8; e o `labels.json` gerado pelo export da fixture tem `ungraded_object_types`.
- **CA-19 (gerador)** — *Dado* `make_synthetic_dataset` com os parâmetros padrão em dois diretórios, um deles com `tool_items_per_stratum=0, external_tool_items_per_type=0` explícitos, *então* os arquivos são iguais byte a byte e não há nenhum `item_id` `T-` nem `XT-`.
- **CA-20 (R-11)** — *Dado* o split (c) do CA-15 com `external_tool_items_per_type=2`, *então* a interseção de `item_id` entre `train`, `val` e `test` é vazia e nenhuma imagem `XT-` está em `val` ou `test`.

### Manual

- **CA-21 (manual, dupla: treino real com ferramentas)** — 1. Coleta das ferramentas concluída com as metas do §3.3; 2. `python -m qc_ml.data report` registrado (com `tool_grade_coverage`); 3. split com `--extend-test-types` para os tipos com 3 peças ou mais, e `--defer-types` para os outros, por PR; 4. treino no Colab com o fluxo da SPEC-031/035; 5. `metrics.json` com `type_confusion` dos tipos do modelo, sem omitir nenhum, e entrada no CHANGELOG com a linha "Tipos do modelo"; 6. o modelo carregado na borda e 5 ferramentas fotografadas pela página, com o resultado registrado no test-report.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (developer) | invariante e grupos; migração e equivalência; SPC e taxa de defeito; `labels.json` e decisão; coleta, importação e resposta; formatação | `packages/contracts/tests/`, `api/tests/`, `edge/tests/`, `dashboard/tests/` |
| Unitário (ml-engineer) | prefixos e grau; critério; split com extensão e adiamento; `derive_model_labels`; `grade_target`; limiares; `tool_grade_metrics`; gerador | `ml/tests/` |
| Aceite (tester) | Um por CA automatizado, nos 5 arquivos do §3.1 | `*/tests/acceptance/test_spec_016.py` |
| Manual (dupla) | CA-21 | descrito no CA |

- **Ordem da rodada:** developer (Parte A) → ml-engineer (Parte B) → tester → reviewer → security-devops. Cada autor faz commits só nos caminhos do próprio papel e acrescenta a sua seção no `reviews/SPEC-016/r<N>-dev-report.md` (o ml-engineer acrescenta `## Parte B (ml-engineer)` no fim, sem mudar a parte do developer).
- Nada é mockado além das fronteiras: banco de teste real nos CAs de API e banco; modelo dummy na borda; fixture ONNX sem torch no ML.
- **Rodada r2 (correção dos SPEC_ISSUE-1 e 2 da r1):** só a Parte B muda (ml-engineer: escopo do `grade_review_threshold` no `qc_ml.thresholds` e estrato e checagem da extensão no `qc_ml.split`, com os testes do autor afetados). O tester escreve o CA-22 e o CA-23 e reroda os CAs da Parte B (CA-13 a CA-20); os CAs da Parte A não precisam de teste novo.

## 7. Riscos e notas para o implementador

- **Deploy:** contracts → banco → API → dashboard → borda (skill `contrato-api`). Uma borda 0.4.0 contra uma API 0.3.0 teria cada ferramenta recusada com 422 e marcada `dead`; depois de atualizar a API, `python -m qc_edge.requeue` (SPEC-034) as devolve.
- **SPC e taxa de defeito:** troque a condição nos dois lugares e só neles. Os testes das SPECs 005, 006 e 026 têm de continuar passando sem ajuste, porque nos dados deles `object_type <> 'unknown'` e `grade is not null` selecionam as mesmas linhas.
- **Teto de 30% de externas** (SPEC-035): é global no treino. Muitas imagens `XT-` podem estourar o teto; a dupla escolhe quantas importar.
- **Tipos fora do modelo:** um tipo do contrato pode não estar no `labels.json` (poucos dados). A borda só decide entre os tipos do modelo.
- **Comparabilidade:** `grade_*` continua medido nas mesmas peças de parafuso e porca (ADR-022); a `type_accuracy` muda de escopo.
- **Estrato da extensão (§4.7):** com a meta de 6 peças por ferramenta espalhadas pelos graus, estratificar uma ferramenta sem grau por (tipo, grau dominante) deixaria quase todo estrato com menos de 3 peças e, em geral, o tipo sem nenhuma peça no teste; por isso o estrato depende do critério do §4.6 no momento da extensão. Se o tipo mudar de grupo depois (mais fotos), o teste dele continua o congelado na extensão (ADR-022, decisão 5).

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `packages/contracts/README.md`, `ml/README.md`, `edge/README.md` (coleta e importação de ferramentas) atualizados; `docs/architecture.md` e `docs/dataset-protocol.md` pelo architect
- [x] ADR-021 e ADR-022 `Aceito` (aprovados pelo humano em 2026-10-24, PR #45)
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-21 manual registrado depois da coleta (não bloqueia o merge, como o CA-28 da SPEC-012)

## 9. Perguntas para a aprovação (humano) — respondidas em 2026-10-24

Mantidas como registro. As respostas estão na linha da aprovação no Histórico (2026-10-24, PR #45).

1. **ADR-021 e ADR-022:** aceitar os dois como estão? **Recomendação:** sim. O ADR-021 não muda nenhum valor do MVP e evita mudar o contrato a cada modelo; o ADR-022 mede as ferramentas sem perder a comparabilidade de parafusos e porcas. **Resposta (2026-10-24):** aceitos como estão (`Aceito`).
2. **Unidades disponíveis:** quantas unidades de cada ferramenta a dupla tem ou consegue com conhecidos? **Recomendação:** seguir só com os tipos que chegarem a 3 peças físicas (meta de 6); os outros ficam no contrato, mas fora do modelo, sem nova SPEC. **Resposta (2026-10-24):** a dupla ainda não sabe quantas unidades tem; vale a recomendação (no mínimo 3 peças físicas por tipo, meta de 6; abaixo disso, o tipo fica no contrato e fora do modelo, sem SPEC nova).

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | §4 ganha o requisito "Carta p (SPC)" e §6 ganha a pergunta 7: os tipos novos e o filtro `object_type` do SPC precisam de decisão explícita. A SPEC continua `Draft`. | RV-01 de `reviews/SPEC-006/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-20 | §4: imagens públicas passam de "treino e validação" para **só treino**, com `item_id` `XT-NNNN`, importação pela SPEC-036 e registro de fontes da SPEC-035; o critério de grau conta só as imagens não externas. §6, pergunta 3: resolvida pelo ADR-020. ADRs relevantes: o ADR-020 entra junto com os demais. A SPEC continua `Draft`. | Decisão do humano de 2026-10-19 (ADR-020) | Orquestrador, a pedido do humano |
| 2026-10-24 | SPEC reescrita para a aprovação. Perguntas do rascunho resolvidas: (1) invariante → ADR-021 (`Proposto`; grau opcional para as ferramentas, `ungraded_object_types` no `labels.json`, SPC e taxa de defeito por `grade is not null`, contrato 0.4.0 minor); (2) teste congelado → ADR-022 (`Proposto`; extensão única por tipo com `--extend-test-types` e adiamento com `--defer-types`); (3) já resolvida; (4) correção de tipo fora (exclusão e nova foto); (5) mapeamento de classes públicas é trabalho humano com a rubrica; (6) piloto de concordância só se algum tipo for graduado; (7) SPC pelo filtro `object_type`, sem carta separada por padrão. Novos: Parte A (developer) e Parte B (ml-engineer) na mesma rodada; tag `security` (entrada da API, banco, coleta e importação); dependência da SPEC-034 (prazo dela), 035, 036, 037, 026 e 028; trabalho humano e metas por ferramenta (§3.3); rubrica e captura das ferramentas (§4.11); lista de ajustes de aceite antigos; CAs testáveis CA-01 a CA-20 e o CA-21 manual. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com o pacote das Fases 2 e 3, os ADRs 021 e 022 e a ordem `034 → 016 → 018 → 017 → portão da Fase 3 → 020 → 019 → 021`. Ferramentas: a dupla ainda não sabe quantas unidades tem; segue a regra de no mínimo 3 peças físicas por tipo (meta de 6), e os tipos abaixo disso ficam no contrato e fora do modelo, sem SPEC nova. | Respostas do humano de 2026-10-24 (PR #45) | Orquestrador, a pedido do humano |
| 2026-10-24 | Limpeza de consistência pós-aprovação, sem mudança de requisito, CA, valor ou escopo: aviso do topo registra a aprovação; ADR-021 e ADR-022 como `Aceito` nos "ADRs relevantes" e na Definição de pronto (item marcado); §3.3 e §9 marcadas como respondidas, com as respostas da linha anterior; §4.11 copiado para `docs/dataset-protocol.md` §1.1 e §3, como a própria §4.11 manda. As linhas anteriores do Histórico ficam como estavam (registro). | Status `Ready` e ADRs `Aceito` desde o PR #45; sobravam textos da fase de rascunho | Architect, a pedido do orquestrador |
| 2026-10-24 | Entra em `In Dev` antes de a SPEC-036 estar `Done` (só falta o CA-17 manual dela), por decisão do humano; a branch nasce da `spec/SPEC-036-importacao-de-fotos` e o merge desta SPEC só acontece depois do merge da 036. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
| 2026-10-24 | **SPEC_ISSUE-1 (§4.8, Limiares; CA-22 novo).** Texto antigo: "`unusable_threshold` e `grade_review_threshold` continuam calculados só em `screw`/`nut`." Texto novo: as imagens de validação das ferramentas não entram nesses dois limiares, que mantêm a regra da SPEC-012 §4.6 nas demais imagens: `unusable_threshold` em `screw`/`nut`; `grade_review_threshold` pela fração de `needs_review` entre as imagens de validação de `screw`, `nut` e `other`. CA-22 (novo) cobre só esse escopo. Intenção: o "continuam" pedia a regra vigente sem mudança no MVP, e o "só em `screw`/`nut`" descrevia mal o `grade_review_threshold`. Evidência: SPEC-012 §4.6 ("calcula a fração de val com `needs_review`", todas as imagens de val, `other` inclusive); `ml/src/qc_ml/thresholds.py` antes da SPEC-016 (`_choose_review` com `n = len(val)`); skill `ml-pipeline` §6 ("cerca de 10% das inspeções da validação"); com a leitura literal, o `grade_review_threshold` de um modelo do MVP mudaria de valor sem ADR. A grade de `r`, a faixa de 5% a 15%, a meta de 10% e o padrão 0,60 (`docs/architecture.md` §6.2) não mudam, e nos dados do MVP o valor escolhido é o mesmo da SPEC-012 (nenhum valor prometido muda, X-6). **Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão).** Como vai no mesmo commit da correção do SPEC_ISSUE-2, que exige humano, a reaprovação da SPEC fica com o humano. | SPEC_ISSUE-1 de `reviews/SPEC-016/r1-dev-report.md` (Parte B, ml-engineer) | Orquestrador (loop da SPEC-016) |
| 2026-10-24 | **SPEC_ISSUE-2 (§4.7, Extensão; CA-23 novo; nota no §3.3, no §6 e no §7),** registrado pelo architect a partir da observação "Contagem de imagens por estrato da extensão" de `reviews/SPEC-016/r1-dev-report.md` (Parte B). Contradição: com a meta de 6 peças por ferramenta espalhadas pelos 5 graus (mínimo 3), o estrato (tipo, grau dominante) do texto antigo deixa quase todo estrato com menos de 3 peças, que o `split_v1` manda inteiros para o treino (SPEC-011 §4.4); o tipo estendido fica sem teste, contra o objetivo do ADR-022 ("cada tipo novo tem um teste próprio"; "um tipo com menos de 3 peças físicas não teria teste", isto é, com 3 ou mais teria), contra a checagem "menos de 3 peças" do CA-15 (e) e contra o CA-21. Texto antigo: "estrato = (tipo, grau dominante) se o tipo tem grau no manifest; a divisão não depende do critério do §4.6 … Menos de 3 peças não externas num tipo estendido → saída 2 com `too few items to extend the test: <tipo>`." Texto novo: estrato = (tipo, grau dominante) se o tipo é graduado pelo critério do §4.6 (calculado no `df` lido pela CLI do split), só o tipo se é sem grau; um tipo estendido que ficaria sem nenhuma peça no teste (em particular, com menos de 3 peças) → saída 2 com a mesma mensagem, sem gravar nada. É uma das duas leituras do ADR-022, decisão 3 ("por (tipo, grau dominante) quando o tipo tem grau e só por tipo quando não tem"), sem mudar o ADR. CA-23 (novo) cobre os dois ramos; CA-15 (c) continua válido (4 peças por grau, 12 imagens: sem grau, estrato só por tipo, 14/3/3). §3.3 ganha o lembrete de conferir o teste dos tipos estendidos no `split_v<N>.json` e a nota de que o piloto de concordância das ferramentas exige uma SPEC curta para o `qc_ml.agreement` (só se algum tipo for graduado); §6 ganha a nota da rodada r2; §7 ganha o risco. **Classificação ADR-019: exige humano (X-7: muda a regra de divisão do split, que verifica a R-11; X-5 e E-4: muda o comportamento pedido da extensão, que antes não dependia do critério do §4.6, e acrescenta um caso de recusa).** | Observação da Parte B em `reviews/SPEC-016/r1-dev-report.md`; ADR-022 | Orquestrador (loop da SPEC-016) |
| 2026-10-24 | Correções dos SPEC_ISSUE-1 (§4.8, CA-22) e SPEC_ISSUE-2 (§4.7, opção B: estrato por tipo e grau quando graduado, só por tipo quando sem grau; CA-23) reaprovadas pelo humano (commit do architect 83d64a1). A rodada r1 continua: o ml-engineer ajusta a Parte B. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
