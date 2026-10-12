# SPEC-023 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-023](../../docs/specs/SPEC-023-pacotes-compartilhados-0-2.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-023-pacotes-0-2` (empilhada sobre `spec/SPEC-003-schema-banco`; diff da SPEC: `spec/SPEC-003-schema-banco...HEAD`) |
| Commits | `3caaaf0` (feat(contracts)), `d3e1679` (feat(preprocess)), mais o commit deste relatório |

## Resumo

- `qc_contracts` 0.2.0:
  - constante pública `MAX_LATENCY_MS = 2_147_483_647` em `qc_contracts.schemas`, reexportada na raiz;
  - `latency_ms` em `_InspectionBase` (e, portanto, em `InspectionCreate`, `InspectionRead` e nos itens de `BatchCreate`) passa a `Field(ge=0, le=MAX_LATENCY_MS)`. Acima do teto, o resultado é um único erro `less_than_equal` em `("latency_ms",)`;
  - README com as duas regras novas (teto e modo lax) e a linha `0.2.0` no histórico. A linha `0.1.0` foi mantida.
- `qc_preprocess` 0.2.0:
  - constante pública `MAX_ASPECT_RATIO = 10` em `qc_preprocess.image`, reexportada na raiz;
  - `load_image` começa verificando `PIL.ImageFile.LOAD_TRUNCATED_IMAGES`, lida a cada chamada. Se a flag estiver ligada, levanta `RuntimeError`, sem alterá-la;
  - logo depois da checagem de `MAX_PIXELS`, e antes do `.load()`, a função rejeita `min(w, h) == 0` e `max(w, h) > 10 * min(w, h)`, em aritmética inteira, com `InvalidImageError("... aspect ratio above 10:1")`;
  - `preprocess`, `transform.py` e `params.py` não foram tocados.
- `uv.lock`: só as versões de `qc-contracts` e `qc-preprocess` mudaram (de 0.1.0 para 0.2.0), em duas linhas.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/contracts/src/qc_contracts/__init__.py`, `packages/contracts/pyproject.toml`, `packages/preprocess/src/qc_preprocess/__init__.py`, `packages/preprocess/pyproject.toml`, `uv.lock` | `packages/contracts/tests/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version`; `packages/preprocess/tests/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version` |
| CA-02 | `qc_contracts/schemas.py`, `qc_contracts/__init__.py`, `qc_preprocess/image.py`, `qc_preprocess/__init__.py` | `packages/contracts/tests/test_schemas.py::test_max_latency_is_integer_column_max`; `packages/preprocess/tests/test_image.py::test_max_aspect_ratio_constant`; `test_smoke.py::test_public_api_is_exported` (contracts) |
| CA-03 | `qc_contracts/schemas.py` (`_InspectionBase.latency_ms`) | `test_schemas.py::test_latency_at_max_accepted`, `::test_latency_above_max_rejected[2147483648 e 2**63]` (dict e JSON, 1 erro `less_than_equal` em `("latency_ms",)`) |
| CA-04 | idem | `test_schemas.py::test_read_latency_above_max_rejected`, `::test_read_latency_at_max_accepted` |
| CA-05 | idem | `test_schemas.py::test_batch_latency_above_max_points_to_item` (3 itens, 1 erro em `("items", 1, "latency_ms")`) |
| CA-06 | `packages/contracts/README.md` | `test_smoke.py::test_readme_has_version_history_row` (linhas `0.1.0` e `0.2.0`, `MAX_LATENCY_MS`) |
| CA-07 | `qc_preprocess/image.py` | `test_image.py::test_aspect_ratio_at_limit_accepted` (100×1000, 1000×100, 1×10, 10×1), `::test_jpeg_at_aspect_ratio_limit_accepted` (40×400), `::test_preprocess_of_accepted_strip` |
| CA-08 | idem | `test_image.py::test_aspect_ratio_above_limit_rejected` (100×1001, 1001×100, 100×400 000, 20×2 000 000, 1×11, 11×1, todos PNGs reais) |
| CA-09 | idem | `test_image.py::test_aspect_ratio_checked_from_header_only`; `::test_rejected_aspect_ratio_is_never_decoded` (espião no `ImageFile.load`: não é chamado para 100×400 000, é chamado para 100×1000); `::test_pixel_limit_checked_before_aspect_ratio` |
| CA-10 | idem | `test_image.py::test_aspect_ratio_with_exif_rotation` (400×40 com Orientation 6 → `(40, 400)`; 401×40 → `aspect ratio`) |
| CA-11 | idem | `test_image.py::test_truncated_images_flag_refused` (JPEG válido, JPEG truncado, `Path("nao_existe.jpg")`, tipo errado e bytes vazios: `RuntimeError`, que não é `ValueError`, e a flag continua `True`); `::test_truncated_images_flag_read_on_every_call` |
| CA-12 | `transform.py` e `params.py` sem alteração | suíte do autor da SPEC-002 inalterada e passando. Nos dois `test_spec_002.py`, só o CA-01 falha, como esperado (ver abaixo) |
| CA-13 | todo o diff | `ruff check`, `ruff format --check` e `pytest -q` (resultado abaixo) |

Teste adicional sem CA próprio: `test_image.py::test_zero_sized_image_rejected` cobre o ramo `min(w, h) == 0`. O Pillow já recusa um IHDR com lado 0 no `Image.open` ("content is not a JPEG or PNG image"), então o teste força `_size` por um wrapper de `Image.open` para exercitar o ramo defensivo.

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest -q packages/contracts/tests packages/preprocess/tests
git diff spec/SPEC-003-schema-banco -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py   # vazio
git diff spec/SPEC-003-schema-banco -- uv.lock   # só as duas linhas de versão
```

## Resultado das checagens

- `uv run ruff check .`: All checks passed.
- `uv run ruff format --check .`: 51 files already formatted.
- `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`: **3 failed, 988 passed**. As três falhas são esperadas e se resolvem quando o tester ajustar o CA-01 da SPEC-002 (§3.1 da SPEC):
  - `packages/contracts/tests/acceptance/test_spec_002.py::test_ca01_contracts_version` (espera `"0.1.0"`, recebe `"0.2.0"`);
  - `packages/preprocess/tests/acceptance/test_spec_002.py::test_ca01_preprocess_version` (idem);
  - `tests/acceptance/test_spec_022.py::test_ca15_ruff_and_full_suite_without_ci_and_db_url`: esse teste roda a suíte inteira num subprocesso, e o subprocesso falha só por causa das duas falhas acima (`2 failed, 804 passed, 184 skipped, 1 deselected`).

## Decisões tomadas dentro do escopo da SPEC

- Os testes do autor ficaram nos arquivos que já existiam (`test_schemas.py`, `test_image.py`, `test_smoke.py`), em seções marcadas com "SPEC-023".
- Na tabela "Conteúdo" do README de contratos, a linha de `qc_contracts.schemas` passou a listar as constantes públicas `MAX_LATENCY_MS`, `MAX_BATCH_SIZE` e `MAX_FUTURE_SKEW`. As duas últimas já eram exportadas desde a 0.1.0, mas não estavam documentadas.
- A mensagem de erro da proporção segue o exemplo da SPEC: `image is {w}x{h} pixels; aspect ratio above 10:1`. A do `RuntimeError` é `PIL.ImageFile.LOAD_TRUNCATED_IMAGES is enabled; refusing to load images because truncated files would be accepted`.
- O `uv.lock` foi dividido entre os dois commits: cada commit leva a linha de versão do seu pacote.

## SPEC_ISSUE (se houver)

Nenhuma.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (contracts: 186; preprocess: 100)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
