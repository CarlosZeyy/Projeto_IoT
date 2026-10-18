# SPEC-011 — r3 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) (corrigida em `60ce217`, reaprovada pelo humano) |
| Rodada | r3 (última, R-10) |
| Autor | ml-engineer |
| Branch | `spec/SPEC-011-ml-dados-split` |
| Commits | `5e30539` (feat(ml): congelamento do split sobre o histórico inteiro), mais o commit deste relatório |

## Resumo

Implementei a §4.4 nova, que resolve o SPEC_ISSUE-01 da r2 (RV-05 = T-02). A peça passa a manter o conjunto que teve em **qualquer** versão anterior do split, e não só na de maior N. Tudo em `ml/src/qc_ml/split.py`:

- **`item_id_resolver(df)`** (função pública auxiliar): resolve o `item_id` de uma imagem de um split anterior pelas três fontes, nesta ordem:
  1. a linha de `df`, inclusive uma linha que esteja em `excluded`;
  2. `df.attrs["excluded_items"]`, **só** se o `item_id` casar `[SNOT]-[0-9]{3}` (RV-06); senão, passa à fonte 3;
  3. o nome de arquivo da SPEC-010.

  Sem fonte, devolve `None`, e a imagem é ignorada.
- **`item_history(splits, df) -> dict[str, str]`:** percorre todas as versões e devolve `item_id → split`. Uma peça em dois splits, entre versões ou dentro de uma só, levanta `SplitIntegrityError` com o `item_id` e, para cada split, os arquivos de onde veio. O pipeline não resolve o conflito.
- **`make_split(..., history=None)`:**
  - valida o `history`: valor fora de `train`/`val`/`test` → `SplitError`; não vazio sem `previous` → `SplitError`;
  - uma peça é antiga se estiver no `history` **ou** se alguma imagem do `previous` resolver para ela;
  - o split dela é o do `history` ou, sem entrada, o do `previous`;
  - `history` diferente do `previous` → `SplitIntegrityError` com o `item_id`;
  - imagens da peça no `previous` em dois splits → `SplitIntegrityError`;
  - uma entrada do `history` sem imagens em `df` é ignorada;
  - os avisos e o `SplitError` de imagens ausentes continuam olhando só o `previous`.
- **CLI, passos 1 a 6 da §4.4:**
  1. manifest e exclusões;
  2. lista os `split_v<N>.csv`;
  3. exige as versões `1…M` sem lacuna; senão, sai com 2, `split history incomplete: missing split_v<K>.csv, ...` na saída de erro e nada gravado;
  4. lê todas as versões com `load_split`; um erro sai com 2 e com o nome do arquivo na saída de erro;
  5. `previous` = versão `M`, `history = item_history(todas)`; um conflito sai com 2 e com a mensagem do `SplitIntegrityError`;
  6. `make_split(..., history=history)`, gravando `split_v{M+1}` só se houver mudança.

  Todo erro sai antes de qualquer gravação.

O `data.py` não mudou na r3. O `excluded_items` já era gravado na r2 com o `item_id` como está na linha, que é o que a §4.1 nova descreve. O filtro do RV-06 fica na fonte 2, na resolução do split.

## Rastreabilidade (critério de aceite → implementação)

Os CA-01 a CA-32 continuam como na r1/r2 (`r1-dev-report.md`). Os novos, com os testes do autor em `ml/tests/test_split.py`:

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-33 | `split.py` (`item_history`, `make_split` com `history`, `main` passos 3 a 6) | `::test_cli_rephoto_after_an_intermediate_split` (sequência do CA-33 com o dataset do CA-12, peça de teste e de validação, comparação do conjunto de `item_id` de teste v3 × v1) |
| CA-34 | `split.py` (`main` passos 3 a 5, `item_history`) | `::test_cli_gap_in_the_history` (faltando o `split_v1.csv` com `.sha256`/`.json` mantidos, e lacuna no meio), `::test_cli_hash_mismatch_in_an_old_version` (hash divergente no `split_v1`, que não é a última), `::test_cli_conflict_in_the_history` (caso (c) e `item_history` direto); todos conferem que `--splits-dir` fica igual byte a byte |
| CA-35 | `split.py` (`make_split`) | `::test_make_split_with_history`, `::test_make_split_history_validation` |

Itens da §6 (autor) além dos CAs:

| Item da §6 | Teste |
|---|---|
| `item_history` com 1 e com 3 versões | `::test_item_history_one_and_three_versions` |
| conflito dentro de uma versão e entre versões | `::test_item_history_conflicts_are_never_resolved` |
| as três fontes e a precedência entre elas; `item_id` inválido em `excluded_items` ignorado (passa ao nome do arquivo) | `::test_resolver_sources_and_precedence` |
| `history` com valor inválido, sem `previous` e em conflito com o `previous` | `::test_make_split_history_validation` |
| CLI com lacuna (inclusive faltando o `split_v1`) e com hash divergente numa versão que não é a última | `::test_cli_gap_in_the_history[1]`, `[2]`, `::test_cli_hash_mismatch_in_an_old_version` |

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r2-review-report.md` RV-05 (alta) = T-02, via SPEC_ISSUE-01 | Implementado conforme a §4.4 corrigida (Resumo). O `test_bug_t02_rephoto_after_an_intermediate_split_keeps_test` do tester agora dá **XPASS**. |
| `r2-review-report.md` RV-06 (baixa) | Feito na fonte 2 (`item_id_resolver`): um valor de `excluded_items` que não casa `re.fullmatch(r"[SNOT]-[0-9]{3}", ...)` é ignorado, e a imagem passa ao nome do arquivo. |

## Teste de aceite que a §4.4 nova invalida (para o tester)

`ml/tests/acceptance/test_spec_011.py::test_extra_split_versions_use_numeric_order` **falha**, e não alterei o arquivo (R-07).

O teste cria `split_v1`, `split_v9` e `split_v10` (lacuna de 2 a 8) e espera saída 0 com `split unchanged: split_v10`. A §4.4 nova, passo 3 ("as versões encontradas têm de ser exatamente `1, 2, …, M`. Faltando alguma → exit 2, com a saída de erro contendo `split history incomplete`"), exige saída 2 nesse cenário.

A falha é consequência direta do requisito novo, e não um bug. A intenção do teste (ordem numérica, e não lexicográfica, das versões) pode continuar sendo verificada com as versões 1 a 10 completas. Pela regra de `docs/architecture.md` §10 ("Testes de aceite de SPECs anteriores"), aplicada aqui ao arquivo da própria SPEC, o ajuste é do tester.

## Como rodar e verificar

```bash
uv sync --all-packages                   # ambiente do CI, sem o extra train
uv run pytest -q ml/tests/test_split.py  # 40 passed
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultados (sem torch: `import torch` falha):
- `ruff check` e `ruff format --check` limpos (182 arquivos);
- suíte inteira: **4617 passed, 4 skipped, 1 xpassed, 1 failed**:
  - o XPASS é o `test_bug_t02_*`;
  - a falha é o `test_extra_split_versions_use_numeric_order`, descrito acima;
  - os pulados são os dois testes de torch do arquivo de aceite, o `ml/tests/test_dataset.py` e o CA-16 manual da SPEC-008.

## Decisões tomadas dentro do escopo da SPEC

- **`#<posição na lista>` é o índice da lista em Python, começando em 0** (`#0` para o primeiro `DataFrame`). Ele só aparece quando o `DataFrame` não tem `attrs["split_file"]`, ou seja, quando foi montado à mão. Pela CLI, as mensagens sempre trazem `split_vN.csv`. Nenhum CA depende disso. Se o architect preferir contar a partir de 1, a troca é de um caractere.
- **Formato das mensagens:**
  - conflito: `split history conflict (R-11; never resolved automatically): item S-003 is in more than one split: test in split_v2.csv; val in split_v1.csv`. Os splits saem em ordem alfabética e os arquivos na ordem das versões; vários conflitos são separados por ` | `;
  - lacuna: `split history incomplete: missing split_v1.csv[, ...] (restore it from Git; ...)`;
  - erro de leitura de uma versão: `split error: split_vK.csv: <motivo>`.
- **`item_id_resolver` é público**, porque `make_split` e `item_history` compartilham as mesmas fontes, e ter uma única função evita divergência. O resolvedor de `make_split` é montado com o `df` **antes** de tirar as linhas em `excluded`, para a fonte 1 incluir essas linhas, como a §4.4 manda.
- **Ordem das validações de `history` em `make_split`:** primeiro "sem `previous`", depois os valores inválidos. Os dois casos levantam `SplitError`, então a ordem não muda o resultado de nenhum CA.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`ml/tests`: todos; `test_split.py`: 40 passed)
- [x] Suíte inteira sem o extra `train`: 4617 passed, 4 skipped, 1 xpassed; 1 falha num teste de aceite invalidado pela §4.4 nova (acima)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada de `ml/data/` lido, copiado ou commitado
