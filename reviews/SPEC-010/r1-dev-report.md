# SPEC-010 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-010](../../docs/specs/SPEC-010-modo-coleta.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-010-modo-coleta` |
| Commits | `e9d69f8` (feat(edge): writer do dataset e cobertura), `f36508e` (feat(edge): rota, página e console do modo coleta), `277159e` (docs(edge): README e `.env.example`), mais o commit deste relatório |

## Resumo

- `edge/src/qc_edge/collect.py` (novo): `CollectRequest.from_fields` valida os campos do §4.1 com `re.fullmatch` e igualdade exata, antes de tocar o disco; `DatasetWriter.write` faz os passos 1 a 5 do §4.2 sob um `threading.Lock` **e** um `fcntl.flock` em `DATASET_DIR/manifest.csv.lock`, com modos exatos `0700`/`0600` (§4.2, item 5); `CoverageCell` e `compute_coverage()` do §4.4.
- `POST /api/capture` com `mode=collect` substitui o 501 da SPEC-007. Ordem: token (401) → tamanho (413) → campos (422) → limitador único (503 `server busy`) → `load_capture_image` (415) → gravação (409/500). Não chama `Inferencer` nem `InspectionSink` e funciona com `inferencer=None`.
- Página `/capture`: "coleta" habilitado, campos de coleta (rótulos PT-BR; os graus vêm de `qc_contracts.GRADE_LABELS_PT`), persistência em `localStorage`, ângulo que avança 0→4 e volta a 0 com "Peça completa — troque o item_id", cartão "Salvo: …" e o lembrete "Sem pessoas no quadro". `capture.js` tem 196 linhas (limite 200).
- Console (`GET /`): tabela `<table id="coverage">` com "imagens/meta" e "peças/meta", destaque das células completas e total de imagens; manifest ausente → tabela zerada.
- `EdgeSettings.DATASET_DIR` com padrão `ml/data` (não é criado na subida). `.env.example` e `edge/README.md` (seção "Modo coleta" e roteiro do CA-17) atualizados.
- `edge/src/qc_edge/jpeg.py` (novo): `write_capture_jpeg` (JPEG como chegou, PNG reencodado q=90), usado pelos dois modos, para não duplicar a regra que estava no `_CaptureStore`.

## Rastreabilidade (critério de aceite → implementação)

Abreviações dos testes do autor (todos em `edge/tests/`): `col/` = `test_collect.py`, `rt/` = `test_collect_route.py`, `cfg/` = `test_config.py`, `cap/` = `test_capture_route.py`, `pg/` = `test_pages.py`. Os arquivos de produção estão em `edge/src/qc_edge/`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `collect.py` (`DatasetWriter._write_locked`, `_append`, `MANIFEST_COLUMNS`, `CAPTURE_DEVICE_MAX_LENGTH`), `app.py` (`read_capture_form`, `collect`) | `col/::test_first_write_creates_image_and_manifest`, `::test_clock_is_converted_to_utc`; `rt/::test_collect_success_without_model` (User-Agent de 80 → 60) |
| CA-02 | `collect.py` (`NO_GRADE_DIR`, `_parse_grade`) | `col/::test_other_goes_to_underscore_with_empty_grade`, `::test_other_takes_no_grade`; `rt/::test_other_without_grade` |
| CA-03 | `collect.py` (`_parse_grade`) | `col/::test_invalid_fields` (grade ausente, vazio, `excellent`), `::test_other_takes_no_grade`; `rt/::test_invalid_fields_are_422_and_touch_nothing` |
| CA-04 | `collect.py` (`ITEM_PREFIX_TYPES`, `_OBJECT_TYPE_VALUES`) | `col/::test_invalid_fields` (`N-001`/screw, `T-001`, `unknown`); `rt/::test_invalid_fields_are_422_and_touch_nothing` |
| CA-05 | `collect.py` (`ITEM_ID_PATTERN` com `re.fullmatch`, `ANGLE_PATTERN` antes de `int()`, igualdade exata em `object_type`/`grade`/`labeler`, `_valid_notes`) | `col/::test_invalid_fields` (todos os valores do CA-05 e mais alguns), `::test_non_string_values_are_invalid`; `rt/::test_invalid_fields_are_422_and_touch_nothing` (`DATASET_DIR` nem é criado) |
| CA-06 | `collect.py` (`ItemTypeConflictError`, conferido antes de gravar) | `col/::test_item_with_another_type_is_409`; `rt/::test_conflicts_and_header_mismatch` |
| CA-07 | `collect.py` (`item_images` conta as linhas do `item_id`) | `col/::test_same_item_other_grade_counts_images` |
| CA-08 | `collect.py` (`CaptureExistsError`, `os.path.lexists` sob os locks) | `col/::test_same_second_is_409_and_nothing_changes`; `rt/::test_conflicts_and_header_mismatch` |
| CA-09 | `collect.py` (`threading.Lock` + `fcntl.flock`, linha escrita com um único `write`) | `col/::test_concurrent_writes_from_threads` (16 threads), `::test_file_lock_is_taken`, `::test_write_waits_for_the_file_lock_of_another_holder` |
| CA-10 | `collect.py` (`_csv_line`: `csv.writer`, `QUOTE_MINIMAL`, `lineterminator="\n"`) | `col/::test_quoting_round_trips`, `::test_notes_are_optional_and_kept_verbatim` |
| CA-11 | `collect.py` (`_read_manifest`, `ManifestHeaderMismatchError`) | `col/::test_header_mismatch_writes_nothing` (cabeçalho diferente, BOM, coluna renomeada, arquivo vazio), `::test_invalid_utf8_header_is_a_mismatch`; `rt/::test_conflicts_and_header_mismatch` |
| CA-12 | `app.py` (`collect` não usa `inferencer` nem `sink`) | `rt/::test_collect_never_calls_the_inferencer_nor_the_sink`, `::test_collect_success_without_model` (`inferencer=None`) |
| CA-13 | `app.py` (só `/static` é montado; nenhuma rota serve `DATASET_DIR`) | `rt/::test_dataset_is_never_served` |
| CA-14 | `app.py` (mesma ordem da SPEC-007: 401 → 413 → 422 → limitador → 415) | `rt/::test_token_size_and_image_errors_store_nothing`, `::test_collect_uses_the_decode_limiter` |
| CA-15 | `collect.py` (`compute_coverage`, `CoverageCell`, metas), `app.py` (`_coverage_html`, `_coverage_row_html`), `templates/console.html` | `col/::test_coverage_counts_images_and_items` (os números exatos do CA-15), `::test_coverage_of_a_missing_manifest`, `::test_coverage_cell_complete_needs_both_targets`; `rt/::test_console_coverage_without_manifest`, `::test_console_coverage_after_collecting`, `::test_console_highlights_complete_cells` |
| CA-16 | `templates/capture.html`, `app.py` (`_render_capture_page`) | `rt/::test_capture_page_has_the_collect_fields`; `pg/::test_capture_page` |
| CA-17 (manual) | `static/capture.js` (`syncForm`, `showSaved`, `save`/`load`), `edge/README.md` ("Teste manual do modo coleta") | `rt/::test_capture_script_rules`; roteiro manual abaixo |
| CA-18 | `collect.py` (`_make_dirs` + `_set_mode`, `tempfile.mkstemp` + `fchmod`, `_open_file` com `O_EXCL` + `fchmod`) | `col/::test_exact_modes_whatever_the_umask` (umask `022`, `077`, `000`, `277`, JPEG e PNG), `::test_existing_directories_and_files_are_not_changed`, `::test_chmod_failure_is_a_warning`, `::test_missing_parents_of_dataset_dir_are_0700` |

### CA-17 (manual, com celular)

Passo a passo no `edge/README.md`, seção "Teste manual do modo coleta (CA-17 da SPEC-010)". Resumo: subir `DATASET_DIR=/tmp/partqc-coleta uv run --package qc-edge qc-edge` (sem modelo); no celular, "coleta", `S-001`, parafuso, perfeito, `a`, ângulo 0; 5 fotos (ângulo 0→4 e "Peça completa"); recarregar (campos mantidos); trocar para "outro" (grau desabilitado); no notebook, 5 arquivos em `raw/screw/perfect/`, 6 linhas no manifest (cabeçalho + 5), modos `700`/`600` e, no console, `5/120` e `1/12`.

A lógica da página (ângulo avançando, "Peça completa" depois do 4, grau desabilitado e vazio para "outro", recusa de prefixo errado, campos enviados e guardados, mensagens de 409/422) foi exercitada fora do repositório com um stub mínimo de DOM em Node. O script não foi versionado. Não substitui o CA-17.

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q edge/tests/test_collect.py edge/tests/test_collect_route.py
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
DATASET_DIR=/tmp/partqc-coleta uv run --package qc-edge qc-edge   # coleta sem modelo
```

## Decisões tomadas dentro do escopo da SPEC

- **Tipos do modo coleta:** `DatasetObjectType` (`screw`, `nut`, `other`) é um `StrEnum` local de `collect.py`. `other` é classe do modelo, e não valor do contrato (`ObjectType` tem `unknown`), por isso não foi para `qc_contracts`. O rótulo "outro" fica em `app.py` (`DATASET_OBJECT_TYPE_LABELS_PT`). "parafuso" e "porca" vêm de `OBJECT_TYPE_LABELS_PT`, e os graus de `GRADE_LABELS_PT`.
- **`item_id` com `re.ASCII`:** `re.fullmatch(r"[SNOT]-\d{3}", v, re.ASCII)`. Sem a flag, `\d` aceita dígitos Unicode (ex.: `S-٠١٢`), que virariam nome de arquivo. É mais estrito que o texto da SPEC e não muda nenhum CA. O JS usa `[0-9]`.
- **`notes`:** recusa as categorias Unicode `Cc` (C0, DEL e C1, incluindo `\r`, `\n` e `\t`) e `Cs` (surrogates isolados, que não podem ser gravados em UTF-8). O conteúdo aceito é gravado sem nenhuma alteração.
- **Detalhes de erro sem texto na SPEC:**
  - 422 `missing or invalid <campo>`, no mesmo formato da SPEC-007;
  - `item_id prefix does not match object_type` e `grade must be empty for other`;
  - 500 `manifest unreadable` (cabeçalho certo, linhas que não são UTF-8 ou CSV válido);
  - 500 `failed to write dataset` (`OSError` ao criar diretório, imagem ou manifest, depois de apagar a imagem).
- **Cabeçalho:** a primeira linha é lida em bytes e comparada com as 9 colunas. BOM, arquivo vazio e primeira linha que não é UTF-8 contam como "header mismatch" (500, nada gravado).
- **Integridade do manifest:**
  - a linha é montada com `csv.writer` e escrita num único `write` (`O_APPEND`), seguido de `fsync`;
  - se a escrita falhar, o arquivo volta ao tamanho anterior (`ftruncate`) ou, se esta chamada o criou, é removido. Assim, não fica cabeçalho órfão nem linha pela metade;
  - um manifest editado à mão sem a quebra de linha final ganha um `\n` antes da nova linha, para as duas não se fundirem.
- **Arquivos:**
  - a imagem é gravada num temporário `.<nome>.jpg.<aleatório>.tmp` (não termina em `.jpg`) com `fsync` e `rename`;
  - `manifest.csv` e `manifest.csv.lock` são abertos com `O_NOFOLLOW`, e um symlink plantado no lugar do manifest não é seguido na escrita;
  - o 409 do passo 3 usa `os.path.lexists`, sob os dois locks.
- **Permissões:**
  - os pais de `DATASET_DIR` que a borda criar também ficam com `0700`, porque são criados pelo modo coleta;
  - `DATASET_DIR` e o que já existia não são alterados (testado com `0755`/`0644`);
  - se o `chmod`/`fchmod` falhar, sai um `WARNING` com o caminho e o modo, e a coleta segue.
- **`DATASET_DIR` nas settings:** um validador recusa (saída 2) um caminho que existe e não é diretório. O diretório não é criado na subida: o §4.2, item 5, e o CA-18 esperam que a primeira coleta o crie.
- **Limitador:** o slot é mantido durante a decodificação **e** a gravação, como no modo `inspect` (passos 3 a 7). A espera continua no threadpool (`acquire(timeout=...)`): a mudança para o event loop é da SPEC-025, que ainda não está `Done` (SPEC-010 §7).
- **Console:**
  - a cobertura é lida sob o lock de processo do writer, nunca no meio de uma escrita deste processo;
  - um manifest ilegível gera um `WARNING` no log, a tabela zerada e um aviso na página, em vez de um 500 no console;
  - "Total de imagens" é a soma das 11 células;
  - o console também mostra o caminho absoluto do `DATASET_DIR`.
- **Página:**
  - o modo (inspeção/coleta) também é guardado no `localStorage`, para o recarregamento do CA-17 voltar em "coleta";
  - o lembrete "Sem pessoas no quadro" fica sempre visível;
  - os `id` do cartão de inspeção passaram a `object_type_label`/`grade_label`, porque `object_type` e `grade` agora são os campos do formulário (ids duplicados são HTML inválido);
  - `item_id` e lote são enviados sem espaços nas pontas, e a página recusa no cliente o prefixo que não bate com o tipo e o grau vazio para parafuso/porca;
  - `notes` não aparece no log do servidor.
- **Formulário:** no modo `collect`, o `lot_id` não é lido nem validado. Agora o `mode` é validado antes do `lot_id`, e os dois continuam no passo "campos (422)" da SPEC-007.

## SPEC_ISSUE (se houver)

**SPEC_ISSUE-01 — três testes de aceite da SPEC-007 contradizem a SPEC-010 (não bloqueia a implementação; precisa de decisão do orquestrador antes do tester).**

Com esta implementação, `TEST_DATABASE_URL=… uv run pytest -q` dá **3 failed, 1808 passed**. As 3 falhas estão em `edge/tests/acceptance/test_spec_007.py`, arquivo que eu não posso editar (R-07):

| Teste | O que ele exige | Por que deixou de valer |
|---|---|---|
| `test_ca15_capture_page` (linha 998) | opção `collect` com `disabled` | SPEC-007 §3.2/§4.4: "coleta desabilitado **até a SPEC-010**"; o CA-16 da SPEC-010 exige "coleta" habilitado |
| `test_extra_collect_mode_is_501` (linha 1670) | `mode=collect` → 501 | SPEC-010 §3.1: a rota "substitui o 501 da SPEC-007". Sem os campos de coleta, agora é 422 |
| `test_ca13_console_from_loopback` (linha 933) | `page.count("parafuso") == 10` no console inteiro | a tabela de cobertura do §4.4 da SPEC-010 acrescenta 5 linhas "parafuso" ao console (rótulos PT-BR, ADR-012). As 10 linhas de inspeção continuam lá |

A SPEC-010 não autoriza o tester a ajustar o arquivo de aceite da SPEC-007, e a única forma de autorização registrada é a do `docs/architecture.md` §10, via §3.1 da SPEC. Não contornei o CA-13 com rótulos diferentes ("Parafuso", códigos em inglês), porque isso só esconderia a contradição. Proposta: o architect acrescenta à §3.1 da SPEC-010 a autorização para o tester atualizar essas três asserções (CA-15 da SPEC-007 sem exigir `disabled`, o teste extra do 501 removido ou trocado por 422, e a contagem do CA-13 restrita às linhas `<tr class="inspection">`), nos moldes do §10.

Nenhuma ambiguidade nos requisitos da SPEC-010 em si.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (107 arquivos)
- [x] Testes unitários do autor passando: **249** em `edge/tests` sem `acceptance/` (105 novos em `test_collect.py` e `test_collect_route.py`). Suíte inteira **com** `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`: **1808 passed, 3 failed** (as 3 da SPEC_ISSUE-01), em 4 min 16 s, com 1 aviso já existente (`StarletteDeprecationWarning` do `TestClient`)
- [x] `.env.example`: `DATASET_DIR=ml/data` já existia. Ganhou um comentário (modo coleta, criado na primeira coleta com `0700`/`0600`, nunca sai da LAN nem vai para o Git). Nenhum valor secreto. `ml/data/` já está no `.gitignore`
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim; nada em `ml/**`
- [x] Imagens dos testes geradas em memória (Pillow), sem binários no Git; os testes usam `tmp_path` como `DATASET_DIR` (a fixture `settings` do `conftest.py` nunca deixa o padrão `ml/data` apontar para o repositório)
- [x] Nenhum teste roda o pytest em subprocesso; nenhuma credencial literal em URL, conninfo ou header (o token é lido de `app.state.session_token`)
- [x] Sem dependência nova (`uv.lock` intacto); `fcntl`, `tempfile`, `csv` e `unicodedata` são da biblioteca padrão
