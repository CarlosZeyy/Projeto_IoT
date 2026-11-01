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
4. envia uma mensagem de texto puro, sem imagem (R-02), por `POST https://api.telegram.org/bot<token>/sendMessage`, com timeout total de 5 s (conexão, cabeçalhos, corpo e resolução de nome). A requisição pede `Accept-Encoding: identity`; uma resposta com outra codificação nunca é descomprimida e conta como falha, sem ler o corpo (`telegram send failed: unsupported content encoding (status=<n>)`, SPEC-040). A linha fica com `delivered = true` quando o Telegram responde `{"ok": true}`. Uma falha (erro HTTP, 429, timeout, resposta comprimida) fica com `delivered = false` e **não** é repetida. O envio roda numa thread de trabalho que a verificação espera por no máximo 5 s; se o servidor ainda não terminou, o envio conta como falha e a thread é abandonada (ela termina sozinha). Enquanto uma thread abandonada estiver viva, a verificação não grava nem envia outro alerta e registra o aviso `alerts check stopped: a previous send is still running (abandoned_for_s=<n>, lot_id=<lote>, source=<origem>)`, em que `<n>` são os segundos desde o abandono e o lote é o que ficou sem reserva (SPEC-040); os alertas pendentes saem numa verificação seguinte, se ainda estiverem na janela.

Exemplo de mensagem:

```text
Lote L-005 fora de controle (acima do LSC): p = 80,0%, LSC = 64,5%, LIC = 0,0%, n = 10, defeituosas = 8. Origem: real.
```

Com origem `simulated`, o texto começa com `[SIMULADO] ` e termina com `Origem: simulado.` (R-06).

**Nunca derruba a ingestão.** A verificação roda numa thread, fora do caminho das requisições. Uma exceção é registrada (só a classe e, nos erros de banco, o SQLSTATE) e o laço continua. Com `ALERTS_ENABLED=true` e alguma variável inválida, a API sobe normalmente, registra **um** erro `alerts disabled: invalid configuration (<nome da variável>)`, sem o valor, e não inicia o laço.

**O token nunca aparece** (R-03): ele vai só na URL do Telegram. Um filtro troca o token por `***` nos registros dos loggers `httpx` e `httpcore` (que registram a URL), e os erros do `httpx` são registrados só pela classe. Ele fica só nas Environment Variables do `partqc-api` no Coolify (e no painel do Render, só com a reserva ativa), nunca no Git.

**Custo** (R-01): a Bot API do Telegram é gratuita para mensagens comuns (<https://core.telegram.org/bots/faq>, conferido pelo architect em 2026-10-24); o teto de 10 mensagens por hora fica muito abaixo do limite de 20 por minuto num grupo.

### Criar o bot e ligar os alertas

A API roda no recurso **`partqc-api`** do Coolify (ADR-023). Nenhum `.env` é criado à mão na VPS, e nenhum checkout é feito nela: a configuração fica nas Environment Variables do recurso. O passo a passo completo está no [`docs/deployment-plan.md`](../docs/deployment-plan.md) §8, item 5.

1. No Telegram, abra uma conversa com o `@BotFather`, envie `/newbot` e siga as instruções (nome e usuário do bot). Ele responde com o token: copie-o direto para o campo `TELEGRAM_BOT_TOKEN` das Environment Variables do recurso **`partqc-api`** no Coolify (só runtime, Locked, Literal), nunca para o `partqc-web` nem para outro lugar (chat, issue, commit, arquivo). Deixe `ALERTS_ENABLED=false` por enquanto e faça **Redeploy** (ou **Restart**) só desse recurso, para o contêiner da API receber o token.
2. Descubra o `chat_id`:
   - **conversa direta:** envie qualquer mensagem ao bot;
   - **grupo:** adicione o bot ao grupo do supervisor e envie uma mensagem no grupo.

   Depois, **na VPS** (para o token não passar por outra máquina), leia o `chat_id` com o comando abaixo, que tira o token do ambiente do contêiner da API e o entrega ao `curl` por um descritor. O `docker exec` recebe só o nome da variável; o token não vai para o `argv` nem para o histórico do shell, e nenhum arquivo é gravado. O nome do contêiner vem da listagem do plano de deploy (convenções da §4 do [`docs/deployment-plan.md`](../docs/deployment-plan.md)). O `chat_id` é o `id` do objeto `chat` (negativo nos grupos):

   ```bash
   t=$(docker exec <contêiner da api> printenv TELEGRAM_BOT_TOKEN)
   curl -s -K <(printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$t") | python3 -m json.tool | grep -A4 '"chat"'
   unset t
   ```

3. Nas Environment Variables do `partqc-api`: `ALERTS_ENABLED=true`, `TELEGRAM_CHAT_ID=<id>` e, se quiser, os outros parâmetros da tabela acima. Depois, **Redeploy** (ou **Restart**) só desse recurso.
4. Confira, na aba de logs da `api` no painel, ou na VPS com o comando abaixo, que apareceu `alerts enabled: ...` e nenhum `alerts disabled: invalid configuration`:

   ```bash
   docker logs --tail 200 <contêiner da api> 2>&1 | grep -E 'alerts (enabled|disabled)'
   ```

Para desligar, volte `ALERTS_ENABLED=false` nas Environment Variables do `partqc-api`, com **Redeploy** (ou **Restart**) só desse recurso. Para trocar o token (vazado ou revogado), use `/revoke` no `@BotFather`, cole o novo no campo `TELEGRAM_BOT_TOKEN` do `partqc-api` e faça o mesmo **Redeploy** (ou **Restart**).

Se o aviso `alerts check stopped: a previous send is still running` aparecer por muitos minutos seguidos (o campo `abandoned_for_s` mostra há quantos segundos o envio foi abandonado), faça **Restart** só do `partqc-api` (SEC-17-03).
