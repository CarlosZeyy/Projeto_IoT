# SPEC-039 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `b3e922c..142208e` (delta da r2). A base é `ff60d34`, igual à `origin/main`, e a branch não tem conflito com ela. |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

A r2 existe só pelo RV-05 (bloqueante) do adendo do `r1-review-report.md`. O código de produção não mudou desde o `78f6ceb`, revisado no adendo da r1.

## Achados

Nenhum achado novo.

| ID | Situação |
|---|---|
| RV-05 (bloqueante, r1) | **Resolvido.** O `3bde2a2` move o `@pytest.mark.docker` do helper `_resolved_services` de volta para o `test_extra_compose_config_resolves_pids_and_override` (`infra/tests/acceptance/test_spec_032.py:888`), como na `main`. Conferi o resultado: <ul><li>`pytest --collect-only -m docker` volta a coletar o teste;</li><li>sem `PARTQC_DOCKER_TESTS`, o teste é pulado (`set PARTQC_DOCKER_TESTS=1 to run`);</li><li>a varredura de `infra/tests/` e `infra/tests/acceptance/` não acha mais nenhum marcador `docker` em função que não seja `test_`.</li></ul>O ajuste está na tabela da §10 do `r2-test-report.md`, como correção da linha da r1. As asserções não mudaram. |
| RV-06 (baixa, r1) | **Resolvido.** O `68e3d96` corrige o aviso do topo da SPEC, o campo "Depende de" e a nota da hospedagem em `docs/architecture.md` §1. Os três passam a dizer que a emenda 1 foi aceita pelo humano em 2026-10-25, e o Histórico da SPEC ganhou uma linha. Nada mudou em requisito, CA ou no campo Status: o texto só registra um fato já aprovado pelo humano no `94282f5`. Por isso não há reaprovação a conferir pelo ADR-019. |
| RV-01 (baixa, r1) | **Resolvido.** O plano já estava certo desde a r1, e a parte da arquitetura saiu com o RV-06. |
| RV-02 (baixa, r1) | **Continua.** Os comentários do `infra/docker/api.Dockerfile:3`, do `dashboard.Dockerfile:3` e do `.streamlit/config.toml:3` ainda citam o modelo antigo. Os arquivos ficam fora da §3.2, então o certo é tratar na Parte B da SPEC-038, como o dev-report da r2 também propõe. |
| RV-03 (baixa, r1) | **Continua.** A frase do CA-15, passo 2, diz "em Advanced", e o plano diz "General > Build pipeline". A instrução é a mesma (opção desligada). Fica com o architect, sem rodada nova. |
| RV-04 (baixa, r1) | **Continua.** `PUBLIC_HOST_RE` e `_env_file_paths` seguem sem uso em `test_spec_015.py:1548` e `:1564`. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | O delta da r2 só traz a correção do RV-05, o texto do RV-06, os relatórios e os commits de status. Nenhuma reaprovação delegada (ADR-019) nesta rodada. |
| 2. Regras inegociáveis | ✅ | Ver abaixo. |
| 3. Corretude | ✅ | Produção sem mudança desde o `78f6ceb`. A revisão de corretude do adendo da r1 continua valendo. |
| 4. Testes | ✅ | Ver abaixo. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (239 arquivos). |
| 6. Segurança | N/A nesta rodada | Não há mudança de produção. O portão de segurança da SPEC é do reviewer, em relatório próprio. |

### 2. Regras inegociáveis

- **R-03 e R-13:** o delta só tem texto e um decorador movido. Não há segredo, host, IP, UUID nem URL do painel.
- **R-07:** os 6 commits do delta têm o trailer `Agent:` e respeitam os papéis:
  - `security-devops` (`d5e079b`): só o `r2-dev-report.md`;
  - `architect` (`68e3d96`): só a SPEC e o `docs/architecture.md`;
  - `tester` (`3bde2a2`): só `infra/tests/acceptance/test_spec_032.py` e o `r2-test-report.md`;
  - `orchestrator` (`497f587`, `fdfe18d`, `142208e`): só o status no `docs/plan.md` e na SPEC.

  Todos os commits são da identidade do projeto (CarlosZeyy), em Conventional Commits, com `Refs: SPEC-039`.

### 4. Testes

Reproduzi aqui, sem `TEST_DATABASE_URL`, sem `CI` e sem VPS:

- `uv run pytest -q infra/tests tests`: 834 passed e 386 skipped. Em relação à r1, há um skip a mais: é o teste do RV-05, que agora é pulado sem Docker;
- `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests`: 92 passed. Em relação à r1, há um teste a mais: é o mesmo, que voltou ao job `docker`;
- limpeza: não sobrou contêiner, rede `partqc*` (inclusive a `partqc-api-link`), imagem `partqc.test=1` nem volume novo. Os `partqc-pg*` são preexistentes e não foram tocados.

O test-report da r2 é PASS e explica a diferença de contagem em relação à r1. A cobertura dos CA-01 a CA-13 e do CA-19 continua a do adendo da r1, com os testes `docker` executados.

## Pontos positivos

- A correção do RV-05 é mínima e veio com uma varredura de marcadores nos três arquivos de aceite, comparada com a `origin/main`.
- O autor também conferiu os próprios testes procurando o mesmo defeito, sem mexer em código fora do papel dele.

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit de implementação ou de teste desta SPEC.
