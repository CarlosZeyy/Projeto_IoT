# SPEC-017: Fase 2 — alertas no Telegram

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-006, SPEC-026, SPEC-015 (a API publicada na VPS, para o CA manual) e SPEC-016 (SPC por `grade is not null`, ADR-021) (e SPEC-003, SPEC-004, SPEC-014) |
| Semana alvo | S6 |
| Requisitos cobertos | RF-17; PRD §4.2; R-01, R-02, R-03, R-06 |
| ADRs relevantes | ADR-013, ADR-017, ADR-018, ADR-021, ADR-006 |

> **Aprovada pelo humano em 2026-10-24** (PR #45), no pacote das Fases 2 e 3, com os ADRs 021 e 022 `Aceito`. Revista pelo architect em 2026-10-24 (ver o Histórico). Sem mudança de contrato.

## 1. Contexto

A carta p (SPEC-006, `docs/architecture.md` §3.4) mostra lotes fora de controle, mas só quando alguém abre o dashboard. Um aviso ativo no celular do supervisor fecha o ciclo da Indústria 4.0. Desde o ADR-018, a API roda sempre ligada na VPS pessoal, então a verificação pode rodar dentro do próprio processo da API, sem agendador externo.

**Custo (R-01):** a Bot API do Telegram é gratuita para mensagens comuns: "bots are able to message their users at no cost" (<https://core.telegram.org/bots/faq>, consultado pelo architect em 2026-10-24). A mesma página limita a uma mensagem por segundo num chat e a 20 por minuto num grupo; o teto desta SPEC (10 por hora) fica muito abaixo disso. As chamadas são `https://api.telegram.org/bot<token>/<método>` (<https://core.telegram.org/bots/api>, consultado em 2026-10-24): o token vai na URL, o que exige cuidado com os logs (§4.5).

## 2. Objetivo

Quando um lote `live` **concluído** fica fora de controle na carta p, a API envia **uma** mensagem de texto para um chat do Telegram configurado, sem afetar a ingestão e sem nunca expor o token.

## 3. Escopo

### 3.1 Dentro

- `api/src/qc_api/services/alerts.py`: verificação, deduplicação, teto por hora, texto e envio (§4.1 a §4.5).
- Laço em segundo plano no `lifespan` da API (§4.2).
- `infra/migrations/NNN_alerts.sql` (próximo número livre): tabela `alerts_sent` (§4.3).
- Configuração (§4.6): `.env.example`, `api/README.md` e `docs/deployment-plan.md` (as variáveis no `infra/.env.api` da VPS e o passo a passo do bot).
- Testes do autor em `api/tests/` (fora de `acceptance/`).
- **Tester:** `api/tests/acceptance/test_spec_017.py`.

### 3.2 Fora

- Alertas por e-mail ou outros canais; alerta de dispositivo offline (a SPEC-018 entrega o estado, sem alerta).
- Regras de Western Electric 2 a 4 (ADR-013).
- Fechamento explícito de lote por campo ou rota nova (mudaria o contrato): não adotado (§4.1).
- Reenvio de uma mensagem que falhou: não adotado (no máximo uma tentativa por alerta, §4.3).

### 3.3 Trabalho humano

1. Criar o bot pelo `@BotFather` no Telegram (gratuito), guardar o token só no `infra/.env.api` da VPS (R-03) e descobrir o `chat_id` do chat ou grupo do supervisor.
2. Ligar `ALERTS_ENABLED=true` na VPS e registrar o CA-13 (manual).

## 4. Requisitos detalhados

### 4.1 O que dispara um alerta

- **Lote concluído:** um lote é considerado concluído quando a última inspeção dele (`ended_at` da carta) tem pelo menos `ALERTS_LOT_IDLE_MINUTES` minutos (padrão 10) em relação ao relógio do servidor (UTC). Não há evento de fechamento no contrato, e o operador não informa o fim do lote; o tempo sem inspeção é a única regra que não muda o contrato.
- **Janela:** só lotes com `ended_at` nas últimas `ALERTS_LOOKBACK_HOURS` horas (padrão 24). Ao ligar os alertas, lotes antigos não disparam.
- **Regra:** a carta da SPEC-006 com os parâmetros padrão (`baseline_lots=20`, `min_lot_size=5`), sem filtro de tipo, avaliada no momento da verificação. Um ponto com `out_of_control = true` que cumpre as duas condições acima e ainda não tem linha em `alerts_sent` gera um alerta. Pela ADR-021, só entram as inspeções com grau.
- **Origens:** `live` sempre. `simulated` só com `ALERTS_INCLUDE_SIMULATED=true` (padrão `false`), e o texto marca a origem (R-06, §4.4).
- **Custo limitado (ADR-017, SEC-06-01 e SEC-26-01):** cada verificação chama, por origem, `lot_selection(pool, source, None, baseline_lots=20, min_lot_size=5, max_points=3, max_excluded=0)` e `build_p_chart` com os mesmos parâmetros. `max_points` e `max_excluded` são sempre `int` (nunca `None`, que no repositório vira `limit null`). Nada carrega nem recalcula a história inteira em Python. Como a carta ordena os lotes pelo início, um lote intercalado que termina depois de 3 lotes mais novos pode ficar fora da janela: risco aceito.

### 4.2 Laço em segundo plano

- Com `ALERTS_ENABLED=true` e a configuração válida, o `lifespan` da API inicia uma tarefa `asyncio` que chama a verificação a cada `ALERTS_CHECK_INTERVAL_S` segundos (padrão 60; inteiro de 30 a 3.600). A verificação, que usa o pool síncrono do psycopg e o `httpx` síncrono, roda numa thread (`asyncio.to_thread`) e nunca no caminho de uma requisição. A tarefa é cancelada no encerramento.
- Qualquer exceção numa verificação é registrada (classe da exceção e SQLSTATE, regra de `docs/architecture.md` §4) e a tarefa continua.
- Função pública para testes: `run_check(pool, settings, *, now: datetime, transport: httpx.BaseTransport | None = None) -> int` (número de mensagens enviadas com sucesso).
- Com mais de um worker do uvicorn, cada um roda a verificação; a chave primária de `alerts_sent` garante uma mensagem por lote (§4.3).

### 4.3 Deduplicação e teto (`alerts_sent`)

```sql
alerts_sent(
  lot_id text not null check (lot_id ~ '^[A-Za-z0-9_-]{1,40}$'),
  source text not null check (source in ('live','simulated')),
  kind text not null check (kind in ('out_of_control')),
  created_at timestamptz not null default now(),
  delivered boolean not null default false,
  primary key (lot_id, source, kind)
)  -- RLS habilitado, sem políticas, como as demais tabelas (docs/architecture.md §5)
```

- Para cada alerta: `INSERT … ON CONFLICT DO NOTHING RETURNING lot_id` **antes** de enviar. Sem linha devolvida, o lote já foi tratado e nada é enviado. Depois de um envio aceito pelo Telegram (`ok = true`), `delivered = true`.
- **No máximo uma tentativa por alerta:** uma falha de envio fica com `delivered = false` e não é repetida.
- **Teto:** antes de inserir, se `alerts_sent` já tem `ALERTS_MAX_PER_HOUR` linhas (padrão 10; inteiro de 1 a 60) com `created_at` na última hora, o alerta é pulado sem inserir (pode sair numa verificação seguinte, se ainda estiver na janela) e a API registra um aviso com a contagem.

### 4.4 Texto da mensagem

- Texto puro (sem `parse_mode`), em PT-BR, sem imagem (R-02):

  `Lote <lot_id> fora de controle (<acima do LSC | abaixo do LIC>): p = <p>, LSC = <ucl>, LIC = <lcl>, n = <n>, defeituosas = <defects>. Origem: <real | simulado>.`

- `<p>`, `<ucl>` e `<lcl>` em porcentagem com 1 casa e vírgula decimal (ex.: `40,0%`). "acima do LSC" quando `p > ucl`; "abaixo do LIC" quando `p < lcl`.
- Com origem `simulated`, o texto começa com `[SIMULADO]` seguido de um espaço.
- O `lot_id` já casa a regex do contrato, então o texto não tem caractere de controle.

### 4.5 Envio e segredo (R-03)

- `POST https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage`, corpo JSON `{"chat_id": <TELEGRAM_CHAT_ID>, "text": <texto>}`, com `httpx` síncrono e timeout total de 5 s. Sucesso = HTTP 200 com `{"ok": true}`; qualquer outro resultado (inclusive 429 e timeout) é falha, registrada e não repetida.
- **O token nunca aparece:** em nenhum registro de log, de nenhum logger e de nenhum nível (inclusive os do `httpx` e do `httpcore`, que registram a URL); em nenhuma resposta da API; em nenhuma mensagem de exceção que a API registre. As exceções do `httpx` são registradas só pela classe. A implementação pode usar um filtro de log que troca o token por `***` nos loggers `httpx` e `httpcore`, desde que o CA-05 passe.
- O `httpx` já é dependência do `qc-api`; nenhuma dependência nova.

### 4.6 Configuração

| Variável | Padrão | Regra |
|---|---|---|
| `ALERTS_ENABLED` | `false` | booleano |
| `TELEGRAM_BOT_TOKEN` | vazio | obrigatória com os alertas ligados; `re.fullmatch(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}", valor)` |
| `TELEGRAM_CHAT_ID` | vazio | obrigatória com os alertas ligados; `re.fullmatch(r"-?[0-9]{1,20}", valor)` |
| `ALERTS_LOT_IDLE_MINUTES` | `10` | inteiro de 1 a 1.440 |
| `ALERTS_LOOKBACK_HOURS` | `24` | inteiro de 1 a 168 |
| `ALERTS_CHECK_INTERVAL_S` | `60` | inteiro de 30 a 3.600 |
| `ALERTS_MAX_PER_HOUR` | `10` | inteiro de 1 a 60 |
| `ALERTS_INCLUDE_SIMULATED` | `false` | booleano |

- **Configuração inválida com `ALERTS_ENABLED=true`:** a API sobe normalmente, registra **um** erro `alerts disabled: invalid configuration (<nome da variável>)`, sem o valor, e não inicia o laço. Os alertas nunca impedem a ingestão.
- As variáveis ficam no `.env.example` (sem valores reais) e no `infra/.env.api` da VPS. No painel do Render, só se a reserva estiver ativa.

## 5. Critérios de aceite

Contexto comum: banco de teste do marcador `db`; inspeções inseridas pelo teste com `inspected_at` controlado; `now` passado a `run_check`; Telegram simulado por `httpx.MockTransport`, que registra as requisições; `TELEGRAM_BOT_TOKEN = "123456:" + "A" * 35` e `TELEGRAM_CHAT_ID = "-1001"`; os demais parâmetros nos padrões. "Lote fora" = 4 lotes `live` de 10 `screw` com 1 `poor` cada, seguidos do lote `L-005` com 10 `screw` e 8 `poor`, com a última inspeção de `L-005` em `T`.

- **CA-01 (alerta)** — *Dado* o lote fora e `now = T + 11 min`, *quando* `run_check` roda, *então* devolve 1, há exatamente uma requisição `POST` para o caminho `/bot<token>/sendMessage`, o corpo JSON tem `chat_id == -1001` (ou `"-1001"`) e `text` igual a `Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = <ucl>, LIC = <lcl>, n = 10, defeituosas = 8. Origem: real.`, com `<ucl>` e `<lcl>` iguais aos da carta da SPEC-006 para esses lotes, formatados como no §4.4; e `alerts_sent` tem a linha `(L-005, live, out_of_control)` com `delivered = true`.
- **CA-02 (deduplicação)** — *Dado* o estado depois do CA-01, *quando* `run_check` roda de novo com `now = T + 12 min`, *então* devolve 0 e nenhuma requisição é feita.
- **CA-03 (lote ainda aberto e lote antigo)** — *Dado* o lote fora, *quando* `run_check` roda com `now = T + 5 min`, *então* nenhuma requisição é feita e `alerts_sent` fica vazia; com `now = T + 25 h`, também nenhuma.
- **CA-04 (falha do Telegram não afeta a ingestão)** — *Dado* o lote fora e o transporte respondendo 500, ou levantando `httpx.ConnectTimeout`, *quando* `run_check` roda com `now = T + 11 min`, *então* não levanta exceção, devolve 0, a linha de `L-005` fica com `delivered = false`, e uma nova verificação não faz outra requisição. *Dado* a app com `ALERTS_ENABLED=true` e esse transporte, *quando* um dispositivo faz `POST /api/v1/inspections` válido, *então* a resposta é 201.
- **CA-05 (R-03, token)** — *Dado* `caplog` em `DEBUG` no logger raiz e nos loggers `httpx` e `httpcore`, *quando* `run_check` roda nos três cenários (envio aceito, resposta 500 e `httpx.ConnectTimeout`), *então* nenhum registro capturado contém o token nem a parte depois de `123456:`; e o token não aparece no corpo de nenhuma resposta da API durante o teste.
- **CA-06 (R-06, simulado)** — *Dado* o lote fora gravado com `source=simulated`, *quando* `run_check` roda com `now = T + 11 min` e `ALERTS_INCLUDE_SIMULATED=false`, *então* nenhuma requisição é feita; com `ALERTS_INCLUDE_SIMULATED=true`, há uma requisição cujo `text` começa com `[SIMULADO] Lote L-005 fora de controle` e termina com `Origem: simulado.`.
- **CA-07 (desligado)** — *Dado* `ALERTS_ENABLED=false`, *quando* a app sobe e o lote fora existe, *então* nenhuma tarefa de alertas é criada e o transporte não recebe requisição.
- **CA-08 (SEC-26-01)** — *Dado* um espião em `qc_api.repositories.inspections.lot_selection` (que chama o original), *quando* `run_check` roda com lotes `live` no banco, *então* toda chamada registrada tem `max_points` e `max_excluded` do tipo `int` (não `bool` nem `None`), com `2 <= max_points <= 10` e `max_excluded == 0`; e o `ast` de `qc_api/services/alerts.py` não tem chamada a `lot_selection` com `max_points=None` ou `max_excluded=None`.
- **CA-09 (teto por hora)** — *Dado* o lote fora, `ALERTS_MAX_PER_HOUR=10` e 10 linhas em `alerts_sent` de outros lotes, inseridas pelo teste com `created_at = now − 30 min`, *quando* `run_check` roda com `now = T + 11 min`, *então* devolve 0, nenhuma requisição é feita, não há linha de `L-005` em `alerts_sent` e o log tem um aviso com a contagem 10. *Dado* as mesmas 10 linhas com `created_at = now − 61 min`, *então* há exatamente uma requisição.
- **CA-10 (configuração inválida)** — *Dado* `ALERTS_ENABLED=true` e, em casos separados, `TELEGRAM_BOT_TOKEN` vazio, `TELEGRAM_BOT_TOKEN="abc"` e `TELEGRAM_CHAT_ID="x"`, *quando* a app sobe, *então* `GET /api/v1/health` responde 200, o log tem exatamente um registro `alerts disabled: invalid configuration` citando o nome da variável, sem o valor, e nenhuma requisição ao Telegram é feita.
- **CA-11 (banco)** — *Dado* as migrações aplicadas, *então* `alerts_sent` existe com `relrowsecurity = true` e nenhuma política em `pg_policies`; inserir duas vezes `(L-001, live, out_of_control)` falha na segunda com `23505`; e `kind='other'` é recusado com `23514`.
- **CA-12 (abaixo do LIC)** — *Dado* uma linha de base com `p̄` alto (por exemplo, 4 lotes de 20 `screw` com 8 `poor`) e um lote `L-009` de 20 `screw` sem defeito, concluído, *quando* `run_check` roda, *então* o texto contém `(abaixo do LIC)` e `defeituosas = 0`.
- **CA-13 (manual, dupla)** — 1. Criar o bot e obter o `chat_id` (§3.3); 2. configurar o `infra/.env.api` da VPS e reiniciar só a API; 3. rodar o simulador (SPEC-014) com um lote fora de controle e `ALERTS_INCLUDE_SIMULATED=true`; 4. conferir uma única mensagem `[SIMULADO] …` no celular depois de `ALERTS_LOT_IDLE_MINUTES`; 5. conferir no `docker compose logs api` que o token não aparece; 6. voltar `ALERTS_INCLUDE_SIMULATED=false`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Texto (acima e abaixo, percentuais, simulado); regras de concluído e janela; teto; configuração; redação do token; laço que sobrevive a exceção | `api/tests/` |
| Aceite (tester) | Um por CA automatizado, com o banco de teste e `httpx.MockTransport` | `api/tests/acceptance/test_spec_017.py` |
| Manual (dupla) | CA-13 | descrito no CA |

Nenhum teste fala com o Telegram de verdade.

## 7. Riscos e notas para o implementador

- **Relógios:** `ended_at` vem do `inspected_at` da borda, e `now` é o relógio do servidor. O contrato já limita o futuro a 5 min; um relógio atrasado da borda antecipa o alerta, sem duplicá-lo.
- **Fase I:** com menos de `baseline_lots` lotes, `p̄` muda a cada lote novo. O alerta avalia o lote só enquanto ele está na janela e, uma vez enviado (ou tentado), não volta. É o comportamento esperado na demo.
- **Teto do Telegram:** a FAQ do Telegram limita a 20 mensagens por minuto num grupo; o teto de 10 por hora fica longe disso.
- **Render:** a reserva fria hiberna; com ela ativa, os alertas só rodam enquanto ela está acordada. Registrar no `docs/deployment-plan.md`.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `.env.example`, `api/README.md` e `docs/deployment-plan.md` atualizados
- [ ] PR aberto com os relatórios; merge conforme R-09; CA-13 manual registrado

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | §4: a regra usa a seleção limitada da SPEC-026 (ADR-017) e nunca recalcula a história inteira; depende, na prática, da SPEC-026. A SPEC continua `Draft`. | SEC-06-01 de `reviews/SPEC-006/r1-security-report.md`; RV-03 de `reviews/SPEC-006/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-17 | §4: `lot_selection` sempre com tetos inteiros (`max_points=2` e `max_excluded=0`, preliminares), nunca `None`; CA-07 preliminar novo (espião e busca no `ast`). A SPEC continua `Draft`. | SEC-26-01 de `reviews/SPEC-026/r1-security-report.md` (= RV-02 de `reviews/SPEC-026/r1-review-report.md`) | Orquestrador, a pedido do humano |
| 2026-10-18 | §3.1 e §6, pergunta 2: variáveis no `infra/.env.api` da VPS e o gatilho reavaliado com a API sempre ligada. A SPEC continua `Draft`. | ADR-018 (hospedagem na VPS pessoal) | Orquestrador, a pedido do humano |
| 2026-10-24 | SPEC reescrita para a aprovação. Perguntas do rascunho resolvidas pelo architect: (1) lote concluído = `ALERTS_LOT_IDLE_MINUTES` (10) sem inspeção, sem mudar o contrato; (2) gatilho = laço em segundo plano no `lifespan` da API a cada 60 s (a API fica sempre ligada na VPS); (3) avalia só lotes concluídos nas últimas 24 h, uma vez por lote; (4) `simulated` só com `ALERTS_INCLUDE_SIMULATED=true`, com `[SIMULADO]` no texto; (5) teto de 10 mensagens por hora. Também: `max_points=3` e `max_excluded=0`; uma tentativa por alerta com `delivered`; texto com acima do LSC ou abaixo do LIC; token nunca em log (inclusive `httpx`/`httpcore`); configuração inválida não derruba a API; dependência das SPECs 015 e 016; fatos do Telegram verificados em 2026-10-24; CAs CA-01 a CA-12 testáveis e CA-13 manual. A SPEC continua `Draft`. | Decisão do humano de 2026-10-24 (projeto inteiro, todas as fases) | Orquestrador, a pedido do humano |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com o pacote das Fases 2 e 3 e a ordem proposta. | Respostas do humano de 2026-10-24 (PR #45) | Orquestrador, a pedido do humano |
| 2026-10-24 | Limpeza de consistência pós-aprovação, sem mudança de requisito, CA, valor ou escopo: o aviso do topo passa a registrar a aprovação. | Status `Ready` desde o PR #45; sobrava o aviso da fase de rascunho | Architect, a pedido do orquestrador |
| 2026-10-25 | Entra em `In Dev` encadeada na SPEC-018 (que está sobre a 016 e a 036), antes de a SPEC-016 estar `Done`, por decisão do humano de 2026-10-24; o merge desta SPEC só acontece depois dos merges da 036, da 016 e da 018. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
