# SPEC-021: Fase 3 — ferramentas elétricas (só identificação)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer (Parte A: contrato, banco, API, borda e dashboard) e depois ml-engineer (Parte B: `qc-ml`), na mesma rodada, como na SPEC-016 |
| Tags | contrato, security |
| Depende de | SPEC-016 (grupos de tipos, `ungraded_object_types`, extensão do teste), SPEC-018 (contrato 0.5.0; esta SPEC leva a 0.6.0), SPEC-034 |
| Semana alvo | S8, **só se a Fase 2 fechar no prazo** (PRD §4.3). Ver a pergunta 1 do §9 sobre o congelamento do modelo (M3, 22/11) |
| Requisitos cobertos | PRD §4.3 e §4.4; R-04, R-06, R-11, R-12, R-14 |
| ADRs relevantes | ADR-021 (`Proposto`; grupo "sem grau"), ADR-022 (`Proposto`; extensão do teste), ADR-020, ADR-014, ADR-001 |

> **Pronta para a aprovação humana**, com a regra de escopo mantida. Revista pelo architect em 2026-10-24 (ver o Histórico).

## 1. Contexto

O PRD §4.3 prevê, só se a Fase 2 fechar no prazo, a **identificação** de esmerilhadeira, serra, furadeira e parafusadeira. O estado interno (motor, escovas) está fora do escopo (PRD §4.4): estas ferramentas **nunca** têm grau. `docs/architecture.md` §3.1 reserva os valores `angle_grinder`, `saw`, `drill` e `cordless_screwdriver`.

A SPEC-016 já entrega os mecanismos: o grupo de tipos "sem grau" do contrato (ADR-021), a lista `ungraded_object_types` do `labels.json` e a extensão única do teste para tipos novos (ADR-022). Esta SPEC só acrescenta os 4 tipos ao grupo "sem grau" e às listas de cada componente.

**O que é código e o que é humano.** O código é testável com dados sintéticos. As fotos das ferramentas elétricas, que dependem de a dupla ter acesso a unidades suficientes, e o treino real são trabalho humano (§3.3 e CA-14).

## 2. Objetivo

O contrato 0.6.0 e os componentes aceitam as 4 ferramentas elétricas sempre sem grau, fora do SPC; a coleta e a importação aceitam as fotos delas; e o `qc-ml` treina um modelo que as identifica, medidas num teste próprio.

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `packages/contracts`: `qc-contracts` **0.6.0**: os 4 valores em `ObjectType`, depois de `phillips_screwdriver` e nesta ordem (`angle_grinder`, `saw`, `drill`, `cordless_screwdriver`); rótulos `esmerilhadeira`, `serra`, `furadeira`, `parafusadeira`; os 4 em `GRADE_FORBIDDEN_OBJECT_TYPES`.
- `infra/migrations/NNN_power_tool_object_types.sql`: o `check` de `object_type` com os 12 valores e o `check` de grau com os 4 no ramo "sem grau".
- `api/`: nada além do contrato e da migração. O `SpcObjectType` **não** muda (as elétricas nunca têm grau e nunca entram no SPC).
- `edge/`: modo coleta e importação com os 4 tipos (prefixo `T`/`XT`, grau **vazio** obrigatório; caminho `raw/<tipo>/_/`, o mesmo diretório sem grau do `other`, `NO_GRADE_DIR`); a regra do carregamento da SPEC-016 §4.4 (tipo sem grau do contrato presente no modelo tem de estar em `ungraded_object_types`) passa a valer para eles; a tabela de cobertura do console ganha uma linha por tipo, sem grau.
- `dashboard/`: rótulos, cores e "sem grau".

**Parte B (ml-engineer):**

- `qc_ml.data`: os 4 tipos em `KNOWN_OBJECT_TYPES`; o prefixo `T`/`XT` exige uma ferramenta manual ou elétrica; grau vazio obrigatório para as elétricas; `tool_grade_coverage` continua só com as 5 manuais.
- `derive_model_labels`: as elétricas do modelo entram **sempre** em `ungraded_object_types`, sem passar pelo critério.
- Split: as elétricas usam a extensão e o adiamento da SPEC-016 §4.7, com o estrato só por tipo.
- `make_synthetic_dataset(…, power_tool_items_per_type=0, external_power_tool_items_per_type=0)`, com padrão byte a byte igual ao de hoje.
- Fixture `ml/tests/fixtures/tiny_model_power_tools/` (12 tipos; `ungraded_object_types` com as 4 elétricas), pelo `make_tiny_fixture.py` (opção `--with-power-tools`).
- `ml/README.md`, seção "Ferramentas elétricas (Fase 3)".

**Tester:** `test_spec_021.py` em `packages/contracts`, `api`, `edge`, `dashboard` e `ml` (`tests/acceptance/`).

**Tester, ajustes de aceite antigos** (`docs/architecture.md` §10): as asserções exatas de `0.5.0` em `packages/contracts/tests/acceptance/test_spec_018.py` viram a forma de piso e o `ALLOWED_EXACT` do CA-28 da SPEC-004 passa a apontar para `test_spec_021.py` com `0.6.0`, no mesmo commit; em `test_spec_016.py` dos componentes, as asserções que fixam a lista completa do `ObjectType` (8 valores) ou o conteúdo exato de `GRADE_FORBIDDEN_OBJECT_TYPES` (`{unknown}`) passam a conferir o que a SPEC-016 introduziu (os 8 primeiros valores, nessa ordem; `unknown` no grupo).

### 3.2 Fora

- Grau de estado de ferramentas elétricas e tornos e fresadoras (PRD §4.4).
- Juntar furadeira e parafusadeira numa classe só: não adotado; a confusão entre as duas é reportada na `type_confusion` (R-11). Se uma delas não tiver unidades suficientes, ela fica fora do modelo (§3.3).

### 3.3 Trabalho humano

- **Unidades:** cada tipo precisa de pelo menos 3 unidades físicas diferentes (meta: 6) para ter teste (ADR-022). Fotos de conhecidos (`T-501`…, importação da SPEC-036) contam. Um tipo abaixo de 3 unidades fica adiado (`--defer-types`) e fora do modelo.
- **Meta de imagens:** 90 por tipo (por exemplo, 6 unidades × 5 ângulos × 3 situações), sem contar as externas.
- **Captura:** ferramenta desligada e fora da tomada (ou sem bateria); fundo liso maior que a ferramenta (lençol ou parede clara), a cerca de 50 a 80 cm, com a ferramenta ocupando 40–70% da foto; de 3 a 5 ângulos; sem mãos nem pessoas no quadro (R-14). Grau sempre vazio.
- **Fontes públicas candidatas** (só treino, `XT-`; conferir licença e conteúdo na página oficial antes de registrar): Angle grinder (<https://universe.roboflow.com/shaheens-workspace-3ut7f/angle-grinder>, CC BY 4.0 e cerca de 183 imagens segundo o rascunho de 2026-10-12, não verificado: o Roboflow recusa a consulta direta); a classe de serra do I3D-Tools, se existir (ver a SPEC-016 §3.3).
- Treino real e CA-14 (manual).

## 4. Requisitos detalhados

- **Contrato (ADR-021):** `drill` (e as outras 3) com `grade` não nulo → `ValidationError`; com `grade`, `grade_score` e `grade_confidence` nulos → aceito. Os três grupos continuam disjuntos e somam os 12 membros. Mudança **minor**.
- **SPC e taxa de defeito:** nada muda no código; pela regra `grade is not null` da SPEC-016, as elétricas ficam fora da carta e do denominador de `defect_rate`, como o `unknown`.
- **Borda:** com uma elétrica decidida, a resposta da captura é a da ferramenta sem grau da SPEC-016 §4.4 (`approved = null`, `verdict = "sem grau"`).
- **Ordem de deploy:** contracts → banco → API → dashboard → borda (skill `contrato-api`); SPEC-034 para os `dead` da transição.

## 5. Critérios de aceite

Contexto comum: o mesmo da SPEC-016 (banco de teste `db`, modelo dummy, `make_synthetic_dataset`).

### Parte A

- **CA-01 (contrato)** — *Dado* `qc_contracts`, *então* `__version__ == importlib.metadata.version("qc-contracts") == "0.6.0"`; os 4 últimos valores de `ObjectType` são `angle_grinder`, `saw`, `drill` e `cordless_screwdriver`, nessa ordem; os rótulos são `esmerilhadeira`, `serra`, `furadeira` e `parafusadeira`; e `GRADE_FORBIDDEN_OBJECT_TYPES == {unknown, angle_grinder, saw, drill, cordless_screwdriver}`.
- **CA-02 (invariante)** — *Dado* um `InspectionCreate` válido, *quando* `object_type="drill"` com os três campos de grau nulos, *então* é aceito; com `grade="fair"`, `grade_score=2.0` e `grade_confidence=0.7`, `ValidationError`.
- **CA-03 (banco)** — *Dado* as migrações aplicadas, *quando* o teste insere direto, para cada um dos 12 tipos e cada grau (os 5 e `null`), uma linha com os demais campos válidos, *então* o banco aceita exatamente os pares que o `InspectionCreate` 0.6.0 aceita e recusa os demais com `23514`.
- **CA-04 (API e SPC)** — *Dado* um dispositivo, *quando* faz `POST /api/v1/inspections` com `drill` sem grau, *então* 201. *Dado* no banco os lotes `L-01` a `L-03` com 10 `screw` cada (1 `poor` em cada) e o lote `L-04` com 10 `drill`, *quando* `GET /api/v1/metrics/spc?source=live` é chamado, *então* `L-04` não está em `points` nem em `excluded_lots`; com `object_type=drill`, 422; e o enum `SpcObjectType` no `openapi.json` é igual ao da SPEC-016 (CA-05 dela).
- **CA-05 (borda, modelo e decisão)** — *Dado* um modelo dummy com `object_types = ["screw", "nut", "other", "drill"]`, *quando* o `labels.json` tem `ungraded_object_types = []`, *então* `ModelLoadError`; com `["drill"]`, carrega; e a decisão com `type_probs = [0.05, 0.03, 0.02, 0.90]` dá `object_type == ObjectType.DRILL` e `grade is None`.
- **CA-06 (coleta)** — *Dado* a borda no modo `collect`, *quando* envia `T-010` com `drill` e grau vazio, *então* a foto é gravada em `raw/drill/_/` com a linha no manifest; com `T-010`, `drill` e `good`, 422 sem gravar nada.
- **CA-07 (importação)** — *Dado* um plano com `XT-0010` `angle_grinder` sem grau, `external`, com a fonte registrada, e `XT-0011` `saw` com grau `good`, *quando* a importação roda, *então* a primeira linha entra e a segunda é recusada sem gravar nada.
- **CA-08 (dashboard)** — *Dado* `formatting.history_rows` com um `InspectionRead` `drill` sem grau, *então* `Tipo == "furadeira"` e `Grau == "sem grau"`.

### Parte B

- **CA-09 (dados)** — *Dado* `make_synthetic_dataset(<root>, power_tool_items_per_type=3)`, *quando* `load_manifest` é chamado, *então* não há erro e há 12 peças `T-` elétricas; com uma linha editada para grau `good` numa elétrica, `ManifestError` com o mesmo código de problema que um `other` com grau preenchido recebe hoje (SPEC-011 §4.1).
- **CA-10 (tipos do modelo)** — *Dado* o `df` do CA-09, *quando* `derive_model_labels(df, df)` é chamado, *então* `object_types` termina com `angle_grinder`, `saw`, `drill`, `cordless_screwdriver` e `ungraded_object_types` contém os 4; e `grade_target("drill", None, labels) is None`.
- **CA-11 (split)** — *Dado* o `split_v1` sem ferramentas e, depois, `power_tool_items_per_type=6`, *quando* a CLI de split roda com `--extend-test-types angle_grinder,saw,drill,cordless_screwdriver`, *então* sai com 0, cada elétrica tem peças em `train`, `val` e `test`, as linhas do `split_v1` mantêm o split; e, com uma elétrica de só 2 peças, sai com 2 com `too few items to extend the test`.
- **CA-12 (avaliação)** — *Dado* a fixture `tiny_model_power_tools`, o dataset do CA-11 e o split estendido, *quando* `thresholds` e `evaluate` rodam (sem torch), *então* `type_confusion` é 12×12, `labels.ungraded_object_types` tem as 4 elétricas, `tool_grade_metrics` não tem nenhuma elétrica, e as chaves de topo do `metrics.json` são as da SPEC-016.
- **CA-13 (gerador)** — *Dado* `make_synthetic_dataset` padrão em dois diretórios, um deles com `power_tool_items_per_type=0, external_power_tool_items_per_type=0` explícitos, *então* os arquivos são iguais byte a byte.

### Manual

- **CA-14 (manual, dupla)** — 1. Unidades e fotos do §3.3; 2. relatório de dados; 3. split com `--extend-test-types` só para os tipos com 3 unidades ou mais (os outros em `--defer-types`), por PR; 4. treino no Colab; 5. `metrics.json` com a `type_confusion` completa (sem omitir tipo, R-11) e a entrada do CHANGELOG; 6. o modelo na borda e 4 ferramentas elétricas fotografadas pela página, com o resultado registrado.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (developer) | grupos e invariante; migração; coleta, importação e carregamento; formatação | `packages/contracts/tests/`, `api/tests/`, `edge/tests/`, `dashboard/tests/` |
| Unitário (ml-engineer) | prefixo e grau vazio; `derive_model_labels`; split; gerador | `ml/tests/` |
| Aceite (tester) | Um por CA automatizado | `*/tests/acceptance/test_spec_021.py` |
| Manual (dupla) | CA-14 | descrito no CA |

Ordem da rodada e relatório de dev: como na SPEC-016 §6.

## 7. Riscos e notas para o implementador

- **Congelamento do modelo:** um modelo com as elétricas é treinado depois do M3 (22/11). Ele só substitui o modelo da demo se a comparação no CHANGELOG (métricas de parafuso e porca nas mesmas peças de teste, ADR-022) não piorar; a decisão é humana (pergunta 1 do §9).
- **Furadeira × parafusadeira:** espere confusão alta entre as duas; ela é reportada, não escondida (R-11).
- **Distância:** as fotos de longe mudam o domínio em relação às peças pequenas; não é um problema de código.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] READMEs atualizados; `docs/architecture.md` §3.1 e `docs/dataset-protocol.md` pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-14 manual registrado depois da coleta

## 9. Perguntas para a aprovação (humano)

1. **Modelo depois do congelamento (M3):** se a Fase 3 for liberada, o modelo com as elétricas pode substituir o modelo congelado da demo? **Recomendação:** só se as métricas de parafuso e porca não piorarem na comparação do CHANGELOG; senão, a demo mostra as elétricas como trabalho extra, com o modelo congelado em uso.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-24 | SPEC reescrita para a aprovação, com a regra de escopo mantida. Perguntas do rascunho resolvidas: (1) invariante → ADR-021 (as elétricas no grupo "sem grau", contrato 0.6.0 minor); (2) furadeira e parafusadeira separadas, confusão reportada; (3) metas humanas (3 unidades no mínimo, 6 de meta, 90 imagens) e adiamento de tipo sem unidades; (4) teste estendido → ADR-022. Corrigido: imagens públicas só no treino (ADR-020; o rascunho dizia treino e validação). Novos: Parte A e Parte B na mesma rodada; tag `security`; dependências das SPECs 016, 018 e 034; captura das elétricas; fixture com 12 tipos; ajustes de aceite antigos; CAs CA-01 a CA-13 testáveis e CA-14 manual; pergunta sobre o congelamento do modelo. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
