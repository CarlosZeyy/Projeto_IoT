# SPEC-032 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-032](../../docs/specs/SPEC-032-manutencao-deploy.md) |
| Rodada | r1 |
| Autor | security-devops (o portão de segurança desta SPEC é do **reviewer**, `reviews/README.md`) |
| Branch | `spec/SPEC-032-manutencao-deploy` |
| Commits | `6962098` (§4.1), `9fd99af` (§4.2), `3ef1ae9` (§4.3), `8574e21` (§4.4, `.env.example` e plano), `883a0bc` (risco residual dos headers no plano), mais o commit deste relatório |

## Resumo

As quatro seções da SPEC foram implementadas, e os candidatos SEC-15-04 e SEC-15-05 mantidos pelo humano estão incluídos. O `smoke_test.py` passou a recusar abreviações (`allow_abbrev=False`). O `.gitignore` ganhou as variantes sem diferenciar maiúsculas, inclusive `heic` e `webp`, sem mudar nenhuma linha existente. O Caddy apaga `Server` e `Via` e define `Referrer-Policy` e `frame-ancestors`. Os três contêineres rodam com `read_only`, um `tmpfs` só em `/tmp` (`64m`) e `pids_limit` `256`, configurável no `infra/.env`. Medi a folga: o pico foi de 15 PIDs no dashboard, 51 na API e 11 no Caddy. Não há SPEC_ISSUE. Há uma observação para o architect sobre respostas geradas pelo próprio Caddy (O-01).

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `scripts/smoke_test.py` (`_build_parser`: `allow_abbrev=False`) | `infra/tests/test_smoke_script.py::test_abbreviations_are_unknown_arguments_never_echoed` (`--=<m>`, `--api=https://<m>.example.org`, `--dash https://<m>.example.org`, `--he <m>`: código 2, 0 requisições, marcador ausente, sem `ambiguous`, com `value(s) (not shown)`), `::test_parser_has_no_prefix_matching`, `::test_full_option_names_win_over_the_environment` (nomes por extenso com `CLOUD_API_URL`/`DASHBOARD_URL` definidas → 0); os testes da SPEC-015 continuam passando |
| CA-02 | `.gitignore` | `infra/tests/test_deploy_files.py::test_gitignore_ignores_sensitive_files_in_any_case` (os 15 caminhos do CA e mais 6, entre eles `entrada/IMG_1234.JPG` e `entrada/a.HEIC` do SEC-36-02), `::test_gitignore_keeps_the_exceptions_in_any_case` (os 6 do CA e mais 3), `::test_gitignore_keeps_every_previous_line_in_order` (cópia literal do `.gitignore` anterior), `::test_gitignore_variants_sit_next_to_their_patterns_and_before_the_exceptions` |
| CA-03 | `.gitignore` | `test_deploy_files.py::test_gitignore_variants_do_not_ignore_tracked_files` (`ls-files -ci` com o `.gitignore` atual e com uma cópia temporária sem as linhas que casam `\[[a-z][A-Z]\]`; sem depender do ref `main`) |
| CA-04 | `infra/Caddyfile` | `test_deploy_files.py::test_caddyfile_header_block_spec_032` (as 6 linhas exatas do bloco, um único `header`, sem `script-src`/`default-src`) e `::test_caddyfile_routes_and_headers` (condições do CA-30 da SPEC-015, sem mudança) |
| CA-05 (docker) | `infra/Caddyfile` | `infra/tests/test_docker_images.py::test_caddy_adapts_the_caddyfile` (estendido: um único handler `headers`, `deferred: true`, `delete == ["Server", "Via"]`, `set` com os 4 headers) e `::test_caddy_header_block_strips_server_and_via_behind_the_proxy` (o bloco real atrás de um `reverse_proxy` cuja origem responde `Server: uvicorn`: a resposta sai sem `server` e sem `via` e com os 4 headers) |
| CA-06 | `infra/compose.yaml`, `.env.example` | `test_deploy_files.py::test_compose_hardening_spec_032` (`read_only is True`, `pids_limit` igual à string da §4.4, `/tmp` em `tmpfs`, `size` ≤ `64m`, `/home/app` só na `api` e no `dashboard`), `::test_env_example_compose_values_match_the_compose_defaults` e `::test_env_example_vps_block` (as 3 variáveis com `256`, dentro do bloco `infra/.env`); docker: `test_docker_images.py::test_compose_config_quiet_with_the_hardening` (`config --quiet` numa cópia temporária → 0, stdout vazio), `::test_compose_resolves_host_and_limits` (estendido: `pids_limit` 256, `read_only`, `tmpfs`) e `::test_compose_pids_limit_override` |
| CA-07 (docker) | `infra/compose.yaml` | `test_docker_images.py::test_dashboard_runs_read_only` e `::test_api_runs_read_only` (opções tiradas do compose: `--read-only`, os `tmpfs` do compose, `--pids-limit 256`, `--cap-drop ALL`, `no-new-privileges`, `10001:10001`; o dashboard fica `healthy` e responde `200 ok`; a API responde 503 sem banco; sem `Read-only file system`, `EROFS` nem `PermissionError` no log; `touch /tmp/x` → 0; `touch /app/x` falha; `pids.max` = 256) |
| CA-08 (docker) | `infra/compose.yaml`, `infra/Caddyfile` | `test_docker_images.py::test_caddy_runs_read_only` (`--read-only`, `tmpfs` do compose, volumes anônimos em `/data` e `/config`, `--pids-limit 256`, `--network none`, Caddyfile real, `PUBLIC_HOST=partqc.example.org`: `running` depois de 10 s, sem `read-only file system` no log; `/tmp` e `/data` graváveis, `/etc` não) |
| CA-09 (manual, VPS) | `docs/deployment-plan.md` §9, "CA manual da SPEC-032" | Passo humano (lista abaixo) |

## Medições da §4.4 (itens 2 e 3)

Todas locais, em 2026-10-24, com o Docker Engine 29.9.2 e o Compose 5.6.1. As imagens foram construídas de uma cópia temporária da árvore rastreada (`copy_tracked_tree`), com `--network none` nos contêineres. Os contêineres e as imagens de sonda foram removidos no fim.

### `tmpfs`: onde cada processo escreve

| Serviço | `tmpfs` | Motivo | Como medi |
|---|---|---|---|
| `api` | `/tmp:size=64m` | Exigido pela §4.4 nos três serviços. Nenhuma escrita observada | `docker diff` num contêiner **gravável** (as demais opções iguais) depois de chamar `/api/v1/health`, `/inspections`, `/lots` e `/metrics/summary`: saída vazia. Com `--read-only` e **sem** nenhum `tmpfs`, a API subiu e respondeu 503 sem nenhum erro de escrita no log |
| `dashboard` | `/tmp:size=64m` | Exigido pela §4.4. Nenhuma escrita observada | `docker diff` num contêiner gravável depois de abrir as 4 páginas pelo WebSocket (`/_stcore/stream`, `BackMsg.rerun_script` com o `page_name` de cada página) contra uma API falsa local com os corpos dos fixtures do `dashboard/tests/conftest.py`. Foram renderizados `plotly_chart`, `dataframe`, `metric` e `download_button`. Saída vazia. Com `--read-only` e sem `tmpfs`, o painel ficou `healthy` e sem erro no log |
| `api`, `dashboard` | **nenhum** em `/home/app` | O Streamlit não escreveu em `~/.streamlit` (o `server.headless = true` do `.streamlit/config.toml` evita o pedido de credenciais), e o bytecode já vem compilado na imagem | O mesmo `docker diff` (nada em `/home/app`). `touch /home/app/x` falha com `Read-only file system`, e nenhum log mostra tentativa de escrita lá |
| `caddy` | `/tmp:size=64m` | Exigido pela §4.4. O Caddy só escreve em `/data` (`instance.uuid`, `last_clean.json`, `locks/`) e em `/config` (`autosave.json`), que são os volumes `caddy_data` e `caddy_config`, graváveis | `docker diff` num Caddy gravável com o Caddyfile real por 12 s. Depois, com `--read-only`, `tmpfs /tmp` e volumes, ficou `running` e sem `read-only` no log |

O `tmpfs` efetivo, conferido com `docker compose -p partqc-test-032 run --rm --no-deps` nos três serviços, numa cópia temporária e com os volumes de teste removidos depois, é `tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,relatime,size=65536k`, com `pids.max=256` e a raiz `ro`. O usuário `10001`, e o `root` no Caddy, escreve em `/tmp` (modo padrão `1777`). A referência do Compose não documenta `size` na forma curta, por isso conferi o efeito real.

### PIDs (`pids.current` do cgroup de cada contêiner, lido no host)

A carga veio de fora do cgroup medido (contêiner separado com `--network container:<alvo>`), e a amostragem foi a cada 50 ms. A sonda e a amostragem não entram na conta do Streamlit.

| Serviço | Em repouso | Com carga | Carga | Folga em relação a 256 |
|---|---|---|---|---|
| `dashboard` | 5 | **15** | 5 sessões simultâneas pelo WebSocket, 3 execuções cada (como mudanças de filtro), nas 4 páginas, com a API falsa respondendo dados reais | 17× |
| `api` | 6 | **51** | 200 requisições, 100 simultâneas, em `/health`, `/inspections`, `/lots` e `/metrics/spc`, sem banco (o pool de threads do AnyIO para em 40) | 5× |
| `caddy` | 9 | **11** | 2.000 requisições, 100 simultâneas, na porta 80 | 23× |

O limite tem pelo menos o dobro do medido nos três (§4.4, item 3). A interpolação `${..._PIDS_LIMIT:-256}` foi aceita pelo `docker compose config --quiet`, então não precisei do literal `256`. Um valor inválido (`API_PIDS_LIMIT=abc`) faz o `config` falhar com `failed to cast to expected type`.

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
env -u TEST_DATABASE_URL -u CI uv run pytest -q                               # 5654 passed, 732 skipped
env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker  # 36 passed, 4 skipped (torch)
uv run pytest -q infra/tests/test_smoke_script.py infra/tests/test_deploy_files.py
```

Não usei o banco de teste (`TEST_DATABASE_URL` e `CI` fora do ambiente, a pedido do orquestrador): os testes com banco ficaram `skipped`, e nenhum deles é desta SPEC. Os testes `docker` rodaram com a rede bridge padrão. Não precisei de `PARTQC_DOCKER_BUILD_NETWORK=host`.

Mutações conferidas: com `allow_abbrev=True`, 5 testes do smoke falham. Sem a linha `*.[hH][eE][iI][cC]`, 4 testes do `.gitignore` falham. Sem `-Via` no Caddyfile, os 2 testes `docker` do Caddy falham.

## Decisões tomadas dentro do escopo da SPEC

- **`.gitignore`:** entraram 2 linhas de comentário no grupo de segredos, explicando as variantes (SPEC-032 §4.2). As variantes de `.env` ficam entre `.env.*` e `!.env.example`. As de fotos ficam antes das 4 exceções. Os testes usam `-c core.ignorecase=false` para que o resultado seja o do Linux também num sistema de arquivos sem distinção de maiúsculas.
- **Caddyfile:** o `defer` automático vale para o bloco inteiro, então HSTS e `nosniff` também passam a ser aplicados depois do `reverse_proxy`. Assim os valores do Caddy prevalecem sobre os que a origem mandar. Conferi a documentação do Caddy de novo em 2026-10-24 e atualizei a data numa linha nova da §2 do plano.
- **`compose.yaml`:** usei a forma curta `"/tmp:size=64m"`. Os padrões `noexec,nosuid,nodev` do Docker continuam, como conferido acima. O comentário do topo resume o endurecimento.
- **Plano:** §2 (2 linhas novas na tabela, com fonte e data; um parágrafo de endurecimento com a tabela de PIDs; e o que fazer quando um contêiner bate no `pids_limit` ou dá erro de `read_only`), §3 e §4 (passo 5) com as 3 variáveis, §7 com os riscos 8 e 9, e §9 com o roteiro e a linha do CA-09. O roteiro do CA-09 tem um passo 5 **complementar**, marcado como fora do texto do CA (`grep` de `read-only file system` nos logs), e o passo 6 de registro.
- **Testes extras além dos CAs:** `--he <valor>` no smoke, mais caminhos no `.gitignore` (`*.Pth`, `*.Sqlite`, `docs/img/foto.JPG` ignorado, `MODEL.ONNX` dos fixtures não ignorado) e o teste de ponta a ponta do bloco de headers atrás de um proxy.

## Observações (não são SPEC_ISSUE)

- **O-01 (para o architect, informativo): respostas geradas pelo próprio Caddy mantêm `Server: Caddy`.** O `defer` só age nas respostas que passam pelo `reverse_proxy`. Conferi com a imagem fixada, em 2026-10-24: o redirecionamento `308` da porta 80 e o `502` que o Caddy devolve quando uma origem está fora do ar saem com `Server: Caddy` e sem os 4 headers. As respostas normais da API e do Streamlit por HTTPS, que são as que o CA-09, passo 2, confere, saem corretas. A §4.3 e os CA-04, CA-05 e CA-09 estão cumpridos como escritos. Só o objetivo da §2 ("as respostas públicas deixam de identificar o software") não vale nesses dois casos. Cobri-los (por exemplo, com `handle_errors` no site; o redirecionamento da porta 80 é de um servidor gerado automaticamente) iria além do texto da §4.3, então não improvisei: registrei como risco aceito 9 na §7 do plano. Se o humano quiser cobrir esses casos, isso entra por SPEC nova.
- **O-02 (SEC-36-02): o plano de importação continua sem proteção do `.gitignore`.** Com esta SPEC, `entrada/IMG_1234.JPG` e `entrada/a.HEIC` passam a ser ignorados. O `entrada/plano.csv` não é ignorado, porque `*.csv` está fora da §4.2, e ignorá-lo esconderia CSVs rastreados. A ação humana do SEC-36-02 continua: manter a pasta de entrada e o plano **fora** do repositório (`~/partqc-entrada/`).
- O `.gitignore` não tira do índice nada já rastreado (CA-03). Hoje nenhum arquivo rastreado casa as variantes.

## SPEC_ISSUE (se houver)

Nenhum.

## Pendências para o humano (VPS e navegador)

CA-09 da SPEC-032, depois de esta SPEC estar na `main` e da atualização da §4 ("Atualização") do `docs/deployment-plan.md`. O roteiro está no fim da §9 do plano:

1. `docker compose -f infra/compose.yaml ps`: 3 serviços `running`, `api` e `dashboard` `healthy`.
2. `curl -sI https://<subdominio>/api/v1/health`: tem `referrer-policy: no-referrer` e `content-security-policy: frame-ancestors 'self'`, e não tem `server:` nem `via:`.
3. Passos 1 a 3 do CA-17 da SPEC-015: painel no desktop e no celular, `wss://<subdominio>/_stcore/stream` com 101 aberto por 5 min, filtro atualizando os gráficos. Se algum componente quebrar por causa do `frame-ancestors`, parar e registrar `SPEC_ISSUE`.
4. Com 3 abas abertas, `docker stats --no-stream`: `PIDS` de cada serviço ≤ 128.
5. Registrar as saídas na §9 do plano e no dev-report, com `<subdominio>` no lugar do host.

Os CAs manuais da SPEC-015 (CA-13 a CA-19, CA-26, CA-40, CA-42 e CA-43) continuam pendentes e são feitos na mesma visita. Depois desta SPEC, o CA-13 deve ver os headers novos. O CA-42 continua valendo para os relatórios desta SPEC, que não têm host nem IP.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (inclusive os `docker`, com `PARTQC_DOCKER_TESTS=1`)
- [x] `.env.example` atualizado (`API_PIDS_LIMIT`, `DASHBOARD_PIDS_LIMIT`, `CADDY_PIDS_LIMIT`)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum subdomínio, IP ou valor com cara de segredo no diff (URLs com `partqc.example.org`, chaves geradas em tempo de execução, `<user>:<password>` como marcador)
- [x] Nenhuma ação na VPS, no Supabase, no DNS ou no GitHub; nenhum push
