# SPEC-039 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r1 |
| Autor | security-devops (o portão de segurança desta SPEC é do **reviewer**, `reviews/README.md`) |
| Branch | `spec/SPEC-039-manutencao-deploy-coolify` |
| Commits | `c167a17` (implementação e testes do autor), mais o commit deste relatório |

## Resumo

O `infra/compose.yaml` passou a seguir o ADR-023:

- nenhum serviço publica portas (só `expose`);
- não há labels do proxy, rede própria, alias, volumes nem `env_file`;
- as variáveis vêm do recurso no Coolify pelo `environment` da `api` e do `dashboard`, exatamente como nas listas da §4.1. Os segredos usam `${NOME:?}`, e as 8 variáveis da SPEC-017 são opcionais, com os alertas desligados.

O Caddy escuta só em `:80`, sem TLS e sem healthcheck. Ele roda a partir de uma imagem nova (`infra/docker/caddy.Dockerfile`) que embute o Caddyfile, e o contexto de build só admite esse arquivo. Em `/data` e `/config`, usa `tmpfs` no lugar dos volumes.

O `.env.example` e o `docs/deployment-plan.md` descrevem as variáveis do recurso. No plano, conferi os comandos, corrigi o grupo da interface de duas opções (veja as decisões) e atualizei o estado e as fontes. Os testes do autor das SPECs 015 e 032 foram ajustados, e um arquivo novo cobre os CAs 01 a 13. Todos os testes `docker` foram executados e passaram. Não há SPEC_ISSUE.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `infra/compose.yaml` | `infra/tests/test_coolify_deploy.py::test_compose_has_no_ports_networks_labels_or_volumes`, `::test_compose_caddy_is_built_stateless_and_without_healthcheck`; `infra/tests/test_deploy_files.py::test_compose_structure` (reescrito: `name`, serviços, sem `ports`/`networks`/`env_file`/`labels`/`container_name`/`image`, `expose` 80/8000/8501, `build` dos três, topo só com `name` e `services`, `depends_on` em lista) |
| CA-02 | `infra/compose.yaml` | `test_coolify_deploy.py::test_compose_environment_is_exactly_the_spec` (dicionários exatos dos itens 6 e 7, regex de todos os valores, `DATABASE_URL` só na `api`, `caddy` sem `environment`) |
| CA-03 | `infra/compose.yaml` | `test_deploy_files.py::test_compose_structure` (restart, `no-new-privileges`, logging, `mem_limit`/`cpus`, `cap_drop`, só o `caddy` com `cap_add`) e `::test_compose_hardening_spec_032` (`read_only`, `pids_limit`, `tmpfs` exatos: `api`/`dashboard` `/tmp:size=64m`, `caddy` com `/data` e `/config` `size=16m`) |
| CA-04 | `infra/Caddyfile` | `test_coolify_deploy.py::test_caddyfile_single_site_on_port_80`, `::test_caddyfile_forbidden_token` (16 tokens, inclusive `handle_errors`, que entra pela SPEC-038), `::test_caddyfile_routes_headers_and_no_literal_host`, `::test_caddyfile_comments_name_coolify_and_spec_038`; `test_deploy_files.py::test_caddyfile_routes_and_headers` (primeira linha `:80 {`) e `::test_caddyfile_header_block_spec_032` |
| CA-05 | `infra/docker/caddy.Dockerfile`, `infra/docker/caddy.Dockerfile.dockerignore` | `test_coolify_deploy.py::test_caddy_dockerfile_instructions`, `::test_caddy_dockerignore_admits_only_the_caddyfile`, `::test_compose_has_no_caddy_version_and_no_domain`; `test_deploy_files.py::test_caddy_version_is_pinned_only_in_its_dockerfile` (substitui o teste da tag no compose) |
| CA-06 | `.env.example` | `test_coolify_deploy.py::test_env_example_coolify_block`, `::test_env_example_no_longer_names_the_vps_env_files`; `test_deploy_files.py::test_env_example_vps_block` (título novo) e `::test_env_example_compose_values_match_the_compose_defaults` |
| CA-07 | `docs/deployment-plan.md` | `test_coolify_deploy.py::test_plan_names_the_coolify_interface`, `::test_plan_line_rules` (`Webhook secret`, `secrets.*WEBHOOK`, `coolify-proxy`, `Raw`), `::test_plan_has_no_webhook_url_nor_panel_host`; `test_deploy_files.py::test_plan_*` e os CAs 25/27/38/41 da SPEC-015 continuam passando |
| CA-08 (docker) | `infra/compose.yaml` | `test_coolify_deploy.py::test_compose_config_resolves_every_variable` (URL fictícia montada no teste, chave gerada, padrões, 8 variáveis de alerta só na `api`, sem `ports`, 512 MiB), `::test_compose_config_fails_without_a_mandatory_variable` (3 casos: código ≠ 0, nome no stderr, sem a chave e a senha na saída); `test_docker_images.py::test_compose_resolves_host_and_limits`, `::test_compose_requires_each_mandatory_variable`, `::test_compose_config_quiet_with_the_hardening` |
| CA-09 (docker) | `infra/compose.yaml` | `test_coolify_deploy.py::test_compose_config_in_the_coolify_invocation` (`--env-file` fora da cópia, `--project-name partqc-coolify-test`, `--project-directory <cópia>/infra`, sem `infra/.env`: `name`, `build.context` absoluto igual à raiz da cópia nos 3 serviços, `dockerfile`, `API_BASE_URL`) |
| CA-10 (docker) | `infra/Caddyfile`, `infra/docker/caddy.Dockerfile` | `test_coolify_deploy.py::test_caddy_image_adapts_without_public_host` (sem aviso de formatação, 1 servidor `[":80"]`, sem app `tls`, sem `match.host`, 2 `reverse_proxy` com as rotas certas, `headers` com 4 `set` e `delete` de `Server`/`Via`); `test_docker_images.py::test_caddy_adapts_the_caddyfile` e `::test_caddy_header_block_strips_server_and_via_behind_the_proxy` (agora com a imagem construída) |
| CA-11 (docker) | `infra/docker/caddy.Dockerfile` | `test_coolify_deploy.py::test_caddy_image_embeds_the_caddyfile_and_keeps_the_base_command` (bytes iguais ao `infra/Caddyfile`, label, sem `Healthcheck`, `Cmd`, `Entrypoint` e `User` iguais aos da imagem do `FROM`) |
| CA-12 (docker) | `infra/compose.yaml`, `infra/Caddyfile` | `test_coolify_deploy.py::test_caddy_routes_on_a_private_network` (rede própria do teste, aliases `api`/`dashboard`/`caddy`, Caddy com `--read-only`, os 3 `tmpfs`, `--cap-drop ALL`, `--cap-add NET_BIND_SERVICE`, `no-new-privileges`, `--pids-limit 256`, sem `-p` e sem volume; sonda HTTP/1.1 com `Host: partqc.example.org` de outro contêiner: health 200/503 com `status`, `/_stcore/health` 200 `ok`, os 4 headers, sem `server`/`via`, `/docs` sem `swagger`, `/openapi.json` sem `"openapi"`, `caddy:443` recusado, sem `read-only file system`, `running`); `test_docker_images.py::test_caddy_runs_read_only` (os 3 `tmpfs`, `.Mounts` vazio: nenhum volume anônimo do `VOLUME` da imagem) |
| CA-13 (docker) | `.dockerignore` dos 3 Dockerfiles | `test_coolify_deploy.py::test_env_sentinels_stay_out_of_every_image` (sentinelas `infra/.env` e `.env` com `DATABASE_URL=<marcador gerado>`; `api`/`dashboard`: os dois `test -e` falham e `grep -rl` vazio; Caddy: `find / -xdev -name '.env*'` vazio e sem `/app`), `::test_api_and_dashboard_dockerignore_keep_the_env_rules`; o CA-36 da SPEC-015 continua passando |
| CA-14 a CA-18 (manuais) | `docs/deployment-plan.md` §4 e §9 | Passos humanos (lista abaixo) |

## Testes de aceite antigos afetados (para o tester, `docs/architecture.md` §10)

Rodei as suítes de aceite com e sem `PARTQC_DOCKER_TESTS=1`. As 17 falhas abaixo estão todas na tabela da §3.1 da SPEC, e nenhum outro teste de aceite antigo falhou. Quem ajusta é o tester. Eu não toquei em `acceptance/`.

| Arquivo | Teste | Falha observada |
|---|---|---|
| `infra/tests/acceptance/test_spec_015.py` | `test_ca29_compose_structure` | `ports`, `image`, volumes e rede do `caddy`, `env_file` |
| `infra/tests/acceptance/test_spec_015.py` | `test_extra_compose_network_is_bridge_and_no_extra_capabilities` | rede `partqc` ausente |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca30_caddyfile` | endereço `{$PUBLIC_HOST}` → `:80` |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca33_compose_config_resolves` (docker) | fixture `compose_copy` com `.env.api`/`.env.dashboard` e alias |
| `infra/tests/acceptance/test_spec_015.py` | `test_extra_compose_single_quoted_dollar_is_literal` (docker) | mesma fixture |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca34_caddy_adapt` (docker) | `KeyError` na imagem do compose; `match.host` |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca04_caddyfile_headers` | endereço `:80` |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca06_compose_hardening` | `tmpfs` do `caddy` com `/data` e `/config` |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_compose_tmpfs_mount_points_are_exact` | idem |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_compose_keeps_caddy_volumes_writable` | volumes `caddy_data`/`caddy_config` saíram |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca05_caddy_adapt_headers` (docker) | origem da imagem do Caddy, `PUBLIC_HOST` |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_caddy_adapt_single_header_handler_is_deferred` (docker) | idem |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_headers_through_reverse_proxy` (docker) | idem |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca06_compose_config_quiet` (docker) | fixture `compose_copy` (variáveis num único `infra/.env`) |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_compose_config_resolves_pids_and_override` (docker) | idem |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca08_caddy_runs_read_only` (docker) | imagem e volumes temporários → `tmpfs` |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_caddy_with_compose_capabilities_writes_only_volumes` (docker) | volumes que saíram |

Três itens da tabela da SPEC **continuam passando** sem ajuste, porque o que eles conferem não mudou de forma que os quebre: `test_ca39_env_example`, `test_extra_env_example_matches_compose_defaults` (SPEC-015) e `test_extra_env_example_pids_variables_in_the_infra_block` (SPEC-032). O tester confere se a intenção deles ainda vale com o título novo do bloco.

## CAs manuais (humano; só depois do merge)

Na ordem do `docs/deployment-plan.md` §4. Os resultados vão na §9 do plano e num dev-report de registro, com `<subdominio>`, `<IP>` e `<uuid>` no lugar dos valores reais.

1. **CA-14:** a versão do Coolify (rodapé ou Settings) na tabela "Conferência da VPS" do plano §2. Depois, `docker ps --filter name=coolify-proxy ...` (imagem `traefik`, portas 80/443) e o `StartedAt` do proxy, anotado fora do repositório.
2. **CA-15:**
   - criar o recurso: Public Repository, branch `main`, Docker Compose, Base Directory `/infra`, Docker Compose Location `/compose.yaml`;
   - deixar desligados o modo Raw, "Connect to predefined network" e "Preserve repository during deployment";
   - domínio só no `caddy`: `https://<subdominio>:80`;
   - o primeiro deploy é pelo botão, com o log lido sem colar segredos. No fim, 3 contêineres sem portas publicadas.
3. **CA-16:** `docker inspect` dos 3 contêineres (limites, `read_only`, `tmpfs`, capacidades, `no-new-privileges`, `PortBindings` vazio, `unless-stopped`).
4. **CA-17:**
   - `DATABASE_URL` e `READ_API_KEY` só em runtime, Locked e Literal;
   - `docker history` sem os nomes;
   - `.env*` fora de `/app`;
   - modo e dono do `.env` do Coolify no plano §7, item 7.
5. **CA-18:**
   - webhook do passo 7A e um merge de teste, com a entrega `push` 2xx;
   - a branch do PR não dispara deploy;
   - o deploy termina com sucesso, e o smoke dá 8 × `PASS`;
   - o log não mostra segredos;
   - registrar o SHA curto e a data, sem a URL do webhook.
6. Depois deles, os CAs manuais da SPEC-015 (CA-13 a CA-19, CA-26, CA-40, CA-42 e CA-43) e o CA-09 da SPEC-032, com a equivalência da §4.7, já transcrita no plano.

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest infra/tests --ignore=infra/tests/acceptance -q          # 243 passed, 142 skipped (sem banco)
PARTQC_DOCKER_TESTS=1 uv run pytest infra/tests/test_coolify_deploy.py infra/tests/test_docker_images.py -m docker -q   # 30 passed
```

Resultados desta rodada, em 2026-10-25, com o Docker Engine 29.9.2 e o Compose 5.6.1, sem `TEST_DATABASE_URL` e sem `CI`:

- testes do autor em `infra/tests` (fora de `acceptance/`): 243 passed, 142 skipped (banco e docker);
- os mesmos, marcados `docker`: 30 passed;
- suíte inteira sem `infra/tests/acceptance`: 5580 passed, 547 skipped;
- `infra/tests/acceptance` e `tests/`: 7 falhas sem docker e 10 com docker, todas na tabela acima.

Limpeza: as imagens `partqc-test-*` são removidas pelo `build_image` no fim da sessão, e o teste de rede remove os contêineres e a rede dele no `finally`. Depois das execuções, não sobrou nenhum contêiner, rede ou imagem `partqc-test-*`, e nenhum volume foi criado (o `tmpfs` em `/data` e `/config` evita os volumes anônimos do `VOLUME` da imagem oficial).

`caddy fmt --diff` com a imagem fixada não mostrou nenhuma diferença no `infra/Caddyfile`.

## Decisões tomadas dentro do escopo da SPEC

- **Plano, §4, passo 4:** a página oficial do build pack Docker Compose (conferida em 2026-10-25) põe **Base Directory**, **Docker Compose Location** e **Preserve repository during deployment** em General > Build pipeline. O modo Raw fica em Advanced > Docker compose > Compose deployment, e **Connect to predefined network** em Advanced > Docker compose > Predefined network. O texto do architect punha o "Preserve repository" em Advanced. Corrigi o caminho, sem mudar a instrução (desligado).
- **Plano, §2, linha "Coolify":** o humano ainda não informou a versão instalada, e quem a registra é o CA-14, passo 1. Deixei a coluna como "a completar pelo humano no CA-14". Como referência, anotei a última versão publicada no GitHub (`v4.5.0`, marcada "Latest", de 23/10), com a página de releases como fonte. A página do build pack Docker Compose entrou como fonte, e conferi de novo a dos webhooks manuais (mínimo de 16 caracteres, nomes da interface).
- **Plano, passo 5:** acrescentei que as variáveis `ALERTS_*`/`TELEGRAM_*` ficam com os padrões até a SPEC-017 e que o `TELEGRAM_BOT_TOKEN`, quando preenchido, fica só em runtime, Locked e Literal (§4.1, item 6). As instruções de como ligar os alertas ficam para a 017 (§3.2).
- **Plano, cabeçalho:** o aviso de estado agora diz ADR-023 `Aceito` e SPEC-039 em desenvolvimento, e ganhou uma linha no histórico do arquivo.
- **Testes do autor:**
  - em `test_docker_images.py`, `_compose_copy` passou a gravar um único `infra/.env`, com uma `DATABASE_URL` fictícia montada em tempo de execução e uma chave gerada. Os testes do Caddy usam a imagem construída do `caddy.Dockerfile` (fixture `caddy_image`, por `build_image`);
  - `test_compose_requires_the_api_env_file` virou `test_compose_requires_each_mandatory_variable`, com 3 casos;
  - `test_compose_caddy_version_matches_nothing_floating` virou `test_caddy_version_is_pinned_only_in_its_dockerfile`.
- **Teste de rede (CA-12):** os contêineres da `api` e do `dashboard` usam imagens construídas sem arquivos extras (`build_image(dockerfile)`). A sonda roda num contêiner da imagem da API, com `http.client`, que manda HTTP/1.1 com o `Host` explícito.

## Observações (fora do escopo; nenhuma bloqueia)

- **O-01:** o comentário de cabeçalho do `infra/docker/api.Dockerfile` ainda diz que os segredos chegam "pelo env_file do compose". O `.streamlit/config.toml` (linha 3) ainda cita o `infra/.env.dashboard (VPS)`. Os dois arquivos estão fora do escopo da §3.1 (Dockerfiles sem mudança, §3.2), e o texto é só comentário, sem efeito. Fica como sugestão de uma linha numa manutenção futura, por exemplo na SPEC-038.
- **O-02:** os comentários dos `.dockerignore` da API e do dashboard ainda listam `infra/.env.api` e `infra/.env.dashboard` entre os exemplos cobertos. Continuam corretos, porque o padrão `**/.env*` os cobre, e a §4.6 exige não mexer nessas linhas.

## SPEC_ISSUE

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando, inclusive os 30 marcados `docker`, executados
- [x] `.env.example` atualizado (nenhuma variável nova; bloco e comentários da §4.4)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum valor real de subdomínio, IP, UUID, URL do painel ou segredo no repositório; nenhum domínio novo nos arquivos de `infra/`
