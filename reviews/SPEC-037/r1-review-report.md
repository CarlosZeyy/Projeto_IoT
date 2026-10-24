# SPEC-037 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-037](../../docs/specs/SPEC-037-manutencao-ml-origem.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...d65cad9` (base `31979b9`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `docs/specs/SPEC-035-ml-origem-das-imagens.md:5` | O commit `ecb5723` (`chore: start SPEC-037`, orchestrator) marcou a SPEC-035 como `Done` só no `docs/plan.md`. O campo `Status` do arquivo da SPEC-035 continua `In Review`, igual ao da `main`. A skill `features` (passo 2 e regra 1 do fechamento) pede a marcação no arquivo da SPEC **e** no plano. Não afeta o código desta SPEC. | No próximo commit de status do orquestrador nesta branch (ou no `chore: start` da próxima SPEC), trocar o `Status` da SPEC-035 para `Done`. |
| RV-02 | baixa | `ml/src/qc_ml/report.py:362`, `ml/src/qc_ml/report.py:366` | Fora do escopo desta SPEC, registrado para uma manutenção futura: o `changelog` ainda copia valores do `metrics.json` sem conferir o tipo fora da seção `### Dados`. São as contagens de `n_items_test_by_grade` (linha "Peças no teste por grau") e as strings de `warnings` (uma linha `- …` por aviso). Um texto com quebra de linha forja linhas no CHANGELOG, o mesmo mecanismo do T-01. O risco é menor, porque o CHANGELOG passa por PR e não vai para a página pública do Release. A SPEC limita a conferência aos campos da tabela do §4.1, e o autor seguiu esse limite. | Numa próxima SPEC de manutenção do ML, aplicar `is_valid_count` a `n_items_test_by_grade` e recusar (ou neutralizar) `warnings` com caractere de controle. |

Nenhum achado bloqueante, alto ou médio.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os 11 CAs têm implementação e teste de aceite (tabela abaixo). O diff fica nos arquivos do §3.1 (`report.py`, `split.py`, `data.py`, `synthetic.py`, `export.py`, `ml/README.md`, testes do autor e do tester), mais os commits de status do orquestrador. O texto da SPEC só mudou nas linhas de status: o `git diff` do arquivo da SPEC contra a `main` mostra apenas `Status` e `Rodada atual`. Não houve reaprovação sob o ADR-019 nesta branch: o Histórico tem só a criação e a aprovação humana de 2026-10-24 (PR #45). As decisões 1 a 10 do dev-report ficam dentro das escolhas que a SPEC deixa ao autor: formato da linha de erro (§4.1), parâmetro do `parse_csv` (§7), posição do `try` (§4.6). A decisão 4 (`--previous` não conferido) e a 5 (`by_source` que não é objeto mantém o erro da SPEC-035) seguem a letra do §4.1. A decisão 6 (problema do registro antes das contagens no `release-notes`) segue a ordem do §4.1. |
| 2. Regras inegociáveis | ✅ | R-01/R-12: nenhuma dependência nova (`pyproject.toml` e `uv.lock` sem mudança). R-02/R-14: só imagens sintéticas em `tmp_path`. R-03: busca por `secret`, `token`, `password`, `postgres://`, `eyJ` e `api_key` nas linhas adicionadas sem resultado. R-04/R-05/R-06: não se aplicam (contrato, API e `source` não foram tocados). R-07: os trailers conferem com os arquivos de cada commit. `0637c7d` e `6bb265b` (ml-engineer) tocam só `ml/src/**`, `ml/README.md`, `ml/tests/test_*.py` fora de `acceptance/` e o dev-report. `3690861` (tester) toca só `ml/tests/acceptance/test_spec_037.py` e o test-report. `ecb5723`, `249e918` e `d65cad9` (orchestrator) tocam só `docs/plan.md` e o status da SPEC. Todos os commits têm `Agent:`. R-11: o split das peças próprias não mudou, só o `type` do argumento `--max-external-fraction`. As contagens passam a ser exibidas só quando são inteiros medidos, o que reforça a R-11, e nenhuma escolha usa o teste. R-13: autor `Carlos Moises <…CarlosZeyy@users.noreply.github.com>` em todos os commits, Conventional Commits, nenhuma menção a empresa. |
| 3. Corretude | ✅ | `is_valid_count` exclui `bool` antes do `int` (§7). `check_counts` é a única conferência, chamada no início do `release_notes` e do `changelog_entry` (e de novo no `data_section`, sem efeito colateral), antes de qualquer linha. O `<id>` passa pelo `shown_source_id`, e nenhuma mensagem ecoa o valor nem o cabeçalho lido. Os dois `main` capturam `InvalidCountsError` antes do `ValueError` genérico e retornam 2 sem abrir o `--output`/`--append`. O `_fraction_argument` confere o `float` depois da conversão (`1e-400` → 2, `1e-300` aceito). O `parse_csv(..., exact_header=True)` só roda depois do `missing_column`, então BOM e coluna faltando continuam como `missing_column`. Os outros três leitores (manifest, overrides, exclusions) e o `agreement.py` não passam o parâmetro. `HEADER_PROBLEMS` deixa o `sources.csv` como `readable=False`, o que suprime o `missing_source`. No registro, `unexpected_header` não carrega nenhuma linha. O gerador valida antes do `mkdir`. O `export_onnx` inicializa `caught = []` e registra os avisos no `finally`, fora do `catch_warnings`, sem converter a exceção. |
| 4. Testes | ✅ | Test-report PASS, com um teste por CA e controles negativos contra a base `ecb5723`: 39 falhas na base, e os CA-04/CA-05 passam nela, como esperado, porque só fixam um comportamento que já existia. Os testes não fazem mock do que testam: CLIs em subprocesso e `metrics.json` escrito pelo teste. O único mock é o `torch.onnx.export` no CA-11, permitido pelo §6. Sem rede e sem banco. Nenhum teste de aceite antigo foi alterado (`git diff --stat` mostra só `test_spec_037.py` em `acceptance/`), e a seção "Ajustes em testes de aceite de SPECs anteriores" diz "Nenhum", o que bate com o diff. O CA-11 (`slow`, torch) foi rodado pelo autor e pelo tester com torch, com controle negativo. Nesta revisão, ele aparece como `skipped` (sem torch, estado do CI). |
| 5. Qualidade | ✅ | `ruff check .` e `ruff format --check .` limpos (233 arquivos). Type hints nas funções novas e docstrings com `Raises`. Sem `print` novo fora das funções de CLI que já imprimiam no stderr. `ml/README.md` atualizado (§4.4), com a frase do cabeçalho exato e mais duas frases coerentes com a SPEC. |
| 6. Segurança | N/A | A SPEC não tem a tag `security` nem `deploy`, e o autor é o ml-engineer. |

### Rastreabilidade (CA → implementação → teste de aceite)

| CA | Implementação | Teste de aceite (`ml/tests/acceptance/test_spec_037.py`) | Exercita de fato? |
|---|---|---|---|
| CA-01 | `report.py` `is_valid_count`, `check_counts`, `release_notes`, `_release_notes_main` | `test_ca01_*` (base, 7 inválidos, `--output` preservado, zero) | Sim: subprocesso, `11.0` escrito como decimal no texto JSON, stdout vazio e `notes.md` ausente/preservado |
| CA-02 | `check_counts` antes de `source_lines`/`missing` | `test_ca02_release_notes_counts_before_missing_sources` | Sim: o id inválido com RLO não está no registro, e `source not in registry` não aparece |
| CA-03 | `changelog_entry` → `check_counts(data_section=True)`; `main` | `test_ca03_changelog_valid_base`, `test_ca03_changelog_invalid_count` (a–h) | Sim: o arquivo continua `# CHANGELOG\n` e o marcador não aparece |
| CA-04 | `_has_origins` decide | `test_ca04_changelog_without_by_origin_not_checked` | Sim |
| CA-05 | `source_lines` (sem mudança) | `test_ca05_changelog_invalid_source_id_line` | Sim: ordem e texto exatos das duas linhas |
| CA-06 | `split.py` `_fraction_argument` | `test_ca06_underflow_refused`, `test_ca06_representable_values_accepted` | Sim: `<splits>` vazio e `max_external_fraction` gravado |
| CA-07 | `data.py` `parse_csv(exact_header)`, `_read_sources`, `HEADER_PROBLEMS` | `test_ca07_*` (a/b/c, `validate` CLI, `missing_column`) | Sim |
| CA-08 | `data.py` `_read_registry` | `test_ca08_*` (a/b/c com `load_manifest`, `load_external_sources` e `release-notes`; cabeçalho exato) | Sim: o caso (c) da `license` repetida é recusado |
| CA-09 | `synthetic.py` `make_synthetic_dataset` | `test_ca09_*` | Sim: contagem de 1.111 `item_id`, pares únicos e `load_manifest` |
| CA-10 | `export.py` `export_onnx` (`try`/`finally`) | `test_ca10_export_warnings_logged_in_finally` (`ast`) | Sim: falha na base |
| CA-11 | `export.py` | `test_ca11_export_logs_warnings_when_it_raises` (`slow`) | Sim, com torch: registro único `torch.onnx.export: <marcador1>` e `RuntimeError` original |

### Verificações executadas nesta revisão (read-only, sem banco)

- `uv run ruff check .` e `uv run ruff format --check .`: limpos.
- `env -u CI -u TEST_DATABASE_URL uv run pytest -q ml/tests/acceptance/test_spec_037.py ml/tests/test_maintenance_037.py ml/tests/test_export_warnings.py`: **148 passed, 3 skipped** (torch ausente).
- `env -u CI -u TEST_DATABASE_URL uv run pytest -q ml/tests tests`: **1176 passed, 28 skipped** (torch, `model.onnx` local e banco ausentes). O número bate com o do dev-report (1108 passed, 26 skipped) somado aos 68 passed e 2 skipped do `test_spec_037.py`.
- `git log`/`git show --stat` de cada commit da branch para conferir a R-07, e `git diff origin/main...HEAD` para conferir o texto da SPEC e as dependências.

## Pontos positivos

- Uma função só (`check_counts`) para os dois comandos, com o mesmo `sorted` do `source_lines`. Assim, a ordem dos campos no erro e a das linhas geradas nunca divergem.
- `InvalidCountsError` como subclasse de `ValueError`, tratada antes do genérico. Os outros erros continuam com as mensagens da SPEC-035.
- `exact_header` só por palavra-chave, ligado só nos dois leitores novos, com um teste de autor que garante o manifest com o cabeçalho flexível (`test_manifest_keeps_the_loose_header`).
- No export, `caught` é inicializado antes do `try`, e o `finally` fica fora do `catch_warnings`, como a SPEC preferia.
- Controles negativos bem documentados pelo autor (CA-11) e pelo tester (base inteira extraída para um `PYTHONPATH` temporário, sem tocar a worktree).

## Observações para o orquestrador (sem severidade)

- O Histórico da SPEC registra a resposta do humano à pergunta 3 do §9 como "posição no loop logo depois da 036", e a SPEC-036 ainda está `Ready`. Se a ordem mudou por decisão posterior do humano, nada a fazer. Se a SPEC-036 for mergeada antes, confirme que o importador grava exatamente `SOURCE_COLUMNS`, porque o leitor agora recusa outro cabeçalho com `unexpected_header`.
- A suíte com banco fica com o orquestrador antes do PR, como no test-report. Esta SPEC não toca API nem banco.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
