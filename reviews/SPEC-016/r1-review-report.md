# SPEC-016 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-016](../../docs/specs/SPEC-016-ferramentas-manuais.md) |
| Rodada | r1 (Parte A do developer, Parte B do ml-engineer com o adendo "Ajuste depois da reaprovação") |
| Reviewer | reviewer |
| Diff revisado | `spec/SPEC-036-importacao-de-fotos...ca82ff0`, sem o merge da `main` (`63fdf0e`): os 26 commits de `git log --no-merges HEAD ^origin/main ^spec/SPEC-036-importacao-de-fotos` (`ebef723` a `ca82ff0`) |
| Test report | r1-test-report.md (FAIL inicial pelo SPEC_ISSUE-T1; **PASS** no adendo, commit conferido `f564584`) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Os quatro achados abaixo são baixos e não bloqueiam.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `ml/README.md:172`, `ml/README.md:174` | Os dois exemplos de `python -m qc_ml.split` com `--defer-types` e `--extend-test-types` têm uma sequência de espaços onde estava uma continuação de linha (`\` e quebra). O comando roda (o shell ignora os espaços), mas a linha fica longa e parece cortada. | Voltar o `\` e a quebra antes de `--defer-types`/`--extend-test-types`, como no exemplo do topo do mesmo README. |
| RV-02 | baixa | `infra/migrations/003_tool_object_types.sql:44-49` | A restrição de grau mantém o nome `inspections_grade_null_iff_unknown`, que não descreve mais a regra (grupos do ADR-021), e foi escrita como duas implicações, não com a expressão literal da §4.2. A troca é justificada e coberta: nos 8 valores que `inspections_object_type_check` admite, as duas formas dão o mesmo resultado (`infra/tests/test_schema_db.py::test_grade_check_equals_the_spec_expression_on_the_enum`), e a forma literal faria um valor fora do enum ser acusado pela restrição de grau antes da de tipo, quebrando o CA-06 da SPEC-003 (decisão 1 da Parte A). Fica só o nome enganoso. | Nada nesta SPEC. Na SPEC-021 (próxima mudança desse `check`), o architect pode decidir se renomeia a restrição (com ajuste dos testes que a citam) ou registra em `docs/architecture.md` §5 que o nome é histórico. |
| RV-03 | baixa | `ml/src/qc_ml/split.py:227-252` (`line_type_resolver`), `:267-277` (`new_object_types`) e `:280` (`type_decision_problems`) | O tipo de uma linha antiga do split vem da linha do `df` ou do tipo da peça no `df`; uma peça `T-` cujas imagens saíram todas do `df` (todas em `exclusions.csv`) não tem tipo (a letra `T` é ambígua). Se isso acontecer com **todas** as peças já divididas de uma ferramenta estendida e chegarem peças novas dela, a ferramenta volta a ser "tipo novo" e a CLI aceitaria um segundo `--extend-test-types`, contra o ADR-022, decisão 5 ("o teste do tipo fica congelado"). O cenário exige excluir todas as fotos antigas do tipo, por isso é improvável. | Em `type_decision_problems`, tratar como não novo também todo tipo registrado em `test_extended_types` de qualquer `split_v<M>.json` anterior (o campo já é gravado), com um teste do autor para o caso. Pode ir numa SPEC de manutenção do ML. |
| RV-04 | baixa | `docs/specs/SPEC-016-ferramentas-manuais.md` §6 (commit `6d25aaf`) | Na correção do SPEC_ISSUE-T1, além do CA-11 e da nota nova de rodada, o architect trocou o rótulo da nota anterior ("Rodada r2 (correção dos SPEC_ISSUE-1 e 2 da r1)" → "Ajuste na r1, depois da reaprovação de 2026-10-24 (…)"). Esse ajuste veio de uma Observação do test-report, não do SPEC_ISSUE-T1, o que tensiona o E-5 ("só os trechos ligados ao SPEC_ISSUE citado"). Aceito como dentro dos limites: é nota de rodada (E-4, tipo 4), não muda requisito, CA nem comportamento, e a nota nova ("a rodada continua na r1") ficaria contraditória sem ele. O Histórico registra a mudança. | Nas próximas correções sob o ADR-019, quando uma Observação pedir ajuste de texto vizinho, citá-la explicitamente no Histórico como parte do mesmo SPEC_ISSUE (ou abrir um SPEC_ISSUE próprio para ela). |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos do §4.1 ao §4.10 implementados; nenhum CA alterado pelos autores (R-08). Rastreabilidade CA → arquivo → teste nas Partes A e B do dev-report (CA-22 e CA-23 no adendo). As decisões dos dois dev-reports cabem no texto da SPEC ou dos ADRs (ver "Decisões conferidas"). Correções de SPEC: SPEC_ISSUE-1 e 2 (`83d64a1`, architect, só SPEC e `docs/plan.md`) reaprovadas pelo humano (`be3d2ec`); SPEC_ISSUE-T1 (`6d25aaf`) reaprovada pelo orquestrador sob o ADR-019 (`f564584`), conferida abaixo e dentro dos limites (com a ressalva baixa RV-04). |
| 2. Regras inegociáveis | ✅ | R-01: nenhuma dependência nova. R-02: nenhuma rota aceita imagem; a borda não muda o que sobe. R-03: busca por `postgres://…:…@`, `eyJ`, `password=`, `secret=`, `service_role` no diff sem ocorrências; `.env.example` sem variável nova. R-04: payload mudado só em `packages/contracts` (0.4.0 minor, ADR-021, `pyproject.toml`, `__version__`, `uv.lock` e histórico do README). R-05: escrita sem mudança; reenvio idempotente de ferramentas coberto no aceite. R-06: SPC e taxa de defeito continuam por `source`. R-07: conferido commit a commit (tabela abaixo). R-11: split por `item_id`, extensão sem mexer em atribuição anterior, `XT-` só no treino (CA-20), limiares só na validação, critério de grau por volume (não usa split nem resultado de modelo, como a §4.6 manda). R-12: `qc-api` e `qc-dashboard` sem torch/onnxruntime (o dashboard declara `SPC_OBJECT_TYPES` em vez de importar `qc_api`). R-13: os 26 commits com `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, Conventional Commits. |
| 3. Corretude | ✅ | Invariante do contrato pelos grupos, com mensagens sem valores; `check` do banco equivalente nos 48 pares; SPC e `defect_rate` por `grade is not null` em resumo, série e `lot_selection` (SQL parametrizado, `nullif` no denominador); `SpcObjectType` declarado. Borda: `ungraded_object_types` validado (lista de strings, sem repetição, dentro de `object_types`, só grupos opcional/proibido, proibidos presentes listados), decisão sem grau com `needs_review` só pela margem de tipo, `approved = null` e "sem grau" na resposta e no console. Coleta e importação com `T-`/`XT-` e grau obrigatório; plano inteiro validado antes de gravar (SPEC-036 §4.2). Datas sem mudança. RV-03 é um caso de borda improvável. |
| 4. Testes | ✅ | Test-report PASS (adendo), 245 testes novos de aceite (58 de CA) cobrindo CA-01 a CA-20, CA-22 e CA-23; CA-21 manual pendente e fora do portão (Definição de pronto). Testes não tautológicos (CA-03 compara o banco com o `InspectionCreate` em 48 pares e confere a própria expectativa, 41 aceitos; CA-22 tem o caso de contraste sem `other`). Banco real, modelo dummy ONNX e fixture `tiny_model_tools` sem torch; sem rede externa; o split roda pela CLI e nenhum teste roda a suíte em subprocesso. Ajustes de aceites antigos: 16 linhas na tabela do test-report, cada uma conferida no diff de `d7d1810` contra o requisito citado; nenhum `test_caNN_` removido ou renomeado; a coerência `__version__ == importlib.metadata.version` e o piso da §10 ficam no `test_spec_026.py`, e o `ALLOWED_EXACT` aponta para `test_spec_016.py` com `0.4.0` no mesmo commit. Nenhuma credencial literal em URL. Suíte rodada pelo reviewer (ver "Verificação"). |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (251 arquivos). Type hints nas funções públicas novas; sem `print` em produção fora das CLIs; sem duplicar regra do `qc_contracts` (grupos importados na borda, no `qc_ml.data` e no `qc_ml.artifacts`). READMEs de `packages/contracts`, `edge` e `ml` atualizados; `docs/architecture.md` §3, §3.1, §5 e §10 atualizados pelo architect (`c2c337a`). RV-01 é cosmético. |
| 6. Segurança | ✅ | Tag `security`: SQL sempre parametrizado (`sql.SQL` constante, valores em `%(…)s`); entrada da API validada pelo contrato (`extra="forbid"` intacto) e pelo enum `SpcObjectType` (422 para `unknown` e valores fora); `labels.json` validado no carregamento sem ecoar valores; plano de importação validado inteiro antes de gravar, `--privacy-checked` intacto (R-14); nenhuma rota nova, nenhuma autenticação alterada; logs sem segredos. Reaprovação delegada do SPEC_ISSUE-T1 não toca limite de segurança (X-6) nem trecho de regra inegociável (X-7). O `security-report` é do `security-devops` (portão seguinte). |

### Separação de papéis (R-07)

| Papel (trailer `Agent:`) | Commits | Arquivos tocados | Resultado |
|---|---|---|---|
| orchestrator | `ebef723`, `feaf525`, `be3d2ec`, `5e5745f`, `734f2c8`, `f564584`, `ca82ff0` (e o merge `63fdf0e`) | só `docs/plan.md` e o status/Histórico das SPECs (o merge resolveu conflito só em `docs/plan.md` e no topo/Histórico da SPEC-016) | ✅ |
| developer | `fb6383e`, `a9a875b`, `7fab41e`, `00d4cc9`, `7249839`, `ad252a4` | `packages/contracts/`, `uv.lock`, `infra/`, `api/`, `edge/`, `dashboard/` (código e `tests/` fora de `acceptance/`), dev-report (Parte A) | ✅ nada em `ml/` nem em `acceptance/` |
| ml-engineer | `ba35ae3`, `e25c928`, `60f7bc1`, `0e412ef`, `6288215`, `f6fe277`, `cec9f3a`, `1f5c7ed` | só `ml/` (fora de `acceptance/`) e a seção "Parte B" do dev-report | ✅ |
| architect | `83d64a1`, `6d25aaf`, `c2c337a` | só `docs/` (SPEC, `docs/plan.md`, `docs/architecture.md`) | ✅ |
| tester | `d7d1810`, `f2e45ac` | só `*/tests/acceptance/` e o test-report | ✅ |

Todos os 26 commits têm o trailer `Agent:` e `Refs: SPEC-016`.

### Reaprovação delegada do SPEC_ISSUE-T1 (ADR-019; checklist §1 e §6)

Conferida no `git show 6d25aaf` (architect) e `git show f564584` (orquestrador), contra a linha do Histórico.

| Critério | Resultado |
|---|---|
| E-1 Origem | ✅ SPEC_ISSUE-T1 com ID no `reviews/SPEC-016/r1-test-report.md` |
| E-2 Autoria | ✅ `6d25aaf` com `Agent: architect`, toca só a SPEC e `docs/plan.md`; a atualização de `docs/architecture.md` foi para um commit separado (`c2c337a`), sem ligação com o CA-11 |
| E-3 Estado | ✅ SPEC aprovada (PR #45) e `Blocked` por este SPEC_ISSUE (`734f2c8`) |
| E-4 Natureza | ✅ CA-11: forma de verificação ajustada à regra vigente da SPEC-036 §4.2, intenção preservada (aceitar `T-`/`XT-` com ferramenta, recusar `XT-` com `screw` por `item_prefix_mismatch`), com o caso (c) cobrindo só a regra que já valia (tipos 2 e 3); §6, aviso do topo e Histórico (tipo 4) |
| E-5 Abrangência | ✅ com ressalva baixa (RV-04): a troca do rótulo da nota "Rodada r2" é ajuste de nota de rodada necessário para a coerência da nota nova |
| X-1 a X-4 | ✅ nenhuma SPEC nova, ADR, regra, contrato ou documento fora da SPEC/`docs/plan.md` exigido pela correção |
| X-5 | ✅ nenhum comportamento novo: o plano misto sair com 2 sem gravar é o que a SPEC-036 §4.2 e o CA-04 dela já exigiam, e o código não mudou (`git diff --stat d7d1810 f564584` só em `docs/`) |
| X-6 | ✅ nenhum CA removido, nenhum caso de erro retirado, nenhum valor prometido nem limite de segurança mudou |
| X-7 | ✅ o CA-11 não verifica regra inegociável; o `--privacy-checked` (R-14) fica fora da correção |
| X-9 | ✅ nenhuma marcação "exige humano"; o CA-11 e a nota de rodada nunca foram corrigidos sob o ADR-019 nesta SPEC (as correções anteriores foram reaprovadas pelo humano) |
| Registro | ✅ `f564584` só de status (`Agent: orchestrator`): aviso do topo "Reaprovada pelo orquestrador sob o ADR-019 em 2026-10-24 (UTC)", linha do Histórico com o sha `6d25aaf`, `docs/plan.md` (status e o rótulo dos ADRs 021/022 como `Aceito`, que já era o estado deles) |

Classificação do architect conferida: elegível. Nenhum `SPEC_ISSUE` "exige humano".

As correções do SPEC_ISSUE-1 e 2 (`83d64a1`) foram classificadas como "exige humano" (X-7 e X-5 pelo SPEC_ISSUE-2) e reaprovadas pelo humano (`be3d2ec`); a implementação segue o texto reaprovado (`f6fe277`: `grade_review_threshold` em `screw`, `nut` e `other`; `cec9f3a`: estrato da extensão por tipo e grau dominante se graduada, só por tipo se sem grau, recusa de tipo sem peça no teste).

### Decisões conferidas nos dev-reports

- **Parte A, 1 (`check` como implicações):** equivalente à §4.2 no domínio admitido, testado; ver RV-02.
- **Parte A, 2 (metas 60/5 por célula de ferramenta):** vêm da tabela de metas do §3.3 ("Grau (opcional): ≥ 60 imagens por grau, vindas de ≥ 5 peças"); a meta de identificação aparece no console e no README.
- **Parte A, 4 (`SPC_OBJECT_TYPES` no dashboard):** necessário pela R-12/ADR-007 (o dashboard não importa `qc_api`); dois testes amarram a lista e o `SpcObjectType` aos grupos do contrato.
- **Parte A, 5 ("sem grau" no CSV e no console):** extensão coerente do §4.4/§4.5, sem mudar contrato.
- **Parte A, 7 (`tools_not_supported` removido):** consequência do §4.4; o ajuste do `test_spec_036.py` está na tabela da §10.
- **Parte B, 2 (`ungraded_object_types` em chave própria do `training_config.json`):** mantém o formato do `labels` que o CA-08 da SPEC-012 compara, e cumpre o §4.8 ("passam a ter `ungraded_object_types`").
- **Parte B, 4 (`qc_ml.decision` igual à borda):** necessário para os limiares e o `needs_review_rate`; teste cruzado com a borda.
- **Parte B, 8 e 9 (um sorteio por tipo; versão gravada quando só `deferred_types` muda):** cabem no "procedimento do `split_v1`, com a mesma seed" e no CA-15 (b).
- **Parte B, 13 (`false_unknown_rate` do `metrics.json` continua em `screw`/`nut`):** a §4.8 só muda o `FU(t)` dos limiares; a identificação das ferramentas aparece inteira na `type_confusion` (R-11, nenhuma classe omitida).
- **Parte B, 12 (`TrainError` sem `other` no treino; pesos de classe só das linhas da loss):** cabem na skill `ml-pipeline` §4 (loss mascarada) e na regra de decisão.

## Verificação

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
251 files already formatted
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run --locked pytest -q
7293 passed, 75 skipped, 1 warning in 617.46s (0:10:17)
```

Mesmo resultado do test-report (`7293 passed, 75 skipped`), no ambiente do CI (sem o extra `train`), com o `partqc_test` e nenhuma outra suíte com banco rodando. Os 75 pulados são os de Docker, MQTT, modelo real e torch.

## Pontos positivos

- Contrato 0.4.0 enxuto: os grupos do ADR-021 são a única fonte da invariante, reaproveitados na borda (`ungraded_object_types`), no `qc_ml` (`TOOL_OBJECT_TYPES`, `check_labels`) e nos testes que amarram `SpcObjectType` e o filtro do dashboard ao contrato.
- A troca do SPC e da taxa de defeito para `grade is not null` ficou nos três lugares certos e só neles, sem mudar nenhum valor dos dados do MVP (aceites das SPECs 005, 006 e 026 passam sem ajuste nessa parte).
- Split com extensão e adiamento auditável: cada problema numa linha própria da saída de erro, nada gravado em erro, `test_extended_types`/`deferred_types` no JSON e um gerador por tipo, que torna a extensão de um tipo independente das demais.
- O test-report e a tabela de ajustes de aceites antigos estão completos e fiéis ao diff; o tester registrou o SPEC_ISSUE-T1 em vez de forçar uma leitura do CA-11.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
