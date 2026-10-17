# SPEC-006: SPC — carta p por lote

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-004 |
| Semana alvo | S4 |
| Requisitos cobertos | RF-10, RNF-09 (cobertura ≥ 80% em `qc_api.services`), R-06 |
| ADRs relevantes | ADR-013 (carta p por lote e regra de defeito), ADR-006 (FastAPI + psycopg) |

## 1. Contexto

`docs/architecture.md` §3.4 define a carta p por lote: subgrupo `lot_id`, exclusão de lotes pequenos, `p̄` sobre os primeiros lotes válidos, limites de 3σ por lote e a regra 1 de fora de controle. A lógica é uma **função pura** em `qc_api.services.spc`; o endpoint só consulta os agregados por lote e serializa `SpcResponse` (SPEC-002). O dashboard (SPEC-013) desenha a carta a partir desta rota.

## 2. Objetivo

`GET /api/v1/metrics/spc` devolve a carta p por lote, calculada por `compute_p_chart` com valores que batem com os exemplos numéricos desta SPEC até a 4ª casa decimal, usando por padrão só dados `live`.

## 3. Escopo

### 3.1 Dentro

- `api/src/qc_api/services/__init__.py` e `services/spc.py` (`LotCounts`, `compute_p_chart`).
- Rota `GET /api/v1/metrics/spc` em `api/src/qc_api/routers/metrics.py` (criado na SPEC-005; se ainda não existir, criar).
- Passo novo no `.github/workflows/ci.yml`: portão de cobertura de `qc_api.services` (4.3).
- Testes em `api/tests/`.

### 3.2 Fora

- Desenho da carta e destaque visual dos pontos (SPEC-013).
- Alertas de lote fora de controle (SPEC-017).
- Regras de Western Electric além da regra 1, e recálculo de `p̄` sem os pontos fora de controle (não previstos no ADR-013).

## 4. Requisitos detalhados

### 4.1 `qc_api.services.spc`

- `@dataclass(frozen=True) class LotCounts`: `lot_id: str`, `started_at: datetime`, `ended_at: datetime`, `n: int`, `defects: int`. Em `__post_init__`: `n >= 1` e `0 <= defects <= n`, senão `ValueError`.
- `compute_p_chart(lots: Sequence[LotCounts], baseline_lots: int = 20, min_lot_size: int = 5, *, source: Source = Source.LIVE) -> SpcResponse`. O parâmetro `source` só é repassado à resposta.
- Algoritmo (fiel a `architecture.md` §3.4):
  1. `baseline_lots < 1` ou `min_lot_size < 1` → `ValueError`.
  2. Ordena por `(started_at, lot_id)` (sem alterar a sequência recebida).
  3. Lotes com `n < min_lot_size` vão para `excluded_lots` (`SpcExcludedLot(lot_id, n)`), na mesma ordem; os demais são **válidos**.
  4. Menos de 2 válidos → `points = []`, `p_bar = None` e `message = "insufficient data: need at least 2 lots with n >= {min_lot_size} (found {k})"`.
  5. `p̄ = Σ defects / Σ n` sobre os primeiros `baseline_lots` válidos (todos, se houver menos).
  6. Para cada lote válido `i`: `p_i = defects_i / n_i`; `σ_i = √(p̄(1−p̄)/n_i)`; `ucl_i = min(1, p̄ + 3σ_i)`; `lcl_i = max(0, p̄ − 3σ_i)`; `cl = p̄`; `out_of_control = p_i > ucl_i or p_i < lcl_i` (desigualdades estritas).
  7. `p̄ = 0` ou `p̄ = 1` → `σ = 0` e `ucl = lcl = p̄`, sem erro de divisão ou de raiz.
  8. Sem arredondamento: os valores saem em precisão `float`; `message = None` quando há pontos.
- Função **pura**: sem I/O, sem relógio, sem logging de dados, não muta a entrada.

### 4.2 Rota `GET /api/v1/metrics/spc`

| Parâmetro | Padrão | Validação (fora → 422) |
|---|---|---|
| `source` | `live` | `Source` |
| `object_type` | ausente (todos exceto `unknown`) | `screw` ou `nut`; `unknown` → 422 |
| `baseline_lots` | 20 | inteiro 2…100 |
| `min_lot_size` | 5 | inteiro 1…500 |

- Auth: `require_read_key` (401 como na SPEC-005); banco indisponível → 503 `{"detail": "Database unavailable"}`.
- Consulta parametrizada (registros com `object_type <> 'unknown'` e `source = %s`, mais `object_type = %s` se informado), agrupada por `lot_id`: `n = count(*)`, `defects = count(*) filter (where is_defective)`, `started_at = min(inspected_at)`, `ended_at = max(inspected_at)`. O resultado vira `LotCounts` e vai para `compute_p_chart`.
- Resposta 200 `SpcResponse` com `baseline_lots`, `min_lot_size` e `source` iguais aos parâmetros efetivos.
- Dados `simulated` só entram com `source=simulated` explícito; nunca há mistura de origens numa carta (R-06).

### 4.3 Portão de cobertura (RNF-09)

- Passo no CI, depois do pytest: `uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-report=term-missing --cov-fail-under=80`. Os testes unitários de `spc.py` não usam banco.

### 4.4 Exemplos numéricos de referência

**Exemplo 1** — `baseline_lots=3`, `min_lot_size=5`, `T0 = 2026-10-01T08:00:00Z`, lote `k` começando em `T0 + k h`:

| Lote | started_at | n | defects |
|---|---|---|---|
| L-001 | T0 + 0 h | 20 | 2 |
| L-002 | T0 + 1 h | 25 | 3 |
| L-003 | T0 + 2 h | 4 | 1 |
| L-004 | T0 + 3 h | 20 | 4 |
| L-005 | T0 + 4 h | 20 | 12 |
| L-006 | T0 + 5 h | 25 | 0 |
| L-007 | T0 + 6 h | 100 | 1 |

- `L-003` é excluído (`n = 4 < 5`). Base = L-001, L-002, L-004: `p̄ = (2+3+4)/(20+25+20) = 9/65 = 0.138462`; `p̄(1−p̄) = 0.119290`.
- `n = 20`: `σ = 0.077230`, `3σ = 0.231690` → `ucl = 0.3702`, `lcl = max(0, −0.0932) = 0`.
- `n = 25`: `σ = 0.069077`, `3σ = 0.207230` → `ucl = 0.3457`, `lcl = 0`.
- `n = 100`: `σ = 0.034538`, `3σ = 0.103615` → `ucl = 0.2421`, `lcl = 0.0348`.

| Lote | p | cl | ucl | lcl | out_of_control |
|---|---|---|---|---|---|
| L-001 | 0.1000 | 0.1385 | 0.3702 | 0.0000 | false |
| L-002 | 0.1200 | 0.1385 | 0.3457 | 0.0000 | false |
| L-004 | 0.2000 | 0.1385 | 0.3702 | 0.0000 | false |
| L-005 | 0.6000 | 0.1385 | 0.3702 | 0.0000 | **true** (acima) |
| L-006 | 0.0000 | 0.1385 | 0.3457 | 0.0000 | false |
| L-007 | 0.0100 | 0.1385 | 0.2421 | 0.0348 | **true** (abaixo) |

**Exemplo 2** — os mesmos lotes com os padrões (`baseline_lots=20`, `min_lot_size=5`): a base são os 6 válidos, `p̄ = 22/210 = 0.1048` (0.104762); `ucl(n=20) = 0.3102`, `ucl(n=25) = 0.2885`, `ucl(n=100) = 0.1966`, `lcl(n=100) = 0.0129`, demais `lcl = 0`; fora de controle: L-005 e L-007.

## 5. Critérios de aceite

Comparações numéricas com tolerância absoluta de `5e-5` (4 casas decimais).

- **CA-01** — Dado os lotes do Exemplo 1, quando `compute_p_chart(lots, baseline_lots=3, min_lot_size=5)`, então `p_bar = 0.1385`, `points` tem 6 itens na ordem L-001, L-002, L-004, L-005, L-006, L-007 com `p`, `cl`, `ucl`, `lcl` e `out_of_control` iguais à tabela de 4.4, `excluded_lots = [{"lot_id": "L-003", "n": 4}]` e `message = None`.
- **CA-02** — Dado os lotes do Exemplo 1, quando `compute_p_chart(lots)` (padrões), então `p_bar = 0.1048`, `ucl` de L-001 = `0.3102`, de L-002 = `0.2885`, de L-007 = `0.1966`, `lcl` de L-007 = `0.0129`, e só L-005 e L-007 têm `out_of_control = true`; a resposta tem `baseline_lots = 20`, `min_lot_size = 5` e `source = "live"`.
- **CA-03** — Dado os lotes do Exemplo 1 passados em ordem embaralhada, quando `compute_p_chart` roda, então o resultado é igual ao do CA-01 e a lista de entrada continua na ordem embaralhada original.
- **CA-04** — Dado dois lotes com o mesmo `started_at` (`L-B` e `L-A`, ambos com `n=10`), quando `compute_p_chart` roda, então `points` vem na ordem `L-A`, `L-B`.
- **CA-05** — Dado os lotes `(n=10, defects=0)`, `(10, 0)`, `(10, 1)` em sequência e `baseline_lots=2`, quando `compute_p_chart` roda, então `p_bar = 0`, todos os pontos têm `ucl = lcl = 0`, o 3º lote (`p = 0.1`) tem `out_of_control = true` e os dois primeiros `false`, sem exceção.
- **CA-06** — Dado os lotes `(n=5, defects=5)`, `(5, 5)`, `(5, 4)` e `baseline_lots=2`, quando `compute_p_chart` roda, então `p_bar = 1`, todos os pontos têm `ucl = lcl = 1`, o 3º lote (`p = 0.8`) tem `out_of_control = true`.
- **CA-07** — Dado os lotes `L-1 (n=20, defects=2)` e `L-2 (n=3, defects=1)` com `min_lot_size=5`, quando `compute_p_chart` roda, então `points = []`, `p_bar = None`, `excluded_lots = [{"lot_id": "L-2", "n": 3}]` e `message = "insufficient data: need at least 2 lots with n >= 5 (found 1)"`; com a lista vazia, `message` termina em `(found 0)` e `excluded_lots = []`.
- **CA-08** — Dado 3 lotes válidos com `p̄` tal que `p̄ + 3σ > 1` (ex.: `(5, 4)`, `(5, 4)`, `(5, 5)` com `baseline_lots=2`, `p̄ = 0.8`), quando `compute_p_chart` roda, então todo `ucl` vale no máximo `1.0` e todo `lcl` vale no mínimo `0.0`.
- **CA-09** — Dado `LotCounts(n=5, defects=6)`, `LotCounts(n=5, defects=-1)` ou `LotCounts(n=0, defects=0)`, quando construído, então levanta `ValueError`; e `compute_p_chart(lots, baseline_lots=0)` ou `min_lot_size=0` levanta `ValueError`.
- **CA-10** — Dado o banco de teste com os lotes do Exemplo 1 gravados como inspeções `live` de `object_type=screw` (em cada lote, `defects` linhas `poor` e as demais `good`), mais 3 linhas `unknown` em L-001 e o lote `L-SIM` `simulated` com `n=10`, `defects=9`, quando `GET /api/v1/metrics/spc?baseline_lots=3` com a chave de leitura, então 200 com os mesmos valores do CA-01 (L-001 com `n=20`, sem as `unknown`), `source="live"` e sem `L-SIM`.
- **CA-11** — Dado o banco do CA-10, quando `GET /api/v1/metrics/spc` sem parâmetros, então os valores batem com o CA-02.
- **CA-12** — Dado o banco do CA-10, quando `GET /api/v1/metrics/spc?source=simulated`, então 200 com `points = []`, `p_bar = null`, `source = "simulated"` e `message` terminando em `(found 1)`; e `?object_type=nut` retorna `points = []` e `message` terminando em `(found 0)`; e `?object_type=screw&baseline_lots=3` retorna o mesmo que o CA-10.
- **CA-13** — Dado o banco do CA-10, quando `baseline_lots=1`, `baseline_lots=101`, `min_lot_size=0`, `min_lot_size=501`, `source=all` ou `object_type=unknown`, então cada requisição responde 422; e `baseline_lots=2`, `baseline_lots=100`, `min_lot_size=1` e `min_lot_size=500` respondem 200.
- **CA-14** — Dado a rota, quando chamada sem `X-API-Key` ou com a chave de um dispositivo, então 401 com `{"detail": "Missing or invalid API key"}`; e numa app com `DATABASE_URL` para uma porta local fechada, com a chave de leitura, 503 com `{"detail": "Database unavailable"}`.
- **CA-15** — Dado o módulo `qc_api/services/spc.py`, quando se analisam seus `import` via `ast`, então não há `psycopg`, `fastapi`, `logging`, `os`, `time` nem `datetime.now` no código (função pura).
- **CA-16** — Dado o repositório, quando se roda `uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-fail-under=80`, então o código de saída é 0; e o `.github/workflows/ci.yml` contém esse passo.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `LotCounts` e `compute_p_chart` com os Exemplos 1 e 2, bordas `p̄=0`/`p̄=1`, empates, menos de 2 lotes, entrada embaralhada (sem banco) | `api/tests/test_spc.py` |
| Unitário (autor) | Rota com banco de teste | `api/tests/test_spc_route.py` (marcado `db`) |
| Aceite (tester) | Um teste por CA (CA-10…CA-14 marcados `db`) | `api/tests/acceptance/test_spec_006.py` |

Banco: Postgres 16 de teste com as fixtures da SPEC-003; os dados do CA-10 são inseridos por SQL direto. Sem mocks.

## 7. Riscos e notas para o implementador

- O `ucl_i = min(1, ·)` é um limite de exibição: como `p_i ≤ 1`, ele não muda nenhum `out_of_control`.
- O `p̄` inclui lotes da base que estejam fora de controle (não há recálculo de fase I), conforme o ADR-013.
- `p̄(1−p̄)` pode dar um negativo minúsculo por erro de ponto flutuante quando `p̄` está muito perto de 0 ou 1: use `max(0.0, ...)` antes da raiz.
- O parâmetro `source` de `compute_p_chart` é só para preencher a resposta; a filtragem por origem é da consulta.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde, incluindo o portão de cobertura; `ruff` limpo
- [ ] PR aberto com os relatórios; merge humano
