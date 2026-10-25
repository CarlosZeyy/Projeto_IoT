# SPEC-017 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-017](../../docs/specs/SPEC-017-alertas-telegram.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `728e4a9` (correção em `a9da68a` e `15fa685`, dev report em `653537f`, `docs/architecture.md` do architect em `728e4a9`) |
| **Veredicto** | **PASS**: os CAs automatizados (CA-01 a CA-12) têm teste e passam, a suíte inteira passa e o ruff está limpo. O T-01 do r1 (prazo total do envio) está corrigido, e o `xfail` estrito saiu. Nenhum bug novo e nenhum `SPEC_ISSUE`. O CA-13 é manual e continua pendente para a dupla. |

O que esta rodada fez:

- **T-01 (r1), RV-01:** retirei o `xfail(strict=True)` de `test_extra_total_timeout_with_slow_headers`, que agora passa (cerca de 5,0 s).
- Escrevi os testes novos do prazo total **antes** de ler o `send_message` da r2, a partir do §4.5 ("timeout total de 5 s") e dos cenários que o reviewer reproduziu no RV-01. Da r2, antes de escrever, li só o dev report: o texto do aviso `alerts check stopped: a previous send is still running`, a regra de uma thread abandonada por processo e o fato de que `transport=None` usa o transporte padrão de produção. Depois li a implementação para procurar o que os testes não cobriam.
- Ferramentas, como no r1: servidor TCP local em `127.0.0.1` com o `httpx.HTTPTransport` real (`RedirectTransport`), ou `socket.getaddrinfo` trocado por um resolvedor que trava. Nenhum teste fala com o Telegram, e nenhuma consulta de nome sai da máquina. Os tokens dos testes novos vêm de `secrets` em tempo de execução, e nenhum literal com formato de credencial entrou no arquivo nem neste relatório.
- Cada teste novo libera o próprio servidor (ou o resolvedor) e espera a thread abandonada terminar antes de sair. Assim, o limite de uma thread abandonada por processo não vaza para o teste seguinte.

## Arquivos e contagem

| Arquivo | Testes | Itens de CA (`test_caNN_*`, com parametrização) | Exploratórios (`test_extra_*`) |
|---|---|---|---|
| `api/tests/acceptance/test_spec_017.py` | 101 (r1: 95) | 21 | 80 (6 novos, 0 `xfail`) |

Sem banco (`TEST_DATABASE_URL` ausente), os testes do marcador `db` são pulados, como no r1.

## Cobertura dos critérios de aceite

Os CAs não mudaram na r2, e os testes deles também não: os 21 itens passam sem alteração. O detalhe de cada teste está no `r1-test-report.md`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `api/tests/acceptance/test_spec_017.py::test_ca01_out_lot_sends_one_message`, `::test_ca01_limits_match_the_spec006_chart` | ✅ |
| CA-02 | `::test_ca02_second_check_sends_nothing` | ✅ |
| CA-03 | `::test_ca03_open_lot_and_old_lot_send_nothing` | ✅ |
| CA-04 | `::test_ca04_telegram_failure_is_one_attempt[500]` e `[timeout]`, `::test_ca04_failing_telegram_does_not_affect_ingestion[500]` e `[timeout]`; para o prazo total, também os exploratórios da r2 abaixo | ✅ |
| CA-05 | `::test_ca05_token_never_in_logs_or_responses`; nos cenários de prazo, também os exploratórios da r2 (nenhum registro, de nenhum logger e em `DEBUG`, tem o token nem a parte secreta, inclusive os do `httpcore` emitidos pela thread abandonada) | ✅ |
| CA-06 | `::test_ca06_simulated_needs_the_flag_and_is_marked` | ✅ |
| CA-07 | `::test_ca07_disabled_creates_no_task`, `::test_ca07_default_settings_create_no_task` | ✅ |
| CA-08 | `::test_ca08_lot_selection_called_with_integer_caps`, `::test_ca08_ast_has_no_none_caps` | ✅ |
| CA-09 | `::test_ca09_hourly_cap_skips_without_a_row`, `::test_ca09_rows_older_than_one_hour_do_not_count` | ✅ |
| CA-10 | `::test_ca10_invalid_configuration_keeps_the_api_up[...]` (3 casos) | ✅ |
| CA-11 | `::test_ca11_alerts_sent_table` | ✅ |
| CA-12 | `::test_ca12_lot_below_the_lcl` | ✅ |
| CA-13 | manual (bot real, na VPS, dupla) | ⏳ pendente (roteiro no `docs/deployment-plan.md`, sem mudança) |

## Achados do r1: conferência

| Achado | Teste | Resultado |
|---|---|---|
| T-01 (r1-test-report) / RV-01 (r1-review-report), cabeçalhos a 4,5 s e mais 1 byte do corpo a 4,5 s | `::test_extra_total_timeout_with_slow_headers` (sem `xfail`) | ✅ ~5,0 s (r1: ~9 s) |
| RV-01, cabeçalhos em gotas (1 byte por segundo, nenhuma leitura estoura o timeout de operação) | `::test_extra_r2_total_deadline_against_a_dripping_server[header-drip]` | ✅ ~5,0 s (o reviewer mediu 14 s no r1) |
| RV-01, corpo em gotas (cabeçalhos na hora, `Content-Length: 100000`, 1 byte por segundo) | `::...[body-drip]` | ✅ ~5,0 s |
| RV-01, servidor mudo | `::...[silent]` (e o `test_extra_total_timeout_of_5_seconds[silent]` do r1) | ✅ ~5,0 s |
| RV-01, DNS lento (`getaddrinfo` de `api.telegram.org` travado, transporte padrão de produção, `transport=None`) | `::test_extra_r2_total_deadline_with_slow_name_resolution` | ✅ ~5,0 s; uma única consulta de nome, para `api.telegram.org` |
| RV-01, no máximo uma thread abandonada por processo | `::test_extra_r2_at_most_one_abandoned_send_per_process` | ✅ |
| RV-02, "timeout total" na documentação | leitura de `api/README.md` (passo 4) e do bloco "Envio" do `docs/architecture.md` §4 | ✅ os dois dizem "timeout total de 5 s" e citam resolução de nome, conexão, cabeçalhos e corpo |
| RV-03, texto formatado antes da reserva | `::test_extra_r2_inconsistent_point_leaves_no_row` | ✅ |

O que cada teste do prazo confere, nos quatro cenários (cabeçalhos em gotas, corpo em gotas, mudo e DNS lento):

1. `run_check` devolve 0 entre 4,5 s e 6,0 s;
2. a linha `(L-005, live, out_of_control)` fica com `delivered = false`;
3. o servidor recebeu exatamente uma conexão (no DNS, houve uma consulta de nome), e o caminho foi `/bot<token>/sendMessage`;
4. depois que o servidor solta a conexão (ou o resolvedor é liberado), a thread abandonada termina, e nenhuma thread fica viva além das que existiam antes do teste;
5. uma nova verificação, com o servidor já respondendo `{"ok": true}`, devolve 0 e não abre nova conexão (uma tentativa por alerta, §4.3);
6. nenhum registro capturado (`caplog` em `DEBUG` no raiz, no `httpx` e no `httpcore`) tem o token nem a parte depois de `:`.

O teste do limite de threads usa dois candidatos (`L-005` `live` e `simulated`, com `ALERTS_INCLUDE_SIMULATED=true`) e um servidor de cabeçalhos em gotas. Ele confere:

1. a primeira verificação devolve 0 em menos de 7,5 s (5 s do envio e até 1 s de espera), com uma linha só (`delivered = false`), uma conexão, uma thread viva além da linha de base e um aviso `alerts check stopped: a previous send is still running`;
2. a segunda verificação, com a thread ainda viva, para em menos de 3 s, sem reservar linha, sem conexão nova, sem thread nova e com um segundo aviso;
3. depois que a thread termina, a terceira verificação envia o candidato pendente (devolve 1, segunda conexão, linha com `delivered = true`), e a linha que falhou continua `delivered = false`, sem nova tentativa.

O teste do RV-03 embrulha o `build_p_chart` da SPEC-006. É uma dependência, e não a unidade testada, e é o único jeito de alcançar o caso, que é inalcançável com a carta real. O embrulho devolve o `L-005` `live` com `p` entre os limites e `out_of_control = true`. O teste confere que essa linha não é gravada, que um aviso cita o lote e que o alerta `simulated` da mesma verificação sai normalmente (devolve 1, texto exato do §4.4, linha `delivered = true`).

## Suíte completa

Ambiente do CI (`uv sync --all-packages`, sem torch), banco `partqc_test`, nenhuma outra suíte com banco rodando, no estado do commit de testes deste relatório:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
7913 passed, 75 skipped, 1 warning in 725.57s (0:12:05)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
268 files already formatted
```

Conta com o dev report (`7906 passed, 75 skipped, 1 failed` no `15fa685`): a falha era o `XPASS(strict)` do T-01, que agora passa sem o marcador (7907), e os 6 exploratórios novos completam 7913. Os 75 pulados são os de Docker, MQTT, modelo real e torch, como no r1. Nenhuma falha.

O arquivo de aceite desta SPEC também foi executado 3 vezes seguidas (`101 passed` em cada, ~57 s), sem falha intermitente nos testes de tempo e de concorrência.

## Ajustes em testes de aceite de SPECs anteriores (`docs/architecture.md` §10)

Nenhum novo nesta rodada. O ajuste do r1 em `api/tests/acceptance/test_spec_018.py::test_extra_heartbeat_migration_is_the_next_free_number` continua como estava. No arquivo desta SPEC, a única mudança em teste existente foi retirar o `xfail` do T-01 e acrescentar a referência ao T-01 na docstring; as asserções são as mesmas.

## Bugs encontrados

Nenhum bug novo. O T-01 do r1 está corrigido.

## Testes exploratórios (além dos critérios)

Os seis testes `test_extra_r2_*` acima, mais:

- **Encerramento do processo com envio preso:** um script avulso (fora do pytest) chama `send_message` contra um servidor local de cabeçalhos em gotas. O envio falha em 5,02 s (`deadline exceeded`), a thread abandonada ainda está viva, e o processo inteiro termina em ~5,4 s. A thread *daemon* não segura a saída do interpretador, como diz a decisão 5 do dev report.
- **Reuso do transporte injetado depois de uma thread abandonada:** no teste do limite, a terceira verificação usa o mesmo `RedirectTransport` (e o mesmo `httpx.HTTPTransport` interno) que a thread abandonada fechou ao terminar, e o envio funciona.
- **Ordem no `run_check` (leitura do código depois dos testes):** a formatação vem antes de `previous_send_running`, e esta vem antes de `reserve_alert`, o que bate com o dev report e com o teste do RV-03. A resolução de nome, a conexão e a leitura acontecem dentro de `_post`, na thread de trabalho. O DNS lento confirma isso de fora: o tempo para em ~5 s mesmo com o `getaddrinfo` preso por 60 s.

## Observações (não bloqueiam)

- **Corrida na borda do prazo:** se a resposta chegar logo depois de `join(5 s)` e antes da conferência de `outcome`, o envio conta como falha (`delivered = false`) mesmo que o Telegram tenha aceitado a mensagem. É a semântica normal de um prazo (o §4.5 trata o timeout como falha), e o efeito, no pior caso, é uma mensagem entregue com a linha marcada como não entregue, sem duplicação.
- **Risco residual registrado pelo autor:** contra um servidor que goteja cabeçalhos para sempre, a thread abandonada só termina quando o servidor fecha a conexão ou quando o `httpcore` atinge o teto de cabeçalho incompleto. Nesse intervalo, cada verificação para em ~1 s com o aviso e nenhum alerta sai. O comportamento está testado (o laço não trava e não acumula threads); fica para o security-devops, com os atenuantes já registrados (TLS verificado para `api.telegram.org`, `trust_env=False`).
- **Encerramento da API:** com uma verificação em andamento na thread do `asyncio.to_thread`, ela agora dura no máximo ~5 s por envio, mais 1 s de espera, antes de terminar sozinha. No r1, o T-01 deixava isso sem limite prático.
- As observações do r1 sobre o teto de 64 KiB da resposta, os espaços na configuração, o `created_at` e o alcance do filtro de redação continuam valendo, sem mudança na r2.

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
