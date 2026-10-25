# SPEC-018 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-018](../../docs/specs/SPEC-018-heartbeat-dispositivos.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops (autor: developer) |
| Diff revisado | `spec/SPEC-016-ferramentas-manuais...a9ca70d` (branch encadeada; 13 commits, `92014ca` a `a9ca70d`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os três achados baixos e o informativo abaixo não bloqueiam. Não há `SPEC_ISSUE`. Não houve reaprovação delegada (ADR-019) nesta branch: os commits do orquestrador mudam só o status, a rodada, a linha do Histórico sobre o encadeamento e o `docs/plan.md`.

## Superfície analisada

- **Contrato (`qc-contracts` 0.5.0, R-04):** `HeartbeatCreate` com `extra="forbid"`, `sent_at` com fuso (`UtcDatetime`, normalizado para UTC; fora da faixa depois da normalização → `ValueError`, então 422 e nunca 500) e no máximo `MAX_FUTURE_SKEW` no futuro, `model_version`/`model_sha256` pelas regexes do contrato e nulos juntos, `app_version` com `APP_VERSION_PATTERN` (o `$` do Pydantic não aceita `\n` final; testado com `"1.0\n"`), contadores de 0 a `MAX_HEARTBEAT_COUNT` (o limite da coluna `integer`). `DeviceStatus` com `extra="ignore"`. Minor de verdade: nenhum schema existente muda (o tester confere `InspectionCreate` campo a campo). Versão em `__version__`, `pyproject.toml`, `uv.lock` e histórico do README.
- **Banco (`infra/migrations/004_device_heartbeat.sql`):** um único bloco `do $$ … $$`, sem `BEGIN`/`COMMIT`, `add column if not exists` nas 8 colunas anuláveis e cada `check` nomeado criado só se não existir. Reexecutar não muda nada (o tester rodou duas vezes a mais, sem `check` novo e sem perder dados). Os `check` espelham as regexes do contrato, os contadores `>= 0` e o par do modelo nulo junto. **Nenhum** `grant`, `revoke`, política, papel ou mudança de RLS: `devices` segue com RLS ligado e sem políticas (`001`), e os grants de tabela (conferidos/revogados pelo CA-14 da SPEC-015) cobrem as colunas novas. Nenhuma credencial no arquivo.
- **API, `POST /api/v1/devices/{device_id}/heartbeat`:**
  - `require_device` (SHA-256 da chave, `secrets.compare_digest`, chave vazia ou acima de 256 caracteres recusada antes do banco), o mesmo da SPEC-004, sem mudança em `auth.py`.
  - `device_id` do caminho com `Path(pattern=DEVICE_ID_PATTERN)`.
  - 403 quando o dono da chave não é o `device_id` do caminho, com o mesmo `detail` para dispositivo registrado ou não (sem enumeração).
  - O `UPDATE` usa `owner` (o dono da chave), nunca o valor do caminho.
  - O corpo passa pelo `BodySizeLimitMiddleware` (256 KB, 413).
  - SQL só com parâmetros psycopg.
  - Erro de classe 22/23 vira 422 `Value cannot be stored`, com log só de rota, `device_id` (do dono) e SQLSTATE.
  - O log de 403 cita só o dono da chave.
  - O log de requisição registra o template da rota, sem query string.
- **API, `GET /api/v1/devices`:** `require_read_key` (comparação em bytes, tempo constante); chave de dispositivo → 401. Transação `read only`, `limit 500`, parâmetros psycopg, sem parâmetro de consulta do cliente (os extras são ignorados). `online` e `last_heartbeat_at` pelo `now()` do banco; o `sent_at` da borda fica só em `hb_sent_at`, que nem é devolvido.
- **Borda:**
  - `HttpPublisher.send_heartbeat`, no único módulo com `httpx` (CA-11 e CA-17 da SPEC-007 passam).
  - HTTPS obrigatório fora de `localhost`/`127.0.0.1` (`check_cloud_api_url`), `follow_redirects=False`, timeout de 5 s, prazo de 15 s e teto de 512 KiB (SPEC-030).
  - O corpo da resposta só é lido em 204 e 413/422, e só o `refusal_summary` sai na exceção.
  - Erros de rede passam por `_redact`, que remove a chave.
  - `device_id` validado por `re.fullmatch` antes de entrar no caminho.
  - `HeartbeatLoop` numa thread própria, com um `HttpPublisher` próprio. Nunca grava no outbox; só lê `SinkStats` sob o `threading.Lock` do `SqliteOutbox`.
  - 401/403 viram um `ERROR` único (só `HTTP <status>`) e param o laço.
  - Exceção inesperada do envio: só o nome da classe.
  - Registro do laço nas condições do `PublishLoop`, nunca com `--stub-model` (R-06).
  - `HEARTBEAT_INTERVAL_S` inválido sai com código 2, citando a variável e nunca o valor.
- **Dashboard:** `ApiClient.devices()` com a chave de leitura do lado do servidor, `fetch_devices()` com o cache de 30 s e `max_entries` (uma consulta a cada 30 s, no máximo, qualquer que seja o número de visitantes). A página mostra a origem pelo `SOURCE_LABELS_PT` e liga o selo de simulado quando algum `last_source` é `simulated` (R-06). Erro da API vira mensagem, sem a chave na tela.
- **Configuração de deploy:** nenhuma mudança em `infra/compose.yaml`, `infra/Caddyfile`, `infra/docker/` ou `render.yaml`. A única variável nova é `HEARTBEAT_INTERVAL_S` (borda, não secreta), documentada no `.env.example`.

### Verificação feita

- Leitura de `docs/rules.md`, `reviews/checklist.md` §6, da SPEC, do `docs/architecture.md` (§3, §4, §5, §6.4) e dos relatórios r1 (dev, test e review); diff completo de `api/src`, `packages/contracts/src`, `infra/migrations`, `edge/src`, `dashboard/` e `.env.example`.
- Testes de aceite e do autor da SPEC-018, mais `api/tests/acceptance/test_spec_004.py`, `edge/tests/acceptance/test_spec_007.py` e `infra/tests/test_schema_db.py`, com `CI=true` e o banco `partqc_test`: **719 passed**. A suíte completa já foi rodada pelo tester e pelo reviewer (7684 passed, 75 skipped).
- Sondagem própria da API (script no scratchpad, fora do repositório, com chaves geradas em tempo de execução, no `partqc_test`):

  | Caso | Resultado |
  |---|---|
  | heartbeat com a própria chave | 204 sem corpo |
  | chave de `edge-01` no caminho `sim-01` | 403, e a linha de `sim-01` continua toda nula |
  | chave de outro dispositivo com corpo inválido | 422 (precedência 401 → 422 → 403) |
  | sem chave e caminho `EDGE_01` | 401 |
  | chave válida e caminho `EDGE_01` | 422 |
  | `sim-01%0A` no caminho | 422 |
  | `edge-01%2F..%2Fsim-01` no caminho | 404 |
  | chave de leitura no `POST`, chave de dispositivo no `GET` | 401 |
  | chave com bytes não ASCII, nas duas rotas | 401, nunca 500 |
  | chave na query string | 401 |
  | `sent_at` `0001-01-01T00:00:00+01:00` e `9999-12-31T23:59:59-01:00` | 422, nunca 500 |
  | `Content-Type: text/plain`, `multipart` e campo `image` | 422 (R-02) |
  | corpo de 400 KB | 413 |
  | `?limit=100000` no `GET` | ignorado (no máximo 500) |
  | logs do processo (raiz em `DEBUG`) | sem a chave de dispositivo, sem o hash dela e sem o marcador enviado no corpo |

  A chave de leitura apareceu uma vez no log do processo, mas só na linha do cliente `httpx` do próprio script, porque eu a pus de propósito na query string. Nenhuma linha da API a contém, e o `RequestLogMiddleware` não registra a query string.
- Busca por padrões de segredo no diff (URL com senha, `password=`, JWT, chaves de nuvem, chave privada): nada além de texto de relatório. Nenhum arquivo `.env` real no diff. Nenhuma menção corporativa (R-13). Todos os commits com a identidade do projeto e o trailer `Agent:`.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 | baixa | privacy | `dashboard/views/dispositivos.py:27-39`, `api/src/qc_api/repositories/devices.py:41-66` | O dashboard é público (`docs/deployment-plan.md`: "API e dashboard públicos", sem login), e a página nova mostra a qualquer visitante quando o gateway está ligado (`online`, `Último sinal`, `Ligado há`), além da versão da aplicação e das filas. Como o gateway é o notebook da dupla, isso diz quando ele está ligado e há quanto tempo, mas não traz dado pessoal, imagem ou segredo. `device_id`, `model_version` e `model_sha256` já eram públicos pelo Histórico. É coerente com a decisão de dashboard aberto do ADR-018 e com o que a SPEC pede. | Nenhuma nesta SPEC. A dupla fica ciente. Se incomodar, proteger o dashboard é uma decisão futura (ADR), não desta SPEC. |
| SEC-02 | baixa | input | `infra/migrations/004_device_heartbeat.sql:24-32` | Concordo com o RV-02: `last_heartbeat_at` e `hb_sent_at` não têm `check` de faixa. Um `infinity` gravado à mão (SQL Editor) dá 500 no `GET /devices`, e um `last_heartbeat_at` futuro deixa o dispositivo `online`. Nenhum dos dois é alcançável pela API: `last_heartbeat_at` é sempre `now()`, e `sent_at` fora da faixa dá 422 (conferido na sondagem). Exige acesso de escrita ao banco, que já é o limite de confiança. O 500 loga só classe e SQLSTATE. | Nenhuma nesta SPEC. Proposta ao architect, numa SPEC futura: a faixa da `002` (`>= 0001-01-01` e `< 10000-01-01`) nas colunas de data de `devices`. |
| SEC-03 | baixa | secrets (logs) | `edge/src/qc_edge/heartbeat.py:130-131` | Concordo com o RV-03: uma exceção inesperada ao montar o heartbeat vai para `logger.exception`, com a mensagem e o traceback, ao contrário da regra "só o nome da classe" do envio. Hoje o `build()` só lê `SinkStats`, `model_info` e o relógio. Nenhum deles carrega a chave, que nem é acessível ao laço. O traceback padrão não inclui variáveis locais. Não há vazamento. | Nenhuma nesta SPEC. Na próxima mudança do módulo, registrar só `type(exc).__name__`. |
| SEC-04 | informativa | deploy | `api/src/qc_api/repositories/devices.py:27-39`; `docs/deployment-plan.md` §3 (passo 3) | Se a API 0.5.0 subir antes da migração `004`, o heartbeat e o `GET /devices` dão 500 (`UndefinedColumn`, logado só com classe e SQLSTATE). As inspeções não são afetadas, porque o caminho de escrita delas não muda, e a borda só registra `heartbeat failed: HTTP 500`. O `infra/migrate.py` aplica todas as pendentes, então o passo 3 do plano de deploy já cobre a `004`, sem passo novo. | Seguir a ordem: **migração `004` → API → dashboard → borda**. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ `POST …/heartbeat` com `require_device` (hash + `compare_digest`) e só para o próprio `device_id` (403 caso contrário, mesmo `detail` para dispositivo registrado ou não); `GET /devices` com `require_read_key` (`compare_digest` em bytes); chave de dispositivo na leitura e chave de leitura no heartbeat → 401. Precedência 401 → 422 → 403 da SPEC-004 conferida (CA-03 e sondagem). |
| Entradas validadas (tamanho, tipo real de imagem, regex, `extra="forbid"`) | ✅ Corpo limitado a 256 KB (413); `extra="forbid"`; regex do `device_id` no caminho (`\n` final recusado); regexes e faixas do contrato espelhadas por `check` no banco; `sent_at` com fuso e no máximo 5 min no futuro, e fora da faixa vira 422. Nenhuma rota aceita imagem (`multipart` e campo `image` → 422). |
| SQL sempre parametrizado | ✅ `UPDATE_HEARTBEAT` e `SELECT_DEVICES` são texto fixo com `%(…)s`; nenhuma f-string em SQL. O único `.format` é o caminho HTTP da borda, com `device_id` já validado. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ A `004` não toca em RLS, grants nem papéis. O dashboard lê pela API com a chave de leitura e não conhece a `DATABASE_URL`. |
| CORS fechado ou mínimo | ✅ Sem mudança (nenhum `CORSMiddleware`; o dashboard chama do servidor). |
| Logs sem segredos e sem payloads de imagem | ✅ Corpo inválido nunca logado (CA-03 com marcadores e a minha sondagem); 403 e erro de banco só com rota, dono da chave e SQLSTATE; o log de requisição não tem query string. Na borda, a chave é removida das mensagens de rede, o corpo da resposta nunca aparece e o intervalo inválido não ecoa o valor. SEC-03 (baixa) sem vazamento hoje. |
| Dependências novas | ✅ Nenhuma (`uv.lock` muda só a versão do `qc-contracts`). R-12: `api/` e `dashboard/` sem torch/onnxruntime. |
| Deploy: variáveis no provedor, health check, plano free sem cartão | ✅ Nenhuma mudança de infraestrutura nem de segredo; `HEARTBEAT_INTERVAL_S` é da borda e não é secreta. R-01: o heartbeat custa um `UPDATE` por minuto por dispositivo, na VPS já existente e no Supabase free. Ordem de deploy em SEC-04. |
| Reaprovação delegada (ADR-019) | ✅ Não houve nesta branch: os commits do orquestrador mudam só status, rodada, a linha do Histórico do encadeamento (decisão do humano) e o `docs/plan.md`. |

### Pontos do foco do orquestrador

- **R-02:** o `HeartbeatCreate` tem só os 7 campos do contrato, sem imagem nem dado pessoal (o tester confere o corpo exato que sai da borda).
- **R-05:** o heartbeat roda numa thread e num `HttpPublisher` separados, nunca passa pelo outbox e não toca no caminho das inspeções. O teste ponta a ponta do tester segura a resposta do heartbeat e mostra as 3 inspeções entregues uma única vez cada.
- **R-06:**
  - nunca há heartbeat com `--stub-model` (CA-10, com controle positivo);
  - `last_source` vem da inspeção de maior `received_at`;
  - a página mostra `simulado` e liga o selo;
  - o simulador não envia heartbeat e aparece `offline` com origem `simulado`.
- **Relógio:** `online` usa só o `now()` do banco, contra um `last_heartbeat_at` gravado com o mesmo `now()`. Um `sent_at` antigo ou adiantado não muda nada (teste do tester com `sent_at` de janeiro de 2026).

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova; só `qc-contracts` 0.4.0 → 0.5.0 (pacote do workspace). |

## Ações pendentes para o humano

- Deploy na ordem **migração `004` (`infra/migrate.py`, máquina do humano, modo session) → API → dashboard → borda** (SEC-04).
- CA-13 manual (Definição de pronto), que também confirma em produção que `GET /devices` sem chave dá 401: `curl -s -o /dev/null -w '%{http_code}' https://<subdominio>/api/v1/devices` deve imprimir `401`.
- SEC-01: só ciência de que a página "Dispositivos" mostra publicamente quando o gateway está ligado.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
