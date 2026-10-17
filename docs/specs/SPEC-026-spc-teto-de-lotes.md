# SPEC-026: Carta p com teto de lotes (`qc-contracts` 0.3.0)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | contrato, security |
| Depende de | SPEC-006 (e SPEC-023, pela versão vigente do contrato; SPEC-004, pelo CA-28 de versões) |
| Semana alvo | S4 |
| Requisitos cobertos | RF-10, RNF-09 (cobertura de `qc_api.services`), R-04, R-06 |
| ADRs relevantes | **ADR-017** (novo, `Proposto`), ADR-013, ADR-006 |

> Esta SPEC implementa o ADR-017. Os dois precisam de aprovação humana (ADR `Aceito`, SPEC `Ready`) antes do loop. Ela tem de estar `Done` **antes de a SPEC-013 entrar em `In Dev`**.

## 1. Contexto

A rota `GET /api/v1/metrics/spc` (SPEC-006) devolve um ponto por lote válido e um item de `excluded_lots` por lote pequeno, sem limite. O security-devops mediu (SEC-06-01, média, `reviews/SPEC-006/r1-security-report.md`): com muitos lotes pequenos, a chamada padrão do dashboard passa de 800 MB de memória. O Render free tem 512 MB e 0,1 CPU (<https://render.com/docs/compute-plans>, verificado em 2026-10-17). O processo é morto, e a ingestão cai junto. O custo está no Python, não no banco, então o `statement_timeout` (SPEC-015) não resolve. O reviewer chegou ao mesmo ponto pela leitura (RV-02 de `reviews/SPEC-006/r1-review-report.md`).

O ADR-017 decide o corte: os últimos `max_points` lotes válidos, os 50 excluídos mais recentes, os totais na resposta e a base de `p̄` na história inteira (o ADR-013 não muda). `docs/architecture.md` §3.4 descreve a carta com o corte.

Esta SPEC também fecha o RV-03 do mesmo review (validação de tipos de `LotCounts`), porque mexe no mesmo módulo.

## 2. Objetivo

Para qualquer volume gravado, `GET /api/v1/metrics/spc` responde com no máximo `max_points` pontos (padrão 100, máximo 500) e 50 lotes excluídos, com `valid_lots_total` e `excluded_lots_total`, e com os mesmos `p̄`, limites e `out_of_control` que a carta sem corte teria para esses lotes.

## 3. Escopo

### 3.1 Dentro

- `packages/contracts/`: os 3 campos opcionais de `SpcResponse` (§4.1); versão **0.3.0** em `__init__.py` e `pyproject.toml`; linha nova no histórico de versões do `packages/contracts/README.md`; `uv.lock` atualizado.
- `api/src/qc_api/services/spc.py`: validação de `LotCounts`, `MAX_EXCLUDED_LOTS`, `LotSelection`, `select_lots`, `build_p_chart` e `compute_p_chart` estendida (§4.2).
- `api/src/qc_api/repositories/inspections.py`: `lot_selection` com o corte no SQL (§4.3). A função `lot_counts` sai, se nada mais a usar.
- `api/src/qc_api/routers/metrics.py`: parâmetro `max_points` (§4.4).
- Testes do autor em `api/tests/` e `packages/contracts/tests/` (inclusive `test_smoke.py`, com a versão nova).
- Testes de aceite: `packages/contracts/tests/acceptance/test_spec_026.py` (CA-01 e CA-02) e `api/tests/acceptance/test_spec_026.py` (CA-03 a CA-16).
- **Ajustes autorizados ao tester desta SPEC em testes de aceite de SPECs anteriores** (regra "Expectativas de versão" de `docs/architecture.md` §10 e regra "Testes de aceite de SPECs anteriores" da mesma seção, introduzida pelo PR #16; até ele entrar na `main`, vale esta autorização explícita). Só estes três, e nada mais nesses arquivos:
  1. `packages/contracts/tests/acceptance/test_spec_023.py`, `test_ca01_contracts_version`: as duas asserções exatas (`== "0.2.0"`) passam à forma genérica da §10 (coerência `__version__ == importlib.metadata.version("qc-contracts")`, `re.fullmatch(r"\d+\.\d+\.\d+", v)` e o piso `(0, 2, 0) <= ... < (1, 0, 0)`).
  2. `api/tests/acceptance/test_spec_004.py`, conjunto `ALLOWED_EXACT` do CA-28 da SPEC-004: o par `(SPEC023_CONTRACTS, "qc_contracts", "0.2.0")` passa a `(<caminho de packages/contracts/tests/acceptance/test_spec_026.py>, "qc_contracts", "0.3.0")`, com uma constante de caminho no mesmo padrão das outras. O resto do CA-28 (inclusive `VERSION_FILES` e as contagens) não muda.
  3. `packages/contracts/tests/acceptance/test_spec_002.py`, `test_ca16_response_models_json_round_trip`: só nos casos `spc` e `spc-empty`, o valor esperado de `model_dump(mode="json")` passa a ser `data` acrescido de `"max_points": None, "valid_lots_total": None, "excluded_lots_total": None`. Os fixtures `SPC_JSON` e `SPC_EMPTY_JSON` continuam como estão (são o JSON da 0.2.0, que continua válido). Os outros casos não mudam.

  Nenhum CA das SPECs 002, 004, 006 e 023 muda. O número de testes coletados nesses arquivos não muda.

### 3.2 Fora

- Desenho do corte no dashboard (aviso de carta cortada, controle de `max_points`): SPEC-013.
- `statement_timeout` no banco de produção: SPEC-015.
- Janela `from`/`to` na carta: rejeitada pelo ADR-017 (opção B).
- `check` do banco contra linhas fora do contrato (`infinity`, UUID v1, `model_version`): SPEC-027.
- Tipos da Fase 2 na carta (`SpcObjectType`): SPEC-016.
- Alertas: SPEC-017, que reusa a seleção desta SPEC.

## 4. Requisitos detalhados

### 4.1 Contrato 0.3.0 (`qc_contracts.SpcResponse`)

Três campos novos, depois de `message`, todos opcionais e com padrão `None`:

| Campo | Tipo | Significado |
|---|---|---|
| `max_points` | `int ≥ 1` \| `None` | O teto de pontos usado. `None` quando a carta foi calculada sem teto (só por `compute_p_chart` sem `max_points`; a rota sempre preenche) |
| `valid_lots_total` | `int ≥ 0` \| `None` | Número de lotes válidos (`n ≥ min_lot_size`) da consulta, **antes** do corte |
| `excluded_lots_total` | `int ≥ 0` \| `None` | Número de lotes excluídos da consulta, **antes** do corte |

- É uma mudança minor (campo opcional com padrão; skill `contrato-api`). Um leitor 0.2.0 ignora os campos (`extra="ignore"`), e um JSON 0.2.0 continua válido na 0.3.0, com os 3 campos `None`.
- `qc_contracts.__version__ == "0.3.0"` e a versão do `pyproject.toml` igual. O histórico do `packages/contracts/README.md` ganha a linha `| 0.3.0 | ... |`, citando a SPEC-026.
- `docs/architecture.md` §3.4 já descreve os campos (alterado junto com esta SPEC).

### 4.2 Serviço `qc_api.services.spc`

- **`LotCounts`** (RV-03): além das regras da SPEC-006 §4.1, `__post_init__` levanta `ValueError` quando `n` ou `defects` não for `int` ou for `bool`, e quando `started_at` ou `ended_at` não tiver fuso (`tzinfo is None` ou `utcoffset() is None`).
- **`MAX_EXCLUDED_LOTS = 50`** (constante do módulo).
- **`@dataclass(frozen=True) class LotSelection`**, com os campos `baseline: tuple[LotCounts, ...]`, `window: tuple[LotCounts, ...]`, `excluded: tuple[LotCounts, ...]`, `valid_lots_total: int` e `excluded_lots_total: int`. As três tuplas vêm em ordem crescente de `(started_at, lot_id)`.
- **`select_lots(lots, baseline_lots, min_lot_size, *, max_points, max_excluded) -> LotSelection`**: a referência pura do que o SQL faz.
  1. `baseline_lots < 1`, `min_lot_size < 1`, `max_points` diferente de `None` e `< 1`, ou `max_excluded` diferente de `None` e `< 0` → `ValueError`.
  2. Ordena uma cópia por `(started_at, lot_id)`, comparando `lot_id` como `str` do Python.
  3. Válidos: `n >= min_lot_size`; excluídos: os demais.
  4. `baseline` = os primeiros `baseline_lots` válidos; `window` = os últimos `max_points` válidos (todos, com `None`); `excluded` = os últimos `max_excluded` excluídos (todos, com `None`; nenhum, com `0`).
  5. `valid_lots_total` e `excluded_lots_total` são as contagens antes do corte.
- **`build_p_chart(selection, baseline_lots, min_lot_size, *, source, max_points) -> SpcResponse`**:
  - `valid_lots_total < 2` → `points = []`, `p_bar = None` e a `message` da SPEC-006 §4.1 passo 4, com `k = valid_lots_total`;
  - senão, `p̄` sobre `selection.baseline` (passo 5 da SPEC-006) e um ponto por lote de `selection.window` (passos 6 a 8). `baseline` vazio com `valid_lots_total >= 2` → `ValueError` (seleção incoerente);
  - `excluded_lots` = `selection.excluded`, como `SpcExcludedLot(lot_id, n)`;
  - preenche `baseline_lots`, `min_lot_size`, `source`, `max_points` (o valor recebido, inclusive `None`), `valid_lots_total` e `excluded_lots_total`.
- **`compute_p_chart(lots, baseline_lots=20, min_lot_size=5, *, source=Source.LIVE, max_points=None, max_excluded=None) -> SpcResponse`** = `build_p_chart(select_lots(...), ...)`. Sem `max_points` e sem `max_excluded`, os pontos, `p_bar`, `excluded_lots` e `message` são idênticos aos da SPEC-006. Os parâmetros novos são só por palavra-chave.
- O módulo continua puro (CA-15 da SPEC-006): sem I/O, sem relógio, sem logging.

### 4.3 Repositório: `lot_selection`

`lot_selection(pool, source, object_type, *, baseline_lots, min_lot_size, max_points, max_excluded) -> LotSelection`, com os mesmos filtros da SPEC-006 §4.2 (`object_type <> 'unknown'`, `source = ...` e, se informado, `object_type = ...`).

1. Todos os valores entram como parâmetros nomeados do psycopg, inclusive `%(baseline_lots)s`, `%(max_points)s`, `%(max_excluded)s` e `%(min_lot_size)s`. A composição usa só `psycopg.sql` (CA-19 da SPEC-005).
2. **O corte é no SQL:** a agregação por `lot_id` (`n`, `defects`, `started_at`, `ended_at`) roda **uma vez** por requisição, numa CTE `as materialized`. As partes saem dela com `order by ... limit`:
   - totais: uma linha com as duas contagens;
   - base: os primeiros `baseline_lots` válidos;
   - janela: os últimos `max_points` válidos;
   - excluídos: os últimos `max_excluded` excluídos.
   O Python recebe no máximo `baseline_lots + max_points + max_excluded + 1` linhas.
3. Toda ordenação usa `started_at` e, no desempate, `lot_id collate "C"` (ADR-017, item 6), em ordem crescente ou decrescente conforme a parte. O resultado devolvido vem em ordem crescente.
4. Mesmo snapshot `repeatable read, read only` das outras leituras (`_read_snapshot`).

### 4.4 Rota `GET /api/v1/metrics/spc`

| Parâmetro novo | Padrão | Validação (fora → 422) |
|---|---|---|
| `max_points` | 100 (`SPC_DEFAULT_MAX_POINTS`) | inteiro de 2 a 500 (`SPC_MAX_MAX_POINTS`) |

- A rota chama `lot_selection(..., max_points=max_points, max_excluded=MAX_EXCLUDED_LOTS)` e `build_p_chart`.
- Os outros parâmetros, a autenticação (401 antes de 422), o 503 e a regra de origem (R-06) não mudam (SPEC-006 §4.2).
- Mais lotes do que o teto **não** é erro: a resposta é 200, cortada, com os totais.

### 4.5 Portão de cobertura

O passo do CI da SPEC-006 §4.3 (`qc_api.services` ≥ 80%) continua, sem mudança.

## 5. Critérios de aceite

Comparações numéricas com tolerância absoluta de `5e-5`, como na SPEC-006. "Exemplo 1" é o da SPEC-006 §4.4. `T0 = 2026-10-01T08:00:00Z`.

- **CA-01 (contrato, versão)** — *Dado* o pacote instalado, *quando* se leem as versões, *então* `qc_contracts.__version__ == "0.3.0"`, `importlib.metadata.version("qc-contracts") == "0.3.0"`, e o `packages/contracts/README.md` tem uma linha de tabela que começa com `| 0.3.0 |` e contém `SPEC-026`. (Funções de teste com nome `test_ca01_*`, exigência do CA-28 da SPEC-004.)
- **CA-02 (contrato, campos)** — *Dado* um JSON da 0.2.0 (o exemplo de `architecture.md` §3.4 sem os 3 campos novos, com datas UTC no lugar de `"..."`), *quando* validado por `SpcResponse.model_validate_json`, *então* é aceito e `max_points`, `valid_lots_total` e `excluded_lots_total` valem `None`; *dado* o mesmo JSON com `"max_points": 100, "valid_lots_total": 250, "excluded_lots_total": 7`, *então* o `model_dump(mode="json")` devolve esses valores; *dado* `max_points = 0`, `valid_lots_total = -1` ou `excluded_lots_total = -1`, *então* `ValidationError`; e o conjunto de `SpcResponse.model_fields` é exatamente o da 0.2.0 mais esses 3 nomes.
- **CA-03 (RV-03)** — *Dado* `LotCounts` com `n=True`, `n=5.0`, `defects=False`, `defects=1.5`, `started_at` sem fuso ou `ended_at` sem fuso (demais campos válidos), *quando* construído, *então* levanta `ValueError`; e com `started_at` e `ended_at` em `-03:00`, é aceito.
- **CA-04 (`select_lots`)** — *Dado* os lotes do Exemplo 1, *quando* `select_lots(lots, 3, 5, max_points=2, max_excluded=0)`, *então* `baseline` tem os `lot_id` `L-001`, `L-002`, `L-004`, `window` tem `L-006`, `L-007`, `excluded == ()`, `valid_lots_total == 6` e `excluded_lots_total == 1`; e com `max_points=None, max_excluded=None`, `window` tem os 6 válidos e `excluded` tem `L-003`.
- **CA-05 (corte não muda a base)** — *Dado* os lotes do Exemplo 1, *quando* `compute_p_chart(lots, baseline_lots=3, min_lot_size=5, max_points=2, max_excluded=0)`, *então* `p_bar = 0.1385`; `points` tem `L-006` (`p = 0`, `ucl = 0.3457`, `lcl = 0`, `out_of_control = false`) e `L-007` (`p = 0.01`, `ucl = 0.2421`, `lcl = 0.0348`, `out_of_control = true`), nessa ordem; `excluded_lots == []`; `max_points == 2`; `valid_lots_total == 6`; `excluded_lots_total == 1`; e `message is None`.
- **CA-06 (sem corte = SPEC-006)** — *Dado* os lotes do Exemplo 1, *quando* `compute_p_chart(lots, baseline_lots=3, min_lot_size=5)` (sem os parâmetros novos), *então* `points`, `p_bar`, `excluded_lots` e `message` são iguais aos do CA-01 da SPEC-006, `max_points is None`, `valid_lots_total == 6` e `excluded_lots_total == 1`; e com `max_points=6`, os `points` são os mesmos, com `max_points == 6`.
- **CA-07 (poucos lotes, com totais)** — *Dado* `L-1 (n=20, defects=2)` em `T0`, `L-2 (n=3, defects=1)` em `T0 + 1 h` e `L-3 (n=2, defects=0)` em `T0 + 2 h`, *quando* `compute_p_chart(lots, min_lot_size=5, max_points=10, max_excluded=1)`, *então* `points == []`, `p_bar is None`, `message` termina em `(found 1)`, `excluded_lots == [{"lot_id": "L-3", "n": 2}]`, `valid_lots_total == 1` e `excluded_lots_total == 2`.
- **CA-08 (validação)** — *Dado* os lotes do Exemplo 1, *quando* `select_lots` ou `compute_p_chart` recebe `max_points=0` ou `max_excluded=-1`, *então* levanta `ValueError`; com `max_excluded=0`, não levanta.
- **CA-09 (equivalência, propriedade)** — *Dado* 200 histórias geradas com `random.Random(seed)` para `seed` de 0 a 199 (de 0 a 300 lotes; `n` de 1 a 30; `defects` de 0 a `n`; `started_at` com empates frequentes; `lot_id` sorteado no alfabeto de `LOT_ID_PATTERN`, com maiúsculas, minúsculas, `_` e `-`) e parâmetros sorteados (`baseline_lots` de 1 a 100, `min_lot_size` de 1 a 10, `max_points` de 1 a 50, `max_excluded` de 0 a 20), *quando* se comparam `compute_p_chart` com corte (C) e sem corte (S), *então* `C.p_bar == S.p_bar`, `C.points == S.points[-max_points:]`, `C.excluded_lots == S.excluded_lots[-max_excluded:]` (lista vazia quando `max_excluded == 0`), `C.message == S.message`, `C.valid_lots_total == S.valid_lots_total ==` o número de lotes com `n >= min_lot_size`, e `C.excluded_lots_total == S.excluded_lots_total == len(S.excluded_lots)`.
- **CA-10 (rota, volume pequeno)** — *Dado* o banco do CA-10 da SPEC-006 (Exemplo 1 `live` com 3 `unknown` e o lote `L-SIM` `simulated`), *quando* `GET /api/v1/metrics/spc?baseline_lots=3` com a chave de leitura, *então* 200 com os valores do CA-01 da SPEC-006, `max_points == 100`, `valid_lots_total == 6` e `excluded_lots_total == 1`.
- **CA-11 (rota, corte)** — *Dado* no banco de teste 130 lotes `live` válidos `C-0001` … `C-0130` (`object_type=screw`, `n = 5`, `defects = k mod 3` para o lote `k`, começando em `T0 + k min`) e 60 lotes `live` excluídos `X-001` … `X-060` (`n = 1`, `X-k` começando em `T0 + k min + 30 s`), *quando* `GET /api/v1/metrics/spc` sem parâmetros, *então* 200; `points` são `C-0031` … `C-0130`, em ordem; `p_bar` é `Σ defects / Σ n` de `C-0001` … `C-0020`; `excluded_lots` são `X-011` … `X-060`, em ordem; `valid_lots_total == 130`; `excluded_lots_total == 60`; `max_points == 100`; e o corpo JSON é igual a `compute_p_chart(<os 190 lotes>, 20, 5, source=Source.LIVE, max_points=100, max_excluded=50).model_dump(mode="json")`. Com `?max_points=10`, `points` são `C-0121` … `C-0130`, com o mesmo `p_bar`.
- **CA-12 (desempate com `collate "C"`)** — *Dado* 3 lotes `live` válidos com o mesmo `started_at` e os `lot_id` `a-1` (`n=10`, `defects=9`), `B-1` (`n=10`, `defects=1`) e `_-1` (`n=10`, `defects=5`), *quando* `GET /api/v1/metrics/spc?baseline_lots=2&max_points=2`, *então* `points` tem `_-1` e `a-1`, nessa ordem, e `p_bar = 0.3` (base `B-1` e `_-1`), igual a `compute_p_chart` com os mesmos lotes e parâmetros.
- **CA-13 (parâmetro novo, erros)** — *Dado* o banco do CA-10, *quando* `max_points=1`, `max_points=501`, `max_points=abc` ou `max_points=2.5`, *então* 422 sem stack trace; *quando* `max_points=2` ou `max_points=500`, *então* 200 com `max_points` igual ao enviado; e *dado* nenhuma `X-API-Key` com `max_points=0`, *então* 401 `{"detail": "Missing or invalid API key"}` (401 antes de 422).
- **CA-14 (memória e corpo limitados; `db` e `slow`)** — *Dado* no banco de teste 120 000 lotes `live` de 1 inspeção e 600 lotes `live` de 5 inspeções (inseridos com `generate_series`), e uma requisição de aquecimento com `source=simulated` já feita, *quando* `GET /api/v1/metrics/spc` sem parâmetros é chamado com `tracemalloc` ligado só durante a chamada, *então* 200, `len(points) == 100`, `len(excluded_lots) == 50`, `valid_lots_total == 600`, `excluded_lots_total == 120000`, o corpo tem menos de 64 KB e o pico do `tracemalloc` durante a chamada fica abaixo de 20 MB.
- **CA-15 (corte no SQL, estático)** — *Dado* o módulo `qc_api.repositories.inspections`, *quando* se lê o texto SQL usado por `lot_selection`, *então* ele contém `materialized`, `collate "C"`, `%(baseline_lots)s`, `%(max_points)s`, `%(max_excluded)s` e `%(min_lot_size)s`, e cada um desses três limites aparece numa cláusula `limit`.
- **CA-16 (R-06)** — *Dado* o banco do CA-11 mais 5 lotes `simulated` válidos `S-1` … `S-5`, *quando* `GET /api/v1/metrics/spc` sem `source`, *então* nenhum `S-*` aparece em `points` nem em `excluded_lots` e `valid_lots_total == 130`; e com `source=simulated`, `points` tem só `S-1` … `S-5`, `valid_lots_total == 5` e `source == "simulated"`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Campos e versão do contrato | `packages/contracts/tests/` |
| Unitário (autor) | `LotCounts`, `select_lots`, `build_p_chart` e `compute_p_chart` (sem banco); `lot_selection` e a rota (com banco) | `api/tests/test_spc.py`, `api/tests/test_spc_route.py` |
| Aceite (tester) | CA-01 e CA-02 | `packages/contracts/tests/acceptance/test_spec_026.py` |
| Aceite (tester) | CA-03 a CA-16 (CA-10 a CA-14 e CA-16 marcados `db`; CA-14 também `slow`) | `api/tests/acceptance/test_spec_026.py` |
| Aceite (tester) | Os 3 ajustes autorizados da §3.1 | arquivos citados na §3.1 |

Banco: Postgres 16 de teste com as fixtures da SPEC-003. Os dados do CA-11, CA-12, CA-14 e CA-16 são inseridos por SQL direto, como na SPEC-006. Sem mocks. A docstring do módulo de `test_spec_026.py` do contrato cita só a versão 0.3.0 (§10).

## 7. Riscos e notas para o implementador

- **Ordem de `lot_id`:** sem `collate "C"`, um banco com collation `en_US` ordena `a-1` antes de `B-1`, e o lote que fica na fronteira do corte muda. O CA-12 pega isso. O Postgres do Docker usa `en_US.utf8` por padrão.
- **Uma agregação só:** quatro consultas separadas sobre `inspections` multiplicam o custo do banco (5 s no pior caso local, SEC-06-01). Use a CTE `materialized` com `union all` das partes marcadas, ou várias consultas sobre uma tabela temporária, desde que a agregação de `inspections` rode uma vez.
- **`tracemalloc` no CA-14:** mede só objetos Python, o que basta: sem o corte no SQL, as 120 000 linhas viram dicionários e `LotCounts` (dezenas de MB). Ligue o `tracemalloc` depois do aquecimento, para não contar a construção dos schemas.
- **CA-28 da SPEC-004:** ele procura comparações exatas de versão em todo `packages/*/tests/acceptance/test_spec_*.py`. Por isso, o CA-01 desta SPEC precisa estar em funções `test_ca01_*`, e o `ALLOWED_EXACT` precisa do ajuste 2 da §3.1. Sem ele, o CA-28 falha.
- **`LotCounts` mais estrito:** o `count(*)` do psycopg volta `int`, e `timestamptz` volta com fuso, então a rota não é afetada. O CA-07 da SPEC-014 monta `LotCounts` com `int` e datas UTC, então também não é afetado.
- Ordem de deploy (skill `contrato-api`): `contracts` → API → dashboard. Como nada está publicado, não há janela de transição. O dashboard (SPEC-013) trata os 3 campos como opcionais.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS), e os testes de aceite das SPECs 002, 004, 006, 014 e 023 continuam passando
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde, incluindo o portão de cobertura; `ruff` limpo
- [ ] `packages/contracts/README.md` com a linha da 0.3.0
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)
