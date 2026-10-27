# SPEC-020 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-020](../../docs/specs/SPEC-020-mqtt.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `5ab96d5` (código de produção até `31e4c3a`) |
| **Veredicto** | **PASS** |

Os testes de aceite foram escritos a partir da SPEC (caixa-preta), consultando só os nomes públicos que a SPEC e o dev-report dão (`MqttPublisher`, `MqttBridge`, `InMemoryBroker`/`InMemoryTransport`, `MqttMessage`, `PahoMqttTransport`, `qc_edge.mqtt_bridge.main`). A implementação foi lida depois, para os exploratórios.

Arquivo: `edge/tests/acceptance/test_spec_020.py` — **114 testes coletados** (46 funções, com parametrizações): 112 rodam sem broker, 2 levam o marcador `mqtt` (CA-11 e um exploratório de `retain`). Nenhum ajuste em aceites de SPECs anteriores.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_twenty_items_delivered_once_through_mqtt` (20 itens; API simulada grava 20, uma vez cada; 20 linhas `sent`; toda mensagem em `partqc/v1/edge-01/batch` valida como `BatchCreate`, 1 a 100 itens); `test_ca01_edge_publisher_mqtt_puts_the_mqtt_publisher_in_the_loop` (`EDGE_PUBLISHER=mqtt` no `qc_edge.cli.main` monta o `PublishLoop` com `MqttPublisher`, sem `HttpPublisher`) | ✅ |
| CA-02 | `test_ca02_lost_answer_resent_and_deduplicated` (`InMemoryBroker.intercept` descarta a 1ª resposta da ponte depois da chamada à API; a API recebe o lote 2 vezes, a 2ª com 5 `duplicate`; 5 gravações; 5 `sent`) | ✅ |
| CA-03 | `test_ca03_broker_down_two_minutes_200_items_no_loss_no_duplicate` (40 itens antes, 120 com o broker parado por exatamente 120 s do relógio injetado, 40 depois; nada passa pelo broker parado; 200 ids distintos, 200 gravações, nenhuma linha `pending` ou `dead`) | ✅ |
| CA-04 | `test_ca04_without_bridge_puback_but_rows_stay_pending` (`MQTT_RESPONSE_TIMEOUT_S=1` lido por `EdgeSettings`; PUBACK contado e publicação com QoS 1; 3 linhas `pending` com `attempts == 1` e `sent_at` nulo; nenhuma chamada à API; ciclo dentro de 1 s + folga) | ✅ |
| CA-05 | `test_ca05_refused_item_dead_with_summary_others_sent` (item `dead` com `last_error == "HTTP 422: Value cannot be stored"`, 3 `sent`; toda resposta `rejected` tem exatamente o resumo e nenhuma resposta contém o corpo da API); `test_ca05_body_fields_beyond_the_summary_never_reach_the_answer` (campos extras com marcador no corpo do 422 nunca chegam ao payload das respostas) | ✅ |
| CA-06 | `test_ca06_auth_error_pauses_publishing[401]`, `[403]` (`auth_error` no 1º ciclo; nos 3 ciclos seguintes, +30 s cada, nenhuma publicação nova e nenhuma chamada à API; `attempts == 0`) | ✅ |
| CA-07 | `test_ca07_health_true_with_bridge_false_without_within_timeout` (ponte ligada e API 200 → `True`, com um `GET /api/v1/health` e payload vazio; ponte desligada → `False` em ≤ `MQTT_RESPONSE_TIMEOUT_S` (1 s, lido por `EdgeSettings`) + 0,75 s) | ✅ |
| CA-08 | `test_ca08_invalid_edge_publisher_exits_2_with_the_message`, `test_ca08_remote_mqtt_host_exits_2`, `test_ca08_empty_mqtt_password_exits_2` (subprocesso do `qc_edge.cli.main`, código 2; o 1º imprime `EDGE_PUBLISHER must be http or mqtt`); `test_ca08_bridge_without_device_api_key_exits_2` (`python -m qc_edge.mqtt_bridge`, código 2) | ✅ |
| CA-09 | `test_ca09_no_password_key_or_batch_payload_in_the_logs` (o `main` da ponte com `MQTT_PASSWORD` e `DEVICE_API_KEY` no ambiente e a API num servidor local em 127.0.0.1, rodando os cenários do CA-01, do CA-05 (com marcador no corpo do 422) e do CA-06; depois a borda sobe com `EDGE_PUBLISHER=mqtt` e os mesmos segredos. `caplog` em DEBUG e stderr/stdout capturados: nenhuma ocorrência da senha, da chave, do marcador, de um payload de lote, de um item serializado, de `"inspection_id"` ou do `model_sha256`) | ✅ |
| CA-10 | `test_ca10_paho_only_in_the_transport_httpx_only_in_the_publisher` (AST de todo código de produção do repositório: `paho` só em `edge/src/qc_edge/mqtt_transport.py`; `httpx` em `qc_edge` só em `publisher.py`; inclui `import_module`/`__import__` literais. Fecho do `uv.lock` com dependências, extras e grupos: `paho-mqtt` está no do `qc-edge` e não está no do `qc-api` nem no do `qc-dashboard`) | ✅ |
| CA-11 | `test_ca11_real_broker_repeats_ca01_and_refuses_no_password` (marcador `mqtt`; broker iniciado pelo próprio teste numa porta livre de 127.0.0.1, com usuário e senha aleatórios, sem anônimo; CA-01 repetido com `PahoMqttTransport` na borda e na ponte e um terceiro cliente monitorando o tópico; conexão anônima, só com usuário e com senha errada recusadas) | ✅ (ver nota) |
| CA-12 | manual (dupla), roteiro em `edge/README.md`, seção "Teste manual MQTT (CA-12 da SPEC-020)" | ⏳ manual, pendente da dupla |

**Nota do CA-11.** O `mosquitto` não está instalado nesta máquina e o tester não instala pacotes do sistema. O teste foi rodado com o **Mosquitto 2.1.2** da imagem oficial `eclipse-mosquitto:2` (já presente localmente), por dois wrappers fora do repositório (no scratchpad da sessão) que expõem `mosquitto` e `mosquitto_passwd` no `PATH` e chamam `docker run --rm --network host --user <uid>` com o diretório do `tmp_path` montado; o broker escuta só em `127.0.0.1` (configuração escrita pelo teste) e `mosquitto_passwd` roda com `--network none`. Resultado: `PARTQC_MQTT_TESTS=1 uv run pytest -q -m mqtt edge/tests edge/tests/acceptance/test_spec_020.py` → **6 passed** (2 de aceite + 4 do autor). Nenhum contêiner ficou para trás (`docker ps -a --filter label=acc020=1` vazio). A versão é a mesma do pacote `extra` do Arch citado na SPEC, mas **o registro oficial do CA-11 com o pacote do Arch (`sudo pacman -S mosquitto`) fica para o humano** (Definição de pronto: "CA-11 rodado localmente e registrado").

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
8499 passed, 142 skipped, 1 warning in 802.02s (0:13:22)

Skips: Docker (PARTQC_DOCKER_TESTS não definido), torch (sem o extra train), o CA-16 manual da
SPEC-008 (QC_REAL_MODEL_DIR) e os 6 testes `mqtt` (2 de aceite, 4 do autor; rodados à parte,
abaixo). Aviso: StarletteDeprecationWarning do fastapi.testclient (preexistente).

$ PATH=<wrappers>:$PATH PARTQC_MQTT_TESTS=1 uv run pytest -q -m mqtt edge/tests edge/tests/acceptance/test_spec_020.py
6 passed, 2744 deselected, 1 warning in 34.16s

$ uv run pytest -q edge/tests/acceptance/test_spec_020.py
112 passed, 2 skipped
```

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
282 files already formatted
```

O arquivo de aceite novo também foi rodado mais duas vezes em paralelo com a suíte inteira (carga de CPU), para conferir os testes com prazo: `112 passed, 2 skipped` nas duas.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos automatizados em `test_spec_020.py` (`test_extra_*`) e passando, salvo onde indicado.

| Tema | Caso | Resultado |
|---|---|---|
| §4.1 propriedades | `test_extra_request_properties_follow_section_4_1`: `ResponseTopic` = `partqc/v1/edge-01/reply/<sessão>`, constante dentro de um publisher e diferente entre dois; `CorrelationData` de 16 bytes, distinta por pedido; QoS 1 em toda publicação do publisher e da ponte e nas duas assinaturas da ponte (só `batch` e `health`); resposta no `ResponseTopic` com a mesma correlação e `result=ok`; payload `ok` de `batch` valida como `BatchResult`, de `health` vazio; nenhum payload com `image`/`jpeg` | ✅ |
| Ponte: `ResponseTopic` fora da §4.1 | 11 valores × 2 tópicos (`batch`, `health`): outro dispositivo, o próprio `batch`/`health`, curingas `+` e `#`, sessão vazia, nível extra, outro ramo, `partqc/#`, `$SYS/...`, vazio → a ponte não publica nada e não chama a API; nenhum payload no log | ✅ |
| Ponte: pedido sem propriedades | sem `ResponseTopic`, sem `CorrelationData`, sem os dois, correlação vazia → ignorado, com aviso (`WARNING`), sem chamar a API e sem payload no log | ✅ |
| Ponte: outro dispositivo | `partqc/v1/edge-02/batch`, `.../health` e `partqc/v1/edge-01/batch/x` → nada chega à API, nenhuma resposta | ✅ |
| Ponte: payload malformado ou enorme | vazio, não-JSON, UTF-8 inválido, lista, `{}`, 0 itens, 101 itens, item inválido, **4 MiB**, NUL → `rejected` com exatamente `HTTP 422: invalid batch payload`, correlação copiada, sem chamar a API, em < 10 s, sem eco do payload no log | ✅ |
| R-02/R-04: campo `image` contrabandeado num item | nunca chega ao corpo enviado à API (a ponte reserializa o modelo validado) | ✅ |
| R-05: replay do mesmo lote 3 vezes por outro cliente | `created, created` → `duplicate, duplicate` → `duplicate, duplicate`; 2 gravações | ✅ |
| Mapeamento da ponte | API 503 → `transient`; 401/403 → `auth` (payload vazio); 413 → `rejected` com `HTTP 413…`; health 503 → `transient` e `check_health() == False` | ✅ |
| Publisher: resposta adulterada com a correlação certa | ids trocados, ordem invertida, menor, maior, status inválido, `ok` não-JSON, `ok` vazio, sem `result`, `result` desconhecido, `transient`, `OK` maiúsculo → `PublishTransientError` (consumida na hora, sem esperar o prazo), linhas `pending` com `attempts == 1` | ✅ |
| Publisher: resposta forjada com correlação desconhecida | publicada no `ResponseTopic` verdadeiro com `result=ok` e os ids certos → descartada (o pedido expira em ~1 s); nada vira `sent` | ✅ |
| Publisher: resposta atrasada de um pedido anterior | a resposta do 1º pedido é retida e reinjetada como `rejected` logo antes da resposta do reenvio → descartada; o item fica `sent` | ✅ |
| PUBACK nunca confirma | coberto pelo CA-04 e pelos casos acima (PUBACK sempre presente, nada `sent` sem `ok` da ponte) | ✅ |
| Resumo de recusa vindo da ponte | payload com `\n`, `\r`, ESC, NUL, 2000 caracteres e byte inválido → item `dead`, `last_error` começa com `HTTP 422: bad`, sem caractere de controle, < 2000 caracteres | ✅ |
| Prazo único, broker em memória parado | `check_health() == False` e `PublishTransientError` imediatos; depois do `start()`, `True` | ✅ |
| Prazo único com o `PahoMqttTransport` real, sem Mosquitto | porta fechada em 127.0.0.1 e um listener TCP que aceita e nunca manda CONNACK: `check_health() == False` e `PublishTransientError` cada um em ≤ 1 s + 0,75 s; a senha não aparece no log | ✅ |
| `retain` (broker real, marcador `mqtt`) | depois de um ida e volta, um assinante novo de `partqc/#` não recebe mensagem retida (com controle positivo: o mesmo assinante recebe uma publicação nova) | ✅ |
| R-06 | `source=simulated` chega à API como `simulated` pelo caminho MQTT; `--stub-model` com `EDGE_PUBLISHER=mqtt` não monta `PublishLoop` nem `PahoMqttTransport` e não cria o outbox | ✅ |
| Configuração §4.5 | padrões (`http`, `127.0.0.1`, 1883, 15, credenciais vazias); `127.0.0.1`, `::1`, `localhost` aceitos; `0.0.0.0`, `127.0.0.2`, `broker.example.com`, `localhost.example.com`, porta 0/65536/`abc`, timeout 0,5/61/`nan`/`inf` → código 2 com o nome da variável e sem o valor; `MQTT_USERNAME` ou `MQTT_PASSWORD` ausentes com `mqtt` → 2 com o nome | ✅ |
| Eco de valores | valor marcado em `EDGE_PUBLISHER` não aparece na saída; a senha e a chave não aparecem em nenhuma saída de erro | ✅ |
| Ponte: configuração inválida | sem senha, sem usuário, sem `CLOUD_API_URL`, host remoto, porta 70000, `http://` para host não local → 2, sem a senha e a chave na saída; argumento desconhecido → 2, sem eco de valores (o nome da opção aparece, pela convenção de `qc_edge.argv`) | ✅ |
| Ponte: sinais | `SIGTERM` e `SIGINT` com o broker fora do ar → código 0, sem segredo na saída | ✅ |
| Senha fora de `/api/status` e do console | `GET /api/status` (200) e `GET /` com `EDGE_PUBLISHER=mqtt` e senha → nenhuma ocorrência | ✅ |
| `edge/mosquitto/partqc.conf` | `listener 1883 127.0.0.1`, `allow_anonymous false`, nenhum listener fora de loopback, `password_file` absoluto e fora do repositório | ✅ |
| `.env.example` | documenta `EDGE_PUBLISHER` e as cinco `MQTT_*`; `MQTT_PASSWORD` vazio | ✅ |
| R-12 | `paho-mqtt` só no `edge/pyproject.toml`, travado em 2.1.0 no `uv.lock`; `api/` e `dashboard/` sem `paho` e sem torch/onnxruntime/timm/torchvision no fecho | ✅ |

Observações (não são bugs):

- **Eco do nome da opção.** Um argumento desconhecido na ponte aparece pelo nome (`--opt-…`), nunca pelo valor; é a convenção de `qc_edge.argv.describe_arguments` (SPEC-034). Meu primeiro rascunho do teste esperava nenhum eco; ajustei o teste para verificar só os valores, que é o que a §4.4 pede.
- **IDs no log.** O `PublishLoop` (SPEC-009) registra o `inspection_id` do item que vira `dead`. O CA-09 proíbe o payload de lote, não o id; o teste verifica a ausência de qualquer parte do payload (item serializado, chave JSON `"inspection_id"`, `model_sha256`).
- **Caracteres de formatação Unicode.** O resumo da recusa troca por `?` só os caracteres da categoria `Cc`; caracteres como U+2028 ou U+202E passariam. É a mesma regra do `refusal_summary` da SPEC-009 ("caractere de controle"), então não é desvio desta SPEC; fica como nota para o security-devops.
- **Credencial errada no broker real** (pela leitura do código de `PahoMqttTransport.connect`). Com o broker recusando a conexão, o `connect` só falha ao fim do prazo (o CONNACK de recusa não encerra a espera); fica dentro do prazo único, mas o diagnóstico só aparece depois dele.
- **`docs/architecture.md` §6.4** ainda não lista `EDGE_PUBLISHER` e as `MQTT_*` (já registrado pelo autor; é tarefa do architect pela Definição de pronto).

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
