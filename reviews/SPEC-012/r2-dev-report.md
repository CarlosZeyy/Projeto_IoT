# SPEC-012 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r2 (SPEC_ISSUE-01) |
| Autor | ml-engineer |
| Branch | `spec/SPEC-012-r2-ci-fix` |
| Commits | `406fd66` (teste), mais o commit deste relatório |

## O que mudou

- `ml/tests/test_parity.py::test_ca13_perturbed_fixture_fails`: a asserção `result.max_abs_diff >= 1e-3` virou `9e-4 < result.max_abs_diff < 1.1e-3`, conforme o novo texto do CA-13. A asserção `result.ok is False` e a do código de saída `2` da CLI continuam iguais.

## Por quê

O CI da `main` (run 39191665982) falhou com `max_abs_diff = 0.0009999759495258331`. A fixture é float32, e a saída do onnxruntime no runner difere da gravada em cerca de 1e-8. Por isso a diferença medida depois da perturbação de `1e-3` pode ficar um pouco abaixo de `1e-3`, a depender da CPU. Os limites `1e-3 ∓ 1e-4` seguem a justificativa da SPEC: desigualdade triangular mais o `< 1e-4` do CA-12.

Nada mudou em `ml/src/`, na fixture ou em `ml/tests/acceptance/` (§6, rodada r2).

## Rastreabilidade

| Critério | Arquivo | Teste do autor |
|---|---|---|
| CA-13 | `ml/src/qc_ml/parity.py` (sem mudança) | `ml/tests/test_parity.py::test_ca13_perturbed_fixture_fails` |

## Verificação

- `uv run ruff check .`: passou.
- `uv run ruff format --check .`: passou, com 210 arquivos já formatados.
- `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` (sem torch): **3 failed, 4769 passed, 22 skipped**. Nenhuma das falhas é de `ml/` e nenhuma tem relação com esta SPEC.
  - **Ambiente:** o container `partqc-pg` (postgres:16) não subiu porque o kernel em execução (7.2.10) não tem mais os módulos instalados (só existem os da 7.2.11), e o Docker não cria a rede veth. Para rodar a suíte, usei um Postgres **18.6** local, temporário, na mesma porta 55432. O CI usa `postgres:16`.
  - `infra/tests/acceptance/test_spec_003.py::test_ca12_foreign_keys` e `infra/tests/test_schema_db.py::test_foreign_keys`: o Postgres 18 levanta `RestrictViolation` (SQLSTATE 23001) para FK `ON DELETE RESTRICT`, onde o 16 levantava `ForeignKeyViolation`. É diferença de versão do servidor.
  - `infra/tests/test_schema_db.py::test_rls_blocks_role_without_policies`: a mensagem do servidor saiu em pt_BR. Passa ao reiniciar com `lc_messages=C`; as duas falhas de FK continuam.
- Os dois testes do CA-13 passam localmente, inclusive `ml/tests/acceptance/test_spec_012.py::test_ca13_perturbed_fixture_fails_parity`. Ainda assim, até o tester ajustar a asserção `>= 1e-3` dele, esse é o único teste que pode falhar no CI, como falhou no run 39191665982.

## Métricas

Não houve treino nesta rodada, então não há métricas.

## SPEC_ISSUE

Nenhum.
