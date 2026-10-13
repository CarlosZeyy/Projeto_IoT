# SPEC-005: API de leitura e métricas

| Campo | Valor |
|---|---|
| Status | Ready — **Aguardando reaprovação humana** |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-004 |
| Semana alvo | S4 |
| Requisitos cobertos | RF-09, RF-11, RF-13 (filtro por origem), RF-15 (chave de leitura), RNF-06, R-06 |
| ADRs relevantes | ADR-006 (FastAPI + psycopg), ADR-007 (dashboard lê via API), ADR-013 (regra de defeito) |

## 1. Contexto

`docs/architecture.md` §4 lista as rotas de leitura usadas pelo dashboard (SPEC-013): listagem paginada, resumo, série temporal e lotes. Os schemas de resposta já existem em `qc_contracts` (SPEC-002) e o banco, índices e regra `is_defective` vêm da SPEC-003. Todas as rotas desta SPEC exigem a chave de leitura (`READ_API_KEY`, dependência `require_read_key` da SPEC-004).

## 2. Objetivo

O dashboard obtém, com a chave de leitura, listagens e agregados corretos e filtráveis das inspeções, com contagens verificadas contra um conjunto de dados conhecido.

## 3. Escopo

### 3.1 Dentro

- `api/src/qc_api/routers/inspections.py` (rota `GET`), `routers/metrics.py` (summary e timeseries), `routers/lots.py`.
- `api/src/qc_api/filters.py`: dependência `InspectionFilters` compartilhada pelas rotas.
- `api/src/qc_api/repositories/` (ou módulo equivalente) com as consultas SQL parametrizadas.
- **Manutenção da SPEC-004** (§4.5): `api/src/qc_api/routers/inspections.py` (escrita: `psycopg.IntegrityError` → 422) e `api/src/qc_api/middleware.py` (500 genérico sem a mensagem de `psycopg.Error` no log).
- Testes em `api/tests/`.

### 3.2 Fora

- SPC (`/metrics/spc`) e `qc_api.services.spc` (SPEC-006).
- Dashboard e rótulos PT-BR na tela (SPEC-013).
- Página de dispositivos (SPEC-018).

## 4. Requisitos detalhados

### 4.1 Autenticação e erros comuns

- Todas as rotas usam `require_read_key`: sem chave, chave errada ou chave de dispositivo → 401 `{"detail": "Missing or invalid API key"}`.
- Banco indisponível → 503 `{"detail": "Database unavailable"}`. Validação de parâmetros → 422 padrão do FastAPI. Parâmetros de query desconhecidos são ignorados.

### 4.2 Filtros comuns (`InspectionFilters`)

| Parâmetro | Tipo / validação | Semântica |
|---|---|---|
| `device_id` | `DEVICE_ID_PATTERN` | igualdade |
| `lot_id` | `LOT_ID_PATTERN` | igualdade |
| `object_type` | `ObjectType` | igualdade |
| `grade` | `Grade` | igualdade (exclui linhas com `grade` nulo) |
| `source` | `Source` | igualdade; ausente = todas as origens |
| `defective` | bool | `is_defective = valor` |
| `from` | datetime com fuso | `inspected_at >= from` (inclusivo) |
| `to` | datetime com fuso | `inspected_at < to` (exclusivo) |

- Datetime sem fuso → 422; `from >= to` → 422; valores fora de enum ou regex → 422.
- Filtros combinam com `AND`. Todo valor entra na consulta como **parâmetro** do psycopg; a composição de cláusulas usa `psycopg.sql` (sem f-string com valores).

### 4.3 Rotas

- `GET /api/v1/inspections` → `Page[InspectionRead]`:
  - filtros comuns + `limit` (padrão 50, 1…500; fora → 422) e `offset` (padrão 0, ≥ 0; negativo → 422);
  - ordem `inspected_at desc, inspection_id asc` (paginação estável);
  - `total` = número de linhas que casam com os filtros (independe de `limit`/`offset`); offset além do total → `items = []`.
- `GET /api/v1/metrics/summary` → `MetricsSummary` (filtros comuns):
  - `total` = linhas que casam (inclui `unknown`); `defective` = linhas com `is_defective`; `unknown_count` = linhas com `object_type = 'unknown'`; `needs_review_count` = linhas com `needs_review`;
  - **`defect_rate = defective / (total − unknown_count)`**; denominador 0 → `null` (nunca erro de divisão);
  - `by_grade`: as **5** chaves de `Grade`, preenchidas com 0 quando não há linhas; `by_object_type`: as **3** chaves de `ObjectType`, idem;
  - `mean_type_confidence` = média de `type_confidence` (todas as linhas; `null` se `total = 0`); `mean_grade_score` = média de `grade_score` não nulo (`null` se nenhuma).
- `GET /api/v1/metrics/timeseries` → `list[TimeseriesPoint]` (array JSON):
  - `bucket` ∈ `minute|hour|day` (padrão `hour`; outro → 422) + filtros comuns;
  - `bucket_start = date_trunc(bucket, inspected_at, 'UTC')` (sempre em UTC, com fuso na resposta); o nome do bucket entra como parâmetro, nunca concatenado;
  - por bucket: `total`, `defective` e `defect_rate = defective / (total − unknown do bucket)` (`null` se o denominador for 0);
  - só buckets com dados, em ordem crescente de `bucket_start`;
  - mais de 5 000 buckets → 422 `{"detail": "Too many buckets; narrow the time range or use a larger bucket"}`.
- `GET /api/v1/lots` → `Page[LotSummary]`:
  - filtros comuns + `limit`/`offset` como na listagem;
  - um item por `lot_id` entre as linhas que casam: `n` = linhas (inclui `unknown`), `defects`, `unknown_count`, `started_at = min(inspected_at)`, `ended_at = max(inspected_at)`, `sources` = origens distintas na ordem do enum;
  - ordem `started_at desc, lot_id asc`; `total` = número de lotes.

### 4.4 Desempenho

- As consultas filtram por colunas com índice da SPEC-003 (`inspected_at`, `lot_id`, `(source, inspected_at)`, `device_id`). Agregações são feitas no SQL (`count(*) filter (...)`, `avg`), nunca carregando linhas para o Python.

### 4.5 Erros de banco na escrita e no log (manutenção da SPEC-004)

Pendência SEC-04-01 (= RV-01) de `reviews/SPEC-004/r2-security-report.md` e `r2-review-report.md`. A mensagem de uma `IntegrityError` contém os valores da linha (`DETAIL: Failing row contains (...)`, confirmado em sonda). Se ela escapasse da rota, o `logger.exception` do `UnhandledErrorMiddleware` registraria parte do corpo. Hoje o caminho é inalcançável, porque as `check` do `001_init.sql` espelham o contrato, mas uma migração futura que diverja do contrato o reabriria, e o problema só apareceria em produção. Regra geral em `docs/architecture.md` §4 ("Erros de banco no log").

1. **Escrita** (`POST /api/v1/inspections` e `/inspections/batch`, função `_write`): `psycopg.IntegrityError` (SQLSTATE classe `23`), levantada no `insert` ou no `update devices`, recebe o mesmo tratamento do `psycopg.DataError` (classe `22`) da SPEC-004 §4.5:
   - `rollback` da transação inteira (nada gravado e `last_seen_at` inalterado);
   - 422 com o corpo exato `{"detail": "Value cannot be stored"}`, levantado com `from None`;
   - um log `WARNING` com só a rota, o `device_id` e o SQLSTATE (ex.: `sqlstate=23514`), nunca os valores nem a mensagem do servidor.

   O 422, e não o 500, é o que faz o publisher da SPEC-009 isolar o item por bissecção e marcá-lo como `dead`, em vez de reenviar o lote para sempre. A precedência da SPEC-004 §4.5 não muda: o último degrau "422 (valor que o banco recusa)" passa a cobrir as classes `22` e `23`. `OperationalError` continua → 503.
2. **500 genérico** (`UnhandledErrorMiddleware`): se a exceção não tratada for um `psycopg.Error`, ou tiver um `psycopg.Error` na cadeia `__cause__`/`__context__`, o middleware registra em nível `ERROR` uma única linha `unhandled database error: route=<rota> type=<classe> sqlstate=<código>` (`-` quando não houver SQLSTATE), **sem** `exc_info` e sem a mensagem. `<rota>` segue a mesma regra do log por requisição (o template da rota, ou o `repr` cortado do caminho). `<classe>` é a da primeira `psycopg.Error` da cadeia. As outras exceções continuam com o `logger.exception` de hoje. A resposta continua 500 `{"detail": "Internal server error"}`.

## 5. Critérios de aceite

**Conjunto D** (inserido direto no banco de teste migrado, com `edge-01` e `sim-01` registrados; `T0 = 2026-10-01T10:00:00Z`; campos não listados válidos):

| # | device | lot | source | object_type | grade | grade_score | type_confidence | needs_review | inspected_at |
|---|---|---|---|---|---|---|---|---|---|
| 1 | edge-01 | L-A | live | screw | perfect | 0.2 | 0.90 | false | T0 + 5 min |
| 2 | edge-01 | L-A | live | screw | good | 1.1 | 0.80 | false | T0 + 10 min |
| 3 | edge-01 | L-A | live | nut | poor | 3.0 | 0.70 | true | T0 + 20 min |
| 4 | edge-01 | L-A | live | unknown | — | — | 0.40 | true | T0 + 50 min |
| 5 | edge-01 | L-B | live | nut | unusable | 3.9 | 0.95 | false | T0 + 70 min |
| 6 | edge-01 | L-B | live | screw | fair | 2.0 | 0.85 | false | T0 + 75 min |
| 7 | sim-01 | L-S | simulated | screw | poor | 3.2 | 0.99 | false | T0 + 120 min |
| 8 | sim-01 | L-S | simulated | nut | good | 1.0 | 0.99 | false | T0 + 150 min |

Chave de leitura `R = "r"*32`. Valores `float` comparados com tolerância relativa de `1e-6` (colunas `real`).

- **CA-01** — Dado D, quando `GET /api/v1/inspections` sem `X-API-Key`, com `X-API-Key: errada` ou com a chave do dispositivo `edge-01`, e o mesmo nas rotas `/metrics/summary`, `/metrics/timeseries` e `/lots`, então todas respondem 401 com `{"detail": "Missing or invalid API key"}`.
- **CA-02** — Dado D, quando `GET /api/v1/inspections?limit=3` com `R`, então 200 com `total=8`, `limit=3`, `offset=0` e `items` = linhas #8, #7, #6 nessa ordem; cada item valida como `InspectionRead`, e o item #7 tem `is_defective=true` e `source="simulated"`.
- **CA-03** — Dado D, quando `?limit=3&offset=6`, então `items` = #2, #1 e `total=8`; com `offset=8`, `items=[]` e `total=8`.
- **CA-04** — Dado D, quando `limit=0`, `limit=501`, `offset=-1`, `object_type=bolt`, `grade=bad`, `source=test`, `device_id=Edge_01`, `lot_id=L%20A`, `from=2026-10-01T10:00:00` (sem fuso) ou `from=2026-10-01T12:00:00Z&to=2026-10-01T11:00:00Z`, então cada requisição responde 422; e `limit=500` responde 200.
- **CA-05** — Dado D, quando a listagem é filtrada por `source=live` → `total=6`; `lot_id=L-A` → 4; `grade=poor` → #7, #3; `defective=true` → 3; `device_id=sim-01` → 2; `object_type=unknown&grade=poor` → 0; `from=2026-10-01T11:00:00Z&to=2026-10-01T12:00:00Z` → #6, #5 (a linha #7, em 12:00, fica de fora porque `to` é exclusivo).
- **CA-06** — Dado D, quando `GET /api/v1/metrics/summary` sem filtros, então `total=8`, `defective=3`, `unknown_count=1`, `needs_review_count=2`, `defect_rate=3/7≈0.428571`, `by_grade={"perfect":1,"good":2,"fair":1,"poor":2,"unusable":1}`, `by_object_type={"screw":4,"nut":3,"unknown":1}`, `mean_type_confidence=0.8225` e `mean_grade_score=14.4/7≈2.057143`.
- **CA-07** — Dado D, quando o resumo é filtrado por `source=live`, então `total=6`, `defective=2`, `unknown_count=1`, `defect_rate=0.4`, `mean_type_confidence≈0.766667` e `mean_grade_score=2.04`; com `source=simulated`, `total=2`, `defective=1`, `defect_rate=0.5`; com `lot_id=L-A`, `defect_rate=1/3`.
- **CA-08** — Dado D, quando o resumo é filtrado por `lot_id=L-ZZZ` (sem linhas), então 200 com `total=0`, `defective=0`, `defect_rate=null`, `mean_type_confidence=null`, `mean_grade_score=null`, `by_grade` com as 5 chaves valendo 0 e `by_object_type` com as 3 chaves valendo 0.
- **CA-09** — Dado D, quando o resumo é filtrado por `object_type=unknown`, então `total=1`, `defective=0`, `defect_rate=null` (denominador 0), `mean_grade_score=null` e `mean_type_confidence=0.40`.
- **CA-10** — Dado D, quando `GET /api/v1/metrics/timeseries?bucket=hour`, então a resposta é um array com 3 pontos, em ordem: `2026-10-01T10:00:00Z` (`total=4`, `defective=1`, `defect_rate=1/3`), `11:00Z` (`2`, `1`, `0.5`) e `12:00Z` (`2`, `1`, `0.5`); com `bucket=day`, 1 ponto `2026-10-01T00:00:00Z` com `total=8`, `defective=3`, `defect_rate=3/7`; com `bucket=minute`, 8 pontos.
- **CA-11** — Dado D mais uma linha #9 (`edge-01`, `L-C`, `live`, `screw`, `good`) com `inspected_at = 2026-10-01T23:30:00-03:00`, quando `timeseries?bucket=day&lot_id=L-C`, então há 1 ponto com `bucket_start = 2026-10-02T00:00:00Z` (bucket em UTC, não no fuso local).
- **CA-12** — Dado D, quando `timeseries?bucket=week` ou `bucket=hour;drop table inspections`, então 422 e a tabela `inspections` continua com 8 linhas; com `timeseries?bucket=hour&source=simulated`, 1 ponto (`12:00Z`, `total=2`).
- **CA-13** — Dado 5 001 linhas válidas em minutos distintos (inseridas com `generate_series`), quando `timeseries?bucket=minute`, então 422 com `{"detail": "Too many buckets; narrow the time range or use a larger bucket"}`; com `bucket=day`, 200.
- **CA-14** — Dado D, quando `GET /api/v1/lots`, então `total=3` e `items` em ordem `L-S`, `L-B`, `L-A`; `L-A` tem `n=4`, `defects=1`, `unknown_count=1`, `started_at=2026-10-01T10:05:00Z`, `ended_at=2026-10-01T10:50:00Z`, `sources=["live"]`; `L-S` tem `n=2`, `defects=1`, `sources=["simulated"]`.
- **CA-15** — Dado D mais uma linha em `L-A` com `device_id=sim-01` e `source=simulated`, quando `GET /api/v1/lots?lot_id=L-A`, então `sources=["live","simulated"]` e `n=5`; e `GET /api/v1/lots?source=live&lot_id=L-A` retorna `n=4` e `sources=["live"]`.
- **CA-16** — Dado D, quando `GET /api/v1/lots?limit=1&offset=1`, então `items` = [`L-B`] e `total=3`; com `limit=501`, 422.
- **CA-17** — Dado uma app com `DATABASE_URL` para uma porta local fechada, quando qualquer das quatro rotas é chamada com `R`, então 503 com `{"detail": "Database unavailable"}`.
- **CA-18** — Dado D, quando a listagem é chamada com `lot_id=L-A` e o parâmetro desconhecido `foo=bar`, então 200 com `total=4` (parâmetros desconhecidos ignorados).
- **CA-19** — Dado o código de `api/src/qc_api`, quando o teste procura f-strings, formatação com `%` ou `str.format` aplicados a textos SQL (que contenham `SELECT`, `WHERE` ou `INSERT`), então não encontra nenhuma ocorrência (SQL sempre parametrizado); a composição com `psycopg.sql.SQL(...).format(...)` é permitida e não conta como ocorrência.
- **CA-20 (security, SEC-04-01)** — Dado o contexto comum da SPEC-004 §5 (chave `KE` de `edge-01`, payload `P(id)`), `edge-01` com `last_seen_at` nulo e, no banco de teste, a restrição extra `alter table inspections add constraint ca20_marker check (lot_id <> 'L-INTEG-MARK')`, criada pelo teste e removida num `finally` (ou num banco próprio do teste, com nome que contém `test`), quando `POST /api/v1/inspections` recebe `P(X)` com `lot_id="L-INTEG-MARK"`, e quando `POST /api/v1/inspections/batch` recebe `[P(A), P(B)]` em que `P(B)` tem esse `lot_id`, então cada resposta é 422 com o corpo exato `{"detail": "Value cannot be stored"}`, a tabela não ganha nenhuma linha (`X`, `A` ou `B`), `last_seen_at` continua nulo, ao menos um registro de log contém `sqlstate=23514`, e nenhum registro de log (`caplog` no nível DEBUG) nem corpo de resposta contém `L-INTEG-MARK`.
- **CA-21 (security, regra de `architecture.md` §4)** — Dado o app da API com três rotas de teste acrescentadas pelo próprio teste (`app.add_api_route`): a 1ª levanta `psycopg.errors.UndefinedTable(<marcador 1>)`, a 2ª levanta `RuntimeError("wrapper")` com `__cause__` igual a `psycopg.errors.CheckViolation(<marcador 2>)` e a 3ª levanta `ValueError(<marcador 3>)` (marcadores gerados no teste), quando cada uma é chamada com `TestClient(app, raise_server_exceptions=False)`, então as três respondem 500 com o corpo exato `{"detail": "Internal server error"}`; nos dois primeiros casos, há um registro `ERROR` com `sqlstate=42P01` (e `sqlstate=23514`, respectivamente), nenhum registro contém o marcador 1 nem o 2, e nenhum registro tem `exc_info`; no 3º caso, há um registro com `exc_info` (o comportamento atual continua para exceções que não são de banco).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Validação de filtros (sem banco); consultas e agregações contra o banco de teste com D | `api/tests/` |
| Aceite (tester) | Um teste por CA (marcados `db`, exceto CA-19 e CA-21) | `api/tests/acceptance/test_spec_005.py` |

Banco: Postgres 16 de teste com as fixtures da SPEC-003. O conjunto D é inserido por SQL direto (não pela API), para não depender da regra dos 5 min no futuro. Sem mocks. No CA-20, a restrição extra é real (nada de mock da exceção) e sai do banco no fim do teste. No CA-21, as rotas de teste existem só no app do teste. Para construir as exceções do `psycopg` diretamente, note que o SQLSTATE é atributo de classe (`psycopg.errors.UndefinedTable.sqlstate == "42P01"`).

## 7. Riscos e notas para o implementador

- `date_trunc(text, timestamptz, text)` existe a partir do Postgres 14; o Supabase e o CI usam ≥ 15/16.
- `avg` sobre `real` devolve `double precision`, mas os valores guardados já foram arredondados para `float4`: compare com tolerância.
- `from` é palavra reservada em Python: use `alias="from"` no parâmetro de query.
- `/lots` devolve `Page[LotSummary]`; a SPEC-013 consome esse formato.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-13 | Mudanças: (a) §3.1 inclui a manutenção da escrita (`routers/inspections.py`) e do `middleware.py` da SPEC-004; (b) §4.5 nova: `psycopg.IntegrityError` (classe `23`) na escrita → `rollback` e 422 `{"detail": "Value cannot be stored"}`, com log só de rota, `device_id` e SQLSTATE; 500 genérico sem a mensagem de `psycopg.Error` no log; (c) CAs novos: CA-20 e CA-21; (d) §6 atualizada. Nenhum CA existente muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-04-01 de `reviews/SPEC-004/r2-security-report.md` (= RV-01 de `r2-review-report.md`); regra nova em `docs/architecture.md` §4 | Orquestrador, a pedido do humano |
