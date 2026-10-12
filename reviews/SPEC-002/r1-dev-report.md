# SPEC-002 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-002](../../docs/specs/SPEC-002-pacotes-compartilhados.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-002-pacotes-compartilhados` |
| Commits | `19d2a38` (feat(contracts)), `eb9c15a` (feat(preprocess)), mais o commit deste relatório |

## Resumo

- `qc_contracts` 0.1.0 implementa o §3 de `architecture.md`:
  - enums `StrEnum`, `GRADE_ORDER`, `grade_index` e `grade_from_index`;
  - `is_defective`, a única implementação da regra no projeto;
  - todos os schemas Pydantic v2 das §§3.2 a 3.4, com invariantes num `model_validator` de uma base comum (`_InspectionBase`) e datas com fuso normalizadas para UTC por um tipo anotado único (`UtcDatetime`);
  - as quatro regexes públicas;
  - rótulos PT-BR em `MappingProxyType`;
  - README com o histórico de versões.
- `qc_preprocess` 0.1.0 traz:
  - `PreprocessParams` (frozen, validado, ida e volta pelo `preprocessing.json`);
  - `load_image`, que valida pelo conteúdo, aceita só JPEG/PNG, impõe o limite de 40 M pixels pelo cabeçalho, trata arquivo truncado e bomba de descompressão e aplica `exif_transpose` antes de converter para RGB;
  - `preprocess`, que faz o resize bilinear do lado menor com truncamento, o crop central, a conversão para `float32` e a normalização, e devolve um array C-contíguo `(1, 3, crop, crop)`. Não usa torch.
- As versões estão em `0.1.0` nos dois `pyproject.toml`. O `uv.lock` foi atualizado: só as versões dos dois membros mudaram, e nenhuma dependência nova entrou.

## Rastreabilidade (critério de aceite → implementação)

Testes em `packages/contracts/tests/` (abreviado `ct/`) e `packages/preprocess/tests/` (abreviado `pt/`).

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/__init__.py`, `packages/contracts/pyproject.toml`, `packages/preprocess/src/qc_preprocess/__init__.py`, `packages/preprocess/pyproject.toml`, `uv.lock` | `ct/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version`; `pt/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version` |
| CA-02 | `qc_contracts/enums.py`, `qc_contracts/schemas.py` (constantes `*_PATTERN`) | `ct/test_enums.py::test_enum_values`, `::test_grade_order_matches_definition_order`; `ct/test_schemas.py::test_pattern_constants` |
| CA-03 | `qc_contracts/enums.py` | `ct/test_enums.py::test_grade_index_values`, `::test_grade_index_round_trip`, `::test_grade_from_index_rejects_out_of_range` |
| CA-04 | `qc_contracts/defects.py` | `ct/test_defects.py::test_is_defective`, `::test_is_defective_accepts_grade_strings`, `::test_is_defective_rejects_unknown_values` |
| CA-05 | `qc_contracts/schemas.py` (`UtcDatetime`, `InspectionCreate`) | `ct/test_schemas.py::test_base_payload_is_valid`, `::test_inspected_at_normalized_to_utc`, `::test_fixed_instant_conversion`, `::test_round_trip_json` |
| CA-06 | `qc_contracts/schemas.py` (`AwareDatetime`) | `ct/test_schemas.py::test_naive_datetime_rejected` |
| CA-07 | `qc_contracts/schemas.py` (`InspectionCreate._not_in_future`, `MAX_FUTURE_SKEW`) | `ct/test_schemas.py::test_future_limit`, `::test_future_limit_with_other_timezone` |
| CA-08 | `qc_contracts/schemas.py` (`_InspectionBase._check_grade_invariants`) | `ct/test_schemas.py::test_unknown_with_grade_rejected`, `::test_known_type_without_grade_rejected` |
| CA-09 | idem | `ct/test_schemas.py::test_unknown_with_null_grade_fields_accepted`, `::test_null_grade_with_score_or_confidence_rejected`, `::test_grade_without_score_or_confidence_rejected` |
| CA-10 | `qc_contracts/schemas.py` (tipos `Probability`, `GradeScore`, `DeviceId`, `LotId`, `ModelVersion`, `Sha256Hex`, `UUID4`) | `ct/test_schemas.py::test_invalid_field_values` (32 casos, incluindo todos os do CA) |
| CA-11 | idem | `ct/test_schemas.py::test_inclusive_limits`, `::test_pattern_boundaries_accepted` |
| CA-12 | `qc_contracts/schemas.py` (`extra="forbid"`) | `ct/test_schemas.py::test_extra_fields_forbidden` |
| CA-13 | `qc_contracts/schemas.py` (`BatchCreate`, `MAX_BATCH_SIZE`) | `ct/test_schemas.py::test_batch_size_rejected`, `::test_batch_size_accepted`, `::test_batch_error_points_to_item`, `::test_batch_extra_forbidden` |
| CA-14 | `qc_contracts/schemas.py` (`InspectionRead`) | `ct/test_schemas.py::test_read_tolerates_extra_and_future`, `::test_read_keeps_invariants`, `::test_read_requires_server_fields`, `::test_read_normalizes_received_at`, `::test_read_round_trip` |
| CA-15 | `qc_contracts/schemas.py` (`InspectionCreated`) | `ct/test_schemas.py::test_inspection_created_status`, `::test_inspection_created_bad_status` |
| CA-16 | `qc_contracts/schemas.py` (`Page`, `MetricsSummary`, `TimeseriesPoint`, `SpcPoint`, `SpcExcludedLot`, `SpcResponse`, `LotSummary`, `HealthResponse`, `BatchResult`) | `ct/test_schemas.py::test_page_of_inspection_read_round_trip`, `::test_page_rejects_invalid`, `::test_metrics_summary_round_trip`, `::test_timeseries_point_round_trip`, `::test_spc_response_round_trip`, `::test_spc_response_empty_with_message`, `::test_lot_summary_round_trip`, `::test_health_response_valid`, `::test_health_response_invalid`, `::test_batch_result_round_trip`, `::test_response_models_ignore_extra_fields` |
| CA-17 | `qc_contracts/labels.py` | `ct/test_labels.py::test_one_label_per_member`, `::test_labels_are_read_only`, `::test_lookup_by_plain_string` |
| CA-18 | todos os módulos de `qc_contracts` (só imports absolutos), `packages/contracts/pyproject.toml` | `ct/test_no_io_imports.py::test_only_allowed_imports`; `ct/test_smoke.py::test_only_pydantic_dependency` |
| CA-19 | `qc_preprocess/params.py` | `pt/test_params.py::test_defaults`, `::test_invalid_params`, `::test_json_round_trip`, `::test_json_format`, `::test_from_json_invalid`, `::test_from_json_not_json` |
| CA-20 | `qc_preprocess/transform.py` | `pt/test_transform.py::test_shape_dtype_contiguous_and_values_for_solid_color`, `::test_resize_target_uses_truncation` |
| CA-21 | `qc_preprocess/transform.py` | `pt/test_transform.py::test_exact_crop_without_resampling` |
| CA-22 | `qc_preprocess/transform.py`, `qc_preprocess/image.py` | `pt/test_transform.py::test_deterministic_bit_identical`, `::test_input_image_is_not_modified` |
| CA-23 | `qc_preprocess/image.py` | `pt/test_image.py::test_exif_orientation_applied`, `::test_png_modes_converted_to_rgb`, `::test_grayscale_jpeg_converted_to_rgb` |
| CA-24 | `qc_preprocess/image.py`, `qc_preprocess/errors.py` | `pt/test_image.py::test_invalid_images` (vazio, texto, JPEG e PNG truncados, GIF, BMP, WEBP, 8000×8000, limite+1, bomba do Pillow), `::test_missing_path`, `::test_pixel_limit_is_inclusive`, `::test_content_not_extension_decides` |
| CA-25 | `qc_preprocess/transform.py` | `pt/test_transform.py::test_non_rgb_rejected` |
| CA-26 | `packages/preprocess/pyproject.toml`, `qc_preprocess/*` | `pt/test_smoke.py::test_import_does_not_load_torch` (processo novo), `::test_only_numpy_and_pillow_dependencies` |
| CA-27 | `packages/contracts/README.md` | `ct/test_smoke.py::test_readme_has_version_history_row` |

## Resposta à rodada anterior (a partir de r2)

Não se aplica: esta é a r1.

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q packages/contracts packages/preprocess
uv run pytest -q          # suíte inteira: 407 passed, 2 skipped (TEST_DATABASE_URL ausente)
```

## Decisões tomadas dentro do escopo da SPEC

1. **Campos anuláveis obrigatórios.** `grade`, `grade_score` e `grade_confidence` aceitam `null`, mas não têm default: a chave tem de vir no JSON, como todas as outras de §3.2. O §3.2 não marca nenhum campo como opcional. O CA-08 e o CA-09 enviam os nulos explicitamente.
2. **Base comum e tipo de data único.**
   - `_InspectionBase`, que é privada, concentra os campos e as invariantes. `InspectionCreate` acrescenta `extra="forbid"` e a regra dos 5 min; `InspectionRead` acrescenta `extra="ignore"`, `received_at` e `is_defective` (§7 da SPEC).
   - `UtcDatetime` (`AwareDatetime` mais `astimezone(datetime.UTC)`) é usado em todas as datas dos schemas. Assim, `tzinfo is datetime.UTC`, que é o mesmo objeto que `timezone.utc`.
3. **Constantes públicas extras.** O código expõe também `MAX_FUTURE_SKEW = timedelta(minutes=5)` e `MAX_BATCH_SIZE = 100` em `qc_contracts`, e `MAX_PIXELS = 40_000_000` e `ACCEPTED_FORMATS = ("JPEG", "PNG")` em `qc_preprocess`. A ideia é que a API e a borda reusem esses valores sem redefini-los. São só os números que a SPEC já fixa.
4. **Sem restrições além da SPEC nos modelos de resposta.**
   - As contagens de `MetricsSummary`, `TimeseriesPoint`, `SpcPoint` e `LotSummary` são `int` sem limite, porque a semântica é da SPEC-005/006.
   - `LotSummary.sources` é `list[Source]`, sem validar unicidade nem ordem. A docstring registra a semântica ("distintos, na ordem do enum"), e quem garante isso é a SPEC-005.
   - `InspectionRead.is_defective` não é conferido contra `grade`, porque a SPEC o define só como `bool` vindo do servidor.
5. **`is_defective` e `grade_index`.** A anotação é `Grade | None`, como na SPEC. Uma `str` igual a um valor do enum é aceita via `Grade(value)`, e qualquer outra entrada levanta `ValueError`. `grade_from_index` também rejeita `bool` e não `int` com `ValueError`, o que evita que `True` vire o índice 1.
6. **`PreprocessParams`.**
   - `mean` e `std` são normalizados em `__post_init__` para `tuple[float, float, float]`, para que listas do JSON e tuplas sejam iguais na comparação.
   - Valores não finitos e tipos errados (`bool`, `str`, `float` em campo inteiro) levantam `ValueError`.
   - `from_json` aceita só um objeto JSON com exatamente as quatro chaves.
7. **`load_image`.**
   - O `Image.open` usa `formats=("JPEG", "PNG")`. O `DecompressionBombWarning` vira erro dentro de `warnings.catch_warnings()`, sem alterar o estado global.
   - O limite de pixels é checado depois do `open` (só o cabeçalho foi lido) e antes do `.load()`.
   - Falhas de `exif_transpose` ou de `convert("RGB")` viram `InvalidImageError`.
   - Uma entrada que não seja `bytes` nem `Path` levanta `TypeError`.
8. **`preprocess`.**
   - O default é a constante de módulo `_DEFAULT_PARAMS = PreprocessParams()`. É equivalente à assinatura da SPEC, porque a dataclass é frozen, e evita o B008 do ruff.
   - Imagem vazia (0 px) levanta `ValueError` e entrada que não é `PIL.Image.Image` levanta `TypeError`.
   - A aritmética é `float32` do começo ao fim: `/ np.float32(255)` e `mean`/`std` como arrays `float32`.
9. **Testes do autor sem `conftest.py`.** O pytest roda com `--import-mode=importlib`, que não permite importar helpers de um módulo irmão. Além disso, um `conftest.py` em `packages/preprocess/tests/` valeria também para `tests/acceptance/` do tester. Por isso os dois helpers (`encode`, `pattern_image`) ficam repetidos em `test_image.py` e `test_transform.py`.
10. **`uv.lock` dividido entre os commits.** Cada commit leva só o hunk da versão do seu pacote, para que o lock fique coerente em cada commit.

## Observações para o architect (não bloqueantes)

Nenhuma delas impede esta SPEC. Registro aqui para quem escrever a SPEC-004 e as SPECs 007 e 008.

- **O1 — Razão de aspecto extrema no `preprocess` (risco de memória na borda).**
  - O problema: a SPEC limita o total de pixels (40 M), mas não a proporção. Uma imagem de 100×400 000 (40 M px, poucos KB em PNG) seria redimensionada para 256×1 024 000, uma alocação de cerca de 786 MB antes do crop. Uma de 1×40 000 000 levaria a um alvo de 256×10 240 000 000.
  - Por que não corrigi: implementei exatamente a fórmula da SPEC, sem rejeitar proporções.
  - Sugestão: a SPEC-007/008 (ou uma revisão desta) pode definir uma proporção máxima, por exemplo lado maior / lado menor ≤ 10, no `load_image` ou na rota `/api/capture`. A página do celular já limita o lado maior a 1280 px, mas um cliente com o token pode enviar o que quiser.
- **O2 — Uso das regexes públicas com o módulo `re`.**
  - Os schemas validam com o motor de regex do Pydantic (Rust), em que `$` só casa no fim do texto. Por isso `"edge-01\n"` é rejeitado, e há teste para isso.
  - Com o `re` do Python, `re.match(DEVICE_ID_PATTERN, "edge-01\n")` **aceita**, porque `$` casa antes de um `\n` final.
  - Quem reusar as constantes na API ou nos scripts deve usar `re.fullmatch` ou validar pelo próprio schema.
  - Os valores das constantes estão fixados pelo CA-02, então não os alterei.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (contracts: 156; preprocess: 71; suíte inteira: 407 passed, 2 skipped)
- [x] `.env.example` atualizado (se houver variável nova): não se aplica, nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
