# SPEC-039 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `c167a17` na primeira passada; `78f6ceb` (correção do SEC-39-01), com a branch em `9d31e4c`, na segunda (adendo no fim) |
| **Veredicto** | **PASS** (final, depois da correção do SEC-39-01; veja o adendo) |

Escrevi os testes de aceite a partir da SPEC (caixa-preta) e rodei-os antes de ler a implementação. Os testes `docker` foram **executados** (Docker Engine 29.9.2, Compose 5.6.1), e não só pulados.

## Cobertura dos critérios de aceite

Arquivo: `infra/tests/acceptance/test_spec_039.py`, com 36 testes: 21 itens de CA (com os parâmetros) e 15 extras/exploratórios.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_compose_structure` | ✅ |
| CA-02 | `test_ca02_compose_environment_and_secrets` | ✅ |
| CA-03 | `test_ca03_compose_hardening` | ✅ |
| CA-04 | `test_ca04_caddyfile` | ✅ |
| CA-05 | `test_ca05_caddy_dockerfile_and_dockerignore` | ✅ |
| CA-06 | `test_ca06_env_example` (reexecuta o CA-39 e o CA-05 da SPEC-015 sobre o `.env.example`) | ✅ |
| CA-07 | `test_ca07_deployment_plan` (reexecuta os CAs 25, 27, 38 e os dois do 41 da SPEC-015) | ✅ |
| CA-08 (docker) | `test_ca08_compose_config_resolves`, `test_ca08_compose_config_requires_each_mandatory_variable[PUBLIC_HOST/DATABASE_URL/READ_API_KEY]` | ✅ |
| CA-09 (docker) | `test_ca09_compose_config_in_the_coolify_invocation` | ✅ |
| CA-10 (docker) | `test_ca10_caddy_adapt` (imagem construída do `caddy.Dockerfile`, sem `PUBLIC_HOST`) | ✅ |
| CA-11 (docker) | `test_ca11_caddy_image_embeds_the_caddyfile` (`Cmd` comparado com a imagem do `FROM`, inspecionada no mesmo teste) | ✅ |
| CA-12 (docker) | `test_ca12_caddy_routes_on_a_private_network` | ✅ |
| CA-13 (docker) | `test_ca13_env_sentinels_stay_out_of_api_and_dashboard[api/dashboard]`, `test_ca13_env_sentinels_stay_out_of_the_caddy_image`, `test_ca13_ca36_of_spec_015_still_holds[api/dashboard]` | ✅ |
| CA-14 a CA-18 | manuais (humano, VPS, painel do Coolify e GitHub), depois do merge | não automatizados (fora do papel do tester) |

Para mostrar que os testes estáticos não são tautológicos, rodei-os contra os arquivos da `origin/main`, por um script fora do repositório que troca os caminhos. CA-01, CA-02, CA-04, CA-05 e CA-06 **falham** contra a `main`. O CA-03 e o CA-07 passam também na `main`, o que já era esperado: o CA-03 confere o endurecimento que se mantém, e o plano do CA-07 foi reescrito pelo architect no PR #55.

## Suíte completa

Por instrução do orquestrador, rodei **sem `TEST_DATABASE_URL` e sem `CI=true`**, para não usar o `partqc_test`, que outro agente pode estar usando. Os testes `db` foram pulados. Esta SPEC não toca a API nem o banco em código.

```text
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
5781 passed, 774 skipped, 1 warning in 429.80s
(skips: db sem TEST_DATABASE_URL, docker sem PARTQC_DOCKER_TESTS, torch ausente;
 warning: StarletteDeprecationWarning do fastapi.testclient, preexistente)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker
78 passed, 4 skipped, 6473 deselected in 167.18s
(os 4 skips são módulos do ml que pulam por falta do torch; nenhum teste docker pulado)

$ PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests/acceptance tests
48 passed, 764 deselected in 115.42s

$ uv run pytest -q infra/tests/acceptance        # sem docker
201 passed, 227 skipped

$ uv run ruff check .          -> All checks passed!
$ uv run ruff format --check . -> 239 files already formatted
```

Limpeza conferida no fim:

- nenhum contêiner `partqc-acc*`/`partqc-test*`, nenhuma imagem com a label `partqc.test=1` e nenhuma rede `partqc*`;
- nenhum volume novo (lista de volumes comparada antes e depois);
- o projeto compose `partqc-test-039-tester` só foi usado com `config`, que não cria recursos.

## Testes de aceite de SPECs anteriores ajustados (`docs/architecture.md` §10; SPEC-039 §3.1)

Fiz só os ajustes da tabela da §3.1. Nenhum `test_caNN_` foi removido nem renomeado, e nenhum teste de aceite antigo fora da tabela falhou.

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `test_spec_015.py` | `test_ca29_compose_structure` | `caddy.ports == ["80:80","443:443","443:443/udp"]` → `"ports" not in caddy` e `caddy.expose == ["80"]` (no mesmo laço da `api` e do `dashboard`) | §4.1 item 2 |
| `test_spec_015.py` | `test_ca29_compose_structure` | `_env_file_paths(env_file) == [(".env.<svc>", True)]` → `"env_file" not in` `api`/`dashboard` | §4.1 itens 6 e 7 |
| `test_spec_015.py` | `test_ca29_compose_structure` | `PUBLIC_HOST` no `environment` do `caddy` e alias `${PUBLIC_HOST:?}` na rede `partqc` → `"environment" not in caddy` e `"networks" not in caddy` | §4.1 itens 4 e 5 |
| `test_spec_015.py` | `test_ca29_compose_structure` | "nenhum `environment` tem `DATABASE_URL`/`READ_API_KEY`" → `DATABASE_URL` só na `api`, com valor exatamente `${DATABASE_URL:?}`, e `READ_API_KEY` sempre `${READ_API_KEY:?}`. A intenção (nenhum segredo literal no compose) continua. | §4.1 itens 6 a 8 |
| `test_spec_015.py` | `test_ca29_compose_structure` | `caddy.image` casa `caddy:2.x(@sha256)` → `"image" not in caddy` e `caddy.build == {context: "..", dockerfile: infra/docker/caddy.Dockerfile}` (o pino da versão passou para o Dockerfile, coberto pelo CA-05 da 039) | §4.1 item 5, §4.3 |
| `test_spec_015.py` | `test_ca29_compose_structure` | volumes `./Caddyfile`, `caddy_data` e `caddy_config` no `caddy` e no topo → `"volumes" not in caddy` e `"volumes" not in data` | §4.1 itens 5 e 9 |
| `test_spec_015.py` | `test_ca29_compose_structure` | rede `partqc` não interna e presente em todo serviço → sem `networks` no topo e em nenhum serviço. Proibições, limites, endurecimento, `restart` e `logging` continuam iguais. | §4.1 item 4 |
| `test_spec_015.py` | `test_extra_compose_network_is_bridge_and_no_extra_capabilities` | `networks.partqc.driver == "bridge"` → `"networks" not in data` (a rede padrão do projeto, bridge). A parte das capacidades continua. O nome não mudou, porque a rede padrão continua sendo bridge. | §4.1 item 4 |
| `test_spec_015.py` | `test_ca30_caddyfile` | `top_level == ["{$PUBLIC_HOST} {"]` → `top_level == [":80 {"]`. As demais condições continuam. | §4.2 |
| `test_spec_015.py` | fixture `compose_copy` | `infra/.env` (`PUBLIC_HOST`) + `infra/.env.api` + `infra/.env.dashboard` → um único `infra/.env` com `PUBLIC_HOST`, `DATABASE_URL` (fictícia, com marcadores) e `READ_API_KEY` (gerada) | §4.1 itens 6 e 7 |
| `test_spec_015.py` | `test_ca33_compose_config_resolves` | alias do `caddy` `== [TEST_HOST]` → sem alias (o `caddy` só na rede `default`) | §4.1 item 4 |
| `test_spec_015.py` | `test_ca33_compose_config_resolves` | caso sem `PUBLIC_HOST`: `infra/.env` só com `API_MEM_LIMIT` → o `infra/.env` sem a linha `PUBLIC_HOST` (com as outras obrigatórias), para o erro continuar sendo o do `PUBLIC_HOST` | §4.1 itens 6 e 7 |
| `test_spec_015.py` | `test_ca33_compose_config_resolves` | cópia sem `infra/.env.api` → código ≠ 0 passa a ser: `infra/.env` sem `DATABASE_URL` → código ≠ 0. A variável `api_env` e a restauração dela saíram. | §4.1 itens 6 e 7 (texto da §3.1) |
| `test_spec_015.py` | `test_extra_compose_single_quoted_dollar_is_literal` | arquivo editado: `infra/.env.api` → `infra/.env` (o `LOG_LEVEL` chega pelo `${LOG_LEVEL:-INFO}`). As asserções não mudaram. | §4.1 itens 6 e 7 |
| `test_spec_015.py` | `_caddy_image()` (usado pelo `test_ca34_caddy_adapt`) | `compose.services.caddy.image` → o `FROM` do `infra/docker/caddy.Dockerfile`, com o Caddyfile montado só para leitura, como antes (alternativa prevista na §3.1) | §4.3 |
| `test_spec_015.py` | `test_ca34_caddy_adapt` | `-e PUBLIC_HOST=partqc.example.org` removido; `hosts and set(hosts) == {TEST_HOST}` → `hosts == []` (sem `match.host`). Rotas, `dial` e HSTS continuam. | §4.2 |
| `test_spec_032.py` | `test_ca04_caddyfile_headers` | `top_level == ["{$PUBLIC_HOST} {"]` → `[":80 {"]` | §4.2 |
| `test_spec_032.py` | `_caddy_image()` (usado pelo `test_ca05_caddy_adapt_headers`, pelos 2 extras de header e pelos de execução) | `compose.services.caddy.image` → o `FROM` do `caddy.Dockerfile`, com o Caddyfile montado | §4.3 |
| `test_spec_032.py` | `test_ca05_caddy_adapt_headers`, `test_extra_caddy_adapt_single_header_handler_is_deferred` | `-e PUBLIC_HOST=...` removido. As asserções não mudaram. | §4.2 |
| `test_spec_032.py` | `test_extra_headers_through_reverse_proxy` | `-e PUBLIC_HOST=http://partqc.example.org` e `-v /data -v /config` removidos (o site `:80` já é HTTP, e os `tmpfs` do compose cobrem `/data` e `/config`); docstring ajustada. As asserções não mudaram. | §4.1 item 5, §4.2 |
| `test_spec_032.py` | `test_ca06_compose_hardening` | os itens de `tmpfs` podiam começar só com `/tmp` ou `/home/app` → também `/data` e `/config`, só no `caddy` e com `size=16m`. O limite ≤ 64m continua. | §4.1 item 5 |
| `test_spec_032.py` | `test_extra_compose_tmpfs_mount_points_are_exact` | destinos em `("/tmp", "/home/app")` → no `caddy`, `("/tmp", "/data", "/config")`; na `api` e no `dashboard`, como antes | §4.1 item 5 |
| `test_spec_032.py` | `test_extra_compose_keeps_caddy_volumes_writable` → **renomeado** `test_extra_compose_keeps_caddy_state_dirs_writable_in_tmpfs` | volumes `caddy_data`/`caddy_config`/`./Caddyfile` → `/data:size=16m` e `/config:size=16m` no `tmpfs` e `"volumes" not in caddy` (troca prevista na §3.1) | §4.1 item 5 |
| `test_spec_032.py` | `test_extra_caddy_with_compose_capabilities_writes_only_volumes` → **renomeado** `..._writes_only_tmpfs` | imagem: `caddy["image"]` → `_caddy_image()`. `-v /data -v /config` removidos, porque os `tmpfs` do compose cobrem. A mesma sonda continua: `/tmp`, `/data` e `/config` graváveis, `/etc` só leitura, `pids.max` 256. | §4.1 item 5, §4.3 |
| `test_spec_032.py` | fixture `compose_copy` | `infra/.env` + `.env.api` + `.env.dashboard` → um único `infra/.env` com as 3 variáveis | §4.1 |
| `test_spec_032.py` | `test_extra_compose_config_resolves_pids_and_override` | os overrides reescreviam o `infra/.env` só com `PUBLIC_HOST` + override → conteúdo base (as 3 obrigatórias) + override. Sem isso, o caso `API_PIDS_LIMIT=abc` falharia por falta de variável, e não pelo `abc`. | §4.1 |
| `test_spec_032.py` | `test_ca06_compose_config_quiet` | sem mudança no corpo; passa com a fixture nova | §4.1 |
| `test_spec_032.py` | `test_ca08_caddy_runs_read_only` | `caddy["image"]` → `_caddy_image()` (o `FROM` da §4.3, com o Caddyfile real montado, como antes); volumes temporários `-v /data -v /config` → os `tmpfs` de `/data` e `/config` do compose (`_tmpfs_args`) | §4.1 item 5, §4.3 |

Três itens da tabela da §3.1 **não precisaram de ajuste** e continuam passando com a intenção intacta:

- `test_ca39_env_example` e `test_extra_env_example_matches_compose_defaults` (SPEC-015): as linhas e os padrões das variáveis não mudaram;
- `test_extra_env_example_pids_variables_in_the_infra_block` (SPEC-032): o título novo continua começando com `# ----------` e contendo `infra/.env`, e os 3 `*_PIDS_LIMIT=256` estão no bloco.

Ficaram sem uso no `test_spec_015.py` o `PUBLIC_HOST_RE` e o `_env_file_paths`. Não os apaguei, para não mexer em linhas fora da tabela (o ruff não acusa nomes de módulo sem uso).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados em `test_spec_039.py` (todos passam):

| Teste | O que verifica |
|---|---|
| `test_extra_compose_text_has_no_literal_secret_or_env_file` | No texto cru do compose: sem `env_file`, `.env.api`, `.env.dashboard` ou `postgres`; toda ocorrência de `DATABASE_URL`/`READ_API_KEY` é `${NOME:?}` |
| `test_extra_compose_no_dangerous_keys_anywhere` | Fora dos comentários, o compose não tem `ports:`, `labels:`, `traefik`, `NET_ADMIN`, `SYS_ADMIN`, `extra_hosts` nem `docker.sock`, e o `caddy` não tem `healthcheck` |
| `test_extra_caddyfile_comments_and_format` | Comentários citam Coolify, ADR-023, SPEC-038 e `handle_errors`, e não há `handle_errors` ativo; indentação de `caddy fmt`; um único bloco `header`, no nível do site `:80` |
| `test_extra_caddy_dockerfile_has_no_forbidden_instruction` | Nada de `RUN`/`USER`/`ENV`/`ARG`/`EXPOSE`/`HEALTHCHECK`/`ENTRYPOINT`/`CMD`/`ADD`; `FROM` com digest |
| `test_extra_env_example_coolify_wording` | `Redeploy`, `API_BASE_URL` montada a partir de `PUBLIC_HOST`, `TELEGRAM_*` citado, a frase nova do bloco `qc-dashboard` e uma única linha `PUBLIC_HOST=` |
| `test_extra_plan_has_no_panel_url_uuid_or_webhook_url` | O plano não tem a rota de webhook do Coolify, nenhum UUID concreto nem `sslip.io`; o seletor `com.docker.compose.project=` só aparece com `<uuid>` ou `...` |
| `test_extra_plan_and_repo_reference_no_coolify_api_token_in_actions` | Nenhum workflow cita `coolify` ou `webhook` (ADR-023, decisão 5) |
| `test_extra_compose_config_quiet_with_limit_override_and_alerts` (docker) | `config --quiet` passa; o override de limite e de `pids_limit` vale; `ALERTS_ENABLED=true`, `TELEGRAM_*` e `LOG_LEVEL` chegam só à `api`, e o token não aparece no `dashboard` nem no `caddy`; `API_PIDS_LIMIT=abc` falha sem ecoar a chave |
| `test_extra_compose_single_quoted_dollar_in_a_secret_is_literal` (docker) | Uma `READ_API_KEY` com `$` entre aspas simples continua literal (é o motivo do "Literal" no Coolify) |
| `test_extra_coolify_invocation_fails_without_the_panel_variables` (docker) | Na forma do Coolify com `--env-file` vazio, o `config` falha e cita uma variável obrigatória: o `:?` bloqueia o deploy |
| `test_extra_caddy_adapt_has_no_automatic_https_and_no_redirect` (docker) | O JSON adaptado não tem `automatic_https`, `tls_connection_policies`, `https://` nem `static_response`, e tem um único `headers`, `deferred` |
| `test_extra_caddy_image_keeps_the_base_user_entrypoint_env_and_ports` (docker) | `User`, `Entrypoint`, `Env`, `ExposedPorts`, `WorkingDir` e `Volumes` iguais aos da imagem do `FROM`; nenhuma label `traefik.`/`coolify.` na imagem |
| `test_extra_caddy_context_admits_only_the_caddyfile` (docker) | Com foto, `.git/config`, `notas-locais/`, `.streamlit/secrets.toml` e `infra/.env.api` plantados no contexto, nenhum deles (nem o marcador) chega à imagem do Caddy (R-02, R-14) |
| `test_extra_caddy_blocks_api_docs_variants_and_accepts_any_host` (docker) | Através do Caddy, `/api/docs`, `/api/v1/docs`, `/api/openapi.json`, `/api/v1/openapi.json`, `/redoc`, `/api/redoc` e `/docs/oauth2-redirect` não servem Swagger, OpenAPI nem ReDoc. Um `Host` diferente também é roteado, o que é esperado pela SPEC §7: só o proxy do Coolify alcança o Caddy. |
| `test_extra_caddy_runs_stateless_under_compose_options` (docker) | Com as opções do compose: `.Mounts == []` (nenhum volume anônimo do `VOLUME` da imagem); `/data` e `/config` são `tmpfs` de 16m graváveis; `/etc` e `/etc/caddy` só leitura; `pids.max` 256; sem `read-only file system` |
| `test_extra_dockerignores_keep_the_env_rules` | `**/.env*` e a variante sem diferenciar maiúsculas continuam nos `.dockerignore` da API e do dashboard; o do Caddy começa com `*` |

Conferências manuais (sem teste novo):

- **Forma do Coolify com variáveis extras:** um `.env` com `SERVICE_FQDN_CADDY_80`, `COOLIFY_RESOURCE_UUID` e `COOLIFY_CONTAINER_NAME`, chamado com `--env-file infra/.env --project-name partqc-test-039-tester --project-directory infra` a partir da raiz da cópia, com caminhos relativos. O `config` resolve:
  - essas variáveis não entram no `environment` de nenhum serviço (a `api` só tem as 12 da §4.1, e o `dashboard` as 3);
  - não há `ports`, `volumes` nem volumes no topo;
  - a rede é só a `partqc-test-039-tester_default`;
  - o `build.context` é a raiz da cópia.

  Sem `--env-file`, com o `infra/.env` no `--project-directory`, o `config --quiet` também sai com 0.
- **`.gitignore`:** `git check-ignore` confirma que `infra/.env`, `infra/.ENV` e `.env` são ignorados (`.[eE][nN][vV]`).
- **Endurecimento:** CA-03 e CA-12, mais o extra de execução sem estado, confirmam `read_only`, `tmpfs`, `pids_limit`, `cap_drop`, `cap_add` só no Caddy e `no-new-privileges` (no compose e na execução real).
- **Segredos nos testes:** nenhum valor parecido com segredo aparece como literal. Chaves, senhas e marcadores são gerados com `secrets`, e a URL fictícia do banco é montada em f-string (`{user}:{password}`). O CA-05 da SPEC-015 (varredura de segredos nos arquivos rastreados) passa com o arquivo novo.
- **O-01 confirmado, e mais amplo do que o dev-report diz:** além do `infra/docker/api.Dockerfile` (linha 3) e do `.streamlit/config.toml` (linha 3), o `infra/docker/dashboard.Dockerfile` (linha 3) também ainda diz que a chave chega "pelo env_file do compose". É só comentário, fora do escopo da §3.1 (§3.2: Dockerfiles sem mudança). Fica para uma manutenção futura.
- **O-02 confirmado:** os comentários dos `.dockerignore` da API e do dashboard ainda citam `infra/.env.api` e `infra/.env.dashboard`. A regra `**/.env*` está correta, e a §4.6 exige não mexer nela.

## SPEC_ISSUE (se houver)

Nenhum. Todos os ajustes de aceites antigos decorrem da tabela da §3.1 e mantêm a intenção dos CAs antigos.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.

---

## Depois da correção do SEC-39-01

| Campo | Valor |
|---|---|
| Origem | SEC-39-01 (`r1-security-report.md`); SPEC corrigida pelo architect (`4239a2f`) e reaprovada pelo humano (`94282f5`) |
| Commit testado | `78f6ceb` (dois recursos: `infra/compose.api.yaml` e `infra/compose.yaml`), com a branch em `9d31e4c` |
| **Veredicto final** | **PASS** |

O que mudou desde a primeira passada:

- a SPEC divide o deploy em dois recursos do Coolify:
  - `partqc-api` (`infra/compose.api.yaml`), só com a `api`;
  - `partqc-web` (`infra/compose.yaml`), com o `caddy` e o `dashboard`;
- os dois ficam ligados pela rede `partqc-api-link` (`internal` no `partqc-api`, `external` no `partqc-web`);
- os `.dockerignore` da API e do dashboard ganham a linha `infra/` (SEC-39-02);
- o CA-13 passa a exigir `/app/infra` ausente, e entram o CA-19 (automatizado) e o CA-20 (manual).

Reescrevi os testes de aceite a partir da SPEC corrigida (§4.1, §4.1A, §4.6, §4.7, §4.8, CA-01 a CA-13 e CA-19) antes de ler a implementação nova, como na primeira passada.

### Cobertura dos critérios de aceite (SPEC corrigida)

Arquivo: `infra/tests/acceptance/test_spec_039.py`, com 46 testes (18 estáticos e 28 `docker`): 24 itens de CA (contando os parâmetros) e 22 exploratórios.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_compose_structure`: os dois arquivos, `name`, serviços, redes `link` (`internal`/`external`), `networks` da `api` e do `caddy`, `dashboard` sem `networks`, `caddy.depends_on == ["dashboard"]` | ✅ |
| CA-02 | `test_ca02_compose_environment_and_secrets`: inclui o texto do `compose.yaml` sem `DATABASE_URL`/`TELEGRAM_`/`ALERTS_`, o do `compose.api.yaml` sem `PUBLIC_HOST`/`MODEL_METRICS_PATH` e nenhum valor vazio | ✅ |
| CA-03 | `test_ca03_compose_hardening` (os 3 serviços, lidos dos dois arquivos) | ✅ |
| CA-04 | `test_ca04_caddyfile` | ✅ |
| CA-05 | `test_ca05_caddy_dockerfile_and_dockerignore` (`caddy:2.` ausente nos dois composes) | ✅ |
| CA-06 | `test_ca06_env_example` (com `partqc-api`, `partqc-web` e `compose.api.yaml`) | ✅ |
| CA-07 | `test_ca07_deployment_plan`: os itens novos (`/compose.api.yaml`, os dois recursos, `partqc-api-link`, `label=partqc.component`, `Config.Env`, `2FA`), a linha com `ARG` e `build` e a regra do `Connect to predefined network` | ✅ |
| CA-08 (docker) | `test_ca08_compose_config_resolves`, `test_ca08_compose_config_requires_each_mandatory_variable[4 pares]`, `test_ca08_web_compose_does_not_need_the_database_url` | ✅ |
| CA-09 (docker) | `test_ca09_compose_config_in_the_coolify_invocation` (`api.env` e `web.env` fora da cópia; projetos `partqc-api-coolify-test` e `partqc-web-coolify-test`) | ✅ |
| CA-10 (docker) | `test_ca10_caddy_adapt` | ✅ |
| CA-11 (docker) | `test_ca11_caddy_image_embeds_the_caddyfile` | ✅ |
| CA-12 (docker) | `test_ca12_caddy_routes_through_the_link_network` (renomeado; antes `..._on_a_private_network`, teste desta própria SPEC). A `api` fica só na `link` (`--internal`), o `dashboard` só na `web` e o Caddy nas duas; a sonda roda na `web`. A rede `web` também é `--internal`, mais restrito que o CA, para nenhum contêiner do teste ter saída. A fixture confere as redes de cada contêiner, `.Mounts == []` e `PortBindings` vazio. | ✅ |
| CA-13 (docker) | `test_ca13_env_sentinels_stay_out_of_api_and_dashboard[api/dashboard]` (agora com `test -e /app/infra` falhando), `test_ca13_env_sentinels_stay_out_of_the_caddy_image`, `test_ca13_ca36_of_spec_015_still_holds[api/dashboard]` | ✅ |
| CA-19 (docker) | `test_ca19_coolify_env_file_keeps_the_api_secrets_in_the_api_resource` e o controle negativo `test_ca19_negative_control_one_resource_would_leak` | ✅ |
| CA-14 a CA-18, CA-20 | manuais (humano), depois do merge | não automatizados |

**CA-19, como foi testado:**

- **Montagem:** duas cópias do repositório, uma por recurso.
  - Em cada uma, o arquivo do recurso é carregado, recebe `env_file: [".env"]` em todos os serviços e é gravado de novo **no mesmo caminho**.
  - O `infra/.env` tem exatamente os nomes que `\$\{([A-Z0-9_]+)` acha no arquivo original, com valores fictícios: a `DATABASE_URL` montada em tempo de execução, a `READ_API_KEY` e o `TELEGRAM_BOT_TOKEN` gerados, o `PUBLIC_HOST` e os padrões do arquivo nas demais.
- **Execução:** `config` na forma do Coolify (`--env-file <cópia>/infra/.env --project-name ... --project-directory <cópia>/infra -f <arquivo reescrito>`). A saída nunca é impressa, e as mensagens de asserção só citam nomes, nunca valores.
- **Resultado:**
  - nenhuma chave nem valor dos segredos da API no `caddy` ou no `dashboard`;
  - os dois valores estão na `api`;
  - o conjunto de nomes do `partqc-web` não tem `DATABASE_URL`, `TELEGRAM_*` nem `ALERTS_*`.
- **Controle negativo:** os três serviços num **único** recurso (o layout da primeira passada), com o mesmo `env_file` e o `.env` com as referências dos dois arquivos. A `DATABASE_URL` **aparece** no `caddy` e no `dashboard`, ou seja, a simulação reproduz o SEC-39-01 e o CA-19 não passa por vacuidade.

### Suíte completa (sem `TEST_DATABASE_URL` e sem `CI`, como antes)

```text
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
5791 passed, 787 skipped, 1 warning in 428.87s   (warning preexistente do fastapi.testclient)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker
91 passed, 4 skipped, 6483 deselected in 187.70s   (os 4 skips: módulos do ml sem torch)

$ PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests/acceptance tests
54 passed, 768 deselected

$ uv run pytest -q infra/tests/acceptance tests/acceptance      # sem docker
358 passed, 235 skipped

$ uv run ruff check .          -> All checks passed!
$ uv run ruff format --check . -> 239 files already formatted
```

Limpeza conferida no fim:

- nenhum contêiner `partqc-acc*`/`partqc-test*`, nenhuma imagem com a label `partqc.test=1` e nenhuma imagem dos projetos locais;
- nenhuma rede `partqc*`, inclusive a `partqc-api-link`, que o exploratório de subida local cria e remove (o teste confere a remoção);
- nenhum volume novo (lista comparada antes e depois).

### Ajustes adicionais em aceites antigos (última linha da tabela da §3.1)

Estes ajustes se somam aos da primeira passada (tabela acima). Nenhum `test_caNN_` foi removido nem renomeado, e a intenção de cada CA antigo continua verificada.

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `test_spec_015.py` | `test_ca29_compose_structure` | serviços lidos só de `compose.yaml` → `api` de `compose.api.yaml` (com `name: partqc-api`) e `caddy`/`dashboard` de `compose.yaml`; a contagem dos 3 serviços continua | §4.1 item 1, §4.1A |
| `test_spec_015.py` | `test_ca29_compose_structure` | `"networks" not in caddy` → `caddy.networks == ["default", "link"]` (lista, sem alias) | §4.1 item 4 |
| `test_spec_015.py` | `test_ca29_compose_structure` | `depends_on == {"api", "dashboard"}` → `{"dashboard"}`; a proibição de `service_healthy` continua | §4.1 item 5 |
| `test_spec_015.py` | `test_ca29_compose_structure` | sem `networks` no topo e nos serviços → `compose.yaml` com `{link: {name: partqc-api-link, external: true}}`, `compose.api.yaml` com `{link: {..., internal: true}}`, `api.networks == ["default", "link"]` e `dashboard` sem `networks`; `volumes` ausente também no topo do `compose.api.yaml` | §4.1 itens 4 e 9 |
| `test_spec_015.py` | `test_extra_compose_network_is_bridge_and_no_extra_capabilities` | sem `networks` no topo → a única rede é a `link`, bridge (sem `driver`) e `internal` no `compose.api.yaml`, `external` no `compose.yaml`; capacidades e volumes da `api` lidos de `compose.api.yaml`; `NET_ADMIN`/`SYS_ADMIN` procurados nos dois textos | §4.1 item 4, §4.1A |
| `test_spec_015.py` | `_compose_config` (CA-33 e o extra das aspas) | `config` só de `compose.yaml` → parâmetro `filename` (padrão `compose.yaml`) | §4.1 |
| `test_spec_015.py` | `test_ca33_compose_config_resolves` | `caddy` só na rede `default` → redes `{default, link}`, sem `aliases`; `mem_limit`/`cpus` da `api`, o override `API_MEM_LIMIT=768m` e o caso "sem `DATABASE_URL` → código ≠ 0" passam a usar o `config` de `compose.api.yaml`. O caso "sem `PUBLIC_HOST`" continua no `compose.yaml`. | §4.1, §4.1A |
| `test_spec_015.py` | `test_extra_compose_single_quoted_dollar_is_literal` | o `LOG_LEVEL` da `api` é lido do `config` de `compose.api.yaml`; as asserções não mudaram | §4.1A |
| `test_spec_032.py` | `_all_services()` (helper novo) | `api` de `compose.api.yaml` + `caddy`/`dashboard` de `compose.yaml` | §4.1, §4.1A |
| `test_spec_032.py` | `test_ca06_compose_hardening`, `test_extra_compose_tmpfs_mount_points_are_exact` | `_load_yaml(COMPOSE)["services"]` → `_all_services()`. Sem isso, o primeiro falharia (`set(services)`) e o segundo deixaria de conferir a `api` em silêncio. | §4.1 |
| `test_spec_032.py` | `_tmpfs_args` (usado pelo `test_ca07_api_runs_read_only`, pelo `test_extra_hardening_is_effective_inside[api]`, pelo `test_extra_headers_through_reverse_proxy` e pelos do Caddy) | `_load_yaml(COMPOSE)["services"][service]` (`KeyError: 'api'`) → `_all_services()[service]` | §4.1 |
| `test_spec_032.py` | `_compose` | só `compose.yaml` → parâmetro `filename` (padrão `compose.yaml`) | §4.1 |
| `test_spec_032.py` | `test_ca06_compose_config_quiet` | `config --quiet` de `compose.yaml` → dos dois arquivos | §4.1 (última linha da §3.1) |
| `test_spec_032.py` | `test_extra_compose_config_resolves_pids_and_override` | `config` de um arquivo → `_resolved_services` (helper novo, `config` dos dois arquivos); o caso `API_PIDS_LIMIT=abc` passa a usar `compose.api.yaml`, onde a variável é usada (antes ele falharia por um motivo trivial: a variável não existe no `compose.yaml`) | §4.1, §4.1A |

Nenhum outro teste de aceite antigo falhou. Conferi os 20 itens da lista do dev-report: os 9 das SPECs 015 e 032 estão na tabela acima, e os 11 da SPEC-039 são meus, reescritos para a SPEC corrigida.

### Bugs encontrados

Nenhum.

### Exploratórios novos ou atualizados (todos passam)

| Teste | O que verifica |
|---|---|
| `test_extra_referenced_variables_follow_the_split_of_section_4_1a` | Os nomes `${NOME` de cada arquivo (com os comentários, como o Coolify extrai) são exatamente os da tabela da §4.1A: 9 no `partqc-web` (`PUBLIC_HOST`, `READ_API_KEY`, `MODEL_METRICS_PATH`, os 6 limites `DASHBOARD_*`/`CADDY_*`) e 15 no `partqc-api` (as 12 do item 6 mais os 3 `API_*`) |
| `test_extra_no_empty_value_anywhere_in_the_compose_files` | Nenhum `NOME: ""` nem valor nulo em nenhum mapeamento dos dois arquivos (§4.1 item 8) |
| `test_extra_compose_text_has_no_literal_secret_or_env_file` | Nos dois arquivos: sem `env_file`, sem `.env.api`/`.env.dashboard`, sem `postgres`; toda ocorrência de `DATABASE_URL`/`READ_API_KEY` é `${NOME:?}`; `supabase` ausente do `compose.yaml` |
| `test_extra_compose_files_have_no_ipv4_or_real_host` | O `compose.api.yaml` (que o CA-41 da SPEC-015 não lista) também não tem IPv4 literal nem domínio fora de `example.org`/`example.com` |
| `test_extra_compose_no_dangerous_keys_anywhere` | Nos dois arquivos: sem `ports:`, `labels:`, `traefik`, `NET_ADMIN`, `SYS_ADMIN`, `extra_hosts` nem `docker.sock` |
| `test_extra_compose_config_quiet_with_limit_override_and_alerts` (docker) | `config --quiet` dos dois arquivos; override de limite e de alertas só na `api`; o token do bot não aparece no `partqc-web`; `API_PIDS_LIMIT=abc` falha sem ecoar a chave |
| `test_extra_compose_single_quoted_dollar_in_a_secret_is_literal` (docker) | `READ_API_KEY` com `$` entre aspas simples continua literal nos dois recursos |
| `test_extra_coolify_invocation_fails_without_the_panel_variables[2 arquivos]` (docker) | Na forma do Coolify, com `--env-file` vazio, cada recurso falha e cita uma variável obrigatória |
| `test_extra_api_is_reachable_only_through_the_link_network` (docker) | Na rede `web`, o nome `api` não é alcançável (só o Caddy, nas duas redes, chega à API); na rede `link`, é |
| `test_extra_local_up_of_both_projects_keeps_api_secrets_in_the_api` (docker) | Ensaio do CA-20 sem Coolify: `up -d --build` de `compose.api.yaml` e depois de `compose.yaml`, com projetos próprios (`partqc-test-039-tester-api` e `-web`) e um `infra/.env` com todas as variáveis, inclusive `TELEGRAM_BOT_TOKEN`. Resultados: <ul><li>o `Config.Env` do `dashboard` e do `caddy` não tem `DATABASE_URL`, `TELEGRAM_*` nem `ALERTS_*`, nem os valores fictícios, nem `supabase`;</li><li>a `api` tem `DATABASE_URL`, `READ_API_KEY` e os `TELEGRAM_*`, e não tem `PUBLIC_HOST` nem `MODEL_METRICS_PATH`;</li><li>a `partqc-api-link` tem `Internal = true` e contém a `api` e o `caddy`;</li><li>nenhum `PortBindings`.</li></ul>No fim, `down --rmi local` (web antes de api), e o teste confere que a rede sumiu. Se já existir uma `partqc-api-link` no host, o teste pula, para não mexer em recurso alheio; nesta execução ele rodou. |
| `test_extra_dockerignores_keep_the_env_rules` | Além do `**/.env*`: a linha `infra/` está nos `.dockerignore` da API e do dashboard, sem exceção `!infra`, e eles não excluem `pyproject.toml`, `uv.lock` nem `packages/` |

Os exploratórios de segurança da primeira passada continuam valendo e passando (mesmos testes):

- Caddy só em `:80`, sem TLS, sem `automatic_https`, com a 443 recusando conexão;
- `/docs` e variantes bloqueados, e os headers da SPEC-032 nas respostas reais;
- endurecimento efetivo (`read_only`, `tmpfs` de 16m, `pids.max` 256, `cap_drop`, `no-new-privileges`, nenhum volume anônimo);
- nenhum `.env` nem `/app/infra` nas imagens, e o contexto do Caddy só com o Caddyfile;
- nenhuma label `traefik.`/`coolify.`;
- padrões das variáveis de alerta iguais aos da SPEC-017, e elas só na `api`.

**Observação (sem bug):** localmente, o `dashboard` não entra na `partqc-api-link`, porque não declara `networks`. No Coolify, ele entra, porque o parser liga todas as redes do topo a todos os serviços. A SPEC (§4.1 item 4, §7) aceita essa diferença, e o CA-20, passo 4, espera 3 contêineres na rede. O ensaio local confere só `{api, caddy} ⊆ membros`. O-01 e O-02 da primeira passada continuam como estavam (só comentários).

### SPEC_ISSUE

Nenhum.

### Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
