# SPEC-020 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-020](../../docs/specs/SPEC-020-mqtt.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `spec/SPEC-038-manutencao-borda-deploy...a49fcf5` (branch encadeada na SPEC-038; 11 commits, de `56360f8` a `a49fcf5`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Os cinco achados abaixo são baixos e não pedem rodada nova; podem entrar numa SPEC de manutenção ou ficar como nota para o portão de segurança.

## Verificações executadas

| Comando | Resultado |
|---|---|
| `uv run ruff check .` e `uv run ruff format --check .` | limpos (282 arquivos) |
| `uv lock --check` | `uv.lock` em dia (116 pacotes) |
| `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` | **8499 passed, 142 skipped**, 0 falhas (800,88 s): mesma contagem do test-report |
| `PARTQC_MQTT_TESTS=1 uv run pytest -q -m mqtt edge/tests edge/tests/acceptance/test_spec_020.py` | **6 passed** (CA-11, o exploratório de `retain` e os 4 do autor), com o Mosquitto 2.1.2 da imagem oficial `eclipse-mosquitto:2` por wrappers no scratchpad da sessão (`docker run --rm --network host`, `mosquitto_passwd` com `--network none`). Nenhum contêiner ficou para trás |
| `importlib.metadata` do `paho-mqtt` instalado | `2.1.0`, `License: EPL-2.0 OR BSD-3-Clause`; única dependência declarada é `pysocks` no extra `proxy`, que não é pedido |
| `git log --format='%h %an <%ae> %(trailers:key=Agent)'` + `git show --stat` por commit | ver a seção R-07 abaixo |
| Busca de segredos no diff (`postgres://u:p@`, `eyJ`, `password=`, chaves literais) | nada; as senhas dos testes são geradas em tempo de execução (`secrets.token_urlsafe`) ou montadas por concatenação, nunca em URL ou conninfo |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `edge/src/qc_edge/mqtt_transport.py:221-223`, `:282-286` | Com o broker recusando a credencial (CONNACK `Not authorized`), o `connect` não termina na recusa: espera o prazo inteiro (até `MQTT_RESPONSE_TIMEOUT_S`) e só então levanta o erro com o motivo (observação 4 do test-report). Além disso, a reconexão automática do `paho` (`reconnect_delay_set(1, 30)`) tenta de novo com a mesma senha errada e cada CONNACK de recusa gera um `WARNING` novo, o que enche o log da borda e da ponte enquanto a senha não for corrigida. Fica dentro do prazo único e não vaza segredo. | Ao receber um CONNACK de falha, sinalizar a espera (um `Event` de "recusado") para o `connect` falhar na hora, e registrar a recusa só na primeira vez ou quando o motivo mudar. |
| RV-02 | baixa | `edge/src/qc_edge/config.py:74`; `edge/src/qc_edge/publisher.py:69` | O padrão de `MQTT_RESPONSE_TIMEOUT_S` (15 s, valor da SPEC §4.5) é igual ao prazo total de uma requisição do `HttpPublisher` da ponte (15 s, SPEC-030), e o prazo da borda ainda inclui conexão, PUBACK e a resposta. Com a API lenta, mas respondendo perto do limite, a borda desiste antes da ponte responder: o lote volta a `pending`, o reenvio recebe `duplicate` (correto por R-05) e o `last_error` diz "no answer from the mqtt bridge", não "API lenta". Não é bug nem `SPEC_ISSUE`: o valor é da SPEC e a idempotência cobre. | Uma linha no `edge/README.md` ("Transporte MQTT") recomendando `MQTT_RESPONSE_TIMEOUT_S` acima de 15 s (ex.: 20 a 25) quando a API estiver lenta; se a dupla quiser mudar o padrão, isso passa por uma correção de SPEC. |
| RV-03 | baixa | `edge/README.md:304` (passo a passo do "Transporte MQTT") | O passo diz "edite `edge/mosquitto/partqc.conf` (ou uma cópia fora do repositório) e troque `<usuario>`". Editar o arquivo versionado deixa a árvore suja com um caminho pessoal (`/home/<nome>/...`), que pode acabar num commit por descuido. | Pôr a cópia como caminho principal, por exemplo `cp edge/mosquitto/partqc.conf ~/.config/partqc/partqc.conf`, editar a cópia e rodar `mosquitto -c ~/.config/partqc/partqc.conf`. |
| RV-04 | baixa | `edge/mosquitto/partqc.conf:7-16` | O exemplo não limita o tamanho das mensagens (`max_packet_size` / `message_size_limit`); o padrão do Mosquitto 2 aceita pacotes muito grandes, e a ponte e a fila de despacho do transporte (`MAX_PENDING_INBOUND = 1000`) guardam os payloads em memória. O risco é pequeno (só loopback, sem anônimo, um usuário), e o exploratório de 4 MiB mostra a ponte recusando sem eco. | Acrescentar `max_packet_size 1048576` (um `BatchCreate` de 100 itens fica muito abaixo de 1 MiB). Fica como nota para o portão de segurança. |
| RV-05 | baixa | `edge/src/qc_edge/publish_loop.py:246-254` (sem mudança nesta SPEC); `edge/src/qc_edge/cli.py:175-193` | O `PublishLoop.stop()` espera no máximo 10 s, mas um pedido MQTT em andamento pode esperar até `MQTT_RESPONSE_TIMEOUT_S` (máximo 60 s) sem olhar o evento de parada; ao fechar a borda no meio de um pedido aparece "publisher thread did not stop within 10 s" (a thread é daemon, nada trava). O cliente `paho` também não é desconectado na saída (o `MqttPublisher.close()` não é chamado, como já acontecia com o `HttpPublisher.close()`). É o mesmo comportamento que já existia com o prazo de 15 s do HTTP, só que agora pode durar mais. | Numa SPEC de manutenção: deixar o `PublishLoop.stop()` chamar `close()` do publisher, quando existir, e, no `MqttPublisher`, acordar a espera de `pending.event` ao fechar. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os arquivos do diff são exatamente os da §3.1 (transporte, publisher, ponte, configuração e `cli`, `partqc.conf`, README, `pyproject.toml` do edge e da raiz, `uv.lock`, `.env.example`, testes do autor, aceite do tester) mais a §6.2, a nova tabela da §6.4 e a §10 do `docs/architecture.md`, escritas pelo architect conforme a Definição de pronto. Nenhum CA foi alterado. A rastreabilidade CA → arquivo/teste está no dev-report. Nenhuma reaprovação sob o ADR-019 nesta branch: os commits do orquestrador (`56360f8`, `5ab96d5`, `a49fcf5`) só mudam o status e a rodada e registram no Histórico a decisão do humano de 2026-10-26 de adiantar a SPEC, sem tocar requisito ou CA. **Decisões do dev-report:** (1) a ponte só responde num `ResponseTopic` da forma `partqc/v1/<DEVICE_ID>/reply/<sessão>`: aperta o que a §4.1 já define como forma do tópico de resposta, impede usar a ponte para publicar em outro tópico, não muda CA e foi incorporada pelo architect na §6.2; aceita. (2) A ponte lê o ambiente do processo (`--env-file`), a mesma convenção do `qc-edge`; aceita. (3) As `MQTT_*` são validadas em toda subida e as credenciais são exigidas com `EDGE_PUBLISHER=mqtt` mesmo com `--stub-model`: segue o texto literal da §4.5 e está na §6.4; aceita. (4) Mensagem exata de `EDGE_PUBLISHER` por `PydanticCustomError`, com `config_error_message` movida para o `config.py` sem mudar as outras mensagens (nenhum outro chamador do nome antigo; suíte verde); aceita. (5) Prazo único de conexão, PUBACK e resposta: é o que faz o CA-07 valer com o broker fora do ar; aceita. (6) a (10): conexão preguiçosa, despacho fora da thread de rede, client ids, `parse_batch_results` público (mesmo corpo) e saneamento do resumo `rejected` com a regra do `refusal_summary`; todos são detalhes de implementação dentro da SPEC. |
| 2. Regras inegociáveis | ✅ | **R-01:** Mosquitto local (software livre, repositório `extra` do Arch) e `paho-mqtt` (EPL-2.0 OR BSD-3-Clause); nenhum serviço novo nem broker na nuvem. **R-02:** os payloads são só `BatchCreate`/`BatchResult`/resumo de recusa; a ponte reserializa o modelo validado (o exploratório com um campo `image` contrabandeado confirma que ele não chega à API). **R-03:** nenhum segredo no diff; `MQTT_PASSWORD` é `SecretStr`, vazia no `.env.example`, ausente dos logs, do `/api/status` e do console (CA-09 e exploratórios); mensagens de erro citam a variável, nunca o valor (`hide_input_in_errors=True`). **R-04:** nenhum schema novo; `qc_contracts` intocado. **R-05:** a ponte não tem estado; o CA-02 e o replay triplo mostram `duplicate` sem regravar. **R-06:** `source=simulated` atravessa o caminho MQTT; `--stub-model` com `mqtt` não monta publisher nem outbox. **R-07:** ver abaixo. **R-11:** N/A. **R-12:** `paho-mqtt` só em `edge/pyproject.toml` (`>=2.1,<3`), travado em **2.1.0** no `uv.lock` (wheel `py3-none-any`, sha256 `6db9ba9b…feee`); fora do fecho do `qc-api` e do `qc-dashboard` (CA-10 e `test_paho_is_not_in_the_api_or_dashboard_closure`); `paho` importado só por `qc_edge/mqtt_transport.py`; `httpx` continua só em `publisher.py`. **R-13:** todos os commits como `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, Conventional Commits, `Refs: SPEC-020` e `Agent:` no mesmo bloco final. |
| 3. Corretude | ✅ (RV-01, RV-02, RV-05) | Confirmação de ponta a ponta correta: o item só vira `sent` com `ok` + `BatchResult` com os mesmos ids na mesma ordem; o PUBACK nunca marca nada. A correlação fica registrada antes do `publish` (a resposta síncrona do `InMemoryBroker` e a resposta rápida do broker real não se perdem) e é removida no `finally`; correlação desconhecida, já atendida ou de outra sessão é descartada. Prazos com `time.monotonic()`, sem depender do relógio de parede. O `SUBSCRIBE` sai antes do `connected.set()` e antes de qualquer publicação da mesma conexão, então a resposta não chega antes da assinatura; as assinaturas são refeitas a cada CONNACK. O despacho numa thread própria evita o deadlock de esperar o PUBACK dentro do callback do `paho`. Tópicos sem curingas nem NUL na publicação; `DEVICE_ID_PATTERN` (`^[a-z0-9-]{3,32}$`) não deixa caractere de tópico especial entrar. Nenhum `except Exception: pass`: os inesperados são registrados só pela classe (R-03). Sem handler async novo. |
| 4. Testes | ✅ | Test-report PASS, com um teste de aceite por CA automatizado (CA-01 a CA-11) e o CA-12 manual pendente da dupla. Os testes exercitam o caminho real (`PublishLoop` → `MqttPublisher` → broker → `MqttBridge` → `HttpPublisher` → `httpx.MockTransport` idempotente) sem fazer mock do que testam; o CA-10 inspeciona o AST e o fecho do `uv.lock` com um controle positivo (o `paho-mqtt` está no fecho do `qc-edge`). Sem rede externa: `MockTransport`, servidor local em 127.0.0.1 e, no marcador `mqtt`, um broker em porta livre de loopback. Nenhum teste chama o pytest em subprocesso. Nenhum aceite de SPEC anterior foi ajustado (o test-report e o dev-report dizem "nenhum", e o `git diff --stat` confirma: só `edge/tests/acceptance/test_spec_020.py` em `acceptance/`). Credenciais de teste geradas em tempo de execução, nunca em URL. O marcador `mqtt` está declarado e documentado na §10. |
| 5. Qualidade | ✅ (RV-03) | Ruff limpo; type hints nas funções públicas; sem `print`; o `InMemoryBroker` e o `PahoMqttTransport` atrás do mesmo Protocol; a validação do `BatchResult` reaproveitada (`parse_batch_results`), sem duplicar lógica de `qc_contracts`. README com a seção "Transporte MQTT", a tabela de variáveis e o roteiro do CA-12; `.env.example` com as seis variáveis comentadas; docstrings dos módulos explicam as decisões (reenvio pelo `paho`, fila de despacho, prazo único). |
| 6. Segurança | N/A (portão do `security-devops`) | A SPEC tem a tag `security`, mas o autor é o `developer`; o `security-report` é do `security-devops`. Conferido aqui, sem substituir o portão: licença e fixação da dependência nova (acima), broker só em loopback e sem anônimo no exemplo, ponte que só responde no espaço de resposta do próprio dispositivo, nenhum log com payload ou segredo. Notas para o portão: RV-04 e a observação 3 do test-report (o resumo da recusa troca só a categoria `Cc`, regra herdada da SPEC-009). Não fiz consulta de CVE do `paho-mqtt` 2.1.0 (`uv pip audit` não existe nesta versão do uv); fica para o portão. |

### R-07 (trailers × arquivos)

| Commit | `Agent:` | Arquivos | OK |
|---|---|---|---|
| `56360f8` | orchestrator | `docs/plan.md`, `docs/specs/SPEC-020-mqtt.md` (status e Histórico) | ✅ |
| `3012178` | developer | `edge/pyproject.toml`, `uv.lock` | ✅ |
| `f230961` | developer | código de produção em `edge/src/qc_edge/`, `edge/mosquitto/partqc.conf`, `.env.example`, `pyproject.toml`, testes do autor em `edge/tests/` (fora de `acceptance/`), incluindo `conftest.py` e `mosquitto_support.py` | ✅ |
| `da8a877` | developer | `edge/README.md` | ✅ |
| `31e4c3a` | developer | `mqtt_publisher.py`, `mqtt_transport.py`, `edge/tests/test_mqtt_publisher.py` | ✅ |
| `2c02879` | developer | `reviews/SPEC-020/r1-dev-report.md` | ✅ |
| `5ab96d5` | orchestrator | `docs/plan.md`, `docs/specs/SPEC-020-mqtt.md` (status) | ✅ |
| `f989e02` | architect | `docs/architecture.md` (§6.2, §6.4, §10; atribuído ao architect pela Definição de pronto) | ✅ |
| `7745a2d` | tester | `edge/tests/acceptance/test_spec_020.py`, `reviews/SPEC-020/r1-test-report.md` | ✅ |
| `a49fcf5` | orchestrator | `docs/plan.md`, `docs/specs/SPEC-020-mqtt.md` (status) | ✅ |

O tester não tocou código de produção, o developer não tocou `tests/acceptance/`, e todos os commits têm o trailer `Agent:` no bloco final, junto de `Refs:` e `Co-Authored-By:`.

## Itens da Definição de pronto que ficam para o merge (não são achados)

- **CA-11 "rodado localmente e registrado":** rodado pelo developer, pelo tester e por este review (6 passed) com o Mosquitto 2.1.2 da imagem oficial em Docker, a mesma versão do pacote `extra` do Arch citado na SPEC. O registro com o pacote do Arch (`sudo pacman -S mosquitto`, §3.3) ficou para o humano no test-report; cabe ao orquestrador confirmar com o humano se o registro em contêiner basta ou se ele vai repetir com o pacote antes do merge.
- **CA-12 (manual, dupla):** pendente; o roteiro está em `edge/README.md`, "Teste manual MQTT (CA-12 da SPEC-020)".
- **security-report PASS** (tag `security`) e o merge na ordem do encadeamento (depois da 036, 016, 018, 017 e 038), conforme o Histórico da SPEC.

## Pontos positivos

- A confirmação de ponta a ponta está bem isolada: o `PublishLoop`, o backoff, a bissecção e o `dead` da SPEC-009 não mudaram uma linha, e o `MqttPublisher` só traduz respostas para as mesmas exceções do `HttpPublisher`.
- A decisão de restringir o `ResponseTopic` ao espaço de resposta do dispositivo fecha um vetor real (usar a ponte para publicar em `batch` ou em outro tópico) sem mudar contrato nem CA, e o tester a exercitou com 22 combinações.
- O prazo único (`31e4c3a`) foi encontrado e corrigido pelo próprio autor antes do teste, e o tester o confirmou com o transporte real contra uma porta fechada e um listener mudo.
- Exploratórios fortes no aceite: respostas adulteradas com a correlação certa, resposta forjada com correlação desconhecida, resposta atrasada de um pedido anterior, payload de 4 MiB, `retain` no broker real.
- Mensagens de erro e logs disciplinados: só nome de variável, classe da exceção, contagem, `result` e tópico.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
