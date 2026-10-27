# SPEC-020 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-020](../../docs/specs/SPEC-020-mqtt.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `spec/SPEC-038-manutencao-borda-deploy...0f58379` (branch encadeada na SPEC-038; 12 commits, de `56360f8` a `0f58379`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os cinco achados abaixo são baixos ou informativos e não pedem rodada nova; servem para uma SPEC de manutenção. Nenhuma reaprovação sob o ADR-019 nesta branch.

## Superfície analisada

- **Entrada nova na borda:** o broker Mosquitto local (`edge/mosquitto/partqc.conf`) e os dois consumidores de mensagens MQTT: a ponte (`qc_edge/mqtt_bridge.py`, tópicos `batch` e `health` do `DEVICE_ID`) e o `MqttPublisher` (`qc_edge/mqtt_publisher.py`, tópico de resposta da sessão).
- **Credenciais:** `MQTT_USERNAME`/`MQTT_PASSWORD` (novas, `SecretStr`) e o `DEVICE_API_KEY` agora também lido pela ponte (`BridgeSettings`).
- **Transporte:** `qc_edge/mqtt_transport.py` (`PahoMqttTransport`, único módulo que importa `paho`; `InMemoryBroker` só para testes).
- **Configuração e subida:** `qc_edge/config.py` (`EDGE_PUBLISHER`, `MQTT_*`, `BridgeSettings`, `config_error_message`), `qc_edge/cli.py` (`_build_publisher`), `.env.example`, `edge/README.md`.
- **Dependência nova:** `paho-mqtt` 2.1.0 (só `qc-edge`).
- **Suporte de teste:** `edge/tests/mosquitto_support.py` e a fixture `mosquitto_broker` (broker real em porta livre de 127.0.0.1, credenciais geradas na hora, `tmp_path`).
- **Fora do diff:** nenhuma rota HTTP nova, nenhum SQL, nada em `api/`, `dashboard/` ou `infra/` (sem broker na nuvem, R-01).

## Verificações executadas

| Comando / ação | Resultado |
|---|---|
| `uv sync --all-packages --locked`; `uv lock --check` | lock em dia (116 pacotes) |
| `uv run pytest -q edge/tests/test_mqtt_{transport,publisher,bridge,config}.py edge/tests/acceptance/test_spec_020.py` | **286 passed, 6 skipped** (os 6 são do marcador `mqtt`) |
| `PARTQC_MQTT_TESTS=1 uv run pytest -q -m mqtt edge/tests edge/tests/acceptance/test_spec_020.py`, com o Mosquitto **2.1.2** da imagem oficial `eclipse-mosquitto:2` por wrappers no scratchpad (`--network host` no broker, que escuta só em 127.0.0.1 pela configuração do teste; `--network none` no `mosquitto_passwd`) | **6 passed**; nenhum contêiner ficou para trás |
| `uv tree --package qc-api` / `qc-dashboard` / `qc-edge` | `paho-mqtt` só no fecho do `qc-edge` (R-12) |
| OSV (`api.osv.dev/v1/query`, PyPI `paho-mqtt`, com e sem a versão 2.1.0), GitHub Advisory Database (`/advisories?ecosystem=pip&affects=paho-mqtt`) e advisories do repositório `eclipse-paho/paho.mqtt.python`, consultados em 2026-10-26 | **nenhum aviso** |
| PyPI JSON de `paho-mqtt` (2026-10-26) | última versão 2.1.0 (2024-04-29), licença `EPL-2.0 OR BSD-3-Clause` |
| Sondagem própria com broker real (2.1.2), credenciais geradas na hora, limpeza no fim | ver SEC-01, SEC-03 e SEC-05: sem ACL, um cliente autenticado assina `#` e vê pedidos com a `CorrelationData`; publicação de 1 MiB aceita e de 2 MiB descartada com desconexão; mensagem retida entregue a assinante novo; senha errada falha ao fim do prazo (3,0 s com prazo de 3 s), 4 avisos de recusa em ~9 s, senha ausente de toda a captura de log |
| Busca de segredos no diff (padrões de senha literal, JWT, conninfo com senha) | nada; senhas e chaves dos testes vêm de `secrets.token_*` em tempo de execução |
| Leitura de `app.py`, templates e `static/` | nenhuma referência às `MQTT_*` (senha fora de `/api/status` e do console) |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 | baixa | auth | `edge/mosquitto/partqc.conf:7-16`; `edge/README.md` (passo a passo do "Transporte MQTT") | O broker usa um único usuário (`partqc-edge`) para a borda, a ponte e o `mosquitto_sub`, sem `acl_file`; no Mosquitto, sem ACL, todo cliente autenticado lê e escreve em qualquer tópico. Confirmado com broker real: quem tem a senha assina `#`, vê os pedidos com a `CorrelationData` e pode (a) publicar no tópico de resposta da sessão um `ok` forjado com os ids certos, o que marca os itens como `sent` sem que tenham chegado à nuvem (perda silenciosa); (b) publicar lotes que a ponte repassa com o `DEVICE_API_KEY`; (c) deixar mensagens retidas em `batch`. Mitigação real: listener só em loopback, sem anônimo, e a senha mora no mesmo `.env` do `DEVICE_API_KEY` (mesma fronteira de confiança); a ponte ainda exige `ResponseTopic` no espaço de resposta do dispositivo e o `BatchCreate` válido, e a API confere o `device_id` contra a chave. A SPEC (§3.3) prescreve esse arranjo, então não é desvio. | Não bloqueia. Numa SPEC de manutenção (com correção de SPEC, porque mexe em permissão): dois usuários (borda e ponte) e um `acl_file` (borda escreve `partqc/v1/<id>/batch` e `/health` e lê `/reply/#`; ponte lê `batch`/`health` e escreve `/reply/#`), um usuário só de leitura para o `mosquitto_sub` e `retain_available false`. |
| SEC-02 | baixa | secrets | `edge/README.md` (comando `mosquitto_sub` do passo a passo e do passo 6 do CA-12) | O exemplo passa a senha do broker pela opção `-P` na linha de comando: ela fica no histórico do shell e em `/proc/<pid>/cmdline`, visível por `ps` a outros usuários locais enquanto o comando roda. O `mosquitto_passwd -c` do mesmo passo a passo pede a senha interativamente (correto). | Não bloqueia. Trocar o exemplo por um meio que não ponha a senha na linha de comando (por exemplo, o arquivo de opções padrão do `mosquitto_sub` em `~/.config/mosquitto_sub`, modo 600, fora do repositório), ou ao menos avisar para não deixar a senha no histórico. |
| SEC-03 | baixa | deploy | `edge/mosquitto/partqc.conf:7-16` | O exemplo não fixa `max_packet_size` nem `persistence`. **Correção da premissa do RV-04:** pelo manual oficial do `mosquitto.conf`, o `max_packet_size` "defaults to 2000000 bytes since 2.1" (antes, sem limite), e `persistence` é `false` por padrão. Com o 2.1.2 citado pela SPEC, o limite já existe (confirmado: 1 MiB aceito, 2 MiB descartado com desconexão do cliente) e nada vai para o disco. O risco aparece só se o broker for um 2.0.x (Debian/Ubuntu, imagens antigas): sem limite, um cliente autenticado enche a fila de despacho (`MAX_PENDING_INBOUND = 1000`) com mensagens grandes na memória da ponte. | Não bloqueia. Fixar no exemplo `max_packet_size 1048576` (um `BatchCreate` de 100 itens fica bem abaixo) e `persistence false`, para não depender da versão instalada. |
| SEC-04 | baixa | input | `edge/src/qc_edge/mqtt_publisher.py:78-82` (`rejected_detail`); herdado de `edge/src/qc_edge/publisher.py:131-133` (`refusal_summary`, SPEC-009) | O resumo de recusa troca por `?` só a categoria Unicode `Cc`; caracteres de formatação (`Cf`, por exemplo U+202E) e separadores de linha/parágrafo (U+2028/U+2029) passam para o `last_error` e para o log `inspection ... marked dead: ...` do `PublishLoop` (observação 3 do test-report). Permite falsificar a aparência de uma linha de log no terminal local. A fonte é a ponte (que repassa o `detail` da API autenticada) ou, no caminho MQTT, quem tiver a senha do broker e a correlação (SEC-01). O `qc-edge-requeue` já mascara `Cf` ao exibir (`printable_error`). Mesma regra da SPEC-009, que fala só em "caractere de controle": não é desvio desta SPEC. | Não bloqueia. Numa manutenção: alinhar `rejected_detail` e `refusal_summary` às categorias do `printable_error` (`Cc`, `Cf`, `Zl`, `Zp`). |
| SEC-05 | informativa | deploy | `edge/src/qc_edge/mqtt_transport.py:221-223`, `:282-286` | Com credencial errada, o `connect` só falha ao fim do prazo (o CONNACK de recusa não encerra a espera), e a reconexão automática do `paho` gera um `WARNING` por recusa (4 em ~9 s, depois a cada até 30 s pelo backoff). O prazo único é respeitado (a borda devolve `PublishTransientError` dentro de `MQTT_RESPONSE_TIMEOUT_S` e as linhas seguem `pending`), e o aviso só cita o motivo (`Not authorized`), nunca o usuário ou a senha (confirmado com broker real). Mesmo ponto do RV-01; é diagnóstico e ruído de log, não exposição. | Nenhuma exigida. Se o RV-01 for tratado, falhar o `connect` na recusa e registrar a recusa uma vez por motivo. |

## Itens do foco pedido

| Item | Resultado |
|---|---|
| `paho-mqtt`: licença | `EPL-2.0 OR BSD-3-Clause` (PyPI e `METADATA`), compatível (opção BSD-3-Clause) |
| `paho-mqtt`: avisos de segurança | nenhum no OSV, no GitHub Advisory Database nem nos advisories do repositório (2026-10-26) |
| `paho-mqtt`: fixação e escopo | `paho-mqtt>=2.1,<3` só em `edge/pyproject.toml`; travado em 2.1.0 no `uv.lock`, com hash do sdist e do wheel; fora do fecho de `qc-api` e `qc-dashboard`; sem dependência de runtime (o extra `proxy` não é pedido) |
| `paho-mqtt`: manutenção | última versão de 2024-04-29, mas o repositório oficial segue ativo (commits em 2026-10, não arquivado). Aceitável; acompanhar uma 2.2 |
| Mosquitto só em loopback, sem anônimo | `listener 1883 127.0.0.1`, `allow_anonymous false`, `password_file` absoluto fora do repositório; a configuração do teste repete isso e o CA-11 mostra anônimo, só usuário e senha errada recusados |
| ACL / autenticação | autenticação por senha, sem ACL (SEC-01) |
| `max_packet_size` | 2000000 bytes por padrão no 2.1.x; não explícito no exemplo (SEC-03) |
| Persistência / retain | `persistence` desligada por padrão (a configuração de teste fixa `false`); `clean_start=True`; nenhuma publicação do projeto usa `retain` (o exploratório do tester confirma); retain por cliente autenticado é possível (SEC-01) |
| Ponte sem estado e só no `ResponseTopic` da §4.1 | sem estado; responde só se o `ResponseTopic` casar `partqc/v1/<DEVICE_ID>/reply/[A-Za-z0-9_-]{1,64}` por inteiro (o `DEVICE_ID` segue `DEVICE_ID_PATTERN`, sem curingas); ignora pedido sem `ResponseTopic`/`CorrelationData` |
| Ponte não confia no payload | valida `BatchCreate` (`extra="forbid"`, 1 a 100 itens) antes de chamar a API, reserializa o modelo validado, e a API confere `device_id` contra a chave; inválido → `HTTP 422: invalid batch payload`, sem eco. O `MqttPublisher` também não confia na resposta: `ok` só com `BatchResult` com os mesmos ids na mesma ordem; correlação desconhecida ou já atendida é descartada |
| R-02 (nunca imagem) | payloads só `BatchCreate`/`BatchResult`/resumo; `InspectionCreate` não tem campo de imagem e proíbe extras |
| R-05 (idempotência) | CA-02 e o replay triplo do tester: `duplicate` sem regravar |
| Prazo único (broker fora, credencial errada) | conexão, PUBACK e resposta dividem `response_timeout_s` (`_remaining(deadline)`); confirmado com porta fechada, listener mudo (tester) e senha errada (esta revisão, SEC-05) |
| Segredos fora de log, stderr, console e `/api/status` | `SecretStr` + `hide_input_in_errors=True`; mensagens citam só o nome da variável; exceções registradas só pela classe; `paho` sem logger; `/api/status` e console não leem as `MQTT_*`; CA-09 e sondagem própria sem a senha. Ressalva de documentação: SEC-02 |
| Arquivo de senhas fora do repositório (R-03) | `~/.config/partqc/mosquitto.passwd`, diretório `chmod 700`; nos testes, `tmp_path` com `0700` e arquivo `0600`. O passo de editar o `partqc.conf` versionado (RV-03) não expõe segredo, só um caminho pessoal |
| R-01 | Mosquitto local (software livre, sem cartão); nenhum broker ou serviço na nuvem; `infra/` intocado |
| R-06 | `source=simulated` atravessa o caminho MQTT; `--stub-model` não monta publisher nem outbox (tester) |
| R-12 | confirmado pelo `uv tree` e pelo CA-10 |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | ✅ Nenhuma rota HTTP nova. A ponte usa a rota já autenticada pela chave do dispositivo (SPEC-004), via `HttpPublisher`. O broker exige usuário e senha (a comparação é do Mosquitto). Autorização por tópico ausente: SEC-01 (baixa) |
| Entradas validadas (tamanho, tipo, regex, `extra="forbid"`) | ✅ `BatchCreate` estrito na ponte; regex do `ResponseTopic`; `DEVICE_ID_PATTERN`; `MQTT_HOST` só loopback, porta e prazo com limites; tamanho limitado pelo broker 2.1 (SEC-03). Imagem: N/A (nenhuma imagem no caminho) |
| SQL parametrizado | N/A (nenhum SQL no diff) |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A |
| CORS | N/A |
| Logs sem segredos nem payloads | ✅ Só contagens, `result`, tópico fixo e classe de exceção; ressalvas SEC-02 (documentação) e SEC-04 (formatação Unicode no resumo) |
| Dependências novas mantidas, licença compatível, sem CVE | ✅ `paho-mqtt` 2.1.0, ver acima |
| Deploy: variáveis no provedor, health check, free sem cartão | N/A para a nuvem (nada de deploy mudou). Configuração local do broker: ✅, com SEC-01 e SEC-03 |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma: os commits do orquestrador (`56360f8`, `5ab96d5`, `a49fcf5`, `0f58379`) só mudam status, rodada, o plano e o Histórico com a decisão do humano de 2026-10-26; nenhum requisito, limite ou CA alterado |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| `paho-mqtt` | 2.1.0 (travada no `uv.lock`; faixa `>=2.1,<3`) | EPL-2.0 OR BSD-3-Clause | Sem aviso no OSV, no GitHub Advisory Database e nos advisories do repositório (2026-10-26). Última versão de 2024-04-29; repositório oficial ativo. Só no `qc-edge` |
| Mosquitto (pacote do sistema, não entra no `uv.lock`) | 2.1.2 (Arch `extra`; imagem `eclipse-mosquitto:2` nos testes) | EPL-2.0 / EDL-1.0 | Instalado pelo humano (§3.3). Não encontrei aviso público que afete o 2.1.2 (os avisos recentes de distribuições tratam de CVEs de 2024 já corrigidos em linhas anteriores). Manter o pacote atualizado pelo `pacman` |

## Ações para o humano

- Seguir o §3.3 com o arquivo de senhas em `~/.config/partqc/` (diretório `700`), copiando o `partqc.conf` para fora do repositório antes de trocar `<usuario>` (RV-03).
- Não deixar a senha do broker no histórico do shell ao usar o `mosquitto_sub` (SEC-02).
- Registrar o CA-11 com o pacote do Arch e o CA-12 (pendências da Definição de pronto, já apontadas pelo tester e pelo reviewer).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
