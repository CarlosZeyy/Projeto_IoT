# SPEC-010 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-010](../../docs/specs/SPEC-010-modo-coleta.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `c2f8ea3` (código da r1: `e9d69f8`, `f36508e`, `277159e`; branch `spec/SPEC-010-modo-coleta`) |
| **Veredicto** | **PASS** (CAs automatizáveis); o CA-17 é manual e fica **pendente para a dupla** (ver abaixo) |

Escrevi os testes a partir da SPEC (caixa-preta), antes de ler a implementação. Arquivo: `edge/tests/acceptance/test_spec_010.py`, com **125 testes**: 52 ligados a CAs e 73 exploratórios (`test_extra_*`).

Regras seguidas (`reviews/checklist.md` e `docs/architecture.md` §10):

- o token de sessão é gerado em tempo de execução (`secrets.token_urlsafe`), sem credencial literal em URL, conninfo ou header;
- as imagens são geradas em memória (Pillow) e `DATASET_DIR` fica sempre em `tmp_path`. A fixture também faz `chdir` para um diretório temporário, então nenhuma escrita relativa cai no repositório;
- nenhum teste roda o pytest em subprocesso;
- as únicas fronteiras simuladas são o relógio (`clock` de `create_app`), a rede (para provar a R-02) e os dublês de inferenciador e sink que as interfaces da SPEC-007 aceitam.

## Cobertura dos critérios de aceite

Prefixo dos testes: `edge/tests/acceptance/test_spec_010.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_valid_jpeg_creates_image_and_manifest_line`: resposta exata; arquivo com os bytes recebidos; manifest sem BOM, sem `\r`, com o cabeçalho exato; linha completa, `captured_at=2026-10-22T14:15:03Z` e `capture_device` com os 60 primeiros caracteres de um User-Agent de 80 | ✅ |
| CA-02 | `test_ca02_other_goes_to_underscore_with_empty_grade[grade-empty, grade-absent]` | ✅ |
| CA-03 | `test_ca03_grade_rules_are_422_and_nothing_written[other-with-good, screw-without-grade, screw-empty-grade, grade-excellent]`: 422, nenhum caminho criado em `tmp_path` e `DATASET_DIR` nem é criado | ✅ |
| CA-04 | `test_ca04_prefix_and_type_rules_are_422[N-as-screw, T-as-screw, T-as-nut, T-as-other, unknown-type, S-as-nut, O-as-screw, S-as-other]` | ✅ |
| CA-05 | `test_ca05_invalid_fields_are_422_and_nothing_outside_dataset_dir` (10 casos: `S-12`, `s-012`, `S-0123`, `../S-001`, `angle` 5, -1 e `x`, `labeler=c`, `notes` com 201 caracteres e com `\n`); `test_ca05_trailing_newline_is_422_and_dataset_dir_stays_empty` (`"S-012\n"`, `"2\n"`, `"screw\n"`: `DATASET_DIR` existente e vazio continua vazio). Nos dois testes, a árvore inteira de `tmp_path` fica igual | ✅ |
| CA-06 | `test_ca06_item_registered_with_another_type_is_409`: detalhe exato, nenhuma imagem e bytes do manifest iguais | ✅ |
| CA-07 | `test_ca07_same_item_new_grade_is_allowed`: `item_images=2` e grades `fair`, `poor` | ✅ |
| CA-08 | `test_ca08_identical_requests_in_the_same_second`: 200 e depois 409 com o detalhe exato; 1 linha e 1 imagem; a primeira imagem não é sobrescrita | ✅ |
| CA-09 | `test_ca09_two_concurrent_requests_give_two_valid_lines`: 2 threads com barreira (`S-001`, `N-001`); um único cabeçalho, 3 linhas e as 9 colunas com os valores enviados | ✅ |
| CA-10 | `test_ca10_notes_with_quotes_and_comma_round_trip`: `DictReader` devolve o texto idêntico e a linha bruta termina em `"tem ""aspas"", vírgula"` | ✅ |
| CA-11 | `test_ca11_header_mismatch_is_500_and_nothing_changes[reordered, missing-column, extra-column, other-csv, bom]` | ✅ |
| CA-12 | `test_ca12_collect_without_model_never_reaches_the_sink` (`inferencer=None`, nada em `captures/`); `test_ca12_collect_never_calls_the_stub_inferencer_nor_the_sink` (`StubInferencer.calls == 0`, sink vazio) | ✅ |
| CA-13 | `test_ca13_dataset_files_are_never_served`: as 3 URLs dão 404, com e sem token | ✅ |
| CA-14 | `test_ca14_without_valid_token_is_401[missing, wrong]`, `test_ca14_image_of_3_mib_plus_one_byte_is_413` (3 145 729 bytes), `test_ca14_text_renamed_to_jpg_is_415`, `test_ca14_jpeg_above_the_route_pixel_limit_is_415` (2001×2000); em todos, nenhuma imagem e nenhum manifest | ✅ |
| CA-15 | `test_ca15_compute_coverage_counts_images_and_items` (11 células com as chaves, contagens e metas exatas); `test_ca15_console_shows_the_coverage_table` (loopback, URL base `http://127.0.0.1:<EDGE_PORT>`, `<table id="coverage">`, `130/120`, `9/12`, `40/120`, `10/150`, `10/30` e total 180); `test_ca15_missing_manifest_is_an_empty_table` | ✅ |
| CA-16 | `test_ca16_capture_page_has_collect_fields_and_enabled_mode`: os 6 campos; opção `collect` sem `disabled`; rótulos parafuso, porca e outro; os 5 graus de `GRADE_LABELS_PT`; "Sem pessoas no quadro" | ✅ |
| CA-17 | manual: **pendente para a dupla**. Revisei o roteiro e simulei a parte possível sem celular (abaixo) | ⏳ |
| CA-18 | `test_ca18_exact_modes_whatever_the_umask[umask-022, umask-077]`: umask restaurado em `finally`, `DATASET_DIR` inexistente, JPEG `S-012` e PNG `O-004`; `0700` nos 6 diretórios e `0600` nas 2 imagens, no `manifest.csv` e no `manifest.csv.lock`; o PNG foi gravado como JPEG | ✅ |

## Ajustes em testes de aceite de SPECs anteriores

Feitos em commit próprio (`5bfc4fb`, `test: adjust SPEC-007 acceptance tests superseded by SPEC-010`, `Agent: tester`), exatamente os três da §3.1 da SPEC-010 (`docs/architecture.md` §10, "Testes de aceite de SPECs anteriores"). Nenhum `test_caNN_` foi removido, e nenhuma outra linha de `test_spec_007.py` mudou (`git show 5bfc4fb --stat`: 6 inserções e 4 remoções).

| Arquivo | Teste | Asserção antes → depois | Requisito da SPEC-010 que motivou |
|---|---|---|---|
| `edge/tests/acceptance/test_spec_007.py` | `test_ca15_capture_page` | `assert collect and all("disabled" in a for a in collect)` → `assert collect` (a opção `collect` continua obrigatória; as demais asserções não mudam) | CA-16 (coleta habilitado); §3.1, ajuste 1 |
| `edge/tests/acceptance/test_spec_007.py` | `test_extra_collect_mode_is_501` → `test_extra_collect_mode_without_collect_fields_is_422` | `assert r.status_code == 501` → `assert r.status_code == 422`. O nome do teste mudou junto, porque descrevia o 501. `stub.calls == 0` e `edge.captures() == []` foram mantidos. Teste extra, sem CA da SPEC-007 | §3.1 (substitui o 501) e §4.1 (campos de coleta ausentes → 422); §3.1, ajuste 2 |
| `edge/tests/acceptance/test_spec_007.py` | `test_ca13_console_from_loopback` | `assert page.count("parafuso") == 10` → as linhas `<tr class="inspection" …>` do console são exatamente 10, e a soma de "parafuso" dentro delas é 10. As demais asserções não mudam | §4.4 (a tabela de cobertura acrescenta 5 linhas "parafuso"); §3.1, ajuste 3 |

## Suíte completa

```text
$ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
1936 passed, 1 warning in 265.85s (0:04:25)

$ uv run pytest -q          # sem TEST_DATABASE_URL
1493 passed, 443 skipped, 1 warning in 154.47s (0:02:34)

$ uv run pytest -q edge/tests/acceptance/test_spec_010.py
125 passed, 1 warning in 4.46s

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
108 files already formatted
```

O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia. As execuções não criaram `ml/data/` nem outro arquivo no repositório (`git status` limpo, salvo os arquivos deste commit).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_extra_*` e passam.

- **Campos que viram caminho:** 32 variações dão 422, sem tocar o disco:
  - `item_id`:
    - `S-٠١٢` (dígitos arábicos, que um `\d` sem `re.ASCII` aceitaria; a implementação usa `re.ASCII`);
    - espaço antes ou depois;
    - hífen Unicode;
    - `S-012/`;
    - vazio ou ausente;
  - `angle`: `" 2"`, `"02"`, `"²"`, `"٢"`, `"2.0"`, vazio ou ausente;
  - `object_type`: `Screw`, `" screw"`, vazio;
  - `grade`: `Fair`, `"fair\n"`, `" fair"`;
  - `labeler`: `A`, `"a\n"`, vazio ou ausente;
  - `notes` com `\t`, `\r`, NUL, DEL, ESC ou C1 (`\x85`);
  - `mode`: `"collect\n"`, `Collect`.
- **Campo `item_id` repetido** no multipart (`S-012` e `../../S-001`): a resposta é 422 (o Starlette usa o último valor) e nenhum caminho com `S-001` é criado.
- **`notes` válidas gravadas sem alteração:** 200 caracteres ASCII, 200 `ç` (o limite é em caracteres, não em bytes), vazia, ausente, com espaços nas pontas, `=SUM(A1)`, emoji e separadores.
- **`lot_id` inválido no modo coleta:** é ignorado (200) e não vai para o manifest.
- **User-Agent:** ausente → `capture_device` vazio; com vírgula e aspas → o round-trip pelo CSV é exato.
- **Relógio fora de UTC:** `-03:00`, com microssegundos → o nome do arquivo e `captured_at` saem em UTC, sem fração.
- **PNG:** reencodado como JPEG, com as mesmas dimensões.
- **Limites:** imagem de exatamente 3 145 728 bytes → 200.
- **Arquivos temporários:** nenhum sobra depois de um sucesso seguido de um 409.
- **Manifest editado à mão:**
  - sem a quebra de linha final → a nova linha não se funde com a anterior;
  - só com o cabeçalho → 200 e `item_images=1`;
  - arquivo vazio → 500 `manifest header mismatch` e nada muda (o arquivo não tem o cabeçalho esperado, o que é coerente com o §4.2, passo 1);
  - cabeçalho com CRLF → aceito, e as linhas continuam legíveis;
  - linhas que não são UTF-8 → 500 (`manifest unreadable`, detalhe definido pelo autor) e nada muda.
- **Falha no passo 5 do §4.2:** com o `manifest.csv` em `0400`, a resposta é 500 só com `detail`, sem stack trace. A imagem já gravada é apagada e o manifest fica intacto.
- **Symlink no lugar do `manifest.csv`:** apontando para fora de `DATASET_DIR`, o alvo não é alterado (500) e nenhuma imagem fica.
- **`DATASET_DIR` que é um arquivo:** `EdgeSettings()` recusa e cita a variável.
- **Padrão de `DATASET_DIR`:** `ml/data`. `.env.example` e `edge/README.md` documentam a variável.
- **Concorrência:**
  - 24 threads, distribuídas entre **dois apps** sobre o mesmo `DATASET_DIR` (dois `threading.Lock` diferentes, então só o `flock` serializa): 24 linhas íntegras, 1 cabeçalho, 24 imagens;
  - 6 requisições idênticas e simultâneas nos dois apps: exatamente um 200 e cinco 409, com 1 linha e 1 imagem.
- **Sensibilidade dos testes:** com um plugin temporário fora do repositório, sem alterar código de produção:
  - anular o `fcntl.flock` faz os dois testes de concorrência entre apps falharem;
  - anular o `chmod`/`fchmod` faz falhar `test_extra_exact_modes_with_extreme_umasks[umask-277]`.
- **Permissões:**
  - umask `000` e `277` → modos exatos `0700`/`0600`;
  - `DATASET_DIR` (`0755`) e `manifest.csv` (`0644`) que já existiam ficam como estavam, e `raw/` criado pela coleta fica `0700`.
- **Limitador compartilhado:** com `max_concurrent_decodes=1` e o slot ocupado por uma inspeção bloqueada, a coleta recebe 503 `server busy` e nada é gravado. Depois de liberar o slot, a coleta dá 200.
- **R-02:**
  - com `socket.connect`, `connect_ex`, `create_connection` e `httpx.HTTPTransport.handle_request` trocados por funções que falham, 3 coletas dão 200 e nenhuma tentativa de conexão é registrada;
  - nenhuma rota serve o dataset: `/static/../manifest.csv`, `/static/%2e%2e/%2e%2e/manifest.csv`, `/static/..%2f..%2fmanifest.csv`, `/raw/`, `/dataset/manifest.csv` e `/data/manifest.csv` dão 404.
- **Console:**
  - destaca só a célula que atingiu as duas metas (120/120 e 12/12); 130/120 com 11 peças e 119/120 não são destacadas;
  - um manifest ilegível não derruba o console (200 com a tabela);
  - linhas com tipo ou grau desconhecido não entram na cobertura.
- **Modo inspeção ao lado do coleta:** continua chamando o inferenciador e o sink uma vez cada e não escreve no dataset.
- **Página:** `capture.js` tem 196 linhas (limite 200) e contém "Salvo:" e `localStorage`. "Peça completa — troque o item_id" está na página.

### Observações (não são bugs)

- **O-01 (CA-18):** com umask `022` ou `077`, um `mkdir(mode=0o700)` e um `mkstemp` já dão `0700`/`0600` sem `chmod`. Por isso, o CA-18, como escrito, não detecta um `chmod` esquecido nessa implementação. O teste extra com umask `0o277` cobre essa lacuna. Sugestão para o architect, sem efeito nesta rodada: incluir um umask que tire bits do dono numa revisão futura do CA.
- **O-02 (R-14, para o security-devops):** um JPEG enviado fora da página é salvo "como chegou" (§4.2, passo 4), com o EXIF original (GPS, por exemplo). A página reencoda via canvas e descarta o EXIF. É o comportamento que a SPEC pede, igual ao da SPEC-007.
- **O-03:** o relógio da coleta não é conferido contra o futuro (o do modo inspeção é, pelo contrato). A SPEC não pede essa conferência.
- **O-04:** a espera pelo slot do limitador continua no threadpool, como a SPEC-010 §7 prevê enquanto a SPEC-025 não estiver `Done`.

## CA-17 (manual): pendente para a dupla

Revisei a seção "Teste manual do modo coleta (CA-17 da SPEC-010)" do `edge/README.md`. O roteiro é executável e cobre os 6 passos do CA:

| Passo do CA-17 | Passo do README |
|---|---|
| 1. subir sem modelo | 1 (`DATASET_DIR` descartável, sem `--stub-model`, sem `MODEL_DIR`, console com a tabela zerada) |
| 2. "coleta", `S-001`, parafuso, perfeito, `a`, ângulo 0 | 2 |
| 3. 5 fotos, ângulo 0→4, "Peça completa" | 3 (inclui o cartão "Salvo: …") |
| 4. recarregar e conferir os campos | 4 (o modo também persiste) |
| 5. "outro" → grau desabilitado | 5 |
| 6. 5 arquivos, 5 linhas, `5/120` e `1/12` | 6 (`ls -l`, `wc -l`, que dá 6 com o cabeçalho, `stat` dos modos e o console) e 7 (limpeza) |

**Simulação sem celular (feita):** subi o `qc-edge` real, sem modelo, em `127.0.0.1:18765`, com `DATASET_DIR` num diretório temporário, e enviei 5 coletas por `curl` (`S-001`, `screw`, `perfect`, `a`, ângulos 0 a 4). Resultado:

- 5 respostas 200, com `item_images` de 1 a 5;
- 5 arquivos `-rw-------` em `raw/screw/perfect/`;
- `manifest.csv` com 6 linhas;
- `stat`: `700` em `DATASET_DIR`, `raw`, `raw/screw` e `raw/screw/perfect`, e `600` em `manifest.csv` e `manifest.csv.lock`;
- console com `<tr><td>parafuso</td><td>perfeito</td><td>5/120</td><td>1/12</td></tr>`;
- modo inspeção sem modelo → 503;
- o token não aparece no log do servidor.

A simulação não substitui o CA-17: ela não exercita a página no celular (`localStorage`, avanço do ângulo, "Peça completa", grau desabilitado).

**O que a dupla deve registrar** (aqui ou numa rodada seguinte):

| Item | Celular |
|---|---|
| Modelo do aparelho e navegador (versão) | _a preencher_ |
| Ângulo avançou 0→1→2→3→4 e voltou a 0, com "Peça completa — troque o item_id" | _a preencher_ |
| Cartão "Salvo: S-001, ângulo n (fotos desta peça: n+1)" | _a preencher_ |
| Campos e modo mantidos depois de recarregar | _a preencher_ |
| "outro" → grau desabilitado e vazio | _a preencher_ |
| Saída de `ls -l`, `wc -l` e `stat` do passo 6 | _a preencher_ |
| Console: parafuso/perfeito com `5/120` e `1/12` | _a preencher_ |

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-01 do dev-report foi resolvido na §3.1 (commit `17539bf`), e os três ajustes estão na tabela acima.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório. Os ajustes em `edge/tests/acceptance/test_spec_007.py` são os três autorizados pela §3.1 da SPEC-010 e estão listados acima.
