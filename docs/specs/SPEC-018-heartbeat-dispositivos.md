# SPEC-018: Fase 2 — heartbeat e página de dispositivos

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | contrato, security |
| Depende de | SPEC-004 (e SPEC-002, SPEC-003, SPEC-009, SPEC-013) |
| Semana alvo | S6 |
| Requisitos cobertos | RF-18; PRD §4.2 |
| ADRs relevantes | ADR-002, ADR-006, ADR-007, ADR-009 |

> **Rascunho.** Precisa de refinamento do `architect` e de aprovação humana antes de virar `Ready`.

## 1. Contexto

Hoje a nuvem só sabe que a borda existe quando chega uma inspeção (`devices.last_seen_at`, `docs/architecture.md` §4). Telemetria de saúde do gateway (modelo carregado, fila pendente, tempo ligado) é típica de IoT e ajuda na demo e na operação.

## 2. Objetivo

A borda envia um heartbeat a cada 60 s, e o dashboard mostra cada dispositivo como online (último heartbeat há menos de 3 min) ou offline, com o estado do gateway.

## 3. Escopo

### 3.1 Dentro

- Contrato (`qc-contracts` minor): `HeartbeatCreate` (`sent_at`, `model_version`, `model_sha256`, `app_version`, `uptime_s` ≥ 0, `outbox_pending` ≥ 0, `outbox_dead` ≥ 0; `extra="forbid"`) e `DeviceStatus` (`device_id`, `last_seen_at`, `last_heartbeat_at`, `online`, mais os campos do último heartbeat).
- API: `POST /api/v1/devices/{device_id}/heartbeat` (chave de dispositivo) → 204; `GET /api/v1/devices` (chave de leitura) → `list[DeviceStatus]`.
- Banco: migração com as colunas do último heartbeat em `devices` (um upsert por heartbeat; sem histórico).
- Borda: laço em segundo plano a cada `HEARTBEAT_INTERVAL_S` (padrão 60).
- Dashboard: página "Dispositivos".

### 3.2 Fora

- Histórico de heartbeats e gráficos de saúde; alerta de dispositivo offline (poderia estender a SPEC-017).

## 4. Requisitos-chave (preliminares)

- `device_id` do caminho precisa ser o dono da chave → senão 403; sem chave ou chave inválida → 401; corpo inválido → 422. Mesma comparação em tempo constante da SPEC-004.
- `online = now − last_heartbeat_at < 180 s`, calculado **no servidor** (UTC).
- O heartbeat **não** passa pelo outbox: é efêmero. Falha de envio é logada e ignorada.
- Corpo pequeno (< 1 KB), sem imagem nem dado pessoal (R-02).
- Dashboard: tabela com `Dispositivo`, `Situação` (`online`/`offline`), `Último sinal` (hora local), `Modelo`, `Versão`, `Pendentes`, `Com falha`, `Ligado há`.

## 5. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* um dispositivo registrado, *quando* faz `POST /api/v1/devices/edge-01/heartbeat` com a própria chave e corpo válido, *então* a resposta é 204 e `GET /api/v1/devices` mostra `online = true` e `outbox_pending` igual ao enviado.
- **CA-02 (preliminar)** — *Dado* a chave de `edge-01`, *quando* envia heartbeat para `/devices/sim-01/heartbeat`, *então* a resposta é 403; sem chave, 401; com um campo extra no corpo, 422.
- **CA-03 (preliminar)** — *Dado* um último heartbeat há 181 s (relógio controlado no teste), *quando* `GET /api/v1/devices` é chamado, *então* `online = false`.
- **CA-04 (preliminar)** — *Dado* a nuvem fora do ar (MockTransport com erro), *quando* o laço de heartbeat roda, *então* a borda continua inspecionando e nada é gravado no outbox.
- **CA-05 (preliminar)** — *Dado* `GET /api/v1/devices` sem a chave de leitura, *quando* chamado, *então* a resposta é 401.

## 6. Perguntas em aberto

1. ~~**Tag `security`:** a SPEC cria uma rota autenticada nova; pela skill `criar-spec`, deveria ter a tag `security` (o quadro do `docs/plan.md` só traz `contrato`).~~ Resolvido: a SPEC e o quadro do `docs/plan.md` têm as tags `contrato, security`.
2. ~~`outbox_dead` pressupõe um estado "morto" no outbox da SPEC-009. Confirmar que ele existe e com que nome.~~ Resolvido: a SPEC-009 define o status `dead` no outbox (`mark_dead`, campo `dead` de `SinkStats`).
3. ~~Heartbeat a cada 60 s mantém o Render acordado enquanto a borda está ligada. Está dentro das 750 h/mês, mas vale registrar.~~ Superado pelo ADR-018 (2026-10-18): a API fica sempre ligada na VPS, e o heartbeat não tem efeito de custo. Com a reserva no Render ativa, vale a nota antiga.
4. O simulador (SPEC-014) deve enviar heartbeats com `source` simulado? O contrato do heartbeat não tem `source`; a página precisa distinguir dispositivos simulados (R-06)?

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-18 | §6, pergunta 3: nota do Render superada, porque a API fica sempre ligada na VPS. A SPEC continua `Draft`. | ADR-018 (hospedagem na VPS pessoal) | Orquestrador, a pedido do humano |
