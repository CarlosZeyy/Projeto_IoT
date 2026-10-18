# SPEC-025 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-025-manutencao-borda` |
| Commits | `2c4f4b8`, `fb20890`, `40f7597` (+ o commit deste relatório) |

## Resumo

Esta rodada trata só o SPEC_ISSUE-01 (RV-01 de `r1-review-report.md`). O architect o resolveu com a opção (c) no commit `f4be335`, e o humano reaprovou.

- `qc_edge.jpeg.has_exif_rotation(data)` é nova (§4.8). Ela devolve `True` quando a tag `Orientation` (274) de `Image.open(..., formats=("JPEG",)).getexif()` tem um dos valores 2 a 8 que o `ImageOps.exif_transpose` aplica. O `getexif` também lê o `tiff:Orientation` do XMP. A função lê só o cabeçalho. Qualquer exceção do Pillow, salvo `MemoryError`, vira `JpegStructureError` com mensagem fixa.
- **Modo coleta:** um JPEG com rotação EXIF recebe 415 `{"detail": "invalid image: EXIF orientation not supported"}`, sem gravar nada. Os outros JPEGs continuam sendo gravados com `strip_private_segments`. Um `JpegStructureError` em qualquer dos dois passos dá o 415 `unsupported JPEG structure` que já existia. A checagem roda dentro do slot e na mesma chamada `to_thread.run_sync` (§4.2).
- **`python -m qc_edge.privacy`:** a varredura ganhou o achado `orientation` (§4.9). O `--fix` não reescreve arquivo com `invalid` nem com `orientation`, e o código de saída fica 1 enquanto um deles existir.
- **`edge/README.md`, seção "Modo coleta":** ganhou o item 4 da §4.12 e uma linha na tabela de respostas. O item 1 ("os pixels não mudam") ficou correto também para o `load_image`. Ver RV-01 do r1.
- Nenhuma variável nova. O `.env.example` não muda.

## Rastreabilidade (critério de aceite → implementação)

Só os CAs tocados nesta rodada. Os demais (CA-01 a CA-12, CA-14 e CA-16 a CA-18) estão como no `r1-dev-report.md`, sem mudança de código.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-11 (item `orientation` do README) | `edge/README.md` (seção "Modo coleta", item 4 e tabela de respostas) | Sem teste unitário: o CA é do tester. Conferi com `grep` que o trecho da seção contém `python -m qc_edge.privacy`, `--fix`, `orientation` e `dataset-protocol.md`. |
| CA-13 (pixels também pelo `load_image`) | `edge/src/qc_edge/collect.py` (`dataset_image_bytes`) | `test_collect.py::test_orientation_1_is_stripped_and_keeps_the_load_image_result`, `test_collect_route.py::test_orientation_1_is_stored_without_metadata`, `test_jpeg.py::test_no_exif_or_no_orientation_tag` (JPEG com metadados: `load_image` igual antes e depois da remoção), e os testes do r1 |
| CA-15 (pixels também pelo `load_image`) | `edge/src/qc_edge/privacy.py` | `test_privacy.py::test_fix_never_rewrites_an_orientation_finding` (o `f.jpg` corrigido tem o mesmo `load_image`), e os testes do r1 |
| CA-19 (`rot6` na coleta → 415; inspeção → 200 byte a byte) | `edge/src/qc_edge/collect.py` (`ExifOrientationNotSupportedError`, `dataset_image_bytes`), `edge/src/qc_edge/app.py` (o 415 sai pelo `CollectError` que já existia) | `test_collect_route.py::test_exif_rotated_jpeg_is_415_and_the_inspect_mode_keeps_it` (com `max_concurrent_decodes=1`: a inspeção seguinte confirma que o slot foi liberado), `test_collect.py::test_exif_rotated_jpeg_is_415_before_touching_the_disk` (EXIF 6 e XMP 8; `DATASET_DIR` não é criado), `test_collect.py::test_rotation_check_comes_before_the_strip`, `test_collect.py::test_unreadable_orientation_is_an_unsupported_structure`, `test_collect_route.py::test_orientation_check_runs_in_the_worker_thread` |
| CA-19 (`rot1` na coleta → 200, sem achados, `load_image` igual) | idem | `test_collect.py::test_orientation_1_is_stripped_and_keeps_the_load_image_result`, `test_collect_route.py::test_orientation_1_is_stored_without_metadata` |
| CA-19 (`has_exif_rotation`) | `edge/src/qc_edge/jpeg.py` | `test_jpeg.py`, 42 casos novos: `test_orientation_values_1_to_8` (de 1 a 8; a função dá `True` exatamente quando a remoção mudaria o `load_image`), `test_rot6_is_portrait_for_load_image`, `test_no_exif_or_no_orientation_tag`, `test_orientation_only_in_the_xmp` (atributo e elemento), `test_exif_orientation_1_wins_over_the_xmp`, `test_values_out_of_range_are_not_a_rotation` (0, 9, 255 e 65535), `test_odd_tiff_types_follow_exif_transpose`, `test_rotation_is_read_from_the_header_only` (dados de entropia cortados), `test_pillow_errors_become_structure_errors` (`b"not a jpeg"` e outros), `test_png_is_not_read_as_jpeg`, `test_any_pillow_exception_is_a_structure_error`, `test_memory_error_is_not_converted`, `test_rotation_check_logs_nothing` |
| CA-19 (`--fix` com `e.jpg` = `rot6` e `f.jpg` = `rot1`) | `edge/src/qc_edge/privacy.py` (`FINDING_ORIENTATION`, `UNFIXABLE_FINDINGS`, `_findings`) | `test_privacy.py::test_fix_never_rewrites_an_orientation_finding` (umask `0o022` e `0o277`; `e.jpg` e `g.jpg`, com orientação só no XMP, ficam iguais byte a byte; código 1; a nova execução sem `--fix` lista só os `orientation`), `test_privacy.py::test_orientation_is_a_finding_without_fix`, `test_privacy.py::test_unreadable_orientation_is_only_invalid`, `test_privacy.py::test_rotation_is_not_checked_when_the_walk_fails` |
| CA-08 (as três chamadas sem event loop) | sem mudança. A checagem da rotação roda na mesma chamada `to_thread.run_sync` | `test_collect_route.py::test_orientation_check_runs_in_the_worker_thread` |

Os helpers dos testes (`orientation_exif`, `rotated_jpeg`, `xmp_orientation_jpeg` e `tiff_orientation_exif`) estão em `edge/tests/conftest.py`, na fixture `jpeg_tools`. As imagens são geradas em memória (R-14).

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-review-report.md`, RV-01 (SPEC_ISSUE-01), média | Resolvido pela opção (c) da SPEC (`f4be335`), implementada nos commits `2c4f4b8` (coleta), `fb20890` (varredura) e `40f7597` (README). As mudanças estão no resumo e na rastreabilidade acima. O README não diz mais, sem ressalva, que "os pixels não mudam": agora explica que a foto com rotação nunca passa pela remoção, e por isso o `load_image` dá a mesma imagem. |
| `r1-review-report.md`, RV-02 a RV-05, baixas | **Não tratados**, por instrução do orquestrador. São sugestões de emenda para o architect, e o reviewer não pediu mudança de código nesta rodada. |
| `r1-test-report.md`, observações O-01 a O-04 | Sem mudança. O O-01 e o O-04 correspondem ao RV-03 e ao RV-02. O O-02 e o O-03 ficam com o security-devops, como diz o review. |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q edge/tests --ignore=edge/tests/acceptance      # 472 passed
uv run ruff check . && uv run ruff format --check .             # limpos (148 arquivos)
uv run pytest -q                                                # sem TEST_DATABASE_URL: 3016 passed, 643 skipped
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q   # 3659 passed
```

Os testes de aceite que já existiam (inclusive o `test_spec_025.py` do r1 e o `test_spec_010.py`) passam sem ajuste. Os JPEGs desses testes não têm rotação EXIF. O CA-19 e os ajustes do CA-11, do CA-13 e do CA-15 são do tester.

## Decisões tomadas dentro do escopo da SPEC

1. **Que valores de `Orientation` contam como rotação (§4.8).** A SPEC diz "um inteiro de 2 a 8" e "são exatamente os valores que o `ImageOps.exif_transpose` aplica". O `exif_transpose` busca a orientação num `dict` (`{2: …, …, 8: …}.get(orientation)`). Por isso, a função testa se o valor pertence a `frozenset(range(2, 9))`, que usa o mesmo hash e a mesma igualdade.
   - Um JPEG montado à mão pode gravar a tag 274 com tipo TIFF RATIONAL, FLOAT ou DOUBLE. O Pillow devolve então `6.0` (`IFDRational` ou `float`), e o `exif_transpose` gira a imagem mesmo assim. Com um teste `isinstance(valor, int)`, essa foto perderia o APP1 e a rotação, e a paridade do ADR-004 quebraria.
   - Li "inteiro de 2 a 8" como "valor numérico igual a um inteiro de 2 a 8", que satisfaz as duas frases. Por isso não abri um SPEC_ISSUE.
   - O `test_odd_tiff_types_follow_exif_transpose` mostra, tipo a tipo, que a função dá `True` exatamente quando a remoção mudaria o resultado do `load_image`. Os tipos testados são SHORT, LONG, SSHORT, RATIONAL 6/1, FLOAT, DOUBLE, RATIONAL 6,5, ASCII `"6"` e BYTE.
   - Um valor sem hash dá `False`. Nesse caso o `exif_transpose` levantaria exceção, e o `load_capture_image` já teria recusado a imagem com 415.
2. **Onde a checagem acontece:** em `collect.dataset_image_bytes`, chamado por `DatasetWriter.write` antes de qualquer acesso ao disco. É o mesmo ponto da remoção do r1 (decisão 3 do r1).
   - A ordem é a da §4.8: primeiro `has_exif_rotation` e, se der `False`, `strip_private_segments`.
   - O 415 não cria nem o `DATASET_DIR`.
   - Um PNG não passa por nenhum dos dois passos. A rotação do `eXIf` de um PNG já vem aplicada pelo `load_capture_image`, e o reencode não grava EXIF (`test_png_orientation_is_applied_before_the_reencode`).
3. **Nova classe de erro:** `ExifOrientationNotSupportedError(CollectError)`, com `status_code = 415`. Ela sai pelo mesmo `except CollectError` da rota, com o `WARNING` `collect refused: invalid image: EXIF orientation not supported`, que não traz o valor da tag. `app.py` só mudou na docstring.
4. **Varredura:** `has_exif_rotation` só é chamada se `jpeg_private_findings` não levantar. Um `JpegStructureError` de qualquer das duas vira só `invalid` (§4.9). O arquivo `orientation` entra no `k` do resumo (`checked n images, k with private data`), como no CA-19. Na prática, `orientation` sempre aparece junto com `app1`, porque a tag fica no APP1 (EXIF ou XMP).
5. **README:** além do item 4 da §4.12, entraram:
   - a lista dos achados possíveis no item 2;
   - `invalid` **ou** `orientation` não são corrigidos e o código continua 1;
   - uma linha na tabela de respostas para o 415 novo.
6. **Teste de log da rota:** usa o nível `INFO`, o mesmo da produção (ver O-01).

## Observações (não bloqueiam; não são SPEC_ISSUE)

- **O-01 (para o security-devops, R-14): logs DEBUG do próprio Pillow.**
  - O logger `PIL.TiffImagePlugin` registra em `DEBUG` os valores crus das tags EXIF que lê e grava.
  - Em `has_exif_rotation`, isso inclui a tag 274 (`tag: Orientation (274) … value: b'\x00\x06'`).
  - Em `qc_preprocess.load_image`, isso inclui o GPS completo. O `exif_transpose` apaga a orientação e serializa o EXIF de novo, o que gera `Tag 2, Type: 5, Value: (22.0, 54.0, 30.21)`. Esse comportamento já existia desde a SPEC-007/010 e vale também para o modo `inspect`.
  - Na produção esses registros nem são criados:
    - o `qc-edge` só configura o logger `qc_edge` (INFO);
    - a raiz fica no padrão `WARNING`;
    - o `python -m qc_edge.privacy` usa `basicConfig(level=INFO)`.
  - Só apareceriam se alguém ligasse `DEBUG` na raiz. Nenhum código desta SPEC registra valores de tag. Se o security-devops quiser blindar o caso, uma emenda pode fixar `logging.getLogger("PIL").setLevel(logging.INFO)` na subida e na CLI.
- **O-02:** `has_exif_rotation` abre o cabeçalho de novo com o Pillow, depois do `load_capture_image`. Isso custa uma leitura de marcadores, sem decodificação, e fica dentro do slot. Reaproveitar a imagem decodificada não serviria: o `load_image` já devolve a imagem girada, sem a tag.

## SPEC_ISSUE (se houver)

Nenhum. A leitura de "inteiro de 2 a 8" está registrada na decisão 1.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (148 arquivos)
- [x] Testes unitários do autor passando (472 em `edge/tests`, fora de `acceptance/`)
- [x] Suíte inteira sem banco: 3016 passed, 643 skipped, 0 failed
- [x] Suíte inteira com `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`: 3659 passed, 0 failed. Uma primeira tentativa deu falhas em `infra/tests/*_db.py` porque eu rodei, sem querer, duas suítes com banco ao mesmo tempo no mesmo `partqc_test`. A execução isolada passou inteira.
- [x] `.env.example`: nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum segredo literal. JPEGs gerados em memória, nunca fotos reais (R-14). `DATASET_DIR`/`EDGE_DATA_DIR` em `tmp_path`
- [x] R-02: nada novo abre conexão de rede. `has_exif_rotation` só lê bytes em memória
- [x] Não trabalhei em `ml/`. Não houve mudança de contrato (`qc_contracts`) nem de `qc_preprocess`
