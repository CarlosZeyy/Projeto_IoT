# SPEC-017 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-017](../../docs/specs/SPEC-017-alertas-telegram.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-017-alertas-telegram` |
| Commits | `a9da68a`, `15fa685` (e o commit deste relatório) |

## Resumo

- **RV-01 (alta):** o envio ao Telegram agora tem o **timeout total de 5 s** do §4.5. A requisição inteira (montagem do cliente, resolução de nome, conexão, escrita, linha de status, cabeçalhos e corpo) roda numa thread de trabalho *daemon*, e `send_message` espera por ela no máximo `SEND_TIMEOUT_S` (5 s, relógio de parede). Passou disso, o envio é falha (`delivered = false`, sem repetir), registrada como `telegram send failed: deadline exceeded`, e a thread é abandonada. Foi a opção (B) do reviewer, com o limite de threads abandonadas que ele sugeriu.
- Enquanto uma thread abandonada estiver viva, a verificação não reserva nem envia outro alerta: espera até 1 s por ela e, se ainda estiver viva, para com o aviso `alerts check stopped: a previous send is still running`. Os alertas não reservados saem numa verificação seguinte, se ainda estiverem na janela. No máximo uma thread fica presa por processo.
- **RV-03:** o texto é formatado **antes** da reserva. Um ponto dentro dos limites é descartado com um aviso e não grava linha, e os outros alertas da verificação seguem.
- **RV-02 (minha parte):** o passo 4 da seção de alertas do `api/README.md` passa a dizer "timeout total de 5 s (conexão, cabeçalhos, corpo e resolução de nome)" e descreve a thread abandonada. A frase do `docs/architecture.md` §4 fica com o architect.
- Sem dependência nova (R-01/R-12): só `threading` da biblioteca padrão. `uv.lock` e os `pyproject.toml` intocados.

## Rastreabilidade (critério de aceite → implementação)

Os CAs não mudaram. Mudou só o envio (`send_message`, que agora recebe o `transport` em vez do cliente), dentro do mesmo arquivo.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (alerta) | `api/src/qc_api/services/alerts.py` (`run_check`, `find_alerts`, `reserve_alert`, `send_message`, `_post`, `format_alert_text`, `mark_delivered`) | `api/tests/test_alerts_db.py::test_out_lot_sends_one_message_and_marks_it_delivered`; `api/tests/test_alerts.py::test_text_above_the_ucl_live`, `test_send_posts_the_json_body_to_the_bot_path`; `api/tests/test_alerts_deadline.py::test_fast_answer_is_delivered_without_waiting` |
| CA-02 (deduplicação) | `alerts.py` (`reserve_alert`) | `test_alerts_db.py::test_out_lot_sends_one_message_and_marks_it_delivered` |
| CA-03 (aberto e antigo) | `alerts.py` (`is_concluded`, `is_within_lookback`, `is_alertable`) | `test_alerts_db.py::test_open_lot_and_old_lot_send_nothing`, `test_idle_and_lookback_settings_are_used`; `test_alerts.py::test_concluded_after_the_idle_minutes`, `test_lookback_window` |
| CA-04 (falha do Telegram) | `alerts.py` (`send_message` nunca levanta; uma tentativa por alerta; prazo total de 5 s), `main.py` | `test_alerts_db.py::test_failed_send_is_kept_undelivered_and_never_retried`, `test_app_with_alerts_and_a_failing_telegram_still_ingests`; `test_alerts.py::test_send_failures`, `test_send_never_raises`; `test_alerts_deadline.py::test_send_ends_at_the_total_deadline` (5 casos), `test_send_with_slow_name_resolution_ends_at_the_deadline`, `test_check_stops_while_an_abandoned_send_is_alive` |
| CA-05 (token) | `alerts.py` (`TokenRedactingFilter`, `install_token_redaction`; o motivo da falha leva só inteiros e o nome da classe; a thread abandonada não registra nada) | `test_alerts_db.py::test_token_never_reaches_the_logs`; `test_alerts.py::test_send_logs_never_carry_the_token`, `test_filter_redacts_the_token_and_its_secret_part`; `test_alerts_deadline.py` (cada caso confere que nenhum registro tem a parte secreta do token) |
| CA-06 (simulado) | `alerts.py` (`find_alerts`, `format_alert_text`) | `test_alerts_db.py::test_simulated_needs_the_flag_and_is_marked`; `test_alerts.py::test_text_simulated_is_marked_at_both_ends` |
| CA-07 (desligado) | `main.py`, `alerts.py` (`start_alerts_task`) | `test_alerts.py::test_app_without_alerts_has_no_task`, `test_start_task_disabled_creates_nothing` |
| CA-08 (SEC-26-01) | `alerts.py` (`find_alerts`) | `test_alerts_db.py::test_lot_selection_is_called_with_integer_caps`; `test_alerts.py::test_source_calls_lot_selection_only_with_integer_caps` |
| CA-09 (teto por hora) | `alerts.py` (`reserve_alert`) | `test_alerts_db.py::test_hourly_cap_skips_without_a_row`, `test_hourly_cap_counts_only_the_last_hour`, `test_hourly_cap_setting` |
| CA-10 (configuração inválida) | `alerts.py` (`load_alert_config`, `alerts_enabled`, `start_alerts_task`), `config.py`, `main.py` | `test_alerts_db.py::test_app_with_an_invalid_alert_configuration_is_healthy`; `test_alerts.py::test_start_task_invalid_logs_one_error_without_the_value` |
| CA-11 (banco) | `infra/migrations/005_alerts.sql` | `test_alerts_db.py::test_alerts_sent_schema`, `test_alerts_sent_checks` |
| CA-12 (abaixo do LIC) | `alerts.py` (`format_alert_text`) | `test_alerts_db.py::test_lot_below_the_lcl`; `test_alerts.py::test_text_below_the_lcl` |
| CA-13 (manual) | `docs/deployment-plan.md`, `api/README.md` | manual, da dupla (roteiro do r1-dev-report, sem mudança) |
| §4.5 "timeout total de 5 s" (T-01, RV-01) | `alerts.py` (`send_message`, `_post`, `previous_send_running`, `SEND_TIMEOUT_S`, `ABANDONED_SEND_GRACE_S`) | `test_alerts_deadline.py::test_send_ends_at_the_total_deadline[slow-headers]`, `[header-drip]`, `[body-drip]`, `[500-slow-body]`, `[silent]`; `::test_send_with_slow_name_resolution_ends_at_the_deadline`; `::test_check_stops_while_an_abandoned_send_is_alive` |

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| r1-review-report, RV-01 (alta) | `send_message` roda `_post` numa thread *daemon* e a espera com `join(SEND_TIMEOUT_S)`. A resolução de nome, a conexão, a escrita, a linha de status, os cabeçalhos e o corpo acontecem dentro da thread, então o prazo total cobre todos eles, para qualquer transporte (o padrão de produção e os injetados nos testes). Estourou, é falha registrada só como `deadline exceeded`, e a thread é abandonada (recebe um sinal de cancelamento, que ela confere a cada bloco do corpo, além do próprio prazo). O laço não espera mais um envio preso: cada envio custa no máximo 5 s à verificação. Limite de threads abandonadas: `previous_send_running` espera até `ABANDONED_SEND_GRACE_S` (1 s) e, com uma viva, a verificação para antes de reservar o próximo alerta. Cada thread monta e fecha o próprio cliente `httpx`, então a thread principal nunca toca num cliente que uma thread abandonada ainda usa. Testes do autor, todos com servidor local em `127.0.0.1` (pelo `httpx.HTTPTransport` real) ou com um resolvedor falso: o caso do tester (cabeçalhos a 4,5 s e 1 byte a mais 4,5 s), gotejamento de cabeçalhos (1 byte por segundo, nenhuma leitura estoura sozinha), corpo em gotas (1 byte a cada 0,3 s), 500 com corpo lento, servidor mudo e DNS lento (`socket.getaddrinfo` preso, com o transporte padrão de produção). Todos terminam entre 4,9 s e 5,75 s, com `deadline exceeded` no log e sem a parte secreta do token. A decisão 6 do r1 fica substituída pela decisão 1 abaixo |
| r1-review-report, RV-02 (baixa) | `api/README.md`, passo 4: "timeout total de 5 s (conexão, cabeçalhos, corpo e resolução de nome)", mais a thread abandonada e o aviso `alerts check stopped`. O `docs/architecture.md` (bloco "Envio" do §4) é do architect e não foi tocado |
| r1-review-report, RV-03 (baixa) | `run_check` formata o texto antes de `previous_send_running` e de `reserve_alert`. Um `ValueError` vira o aviso `alert skipped: point inside the control limits (lot_id=..., source=...)` e o laço segue para o próximo alerta, sem gravar linha. Teste: `test_alerts.py::test_inconsistent_point_is_dropped_before_the_reservation` |
| r1-test-report, T-01 | Corrigido pelo RV-01. O `test_extra_total_timeout_with_slow_headers` passou a terminar em cerca de 5 s e, por isso, hoje dá `XPASS(strict)` (falha), como previsto no marcador. Retirar o `xfail` é do tester (R-07); não toquei em `api/tests/acceptance/` |

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q api/tests/test_alerts.py api/tests/test_alerts_deadline.py   # sem banco (~40 s)
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test \
  uv run pytest -q api/tests/test_alerts.py api/tests/test_alerts_db.py \
  api/tests/test_alerts_deadline.py api/tests/acceptance/test_spec_017.py
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Testes do autor desta SPEC: 126 passaram (91 em `test_alerts.py`, 8 em `test_alerts_deadline.py`, 27 em `test_alerts_db.py`). Com o aceite da SPEC-017 junto: 220 passaram e 1 falhou, o `XPASS(strict)` do T-01 descrito acima. Resultado da suíte completa em "Checagens do autor".

## Decisões tomadas dentro do escopo da SPEC

1. **Prazo total pela thread de trabalho (substitui a decisão 6 do r1).** Das duas opções do reviewer, escolhi a (B): ela vale para qualquer transporte, inclusive os injetados nos testes de aceite (o `RedirectTransport` do tester cria o próprio `httpx.HTTPTransport`, que um *network backend* próprio não alcançaria), e não depende de atributos privados do `httpx` (o `HTTPTransport` 0.28 não recebe `network_backend`). O prazo de 5 s é contado no relógio de parede a partir do início da thread e cobre tudo o que acontece nela, inclusive a montagem do cliente e a resolução de nome. O `httpx.Timeout(5.0)` por operação continua dentro da thread, para que uma thread abandonada termine sozinha na maioria dos casos (servidor mudo, conexão presa); a conferência do prazo e do cancelamento a cada bloco do corpo também continua, pelo mesmo motivo. O limite de 5 s não foi afrouxado.
2. **No máximo uma thread presa.** Uma thread abandonada não pode ser interrompida. Para não acumular, a verificação não reserva nenhum alerta enquanto houver uma viva (depois de esperar até 1 s por ela). Como nada é reservado, o §4.3 continua valendo: nenhuma linha fica com `delivered = false` sem tentativa, e o alerta pode sair numa verificação seguinte se ainda estiver na janela, como no teto por hora. A espera de 1 s é por verificação no pior caso, e só existe quando há uma thread abandonada.
3. **A thread abandonada não registra nada.** O motivo da falha volta para a thread principal, que faz o único registro (`telegram send failed: <motivo>`). O motivo leva só inteiros e o nome da classe da exceção, nunca o token nem a mensagem da exceção. Uma thread abandonada não gera um segundo registro mais tarde.
4. **Um cliente `httpx` por envio, dentro da thread.** A thread principal nunca toca num cliente que outra thread usa. Com o transporte padrão, cada mensagem abre a própria conexão TLS (no máximo 6 por verificação, 3 por origem). Com um transporte injetado, o cliente o fecha ao fim de cada envio, como o r1 já fazia ao fim de cada verificação; o `httpx.HTTPTransport` e o `MockTransport` podem ser reusados depois de fechados (conferido).
5. **Encerramento:** a thread de envio é *daemon* e não segura a saída do interpretador. A thread da verificação (`asyncio.to_thread`) fica limitada pelo timeout do pool e por 5 s por envio, mais 1 s de espera no pior caso.

**Risco residual, para o reviewer e o security-devops:** uma thread abandonada contra um servidor que goteja os cabeçalhos só termina quando o servidor fecha a conexão ou quando o `httpcore` atinge o teto de cabeçalho incompleto (o cenário do SEC-30-03). Nesse intervalo, o laço continua vivo e cada verificação para com o aviso `alerts check stopped: a previous send is still running`, em vez de ficar presa em silêncio como no r1. Valem os atenuantes do RV-01: o alvo é `https://api.telegram.org` com TLS verificado e `trust_env=False`, então isso exige o próprio Telegram degradado ou um MITM com certificado válido.

**Sugestão ao architect (RV-02, não bloqueia):** trocar no `docs/architecture.md` §4 (bloco "Envio") "timeout de 5 s" por "timeout total de 5 s (conexão, cabeçalhos, corpo e resolução de nome)".

## Testes de aceite de SPECs anteriores afetados (`docs/architecture.md` §10)

Nenhum novo nesta rodada. No arquivo de aceite desta SPEC, o `test_extra_total_timeout_with_slow_headers` dá `XPASS(strict)` porque o T-01 foi corrigido. Retirar o marcador é do tester.

## SPEC_ISSUE (se houver)

Nenhum. Os 5 s totais são viáveis, e o limite foi mantido.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (268 arquivos)
- [x] Testes unitários do autor passando (126: 91 + 8 sem banco e 27 com banco)
- [x] `.env.example` sem mudança (nenhuma variável nova; `SEND_TIMEOUT_S` e `ABANDONED_SEND_GRACE_S` são constantes)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma dependência nova; nenhuma chamada real ao Telegram nem à rede (servidores em `127.0.0.1` e resolvedor falso); tokens gerados em tempo de execução
- Suíte completa no commit `15fa685`, com `CI=true` e o banco `partqc_test`, sem o extra `train`: 7906 passaram, 75 pulados e 1 falhou (12 min 12 s). A única falha é o `XPASS(strict)` de `api/tests/acceptance/test_spec_017.py::test_extra_total_timeout_with_slow_headers`, que mostra o T-01 corrigido; o marcador sai na r2 do tester. Os 75 pulados são os de Docker, MQTT, modelo real e torch, como no r1. Diferença para o test-report do r1 (7897 + 1 `xfail`): os 9 testes novos do autor (8 em `test_alerts_deadline.py` e 1 em `test_alerts.py`).
