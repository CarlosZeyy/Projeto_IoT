# SPEC-020: Fase 3 — transporte MQTT

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-009 (e SPEC-004) |
| Semana alvo | S8 (só se a Fase 2 fechar no prazo, ou antes, se o professor exigir) |
| Requisitos cobertos | PRD §4.3; RF-06, RF-07 (mantidos com o novo transporte) |
| ADRs relevantes | ADR-009, ADR-008, ADR-002 |

> **Rascunho.** Só deve ser refinada se o professor exigir MQTT (`docs/professor-questions.md`, pergunta 1). Precisa de refinamento do `architect`, decisão humana sobre o broker e aprovação humana antes de virar `Ready`.

## 1. Contexto

O MVP usa HTTP da borda para a nuvem (N-08, ADR-009): o outbox (SPEC-009) envia por `HttpPublisher`, que implementa o Protocol `Publisher`. MQTT é comum em IoT, mas o projeto não tem um broker gratuito e sempre ligado confirmado (`docs/deployment-plan.md` §2).

## 2. Objetivo

Um `MqttPublisher`, alternativo ao `HttpPublisher` e escolhido por variável de ambiente, entrega as inspeções do outbox via MQTT sem perder nem duplicar registros.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/publishers/mqtt.py`: `MqttPublisher` que implementa o Protocol `Publisher` da SPEC-009.
- Tópico `partqc/v1/<device_id>/inspections`, QoS 1, payload = JSON do `InspectionCreate` (`qc_contracts`).
- `EDGE_PUBLISHER=http|mqtt` (padrão `http`), `MQTT_URL`, `MQTT_USERNAME`, `MQTT_PASSWORD`.
- Um assinante que grava na nuvem, conforme a opção escolhida em §4.

### 3.2 Fora

- Trocar o HTTP como padrão; MQTT para o heartbeat (SPEC-018), salvo decisão posterior.

## 4. Opções de arquitetura (preliminar)

| Opção | Como | Problema |
|---|---|---|
| (a) Mosquitto local + ponte | Broker no notebook; um processo na própria borda assina o tópico e repassa à API por HTTP | A nuvem continua recebendo por HTTP; o MQTT fica só dentro da LAN |
| (b) Assinante na nuvem | Serviço sempre ligado assinando um broker na internet | Antes do ADR-018: o Render free dorme e não acorda com MQTT. Desde o ADR-018 (2026-10-18), a VPS pessoal fica sempre ligada e poderia hospedar um broker (Mosquitto) e o assinante no compose. Exigiria publicar mais uma porta (MQTT sobre TLS), com autenticação por dispositivo e regra de firewall só acrescentada (SPEC-015 §4.15), e uma revisão de segurança própria |
| (c) Broker gerenciado gratuito | Broker na nuvem + assinante | A página oficial do HiveMQ não lista mais plano gratuito (<https://www.hivemq.com/pricing/>, verificado em 2026-10-12); brokers públicos de teste não têm privacidade |

A nuvem não consegue assinar um broker da LAN sem expor o notebook à internet. **Recomendação:** implementar só se o professor exigir, e então a opção (a), que mostra o protocolo sem custo e sem expor a rede.

## 5. Requisitos-chave (preliminares)

- Idempotência mantida pelo `inspection_id` (R-05): o assinante usa a mesma ingestão da API.
- O outbox só marca como enviado após a confirmação **de ponta a ponta**; o PUBACK do QoS 1 só confirma o broker, não o banco.
- Payload sem imagem (R-02); credenciais do broker só no `.env` (R-03).

## 6. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* `EDGE_PUBLISHER=mqtt` e um broker de teste local, *quando* 20 inspeções entram no outbox, *então* 20 mensagens válidas como `InspectionCreate` chegam ao tópico do dispositivo.
- **CA-02 (preliminar, R-05)** — *Dado* a mesma mensagem publicada 2 vezes, *quando* o assinante processa, *então* a API registra 1 inspeção (`created` e `duplicate`).
- **CA-03 (preliminar)** — *Dado* o broker fora do ar por 2 min durante 200 inspeções, *quando* ele volta, *então* há 0 perdas e 0 duplicatas (RNF-04).
- **CA-04 (preliminar)** — *Dado* `EDGE_PUBLISHER=xyz`, *quando* a borda inicia, *então* falha com uma mensagem clara de configuração.

## 7. Perguntas em aberto

1. O professor exige MQTT (pergunta 1)? Se não, esta SPEC é descartada.
2. Biblioteca: `paho-mqtt` (licença EPL/EDL) ou `aiomqtt`? Conferir licença e manutenção (portão de segurança).
3. Na opção (a), a "ponte" na mesma máquina demonstra o suficiente, ou o professor espera o broker fora do notebook?
4. ~~Se a SPEC avançar, ela precisa da tag `security` (credenciais e rede)? O quadro do `docs/plan.md` hoje não traz tag.~~ Resolvido: a SPEC e o quadro do `docs/plan.md` têm a tag `security`.
5. Com a VPS sempre ligada (ADR-018), a opção (b) passa a ser viável sem custo. A recomendação da §4 (opção (a)) continua até o professor responder a pergunta 1; se ele esperar o broker fora do notebook, reavaliar a (b) com um ADR.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-18 | §4, opção (b), e §7, pergunta 5: a VPS pessoal sempre ligada torna a opção (b) viável; a recomendação não muda. A SPEC continua `Draft`. | ADR-018 (hospedagem na VPS pessoal) | Orquestrador, a pedido do humano |
