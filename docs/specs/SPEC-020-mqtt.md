# SPEC-020: Fase 3 — transporte MQTT (Mosquitto local e ponte para a API)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-009, SPEC-030, SPEC-034 (e SPEC-004). Sem mudança de contrato |
| Semana alvo | S8, **só se a Fase 2 fechar no prazo** (PRD §4.3), ou antes, se o professor exigir MQTT (`docs/professor-questions.md`, pergunta 1) |
| Requisitos cobertos | PRD §4.3; RF-06, RF-07, RNF-04 (mantidos com o novo transporte); R-01, R-02, R-03, R-05, R-12 |
| ADRs relevantes | ADR-009 (decisão: `MqttPublisher` com Mosquitto local na Fase 3, atrás da interface `Publisher`), ADR-018, ADR-002 |

> **Pronta para a aprovação humana**, com a regra de escopo mantida. Revista pelo architect em 2026-10-24 (ver o Histórico). Segue a opção C do ADR-009 (Mosquitto local + ponte); nenhum ADR novo é necessário enquanto o broker ficar no notebook.

## 1. Contexto

O MVP envia da borda para a nuvem por HTTP (N-08, ADR-009), com o `HttpPublisher` atrás do Protocol `Publisher` da SPEC-009. O ADR-009 já previu um `MqttPublisher` na Fase 3, com Mosquitto local, sem mudar o outbox.

Fatos verificados pelo architect em 2026-10-24:

- **Mosquitto** é software livre (EPL/EDL) e implementa MQTT 5.0, 3.1.1 e 3.1 (<https://mosquitto.org/>); está no repositório oficial `extra` do Arch Linux, versão 2.1.2-2 (<https://archlinux.org/packages/?q=mosquitto>). Custo zero e sem cartão (R-01).
- **paho-mqtt** 2.1.0 (29/04/2024), licença `EPL-2.0 OR BSD-3-Clause`, implementa MQTT 5.0, 3.1.1 e 3.1 (<https://pypi.org/project/paho-mqtt/>).

**Por que broker local e ponte (opção C do ADR-009):** a nuvem não consegue assinar um broker da LAN sem expor o notebook à internet, e um broker na VPS (ADR-018) exigiria publicar mais uma porta com TLS e autenticação por dispositivo fora do Caddy, com revisão de segurança própria. Com o broker escutando só em loopback no notebook, o protocolo aparece na demo, a rede não fica exposta e a nuvem continua recebendo pela rota já autenticada e testada (SPEC-004). Se o professor esperar o broker fora do notebook (pergunta 1 e pergunta 3 do rascunho), isso exige um ADR novo (§3.2).

## 2. Objetivo

Com `EDGE_PUBLISHER=mqtt`, a borda entrega as inspeções do outbox por MQTT a um broker Mosquitto local, uma ponte as repassa à API, e o outbox só marca um item como enviado depois da confirmação de ponta a ponta, sem perder nem duplicar registros (RNF-04).

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/mqtt_transport.py`: Protocol `MqttTransport`, a implementação com paho-mqtt (MQTT 5) e um `InMemoryBroker` determinístico para testes (§4.2).
- `edge/src/qc_edge/mqtt_publisher.py`: `MqttPublisher`, que implementa o Protocol `Publisher` (§4.3).
- `edge/src/qc_edge/mqtt_bridge.py`: `python -m qc_edge.mqtt_bridge`, a ponte (§4.4).
- Escolha do publisher na subida do `qc-edge` e configuração (§4.5).
- `edge/mosquitto/partqc.conf` (exemplo de configuração do broker) e `edge/README.md` (seção "Transporte MQTT").
- `edge/pyproject.toml` com `paho-mqtt` e o `uv.lock` (regenerado por `uv lock`), `.env.example`.
- Marcador de teste `mqtt` no `pyproject.toml` da raiz (§6).
- Testes do autor em `edge/tests/` (fora de `acceptance/`).
- **Tester:** `edge/tests/acceptance/test_spec_020.py`.

### 3.2 Fora

- Trocar o HTTP como padrão (`EDGE_PUBLISHER=http` continua o padrão).
- Broker fora do notebook (na VPS ou gerenciado): exige um ADR novo, que trate da porta publicada, do TLS e da autenticação por dispositivo; só se o professor pedir.
- Heartbeat por MQTT (a SPEC-018 usa HTTP).
- MQTT entre o celular e a borda.

### 3.3 Trabalho humano

1. `sudo pacman -S mosquitto`; criar o arquivo de senhas com `mosquitto_passwd` fora do repositório; subir o broker com o `edge/mosquitto/partqc.conf` (só loopback, sem anônimo).
2. Pôr `MQTT_USERNAME` e `MQTT_PASSWORD` no `.env` local (nunca no Git, R-03).
3. Executar o CA-12 (manual).

## 4. Requisitos detalhados

### 4.1 Tópicos e mensagens (MQTT 5, QoS 1)

| Tópico | Quem publica | Payload | Propriedades |
|---|---|---|---|
| `partqc/v1/<device_id>/batch` | `MqttPublisher` | `qc_contracts.BatchCreate` em JSON (1 a 100 itens) | `ResponseTopic`, `CorrelationData` (16 bytes aleatórios) |
| `partqc/v1/<device_id>/health` | `MqttPublisher` | vazio | `ResponseTopic`, `CorrelationData` |
| `ResponseTopic` (`partqc/v1/<device_id>/reply/<id da sessão do publisher>`) | ponte | ver `result` | `CorrelationData` copiada do pedido; propriedade de usuário `result` |

- `result` ∈ `ok`, `rejected`, `auth`, `transient`. Com `ok`, o payload de uma resposta a `batch` é o `qc_contracts.BatchResult` em JSON, e o de `health` é vazio. Com `rejected`, o payload é o resumo da recusa da SPEC-009 §4.2 (`HTTP <status>: …`), em UTF-8, **nunca** o corpo da API. Com `auth` e `transient`, o payload é vazio.
- Nenhum payload tem imagem (R-02). Nenhum schema novo: os payloads são os do `qc-contracts` (R-04).

### 4.2 Transporte

- `MqttTransport` (Protocol): conectar, publicar com propriedades, assinar com callback, desconectar. A implementação real usa `paho-mqtt` com `protocol=MQTTv5`, usuário e senha, e é o **único** módulo da borda que importa `paho`.
- `InMemoryBroker`: entrega síncrona e determinística entre clientes do mesmo processo, com `stop()` e `start()` para simular queda; só para testes, sem rede.

### 4.3 `MqttPublisher`

```python
class MqttPublisher:            # implementa Publisher (SPEC-009 §4.2)
    def __init__(self, transport: MqttTransport, device_id: str, response_timeout_s: float = 15.0) -> None
    def publish_batch(self, items: Sequence[InspectionCreate]) -> list[PublishResult]: ...
    def check_health(self) -> bool: ...
```

- `publish_batch` publica o `BatchCreate` e espera a resposta com a mesma `CorrelationData` por até `response_timeout_s`:
  - `ok` com um `BatchResult` válido, do mesmo tamanho, com os mesmos ids na mesma ordem → a lista de `PublishResult` (como o `HttpPublisher`);
  - `rejected` → `PublishRejectedError(detail=<payload>)`; `auth` → `PublishAuthError`;
  - `transient`, resposta malformada, timeout, broker fora do ar ou desconexão → `PublishTransientError`.
- O PUBACK do QoS 1 só confirma o broker e **nunca** marca um item como enviado. O `PublishLoop`, o backoff, a bissecção e o `dead` da SPEC-009 não mudam.
- `check_health`: `True` só com resposta `ok` a `health` dentro do prazo.
- Respostas com `CorrelationData` desconhecida são descartadas.

### 4.4 Ponte (`python -m qc_edge.mqtt_bridge`)

- Lê do `.env` `DEVICE_ID`, `DEVICE_API_KEY`, `CLOUD_API_URL` (regras da SPEC-009) e as variáveis `MQTT_*` (§4.5). Assina só `partqc/v1/<DEVICE_ID>/batch` e `partqc/v1/<DEVICE_ID>/health`, com QoS 1.
- Para cada `batch`: valida o payload como `BatchCreate` (inválido → `rejected` com `HTTP 422: invalid batch payload`); chama `HttpPublisher.publish_batch` (o `httpx` continua só em `publisher.py`, com os limites da SPEC-030); responde `ok` com o `BatchResult`, ou `rejected`, `auth` ou `transient`, conforme a exceção do `HttpPublisher`.
- Para cada `health`: `HttpPublisher.check_health()` → `ok` ou `transient`.
- Pedido sem `ResponseTopic` ou sem `CorrelationData` → ignorado, com um aviso.
- A ponte não guarda estado: se ela cair entre a API e a resposta, o publisher não recebe a resposta, reenvia, e a idempotência por `inspection_id` devolve `duplicate` (R-05).
- Logs só com contagens, `result` e o tópico; nunca o payload, a senha nem a `DEVICE_API_KEY`.
- Saída: 0 ao receber SIGINT/SIGTERM; 2 com configuração inválida.

### 4.5 Configuração e escolha do publisher

| Variável | Padrão | Regra |
|---|---|---|
| `EDGE_PUBLISHER` | `http` | `http` ou `mqtt`; outro valor → erro na subida, código 2, com `EDGE_PUBLISHER must be http or mqtt` |
| `MQTT_HOST` | `127.0.0.1` | só `127.0.0.1`, `::1` ou `localhost` (broker no notebook, §1); outro → código 2 |
| `MQTT_PORT` | `1883` | inteiro de 1 a 65535 |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | vazios | obrigatórias com `EDGE_PUBLISHER=mqtt` e na ponte |
| `MQTT_RESPONSE_TIMEOUT_S` | `15` | número de 1 a 60 |

- Com `EDGE_PUBLISHER=mqtt`, a borda usa o `MqttPublisher` no `PublishLoop`, nas mesmas condições da SPEC-009 §4.4 (com `DEVICE_API_KEY` e `CLOUD_API_URL`, que a ponte usa; sem `--stub-model`). Com `--stub-model`, nada muda: `InMemorySink` e nenhum publisher (R-06).
- A senha do MQTT não aparece em log, em `/api/status` nem no console.
- `edge/mosquitto/partqc.conf`: `listener 1883 127.0.0.1`, `allow_anonymous false`, `password_file` com um caminho de exemplo fora do repositório.

## 5. Critérios de aceite

Contexto comum: `InMemoryBroker`; a API simulada por um `httpx.MockTransport` idempotente (guarda cada `inspection_id` uma vez e responde `created` ou `duplicate`, como a SPEC-004); a ponte e o publisher no mesmo processo; relógio injetado no `PublishLoop`.

- **CA-01 (entrega)** — *Dado* `EDGE_PUBLISHER=mqtt`, a ponte ligada e 20 inspeções no outbox, *quando* o `PublishLoop` roda até esvaziar, *então* a API simulada guardou as 20, uma vez cada, as 20 linhas do outbox estão `sent`, e cada mensagem publicada em `partqc/v1/<device_id>/batch` valida como `BatchCreate`.
- **CA-02 (R-05, resposta perdida)** — *Dado* a ponte configurada no teste para descartar a primeira resposta depois de chamar a API, *quando* o `PublishLoop` roda até esvaziar com 5 inspeções, *então* a API simulada guardou as 5 uma vez cada, recebeu o lote duas vezes (a segunda com 5 `duplicate`) e as 5 linhas estão `sent`.
- **CA-03 (RNF-04)** — *Dado* 200 inspeções entrando no outbox enquanto o broker fica parado por 2 minutos do relógio injetado (`stop()` e depois `start()`), *quando* o `PublishLoop` roda até esvaziar, *então* a API simulada tem 200 `inspection_id` distintos, nenhum gravado duas vezes, e nenhuma linha do outbox fica `pending` ou `dead`.
- **CA-04 (sem ponte = sem confirmação)** — *Dado* o broker ligado e a ponte desligada, *quando* um ciclo do `PublishLoop` roda com 3 inspeções e `MQTT_RESPONSE_TIMEOUT_S=1`, *então* o PUBACK acontece, mas as 3 linhas continuam `pending` com `attempts == 1` (retry da SPEC-009).
- **CA-05 (recusa)** — *Dado* a API simulada respondendo 422 com `{"detail": "Value cannot be stored"}` para um dos 4 itens de um lote (e 200 para os outros, nos lotes sem ele), *quando* o `PublishLoop` roda, *então* esse item fica `dead` com `last_error == "HTTP 422: Value cannot be stored"` e os outros 3 ficam `sent` (bissecção da SPEC-009); e o payload de nenhuma resposta da ponte contém o corpo devolvido pela API além desse resumo.
- **CA-06 (autenticação)** — *Dado* a API simulada respondendo 401, *quando* um ciclo roda, *então* o `PublishLoop` entra em `auth_error` (SPEC-009 §4.3) e não faz nova publicação no ciclo seguinte.
- **CA-07 (health)** — *Dado* a ponte ligada e a API simulada respondendo 200 em `/api/v1/health`, *então* `check_health()` devolve `True`; com a ponte desligada, devolve `False` dentro de `MQTT_RESPONSE_TIMEOUT_S`.
- **CA-08 (configuração)** — *Dado* `EDGE_PUBLISHER=xyz`, ou `EDGE_PUBLISHER=mqtt` com `MQTT_HOST=192.168.0.10`, ou com `MQTT_PASSWORD` vazio, *quando* a borda sobe, *então* sai com código 2; o primeiro caso imprime `EDGE_PUBLISHER must be http or mqtt`. *Dado* `python -m qc_edge.mqtt_bridge` sem `DEVICE_API_KEY`, *então* sai com 2.
- **CA-09 (segredos, R-03)** — *Dado* a captura de logs da borda e da ponte durante os CA-01, CA-05 e CA-06, *então* nenhum registro contém `MQTT_PASSWORD`, `DEVICE_API_KEY` nem um payload de lote.
- **CA-10 (isolamento, R-12)** — *Dado* o código, *então* só `qc_edge/mqtt_transport.py` importa `paho`, só `qc_edge/publisher.py` importa `httpx`; e o `paho-mqtt` não está no fecho de dependências do `qc-api` nem do `qc-dashboard` no `uv.lock`.
- **CA-11 (broker real, marcador `mqtt`)** — *Dado* `PARTQC_MQTT_TESTS=1` e o executável `mosquitto` no `PATH` (senão o teste é pulado), com um broker iniciado pelo teste numa porta livre de `127.0.0.1` com usuário e senha, *quando* o CA-01 é repetido com o `MqttTransport` real, *então* o resultado é o mesmo; e uma conexão sem senha é recusada pelo broker.
- **CA-12 (manual, dupla)** — 1. Broker local pelo §3.3; 2. ponte e borda com `EDGE_PUBLISHER=mqtt`; 3. inspecionar 10 peças; 4. conferir as 10 na nuvem; 5. derrubar a ponte, inspecionar 3 peças, conferir que ficam pendentes no console, religar a ponte e conferir as 3 na nuvem; 6. `mosquitto_sub` com o usuário mostra os lotes no tópico, sem imagem.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Publisher (cada `result`, timeout, correlação, resposta malformada); ponte (validação, mapeamento, pedido sem propriedades); configuração | `edge/tests/` |
| Aceite (tester) | Um por CA automatizado; o CA-11 com o marcador `mqtt` | `edge/tests/acceptance/test_spec_020.py` |
| Manual (dupla) | CA-12 | descrito no CA |

- O marcador `mqtt` entra na lista de `docs/architecture.md` §10 (como o `docker`): o teste só roda com `PARTQC_MQTT_TESTS=1` e o `mosquitto` instalado, e não roda no CI.
- Nenhum teste usa broker público ou rede externa.

## 7. Riscos e notas para o implementador

- **Confirmação de ponta a ponta:** o item só vira `sent` com a resposta `ok` da ponte, que só existe depois da resposta da API. A ponte não precisa de persistência nem de ack manual.
- **Sessão do publisher:** use um identificador de sessão aleatório no `ResponseTopic`, para que respostas atrasadas de uma subida anterior sejam descartadas.
- **Licença:** `paho-mqtt` é `EPL-2.0 OR BSD-3-Clause`; o reviewer confere a versão travada no `uv.lock`.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS); CA-11 rodado localmente e registrado
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md`, `.env.example` e `edge/mosquitto/partqc.conf`; `docs/architecture.md` §6.2 e §10 pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-12 manual registrado

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-18 | §4, opção (b), e §7, pergunta 5: a VPS pessoal sempre ligada torna a opção (b) viável; a recomendação não muda. A SPEC continua `Draft`. | ADR-018 (hospedagem na VPS pessoal) | Orquestrador, a pedido do humano |
| 2026-10-24 | SPEC reescrita para a aprovação, com a regra de escopo mantida e sem esperar a resposta do professor (o humano liberou todas as fases). Decisões do architect: opção (a)/C do ADR-009, com o broker só em loopback e sem anônimo; MQTT 5 com pedido e resposta (`ResponseTopic` e `CorrelationData`) e os payloads do contrato, sem schema novo; confirmação de ponta a ponta pela resposta da ponte, nunca pelo PUBACK; ponte sem estado que reusa o `HttpPublisher`; `paho-mqtt` 2.1.0 (licença verificada em 2026-10-24) isolado num módulo; `InMemoryBroker` para os testes e marcador `mqtt` para o broker real; broker fora do notebook só com ADR novo; dependências das SPECs 030 e 034; CAs CA-01 a CA-11 testáveis e CA-12 manual. Perguntas do rascunho: 1 e 3 (professor) ficam como gatilho de ADR; 2 resolvida (`paho-mqtt`); 4 e 5 já resolvidas. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
