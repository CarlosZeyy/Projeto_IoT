# SPEC-036 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-036](../../docs/specs/SPEC-036-importacao-de-fotos.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `6020c0c` |
| **Veredicto** | **PASS** (CAs automatizáveis); o CA-17 é manual e fica **pendente para a dupla** (ver abaixo) |

Os testes foram escritos a partir dos critérios de aceite (caixa-preta), antes da leitura da implementação, sobre o texto atual da SPEC (CA-15 com `qc_ml.data.SOURCE_COLUMNS` e a tabela "Coluna mostrada em `plan line <n>: <code> (<coluna>)`" do §4.2, corrigidos no commit 06e13f4 e reaprovados sob o ADR-019 no 6020c0c). Arquivo: `edge/tests/acceptance/test_spec_036.py`, com **141 testes**: 51 itens de critério de aceite (`test_caNN_*`, contando os casos parametrizados) e 90 exploratórios (`test_extra_*`).

- Todas as imagens são geradas no teste pelo Pillow (nunca fotos reais, R-14); os marcadores vêm de `secrets` em tempo de execução; nada de `~/partqc-entrada/` foi lido ou usado.
- As únicas fronteiras simuladas são as da SPEC §6: relógio, `sleep` (espião), `socket.socket` (CA-11) e a escrita de arquivo nos casos de erro (CA-09: espião em `os.write` que reconhece o alvo por `/proc/self/fd/<fd>`, como o dev report indica no item 11). O sistema de arquivos é real, sempre sob `tmp_path`, com o `cwd` também em `tmp_path`.
- As linhas `plan line <n>: <code> (<coluna>)` são procuradas em `err.splitlines()`, sem exigir que sejam as únicas (dev report, decisão 4).

## Cobertura dos critérios de aceite

Prefixo dos testes: `edge/tests/acceptance/test_spec_036.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_phone_photo_is_rotated_reduced_and_clean` (foto de celular 4000×3000 gravada com `ROTATE_90`, `Orientation=6` e GPS; confere o caminho, o total, 960×1280, `jpeg_private_findings` vazio, `has_exif_rotation` falso, `getexif()` vazio, sem `Exif\0\0`, canto vermelho, diferença média ≤ 4 por canal contra `load_image(original).resize(..., LANCZOS)`, manifest e `sources.csv` com o SHA-256 do arquivo de entrada) | ✅ |
| CA-02 | `test_ca02_motion_photo_trailer_is_dropped` (confere antes que `load_image` recusa o original com `JPEG scans`) | ✅ |
| CA-03 | `test_ca03_external_png_is_imported` (PNG RGBA 2048×1024 → JPEG RGB 1280×640) | ✅ |
| CA-04 | `test_ca04_invalid_plan_is_refused_and_nothing_written` (24 casos, um por caso do CA, cada um com a linha exata `plan line 2: <code> (<coluna>)` ou `plan line 3: ...` nos dois duplicados, e `DATASET_DIR` igual em nomes e bytes), `test_ca04_plan_without_notes_column` (`plan line 1: missing_column (notes)`), `test_ca04_bidi_source_ref_is_never_echoed` (marcador + U+202E ausente do stdout, do stderr e do log) | ✅ |
| CA-05 | `test_ca05a_missing_privacy_checked` … `test_ca05g_sources_header_mismatch` (um teste por letra; todos saem com 2 e nada é gravado) | ✅ |
| CA-06 | `test_ca06_rejected_images_do_not_stop_the_import` (`failed x.heic: unsupported image`, `failed pequena.jpg: image too small`, 2 `imported`, `imported 2, skipped 0, failed 2`, 2 linhas em cada CSV, nenhum temporário) | ✅ |
| CA-07 | `test_ca07_rerun_skips_and_excluded_image_is_imported_again` | ✅ |
| CA-08 | `test_ca08_same_name_waits_one_second`, `test_ca08_clock_that_never_moves` | ✅ |
| CA-09 | `test_ca09_sources_write_failure_rolls_back`, `test_ca09_manifest_write_failure_removes_the_image` (o espião confirma que foi acionado) | ✅ |
| CA-10 | `test_ca10_exact_modes_whatever_the_umask[umask022]`, `[umask277]`, `test_ca10_existing_dataset_dir_keeps_its_mode` | ✅ |
| CA-11 | `test_ca11_no_network_inputs_untouched_and_privacy_clean` (três execuções sem `socket.socket`; `privacy` termina com `checked 3 images, 0 with private data`; bytes e `st_mtime_ns` das entradas iguais) | ✅ |
| CA-12 | `test_ca12_dry_run_creates_nothing` | ✅ |
| CA-13 | `test_ca13_coverage_ignores_external_images` (`compute_coverage`, `count_external_images` e o console por loopback) | ✅ |
| CA-14 | `test_ca14_collect_route_refuses_an_external_item_id` (422; nem imagem, nem linha) | ✅ |
| CA-15 | `test_ca15_formats_equal_to_qc_ml` (as três constantes e `qc_ml.data.load_manifest(<D>, external_sources=<registro>)` com `contributor` e `external`) | ✅ |
| CA-16 | `test_ca16_readme_section` (o trecho é isolado ignorando `#` dentro de blocos de código) | ✅ |
| CA-17 | manual: **pendente para a dupla** (ver "CA-17 (manual)") | ⏳ |

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
234 files already formatted
$ uv run pytest -q edge/tests/acceptance/test_spec_036.py
141 passed
$ uv run pytest -q                       # sem banco
5657 passed, 724 skipped, 1 warning in 360.80s (0:06:00)
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
6327 passed, 54 skipped, 1 warning in 465.32s (0:07:45)
```

- 6327 = os 6186 do dev report + os 141 deste arquivo; sem banco, 5657 = 5516 + 141. Os 54 skips são os de sempre (30 de Docker sem `PARTQC_DOCKER_TESTS=1`, 21 sem torch e 3 do modelo real, que não está no Git); o aviso (`httpx` com o `TestClient` do Starlette) não vem desta SPEC.
- Os testes de aceite das SPECs anteriores do `edge/` (007, 008, 009, 010, 025 e 030) passam sem alteração. **Nenhum ajuste** em testes de aceite antigos (`docs/architecture.md` §10), como a §3.1 previa.
- A suíte rodou sem o extra `train` (estado do CI).

## Bugs encontrados

Nenhum. Nenhum CA falhou e nenhum teste exploratório mostrou comportamento contrário à SPEC.

## Observações (não são bugs; para o reviewer e o security-devops)

| ID | Observação | Evidência |
|---|---|---|
| O-01 | Um **hard link** na pasta de entrada para um arquivo de fora dela é aceito: é um arquivo regular cujo `realpath` fica dentro de `--inbox`, e a SPEC só proíbe link simbólico (§4.2). O arquivo de fora não é alterado, e só a imagem normalizada entra no dataset. | `test_extra_hardlink_from_outside_is_a_regular_file` |
| O-02 | Células com cara de fórmula de planilha (`=HYPERLINK(...)` em `notes`, `@SUM(...)` em `source_ref`) são gravadas sem alteração, como a SPEC-010 manda para `notes`. O README traz o aviso pedido no §7 (exportar como CSV UTF-8 e conferir as células que começam com `=`, `+`, `-` ou `@`). | `test_extra_formula_like_cells_are_stored_verbatim`; `edge/README.md`, linha 170 |
| O-03 | Depois de um rollback (CA-09), pode sobrar um **diretório vazio** `raw/<tipo>/<grau>/` criado para a imagem desfeita. O CA-09 exige só "nenhuma imagem nem temporário", então o teste compara os arquivos de `raw/`, não os diretórios. A varredura de privacidade e o `validate` não se importam com diretório vazio. | `test_ca09_sources_write_failure_rolls_back` (primeira versão do teste, que comparava também os diretórios, falhou só por `raw/screw/fair`) |
| O-04 | O `file` pode ter caracteres de controle e bidi (a SPEC só proíbe `\`, NUL, componentes vazios, `.` e `..`). O eco passa por `printable_path`: ESC, U+202E, DEL, CR e `\n` nunca aparecem crus no stdout nem no stderr, e cada linha do plano continua sendo uma linha da saída. | `test_extra_control_and_bidi_in_file_names_are_never_echoed_raw` (5 casos) |
| O-05 | O log de DEBUG do próprio Pillow (`PIL.TiffImagePlugin`) mostra os valores das tags EXIF (por exemplo, `Make`) quando o logger raiz está em DEBUG. A CLI configura o logging em INFO, e o teste com o processo real (`python -m qc_edge.importer`) confirma que nada do EXIF nem caminho absoluto chega ao stdout ou ao stderr. Só aparece se alguém rodar a CLI dentro de um processo com o logger raiz em DEBUG. Os logs do `qc_edge` nunca têm valor de EXIF. | `test_extra_real_process_stderr_has_no_metadata`, `test_extra_no_metadata_in_the_output_or_on_disk` |

## Testes exploratórios (além dos critérios)

Todos em `test_spec_036.py` (`test_extra_*`), passando, salvo indicação.

### Imagens e normalização

| Caso | Resultado |
|---|---|
| Os 8 valores de `Orientation` (600×400 com bloco vermelho, q=95) | `load_image(<gravado>)` igual a `load_image(<original>)` (que aplica o `exif_transpose`) no tamanho e com diferença média ≤ 4 por canal; `exif_orientation` devolve o valor e `has_exif_rotation == (valor in 2..8)` |
| `Orientation` ausente, 0, 9 e 300 | `exif_orientation == 1`, `has_exif_rotation` falso |
| Redução: 2000×1001, 1001×2000, 1281×1000, 1280×960, 1280×256, 2560×513 | 1280×641, 641×1280, 1280×999, sem mudança, sem mudança, 1280×257 (512,5 arredonda para cima, aritmética inteira) |
| 2560×510 (lado menor final 255) | `failed <file>: image too small`, código 1, nada gravado |
| SOF de JPEG adulterado para 60000×60000; IHDR de PNG para 50000×50000 (bombas de descompressão) | `failed <file>: unsupported image`; a outra linha é importada; código 1; sem traceback |
| JPEG truncado, lixo começando com `FF D8 FF`, proporção 11:1, GIF renomeado, arquivo vazio | a linha falha com um dos motivos fixos do §4.3; a outra é importada; código 1 |
| Exatamente 40 MiB (JPEG válido + zeros esparsos depois do EOI) | importado (código 0); o arquivo gravado tem menos de 1 MiB e nenhum achado |
| JPEG em escala de cinza e CMYK; PNG `I;16`, `P` com transparência, `LA`, `1` e `RGB` | importados, JPEG com o tamanho original, modo `RGB` ou `L` |
| `other` sem grau | `raw/other/_/O-501__2__...jpg`, `grade` vazio no manifest |
| Foto de 6400×6000 com `Orientation=8` (sonda manual em scratch, fora do Git) | importada em 0,65 s, 1200×1280, pico de memória de 344 MB |

### Plano

| Caso | Resultado |
|---|---|
| `file` = `./ok.jpg`, `sub//ok.jpg`, `sub\ok.jpg`, vazio, 256 caracteres, `sub/../ok.jpg`, `/` | `plan line 2: invalid_file (file)`; 255 caracteres é aceito |
| Componente de diretório que é link simbólico para fora; link simbólico para um arquivo dentro da própria pasta; diretório; FIFO | `invalid_file`; a FIFO não bloqueia (thread com prazo de 20 s) |
| `item_id` com dígitos de largura total (`S-５０１`); `angle` `٢`, espaço antes do `2`, `5`; `contributor` `c٠١`, `C01`; `labeler=A`; `origin=capture`; `object_type=Screw`; grau vazio; grau `excellent`; `notes` com 201 caracteres, TAB ou U+202E; `source_id` numa `contributor` | o código e a coluna da tabela do §4.2 (`invalid_item_id`, `invalid_angle`, `invalid_contributor`, `invalid_labeler`, `invalid_origin`, `invalid_object_type`, `missing_grade`, `invalid_grade`, `invalid_notes`, `source_fields_mismatch (source_id)`) |
| Externa com `source_id` `AB` ou vazio, `source_ref` com 201 caracteres ou com U+00AD, `contributor` preenchido | `invalid_source_id`, `invalid_source_ref`, `invalid_contributor`; `source_ref` com 200 caracteres é aceito |
| Mesmo `item_id` com dois `object_type` no plano | `item_type_conflict (item_id)` |
| Vários problemas em linhas diferentes | todos listados, um por linha, na ordem do plano |
| BOM; UTF-16; byte inválido em UTF-8; campo a mais; campo a menos; colunas fora de ordem; coluna a mais; 5.001 linhas; plano acima de 5 MiB; NUL no `file` | `missing_column (file)`; `unreadable_csv (-)`; `unreadable_csv (-)`; `malformed_row (-)` (×2); `missing_column (-)` (×2); `too_many_rows (-)`; `unreadable_csv (-)`; `invalid_file (file)`. Sempre código 2 e `DATASET_DIR` inexistente |
| 5.000 linhas | não é `too_many_rows` (só os `duplicate_file`, até `plan line 5001`) |
| Plano vazio (só o cabeçalho) | código 0, `imported 0, skipped 0, failed 0` |

### Argumentos, caminhos, eco e permissões

| Caso | Resultado |
|---|---|
| Argumento solto com marcador; `--x <marcador>`; `--<marcador><marcador>` (fora do formato de nome); `--Token=<marcador>`; `--dry-run=<marcador>` | código 2; o marcador não aparece no stdout, no stderr nem no log. Um nome de opção desconhecido **no formato permitido** (`--[a-z][a-z0-9-]{0,30}`) é ecoado, como manda a SPEC-025 §4.5 |
| `--inbox` por link simbólico para dentro do dataset; `--dataset-dir` por link simbólico para a pasta de entrada | `inbox must be outside the dataset` (o `realpath` é comparado) |
| `--inbox` inexistente; `exclusions.csv` com outro cabeçalho | código 2 e nada gravado |
| Saída com linha recusada, linha importada e externa | nenhum caminho absoluto e nenhum marcador de `notes` no stdout, no stderr ou no log; `source_id` e `source_ref` fora do stdout; o mesmo (caminho e marcador) com `file` absoluto no plano |
| Escrita fora de `DATASET_DIR` | nenhuma: o resto de `tmp_path` (pasta de entrada, registro, plano, `cwd`) fica igual em nomes e bytes, e o `st_mtime_ns` da pasta de entrada não muda |
| Metadados | nenhum byte de `Make`, `Exif` ou GPS em arquivo nenhum sob `DATASET_DIR`; nada disso na saída nem nos logs do `qc_edge` (ver O-05) |
| `DATASET_DIR` existente com `0o750` e manifest com `0o640` | continuam `0o750` e `0o640`; o `sources.csv` criado tem `0o600` |
| `ENOSPC` na escrita do `sources.csv` sem `sources.csv` anterior | código 1, manifest igual byte a byte, nenhuma imagem |
| `EIO` na linha do manifest da 2ª de 3 linhas | código 1, para na hora; manifest, `sources.csv` e imagens com a mesma contagem; a 3ª linha não é tentada. Nova execução: código 0, as importadas antes aparecem como `already imported` e o resto entra |
| `--dry-run` sobre um dataset existente (linha já importada, linha nova, linha pequena) | `skipped`, `would import`, `failed ...: image too small`, `would import 1, skipped 1, failed 1`, código 1; nomes, bytes e `st_mtime_ns` de tudo sob `DATASET_DIR` iguais |
| Concorrência com a rota de coleta: importação de 5 linhas numa thread e 5 `POST /api/capture` ao mesmo tempo | importação com código 0; coletas 200 (ou 503 por lock ocupado, aceito); manifest com um único cabeçalho e uma linha por imagem existente; as 5 linhas de `sources.csv` apontam para imagens do manifest |
| `python -m qc_edge.importer` num subprocesso sem `--privacy-checked` | código 2 com `missing --privacy-checked`, nada criado |

## CA-17 (manual): pendente para a dupla

O CA-17 exige uma foto real de um conhecido enviada pelo WhatsApp como documento, a checagem humana de privacidade e a abertura do arquivo gravado. Não executei: o tester não usa fotos reais (R-14) e não acessou `~/partqc-entrada/`. A parte automatizável do roteiro (normalização de uma foto de celular com rotação EXIF, `--dry-run` e depois sem ele, `privacy` com `0 with private data` e `qc_ml.data.load_manifest` sem erro) está coberta pelos CA-01, CA-11, CA-12 e CA-15, e a sonda de 6400×6000 com `Orientation=8` acima mostra o tempo e a memória de uma foto grande. A dupla deve registrar, no PR ou numa rodada seguinte deste relatório, o tamanho original e o gravado (sem a foto), como pede o CA.

## SPEC_ISSUE (se houver)

Nenhum. Os SPEC_ISSUE-01 e 02 do dev report já foram corrigidos (06e13f4) e reaprovados sob o ADR-019 (6020c0c). O texto atual dá a linha exata de cada caso do CA-04, e o CA-15 é executável como está escrito.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` (`edge/tests/acceptance/test_spec_036.py`, novo) e este relatório.
