# SPEC-038: Manutenção da borda e do deploy (linhas inválidas do outbox, importação de fotos e respostas de erro do Caddy)

| Campo | Valor |
|---|---|
| Status | Blocked |
| Rodada atual | r1 |
| Autor da implementação | developer (Parte A: `edge/`) e depois security-devops (Parte B: `infra/`, `.gitignore`, `.env.example` e `docs/deployment-plan.md`), na mesma rodada (§6) |
| Tags | security, deploy, infra |
| Depende de | SPEC-036 e SPEC-032 **mergeadas antes de esta entrar em `In Dev`** (a Parte A muda o `importer.py` da 036; a Parte B muda o `Caddyfile`, o `.gitignore`, os `.dockerignore` e o plano de deploy da 032); SPEC-034 (`Done`); e SPEC-009, 015, 025 e 030 |
| Semana alvo | S6–S7: depois da Fase 2 (logo depois da SPEC-017) e antes do ensaio da apresentação (M4, 29/11). Decisão do humano de 2026-10-24 |
| Requisitos cobertos | RF-06, RF-07, RNF-04, RNF-05, RNF-06, RNF-10; R-02, R-03, R-05, R-14 |
| ADRs relevantes | ADR-009, ADR-018, ADR-020, ADR-016, ADR-023 (`Proposto`; só a Parte B) |

> **Aguardando reaprovação humana** (2026-10-26): correção do SPEC_ISSUE-038-B1 (SEC-39-06), que proíbe os placeholders de ambiente `{env.*}` e `{$...}` em todo o `infra/Caddyfile` (§4.9 e CA-12). Ver o Histórico.
>
> **Reaprovada pelo humano em 2026-10-25** (nota de 2026-10-25, pelo ADR-023, `Aceito`). A Parte A não muda. A Parte B continua, mas passa a valer sobre o Caddyfile e o compose da **SPEC-039** (Caddy como roteador interno em `:80`, atrás do proxy do Coolify). Leia-se:
>
> - **Depende de:** também a SPEC-039 mergeada antes de esta entrar em `In Dev`.
> - **§4.9:**
>   - o bloco `handle_errors` fica dentro do bloco do site `:80` (não `{$PUBLIC_HOST}`). Ele continua necessário, porque o 502 com a API ou o dashboard fora do ar ainda é gerado pelo Caddy e passa pelo proxy do Coolify até o cliente;
>   - no texto do risco do `deployment-plan.md` (hoje o item 9 da §7), "o 308 da porta 80 continua sem eles (servidor automático, HSTS ignorado em HTTP)" passa a ser "o redirecionamento HTTP → HTTPS e os erros gerados pelo próprio proxy do Coolify (por exemplo, com o contêiner do Caddy parado) continuam sem eles".
> - **§4.10:** o `.dockerignore` do Caddy da SPEC-039 (`*` e `!infra/Caddyfile`) já exclui todas as extensões. As 9 linhas entram só nos dois `.dockerignore` da API e do dashboard, como está.
> - **CA-12:** "dentro do bloco `{$PUBLIC_HOST}`" passa a ser "dentro do bloco do site `:80`", e "as condições do CA-30 da SPEC-015" passa a ser "as condições do CA-04 da SPEC-039".
> - **CA-13:** "a imagem do Caddy fixada no compose" passa a ser "a imagem construída de `infra/docker/caddy.Dockerfile` (SPEC-039 §4.3)", sem `PUBLIC_HOST` no ambiente.
> - **CA-14:**
>   - a imagem é a da SPEC-039 §4.3, executada com as opções do CA-12 da SPEC-039: `--read-only`, `tmpfs` em `/tmp`, `/data` e `/config` (no lugar dos volumes temporários), `--cap-drop ALL`, `--cap-add NET_BIND_SERVICE`, `--pids-limit 256` e `--network none`;
>   - sai o `PUBLIC_HOST=http://partqc.example.org` "só no teste": o Caddyfile real já serve HTTP em `:80`;
>   - as requisições a `127.0.0.1:80` com `Host: partqc.example.org` e as expectativas não mudam.
> - **CA-18 (manual):**
>   - passo 1: `docker stop <contêiner da api>`, com o nome pela listagem `docker ps --filter label=com.docker.compose.project=<uuid>` (SPEC-039 §4.7);
>   - passo 3: `docker start <contêiner da api>`;
>   - passo 4: registrar também sem o UUID do recurso.
> - **Testes de aceite de SPECs anteriores (§3.1):** vale a mesma regra para um teste de aceite da SPEC-039 que a §4.9 invalide (por exemplo, uma contagem de handlers `headers` no JSON do `caddy adapt`).
>
> Ver o Histórico.

## 1. Contexto

Junta as pendências baixas, não bloqueantes, dos portões r1 de três SPECs: a SPEC-034 (reenvio de `dead`, `docs/architecture.md` §6.2), a SPEC-036 (importação de fotos, §6.3) e a SPEC-032 (manutenção do deploy, §8 e §9). Nenhuma pendência foi exigida antes do merge, e nenhuma muda o contrato, a API, o banco nem uma regra negociável. Por isso não há ADR.

| Pendência | Origem | Severidade | Decisão |
|---|---|---|---|
| SEC-34-01 (= RV-01 = T-01) | `reviews/SPEC-034/r1-security-report.md`, `r1-review-report.md` | baixa | **Entra** (§4.1): uma linha do outbox adulterada derruba a listagem do `qc_edge.requeue` com traceback que ecoa o valor, e, depois do `--yes`, trava o `fetch_due` do laço em todo ciclo |
| SEC-34-02 (= RV-02) | mesmos relatórios | baixa | **Entra** (§4.2): `OperationalError` na abertura aparece como "not an outbox file" |
| SEC-34-03, SEC-34-04 | `reviews/SPEC-034/r1-security-report.md` | informativo | Fora, sem ação (o próprio relatório) |
| SEC-36-01 | `reviews/SPEC-036/r1-security-report.md` | baixa | **Entra** (§4.3): o Pillow copia o `comment` de um PNG para o JPEG, e a importação recusa a imagem com `normalization check failed` |
| SEC-36-03 (= RV-04 = O-05) | `reviews/SPEC-036/r1-security-report.md`, `r1-review-report.md`, `r1-test-report.md` | baixa | **Entra** (§4.4): logger `PIL` em DEBUG mostra tags EXIF (`Make`, `Artist`) |
| RV-01 (= O-03) | `reviews/SPEC-036/r1-review-report.md`, `r1-test-report.md` | baixa | **Entra** (§4.5): diretórios vazios depois do rollback |
| RV-02 | `reviews/SPEC-036/r1-review-report.md` | baixa | **Entra** (§4.6): duas execuções simultâneas do mesmo plano gravam a mesma foto duas vezes |
| SEC-36-02 + SEC-32-02 (plano CSV) | `reviews/SPEC-036/r1-security-report.md`; `reviews/SPEC-032/r1-security-report.md` | baixa | **Entra** (§4.7): pasta de entrada e plano dentro de um repositório Git são recusados |
| RV-03 | `reviews/SPEC-036/r1-review-report.md` | baixa | **Fora** (§3.2): caracteres invisíveis literais nos testes e a regra `PLE2502` |
| O-01, O-02, O-04 | `reviews/SPEC-036/r1-test-report.md` | observação | Fora, sem ação: aceitos pelo reviewer e pelo security-devops |
| SEC-32-01 (= RV-01 = T-01) | `reviews/SPEC-032/r1-security-report.md`, `r1-review-report.md`, `r1-test-report.md` | baixa | **Entra** (§4.9): o 502 gerado pelo próprio Caddy sai sem HSTS, `nosniff`, `Referrer-Policy` e `frame-ancestors`, e com `Server: Caddy` |
| SEC-32-02 (extensões) | `reviews/SPEC-032/r1-security-report.md` | baixa | **Entra** (§4.10): `.heif`, `.jfif`, `.jpe`, `.tif`/`.tiff`, `.dng`, `.avif`, `.mov` e `.mp4` no `.gitignore` e nos dois `.dockerignore` |
| SEC-32-03 (= RV-02 = O-T-02) | `reviews/SPEC-032/r1-security-report.md`, `r1-review-report.md`, `r1-test-report.md` | baixa | **Entra** (§4.11): `*_PIDS_LIMIT=0` ou `-1` remove o limite sem aviso |
| RV-03 | `reviews/SPEC-032/r1-review-report.md` | baixa | **Entra** (§4.11): o roteiro de "Atualização" não aponta para o diagnóstico do `read_only` e do `pids_limit` |
| O-T-01 | `reviews/SPEC-032/r1-test-report.md` | observação | Fora, sem ação (§3.2) |

**Duas partes.** A Parte A é da borda (developer). A Parte B é de deploy e repositório (security-devops), como na SPEC-032. Elas não tocam arquivos em comum. O portão de segurança segue a regra de nunca ser feito pelo autor (`reviews/README.md`): o security-devops faz o da Parte A, e o reviewer faz o da Parte B (§6).

## 2. Objetivo

Uma linha do outbox fora do formato vira `dead` no laço e é pulada na listagem, sem traceback e sem parar o envio dos outros itens; a importação aceita um PNG com `comment`, não deixa diretório vazio, não grava a mesma foto duas vezes e recusa pasta de entrada ou plano dentro de um repositório Git; o 502 do Caddy sai com os mesmos headers das respostas normais e sem `Server`; e o Git e os contextos de build ignoram os outros formatos de foto e vídeo de celular.

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `edge/src/qc_edge/outbox.py`: validação das linhas lidas em `fetch_due()` e `dead_items()` (§4.1).
- `edge/src/qc_edge/requeue.py`: captura de `ValueError`/`TypeError` (§4.1) e mensagens de abertura (§4.2).
- `edge/src/qc_edge/importer.py`: metadados herdados antes do `save` (§4.3), nível do logger `PIL` (§4.4), rollback dos diretórios (§4.5), reconferência do hash sob o lock (§4.6) e recusa de pasta de entrada e plano dentro de repositório Git (§4.7).
- `edge/src/qc_edge/privacy.py`: nível do logger `PIL` (§4.4).
- `edge/README.md`: seções "Reenviar itens `dead`" e "Importar fotos de fora da página" (§4.8).
- Testes do autor em `edge/tests/` (fora de `acceptance/`).

**Parte B (security-devops):**

- `infra/Caddyfile`: `handle_errors` (§4.9).
- `.gitignore`, `infra/docker/api.Dockerfile.dockerignore` e `infra/docker/dashboard.Dockerfile.dockerignore`: extensões novas (§4.10).
- `.env.example` e `docs/deployment-plan.md` (§4.9 e §4.11).
- Testes do autor em `infra/tests/` (fora de `acceptance/`), inclusive os de marcador `docker` (SPEC-015 §4.14). Os testes do autor da SPEC-032 que exigem um único bloco `header` (`infra/tests/test_deploy_files.py::test_caddyfile_header_block_spec_032` e o `(response,) = ...` de `infra/tests/test_docker_images.py`) são ajustados pelo próprio security-devops.

**Tester:** `edge/tests/acceptance/test_spec_038.py` (CA-01 a CA-11) e `infra/tests/acceptance/test_spec_038.py` (CA-12 a CA-17).

**Testes de aceite de SPECs anteriores** (`docs/architecture.md` §10, aplicação explícita): a §4.9 invalida duas asserções exploratórias de `infra/tests/acceptance/test_spec_032.py`. O tester as ajusta assim, e nada mais no arquivo:

| Teste | Antes | Depois |
|---|---|---|
| `test_extra_caddyfile_headers_are_in_one_header_block_and_no_full_csp` | 1 bloco `header`; `Content-Security-Policy` 1 vez | 1 bloco `header` fora do `handle_errors` e 1 dentro dele, cada um com as 6 linhas; `Content-Security-Policy` 2 vezes; o resto igual |
| `test_extra_caddy_adapt_single_header_handler_is_deferred` | 1 handler `headers` em todo o JSON | 1 handler `headers` nas `routes` do servidor, adiado (`deferred: true`); os handlers de `errors` ficam fora da contagem |

Se outro teste de aceite antigo falhar por causa de um requisito desta SPEC (por exemplo, um teste da SPEC-036 com a pasta de entrada dentro de um repositório Git), vale a mesma regra.

**Architect (feito junto com esta SPEC):** `docs/dataset-protocol.md` §10.6, passo 1 (pasta de entrada e plano fora do repositório, recomendação (a) do SEC-32-02) e a nota "a partir da SPEC-038" em `docs/architecture.md` §6.2.

### 3.2 Fora

- **RV-03 da SPEC-036** (U+202E, U+2028, U+00AD e U+FEFF literais nos testes; a regra `PLE2502` do ruff): fora, sem SPEC agora. É higiene de revisão só em testes: o security-devops conferiu que nenhum arquivo de produção tem esses caracteres. Ligar o `PLE2502` (que acusa caracteres de formatação bidirecional, <https://docs.astral.sh/ruff/rules/bidirectional-unicode/>, consultado em 2026-10-24) obriga a corrigir, no mesmo PR, os 14 arquivos de teste que hoje têm um desses caracteres literal (busca do architect em 2026-10-24): 5 do developer em `edge/tests/`, 3 do ml-engineer em `ml/tests/` e 6 de aceite das SPECs 011, 030, 034, 035, 036 e 037. Seriam três papéis autores e seis arquivos de aceite antigos alterados por um ganho pequeno. Se o humano quiser, entra numa SPEC própria de ferramentas (`infra`), com a regra ligada e os escapes `\u…` em todos os arquivos de uma vez.
- **O-01** (hard link de fora da pasta de entrada), **O-02** (células com cara de fórmula) e **O-04** (controles e bidi em `file`) da SPEC-036: aceitos pelos portões, sem ação.
- **O-T-01** da SPEC-032 (o CA-06 dela não cita o `.env.api` e o `.env.dashboard`): sem ação. O teste já cria os 3 arquivos, e a SPEC-032 está entregue.
- **SEC-34-03 e SEC-34-04:** informativos, sem ação.
- **O 308 da porta 80 sem headers:** já era assim antes da SPEC-032 (servidor automático do Caddy), e o navegador ignora HSTS em HTTP. Sem ação.
- **`!docs/**/*.png`** reabre qualquer PNG em `docs/`: por projeto (SPEC-032 §4.2). Sem ação.
- **Plano CSV no `.gitignore`:** não dá para ignorar `*.csv` (o `ml/external_sources.csv` e outros CSV são rastreados). A defesa é a recusa da §4.7.
- **Logger `PIL` no gateway `qc-edge`:** o `qc-edge` não tem caminho para DEBUG (`qc_edge` e `uvicorn` em INFO, raiz sem configuração). Sem ação.
- **Outras pendências marcadas "próxima manutenção" em `docs/plan.md` §3** (SPEC-029: `API_BASE_URL` com `Cf`/punycode inválido; SPEC-030: `Content-Encoding` empilhado, prazo dos headers, subpastas ilegíveis, exceção `.*.tmp` e comentário desatualizado; SPEC-031/037): fora. A decisão do humano de 2026-10-24 limita esta SPEC às SPECs 034, 036 e 032. Ver a pergunta 3 do §9.
- Botão ou rota para o reenvio, reenvio automático e apagar linhas do outbox: continuam fora (SPEC-034 §3.2).
- `Content-Security-Policy` completa e limitação de taxa no Caddy: continuam fora (SPEC-032 §3.2).

## 4. Requisitos detalhados

### Parte A (developer)

#### 4.1 Linhas inválidas no outbox (SEC-34-01)

**Linha válida** = cada coluna lida tem o tipo Python que o `sqlite3` devolve para o formato gravado pela SPEC-009, e a conversão funciona. Na ordem em que são conferidas:

| Coluna | Válida quando | Conferida em |
|---|---|---|
| `inspection_id` | `str` e `uuid.UUID(valor)` não levanta | `fetch_due`, `dead_items` |
| `created_at` | `str` e `datetime.fromisoformat(valor)` não levanta | `fetch_due`, `dead_items` |
| `attempts` | `int` | `fetch_due`, `dead_items` |
| `next_attempt_at` | `str` e `datetime.fromisoformat(valor)` não levanta | `fetch_due` |
| `last_error` | `str` ou `None` | `dead_items` |

A conversão de uma linha válida não muda (`parse_timestamp` e `UUID` de hoje). O `payload` continua revalidado pelo `_load` do laço (SPEC-009 §4.3), sem mudança.

- **`fetch_due`:** cada linha `pending` inválida selecionada pela consulta de hoje vira `dead`, por `rowid`, com `last_error = "invalid outbox row"` (constante `INVALID_ROW_ERROR` em `qc_edge.outbox`), na mesma chamada, sob o lock e numa transação: `UPDATE outbox SET status = 'dead', last_error = ? WHERE rowid = ? AND status = 'pending'`. As outras colunas não mudam. A linha não entra na lista devolvida, e as linhas válidas são devolvidas como hoje (a lista pode ter menos que `limit` itens nesse ciclo). Para cada linha, um registro `WARNING` no logger `qc_edge.outbox` com o texto fixo `invalid outbox row marked dead (rowid=<n>, column=<coluna>)`, em que `<coluna>` é a primeira coluna inválida na ordem da tabela.
- **`dead_items`:** cada linha `dead` inválida é pulada (não entra na lista) e gera um `WARNING` no logger `qc_edge.outbox` com `invalid dead row skipped (rowid=<n>, column=<coluna>)`. Nada é escrito.
- **Nunca o valor:** nenhuma mensagem, log ou exceção desta seção contém o valor da coluna.
- **`requeue_dead` não muda.** Com `ids = None`, uma linha `dead` inválida também volta a `pending`. Se a coluna inválida for `attempts` ou `next_attempt_at`, o reenvio a corrige (`attempts = 0`, `next_attempt_at = now`), e a linha sobe normalmente. Se for `inspection_id` ou `created_at`, o próximo ciclo do laço a devolve a `dead` com `invalid outbox row`. É o mesmo comportamento de um item ainda recusado (SPEC-034 §4.3), e nenhum ciclo para.
- **CLI (`qc_edge.requeue.main`), defesa em profundidade:** um `ValueError` ou `TypeError` em volta de `list_dead`/`requeue_dead` sai com código 1 e loga só `outbox has an invalid row (<Classe>)`, sem traceback e sem a mensagem da exceção, como já é feito com `sqlite3.Error`.
- Com as linhas pulando, a listagem com uma linha inválida sai com 0, imprime só os itens válidos e o resumo de hoje (`<k> dead item(s); run again with --yes to requeue`, com `k` = itens válidos selecionados) e mostra os avisos no log (stderr). O formato do stdout com um outbox válido não muda (CA-05 da SPEC-034).

#### 4.2 Mensagens de abertura do `--outbox-path` (SEC-34-02)

Em `qc_edge.requeue.main`, o erro de `SqliteOutbox.open_existing` passa a ter duas mensagens, todas com código 2, como hoje:

| Exceção | Mensagem no log |
|---|---|
| `sqlite3.OperationalError` (permissão, diretório sem escrita para o `-shm`, E/S) | `cannot open --outbox-path (OperationalError)` |
| `NotAnOutboxError` ou outro `sqlite3.DatabaseError` (arquivo que não é SQLite, páginas corrompidas) | `--outbox-path is not an outbox file (<Classe>)` (a de hoje) |
| outro `sqlite3.Error` | `cannot open --outbox-path (<Classe>)` |

O `OperationalError` é subclasse de `DatabaseError`: a captura dele vem primeiro.

#### 4.3 PNG com `comment` (SEC-36-01)

Em `normalize_imported_image`, a imagem passada ao `save` não leva metadados herdados da entrada: o `info` dela é esvaziado imediatamente antes do `save` (por exemplo, `image.info.clear()`), e o `save` continua sem `exif`, `icc_profile`, `xmp`, `comment`, `progressive` e `optimize` (SPEC-036 §4.3, passo 4). A conferência do passo 5 continua igual. Com isso, um PNG com chunk `tEXt`, `zTXt` ou `iTXt` de chave `comment` é importado sem segmento COM. Nenhum outro comportamento da normalização muda.

#### 4.4 Logger `PIL` (SEC-36-03)

No `main` de `qc_edge.importer` e no de `qc_edge.privacy`, logo depois do `_configure_logging()`: se `logging.getLogger("PIL").getEffectiveLevel()` for menor que `logging.INFO`, o logger `PIL` recebe `setLevel(logging.INFO)`. Um nível maior (por exemplo, `WARNING`) não é rebaixado. Assim, mesmo com o logger raiz em DEBUG, o `PIL.TiffImagePlugin` não registra os valores das tags EXIF ao ler a orientação. Os logs do próprio `qc_edge` não mudam.

#### 4.5 Rollback dos diretórios (RV-01 da SPEC-036)

No `_store_locked`, a lista devolvida por `make_private_dirs` no passo 4 (diretórios criados nesta linha, do mais externo para o mais interno) é guardada. Numa falha de E/S na escrita da imagem (passo 4) ou nos passos 5 e 6 (SPEC-036 §4.4), depois de apagar a imagem e desfazer o manifest como hoje, cada diretório dessa lista é removido com `os.rmdir`, do mais interno para o mais externo, ignorando `OSError` (um diretório que não está vazio fica), com `fsync_dir` do pai de cada um removido. Diretórios que já existiam antes da linha nunca são removidos. A remoção acontece ainda sob o lock.

#### 4.6 Reconferência do hash sob o lock (RV-02 da SPEC-036)

No passo 2 da SPEC-036 §4.4 (sob o `manifest_file_lock`), além dos cabeçalhos e do `item_type_conflict`, o importador relê `exclusions.csv` e confere se o `input_sha256` da linha já está numa linha de `sources.csv` cujo `image_path` não está em `exclusions.csv` (a mesma regra da retomada, SPEC-036 §4.2). Se estiver, a linha é **pulada**: nada é gravado, o stdout tem `skipped <file>: already imported` e ela conta em `skipped` no resumo, como uma linha marcada na fase 1. O código de saída segue a SPEC-036 §4.6. Um `exclusions.csv` com outro cabeçalho ou ilegível nesse ponto para a importação com código 1, como um cabeçalho divergente no passo 2.

`load_plan(*, dataset_dir, inbox, plan, external_sources) -> list[PlanRow]` (fase 1) e `run_import(rows, *, dataset_dir, dry_run, clock, sleep, out) -> int` (fase 2), já existentes em `qc_edge.importer`, ficam com estas assinaturas, porque o CA-09 os chama diretamente.

#### 4.7 Pasta de entrada e plano fora de um repositório Git (SEC-36-02, SEC-32-02)

- **Dentro de um repositório Git** = o caminho ou algum diretório acima dele, até a raiz do sistema de arquivos, tem uma entrada chamada `.git` (diretório ou arquivo, como numa worktree), conferida com `os.path.lexists`.
- `load_plan` recusa, com `UsageError` e código 2, antes de ler o dataset e o plano:
  - `--inbox` cujo `realpath` está dentro de um repositório Git → `inbox must be outside any git repository`;
  - `--plan` cujo diretório pai, depois do `realpath` do plano, está dentro de um repositório Git → `plan must be outside any git repository`.
- Ordem: `--inbox` diretório existente → pasta de entrada fora do dataset (SPEC-036 §4.1) → pasta de entrada fora de repositório Git → plano fora de repositório Git → o resto da fase 1. Nada é criado nem gravado.
- O `--external-sources` (padrão `ml/external_sources.csv`, dentro do repositório) e o `--dataset-dir` não entram nesta regra.
- Motivo: um `git add -A` com a pasta de entrada no checkout publicaria fotos de terceiros com EXIF e GPS, porque o repositório é público, e o `.gitignore` não cobre todos os formatos que um celular produz nem o plano (SEC-32-02). A regra cobre qualquer nome de pasta, ao contrário de uma linha nova no `.gitignore`.

#### 4.8 `edge/README.md`

- Seção "Reenviar itens `dead`": uma linha inválida (editada à mão ou corrompida) é pulada na listagem, com um aviso no log que cita só o `rowid` e a coluna; o laço a move para `dead` com `invalid outbox row`; o `--yes` corrige `attempts` e `next_attempt_at`; com `inspection_id` ou `created_at` inválidos, a linha volta a `dead` e precisa ser corrigida ou retirada à mão.
- Seção "Importar fotos de fora da página": a pasta de entrada e o plano ficam fora do repositório (e fora de `ml/data/`), e a importação recusa os dois dentro de um repositório Git.

### Parte B (security-devops)

#### 4.9 Respostas de erro geradas pelo Caddy (SEC-32-01)

- No bloco do site de `infra/Caddyfile`, um bloco `handle_errors` **sem** códigos de status (vale para todo erro gerado pelo Caddy, como o 502 com a API ou o dashboard fora do ar e o 504 por timeout), com:
  - um bloco `header` com as mesmas 6 linhas do bloco do site (SPEC-032 §4.3): `Strict-Transport-Security "max-age=31536000"`, `X-Content-Type-Options "nosniff"`, `Referrer-Policy "no-referrer"`, `Content-Security-Policy "frame-ancestors 'self'"`, `-Server` e `-Via`;
  - uma resposta com **corpo vazio** e o status do erro original. Pelo código do Caddy, um `respond` dentro de uma rota de erro usa o status recomendado do erro quando nenhum status é dado (comentário de `ServeHTTP` em <https://github.com/caddyserver/caddy/blob/master/modules/caddyhttp/staticresp.go>, consultado pelo architect em 2026-10-24); o autor confere a sintaxe com o `caddy adapt`, registra a URL e a data no `deployment-plan.md`, e o CA-14 confere o status.
- O bloco `handle_errors` **não** tem `reverse_proxy`, `file_server`, `templates`, `rewrite` nem placeholder `{err.*}` além de `{err.status_code}`: a mensagem interna do erro (por exemplo, a falha de DNS da origem) nunca vai para o cliente.
- **Nenhum placeholder de ambiente em todo o arquivo** (SEC-39-06, R-03), e não só no `handle_errors`: nem `{env.*}`, substituído em tempo de execução, nem `{$...}`, substituído antes da análise do Caddyfile (inclusive na forma `{$VAR:padrão}`). Fonte: seção "Environment variables" de <https://caddyserver.com/docs/caddyfile/concepts>, consultada pelo architect em 2026-10-26. O motivo é que o ambiente do contêiner do Caddy tem a `READ_API_KEY` e o `PUBLIC_HOST` (ADR-023, emenda 1; SPEC-039), e um desses placeholders num `respond`, num `header` ou num log poderia devolver a chave ao cliente. A regra vale para o texto sem comentários (CA-12).
- O bloco `header` do site, o `handle /api/*` e o `handle` sem matcher não mudam. Continuam sem snippet, sem bloco global e sem domínio literal (CA-30 da SPEC-015 e CA-04 da SPEC-032). O arquivo continua formatado por `caddy fmt`.
- `docs/deployment-plan.md`: o risco que hoje descreve o 502 do Caddy sem os headers (risco 9 da SPEC-032) passa a dizer que, desde a SPEC-038, as respostas de erro geradas pelo Caddy saem com os 4 headers, sem `Server` e com corpo vazio, por `handle_errors`, e que o 308 da porta 80 continua sem eles (servidor automático, HSTS ignorado em HTTP).

#### 4.10 Formatos de foto e vídeo no `.gitignore` e nos `.dockerignore` (SEC-32-02)

- **`.gitignore`**, no grupo "Dados e imagens", **antes** das exceções de PNG: uma linha por extensão, só na forma com classes de caracteres (que já cobre a literal): `*.[hH][eE][iI][fF]`, `*.[jJ][fF][iI][fF]`, `*.[jJ][pP][eE]`, `*.[tT][iI][fF]`, `*.[tT][iI][fF][fF]`, `*.[dD][nN][gG]`, `*.[aA][vV][iI][fF]`, `*.[mM][oO][vV]` e `*.[mM][pP]4`.
- **`infra/docker/api.Dockerfile.dockerignore` e `infra/docker/dashboard.Dockerfile.dockerignore`**, no grupo "Dados e fotos", antes das exceções de `ml/reports/`: as mesmas 9 extensões, com o prefixo `**/` (por exemplo, `**/*.[hH][eE][iI][fF]`).
- Nenhuma linha existente sai, muda ou troca de posição relativa. Antes de gravar, o autor confere que `git -c core.excludesFile=/dev/null ls-files -ci --exclude-standard` continua vazio.

#### 4.11 `pids_limit` igual a `0` ou `-1` e roteiro de atualização (SEC-32-03, RV-03 da SPEC-032)

- `.env.example`, no comentário logo acima de `API_PIDS_LIMIT=256`: uma linha dizendo que o valor é um inteiro positivo e que `0` ou `-1` removem o limite, então nunca devem ser usados. Texto: `# Inteiro positivo: 0 ou -1 removem o limite (sem aviso do compose); nunca use.`
- `docs/deployment-plan.md` §2, no item "Se um contêiner bater no `pids_limit`": a mesma regra, com "`0` ou `-1`".
- `docs/deployment-plan.md` §4, "Atualização", passo 3: "se algum serviço não subir ou reiniciar em loop, veja §2, 'Endurecimento dos contêineres' (`Read-only file system`, `can't start new thread`)".

## 5. Critérios de aceite

### Parte A

Contexto comum dos CA-01 a CA-05: como na SPEC-034 §5 (nuvem falsa com `httpx.MockTransport` e idempotência por `inspection_id`, relógio falso, `random.Random(0)`, SQLite real em `tmp_path`). "Linha adulterada" = linha criada por `put` (e `mark_dead`, quando `dead`) e depois alterada pelo teste com `sqlite3` direto no arquivo (`UPDATE outbox SET <coluna> = ? WHERE rowid = ?`). `M = "MARK" + secrets.token_hex(8)` (não é UUID nem data). "Log" = os registros capturados de todos os loggers.

- **CA-01 (security, SEC-34-01, listagem)** — *Dado* um outbox com 3 itens `dead` (`d1`, `d2`, `d3`, criados nessa ordem) e `d2` adulterado, em casos separados, com (a) `created_at = M`, (b) `attempts = M`, (c) `inspection_id = M`, (d) `created_at = b"\x00\xff"` (BLOB) e (e) `last_error = M.encode()` (BLOB), *quando* `main(["--outbox-path", <arquivo>])` roda, *então* o código é 0; o stdout tem exatamente 3 linhas: a de `d1`, a de `d3` e `2 dead item(s); run again with --yes to requeue`; o log tem exatamente um registro `WARNING` do logger `qc_edge.outbox` com `rowid=<rowid de d2>` e `column=<coluna>`, com `<coluna>` igual a `created_at`, `attempts`, `inspection_id`, `created_at` e `last_error`, respectivamente; `M` não aparece no stdout, no stderr nem no log; o stderr não contém `Traceback`; e o arquivo tem os mesmos bytes de antes.
- **CA-02 (security, R-05, SEC-34-01, reenvio e laço)** — *Dado* um outbox com 2 itens `pending` válidos (`p1`, `p2`), 1 `dead` válido (`d1`) e 1 `dead` adulterado com `created_at = M` (`d2`), e a nuvem falsa aceitando, *quando* `main(["--outbox-path", <arquivo>, "--yes"])` roda, *então* o código é 0 e o stdout é `requeued 2 item(s)`; *quando*, em seguida, `run_once` roda até `stats().pending == 0` (no máximo 10 ciclos), *então* `p1`, `p2` e `d1` ficam `sent`; `d2` fica `dead`, com `last_error == "invalid outbox row"` e `created_at` ainda igual a `M`; a nuvem tem exatamente os 3 ids de `p1`, `p2` e `d1` e 0 gravações duplicadas; o log tem exatamente um `WARNING` do `qc_edge.outbox` com `rowid=<rowid de d2>` e `column=created_at` e nenhum registro com `publish cycle failed unexpectedly`; `M` não aparece no log; e, em 5 ciclos seguintes, a nuvem não recebe nenhuma requisição de envio e o log não ganha `WARNING` do `qc_edge.outbox`.
- **CA-03 (SEC-34-01, `pending` adulterado)** — *Dado* um outbox com `p1` `pending` válido e `p2` `pending` adulterado, em casos separados, com (a) `next_attempt_at = M`, (b) `attempts = M` e (c) `inspection_id = M`, e a nuvem falsa aceitando, *quando* `run_once` roda até `stats().pending == 0` (no máximo 10 ciclos), *então* `p1` fica `sent`, a linha de `p2` fica `dead` com `last_error == "invalid outbox row"`, o log tem um `WARNING` do `qc_edge.outbox` com `rowid=<rowid de p2>` e `column=<coluna>` (`next_attempt_at`, `attempts` e `inspection_id`) e não contém `M`. *Quando*, nos casos (a) e (b), `main(["--outbox-path", <arquivo>, "--yes"])` roda e `run_once` roda até `stats().pending == 0`, *então* `p2` fica `sent` e a nuvem tem `p1` e `p2` uma vez cada.
- **CA-04 (security, SEC-34-01, defesa em profundidade)** — *Dado* um outbox válido com 1 item `dead` e `SqliteOutbox.dead_items` substituído no teste (com `monkeypatch`) por uma função que levanta `ValueError(M)`, *quando* `main(["--outbox-path", <arquivo>])` roda, *então* o código é 1, o log tem `outbox has an invalid row (ValueError)`, e `M` e `Traceback` não aparecem no stdout, no stderr nem no log. *Dado* `SqliteOutbox.requeue_dead` substituído por uma função que levanta `TypeError(M)`, *quando* `main([..., "--yes"])` roda, *então* o código é 1, com `outbox has an invalid row (TypeError)`, sem `M` e sem `Traceback`.
- **CA-05 (security, SEC-34-02)** — *Dado* um outbox válido com 1 item `dead` e modo `0o000` (o teste é pulado com `os.geteuid() == 0` e restaura o modo no fim), *quando* `main` roda com e sem `--yes`, *então* o código é 2, o log tem `cannot open --outbox-path (OperationalError)` e não tem `not an outbox file`, e, depois de restaurado o modo, a linha continua `dead`. *Dado* um arquivo de 4096 bytes `b"x"`, *então* o código é 2 com `--outbox-path is not an outbox file (DatabaseError)`. *Dado* um banco SQLite só com a tabela `other(x)`, *então* o código é 2 com `--outbox-path is not an outbox file (NotAnOutboxError)`. Nos dois últimos casos, com e sem `--yes`, o arquivo tem os mesmos bytes de antes.

Contexto comum dos CA-06 a CA-10: o da SPEC-036 §5 (`DATASET_DIR`, pasta de entrada e registro em `tmp_path`, fora de qualquer repositório Git; relógio falso em `2026-10-22T14:15:03Z`; `sleep` espião; imagens geradas pelo Pillow, nunca fotos reais, R-14; "linha de conhecido" = `S-501,screw,fair,a,2,contributor,c01,,,` com `notes` vazio).

- **CA-06 (security, R-14, SEC-36-01)** — *Dado* um PNG RGB 800×600 com um chunk de texto de chave `comment` e valor `M`, em casos separados, gravado como `tEXt` (`PngInfo.add_text("comment", M)`), `zTXt` (`add_text("comment", M, zip=True)`) e `iTXt` (`add_itxt("comment", M)`), *quando* é importado como linha de conhecido com `--privacy-checked`, *então* a CLI sai com 0, o stdout termina com `imported 1, skipped 0, failed 0`, e o arquivo gravado tem `jpeg_private_findings` vazio e não contém `M.encode()`.
- **CA-07 (security, R-14, SEC-36-03)** — *Dado* um JPEG 800×600 com EXIF `Make = M1`, `Artist = M2` e `Orientation = 1` (marcadores gerados no teste) e o teste conferindo antes a premissa: com o logger `PIL` em DEBUG, `qc_edge.jpeg.exif_orientation(<bytes>)` registra `M1`; *quando*, com o logger raiz em DEBUG (`caplog.set_level(logging.DEBUG)`), o nível do logger `PIL` em `NOTSET` e restaurado no fim do teste, (a) a importação roda com a linha de conhecido, e (b) `qc_edge.privacy.main(["--dataset-dir", <D2>])` roda sobre um `<D2>` com esse JPEG gravado diretamente em `raw/screw/fair/S-001__0__20261022T141503Z.jpg`, *então* (a) sai com 0 e (b) sai com 1, `M1` e `M2` não aparecem no log capturado, e, depois de cada `main`, `logging.getLogger("PIL").getEffectiveLevel() >= logging.INFO`. *Dado* o logger `PIL` em `WARNING` antes do `main`, *então* ele continua em `WARNING` depois.
- **CA-08 (security, RV-01 da SPEC-036, rollback dos diretórios)** — *Dado* `DATASET_DIR` com uma importação anterior da linha `N-501,nut,good,a,0,contributor,c01,,,` (existem `raw/` e `raw/nut/good/`) e o conjunto dos diretórios sob `DATASET_DIR`, com os modos, registrado, *quando* a linha de conhecido é importada com o espião do CA-09 da SPEC-036 levantando `OSError(errno.ENOSPC, ...)`, em casos separados, (a) na escrita do `sources.csv`, (b) na escrita do `manifest.csv` e (c) na escrita da imagem, *então* a CLI sai com 1, o conjunto dos diretórios sob `DATASET_DIR` (caminhos e modos) é igual ao de antes, e `raw/screw` não existe. *Dado* `raw/screw/` já existente antes (criado por uma importação anterior de `S-502,screw,good,a,0,contributor,c01,,,`), *quando* o caso (a) roda, *então* `raw/screw/` continua com o mesmo modo, e `raw/screw/fair` não existe.
- **CA-09 (RV-02, execução simultânea)** — *Dado* `DATASET_DIR` inexistente, um plano com a linha de conhecido, um relógio que avança 1 s por chamada do `sleep` espião e `rows_1 = load_plan(...)` e `rows_2 = load_plan(...)` chamados com os mesmos argumentos, os dois antes de qualquer gravação, *quando* `run_import(rows_1, dry_run=False, ...)` e depois `run_import(rows_2, dry_run=False, ...)` rodam, *então* o primeiro devolve 0 e escreve `imported 1, skipped 0, failed 0`; o segundo devolve 0, escreve `skipped <file>: already imported` e `imported 0, skipped 1, failed 0`; e o `manifest.csv` e o `sources.csv` têm 1 linha de dados cada, com 1 arquivo sob `raw/`. *Dado* o mesmo começo, mas, entre os dois `run_import`, a imagem gravada apagada e o `image_path` dela registrado em `exclusions.csv` (formato da SPEC-011, `reason=other`), *então* o segundo escreve `imported 1, skipped 0, failed 0`, e o `sources.csv` tem 2 linhas com o mesmo `input_sha256` e `image_path` diferentes.
- **CA-10 (security, R-14, SEC-36-02, entradas)** — *Dado* `tmp_path/repo` com um diretório `.git` vazio e, em outro caso, com um **arquivo** `.git` (como numa worktree), *quando* a CLI roda com `--privacy-checked` e (a) `--inbox tmp_path/repo/entrada`, (b) `--inbox tmp_path/repo/a/b`, (c) `--inbox` igual a um link simbólico fora do repositório que aponta para `tmp_path/repo/entrada`, (d) a pasta de entrada fora e `--plan tmp_path/repo/plano.csv` e (e) a pasta de entrada fora e `--plan` igual a um link simbólico fora que aponta para `tmp_path/repo/plano.csv`, *então* sai com 2 em todos os casos, a saída de erro contém `inbox must be outside any git repository` (a, b e c) ou `plan must be outside any git repository` (d e e), o `DATASET_DIR` não é criado, e o stdout está vazio. *Dado* a pasta de entrada e o plano fora de `tmp_path/repo`, *então* a importação da linha de conhecido sai com 0.
- **CA-11 (README)** — *Dado* `edge/README.md`, *então* a seção "Reenviar itens `dead`" contém `invalid outbox row` e `rowid`, e a seção "Importar fotos de fora da página" contém `fora do repositório` e `repositório Git`.

### Parte B

Os CAs marcados `docker` rodam só com `PARTQC_DOCKER_TESTS=1` (SPEC-015 §4.14), com contextos e cópias temporárias, nunca a árvore real. O host fictício é `partqc.example.org`.

- **CA-12 (security, R-03, SEC-32-01, SEC-39-06, Caddyfile)** — *Dado* `infra/Caddyfile` como texto, sem comentários, *então*: as condições do CA-30 da SPEC-015 e do CA-04 da SPEC-032 continuam valendo; há exatamente um bloco `handle_errors {` (sem argumento), dentro do bloco `{$PUBLIC_HOST}`; dentro dele, um bloco `header` com as 6 linhas da §4.9; o bloco `handle_errors` não contém `reverse_proxy`, `file_server`, `templates`, `rewrite`, nem `{err.` seguido de outra coisa que não `status_code}`; o bloco `header` fora do `handle_errors` tem as mesmas 6 linhas; e o texto do arquivo inteiro (sem comentários) não contém `{env.` nem `{$` (o site é o `:80`, pela nota do topo, e o `{$PUBLIC_HOST}` não existe mais no arquivo).
- **CA-13 (docker, SEC-32-01, adapt)** — *Dado* a imagem do Caddy fixada no compose, *quando* `caddy adapt --config /etc/caddy/Caddyfile` roda com `PUBLIC_HOST=partqc.example.org` e `--network none`, *então* sai com 0, sem aviso de formatação; em `apps.http.servers.<servidor>.errors.routes` há, em qualquer profundidade, um handler `headers` cuja resposta apaga `Server` e `Via` e define os 4 headers do CA-04 da SPEC-032, e nenhum handler `reverse_proxy`; e o CA-05 da SPEC-032 continua valendo nas `routes`.
- **CA-14 (docker, SEC-32-01, resposta de erro)** — *Dado* a imagem do Caddy executada como no CA-08 da SPEC-032 (`--read-only`, o `tmpfs` de `/tmp`, volumes temporários em `/data` e `/config`, `--pids-limit 256`, `--network none`), com o `infra/Caddyfile` real, `PUBLIC_HOST=http://partqc.example.org` (só no teste, para ler a resposta sem certificado) e sem os contêineres `api` e `dashboard`, *quando* uma requisição HTTP/1.1 é feita de dentro do contêiner a `127.0.0.1:80`, com `Host: partqc.example.org`, para `GET /api/v1/health` e para `GET /`, *então* cada resposta tem status 502; os headers `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `Content-Security-Policy: frame-ancestors 'self'`; nenhum header `Server` nem `Via`; corpo com 0 bytes; e o contêiner continua `running`.
- **CA-15 (R-02, R-14, SEC-32-02, `.gitignore`)** — *Dado* o `.gitignore` do repositório, *quando* `git -c core.excludesFile=/dev/null -c core.ignorecase=false check-ignore --no-index -q <caminho>` roda para cada caminho, *então* são ignorados `entrada/IMG_0001.HEIF`, `entrada/foto.heif`, `fotos/a.JFIF`, `fotos/a.jfif`, `fotos/a.JPE`, `fotos/a.jpe`, `scan/a.TIF`, `scan/a.tiff`, `scan/a.Tiff`, `raw/IMG_0001.DNG`, `fotos/a.avif`, `fotos/A.AVIF`, `entrada/IMG_0001.MOV`, `entrada/v.mov`, `entrada/v.MP4`, `entrada/v.mp4`, `docs/img/foto.tif` e `ml/reports/v1/curva.tiff`; e não são ignorados `.env.example`, `docs/img/Arquitetura.PNG`, `ml/reports/v1/grade_confusion.png`, `edge/src/qc_edge/importer.py`, `notas.movie`, `video.mp4.txt`, `README.md` e `ml/tests/fixtures/tiny_model/model.onnx`. E cada linha não vazia do `.gitignore` do início da rodada (copiada literalmente no teste) continua presente, na mesma ordem relativa, e `git -c core.excludesFile=/dev/null ls-files -ci --exclude-standard` não imprime nada.
- **CA-16 (R-02, R-14, SEC-32-02, `.dockerignore`)** — *Dado* os dois arquivos `infra/docker/<nome>.Dockerfile.dockerignore`, *então* cada um tem as 9 linhas `**/*.[hH][eE][iI][fF]`, `**/*.[jJ][fF][iI][fF]`, `**/*.[jJ][pP][eE]`, `**/*.[tT][iI][fF]`, `**/*.[tT][iI][fF][fF]`, `**/*.[dD][nN][gG]`, `**/*.[aA][vV][iI][fF]`, `**/*.[mM][oO][vV]` e `**/*.[mM][pP]4`, todas antes de `!ml/reports/**/*.png`. *(docker)* *Dado* um contexto montado com `build_image(..., extra_files=<sentinelas>)` (CA-36 da SPEC-015) com as sentinelas `foto.HEIF`, `foto.jfif`, `foto.JPE`, `scan.tif`, `scan.TIFF`, `raw.dng`, `foto.AVIF`, `IMG_0001.MOV` e `video.mp4`, *quando* as duas imagens são construídas e se roda nelas `test -e /app/<caminho>` para cada sentinela, *então* nenhuma existe em nenhuma das duas imagens, e o CA-36 da SPEC-015 continua valendo.
- **CA-17 (SEC-32-03, RV-03 da 032, documentação)** — *Dado* o `.env.example`, *então* as 3 linhas logo acima de `API_PIDS_LIMIT=256` contêm `Inteiro positivo: 0 ou -1 removem o limite`. *Dado* o `docs/deployment-plan.md`, *então* o item que começa com `- **Se um contêiner bater no` contém `` `0` ou `-1` ``; o passo 3 da seção `### Atualização` contém `Endurecimento dos contêineres` e `Read-only file system`; e o arquivo contém `handle_errors` e a URL `https://github.com/caddyserver/caddy/blob/master/modules/caddyhttp/staticresp.go` (a fonte da §4.9).
- **CA-18 (manual, VPS)** — Depois da atualização da SPEC-015 §4.16 com esta SPEC na `main`:
  1. `docker compose -f infra/compose.yaml stop api`;
  2. `curl -sI https://<subdominio>/api/v1/health`: status 502, com `strict-transport-security`, `x-content-type-options`, `referrer-policy` e `content-security-policy`, e sem `server:` nem `via:`;
  3. `docker compose -f infra/compose.yaml start api` e, em até 60 s, `curl -s https://<subdominio>/api/v1/health` responde 200;
  4. registrar as saídas no dev-report e no `deployment-plan.md`, com o subdomínio trocado por `<subdominio>` (SEC-15-01).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor, Parte A) | Validação de cada coluna (tipos, BLOB, `NULL` onde a SPEC-009 permite), `fetch_due` com linhas inválidas no meio e no limite de 100, `dead_items`, captura na CLI, mensagens de abertura, `info` vazio antes do `save`, nível do `PIL`, rollback dos diretórios, reconferência do hash com e sem exclusão, detecção do `.git` (diretório, arquivo, link) | `edge/tests/` |
| Unitário (autor, Parte B) | Caddyfile como texto, `caddy adapt` e resposta de erro (docker), `.gitignore` e `.dockerignore` (caminhos de exemplo), textos do `.env.example` e do plano | `infra/tests/` |
| Aceite (tester) | Um por CA automatizável | `edge/tests/acceptance/test_spec_038.py` (CA-01 a CA-11); `infra/tests/acceptance/test_spec_038.py` (CA-12 a CA-17) |
| Manual (humano) | CA-18, na VPS | descrito no CA |

- **Mocks:** só fronteiras: a nuvem (`httpx.MockTransport`), o relógio, o RNG, o `sleep`, a escrita de arquivo nos casos de erro (o espião do CA-09 da SPEC-036). O CA-04 substitui `dead_items`/`requeue_dead` de propósito, para exercitar a defesa em profundidade. Nenhum teste usa a VPS, o DNS nem a rede externa.
- O CA-07 muda níveis de logger globais: o teste restaura o nível do `PIL` e do raiz no fim (`monkeypatch` ou `try/finally`).
- **Ordem da rodada:** developer (Parte A) → security-devops (Parte B) → tester → reviewer → portão de segurança. Cada autor faz commits só nos caminhos da própria parte e acrescenta a sua seção no `reviews/SPEC-038/r<N>-dev-report.md` (o security-devops acrescenta `## Parte B (security-devops)` no fim, sem mudar a parte do developer).
- **Portão de segurança (R-07):** um único `reviews/SPEC-038/r<N>-security-report.md` com duas seções: `## Parte A (security-devops)`, escrita pelo security-devops, e `## Parte B (reviewer)`, escrita pelo reviewer com a seção 6 do checklist, como na SPEC-032. Cada um só escreve a própria seção. O veredicto do relatório é PASS só com as duas seções PASS.

## 7. Riscos e notas para o implementador

- **Escrita dentro do `fetch_due`:** hoje ele só lê. A mudança para `dead` por `rowid` é a única escrita nova e fica numa transação curta, sob o mesmo lock. Não use o `inspection_id` no `WHERE`, porque ele pode ser justamente a coluna inválida.
- **Afinidade de tipo do SQLite:** a coluna `TEXT` converte números em texto, e a `INTEGER` converte texto numérico em inteiro, mas um BLOB fica BLOB, e um texto não numérico em `attempts` fica texto. Por isso a validação confere o tipo Python devolvido, e não só a conversão.
- **`created_at` inválido e ordenação:** a consulta ordena pelo texto. Um valor como `MARK…` ordena depois dos timestamps válidos e entra na janela de 100 quando há 100 pendentes ou menos, que é o caso dos testes.
- **Logger `PIL`:** não mude o nível dentro de `qc_edge.jpeg` (efeito colateral numa biblioteca usada pela rota de coleta); só nos dois `main`.
- **`.git` acima da pasta de entrada:** se a pasta pessoal do operador for um repositório Git (dotfiles), toda pasta de entrada dentro dela será recusada. A mensagem diz o motivo, e o README orienta a usar uma pasta fora. Um `TMPDIR` dentro de um repositório faria os testes falharem: o contexto comum exige `tmp_path` fora de repositório.
- **`handle_errors` sem resposta:** se a rota de erro não escrever nada, o servidor HTTP do Go pode responder 200 com corpo vazio. Por isso a §4.9 exige uma resposta explícita com o status do erro, e o CA-14 confere o 502.
- **Vídeo da demo:** com `*.[mM][pP]4` e `*.[mM][oO][vV]` no `.gitignore`, um vídeo de backup da demo (S7) não entra no Git por engano. Se a dupla quiser um vídeo no repositório, precisa de exceção explícita e de SPEC.
- **Até esta SPEC entrar:** continua valendo a nota de operação do SEC-34-01 (se a listagem sair com código 1 e traceback, não rodar `--yes` sem `--id`), e um PNG de dataset público com `comment` é recusado com `normalization check failed`. Nesse caso, use outra imagem da fonte ou converta o PNG sem os chunks de texto antes de colocá-lo na pasta de entrada.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS), inclusive os `docker` no workflow `docker`
- [ ] review-report APPROVED + security-report PASS nas duas seções (Parte A pelo security-devops, Parte B pelo reviewer)
- [ ] CI verde (`ci` e `docker`); `ruff` limpo; cobertura de `qc_edge.outbox` ≥ 80% (RNF-09)
- [ ] `edge/README.md`, `.env.example` e `docs/deployment-plan.md` atualizados
- [ ] CA-18 (manual) registrado
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## 9. Perguntas para a aprovação (humano)

1. **Duas partes e portão dividido:** manter a Parte B com o security-devops (portão de segurança dela pelo reviewer, e o da Parte A pelo security-devops), ou passar tudo ao developer, com o security-devops fazendo o portão inteiro? **Recomendação do architect:** duas partes. O `Caddyfile`, os testes `docker` e os `.dockerignore` são do security-devops desde a SPEC-015, e os testes de autor da SPEC-032 que mudam são dele.
2. **CA-18 (manual, VPS):** manter o passo que para a `api` em produção por alguns segundos para ver o 502, ou confiar só no CA-14 (mesma imagem do Caddy, em contêiner local)? **Recomendação do architect:** manter. Só ele confere o caminho real com TLS e o Caddy publicado, e cabe na próxima atualização da VPS. Sem ele, a SPEC fecha sem pendência manual.
3. **Outras pendências de "próxima manutenção":** incluir também as baixas da SPEC-030 (por exemplo, `Content-Encoding` empilhado no publisher, SEC-30-01) e da SPEC-029 que o `docs/plan.md` §3 deixou sem SPEC? **Recomendação do architect:** não. A decisão de 2026-10-24 limitou a 038 às SPECs 034, 036 e 032. Incluir as outras quase dobraria a Parte A e mexeria no publisher logo antes da apresentação, para riscos que exigem um servidor hostil ou uma configuração errada feita à mão.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-24 | SPEC criada (`Draft`). Decisões do architect: (a) linha inválida do outbox vira `dead` no laço (`invalid outbox row`, por `rowid`) e é pulada na listagem, com aviso só de `rowid` e coluna; a CLI também captura `ValueError`/`TypeError` (§4.1); (b) `OperationalError` na abertura com mensagem própria, sem mudar o código 2 (§4.2); (c) `info` vazio antes do `save` na importação (§4.3); (d) logger `PIL` em pelo menos INFO nos `main` do importador e da varredura (§4.4); (e) rollback dos diretórios criados na linha (§4.5); (f) **RV-02 da 036 entra**: reconferência do hash sob o lock, porque o custo é pequeno (o `sources.csv` já é relido ali), o teste é determinístico e evita parar o pipeline com `duplicate_input` (§4.6); (g) pasta de entrada e plano recusados dentro de um repositório Git, no lugar de mais linhas no `.gitignore` para o plano (§4.7); (h) `handle_errors` no Caddy, com os mesmos 6 headers e corpo vazio, em vez de um segundo bloco `header` não adiado, que manteria o `Server` e poderia duplicar headers vindos da origem (§4.9); (i) 9 extensões de foto e vídeo só na forma com classes de caracteres (§4.10); (j) `0`/`-1` do `pids_limit` e o roteiro de atualização só em documentação (§4.11); (k) **RV-03 da 036 fica fora**, com a regra `PLE2502` (§3.2); (l) duas partes, developer e security-devops, com o portão de segurança dividido (§6). | SEC-34-01/02 de `reviews/SPEC-034/r1-security-report.md` e RV-01/02 de `r1-review-report.md`; O-01 a O-05 de `reviews/SPEC-036/r1-test-report.md`, RV-01 a RV-04 de `r1-review-report.md` e SEC-36-01 a 03 de `r1-security-report.md`; T-01, O-T-01 e O-T-02 de `reviews/SPEC-032/r1-test-report.md`, RV-01 a RV-03 de `r1-review-report.md` e SEC-32-01 a 03 de `r1-security-report.md`. Os relatórios das SPECs 036 e 032 foram lidos nas branches delas (`spec/SPEC-036-importacao-de-fotos` e a worktree da SPEC-032, PR #50) | Orquestrador, a pedido do humano (decisão de 2026-10-24) |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com as recomendações do §9: duas partes (developer na borda, security-devops no deploy) com o portão de segurança dividido, CA-18 manual na VPS mantido, sem pendências de outras SPECs. | Resposta do humano de 2026-10-24 (PR #51) | Orquestrador, a pedido do humano |
| 2026-10-25 | Nota no topo (ADR-023, `Proposto`). A Parte B passa a valer sobre o Caddy da SPEC-039: (a) depende também da SPEC-039 mergeada; (b) `handle_errors` dentro do site `:80`, e o texto do risco no `deployment-plan.md` cita o redirecionamento e os erros do proxy do Coolify; (c) o `.dockerignore` do Caddy não recebe as extensões; (d) CA-12, CA-13 e CA-14 com o endereço `:80`, a imagem de `infra/docker/caddy.Dockerfile` e os `tmpfs` da SPEC-039, sem o `PUBLIC_HOST` de teste; (e) CA-18 com `docker stop`/`docker start` pelo seletor do projeto do Coolify; (f) a regra dos testes de aceite antigos vale também para os da SPEC-039. A Parte A não muda. **O `handle_errors` continua nesta SPEC**, e não na SPEC-039, que fica restrita ao necessário para subir no Coolify (a confirmar pelo humano na aprovação do ADR-023). Classificação ADR-019: exige humano (X-2: ADR novo; X-5: dependência nova, a SPEC-039). SPEC marcada como "Aguardando reaprovação humana"; o status continua `Ready`. | Fato novo do humano em 2026-10-25 (VPS gerenciada pelo Coolify) e ADR-023 | Orquestrador, a pedido do humano |
| 2026-10-25 | Alteração pelo ADR-023 reaprovada pelo humano (deploy pelo Coolify). | Resposta do humano de 2026-10-25 (PR #55) | Orquestrador, a pedido do humano |
| 2026-10-25 | Entra em `In Dev` encadeada na SPEC-017 (sobre a 018, a 016 e a 036), por decisão do humano de 2026-10-24: a Parte A (developer, borda) começa agora; a Parte B (security-devops, Caddy) entra depois do merge da SPEC-039 na `main` (ADR-023), trazida para esta branch. O merge desta SPEC só acontece depois dos merges da 036, 016, 018, 017 e 039. | Resposta do humano de 2026-10-24; ADR-023 | Orquestrador, a pedido do humano |
| 2026-10-26 | Correção do **SPEC_ISSUE-038-B1** (SEC-39-06). **§4.9, antes:** só o bloco `handle_errors` tinha proibição de placeholder ("nem placeholder `{err.*}` além de `{err.status_code}`"). **§4.9, depois:** um item novo, logo depois desse, proíbe em todo o arquivo os placeholders de ambiente `{env.*}` e `{$...}` (inclusive `{$VAR:padrão}`), porque o contêiner do Caddy tem a `READ_API_KEY` e o `PUBLIC_HOST` no ambiente (ADR-023, emenda 1). A fonte é a seção "Environment variables" de <https://caddyserver.com/docs/caddyfile/concepts>, consultada em 2026-10-26. **CA-12, antes:** "(SEC-32-01, Caddyfile) … e o bloco `header` fora do `handle_errors` tem as mesmas 6 linhas." **CA-12, depois:** "(security, R-03, SEC-32-01, SEC-39-06, Caddyfile) … o bloco `header` fora do `handle_errors` tem as mesmas 6 linhas; e o texto do arquivo inteiro (sem comentários) não contém `{env.` nem `{$` (o site é o `:80`, pela nota do topo, e o `{$PUBLIC_HOST}` não existe mais no arquivo)." O resto do CA-12 e da §4.9 não muda, nem os outros requisitos e CAs. **Evidência:** o `infra/Caddyfile` do commit `e601f98` (Parte B, r1) não tem `{env.` nem `{$` fora dos comentários: todas as chaves do arquivo delimitam blocos, e o `respond ""` não tem placeholder. Então a produção não muda: entram só o teste do autor (security-devops) e o do tester no CA-12, na mesma rodada r1. **Classificação ADR-019: exige humano.** Ela cumpre E-1 (o SPEC_ISSUE está em `reviews/SPEC-038/r1-dev-report.md`), E-2, E-3 (SPEC aprovada, `Blocked` por este SPEC_ISSUE) e E-5, mas não cabe em E-4, pelas exclusões X-5 e X-7. **X-5 (requisito novo):** a proibição não esclarece nem ajusta um requisito existente. A §4.9 só proibia `{err.*}` dentro do `handle_errors`, e o CA-12 herdava só a proibição do texto `PUBLIC_HOST` (CA-04 da SPEC-039). O CA novo não cabe em E-4.3, que exige cobrir só um comportamento corrigido em E-4.1 ou E-4.2: aqui não há correção desse tipo, e sim uma regra nova, que o código já cumpre por acaso. **X-7 (regra inegociável):** o item novo e o CA-12 passam a verificar a R-03, porque mantêm a `READ_API_KEY` fora das respostas e dos logs. A tag `security` da SPEC não é motivo, porque a X-8 foi removida. | SPEC_ISSUE-038-B1 da seção "Parte B (security-devops)" de `reviews/SPEC-038/r1-dev-report.md`; SEC-39-06 de `reviews/SPEC-039/r2-security-report.md` | Orquestrador (SPEC_ISSUE-038-B1) |
