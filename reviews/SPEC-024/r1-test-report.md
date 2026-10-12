# SPEC-024 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-024](../../docs/specs/SPEC-024-preprocess-0-3-scans-jpeg.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `ba644b8` (código de produção em `36f7f2c`; diff da SPEC: `docs/pendencias-pos-003-023...HEAD`) |
| **Veredicto** | **PASS** |

Os testes de aceite foram escritos a partir da SPEC (caixa-preta), antes da leitura de `image.py`. Ambiente local atualizado com `uv sync --all-packages --locked --reinstall-package qc-preprocess` (Pillow 12.3.0).

## Cobertura dos critérios de aceite

Arquivo: `packages/preprocess/tests/acceptance/test_spec_024.py` (29 testes: 17 de CA e 12 exploratórios `test_extra_*`).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `::test_ca01_preprocess_version_and_contracts_unchanged` (`__version__` e `importlib.metadata` em `0.3.0`; `qc_contracts.__version__` em `0.2.0`) | ✅ |
| CA-02 | `::test_ca02_max_jpeg_scans_constant_and_unchanged_limits` (`MAX_JPEG_SCANS` igual em `qc_preprocess` e `qc_preprocess.image`, `== 64`, tipo `int`; `MAX_PIXELS` e `MAX_ASPECT_RATIO` inalterados) | ✅ |
| CA-03 | `::test_ca03_common_jpegs_accepted[baseline-rgb-64x48, progressive-rgb-640x480, progressive-gray-640x480]`; `::test_ca03_progressive_files_really_have_several_scans` (guarda: 10 e 6 marcadores, como a §1 prevê) | ✅ |
| CA-04 | `::test_ca04_limit_64_markers_accepted_and_bit_identical` (COM de 63 pares, 64 marcadores: aceito e `preprocess(...).tobytes()` idêntico ao do JPEG sem COM); `::test_ca04_65_markers_rejected` (COM de 64 pares: `InvalidImageError` com `JPEG scans`) | ✅ |
| CA-05 | `::test_ca05_repeated_progressive_scans_rejected[65, 1000]` (contagem exata de `FF DA` conferida no arquivo gerado); `::test_ca05_construction_is_decodable_at_limit` (guarda da §7: o mesmo arranjo com 64 marcadores decodifica, então a rejeição de 65/1000 vem da regra) | ✅ |
| CA-06 | `::test_ca06_rule_runs_before_image_open` (SOI + COM com 65 pares: `JPEG scans`); `::test_ca06_within_limit_fails_for_another_reason` (10 pares: `InvalidImageError` sem `JPEG scans`) | ✅ |
| CA-07 | `::test_ca07_png_with_marker_pairs_accepted` (PNG 64×48 com `tEXt` de 100 pares `FF DA`, conferidos no arquivo: aceito, `(64, 48)`, RGB) | ✅ |
| CA-08 | `::test_ca08_truncated_flag_checked_before_scans` (`monkeypatch` da flag em `True` + COM de 64 pares: `RuntimeError` com `LOAD_TRUNCATED_IMAGES`); `::test_ca08_empty_checked_before_scans` (flag em `False`, `b""`: `InvalidImageError` sem `JPEG scans`, e com `empty`) | ✅ |
| CA-09 | `::test_ca09_old_preprocess_acceptance_files_pass` (roda `test_spec_002.py` e `test_spec_023.py` do `qc-preprocess` em subprocesso, com caminhos explícitos, e confere que as expectativas de versão do `qc-preprocess` são `0.3.0` e que os CAs de valores, determinismo, dependências, proporção e flag continuam nos arquivos). Também verificado pela suíte inteira e por `uv run pytest -q` nos dois arquivos: `86 passed` | ✅ |

**CA-09 e a regra de `docs/architecture.md` §10.** O subprocesso passa caminhos de arquivo explícitos, não usa banco e faz `--deselect` do `test_spec_023.py::test_ca12_spec002_acceptance_suites_still_pass`, porque esse teste roda o pytest em subprocesso, e a §10 proíbe incluir um teste assim num subprocesso. O CA-12 continua rodando (e passando) na suíte inteira. Nenhum teste novo roda a suíte inteira.

### Troca das expectativas de versão (§3.1 da SPEC)

| Arquivo | Mudança |
|---|---|
| `packages/preprocess/tests/acceptance/test_spec_002.py` | CA-01: `"0.2.0"` → `"0.3.0"` (2 linhas); docstring do módulo `qc-preprocess 0.2.0` → `0.3.0` |
| `packages/preprocess/tests/acceptance/test_spec_023.py` | CA-01 (`test_ca01_preprocess_version`): `"0.2.0"` → `"0.3.0"` (2 linhas). As linhas do `qc-contracts` continuam `"0.2.0"` |
| `packages/contracts/tests/acceptance/test_spec_023.py` | CA-01 (`test_ca01_both_packages_version`, parte do `qc-preprocess`): `"0.2.0"` → `"0.3.0"` (2 linhas). As linhas do `qc-contracts` (85, 86 e 184) continuam `"0.2.0"` |

Decisões:

- **Igualdade exata a `"0.3.0"`, sem expectativa "resistente a minor".** Avaliei trocar por algo como "mesma major e `>= 0.2.0`", mas a SPEC é literal: a §3.1 autoriza mudar "**só** as expectativas de versão (`"0.2.0"` → `"0.3.0"`)", o CA-09 diz "com só as expectativas de versão do `qc-preprocess` trocadas para `"0.3.0"`", e a §7 manda o reviewer conferir que só isso mudou. Uma asserção por faixa mudaria o que o CA-01 das SPECs 002/023 verifica (versão exata publicada) e sairia do escopo autorizado. Sugestão para o architect (não é `SPEC_ISSUE` desta SPEC): numa próxima SPEC que mude a versão, autorizar que os testes antigos comparem `qc_preprocess.__version__ == importlib.metadata.version("qc-preprocess")` e deixem a versão exata só para o teste da SPEC vigente.
- **Docstring do `preprocess/tests/acceptance/test_spec_023.py` mantida** (`SPEC-023 (qc-preprocess 0.2.0: aspect ratio and truncated-image flag)`): ela nomeia o assunto da SPEC-023, que introduziu a 0.2.0, e não a versão verificada. A SPEC permite trocar menções de versão das docstrings, mas não obriga; trocar aqui tornaria o título falso. A docstring do `test_spec_002.py` descreve a versão verificada pelo arquivo e foi trocada.

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
55 files already formatted

$ TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
1098 passed in 138.35s (0:02:18)

$ env -u TEST_DATABASE_URL -u CI uv run pytest -q
914 passed, 184 skipped in 106.56s (0:01:46)        # os 184 skips são os testes `db`

$ uv run pytest -q packages/preprocess/tests/acceptance/test_spec_024.py
29 passed in 4.23s

$ uv run pytest -q packages/preprocess/tests/acceptance/test_spec_002.py packages/preprocess/tests/acceptance/test_spec_023.py
86 passed in 5.48s
```

As 6 falhas apontadas no dev-report (3 de expectativa de versão e 3 em cascata: `test_ca12` da SPEC-023 no `qc-preprocess`, `test_ca13` da SPEC-023 no `qc-contracts` e `test_ca15` da SPEC-022) passam depois da troca de versão. Os meta-testes CA-15 da SPEC-022 e CA-13 da SPEC-023 continuam no repositório e passam; a remoção deles é do tester da SPEC-004 (§10).

Conferências adicionais: `transform.py` e `params.py` sem diff contra `main` e contra `docs/pendencias-pos-003-023`; nenhuma credencial fictícia em URL ou conninfo nos arquivos de aceite; nenhum binário de imagem versionado.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados em `test_spec_024.py` (todos passam):

| Teste | Caso | Resultado |
|---|---|---|
| `test_extra_path_input_is_checked` | Entrada `Path` com 65 e 64 marcadores | 65 rejeitado com `JPEG scans`; 64 aceito |
| `test_extra_markers_after_eoi_are_counted` | 64 pares `FF DA` depois do EOI (65 no total) | Rejeitado: a contagem cobre o arquivo inteiro (§4.1) |
| `test_extra_trailing_markers_up_to_limit_accepted` | 63 pares depois do EOI (64 no total) | Aceito |
| `test_extra_message_reports_count_and_limit` | COM de 99 pares (100 marcadores) | Mensagem com `100` e `64` |
| `test_extra_signature_must_be_at_start` | Assinatura deslocada 1 byte; `FF D8 00…`; texto com 100 pares | `InvalidImageError` sem `JPEG scans` (a regra só vale com `FF D8 FF` no início) |
| `test_extra_fill_bytes_do_not_add_markers` | Bytes `FF` de enchimento antes do EOI num arquivo com 64 marcadores | Contagem continua 64; aceito |
| `test_extra_cmyk_progressive_accepted` | JPEG progressivo CMYK (18 scans, o maior script padrão citado na §1) | Aceito, RGB 64×48 |
| `test_extra_exif_thumbnail_jpeg_accepted` | APP1 com miniatura JPEG embutida (2 marcadores) | Aceito |
| `test_extra_rejected_quickly_on_large_body` | ~10 MiB de pares `FF DA` após a assinatura | Rejeitado em < 2 s (medido: 7,5 ms) |
| `test_extra_repeated_rejection_is_stable` | 6 rejeições seguidas e depois uma imagem boa | Mesma mensagem; nenhum estado vazado |
| `test_extra_progressive_preprocess_unchanged_by_limit[RGB, L]` | Progressivos aceitos passam pelo `preprocess` | `(1, 3, 224, 224)`, determinístico e finito |

Testes de mutação (manuais, em cópias do pacote no diretório temporário da sessão, via `PYTHONPATH`; código de produção intocado), rodando `test_spec_024.py` sem o CA-09:

| Mutação | Testes que falharam |
|---|---|
| `>` trocado por `>=` | 5 (inclui CA-04 limite e CA-05 guarda) |
| Limite 65 | 8 (inclui CA-02, CA-04, CA-05[65], CA-06) |
| Regra removida | 9 (CA-04, CA-05, CA-06 e extras) |
| Regra aplicada a qualquer formato | 2 (CA-07 e assinatura) |
| Mensagem sem `JPEG scans` | 9 |
| Assinatura reduzida a `FF D8` | 1 (`test_extra_signature_must_be_at_start`) |
| Regra movida para depois do `Image.open` | 3 (inclui CA-06) |
| Checagem de vazio removida | 0: com `b""`, a ordem vazio→scans não é observável, porque `b""` não tem a assinatura JPEG; o CA-08 só exige que a mensagem não contenha `JPEG scans`. É uma limitação do CA como está escrito, não um defeito. |

Medição do ataque do SEC-01 em tamanho real (`load_image` local, Pillow 12.3.0), com o último scan repetido:

| Arquivo | Marcadores | Tamanho | Tempo |
|---|---|---|---|
| Progressivo 6000×6600 (39,6 M pixels), conteúdo com textura | 10 (original) | 9,3 MB | 0,69 s |
| idem | 64 (aceito) | — | 4,79 s |
| idem | 65 | — | rejeitado em 0,096 s (contagem) |
| Progressivo 6000×6600, cor sólida (scans de 61 bytes) | 10 | 233 KB | 0,47 s |
| idem | 64 (aceito) | 236 KB | 2,12 s |

**Observação (informativa, não é bug nem `SPEC_ISSUE`):** nesta máquina, cada scan repetido em 40 M pixels custou cerca de 30 ms (scan de 61 bytes) a 75 ms (scan com dados), contra os cerca de 4 ms usados na estimativa da §4.1 ("64 × 4 ms ≈ 0,26 s"). O pior caso aceito medido ficou em cerca de 5 s de CPU por requisição: muito abaixo dos cerca de 10 min do SEC-01, mas acima da estimativa. Nenhum CA depende desse número. Fica registrado para o security-devops desta SPEC e para o limitador de decodificações simultâneas da SPEC-007 (SEC-02).

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
