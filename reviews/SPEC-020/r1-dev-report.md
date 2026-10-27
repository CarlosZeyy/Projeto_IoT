# SPEC-020 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-020](../../docs/specs/SPEC-020-mqtt.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-020-mqtt` (encadeada na SPEC-038, sobre 017, 018, 016 e 036) |
| Commits | `3012178` (dependência), `f230961` (transporte, publisher, ponte, configuração e testes), `da8a877` (README), `31e4c3a` (prazo único de conexão, PUBACK e resposta), mais o commit deste relatório |

## Resumo

- `qc_edge.mqtt_transport`: Protocol `MqttTransport` (`connect`, `publish` com propriedades e espera do PUBACK, `subscribe` com callback, `disconnect`), `MqttMessage` (tópico, payload, `ResponseTopic`, `CorrelationData`, propriedades de usuário), `PahoMqttTransport` (paho-mqtt 2.1.0, `MQTTv5`, usuário e senha; o **único** módulo do `qc_edge` que importa `paho`) e `InMemoryBroker`/`InMemoryTransport` (entrega síncrona e determinística, `stop()`/`start()`, sem rede).
- `qc_edge.mqtt_publisher.MqttPublisher`: implementa o `Publisher` da SPEC-009. Publica o `BatchCreate` em `partqc/v1/<device_id>/batch` (e o health, vazio, em `.../health`) com `ResponseTopic` `partqc/v1/<device_id>/reply/<sessão aleatória>` e `CorrelationData` de 16 bytes, QoS 1, e espera a resposta com a mesma correlação: `ok` → `PublishResult` (mesma validação do `HttpPublisher`), `rejected` → `PublishRejectedError`, `auth` → `PublishAuthError`, o resto → `PublishTransientError`. O PUBACK nunca marca nada como enviado; o `PublishLoop` não mudou.
- `qc_edge.mqtt_bridge` (`python -m qc_edge.mqtt_bridge`): assina só `batch` e `health` do `DEVICE_ID`, valida o `BatchCreate`, chama o `HttpPublisher` (o `httpx` continua só em `publisher.py`) e responde `ok`/`rejected`/`auth`/`transient`. Sem estado; logs só com contagem, `result` e tópico; código 0 em SIGINT/SIGTERM, 2 com configuração inválida.
- Configuração (`qc_edge.config`): `EDGE_PUBLISHER`, `MQTT_HOST` (só loopback), `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_RESPONSE_TIMEOUT_S` e `BridgeSettings`; escolha do publisher no `qc_edge.cli`.
- `edge/mosquitto/partqc.conf`, `edge/README.md` (seção "Transporte MQTT" e o roteiro do CA-12), `.env.example`, marcador `mqtt` no `pyproject.toml` da raiz.

## Dependência nova

| Pacote | Versão travada no `uv.lock` | Licença | Fonte conferida | Onde |
|---|---|---|---|---|
| `paho-mqtt` | **2.1.0** (wheel `paho_mqtt-2.1.0-py3-none-any.whl`, sha256 `6db9ba9b34ed5bc6b6e3812718c7e06e2fd7444540df2455d2c51bd58808feee`, publicada em 2024-04-29) | `EPL-2.0 OR BSD-3-Clause` | <https://pypi.org/pypi/paho-mqtt/json> (campo `license`, consultado em 2026-10-26) e o `METADATA` do pacote instalado (`License: EPL-2.0 OR BSD-3-Clause`) | só `edge/pyproject.toml` (`paho-mqtt>=2.1,<3`); nenhuma dependência de runtime (o extra `proxy` com `pysocks` não é pedido) |

- R-12: `paho-mqtt` não está no fecho de dependências do `qc-api` nem do `qc-dashboard` (`edge/tests/test_mqtt_config.py::test_paho_is_not_in_the_api_or_dashboard_closure`, sobre o `tests/lockgraph.py` da SPEC-001). Nada de torch/onnxruntime novo.
- R-01: o broker é o Mosquitto local (software livre, repositório `extra` do Arch, sem cartão); nenhum broker na nuvem, nenhum serviço novo.

## Rastreabilidade (critério de aceite → implementação)

Arquivos de testes do autor em `edge/tests/`. "e2e" = `PublishLoop` → `MqttPublisher` → `InMemoryBroker` → `MqttBridge` → `HttpPublisher` → `FakeCloud` idempotente da SPEC-009, com relógio manual.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (entrega) | `mqtt_publisher.py`, `mqtt_bridge.py`, `mqtt_transport.py` | `test_mqtt_bridge.py::test_end_to_end_delivery` (20 itens, 20 gravações, todas `sent`); `test_mqtt_publisher.py::test_ok_returns_the_results_and_the_request_is_a_batch_create` (a mensagem valida como `BatchCreate`) |
| CA-02 (R-05, resposta perdida) | `mqtt_bridge.py` (sem estado), `mqtt_publisher.py` (timeout) | `test_mqtt_bridge.py::test_lost_answer_is_resent_and_deduplicated` (`InMemoryBroker.intercept` descarta a 1ª resposta; 2 lotes na API, 5 gravações) |
| CA-03 (RNF-04) | `mqtt_transport.py` (`InMemoryBroker.stop/start`), `mqtt_publisher.py` | `test_mqtt_bridge.py::test_broker_down_then_back` (100 itens, broker parado por 120 s do relógio injetado, nenhum duplicado, todos `sent`); `test_mqtt_publisher.py::test_broker_down_is_transient_and_recovers`, `::test_broker_down_before_the_first_connect` |
| CA-04 (sem ponte = sem confirmação) | `mqtt_publisher.py` | `test_mqtt_bridge.py::test_without_bridge_nothing_is_sent` (PUBACK = 1, 3 linhas `pending` com `attempts == 1`); `test_mqtt_publisher.py::test_no_bridge_times_out_after_the_puback` |
| CA-05 (recusa) | `mqtt_bridge.py` (`_batch`), `mqtt_publisher.py` (`rejected_detail`) | `test_mqtt_bridge.py::test_rejected_item_becomes_dead_by_bisection` (`last_error == "HTTP 422: Value cannot be stored"`, 3 `sent`, nenhuma resposta com o `input` ecoado), `::test_publisher_errors_map_to_results`; `test_mqtt_publisher.py::test_rejected_carries_the_summary`, `::test_rejected_detail_is_one_cut_line` |
| CA-06 (autenticação) | `mqtt_bridge.py`, `mqtt_publisher.py` | `test_mqtt_bridge.py::test_auth_error_pauses_the_loop` (`auth_error`, nenhuma publicação no ciclo seguinte); `test_mqtt_publisher.py::test_auth` |
| CA-07 (health) | `mqtt_publisher.py` (`check_health`), `mqtt_bridge.py` (`_health`) | `test_mqtt_bridge.py::test_health_through_the_bridge`, `::test_health`; `test_mqtt_publisher.py::test_health_ok`, `::test_health_not_ok`, `::test_health_without_bridge_is_false_within_the_timeout`, `::test_health_with_broker_down`, `::test_connection_wait_is_inside_the_response_timeout` |
| CA-08 (configuração) | `config.py` (`EdgeSettings`, `BridgeSettings`, `config_error_message`, `missing_*`), `cli.py` (`_build_sink`, `_build_publisher`), `mqtt_bridge.py` (`main`) | `test_mqtt_config.py::test_invalid_edge_publisher_exits_2_with_the_message` (stderr com `EDGE_PUBLISHER must be http or mqtt`), `::test_remote_mqtt_host_exits_2`, `::test_mqtt_without_credentials_exits_2`, `::test_edge_publisher_refused_with_the_exact_message`, `::test_mqtt_host_refused`, `::test_mqtt_port_refused`, `::test_response_timeout_refused`; `test_mqtt_bridge.py::test_main_invalid_configuration_exits_2`, `::test_module_without_device_api_key_exits_2` (subprocesso, código 2), `::test_main_unknown_argument_exits_2` |
| CA-09 (segredos, R-03) | todos os módulos novos (mensagens fixas; `paho` sem logger) | `test_mqtt_bridge.py::test_no_secret_nor_payload_in_the_logs`, `::test_logs_have_only_counts_result_and_topic`, `::test_main_runs_until_the_stop_event`, `::test_module_exits_0_on_sigterm_with_the_broker_down`; `test_mqtt_config.py::test_mqtt_publisher_in_the_loop`, `::test_password_is_a_secret`; `test_mqtt_publisher.py::test_nothing_is_logged_with_the_payload`; `test_mqtt_transport.py::test_paho_refused_connack_names_only_the_reason`, `::test_in_memory_handler_error_is_logged_without_payload` |
| CA-10 (isolamento, R-12) | `mqtt_transport.py`, `edge/pyproject.toml`, `uv.lock` | `test_mqtt_config.py::test_only_the_transport_imports_paho`, `::test_paho_is_not_in_the_api_or_dashboard_closure`; `test_static_rules.py::test_no_http_client_outside_the_publisher` (existente, continua passando) |
| CA-11 (broker real, marcador `mqtt`) | `mqtt_transport.py` (`PahoMqttTransport`), `edge/tests/mosquitto_support.py`, fixture `mosquitto_broker` e hook do marcador em `edge/tests/conftest.py` | `test_mqtt_bridge.py::test_real_broker_end_to_end` (CA-01 com o transporte real), `::test_real_broker_restart_restores_the_subscriptions`; `test_mqtt_transport.py::test_real_broker_round_trip_with_properties`, `::test_real_broker_refuses_a_client_without_password` (anônimo e senha errada: `refused the connection`) |
| CA-12 (manual) | `edge/README.md` ("Transporte MQTT" e "Teste manual MQTT (CA-12 da SPEC-020)"), `edge/mosquitto/partqc.conf` | manual (dupla) |

Outros testes do autor: a tradução de mensagens e propriedades do `paho` (`test_paho_message_conversion`, `test_paho_properties_conversion`), as reassinaturas a cada CONNACK (`test_paho_on_connect_sends_every_subscription`), o despacho fora da thread de rede (`test_paho_handlers_run_in_the_dispatcher_thread`), a correlação (`test_unknown_correlation_is_discarded`, `test_late_answer_of_an_earlier_request_is_discarded`, `test_answer_for_another_session_is_not_received`), a resposta malformada (`test_malformed_ok_is_transient`, `test_ok_with_other_ids_is_transient`, `test_ok_in_another_order_is_transient`), o pedido sem propriedades ou com `ResponseTopic` fora do padrão (`test_request_without_properties_is_ignored`, `test_response_topic_outside_the_reply_topics_is_ignored`) e o `.env.example`/`partqc.conf`/marcador (`test_env_example_documents_the_variables`, `test_mosquitto_example_config`, `test_mqtt_marker_is_declared`). São 178 testes novos (174 rodam sem broker; 4 com o marcador `mqtt`).

## Apoio para o tester (sem mudar `tests/acceptance/`)

- `InMemoryBroker()`: `client(client_id)` devolve um `InMemoryTransport`; `stop()`/`start()`; `published` (toda publicação com PUBACK, em ordem) e `published_on(filtro)`; `intercept = (message) -> bool` (`False` = PUBACK sem entrega, para o CA-02). `InMemoryTransport.pubacks` conta os PUBACKs (CA-04).
- A ponte nos testes: `MqttBridge(broker.client("bridge"), HttpPublisher(..., transport=FakeCloud().transport), device_id).start()`; "ponte desligada" = `bridge.stop()` (desconecta e remove as assinaturas).
- `mqtt_bridge.main(argv, *, transport_factory=..., stop_event=...)` permite rodar o `main` sem broker; `python -m qc_edge.mqtt_bridge` em subprocesso também funciona (testes do autor).
- Broker real: fixture `mosquitto_broker` (porta livre de `127.0.0.1`, usuário e senha aleatórios, `stop()`/`restart()`), definida em `edge/tests/conftest.py` e válida também para `edge/tests/acceptance/`. O hook do marcador pula os testes `mqtt` sem `PARTQC_MQTT_TESTS=1` ou sem `mosquitto` e `mosquitto_passwd` no `PATH`.

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q edge/tests/test_mqtt_transport.py edge/tests/test_mqtt_publisher.py \
  edge/tests/test_mqtt_bridge.py edge/tests/test_mqtt_config.py
uv run pytest -q                                   # suíte inteira, sem TEST_DATABASE_URL e sem CI=true
PARTQC_MQTT_TESTS=1 uv run pytest -q -m mqtt edge/tests   # broker real (mosquitto instalado)
```

Resultado nesta rodada (sem `TEST_DATABASE_URL`, sem `CI`):

- `ruff check .` e `ruff format --check .`: limpos (281 arquivos).
- `pytest -q` (suíte inteira, antes do commit `31e4c3a`): **7364 passed, 1162 skipped** (banco, Docker e `mqtt`), 0 falhas. Depois do `31e4c3a`, `pytest -q edge/tests`: **2627 passed, 9 skipped**.
- Marcador `mqtt` com broker real: **4 passed**. O `mosquitto` não está instalado nesta máquina (é o passo 1 do §3.3, trabalho humano), então rodei com o Mosquitto **2.1.2** da imagem oficial `eclipse-mosquitto:2`, por dois scripts locais fora do repositório que chamam `docker run --network host` como `mosquitto` e `mosquitto_passwd`. A versão é a mesma do pacote do Arch citado na SPEC, mas o registro oficial do CA-11 deve ser feito com o pacote instalado (`sudo pacman -S mosquitto`).

## Decisões tomadas dentro do escopo da SPEC

1. **`ResponseTopic` só no espaço da resposta.** A ponte só responde a um pedido cujo `ResponseTopic` seja `partqc/v1/<DEVICE_ID>/reply/<sessão>` (`<sessão>` de 1 a 64 caracteres `[A-Za-z0-9_-]`), a forma da §4.1; outro é ignorado com aviso, como o pedido sem `ResponseTopic`. Assim, um cliente do broker não consegue usar a ponte para publicar em outro tópico (por exemplo, no `batch`). Não muda nenhum CA.
2. **Leitura do `.env`.** Como o `qc-edge` (SPEC-007), a ponte lê só o ambiente do processo; o README e o `.env.example` usam `uv run --env-file .env --package qc-edge python -m qc_edge.mqtt_bridge`. "Lê do `.env`" foi lido como "as variáveis do `.env`", a convenção do projeto.
3. **Validação das `MQTT_*`.** `MQTT_HOST`, `MQTT_PORT` e `MQTT_RESPONSE_TIMEOUT_S` são validadas em toda subida (como o `HEARTBEAT_INTERVAL_S`), com ou sem `EDGE_PUBLISHER=mqtt`, porque a tabela da §4.5 não condiciona a regra. `MQTT_USERNAME` e `MQTT_PASSWORD` são exigidas sempre que `EDGE_PUBLISHER=mqtt`, inclusive com `--stub-model` ou sem chave e URL (a SPEC diz "obrigatórias com `EDGE_PUBLISHER=mqtt`"); a mensagem é `invalid configuration: MQTT_PASSWORD: required with EDGE_PUBLISHER=mqtt`.
4. **Mensagem do `EDGE_PUBLISHER`.** O erro usa um `PydanticCustomError` com o texto `EDGE_PUBLISHER must be http or mqtt`, e o formatador de erros (`config_error_message`, movido do `cli.py` para o `config.py`, para a ponte usar o mesmo) não repete o nome da variável quando a mensagem já começa com ela. O stderr mostra `invalid configuration: EDGE_PUBLISHER must be http or mqtt`. As outras mensagens não mudaram.
5. **Prazo único.** A conexão, o PUBACK e a resposta da ponte dividem um só prazo de `response_timeout_s` (o `MqttTransport.connect` e o `publish` recebem um `timeout_s` opcional). Assim, o `check_health` devolve `False` dentro de `MQTT_RESPONSE_TIMEOUT_S` também com o broker fora do ar (CA-07).
6. **Conexão preguiçosa.** O `MqttPublisher` assina a resposta e conecta na primeira chamada (e de novo depois de uma falha), nunca no construtor, para a borda subir com o broker desligado. O `PahoMqttTransport` reconecta sozinho (`reconnect_delay_set(1, 30)`) e reenvia as assinaturas a cada CONNACK (`clean_start=True`); `publish` sem conexão falha na hora, em vez de deixar o `paho` enfileirar.
7. **Despacho fora da thread de rede.** Os callbacks rodam numa thread de despacho do transporte (fila de até 1000 mensagens), porque a ponte publica a resposta e espera o PUBACK dentro do callback, o que travaria na thread de rede do `paho`.
8. **Identificadores de cliente.** `partqc-edge-<DEVICE_ID>` e `partqc-bridge-<DEVICE_ID>` (um de cada por dispositivo, como o broker exige). O heartbeat continua por HTTP, direto da borda (§3.2).
9. **`parse_batch_results`.** A validação do `BatchResult` (`_parse_results` do `publisher.py`) virou pública com o mesmo corpo, para o `MqttPublisher` usar a mesma regra sem duplicá-la.
10. **Resumo da recusa no publisher.** O payload de `rejected` é decodificado em UTF-8 (com substituição), cortado em 240 caracteres (o resumo da SPEC-009 tem no máximo `HTTP <status>: ` + 200), e cada caractere de controle vira `?`, como o `refusal_summary`.

## Observações (não bloqueiam)

- **Reenvio pelo `paho`.** Se o PUBACK de um lote não chegar no prazo, o `paho` pode reenviar a mensagem depois de reconectar. A resposta a ela tem uma correlação que já não está pendente e é descartada, e a API responde `duplicate` (R-05). Está documentado no módulo.
- **`partqc.conf`.** O `password_file` traz `/home/<usuario>/...` (o Mosquitto não expande `~`): o broker só sobe depois de trocar `<usuario>`, como diz o comentário do arquivo e o README.
- **`docs/architecture.md`.** A §6.2 e a §10 já citam a SPEC-020; a §6.4 (lista de variáveis da borda) ainda não tem `EDGE_PUBLISHER` e as `MQTT_*`. A Definição de pronto atribui a documentação da arquitetura ao architect.

## Testes de aceite de SPECs anteriores afetados

Nenhum. A suíte inteira passou sem alterar nenhum arquivo de `tests/acceptance/` (o CA-17 da SPEC-007 e o teste estático de `httpx` só em `publisher.py` continuam valendo: os módulos novos não importam `httpx`).

## CAs manuais

- **CA-11**: automatizado sob o marcador `mqtt` (fora do CI). A Definição de pronto pede que seja rodado localmente e registrado; rodei com o Mosquitto 2.1.2 em contêiner (acima). O registro oficial cabe ao tester com o `mosquitto` instalado pelo §3.3.
- **CA-12**: manual, pela dupla, com o roteiro em `edge/README.md`, seção "Teste manual MQTT (CA-12 da SPEC-020)" (depende do §3.3: `pacman -S mosquitto`, arquivo de senhas fora do repositório e `MQTT_USERNAME`/`MQTT_PASSWORD` no `.env`).

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (e a suíte inteira, sem banco)
- [x] `.env.example` atualizado (`EDGE_PUBLISHER`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_RESPONSE_TIMEOUT_S`, cada uma com comentário)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum segredo literal: senhas e chaves dos testes são geradas em tempo de execução; nenhuma credencial em URL ou header
