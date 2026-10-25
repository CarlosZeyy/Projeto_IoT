# qc-api

API na nuvem do PartQC (FastAPI; SPEC-004, SPEC-005, SPEC-006, SPEC-018 e SPEC-026). Rotas, autenticação e banco em [`docs/architecture.md`](../docs/architecture.md) §4 e §5; como rodar localmente, no [`README.md`](../README.md) da raiz; publicação na VPS, no [`docs/deployment-plan.md`](../docs/deployment-plan.md).

## Configuração

A API lê a configuração só do ambiente (sem `.env` automático: use `uv run --env-file .env ...`). Todas as variáveis estão comentadas no [`.env.example`](../.env.example), no bloco `qc-api`.

| Variável | Padrão | Regra |
|---|---|---|
| `DATABASE_URL` | — | obrigatória; pooler do Supabase em modo transaction (ADR-006) |
| `READ_API_KEY` | — | obrigatória; mínimo de 32 caracteres |
| `MAX_BODY_BYTES` | `262144` | inteiro positivo |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` ou `ERROR` |
| `ALERTS_ENABLED` | `false` | booleano (SPEC-017) |
| `TELEGRAM_BOT_TOKEN` | vazio | segredo; obrigatória com os alertas ligados; `[0-9]{3,20}:[A-Za-z0-9_-]{20,100}` |
| `TELEGRAM_CHAT_ID` | vazio | obrigatória com os alertas ligados; `-?[0-9]{1,20}` |
| `ALERTS_LOT_IDLE_MINUTES` | `10` | inteiro de 1 a 1.440 |
| `ALERTS_LOOKBACK_HOURS` | `24` | inteiro de 1 a 168 |
| `ALERTS_CHECK_INTERVAL_S` | `60` | inteiro de 30 a 3.600 |
| `ALERTS_MAX_PER_HOUR` | `10` | inteiro de 1 a 60 |
| `ALERTS_INCLUDE_SIMULATED` | `false` | booleano |

Nas variáveis de alerta com padrão numérico ou booleano, o valor vazio vale o padrão.

## Alertas no Telegram (SPEC-017)

Desligados por padrão. Com `ALERTS_ENABLED=true` e a configuração válida, a API roda um laço em segundo plano, dentro do próprio processo (sem agendador externo), que a cada `ALERTS_CHECK_INTERVAL_S` segundos (a primeira logo na subida):

1. monta a carta p da SPEC-006 com os parâmetros padrão (`baseline_lots=20`, `min_lot_size=5`), sem filtro de tipo e só com as inspeções com grau (ADR-021), lendo só os 3 lotes válidos mais recentes de cada origem (corte no SQL, ADR-017);
2. escolhe os lotes fora de controle **concluídos**: a última inspeção tem pelo menos `ALERTS_LOT_IDLE_MINUTES` minutos e no máximo `ALERTS_LOOKBACK_HOURS` horas, pela hora do servidor em UTC. Lotes `simulated` só entram com `ALERTS_INCLUDE_SIMULATED=true`;
3. grava cada lote na tabela `alerts_sent` (migração `005_alerts.sql`) **antes** de enviar: um lote nunca gera duas mensagens, mesmo com vários workers do uvicorn. Se a tabela já tem `ALERTS_MAX_PER_HOUR` linhas da última hora, o alerta é pulado sem gravar (pode sair numa verificação seguinte) e a API registra um aviso com a contagem;
4. envia uma mensagem de texto puro, sem imagem (R-02), por `POST https://api.telegram.org/bot<token>/sendMessage`, com timeout de 5 s. A linha fica com `delivered = true` quando o Telegram responde `{"ok": true}`. Uma falha (erro HTTP, 429, timeout) fica com `delivered = false` e **não** é repetida.

Exemplo de mensagem:

```text
Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = 64,5%, LIC = 0,0%, n = 10, defeituosas = 8. Origem: real.
```

Com origem `simulated`, o texto começa com `[SIMULADO] ` e termina com `Origem: simulado.` (R-06).

**Nunca derruba a ingestão.** A verificação roda numa thread, fora do caminho das requisições. Uma exceção é registrada (só a classe e, nos erros de banco, o SQLSTATE) e o laço continua. Com `ALERTS_ENABLED=true` e alguma variável inválida, a API sobe normalmente, registra **um** erro `alerts disabled: invalid configuration (<nome da variável>)`, sem o valor, e não inicia o laço.

**O token nunca aparece** (R-03): ele vai só na URL do Telegram. Um filtro troca o token por `***` nos registros dos loggers `httpx` e `httpcore` (que registram a URL), e os erros do `httpx` são registrados só pela classe. Ele fica só no `infra/.env.api` da VPS, nunca no Git.

**Custo** (R-01): a Bot API do Telegram é gratuita para mensagens comuns (<https://core.telegram.org/bots/faq>, conferido pelo architect em 2026-10-24); o teto de 10 mensagens por hora fica muito abaixo do limite de 20 por minuto num grupo.

### Criar o bot e ligar os alertas

1. No Telegram, abra uma conversa com o `@BotFather`, envie `/newbot` e siga as instruções (nome e usuário do bot). Ele responde com o token: copie-o direto para o `infra/.env.api` da VPS (`TELEGRAM_BOT_TOKEN=...`), com um editor, e não o cole em nenhum outro lugar (chat, issue, commit).
2. Descubra o `chat_id`:
   - **conversa direta:** envie qualquer mensagem ao bot;
   - **grupo:** adicione o bot ao grupo do supervisor e envie uma mensagem no grupo.

   Depois, na raiz do checkout na VPS (para o token não passar por outra máquina), leia o `chat_id` com o comando abaixo, que tira o token do `infra/.env.api` e o entrega ao `curl` por um descritor, sem deixá-lo no `argv` nem no histórico do shell. O `chat_id` é o `id` do objeto `chat` (negativo nos grupos):

   ```bash
   t=$(sed -n 's/^TELEGRAM_BOT_TOKEN[=]//p' infra/.env.api | tr -d "\"' \r")
   curl -s -K <(printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$t") | python3 -m json.tool | grep -A4 '"chat"'
   unset t
   ```

3. No `infra/.env.api`: `ALERTS_ENABLED=true`, `TELEGRAM_CHAT_ID=<id>` e, se quiser, os outros parâmetros da tabela acima. Reinicie só a API: `docker compose -f infra/compose.yaml up -d api`.
4. Confira no log que apareceu `alerts enabled: ...` e nenhum `alerts disabled: invalid configuration`: `docker compose -f infra/compose.yaml logs api`.

Para desligar, volte `ALERTS_ENABLED=false` e reinicie a API. Para trocar o token (vazado ou revogado), use `/revoke` no `@BotFather`, atualize o `infra/.env.api` e reinicie a API.
