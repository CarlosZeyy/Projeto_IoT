# SPEC-038 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-038](../../docs/specs/SPEC-038-manutencao-borda-deploy.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops (Parte A, autor: developer) e reviewer (Parte B, autor: security-devops), como manda a SPEC §6 |
| Diff revisado | `e433c08...f9f6b0d` (`spec/SPEC-017-alertas-telegram..HEAD`, branch encadeada 036 → 016 → 018 → 017 → 038) |
| **Veredicto** | **pendente da Parte B**. O relatório só é PASS com as duas seções PASS (SPEC §6) |

| Parte | Revisor | Veredicto |
|---|---|---|
| A (`edge/`, developer) | security-devops | **PASS** |
| B (`infra/`, `.gitignore`, `.env.example`, `docs/deployment-plan.md`; security-devops) | reviewer | pendente |

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

*A ser escrita pelo reviewer, com a seção 6 do checklist (SPEC §6).*
