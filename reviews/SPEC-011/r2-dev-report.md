# SPEC-011 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) |
| Rodada | r2 |
| Autor | ml-engineer |
| Branch | `spec/SPEC-011-ml-dados-split` |
| Commits | `f66c995` (fix(ml): peças refotografadas mantêm o split anterior), mais o commit deste relatório |

## Resumo

Corrigi o RV-01 (= T-01). Com um split anterior, uma peça só contava como "já presente" se alguma imagem **atual** dela estivesse nesse split. Assim, uma peça de teste com todas as fotos excluídas e depois refotografada era tratada como peça nova e ia para o treino.

Agora `make_split` descobre o `item_id` de **toda** imagem do split anterior, nesta ordem:
1. pela linha atual do `df`;
2. pelas linhas excluídas do manifest, que `load_manifest` passa a guardar em `df.attrs["excluded_items"]` (`image_path → item_id`) e que `make_split` completa com as linhas do próprio `df` que estejam em `excluded`;
3. pelo nome de arquivo da SPEC-010 (`<item_id>__<angle>__<ts>.jpg`), no caso de uma imagem removida do manifest sem exclusão.

A peça recebe o split anterior. Se as imagens antigas dela estiverem em dois splits, continua valendo o `SplitIntegrityError`. Assinaturas, CAs e formatos de arquivo não mudaram.

## Rastreabilidade (critério de aceite → implementação)

Os CAs e os arquivos são os da r1 (ver `r1-dev-report.md`). A mudança da r2 está em `split.py` (`_previous_item_ids`, `IMAGE_FILE_PATTERN`, `make_split`) e em `data.py` (`load_manifest` grava `excluded_items` em `df.attrs`). Testes novos em `ml/tests/test_split.py`:

| Item | Teste do autor |
|---|---|
| RV-01: peça de **teste** e peça de **validação**, cada uma com todas as imagens excluídas e depois refotografadas, herdam o split (CLI de ponta a ponta), e as demais linhas do v1 não mudam | `::test_rephotographed_items_keep_their_split` |
| RV-01: imagem removida do manifest **sem** exclusão (peça de validação); as fotos novas herdam `val` pelo nome de arquivo das antigas; avisos `missing_previous_image` | `::test_removed_without_exclusion_uses_the_file_name` |
| RV-01: `make_split` chamado sem `df.attrs` (DataFrame montado à mão) usa as linhas do `df` que estão em `excluded` | `::test_excluded_images_without_attrs_use_the_rows_of_df` |
| RV-01: imagens antigas da peça (uma excluída) em dois splits → `SplitIntegrityError` | `::test_old_images_of_an_item_in_two_splits_is_an_integrity_error` |
| RV-03: `small_stratum` de peças novas com `"scope": "new_items"` | `::test_small_stratum_of_new_items_has_a_scope` |

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-review-report.md` RV-01 (alta) = `r1-test-report.md` T-01 | Corrigido como descrito no Resumo. Usei as duas fontes sugeridas: (a) `df.attrs["excluded_items"]` para as linhas excluídas, que são o caso do T-01; (b) o nome de arquivo da SPEC-010 só para imagens que não estão no manifest. A linha do manifest tem precedência sobre o nome do arquivo ("conferir contra o manifest quando a linha existir"). Uma imagem antiga sem linha e com nome fora do formato continua sendo ignorada para esse fim, como antes. Não precisei registrar `SPEC_ISSUE` para o subcaso "removida sem exclusão", porque o formato do nome é definido pela SPEC-010. O `test_bug_t01_rephotographed_test_item_keeps_test` do tester agora dá **XPASS**. A conversão para um teste normal, sem o `xfail`, é do tester. |
| RV-02 (baixa), `.JPG` como órfão | Nada mudou no código, como o reviewer indicou. O registro na SPEC fica com o architect. |
| RV-03 (baixa), `small_stratum` no split congelado | Feito, de forma opcional e compatível: no modo congelado, o aviso continua com `code: "small_stratum"` e ganha o campo `"scope": "new_items"`. No `split_v1`, o aviso não muda (o CA-14 e o teste do autor da r1 continuam iguais). A regra de alocação não mudou. |
| RV-04 (baixa), códigos defensivos, `qwk: null` e exclusões na concordância | Nada mudou no código, como o reviewer indicou. O registro na SPEC fica com o architect. |

## Como rodar e verificar

```bash
uv sync --all-packages                   # ambiente do CI, sem o extra train
uv run pytest -q ml/tests
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultados (sem torch: `import torch` falha):
- `ruff check` e `ruff format --check` limpos (182 arquivos);
- suíte inteira: **4597 passed, 4 skipped, 1 xpassed**. O XPASS é o `test_bug_t01_rephotographed_test_item_keeps_test`. Os pulados são os dois testes de torch do arquivo de aceite, o `ml/tests/test_dataset.py` e o CA-16 manual da SPEC-008.

## Decisões tomadas dentro do escopo da SPEC

- **Precedência das fontes de `item_id`:** linha atual do `df` > linha excluída do manifest > nome do arquivo. O nome só é lido quando a imagem não tem nenhuma linha. O padrão é o da SPEC-010, com `[SNOT]-[0-9]{3}`, ângulo `[0-4]`, timestamp `AAAAMMDDTHHMMSSZ` e `.jpg` minúsculo.
- **`df.attrs["excluded_items"]`:** chave nova em `attrs`, ao lado de `manifest_sha256` e `n_excluded`, sem mudar a assinatura de `load_manifest`. Não entra no relatório de dados, que não mostra caminhos de imagens excluídas.
- **Avisos:** não criei um aviso próprio para "peça mantida pelo split das imagens antigas". As imagens que saíram continuam gerando `excluded_previous_image` ou `missing_previous_image`, como na r1, e nenhuma peça muda de conjunto.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`ml/tests/test_split.py`: 30 passed)
- [x] Suíte inteira sem o extra `train`: 4597 passed, 4 skipped, 1 xpassed
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nada de `ml/data/` lido, copiado ou commitado
