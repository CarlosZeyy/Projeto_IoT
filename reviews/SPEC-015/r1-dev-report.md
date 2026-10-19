# SPEC-015 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r1 |
| Autor | security-devops |
| Branch | `spec/SPEC-015-deploy-vps` |
| Commits | `0ab6e9e` (executor de migrações, §4.7), `be25095` (deploy na VPS, workflows, smoke, docs), `b067b85` (credencial fictícia na forma da allowlist), mais o commit deste relatório |

## Resumo

Implementei a publicação na VPS pessoal do ADR-018: as imagens da `qc-api` e do `qc-dashboard` (base Python e `uv` fixados por tag e digest, usuário `10001`, `HEALTHCHECK`, sem ML), um `.dockerignore` por Dockerfile, o `infra/compose.yaml` (só o Caddy publica portas, com limites e endurecimento por serviço), o `infra/Caddyfile`, o `infra/render.yaml` como reserva fria, os workflows `keepalive` e `docker`, o marcador `docker` com o `infra/tests/docker_support.py` e os hooks do `infra/tests/conftest.py`, o `scripts/smoke_test.py`, o `.streamlit/config.toml` e o bloco da VPS no `.env.example`. No `infra/migrate.py`, entraram os ajustes da §4.7: recusa da porta 6543, prazo do lock, detecção de controle de transação no arquivo, regex só com dígitos ASCII e leitura única. O `docs/deployment-plan.md` traz os passos humanos com os comandos exatos, os riscos aceitos, o procedimento do `statement_timeout` e a tabela dos CAs manuais.

Nenhum agente tem acesso à VPS, ao Supabase, ao DNS nem às contas. Por isso, **todos os CAs manuais estão pendentes** (ver "Passos humanos" abaixo).

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `infra/render.yaml` | `infra/tests/test_deploy_files.py::test_render_blueprint_is_the_free_cold_standby`, `::test_render_python_version_matches_the_image_base` |
| CA-02 | `.github/workflows/keepalive.yml` | `test_deploy_files.py::test_keepalive_workflow` |
| CA-05 | todos os arquivos novos (sem segredo); `infra/tests/test_cli.py` (literal da allowlist) | `test_deploy_files.py::test_no_secret_material_in_tracked_files` (escopo do autor: fora de `docs/`, `reviews/` e das suítes de teste; ver SPEC_ISSUE-01) |
| CA-06 | `.gitignore` (sem mudança: `.env` e `.env.*` já cobrem) | `test_deploy_files.py::test_gitignore_covers_the_vps_env_files` |
| CA-07 | `.streamlit/config.toml` | `test_deploy_files.py::test_streamlit_config` |
| CA-08 a CA-12 | `scripts/smoke_test.py` | `infra/tests/test_smoke_script.py` (23 testes: 8 `PASS` na ordem, `source=simulated`, falhas de cada checagem, código 2 sem requisição, nenhuma chave nem `host-secreto-15` na saída, inclusive com `ConnectError`, e sem `verify=False`) |
| CA-20 | `infra/migrate.py` (`ensure_supported_connection`, `UnsupportedConnectionError`, `main`) | `infra/tests/test_migrate_production.py::test_functions_refuse_port_6543_before_connecting`, `::test_cli_refuses_port_6543_with_exit_2` (listener TCP com 0 conexões; URL com 6543, multi-host, `key=value` e `PGPORT`) |
| CA-21 | `infra/migrate.py` (`_acquire_lock`, `lock_wait_s`) | `test_migrate_production.py::test_lock_deadline`, `::test_lock_is_taken_when_released_within_the_deadline`, `::test_lock_wait_must_be_positive`, `::test_lock_wait_is_keyword_only` |
| CA-22 | `infra/migrate.py` (`_apply_one`) | `test_migrate_production.py::test_transaction_control_in_the_file_is_detected` (`commit;`, `commit; begin;` e `rollback;`) |
| CA-23 | `infra/migrate.py` (`FILENAME_PATTERN`) | `test_migrate_production.py::test_non_ascii_digits_are_an_invalid_name`; `test_migration_files.py::test_filename_pattern_is_the_spec_regex` (atualizado) |
| CA-24 | `infra/migrate.py` (`Migration.content`, `load_migrations`) | `test_migrate_production.py::test_each_file_is_read_once`, `::test_checksum_recorded_is_the_sha256_of_the_single_read` |
| CA-25, CA-27, CA-38 | `docs/deployment-plan.md` (§3, §4, §7, §8) | `test_deploy_files.py::test_plan_accepted_risks`, `::test_plan_operation_rules` |
| CA-28 | `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` | `test_deploy_files.py::test_dockerfile_rules`, `::test_both_dockerfiles_use_the_same_uv_and_base` |
| CA-29 | `infra/compose.yaml` | `test_deploy_files.py::test_compose_structure` |
| CA-30 | `infra/Caddyfile` | `test_deploy_files.py::test_caddyfile_routes_and_headers` |
| CA-31 | `.github/workflows/docker.yml` | `test_deploy_files.py::test_docker_workflow` |
| CA-32 | `pyproject.toml`, `infra/tests/docker_support.py`, `infra/tests/conftest.py` | `infra/tests/test_docker_support.py` (marcador, `docker_tests_enabled`, `check_docker`, `copy_tracked_tree`, hook de skip e `UsageError`) |
| CA-33 (docker) | `infra/compose.yaml` | `infra/tests/test_docker_images.py::test_compose_resolves_host_and_limits`, `::test_compose_limit_override`, `::test_compose_requires_public_host`, `::test_compose_requires_the_api_env_file` |
| CA-34 (docker) | `infra/Caddyfile` | `test_docker_images.py::test_caddy_adapts_the_caddyfile` |
| CA-35 (docker) | Dockerfiles | `test_docker_images.py::test_image_has_no_ml_and_only_its_package` |
| CA-36 (docker) | `infra/docker/*.Dockerfile.dockerignore` | `test_docker_images.py::test_build_context_filters_secrets_data_and_weights` |
| CA-37 (docker) | Dockerfiles | `test_docker_images.py::test_image_config`, `::test_dashboard_repo_root_is_app` |
| CA-39 | `.env.example` | `test_deploy_files.py::test_env_example_vps_block`, `::test_env_example_compose_values_match_the_compose_defaults` |
| CA-41 | arquivos de `infra/`, workflows, `.env.example`, `docs/deployment-plan.md` | `test_deploy_files.py::test_no_ipv4_literal`, `::test_public_urls_are_placeholders` |
| CA-13 a CA-19, CA-26, CA-40, CA-42, CA-43 (manuais) | passos em `docs/deployment-plan.md` §4, §8 e §9 | — (passo humano; pendentes) |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q

# Testes `docker` (como no workflow `docker`). Nesta máquina, a rede bridge do Docker está
# quebrada (kernel atualizado sem reboot): o build precisa de PARTQC_DOCKER_BUILD_NETWORK=host.
PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true \
  TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -m docker -q
```

### Verificado localmente (2026-10-19)

- `uv run ruff check .` e `uv run ruff format --check .`: limpos.
- Suíte inteira com `CI=true` e o banco de teste: 4882 passed, 34 skipped (os 12 testes `docker` aparecem como skip sem a variável, como no `ci.yml`).
- `pytest -m docker` com `PARTQC_DOCKER_TESTS=1`: **12 passed** (as duas imagens construídas a partir de uma cópia da árvore rastreada, com sentinelas; contêineres com `--network none`; `docker compose config` numa cópia temporária; `caddy adapt` na imagem fixada do compose). As imagens de teste foram removidas no fim da sessão.
- Imagens: API com cerca de 240 MB e dashboard com cerca de 1,1 GB. Nenhuma tem torch, torchvision, timm, onnx ou onnxruntime; a do dashboard não tem `psycopg`, e a da API não tem `streamlit`. Python 3.12, `User 10001:10001`, `WorkingDir /app`, `REPO_ROOT=/app` no dashboard.
- **Contêineres de verdade, com `--network host`** (sem bridge nesta máquina), contra um banco temporário migrado no Postgres local e já removido. A API e o dashboard ouviram em `127.0.0.1`, com `--cap-drop ALL`, `no-new-privileges` e os limites de memória:
  - os dois ficaram `healthy` pelo `HEALTHCHECK` da imagem;
  - `scripts/smoke_test.py` com `http://127.0.0.1:8000` e `http://127.0.0.1:8501` deu as 8 checagens:

    ```text
    PASS health
    PASS write_requires_key
    PASS write
    PASS read_requires_key
    PASS read
    PASS cors_closed
    PASS dashboard
    PASS dashboard_health
    ```

- **Caddy com o `infra/Caddyfile` real** e o endurecimento do compose (`--cap-drop ALL --cap-add NET_BIND_SERVICE`, `no-new-privileges`, `--memory 256m`), com `PUBLIC_HOST=localhost` (certificado da CA interna do Caddy, só neste teste local) e `--add-host api/dashboard:127.0.0.1`. O Caddy subiu e abriu 80 e 443 sem outra capacidade, o que responde ao risco de capacidades da §7. Resultados:
  - `GET /api/v1/health` → 200 (`db: ok`);
  - `http://` → `308` para `https://localhost/api/v1/health`;
  - `strict-transport-security: max-age=31536000` e `x-content-type-options: nosniff`;
  - `/api/v1/inspections` sem chave → 401;
  - `/docs` → 0 ocorrências de `swagger`, e `/openapi.json` → 0 de `"openapi"`;
  - upgrade de WebSocket em `/_stcore/stream` → `101`;
  - `/` → 200 e `/_stcore/health` → `ok`.
- `caddy fmt --diff` sem diferenças; `caddy adapt` sem aviso.
- `docker compose -f <cópia>/infra/compose.yaml config`, com `infra/.env`, `infra/.env.api` e `infra/.env.dashboard` fictícios:
  - `API_BASE_URL=https://partqc.example.org` e alias `partqc.example.org`;
  - `mem_limit` de 512 MiB (API), 1 GiB (dashboard) e 256 MiB (Caddy);
  - sem `PUBLIC_HOST` → código 1 e a mensagem `set PUBLIC_HOST in infra/.env`;
  - sem `infra/.env.api` → código 1;
  - um valor entre aspas simples com `$` ficou literal.
- A detecção de `COMMIT` no arquivo de migração foi conferida num banco temporário, já removido: `002` com `commit;` deixa `t_tx` criada (já confirmada, como a mensagem avisa) e `schema_migrations` só com `001`.

### Só o CI verifica

- O workflow `docker` em `ubuntu-latest`, com a rede bridge padrão do runner, roda o build sem `PARTQC_DOCKER_BUILD_NETWORK`. Localmente, o build só passou com `--network host`, por causa do problema do kernel desta máquina.
- O `ci.yml` (sem mudança) com os testes `docker` como skip.

### Não foi possível localmente, e por quê

- **Subir o `infra/compose.yaml` inteiro** (rede bridge `partqc`, alias do subdomínio, resolução `api:8000`/`dashboard:8501` pelo DNS do Docker): a rede bridge falha nesta máquina (`veth ... operation not supported`), e não reiniciei a máquina nem mexi na configuração global do Docker. O que cobre esse caso:
  - os testes `docker` do CI, para o `config`;
  - a validação acima com `--network host`, que mostrou rotas, cabeçalhos e capacidades;
  - na VPS, os CAs manuais CA-13, CA-17, CA-40 e CA-43. O alias do subdomínio dentro da rede (o dashboard chamando `https://<subdominio>` sem sair da VPS) só é provado pelo CA-17.

## Passos humanos e CAs manuais (todos pendentes)

Os comandos exatos estão no `docs/deployment-plan.md`. A tabela da §9 de lá recebe os resultados, sem o subdomínio real nem o IP.

1. **Supabase** (§4, passo 1): anotar a região do projeto; conferir o `search_path`; migrar com `.env.migrate` pelo modo session; conferir RLS, grants e restrições da `002` (CA-14, CA-19).
2. **VPS** (passo 2): preencher a tabela "Conferência da VPS" da §2 (versões, RAM, CPUs e disco) e salvar o `ufw status` antes.
3. **DNS** (passo 3): registro `A` de `<subdominio>`.
4. **Checkout e arquivos de ambiente** (passos 4 a 6): os três arquivos com `chmod 600` e o `config --quiet`.
5. **Subida** (passo 7): `up -d --build`, `ps`, certificado e o `find` do CA-43, passo 1.
6. **Dispositivos, borda e keep-alive** (passos 8 a 10): o secret `KEEPALIVE_URL` e o `workflow_dispatch` (CA-16).
7. **Smoke e simulador** (passo 11, CA-15).
8. **`statement_timeout`** (§8, item 1; CA-26).
9. **CA-13, CA-17, CA-18, CA-40, CA-42 e CA-43**, na ordem da §9. O CA-18 inclui a confirmação escrita do humano de que a VPS é preexistente e não mudou de plano.
10. **Região da reserva no Render:** se o projeto Supabase não estiver em `sa-east-1` nem em `us-east-1`, trocar `region` no `infra/render.yaml` por PR antes de ativar a reserva.

## Decisões tomadas dentro do escopo da SPEC

- **Versões e fontes conferidas em 2026-10-19:**
  - `python:3.12.15-slim-trixie` (<https://hub.docker.com/_/python>);
  - `ghcr.io/astral-sh/uv:0.13.2`, a versão do exemplo oficial (<https://docs.astral.sh/uv/guides/integration/docker/>);
  - `caddy:2.11.7` (<https://hub.docker.com/_/caddy>).

  As três estão fixadas também pelo **digest do índice multi-arquitetura**, que serve tanto para amd64 quanto para arm64 na VPS. O `PYTHON_VERSION` do Render é `3.12.15`, e a Render aceita versão completa (<https://render.com/docs/python-version>).
- **Sem a diretiva `# syntax=`** nos Dockerfiles. Ela baixaria um frontend `docker/dockerfile:1` não fixado. O `RUN --mount=type=cache` funciona com o frontend embutido do BuildKit.
- **Cache do `uv` num cache mount** (`--mount=type=cache,target=/root/.cache/uv`): o cache fica fora das camadas da imagem, e as atualizações na VPS não baixam tudo de novo.
- **Exclusões a mais no `.dockerignore`**, além das obrigatórias:
  - `.github`, `**/secrets.toml`, `**/*.pem` e `**/*.key`;
  - `**/*.onnx`, `**/*.pt`, `**/*.pth`, `**/*.npz` e `ml/notebooks/`;
  - caches, `docs/`, `reviews/` e `**/tests`.

  Nenhuma exclusão proibida pela §4.11 foi usada, e as exceções vêm depois da exclusão que abrem.
- **`showErrorDetails = "none"`**: a versão travada no `uv.lock` é a do Streamlit **1.65.0**, e o enum `ShowErrorDetailsConfigOptions` do pacote instalado aceita `full`, `stacktrace`, `type` e `none`. Escolhi o mais restritivo.
- **Região `virginia` no `render.yaml`:** a região do projeto Supabase não está registrada no repositório. Para um projeto em São Paulo ou em `us-east-1`, a região mais próxima entre as do blueprint (`oregon`, `ohio`, `virginia`, `frankfurt` e `singapore`) é `virginia`. Registrei a escolha, a fonte e a pendência na §2 do `deployment-plan.md`.
- **`keepalive.yml`:** o `curl` roda com `-o /dev/null` e com o stderr descartado, e o passo imprime só o código de saída. Assim, uma falha de DNS ou de conexão não leva o nome do host ao log **público** do Actions (R-13). O GitHub só mascara o valor inteiro do secret, e não o host dentro dele.
- **`scripts/smoke_test.py`:**
  - exige também `SIM_DEVICE_ID` (com a regex do contrato), porque o `device_id` da inspeção precisa ser o dono da chave;
  - roda as 8 checagens mesmo depois de uma falha, e `read` falha com `no inspection written` se `write` falhou;
  - as chamadas à API não seguem redirecionamento, e as do dashboard seguem;
  - a URL `https://` também é recusada com usuário e senha, query ou fragmento;
  - erros de uso saem com código 2 (inclusive opção inválida do argparse), sem repetir valores.
- **`infra/migrate.py`:**
  - `ensure_supported_connection` é pública e também é chamada por `_status`;
  - numa lista de vários hosts, um item de porta vazio usa o `PGPORT`;
  - `lock_wait_s` NaN é recusado (`not lock_wait_s > 0`);
  - a mensagem do lock é `could not acquire the migration lock within 30 s (another migration run may be in progress); nothing was applied`;
  - `Migration.content` tem `repr=False`, para o SQL não aparecer em `repr`.
- **`docker_support.py`, além das assinaturas da SPEC:**
  - `docker_build`, `docker_run_args` (sempre `--network none`), `remove_images` e `tracked_files`;
  - `PARTQC_DOCKER_BUILD_NETWORK`, opcional e só de teste (`default`, `host` ou `none`), é a saída local para a rede bridge quebrada; o CI não o define;
  - o padrão de `extra_files` é um `MappingProxyType({})` imutável (o `{}` literal da SPEC seria o B006 do ruff);
  - `copy_tracked_tree` recusa um destino dentro da árvore real e caminhos extras absolutos ou com `..`;
  - o `conftest.py` carrega o módulo com `spec_from_file_location` sob o nome `partqc_docker_support`, que fica em `sys.modules` para os testes do autor e do tester;
  - as imagens de teste recebem o rótulo `partqc.test=1`.
- **`.env.example`:** o comentário `KEEPALIVE_URL` continua logo abaixo do cabeçalho `# ---------- Segredos fora do .env (GitHub Secrets) ----------`. Li "a última linha, que fica ..." da §4.12 como a troca do texto desse cabeçalho, que antes era seguido do mesmo comentário. Se a intenção era que o cabeçalho fosse literalmente a última linha do arquivo, é uma troca de uma linha.
- **`docs/deployment-plan.md`:**
  - ganhou a §8 ("Operação do banco e das chaves", §4.9 da SPEC) e a §9 (registro dos CAs manuais);
  - as duas consultas do `EXPLAIN ANALYZE` foram geradas a partir de `qc_api.repositories.inspections` com os parâmetros padrão das rotas;
  - o smoke usa um `.env.prod` local, coberto pelo padrão `.env.*`;
  - o comando do CA-42 aparece com `grep '^PUBLIC_HOST'`, sem `=`, para não ferir a regra do CA-41.
- **`infra/tests/test_cli.py`** (teste do autor da SPEC-003): as duas f-strings com `u:{SECRET}@` viraram o literal `postgresql://u:s3cr3t-pw@127.0.0.1:1/x`, que está na allowlist do CA-05. O comportamento testado é o mesmo.

## SPEC_ISSUE (se houver)

- **SPEC_ISSUE-01 (CA-05, allowlist incompleta; não bloqueia a implementação, mas bloqueia o aceite literal do tester).** Tomado ao pé da letra, o CA-05 busca os padrões em todos os arquivos de `git ls-files` fora de `docs/`, e a lista de permissão tem só `<user>:<password>`, `postgres:postgres@localhost`, `u:pw@127.0.0.1` e `u:s3cr3t-pw@127.0.0.1`. Hoje o padrão `postgres(ql)?://[^\s:/@]+:[^\s@]+@` casa, sem estar na lista, em arquivos que este papel não pode editar. Nenhum é segredo:
  - `infra/tests/acceptance/test_spec_003.py:640, 1008, 1010, 1023`: f-strings do tester com o esquema `postgresql://` seguido de `u:{SECRET}@127.0.0.1`;
  - `reviews/SPEC-009/r1-review-report.md:46` e `reviews/SPEC-022/r1-review-report.md:29`: o esquema `postgres://` seguido de `…:…@`;
  - `reviews/SPEC-022/r1-review-report.md:22`: o esquema `postgresql://` seguido de `postgres:<senha>@`, e uma ocorrência de `postgres:postgres@` sem `localhost` logo depois;
  - `reviews/checklist.md:42`: o esquema `postgresql://` seguido de `u:senha@…`.

  Os arquivos deste papel já não casam (ver `test_cli.py` acima). Correção sugerida ao architect: incluir na lista os marcadores com reticências (`…:…@`, `u:senha@…`, `postgres:<senha>@`) e a f-string `u:{SECRET}@127.0.0.1`, ou tirar `reviews/` do escopo do CA-05. Pelo ADR-019, a correção toca um CA que verifica a R-03 (X-7), então **exige o humano**.
- Nota para o tester, sem SPEC_ISSUE: no JSON do `caddy adapt` (CA-34), cada `reverse_proxy` fica dentro de um `subroute`, e o `match` com `path: ["/api/*"]` está na rota pai desse `subroute`. "Cuja rota tem `match`" precisa ser lido como a rota que contém o handler, em qualquer nível. O teste `test_caddy_adapts_the_caddyfile` só confere os `dial` e os hosts.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte completa com `CI=true` e o banco de teste; `-m docker` com `PARTQC_DOCKER_TESTS=1`)
- [x] `.env.example` atualizado (bloco `infra/.env`, `CLOUD_API_URL`, `DASHBOARD_URL` e cabeçalhos)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum segredo, subdomínio real ou IP em arquivo versionado; os `.env` de teste ficaram em diretórios temporários e foram apagados
- [x] Nenhum `.dockerignore` na raiz, nenhuma mudança no `ci.yml`, nenhum `dashboard/requirements.txt`
