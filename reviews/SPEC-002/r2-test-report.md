# SPEC-002 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-002](../../docs/specs/SPEC-002-pacotes-compartilhados.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `cbd8e84` |
| **Veredicto** | **PASS** |

A r2 traz três correções do developer: RV-01/T-01 (`9f34958`), RV-04 (`6dd7c8d`) e RV-07 (`2b97ca6`). Nenhum CA mudou. Por isso, mantive os testes `test_caNN_*` da r1, que eu tinha escrito a partir da SPEC (caixa-preta), e rodei todos de novo. Nesta rodada:

- **T-01:** troquei o `xfail` de `test_bug_t01_*` (3 casos, que apareciam como `XPASS`) por testes de regressão normais, sem `xfail`. Também ampliei a cobertura para todos os modelos com data, o lote, o modelo aninhado e os extremos que ainda cabem em UTC.
- **RV-07:** acrescentei um teste de aceite sem mock. Ele roda num processo novo, com um teto real de memória.

Arquivos (marcador `acceptance`):

- `packages/contracts/tests/acceptance/test_spec_002.py`: 22 funções `test_caNN_*` e 21 `test_extra_*`, das quais 4 são novas, para o T-01. Nenhum `xfail`. São **165 casos** depois da parametrização (eram 129).
- `packages/preprocess/tests/acceptance/test_spec_002.py`: 11 funções `test_caNN_*` e 18 `test_extra_*`, das quais 1 é nova, para o RV-07. São **50 casos** (eram 48).

Ambiente: Arch Linux, uv 0.13.0, Python 3.12.15 (`.venv`), pydantic 2.14.1, Pillow 12.3.0, numpy 2.5.4, pytest 9.1.1, FastAPI 0.143.0 (só nos testes exploratórios) e Postgres 16 em Docker (`partqc-pg`, porta 55432).

## Cobertura dos critérios de aceite

Prefixos: `C` = `packages/contracts/tests/acceptance/test_spec_002.py` e `P` = `packages/preprocess/tests/acceptance/test_spec_002.py`. Os testes dos CAs são os da r1 (veja o detalhamento no [r1-test-report](r1-test-report.md)), rodados de novo contra `cbd8e84`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `C::test_ca01_contracts_version`, `P::test_ca01_preprocess_version` | ✅ |
| CA-02 | `C::test_ca02_enum_values_grade_order_and_patterns` | ✅ |
| CA-03 | `C::test_ca03_grade_index_round_trip_and_bounds` | ✅ |
| CA-04 | `C::test_ca04_is_defective_rule` | ✅ |
| CA-05 | `C::test_ca05_valid_payload_normalized_to_utc_and_round_trip` | ✅ |
| CA-06 | `C::test_ca06_naive_datetime_rejected` | ✅ |
| CA-07 | `C::test_ca07_future_limit` | ✅ |
| CA-08 | `C::test_ca08_grade_null_iff_unknown` | ✅ |
| CA-09 | `C::test_ca09_score_and_confidence_null_iff_grade_null` | ✅ |
| CA-10 | `C::test_ca10_invalid_field_values_rejected` | ✅ (17/17) |
| CA-11 | `C::test_ca11_inclusive_limits_accepted` | ✅ |
| CA-12 | `C::test_ca12_extra_fields_forbidden` | ✅ (3/3) |
| CA-13 | `C::test_ca13_batch_size_and_error_location` | ✅ |
| CA-14 | `C::test_ca14_inspection_read_tolerates_extra_and_future` | ✅ |
| CA-15 | `C::test_ca15_inspection_created_status` | ✅ |
| CA-16 | `C::test_ca16_response_models_json_round_trip`, `C::test_ca16_health_rejects_unknown_status`, `C::test_ca16_spc_types` | ✅ (12/12) |
| CA-17 | `C::test_ca17_labels_match_enums_and_are_immutable`, `C::test_ca17_grade_label_examples` | ✅ (5/5) |
| CA-18 | `C::test_ca18_contracts_imports_only_stdlib_without_io_and_pydantic` | ✅ |
| CA-19 | `P::test_ca19_params_defaults_validation_and_json` | ✅ |
| CA-20 | `P::test_ca20_solid_color_values_shape_dtype_contiguity` | ✅ |
| CA-21 | `P::test_ca21_exact_center_crop_without_resampling` | ✅ |
| CA-22 | `P::test_ca22_bit_identical_determinism` | ✅ |
| CA-23 | `P::test_ca23_exif_orientation_and_modes_to_rgb` | ✅ |
| CA-24 | `P::test_ca24_invalid_images_rejected`, `P::test_ca24_missing_path`, `P::test_ca24_invalid_image_error_is_value_error` | ✅ (7/7) |
| CA-25 | `P::test_ca25_preprocess_requires_rgb` | ✅ (5/5) |
| CA-26 | `P::test_ca26_no_torch_and_only_numpy_pillow` | ✅ |
| CA-27 | `C::test_ca27_readme_version_history` | ✅ |

Os 27 CAs têm teste, e todos passam.

### Conferência das correções da r2

| Achado da r1 | Teste de aceite | Resultado na r2 | Contra o código da r1 (`4a5f782`) |
|---|---|---|---|
| T-01 / RV-01 (alta): `OverflowError` cru ao normalizar para UTC | `C::test_extra_t01_out_of_range_after_utc_is_validation_error` (33 casos): 11 combinações de modelo/campo × 3 formas de entrada (`model_validate` com string, `model_validate_json` e objeto `datetime`). Cobre `InspectionCreate.inspected_at`, `InspectionRead.inspected_at`/`received_at`, `TimeseriesPoint.bucket_start`, `SpcPoint.started_at`/`ended_at` e `LotSummary.started_at`/`ended_at`, com `0001-01-01T00:00:00+05:00` e `9999-12-31T23:59:59-05:00`. Cada caso exige `ValidationError` com **um único** erro, do tipo `value_error`, com `loc == (campo,)` | ✅ 33/33 | ❌ 33/33 falham (`OverflowError`) |
| idem, no lote | `C::test_extra_t01_batch_points_to_the_bad_item_only`: lote de 3 itens com o 2º ruim; um único erro, em `("items", 1, "inspected_at")` | ✅ | ❌ |
| idem, em modelo aninhado | `C::test_extra_t01_nested_spc_point_is_validation_error`: `SpcResponse` com `points[0].started_at` fora da faixa; erro em `("points", 0, "started_at")` | ✅ | ❌ |
| idem, não regressão | `C::test_extra_t01_extremes_inside_utc_range_still_accepted` (4 casos): `0001-01-01T00:00:00Z`, `0001-01-01T05:00:00+05:00`, `9999-12-31T23:59:59Z` e `9999-12-31T18:59:59-05:00` continuam aceitos em `InspectionRead.received_at` e `LotSummary.started_at`, normalizados para o instante UTC certo (`tzinfo == UTC`). Os dois de ano 1 também passam em `InspectionCreate`; os de 9999 caem, corretamente, na regra dos 5 min | ✅ 4/4 | ✅ (já passavam) |
| RV-07 (baixa): `MemoryError` virava `InvalidImageError` | `P::test_extra_rv07_memory_error_propagates_from_load_image` (2 casos), sem mock. Um processo novo gera um PNG `L` de 8000×5000, recebe `RLIMIT_AS` = memória atual + 60 MB ou + 120 MB (abaixo dos ~160 MB que decodificar e converter exigem) e chama `load_image`; o teste exige `MemoryError`. Só roda no Linux (`skipif`), que é o sistema do CI | ✅ 2/2 (estável em 3 execuções seguidas) | ❌ 2/2 falham: `InvalidImageError` causado por `MemoryError` |
| RV-04 (baixa): `re.match` × `re.fullmatch` | Sem teste versionado, porque é só documentação. O `packages/contracts/README.md` (linha 57) traz a regra e o exemplo `"edge-01\n"`. Conferi que, nas quatro constantes, `re.fullmatch(p, v + "\n")` é `False` e `re.match(p, v + "\n")` é `True`, como o README diz. O CA-02 continua passando (constantes inalteradas) | ✅ | n/a |

Para comparar com a r1, rodei os mesmos arquivos de aceite numa `git worktree` temporária em `4a5f782`, criada no scratchpad e removida depois.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
41 files already formatted

# sem TEST_DATABASE_URL e sem CI
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q -rsxX
SKIPPED [1] tests/acceptance/test_spec_001.py:174: TEST_DATABASE_URL not set
SKIPPED [1] tests/test_db_smoke.py:11: TEST_DATABASE_URL not set
647 passed, 2 skipped in 8.21s

# com TEST_DATABASE_URL (Postgres 16 local) e CI=true, como no CI
$ CI=true TEST_DATABASE_URL=postgresql://...:55432/partqc_test uv run pytest -q -rsxX
649 passed in 8.43s

# só os aceites da SPEC-002 (os dois arquivos homônimos na mesma sessão)
$ uv run pytest -q -m acceptance packages/contracts/tests/acceptance/test_spec_002.py \
    packages/preprocess/tests/acceptance/test_spec_002.py
215 passed in 1.74s

# cobertura dos dois pacotes (testes do autor + aceite, no mesmo processo)
$ uv run pytest -q --cov=qc_contracts --cov=qc_preprocess packages/contracts packages/preprocess
qc_contracts 100% (schemas.py 130/130)
qc_preprocess/image.py 93% (faltam 43-44 e 55, ramos defensivos de OSError no cabeçalho
                            e de bomba no .load()); total dos dois pacotes 99%
467 passed
```

Antes desta rodada, a suíte dava `606 passed, 2 skipped, 3 xpassed`. Agora não há nenhum `xfail` nem `xpass`: saíram os 3 casos `xfail` e entraram 39 do T-01 e 2 do RV-07 (606 + 41 = 647).

## Bugs encontrados

Nenhum bug novo nesta rodada.

| ID | Severidade | Critério | Situação na r2 |
|---|---|---|---|
| T-01 (r1) | média (alta no review, RV-01) | §4.3 | **Corrigido** e coberto pelos testes `test_extra_t01_*` acima. Ponta a ponta: numa rota FastAPI mínima (`body: InspectionCreate` e `body: BatchCreate`), os dois payloads da r1 agora dão **422** com `loc` `["body", "inspected_at"]` e `["body", "items", 2, "inspected_at"]`; na r1 davam 500 |

## Testes exploratórios (além dos critérios)

Scripts no scratchpad, que não entram no Git.

### Datas, depois da correção do T-01

Rodei cada caso com `model_validate` e com `model_validate_json`:

- Limites finos da conversão para UTC, todos rejeitados com `value_error` "datetime out of range after UTC normalization":
  - `0001-01-01T00:00:00+23:59`;
  - `0001-01-01T00:00:00.000001+00:01` e `0001-01-01T00:00:59+00:01`;
  - `9999-12-31T23:59:59.999999-00:01` e `9999-12-31T23:59:59-23:59`;
  - `datetime.min`/`datetime.max` com offset de ±1 h, passados como objeto.
- Aceitos: `0001-01-01T00:01:00+00:01`, o primeiro instante que cabe (vira `0001-01-01T00:00Z`), e `-00:00`.
- Rejeitados pelo próprio parser do Pydantic, com `ValidationError`: offset `+24:00`, `+99:00` ou com segundos (`+05:30:15`), ano 0, ano 10000, 30 de fevereiro, hora 25 e dígitos de largura total.
- Um `tzinfo` cujo `utcoffset` levanta `OverflowError` vira `ValidationError` (`datetime_object_invalid`), sem exceção crua.
- Mensagem do erro: `e.json()` serializa sem problema.

Observações, que não são bugs pela SPEC:

- O sinal de menos unicode (U+2212) é aceito no offset (`10:00:00−03:00` → `13:00Z`). A ISO 8601 permite esse sinal.
- Um epoch inteiro grande é interpretado como **milissegundos** pela heurística do Pydantic: `-62135596800` vira `1968-01-12T20:06:43.2Z`, e não o ano 1. Isso é parte do modo lax, já registrado no RV-05 (com o architect). A borda manda ISO 8601, não epoch.

### `load_image`

- **`MemoryError` sob teto real de memória (RV-07).** PNG `L`, `P` e `1` de 8000×5000, com `RLIMIT_AS` = memória atual + 10…260 MB. Em todos os tetos o resultado foi `MemoryError` propagado ou sucesso; **nunca** `InvalidImageError`. Pelo traceback, o erro nasceu em `ImageOps.exif_transpose` (cópia) com +40 MB e em `Image.convert` com +120…190 MB. Ou seja, os dois pontos que a correção cobre foram atingidos de verdade. Com +195 MB ou mais, a imagem é carregada normalmente.
- **Cabeçalhos corrompidos.** PNG só com a assinatura, IHDR curto, IHDR com 0×0, profundidade de bit inválida e tipo de cor inválido; JPEG só com SOI, SOF com lixo e SOF com dimensões 0. Todos → `InvalidImageError`.
- **Fuzzing.** 300 variações de um PNG e de um JPEG válidos, com 1 a 6 bytes trocados aleatoriamente (semente fixa), passando por `load_image` e `preprocess`: 219 → `InvalidImageError` e 89 → sucesso. **Nenhuma** exceção de outro tipo.

### Riscos da r1 ainda abertos (com o architect, não bloqueiam esta SPEC)

- **R-A / RV-02 / SPEC_ISSUE-01:** consumo de memória com proporção extrema. Nada mudou, como o review pediu.
- **RV-03 / SPEC_ISSUE-02:** teto de `latency_ms` contra a coluna `integer`. Nada mudou.
- **R-B / RV-06:** `LOAD_TRUNCATED_IMAGES` global.
- **R-C:** PNG `I;16` saturado.

## SPEC_ISSUE (se houver)

Nenhum novo. Todos os CAs continuam testáveis como estão escritos. Os SPEC_ISSUE-01 e 02 do review da r1 seguem com o architect e não afetam o veredicto desta SPEC.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
