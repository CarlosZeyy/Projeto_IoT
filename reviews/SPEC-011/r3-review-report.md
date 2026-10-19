# SPEC-011 — r3 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-011](../../docs/specs/SPEC-011-ml-dados-split.md) (corrigida em `60ce217`, reaprovada pelo humano) |
| Rodada | r3 (última, R-10) |
| Reviewer | reviewer |
| Diff revisado | `origin/main...7ac70cf` (30 arquivos, +6798/−18); diff da r3: `8004b1e..7ac70cf` |
| Test report | [r3-test-report.md](r3-test-report.md) (PASS, sem bugs) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante, alto ou médio, e fica 1 achado baixo, que não bloqueia.

O SPEC_ISSUE-01 da r2 foi resolvido pelo architect, com o mecanismo (A), e reaprovado pelo humano. A implementação segue a §4.4 nova item por item. O T-02 virou teste normal e passa, e os CA-33 a CA-35 têm teste de aceite que os exercita pela CLI e pela API.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-07 | baixa | `ml/src/qc_ml/split.py:49` | **`ITEM_ID_PATTERN` duplicado.** A mesma regex `[SNOT]-[0-9]{3}` já existe em `ml/src/qc_ml/data.py:74`, que o `split.py` já importa para outros nomes. Se um dia o formato do `item_id` mudar (por exemplo, para as ferramentas `T-` da SPEC-016), as duas cópias podem divergir: a validação do manifest aceitaria um `item_id` que a fonte 2 do split ignoraria, ou o contrário. | Numa manutenção futura, importar `ITEM_ID_PATTERN` de `qc_ml.data`. Não justifica rodada nova. |

Os achados anteriores estão todos resolvidos:

| Achado | Situação |
|---|---|
| RV-01 da r1 | Corrigido na r2. |
| RV-02 da r1 | Registrado na SPEC (§4.1, órfão sem diferenciar maiúsculas; §7, outras extensões para uma SPEC futura). |
| RV-03 da r1 | Corrigido na r2 e registrado na SPEC. |
| RV-04 da r1 | Registrado na SPEC (§4.1, `unreadable_csv`, `malformed_row` e `invalid_image_path`; §4.3, `qwk = null` e `exclusions.csv` validado por inteiro). |
| RV-05 / SPEC_ISSUE-01 da r2 | Corrigido na SPEC (`60ce217`) e no código (`5e30539`). |
| RV-06 da r2 | Corrigido: a fonte 2 exige `item_id` válido, em `split.py:177`. |

## Conferência da implementação contra a §4.4 nova

- **Assinaturas.** `make_split(..., excluded=frozenset(), history: Mapping[str, str] | None = None)`: o `history` é o último parâmetro, e as chamadas antigas não mudam. `item_history(splits: Sequence[pd.DataFrame], df) -> dict[str, str]`, com `Mapping` e `Sequence` de `collections.abc`.
- **Fontes do `item_id`** (`item_id_resolver`, `split.py:158-182`), na ordem da SPEC:
  1. a linha de `df`. O resolvedor de `make_split` é montado **antes** de tirar as linhas em `excluded` (`split.py:274`), como a fonte 1 manda;
  2. `df.attrs["excluded_items"]`, só com `fullmatch` de `[SNOT]-[0-9]{3}` (RV-06). Um valor inválido passa à fonte 3;
  3. o nome de arquivo da SPEC-010 (`IMAGE_FILE_PATTERN`, que confere com a SPEC-010 §4.2, passo 3).

  Sem fonte, a imagem é ignorada, sem erro nem aviso. Sem `attrs`, a fonte 2 fica vazia e nada falha.
- **`item_history`.**
  - Percorre todas as linhas de todas as versões e acusa conflito também dentro de um só `DataFrame`.
  - A mensagem do `SplitIntegrityError` traz o `item_id` e, para cada split, os arquivos (`attrs["split_file"]`, ou `#<posição>`).
  - Não lê arquivos nem confere hash, e nunca resolve um conflito. O tester confirmou isso com um conflito de maioria entre v1, v2 e v3.
- **`make_split` com `history`** (`split.py:266-272` e `:326-337`):
  - `history` não vazio sem `previous` → `SplitError`;
  - valor fora de `train`/`val`/`test` → `SplitError`;
  - a peça é antiga se estiver no `history` **ou** se alguma imagem do `previous` resolver para ela, e o split dela é `history[item_id]` ou, sem entrada, o do `previous`;
  - divergência entre `history` e `previous` → `SplitIntegrityError` com o `item_id`;
  - imagens do `previous` em dois splits → `SplitIntegrityError`;
  - entrada sem imagens em `df` é ignorada;
  - os avisos `missing_previous_image`/`excluded_previous_image` e o `SplitError` do teste continuam olhando só o `previous`.
- **CLI, passos 1 a 6** (`split.py:540-613`):
  1. manifest e exclusões;
  2. lista os `split_v<N>.csv` (`[1-9][0-9]*`, e `.sha256`/`.json` soltos são ignorados porque só `.csv` com `is_file()` conta);
  3. lacuna → saída 2 com `split history incomplete` e o nome de cada `split_v<K>.csv` ausente;
  4. todas as versões lidas com `load_split`, e o erro sai com o nome do arquivo;
  5. `previous` = versão M e `history = item_history(...)`, e o conflito sai com 2;
  6. `make_split` com `history`, gravando só se houver mudança.

  Todo erro sai antes de qualquer gravação, e os CA-34 (a/b/c) conferem `--splits-dir` byte a byte.
- **Nenhum formato de arquivo mudou** (`split_v<N>.csv`, `.sha256` e `.json`). O `data.py` não mudou na r3.

## Pontos específicos pedidos pelo orquestrador

- **`test_extra_split_versions_use_numeric_order` (ajuste do tester): aceito.**
  - O teste antigo criava v1, v9 e v10. Pela §4.4 nova (passo 3), isso agora é lacuna e sai com 2. O ajuste decorre diretamente desse requisito, e o autor o apontou sem tocar no arquivo (R-07).
  - O teste novo cria as versões 1 a 10 completas, com hash válido, e continua esperando `split unchanged: split_v10`. A intenção se mantém: numa ordenação lexicográfica dos nomes, a "última" seria `split_v9.csv`, e o teste falharia.
  - É um `test_extra_*` da própria SPEC, não um `test_caNN_` nem um teste de SPEC anterior. Mesmo assim, está na tabela "Mudanças no arquivo de aceite" do test-report, com o motivo, o que satisfaz o espírito do `docs/architecture.md` §10. A lacuna ganhou cobertura própria no CA-34 (a) e no `test_extra_history_gap_in_the_middle`.
- **`#<posição na lista>` começando em 0: aceito.**
  - O texto da §4.4 não fixa a base.
  - O marcador só aparece com `DataFrame` montado à mão, sem `attrs["split_file"]`; pela CLI, a mensagem sempre traz `split_vN.csv`, porque o `load_split` grava o atributo.
  - Nenhum CA depende disso. A decisão está registrada no dev-report, e o teste do tester exige só o `#`.
  - Não é ambiguidade que afete comportamento observável pelo usuário. Por isso, não vira `SPEC_ISSUE`.
- **Commit do architect (`60ce217`) e a R-07: ok.**
  - Ele tem `Agent: architect` e `Refs: SPEC-011` em bloco único, e toca só `docs/`: SPEC-011, nota de texto na SPEC-012, `dataset-protocol.md` §7/§8.1 e o quadro do `plan.md`.
  - O `.claude/agents/architect.md` (seção "Commits") e o `reviews/README.md` dizem que o architect não tem shell e que o orquestrador commita os arquivos dele com `Agent: architect`. É o esperado, e não um desvio de papel.
  - A atualização do quadro do `plan.md` no mesmo commit faz parte do trabalho do architect (skill `criar-spec`, passo 9). A mudança de status para `In Dev` foi num commit separado, do orquestrador (`eaaf850`), que também registra a reaprovação humana no Histórico.
  - A nota da SPEC-012 é só de texto, sem mudar requisito, assinatura ou CA. A dispensa de reaprovação foi decisão do humano e está registrada no Histórico da SPEC-012.
- **R-07 nos demais commits:** os 25 commits da branch têm `Agent:`.
  - Os da r3 do `ml-engineer` (`5e30539`, `0768194`) tocam só `ml/src/qc_ml/split.py`, `ml/tests/test_split.py` e o dev-report.
  - O do `tester` (`42b5cc3`) toca só `ml/tests/acceptance/test_spec_011.py` e o test-report.
  - Os do `orchestrator` tocam só status e plano.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os 35 CAs têm implementação. A rastreabilidade do dev-report da r3 cobre os CA-33 a CA-35 e os itens novos da §6 (autor). Nenhum CA foi alterado por quem implementa ou testa: as mudanças de CA vieram do architect, com reaprovação humana. Nada fora do escopo: `item_id_resolver` é auxiliar público usado pelas duas funções da SPEC, para manter uma única definição das fontes. Não há decisão nova embutida que não esteja registrada no dev-report ou na SPEC. |
| 2. Regras inegociáveis | ✅ | **R-01/R-12:** nenhuma dependência nova; `pyproject.toml` e `uv.lock` intactos; `api/`, `dashboard/` e `edge/` fora do diff. **R-02/R-14:** `git ls-files ml` sem imagens, sem `ml/data/` e sem `ml/splits/` (o `split_v1` real só sai na S3); testes só com dados sintéticos em `tmp_path`, e os apagamentos passam por `safe_unlink`. **R-03:** nada na busca por segredos no diff da r3. **R-04/R-05/R-06:** N/A. **R-07:** ver acima. **R-11:** split por `item_id`; nenhuma peça muda de conjunto em relação a qualquer versão anterior (CA-33); conflitos de histórico nunca são resolvidos automaticamente (CA-34 c e extras); o teste não é usado para escolhas. **R-13:** todos os commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits com `Refs: SPEC-011`. |
| 3. Corretude | ✅ | Validações do `history` antes de qualquer trabalho, e `SplitIntegrityError` (subclasse de `SplitError`) capturado pela CLI com saída 2. A lacuna é calculada sobre `1..M`, inclusive a falta do `split_v1`. Uma versão ilegível é tratada com `(SplitError, OSError)`. A ordem dos passos garante que nada é gravado em erro. O resultado é determinístico (o `item_history` só devolve o split, e `sorted` nas mensagens). Sem async, SQL ou datas novas. |
| 4. Testes | ✅ | O test-report é PASS, com os 35 CAs. CA-33 a CA-35 seguem o texto dos CAs: dataset do CA-12, peça de teste e de validação, os três casos do CA-34 com comparação do diretório byte a byte, e os quatro casos do CA-35. O T-02 virou `test_extra_t02_*`, sem `xfail` e com as mesmas asserções, e não sobra nenhum `xfail` nem `test_bug_*`. **Rodei:** `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` → **4638 passed, 4 skipped** em 290 s, sem o extra `train` (`import torch` falha), igual ao test-report; `git status` limpo depois. Nenhum teste de outra SPEC foi tocado; nenhum teste roda o pytest em subprocesso; nenhuma credencial literal. |
| 5. Qualidade | ✅ (RV-07 baixa) | `ruff check` e `ruff format --check` limpos (182 arquivos). Docstrings de `make_split`, `item_history`, `item_id_resolver` e `main` atualizadas, com os passos da §4.4. Há type hints. Sem `print` fora da saída das CLIs. |
| 6. Segurança | N/A | A SPEC não tem a tag `security` nem `deploy`. |

## Pontos positivos

- A resolução do `item_id` ficou numa única função compartilhada por `make_split` e `item_history`, o que elimina o risco de as duas divergirem.
- As mensagens de erro da CLI dizem o que fazer ("restore it from Git; old split versions are never deleted or renumbered"), alinhadas com a §7 da SPEC e com o `dataset-protocol.md` §7.
- A cobertura do tester na r3 foi além dos CAs: lacuna no meio, `.sha256` ausente numa versão antiga, conflito de maioria, `split_v01`/`split_v0` ignorados e o filtro do RV-06 pela CLI.
- O loop fechou dentro das 3 rodadas, com o problema de SPEC tratado como `SPEC_ISSUE`, e não improvisado no código.

## SPEC_ISSUE (se houver)

Nenhum. O SPEC_ISSUE-01 da r2 está resolvido (`60ce217`, reaprovado).

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
