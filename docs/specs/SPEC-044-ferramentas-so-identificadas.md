# SPEC-044: Martelo, chave de aperto e nível, ferramentas só identificadas (contrato 0.7.0)

| Campo | Valor |
|---|---|
| Status | In Test |
| Rodada atual | r1 |
| Autor da implementação | developer (Parte A: contrato, banco, API, borda e dashboard) e depois ml-engineer (Parte B: constantes do `qc-ml`), na mesma rodada, como nas SPECs 016 e 021 |
| Tags | contrato, security, deploy |
| Depende de | ADR-025 `Aceito`; SPEC-021, SPEC-034 e SPEC-043 `Done` (já estão) |
| Semana alvo | S5 (logo depois da aprovação; antes da SPEC-045) |
| Requisitos cobertos | PRD §4.2 (identificação de ferramentas, ampliada pelo ADR-025); RF-08, RF-09, RF-16; R-04, R-06, R-11, R-12, R-14 |
| ADRs relevantes | ADR-025 (`Aceito`; decisão 1), ADR-021 (grupo "sem grau"), ADR-022 (extensão do teste), ADR-020, ADR-012 |

## 1. Contexto

O humano decidiu, em 2026-11-04, treinar o modelo oficial com as fotos dos colegas e acrescentar as ferramentas que aparecem nelas (ADR-025). Três tipos novos entram no contrato, todos **só identificados**, no grupo "sem grau" do ADR-021, como as ferramentas elétricas da SPEC-021: `hammer` (martelo), `wrench` (chave de aperto: boca, estrela, combinada, L de soquete e grifo) e `spirit_level` (nível).

`docs/architecture.md` §3.1 (enums e grupos de grau), §5 (`check` do banco), §6.3 (prefixos e coleta) e §7 (`labels.json`). A SPEC-021 já entregou todos os mecanismos: grupo sem grau, `ungraded_object_types`, grau vazio obrigatório no dataset, diretório `raw/<tipo>/_/` e extensão do teste. Esta SPEC acrescenta os três tipos a cada lista.

**Por que a Parte B está aqui, e não na SPEC-045:** o `qc_ml.data` deriva as ferramentas elétricas do grupo sem grau do contrato (`GRADE_FORBIDDEN_OBJECT_TYPES` menos `unknown`). Com o contrato 0.7.0 e sem a Parte B, os três tipos virariam "elétricos" no ML, o gerador sintético mudaria e os aceites da SPEC-021 no `ml/` quebrariam no CI desta mesma branch.

## 2. Objetivo

O contrato 0.7.0 e todos os componentes aceitam martelo, chave de aperto e nível sempre sem grau e fora do SPC; a coleta, a importação e o `qc-ml` os tratam como ferramentas sem grau com prefixo `T`; e o banco de produção recebe a migração `007` antes da API.

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `packages/contracts`: `qc-contracts` **0.7.0**. Três valores novos em `ObjectType`, depois de `cordless_screwdriver` e nesta ordem: `HAMMER = "hammer"`, `WRENCH = "wrench"`, `SPIRIT_LEVEL = "spirit_level"` (15 valores). Rótulos em `OBJECT_TYPE_LABELS_PT`: `martelo`, `chave de aperto`, `nível`. Os três em `GRADE_FORBIDDEN_OBJECT_TYPES`. Histórico no `packages/contracts/README.md`.
- `infra/migrations/007_identified_tool_object_types.sql`: os dois `check` da `006` substituídos, com os mesmos nomes (§4.2).
- `api/`: nada além do contrato e da migração. O `SpcObjectType` **não** muda.
- `edge/`:
  - `qc_edge.collect`: os três membros em `DatasetObjectType`; tupla nova `IDENTIFIED_TOOL_OBJECT_TYPES` (os três, nesta ordem) em `UNGRADED_DATASET_TYPES` e no prefixo `T` de `ITEM_PREFIX_TYPES`; mensagem própria de grau preenchido (§4.3); linhas da tabela de cobertura (§4.3);
  - `qc_edge.app`: rótulos dos três na página `/capture` (opções do tipo no modo coleta) e no console (tabela de cobertura e texto das metas);
  - `edge/src/qc_edge/static/capture.js`: os três na lista do prefixo `T` (`PREFIX_TYPES`);
  - a importação (`qc_edge.importer`) aceita os três pelas listas do `qc_edge.collect`, sem regra própria;
  - o carregamento do modelo e a decisão não mudam: um tipo sem grau do contrato presente no modelo tem de estar em `ungraded_object_types` (SPEC-016 §4.4), e isso já vale para os três pela derivação do contrato.
- `dashboard/`: `charts.OBJECT_TYPE_ORDER` e `charts.OBJECT_TYPE_COLORS` com os três; os filtros de tipo do histórico e do resumo já derivam do `ObjectType`; `filters.SPC_OBJECT_TYPES` **não** muda.
- `edge/README.md`, `api/README.md` (só a versão do contrato, se citada) e `dashboard/README.md`, onde listarem os tipos.

**Parte B (ml-engineer):**

- `qc_ml.data`:
  - `POWER_TOOL_OBJECT_TYPES` passa a ser a tupla explícita das 4 ferramentas elétricas (`angle_grinder`, `saw`, `drill`, `cordless_screwdriver`), e não mais derivada do grupo sem grau;
  - `IDENTIFIED_TOOL_OBJECT_TYPES = ("hammer", "wrench", "spirit_level")`, nova;
  - `KNOWN_OBJECT_TYPES`: `screw`, `nut`, `other`, as manuais, as elétricas e as três novas, na ordem do `ObjectType`;
  - prefixo `T` (`ITEM_PREFIX_TYPES`) e `GRADE_FORBIDDEN_DATASET_TYPES` com as três (grau preenchido = problema `grade_on_other`);
  - `derive_model_labels`: as três entram **sempre** em `ungraded_object_types`, como as elétricas; `grade_target` devolve `None` para elas;
  - `tool_grade_coverage` continua só com as 5 manuais.
- `qc_ml.split`: o estrato da extensão (`extension_strata` em `make_split`) usa o tipo inteiro também para as três novas. A mudança do estrato do `split_v1` é da SPEC-045.
- `qc_ml.synthetic.make_synthetic_dataset(…, identified_tool_items_per_type: int = 0, external_identified_tool_items_per_type: int = 0)`, com a saída padrão igual byte a byte à de hoje. Peças `T-` numeradas depois das elétricas, grau vazio, `raw/<tipo>/_/`.
- `qc_ml.plots`: nenhuma mudança esperada (os rótulos já derivam do contrato); conferir no teste.
- `ml/README.md`: os três tipos na seção das ferramentas.

**Tester:** `test_spec_044.py` em `packages/contracts`, `api`, `edge`, `dashboard` e `ml` (`tests/acceptance/`).

**Tester, ajustes de aceite antigos** (aplicação explícita de `docs/architecture.md` §10):

- `packages/contracts/tests/acceptance/test_spec_021.py`: as asserções exatas de `0.6.0` passam para a forma de piso; a lista completa de 12 valores do `ObjectType` passa a conferir os 12 primeiros, nessa ordem; a igualdade exata de `GRADE_FORBIDDEN_OBJECT_TYPES` passa a "contém `unknown` e as 4 elétricas".
- `api/tests/acceptance/test_spec_004.py` (CA-28): o `ALLOWED_EXACT` passa a apontar para `packages/contracts/tests/acceptance/test_spec_044.py` com `0.7.0`, **no mesmo commit** em que esse arquivo é criado.
- Nos `test_spec_016.py` e `test_spec_021.py` dos componentes: uma asserção que fixe a contagem de 12 tipos, a lista completa de tipos de uma tabela, um seletor ou um gráfico, ou a mensagem `grade must be empty for a power tool` para todos os tipos sem grau, passa a conferir só o que aquela SPEC introduziu.

### 3.2 Fora

- Piso do `split_v1` sem porcas, estrato do `split_v1`, `--defer-types` no `split_v1`, correções do dataset, concordância, split e treino: **SPEC-045**.
- Grau de martelo, chave de aperto e nível (rubrica e grupo "grau opcional"): fora do escopo do ADR-025. Se um dia for pedido, é uma SPEC nova com a tag `contrato` (mudança minor, porque só amplia o aceito).
- Tesoura de poda e outros objetos: continuam em `other` (ADR-025, decisão 1).
- Simulador (`scripts/simulate.py`): continua só com parafusos, porcas e `unknown`.
- Remover `nut` ou `adjustable_wrench` do contrato: não é feito (seria major). Eles só ficam sem imagens.

## 4. Requisitos detalhados

### 4.1 Contrato (ADR-021, ADR-025)

- `InspectionCreate` com `object_type` em {`hammer`, `wrench`, `spirit_level`}: aceito com `grade`, `grade_score` e `grade_confidence` nulos; com qualquer um deles não nulo, `ValidationError`. A invariante de `docs/architecture.md` §3.1 não muda, só o conteúdo do grupo.
- Os três grupos continuam disjuntos e somam os 15 membros.
- Mudança **minor** (valores novos no enum, no grupo sem grau). `is_defective` não muda.

### 4.2 Migração `007_identified_tool_object_types.sql`

Mesma forma da `006` (um bloco `DO`, idempotente, sem `BEGIN`/`COMMIT`, sem credenciais):

- `inspections_object_type_check` com os 15 valores do `ObjectType` 0.7.0;
- `inspections_grade_null_iff_unknown`: `(object_type not in ('screw','nut') or grade is not null) and (object_type not in ('unknown','angle_grinder','saw','drill','cordless_screwdriver','hammer','wrench','spirit_level') or grade is null)`.

Toda linha válida antes continua válida: nenhuma linha tem os três tipos ainda.

### 4.3 Borda

- **Coleta:** `T-NNN` com um dos três tipos e grau vazio grava em `raw/<tipo>/_/` (`NO_GRADE_DIR`) e acrescenta a linha ao manifest. Com grau preenchido: 422 com `{"detail": "grade must be empty for an identification-only tool"}`, sem gravar nada. As ferramentas elétricas continuam com `grade must be empty for a power tool`, e o `other` com `grade must be empty for other`.
- **Importação:** o plano aceita os três com `T-`/`XT-` e grau vazio. Um dos três com grau dá o problema `grade_on_other (grade)` e o plano inteiro é recusado (saída 2, nada gravado), como as elétricas.
- **Página `/capture`:** o seletor de tipo do modo coleta tem as opções `hammer`, `wrench` e `spirit_level`, com os rótulos `martelo`, `chave de aperto` e `nível`, depois das elétricas.
- **Console:** a tabela de cobertura ganha uma linha por tipo novo, com o grau `sem grau` e as metas das ferramentas sem grau (90 imagens e 6 peças; mínimo de 3 peças, só no texto). O texto das metas cita "Ferramentas só identificadas (sem grau): martelo, chave de aperto e nível".
- **Decisão e resposta:** um tipo novo decidido sai com `grade`, `grade_score` e `grade_confidence` nulos, `approved = null` e `labels_pt.verdict = "sem grau"` (SPEC-016 §4.4); `labels_pt.object_type` traz o rótulo PT-BR.

### 4.4 Ordem de deploy (skill `contrato-api`)

contracts → banco (`007` pelo `infra/migrate.py`, conexão direta ou pooler em modo session) → API (`partqc-api`) → dashboard (`partqc-web`) → borda. A borda só passa a usar um modelo com os tipos novos depois de a API de produção responder `contract_version = "0.7.0"`. Sem a `007` em produção, uma inspeção com um tipo novo recebe 422 (`Value cannot be stored`) e vira `dead` no outbox; a SPEC-034 a devolve a `pending` depois da migração.

## 5. Critérios de aceite

Contexto comum: o da SPEC-021 (banco de teste `db`, modelo dummy gerado nos testes, `make_synthetic_dataset`).

### Parte A

- **CA-01 (contrato)** — *Dado* `qc_contracts`, *então* `__version__ == importlib.metadata.version("qc-contracts") == "0.7.0"`; `ObjectType` tem 15 membros, e os 3 últimos são `hammer`, `wrench` e `spirit_level`, nessa ordem; os rótulos são `martelo`, `chave de aperto` e `nível`; `GRADE_FORBIDDEN_OBJECT_TYPES == {unknown, angle_grinder, saw, drill, cordless_screwdriver, hammer, wrench, spirit_level}`; e os três grupos são disjuntos e somam `set(ObjectType)`.
- **CA-02 (invariante)** — *Dado* um `InspectionCreate` válido, *quando* `object_type` é cada um dos três tipos novos, com os três campos de grau nulos, *então* é aceito; com `grade="good"`, `grade_score=1.0` e `grade_confidence=0.8`, `ValidationError`.
- **CA-03 (banco)** — *Dado* as migrações aplicadas até a `007`, *quando* o teste insere direto, para cada um dos 15 tipos e cada grau (os 5 e `null`), uma linha com os demais campos válidos, *então* o banco aceita exatamente os pares que o `InspectionCreate` 0.7.0 aceita e recusa os demais com SQLSTATE `23514`; e aplicar a `007` uma segunda vez termina sem erro e sem mudar `pg_get_constraintdef` dos dois `check`.
- **CA-04 (API)** — *Dado* um dispositivo registrado, *quando* faz `POST /api/v1/inspections` com `hammer` sem grau, *então* 201; com `hammer` e `grade="good"`, 422 sem gravar. *Dado* no banco os lotes `L-01` a `L-03` com 10 `screw` cada (1 `poor` em cada) e o lote `L-04` com 10 `wrench`, *quando* `GET /api/v1/metrics/spc?source=live` é chamado, *então* `L-04` não está em `points` nem em `excluded_lots`; com `object_type=wrench`, 422; `GET /api/v1/metrics/summary` traz `by_object_type["wrench"] == 10`; `GET /api/v1/inspections?object_type=spirit_level` responde 200; o enum `SpcObjectType` no `openapi.json` é igual ao da SPEC-016 (CA-05 dela); e `GET /api/v1/health` traz `contract_version == "0.7.0"`.
- **CA-05 (borda, modelo e decisão)** — *Dado* um modelo dummy com `object_types = ["screw", "other", "hammer"]` (sem `nut`), *quando* o `labels.json` tem `ungraded_object_types = []`, *então* `ModelLoadError`; com `["hammer"]`, o modelo carrega; e a decisão com `type_probs = [0.05, 0.05, 0.90]` dá `object_type == ObjectType.HAMMER` e `grade is None`. *Quando* uma captura no modo `inspect` é decidida como `hammer`, *então* a resposta tem `approved` nulo, `labels_pt.verdict == "sem grau"` e `labels_pt.object_type == "martelo"`.
- **CA-06 (coleta)** — *Dado* a borda no modo `collect`, *quando* envia `T-010` com `spirit_level` e grau vazio, *então* a foto é gravada em `raw/spirit_level/_/` e o manifest ganha 1 linha; com `T-011`, `hammer` e `good`, 422 com `detail == "grade must be empty for an identification-only tool"`, sem arquivo novo e sem linha nova; com `O-012` e `hammer`, 422 sem gravar nada; e com `T-013`, `drill` e `good`, o `detail` continua `grade must be empty for a power tool`.
- **CA-07 (importação)** — *Dado* um plano com `T-601` `hammer` sem grau, origem `contributor`, `c01`, *quando* a importação roda, *então* sai com 0 e grava em `raw/hammer/_/`. *Dado* um plano com essa linha e `T-602` `wrench` com grau `good`, *então* sai com 2, a stderr tem `plan line 3: grade_on_other (grade)` e nada é gravado; e com `O-603` `spirit_level`, a stderr tem `item_prefix_mismatch (object_type)`.
- **CA-08 (página e console)** — *Dado* a borda, *quando* `GET /capture?t=<token>` é chamado, *então* o HTML tem `<option value="hammer">martelo</option>`, `<option value="wrench">chave de aperto</option>` e `<option value="spirit_level">nível</option>`, e o `capture.js` servido tem os três na lista do prefixo `T`. *Quando* o console é aberto por `http://127.0.0.1:<porta>/`, *então* a tabela `id="coverage"` tem uma linha para cada tipo novo, com o grau `sem grau`.
- **CA-09 (dashboard)** — *Dado* `formatting.history_rows` com um `InspectionRead` `wrench` sem grau, *então* `Tipo == "chave de aperto"` e `Grau == "sem grau"`. E `charts.OBJECT_TYPE_ORDER` contém cada um dos 15 membros do `ObjectType` uma única vez; `charts.OBJECT_TYPE_COLORS` tem 15 chaves e 15 cores distintas; `filters.TYPE_OPTIONS` contém `martelo`, `chave de aperto` e `nível`; e `filters.SPC_OBJECT_TYPES` é igual ao da SPEC-016.

### Parte B

- **CA-10 (constantes do ML)** — *Dado* `qc_ml.data`, *então* `POWER_TOOL_OBJECT_TYPES == ("angle_grinder", "saw", "drill", "cordless_screwdriver")`, `IDENTIFIED_TOOL_OBJECT_TYPES == ("hammer", "wrench", "spirit_level")`, os três são os 3 últimos de `KNOWN_OBJECT_TYPES`, estão no prefixo `T` e em `GRADE_FORBIDDEN_DATASET_TYPES`, e `tool_grade_coverage` de qualquer `df` tem só as 5 manuais como chaves.
- **CA-11 (dados)** — *Dado* `make_synthetic_dataset(<root>, identified_tool_items_per_type=3)`, *quando* `load_manifest` é chamado, *então* não há erro e há 9 peças `T-` dos três tipos novos, com as imagens em `raw/<tipo>/_/`; com uma linha editada para grau `good` num `hammer`, `ManifestError` com o código `grade_on_other`; e com `power_tool_items_per_type=3` (sem o parâmetro novo), há exatamente 12 peças `T-` elétricas, como no CA-09 da SPEC-021.
- **CA-12 (tipos do modelo)** — *Dado* o `df` do CA-11, *quando* `derive_model_labels(df, df)` é chamado, *então* `object_types` termina com `hammer`, `wrench`, `spirit_level`, `ungraded_object_types` contém os três, e `grade_target("hammer", "good", labels) is None`.
- **CA-13 (extensão do teste)** — *Dado* um `split_v1` sem os tipos novos e, depois, o dataset com `identified_tool_items_per_type=6`, *quando* a CLI de split roda com `--extend-test-types hammer,wrench,spirit_level`, *então* sai com 0, cada tipo novo tem peças em `train`, `val` e `test`, nenhum aviso `small_stratum` cita um estrato `hammer/<grau>`, e as linhas do `split_v1` mantêm o split.
- **CA-14 (gerador)** — *Dado* `make_synthetic_dataset` padrão em dois diretórios, um deles com `identified_tool_items_per_type=0` e `external_identified_tool_items_per_type=0` explícitos, *então* os arquivos são iguais byte a byte.

### Manual

- **CA-15 (manual, produção; humano com o security-devops)** — Depois do merge: 1. `infra/migrate.py` aplica a `007` no Supabase pela conexão direta ou pelo pooler em modo session; 2. `select pg_get_constraintdef(oid) from pg_constraint where conname in ('inspections_object_type_check','inspections_grade_null_iff_unknown')` mostra `spirit_level` nos dois; 3. deploy do `partqc-api` e depois do `partqc-web` pelo Coolify; 4. `GET https://<subdominio>/api/v1/health` responde `contract_version: "0.7.0"`; 5. só então a borda é atualizada; 6. `python -m qc_edge.requeue --outbox-path <arquivo>` lista zero `dead`, ou devolve os `dead` a `pending`. Registrar no test-report a data e o resultado de cada passo, sem o subdomínio real (R-13).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (developer) | grupos e invariante; migração; coleta, importação, página, console; formatação e gráficos | `packages/contracts/tests/`, `api/tests/`, `edge/tests/`, `dashboard/tests/` |
| Unitário (ml-engineer) | constantes, prefixo e grau vazio; `derive_model_labels`; extensão; gerador | `ml/tests/` |
| Aceite (tester) | Um por CA automatizado; o CA-03 e o CA-04 com o marcador `db` | `*/tests/acceptance/test_spec_044.py` |
| Manual | CA-15 | descrito no CA |

Mock só nas fronteiras externas: nenhum teste acessa o Supabase de produção nem a VPS. Ordem da rodada e relatório do autor como na SPEC-021 §6: a Parte A primeiro, a Parte B depois, no mesmo dev-report, com a lista dos aceites antigos afetados (§3.1).

## 7. Riscos e notas para o implementador

- **Ordem de deploy:** a borda com um modelo que conhece os tipos novos não pode publicar antes da `007` e da API 0.7.0 em produção (§4.4, CA-15). O modelo da SPEC-045 só chega à borda depois disso.
- **`grade_on_other`:** o código do problema da importação e do `qc_ml.data` continua com esse nome para todo tipo sem grau (observação do reviewer da SPEC-021); só a mensagem da rota de coleta muda (§4.3).
- **Nome da restrição:** `inspections_grade_null_iff_unknown` continua com o nome antigo (RV-02 da SPEC-016), para não quebrar os testes que o conhecem.
- **Cores:** escolha 3 cores distintas das 12 atuais e do cinza do `unknown`; o CA-09 só confere que são 15 distintas.
- **`spirit_level`:** o nome em inglês evita confusão com "nível de log" e com o grau; a interface sempre mostra `nível`. Se o humano escolher `level` na aceitação do ADR-025, o architect troca o valor nesta SPEC antes do `Ready`.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] READMEs e `packages/contracts/README.md` atualizados; `docs/architecture.md` §3, §5, §6.3 e §7 e `docs/dataset-protocol.md` §5 e §10.3 pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-15 registrado depois do deploy

## 9. Perguntas para a aprovação (humano)

1. Os nomes e rótulos (`hammer`/martelo, `wrench`/chave de aperto, `spirit_level`/nível) são os do ADR-025, pergunta 1. **Recomendação:** aprovar junto com o ADR.
2. O CA-15 (migração e deploy em produção) pode ser feito logo depois do merge, antes da SPEC-045? **Recomendação:** sim. A `007` só amplia o que o banco aceita e não muda nenhuma linha.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-11-04 | SPEC criada como `Draft`: contrato 0.7.0 com `hammer`, `wrench` e `spirit_level` no grupo sem grau, migração `007`, borda, dashboard e constantes do `qc-ml`; CAs 01 a 14 automatizados e CA-15 manual em produção | Decisão do humano de 2026-11-04 (ADR-025, `Proposto`) | Orquestrador, a pedido do humano |
| 2026-11-04 | Aprovada pelo humano (`Ready`): "Aprovar tudo", com as recomendações da §9; rotulagem dupla dispensada e declarada (ADR-025, resposta 5) | Aceite do ADR-025 | Humano |
