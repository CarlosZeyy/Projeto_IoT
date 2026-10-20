# SPEC-015 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r2 |
| Autor | security-devops |
| Branch | `spec/SPEC-015-deploy-vps` |
| Commits | `44c8d87` (RV-01, RV-04), `0bc09a6` (RV-02), `25b36f7` (RV-03), `ec29293` (SEC-15-01 a 03 e o tamanho das imagens), mais o commit deste relatório |

## Resumo

A r1 passou em todos os portões. Esta r2 corrige, antes da primeira subida na VPS, os achados do `r1-review-report.md` (RV-01 a RV-04) e os três achados baixos do `r1-security-report.md` (SEC-15-01 a SEC-15-03). Os informativos SEC-15-04 e SEC-15-05 não foram aplicados (justificativa abaixo). O texto da SPEC não muda, e não há SPEC_ISSUE. Os CAs automatizados da r1 continuam valendo. O que muda para o tester está em "Testes a repetir".

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-review-report.md`, RV-01 (média): cache do `uv` dentro das imagens | `UV_CACHE_DIR=/root/.cache/uv` entrou no bloco `ENV` dos dois Dockerfiles, apontando o `uv` para o alvo do cache mount. Antes, com o `HOME=/home/app` definido antes do `uv sync`, o cache ia para `/home/app/.cache/uv`, dentro da camada. Corrigi também os comentários dos Dockerfiles, que eram falsos. Teste `docker` novo: `infra/tests/test_docker_images.py::test_uv_cache_is_not_in_the_image` (nas duas imagens, `/home/app/.cache` e `/root/.cache/uv` não existem). Tamanhos medidos de novo: a API passou de cerca de 240 MB para **205 MB** e o dashboard de 1,1 GB para **670 MB**. O `.venv` não mudou (42 MB e 518 MB), e o `/home/app` só tem os arquivos padrão do `useradd`. O `docs/deployment-plan.md` §2 foi atualizado. |
| RV-02 (baixa): o argparse do smoke repetia argumento desconhecido | `scripts/smoke_test.py` usa um `NoEchoArgumentParser` no padrão do `scripts/simulate.py` (`parse_known_args`, contagem dos extras, `error()` com `redact_usage_error`). Uma mensagem já redigida não é contada de novo. Testes: `infra/tests/test_smoke_script.py::test_unknown_argument_is_never_echoed` (`--api-key=<valor>`, `--api-key <valor>` e um posicional, os três gerados com `secrets`: código 2, valor ausente da saída, `(not shown)` presente e 0 requisições) e `::test_redaction_keeps_the_count_and_hides_quoted_values`. |
| RV-03 (baixa): porta comparada como texto, `except Exception` | `infra/migrate.py`: `TRANSACTION_POOLER_PORT = 6543` (int), e `_is_transaction_pooler_port` compara `int(port) == 6543`, com `ValueError` tratado como "não é 6543". O `_effective_ports` captura só `psycopg.ProgrammingError`, o erro do `conninfo_to_dict`, conferido no psycopg instalado. Testes: `infra/tests/test_migrate_production.py::test_other_spellings_of_6543_are_refused` (`:06543`, `port=+6543`, `port=' 06543'` e `PGPORT=06543`, nas duas funções, com 0 conexões no listener) e `::test_a_non_numeric_port_is_not_mistaken_for_6543`. |
| RV-04 (baixa): `.dockerignore` diferencia maiúsculas | Nos dois `.dockerignore`, ao lado de cada padrão obrigatório (mantido literalmente), entrou uma variante com classes de caracteres: `**/.[eE][nN][vV]*`, `**/*.[jJ][pP][gG]`, `[jJ][pP][eE][gG]`, `[pP][nN][gG]`, `[hH][eE][iI][cC]`, `[wW][eE][bB][pP]`, `[oO][nN][nN][xX]`, `[pP][tT]`, `[pP][tT][hH]`, `[nN][pP][zZ]`, `[sS][qQ][lL][iI][tT][eE]`, `...3`, `[dD][bB]`, `[pP][eE][mM]` e `[kK][eE][yY]`. As exceções vêm depois das exclusões: `!.env.example` e `!ml/reports/**/*.png`, mais a nova `!ml/reports/**/*.[pP][nN][gG]`. Testes: `test_deploy_files.py::test_dockerignore_rules` (variantes e ordem das exceções) e sentinelas novas no `test_docker_images.py` (`infra/.ENV.API`, `FOTO.JPG`, `IMG_0001.HEIC`, `Foto.Png`, `edge/data/OUTBOX.SQLITE3` e `MODEL.ONNX` ausentes das duas imagens; `ml/reports/.../GRADE_CONFUSION.PNG` presente no dashboard). A lacuna de maiúsculas do `.gitignore` é anterior a esta SPEC e continua como pendência do architect, como o reviewer registrou. |
| `r1-security-report.md`, SEC-15-01 (baixa): saídas com o subdomínio ou o IP | `docs/deployment-plan.md` §9 ganhou a lista das saídas que trazem o host ou o IP e a instrução de trocá-los por `<subdominio>` e `<IP>` antes de colar. A lista cobre: `%{redirect_url}` do CA-13, `openssl s_client` sem o filtro, `printenv API_BASE_URL` e `wss://` do CA-17, `dig`, os `curl` do CA-40, `logs caddy`, logs da API e o erro de conexão da §8. Também diz o que pode ser colado sem edição (o smoke, o `--status` e as consultas SQL). A regra de logs da §4 passou a valer também para o Caddy. |
| SEC-15-02 (baixa): o CA-42 podia dar falso "nenhuma linha" | Comando novo na §9: lê o valor com `sed -n 's/^PUBLIC_HOST[=]//p'` (o `[=]` mantém o CA-41: `PUBLIC_HOST=` só aparece seguido de `<subdominio>`). Depois tira aspas, espaços e `\r` com `tr`, lê o IPv4 com `read -r -p` (fora do histórico do shell) e só roda o `git grep -nF` com valor não vazio (um padrão vazio casaria tudo). Conferi o comando num repositório descartável, com `infra/.env` entre aspas simples, espaço e CRLF no fim: ele achou o host. A linha do CA-42 na tabela aponta para esse comando. |
| SEC-15-03 (baixa): `DATABASE_URL` de produção no `.env.prod` | §8, item 5: a conferência do `statement_timeout` usa um `.env.dbcheck` próprio e temporário (coberto por `.env.*`), com `chmod 600` e `rm .env.dbcheck` logo depois. A `DATABASE_URL` não entra mais no `.env.prod`. Se a conexão falhar, a mensagem não é colada sem edição. |
| SEC-15-04 (informativo): headers `server`/`via`, sem `Referrer-Policy`/`frame-ancestors` | **Não aplicado.** O próprio relatório diz "Nenhuma nesta SPEC". Os headers novos precisariam ser testados contra o WebSocket do Streamlit, e a §4.13 define a lista de headers. Fica para uma SPEC futura de endurecimento. |
| SEC-15-05 (informativo): sem `read_only` nem `pids_limit` | **Não aplicado.** O `read_only` exige mapear onde o Streamlit e o Python escrevem (`tmpfs`), o que não é trivial. Um `pids_limit` é uma linha, mas um valor mal dimensionado derruba o dashboard sob carga (threads por sessão do Streamlit) e não seria medido nesta rodada. A §4.12 não pede nenhum dos dois, e o relatório os deixa como candidatos para uma SPEC futura. |
| SEC-15-06 (informativo): actions fixadas por tag | Sem ação (o próprio relatório: "Nenhuma"). |

## Rastreabilidade (critério de aceite → implementação)

Sem mudança em relação à r1 (`r1-dev-report.md`). As correções desta rodada ficam dentro de CAs existentes:

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-08 a CA-12 (§4.5: "nenhuma chave é impressa") | `scripts/smoke_test.py` | `test_smoke_script.py::test_unknown_argument_is_never_echoed`, `::test_redaction_keeps_the_count_and_hides_quoted_values` |
| CA-20 (§4.7, item 1) | `infra/migrate.py` | `test_migrate_production.py::test_other_spellings_of_6543_are_refused`, `::test_a_non_numeric_port_is_not_mistaken_for_6543` |
| CA-28, CA-35 a CA-37 (§4.10) | `infra/docker/*.Dockerfile` | `test_docker_images.py::test_uv_cache_is_not_in_the_image` |
| CA-36 (§4.11, exclusões extras permitidas) | `infra/docker/*.Dockerfile.dockerignore` | `test_deploy_files.py::test_dockerignore_rules`; sentinelas novas em `test_docker_images.py::test_build_context_filters_secrets_data_and_weights` |
| CA-25, CA-27, CA-38, CA-41 (texto do plano) | `docs/deployment-plan.md` | `test_deploy_files.py::test_plan_accepted_risks`, `::test_plan_operation_rules`, `::test_public_urls_are_placeholders` (passam com o texto novo) |

## Como rodar e verificar

```bash
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true \
  TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -m docker -q
```

### Verificado localmente (2026-10-19)

- `ruff check` e `ruff format --check`: limpos (220 arquivos).
- Suíte inteira com `CI=true` e o banco de teste: **5022 passed, 50 skipped** (os 28 testes `docker` como skip).
- `pytest -m docker` com `PARTQC_DOCKER_TESTS=1` (e `PARTQC_DOCKER_BUILD_NETWORK=host`, por causa da rede bridge quebrada desta máquina): **28 passed**, sendo 14 do tester e 14 do autor. Repeti na árvore já commitada, e as imagens de teste foram removidas pela fixture.
- Tamanhos de imagem: medidos num build a partir de uma cópia da árvore rastreada (`docker image inspect`). As imagens e a cópia foram removidas em seguida.
- O comando do CA-42 foi conferido num repositório descartável com valores fictícios (domínio `example.org` e IP de documentação), já apagado.

### Só o CI verifica

O workflow `docker` com a rede bridge padrão do runner. Os testes `docker` novos rodam lá também.

## Testes a repetir (para o tester)

O texto da SPEC não mudou. O que mudou foram as imagens (Dockerfiles e `.dockerignore`), o `scripts/smoke_test.py`, o `infra/migrate.py` (só a recusa da porta) e o `docs/deployment-plan.md`. Basta repetir os testes `docker` (CA-33 a CA-37), os do smoke (CA-08 a CA-12), o CA-20, o CA-36 e os de texto do plano (CA-25, CA-27, CA-38 e CA-41). Rodei a suíte de aceite do tester sem alteração, e ela passa.

## Decisões tomadas dentro do escopo da SPEC

- **RV-01:** escolhi `UV_CACHE_DIR`, em vez de mover o `HOME` para depois do `uv sync`. Assim, o `HOME` do usuário `app` continua definido em todos os passos, e o alvo do cache mount fica explícito ao lado dele. O nome não fere o CA-28.
- **RV-04:** mantive os padrões obrigatórios literais da §4.11 (o CA-36 e os testes do tester procuram cada um deles) e acrescentei as variantes com classes de caracteres. Não usei só as variantes, que também cobririam as minúsculas, para não mexer na leitura literal dos CAs.
- **RV-02:** o `redact_usage_error` do smoke é uma cópia reduzida do `scripts/simulate.py` (mesma regex de valor entre aspas). Não importei o simulador, porque o smoke é carregado como script independente (§6 da SPEC) e importá-lo traria o gerador inteiro.
- **SEC-15-02:** o `[=]` no `sed` é só para o texto do plano cumprir o CA-41. No `sed`, ele casa o mesmo `=`.

## SPEC_ISSUE (se houver)

Nenhum.

## Passos humanos e CAs manuais

Sem mudança em relação à r1: todos pendentes, conforme o `docs/deployment-plan.md` §4, §8 e §9. Mudaram só as instruções do CA-42 e da conferência do `statement_timeout` (§8, item 5) e o aviso sobre as saídas a editar antes de colar (§9).

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte completa com `CI=true`; `-m docker` com `PARTQC_DOCKER_TESTS=1`)
- [x] `.env.example` sem variável nova (sem mudança nesta rodada)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum segredo, subdomínio real ou IP em arquivo versionado. As credenciais fictícias dos testes são montadas em tempo de execução, e as chaves são geradas com `secrets`.
- [x] Apaguei só o que criei (imagens de medição, cópia de contexto e repositório descartável do CA-42); nenhum contêiner de outro projeto foi tocado
