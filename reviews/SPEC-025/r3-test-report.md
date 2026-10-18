# SPEC-025 — r3 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r3 (última pela R-10) |
| Tester | tester |
| Commit testado | `b1b3b8c` (branch `spec/SPEC-025-manutencao-borda`) |
| **Veredicto** | **PASS** |

**Não há `r3-dev-report.md`:** o código de produção não mudou nesta rodada. A r3 só corrige um teste de aceite do tester que falhou no CI do PR #24. Nenhum outro arquivo foi alterado além de `edge/tests/acceptance/test_spec_025.py` e deste relatório.

## Causa

No GitHub Actions (`CI=true` e `TEST_DATABASE_URL` definidos), falhou:

```
FAILED edge/tests/acceptance/test_spec_025.py::test_ca12_docstrings_of_spec_022_and_023
AssertionError: ERROR: TEST_DATABASE_URL is required when CI=true
assert 4 == 0
```

O helper `_collected` roda `pytest --collect-only` em subprocesso, com caminho explícito, para contar os testes de `test_spec_022.py` e `test_spec_023.py`. Ele tirava `TEST_DATABASE_URL` do ambiente do subprocesso, mas deixava `CI=true`. Nessas condições, a política de banco da SPEC-001 (`pytest_configure` do `conftest.py` da raiz) aborta com código 4. Localmente o teste passou na r1 e na r2 porque `CI` não estava definido. **O defeito estava no teste, não no produto.**

## Correção

O `_collected` agora tira **as duas** variáveis da política (`TEST_DATABASE_URL` e `CI`) do ambiente do subprocesso. O `--collect-only` não toca o banco, então a contagem é a mesma em qualquer ambiente. As asserções não mudaram: 38 testes coletados para a SPEC-022 e 22 para a SPEC-023, os mesmos números da `main`.

Revisei os outros subprocessos do arquivo: `_start_real_edge` (CA-04) e `test_extra_privacy_module_runs_with_python_m` executam `qc_edge`, não o pytest, e por isso não passam pelo `conftest.py`. Os únicos outros testes de aceite com subprocesso são `test_spec_007.py` e `test_spec_010.py`, de outras SPECs, que não são desta rodada e passam nas quatro combinações abaixo. Nenhum teste roda a suíte inteira em subprocesso (`reviews/checklist.md`).

## Reprodução

Antes da correção:

```
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q edge/tests/acceptance/test_spec_025.py
FAILED ...::test_ca12_docstrings_of_spec_022_and_023 - AssertionError: ERROR: TEST_DATABASE_URL is required when CI=true
1 failed, 196 passed, 1 warning in 20.55s
```

Depois da correção, com o mesmo comando: `197 passed, 1 warning in 21.40s`.

## Resultados (suíte inteira, `uv run pytest -q`, uma de cada vez)

| Ambiente | Saída | Resultado |
|---|---|---|
| sem `CI` e sem `TEST_DATABASE_URL` | código 0 | 3080 passed, 643 skipped (testes `db`) |
| só `TEST_DATABASE_URL` | código 0 | 3723 passed |
| `CI=true` e `TEST_DATABASE_URL` (igual ao CI) | código 0 | 3723 passed |
| `CI=true` sem `TEST_DATABASE_URL` | código 4 | `ERROR: TEST_DATABASE_URL is required when CI=true` (como manda a política da SPEC-001) |

`uv run ruff check .`: `All checks passed!`. `uv run ruff format --check .`: `148 files already formatted`.

O arquivo continua com 197 testes coletados: 53 ligados aos 19 CAs e 144 exploratórios. A cobertura por CA é a mesma da tabela de `r2-test-report.md`. Todos os CAs passaram de novo.

## Bugs e SPEC_ISSUE

Nenhum bug de produto. Nenhum `SPEC_ISSUE`. O único defeito, TR-r3-01 (severidade baixa, só no teste, apareceu apenas no CI), foi corrigido nesta rodada.
