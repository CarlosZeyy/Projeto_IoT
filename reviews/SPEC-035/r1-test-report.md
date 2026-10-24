# SPEC-035 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-035](../../docs/specs/SPEC-035-ml-origem-das-imagens.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `04cc749` |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir dos critérios de aceite (caixa-preta), antes da leitura da implementação. Arquivo: `ml/tests/acceptance/test_spec_035.py`, com **126 testes**: 53 itens de critério de aceite (`test_caNN_*`, contando os casos parametrizados) e 73 exploratórios (`test_extra_*`). Tudo é sintético (`make_synthetic_dataset` e JPEGs gerados com Pillow em `tmp_path`, R-14), sem rede, sem torch e sem mock além do sistema de arquivos temporário. O registro usado é sempre `<root>/external_sources.csv`, salvo no CA-14.

## Cobertura dos critérios de aceite

Prefixo dos testes: `ml/tests/acceptance/test_spec_035.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_item_id_pattern_and_helpers` | ✅ |
| CA-02 | `test_ca02_origin_columns` | ✅ |
| CA-03 | `test_ca03_compatibility_without_sources` | ✅ |
| CA-04 | `test_ca04_sources_problems` (12 casos: `unknown_source_id`, `invalid_source_ref` ×2, `invalid_contributor`, `source_fields_mismatch`, `invalid_origin`, `invalid_input_sha256`, `duplicate_input`, `duplicate_source_row`, `source_unknown_image`, `missing_source`, `external_item_mismatch`), `test_ca04_sources_missing_column`, `test_ca04_validate_cli_counts_missing_source` (subprocesso: sai com 2 e imprime `count missing_source: 1`) | ✅ |
| CA-05 | `test_ca05_registry_problems` (10 casos: 6 de `invalid_license`, `invalid_url`, `invalid_date`, `invalid_source_id`, `invalid_text`), `test_ca05_registry_duplicate_source_id`, `test_ca05_header_only_registry_without_externals`; todos conferem `file="external_sources.csv"` | ✅ |
| CA-06 | `test_ca06_excluded_external_image` | ✅ |
| CA-07 | `test_ca07_externals_in_train_and_own_split_unchanged` | ✅ |
| CA-08 | `test_ca08_new_externals_go_to_train` | ✅ |
| CA-09 | `test_ca09_external_never_in_val_or_test` ((a) CLI, (b) `make_split`, (c) `rows_for` em `test` e `val`, e `rows_for(..., "train")` com as 11 externas) | ✅ |
| CA-10 | `test_ca10_external_fraction_ceiling` (18 → 0,30 aceito; 19 → sai com 2 com `external fraction` e `209/671`, nada gravado; `0.35` aceito; `0`, `1.5`, `abc` → 2 sem gravar) | ✅ |
| CA-11 | `test_ca11_data_report_by_origin` | ✅ |
| CA-12 | `test_ca12_metrics_counts_by_origin` (`thresholds` e `evaluate` na fixture `tiny_model`, sem torch) | ✅ |
| CA-13 | `test_ca13_changelog_data_section` | ✅ |
| CA-14 | `test_ca14_repository_registry` | ✅ |
| CA-15 | `test_ca15_generator_defaults_unchanged` | ✅ |
| CA-16 | `test_ca16_release_notes_with_source` (arquivo e stdout comparados byte a byte em subprocesso) | ✅ |
| CA-17 | `test_ca17_source_not_in_registry_blocks` ((a) sem arquivo, (b) com `antigo\n`, `changelog` só marca), `test_ca17_header_only_registry_blocks`, `test_ca17_invalid_source_id_not_echoed` (marcador gerado com `uuid4`, mais U+202E), `test_ca17_order_of_two_sources` | ✅ |
| CA-18 | `test_ca18_release_notes_without_externals[empty]`, `[old_metrics]` | ✅ |
| CA-19 | `test_ca19_release_notes_errors` (5 casos), `test_ca19_existing_output_kept_on_error` | ✅ |
| CA-20 | `test_ca20_readme_section` (o trecho é isolado ignorando `#` dentro de blocos de código) | ✅ |

## Suíte completa

```text
$ uv sync --all-packages --locked        # estado do CI, sem torch
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
231 files already formatted
$ uv run pytest -q ml/tests/acceptance/test_spec_035.py
126 passed in 56.03s
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
6008 passed, 54 skipped, 1 warning in 430.26s (0:07:10)
```

- 6008 = os 5882 do dev report + os 126 deste arquivo. Os 54 skips são os de sempre (Docker sem `PARTQC_DOCKER_TESTS=1`, torch ausente e `model.onnx` real ausente); o aviso não vem do `ml/`.
- Os testes de aceite das SPECs 011, 012 e 031 passam sem nenhuma alteração. **Nenhum ajuste** em testes de aceite antigos (`docs/architecture.md` §10), como a §3.1 previa.
- O `.venv` ficou no estado do CI o tempo todo (`uv sync --all-packages --locked`, sem o extra `train`). Nenhum teste deste arquivo usa torch.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | nenhum CA (§4.6, "Os textos vêm do registro […]: cada fonte ocupa exatamente uma linha") | 1. Diretório de modelo com o `model.sha256` da fixture `tiny_model` e o registro sintético do §4.7. 2. `metrics.json` com `counts.train.by_source = {"synthetic": "11 imagens\n- `forged`: 9"}` (o valor da contagem é texto com quebra de linha). 3. `python -m qc_ml.report release-notes --model-dir <dir> --external-sources <registro>` | Cada fonte ocupa uma linha. Como a SPEC não lista contagem que não é inteiro entre os erros, o esperado razoável é recusar (código 2) ou nunca ecoar um `<n>` que não seja inteiro não negativo | Sai com 0 e as notas trazem duas linhas `` - ` ``: `` - `synthetic`: 11 imagens `` e `` - `forged`: 9 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: … | Fonte: … ``. O crédito da fonte real fica pendurado numa fonte forjada. `-3`, `1.5`, `null` e `true` também são ecoados (`-3 imagens`, `None imagens`, `True imagens`). O mesmo vale para a seção `### Dados` do `changelog` (`<n>`, `<e_val>`, `<e_test>` e `<e_train>` saem sem conferência de tipo) |

Sobre o T-01: o `metrics.json` é gerado pelo pipeline, então o caso só acontece com o arquivo editado à mão ou corrompido. É o mesmo canal que o CA-17 fecha para a **chave** (`source_id` fora do formato não é ecoado), mas aberto pelo **valor**. Não há teste falhando para ele, porque a SPEC não define o comportamento esperado para uma contagem que não é inteira (a lista de "Erros" do §4.6 não cobre o caso). Ele não muda o veredicto pelas regras do papel, mas recomendo corrigir: aceitar só `int` não negativo (sem `bool`) e sair com 2 nos outros casos, como o autor já fez para `by_source` que não é objeto (decisão 8 do dev report). Fica a critério do reviewer e do orquestrador decidir se bloqueia.

## Testes exploratórios (além dos critérios)

Automatizados em `test_extra_*` (todos passam):

- **Registro (§4.3):** as 6 licenças aceitas carregam e `retrieved_at` vira `date`; licença com maiúsculas trocadas ou espaço final; `source_id` com 2 e com 41 caracteres e começando com `-`; `title` vazio, com 201 caracteres, com U+202E (Cf), U+200B (Cf) e U+2028 (Zl); `attribution` com 501 caracteres e com TAB (Cc); `url` com espaço, com não ASCII, com 301 caracteres e só `https://`; `license_url` com `http://`; datas `2026-1-05`, com dígitos de largura total e com hora. Todos recusados com o código e o `file` certos. Limites aceitos: `source_id` de 3 e de 40, `title` de 200, `attribution` de 500 (com `ç`), `url` de 300, `license_url` de 9 (`https://a`) e `2024-02-29`. Cabeçalho sem uma coluna → `missing_column`. Registro inválido é recusado mesmo sem nenhuma imagem externa (§4.3).
- **`sources.csv` (§4.2):** `origin` vazio e `External`; `contributor` `c001`, vazio numa linha `contributor` e preenchido numa linha `external`; `source_ref` numa linha `contributor`; `source_id` vazio numa linha `external`; `source_ref` com 201 caracteres, `\n`, NUL e BOM no meio; `input_sha256` maiúsculo e com 65 caracteres; `image_path` absoluto e com `..`. Todos com o código esperado. `source_ref` com 200 `ç` é aceito. Linha `contributor` para um `XS-` → `external_item_mismatch`. Linha excluída com `input_sha256` repetido não gera `duplicate_input`. Registro ausente com externas → um `unknown_source_id` por imagem (11).
- **Prefixo:** `XS-` com `object_type=nut` → `item_prefix_mismatch`; `XO-` com `other` aceito; `XT-0001` recusado.
- **Split:** `make_split` com `max_external_fraction` `0`, `0.0`, `-0.1`, `1.0000001` e `1.5` → `ValueError`; `1` aceito. Comparação exata: 198/660 passa com `0.3` e falha com `0.29`, com a mensagem `external fraction in train 198/660 above 0.29`. `history={"XN-0003": "val"}` → `SplitIntegrityError`; `item_history` com `XO-0001` em `val` → `SplitIntegrityError`. CLI: `nan`, `inf`, `-0.1`, vazio, `0.0` e `1.0000001` saem com 2 sem gravar; `1` aceito. `split_v1.json` sem externas tem `max_external_fraction` 0,3, `external_fraction_train` 0 e `n_external_images` zerado. Sem as colunas de origem no `df`, as externas continuam no treino (a regra depende só do `item_id`, §7).
- **Relatório de dados:** sem split, `by_split == {}` nas três origens e `external_fraction_train` `null`; sem externas, `by_source == {}`, `n_contributors == 0` e as chaves antigas com os valores de antes; o relatório nunca contém o código `c01`.
- **Notas do Release:** texto completo exatamente como o §4.6 (blocos separados por uma linha em branco, um único `\n` no fim); stdout igual ao arquivo, byte a byte, também com `LC_ALL=C`; `--output` existente é sobrescrito sem deixar arquivo temporário; registro ausente com fonte externa → 2; vários `source_id` ausentes saem em ordem, e um id com `\n` não forja uma linha `source not in registry:`.
- **CHANGELOG:** a fração é arredondada para cima (1 de 3 → `0,3334`).
- **Gerador (§4.7):** numeração de conhecidos a partir de 501 por letra, continuando entre os estratos; externas a partir de `0001` por letra, com 1 imagem no ângulo 0; linhas do `sources.csv` com os campos do §4.7 e `input_sha256` igual ao SHA-256 do arquivo gravado; registro sintético com os valores do §4.7.
- **`TrainConfig`:** sem o campo vale `None`; com o campo, o caminho é lido; `external_sources` não entra em `deviations_from_defaults`.

Manuais (script no scratchpad, fora do repositório):

| Caso | Resultado |
|---|---|
| `sources.csv` com BOM | `missing_column` (a SPEC pede UTF-8 sem BOM) |
| `sources.csv` com CRLF | aceito |
| `sources.csv` vazio (0 bytes) | `missing_column` para as 6 colunas |
| `sources.csv` só com o cabeçalho, com externas no manifest | 11 × `missing_source` |
| `sources.csv` não UTF-8 | `unreadable_csv` |
| `sources.csv` com coluna extra ou com as colunas reordenadas | aceito (mesma regra do manifest na SPEC-011: só a coluna obrigatória ausente é erro). Observação, não bug: a SPEC diz cabeçalho "exatamente", mas só define `missing_column` |
| `sources.csv` com linha curta | `malformed_row` |
| registro com BOM | `missing_column` no registro e `unknown_source_id` nas 11 linhas externas |
| registro com CRLF | aceito |
| `--external-sources` apontando para um diretório | tratado como registro ausente (vazio): 11 × `unknown_source_id` |
| `contributor` `c01 ` (espaço final) | `invalid_contributor` |
| `release-notes`: `metrics.json` `[]` ou não UTF-8; `model.sha256` sem `\n` ou maiúsculo | sai com 2 |
| `release-notes`: `--output` em diretório inexistente ou apontando para um diretório | sai com 2, nada criado, sem arquivo temporário sobrando |
| `metrics.json` novo (com `by_origin` e `by_source`) lido pelo `qc_dashboard.model_info` (SPEC-028) | carrega e monta as tabelas normalmente |
| `thresholds` com externas e config sem `external_sources` (usa o registro do repositório, vazio) | sai com 2 (`unknown_source_id`), sem ver imagem nenhuma |

Observação sobre o CHANGELOG (decisão 7 do dev report): um `source_id` fora do formato do §4.3 vindo do `metrics.json` aparece como `` `<invalid source_id>` `` no CHANGELOG, e não com o valor literal. O §4.6 escreve `` - `<source_id>`: … `` sem essa exceção, mas nenhum CA cobre o caso, e a escolha evita gravar no Git um valor com caractere de controle. Fica registrado para o reviewer.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
