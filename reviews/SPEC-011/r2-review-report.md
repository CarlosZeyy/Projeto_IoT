# SPEC-011 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `origin/main...1d496c5` (25 arquivos, +5775/−5); diff da r2: `4f79349..1d496c5` |
| Test report | [r2-test-report.md](r2-test-report.md) (PASS, com o T-02 alto) |
| **Veredicto** | **CHANGES_REQUESTED** |

O RV-01 da r1 foi corrigido no caso descrito, e a correção está bem feita e bem testada. O T-02 do tester, porém, é real e tem o mesmo efeito do RV-01: uma peça do teste congelado vai para o treino. A diferença é a causa. O T-01 era um defeito da implementação; o T-02 vem da **letra da §4.4**, que define o congelamento só contra "o split de maior N". Qualquer correção exige decidir a fonte do histórico das peças e, provavelmente, mudar uma interface ou um formato fixado pela SPEC. Por isso registro o **SPEC_ISSUE-01** para o architect, em vez de pedir ao autor que improvise na r3, que é a última rodada (R-10).

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-05 | **alta** (depende do SPEC_ISSUE-01) | `ml/src/qc_ml/split.py:263-269` (`make_split`); `:503` (CLI `main`: `previous = load_split(... split_v{versions[-1]} ...)`); SPEC §4.4 | **T-02 confirmado.** Com `--runxfail`, `test_bug_t02_rephoto_after_an_intermediate_split_keeps_test` falha com `['train', 'train'] != ['test', 'test']`.<br><br>**A sequência:**<br>1. `split_v1`;<br>2. todas as fotos de uma peça de teste são apagadas e registradas em `exclusions.csv`;<br>3. `python -m qc_ml.split` grava o `split_v2` sem a peça, como manda o `docs/dataset-protocol.md` §8.1, passo 5;<br>4. a peça é refotografada com o mesmo `item_id` (§8, passo 1);<br>5. o `split_v3` põe as fotos novas no treino.<br><br>**Causa:** `make_split` só conhece o `previous` que recebe, e a CLI passa o de maior N. O `split_v2` não tem nenhuma imagem da peça, então ela volta a ser "nova". A informação de que ela era de teste só existe no `split_v1.csv` e nos avisos `excluded_previous_image` do `split_v2.json`.<br><br>**Impacto:** é o mesmo do RV-01 da r1. O teste congelado (1 ou 2 peças por grau, ADR-014) perde em silêncio uma peça que poderia manter, e uma peça física do teste vira dado de treino. A ordem do T-02 (rodar o split logo depois da exclusão) é a que o próprio protocolo sugere, então é o caminho mais provável na S3. Pelo mesmo mecanismo, uma peça de validação pode cair no treino, e uma de treino na validação.<br><br>**Por que não peço a correção direto ao autor:** o código segue a letra da SPEC. A §4.4 diz "`previous` = split anterior", e a CLI "usa o de maior N como `previous`"; "peças já presentes" só pode ser lido contra esse `previous`. Corrigir exige escolher entre mecanismos que mudam o que a SPEC fixa: o que a CLI passa como `previous`, um parâmetro novo em `make_split` ou um campo novo no `split_v<N>.json`. A regra do projeto é registrar `SPEC_ISSUE` e não improvisar. | Ver o SPEC_ISSUE-01. Depois da decisão do architect: **r3 (ml-engineer)** implementa o texto novo, com teste unitário; **r3 (tester)** transforma o `test_bug_t02_*` num teste normal, sem o `xfail`, e cobre o CA novo. |
| RV-06 | baixa | `ml/src/qc_ml/data.py:486-488` | **`item_id` de uma linha excluída entra em `excluded_items` sem validação** (observação do tester). As linhas excluídas pulam as validações de linha (§4.1), então um `item_id` malformado ou trocado numa linha excluída daria uma herança errada ou um `SplitIntegrityError` falso. O risco é baixo: a linha foi escrita pela borda, que valida o `item_id` (SPEC-010), e um `item_id` malformado não casa com nenhuma peça atual. | Opcional na r3: só usar a linha excluída como fonte se o `item_id` casar com `ITEM_ID_PATTERN`. Não precisa de mudança na SPEC. |

Os achados baixos da r1 (RV-02 a RV-04) continuam válidos e não bloqueiam. O RV-03 foi atendido (`"scope": "new_items"`), e o RV-02 e o RV-04 aguardam o registro na SPEC pelo architect, que pode ser feito junto com o SPEC_ISSUE-01.

## Conferência da correção do RV-01 (r1)

- **Implementação** (`f66c995`):
  - `load_manifest` grava `df.attrs["excluded_items"]` (`image_path → item_id` das linhas excluídas). Isso não aparece no relatório de dados, então nenhum caminho de imagem excluída vaza.
  - `_previous_item_ids` (`split.py:156-177`) resolve o `item_id` de toda imagem do split anterior, nesta ordem de precedência: linha atual do `df`, linha excluída e, por último, nome de arquivo. O padrão `IMAGE_FILE_PATTERN` confere com o formato da SPEC-010 §4.2, passo 3 (`<item_id>__<angle>__<ts:%Y%m%dT%H%M%SZ>.jpg`).
  - Uma peça com imagens antigas em dois splits continua dando `SplitIntegrityError`.
  - Uma imagem de teste removida **sem** exclusão continua sendo `SplitError` (CA-18 preservado, e o tester confirmou que a foto nova não "legaliza" a remoção).
  - Assinaturas, CAs e formatos não mudaram.
- **Testes do autor:** 5 testes novos em `ml/tests/test_split.py`, para teste e validação por CLI, o fallback pelo nome, a chamada sem `attrs`, o conflito e o `scope`.
- **Conversão do T-01:** o `test_bug_t01_*` virou `test_extra_t01_rephotographed_test_item_keeps_test` (`test_spec_011.py:1471`), sem `xfail`, com as mesmas asserções. A única diferença é que a exclusão passou para o auxiliar `exclude_item`. Passa no commit atual. Os 32 `test_caNN_*` não mudaram.
- **Segurança dos testes (observação da r1):** o tester criou `safe_unlink`, que resolve o caminho e confere `is_relative_to(dataset)` antes de apagar, e todo teste novo apaga só por ele.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ❌ (RV-05, SPEC_ISSUE-01) | A r2 mexe só no que o RV-01 e o RV-03 pediram, e nada além. Nenhum CA foi alterado: as mudanças da SPEC na branch são só de status, pelo orquestrador (`b92d304`, `04eebf3`, `1d496c5`). As decisões da r2 (precedência das fontes de `item_id`, `excluded_items` em `attrs`, sem aviso novo) estão no dev-report e cabem no texto. O T-02 depende de uma decisão que a SPEC não toma. |
| 2. Regras inegociáveis | ✅ | **R-01/R-12:** nenhuma dependência nova. `pyproject.toml` e `uv.lock` intactos, e o diff não toca `api/`, `dashboard/` nem `edge/`. **R-02/R-14:** `git ls-files ml` sem imagens e sem `ml/data/`; os testes usam só dados sintéticos em `tmp_path`. **R-03:** nada novo na busca por segredos. **R-07:** os 6 commits da r2 têm `Agent:`. O do `ml-engineer` (`f66c995`) toca só `ml/src/` e `ml/tests/test_split.py`, e o `419b917` só o dev-report. O do `tester` (`00e1a8e`) toca só `ml/tests/acceptance/test_spec_011.py` e o test-report. Os do `orchestrator` tocam só status e plano. **R-11:** dentro de cada versão do split, nenhuma peça fica em dois conjuntos, e o teste não é usado para escolhas. O congelamento entre versões fica para o SPEC_ISSUE-01. **R-13:** todos os commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits com `Refs: SPEC-011`. |
| 3. Corretude | ❌ (RV-05) | A correção do RV-01 está correta nos casos cobertos (ver a conferência acima). Os `attrs` são lidos antes do filtro de exclusões. O fallback pelo nome só entra quando a imagem não tem nenhuma linha. Sem async, sem SQL e sem datas novas. |
| 4. Testes | ✅ | O test-report é PASS, com os 32 CAs inalterados. **Rodei:** `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` → **4608 passed, 4 skipped, 1 xfailed** em 281 s, sem o extra `train` (`import torch` falha), igual ao test-report; `git status` limpo depois. O `xfailed` é o T-02. Com `--runxfail`, o T-01 passa e o T-02 falha. Nenhum teste de aceite de SPEC anterior foi tocado. Nenhum teste roda o pytest em subprocesso, e não há credencial literal em URL. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (182 arquivos). As docstrings de `make_split` e `load_manifest` foram atualizadas, e há type hints. Única nota menor: `split.py:219-225` monta a mesma máscara `isin(list(excluded))` duas vezes, o que é inofensivo. |
| 6. Segurança | N/A | A SPEC não tem a tag `security` nem `deploy`. |

## Pontos positivos

- A correção usou as fontes que já existiam (manifest e nome de arquivo) sem mudar nenhuma assinatura, e manteve todos os erros que protegem o teste (CA-18 e `SplitIntegrityError`).
- O tester explorou a correção em largura: os três splits, a mudança de grau na refotografia, a ausência de `attrs`, o nome fora do padrão e o conflito pela CLI. Foi assim que achou o T-02, que é a variante que importa na prática.
- O auxiliar `safe_unlink` fecha o incidente da r1.

## SPEC_ISSUE (se houver)

### SPEC_ISSUE-01 — O congelamento da §4.4 só olha o último split, e uma peça do teste pode voltar como peça nova (T-02)

**Onde:** SPEC-011 §4.4, nos itens "Congelamento (`previous` = split anterior)", "Imagem excluída" e "CLI" ("usa o de maior N como `previous`"); e `docs/dataset-protocol.md` §8.1, passo 5.

**Contradição:** pela letra, uma peça é "já presente" só se tiver imagem no split de maior N. Pela intenção da R-11, do ADR-014 ("o teste é congelado a partir do `split_v1`: peças novas entram só no treino e na validação") e do `dataset-protocol.md` §2, passo 6 ("o `item_id` continua o mesmo e o split garante que ela fique inteira em um só conjunto"), uma peça que já esteve num conjunto deve continuar nele, em qualquer versão posterior. Com a exclusão da §4.4, uma peça pode sumir de uma versão intermediária. A letra então a trata como nova, e a intenção é violada. A ordem do protocolo (§8.1, passo 5: rodar o split logo depois da exclusão) leva exatamente a esse caso.

**Por que não cabe ao autor:** toda correção muda algo que a SPEC fixa:
- **(A)** a CLI lê **todos** os `split_v*.csv` (cada um com `load_split`, que confere o hash) e passa a `make_split` o mapa histórico `item_id → split`. Isso exige um parâmetro novo em `make_split`, ou um canal por `df.attrs` que a SPEC não prevê. O `previous` continua sendo o de maior N, para os avisos e para o "split unchanged";
- **(B)** o `split_v<N>.json` passa a carregar um campo, por exemplo `retired_items: {item_id: split}`, com as peças que saíram por completo, propagado de versão em versão. Assim, o último split basta. Isso muda o formato da §4.4 ("Arquivos");
- **(C)** ancorar só no `split_v1` para o teste. É mais simples, mas não cobre validação e treino, nem peças entradas no v2 ou depois.

**Recomendação ao architect** (para a r3, que é a última, fechar sem nova ambiguidade):
1. Redefinir "peça já presente" na §4.4 como uma peça com alguma imagem em **qualquer** versão anterior do split, não só na de maior N.
2. Escolher o mecanismo. Sugiro o (A): não muda formato de arquivo, o histórico já está no Git com hash, e a consistência entre versões é verificável (uma peça em dois splits ao longo do histórico → `SplitIntegrityError`). O `item_id` das imagens antigas vem das mesmas fontes da r2 (linha atual, linha excluída e nome de arquivo da SPEC-010).
3. Fixar a assinatura, por exemplo `make_split(..., history: Mapping[str, str] | None = None)` com `item_id → split`, e dizer quem o monta (a CLI).
4. Acrescentar um CA novo (CA-33) com a sequência do T-02 (v1 → exclusão total de uma peça de teste → v2 → refotografia → v3 com as fotos novas em `test`), e, se quiser, a mesma sequência para uma peça de validação.
5. Aproveitar a mesma alteração para registrar no Histórico os pontos baixos da r1: RV-02 (`.JPG` como órfão) e RV-04 (`malformed_row`, `unreadable_csv`, `invalid_image_path`, `qwk: null` e a validação de `exclusions.csv` na concordância).

Ainda não há `split_v1` real (§7 da SPEC: ele só sai dos dados da S3), então nenhuma migração de dados é necessária.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
