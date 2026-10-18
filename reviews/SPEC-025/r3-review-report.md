# SPEC-025 — r3 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r3 (última pela R-10) |
| Reviewer | reviewer |
| Diff revisado | `b1e6b8b..ce3308f` (4 arquivos, +64/−4), o que mudou desde o security report r2. O `main...HEAD` completo já foi revisado na r1 e na r2 ([r2-review-report.md](r2-review-report.md), APPROVED) |
| Test report | [r3-test-report.md](r3-test-report.md) (PASS) |
| **Veredicto** | **APPROVED** |

A r3 só corrige um teste de aceite que falhou no CI do PR #24. O código de produção não mudou, e por isso não há `r3-dev-report.md`. Não há achado bloqueante nem alto. Há um achado baixo novo (RV-08). Os achados baixos RV-02 a RV-07 da r2 continuam abertos, com o mesmo destino indicado naquele relatório.

## Escopo do diff

| Commit | Agent | Arquivos |
|---|---|---|
| `b1b3b8c` | orchestrator | `docs/plan.md` e o cabeçalho da SPEC (status `In Test`, r3) |
| `41a0711` | tester | `edge/tests/acceptance/test_spec_025.py` (+3/−1, só o `_collected`) e `reviews/SPEC-025/r3-test-report.md` |
| `ce3308f` | orchestrator | `docs/plan.md` e o cabeçalho da SPEC (status `In Review`) |

Nada em `edge/src`, nos pacotes, na `api/`, no `dashboard/`, no `infra/`, no `uv.lock` ou nos `pyproject.toml`. Os três commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, com `Refs: SPEC-025` e `Agent:` no bloco final de trailers.

## A correção não afrouxa o CA-12

- A única mudança é o filtro do ambiente do subprocesso: antes ele tirava só `TEST_DATABASE_URL`, e agora tira `TEST_DATABASE_URL` e `CI`. As asserções do `test_ca12_docstrings_of_spec_022_and_023` ficaram iguais: as quatro checagens de docstring, `returncode == 0` e as contagens exatas (38 da SPEC-022 e 22 da SPEC-023, as mesmas da `main`).
- A política do `conftest.py` da raiz só age de duas formas. O `pytest_configure` aborta com `CI=true` sem URL. O `pytest_collection_modifyitems` só **acrescenta** um `skip` aos testes `db`, sem desmarcá-los da coleta. Por isso a contagem do `--collect-only` não depende de nenhuma das duas variáveis, e tirar as duas é a forma correta de deixar o resultado igual em qualquer ambiente. É o mesmo padrão que o `infra/tests/acceptance/test_spec_003.py:666` e o `infra/tests/test_db_fixtures.py:25` já usam.

## Outros subprocessos de pytest

Verifiquei todos os `python -m pytest` em subprocesso do repositório. Nenhum tem o mesmo defeito, que era tirar a URL e manter o `CI`:

- `packages/preprocess/tests/acceptance/test_spec_023.py:250`, `packages/preprocess/tests/acceptance/test_spec_024.py:264` e `api/tests/acceptance/test_spec_004.py:805` herdam as **duas** variáveis juntas, então o par continua coerente;
- `tests/acceptance/test_spec_001.py:58`, `tests/acceptance/test_spec_022.py:164` e `tests/test_db_policy.py:27` montam o par de forma explícita, inclusive o caso `CI=true` sem URL, que é o próprio objeto desses testes;
- `infra/tests/test_db_fixtures.py:31` e `infra/tests/acceptance/test_spec_003.py:672` tiram o `CI` antes de definir a URL;
- os outros subprocessos do `test_spec_025.py` (CA-04 e o `python -m` da varredura) executam o `qc_edge`, não o pytest.

## Execuções

- `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q edge/tests/acceptance/test_spec_025.py`: **197 passed**, 1 warning (o aviso de depreciação do `TestClient`, que já aparecia antes).
- `uv run pytest -q edge/tests/acceptance/test_spec_025.py -k ca12`, sem as variáveis: 1 passed.
- `uv run ruff check .`: `All checks passed!`. `uv run ruff format --check .`: `148 files already formatted`.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-08 | baixa | `edge/tests/acceptance/test_spec_025.py:1317` | O `_collected` não tira `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST` do ambiente, ao contrário do `collect()` do `api/tests/acceptance/test_spec_004.py:801-803`. Um `PYTEST_ADDOPTS` com `-k` ou `-m` mudaria a contagem e faria o CA-12 falhar. O workflow do CI não define essa variável, então hoje o teste não falha. | Se o tester voltar a mexer no arquivo, tirar também essas três variáveis. Não justifica outra rodada. |
| RV-02 a RV-07 (r2) | baixa | ver [r2-review-report.md](r2-review-report.md) | Sem mudança na r3, como esperado. | O destino é o mesmo da r2: pendências para uma SPEC futura de manutenção da borda (RV-03 passa pelo security-devops). |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Só o helper do teste, o test report e o status mudaram. |
| 2. Regras inegociáveis | ✅ | R-07: só o tester tocou `tests/acceptance/`, e o orquestrador só tocou o status. R-03: nenhum segredo no diff (a URL é local e sem senha, igual ao `.env.example`). R-10: esta é a r3, a última. R-13: identidade e trailers corretos. |
| 3. Corretude | ✅ | O produto não mudou. A correção é coerente com a política da SPEC-001. |
| 4. Testes | ✅ | CA-12 com as mesmas asserções, passando com e sem `CI=true`. Nenhum teste roda a suíte inteira em subprocesso. |
| 5. Qualidade | ✅ | O comentário no código explica por que as duas variáveis saem. |
| 6. Segurança | N/A | Sem mudança de produção. O portão de segurança da r2 continua valendo ([r2-security-report.md](r2-security-report.md)). |

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
