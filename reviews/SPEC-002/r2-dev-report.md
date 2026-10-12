# SPEC-002 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-002](../../docs/specs/SPEC-002-pacotes-compartilhados.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-002-pacotes-compartilhados` |
| Commits | `9f34958` (fix(contracts)), `6dd7c8d` (docs(contracts)), `2b97ca6` (fix(preprocess)), mais o commit deste relatório |

## Resumo

A r2 trata os achados que o review da r1 destinou ao developer:

- **RV-01 (alta, bloqueante; T-01 do tester).** `_to_utc` agora captura o `OverflowError` de `astimezone(UTC)` e o relança como `ValueError("datetime out of range after UTC normalization")`. O Pydantic o transforma em `ValidationError` (tipo `value_error`, `loc` no campo). Como `UtcDatetime` é o tipo único de data, a correção vale para `InspectionCreate`, `BatchCreate` (o erro aponta `items.N.inspected_at`), `InspectionRead` (`inspected_at` e `received_at`), `TimeseriesPoint`, `SpcPoint` e `LotSummary`.
- **RV-04 (baixa, opcional).** O `packages/contracts/README.md` passou a exigir `re.fullmatch` (ou o próprio schema / `TypeAdapter`) ao reusar as regexes públicas, nunca `re.match`/`re.search`.
- **RV-07 (baixa, opcional).** `load_image` relança `MemoryError` antes do tratamento genérico, em vez de transformá-lo em `InvalidImageError`.

Nenhum CA, regra ou valor de contrato mudou. As versões continuam `0.1.0`: a correção é parte da entrega inicial, que ainda não chegou à `main` (o CA-01 fixa `0.1.0`).

## Rastreabilidade (critério de aceite → implementação)

Testes em `packages/contracts/tests/` (abreviado `ct/`) e `packages/preprocess/tests/` (abreviado `pt/`). As linhas dos CAs repetem a r1, porque o código desses pontos não mudou. As duas últimas linhas são novas nesta rodada.

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
| §4.3 datas com fuso normalizadas para UTC, sem CA próprio (RV-01/T-01, r2) | `qc_contracts/schemas.py` (`_to_utc`, usado por `UtcDatetime` em todas as datas) | `ct/test_schemas.py::test_create_overflowing_datetime_is_validation_error`, `::test_create_overflowing_datetime_object_is_validation_error`, `::test_batch_with_overflowing_datetime_points_to_item`, `::test_read_overflowing_datetime_is_validation_error`, `::test_response_overflowing_datetime_is_validation_error` (`TimeseriesPoint`, `SpcPoint`, `LotSummary`), `::test_extreme_datetimes_inside_utc_range_accepted` |
| §4.5 `load_image`, sem CA próprio (RV-07, r2) | `qc_preprocess/image.py` | `pt/test_image.py::test_memory_error_during_normalization_propagates`, `::test_other_normalization_failure_is_invalid_image` |

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| r1-review RV-01 / r1-test T-01 (alta) | `9f34958`: em `qc_contracts/schemas.py`, `_to_utc` faz `try: value.astimezone(UTC) except OverflowError: raise ValueError(...) from exc`. Testes do autor novos (22 casos): `0001-01-01T00:00:00+05:00` e `9999-12-31T23:59:59-05:00` em `InspectionCreate` (por `model_validate`, por `model_validate_json` e com um objeto `datetime`), num `BatchCreate` de 3 itens (o erro aponta só `("items", 1, "inspected_at")`), em `InspectionRead` (`inspected_at` e `received_at`) e nos modelos de resposta (`TimeseriesPoint.bucket_start`, `SpcPoint.started_at`/`ended_at`, `LotSummary.started_at`/`ended_at`). Cada caso confere `ValidationError` com um único erro, do tipo `value_error`, no `loc` do campo. Também há o teste de não regressão: os extremos que **cabem** em UTC (`0001-01-01T00:00:00Z`, `0001-01-01T05:00:00+05:00`, `9999-12-31T23:59:59Z`, `9999-12-31T18:59:59-05:00`) são aceitos e normalizados. Conferi que os 18 casos de rejeição falham sem a correção. Os 3 testes `xfail` do tester (`test_bug_t01_*`) agora aparecem como `XPASS`. A troca do `xfail` por teste normal é do tester (R-07), e não toquei em `tests/acceptance/`. |
| r1-review RV-04 (baixa, opcional) | `6dd7c8d`: parágrafo no `packages/contracts/README.md` exigindo `re.fullmatch` (ou validação pelo schema / `TypeAdapter`) ao reusar `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN` e `SHA256_PATTERN`, com o exemplo `"edge-01\n"`. As constantes continuam iguais (CA-02). A nota nas SPECs 004, 007 e 014 continua com o architect. O mesmo commit acrescenta às "Regras principais" do README que uma data fora da faixa depois da conversão para UTC é rejeitada com `ValidationError`. |
| r1-review RV-07 (baixa, opcional) | `2b97ca6`: em `qc_preprocess/image.py`, `except MemoryError: raise` antes do `except Exception`, e a docstring de `load_image` registra isso. O `img.load()` já deixava `MemoryError` passar, porque só captura `OSError`, `SyntaxError` e `ValueError`. Testes do autor: `MemoryError` em `exif_transpose` e em `convert` se propaga (os dois falham sem a correção); qualquer outra falha nesse trecho continua virando `InvalidImageError`. |
| r1-review RV-02 / SPEC_ISSUE-01 (média) | Nada mudou, como pede o review: o limite de proporção é decisão do architect. |
| r1-review RV-03 / SPEC_ISSUE-02 (média) | Nada mudou: o teto de `latency_ms` é decisão do architect. |
| r1-review RV-05, RV-06 e observações (R-C, `frozen`) | Nada mudou: ficam com o architect, numa revisão futura. |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q packages/contracts packages/preprocess
uv run pytest -q          # suíte inteira: 606 passed, 2 skipped, 3 xpassed
```

Reprodução direta do T-01, que agora levanta `ValidationError`:

```bash
uv run python -c "from qc_contracts import TimeseriesPoint as T; T.model_validate({'bucket_start': '0001-01-01T00:00:00+05:00', 'total': 0, 'defective': 0, 'defect_rate': None})"
```

## Decisões tomadas dentro do escopo da SPEC

1. **Versão mantida em `0.1.0`.** A correção do RV-01 não muda o contrato descrito no §3, só faz o pacote cumprir o que o §4.3 já pede (validar a data). Como a `0.1.0` ainda não foi integrada à `main` e o CA-01 fixa esse número, não criei uma `0.1.1` nem uma linha nova no histórico do README.
2. **Mensagem e tipo do erro.** Usei a mensagem sugerida pelo reviewer. O erro é `value_error` com `loc` no campo, o mesmo formato das outras regras de data, para a SPEC-004 devolver um 422 comum.
3. **Mock só nos testes do RV-07.** Não dá para provocar falta de memória de forma confiável num teste. Por isso os dois testes do RV-07 substituem `ImageOps.exif_transpose` ou `Image.Image.convert` por uma função que levanta `MemoryError` (via `monkeypatch`, que desfaz a troca no fim). O resto da suíte continua sem mock.

## SPEC_ISSUE (se houver)

Nenhum novo. Os SPEC_ISSUE-01 (proporção máxima da imagem) e SPEC_ISSUE-02 (teto de `latency_ms`) do review da r1 continuam com o architect e não bloqueiam esta SPEC.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (41 arquivos formatados)
- [x] Testes unitários do autor passando (contracts: 178; preprocess: 74; suíte inteira: 606 passed, 2 skipped por falta de `TEST_DATABASE_URL`, 3 xpassed, que são os `xfail` do T-01 agora corrigido)
- [x] `.env.example` atualizado (se houver variável nova): não se aplica, nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
