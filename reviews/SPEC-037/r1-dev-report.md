# SPEC-037 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-037](../../docs/specs/SPEC-037-manutencao-ml-origem.md) |
| Rodada | r1 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-037-manutencao-ml-origem` |
| Commits | `0637c7d` (código, README e testes do autor); o commit deste relatório |

## Resumo

- `report.py`: uma função única, `check_counts`, confere as contagens exibidas do `metrics.json` (só `int` não negativo, sem `bool`). O `release-notes` a chama antes das fontes ausentes do registro, e o `changelog` a chama antes de montar qualquer linha quando a seção `### Dados` é gerada. Com contagem inválida, os dois saem com 2, imprimem uma linha `invalid count in metrics.json: <campo>` por campo (sem o valor) e não gravam nada.
- `split.py`: `_fraction_argument` confere de novo o `float`, então `1e-400`/`2e-324` saem com 2, sem traceback.
- `data.py`: `parse_csv(..., exact_header=True)`, usado só por `_read_sources` e `_read_registry`, gera um `unexpected_header` quando o cabeçalho tem todas as colunas mas não é a tupla exata. O efeito é o mesmo do `missing_column`.
- `synthetic.py`: `ValueError` quando peças próprias alcançariam o número 501 com `contributor_items_per_stratum > 0`.
- `export.py`: `_log_export_warnings` passou para o `finally`.
- `ml/README.md`: atualizado.

## Rastreabilidade (critério de aceite → implementação)

Testes do autor em `ml/tests/test_maintenance_037.py` (abreviado `t037`) e `ml/tests/test_export_warnings.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `ml/src/qc_ml/report.py` (`is_valid_count`, `check_counts`, `release_notes`, `_release_notes_main`) | `t037::test_release_notes_valid_counts_unchanged`, `::test_release_notes_invalid_count` (7 valores), `::test_release_notes_invalid_count_keeps_output`, `::test_release_notes_zero_count`, `::test_valid_counts`, `::test_invalid_counts`, `::test_message_never_has_the_value` |
| CA-02 | `report.py` (`check_counts` no início de `release_notes`) | `t037::test_release_notes_counts_before_missing_sources`, `::test_release_notes_other_fields_not_checked`, `::test_release_notes_registry_problem_before_counts` |
| CA-03 | `report.py` (`changelog_entry`, `data_section`, `main`) | `t037::test_changelog_valid_counts`, `::test_changelog_invalid_count` (casos a–h, mais `55.0` e `counts.val` ausente), `::test_check_counts_lists_every_field_in_order`, `::test_check_counts_by_origin_not_an_object`, `::test_data_section_checks_counts` |
| CA-04 | `report.py` (`_has_origins` decide se confere) | `t037::test_changelog_without_by_origin_is_not_checked`, `::test_check_counts_accepts_the_base_and_no_sources` |
| CA-05 | `report.py` (`source_lines`, sem mudança) | `t037::test_changelog_invalid_source_id_line` |
| CA-06 | `ml/src/qc_ml/split.py` (`_fraction_argument`) | `t037::test_fraction_argument_refused`, `::test_fraction_argument_accepted`, `::test_split_cli_underflow` |
| CA-07 | `ml/src/qc_ml/data.py` (`parse_csv`, `HEADER_PROBLEMS`, `_read_sources`) e `ml/README.md` | `t037::test_sources_unexpected_header` (extra, ordem, `origin` repetida, vírgula no fim), `::test_sources_unexpected_header_in_load_sources`, `::test_sources_validate_cli`, `::test_sources_missing_column_without_unexpected_header`, `::test_sources_bom_is_missing_column`, `::test_parse_csv_exact_header_only_when_asked`, `::test_parse_csv_missing_column_wins`, `::test_manifest_keeps_the_loose_header` |
| CA-08 | `data.py` (`_read_registry`) | `t037::test_registry_unexpected_header` (4 casos, com `load_manifest`, `load_external_sources` e `release-notes`), `::test_registry_repeated_license_is_refused`, `::test_registry_exact_header_loads`, `::test_repository_registry_has_the_exact_header` |
| CA-09 | `ml/src/qc_ml/synthetic.py` (`make_synthetic_dataset`) | `t037::test_generator_refuses_collision`, `::test_generator_limit_and_no_contributor` |
| CA-10 | `ml/src/qc_ml/export.py` (`export_onnx`) | `t037::test_export_logs_warnings_in_finally` |
| CA-11 | `export.py` | `ml/tests/test_export_warnings.py::test_export_logs_warnings_when_the_export_raises` (`slow`, torch) |

## Como rodar e verificar

```bash
uv sync --all-packages --locked
uv run ruff check . && uv run ruff format --check .
uv run pytest -q ml/tests tests                      # sem torch e sem banco
# parte slow (CA-11):
uv sync --all-packages --extra train --locked && uv run --no-sync pytest -q ml/tests
uv sync --all-packages --locked                      # volta ao estado do CI
```

Resultados nesta worktree (sem `TEST_DATABASE_URL`; o orquestrador roda a suíte com banco):

- Sem torch: `uv run pytest -q ml/tests tests` → **1108 passed, 26 skipped** (os skips são torch, `model.onnx` local ausente e banco).
- Com o extra `train` (torch instalado): `uv run --no-sync pytest -q ml/tests` → **767 passed, 2 skipped** (`model.onnx` real ausente). Os 4 testes de `test_export_warnings.py` passam.
- Controle negativo do CA-11: com o `export.py` da base (`HEAD~1`), o teste novo `test_export_logs_warnings_when_the_export_raises` falha e os 3 antigos passam. Depois, o arquivo foi restaurado.
- O `.venv` voltou ao estado do CI (`uv sync --all-packages --locked`; `torch` ausente, conferido).
- `ruff check .` e `ruff format --check .` limpos (232 arquivos).
- Nenhum teste de aceite antigo falhou nem foi alterado.

## Decisões tomadas dentro do escopo da SPEC

1. **Formato das linhas de erro das contagens.** Cada campo inválido ganha uma linha própria, com o prefixo do comando: `release-notes failed: invalid count in metrics.json: <campo>` ou `report failed: invalid count in metrics.json: <campo>`. É uma das formas previstas no §4.1. A ordem é a da tabela do §4.1: `counts.train.n_images`, depois `by_origin.external` de `train`, `val` e `test`, depois as fontes na ordem do `sorted` sobre os `source_id` **originais** (a mesma do `source_lines`). Por isso, um id inválido pode vir depois de um válido, por exemplo `b-src` antes de `<invalid source_id>` vindo de `"bad id"`.
2. **`InvalidCountsError(ValueError)`** traz `fields`. Os dois `main` o tratam antes do `ValueError` genérico, então os outros erros continuam com as mensagens de hoje.
3. **`data_section` também chama `check_counts`.** O `changelog_entry` já confere logo no início (antes de qualquer linha); a segunda chamada é idempotente e protege quem chama `data_section` direto. Continua sendo uma função só (§7).
4. **`--previous` não é conferido.** O §4.1 lista só os campos da seção `### Dados` do `metrics.json` atual. O `metrics.json` anterior só alimenta a coluna "Anterior" da tabela, que não exibe contagens de origem.
5. **`counts.train.by_source` que não é objeto.** Com a seção gerada, continua valendo o erro de hoje (`counts.train.by_source in metrics.json must be a JSON object`, saída 2, decisão 8 do dev-report da SPEC-035). Nesse caso, os outros campos inválidos não são listados junto, porque o `ValueError` sai antes do `InvalidCountsError`. Nada é gravado do mesmo jeito.
6. **No `release-notes`, um problema do registro vem antes da conferência das contagens** (ordem do §4.1: "depois da leitura … do registro"). Coberto por `test_release_notes_registry_problem_before_counts`.
7. **`unexpected_header` no `parse_csv`**, com o parâmetro só-palavra-chave `exact_header=False`, que só `_read_sources` e `_read_registry` passam (opção do §7). O manifest, o `labels_overrides.csv` e o `exclusions.csv` não mudam (`test_manifest_keeps_the_loose_header`). A mensagem é `the header must be exactly <colunas separadas por vírgula> (in this order, no other column)`: cita a lista esperada e nunca o cabeçalho lido. A constante `HEADER_PROBLEMS` (`missing_column`, `unexpected_header` e `unreadable_csv`) passou a decidir o `readable=False` do `sources.csv`. A checagem do manifest no `load_manifest` ficou como estava.
8. **Gerador:** a regra calcula o último número próprio de `S`, `N` e (com `include_other`) `O`, como no §4.5. Com as fórmulas atuais, `O` nunca colide sozinho, porque `items_per_stratum ≤ items_per_stratum × 5`. Por isso, não há teste que isole o `O`. A mensagem cita `items_per_stratum` e `contributor_items_per_stratum`. A validação vem antes do `mkdir`, e o teste confere que `root` não é criado.
9. **Export:** o `try` envolve o `with warnings.catch_warnings(record=True)`, e `caught` é inicializado como `[]` antes. Assim, o `finally` roda fora do bloco de captura (preferência do §4.6), e um aviso emitido pelo próprio `logging` não fica preso na lista. A exceção sai sem conversão (`pytest.raises(RuntimeError, match=marcador)`), e nenhum `model.onnx` sobra.
10. **README:** além da frase exigida pelo §4.4 (bullet "Cabeçalho exato"), acrescentei uma frase sobre o `invalid count in metrics.json` em "Notas do Release" e outra sobre o limite de `items_per_stratum` com peças de conhecido em "Dataset sintético".

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (sem torch e, na parte `slow`, com torch)
- [x] `.env.example` atualizado (se houver variável nova): N/A, nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Sem dependência nova; `uv.lock` e `pyproject.toml` sem mudança; nenhuma imagem real, nenhum segredo
