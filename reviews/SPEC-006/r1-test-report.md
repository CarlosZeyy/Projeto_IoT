# SPEC-006 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-006](../../docs/specs/SPEC-006-spc.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `bc6778b` (implementação em `df400bd`, `0089839`, `b059f30`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura da implementação. Arquivo: `api/tests/acceptance/test_spec_006.py`, com 41 testes: 22 cobrindo os CAs (o CA-09 parametrizado em 5 casos) e 19 exploratórios (`test_extra_*`). São marcados `db` os testes do CA-10 ao CA-13, o `test_ca14_auth_401` e 8 exploratórios (13 no total).

## Conferência da estatística (cálculo à mão)

Recalculei os Exemplos 1 e 2 de forma independente da implementação, com Python puro e frações:

| Grandeza | À mão | SPEC | Diferença |
|---|---|---|---|
| p̄ (Ex. 1, base L-001, L-002, L-004) | 9/65 = 0.138462 | 0.1385 | 3.8e-5 |
| ucl n=20 (Ex. 1) | 0.370152 | 0.3702 | 4.8e-5 |
| ucl n=25 (Ex. 1) | 0.345692 | 0.3457 | 0.8e-5 |
| ucl n=100 (Ex. 1) | 0.242077 | 0.2421 | 2.3e-5 |
| lcl n=100 (Ex. 1) | 0.034846 | 0.0348 | 4.6e-5 |
| p̄ (Ex. 2, 6 válidos) | 22/210 = 0.104762 | 0.1048 | 3.8e-5 |
| ucl n=20 / n=25 / n=100 (Ex. 2) | 0.310198 / 0.288510 / 0.196636 | 0.3102 / 0.2885 / 0.1966 | ≤ 3.6e-5 |
| lcl n=100 (Ex. 2) | 0.012888 | 0.0129 | 1.2e-5 |

Todos os valores da SPEC ficam dentro da tolerância de `5e-5`. A margem mais apertada é a do ucl(n=20) do Ex. 1 (4.8e-5): não há erro, mas não sobra folga. O LCL negativo (n=20 e n=25) é truncado em 0; L-005 sai acima e L-007 abaixo nos dois exemplos. Os testes também conferem os valores sem arredondamento (`p̄ = 9/65` e `ucl` com `abs=1e-12`).

Pontos do ADR-013 conferidos por teste:
- `p̄` usa só os primeiros `baseline_lots` lotes **válidos**, e o excluído não conta na base (`test_extra_baseline_uses_first_valid_lots_skipping_excluded`).
- `n` varia entre os lotes e cada lote tem os próprios limites.
- O LCL é truncado em 0 e o UCL em 1 (CA-08).
- Os lotes abaixo de `min_lot_size` ficam fora, na ordem da carta.
- `unknown` fica fora tanto de `n` quanto de `started_at`.
- Uma única `source` por carta (R-06).

## Cobertura dos critérios de aceite

Prefixo: `api/tests/acceptance/test_spec_006.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_example_1_with_baseline_3` | ✅ |
| CA-02 | `test_ca02_example_2_defaults` | ✅ |
| CA-03 | `test_ca03_shuffled_input_same_result_and_not_mutated` (5 sementes + ordem invertida; identidade dos objetos da entrada preservada) | ✅ |
| CA-04 | `test_ca04_ties_on_started_at_are_ordered_by_lot_id` | ✅ |
| CA-05 | `test_ca05_p_bar_zero_collapses_limits` | ✅ |
| CA-06 | `test_ca06_p_bar_one_collapses_limits` | ✅ |
| CA-07 | `test_ca07_insufficient_data` (1 válido e lista vazia, com mensagem exata) | ✅ |
| CA-08 | `test_ca08_limits_are_clipped_to_unit_interval` (também confere `p = 1.0 = ucl` → em controle, desigualdade estrita) | ✅ |
| CA-09 | `test_ca09_invalid_lot_counts_raise[5-6, 5--1, 0-0]`, `test_ca09_invalid_parameters_raise[baseline_lots=0, min_lot_size=0]` | ✅ |
| CA-10 | `test_ca10_route_example_1_live_without_unknown_and_simulated` (`db`) | ✅ |
| CA-11 | `test_ca11_route_defaults_match_example_2` (`db`) | ✅ |
| CA-12 | `test_ca12_source_and_object_type_filters` (`db`) | ✅ |
| CA-13 | `test_ca13_parameter_validation` (`db`) | ✅ |
| CA-14 | `test_ca14_auth_401` (`db`: sem chave, chave de `edge-01` e de `sim-01`), `test_ca14_without_database_401_and_503` (porta local fechada, senha gerada em tempo de execução) | ✅ |
| CA-15 | `test_ca15_spc_module_is_pure` (`ast`: `import`/`from … import` sem `psycopg`, `fastapi`, `logging`, `os`, `time`; nenhum atributo `now`/`utcnow`/`today`; sem `open`/`print`/`__import__`) | ✅ |
| CA-16 | `test_ca16_coverage_gate_step_in_ci_after_pytest` (passo presente no `ci.yml` com o comando do §4.3, depois de `uv run pytest -q`), `test_ca16_pytest_cov_is_available`, mais a **execução manual** do comando (abaixo) | ✅ |

### CA-16: execução manual do portão (`docs/architecture.md` §10)

Nenhum teste roda `pytest api/tests` em subprocesso. Rodei uma vez o comando do §4.3, que contém o do CA-16 e acrescenta `--cov-report=term-missing`, sem `CI` e sem `TEST_DATABASE_URL`:

```text
$ uv run pytest api/tests -q -m "not db" --cov=qc_api.services --cov-report=term-missing --cov-fail-under=80
Name                                  Stmts   Miss  Cover   Missing
-------------------------------------------------------------------
api/src/qc_api/services/__init__.py       0      0   100%
api/src/qc_api/services/spc.py           44      0   100%
-------------------------------------------------------------------
TOTAL                                    44      0   100%
Required test coverage of 80% reached. Total coverage: 100.00%
168 passed, 299 deselected, 1 warning in 98.28s (0:01:38)
exit=0
```

Os 168 incluem os 28 testes sem banco deste arquivo, além dos 140 que o autor relatou.

## Suíte completa

```text
# com banco (TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test, sem CI)
$ uv run pytest -q
1814 passed, 1 warning in 310.10s (0:05:10)            exit=0

# sem banco (sem TEST_DATABASE_URL e sem CI)
$ uv run pytest -q
1331 passed, 483 skipped, 1 warning in 171.51s (0:02:51)   exit=0

# só este arquivo: com banco 41 passed; sem banco 28 passed, 13 skipped

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
108 files already formatted
```

O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia antes desta SPEC. A contagem bate: 1773 (dev report) + 41 = 1814. Nenhum teste de aceite de SPEC anterior falhou.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Os casos automatizados estão em `test_extra_*` e passam todos:

| Caso | Resultado |
|---|---|
| Os pontos levam `started_at`, `ended_at`, `n` e `defects` do lote sem alteração | ok |
| Ordenação pelo instante, não pelo offset (`06:00-03:00` = 09:00Z depois de 08:30Z) | ok |
| `baseline_lots` conta só os lotes válidos (o lote excluído no meio não entra em p̄) | ok |
| `excluded_lots` na ordem `(started_at, lot_id)`, não na ordem de entrada | ok |
| Lote com `n == min_lot_size` é válido; `min_lot_size=1` mantém todos; `min_lot_size=21` deixa só os de n ≥ 21 | ok |
| `source` só copiado para a resposta (demais campos idênticos) e só por palavra-chave (`TypeError` posicional) | ok |
| Valores sem arredondamento (`p̄ == 9/65`, ucl exato a 1e-12) | ok |
| `LotCounts` congelado; bordas `defects=0`, `defects=n`, `n=1` aceitas | ok |
| Entrada `tuple` com 2000 lotes: `0 ≤ lcl ≤ cl ≤ ucl ≤ 1` e regra 1 coerente em todos | ok |
| `n = 10¹²` com p̄ ≈ 1e-12: limites finitos, sem erro de raiz | ok |
| `datetime` ingênuo: rejeitado (`ValidationError`, subclasse de `ValueError`, vindo do `SpcPoint`) | ok, não passa em silêncio |
| Rota: uma linha `unknown` 5 h antes do lote não move `started_at`; o lote só com `unknown` não aparece nem em `excluded_lots`; `started_at` em UTC | ok |
| Rota: o mesmo `lot_id` em `live` e `simulated` nunca se mistura; cada carta conta só a própria origem (R-06) | ok |
| Rota: sem `object_type`, os tipos se somam no mesmo lote; com o filtro, os lotes se separam e um lote parcial pode virar excluído | ok |
| Rota: ordem por tempo, não por `lot_id` (`Z-first` antes de `A-second`) | ok |
| Rota: `min_lot_size=1` traz o L-003 para a carta; banco vazio → 200 com `(found 0)` | ok |
| Rota: `baseline_lots=abc`, `2.5`, `-5`, `min_lot_size=` vazio, `source=LIVE`, `object_type=SCREW` e tentativa de injeção em `object_type` → 422 sem traceback | ok |
| Rota: chave errada com parâmetro inválido → 401 (a autenticação vem antes da validação) | ok |

Sondas manuais (não automatizadas, só informativas, sem violar a SPEC):
- Uma lista com `started_at` ingênuo e consciente misturados levanta `TypeError` na ordenação, em vez de `ValueError`. A rota não chega a esse caso, porque `timestamptz` sempre volta com fuso.
- `LotCounts` não verifica o tipo: `n=True` e `n=5.5` são aceitos. A SPEC só exige `n >= 1` e `0 <= defects <= n`, e a rota sempre passa `int` do `count(*)`.
- `compute_p_chart(..., baseline_lots=1)` funciona (a função aceita ≥ 1; a rota limita a 2…100, como a SPEC define).

Checklist §4: nenhum conninfo ou URL com credencial literal no diff nem no arquivo de aceite. O 503 usa uma URL montada com `urlunsplit` e uma senha `secrets.token_hex`. Os trailers `Agent:` dos commits da branch estão presentes (developer e orchestrator).

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
