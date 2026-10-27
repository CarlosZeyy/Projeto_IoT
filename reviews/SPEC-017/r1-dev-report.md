# SPEC-017 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-017](../../docs/specs/SPEC-017-alertas-telegram.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-017-alertas-telegram` (encadeada na SPEC-018, que está sobre a 016 e a 036) |
| Commits | `26e032e`, `680de09`, `68ae1dd`, `a5b4903`, `042077b` (e o commit deste relatório) |

## Resumo

- `api/src/qc_api/services/alerts.py` implementa a verificação (§4.1), a deduplicação e o teto por hora em `alerts_sent` (§4.3), o texto (§4.4), o envio pelo `httpx` síncrono com redação do token (§4.5), a validação da configuração (§4.6) e o laço em segundo plano (§4.2).
- O `lifespan` da API (`main.py`) inicia o laço só com `ALERTS_ENABLED=true` e a configuração válida, e o cancela no encerramento. Uma configuração inválida registra um único erro com o nome da variável, sem o valor, e a API sobe normalmente.
- A migração `infra/migrations/005_alerts.sql` cria a `alerts_sent` do §4.3, com RLS e sem políticas.
- O `.env.example`, o `api/README.md` (novo), o `README.md` da raiz e o `docs/deployment-plan.md` documentam as variáveis, o passo a passo do bot, a migração, o risco da reserva no Render e o CA-13 manual.
- Nenhuma dependência nova: o `httpx` já era dependência do `qc-api`. `uv.lock` intocado. Nenhuma chamada real ao Telegram nos testes (só `httpx.MockTransport`, mais uma trava que falha o teste se o transporte de rede real for usado em `test_alerts.py`).

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (alerta) | `api/src/qc_api/services/alerts.py` (`run_check`, `find_alerts`, `reserve_alert`, `send_message`, `format_alert_text`, `mark_delivered`) | `api/tests/test_alerts_db.py::test_out_lot_sends_one_message_and_marks_it_delivered`; `api/tests/test_alerts.py::test_text_above_the_ucl_live`, `test_send_posts_the_json_body_to_the_bot_path` |
| CA-02 (deduplicação) | `alerts.py` (`reserve_alert`: `ALERT_EXISTS` e `INSERT ... ON CONFLICT DO NOTHING RETURNING`) | `test_alerts_db.py::test_out_lot_sends_one_message_and_marks_it_delivered` (segunda verificação) |
| CA-03 (aberto e antigo) | `alerts.py` (`is_concluded`, `is_within_lookback`, `is_alertable`) | `test_alerts_db.py::test_open_lot_and_old_lot_send_nothing`, `test_idle_and_lookback_settings_are_used`; `test_alerts.py::test_concluded_after_the_idle_minutes`, `test_lookback_window` |
| CA-04 (falha do Telegram) | `alerts.py` (`send_message` nunca levanta; uma tentativa por alerta), `main.py` | `test_alerts_db.py::test_failed_send_is_kept_undelivered_and_never_retried`, `test_app_with_alerts_and_a_failing_telegram_still_ingests`; `test_alerts.py::test_send_failures`, `test_send_never_raises` |
| CA-05 (token) | `alerts.py` (`TokenRedactingFilter`, `install_token_redaction`, logs só pela classe); `config.py` (`SecretStr`) | `test_alerts_db.py::test_token_never_reaches_the_logs`; `test_alerts.py::test_send_logs_never_carry_the_token`, `test_filter_redacts_the_token_and_its_secret_part`, `test_config_and_settings_repr_hide_the_token`, `test_loop_survives_exceptions_and_logs_only_the_class` |
| CA-06 (simulado) | `alerts.py` (`find_alerts`, `format_alert_text`) | `test_alerts_db.py::test_simulated_needs_the_flag_and_is_marked`, `test_live_and_simulated_lots_with_the_same_id_are_separate_alerts`; `test_alerts.py::test_text_simulated_is_marked_at_both_ends` |
| CA-07 (desligado) | `main.py` (`app.state.alerts_task`), `alerts.py` (`start_alerts_task`) | `test_alerts.py::test_app_without_alerts_has_no_task`, `test_start_task_disabled_creates_nothing` |
| CA-08 (SEC-26-01) | `alerts.py` (`find_alerts` com `ALERT_MAX_POINTS = 3` e `ALERT_MAX_EXCLUDED = 0`, chamando `repository.lot_selection` pelo módulo, para o espião funcionar) | `test_alerts_db.py::test_lot_selection_is_called_with_integer_caps`; `test_alerts.py::test_source_calls_lot_selection_only_with_integer_caps` |
| CA-09 (teto por hora) | `alerts.py` (`reserve_alert`: `COUNT_RECENT_ALERTS` e aviso com `count=`) | `test_alerts_db.py::test_hourly_cap_skips_without_a_row`, `test_hourly_cap_counts_only_the_last_hour`, `test_hourly_cap_setting` |
| CA-10 (configuração inválida) | `alerts.py` (`load_alert_config`, `alerts_enabled`, `start_alerts_task`), `config.py`, `main.py` | `test_alerts_db.py::test_app_with_an_invalid_alert_configuration_is_healthy`; `test_alerts.py::test_start_task_invalid_logs_one_error_without_the_value`, `test_invalid_variable_is_named_without_its_value`, `test_app_with_invalid_alerts_still_starts` |
| CA-11 (banco) | `infra/migrations/005_alerts.sql` | `test_alerts_db.py::test_alerts_sent_schema`, `test_alerts_sent_checks`, `test_migration_runs_again_without_changes` |
| CA-12 (abaixo do LIC) | `alerts.py` (`format_alert_text`) | `test_alerts_db.py::test_lot_below_the_lcl`; `test_alerts.py::test_text_below_the_lcl` |
| CA-13 (manual) | `docs/deployment-plan.md` (§8, item 5, e "CA manual da SPEC-017"), `api/README.md` | manual, da dupla (abaixo) |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q api/tests/test_alerts.py                       # sem banco
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test \
  uv run pytest -q api/tests/test_alerts.py api/tests/test_alerts_db.py
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado no commit `042077b` (suíte completa, sem o extra `train`, com o banco `partqc_test`): 7800 passaram, 75 pulados e 3 falharam, detalhados em "Checagens do autor". Os testes do autor desta SPEC: 117 passaram (90 sem banco e 27 com banco).

## Interface para os testes de aceite (o que o tester precisa saber)

- `qc_api.services.alerts.run_check(pool, settings, *, now, transport=None) -> int`, com `settings` do tipo `qc_api.config.Settings` (o mesmo objeto da app). `run_check` **não** lê `ALERTS_ENABLED` (quem decide ligar é o `lifespan`), então os "demais parâmetros nos padrões" do contexto comum funcionam. Com outra variável de alerta inválida, levanta `InvalidAlertConfigError` antes de qualquer consulta. `now` precisa ter fuso.
- Os campos de alerta do `Settings` aceitam o tipo final ou a `str` do ambiente: `ALERTS_MAX_PER_HOUR=10` ou `"10"`, `ALERTS_INCLUDE_SIMULATED=True` ou `"true"`. `TELEGRAM_BOT_TOKEN` é `SecretStr`.
- `create_app(settings, *, alerts_transport=None)`: o transporte do Telegram da app (CA-04 e CA-07). `app.state.alerts_task` é a `asyncio.Task` do laço, ou `None` quando nenhum laço foi iniciado (CA-07 e CA-10).
- O laço faz a primeira verificação logo na subida e depois a cada `ALERTS_CHECK_INTERVAL_S`. Com `ALERTS_ENABLED=true`, uma app de teste com um lote fora concluído pela hora real envia logo na subida.
- O `created_at` gravado em `alerts_sent` é o `now` passado a `run_check`; o teto conta as linhas com `created_at > now − 1 h`.
- A fixture `clean_db` da raiz trunca só `inspections` e `devices`: os testes que usam `alerts_sent` precisam rodar `truncate alerts_sent`, como a fixture `db` de `api/tests/test_alerts_db.py`.
- Logs: logger `qc_api.alerts`. Erro de configuração: `alerts disabled: invalid configuration (<NOME>)`. Teto: aviso `alert skipped: hourly cap reached (count=10, max=10, lot_id=..., source=...)`. Falha de envio: `telegram send failed: ...`. O `httpx` registra a URL com `bot***`.

## Testes de aceite de SPECs anteriores afetados (`docs/architecture.md` §10)

| Arquivo | Teste | Por que falha | Requisito da SPEC-017 |
|---|---|---|---|
| `api/tests/acceptance/test_spec_018.py` | `test_extra_heartbeat_migration_is_the_next_free_number` (teste extra, sem CA) | Afirma que a `004_device_heartbeat.sql` é a **última** migração (`startswith(f"{numbers[-1]:03d}_")`); agora a última é a `005_alerts.sql` | §3.1: `infra/migrations/NNN_alerts.sql` com o próximo número livre. A intenção do teste antigo (a migração do heartbeat ocupou o próximo número livre na época, sem buracos na numeração) continua verificável, por exemplo com a numeração contígua e a do heartbeat em `004` |

O ajuste é do tester (R-07). Nenhum outro teste de aceite antigo falha por causa desta SPEC.

**Falhas pré-existentes, não causadas por esta SPEC** (a base da branch já as tem): `infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs` e `infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files` acusam `reviews/SPEC-018/r1-review-report.md:35`, que cita literalmente o padrão de URL Postgres com senha que esses testes procuram (o texto do review da SPEC-018, commit `a600404`). Não é arquivo meu nem do meu papel: fica para o orquestrador encaminhar (correção no relatório da SPEC-018 pelo reviewer, ou na branch dela).

## CA manual para o humano (CA-13)

Passo a passo completo em `docs/deployment-plan.md`, seção "CA manual da SPEC-017 (alertas no Telegram)", com a tabela de registro (hoje `pendente`):

1. criar o bot no `@BotFather` e obter o `chat_id` (comando no `api/README.md`, que lê o token do `infra/.env.api` sem deixá-lo no `argv` nem no histórico);
2. aplicar a migração `005` com o `.env.migrate` (§8, item 5), configurar o `infra/.env.api` (`ALERTS_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALERTS_INCLUDE_SIMULATED=true`) e reiniciar só a API (`docker compose -f infra/compose.yaml up -d api`);
3. rodar o simulador com o lote fora de controle entre os 3 últimos (exemplo no plano: `--lots 10 --lot-size 50 --defect-rate 0.2 --out-of-control-lots 10`), conferindo no painel que ele ficou fora;
4. conferir uma única mensagem `[SIMULADO] …` no celular depois de `ALERTS_LOT_IDLE_MINUTES`;
5. conferir que o token não aparece no `docker compose logs api` (comando no plano, com o padrão passado ao `grep` por descritor);
6. voltar `ALERTS_INCLUDE_SIMULATED=false`.

## Decisões tomadas dentro do escopo da SPEC

1. **Configuração crua no `Settings`.** As variáveis de alerta entram em `qc_api.config.Settings` sem as regras (`StrictBool | str`, `StrictInt | str`, `SecretStr` no token, `str` no chat), porque uma regra no `Settings` derrubaria a API, contra o §4.6. As regras ficam em `load_alert_config`. `Strict*` impede que um `True` passado em código vire `1`.
2. **Vazio = padrão** nos números e booleanos de alerta (uma linha `ALERTS_LOT_IDLE_MINUTES=` no `env_file` do compose não invalida nada). O token e o chat vazios continuam inválidos com os alertas ligados, como manda o §4.6.
3. **`ALERTS_ENABLED` inválido** (ex.: `sometimes`) conta como desligado e registra o mesmo erro, `alerts disabled: invalid configuration (ALERTS_ENABLED)`: os alertas nunca impedem a ingestão. Com mais de uma variável inválida, o único registro cita todos os nomes, na ordem da tabela do §4.6.
4. **Relógio único.** O `created_at` de `alerts_sent` é o `now` da verificação (não o `now()` do banco), para que o teto e as janelas usem o mesmo relógio; em produção, `now` é a hora do servidor em UTC.
5. **Ordem dentro da reserva:** primeiro "já tratado?" (sai em silêncio), depois o teto (aviso com a contagem, sem linha), depois o `INSERT ... ON CONFLICT DO NOTHING RETURNING`. Assim, um lote já enviado não gera aviso de teto a cada minuto. Um `pg_advisory_xact_lock` (de transação, válido no pooler em modo transaction) serializa essa transação curta entre workers, para o teto valer também com mais de um worker; o lock nunca é mantido durante o envio HTTP.
6. **Timeout de 5 s:** `httpx.Timeout(5.0)` por operação (conexão, escrita, cada leitura) mais um prazo total de 5 s conferido depois de cada pedaço do corpo e um teto de 64 KiB de resposta, o mesmo desenho do publisher da borda (SPEC-030). Uma leitura em andamento não é interrompida no meio: no pior caso, a requisição passa um pouco dos 5 s (até um timeout de operação a mais), sempre limitada. Fica registrado para o reviewer e o security-devops.
7. **Cliente HTTP:** `trust_env=False` (sem variáveis de proxy nem `.netrc`) e `follow_redirects=False` (um 302 é falha). O `chat_id` vai como `str`, exatamente como configurado (o Telegram aceita inteiro ou texto; o CA-01 aceita os dois).
8. **Redação do token:** um único `logging.Filter` nos loggers `httpx`, `httpcore` e nos filhos conhecidos do `httpcore` (um filtro de logger só vale para os registros criados naquele logger). Ele troca o token inteiro e a parte depois de `:` por `***`. Além disso, nenhum código desta SPEC registra mensagem de exceção ou traceback: só a classe (e o SQLSTATE nos erros de banco, pela regra do `docs/architecture.md` §4).
9. **`send_message` nunca levanta**: qualquer exceção do envio vira falha registrada pela classe (uma tentativa por alerta, linha com `delivered = false`), e os outros alertas da verificação continuam.
10. **Primeira verificação na subida** do laço, depois a cada intervalo. No encerramento, a tarefa é cancelada e aguardada; uma verificação já em andamento na thread termina sozinha (threads não são interrompíveis), limitada pelos timeouts do pool e do HTTP.
11. **Índice** `alerts_sent_created_at_idx`, para a contagem do teto a cada verificação.
12. **`api/README.md` não existia**: criado, com a configuração e a seção dos alertas; o `README.md` da raiz aponta para ele.

**Sugestão ao architect (não bloqueia):** o `docs/architecture.md` §5 lista as tabelas e as colunas das migrações `002` a `004`, mas ainda não a `alerts_sent` da `005` (o §4 já cita a tabela). Não editei o documento, que não está no §3.1 da SPEC.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (117: 90 sem banco e 27 com banco)
- [x] `.env.example` atualizado (8 variáveis novas, `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` vazios)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma dependência nova; nenhum token real ou com cara de real em código, testes ou documentos (os testes geram o token em tempo de execução)
- Suíte completa no commit `042077b`, com `CI=true` e o banco `partqc_test`, sem o extra `train`: 7800 passaram, 75 pulados, 3 falharam (11 min 12 s). As 3 falhas são as da seção "Testes de aceite de SPECs anteriores afetados": `test_spec_018.py::test_extra_heartbeat_migration_is_the_next_free_number` (ajuste do tester, decorrente do §3.1) e as 2 pré-existentes que acusam `reviews/SPEC-018/r1-review-report.md:35`
