# SPEC-017 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-017](../../docs/specs/SPEC-017-alertas-telegram.md) |
| Rodada | r2 (última, R-10) |
| Revisor de segurança | security-devops |
| Diff revisado | `5bf8b40..9e9084d` (base = ponta da `spec/SPEC-018-heartbeat-dispositivos`; descontado o merge `8f1cc5b` da SPEC-018) |
| **Veredicto** | **PASS** |

O r1 parou no review (CHANGES_REQUESTED pelo RV-01) e não teve portão de segurança, então este relatório cobre a SPEC inteira, e não só o delta da r2. Nenhum achado bloqueante ou alto. Ficam três achados baixos e três observações informativas, nenhum deles exige outra rodada. O risco residual do RV-04 fica **aceito** (ver SEC-17-03).

## Superfície analisada

- **Rotas:** nenhuma rota nova nem alterada. O laço de alertas roda no `lifespan` (`api/src/qc_api/main.py`), fora do caminho das requisições, e nenhuma resposta da API lê `TELEGRAM_*` (conferido com `grep` em `api/src/qc_api/routers/`).
- **Segredo:** `TELEGRAM_BOT_TOKEN` (`SecretStr` no `Settings`, `config.py`; `AlertConfig.__repr__` o oculta). Ele aparece só na URL montada em `send_message` (`alerts.py:490`).
- **Saída de rede nova:** `POST https://api.telegram.org/bot<token>/sendMessage` com `httpx` síncrono (`alerts.py:438-529`).
- **Entradas externas:** as variáveis de ambiente da §4.6 e a resposta do Telegram.
- **Banco:** a migração `infra/migrations/005_alerts.sql` (tabela `alerts_sent`) e as consultas de `reserve_alert` e `mark_delivered` (`alerts.py:103-123`, `:383-412`).
- **Deploy e operação:** `.env.example`, `api/README.md` (criação do bot e `getUpdates`), `docs/deployment-plan.md` (§3 tabela de variáveis, §6 reserva, §7 item 10, §8 item 5 e o roteiro do CA-13) e o bloco "Envio" do `docs/architecture.md` §4 e §5.

### O que conferi, item a item do pedido

| Ponto | Resultado | Evidência |
|---|---|---|
| Token só em variável de ambiente, `SecretStr` | ✅ | `config.py`: `TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")`. `.env.example` sem valor. Nenhum literal com formato de token no diff (busca por regex de token do Telegram, JWT, URL com senha e prefixos de chave: nada). Os testes geram o token com `secrets` em tempo de execução. |
| Token nunca em log, inclusive `httpx`/`httpcore` | ✅ | `TokenRedactingFilter` (`alerts.py:244-296`) fica preso a cada logger que pode imprimir a URL. Conferi no `httpx` 0.28.1 e no `httpcore` 1.0.9 instalados todos os `getLogger`: `httpx`, `httpcore.connection`, `httpcore.http11`, `httpcore.http2`, `httpcore.proxy` e `httpcore.socks`, todos na lista `REDACTED_LOGGERS` (`:78-87`). O filtro troca o token inteiro e também a parte depois de `:`. Essa parte só tem caracteres não reservados, então nunca sai codificada em porcentagem na URL. O `install_token_redaction` roda antes de qualquer envio (`:549`, `:635`). |
| Token fora da thread abandonada | ✅ | `_post` nunca registra nada e captura `Exception` (`:462-463`), e o motivo leva só inteiros e o nome da classe. O único registro é da thread principal (`:506`, `:510`). O que o `httpx`/`httpcore` registrarem depois, na thread abandonada, passa pelo mesmo filtro, porque ele fica no logger e não depende da thread. O tester cobriu isso em `DEBUG` com o `httpcore` real (`test_extra_random_token_never_logged_with_real_httpcore` e os casos de prazo da r2). |
| Token fora das exceções registradas | ✅ | `log_check_failure` registra só a classe e o SQLSTATE (`:581-591`). `InvalidAlertConfigError` leva só nomes de variáveis. |
| Token fora do `argv` (`getUpdates`, CA-13) | ✅ | `api/README.md`: `sed`/`tr` recebem o nome do arquivo, e não o token. O `printf` é builtin do shell, e o `curl` recebe só o caminho `/dev/fd/N` (`-K <(...)`). O `-s` cala o erro, que poderia ecoar a URL. O roteiro do CA-13 usa `grep -F -f <(printf ...)` e trata o valor vazio. Nada vai para o histórico do shell. O tester tem um teste que confere isso (`test_extra_docs_never_put_the_token_in_argv`). |
| Token fora das respostas da API | ✅ | Nenhuma rota lê `TELEGRAM_*`. O CA-05 confere os corpos das respostas durante o teste. |
| TLS verificado, `trust_env=False`, sem redirecionamento | ✅ | `_client` (`:522-529`): `verify` fica no padrão `True` (CA do `certifi`), `trust_env=False` (sem proxy do ambiente, sem `.netrc`, sem `SSL_CERT_FILE`) e `follow_redirects=False`. Um 3xx vira `status=3xx`, uma falha sem repetição, e o token nunca segue para o `Location`. A base `https://api.telegram.org` é uma constante, não uma configuração. |
| Prazo total e teto de resposta | ✅ (SEC-17-02, SEC-17-03) | `send_message` faz `join(5 s)` de fora da thread, então o prazo vale para DNS, conexão, escrita, cabeçalhos e corpo, qualquer que seja o transporte. O `httpx.Timeout(5.0)` por operação continua dentro da thread, só para a thread abandonada terminar logo. O teto `MAX_RESPONSE_BYTES = 64 KiB` (`:73`, `:457`) é conferido depois de cada bloco. |
| No máximo uma thread abandonada | ✅ | `previous_send_running` (`:422-435`) roda antes de cada reserva (`:565-568`). O `run_check` só é chamado pelo laço único do `lifespan`, então há no máximo uma thread presa por processo (e por worker do uvicorn), longe do `pids_limit` de 256 do contêiner. |
| Teto de 10 por hora com advisory lock | ✅ | `pg_advisory_xact_lock` (de transação, então vale no pooler em modo transaction) serializa a ordem existe → conta → insere (`:390-406`). A chave `1_017_001` não colide com a do `infra/migrate.py` (`0x5051434D4947`, de sessão). O tester confirmou o teto com vários pools concorrentes. |
| Uma tentativa por lote | ✅ | A linha é reservada antes do envio, e a falha fica `delivered = false`, sem nova tentativa. Nada é reservado enquanto há thread viva, então não fica linha sem tentativa. |
| `[SIMULADO]` só com a flag (R-06) | ✅ | `find_alerts` só inclui `simulated` com `include_simulated` (`:356-358`). O texto começa com `[SIMULADO] ` e termina com `Origem: simulado.` (`:340-348`). |
| Configuração inválida não derruba a API | ✅ | Os campos do `Settings` são `StrictBool \| str`, `StrictInt \| str`, `SecretStr` e `str`, que aceitam qualquer valor do ambiente, então o `Settings()` nunca falha por causa dos alertas. As regras ficam em `load_alert_config`, com `re.fullmatch` em padrões limitados (sem ReDoS). `start_alerts_task` registra um erro só com os nomes e não cria a tarefa. CA-10 e `test_extra_invalid_environment_never_stops_the_api`. |
| Migração `005` | ✅ (SEC-17-01) | `enable row level security`, sem políticas, sem `force`, sem `grant`/`revoke`, igual à `001`. `check` da regex de `lot_id` (espelho do contrato), de `source` e de `kind`. Idempotente (`if not exists`), sem credencial. |
| SQL parametrizado | ✅ | Todas as consultas são constantes com `%s`. O único literal é `interval '1 hour'`. Nenhuma f-string em query. |
| R-01 (Telegram grátis) | ✅ | Reconferi a FAQ oficial em 2026-10-25 (<https://core.telegram.org/bots/faq>). Os bots mandam mensagens "at no cost". A cobrança (0,1 Star por mensagem) só vale acima da cota grátis de difusão em massa (cerca de 30 mensagens por segundo, com "paid broadcasts" ligado por opção do dono do bot). Os limites seguem em 1 mensagem por segundo num chat e 20 por minuto num grupo. O teto de 10 por hora fica muito abaixo. Nenhum cartão, nenhuma dependência nova. |
| R-02 | ✅ | O corpo tem só `chat_id` e `text`, e o texto tem só `lot_id` (já validado pela regex) e números. Sem imagem, sem `parse_mode`. |
| R-03 (`.env.example`) | ✅ | Todas as variáveis estão documentadas, e `TELEGRAM_BOT_TOKEN=` e `TELEGRAM_CHAT_ID=` estão vazios. A tabela da §3 do `deployment-plan.md` traz só os nomes. |

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-17-01 | baixa | deploy | `docs/deployment-plan.md:422` (§8 item 5, "Migração"), `:121-137` (passo 1, item 4, CA-14) | O item 5 manda aplicar a `005` em produção com os subitens 4 e 5 do passo 3 (`--status` e aplicar), mas não manda repetir a conferência de RLS e grants (CA-14) para a tabela nova. A conferência existente cita só `devices`, `inspections` e `schema_migrations` nas consultas de `pg_class` e `pg_policies` e no `revoke`. O `docs/architecture.md` §5 lembra que um projeto Supabase criado com grants automáticos dá `anon`/`authenticated` às tabelas novas do `public`, e que o RLS não cobre `TRUNCATE`, `REFERENCES` e `TRIGGER`. O impacto prático é baixo. A chave anon só alcança o PostgREST e o GraphQL, que não fazem `TRUNCATE`. O RLS sem políticas bloqueia leitura e escrita. A tabela não tem dado sensível (só IDs de lote). No pior caso, apagar linhas levaria a um alerta repetido. | Não bloqueia. Numa manutenção do deploy, acrescentar ao §8 item 5: depois de aplicar a `005`, rodar as consultas do passo 1, item 4, com `alerts_sent` na lista (esperado: `relrowsecurity = true`, 0 políticas, nenhum grant a `anon`/`authenticated`) e, se aparecer grant, `revoke all on alerts_sent from anon, authenticated;`. Até lá, fica como ação humana (abaixo). |
| SEC-17-02 | baixa | input | `api/src/qc_api/services/alerts.py:452-458`, `:522-529` | **O teto de 64 KiB vale depois da descompressão, bloco a bloco.** O `httpx` anuncia `Accept-Encoding: gzip, deflate` e descomprime cada bloco bruto inteiro antes de entregá-lo ao `iter_bytes`. Medi com `httpx` 0.28.1: um único bloco bruto de 64 KiB de gzip vira **67.415.144 bytes** decodificados, com pico de cerca de 149 MB alocados só no `httpx`, a que se soma a cópia para o `bytearray` em `:456`. Depois disso, o teto corta. Isso fica abaixo do `mem_limit` de 512 MB da API (`infra/compose.yaml:78`) e não se repete, porque é uma tentativa por alerta e uma thread por vez. Só um par TLS autenticado para `api.telegram.org` produz essa resposta (o próprio Telegram comprometido ou um MITM com certificado válido, já que a verificação está ligada e `trust_env=False`). `brotli` e `zstandard` não estão instalados (`uv tree`), então não há razão de compressão maior. | Não bloqueia. Sugestão para uma manutenção: enviar `Accept-Encoding: identity` no `_client` (o Telegram responde um JSON pequeno) ou ler com `iter_raw` e aplicar o teto aos bytes brutos e decodificados. |
| SEC-17-03 | baixa (risco aceito) | deploy | `api/src/qc_api/services/alerts.py:565-568`, `api/README.md:33` | **Decisão sobre o RV-04 do r2-review-report: aceito como está.** Uma thread abandonada contra um servidor que goteja os cabeçalhos pode viver até o teto de cabeçalho incompleto do `h11` 0.16.0 (100 KiB, cerca de 140 h). Nesse tempo, cada verificação com candidato para em cerca de 1 s com `alerts check stopped: a previous send is still running`, e um lote que sai da janela de `ALERTS_LOOKBACK_HOURS` se perde. Motivos para aceitar: (1) só afeta a disponibilidade dos alertas, nunca a ingestão, o banco ou o segredo; (2) exige o mesmo par TLS autenticado do SEC-17-02; (3) é limitado a uma thread e a um socket por processo, sem acúmulo; (4) o sintoma aparece no log a cada verificação, e não em silêncio como no r1; (5) o remédio é imediato: reiniciar a API mata a thread *daemon*. | Nenhuma correção exigida. Melhorias opcionais para uma manutenção: a sugestão do RV-04 (pôr `abandoned_for_s` e o `lot_id` pendente no aviso, só com inteiros e IDs) e uma linha no `api/README.md` ou no §8 item 5 do `deployment-plan.md`: "se o aviso persistir, `docker compose -f infra/compose.yaml restart api`". |

### Observações informativas (sem achado)

- **Lista fixa de loggers redigidos.** Um logger novo de dependência que imprima a URL não fica coberto. O caso conhecido é o `hpack`, só com HTTP/2. Hoje o `h2` não está instalado e o `http2` está desligado. O `uv.lock` fixa as versões, e o CA-05 e o teste com o `httpcore` real quebram se uma atualização passar a vazar por um logger já listado. Ao atualizar o `httpx`/`httpcore`, repetir o `grep getLogger` que fiz.
- **`send_message` pode levantar no `Thread.start()`.** Com o `pids_limit` esgotado, o `RuntimeError` sobe até o laço. A linha já reservada fica `delivered = false` e não é repetida, e o registro tem só a classe. Isso é coerente com o §4.3 e não vaza nada.
- **Corrida na borda do prazo** (já registrada pelo tester e pelo reviewer): uma mensagem aceita logo depois dos 5 s pode ficar `delivered = false`. É falso negativo de entrega, nunca duplicação.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ N/A: nenhuma rota nova nem alterada. |
| Entradas validadas (tamanho, tipo, regex, `extra="forbid"`) | ✅ As variáveis da §4.6 passam por `re.fullmatch` com padrões limitados e por faixas inteiras. A resposta do Telegram tem teto de 64 KiB, só `ok is True` conta, e o JSON inválido é falha. O `lot_id` tem regex no banco. Ver SEC-17-02. |
| SQL sempre parametrizado | ✅ |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ `alerts_sent` com RLS e sem políticas. Nenhuma credencial nova fora da API. Ver SEC-17-01 para a conferência em produção. |
| CORS fechado ou mínimo | ✅ Sem mudança (a API continua sem middleware de CORS). |
| Logs sem segredos e sem payloads de imagem | ✅ Token redigido nos loggers do `httpx`/`httpcore`, exceções registradas só pela classe, thread abandonada muda. Os registros próprios têm só contagens, `lot_id` e `source`. |
| Dependências novas | ✅ Nenhuma (`uv.lock` e `pyproject.toml` intocados). Na árvore atual, `httpx` 0.28.1, `httpcore` 1.0.9 e `h11` 0.16.0 (a versão com a correção do CVE-2025-43859). |
| Deploy: variáveis no provedor, health check, free sem cartão | ✅ Variáveis documentadas só pelos nomes (`infra/.env.api`; Render só com a reserva ativa). Health check sem mudança. Telegram gratuito (R-01, reconferido em 2026-10-25). Risco da reserva fria registrado no §7 item 10. |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma reaprovação nesta branch. No diff da SPEC, o orquestrador mudou só `Status`, `Rodada atual` e a linha de encadeamento no Histórico. Nenhum requisito, CA ou limite (inclusive o timeout de 5 s e o teto de 10 por hora) foi alterado. |

### Verificações executadas

- `CI=true TEST_DATABASE_URL=…/partqc_test uv run pytest -q api/tests/test_alerts.py api/tests/test_alerts_db.py api/tests/test_alerts_deadline.py api/tests/acceptance/test_spec_017.py infra/tests`: **1010 passed, 47 skipped** (os de Docker), 150 s. Só os quatro arquivos da SPEC: **227 passed**. O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia.
- `uv run ruff check .` e `uv run ruff format --check .`: limpos.
- `grep getLogger` no `httpx`/`httpcore` instalados; `uv tree --package qc-api`; teste de sondagem da amplificação gzip (SEC-17-02) num script avulso no scratchpad, só com `httpx.MockTransport` e sem rede.
- Trailers `Agent:` de todos os commits do diff: developer (produção, `api/tests/` fora de `acceptance/`, docs, dev-reports), tester (`acceptance/` e test-reports), architect (`docs/architecture.md`), reviewer (review-reports) e orchestrator (status). Nenhum commit do security-devops nesta SPEC.
- Nenhuma chamada ao Telegram de verdade.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. Só `threading` da biblioteca padrão. |

## Ações pendentes para o humano

1. Depois do merge, aplicar a `005` com o `.env.migrate` (§8 item 5) e, no SQL Editor, conferir para `alerts_sent`: `relrowsecurity = true`, nenhuma linha em `pg_policies` e nenhum grant a `anon`/`authenticated` em `information_schema.role_table_grants`. Se houver grant, `revoke all on alerts_sent from anon, authenticated;` (SEC-17-01).
2. CA-13 manual (§9 do `deployment-plan.md`): criar o bot, guardar o token só no `infra/.env.api` com um editor, obter o `chat_id` com o comando do `api/README.md` e conferir no log que a contagem da parte secreta do token é `0`.
3. Se um dia aparecer `alerts check stopped: a previous send is still running` por muitos minutos seguidos, reiniciar só a API (SEC-17-03).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
