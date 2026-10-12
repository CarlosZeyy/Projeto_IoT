# SPEC-024 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-024](../../docs/specs/SPEC-024-preprocess-0-3-scans-jpeg.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-024-preprocess-0-3` (empilhada sobre `docs/pendencias-pos-003-023`; diff da SPEC: `docs/pendencias-pos-003-023...HEAD`) |
| Commits | `36f7f2c` (feat(preprocess)), mais o commit deste relatório |

## Resumo

- `qc_preprocess` 0.3.0:
  - constante pública `MAX_JPEG_SCANS: int = 64` em `qc_preprocess.image`, reexportada em `qc_preprocess` (e em `__all__`), com comentário citando o SEC-01 e a contagem conservadora;
  - em `load_image`, logo depois de `empty image data` e antes do `Image.open`: se `data.startswith(b"\xff\xd8\xff")` e `data.count(b"\xff\xda") > MAX_JPEG_SCANS`, levanta `InvalidImageError(f"too many JPEG scans: {n} scan markers, limit {MAX_JPEG_SCANS}")`. A contagem percorre o arquivo inteiro, sem interpretar segmentos (§4.1 e §7);
  - a docstring de `load_image` lista a condição nova;
  - `transform.py` e `params.py` não foram tocados (`git diff docs/pendencias-pos-003-023 -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py` vazio).
- `pyproject.toml` e `__version__` em `0.3.0`; no `uv.lock`, só a linha `version` do `qc-preprocess` mudou (`uv sync --all-packages --locked` aceita o lock).
- `test_smoke.py`: expectativa de versão `0.3.0`. Testes novos em `packages/preprocess/tests/test_jpeg_scans.py`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `packages/preprocess/src/qc_preprocess/__init__.py`, `packages/preprocess/pyproject.toml`, `uv.lock` | `packages/preprocess/tests/test_smoke.py::test_import_and_version`, `::test_pyproject_version_matches_dunder_version`; `packages/contracts/tests/test_smoke.py::test_import_and_version` (contracts continua 0.2.0) |
| CA-02 | `qc_preprocess/image.py`, `qc_preprocess/__init__.py` | `test_jpeg_scans.py::test_constant_value_and_reexport` |
| CA-03 | `qc_preprocess/image.py` | `test_jpeg_scans.py::test_common_jpegs_accepted` (baseline RGB 64×48, progressivo RGB 640×480, progressivo L 640×480) |
| CA-04 | idem | `test_jpeg_scans.py::test_limit_is_inclusive` (COM de 63 pares: aceito e `preprocess(...).tobytes()` igual ao JPEG sem COM), `::test_one_above_limit_rejected` (COM de 64 pares: `JPEG scans`) |
| CA-05 | idem | `test_jpeg_scans.py::test_repeated_scans_rejected[65 e 1000]`; `::test_repeated_scans_at_limit_still_decodes` (o arquivo com 64 marcadores decodifica, então o 65 só falha pela regra) |
| CA-06 | idem | `test_jpeg_scans.py::test_rejected_before_image_open` (SOI + COM com 65 pares: `JPEG scans`, espião em `Image.open` não chamado), `::test_within_limit_reaches_image_open` (10 pares: erro sem `JPEG scans`, `Image.open` chamado 1 vez) |
| CA-07 | idem | `test_jpeg_scans.py::test_png_with_marker_pairs_accepted` (PNG 64×48 com `tEXt` de 100 pares `FF DA`) |
| CA-08 | idem | `test_jpeg_scans.py::test_truncated_flag_checked_before_scans`, `::test_empty_checked_before_scans`; `test_image.py::test_truncated_images_flag_refused` (inalterado) |
| CA-09 | `transform.py` e `params.py` sem alteração | suíte do autor das SPECs 002 e 023 inalterada e passando. Os arquivos de aceite antigos dependem da troca de versão pelo tester (abaixo) |

Testes extras do autor: `::test_markers_after_eoi_are_counted` (pares depois do EOI contam, arquivo inteiro), `::test_path_input_is_checked` (entrada `Path`), `::test_only_jpeg_signature_is_counted` (`FF D8 00…`, texto e assinatura fora do início não passam pela regra).

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --locked --reinstall-package qc-preprocess   # atualiza os metadados do editable para 0.3.0
uv run pytest -q packages/preprocess/tests --ignore=packages/preprocess/tests/acceptance
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Observação: sem o `--reinstall-package` (ou um `uv sync` que reinstale o pacote), o `importlib.metadata.version("qc-preprocess")` do ambiente local continua `0.2.0` e o `test_smoke.py::test_import_and_version` falha. No CI, o ambiente é criado do zero.

## Para o tester (arquivos de aceite antigos, §3.1 da SPEC)

Com a versão 0.3.0, falham hoje só por expectativa de versão (não toquei em `tests/acceptance/`):

- `packages/preprocess/tests/acceptance/test_spec_002.py`: linhas 96 e 97 (`"0.2.0"` → `"0.3.0"`) e a docstring da linha 1;
- `packages/preprocess/tests/acceptance/test_spec_023.py`: linhas 111 e 112 e a docstring da linha 1. As linhas 118 e 119 (`qc-contracts`) continuam `"0.2.0"`;
- `packages/contracts/tests/acceptance/test_spec_023.py`: linhas 92 e 93 (`qc-preprocess`). As linhas 85, 86 e 184 (`qc-contracts`) continuam `"0.2.0"`.

Falhas em cascata dessas três (não são do código da SPEC):

- `packages/preprocess/tests/acceptance/test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass` (roda o `test_spec_002.py` em subprocesso);
- `packages/contracts/tests/acceptance/test_spec_023.py::test_ca13_ruff_and_full_suite` e `tests/acceptance/test_spec_022.py::test_ca15_ruff_and_full_suite_without_ci_and_db_url` (rodam a suíte inteira em subprocesso; pela `docs/architecture.md` §10 são removidos pelo tester da SPEC-004).

## Decisões tomadas dentro do escopo da SPEC

- Constantes privadas `_JPEG_SIGNATURE` e `_JPEG_SOS_MARKER` em `image.py`, para não repetir os literais.
- A mensagem segue o exemplo da SPEC: `too many JPEG scans: {n} scan markers, limit 64`.
- Os testes novos ficaram num arquivo próprio (`test_jpeg_scans.py`), com os mesmos utilitários de geração em memória de `test_image.py`. Nenhum binário de imagem foi versionado.
- O espião do CA-06 substitui `qc_preprocess.image.Image.open` por um wrapper que chama o original (o código testado não é simulado).

## SPEC_ISSUE (se houver)

Nenhuma.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`packages/preprocess/tests` sem `acceptance`: 119 passed)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim

Suíte inteira (`TEST_DATABASE_URL` local): `6 failed, 1063 passed`. As 6 falhas são as listadas em "Para o tester" (3 por expectativa de versão e 3 em cascata).
