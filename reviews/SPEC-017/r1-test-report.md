# SPEC-017 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-017](../../docs/specs/SPEC-017-alertas-telegram.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `cf3b297` (implementação em `26e032e`…`042077b`, dev report em `5068278`, merge da SPEC-018 com a correção `5bf8b40` em `8f1cc5b`) |
| **Veredicto** | **PASS**: todos os CAs automatizados (CA-01 a CA-12) têm teste e passam, a suíte inteira passa e o ruff está limpo; nenhum `SPEC_ISSUE`. Um bug de severidade baixa fora dos CAs (T-01, prazo total do envio). O CA-13 é manual e fica pendente para a dupla. |

Os testes foram escritos a partir do texto da SPEC, em caixa-preta, antes da leitura de `qc_api/services/alerts.py` e do `lifespan`. Da implementação, antes de escrever, li só o `Settings` (`qc_api/config.py`, para saber que os campos de alerta existem), o `create_pool` e a assinatura do `lot_selection` (interfaces de SPECs anteriores), mais a seção "Interface para os testes de aceite" do dev report (`create_app(settings, *, alerts_transport=...)` e `app.state.alerts_task`). As asserções seguem o texto da SPEC.

- Banco real `partqc_test` (marcador `db`, `clean_db` da SPEC-003). A fixture `db` do arquivo trunca também `alerts_sent` e registra o dispositivo das inspeções. Inspeções inseridas por SQL com `inspected_at` controlado.
- `T` (a última inspeção do `L-005`) é o relógio real menos 11 min. Assim `now = T + 11 min` é também o relógio real, e os testes que passam pelo `lifespan` (CA-04, CA-05, CA-07, CA-10), em que o laço usa a hora real, continuam significativos.
- Telegram simulado por `httpx.MockTransport`, que registra as requisições. Nos exploratórios de timeout e de log do `httpcore`, um transporte que redireciona a requisição para um socket local em `127.0.0.1` passa pelo `httpx.HTTPTransport` real. Nenhum teste fala com o Telegram.
- O token dos CAs é o do contexto comum (`"123456" + ":" + "A" * 35`, montado em tempo de execução); os outros vêm de `secrets`. Nenhum token literal com cara de real no arquivo nem neste relatório (R-03). Senhas de banco fictícias geradas em tempo de execução, URL montada com `urlunsplit`.
- Nenhum teste roda o pytest em subprocesso (`docs/architecture.md` §10).

## Arquivos e contagem

| Arquivo | Testes | Itens de CA (`test_caNN_*`, com parametrização) | Exploratórios (`test_extra_*`) |
|---|---|---|---|
| `api/tests/acceptance/test_spec_017.py` | 95 | 21 | 74 (1 deles `xfail` estrito, T-01) |

Sem banco (`TEST_DATABASE_URL` ausente), 5 passam e 90 são pulados (marcador `db`).

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `api/tests/acceptance/test_spec_017.py::test_ca01_out_lot_sends_one_message` (devolve 1; uma requisição `POST` `https://api.telegram.org/bot<token>/sendMessage`; `chat_id` `-1001` ou `"-1001"`; `text` exatamente igual ao do CA, com `LSC = 64,5%` e `LIC = 0,0%` calculados pela fórmula do `docs/architecture.md` §3.4; linha `(L-005, live, out_of_control, delivered = true)`), `::test_ca01_limits_match_the_spec006_chart` (o `LSC`/`LIC` do texto é o `ucl`/`lcl` do `GET /api/v1/metrics/spc` da SPEC-006 para os mesmos lotes, formatado como no §4.4) | ✅ |
| CA-02 | `::test_ca02_second_check_sends_nothing` (`now = T + 12 min` → 0, nenhuma requisição, a linha continua única) | ✅ |
| CA-03 | `::test_ca03_open_lot_and_old_lot_send_nothing` (`T + 5 min` e `T + 25 h`: nenhuma requisição e `alerts_sent` vazia) | ✅ |
| CA-04 | `::test_ca04_telegram_failure_is_one_attempt[500]` e `[timeout]` (`httpx.ConnectTimeout`: sem exceção, devolve 0, `delivered = false`, a segunda verificação não faz requisição), `::test_ca04_failing_telegram_does_not_affect_ingestion[500]` e `[timeout]` (app com `ALERTS_ENABLED=true` e o transporte com falha; o laço tenta e falha na subida; `POST /api/v1/inspections` válido → 201, `/health` → 200) | ✅ |
| CA-05 | `::test_ca05_token_never_in_logs_or_responses` (`caplog` em `DEBUG` no logger raiz, no `httpx` e no `httpcore`; os três cenários, envio aceito, 500 e `ConnectTimeout` cuja mensagem contém a URL com o token; nenhum registro formatado contém o token nem a parte depois de `123456:`; app com os alertas ligados: o corpo das respostas de `/health`, `/metrics/spc`, `/lots`, `/devices`, `/openapi.json`, uma rota inexistente e um `POST` 422 não contém nenhum dos dois) | ✅ |
| CA-06 | `::test_ca06_simulated_needs_the_flag_and_is_marked` (padrão e `ALERTS_INCLUDE_SIMULATED=false`: nenhuma requisição; `true`: uma requisição com `text` que começa com `[SIMULADO] Lote L-005 fora de controle` e termina com `Origem: simulado.`; linha `(L-005, simulated, …, true)`) | ✅ |
| CA-07 | `::test_ca07_disabled_creates_no_task` (`ALERTS_ENABLED=false`, lote fora no banco: `app.state.alerts_task is None`, nenhuma tarefa `asyncio` com "alert" no nome ou na corrotina, nenhuma requisição depois de 1 s nem depois do encerramento, `alerts_sent` vazia), `::test_ca07_default_settings_create_no_task` (o padrão é desligado, mesmo com token válido); controle positivo em `::test_extra_enabled_loop_sends_at_startup` (sem ele, "nenhuma tarefa" passaria trivialmente) | ✅ |
| CA-08 | `::test_ca08_lot_selection_called_with_integer_caps` (espião em `qc_api.repositories.inspections.lot_selection` que chama o original, com `ALERTS_INCLUDE_SIMULATED` falso e verdadeiro; pelo menos uma chamada registrada; em todas, `type(max_points) is int`, `type(max_excluded) is int`, `2 <= max_points <= 10` e `max_excluded == 0`), `::test_ca08_ast_has_no_none_caps` (o `ast` de `alerts.py` tem chamada a `lot_selection` e nenhuma com `max_points=None` ou `max_excluded=None`) | ✅ |
| CA-09 | `::test_ca09_hourly_cap_skips_without_a_row` (10 linhas de outros lotes com `created_at = now − 30 min`: devolve 0, nenhuma requisição, nenhuma linha do `L-005`, um `WARNING` com a contagem 10), `::test_ca09_rows_older_than_one_hour_do_not_count` (`now − 61 min`: exatamente uma requisição) | ✅ |
| CA-10 | `::test_ca10_invalid_configuration_keeps_the_api_up[TELEGRAM_BOT_TOKEN-overrides0-]`, `[TELEGRAM_BOT_TOKEN-overrides1-abc]` e `[TELEGRAM_CHAT_ID-overrides2-x]` (lote fora no banco; `/health` → 200; exatamente um registro `alerts disabled: invalid configuration (<nome>)`, com o nome da variável e sem o valor; `alerts_task is None`; nenhuma requisição) | ✅ |
| CA-11 | `::test_ca11_alerts_sent_table` (`relrowsecurity = true`, nenhuma política em `pg_policies`, segunda inserção de `(L-001, live, out_of_control)` → `23505`, `kind='other'` → `23514`) | ✅ |
| CA-12 | `::test_ca12_lot_below_the_lcl` (4 lotes de 20 com 8 `poor` e `L-009` de 20 sem defeito: o texto contém `(abaixo do LIC)` e `defeituosas = 0`, e é exatamente `Lote L-009 fora de controle (abaixo do LIC): p = 0,0%, LSC = 63,3%, LIC = 0,7%, n = 20, defeituosas = 0. Origem: real.`, com os limites da fórmula do §3.4) | ✅ |
| CA-13 | manual (bot real, na VPS, dupla) | ⏳ pendente: registrar na Definição de pronto; roteiro no `docs/deployment-plan.md` ("CA manual da SPEC-017") e no dev report |

## Suíte completa

Ambiente do CI (`uv sync --all-packages`, sem torch), banco `partqc_test`, nenhuma outra suíte com banco rodando, no estado do commit de testes deste relatório:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
7897 passed, 75 skipped, 1 xfailed, 1 warning in 700.30s (0:11:40)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
267 files already formatted
```

O dev report registra `7800 passed, 75 skipped, 3 failed` no `042077b`. Duas das falhas (os testes `test_no_secret_material_*` que acusavam `reviews/SPEC-018/r1-review-report.md`) já estavam corrigidas pelo `5bf8b40`, mergeado nesta branch em `8f1cc5b`; a terceira é o aceite antigo da tabela abaixo. Depois do ajuste, nenhuma falha: 7800 + 3 + os 94 testes novos que passam = 7897 (mais o `xfail` do T-01). Os 75 pulados são os de Docker, MQTT, modelo real e torch, como antes. O arquivo novo foi executado mais 3 vezes seguidas (94 passed, 1 xfailed em cada), sem falha intermitente nos testes de concorrência e de tempo.

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Só a asserção afetada mudou; nenhum teste foi removido nem renomeado, e a contagem de testes coletados no arquivo é a mesma de antes.

| Arquivo | Teste | Antes → depois | Requisito da SPEC-017 | Na §3.1? |
|---|---|---|---|---|
| `api/tests/acceptance/test_spec_018.py` | `test_extra_heartbeat_migration_is_the_next_free_number` (teste extra, sem CA) | `assert _heartbeat_migration().name.startswith(f"{numbers[-1]:03d}_")` (a migração do heartbeat é a **última**) → `assert _heartbeat_migration().name.startswith("004_")`. A outra asserção (`numbers == list(range(1, len(numbers) + 1))`, numeração contígua, sem buraco) fica como estava, então a intenção do teste (a `004_device_heartbeat.sql` ocupou o próximo número livre depois da `003`, sem buraco) continua verificada; o nome continua correto | §3.1 (`infra/migrations/NNN_alerts.sql` com o próximo número livre: a `005_alerts.sql` passa a ser a última) | não (§10, listado pelo autor no dev report) |

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa (não bloqueante: fora dos CAs, limitado, só na thread do laço, nunca no caminho de uma requisição) | nenhum CA (§4.5, "timeout total de 5 s") | 1. Lote fora concluído no banco (contexto comum). 2. Servidor TCP local que lê a requisição, espera 4,5 s, manda `HTTP/1.1 200 OK` com `Content-Length: 100`, espera mais 4,5 s e manda 1 byte do corpo. 3. `run_check` com um transporte que redireciona a requisição de `api.telegram.org` para esse servidor (`httpx.HTTPTransport` real). Teste: `api/tests/acceptance/test_spec_017.py::test_extra_total_timeout_with_slow_headers`, marcado `xfail(strict=True)` com a referência a este T-01 | O envio desiste em cerca de 5 s (prazo total da requisição), conta como falha e a linha fica com `delivered = false` | Desiste em ~9,0 s (com 4,9 s por etapa, ~9,8 s); a falha e o `delivered = false` estão corretos. O `httpx.Timeout(5.0)` vale por operação (conexão, escrita, cada leitura) e o prazo de 5 s só é conferido depois de cada bloco do corpo, como o próprio dev report admite (decisão 6). Pior caso teórico: conexão, escrita, cabeçalhos e o primeiro bloco a quase 5 s cada (~20 s), mais a resolução de DNS, que nenhum timeout do `httpx` cobre. Com 6 alertas no máximo por verificação (3 por origem), uma verificação pode durar alguns minutos no pior caso; a próxima só começa depois, então não há acúmulo de threads. Quando corrigido, o `xfail` estrito vira `XPASS` e falha, para o marcador ser retirado |

## Testes exploratórios (além dos critérios)

Todos passam, exceto o `xfail` do T-01. Resumo por área:

**Regra (§4.1):** `now = T + 10 min` exatos envia ("pelo menos 10 minutos") e `T + 9 min 59 s` não; `T + 23 h 59 min` envia e `T + 24 h 01 min` não; `ALERTS_LOT_IDLE_MINUTES=30` (com `T + 11 min`) e `ALERTS_LOOKBACK_HOURS=1` (com `T + 61 min`) são respeitados; um lote fora que terminou há 2 dias não dispara ao ligar os alertas; 30 inspeções `unknown` sem grau no `L-005` não mudam o texto (ADR-021); dois lotes fora concluídos entre os 3 últimos → 2 mensagens e 2 linhas, na ordem da carta; um lote de 4 peças todas `poor` (abaixo de `min_lot_size`) nunca dispara; 5 lotes sob controle → nada; `now` sem fuso é recusado sem nenhum envio e sem linha; `now` em `-03:00` equivale ao mesmo instante em UTC.

**R-06:** com a flag ligada, o `L-005` `live` e o `L-005` `simulated` são dois alertas separados (duas linhas), e o texto `live` nunca começa com `[SIMULADO]` nem termina com `simulado` (textos exatos).

**Deduplicação, teto e workers (§4.2 e §4.3):** 6 "workers" (6 pools, `threading.Barrier`) rodam `run_check` ao mesmo tempo sobre o lote fora → exatamente uma requisição, um `run_check` devolve 1 e os outros 0, uma linha; com 9 linhas na última hora e 2 candidatos (`live` e `simulated`), 6 workers simultâneos, repetido 5 vezes → sempre exatamente 10 linhas na última hora e uma única requisição (o teto vale entre workers); 429, `200` com `{"ok": false}`, `200` com HTML e `302` (redirecionamento não seguido) são falhas com uma única tentativa e `delivered = false`, e uma segunda verificação não repete.

**Texto e requisição (§4.4 e §4.5):** o corpo JSON tem exatamente as chaves `chat_id` e `text` (sem `parse_mode`, sem imagem), `Content-Type: application/json`, sem `Authorization` nem `X-API-Key`, sem query string; o texto não tem o `device_id` nem caractere de controle.

**Token (R-03):** com um token aleatório e o `httpx.HTTPTransport` real (redirecionado a `127.0.0.1`), o `httpcore` registra em `DEBUG` e nenhum registro tem o token nem a parte secreta, enquanto o caminho requisitado é mesmo `/bot<token>/sendMessage`; `repr(Settings)` e `model_dump()` não mostram o token; o `.env.example` traz as 8 variáveis com `TELEGRAM_BOT_TOKEN=` e `TELEGRAM_CHAT_ID=` vazios e nenhum valor com o formato de token; o `api/README.md` e o `docs/deployment-plan.md` não têm valor com o formato de token, e nenhuma linha de `curl`/`wget` expande a variável do token na linha de comando. Conferido à mão: o comando do `getUpdates` no `api/README.md` passa a URL ao `curl` por `-K <(printf …)`, com `printf` builtin, então o token não vai para o `argv` de nenhum processo.

**Laço e configuração (§4.2 e §4.6):** com `ALERTS_ENABLED=true`, o laço existe (`alerts_task` e uma tarefa `asyncio` com "alert" no nome), manda a mensagem do lote fora já na subida, marca `delivered = true` e é cancelado no encerramento (`task.done()`); com o banco fora do ar (porta fechada, senha fictícia), a API sobe (`/health` 503), o laço registra a falha e **continua vivo**, e nenhum registro tem a senha nem o token. Pela variável de ambiente (`Settings()` lido do ambiente), cada valor inválido abaixo mantém a API de pé (`/health` 200), não inicia o laço, não faz requisição e gera exatamente um registro `alerts disabled: invalid configuration (...)` que nomeia a variável e nunca mostra o valor: `ALERTS_ENABLED=sometimes`; tokens com 2 ou 21 dígitos, segredo de 19 ou 101 caracteres, com `!`, sem `:`, com `\n` no fim e com espaço no início; `TELEGRAM_CHAT_ID` com 21 dígitos, `--1`, `+1`, vazio e `-1001\n`; `ALERTS_LOT_IDLE_MINUTES` `0`, `1441` e `ten`; `ALERTS_LOOKBACK_HOURS` `0` e `169`; `ALERTS_CHECK_INTERVAL_S` `29`, `3601` e `1.5e2`; `ALERTS_MAX_PER_HOUR` `0`, `61` e `-5`; `ALERTS_INCLUDE_SIMULATED=maybe`. Os limites válidos iniciam o laço sem erro: token com 3 dígitos e segredo de 20, com 20 dígitos e segredo de 100 (com `_` e `-`), `chat_id` de 20 dígitos e `42`, `1` e `1440` minutos, `168` horas, `30` e `3600` s, teto `1` e `60`, `true`/`false` na flag de simulado. `ALERTS_ENABLED` `true`, `TRUE` e `1` ligam; `false` e `0` desligam sem erro.

**Prazo e tamanho da resposta (§4.5):** servidor local que nunca responde → falha em 4 a 7,5 s (~5 s), `delivered = false`; servidor que manda os cabeçalhos e 1 byte do corpo a cada 0,3 s → falha em 4 a 7,5 s (o prazo é conferido a cada bloco); cabeçalhos lentos: T-01. Resposta 200 com um corpo `{"ok": true, "pad": "xxx…"}` de até ~100 MiB entregue em blocos de 1 KiB → menos de 2 MiB lidos (o envio para no teto de 64 KiB do autor).

## SPEC_ISSUE

Nenhum.

## Observações (não bloqueiam)

- **Corpo grande com `{"ok": true}`:** pelo texto do §4.5, "HTTP 200 com `{"ok": true}`" é sucesso; a implementação trata qualquer resposta acima de 64 KiB como falha (teto do autor, decisão 6, mesmo desenho da SPEC-030). O Telegram responde a um `sendMessage` com um JSON pequeno, então não muda nada na prática, e o teto evita ler um corpo sem limite. Fica registrado para o reviewer e o security-devops; o teste exploratório só exige que o corpo não seja lido inteiro.
- **Espaços na configuração:** os inteiros aceitam espaços em volta (`" 10 "` → 10) e zeros à esquerda (`"010"` → 10), e o valor vazio vira o padrão (decisão 2 do autor); os booleanos aceitam `yes`/`on`/`off` (pydantic) e o vazio vira `false`, mas `" true "` com espaços é inválido (os alertas ficam desligados, com o erro de configuração). Tudo dentro de "inteiro de … a …"/"booleano"; a assimetria é só uma nota. O token e o `chat_id` com espaço ou `\n` são inválidos, como manda o `re.fullmatch` do §4.6.
- **`created_at` de `alerts_sent`:** gravado com o `now` da verificação (decisão 4 do autor), e não com o `default now()` do banco, que só vale para inserções manuais. O teto conta `created_at > now − 1 h`. Como os testes usam `now` próximo da hora real, os CAs passam nas duas leituras.
- **Encerramento:** o `lifespan` cancela a tarefa, mas uma verificação já em andamento na thread termina sozinha depois do encerramento (limitada pelos timeouts do pool e do HTTP, e pelo T-01); o dev report registra isso (decisão 10).
- **Filtro de redação:** cobre só os loggers `httpx` e `httpcore` (e os filhos conhecidos do `httpcore`); os demais registros não têm o token porque o código desta SPEC só registra classes de exceção. O CA-05 e o exploratório com o `httpcore` real confirmam nos cenários testados; um logger novo de uma dependência (ex.: `hpack`, se um dia o HTTP/2 for ligado) não seria coberto pelo filtro.
- **`docs/architecture.md` §5** ainda não lista a `alerts_sent` da `005` (sugestão ao architect já registrada no dev report).

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
