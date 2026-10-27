# SPEC-021 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r2 (correção do bug T-01 da r1) |
| Tester | tester |
| Commit testado | `d4c2c74` (correção do developer em `57bf279`) |
| Rodada anterior | [r1-test-report.md](r1-test-report.md) (`69ca648`, FAIL só pelo T-01) |
| **Veredicto** | **PASS** |

## O que mudou desde a r1

`git diff 69ca648..d4c2c74 --stat`:

```text
 docs/plan.md                      |  2 +-
 reviews/SPEC-021/r1-dev-report.md |  2 +-
 reviews/SPEC-021/r2-dev-report.md | 44 +++++++++++++++++++++++++++++++++++++++
 3 files changed, 46 insertions(+), 2 deletions(-)
```

| Commit | Trailer `Agent:` | Arquivos |
|---|---|---|
| `47ba357` | orchestrator | `docs/plan.md` e o status da SPEC (volta para `In Dev`, r2) |
| `57bf279` | developer | `reviews/SPEC-021/r1-dev-report.md` (linha 87 reescrita sem a URL de exemplo com usuário e senha) e `reviews/SPEC-021/r2-dev-report.md` (novo) |
| `d4c2c74` | orchestrator | `docs/plan.md` e o status da SPEC (`In Test`, r2); a mudança no arquivo da SPEC se anula com a do `47ba357` no diff líquido |

Não mudou nenhum código de produção, teste do autor nem teste de aceite. Por isso o resultado da suíte completa da r1 (`8952 passed, 143 skipped` e as 2 falhas do T-01, ver o [r1-test-report.md](r1-test-report.md)) continua valendo para o código, e esta rodada roda só um recorte: os testes do T-01, todo o `infra/tests` e os aceites da SPEC-021.

## Bug da r1

| ID | Situação | Verificação |
|---|---|---|
| T-01 | **Corrigido** em `57bf279` | A linha 87 do `r1-dev-report.md` descreve o exemplo em texto, sem o literal; o `r2-dev-report.md` também não tem o literal. Os 2 testes de segredo passam (abaixo). |

## Cobertura dos critérios de aceite

A mesma da r1, sem mudança nos testes (`*/tests/acceptance/test_spec_021.py`, 226 testes, CA-01 a CA-13). Todos passam no commit testado. O CA-14 continua manual e pendente para a dupla; ele não bloqueia o merge.

## Recorte rodado

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q \
    infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs \
    infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files \
    packages/contracts/tests/acceptance/test_spec_021.py api/tests/acceptance/test_spec_021.py \
    edge/tests/acceptance/test_spec_021.py dashboard/tests/acceptance/test_spec_021.py \
    ml/tests/acceptance/test_spec_021.py
228 passed, 1 warning in 25.94s

$ uv run pytest -q infra/tests          (sem banco: sem TEST_DATABASE_URL e sem CI)
555 passed, 529 skipped in 40.21s

$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q infra/tests
976 passed, 108 skipped in 89.89s      (os skipped são os testes de imagem Docker, PARTQC_DOCKER_TESTS)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
291 files already formatted
```

## Bugs encontrados

Nenhum novo.

## Testes exploratórios (além dos critérios)

Os mesmos da r1 (ver o [r1-test-report.md](r1-test-report.md)). Nesta rodada só conferi que os relatórios novos ou alterados (`r1-dev-report.md`, `r2-dev-report.md`) não contêm o padrão de URL de banco com senha.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só este relatório.
