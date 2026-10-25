# SPEC-018 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-018](../../docs/specs/SPEC-018-heartbeat-dispositivos.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-018-heartbeat-dispositivos` (encadeada sobre `spec/SPEC-016-ferramentas-manuais`) |
| Commits | `77768b6`, `b59de11`, `9cc84a5`, `efd470f`, `baf4f18` (e o commit deste relatório) |

## Resumo

- `qc-contracts` 0.5.0 (minor): `HeartbeatCreate` (`extra="forbid"`, `sent_at` no máximo 5 min no futuro, contadores de 0 a `MAX_HEARTBEAT_COUNT`, `model_version`/`model_sha256` nulos juntos) e `DeviceStatus` (`extra="ignore"`), mais `APP_VERSION_PATTERN` e `MAX_HEARTBEAT_COUNT`. Nenhum schema existente mudou. `pyproject.toml`, `__version__`, `uv.lock` e o histórico do README foram atualizados.
- Migração `infra/migrations/004_device_heartbeat.sql`: as 8 colunas anuláveis da §4.2 em `devices`, com `check` nomeados (regexes do contrato, contadores `>= 0` e o par do modelo nulo junto), num único bloco `DO` idempotente.
- API: `POST /api/v1/devices/{device_id}/heartbeat` (chave de dispositivo, 204) e `GET /api/v1/devices` (chave de leitura, até 500 itens em ordem de `device_id`), com `online` e `last_source` calculados no SQL, pela hora do banco.
- Borda: `HttpPublisher.send_heartbeat` (o único módulo com `httpx`, com os limites da SPEC-030) e `qc_edge.heartbeat.HeartbeatLoop`, registrado depois do `PublishLoop`, nas mesmas condições dele, e só com `HEARTBEAT_INTERVAL_S != 0` (padrão 60; de 10 a 3.600; outro valor → código 2).
- Dashboard: `ApiClient.devices()`, `data.fetch_devices()` (mesmo cache), `formatting.device_rows`/`fmt_uptime` e a página `views/dispositivos.py`, com o selo de simulado quando algum dispositivo tem `last_source = simulated`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (contrato) | `packages/contracts/src/qc_contracts/schemas.py`, `__init__.py`, `pyproject.toml`, `README.md`, `uv.lock` | `packages/contracts/tests/test_heartbeat.py` (o arquivo todo: ida e volta, campo extra, `uptime_s=-1`, `2_147_483_648`, `app_version="1.0\n"`, `sent_at` sem fuso e a 6 min, par do modelo); `packages/contracts/tests/test_smoke.py::test_import_and_version`, `::test_readme_has_version_history_row` |
| CA-02 (escrita) | `api/src/qc_api/routers/devices.py`, `api/src/qc_api/repositories/devices.py`, `api/src/qc_api/main.py` | `api/tests/test_devices.py::test_heartbeat_204_and_stored`, `::test_list_devices_after_a_heartbeat`, `::test_heartbeat_without_model_and_second_heartbeat_overwrites`, `::test_sent_at_does_not_decide_the_heartbeat_time` |
| CA-03 (autenticação e entrada) | `api/src/qc_api/routers/devices.py` (`Path(pattern=DEVICE_ID_PATTERN)` e 403); `auth.py` sem mudança | `api/tests/test_devices.py::test_heartbeat_for_another_device_is_403`, `::test_heartbeat_without_a_valid_device_key_is_401`, `::test_invalid_body_is_422_and_not_logged`, `::test_path_device_id_outside_the_pattern_is_422`, `::test_authentication_comes_before_validation`, `::test_heartbeat_body_limit_is_413` |
| CA-04 (online e offline) | `api/src/qc_api/repositories/devices.py` (`SELECT_DEVICES`, `ONLINE_WINDOW_S = 180`) | `api/tests/test_devices.py::test_online_window` (0, 179, 181 e 3.600 s; `sim-01` sem heartbeat) e `::test_list_devices_after_a_heartbeat` (`last_heartbeat_at == null`) |
| CA-05 (origem, R-06) | `api/src/qc_api/repositories/devices.py` (`left join lateral`) | `api/tests/test_devices.py::test_last_source_is_the_most_recently_received`, `::test_last_source_uses_received_at_not_inspected_at`, `::test_last_source_tie_on_received_at_uses_inspected_at` |
| CA-06 (leitura sem chave) | `api/src/qc_api/routers/devices.py` (`require_read_key`) | `api/tests/test_devices.py::test_list_devices_requires_the_read_key` |
| CA-07 (banco) | `infra/migrations/004_device_heartbeat.sql` | `infra/tests/test_schema_db.py::test_negative_counters_are_refused`, `::test_model_pair_is_null_together`, `::test_hb_model_version_check_mirrors_contract`, `::test_hb_model_sha256_check_mirrors_contract`, `::test_hb_app_version_check_mirrors_contract`, `::test_heartbeat_migration_runs_again_without_error`, `::test_device_columns`; `infra/tests/test_migration_files.py::test_repository_migrations_are_valid` |
| CA-08 (borda, envio) | `edge/src/qc_edge/publisher.py` (`send_heartbeat`, `device_id`), `edge/src/qc_edge/heartbeat.py` | `edge/tests/test_heartbeat.py::test_run_once_sends_one_heartbeat` (modelo dummy ONNX, 2 `pending` e 1 `dead`), `::test_run_once_without_model_sends_nulls`, `::test_send_heartbeat_posts_the_contract_with_the_key`, `::test_build_with_model_and_outbox_counts`, `::test_build_without_model`, `::test_build_caps_the_counters` |
| CA-09 (borda, nuvem fora do ar) | `edge/src/qc_edge/heartbeat.py`, `publisher.py` | `edge/tests/test_heartbeat.py::test_cloud_down_is_a_warning_and_the_outbox_does_not_change` (`ConnectError`, 503 e timeout, 3 ciclos), `::test_auth_error_stops_the_loop_with_one_error` (401 e 403), `::test_capture_keeps_working_with_the_cloud_down`, `::test_thread_ends_after_an_auth_error` e os `::test_send_heartbeat_*` |
| CA-10 (borda, condições) | `edge/src/qc_edge/cli.py` (`_build_sink`), `edge/src/qc_edge/config.py` (`HEARTBEAT_INTERVAL_S`) | `edge/tests/test_heartbeat.py::test_heartbeat_registered_with_the_publish_loop`, `::test_interval_zero_turns_the_heartbeat_off`, `::test_no_heartbeat_with_stub_model`, `::test_no_heartbeat_without_key_or_url`, `::test_invalid_interval_exits_2` (`5`, `9`, `3601`, `-1`, `abc`, `60.5`, `1e3`, com e sem `--stub-model`), `::test_valid_intervals`; `edge/tests/test_cli_cloud.py::test_loop_with_key_and_local_url` |
| CA-11 (borda, `httpx` isolado) | `edge/src/qc_edge/heartbeat.py` não importa `httpx` (só o protocolo `HeartbeatPublisher` de `publisher.py`) | `edge/tests/test_static_rules.py` (regra existente, passa com o módulo novo); o CA-17 da SPEC-007 (`edge/tests/acceptance/test_spec_007.py`) também passa |
| CA-12 (dashboard) | `dashboard/src/qc_dashboard/formatting.py` (`device_rows`, `fmt_uptime`, `DEVICE_COLUMNS`) | `dashboard/tests/test_devices.py::test_device_rows_online_simulated_and_without_heartbeat`, `::test_fmt_uptime`, `::test_last_signal_is_the_heartbeat_not_the_last_inspection` |
| CA-13 (manual) | `dashboard/views/dispositivos.py`, `dashboard/app.py`, `dashboard/src/qc_dashboard/api.py`, `data.py` | apoio: `dashboard/tests/test_devices.py::test_page_*`, `::test_app_lists_the_page`, `::test_client_devices_*`, `::test_fetch_devices_is_cached` (o CA é manual; ver abaixo) |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
# só os testes do autor desta SPEC
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q \
  packages/contracts/tests/test_heartbeat.py api/tests/test_devices.py \
  infra/tests/test_schema_db.py edge/tests/test_heartbeat.py dashboard/tests/test_devices.py
```

Resultado nesta rodada, sem o extra `train`, com `CI=true` e o banco `partqc_test`: `ruff check` e `ruff format --check` limpos; pytest com **7498 passed, 75 skipped, 6 failed** (631 s). As 6 falhas são todas testes de aceite antigos invalidados por requisitos desta SPEC, listados na seção seguinte. Os testes do autor passam todos.

## Testes de aceite antigos afetados (`docs/architecture.md` §10; ajuste do tester)

Não criei nem alterei nenhum arquivo de `tests/acceptance/`. Estes falham hoje, por consequência direta de requisitos desta SPEC:

| Arquivo | Teste | Por que falha | Requisito da SPEC-018 |
|---|---|---|---|
| `packages/contracts/tests/acceptance/test_spec_016.py` | `test_ca01_contracts_version_is_0_4_0` | asserções exatas `== "0.4.0"` | §3.1 ("Tester, ajuste de aceite antigo": vira a forma de piso) e §4.1 (`__version__ = "0.5.0"`) |
| `api/tests/acceptance/test_spec_004.py` | `test_ca28_version_expectations_migrated` | hoje passa. O par `(test_spec_016.py, qc_contracts, "0.4.0")` do `ALLOWED_EXACT` passa a apontar para `packages/contracts/tests/acceptance/test_spec_018.py` com `"0.5.0"`, no mesmo commit do tester que cria esse arquivo e converte o `test_spec_016.py` | §3.1 |
| `api/tests/acceptance/test_spec_016.py` | `test_extra_health_reports_contract_0_4_0` | `body["contract_version"] == "0.4.0"`, num teste extra; o `/health` devolve `qc_contracts.__version__`, agora `0.5.0`. Não está na lista da §3.1, então cai na regra geral do §10 (afrouxar para a forma de piso ou comparar com `qc_contracts.__version__`; renomear o teste extra é opcional e vai na tabela do test-report) | §4.1 (`__version__ = "0.5.0"`) |
| `infra/tests/acceptance/test_spec_003.py` | `test_extra_devices_columns` | o dicionário exato das colunas de `devices` não tem as 8 colunas novas | §4.2 (migração que acrescenta as colunas a `devices`) |
| `dashboard/tests/acceptance/test_spec_028.py` | `test_extra_every_cached_read_has_max_entries` | `len(decorators) == len(functions) == 6`; agora são 7 (`fetch_devices`). A intenção (toda leitura cacheada tem `ttl` e `max_entries`) continua valendo | §4.5 ("lido com o mesmo cache das outras leituras"), com a regra da SPEC-013 §4.1 (uma função por endpoint em `data.py`, e as páginas só leem por elas) |
| `edge/tests/acceptance/test_spec_009.py` | `test_extra_cli_with_key_and_url_publishes_over_real_http` | a asserção de que toda requisição recebida pela nuvem local é `POST /inspections/batch` ou `GET /health` passa a ver também `POST /api/v1/devices/edge-01/heartbeat`: o `HeartbeatLoop` é registrado nas mesmas condições do `PublishLoop`, com o padrão de 60 s, e envia logo na subida. Ajustes possíveis: tirar o heartbeat da checagem ou definir `HEARTBEAT_INTERVAL_S=0` no teste | §4.4 (registro do laço) |
| `edge/tests/acceptance/test_spec_009.py` | `test_ca16_outbox_coverage_is_at_least_80_percent` | roda o `test_spec_009.py` em subprocesso e falha só por causa do teste acima; volta a passar com aquele ajuste, sem mudar este | §4.4 (efeito transitivo) |

Testes do autor que ajustei pelo mesmo motivo: `packages/contracts/tests/test_smoke.py` (versão exata 0.5.0 e a linha do histórico), `infra/tests/test_schema_db.py::test_device_columns`, `infra/tests/test_migration_files.py::test_repository_migrations_are_valid`, `edge/tests/test_cli_cloud.py::test_loop_with_key_and_local_url` (agora `PublishLoop` + `HeartbeatLoop`), `edge/tests/conftest.py` (`HEARTBEAT_INTERVAL_S` em `EDGE_ENV_VARS`), `dashboard/tests/test_filters_data.py::test_every_cached_read_has_max_entries` (`fetch_devices`) e `dashboard/tests/conftest.py` (rota `/devices` no `MockApi` e o construtor `device_status`).

## CAs manuais (para a dupla)

- **CA-13** (Definição de pronto): 1. borda ligada com a nuvem publicada (sem `--stub-model`, com `DEVICE_API_KEY`, `CLOUD_API_URL` e `MODEL_DIR`); 2. abrir "Dispositivos" e conferir `edge-01` `online`, com o modelo, a versão e as filas (`Pendentes`, `Com falha`); 3. desligar a borda e conferir `offline` depois de 3 min (com o cache de 30 s do dashboard, pode levar até ~3,5 min); 4. depois de uma rodada do simulador, conferir `sim-01` com `Origem = simulado`, `Situação = offline` (o simulador não envia heartbeat) e o aviso `Contém dados simulados` no topo da página.
- Ordem de deploy (skill `contrato-api`): banco (`infra/migrate.py`, migração `004`) → API → dashboard → borda. Uma borda nova contra uma API anterior só registra `heartbeat failed: HTTP 404` no log, sem efeito nas inspeções.

## Decisões tomadas dentro do escopo da SPEC

1. **`device_id` do `HttpPublisher`:** a SPEC fixa `send_heartbeat(heartbeat)` sem `device_id`, e a rota exige o `device_id` no caminho. O construtor ganhou o argumento opcional, só por nome, `device_id: str | None = None`, validado com `re.fullmatch(DEVICE_ID_PATTERN, ...)` (inválido → `ValueError`). Sem ele, `send_heartbeat` levanta `ValueError`. As chamadas existentes (`HttpPublisher(url, key, ...)`) não mudam, e o CLI passa `settings.DEVICE_ID`.
2. **Um `HttpPublisher` só para o heartbeat:** o CLI cria uma segunda instância (mesma URL, chave e `device_id`) para o `HeartbeatLoop`, porque os dois laços rodam em threads diferentes e não quis depender de o `httpx.Client` ser seguro entre threads.
3. **Protocolo `HeartbeatPublisher`** em `publisher.py`, separado do `Publisher` da SPEC-009, para não obrigar os publishers existentes (nem o futuro `MqttPublisher` da SPEC-020) a implementar o heartbeat.
4. **`HeartbeatLoop(publisher, sink, inferencer, *, interval_s, app_version=qc_edge.__version__, clock=utc_now, monotonic=time.monotonic)`:** recebe o `Inferencer`, como o `create_app`, e lê o `model_info` dele; `None` = sem modelo. O primeiro heartbeat sai logo no `start()`, e os seguintes a cada `interval_s`. `uptime_s` conta a partir da construção do laço, na subida do `qc-edge`. Depois de um 401/403, `run_once` não faz mais nada e a thread termina, sem nova requisição até reiniciar. Uma falha do outbox (`SinkError`) ou um heartbeat fora do contrato pulam o ciclo com um `WARNING` sem valores; uma exceção inesperada do publisher vira um `WARNING` só com o nome da classe.
5. **Respostas do heartbeat na borda:** o corpo só é lido em 204 e em 413/422, com o prazo e o teto da SPEC-030. 413/422 viram `PublishTransientError` com o `refusal_summary` da SPEC-009 (ex.: `HTTP 422: 2 validation errors`); os outros status, `HTTP <status>`; as falhas de rede, a descrição do `httpx` sem a chave.
6. **`online` calculado no SQL** com o `now()` do banco, o mesmo relógio que grava `last_heartbeat_at` (`ONLINE_WINDOW_S = 180`, `now() - last_heartbeat_at < 180 s`). Para testar os limites, ajusta-se `last_heartbeat_at` direto no banco, como o contexto do §5 permite.
7. **Empate de `received_at` em `last_source`:** as inspeções de um mesmo lote (`/inspections/batch`) têm o mesmo `received_at` (o `now()` da transação). O desempate é `inspected_at desc` e depois `inspection_id desc`, só para o resultado ser determinístico; a regra da SPEC (maior `received_at`) não muda.
8. **Ordem de `GET /devices`:** `order by device_id collate "C"` (a ordem de `str` do Python, como os desempates da SPEC-026), `limit 500`, numa transação `read only`.
9. **403 e erros de banco no heartbeat:** um `device_id` do caminho diferente do dono da chave dá 403 depois da validação do corpo (a precedência da SPEC-004: 401 → 422 → 403), com o mesmo `detail` (`device_id does not match API key`) e o mesmo `WARNING` da rota de inspeções. Um `DataError`/`IntegrityError` no `UPDATE` vira o 422 `Value cannot be stored`, com o log só da rota, do `device_id` e do SQLSTATE (hoje inalcançável, porque os `check` espelham o contrato).
10. **Dashboard:** `Último sinal` é a hora local do último **heartbeat** (`nunca` sem heartbeat), e não o `last_seen_at`, que uma inspeção também atualiza; é a leitura coerente com o CA-12 ("sem heartbeat" → `nunca`). `Ligado há` usa `fmt_uptime`: horas inteiras e minutos com dois dígitos, sem dias e sem arredondar para cima (`7500` → `2 h 05 min`, `59` → `0 h 00 min`, horas com separador de milhar). `Modelo` e `Versão` sem valor viram `—`. A página chama `filters.render_sidebar()`, como as outras (SPEC-013 §4.2), e diz numa legenda que os filtros não se aplicam a ela. O selo é `filters.show_badge()` quando algum `last_source` é `simulated` (função pura `formatting.has_simulated_device`). Lista vazia → `st.info("Nenhum dispositivo registrado.")`.
11. **Migração:** cada `check` tem nome próprio (`devices_hb_*_check` e `devices_hb_model_pair_check`) e só é criado se não existir, no padrão da `002`.

## Observações (sem bloqueio)

1. **`docs/architecture.md`** (pelo architect, Definição de pronto): além da §4, que já cita as duas rotas, ficam desatualizados o título e a linha de versões da §3 (`qc-contracts` 0.4.0 → 0.5.0), o esquema de `devices` da §5 (as colunas da `004`) e a lista de variáveis da §6.4 (`HEARTBEAT_INTERVAL_S`). A linha "Arquivos vigentes" das "Expectativas de versão" (§10) muda junto com o `ALLOWED_EXACT`.
2. **Faixa de datas em `devices`:** a SPEC não pede `check` de faixa para `last_heartbeat_at` (como os da `002` em `inspections`). O campo só é gravado com `now()`, mas um `infinity` escrito à mão (SQL Editor) faria o `GET /devices` responder 500 ao validar o `DeviceStatus`. O `last_seen_at` já tinha a mesma exposição. Fica como possível pendência para o architect.
3. **Custo do `last_source`:** o `left join lateral` usa o índice `(device_id)` de `inspections` e ordena as inspeções de cada dispositivo para pegar a mais recente. Com o volume da demo, é desprezível; num histórico grande, um índice `(device_id, received_at)` resolveria. A rota é só de leitura (chave do dashboard) e passa pelo cache de 30 s.
4. A versão do `qc-edge` continua `0.0.0` (a SPEC não pede aumento), então os heartbeats levam `app_version = "0.0.0"`.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example` atualizado (`HEARTBEAT_INTERVAL_S`, com comentário)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
