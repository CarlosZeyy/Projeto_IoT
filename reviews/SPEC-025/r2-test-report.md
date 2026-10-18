# SPEC-025 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `9e3a63f` (código da r2: `2c4f4b8`, `fb20890`, `40f7597`; branch `spec/SPEC-025-manutencao-borda`) |
| **Veredicto** | **PASS** |

Esta rodada trata o SPEC_ISSUE-01 (RV-01 de `r1-review-report.md`), resolvido pela opção (c) em `f4be335`. Como na r1, escrevi os testes a partir da SPEC (caixa-preta) e só depois li o diff da r2 (`046e2fd..9e3a63f`).

Arquivo: `edge/tests/acceptance/test_spec_025.py`, agora com **197 testes coletados** (82 funções):

- 53 ligados aos 19 CAs (33 funções `test_caNN_*`), contra 48 (28 funções) na r1;
- 144 exploratórios (49 funções `test_extra_*`), contra 85 (39 funções) na r1.

O que mudou no arquivo:

- **CA-11:** a seção "Modo coleta" do README também precisa conter `orientation`.
- **CA-13:** o arquivo gravado e o JPEG enviado também precisam dar a mesma imagem no `qc_preprocess.load_image` (tamanho e `np.array_equal`).
- **CA-15:** no `--fix`, `b.jpg` e `c.jpg` também precisam dar a mesma imagem no `load_image` antes e depois.
- **CA-19:** novo, com cinco funções.
- **Exploratórios novos** sobre a rotação EXIF e a paridade do ADR-004 (ver abaixo).
- A docstring do módulo passa a dizer "CA-01 to CA-19".

Nenhum CA antigo foi removido ou renomeado, e as asserções da r1 continuam todas no arquivo. A §4.7 não prevê ajustes novos para a r2, e nenhum foi necessário: `test_spec_007.py`, `test_spec_010.py`, `test_spec_022.py` e `test_spec_023.py` não foram tocados.

Regras seguidas (as mesmas da r1, `reviews/checklist.md` e `docs/architecture.md` §10):

- imagens geradas em memória: Pillow mais bytes inseridos, inclusive o TIFF montado à mão para os tipos de campo. Nenhuma foto real (R-14);
- `EDGE_DATA_DIR` e `DATASET_DIR` sempre em `tmp_path`;
- token e marcadores gerados com `secrets`, sem credencial literal;
- nenhum teste novo abre subprocesso. Os três da r1 não mudaram (CA-04, CA-12 e `python -m qc_edge.privacy`);
- mocks só nas fronteiras da §6. O único espião novo é o mesmo `qc_edge.limits.load_capture_image` do CA-08, que chama o original;
- `qc_edge.jpeg.has_exif_rotation` e `qc_preprocess.load_image` são usados pela interface pública, sem mock.

## Cobertura dos critérios de aceite

Prefixo dos testes: `edge/tests/acceptance/test_spec_025.py::`. Todos os CAs rodaram de novo nesta rodada.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_console_answers_loopback_hosts[4 Hosts]` (sem mudança desde a r1) | ✅ |
| CA-02 | `test_ca02_console_refuses_other_hosts_before_detecting_ips` (sem mudança) | ✅ |
| CA-03 | `test_ca03_port_80_accepts_hosts_without_port` (sem mudança) | ✅ |
| CA-04 | `test_ca04_real_server_refuses_a_rebound_host` (`slow`, servidor real em `127.0.0.1`; sem mudança) | ✅ |
| CA-05 | `test_ca05_token_routes_do_not_check_the_host` (sem mudança) | ✅ |
| CA-06 | `test_ca06_edge_host_must_be_ipv4[4]`, `test_ca06_ipv4_edge_host_is_passed_to_uvicorn[3]` (sem mudança) | ✅ |
| CA-07 | `test_ca07_waiting_requests_do_not_block_the_status` (sem mudança; passou nas 5 execuções desta rodada: o arquivo, o diretório `edge/tests/acceptance/` 2 vezes e as 2 suítes inteiras) | ✅ |
| CA-08 | `test_ca08_blocking_work_never_runs_on_the_event_loop`, `test_ca08_slot_is_released_after_an_inference_error` (sem mudança) | ✅ |
| CA-09 | `test_ca09_capture_modes_are_exact_whatever_the_umask[0o22, 0o77, 0o0, 0o277]`, `test_ca09_existing_dirs_keep_data_dir_and_fix_captures` (sem mudança) | ✅ |
| CA-10 | `test_ca10_unknown_arguments_exit_2_without_values` (sem mudança) | ✅ |
| CA-11 | `test_ca11_readme_and_env_example`. Conferências: (1) linhas de liberação no firewall com origem; (2) nenhum `--permanent` e `ip -4 route show scope link` no texto; (3) `## Segurança na operação`; (4) linha do `EDGE_HOST`; (5) **seção "Modo coleta" com `python -m qc_edge.privacy`, `--fix`, `orientation` e `dataset-protocol.md`** (r2); (6) `.env.example` | ✅ |
| CA-12 | `test_ca12_docstrings_of_spec_022_and_023` (sem mudança; 38 e 22 testes coletados, como na `main`) | ✅ |
| CA-13 | `test_ca13_collect_stores_the_jpeg_without_private_segments`. Além do que a r1 já conferia, verifica **na r2** que o `qc_preprocess.load_image` do arquivo gravado e do JPEG enviado dá o mesmo tamanho e os mesmos pixels. O JPEG limpo continua gravado byte a byte, e o JPEG com metadados em `mode=inspect` também | ✅ |
| CA-14 | `test_ca14_findings_and_strip_of_the_metadata_jpeg`, `test_ca14_eoi_inside_app1_is_not_the_end`, `test_ca14_structural_errors[3]` (sem mudança) | ✅ |
| CA-15 | `test_ca15_scan_reports_without_changing_anything`, `test_ca15_fix_rewrites_only_the_private_files[0o22, 0o277]` e `test_ca15_usage_errors_exit_2_without_echo[2]`. No `--fix`, verifica **na r2** que `b.jpg` e `c.jpg` dão, depois da correção, o mesmo tamanho e os mesmos pixels de antes no `load_image`, além do `Image.open(...).convert("RGB")` | ✅ |
| CA-16 | `test_ca16_unwalkable_jpeg_is_415_and_releases_the_slot` (sem mudança) | ✅ |
| CA-17 | `test_ca17_directories_are_synced_in_order`, `test_ca17_directory_sync_errors_are_warnings` (sem mudança) | ✅ |
| CA-18 | `test_ca18_notes_with_separators_or_format_chars_are_422[6]`, `test_ca18_valid_notes_are_stored_unchanged`, `test_ca18_user_agent_controls_become_spaces_before_the_cut` (sem mudança) | ✅ |
| CA-19 | Cinco funções, listadas abaixo | ✅ |

As cinco funções do CA-19. Nelas, `rot6` é um JPEG 64×48 do Pillow com `Orientation=6` e o IFD GPS, e `rot1` é o mesmo JPEG com `Orientation=1`:

1. `test_ca19_rot6_is_portrait_for_load_image`: confere a pré-condição. `load_image(rot6).size == (48, 64)`, e `rot1` dá `(64, 48)`.
2. `test_ca19_rotated_jpeg_is_415_in_collect_and_kept_in_inspect`, com `max_concurrent_decodes=1`:
   - `rot6` numa coleta → 415 `{"detail": "invalid image: EXIF orientation not supported"}`, sem imagem e sem linha no manifest;
   - a captura seguinte (`rot6`, `mode=inspect`) → 200, o que confirma que o slot foi liberado;
   - o único arquivo em `captures/` é igual, byte a byte, a `rot6`.
3. `test_ca19_orientation_1_is_stored_without_private_data`: `rot1` → 200. O arquivo gravado não tem achados (`frozenset()`), e o `load_image` dele e o de `rot1` dão o mesmo tamanho e os mesmos pixels.
4. `test_ca19_has_exif_rotation`: `True` para `rot6`; `False` para `rot1` e para um JPEG do Pillow sem EXIF; `JpegStructureError` para `b"not a jpeg"`.
5. `test_ca19_fix_never_rewrites_an_orientation_finding`, com `e.jpg` = `rot6` e `f.jpg` = `rot1`:
   - o `--fix` sai com 1. O stdout tem `raw/screw/fair/e.jpg: app1, orientation`, `raw/screw/fair/f.jpg: app1` e `fixed raw/screw/fair/f.jpg`, não tem `fixed raw/screw/fair/e.jpg` e termina com `checked 2 images, 2 with private data`;
   - `e.jpg` continua igual byte a byte. `f.jpg` fica sem achados e com o mesmo `load_image` de antes;
   - a nova execução sem `--fix` sai com 1, tem `e.jpg: app1, orientation` como única linha de achado e termina com `checked 2 images, 1 with private data`.

**Sensibilidade (os testes falham sem a mudança da r2).** Rodei o arquivo novo contra o código da r1 (`59097ba`), num `git worktree` temporário fora do repositório, removido no fim. A r1 não tem `has_exif_rotation`, então a cópia do teste recebeu um substituto local com a regra da §4.8, só para poder ser importada. Resultado: **32 falhas e 163 passes**.

- Falham:
  - o CA-11, porque o README da r1 não tem `orientation`;
  - o CA-19 na rota e no `--fix`;
  - todos os exploratórios em que o `load_image` gira a imagem: orientações 2 a 8, XMP, tipos TIFF que giram e estruturas incomuns com rotação.
- Passam nos dois lados, como esperado:
  - os casos sem rotação;
  - os ajustes do CA-13 e do CA-15, cujas imagens não têm `Orientation`. Eles protegem a paridade contra regressões, mas não distinguem a r1 da r2.

## Ajustes em testes de aceite de SPECs anteriores

Nenhum nesta rodada. A SPEC (histórico de 2026-10-18) diz "Nenhum ajuste novo em testes antigos (§4.7)", e todos os arquivos antigos passam sem mudança. Os ajustes da r1 (`2d5ab42`, `1fce170`) continuam como estão registrados em `r1-test-report.md`.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
148 files already formatted

$ env -u TEST_DATABASE_URL uv run pytest -q
3080 passed, 643 skipped, 1 warning in 260.53s (0:04:20)

$ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
3723 passed, 1 warning in 433.03s (0:07:13)

$ uv run pytest -q edge/tests/acceptance/test_spec_025.py
197 passed, 1 warning in 20.17s

$ uv run pytest -q edge/tests/acceptance/          # 2 execuções seguidas
432 passed, 1 warning in ~35 s                     # 110 (SPEC-007) + 125 (SPEC-010) + 197 (SPEC-025)
```

- As contagens batem com o dev-report: 3016 + 64 = 3080 sem banco, e 3659 + 64 = 3723 com banco. Os 64 são os testes novos do arquivo (197 − 133).
- Rodei as duas suítes **uma depois da outra**. Antes da suíte com banco, conferi com `pgrep` que não havia outro pytest em execução.
- O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia. O caso `short-6-6` gera um `UserWarning: Metadata Warning, tag 274 had too many entries` do Pillow, que é o próprio objeto do caso. Esse aviso é filtrado só nesse teste (`filterwarnings`).
- Limpeza: nenhum processo `qc_edge` ficou rodando, o worktree temporário foi removido (`git worktree list` mostra só o repositório) e o `git status` mostra só os arquivos deste trabalho.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos estão automatizados em `test_extra_*` e passam. Os da r1 continuam no arquivo. Abaixo, só os novos, da r2.

O critério de paridade usado é o do ADR-004 e da §4.8. Em `rotates_in_load_image(x)`, o `load_image(x)` dá uma imagem diferente da de `load_image(strip_private_segments(x))`, comparando tamanho e pixels. A imagem de teste é ruído 64×48, então qualquer transposição muda o resultado. Para cada caso, os testes conferem quatro coisas:

1. `has_exif_rotation(x) is rotates_in_load_image(x)`;
2. na coleta, 415 `EXIF orientation not supported` sem gravar nada quando há rotação; senão, 200 com o mesmo `load_image` no arquivo gravado;
3. na varredura, o achado `orientation` aparece exatamente nos arquivos com rotação;
4. no `--fix`, esses arquivos ficam iguais byte a byte e o código é 1; os outros são corrigidos com o mesmo `load_image` e o código é 0.

- **Orientações 2 a 8 no EXIF** (`test_extra_every_exif_rotation_is_refused_and_flagged[2..8]`): as 7 recebem 415 na coleta, sem gravar nada. Na varredura com `--fix`, cada uma dá `app1, orientation` e `checked 1 images, 1 with private data`, com código 1 e o arquivo intacto.
- **Orientação só no XMP** (`test_extra_orientation_only_in_the_xmp_is_refused_and_flagged`):
  - formas: atributo `tiff:Orientation="N"` e elemento `<tiff:Orientation>N</tiff:Orientation>`, com N em 2, 6 e 8, sem tag no EXIF;
  - os 6 casos: 415 na coleta, `app1, orientation` na varredura e o arquivo intacto depois do `--fix`.
- **Valores que não giram** (`test_extra_orientation_values_that_do_not_rotate_are_stored_with_load_image_parity`): EXIF 0, EXIF 9, XMP 1, XMP 9, EXIF 1 com XMP 6 (o EXIF prevalece no Pillow) e GPS sem orientação. Todos: 200, sem achados no arquivo gravado e o mesmo `load_image`.
- **Decisão 1 do dev-report: valores não inteiros** (`test_extra_odd_tiff_types_follow_the_loader`, 18 casos). Cada caso é um APP1 EXIF montado à mão, só com a tag 274, em tipos TIFF diferentes. Resultado medido:

  | Tipo TIFF (valor) | Valor no `getexif()` do Pillow | `exif_transpose` gira? | Coleta | Varredura |
  |---|---|---|---|---|
  | SHORT 6, SHORT ×2 (6, 6), LONG 6, SSHORT 6, SLONG 8 | `int` (6 ou 8) | sim | 415 | `app1, orientation` |
  | RATIONAL 6/1, RATIONAL 12/2, SRATIONAL 3/1 | `IFDRational` (6.0, 6.0, 3.0) | sim | 415 | `app1, orientation` |
  | FLOAT 6.0, DOUBLE 8.0 | `float` | sim | 415 | `app1, orientation` |
  | RATIONAL 13/2, FLOAT 6.5 | 6.5 | não | 200, mesmo `load_image` | `app1`, corrigido |
  | BYTE 6 | `bytes` (`b"\x06"`) | não | 200, mesmo `load_image` | `app1`, corrigido |
  | ASCII `"6"` | `str` | não | 200, mesmo `load_image` | `app1`, corrigido |
  | SSHORT −6, SHORT 0, SHORT 9, SHORT 65535 | `int` fora de 2 a 8 | não | 200, mesmo `load_image` | `app1`, corrigido |

  A função dá `True` exatamente quando a remoção mudaria o `load_image`, que é a garantia da §4.8 e do ADR-004. Uma leitura literal de "inteiro" (`isinstance(valor, int)`) daria `False` para RATIONAL 6/1, FLOAT e DOUBLE. A coleta gravaria a foto sem o APP1, e o treino a leria girada. É exatamente o defeito do SPEC_ISSUE-01. Ver a O-r2-01.
- **Estruturas incomuns** (`test_extra_odd_structures_keep_the_load_image_parity`, 8 casos), na mesma propriedade:
  - **MPO de 2 quadros** (índice MPF no APP2, 2º quadro depois do EOI): achado `trailer`. A coleta grava só o 1º quadro, com o MPF mantido. O `load_image` do arquivo gravado é o mesmo, porque o loader lê só o quadro 0. O mesmo vale para o MPO com `Orientation=1`;
  - **MPO com `Orientation=6`:** 415 e `orientation`;
  - **dois APP1 EXIF, um com GPS e outro com `Orientation=6`, nas duas ordens:** o Pillow concatena os dois. Com o de rotação primeiro, gira (415). Com o de GPS primeiro, não gira, e o resultado é 200 com paridade. Nos dois, a função acompanha o loader;
  - **APP1 com `Orientation=6` entre dois scans progressivos:** o Pillow não lê marcadores depois do 1º SOS, então nada gira. O resultado é 200, o APP1 é removido e a paridade se mantém;
  - **XMP com `tiff:Orientation="60"`:** a expressão do Pillow lê só o primeiro dígito e trata o valor como 6. A imagem gira, a coleta dá 415 e a varredura acusa `orientation`. A função acompanha o loader nesse caso também;
  - **EXIF só com GPS e orientação só no XMP:** 415 e `orientation`.
- **Paridade de toda imagem aceita** (`test_extra_every_accepted_jpeg_keeps_the_load_image_result`, 8 casos): JPEG limpo, JPEG com metadados, `rot1`, progressivo com EXIF, com RSTn e EXIF, CMYK com APP14 Adobe, cinza e APP1 com uma miniatura que contém `FF D9`. Em todos, o `load_image` e o `Image.open(...).convert("RGB")` do arquivo gravado são iguais aos do enviado, e o arquivo gravado não tem achados.
- **PNG com `Orientation` 1, 6 e 8 no `eXIf`** (`test_extra_png_with_exif_orientation_keeps_the_loaded_size`): 200. O JPEG reencodado tem o mesmo tamanho do PNG no `load_image` (48×64 com 6 e 8), não tem achados e `has_exif_rotation` dá `False` nele. Os pixels não são comparados, porque o reencode q=90 da SPEC-010 tem perda por definição (§4.8: "O PNG continua reencodado").
- **`has_exif_rotation` lê só o cabeçalho e nunca registra o valor** (`test_extra_has_exif_rotation_reads_only_the_header_and_never_logs_the_value`):
  - um `rot6` cortado no meio dos dados de entropia dá `True`, sem decodificar;
  - `b""`, só SOI, PNG, GIF e APP1 truncado levantam `JpegStructureError`, com mensagem sem bytes da entrada;
  - nenhum registro dos loggers `qc_edge` cita `Orientation`.
- **Slot e log** (`test_extra_rotated_collect_releases_the_slot_and_logs_no_gps`): com 1 slot, três `rot6` seguidos recebem 415, e um `rot1` em seguida recebe 200, com 1 linha no manifest. Nenhum log `qc_edge` contém a latitude.
- **Fora do event loop** (`test_extra_rotation_check_runs_inside_the_slot_off_the_event_loop`): com `rot6`, o espião do CA-08 em `load_capture_image` é chamado 1 vez, sem event loop na thread, antes do 415.

### Leitura do código, depois dos testes caixa-preta

- **`has_exif_rotation`** (`edge/src/qc_edge/jpeg.py`):
  - usa `Image.open(..., formats=("JPEG",))` e `getexif().get(274)` sem `load()`;
  - testa `in frozenset(range(2, 9))`, a mesma busca por hash do `exif_transpose`;
  - um valor sem hash dá `False`;
  - qualquer exceção, salvo `MemoryError`, vira `JpegStructureError` com mensagem fixa. Bate com a §4.8.
- **`dataset_image_bytes`** (`collect.py`): a ordem é `has_exif_rotation` primeiro e `strip_private_segments` depois, e as duas recusas acontecem antes do disco e dentro da mesma `to_thread.run_sync`. Bate com a §4.2 e a §4.8.
- **`_findings`** (`privacy.py`): `has_exif_rotation` só é chamada quando a varredura estrutural passa, e o `--fix` pula `invalid` e `orientation` (`UNFIXABLE_FINDINGS`). Bate com a §4.9.

### Observações (não são bugs; para o reviewer, o architect e o security-devops)

- **O-r2-01 (§4.8, informativa; decisão 1 do dev-report):** a §4.8 tem duas frases:
  - "o valor da tag `Orientation` … for **um inteiro** de 2 a 8";
  - "São **exatamente os valores** que o `ImageOps.exif_transpose` aplica".

  Num EXIF montado à mão com tipo RATIONAL, FLOAT ou DOUBLE, o Pillow devolve `6.0`, e as duas frases divergem: o valor não é um `int`, mas o `exif_transpose` aplica a rotação. A implementação segue a segunda frase, que é a única que mantém a garantia escrita logo depois ("Assim o `load_image` dá a mesma imagem…", ADR-004), e o teste exploratório mostra a equivalência tipo a tipo. Não registro `SPEC_ISSUE`, por três motivos:
  - nenhum CA depende do caso;
  - o CA-19 usa só `Orientation=6` e `1` do Pillow (SHORT);
  - a leitura literal reabriria o próprio SPEC_ISSUE-01.

  Sugestão para uma emenda do architect: trocar "um inteiro de 2 a 8" por "um valor igual a um inteiro de 2 a 8 (a busca do `exif_transpose`)".
- **O-r2-02 (informativa):** algumas rotações vêm de leituras pouco intuitivas do Pillow:
  - o XMP `tiff:Orientation="60"` vale como 6;
  - com dois APP1 EXIF, o Pillow concatena os dois, e a ordem decide se há rotação.

  Nos dois casos, a coleta e a varredura acompanham o loader, então a paridade do ADR-004 se mantém. Para a dupla, o efeito é só refotografar uma foto montada à mão.
- **O-r2-03 (§4.8, informativa):** um MPO (por exemplo, o de algumas câmeras de celular) é aceito na coleta e gravado só com o 1º quadro. O APP2 MPF fica, com um índice que aponta para o quadro removido. O `load_image` não muda, porque lê só o quadro 0. Quem abrir o arquivo como MPO vai ver `n_frames` inconsistente com o tamanho. A §4.8 manda manter o APP2, então isso não é bug.
- **Dev O-01 (logs DEBUG do Pillow):** não reproduzi além do que o dev-report descreve. O teste exploratório confere só que os loggers `qc_edge` não registram nem a orientação nem a latitude. Fica com o security-devops, como diz o dev-report.
- As observações O-01 a O-04 da r1 (RV-02 e RV-03 do review) continuam valendo, sem mudança de código nesta rodada.

## SPEC_ISSUE (se houver)

Nenhum. A tensão de texto da §4.8 está registrada como O-r2-01, porque a implementação satisfaz a garantia normativa da SPEC (ADR-004) e todos os CAs.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório:
  - `edge/tests/acceptance/test_spec_025.py` (CA-11, CA-13 e CA-15 ajustados, CA-19 novo e exploratórios novos).
