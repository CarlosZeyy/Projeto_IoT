# SPEC-039 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r2 |
| Autor | security-devops (o portão de segurança desta SPEC é do **reviewer**, `reviews/README.md`) |
| Branch | `spec/SPEC-039-manutencao-deploy-coolify` |
| Commits | só o commit deste relatório (nenhuma mudança de produção nem de teste do autor) |

## Resumo

O CHANGES_REQUESTED da r1 vem só do RV-05, que está num arquivo de aceite (`infra/tests/acceptance/test_spec_032.py`). A correção é do tester (R-07). Conferi os achados RV-02 a RV-06 contra os arquivos de produção e os meus testes de autor, e nenhum deles exige mudança da minha parte nesta rodada.

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| r1-review-report, RV-05 (bloqueante) | Nada da minha parte. O marcador `docker` perdido está num teste de aceite da SPEC-032, e quem corrige é o tester. Varri os meus testes de autor procurando o mesmo defeito, ou seja, um `@docker` ou `@pytest.mark.docker` em cima de um helper. Não achei nenhum caso em `test_coolify_deploy.py`, `test_docker_images.py` e `test_deploy_files.py`. `uv run pytest --collect-only -q -m docker` nos dois arquivos com testes docker coleta 37 testes, os mesmos 37 executados com `PARTQC_DOCKER_TESTS=1` no adendo da r1. Nenhum teste que chama Docker fica fora do marcador |
| RV-06 (baixa) | Nada. É texto da SPEC e do `docs/architecture.md`, que são do architect e do orquestrador, e o próprio relatório o encaminha para o commit de `Done` |
| RV-02 (baixa) | Nada nesta rodada. Os comentários desatualizados ficam nos Dockerfiles da API e do dashboard, que a §3.2 deixa fora do escopo, e no `.streamlit/config.toml`, que não está na §3.1. Mexer neles seria sair do escopo aprovado. Fica para a Parte B da SPEC-038, como o próprio relatório sugere |
| RV-03 (baixa) | Nada. O plano segue a interface conferida na página oficial (General > Build pipeline). Alinhar a frase do CA-15 é texto da SPEC, a cargo do architect, e o relatório diz que não precisa de rodada nova |
| RV-04 (baixa) | Nada. Os nomes sem uso estão em `test_spec_015.py`, que é arquivo de aceite do tester |

## Como rodar e verificar

```bash
uv run pytest infra/tests/test_coolify_deploy.py infra/tests/test_docker_images.py --collect-only -q -m docker   # 37 testes
uv run pytest infra/tests --ignore=infra/tests/acceptance -q                                                     # 249 passed, 149 skipped (sem banco)
```

## SPEC_ISSUE

Nenhum.

## Checagens do autor

- [x] Nenhum arquivo de produção nem teste do autor mudou nesta rodada
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
