# SPEC-036 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-036](../../docs/specs/SPEC-036-importacao-de-fotos.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...b43b03e` (`origin/main` = `31979b9`; a `main` local está atrás e inclui o PR #45, já mergeado) |
| Test report | r1-test-report.md (PASS nos CA-01 a CA-16; CA-17 manual pendente da dupla) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante, alto ou médio. Os quatro achados são baixos e não pedem rodada nova. Ficam como pendências para uma manutenção da borda ou para o security-devops avaliar no `r1-security-report.md`, que a tag `security` exige.

Para o merge (R-09), ainda faltam o `security-report` PASS do security-devops e o registro do CA-17 manual pela dupla, que a Definição de pronto exige.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `edge/src/qc_edge/importer.py:839` e `:880` | No rollback de uma falha de E/S (§4.4), o `_remove_image` apaga a imagem e faz o `fsync` do diretório, mas os diretórios `raw/<tipo>/<grau>/` criados para ela pelo `make_private_dirs` (passo 4) ficam vazios (O-03 do test-report). O CA-09 só pede "nenhuma imagem nem temporário", então o comportamento cumpre a SPEC. A varredura de privacidade e o `validate` ignoram diretório vazio, e o modo é `0700`. | Numa manutenção da borda: guardar a lista que o `make_private_dirs` devolve e, no rollback, remover com `rmdir` os diretórios criados nesta linha (do mais interno para o mais externo, ignorando `OSError`). A alternativa é registrar no README que pode sobrar diretório vazio. |
| RV-02 | baixa | `edge/src/qc_edge/importer.py:825-829` (`_store_locked`) e `:592-595` | A decisão de pular (`skip`) é tomada só na fase 1. Sob o lock, o passo 2 reconfere os cabeçalhos e o `item_type_conflict`, como a SPEC manda, mas não reconfere o `input_sha256`. Duas execuções simultâneas do mesmo plano (dois terminais) gravam a mesma foto duas vezes. Confirmei com uma sonda fora do repositório: duas chamadas ao `load_plan` antes de dois `run_import` geram duas linhas no `sources.csv` com o mesmo `input_sha256`. O `qc_ml.data` acusa isso depois como `duplicate_input` (`ml/src/qc_ml/data.py:634-641`), e a correção é pelo `exclusions.csv`. Nada se perde e nada vaza entre splits (mesmo `item_id`), mas o pipeline para até a dupla corrigir. A SPEC não exige a reconferência. | Numa manutenção da borda (com SPEC): o `_check_headers` já lê o `sources.csv` inteiro sob o lock. Basta reconferir ali se o `input_sha256` já está numa linha não excluída e, nesse caso, imprimir `skipped <file>: already imported`. |
| RV-03 | baixa | `edge/tests/acceptance/test_spec_036.py:678, 756, 1598, 1617, 1674`; `edge/tests/test_importer.py:581, 586, 854, 881, 1058` | Os testes têm caracteres invisíveis literais no código-fonte (U+2028, U+202E, U+00AD, U+FEFF). O U+202E literal é o padrão "Trojan Source": um revisor vê `marker + ""` e não sabe o que o teste exercita. O `edge/tests/test_collect.py` já fazia o mesmo antes desta SPEC, e os testes estão certos (conferi os bytes: `E2 80 A8`, `E2 80 AE`). | Escrever como escape (`" "`, `"‮"`, `"­"`, `"﻿"`) nos dois arquivos novos e, numa manutenção, ligar a regra `PLE2502` (bidirectional-unicode) do ruff. Cada arquivo é do seu papel: tester no de aceite, developer no `test_importer.py`. |
| RV-04 | baixa | `edge/src/qc_edge/jpeg.py:112-138` (`exif_orientation`, via `Image.getexif` na linha 126) e `edge/src/qc_edge/importer.py:972-974` | O-05 do test-report: com o logger raiz em DEBUG, o `PIL.TiffImagePlugin` loga os valores das tags EXIF (por exemplo, `Make`) ao ler a orientação. A CLI configura o logging em INFO, e o teste com o processo real confirma que nada disso chega ao stdout nem ao stderr. O risco é só em quem chamar `main()` dentro de um processo com o logger raiz em DEBUG. O mesmo comportamento já existia no `has_exif_rotation` (SPEC-025). O §4.5 promete que o EXIF nunca é impresso. | Numa manutenção: no `main` do importador (e no da varredura), fixar `logging.getLogger("PIL").setLevel(logging.INFO)`, ou registrar a limitação no README. O security-devops avalia se basta como está. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Ver "Escopo, rastreabilidade e decisões do dev-report" e "Reaprovação delegada (ADR-019)" abaixo. |
| 2. Regras inegociáveis | ✅ | Ver "Regras inegociáveis" abaixo. |
| 3. Corretude | ✅ | RV-01 e RV-02 (baixos). Os casos de borda que conferi estão abaixo. |
| 4. Testes | ✅ | RV-03 (baixo). Ver "Testes" abaixo. |
| 5. Qualidade | ✅ | Ver "Qualidade" abaixo. |
| 6. Segurança | N/A neste relatório | A SPEC tem a tag `security` e o autor é o developer: o portão é o security-devops (`r1-security-report.md`). Ele também confere a reaprovação ADR-019 (checklist §6, X-6 e X-7) e as observações O-01, O-04 e O-05 e o RV-04. Pela minha leitura, a reaprovação não toca limite de segurança nem regra inegociável (ver §1 abaixo). |

### 1. Escopo, rastreabilidade e decisões do dev-report

- **Requisitos.** Conferi cada item da SPEC contra o código:
  - §4.1 CLI: argumentos, `--privacy-checked` antes de qualquer leitura, pasta de entrada fora do dataset por `realpath` nos dois sentidos, padrão do `--external-sources` (`parents[3]` de `qc_edge/__init__.py` = raiz), registro só com linha `external` e não eco pelo `QuietArgumentParser`/`describe_arguments`.
  - §4.2: as regras por célula, a ordem `tools_not_supported` → `origin_item_mismatch` → `invalid_item_id`, `re.ASCII` nas regex, os limites de 5 MiB e 5.000 linhas, a tabela de colunas da correção 02 e a retomada pelo hash fora do `exclusions.csv`.
  - §4.3: a orientação é lida antes do `strip_private_segments`; o `load_image` recebe os bytes limpos; a tabela do `exif_transpose`; a redução inteira (`reduced_size`); o mínimo de 256 vem de `PreprocessParams().resize_shorter`; q=90 sem `exif`/`icc_profile`; a conferência de saída e os 5 motivos fixos.
  - §4.4: normalização fora do lock; `flock` por linha; colisão de nome com `sleep(1.0)` e 3 tentativas; manifest antes do `sources.csv`; rollback com `ftruncate` + `fsync` ou `unlink` do arquivo criado; modos exatos; `--dry-run` sem nada sob `DATASET_DIR`.
  - §4.5 a §4.8: entradas só lidas; saída por `printable_path`; códigos 0/1/2; cobertura e `count_external_images`; README.
- **Fora do escopo:** nada. O `collect.py` só extraiu funções (`read_csv_rows`, `read_manifest_entries`, `append_csv_row`, `rollback_append`, `valid_notes`, `has_forbidden_char`), e o `DatasetWriter` continua com o mesmo comportamento. Os testes de aceite das SPECs 010, 025 e 030 passam sem ajuste, e a regex da rota (`ITEM_ID_PATTERN`) não mudou (CA-14).
- **CAs não alterados pelo autor [R-08]:** ✅. Os únicos textos alterados foram os da reaprovação ADR-019, feitos pelo architect.
- **Rastreabilidade:** ✅ no dev-report (CA → arquivo → teste do autor) e no test-report (CA → teste de aceite).
- **Decisões do dev-report fora da SPEC** (itens 1 a 11). Nenhuma muda contrato, regra ou comportamento pedido, e todas estão registradas, não só embutidas no código:
  - item 1: mensagens fixas de código 2 que a SPEC não lista; o `exclusions.csv` com o cabeçalho exato da SPEC-011, igual ao `qc_ml.data.EXCLUSION_COLUMNS`;
  - item 2: plano acima de 5 MiB → `unreadable_csv (-)`;
  - item 3: ordem das checagens;
  - item 4: as linhas `plan line` vão direto ao stderr;
  - item 5: releitura com o hash conferido e `input changed since validation`. Aceito: a fase 2 precisa dos bytes, guardar 5.000 × 40 MiB em memória não é viável, e conferir o hash garante que o `input_sha256` gravado é o da imagem gravada (§4.5);
  - item 6: `item_type_conflict` sob o lock → só a linha falha, com o texto da coleta;
  - item 7: parada por E/S com `failed to write dataset`;
  - item 8: validação com a origem inválida;
  - item 9: logs só com `strerror`;
  - item 10: a refatoração do `collect.py`;
  - item 11: a dica para o espião do CA-09.

  Eu não abriria `SPEC_ISSUE` para nenhuma delas.

#### Reaprovação delegada (ADR-019) [R-08, R-09]

Conferi o `git show 06e13f4` (architect) e o `git show 6020c0c` (orquestrador) contra o Histórico.

| Critério | SPEC_ISSUE-01 (§4.2, último parágrafo, e CA-15) | SPEC_ISSUE-02 (§4.2, tabela "Coluna mostrada") |
|---|---|---|
| E-1 Origem | ✅ SPEC_ISSUE-01 de `r1-dev-report.md` | ✅ SPEC_ISSUE-02 de `r1-dev-report.md` |
| E-2 Autoria | ✅ `06e13f4`, `Agent: architect`, só `docs/specs/SPEC-036-importacao-de-fotos.md` | ✅ o mesmo commit |
| E-3 Estado | ✅ aprovada pelo humano em 2026-10-23; `Blocked` por estes SPEC_ISSUE em `463f4f0` | ✅ idem |
| E-4 Natureza | ✅ tipos 1 e 2: o nome real da constante do `qc_ml` (`SOURCE_COLUMNS`, `ml/src/qc_ml/data.py:78`), com a mesma intenção (as duas tuplas iguais). O lado da borda não muda | ✅ tipo 1: o formato `plan line <n>: <code> (<coluna>)` já era exigido, e a correção só fixa a coluna dos códigos que a tabela não cobria. Mesmos códigos, mesmo código de saída, nada gravado |
| E-5 Abrangência | ✅ só o parágrafo e o CA-15, mais o aviso do topo e o Histórico (E-4.4) | ✅ só o parágrafo e a tabela novos, mais o aviso e o Histórico |
| X-1 a X-4 | ✅ nenhuma | ✅ nenhuma |
| X-5 Escopo novo | ✅ nenhum arquivo, constante ou assinatura novos | ✅ nenhum código, comando ou requisito novo; a coluna mostrada é sempre um nome fixo ou `-` |
| X-6 CA enfraquecido | ✅ não | ✅ não: o CA-04 não mudou e ficou mais preciso |
| X-7 Regra inegociável | ✅ o CA-15 verifica formato entre pacotes, não uma regra inegociável | ✅ a regra de não eco e as regras de `file` (R-14) não mudaram. A tabela só nomeia colunas, e o CA-04 ainda exige o marcador ausente |
| X-9 | ✅ primeira correção deste trecho e deste CA | ✅ primeira correção deste trecho |
| Registro | ✅ texto antigo, novo, evidência e classificação no Histórico; aviso do topo e linha de aprovação no formato do ADR-019, passo 2 (`6020c0c`) | ✅ idem |

Conclusão: as duas correções estão dentro dos limites do ADR-019. Nenhum `SPEC_ISSUE` "exige humano". O PR precisa trazer a seção "Reaprovações sob o ADR-019" (ADR-019, passo 4), com `06e13f4` e `6020c0c`.

### 2. Regras inegociáveis

| Regra | Resultado | Evidência |
|---|---|---|
| R-01 | ✅ | Nenhuma dependência nova: `uv.lock` e `pyproject.toml` fora do diff. |
| R-02 | ✅ | O `importer.py` não importa nada de rede (nem `socket`, nem `httpx`, nem `urllib`). O CA-11 roda as três importações com `socket.socket` levantando `OSError`. Nenhuma imagem vai para a API: só arquivos locais sob `DATASET_DIR`. |
| R-03 | ✅ | Busca por `key`, `secret`, `token`, `password`, `postgres://`, `eyJ` e chaves privadas no diff: só marcadores gerados por `secrets` em tempo de execução, nomes de variáveis de teste e a `TEST_DATABASE_URL` local sem senha nos relatórios. Nenhuma variável de ambiente nova. |
| R-04 | ✅ | Nenhum payload do contrato muda. `sources.csv` e o manifest são arquivos locais do dataset; o CA-15 garante que os formatos são iguais aos do `qc-ml`. |
| R-05, R-06 | N/A | Sem escrita na API e sem dado simulado. |
| R-07 | ✅ | Conferi trailer e arquivos de cada commit (`git log --format='%h %s%n%(trailers:key=Agent)' origin/main..HEAD` e `git show --stat`). Developer: `3b73f98`, `a680c7c` e `2f10eca` (produção e `edge/tests/` fora de `acceptance/`), `4eba5a6` (README) e `23c6dcf` (dev-report). Tester: `4316fbf`, só `edge/tests/acceptance/test_spec_036.py` e o test-report. Architect: `06e13f4`, só a SPEC. Orquestrador: `38698a2`, `463f4f0`, `6020c0c`, `5319f71` e `b43b03e`, só status em `docs/plan.md` e nas SPECs. O merge `5319f71` (`git show --cc`) só resolve o conflito em `docs/plan.md`, sem mudança escondida. Todos os commits têm `Agent:`. |
| R-08 | ✅ | SPEC `Ready` aprovada pelo humano em 2026-10-23. Reaprovação ADR-019 conferida acima. |
| R-11 | ✅ (indireto) | `item_id` externo `X…-NNNN` separado do da dupla; a cobertura ignora os externos; nenhuma mudança em split ou métricas. |
| R-12 | ✅ | Só `edge/` muda; `api/` e `dashboard/` intocados. |
| R-13 | ✅ | Autor único: `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`. Conventional Commits. Nenhuma empresa citada. |
| R-14 | ✅ | `--privacy-checked` obrigatório antes de qualquer leitura. Os bytes recebidos nunca vão para `DATASET_DIR`: só a saída reencodada, conferida por `jpeg_private_findings`, `has_exif_rotation` e `load_image`. Conferi à parte, com um script fora do repositório, que o perfil ICC não passa para a saída (JPEG e PNG) e que a orientação EXIF de um PNG (`eXIf`) é aplicada pelo `load_image`, sem sobrar metadado. As entradas só são lidas (`O_NOFOLLOW`, `O_NONBLOCK`, nunca escritas). A saída e os logs nunca têm valor de célula, caminho absoluto nem EXIF, salvo o caso de DEBUG do RV-04. Os testes usam só imagens geradas pelo Pillow. |

### 3. Corretude

Casos que conferi no código, além dos testados:

- **`file` absoluto:** o `os.path.join` descartaria a pasta de entrada, mas a barra inicial gera um componente vazio, recusado antes (`invalid_file`).
- **Link simbólico:** é recusado no último componente pelo `lstat`. Num componente de diretório que sai da pasta de entrada, é recusado pelo `realpath`. Na fase 2, o `O_NOFOLLOW` sobre o `realpath` guardado fecha a troca por link depois da validação.
- **Arquivo esparso de 40 MiB + 1:** é recusado pelo `lstat`, sem leitura. A leitura é limitada a `IMPORT_MAX_BYTES + 1` mesmo se o arquivo crescer.
- **FIFO:** com `O_NONBLOCK`, nunca bloqueia (teste do tester com prazo).
- **Retomada com exclusão e colisão de `image_path` já excluído:** reconferida contra o manifest sob o lock (CA-07).
- **Concorrência com a rota de coleta:** o mesmo `flock`, bloqueante e por linha. O `DatasetWriter` relê o manifest sob o lock em cada coleta, sem cache, então uma linha gravada pelo importador entre duas coletas é vista. O teste exploratório de concorrência passa. Ver o RV-02 para duas importações simultâneas.
- **Rollback:** a falha no passo 5 desfaz a imagem; no passo 6, desfaz o manifest e a imagem; um arquivo criado nesta chamada é apagado, e não truncado. O `BaseException` cobre `KeyboardInterrupt`. Ver o RV-01 para os diretórios vazios.
- **Datas:** `clock()` convertido para UTC; `captured_at` e o nome com `Z`.
- **Nada de `except Exception: pass`.** Os erros de E/S são logados com `strerror`.

### 4. Testes

- Test-report PASS e cobertura de todos os CAs automatizáveis. Conferi a correspondência de cada `test_caNN_*` com o texto do CA:
  - CA-04 com 24 casos parametrizados mais 2, cada um com a linha exata e o snapshot de `DATASET_DIR` em nomes e bytes;
  - CA-09 com o espião em `os.write` que confirma que foi acionado;
  - CA-10 com os dois `umask`;
  - CA-11 com `socket.socket` substituído e a varredura real.
- Os testes não são tautológicos: o sistema de arquivos é real em `tmp_path`, e só as fronteiras da SPEC §6 são simuladas. Nenhum depende de rede externa (o console do CA-13 usa `httpx.ASGITransport`).
- Nenhum ajuste em testes de aceite de SPECs anteriores; o único arquivo de aceite no diff é o `test_spec_036.py`.
- Nenhum teste roda a suíte em subprocesso. O único subprocesso é `python -m qc_edge.importer`.
- Nenhuma credencial literal em URL.
- Cobertura dos módulos alterados, medida por mim com os testes do autor e os de aceite: `importer.py` 95%, `collect.py` 90%, `jpeg.py` 85%. A RNF-09 não inclui esses módulos.
- Rodei:

```text
$ uv run ruff check .                          -> All checks passed!
$ uv run ruff format --check .                 -> 234 files already formatted
$ uv run pytest -q edge/tests/test_importer.py edge/tests/acceptance/test_spec_036.py \
    edge/tests/test_jpeg.py edge/tests/test_collect.py edge/tests/test_collect_route.py
536 passed
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
6327 passed, 54 skipped, 1 warning in 455.54s (os 54 skips de sempre: Docker, extra `train` e modelo real)
```

### 5. Qualidade

- `ruff check` e `ruff format --check` limpos; type hints nas funções públicas; nenhum `print` (a saída usa `out.write` e `sys.stderr.write`, como a SPEC pede para o stdout e o stderr).
- Sem duplicação: o mínimo de 256 vem do `qc_preprocess`, e os gravadores, o lock e os filtros de texto são os da coleta. O `ALLOWED_LICENSES` e o `SOURCES_COLUMNS` são cópias deliberadas, porque o `qc_edge` não importa o `qc_ml`, e o CA-15 garante a igualdade.
- README atualizado (§4.8): todos os itens pedidos, inclusive o aviso de fórmulas de planilha do §7.

## Pontos positivos

- A fase 1 é de fato "tudo ou nada": toda a validação, inclusive o hash de cada entrada e os cabeçalhos do dataset, acontece antes de criar qualquer coisa. O `--dry-run` reaproveita o mesmo caminho até a normalização.
- A releitura com o hash conferido (decisão 5) fecha a janela entre as duas fases, sem guardar os arquivos em memória.
- A extração dos gravadores do `collect.py` (`append_csv_row` e `rollback_append`) deixou a coleta e a importação com o mesmo rollback, sem mudar a rota.
- Os testes exploratórios do tester cobrem muito além dos CAs: as 8 orientações, bombas de descompressão, FIFO, links por diretório, bidi nos nomes, concorrência com a rota de coleta e retomada depois de `EIO`.

## SPEC_ISSUE (se houver)

Nenhum. As duas reaprovações delegadas (SPEC_ISSUE-01 e 02, `06e13f4` e `6020c0c`) estão dentro dos limites do ADR-019.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
