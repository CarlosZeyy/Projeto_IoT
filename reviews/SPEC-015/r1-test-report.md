# SPEC-015 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r1 (depois da retomada do SPEC_ISSUE-01) |
| Tester | tester |
| Commit testado | `8739737` (implementação até `aa4af32`, relatório do autor em `1efb04b`) |
| **Veredicto** | **PASS** (CAs automatizados); CAs manuais pendentes do humano |

Os testes foram escritos a partir da SPEC (caixa-preta) antes da leitura da implementação. Arquivo: `infra/tests/acceptance/test_spec_015.py` (82 funções, **132 itens**: 118 sem Docker e 14 marcados `docker`), mais a sonda `infra/tests/acceptance/ca32_docker_marker_probe.py`, que a suíte não coleta (o nome não casa `test_*.py`) e que dois testes extras rodam num subprocesso, por caminho explícito, para verificar os hooks do marcador `docker` (§4.14). Nenhum teste roda a suíte inteira em subprocesso.

Marcadores: módulo `acceptance`; CA-21 a CA-24 (e os extras do executor) `db`; CA-33 a CA-37 (e os extras de imagem) `docker`. Nenhuma credencial, chave ou IPv4 literal no arquivo: o loopback, a senha fictícia e os exemplos de segredo são montados em tempo de execução, e as chaves vêm de `secrets.token_urlsafe` (§6, §7). A varredura do próprio CA-05 e o CA-10 da SPEC-022 passam com o arquivo incluído.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite (`infra/tests/acceptance/test_spec_015.py::`) | Resultado |
|---|---|---|
| CA-01 | `test_ca01_render_blueprint` | ✅ |
| CA-02 | `test_ca02_keepalive_workflow` | ✅ |
| CA-03, CA-04 | removidos da SPEC (2026-10-18) | n/a |
| CA-05 | `test_ca05_no_secret_material_outside_docs`, `test_ca05_scope_includes_reviews_and_acceptance_suites`, `test_ca05_env_example_secrets_are_blank_or_markers` | ✅ |
| CA-06 | `test_ca06_gitignore_ignores` (7 caminhos), `test_ca06_gitignore_keeps` (2) | ✅ |
| CA-07 | `test_ca07_streamlit_config` | ✅ |
| CA-08 | `test_ca08_all_checks_pass_in_order` | ✅ |
| CA-09 | `test_ca09_open_endpoint_fails[read\|write]` | ✅ |
| CA-10 | `test_ca10_broken_service_fails` (6 casos: `ACAO *`, `db=error` com 503 e com 200, `contract_version` diferente, corpo `nope`, 502) | ✅ |
| CA-11 | `test_ca11_invalid_input_exits_2_without_requests` (3 casos) | ✅ |
| CA-12 | `test_ca12_no_key_or_host_in_output` (sucesso, falhas por status, `db=error`, `ConnectError` e `ReadTimeout` com a URL na mensagem da exceção), `test_ca12_source_has_no_verify_false` | ✅ |
| CA-13 a CA-19 | manuais | ⏳ pendente do humano |
| CA-20 | `test_ca20_cli_refuses_port_6543[apply\|status]`, `test_ca20_cli_spec_literal_multi_host`, `test_ca20_functions_raise_before_connecting` (listeners TCP reais na 6543 e na porta do primeiro host: 0 conexões) | ✅ |
| CA-21 | `test_ca21_lock_deadline`, `test_ca21_lock_wait_must_be_positive` (0, -1, -0,5, NaN) | ✅ |
| CA-22 | `test_ca22_transaction_control_in_file` (`commit;`, `commit; begin;` e, como extras, `rollback;` e `rollback; begin;`) | ✅ |
| CA-23 | `test_ca23_non_ascii_digits_are_an_invalid_name` | ✅ |
| CA-24 | `test_ca24_each_file_read_once` | ✅ |
| CA-25 | `test_ca25_accepted_risks_and_register_device` | ✅ |
| CA-26 | manual | ⏳ pendente do humano |
| CA-27 | `test_ca27_statement_timeout_keys_render_and_simulator` | ✅ |
| CA-28 | `test_ca28_dockerfile_rules[api\|dashboard]`, `test_ca28_same_uv_version_in_both` | ✅ |
| CA-29 | `test_ca29_compose_structure` | ✅ |
| CA-30 | `test_ca30_caddyfile` | ✅ |
| CA-31 | `test_ca31_docker_workflow` | ✅ |
| CA-32 | `test_ca32_marker_declared`, `test_ca32_docker_tests_enabled`, `test_ca32_check_docker`, `test_ca32_copy_tracked_tree` | ✅ |
| CA-33 (docker) | `test_ca33_compose_config_resolves` | ✅ executado |
| CA-34 (docker) | `test_ca34_caddy_adapt` | ✅ executado |
| CA-35 (docker) | `test_ca35_images_without_ml[api\|dashboard]` | ✅ executado |
| CA-36 (docker) | `test_ca36_build_context_filters_sentinels[api\|dashboard]` | ✅ executado |
| CA-37 (docker) | `test_ca37_image_config[api\|dashboard]`, `test_ca37_dashboard_repo_root_is_app` | ✅ executado |
| CA-38 | `test_ca38_operation_rules` | ✅ |
| CA-39 | `test_ca39_env_example` | ✅ |
| CA-40 | manual | ⏳ pendente do humano |
| CA-41 | `test_ca41_no_ipv4_literal_in_deploy_files`, `test_ca41_public_urls_are_placeholders` | ✅ |
| CA-42, CA-43 | manuais | ⏳ pendente do humano |

**CAs manuais pendentes do humano** (nenhum agente tem acesso à VPS, ao Supabase, ao DNS nem às contas; não contam como falha desta rodada, mas a Definição de pronto §8 exige registrá-los): CA-13, CA-14, CA-15, CA-16, CA-17, CA-18, CA-19, CA-26, CA-40, CA-42 e CA-43. A exploração local abaixo antecipa parte do CA-13 (itens 2, 3, 4 e 6), do CA-15, do CA-17 (WebSocket 101) e do CA-43 (item 1, `find /app -name '.env*'`), mas não os substitui: o certificado público, o alias do subdomínio na rede bridge, o firewall e a coexistência com os outros projetos só existem na VPS.

### Leituras adotadas (sem SPEC_ISSUE: nenhuma muda a intenção do CA)

- **CA-05, cláusula do `.env.example`** ("só têm valor vazio ou marcadores `<...>`"): a linha `DATABASE_URL=postgresql://<user>:<password>@<host>:6543/postgres` existe desde a fundação e a cláusula não mudou com o SPEC_ISSUE-01. Li "marcadores" (no plural) como um valor em que usuário, senha e host são todos marcadores `<...>`. Qualquer outro valor não vazio só passa se for um único marcador.
- **CA-25:** "uma linha contém `pool` e `503`, outra contém `psycopg.pool`": exigi duas linhas distintas.
- **CA-34**, "cuja rota tem `match` com `path == ["/api/*"]`": no JSON do `caddy adapt`, cada `handle` vira um `subroute`, e o `match` fica na rota pai. O teste percorre a cadeia de rotas até o handler: a do `api:8000` tem `path == ["/api/*"]` num ancestral, e nenhuma rota da cadeia do `dashboard:8501` tem matcher de `path`. Também confere que só existem os dois `dial`, que todo `match.host` é `partqc.example.org` e o header HSTS.
- **CA-38:** a linha do Koyeb na tabela da §2 diz `**Não usado**`; a comparação com "não usado" ignora a caixa.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
220 files already formatted

$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5013 passed, 48 skipped, 1 warning in 315.69s (0:05:15)
  - os 48 skips: 26 testes `docker` (12 do autor e 14 deste arquivo, motivo "set PARTQC_DOCKER_TESTS=1 to run",
    como no job do ci.yml) e 22 preexistentes (torch ausente e o CA-16 manual da SPEC-008)
  - o aviso é o StarletteDeprecationWarning preexistente do fastapi.testclient

$ PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true TEST_DATABASE_URL=... \
    uv run pytest infra/tests/acceptance/test_spec_015.py -m docker -v
14 passed, 118 deselected in 79.79s

$ PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true TEST_DATABASE_URL=... uv run pytest -m docker -q
26 passed, 3 skipped, 5032 deselected, 1 warning in 10.63s
  - o mesmo comando do workflow `docker` (12 do autor + 14 deste arquivo; os 3 skips são os módulos de ML sem torch,
    pulados na coleta)
```

### Testes `docker`

- **Executados localmente:** os 14 deste arquivo (CA-33 a CA-37 e 4 extras), com `PARTQC_DOCKER_TESTS=1` e `PARTQC_DOCKER_BUILD_NETWORK=host`. A rede bridge do Docker não funciona nesta máquina sem reboot; o build usa `--network host` só nos `RUN`, e todo contêiner de teste roda com `--network none`.
- **Só o CI prova:** o build com a rede padrão (bridge) do runner, sem `PARTQC_DOCKER_BUILD_NETWORK` (o `docker.yml` não define a variável, conferido em `test_extra_docker_workflow_matches_ci_database_and_has_no_build_network_override`), e o pull das imagens base a partir de um runner limpo.
- **Nem o CI prova:** o `compose up` com a rede bridge `partqc`, a resolução de `api:8000`/`dashboard:8501` pelo DNS do Docker e o alias do subdomínio. Isso só é provado na VPS (CA-13, CA-17, CA-40, CA-43).
- Primeira execução: 3 falhas, todas do lado dos testes ou de achados exploratórios (corrigidas antes desta versão): o `docker compose config` imprime um `$` literal como `$$` (o teste extra passou a comparar com o valor escapado e a mostrar que, sem aspas, o valor é interpolado), e o sentinela extra `FOTO.JPG` entrou nas duas imagens (achado T-03, retirado do teste porque a SPEC lista os padrões em minúsculas).
- **Limpeza:** as imagens de teste foram removidas pela fixture `build_image` no fim de cada sessão; as imagens e os contêineres da exploração (`partqc-tester-*`) e o banco `partqc_test_acc015_live` foram removidos por mim; o `caddy:2.11.7@sha256:685ae3…`, baixado pelo CA-34 e ausente antes, também foi removido. Nenhum contêiner que não fosse meu foi tocado. O cache do BuildKit não foi limpo (um `prune` afetaria outros projetos).

## Bugs encontrados

Nenhum bug viola um CA. Os três achados abaixo são de severidade baixa, ficam para o reviewer (portão de segurança, já que o autor é o security-devops) e não mudam o veredicto pela regra do tester (todos os CAs têm teste e passam).

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | §4.5 ("nenhuma chave é impressa", R-03/R-13); fora dos cenários do CA-12 | `READ_API_KEY=x SIM_DEVICE_ID=sim-01 SIM_DEVICE_API_KEY=y uv run --package qc-api python scripts/smoke_test.py --api-key=TOPSECRETVALUE123` (ou `--api-url-typo <url>`) | Código 2 sem repetir o valor, como o dev-report afirma ("erros de uso saem com código 2 (inclusive opção inválida do argparse), sem repetir valores") e como o simulador já faz desde a SPEC-027 (`NoEchoArgumentParser`, SEC-01 da SPEC-014) | Código 2 com `smoke_test.py: error: unrecognized arguments: --api-key=TOPSECRETVALUE123` no stderr. Uma chave ou URL digitada numa opção errada vai para o terminal e para a saída que o §4.5 manda colar no dev-report |
| T-02 | baixa | §4.7, item 1 (porta efetiva 6543); fora das entradas do CA-20 | Listener TCP em `127.0.0.1:6543`; `python infra/migrate.py --status --database-url "host=127.0.0.1 port='06543' user=u dbname=x_test connect_timeout=2"` (o mesmo com `port='+6543'` ou a URL com `:06543`) | Recusa com código 2 e 0 conexões (o libpq lê `06543` e `+6543` como a porta 6543) | Código 1, **1 conexão** recebida na 6543 e `could not connect to the database at 127.0.0.1:06543`. A comparação é por texto (`port == "6543"`). A §7 chama a recusa de heurística para o caso real (a `DATABASE_URL` da API usada por engano), e um zero à esquerda não é esse caso; sugestão: comparar `int(port)` |
| T-03 | baixa | §4.11 (R-02, R-03, R-14); o CA-36 passa, porque os padrões obrigatórios da SPEC são em minúsculas | Build da API (`docker_support.docker_build`) a partir de `copy_tracked_tree` com os extras `FOTO.JPG`, `a/IMG_0001.HEIC`, `b/shot.PNG`, `c/x.Jpeg`, `d/y.WEBP`, `OUTBOX.SQLITE3`, `infra/.ENV.API` e `secrets/.Env`; depois `test -e /app/<caminho>` | Nenhum desses arquivos na imagem | Os 8 estão na imagem (os padrões do `.dockerignore` diferenciam maiúsculas). Só `edge/data/captures/z.JPG` ficou fora, por estar num diretório excluído. Na VPS o contexto é um `git clone` mais os `infra/.env*` (em minúsculas), então o risco prático é baixo, mas `.JPG` e `.HEIC` são as extensões padrão de muitas câmeras e do iPhone. Sugestão ao architect: padrões sem distinção de caixa (ex.: `**/*.[jJ][pP][gG]`) numa emenda da §4.11 |

Informativo (sem requisito na SPEC): pelo Caddy, as respostas da API e do dashboard levam `server: uvicorn` e `via: 1.1 Caddy`, o que identifica o software. Não é segredo; fica registrado para o portão de segurança.

## Testes exploratórios (além dos critérios)

**Automatizados** (`test_extra_*`, todos passando):

- **Smoke:**
  - URLs parecidas com loopback recusadas sem requisição: `http://localhost.evil.example`, `http://127.0.0.1.nip.io`, `ftp://`, sem esquema, vazia, `https://` sem host e `javascript:`;
  - `http://localhost` e `http://127.0.0.1` aceitas; URLs lidas de `CLOUD_API_URL`/`DASHBOARD_URL`;
  - barra final nas URLs sem `//` no caminho; o dashboard segue redirecionamento;
  - corpo não JSON no health vira `FAIL health`, sem exceção;
  - falta de `SIM_DEVICE_ID` ou `SIM_DEVICE_API_KEY` sai com código 2 sem requisição;
  - URL com usuário e senha recusada sem repetir a senha nem o host;
  - a leitura usa a `READ_API_KEY`, `lot_id` e `source=simulated`; o `Origin` estranho vai para `/api/v1/health`.
- **Executor:**
  - recusa da 6543 em `key=value`, `?port=6543`, IPv6 `[::1]:6543`, multi-host com `PGPORT` e item de porta vazio, e pela variável `DATABASE_URL`; nenhuma vaza a senha;
  - a porta de sessão não é recusada (tenta conectar e sai com 1);
  - `lock_wait_s` só por palavra-chave, padrão 30; o lock é pego quando liberado dentro do prazo, sem lock consultivo preso depois;
  - `rollback;` e `rollback; begin;` também são detectados;
  - dígitos Unicode (`001` arábico-índico, `00١`, dígitos de largura total) recusados por `load_migrations`;
  - `Migration.content` é `bytes`, `read_sql()` decodifica esses bytes e o SQL não aparece no `repr`.
- **Keep-alive:** o passo roda no `bash` com um `curl` falso:
  - secret vazio: falha com mensagem e sem chamar o `curl`;
  - com URL: chama `<URL>/api/v1/health` com `-fsS --retry 5 --retry-delay 30`;
  - `curl` falhando com o host no stderr: nada do host chega à saída do passo (R-13).
- **Arquivos:**
  - `render.yaml` com `name`, `branch` e `region` explícitos, e `PYTHON_VERSION` igual ao patch da imagem;
  - Dockerfiles com as demais linhas da tabela da §4.10 (`UV_COMPILE_BYTECODE`, `UV_LINK_MODE`, `PYTHONUNBUFFERED`, `PATH`, `COPY . /app`, `EXPOSE`, usuário `10001` e `/home/app`, `HEALTHCHECK` em forma exec com `--timeout=10s --start-period=30s --retries=3`), sem `ADD` de URL nem `curl | sh`;
  - compose com rede `bridge`, sem `cap_add` na API e no dashboard, sem volumes neles e sem `NET_ADMIN`/`SYS_ADMIN`;
  - Caddyfile sem `log`, `email`, `debug`, `tls`, `basicauth` nem `rewrite`;
  - `.dockerignore` com todos os padrões obrigatórios, sem exclusões proibidas, e a exceção dos PNG depois da exclusão;
  - nenhum `.dockerignore` na raiz nem `dashboard/requirements.txt`; só `.env.example` rastreado entre os `.env*`;
  - `.env.example` com os padrões de recursos iguais aos do compose;
  - `docker.yml` com o mesmo `TEST_DATABASE_URL` do `ci.yml` e `uv python install 3.12`;
  - nenhum domínio concreto fora dos de exemplo e de documentação nos arquivos de deploy;
  - no `deployment-plan.md`, toda linha com `uv run` e `migrate.py` usa `--env-file .env.migrate` e nunca `--database-url`.
- **`docker_support` e hooks:**
  - `docker_tests_enabled` recusa `" 1"`, `"1 "`, `"01"`, `"yes"` e `"TRUE"`;
  - `check_docker` com executável ausente levanta `DockerUnavailableError` citando `docker`;
  - `copy_tracked_tree` recusa caminhos com `..` ou absolutos e um destino dentro do repositório, sem escrever nada;
  - sonda em subprocesso: sem a variável, o item `docker` é pulado com o motivo exato; com `PARTQC_DOCKER_TESTS=1` e um `docker` falso cujo `compose version` falha, a sessão para com `UsageError` (código 4) citando `compose`.
- **Imagens (docker):**
  - GID `10001`, `HOME=/home/app`, `/app` sem escrita para o usuário `app`, `.venv` de dono root;
  - `find /app -maxdepth 3 -name '.env*'` só acha `/app/.env.example` (equivalente local do CA-43, item 1);
  - nenhuma variável de segredo no `Config.Env`; `ExposedPorts` só com 8000/tcp (resp. 8501/tcp);
  - nenhum `*.onnx`, `*.jpg` ou `*.sqlite3` fora do `.venv`;
  - mais 14 sentinelas extras (`dashboard/.streamlit/secrets.toml`, `edge/.env`, `.pt`/`.pth`, `ml/checkpoints/`, `data/`, `*.db`, `.claude/agents/`, `.venv` e `__pycache__` de pacote, caches) fora das duas imagens.
- **Compose:** valor com `$` entre aspas simples fica literal, e sem aspas é interpolado (§4.12).

**Manuais** (contêineres meus, todos em `127.0.0.1`, conferido com `ss -tlnpu`: 8000, 8501, 18080, 18443/tcp e udp e o admin do Caddy na 2019, nada fora do loopback; removidos no fim):

- Imagens `partqc-tester-api:explore` e `partqc-tester-dashboard:explore` construídas pelo `docker_support.docker_build` a partir de `copy_tracked_tree`.
- **Contêineres:**
  - API e dashboard com `--network host`, `--cap-drop ALL`, `no-new-privileges` e os limites do compose, e o comando sobrescrito só no endereço de escuta (`127.0.0.1` no lugar de `0.0.0.0`);
  - a API ligada a um banco temporário migrado (`partqc_test_acc015_live`, com o `sim-01`), o dashboard com `API_BASE_URL=http://127.0.0.1:8000`;
  - os dois ficaram `healthy` pelo `HEALTHCHECK` da imagem;
  - uso de memória: API 46 MiB de 512 MiB, dashboard 62 MiB de 1 GiB, Caddy 15 MiB de 256 MiB.
- **`scripts/smoke_test.py`** contra os contêineres (`http://127.0.0.1:8000` e `:8501`): as 8 checagens `PASS`, código 0.
- **Caddy:**
  - a imagem fixada do compose, com `--cap-drop ALL --cap-add NET_BIND_SERVICE`, `no-new-privileges` e `--memory 256m`;
  - o `infra/Caddyfile` real, com um bloco global **acrescentado só nesta cópia** (`default_bind 127.0.0.1`, portas 18080/18443, `local_certs`), para nada escutar fora do loopback;
  - `PUBLIC_HOST=localhost`.
- **Resultados pelo Caddy:**
  - `/api/v1/health` → 200 (`db: ok`, `contract_version` 0.3.0), com `strict-transport-security: max-age=31536000` (sem `includeSubDomains`) e `x-content-type-options: nosniff`; os dois headers também saem nas respostas do dashboard;
  - `http://` → `308` para `https://`;
  - `/api/v1/inspections` sem chave → 401;
  - `/docs` → 0 ocorrências de `swagger`, `/openapi.json` → 0 de `"openapi"`, e `/api/docs`, `/api/v1/docs` e `/api/openapi.json` → 404;
  - caminhos com travessia (`/api/../docs`, `/api/%2e%2e/docs`, `/api/..%2fdocs`, `/api/v1/..%2f..%2fdocs`, `//docs`, `/api/v1/../../openapi.json`, com `--path-as-is`) → 400, sem Swagger nem OpenAPI;
  - `/API/v1/health` → 404;
  - upgrade de WebSocket em `/_stcore/stream` → `101`; `/_stcore/health` → `ok`;
  - `Origin: https://example.org` → sem `access-control-allow-origin`;
  - `Host: evil.example` → resposta vazia do próprio Caddy (`server: Caddy`, `content-length: 0`), sem chegar à API.
- **Logs do Caddy:** só os avisos esperados da porta HTTP sem TLS; nenhum aviso de capacidade.

## Ajustes em testes de aceite de SPECs anteriores

Nenhum. A suíte inteira passou sem tocar em `test_spec_001`, `test_spec_003`, `test_spec_022`, `test_spec_027`, `test_spec_028` ou em qualquer outro arquivo de aceite.

## SPEC_ISSUE (se houver)

Nenhum. Para o architect, sem bloquear: T-02 e T-03 apontam lacunas da redação da §4.7 (porta comparada como texto) e da §4.11 (padrões com distinção de caixa), e a implementação segue a SPEC ao pé da letra nos dois casos.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
