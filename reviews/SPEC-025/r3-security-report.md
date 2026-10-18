# SPEC-025 — r3 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r3 (última pela R-10) |
| Revisor de segurança | security-devops |
| Diff revisado | `b1e6b8b..56e95e8` (o que mudou desde o [r2-security-report.md](r2-security-report.md)); `main` continua em `8392a8e`, a mesma base da r2 |
| Relatórios lidos | [r3-test-report.md](r3-test-report.md) (PASS), [r3-review-report.md](r3-review-report.md) (APPROVED) |
| **Veredicto** | **PASS** |

A r3 só corrige o helper `_collected` do teste de aceite CA-12, que falhou no CI do PR #24. Nada de produção nem de configuração de segurança mudou. O portão da r2 continua valendo na íntegra, inclusive os achados SEC-25-01 a SEC-25-07 e as ações pendentes para o humano.

## Superfície analisada

| Commit | Agent | Arquivos |
|---|---|---|
| `b1b3b8c`, `ce3308f`, `56e95e8` | orchestrator | `docs/plan.md` e o cabeçalho da SPEC (só status e rodada) |
| `41a0711` | tester | `edge/tests/acceptance/test_spec_025.py` (+3/−1, só o filtro de ambiente do `_collected`) e `reviews/SPEC-025/r3-test-report.md` |
| `55d215a` | reviewer | `reviews/SPEC-025/r3-review-report.md` |

`git diff --name-only b1e6b8b..HEAD` não lista nada em `edge/src`, `packages/`, `api/`, `dashboard/`, `scripts/`, `infra/`, `.github/`, `conftest.py`, `.env.example`, `uv.lock` ou `pyproject.toml`.

A mudança tira `CI` (além de `TEST_DATABASE_URL`) do ambiente de um subprocesso `pytest --collect-only` que conta os testes de dois arquivos. Isso **não afrouxa** a política de banco da SPEC-001: o `conftest.py` da raiz não mudou, a execução principal do CI continua sujeita a ela, e o subprocesso só coleta, sem tocar banco nem rede. O padrão é o mesmo do `infra/tests/test_db_fixtures.py` e do `infra/tests/acceptance/test_spec_003.py`.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| — | — | — | — | Nenhum achado novo. O RV-08 do review (`PYTEST_ADDOPTS` herdado no subprocesso) é de robustez do teste, não de segurança. | — |
| SEC-25-01 a SEC-25-07 (r2) | baixa / informativa | ver [r2-security-report.md](r2-security-report.md) | — | Sem mudança na r3, como esperado. | Mesmo destino da r2 (emenda do architect numa SPEC futura de manutenção da borda). |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação e autorização | N/A nesta rodada (sem mudança de produção; vale a r2) |
| Validação de entrada | N/A nesta rodada (vale a r2) |
| SQL parametrizado, RLS, CORS | N/A |
| Logs sem dados sensíveis | N/A nesta rodada (vale a r2) |
| Segredos (R-03) | ✅ Nenhum segredo no diff (busca por `secret`, `token`, `password`, `key=` sem resultado) |
| Privacidade das imagens (R-02, R-14) | N/A nesta rodada (vale a r2) |
| Dependências novas | ✅ Nenhuma (`uv.lock` e `pyproject.toml` intocados) |
| Deploy e CI | ✅ `.github/` e `infra/` intocados; a política de banco do `conftest.py` da raiz não mudou |
| R-07 / R-13 | ✅ Cada commit com o `Agent:` do seu papel; nenhum `Agent: security-devops` na branch; identidade CarlosZeyy |

Teste que rodei: `uv run pytest -q edge/tests/acceptance/test_spec_025.py -k ca12`, sem `CI` e sem `TEST_DATABASE_URL` → 1 passed. Não rodei a suíte inteira.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma nesta rodada. |

## Ações pendentes para o humano

As mesmas da r2: conferir o código de saída da varredura e o `find ml/data/raw -type f ! -name '*.jpg'` antes de cada backup, e decidir com o architect a emenda do SEC-25-01 e do SEC-25-02.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
