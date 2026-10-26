# SPEC-039 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `fdfe18d`. O código de produção não mudou desde a r1: o último commit em `infra/compose*.yaml` é o `78f6ceb`, e o dev-report da r2 registra "no author changes". |
| **Veredicto** | **PASS** |

## Motivo da rodada

O **RV-05** (adendo de `reviews/SPEC-039/r1-review-report.md`) apontou um problema no `infra/tests/acceptance/test_spec_032.py`. Ao inserir o helper `_resolved_services` na r1, eu o coloquei entre o `@pytest.mark.docker` e o `def test_extra_compose_config_resolves_pids_and_override`. Com isso, o teste perdeu o marcador `docker`, e o marcador passou a decorar o helper. Como consequência:

- o teste saía da coleta do job `docker` (`-m docker`);
- e rodava na suíte comum, chamando `docker compose` sem `PARTQC_DOCKER_TESTS=1`.

## Correção

Movi o decorador de volta para cima do teste, e o helper ficou sem marcador. Foi uma única mudança, de uma linha, no `test_spec_032.py`.

## Ajuste em aceite antigo (`docs/architecture.md` §10)

Esta linha corrige o ajuste da r1 registrado no `r1-test-report.md` (adendo, tabela "Ajustes adicionais", linha do `test_extra_compose_config_resolves_pids_and_override`).

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_compose_config_resolves_pids_and_override` e o helper `_resolved_services` | `@pytest.mark.docker` decorava o `_resolved_services` (deslocado na r1) → decora de novo o `test_extra_compose_config_resolves_pids_and_override`, como na `main`. O helper fica sem marcador. As asserções não mudaram. | SPEC-015 §4.14 (marcador `docker`); RV-05 do adendo do `r1-review-report.md`. O ajuste original decorre da SPEC-039 §4.1 (última linha da §3.1). |

## Conferências

- **Coleta:** `uv run pytest --collect-only -q -m docker infra/tests/acceptance/test_spec_032.py` coleta 11 itens, entre eles o `test_extra_compose_config_resolves_pids_and_override`. Antes da correção, ele ficava fora.
- **Sem `PARTQC_DOCKER_TESTS`:** o teste é pulado (`SKIPPED ... set PARTQC_DOCKER_TESTS=1 to run`).
- **Varredura dos meus três arquivos de aceite** (`test_spec_015.py`, `test_spec_032.py`, `test_spec_039.py`). Usei um script `ast` fora do repositório, que verifica:
  - se há marcador `docker` em função que não começa com `test_`: nenhum caso, depois da correção;
  - se há `test_*` sem marcador que use as fixtures `build_image`/`compose_copy`/`containers`/`routed_stack`/`*_image` ou chame `docker`/`compose`: só 3 falsos positivos no `test_spec_015.py` (`test_ca32_check_docker`, `test_extra_check_docker_missing_executable` e `test_extra_docker_marker_hook_usage_error_without_docker`). São testes da SPEC-015 que eu não alterei e que exercitam o `check_docker` com executores falsos;
  - **comparação com a `origin/main`:** o conjunto de testes com `@pytest.mark.docker` é igual no `test_spec_015.py` (10). No `test_spec_032.py`, também são 10, e a única diferença é a renomeação já registrada na r1 (`..._writes_only_volumes` → `..._writes_only_tmpfs`). Nenhum marcador se perdeu.

## Suíte completa

Rodei sem `TEST_DATABASE_URL` e sem `CI`, como nas rodadas anteriores, para não usar o banco de teste compartilhado. Os testes `db` foram pulados.

```text
$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests
92 passed, 744 deselected in 190.26s

$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
5790 passed, 788 skipped, 1 warning in 432.27s
(na r1: 5791 passed, 787 skipped. A diferença é este teste, que agora é pulado sem
 PARTQC_DOCKER_TESTS em vez de rodar docker na suíte comum. Warning preexistente do
 fastapi.testclient.)

$ uv run ruff check .          -> All checks passed!
$ uv run ruff format --check . -> 239 files already formatted
```

Limpeza conferida depois dos testes `docker`:

- nenhum contêiner `partqc-acc*`/`partqc-test*`;
- nenhuma imagem com a label `partqc.test=1` nem `partqc-test*`;
- nenhuma rede `partqc*`, inclusive a `partqc-api-link`;
- nenhum volume novo.

## Cobertura dos critérios de aceite

Sem mudança desde o adendo da r1 (`r1-test-report.md`, "Depois da correção do SEC-39-01"). Os CA-01 a CA-13 e o CA-19 continuam com teste e passando, e os testes `docker` foram executados. CA-14 a CA-18 e CA-20 são manuais (humano, depois do merge).

## Bugs encontrados

Nenhum.

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
