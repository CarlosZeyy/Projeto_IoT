# SPEC-038 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-038](../../docs/specs/SPEC-038-manutencao-borda-deploy.md) |
| Rodada | r1 |
| Autor | developer (Parte A, `edge/`); a Parte B (security-devops) é acrescentada no fim deste arquivo |
| Branch | `spec/SPEC-038-manutencao-borda-deploy` (encadeada na SPEC-017, sobre a 018, a 016 e a 036) |
| Commits | `c1317fb` (outbox e CLI de reenvio), `e0f1090` (importação, varredura e README), mais o commit deste relatório |

## Parte A (developer)

### Resumo

- `qc_edge.outbox`: `fetch_due` e `dead_items` conferem o tipo e o formato de cada coluna lida, na ordem da §4.1. No `fetch_due`, a linha `pending` inválida vira `dead` com `last_error = INVALID_ROW_ERROR` (`"invalid outbox row"`), por `rowid`, sob o lock e numa única transação; no `dead_items`, é pulada sem escrita. Os dois avisos vão para o logger `qc_edge.outbox` só com `rowid` e coluna.
- `qc_edge.requeue`: `ValueError`/`TypeError` em volta de `list_dead`/`requeue_dead` sai com 1 e loga só a classe (§4.1); a abertura separa `OperationalError` (`cannot open --outbox-path (...)`), `NotAnOutboxError`/`DatabaseError` (a mensagem de hoje) e outro `sqlite3.Error`, todos com 2 (§4.2).
- `qc_edge.importer`: `image.info.clear()` antes do `save` (§4.3); `limit_pil_logging()` no `main` (§4.4); remoção dos diretórios criados na linha, do mais interno para o mais externo, numa falha dos passos 4 a 6 (§4.5); reconferência do hash sob o lock, com a mesma regra de `exclusions.csv` da fase 1 (§4.6); recusa da pasta de entrada e do plano dentro de um repositório Git (§4.7).
- `qc_edge.privacy`: `limit_pil_logging()` (definida aqui e importada pelo importador) no `main` (§4.4).
- `edge/README.md`: as duas seções da §4.8.

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (listagem com linha inválida) | `edge/src/qc_edge/outbox.py` (`dead_items`, `_dead_item`, `_read_*`), `edge/src/qc_edge/requeue.py` | `edge/tests/test_requeue.py::test_cli_listing_skips_an_invalid_row` (5 casos do CA); `edge/tests/test_outbox.py::test_dead_items_skips_an_invalid_row_and_writes_nothing`, `::test_dead_items_accepts_a_null_last_error` |
| CA-02 (reenvio e laço, R-05) | `edge/src/qc_edge/outbox.py` (`fetch_due`, `_pending_item`) | `edge/tests/test_requeue.py::test_invalid_rows_never_stop_the_publish_loop`; `edge/tests/test_outbox.py::test_requeue_of_an_invalid_created_at_goes_back_to_dead` |
| CA-03 (`pending` adulterado) | `edge/src/qc_edge/outbox.py` (`fetch_due`) | `edge/tests/test_outbox.py::test_fetch_due_marks_an_invalid_pending_row_dead` (12 casos: texto, BLOB, inteiro, real, data que estoura em UTC), `::test_fetch_due_reports_the_first_invalid_column`, `::test_fetch_due_accepts_what_sqlite_converts`, `::test_fetch_due_with_invalid_rows_inside_the_limit` (limite de 100), `::test_fetch_due_marks_dead_in_one_transaction`, `::test_fetch_due_without_invalid_rows_writes_nothing`, `::test_requeue_fixes_attempts_and_next_attempt_at` |
| CA-04 (defesa em profundidade) | `edge/src/qc_edge/requeue.py` (`main`) | `edge/tests/test_requeue.py::test_cli_value_and_type_errors_exit_with_1_without_the_message` |
| CA-05 (mensagens de abertura) | `edge/src/qc_edge/requeue.py` (`main`) | `edge/tests/test_requeue.py::test_cli_unopenable_file_is_not_called_not_an_outbox`, `::test_cli_files_that_are_not_an_outbox_keep_their_message`, `::test_cli_other_sqlite_error_on_open` |
| CA-06 (PNG com `comment`) | `edge/src/qc_edge/importer.py` (`normalize_imported_image`) | `edge/tests/test_importer.py::test_png_comment_is_not_copied` (`tEXt`, `zTXt`, `iTXt`), `::test_png_comment_reduced_image_is_not_copied`, `::test_png_with_comment_is_imported` |
| CA-07 (logger `PIL`) | `edge/src/qc_edge/privacy.py` (`limit_pil_logging`, `main`), `edge/src/qc_edge/importer.py` (`main`) | `edge/tests/test_importer.py::test_limit_pil_logging`, `::test_importer_main_keeps_exif_tags_out_of_the_debug_log`, `::test_privacy_main_keeps_exif_tags_out_of_the_debug_log`, `::test_main_never_lowers_a_higher_pil_level` |
| CA-08 (rollback dos diretórios) | `edge/src/qc_edge/importer.py` (`_store_locked`, `_write_row`, `_remove_dirs`) | `edge/tests/test_importer.py::test_failed_row_removes_the_directories_it_created` (`sources.csv`, `manifest.csv`, imagem), `::test_failed_row_keeps_a_directory_that_existed`, `::test_directory_that_cannot_be_removed_stays` |
| CA-09 (execução simultânea) | `edge/src/qc_edge/importer.py` (`_check_headers`, `_store_locked`, `run_import`, `_AlreadyImported`) | `edge/tests/test_importer.py::test_two_runs_of_the_same_plan_store_the_photo_once`, `::test_a_hash_excluded_meanwhile_is_imported_again`, `::test_bad_exclusions_under_the_lock_stops_the_import` |
| CA-10 (repositório Git) | `edge/src/qc_edge/importer.py` (`inside_git_repository`, `load_plan`) | `edge/tests/test_importer.py::test_inside_git_repository` (diretório, arquivo, link pendurado), `::test_inbox_inside_a_git_repository_is_refused`, `::test_plan_inside_a_git_repository_is_refused`, `::test_inbox_is_checked_before_the_plan`, `::test_inbox_inside_the_dataset_is_checked_first`, `::test_dataset_and_registry_inside_a_repository_are_accepted` |
| CA-11 (README) | `edge/README.md` | (conferido pelo tester; os textos `invalid outbox row`, `rowid`, `fora do repositório` e `repositório Git` estão nas seções da §4.8) |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests/test_outbox.py edge/tests/test_requeue.py edge/tests/test_importer.py
uv run pytest -q   # suíte inteira, sem TEST_DATABASE_URL e sem CI=true
```

### Decisões tomadas dentro do escopo da SPEC

1. **Logger dos avisos.** O módulo `qc_edge.outbox` já usava o logger `qc_edge` (aviso do WAL). Para não mudar esse aviso, os dois avisos novos vão para um logger próprio, `row_logger = logging.getLogger("qc_edge.outbox")`, como a §4.1 pede.
2. **"A conversão funciona".** A validação de `created_at` e `next_attempt_at` roda o próprio `parse_timestamp` de hoje (`fromisoformat` + `astimezone(UTC)`) e trata `ValueError` e `OverflowError` como inválido. Assim, um texto como `0001-01-01T00:00:00+05:00`, que o `fromisoformat` aceita mas cuja conversão para UTC estoura, também vira `dead` em vez de derrubar o ciclo. Para os valores que a tabela da §4.1 descreve, o resultado é o mesmo (a definição de "linha válida" exige que "a conversão funcione"). `attempts` exige `int` (e não `bool`, que o `sqlite3` nunca devolve).
3. **Escrita no `fetch_due`.** A leitura, a validação e o `UPDATE ... WHERE rowid = ? AND status = 'pending'` (um `executemany`, um `COMMIT`) acontecem sob o mesmo `threading.Lock`; os avisos são registrados depois do commit, fora do lock. Sem linha inválida, nada é escrito (teste com `set_trace_callback`).
4. **Sinal de "já importado" sob o lock (§4.6).** `_store_locked` levanta a exceção interna `_AlreadyImported` depois do `item_type_conflict` (a ordem da frase da §4.6), e o `run_import` a trata como a linha marcada na fase 1 (`skipped <file>: already imported`, conta em `skipped`). Um `exclusions.csv` com outro cabeçalho ou ilegível nesse ponto vira `_ImportStopped` com `exclusions header mismatch`/`exclusions unreadable` (as mensagens da fase 1), código 1; um `OSError` na leitura cai no caminho de E/S de hoje (`failed to write dataset`, código 1).
5. **Rollback dos diretórios (§4.5).** Os passos 4 (imagem) a 6 foram movidos para `_write_row`, sem mudança de lógica; `_store_locked` envolve a chamada num `try/except BaseException` que chama `_remove_dirs(created)` depois de a imagem e o manifest já terem sido desfeitos, ainda sob o lock. `fsync_dir` só do pai de cada diretório efetivamente removido.
6. **`limit_pil_logging`** fica em `qc_edge.privacy` (o importador já importa `printable_path` de lá) e não em `qc_edge.jpeg` (§7 da SPEC).
7. **`inside_git_repository(path)`** é pública em `qc_edge.importer` e recebe o caminho já resolvido: `load_plan` passa o `realpath` da pasta de entrada e o pai do `realpath` do plano. A verificação acontece logo depois da regra "fora do dataset" e antes de `DATASET_NOT_DIR` e de qualquer leitura, na ordem da §4.7.
8. **Fixture `restore_pil_logger_level` (autouse) em `edge/tests/conftest.py`.** Os `main` do importador e da varredura agora sobem o nível do logger `PIL` quando o raiz está em DEBUG (o `caplog.set_level(logging.DEBUG)` de vários testes). A fixture devolve o nível de antes ao fim de cada teste, para não vazar estado global entre testes (vale também para os de aceite, que herdam o `conftest.py`, sem mudar nenhum deles).

### Observações (não bloqueiam)

- **`inspection_id` fora da forma canônica.** Pela tabela da §4.1, um `inspection_id` `str` que o `uuid.UUID` aceita é válido, mesmo em maiúsculas ou com chaves. Nesse caso (só com edição à mão), `mark_sent`/`mark_retry` usam `str(UUID)` (minúsculas) no `WHERE` e não acham a linha, que é reenviada a cada ciclo sem nunca virar `sent` (a idempotência da API evita duplicata, R-05, e os outros itens seguem). É o comportamento de antes da SPEC-038, e a SPEC define a validade assim; não mudei. Se o architect quiser, basta exigir `str(UUID(v)) == v` numa SPEC futura.
- **Falha no próprio `make_private_dirs`.** A §4.5 usa a lista devolvida por `make_private_dirs`; se o `mkdir` de um diretório interno falhar depois de criar os externos, a lista não volta e os externos vazios ficam (como antes). É um caso de E/S raro e fora do texto da §4.5.

### Testes de aceite de SPECs anteriores afetados (`docs/architecture.md` §10)

Nenhum. A suíte inteira (inclusive `edge/tests/acceptance/test_spec_009.py`, `test_spec_034.py` e `test_spec_036.py`) passa sem mudança: os testes de aceite da SPEC-036 usam `tmp_path`, fora de qualquer repositório Git, e o CA-16 da SPEC-009 (cobertura de `qc_edge.outbox` ≥ 80%) continua passando com os testes novos em `edge/tests/test_outbox.py`. Os dois testes de `infra/tests/acceptance/test_spec_032.py` citados na §3.1 dependem da Parte B (`handle_errors`) e não são afetados pela Parte A.

### SPEC_ISSUE

Nenhum.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (suíte inteira sem banco: 6965 passed, 1097 skipped, 0 failed)
- [x] `.env.example` sem mudança na Parte A (nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim; nada em `infra/`, `.gitignore`, `.dockerignore`, `.env.example` nem `docs/deployment-plan.md`
- [x] Imagens dos testes geradas pelo Pillow; marcadores gerados com `secrets`; nada lido de `~/partqc-entrada/`

## Parte B (security-devops)

| Campo | Valor |
|---|---|
| Autor | security-devops (Parte B: `infra/`, `.gitignore`, `.env.example` e `docs/deployment-plan.md`) |
| Commits | `e601f98` (Caddyfile, `.gitignore`, `.dockerignore`, `.env.example`, plano e testes do autor), mais o commit desta seção |
| Base | o Caddy da SPEC-039 (ADR-023): site `:80`, imagem de `infra/docker/caddy.Dockerfile`, dois recursos no Coolify, conforme a nota do topo da SPEC |

### Resumo

- `infra/Caddyfile` (§4.9, SEC-32-01): um bloco `handle_errors` sem códigos de status, dentro do site `:80`, com um `header` igual ao do site (as 6 linhas) e `respond ""` (um único argumento que não é número de 3 dígitos é o corpo; sem status, a rota de erro usa o status do erro original). Sem `reverse_proxy`, `file_server`, `templates`, `rewrite` e sem nenhum placeholder `{err.*}`. O `header` do site, o `handle /api/*` e o `handle` sem matcher não mudaram, e o arquivo continua formatado pelo `caddy fmt`.
- `.gitignore` e os `.dockerignore` da API e do dashboard (§4.10, SEC-32-02): as 9 extensões, só na forma com classes de caracteres, logo depois de `*.[wW][eE][bB][pP]` e antes das exceções de PNG (com `**/` nos `.dockerignore`). Nenhuma linha existente saiu ou mudou de posição relativa. O `.dockerignore` do Caddy não mudou (nota do topo).
- `.env.example` e `docs/deployment-plan.md` (§4.9, §4.11): a linha `# Inteiro positivo: 0 ou -1 removem o limite (sem aviso do compose); nunca use.` logo acima de `API_PIDS_LIMIT=256`; no plano, a mesma regra no item do `pids_limit` (§2), o diagnóstico no passo 3 da "Atualização" (§4), o risco 9 da §7 no texto da nota do topo (redirecionamento e erros do proxy do Coolify), uma linha nova "Caddy: respostas de erro" na tabela da §2 com as fontes e a data, e o CA manual da SPEC-038 na §9 (`docker stop`/`docker start` pelo seletor do projeto do Coolify).

### Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-12 (Caddyfile como texto) | `infra/Caddyfile` | `infra/tests/test_deploy_maintenance.py::test_one_handle_errors_without_status_codes_inside_the_site`, `::test_handle_errors_has_the_six_header_lines`, `::test_handle_errors_responds_with_an_empty_body_and_no_status`, `::test_handle_errors_never_forwards_or_renders` (4 casos), `::test_handle_errors_uses_no_error_placeholder_but_the_status_code`, `::test_the_rest_of_the_site_does_not_change`, `::test_site_header_block_keeps_the_six_lines`, `::test_caddyfile_comments_explain_handle_errors_without_a_domain`; as condições do CA-04 da SPEC-039 continuam nos testes do autor da 039 (`infra/tests/test_coolify_deploy.py::test_caddyfile_*`) |
| CA-13 (docker, `caddy adapt`) | `infra/Caddyfile` | `infra/tests/test_deploy_maintenance.py::test_caddy_adapt_puts_the_headers_in_the_error_routes` (handler `headers` em `errors.routes` com os 4 headers e `delete` de `Server`/`Via`; `static_response` sem status e sem corpo; nenhum `reverse_proxy` nos erros; nas `routes`, 1 `headers` adiado e os 2 proxies); `infra/tests/test_docker_images.py::test_caddy_adapts_the_caddyfile` e `infra/tests/test_coolify_deploy.py::test_caddy_image_adapts_without_public_host` (ajustados às `routes`) |
| CA-14 (docker, resposta de erro) | `infra/Caddyfile` | `infra/tests/test_deploy_maintenance.py::test_caddy_error_response_has_the_headers_and_an_empty_body` (imagem da SPEC-039 §4.3 com `--read-only`, 3 `tmpfs`, `--cap-drop ALL`, `--cap-add NET_BIND_SERVICE`, `--pids-limit 256`, `--network none`; HTTP/1.1 bruto a `127.0.0.1:80` com `Host: partqc.example.org` em `/api/v1/health` e `/`: `502`, os 4 headers, sem `Server`/`Via`, `Content-Length: 0`, corpo vazio, nenhum header duplicado, contêiner `running`); controle negativo `::test_control_without_handle_errors_the_502_leaks_server` (o mesmo Caddyfile sem o bloco devolve `Server: Caddy` e nenhum dos headers) |
| CA-15 (`.gitignore`) | `.gitignore` | `infra/tests/test_deploy_maintenance.py::test_gitignore_ignores_the_new_photo_and_video_formats` (os 18 caminhos do CA e mais 5), `::test_gitignore_keeps_what_must_stay_tracked` (os 8 do CA e mais 3), `::test_gitignore_new_lines_sit_before_the_png_exceptions`, `::test_gitignore_keeps_every_line_of_the_start_of_the_round` (cópia literal), `::test_no_tracked_file_is_ignored`; `infra/tests/test_deploy_files.py::test_gitignore_variants_sit_next_to_their_patterns_and_before_the_exceptions` (ajustado) |
| CA-16 (`.dockerignore`) | `infra/docker/api.Dockerfile.dockerignore`, `infra/docker/dashboard.Dockerfile.dockerignore` | `infra/tests/test_deploy_maintenance.py::test_dockerignore_has_the_new_formats_before_the_exceptions`, `::test_dockerignore_keeps_every_rule_of_the_start_of_the_round` (api e dashboard), `::test_caddy_dockerignore_is_unchanged`; *(docker)* as 9 sentinelas do CA e mais 3 em subpastas entraram em `SENTINELS_ABSENT` de `infra/tests/test_docker_images.py` (`::test_build_context_filters_secrets_data_and_weights`, que é o CA-36 da SPEC-015 do autor) |
| CA-17 (documentação) | `.env.example`, `docs/deployment-plan.md` | `infra/tests/test_deploy_maintenance.py::test_env_example_warns_against_zero_or_minus_one`, `::test_plan_pids_limit_item_forbids_zero_and_minus_one`, `::test_plan_update_step_3_points_to_the_hardening_diagnosis`, `::test_plan_risk_9_describes_handle_errors_and_the_coolify_proxy`, `::test_plan_lists_the_caddy_error_sources_with_the_date`, `::test_plan_manual_ca_18_uses_the_coolify_container_names` |
| CA-18 (manual, VPS) | `docs/deployment-plan.md` §9, "CA manual da SPEC-038" | manual (humano), pendente |

### Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q infra/tests/test_deploy_maintenance.py infra/tests/test_deploy_files.py infra/tests/test_coolify_deploy.py
PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests/test_deploy_maintenance.py infra/tests/test_docker_images.py infra/tests/test_coolify_deploy.py
```

Resultados (sem `TEST_DATABASE_URL` e sem `CI`):

- suíte inteira sem docker: 7047 passed, 1145 skipped, **2 failed**, que são os dois testes de aceite estáticos listados abaixo;
- `PARTQC_DOCKER_TESTS=1 uv run pytest -m docker infra/tests`: 91 passed e 4 failed antes da correção do parser de HTTP dos meus 2 testes de resposta (modo texto do `subprocess` trocava CRLF por LF); depois dela, `infra/tests/test_deploy_maintenance.py -m docker`: 3 passed. As outras 2 falhas são os dois testes de aceite docker listados abaixo;
- limpeza: a lista de contêineres, redes e imagens do Docker antes e depois das execuções é a mesma (nenhum `partqc-test-*` restante). Os contêineres e as imagens rodam com nomes `partqc-test-*` e `--network none`, e nenhum teste novo usa compose.

### Testes de aceite de SPECs anteriores afetados (`docs/architecture.md` §10; ajuste do tester)

Os dois da §3.1 e, pela nota do topo ("vale a mesma regra para um teste de aceite da SPEC-039"), mais dois da SPEC-039. Não alterei nenhum.

| Teste | Por que falha | Ajuste esperado (pela SPEC) |
|---|---|---|
| `infra/tests/acceptance/test_spec_032.py::test_extra_caddyfile_headers_are_in_one_header_block_and_no_full_csp` | 2 blocos `header` e `Content-Security-Policy` 2 vezes | o da tabela da §3.1 |
| `infra/tests/acceptance/test_spec_032.py::test_extra_caddy_adapt_single_header_handler_is_deferred` (docker) | 2 handlers `headers` no JSON (o segundo em `errors`) | o da tabela da §3.1 |
| `infra/tests/acceptance/test_spec_039.py::test_extra_caddyfile_comments_and_format` | `assert "handle_errors" not in _caddy_text()` e `len(blocks) == 1` dentro do `:80` | a §4.9 põe o `handle_errors` e o segundo `header` no site; o resto do teste (comentários, tabs) continua passando |
| `infra/tests/acceptance/test_spec_039.py::test_extra_caddy_adapt_has_no_automatic_https_and_no_redirect` (docker) | `statics == []` (o `respond ""` vira um `static_response` em `errors`) e `len(headers) == 1` | contar só nas `routes` do servidor, como na §3.1; o `static_response` dos erros não é redirecionamento (sem status e sem `Location`) |

### Decisões tomadas dentro do escopo da SPEC

1. **`respond ""`.** O `respond` do Caddyfile exige pelo menos um argumento (`respond` sozinho falha no `caddy adapt` com "wrong argument count"). Com um argumento só, que não é número de 3 dígitos, ele é o corpo, e o status fica vazio, então a rota de erro usa o status recomendado do erro (comentário de `ServeHTTP` e `UnmarshalCaddyfile` em `staticresp.go`, consultado em 2026-10-26). Escolhi isso em vez de `respond "" {err.status_code}`, que também é permitido pela §4.9, porque é exatamente o mecanismo que a §4.9 cita, sem nenhum placeholder.
2. **Verificação prática.** Com a imagem `caddy:2.11.7` fixada e sem a API e o dashboard, o `502` de `/api/v1/health` e de `/` saiu com os 4 headers, sem `Server` e sem `Via` e com `Content-Length: 0`. Com o mesmo arquivo sem o bloco, saiu `Server: Caddy` sem os headers (é o controle negativo do teste do autor).
3. **Linha nova na tabela da §2 do plano** ("Caddy: respostas de erro"), com as duas fontes e a data de 2026-10-26, além do texto do risco 9: a regra do agente pede a fonte verificada com "Verificado em", e a §4.9 pede a URL e a data no plano.
4. **CA manual da SPEC-038 na §9 do plano**, no formato dos CAs manuais das SPECs 032 e 017, já com os passos da nota do topo (`docker stop`/`docker start` do contêiner da API pelo seletor `com.docker.compose.project=<uuid>`) e a proibição de parar o `coolify-proxy`.
5. **`pids_limit` `0` e `-1`, conferido.** Com o Compose 5.6.1, `pids_limit: "${P:-256}"` com `P=0` resolve sem o campo, e com `P=-1` resolve `pids_limit: -1`, os dois sem aviso. Registrei isso no item da §2 do plano.
6. **Testes do autor ajustados** (§3.1, os do security-devops): `test_caddyfile_header_block_spec_032` (2 blocos, o segundo dentro do `handle_errors`), o `(response,) = ...` de `test_caddy_adapts_the_caddyfile` e o `(headers,) = ...` de `test_caddy_image_adapts_without_public_host` (só as `routes` do servidor), `handle_errors` fora da lista de tokens proibidos de `test_caddyfile_forbidden_token` (teste do autor da 039, que antecipava a SPEC-038) e as 9 linhas novas no teste de variantes do `.gitignore` da SPEC-032.

### Fora do escopo desta parte (registrado a pedido do orquestrador)

- **RV-02 da SPEC-039** (comentários antigos de `env_file` e `infra/.env.dashboard` em `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` e `.streamlit/config.toml`): fora. A §3.1 da SPEC-038 limita a Parte B a `infra/Caddyfile`, `.gitignore`, os dois `.dockerignore`, `.env.example`, `docs/deployment-plan.md` e testes em `infra/tests/`. Os dois Dockerfiles e o `config.toml` não estão nela. Fica para a próxima manutenção (ou uma correção pequena, se o humano decidir).
- **SEC-39-06** (proibir `{env.` e `{$` no Caddyfile): ver o SPEC_ISSUE abaixo. O Caddyfile desta parte não usa nenhum placeholder de ambiente nem de requisição, e o `handle_errors` não usa nenhum `{err.*}`.

### SPEC_ISSUE

- **SPEC_ISSUE-038-B1 (SEC-39-06, não bloqueia o resto da Parte B).** O `reviews/SPEC-039/r2-security-report.md` pede que, na Parte B da SPEC-038, o CA do Caddyfile passe a exigir que o texto sem comentários não contenha `{env.` nem `{$`, porque o ambiente do Caddy agora tem a `READ_API_KEY` (e o `PUBLIC_HOST`). A SPEC-038 não diz isso: o CA-12 cita as condições do CA-30 da SPEC-015 e do CA-04 da SPEC-039 (que proíbem só o texto `PUBLIC_HOST`, e não `{env.READ_API_KEY}` nem `{$READ_API_KEY}`), e a §4.9 proíbe só `{err.*}` além de `{err.status_code}` dentro do `handle_errors`. Pela instrução do orquestrador, não improvisei o requisito nem um teste do autor para ele. **Sugestão para o architect** (correção pequena, ADR-019, se couber): acrescentar à §4.9 "o arquivo não usa placeholder de ambiente (`{env.*}` nem `{$...}`)" e ao CA-12 "o texto sem comentários não contém `{env.` nem `{$`". O Caddyfile atual já cumpre, então a correção só acrescenta o teste (do autor e do tester), sem mudar a produção.

### CAs manuais

- **CA-18 (VPS, humano)**, depois da atualização com a SPEC-038 na `main`: passos em `docs/deployment-plan.md` §9, "CA manual da SPEC-038". Registrar a tabela de lá e esta seção com `<subdominio>`, sem o UUID e sem o nome do contêiner.

### Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando, inclusive os 3 `docker` novos e os `docker` antigos de `infra/tests/` que não são de aceite
- [x] `.env.example` atualizado (só o comentário da §4.11; nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim; nada em `edge/`
- [x] Nenhum segredo, subdomínio, IP ou UUID real; o host dos testes é `partqc.example.org`; nada feito na VPS nem no Coolify
- [x] `git -c core.excludesFile=/dev/null ls-files -ci --exclude-standard` vazio antes e depois da mudança
