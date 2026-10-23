# SPEC-031 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-031](../../docs/specs/SPEC-031-manutencao-ml.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...c0cd799` (16 commits, de `3913c86` a `c0cd799`; base real do branch `9633985`, merge do PR #40) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 2 achados baixos, que não bloqueiam, e nenhum `SPEC_ISSUE`.

Conferências que rodei (só leitura):

- `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q -p no:cacheprovider` (sem torch, ambiente do CI): `5758 passed, 54 skipped, 1 warning`, a mesma contagem do test-report;
- `uv run pytest -q ml/tests tests`: `778 passed, 26 skipped`, a mesma contagem do test-report;
- `uv run ruff check .` (`All checks passed!`) e `uv run ruff format --check .` (`227 files already formatted`);
- `uv lock --check` (`Resolved 115 packages`), `torch` travado em `2.14.1` no `uv.lock`, e `import torch` falha no `.venv` (ambiente de volta ao estado do CI);
- `git merge-tree --write-tree origin/main HEAD`: sem conflito (a `main` avançou só com docs, PRs #38 e #41);
- busca de segredos nas linhas adicionadas (`secret`, `token`, `password`, `postgres://`, `eyJ`, `api_key`): só aparecem a regex do CA-26 da SPEC-012 no teste do notebook, caminhos fictícios de imagem num teste de `Predictions` e a URL do banco de teste local, sem senha, nos relatórios.

A parte `slow` do CA-05 (com torch) não rodei: exigiria `uv sync --extra train`, que altera o `.venv`. Conferi o código do teste e o registro do test-report (`2 passed` com o torch `2.14.1`, com o registro `WARNING qc_ml.export ... torch.onnx.export: partqc-spec031-ca05-marker`).

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `ml/src/qc_ml/export.py:93-106` | `_log_export_warnings(caught)` roda **depois** do bloco `with warnings.catch_warnings(record=True)`. Se o `torch.onnx.export` levantar exceção, os avisos já capturados (por exemplo, o aviso de depreciação que explicaria a quebra do caminho TorchScript) são descartados sem log, porque o `record=True` também impede que apareçam no stderr. A exceção em si continua visível, então a checagem do notebook (§4.3, item 3) ainda falha alto; só se perde o contexto. A SPEC não trata desse caso, e o comportamento pedido (avisos registrados num export que termina) está certo. | Numa SPEC futura do ML: envolver o `torch.onnx.export` em `try/finally` e chamar `_log_export_warnings(caught)` no `finally`, com um teste unitário em que o export embrulhado emite um aviso e depois levanta. |
| RV-02 | baixa | `tests/test_dependency_isolation.py:74` | A igualdade passou a ser entre **conjuntos de nomes**. Duas entradas distintas com o mesmo nome (por exemplo, `"torch<2.15"` e `"torch>=2"`) colapsam num só `torch` e o teste não as acusa. É exatamente o que a §4.8 prescreve (o `declared` já era um conjunto antes), e o CA-04 desta SPEC cobre o caso do `torch` no aceite (`test_ca04_torch_ceiling_in_pyproject_and_lock` exige uma única entrada `torch`). Também não há normalização PEP 503 (`_`/`.` → `-`), que a §4.8 não pede e que os nomes atuais não precisam. | Nada nesta SPEC. Se o teste for tocado de novo, comparar também `len(declared) == len(names)` para que entradas duplicadas falhem. |

### Observações sem severidade

- O test-report diz que o controle negativo usou "a base do branch (`3ed113c`)". A base real do branch é `9633985` (pai de `3913c86`). Conferi que `git diff 3ed113c 9633985 -- ml/` é vazio, então o controle negativo vale do mesmo jeito.
- Decisão 3 do dev-report: além dos `DeprecationWarning`, os outros avisos capturados também viram `WARNING` (`torch.onnx.export (<Categoria>): …`). A §4.3 só fala dos de depreciação, mas o `catch_warnings(record=True)` capturaria todos, e logá-los evita que sumam em silêncio. Nenhum é reemitido, como a SPEC pede. Aceito como decisão dentro do escopo, registrada no dev-report.

## Pontos pedidos pelo orquestrador

### §4.8: o CA-08 da SPEC-001 continua verificado

`git show bde95df` (`Agent: developer`, `Refs: SPEC-031`) toca só `tests/test_dependency_isolation.py`, com 3 linhas a mais e 1 a menos:

- `import re` acrescentado;
- `assert declared == {...}` (antiga linha 73) trocado por `names = {re.match(r"[A-Za-z0-9._-]+", dep)[0].lower() for dep in declared}` e `assert names == {"torch", "torchvision", "timm", "onnx", "coral-pytorch"}`.

O conjunto esperado é o mesmo, com os mesmos cinco nomes, e a comparação continua de **igualdade** (`==`), nem subconjunto nem superconjunto: um nome a mais ou a menos no extra `train` falha. A regex é a da §4.8 e o nome sai em minúsculas. Não se usa `packaging`. Uma string que não comece com um nome válido daria `TypeError` no `[0]`, o que também falha o teste. As outras asserções do arquivo (sobre o `uv.lock`, a R-12 e o fecho do `qc-api`/`qc-dashboard`) não mudaram. O adendo do developer está num commit separado (`03b46be`, `Agent: developer`), só em `reviews/SPEC-031/r1-dev-report.md`, no fim do relatório, com o sha e o resultado (`14 passed`). O resto do relatório do ml-engineer não mudou nesse commit (20 linhas acrescentadas, nenhuma removida).

### Ajustes do tester em `ml/tests/acceptance/test_spec_012.py` (`docs/architecture.md` §10)

Conferi o diff linha a linha: são exatamente 2 linhas trocadas, as duas na tabela do test-report, e nenhuma asserção mudou.

| Ajuste | Conferência |
|---|---|
| `test_ca17_unusable_threshold_for_recall_90pct` (`:733`): `1.0 - 0.55 - p` → `1.0 - (0.55 + p)` | ✅ §3.1 e §4.2 ("Efeito nos CAs da SPEC-012", CA-17); é a forma citada como exemplo na própria §3.1. Mesmo valor matemático; para `p = 0.45`, `0.55 + 0.45` arredonda para `1.0` e `fair` dá `0.0` exato, e os outros 9 valores continuam positivos. As asserções (`unusable_threshold == 0.12`, recall 0,9, caso `unusable_target_not_met`) não mudaram, então a intenção do CA-17 da SPEC-012 continua verificada. |
| `test_ca18_review_threshold_targets_10pct`, segundo caso (`:761`): `0.5525 + 0.005 * i` → `min(0.5525 + 0.005 * i, 1.0)` | ✅ §3.1 e §4.2 (CA-18). Só as imagens com i ≥ 90 mudam (de 1,0025–1,0475 para 1,0), todas acima de 0,60; continuam 10 imagens abaixo de 0,60, e as asserções (`grade_review_threshold == 0.60`, sem `review_adjusted`) não mudaram. |

Nenhum `test_caNN_` foi removido ou renomeado. Os dois ajustes vão no commit do tester (`7683359`, `Agent: tester`).

### Trailers `Agent:` contra os arquivos tocados (R-07)

`git log --format='%h %s%n%(trailers:key=Agent)'` + `git show --stat` de cada commit. Todos os 16 commits têm `Refs: SPEC-031` e `Agent:`, com a identidade `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`.

| Papel | Commits | Arquivos | Conferência |
|---|---|---|---|
| ml-engineer | `625e48d`, `5e7d721`, `177d75f`, `dcd278b`, `3bdd80c`, `c041309`, `14e7e51` | `ml/src/qc_ml/{parity,predict,export,split}.py`, `ml/pyproject.toml`, `uv.lock`, `ml/README.md`, notebook, `ml/tests/test_*.py` (fora de `acceptance/`), `reviews/SPEC-031/r1-dev-report.md` | ✅ Dentro de `ml/**`, mais o `uv.lock` pela exceção da §4.7 (commit `177d75f`: diff de 1 linha, só o `requires-dist` do `torch` no `qc-ml`, `specifier = "<2.15"`; nenhuma versão resolvida mudou; `uv lock --check` passa). Nenhum arquivo de `acceptance/`. |
| developer | `bde95df`, `03b46be` | `tests/test_dependency_isolation.py`; adendo no dev-report | ✅ Exatamente o que a §4.8 autoriza, em commits separados. |
| tester | `7683359` | `ml/tests/acceptance/test_spec_031.py` (novo), `ml/tests/acceptance/test_spec_012.py` (2 linhas), `reviews/SPEC-031/r1-test-report.md` | ✅ Nenhum código de produção. |
| architect | `8521ec7` | `docs/specs/SPEC-031-manutencao-ml.md`, `docs/plan.md` | ✅ Correção dos SPEC_ISSUE-01 e 02. |
| orchestrator | `3913c86`, `b4d1441`, `dc83c6c`, `0e4d486`, `c0cd799` | `docs/plan.md`, status nas SPECs 030 e 031 | ✅ Só status, `Done` da SPEC-030 no primeiro commit e a linha de reaprovação humana no Histórico. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os 9 CAs têm implementação e teste de aceite (rastreabilidade no dev-report e cobertura no test-report). Nada fora do §3.1: o diff de produção toca só `parity.py`, `predict.py`, `export.py`, `split.py`, `ml/pyproject.toml`, `uv.lock`, README e notebook. Nenhum CA foi reinterpretado: o `np.maximum` (em vez do `np.fmax` dado como exemplo) atende ao texto "uma forma que não descarta `NaN`" e é coerente com o §7; o `IMAGE_FILE_PATTERN` montado a partir de `ITEM_ID_PATTERN.pattern` foi necessário para o CA-09 e é idêntico caractere a caractere. ADR-019: **não houve reaprovação delegada nesta branch**. A correção do `8521ec7` classificou o SPEC_ISSUE-01 como elegível e o 02 como "exige humano" (X-5, X-7), e as duas foram reaprovadas **pelo humano** em 2026-10-20 (linha do Histórico e aviso no topo da SPEC, commit `dc83c6c`). Conferi o `git show 8521ec7`: muda só a SPEC-031 e o `docs/plan.md`, sem tocar nos CAs da SPEC-031 nem na SPEC-012 (`Done`). |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova (só o teto do `torch`). R-02, R-05, R-06: N/A (nada de borda, API ou dados). R-03: sem segredos; nenhuma variável nova. R-04: contrato intocado. R-07: ver a tabela acima. R-11: o split não muda (o `IMAGE_FILE_PATTERN` e o `ITEM_ID_PATTERN` geram as mesmas regex, conferido pelos exploratórios do tester); `Predictions` só ganhou validação, os limiares continuam saindo da validação. R-12: `qc-api` e `qc-dashboard` sem torch (14 testes de `tests/test_dependency_isolation.py` passam, e o CA-04 percorre o fecho do lock); `uv.lock` coerente. R-13: identidade CarlosZeyy em todos os commits, Conventional Commits. |
| 3. Corretude | ✅ | Paridade: forma dos dois pares, depois finitude (saída do ONNX e referências da fixture), depois as diferenças; `sha256_match` calculado como antes; a CLI continua saindo com 2. `Predictions`: a finitude vem antes da faixa (necessário, porque `NaN < 0` é falso), e `probs.size` protege o `min()` em `n = 0`; mensagens só com o nome do campo. Export: `simplefilter("always")` dentro do bloco faz o registro funcionar mesmo com um filtro `"error"` de fora, como o CA-05 exige. Ver RV-01 sobre avisos perdidos quando o export levanta. |
| 4. Testes | ✅ | Test-report PASS, um teste por CA e 16 exploratórios, com controle negativo (sem a SPEC, 22 falham e 7 passam). Os testes de paridade alteram só cópias da fixture em `tmp_path`; nenhum usa rede. O subprocesso do CA-01 roda `python -m qc_ml.parity`, não o pytest. Ajustes do §10 conferidos acima. Testes do autor em `ml/tests/` (fora de `acceptance/`), incluindo o lado só-ONNX com `NaN` e os 3 parâmetros `slow` do aviso. O `_review_preds` de `ml/tests/test_thresholds.py` (teste do autor) recebeu o mesmo `min(…, 1.0)`, com o resultado esperado inalterado. |
| 5. Qualidade | ✅ | `ruff` limpo; type hints e docstrings nas funções novas; sem `print`; o `ITEM_ID_PATTERN` agora tem uma só definição. README ("Do Colab ao Release", passo 0 com o comando real do `qc_ml.split`, cujas flags `--dataset-dir`, `--splits-dir` e `--seed` existem) e notebook atualizados; o notebook continua sem saídas, sem `def`/`class` e sem token. |
| 6. Segurança | N/A | SPEC sem tag `security` ou `deploy`. |

## Pontos positivos

- A checagem de finitude vem antes de qualquer diferença, e o comentário no código explica por que o `max()` do Python perdia o `NaN`.
- O notebook ganha a checagem do export logo depois da instalação, e o ml-engineer conferiu que o `model.sha256` gerado é idêntico ao da fixture versionada, o que mostra que o teto não mudou o grafo exportado.
- Os dois SPEC_ISSUE foram levantados em vez de contornados (nenhuma edição em `acceptance/` nem no teste do developer), e a §4.8 foi aplicada pelo papel certo, com um commit só do arquivo.
- O tester rodou um controle negativo contra o código sem a SPEC e documentou a observação sobre o pixel `NaN` que a convolução não lê.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
