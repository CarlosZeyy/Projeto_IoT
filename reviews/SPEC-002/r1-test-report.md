# SPEC-002 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-002](../../docs/specs/SPEC-002-pacotes-compartilhados.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `31683ae` |
| **Veredicto** | **PASS** |

Escrevi os testes de aceite primeiro, a partir da SPEC (caixa-preta). Só depois li a implementação, para os testes exploratórios.

Arquivos (marcador `acceptance`):

- `packages/contracts/tests/acceptance/test_spec_002.py`: 22 funções `test_caNN_*`, 17 `test_extra_*` (requisitos da §4 sem CA próprio) e 1 `test_bug_t01_*` (`xfail`, ver T-01). São 129 casos depois da parametrização.
- `packages/preprocess/tests/acceptance/test_spec_002.py`: 11 funções `test_caNN_*` e 17 `test_extra_*`, que viram 48 casos.

Os dois arquivos têm o mesmo nome. Com `--import-mode=importlib` (do `pyproject.toml` da raiz), o pytest coleta os dois sem conflito de módulo: na suíte inteira aparecem 129 + 48 casos de `test_spec_002.py`. Todas as imagens são geradas em memória e nenhum binário entra no Git.

Ambiente: Arch Linux, uv 0.13.0, Python 3.12.15 (`.venv`), pydantic 2.14.1, Pillow 12.3.0, numpy 2.5.4, pytest 9.1.1 e Postgres 16 em Docker (`partqc-pg`, porta 55432).

## Cobertura dos critérios de aceite

Prefixos: `C` = `packages/contracts/tests/acceptance/test_spec_002.py` e `P` = `packages/preprocess/tests/acceptance/test_spec_002.py`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `C::test_ca01_contracts_version`, `P::test_ca01_preprocess_version` | ✅ |
| CA-02 | `C::test_ca02_enum_values_grade_order_and_patterns`: valores, membros em maiúsculas, `StrEnum`, `GRADE_ORDER` como `tuple` e as 4 regexes como `str` exatas | ✅ |
| CA-03 | `C::test_ca03_grade_index_round_trip_and_bounds` | ✅ |
| CA-04 | `C::test_ca04_is_defective_rule` | ✅ |
| CA-05 | `C::test_ca05_valid_payload_normalized_to_utc_and_round_trip`: `P` com `-03:00`, o caso fixo `12:00-03:00 → 15:00Z` e a ida e volta por `model_dump(mode="json")` | ✅ |
| CA-06 | `C::test_ca06_naive_datetime_rejected`, com string e com `datetime` naive | ✅ |
| CA-07 | `C::test_ca07_future_limit` (+10 min rejeitado, +4 min aceito) | ✅ |
| CA-08 | `C::test_ca08_grade_null_iff_unknown` | ✅ |
| CA-09 | `C::test_ca09_score_and_confidence_null_iff_grade_null`, incluindo o caso simétrico `grade_confidence=null` | ✅ |
| CA-10 | `C::test_ca10_invalid_field_values_rejected`: os 17 casos do CA, cada um conferindo que o erro aponta o campo | ✅ (17/17) |
| CA-11 | `C::test_ca11_inclusive_limits_accepted`, com os dois extremos das faixas | ✅ |
| CA-12 | `C::test_ca12_extra_fields_forbidden`: `image`, `foo` e `is_defective`, todos com tipo `extra_forbidden` e `loc` no campo | ✅ (3/3) |
| CA-13 | `C::test_ca13_batch_size_and_error_location`: 0 e 101 rejeitados; 1 e 100 aceitos; todos os erros com `loc[:2] == ("items", 56)` | ✅ |
| CA-14 | `C::test_ca14_inspection_read_tolerates_extra_and_future` | ✅ |
| CA-15 | `C::test_ca15_inspection_created_status` | ✅ |
| CA-16 | `C::test_ca16_response_models_json_round_trip` (10 casos: `Page[InspectionRead]` com um item `screw` e outro `unknown`/`simulated`; `MetricsSummary` cheio e vazio; `TimeseriesPoint` cheio e vazio; `SpcResponse` com o exemplo de §3.4 e o caso vazio com `message`; `LotSummary`; `HealthResponse` ok e degraded). Cada caso passa por `model_validate_json` e `model_validate`, e o `model_dump(mode="json")` tem de ser igual à entrada. Também `C::test_ca16_health_rejects_unknown_status` e `C::test_ca16_spc_types` | ✅ (12/12) |
| CA-17 | `C::test_ca17_labels_match_enums_and_are_immutable` (4 mapeamentos: `MappingProxyType`, uma chave por membro, valores de §3.1, atribuição levanta `TypeError`) e `C::test_ca17_grade_label_examples` | ✅ (5/5) |
| CA-18 | `C::test_ca18_contracts_imports_only_stdlib_without_io_and_pydantic`: análise `ast` de todos os `.py` do pacote instalado (`collections` só como `collections.abc`; também procura chamadas `open`/`__import__`), mais `importlib.metadata.requires("qc-contracts") == {pydantic}` | ✅ |
| CA-19 | `P::test_ca19_params_defaults_validation_and_json`: padrões, `frozen`, os dois `ValueError` do CA, ida e volta JSON (padrão e customizado), JSON sem `crop` e JSON com `"resize"` | ✅ |
| CA-20 | `P::test_ca20_solid_color_values_shape_dtype_contiguity`. Valores obtidos: `2.2489083`, `-2.0357141` e `-0.91555554`, constantes em todos os pixels | ✅ |
| CA-21 | `P::test_ca21_exact_center_crop_without_resampling`: canal R com tolerância `1e-6`; G e B também conferidos | ✅ |
| CA-22 | `P::test_ca22_bit_identical_determinism`: 64×48 por fórmula, duas execuções iguais; `load_image(PNG)` duas vezes igual e igual à imagem em memória (PNG sem perdas); também com parâmetros não padrão | ✅ |
| CA-23 | `P::test_ca23_exif_orientation_and_modes_to_rgb`: JPEG 40×20 com `Orientation=6` (o teste confere que a tag está no arquivo) sai `(20, 40)` em `RGB`; PNG `RGBA` e `L` saem em `RGB` | ✅ |
| CA-24 | `P::test_ca24_invalid_images_rejected` (5 casos). O GIF 10×10 e o PNG 8000×8000 são arquivos **válidos e completos**, e o teste confere isso com o Pillow antes de chamar `load_image`; assim, a rejeição vem da regra (formato e limite de pixels), não de um arquivo quebrado. Também `P::test_ca24_missing_path` (`Path("nao_existe.jpg")` com `cwd` num diretório temporário) e `P::test_ca24_invalid_image_error_is_value_error` | ✅ (7/7) |
| CA-25 | `P::test_ca25_preprocess_requires_rgb` (`L`, `RGBA`, `P`, `CMYK`, `1`) | ✅ (5/5) |
| CA-26 | `P::test_ca26_no_torch_and_only_numpy_pillow`: processo novo (`sys.executable -c`), sem `torch`, `torchvision` nem `timm` em `sys.modules`; `requires("qc-preprocess") == {numpy, pillow}` | ✅ |
| CA-27 | `C::test_ca27_readme_version_history`: o título "Histórico de versões" é seguido de uma tabela com a linha `0.1.0`, `2026-10` e `SPEC-002` | ✅ |

Os 27 CAs têm teste, e todos passam.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
41 files already formatted

# sem TEST_DATABASE_URL e sem CI
$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
SKIPPED [1] tests/acceptance/test_spec_001.py:174: TEST_DATABASE_URL not set
SKIPPED [1] tests/test_db_smoke.py:11: TEST_DATABASE_URL not set
XFAIL ...test_bug_t01_out_of_range_datetime_raises_validation_error[create-year1]
XFAIL ...test_bug_t01_out_of_range_datetime_raises_validation_error[create-year9999]
XFAIL ...test_bug_t01_out_of_range_datetime_raises_validation_error[read-received-year9999]
581 passed, 2 skipped, 3 xfailed in 7.60s

# com TEST_DATABASE_URL (Postgres 16 local) e CI=true, como no CI
$ CI=true TEST_DATABASE_URL=postgresql://...:55432/partqc_test uv run pytest -q
583 passed, 3 xfailed in 7.83s

# só os aceites da SPEC-002 (os dois arquivos homônimos na mesma sessão)
$ uv run pytest -q -m acceptance packages/contracts/tests/acceptance/test_spec_002.py \
    packages/preprocess/tests/acceptance/test_spec_002.py
174 passed, 3 xfailed in 0.89s
```

Os 3 `xfailed` documentam o bug T-01. Os testes estão marcados `xfail(strict=False, raises=OverflowError)`: afirmam o comportamento esperado, só "falham como esperado" com o `OverflowError` atual e vão aparecer como `XPASS` quando o bug for corrigido.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média | §4.3 (`inspected_at`/datas UTC; nenhum CA específico) | 1. `InspectionCreate.model_validate({**P, "inspected_at": "0001-01-01T00:00:00+05:00"})` (vale também para `model_validate_json`). 2. Repetir com `"9999-12-31T23:59:59-05:00"`. 3. Repetir com `InspectionRead` em `received_at`, ou com `TimeseriesPoint.bucket_start` | `ValidationError`, que a API (SPEC-004) devolve como 422 | `OverflowError: date value out of range`, uma exceção crua que escapa da validação. Na rota do FastAPI isso vira 500, não 422. Causa: `_to_utc` (`value.astimezone(UTC)`) no `AfterValidator` de `UtcDatetime`, em `qc_contracts/schemas.py`, só é convertido em erro de validação quando a exceção é `ValueError`/`AssertionError`. O caso `"9999-12-31T23:59:59Z"` já dá `ValidationError` corretamente (pela regra dos 5 min) |

Teste que reproduz: `C::test_bug_t01_out_of_range_datetime_raises_validation_error` (3 casos, `xfail`).

O T-01 não viola nenhum CA, então não muda o veredicto pelo critério de PASS. Mesmo assim, recomendo corrigir antes do merge ou, no máximo, antes da SPEC-004. Um cliente com chave de dispositivo consegue gerar um 500 na ingestão com um único item.

## Testes exploratórios (além dos critérios)

Além dos `test_extra_*` versionados, rodei scripts no scratchpad. Nenhum deles entra no Git.

### `qc_contracts`

Comportamento correto (também coberto por `test_extra_*` nos arquivos de aceite):

- reexportação de toda a API pública na raiz do pacote;
- `HealthResponse` com `status=ok`+`db=error` ou `degraded`+`ok` → erro;
- limites de `Page` (`total=-1`, `limit=0`, `offset=-1` → erro);
- `InspectionRead` mantém as invariantes de grau, rejeita data naive, exige `received_at` e `is_defective` e normaliza `received_at` para UTC;
- `BatchCreate` com campo extra → `extra_forbidden`; `BatchResult` faz ida e volta;
- todos os modelos de resposta ignoram campo desconhecido;
- `NaN` e `±inf` em `type_confidence`, `grade_confidence` e `grade_score` são rejeitados, tanto por objeto Python quanto por JSON (`NaN`, `Infinity`, `"nan"`, `"inf"`);
- `latency_ms` com `1.5`, `"abc"` ou `None` → erro;
- regexes:
  - newline no fim (`"edge-01\n"` e equivalentes nos quatro campos) → erro;
  - unicode (`"ééééé"`, `"Lóte"`, `"L-００１"` com dígitos de largura total) → erro;
  - tamanhos 33/41/2 → erro;
  - limites exatos 3/32/1/40 → aceitos;
- UUID nil, v1, v3, v5, v7, variante não RFC com nibble 4 e `"not-a-uuid"` → `uuid_version`/erro;
- `grade="FAIR"` e `source="Live"` (caixa diferente) → erro;
- cada um dos 14 campos de `P` é obrigatório (remover qualquer um → erro);
- offsets `Z` e `+05:30` normalizados para o mesmo instante;
- a regra dos 5 min usa o instante, não a hora local: +4 min escrito em `+14:00` é aceito, e +6 min em `-12:00` é rejeitado;
- `grade_from_index` com `True`, `1.0`, `"1"` ou `None` → `ValueError`;
- `is_defective` com `"POOR"`, `""`, `" poor"`, `"unknown"`, `3`, `[]` ou `ObjectType.UNKNOWN` → `ValueError`;
- enums passados diretamente (e `uuid.UUID`) são aceitos e serializados como string.

Observações, que não são bugs pela SPEC:

- **Coerção do modo lax do Pydantic nos modelos de entrada.** Ela aceita:
  - `needs_review="yes"`/`1` → `True`;
  - `latency_ms=True` → `1` e `120.0` → `120`;
  - `type_confidence=True` → `1.0`;
  - `grade_score="2.1"` (inclusive via JSON);
  - `inspected_at` como inteiro epoch → UTC;
  - `latency_ms=2**63` (acima do `bigint` do Postgres, o que importa para a SPEC-003/004).

  A SPEC não pede modo estrito. Sugiro ao architect avaliar `strict` em `InspectionCreate` e um teto para `latency_ms`.
- **Modelos mutáveis sem `validate_assignment`.** `m.type_confidence = 9.0` depois da validação é aceito, e `model_construct` ignora as regras. A SPEC não exige `frozen`.
- **Campos de resposta que a SPEC deixa para a SPEC-005.** `InspectionRead.is_defective` não é conferido contra `grade`, as contagens de resposta aceitam valores negativos e `LotSummary.sources` aceita repetição e qualquer ordem. O dev-report registra essas três escolhas (decisão 4).
- **UUID em outros formatos.** Maiúsculas, sem hífens e `urn:uuid:` são aceitos e normalizados para a forma canônica. Isso é bom para a idempotência (R-05), porque o ID chega normalizado.

### `qc_preprocess`

Comportamento correto:

- `load_image`:
  - aceita JPEG progressivo, CMYK e PNG `P`/`LA`/`1`, todos devolvidos em `RGB`;
  - aplica o EXIF `Orientation=8` em JPEG e `Orientation=6` em PNG (chunk `eXIf`);
  - ignora sem erro uma orientação inválida (99) e um APP1 Exif corrompido;
  - aceita APNG (primeiro quadro) e JPEG/PNG com bytes extras depois do fim;
  - rejeita com `InvalidImageError`: BMP, WEBP, TIFF e ICO, além de SVG, PDF, PNG com CRC errado, PNG sem IDAT, PNG truncado e JPEG cortado em 50% e em 95% (inclusive só sem o marcador EOI);
  - limite de pixels: 8000×5000 (exatamente 40 M) é aceito; 8000×5001 e 20000×10000 (acima do limite de bomba do Pillow) são rejeitados;
  - o conteúdo decide, não a extensão: um PNG salvo como `.jpg` é aceito, e um GIF salvo como `.png` é rejeitado;
  - os mesmos bytes, lidos de `bytes` ou de `Path`, dão o mesmo tensor;
  - funciona com caminho que tem acento, espaço e unicode;
  - `bytearray`, `memoryview` e `str` → `TypeError`;
  - um diretório passado como `Path` → `FileNotFoundError`;
- `PreprocessParams`:
  - `0`, negativos, `bool`, `float`, `np.int64`, `"256"`, 2 ou 4 valores em `mean`/`std`, `std` negativo, `NaN` e `inf` → `ValueError`;
  - `from_json` com arquivo vazio, texto que não é JSON, `[]`, `mean` com 2 valores ou `NaN` → `ValueError`;
  - `to_json` grava exatamente `{"resize_shorter": 256, "crop": 224, "mean": [...], "std": [...]}`;
- `preprocess`:
  - confere o truncamento do lado maior (300×401 → 256×342) e a origem do crop contra uma reimplementação manual dos passos da SPEC, com tolerância `1e-6`;
  - confere a origem do crop sem reamostragem numa imagem paisagem de lados ímpares;
  - não altera a imagem de entrada;
  - `crop == resize_shorter` é aceito;
  - imagens 1×1 e 1×3 funcionam;
  - 0×0 → `ValueError`;
  - entrada que não é imagem → `TypeError`;
- desempenho: `preprocess` de 4000×3000 levou 0,04 s, e `load_image` de um PNG de 1 bit com 8000×5000 levou 0,15 s.

Riscos e observações, que não são bugs pela SPEC:

- **R-A (média, segurança da borda; confirma a O1 do dev-report).** Uma proporção extrema dentro do limite de 40 M pixels gasta memória desproporcional no `preprocess`, porque a fórmula da SPEC redimensiona antes de cortar. Medi em subprocesso com `RLIMIT_AS` de 3 GB:

  | Imagem | Tamanho do PNG | Resultado |
  |---|---|---|
  | 100×40 000 | 623 B | pico de 194 MB |
  | 100×400 000 | 5,5 KB | pico de 1,6 GB e 2,2 s |
  | 20×2 000 000 | 7,8 KB | `MemoryError` ao atingir o teto de 3 GB |

  Sem teto, um único upload pequeno pode derrubar o notebook da borda por OOM. A implementação segue a SPEC à risca, então não registro como bug. Recomendo que o architect defina uma proporção máxima (por exemplo, lado maior / lado menor ≤ 10) no `load_image` ou na rota `/api/capture` (SPEC-007/008), ou que revise esta SPEC.
- **R-B (baixa).** `ImageFile.LOAD_TRUNCATED_IMAGES` é global no Pillow. Se outro módulo do processo o puser em `True`, um JPEG truncado na metade passa pelo `load_image` (verifiquei). O código não força o valor localmente.
- **R-C (baixa).** Um PNG de 16 bits em tons de cinza (`I;16`) é convertido com saturação: o valor 40000/65535 vira 255, e a imagem sai branca. A página do celular reencoda em JPEG de 8 bits, então isso não afeta o fluxo normal.

## SPEC_ISSUE (se houver)

Nenhum. Todos os CAs são testáveis como estão escritos. O R-A é uma lacuna de requisito (falta um limite de proporção), não uma ambiguidade nem uma contradição. Fica como recomendação ao architect.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
