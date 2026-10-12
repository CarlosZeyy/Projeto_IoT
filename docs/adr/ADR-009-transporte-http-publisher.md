# ADR-009: Enviar da borda para a nuvem por HTTP REST, atrás de uma interface `Publisher`; MQTT opcional na Fase 3

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-002, ADR-006, ADR-008, SPEC-004, SPEC-009, SPEC-020, R-01, R-02, R-05, N-08 |

## Contexto

A borda grava cada inspeção no outbox SQLite e precisa entregá-la à nuvem **exatamente uma vez** (RF-06, RNF-04), mesmo com queda de rede e cold start da API (ADR-008). Em matérias de IoT, MQTT é o protocolo esperado com frequência, mas exige um broker:

- a página oficial de preços do HiveMQ **não lista mais** um plano gratuito Serverless. Fonte: <https://www.hivemq.com/pricing/> (verificado em 2026-10-12);
- um broker próprio na nuvem free tier precisaria de um processo sempre ligado, que os serviços escolhidos não oferecem (hibernam, ADR-008);
- um Mosquitto local, no notebook, é gratuito, mas fica na LAN e não leva os dados à nuvem sozinho.

A expectativa do professor ainda não é conhecida (pergunta 1 de `docs/professor-questions.md`).

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) HTTP REST (`POST /api/v1/inspections/batch`) atrás de uma interface `Publisher`, com `HttpPublisher` no MVP | A API já existe; a idempotência por `inspection_id` resolve os reenvios; lotes de até 100; funciona com a API hibernando (backoff); nenhum serviço extra | Não é publish/subscribe; pode ser visto como "menos IoT" |
| B MQTT com broker na nuvem (HiveMQ Cloud ou outro gerenciado) | Protocolo típico de IoT; QoS 1 | Sem plano gratuito oficial verificado; ainda precisaria de um consumidor que grave no Postgres; mais uma peça para operar |
| C MQTT com Mosquitto local + ponte para a API | Gratuito; mostra MQTT na demo | Mais processos na borda; a ponte acaba usando HTTP do mesmo jeito; só faz sentido como extra |

## Decisão

No MVP, a borda publica por **HTTP REST** com o `HttpPublisher`:

- lotes de até 100 inspeções via `/inspections/batch`;
- timeout de 5 s e backoff exponencial de 1 s a 60 s, com jitter;
- a inspeção é marcada como enviada ao receber `created` ou `duplicate`.

O envio fica atrás de uma interface **`Publisher`**, para que um `MqttPublisher` (Fase 3, SPEC-020, com Mosquitto local) entre sem mudar o outbox.

## Consequências

- **Positivas:**
  - um único caminho de escrita na nuvem, autenticado por dispositivo (`X-API-Key`) e testado (SPEC-004);
  - a idempotência no banco (`ON CONFLICT DO NOTHING`) tolera qualquer número de reenvios (R-05).
- **Negativas / custos aceitos:**
  - sem push da nuvem para a borda; a borda descobre a conectividade pelo resultado do envio;
  - o MQTT, se for exigido, entra como extra e não como base.
- **O que passa a ser obrigatório:**
  - o outbox e o laço de envio dependem só da interface `Publisher`, e não de `httpx` diretamente (SPEC-009);
  - só o JSON do contrato (`InspectionCreate`) sai da borda; nenhuma imagem (R-02);
  - o teste de aceite da SPEC-009 cobre RNF-04: 200 inspeções com a nuvem fora do ar por 2 min, 0 perdas e 0 duplicatas;
  - qualquer broker MQTT usado precisa ser gratuito e sem cartão (R-01).

## Quando revisitar

- Quando o professor responder a pergunta 1: se exigir MQTT, a SPEC-020 sobe de prioridade e este ADR é substituído.
- Se um broker MQTT gerenciado, gratuito e sem cartão for verificado em fonte oficial.
