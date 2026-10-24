# SPEC-035 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-035](../../docs/specs/SPEC-035-ml-origem-das-imagens.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `f014d31...f1896d7` (base `origin/main`) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 1 achado médio (o T-01 do tester) e 4 baixos, que ficam como pendência e não bloqueiam o merge.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `ml/src/qc_ml/report.py:218` (e `:241`–`:250`) | **= T-01.** As contagens lidas do `metrics.json` são ecoadas sem conferir o tipo: o `<n>` de cada fonte (`by_source[source_id]`) e o `<e_val>`, `<e_test>`, `<e_train>` e `<n_train>` da seção `### Dados`. Reproduzi chamando a função: com `by_source = {"synthetic": "11 imagens\n- \`forged\`: 9"}`, o `release_notes` devolve duas linhas `` - ` ``, e o crédito da fonte real fica pendurado na fonte forjada. Com `n_images = "x\nINJ"`, a linha `- Treino:` do CHANGELOG se parte em duas. Valores `True`, `-3`, `1.5` e `null` saem como `True imagens` e assim por diante. Isso quebra a premissa do §4.6 ("cada fonte ocupa exatamente uma linha"). A CA-17 fecha esse canal para a **chave** (`source_id` fora do formato), mas ele continua aberto pelo **valor**. **Por que não bloqueia:** o `metrics.json` é um artefato que o próprio pipeline gera e que vai para o Git por PR. O `release-notes` e o `changelog` rodam na máquina da dupla. Para disparar o problema, é preciso editar o arquivo à mão ou corrompê-lo, e nenhum caminho de entrada de terceiros chega lá. Além disso, a lista "Erros" do §4.6 não prevê esse caso, então hoje nenhum teste pode exigir o comportamento. | Aceitar só `int` não negativo (excluindo `bool`) nos valores de `counts.train.by_source`, em `by_origin.external` e em `n_images`. Nos outros casos, sair com 2, como o autor já faz quando o `by_source` não é objeto (decisão 8 do dev-report), tanto no `release-notes` quanto no `changelog`. Como isso acrescenta um caso à lista "Erros" do §4.6, registrar como pendência no `docs/plan.md` para a próxima manutenção do ML (ou uma correção pequena da SPEC, nos limites do ADR-019, se o orquestrador preferir corrigir antes). |
| RV-02 | baixa | `ml/src/qc_ml/split.py:638`–`:646` | O `_fraction_argument` valida o `Decimal` e depois devolve `float(value)`. Valores que dão underflow passam pela validação e viram `0.0`. Exemplo: com `--max-external-fraction 1e-400`, o `make_split` levanta um `ValueError` que o `main` não captura: sai um traceback com código 1, em vez de 2 (§4.4: "outro valor sai com 2"). Nada é gravado. Na outra ponta, `0.30000000000000000001` é aceito e vira o teto `0.3` (perda de precisão, sem efeito prático). | Conferir `0 < float(value) <= 1` depois da conversão, ou passar o `Decimal`/`Fraction` adiante até o `make_split`. |
| RV-03 | baixa | `ml/src/qc_ml/report.py:201`, `:221` | Decisão 7 do dev-report (observação do tester). No CHANGELOG, um `source_id` do `metrics.json` fora do formato do §4.3 aparece como `` `<invalid source_id>` ``. Já o §4.6 escreve `` - `<source_id>`: … `` para o `changelog`, sem essa exceção. Nenhuma CA cobre o caso. Para ids válidos, o texto é exatamente o do §4.6 (CA-13 e CA-17 conferem). A escolha é defensiva e segue a regra do `release-notes` da mesma seção: evita gravar no Git um valor com caractere de controle. Aceito: não é `SPEC_ISSUE`, porque não contraria nenhuma CA nem a intenção do requisito. | O architect registra a regra no §4.6, junto com a RV-01, na próxima revisão da SPEC ou na SPEC de manutenção do ML. |
| RV-04 | baixa | `ml/src/qc_ml/data.py:202` (via `_read_sources` e `_read_registry`) | Observação do tester: o §4.2 e o §4.3 pedem cabeçalho "**exatamente**" `image_path,origin,…` e `source_id,title,…`. O `parse_csv` aceita coluna extra e colunas reordenadas (só a ausência gera `missing_column`, como no manifest da SPEC-011). A SPEC só define o código `missing_column`, então a implementação segue o que a SPEC torna testável. O importador da SPEC-036 grava o cabeçalho exato. | O architect decide numa revisão futura: ou define um código para cabeçalho diferente (ex.: `unexpected_header`), ou troca "exatamente" por "com as colunas". |
| RV-05 | baixa | `ml/src/qc_ml/synthetic.py:254` | O `make_synthetic_dataset` só confere `last_contributor <= 999`. Com `items_per_stratum > 100` (peças próprias até `S-5xx` ou além) e `contributor_items_per_stratum > 0`, as peças de conhecido a partir de `S-501` colidem com peças próprias de mesmo `item_id` e grau diferente. O mesmo vale para `O-501` com `items_per_stratum >= 501`. Só afeta o gerador de testes, e nenhuma CA usa essa combinação. | Levantar `ValueError` quando o último número próprio de uma letra for `>= CONTRIBUTOR_FIRST_NUMBER` e `c > 0`. |

### Decisão sobre o T-01 e as observações do tester

- **T-01 → RV-01 (média, pendência, não bloqueia).** Eu subi a severidade de baixa para média, porque o defeito quebra uma propriedade escrita no §4.6 e afeta um texto que vai para a página pública do Release. Ele não chega a alto, porque depende de editar à mão um artefato gerado pelo pipeline (ver a justificativa na tabela).
- **Observação sobre `<invalid source_id>` no CHANGELOG → RV-03 (baixa, aceita).**
- **Observação sobre o cabeçalho "exatamente" → RV-04 (baixa).**
- Registro passado em `--external-sources` que aponta para um diretório: é tratado como ausente, ou seja, registro vazio. Segue o que o §4.2 e o §4.6 dizem ("registro ausente = registro vazio") e falha do lado seguro: toda linha `external` vira `unknown_source_id`, e o `release-notes` com fonte sai com 2. Não é achado.

### Interpretações do §"Decisões" do dev-report

| # | Decisão | Avaliação |
|---|---|---|
| 1 | `n_external_images` em `counts.n_external_images` do `split_v<N>.json` | ✅ O §4.4 diz "nas contagens por split" e essa é a forma das chaves `counts.images`/`counts.items`. A CA-08 confere. |
| 2 | Ordem das checagens do `sources.csv` (`missing_source` suprimido com `missing_column`/`unreadable_csv`; `external_item_mismatch` só nas linhas sem outro problema) | ✅ O arquivo continua recusado, porque o erro de leitura já está na `ManifestError`. Isso só evita um problema por imagem gerado a partir de um arquivo ilegível. |
| 3 | `source_id` de linha inválida do registro conta como conhecido | ✅ O `load_manifest` falha do mesmo jeito (`invalid_license` etc.). Isso só evita repetir o mesmo erro como `unknown_source_id` em cada imagem. Com o id fora do formato, as imagens também acusam o erro (CA-05). |
| 4 | `load_sources` sem os 3 problemas que dependem do manifest | ✅ Segue o padrão do `load_exclusions`. O `load_manifest` faz as três checagens (CA-04). |
| 5 | `load_external_sources` com arquivo ausente → `{}` | ✅ É a regra do §4.2 e do §4.6. |
| 6 | Posição da `### Dados` e fração `—` com `n_train = 0` | ✅ A seção fica "depois da tabela de métricas" (§4.6). O arredondamento é exato com `ceil(Fraction·10⁴)` (conferido no código e por teste de autor e exploratório). |
| 7 | `<invalid source_id>` no CHANGELOG | Ver RV-03 (aceita, baixa). |
| 8 | `release-notes`: stdout em bytes UTF-8, `--output` atômico e saída 2 com `by_source`/`metrics.json` que não são objeto | ✅ Todas as validações acontecem antes de abrir o `--output`, que é gravado com `mkstemp` + `fsync` + `os.replace`, sem sobrar arquivo temporário. Os dois casos extras endurecem o comando sem contrariar nenhuma CA. |
| 9 | `TrainConfig.external_sources = ""` recusado | ✅ Evita `Path("")` = diretório atual. O campo não está em `HYPERPARAMETER_FIELDS` (o teste exploratório do tester confere). |
| 10 | Gerador: peças próprias primeiro, título `Synthetic dataset` e limites | ✅ O §4.7 não fixa o título. Ver RV-05 sobre o limite das peças de conhecido. |
| 11 | `test_maintenance.py` (teste de **autor** da SPEC-031) atualizado | ✅ É teste de autor, fora de `tests/acceptance/`. Passa a conferir que o `IMAGE_FILE_PATTERN` é montado a partir do `ITEM_ID_PATTERN`, como exige o §4.1. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Os §4.1–4.8 estão implementados: regex única (`split.ITEM_ID_PATTERN is data.ITEM_ID_PATTERN`; nenhuma regex de `split.py` tem `[SNOT]` literal); `sources.csv` e registro com todos os códigos das tabelas; `ALLOWED_LICENSES` exatamente igual ao §4.3; colunas novas depois de `grade_original`/`overridden`; `TrainConfig.external_sources` repassado por `train`, `thresholds`, `evaluate` e `pipeline` (via config); `--external-sources` em `data validate`/`report`, `split`, `report changelog`/`release-notes`; README com o passo `--notes-file`. Há rastreabilidade das CA-01 a CA-20 no dev-report. Nenhuma CA alterada. Não houve reaprovação sob o ADR-019 nesta branch: o Histórico registra só aprovações e reaprovações humanas de 2026-10-23, e os commits do orquestrador (`4894bbf`, `04cc749`, `f1896d7`) só mudam o status no cabeçalho da SPEC e no `plan.md`. As decisões do autor estão no dev-report (ver tabela acima). |
| 2. Regras inegociáveis | ✅ | **R-07:** os trailers batem com os arquivos de cada commit. `e50bab3`, `851ef7d` e `33bcf5c` (`ml-engineer`) tocam só `ml/src/**`, `ml/README.md`, `ml/external_sources.csv` e testes de autor em `ml/tests/`. `84e5ad1` (`ml-engineer`) toca só o dev-report. `64e28c5` (`tester`) toca só `ml/tests/acceptance/test_spec_035.py` e o test-report. `4894bbf`, `04cc749` e `f1896d7` (`orchestrator`) tocam só o `docs/plan.md` e o status das SPECs 031/035. Todos os 8 commits têm `Agent:`. **R-11:** as externas ficam fora dos estratos, da permutação e do arredondamento (`item_strata(df[~external])`), e o RNG consome as mesmas posições: a CA-07 confere que o split das peças próprias é idêntico ao do dataset sem externas. Externas vão para `train` no v1 e nas versões seguintes. Peça externa em `val`/`test` no `previous`, no `history` ou em qualquer versão do `item_history` levanta `SplitIntegrityError`. O `rows_for(…, "val"/"test")` recusa externa, e ele é o único caminho de `train`, `thresholds`, `evaluate` (inclusive `--latency-only`). A integridade por `item_id` (interseção vazia) continua conferida por `check_item_integrity`. A regra depende só do `item_id`, nunca do `sources.csv` (§7). **R-14:** só dados sintéticos; o relatório nunca contém o código `c01` (só `n_contributors`). **R-03:** nenhum segredo no diff; as únicas URLs de banco estão nos relatórios, sem credencial. **R-01/R-12:** nenhuma dependência nova; `uv.lock` e os `pyproject.toml` não mudaram; torch ausente no ambiente do CI (conferido). **R-13:** todos os commits são `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, sem menção corporativa. R-02, R-04, R-05 e R-06: N/A (sem contrato, API nem imagem saindo da LAN). |
| 3. Corretude | ✅ (RV-01, RV-02, RV-05) | A comparação do teto é exata (`Fraction(n_ext, n_train) > Fraction(str(x))`) e o próprio teto é aceito (CA-10: 198/660 com 0,30). O teto é conferido antes de gravar, e o CLI sai com 2 sem tocar no `--splits-dir`. A fração no relatório de dados e no `split_v<N>.json` também usa `is_external_item`, como o split. O `release-notes` valida tudo antes de abrir o `--output` e grava de forma atômica. O texto livre (`source_ref`, `title`, `attribution`) é filtrado pelas categorias Unicode `Cc`/`Cs`/`Cf`/`Zl`/`Zp`. Não há I/O assíncrono nem datas novas. Os casos de borda pendentes estão nos RV-01, RV-02 e RV-05. |
| 4. Testes | ✅ | Test-report PASS, cobrindo as CA-01 a CA-20 (126 testes de aceite, 53 deles de CA). Li as CA-07 a CA-10: não são tautológicas. Usam a CLI real, comparam o snapshot do `--splits-dir` e testam o `rows_for` em `val` e `test`. Nada é mockado além do `tmp_path`, sem rede e sem torch. A CA-14 é a única que usa o registro do repositório. **Nenhum teste de aceite de SPEC anterior foi alterado**: no diff, o único arquivo em `tests/acceptance/` é o `test_spec_035.py`, então não há tabela de ajustes a conferir. Rodei de novo: `uv run ruff check .` e `ruff format --check .` limpos (231 arquivos); `CI=true TEST_DATABASE_URL=… uv run pytest -q` → **6008 passed, 54 skipped**, os mesmos números do test-report. |
| 5. Qualidade | ✅ | Type hints nas funções públicas (`load_sources`, `load_external_sources`, `item_type_letter`, `is_external_item`, `source_lines`, `release_notes`, `split_counts`…). Sem `print` fora das CLIs. O `source_lines` é a função única que alimenta as linhas de fonte do CHANGELOG e das notas, como pede o §7, e a CA-17 confere que as duas saídas batem. O README foi atualizado (§4.8 e CA-20) e o passo antigo do `--notes "sha256: …"` foi substituído. |
| 6. Segurança | N/A | A SPEC não tem a tag `security` nem `deploy`. |

## Pontos positivos

- A regra das externas tem quatro camadas que dependem só do `item_id`: alocação, `previous`/`history`, `item_history` e a guarda no `rows_for`. Com isso, uma imagem externa não chega à validação nem ao teste, nem com um split editado à mão (CA-09).
- Deixar as externas fora da permutação preserva bit a bit o split das peças próprias. É a propriedade mais importante para não contaminar o `split_v1` antes do congelamento, e um teste a confere diretamente.
- O `release-notes` é robusto: valida tudo antes de abrir o `--output`, grava de forma atômica e escreve no stdout em bytes UTF-8 (igual ao arquivo mesmo com `LC_ALL=C`). Também não ecoa `source_id` inseguro, nem no CHANGELOG.
- O autor endureceu o comando sem extrapolar o escopo (decisões 8 e 9) e registrou cada interpretação no dev-report.

## SPEC_ISSUE (se houver)

Nenhum. Os itens que pedem uma revisão futura do texto da SPEC (RV-01, RV-03 e RV-04) não contrariam nenhuma CA e não impedem o merge. Recomendo registrá-los como pendência da próxima manutenção do ML no `docs/plan.md`, junto com a RV-02 e a RV-05.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
