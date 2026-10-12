# SPEC-017: Fase 2 — alertas no Telegram

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-006 (e SPEC-003, SPEC-004) |
| Semana alvo | S6 |
| Requisitos cobertos | RF-17; PRD §4.2 |
| ADRs relevantes | ADR-013, ADR-006, ADR-008 |

> **Rascunho.** Precisa de refinamento do `architect` e de aprovação humana antes de virar `Ready`.

## 1. Contexto

A carta p (SPEC-006, `docs/architecture.md` §3.4) mostra lotes fora de controle, mas só quando alguém abre o dashboard. Um aviso ativo no celular do supervisor fecha o ciclo da Indústria 4.0. Bots do Telegram são gratuitos e não exigem cartão (R-01).

## 2. Objetivo

Quando um lote `live` **recém-concluído** fica fora de controle, a API envia **uma** mensagem de texto para um chat do Telegram configurado.

## 3. Escopo

### 3.1 Dentro

- `api/src/qc_api/services/alerts.py`: detecção do lote concluído e fora de controle, deduplicação e envio.
- Migração `infra/migrations/NNN_alerts.sql`: tabela `alerts_sent(lot_id, source, kind, sent_at)`, com `unique (lot_id, source, kind)` e RLS ligado, sem políticas.
- Variáveis `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` e `ALERTS_ENABLED` (padrão `false`) no `.env.example` e no painel do Render.

### 3.2 Fora

- Alertas por e-mail ou outros canais; alertas de dispositivo offline (poderiam vir da SPEC-018).

## 4. Requisitos-chave (preliminares)

- **Gatilho:** avaliado depois de cada ingestão (`BackgroundTasks` do FastAPI, sem atrasar a resposta) **ou** por um endpoint `POST /api/v1/alerts/check` chamado periodicamente. A escolha está em aberto (§6).
- **Regra:** usa `compute_p_chart` (SPEC-006) com `source=live` e os parâmetros padrão. Alerta só para o lote recém-concluído com `out_of_control = true` e `n ≥ min_lot_size`.
- **Deduplicação:** no máximo 1 mensagem por `(lot_id, source, kind)`, garantida pelo `unique` (`INSERT ... ON CONFLICT DO NOTHING` antes de enviar).
- **Mensagem** (PT-BR, só texto, **sem imagens** — R-02): `Lote L-007 fora de controle: p = 40,0% (LSC 31,2%), n = 25, defeituosas = 10. Origem: real.`
- **Envio:** `POST https://api.telegram.org/bot<token>/sendMessage` via `httpx`, timeout de 5 s, sem retry infinito. Falha do Telegram é logada e **nunca** afeta a ingestão.
- **Segurança (R-03):** o token compõe a URL; os logs do `httpx` e os da aplicação não podem mostrá-la. O token não aparece em respostas nem em exceções.
- Dados `simulated` não geram alerta, salvo uma flag explícita para a demo (em aberto).

## 5. Critérios de aceite (preliminares)

- **CA-01 (preliminar)** — *Dado* lotes `live` em que o último concluído tem `out_of_control = true`, *quando* a verificação roda com o Telegram mockado (`httpx.MockTransport`), *então* exatamente 1 `sendMessage` é feito, com o `chat_id` configurado e o texto contendo o `lot_id`.
- **CA-02 (preliminar)** — *Dado* o mesmo lote já alertado, *quando* a verificação roda de novo, *então* nenhum `sendMessage` é feito.
- **CA-03 (preliminar)** — *Dado* o Telegram respondendo 500 ou estourando o timeout, *quando* uma inspeção é ingerida, *então* a ingestão responde 201 normalmente e o erro é logado sem o token.
- **CA-04 (preliminar, R-03)** — *Dado* `caplog` em `DEBUG`, *quando* um alerta é enviado, *então* o valor de `TELEGRAM_BOT_TOKEN` não aparece em nenhum log.
- **CA-05 (preliminar, R-06)** — *Dado* um lote `simulated` fora de controle, *quando* a verificação roda, *então* nenhum alerta é enviado.
- **CA-06 (preliminar)** — *Dado* `ALERTS_ENABLED=false`, *quando* a verificação roda, *então* nenhuma chamada externa é feita.

## 6. Perguntas em aberto

1. **O que é "lote concluído"?** O contrato não tem esse evento. Opções: nenhuma inspeção no lote há X minutos (ex.: 10); o mesmo dispositivo começou outro lote; ou um campo/endpoint novo de fechamento de lote (mudança de contrato).
2. **Gatilho:** ingestão (acorda junto com o Render) × verificação periódica pelo GitHub Actions (consome a cota de minutos do repositório privado; intervalo mínimo de 5 min).
3. Enquanto houver menos de `baseline_lots` lotes, `p̄` muda a cada lote novo e um lote antigo pode passar a ficar fora de controle. Alertar só o lote recém-concluído, avaliado no momento da conclusão?
4. Permitir alertas de dados `simulated` na demo, com o selo "SIMULADO" no texto?
5. Limite global de mensagens por hora para evitar spam em caso de bug.
