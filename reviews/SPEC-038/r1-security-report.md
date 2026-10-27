# SPEC-038 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-038](../../docs/specs/SPEC-038-manutencao-borda-deploy.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops (Parte A, autor: developer) e reviewer (Parte B, autor: security-devops), como manda a SPEC §6 |
| Diff revisado | `e433c08...f9f6b0d` (`spec/SPEC-017-alertas-telegram..HEAD`, branch encadeada 036 → 016 → 018 → 017 → 038); a Parte B foi revisada em `405063c`, e depois de `f9f6b0d` só este relatório mudou |
| **Veredicto** | **PASS** (Parte A PASS e Parte B PASS; SPEC §6) |

| Parte | Revisor | Veredicto |
|---|---|---|
| A (`edge/`, developer) | security-devops | **PASS** |
| B (`infra/`, `.gitignore`, `.env.example`, `docs/deployment-plan.md`; security-devops) | reviewer | **PASS** |

## Parte A (security-devops)

**Veredicto da Parte A: PASS.** Nenhum achado bloqueante ou alto. Há 1 achado médio (SEC-38-01, o RV-01 do reviewer) e 2 informativos (SEC-38-02, o O-03 do tester, e SEC-38-03). Nenhum deles exige uma rodada nova: o código cumpre a §4.1 a §4.7, e o SEC-38-01 só se resolve com um requisito novo, que cabe ao architect.

### Superfície analisada

- **Rotas:** nenhuma. O diff da Parte A não toca a API, o gateway HTTP (`qc_edge.server`), o contrato nem o banco da nuvem.
- **Entradas externas:**
  - linhas do outbox SQLite lidas pelo `fetch_due` (laço de publicação) e pelo `dead_items` (CLI `python -m qc_edge.requeue`);
  - o arquivo do `--outbox-path` aberto pela CLI;
  - fotos de terceiros (PNG e JPEG) e o plano CSV do importador (`python -m qc_edge.importer`);
  - `exclusions.csv` e `sources.csv` relidos sob o lock.
- **Segredos:** nenhum novo. O outbox nunca guarda a `DEVICE_API_KEY` (SPEC-009), e a CLI de reenvio não a lê.
- **Dependências novas:** nenhuma. `uv.lock` e os `pyproject.toml` intocados.
- **Deploy:** nada na Parte A.
- **Arquivos de produção:** `edge/src/qc_edge/outbox.py`, `requeue.py`, `importer.py`, `privacy.py` e `edge/README.md` (commits `c1317fb` e `e0f1090`, `Agent: developer`).

### O que conferi

- **§4.1 (outbox).** A validação vem antes de qualquer conversão: `isinstance` e depois `UUID`/`parse_timestamp`. `ValueError` e `OverflowError` contam como coluna inválida, e `bool` é recusado em `attempts`. A exceção interna `_InvalidColumnError` guarda só o nome da coluna, nunca o valor.
  - O `UPDATE outbox SET status = 'dead', last_error = ? WHERE rowid = ? AND status = 'pending'` é parametrizado. Ele vai num `executemany`, sob o mesmo `threading.Lock` e numa transação (`with self._conn`). O `rowid` vem do próprio SQLite, nunca do `inspection_id`, que pode ser a coluna inválida (§7).
  - A guarda `status = 'pending'` impede que uma corrida com o `--yes` da CLI reescreva uma linha que já mudou.
  - Os avisos usam texto fixo, com `%d` para o `rowid` e o nome da coluna vindo de uma constante do código.
- **§4.1 (CLI).** `ValueError`/`TypeError` saem com 1 e logam só a classe, sem traceback e sem a mensagem. O `last_error` de uma linha válida continua passando pelo `printable_error` da SPEC-034.
- **§4.2.** `OperationalError` é capturado antes de `DatabaseError`, e o ramo final é `sqlite3.Error`. Os três saem com 2 e logam só a classe. A abertura continua por URI com `mode=ro`/`mode=rw`, sem criar o arquivo.
- **§4.3 (R-14).** `image.info.clear()` vem imediatamente antes do `save`, que continua sem `exif`, `icc_profile`, `xmp` e `comment`.
  - Conferi no `PIL/JpegImagePlugin.py` do Pillow 12.3.0 (a versão do `uv.lock`): o único metadado que o `_save` lê de `im.info`, e não do `encoderinfo`, é o `comment` (linha 791). Com o `info` vazio, não sobra caminho de metadado herdado.
  - A conferência `_output_is_clean` (passo 5) continua como segunda barreira.
- **§4.4 (R-14).** `limit_pil_logging()` roda logo depois do `_configure_logging()` nos dois `main` e só sobe o nível, nunca o rebaixa. Fica fora de `qc_edge.jpeg`, como pede a §7.
  - Nenhuma CLI tem caminho para DEBUG: `_configure_logging` fixa INFO, e não há variável `LOG_LEVEL`, `dictConfig` nem `fileConfig` em `qc_edge`.
- **§4.5.** `_remove_dirs` remove só a lista devolvida por `make_private_dirs` (diretórios criados nesta linha, sob o `DATASET_DIR`), do mais interno para o mais externo, com `rmdir`, que nunca apaga conteúdo. Um diretório que já existia nunca entra na lista.
- **§4.6 (R-05 no dataset).** `exclusions.csv` e `sources.csv` são relidos sob o `manifest_file_lock`. Um cabeçalho divergente ou ilegível para a importação com 1, e um hash já importado é pulado (`skipped <file>: already imported`, com o caminho pelo `printable_path`).
- **§4.7 (R-02, R-14).** `inside_git_repository` usa `os.path.lexists` no próprio caminho e em todos os `parents`. Recebe o `realpath` da pasta de entrada e o pai do `realpath` do plano, então um link simbólico de fora para dentro do repositório é recusado.
  - A checagem vem antes de qualquer leitura do dataset e do plano, e nada é criado.
  - Um `.git` arquivo (worktree) e um link pendurado também contam.
- **R-02.** Nenhum import de rede novo (`httpx`, `socket`, `requests`, `urllib.request`, `subprocess`) no diff de `edge/src`.
- **R-03.** Busca no diff de `edge/` por JWT, `sk-`, `ghp_`, URL com senha, `password=`, `service_role` e chave privada: nada. Os testes usam marcadores de `secrets`.
- **R-07.** Os commits de produção da Parte A (`c1317fb`, `e0f1090`) e o dev-report (`80a36f8`) têm `Agent: developer`, `Refs: SPEC-038` e `Co-Authored-By` num único bloco final, e só tocam `edge/` e a seção da Parte A do dev-report. Não sou autor de nenhum deles.
- **Comandos (só leitura):**
  - `uv run pytest -q edge/tests/test_outbox.py edge/tests/test_requeue.py edge/tests/test_importer.py edge/tests/acceptance/test_spec_{009,034,036,038}.py`: 683 passed;
  - `uv run ruff check edge`: limpo.
- **Reprodução do RV-01.** Rodei um script no scratchpad da sessão, fora do repositório, sobre um outbox temporário. O resultado está no SEC-38-01.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-38-01 (= RV-01 do reviewer) | média | input | `edge/src/qc_edge/outbox.py:329` (`fetch_due`), `:407` (`dead_items`); `edge/src/qc_edge/publish_loop.py:173` | **Texto que não é UTF-8 numa coluna `TEXT` do outbox ainda trava o laço e ecoa o valor no log.** Detalhes abaixo da tabela. | **Nenhuma nesta rodada (pendência).** Detalhes abaixo da tabela. |
| SEC-38-02 (= O-03 do tester) | informativo | privacy | `edge/src/qc_edge/privacy.py:231-240` (`limit_pil_logging`) | **Logger filho do `PIL` com nível próprio.** Detalhes abaixo da tabela. | Nenhuma. |
| SEC-38-03 | informativo | privacy | `edge/src/qc_edge/importer.py:665-671` (`inside_git_repository`) | **A detecção de repositório só vê uma entrada `.git` no caminho.** Detalhes abaixo da tabela. | Nenhuma. |

#### SEC-38-01: texto não UTF-8 numa coluna `TEXT` do outbox

**O que acontece.** Um valor gravado como `CAST(X'…ff…' AS TEXT)` numa coluna `TEXT` (por edição à mão ou por página corrompida) faz o próprio `fetchall()` levantar `sqlite3.OperationalError: Could not decode to UTF-8 column '<coluna>' with text '<valor>'`, antes de a validação da §4.1 rodar.

**Reprodução.** Rodei um script com 2 linhas `pending` e `created_at = CAST(b"\x1b[31m<marcador>\xff\xfe" AS TEXT)` na segunda. O `fetch_due(100)` levanta a exceção, e a mensagem traz o marcador e a sequência ESC crua.

**Efeitos:**

- **Laço.** Cai no `logger.exception("publish cycle failed unexpectedly")` a cada ciclo. O traceback leva o valor, inclusive caracteres de controle (injeção de sequências de terminal no log).
- **Envio.** Para por inteiro, e não só para o lote: com o `fetchall()` falhando, nenhuma linha do outbox sobe. Num `created_at`, um byte menor que `"2"` ordena a linha antes de todas as outras e a mantém na janela.
- **CLI.** Sem eco. A listagem sai com 1, com `outbox access failed (OperationalError)` (conferido). O `--yes` sem `--id` devolve a linha a `pending`, porque o `UPDATE` não decodifica, e o laço trava.
- **Outras colunas.** A coluna `payload` tem o mesmo problema.

**Por que média e não alta:**

- (a) Exige escrita no arquivo do outbox (`0600`, na conta do operador, no notebook da LAN). Quem tem essa escrita já pode apagar ou alterar os resultados, o que é pior que este efeito. O modelo de ameaça é o mesmo do SEC-34-01.
- (b) Não há perda de dado. Os resultados ficam no outbox e sobem depois que a linha é corrigida, sem duplicata (R-05).
- (c) Não há quebra de confidencialidade. O valor ecoado é o conteúdo do próprio arquivo, que só guarda o JSON dos resultados, o `inspection_id` e datas: nunca imagem (R-02) nem a `DEVICE_API_KEY` (R-03).
- (d) A corrupção natural que produz exatamente um texto não UTF-8, sem o SQLite acusar `malformed`, é rara.

Concordo com a média do reviewer pelo efeito em disponibilidade.

**Por que não FAIL.** O código cumpre a §4.1, que define "linha válida" pelo tipo Python devolvido pelo `sqlite3`. Corrigir exige um requisito novo, que o developer não pode inventar e que viria do architect.

**Pendência para a próxima manutenção da borda.** Levar ao architect, cobrindo `fetch_due` e `dead_items` e todas as colunas `TEXT`, inclusive o `payload`. Dois caminhos possíveis:

- um `text_factory` que, num `UnicodeDecodeError`, devolva um marcador interno tratado como coluna inválida pelos `_read_*`;
- em `OperationalError` de decodificação, reler linha a linha por `rowid` com `CAST(... AS BLOB)`, marcar a linha `dead` por `rowid` (§4.1) e nunca logar a mensagem da exceção.

O teste deve conferir que o valor (e um ESC) não aparece no log do laço.

**Até lá, nota de operação** (a mesma da SPEC-034): se a listagem da CLI sair com 1, não rode `--yes` sem `--id`. Corrija ou retire a linha à mão.

#### SEC-38-02: logger filho do `PIL` com nível próprio

Com o `PIL.TiffImagePlugin` em DEBUG **explícito**, o `limit_pil_logging()` (que, pela §4.4, sobe só o logger `PIL`) não impede o registro do `Make`.

Fica como informativo porque:

- nenhuma CLI do projeto configura um logger filho do `PIL`, nem tem caminho para DEBUG (`_configure_logging` fixo em INFO, sem variável de nível);
- seria preciso configurar o logging à mão no mesmo processo;
- o log fica na máquina do operador (R-02 intacta), que já tem a foto com o EXIF.

Se o humano quiser fechar essa forma também, uma SPEC futura pode pedir que o `limit_pil_logging()` suba os loggers `PIL.*` já criados com nível menor que INFO, ou que ponha um filtro no handler. Não é exigido.

#### SEC-38-03: detecção de repositório só pela entrada `.git`

Um repositório com `GIT_DIR`/`--git-dir` apontando para fora, ou com `core.worktree`, não é detectado.

Fica como informativo porque a §4.7 define a regra exatamente assim, e ela é uma defesa a mais. A defesa principal continua sendo a orientação de manter a pasta de entrada e o plano fora do checkout (`edge/README.md` e `docs/dataset-protocol.md` §10.6), junto com o `.gitignore`.

O caso comum (o checkout do projeto, inclusive uma worktree com `.git` arquivo) é coberto, e o tester o conferiu num repositório real.

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md)), Parte A

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | N/A. Nenhuma rota no diff da Parte A |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | ✅ com pendência. Linhas do outbox conferidas por tipo e formato antes da conversão (§4.1). O `payload` continua revalidado pelo contrato no `_load`. Imagem pelo Pillow com `info` vazio e a conferência do passo 5. Pasta de entrada e plano recusados dentro de repositório Git. A forma não UTF-8 fica pendente (SEC-38-01) |
| SQL sempre parametrizado | ✅ Os `SELECT` e o `UPDATE ... WHERE rowid = ?` novos usam `?`, sem f-string em query |
| RLS; `DATABASE_URL` e `service_role` só na API | N/A. A Parte A não toca o banco da nuvem |
| CORS | N/A |
| Logs sem segredos e sem payload de imagem | ✅ com pendência. Os avisos novos são de texto fixo (`rowid` e coluna), e a CLI loga só classes. O `PIL` fica em INFO ou acima nas duas CLIs. Exceção pendente: o traceback do laço no SEC-38-01, que ecoa o conteúdo do próprio outbox (sem segredo nem imagem) |
| Dependências novas | ✅ Nenhuma |
| Deploy | N/A na Parte A (a Parte B é do reviewer) |
| Reaprovação delegada (ADR-019) | N/A. Nenhuma reaprovação sob o ADR-019 nesta branch. O SPEC_ISSUE-038-B1 (Parte B) foi reaprovado pelo humano em 2026-10-26 e não muda a Parte A |

### Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| (nenhuma) | | | |

### Ações pendentes para o humano

- Decidir se o SEC-38-01 entra na próxima manutenção da borda (SPEC pelo architect). Até lá, vale a nota de operação acima.
- Nenhuma ação em conta externa pela Parte A.

### Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi esta seção do relatório.
- [x] Não sou autor da Parte A (developer). Sou o autor da Parte B, cujo portão é do reviewer, na seção abaixo.

## Parte B (reviewer)

**Veredicto da Parte B: PASS.** Não há achado bloqueante nem alto. Há 1 achado baixo (SEC-38-B4), que não é do autor da Parte B, e 3 informativos (SEC-38-B1 a B3). Nenhum deles pede uma rodada nova. O Caddyfile, os arquivos de ignore, o `.env.example` e o plano de deploy cumprem a §4.9 a §4.11 com a nota do topo (ADR-023) e a correção do SPEC_ISSUE-038-B1.

### Superfície analisada

- **Rotas:** nenhuma rota nova na API nem no dashboard. Mudam só as respostas de erro geradas pelo próprio Caddy no site `:80` (`handle_errors`). O `header` do site, o `handle /api/*` e o `handle` sem matcher continuam iguais.
- **Entradas externas:** as requisições HTTP que chegam ao Caddy pelo proxy do Coolify. O `handle_errors` não usa nenhum placeholder de requisição, de erro nem de ambiente, então nenhuma parte da requisição, do erro ou do ambiente volta ao cliente.
- **Segredos:** nenhum novo. Pela emenda 1 do ADR-023, a `READ_API_KEY` e o `PUBLIC_HOST` estão no ambiente do contêiner do Caddy, e o Caddyfile não tem `{env.` nem `{$` fora dos comentários (nem dentro deles). O `.env.example` ganhou só uma linha de comentário, e nenhuma variável nova.
- **Privacidade das fotos (R-02, R-14):** 9 extensões de foto e vídeo de celular no `.gitignore` e nos `.dockerignore` da API e do dashboard. O `.dockerignore` do Caddy (`*` e `!infra/Caddyfile`) não mudou.
- **Dependências novas:** nenhuma. O `infra/docker/caddy.Dockerfile` (tag e digest), os compose, o `uv.lock` e os `pyproject.toml` não estão no diff.
- **Deploy:** `docs/deployment-plan.md`: o aviso de `pids_limit` `0`/`-1` (§2), o diagnóstico no passo 3 da "Atualização" (§4), o risco 9 (§7), a linha "Caddy: respostas de erro" na tabela da §2 e o CA manual da SPEC-038 (§9).
- **Arquivos de produção da Parte B:** `infra/Caddyfile`, `.gitignore`, `infra/docker/api.Dockerfile.dockerignore`, `infra/docker/dashboard.Dockerfile.dockerignore`, `.env.example` e `docs/deployment-plan.md`, no commit `e601f98`. Os testes do autor estão em `e601f98` e `bc9df6f`, e o dev-report em `8e38f5c`, todos com `Agent: security-devops`.

### O que conferi

- **§4.9, `handle_errors` (`infra/Caddyfile:36-46`):**
  - Há um único bloco, sem códigos de status, dentro do site `:80`, com as mesmas 6 linhas do `header` do site e `respond ""`.
  - Não há `reverse_proxy`, `file_server`, `templates`, `rewrite` nem `{err.*}`. No texto sem comentários, as únicas chaves são as 6 `{` que abrem blocos.
  - No `caddy adapt`, que rodei com a imagem fixada do `caddy.Dockerfile` e `--network none`, `errors.routes` tem 1 handler `headers` (`deferred: true`, apaga `Server` e `Via` e define os 4 headers) e 1 `static_response` sem `status_code` e sem `body`. Não há `reverse_proxy` nos erros.
- **Prova em contêiner (script no scratchpad da sessão, fora do repositório):**
  - **Montagem:** uma cópia do Caddyfile real com só os dois upstreams trocados por `127.0.0.1:9001` (um site do próprio Caddy que responde `503` com um JSON `{"detail": ...}`) e `127.0.0.1:9002` (fechada). O contêiner rodou com `--read-only`, `tmpfs` em `/tmp`, `/data` e `/config` e `--network none`, e o cliente HTTP/1.1 bruto rodou dentro dele.
  - **Erro gerado pelo Caddy:** `GET /` deu `502`, com os 4 headers, sem `Server` e sem `Via` e com `Content-Length: 0`.
  - **Erro da origem:** `GET /api/v1/health` deu o `503` da origem, com o corpo `{"detail": ...}` intacto e os 4 headers. Ou seja, o `handle_errors` não engole as respostas de erro da API, que continuam com `{"detail": ...}`.
  - **Limpeza:** o contêiner foi removido com `-v`, e não sobrou nenhum `partqc-test-reviewer038-*`.
- **§4.9, nenhum placeholder de ambiente (SEC-39-06, R-03):** uma busca por `{env.`, `{$` e `{err.` no texto sem comentários do `infra/Caddyfile` não acha nada. Os testes que plantam `{env.READ_API_KEY}`/`{$READ_API_KEY}` (do autor, numa cópia temporária, e do tester, em memória) usam só o nome da variável, sem valor.
- **§4.9, plano (`docs/deployment-plan.md:56`, `:426`):** o risco 9 segue o texto da nota do topo (redirecionamento e erros do próprio proxy do Coolify continuam sem os headers). A URL do `staticresp.go` e a data estão no risco e na tabela da §2.
- **§4.10, extensões (`.gitignore:40-48`; `infra/docker/{api,dashboard}.Dockerfile.dockerignore:43-51`):**
  - As 9 linhas estão só na forma com classes de caracteres, antes das exceções de PNG (`!docs/**/*.png`, `!ml/reports/**/*.png`). Nenhuma exceção existente as reabre: as 4 exceções do `.gitignore` e as 2 de cada `.dockerignore` casam só PNG.
  - Nos `.dockerignore`, os padrões têm o prefixo `**/`. Os dois arquivos diferem só no comentário do topo.
  - `git -c core.excludesFile=/dev/null ls-files -ci --exclude-standard` está vazio.
  - Os testes docker do autor e do tester confirmam que as sentinelas da raiz e das subpastas ficam fora das imagens.
- **§4.11 (`.env.example:115`; `docs/deployment-plan.md:95`, `:345`):** o texto exato da §4.11 fica logo acima de `API_PIDS_LIMIT=256`. O plano tem a mesma regra, com o comportamento do Compose conferido pelo autor e pelo tester (`0` some do `config`, `-1` passa sem aviso), e o passo 3 da "Atualização" aponta para "Endurecimento dos contêineres".
- **Coerência com o Coolify (ADR-023, dois recursos):**
  - O CA manual (`docs/deployment-plan.md:657`) lista os contêineres pelo `com.docker.compose.project=<uuid>` do `partqc-api`, que pelo `infra/compose.api.yaml` só tem o serviço `api`, e para só ele com `docker stop`.
  - Ele proíbe parar o `coolify-proxy` e os contêineres de outros projetos. A volta é por `docker start` ou, se falhar, por **Deploy** só no `partqc-api`.
  - Nenhum passo reinicia o `coolify-proxy`, mexe no Traefik ou publica porta. O `restart: unless-stopped` não reinicia um contêiner parado com `docker stop`.
  - O registro pede `<subdominio>`, sem o UUID e sem o nome do contêiner (SEC-15-01).
- **Reaprovação do SPEC_ISSUE-038-B1:**
  - O `3631c81` (`Agent: architect`) só muda a SPEC.
  - O Histórico tem o antes e o depois da §4.9 e do CA-12, a classificação "exige humano" (X-5, X-7) e a linha de reaprovação **pelo humano** em 2026-10-26.
  - O `c24af04` (orchestrator) só troca o status, a nota do topo e acrescenta essa linha, sem mexer em requisito.
  - Não há reaprovação sob o ADR-019 nesta branch.
- **R-07:**
  - Os commits de produção e de teste do autor da Parte B (`e601f98`, `bc9df6f`) e o dev-report (`8e38f5c`) têm `Refs: SPEC-038`, `Agent: security-devops` e `Co-Authored-By` num único bloco final. Eles tocam só os arquivos da §3.1 (Parte B), testes de autor em `infra/tests/` fora de `acceptance/` e a seção Parte B do dev-report.
  - Os aceites da Parte B e os 4 ajustes de aceites antigos estão no `d6a58a9` (`Agent: tester`), na tabela do test-report.
  - Não sou autor de nenhum desses commits.
- **R-01:** nenhum serviço ou conta nova. Caddy, Docker e Coolify continuam os mesmos, auto-hospedados.
- **R-03:** busquei no diff da Parte B (inclusive `infra/tests/`) JWT, URL com senha, `password=`, `service_role`, chave privada, `sk-`, `ghp_`, `xox*-` e o formato de token do Telegram, e não achei nada. Também não há subdomínio real, IP (fora de `127.0.0.1`) nem UUID de recurso. O host dos testes é `partqc.example.org`.
- **R-13:** a identidade é única (CarlosZeyy, e-mail `noreply` do GitHub), os commits seguem Conventional Commits e nenhuma empresa ou ferramenta corporativa é citada no diff.
- **Comandos (só leitura):**
  - `uv run ruff check .` e `uv run ruff format --check .`: limpos (273 arquivos);
  - `uv run pytest -q infra/tests`, sem banco e sem docker: 554 passed, 493 skipped;
  - `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker` em `infra/tests/test_deploy_maintenance.py` e em `infra/tests/acceptance/test_spec_{038,032,039}.py`: 55 passed. A lista de contêineres, redes, imagens e volumes ficou idêntica antes e depois.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-38-B1 | informativo | privacy | `.gitignore:40-48`; `infra/docker/{api,dashboard}.Dockerfile.dockerignore:43-51` | **Formatos fora das 9 extensões.** Detalhes abaixo da tabela. | Nenhuma. |
| SEC-38-B2 | informativo | deploy | `infra/Caddyfile:36-46` | **`499` quando o cliente fecha a escrita cedo (O-02 do tester).** Detalhes abaixo da tabela. | Nenhuma. |
| SEC-38-B3 | informativo | deploy | `infra/Caddyfile:36-46` | **Erros que o servidor HTTP do Go gera antes dos handlers do Caddy.** Detalhes abaixo da tabela. | Nenhuma. |
| SEC-38-B4 | baixa | deploy | `docs/plan.md:77` (merge `9d2d7d3`, orchestrator) | **A coluna "Depende de" da SPEC-038 perdeu a SPEC-039.** Detalhes abaixo da tabela. | Nenhuma nesta rodada. Detalhes abaixo da tabela. |

#### SEC-38-B1: formatos fora das 9 extensões

`.3gp`, `.m4v`, `.gif`, `.bmp` e os RAW de fabricante (`.cr2`, `.nef`, `.arw`) não são ignorados.

Fica como informativo porque:

- a §4.10 fixa exatamente as 9 extensões, que cobrem os formatos que um celular grava por padrão (o RAW do celular é DNG, e o vídeo é MP4/MOV);
- a defesa que vale para qualquer nome e formato é a recusa da pasta de entrada e do plano dentro de um repositório Git (§4.7, Parte A);
- o `.dockerignore` deixa `docs/` e `reviews/` fora das imagens, e o código não lê esses formatos.

Se a dupla passar a importar outro formato, ele entra numa SPEC, com o mesmo par `.gitignore`/`.dockerignore`.

#### SEC-38-B2: `499` quando o cliente fecha a escrita cedo

Um cliente que fecha o lado de escrita logo depois da requisição pode receber `499` em vez de `502`.

Fica como informativo porque:

- a resposta continua com os 4 headers, sem `Server` e com corpo vazio, ou seja, o `handle_errors` vale também nesse caso;
- o comportamento do status é o mesmo de antes da SPEC;
- o proxy do Coolify não fecha a escrita.

#### SEC-38-B3: erros gerados antes dos handlers do Caddy

Uma requisição malformada (`400`) ou com headers grandes demais (`431`) é respondida pelo `net/http` antes de qualquer rota, então não passa pelo `handle_errors` nem pelo `header`.

Fica como informativo porque:

- a §4.9 trata dos erros gerados pelo Caddy (rotas), e não dos do servidor HTTP;
- essas respostas não têm conteúdo emoldurável nem dados internos;
- antes de chegar ao Caddy, a requisição já passou pelo Traefik do Coolify.

Isso cabe no "risco aceito" do item 9 da §7 do plano, se o humano quiser registrá-lo numa manutenção.

#### SEC-38-B4: a SPEC-039 sumiu da coluna "Depende de"

**O que aconteceu.** A resolução de conflito do merge `9d2d7d3` trocou "036, 032 e 039 mergeadas" por "036, 032 mergeadas" na linha da SPEC-038 em `docs/plan.md`. Esse merge é do orchestrator, e não do autor da Parte B.

**Por que é baixa:**

- a nota do topo da SPEC continua exigindo a SPEC-039 mergeada, e o review-report a lista entre os merges que faltam (R-09);
- o código da Parte B já está sobre o Caddy da SPEC-039 (site `:80`, `caddy.Dockerfile`);
- o efeito é só na rastreabilidade do plano.

**Correção.** Nenhuma nesta rodada. Na próxima atualização de status da SPEC-038 em `docs/plan.md`, o orquestrador volta a coluna para "036, 032 e 039 mergeadas (e 034, 009, 015, 025, 030)".

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md)), Parte B

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | N/A. Nenhuma rota nova. O Caddy não autentica, e o `handle_errors` não lê nem devolve nenhum header da requisição (as chaves de leitura e da borda continuam só no header de ida para a API) |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | N/A no Caddyfile, que não interpola nenhuma parte da requisição nem do erro na resposta. As fotos ficam fora do Git e das imagens (§4.10) |
| SQL sempre parametrizado | N/A |
| RLS; `DATABASE_URL` e `service_role` só na API | ✅ Nada na Parte B toca o banco. A `DATABASE_URL` continua só no recurso `partqc-api`, e o CA manual não imprime nenhuma variável |
| CORS | N/A. Nenhum header CORS adicionado |
| Logs sem segredos e sem payload de imagem | ✅ O Caddyfile continua sem log de acesso e sem `{env.`/`{$` (a `READ_API_KEY` está no ambiente do contêiner). A resposta de erro tem corpo vazio, sem `{err.*}`, e a mensagem interna do erro (DNS, `dial tcp`) não vai ao cliente (conferido pelo tester e por mim no contêiner) |
| Dependências novas | ✅ Nenhuma. A imagem do Caddy (tag e digest) não mudou |
| Deploy | ✅ Variáveis por recurso no Coolify (sem variável nova), healthchecks e compose intocados, nenhum plano pago (R-01). Os 2 recursos foram respeitados, e nada reinicia o `coolify-proxy`. O CA-18 manual está pendente com o humano |
| Reaprovação delegada (ADR-019) | N/A. Nenhuma reaprovação sob o ADR-019 nesta branch. O SPEC_ISSUE-038-B1 (§4.9 e CA-12) foi reaprovado pelo humano em 2026-10-26, como mostram o Histórico e a nota do topo |

### Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| (nenhuma) | | | |

### Ações pendentes para o humano

- O CA-18 (manual, VPS), depois do merge e da atualização da §4 do plano. Os passos estão em `docs/deployment-plan.md` §9, "CA manual da SPEC-038".
- Nenhuma ação em conta externa pela Parte B.

### SPEC_ISSUE

Nenhum.

### Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Só escrevi esta seção e atualizei o veredicto global no topo do relatório.
- [x] Não sou autor da Parte B (security-devops) nem de nenhum outro commit desta SPEC.
