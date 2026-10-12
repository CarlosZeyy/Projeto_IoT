# SPEC-023 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-023](../../docs/specs/SPEC-023-pacotes-compartilhados-0-2.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `16e76f6` (diff da SPEC: `spec/SPEC-003-schema-banco...16e76f6`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta), antes da leitura de `image.py`/`schemas.py`. Depois disso, li a implementação para procurar lacunas, e nenhum teste precisou mudar de expectativa.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `packages/contracts/tests/acceptance/test_spec_023.py::test_ca01_contracts_version`, `::test_ca01_both_packages_version`; `packages/preprocess/tests/acceptance/test_spec_023.py::test_ca01_preprocess_version`, `::test_ca01_both_packages_version` (os 4 valores = `"0.2.0"`) | ✅ |
| CA-02 | `contracts/.../test_spec_023.py::test_ca02_max_latency_constant`; `preprocess/.../test_spec_023.py::test_ca02_aspect_ratio_and_pixel_constants` | ✅ |
| CA-03 | `contracts/.../test_spec_023.py::test_ca03_ceiling_accepted_from_dict_and_json`, `::test_ca03_above_ceiling_rejected_from_dict[2**31, 2**63]`, `::test_ca03_above_ceiling_rejected_from_json[2**31, 2**63]` (1 erro, `less_than_equal`, `("latency_ms",)`) | ✅ |
| CA-04 | `contracts/.../test_spec_023.py::test_ca04_inspection_read_ceiling` | ✅ |
| CA-05 | `contracts/.../test_spec_023.py::test_ca05_batch_points_to_second_item` (1 erro em `("items", 1, "latency_ms")`) | ✅ |
| CA-06 | `contracts/.../test_spec_023.py::test_ca06_readme_version_history_and_max_latency` (lê as células da tabela, não só o texto) | ✅ |
| CA-07 | `preprocess/.../test_spec_023.py::test_ca07_exact_10_to_1_accepted[png-100x1000, png-1000x100, jpeg-40x400]`, `::test_ca07_preprocess_of_accepted_strip` | ✅ |
| CA-08 | `preprocess/.../test_spec_023.py::test_ca08_above_10_to_1_rejected[100x1001, 1001x100, 100x400000, 20x2000000]` (PNGs reais; os dois últimos com exatamente 40 M pixels) | ✅ |
| CA-09 | `preprocess/.../test_spec_023.py::test_ca09_ratio_comes_from_header_before_decoding` (PNG = assinatura + IHDR + IEND, sem IDAT) | ✅ |
| CA-10 | `preprocess/.../test_spec_023.py::test_ca10_exif_rotation_keeps_ratio_rule` | ✅ |
| CA-11 | `preprocess/.../test_spec_023.py::test_ca11_truncated_images_flag_refused` | ✅ |
| CA-12 | `preprocess/.../test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass` (roda os dois `test_spec_002.py` num subprocesso), e os próprios arquivos com só a versão trocada | ✅ |
| CA-13 | `contracts/.../test_spec_023.py::test_ca13_ruff_and_full_suite` (ruff check, ruff format --check e a suíte inteira num subprocesso) | ✅ |

Ajuste previsto na §3.1 da SPEC, feito: nos dois `tests/acceptance/test_spec_002.py`, só mudaram a expectativa de versão do `test_ca01_*` (`"0.1.0"` → `"0.2.0"`, nas duas linhas) e a versão na primeira linha da docstring do módulo. Nada mais nesses arquivos foi tocado (`git diff` mostra 3 linhas por arquivo).

Contagem: 59 testes de aceite novos (23 em contratos, 36 em preprocess), dos quais 27 cobrem CAs (contando os parâmetros) e 32 são exploratórios (`test_extra_*`).

Notas sobre o CA-13:
- o teste roda a suíte inteira num subprocesso. Para não entrar em recursão, a execução interna recebe `PARTQC_SPEC023_CA13_INNER=1`, e o próprio CA-13 é pulado nela;
- a execução interna também desmarca o `test_spec_022.py::test_ca15_*`, que roda a suíte inteira por conta própria. Sem isso, haveria um terceiro nível de suíte aninhada. Esse teste da SPEC-022 continua rodando na execução externa.

## Suíte completa

Com o banco (`TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`):

```text
uv run pytest -q
1050 passed in 122.14s (0:02:02)
```

Sem o banco (`TEST_DATABASE_URL` removido do ambiente):

```text
uv run pytest -q
866 passed, 184 skipped in 98.47s (0:01:38)
(os 184 skips são todos "TEST_DATABASE_URL not set", em infra/tests e api/tests de banco)
```

Só os quatro arquivos de aceite de pacotes (SPEC-002 e SPEC-023):

```text
274 passed in 29.88s
```

Ruff:

```text
uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 53 files already formatted
```

Conferências feitas para o reviewer:
- `git diff spec/SPEC-003-schema-banco -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py`: vazio;
- `uv.lock`: só as duas linhas de versão (`qc-contracts` e `qc-preprocess`, de 0.1.0 para 0.2.0).

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Contratos (`packages/contracts/tests/acceptance/test_spec_023.py`):

| Caso | Resultado |
|---|---|
| Piso inalterado: `latency_ms=0` aceito; `-1` gera 1 erro `greater_than_equal` em `("latency_ms",)` | OK |
| Modo lax não contorna o teto: `"2147483648"`, `2147483648.0`, `"9223372036854775808"` e `10**30` geram 1 erro em `("latency_ms",)` | OK |
| Modo lax no teto: `"2147483647"` e `2147483647.0` são aceitos e viram `int` | OK |
| Inteiro JSON de 400 dígitos: `ValidationError` em `("latency_ms",)`, sem exceção de outro tipo e sem travar | OK |
| Lote com 2 itens acima do teto (índices 0 e 4), via JSON: 2 erros, cada um no seu item | OK |
| Teto em round trip (`model_dump_json` → `model_validate_json`) e no JSON Schema: `maximum = 2147483647`, `minimum = 0`, `type = integer` (é o que a SPEC-004 vai publicar no OpenAPI) | OK |
| Os 14 campos e as 4 regexes continuam iguais (§4.1, "nada mais muda") | OK |
| README cita o modo lax e o valor 2 147 483 647 nas "Regras principais" | OK |

Preprocess (`packages/preprocess/tests/acceptance/test_spec_023.py`):

| Caso | Resultado |
|---|---|
| Limites inteiros: 1×1, 1×10, 10×1, 3×30 e 7×70 aceitos; 1×11, 11×1, 3×31 e 7×71 rejeitados com `aspect ratio` | OK |
| Regra aplicada também à entrada `Path` (5×51 rejeitado, 5×50 aceito) | OK |
| PNG só com cabeçalho de 20×2 000 000 e de 2 000 000×20 (40 M pixels exatos, proporção 100 000:1) → `aspect ratio`, sem decodificar | OK |
| Acima de `MAX_PIXELS` (8000×5001) e acima de `MAX_PIXELS` e da proporção ao mesmo tempo (10×4 000 001) → `InvalidImageError` | OK |
| Maior faixa válida testada, 1000×10 000 (10 M pixels, 10:1): `preprocess` dá `(1, 3, 224, 224)` `float32` | OK |
| Faixa aceita de 40×400 bate com uma reimplementação independente do pipeline da SPEC-002 §4.5 (atol 1e-6) | OK |
| Flag lida a cada chamada e com valores "verdadeiros" que não são `bool` (`1`, `"yes"`): `RuntimeError`; com valores falsos (`0`, `None`, `""`): imagem aceita; a flag nunca é alterada | OK |
| Flag tem precedência sobre bytes vazios, texto, PNG só com cabeçalho e PNG acima de `MAX_PIXELS` (sempre `RuntimeError`) | OK |
| 8 threads × 20 chamadas (imagem válida e faixa 10×200 rejeitada): nenhum erro inesperado e a flag segue `False` | OK |
| Reprodução do R-A da SPEC-002 sob `RLIMIT_AS` de 64 MB acima do VmSize (processo novo, Linux): 100×400 000 e 20×2 000 000 → `InvalidImageError` com `aspect ratio`, sem `MemoryError` | OK |
| GIF e BMP 2×200: `InvalidImageError` (formato ou proporção) | OK |

Medição manual (fora da suíte), `ru_maxrss` antes e depois de `load_image` num processo novo:

| Imagem | Tamanho do PNG | Resultado | Pico de RSS | Tempo |
|---|---|---|---|---|
| 100×400 000 | 5 519 bytes | `aspect ratio` | 40 MB → 40 MB (nada alocado) | 0,04 s |
| 20×2 000 000 | 7 844 bytes | `aspect ratio` | 42 MB → 42 MB | 0,01 s |
| 2 000×20 000 (maior aceita, 40 M pixels a 10:1) | 4 957 bytes | aceita | 44 MB → 227 MB | 0,16 s |

Na SPEC-002 r1, os dois primeiros casos davam pico de 1,6 GB e acima de 3 GB. O risco R-A está fechado.

Observação, sem bug: ao rejeitar pela proporção (ou por `MAX_PIXELS`), `load_image` não fecha explicitamente a imagem aberta. A origem é um `BytesIO`, sem descritor de arquivo, e o comportamento já era o mesmo na 0.1.0 para `MAX_PIXELS`. Não há impacto.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
