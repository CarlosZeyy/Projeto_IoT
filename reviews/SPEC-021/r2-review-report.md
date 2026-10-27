# SPEC-021 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `spec/SPEC-020-mqtt...04ca3ed` (branch empilhada na SPEC-020; base `3da84d2`) |
| Test report | [r2-test-report.md](r2-test-report.md) (PASS; a r1 tinha FAIL só pelo T-01, corrigido em `57bf279`) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Três achados baixos, nenhum em código de produção.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | merge `de2afcc` | **Merge sem trailers.** O merge `de2afcc` ("Merge branch 'spec/SPEC-020-mqtt' into …") tem a mensagem padrão do Git, sem `Refs:` nem `Agent:`. O checklist §2 trata commit sem `Agent:` como bloqueante. Classifico como baixa, como no precedente RV-02 de `reviews/SPEC-038/r1-review-report.md`: é um merge limpo (`git show --cc de2afcc` vazio, sem resolução de conflito); só traz a correção de `reviews/SPEC-020/r1-review-report.md`, que já tem autoria na branch da 020; não há mudança de autoria a atribuir, e a separação de papéis continua verificável. | Nos próximos merges entre branches encadeadas, usar `git merge --no-edit -m "<assunto>" -m "Refs: SPEC-XXX" -m "Agent: orchestrator" …` com o bloco final de trailers. Não precisa reescrever o histórico desta branch. |
| RV-02 | baixa | `docs/specs/SPEC-021-ferramentas-eletricas.md:6` | **Rodada desatualizada no cabeçalho.** A SPEC está em `In Review` com `Rodada atual = r1`, mas a rodada é a r2 (`docs/plan.md:60` já diz "In Review (r2; …)"). Os commits `47ba357`, `d4c2c74` e `04ca3ed` só mudaram o `Status`. É controle do processo, sem efeito no código. | Orquestrador: no próximo commit de status, pôr `Rodada atual = r2`. |
| RV-03 | baixa | `infra/tests/test_migrate_db.py:145-161` | **Teste de re-execução ficou um pouco mais fraco nos arquivos que nada substitui.** Para cobrir o caso 003 → 006 (decisão 2 da Parte A, ponto 1 do pedido), `test_running_sql_file_again_changes_nothing` passou a rodar, depois do arquivo repetido duas vezes, **todos** os arquivos posteriores, para **toda** migração. Para a 003, é exatamente o que se quer. Para 001, 002, 004 e 005, a re-execução dos posteriores pode mascarar uma regressão futura em que repetir um arquivo antigo desfaça algo de um posterior (por exemplo, a 004 repetida desfazendo uma coluna da 005): antes o teste acusava, agora a 005 repetida "conserta" e o teste passa. Hoje nada disso acontece (o teste passou antes da mudança para esses arquivos), por isso é baixa. O teste novo `test_power_tool_migration_supersedes_the_hand_tool_checks` e a fixture `rerun_003` estão corretos (conexão `autocommit`, a 006 roda de novo no `finally`, o banco da sessão volta aos `check` de 12 valores). | Restringir a lista `later` às migrações que substituem um objeto da atual (um mapa explícito, `{"003": ["006"]}`, ou só as que contêm `inspections_grade_null_iff_unknown` quando a atual também contém), mantendo o "roda de novo e não muda nada" puro para os demais arquivos. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | **Parte A:** `qc-contracts` 0.6.0 com os 4 valores depois de `phillips_screwdriver`, na ordem da §3.1, rótulos `esmerilhadeira`/`serra`/`furadeira`/`parafusadeira`, os 4 em `GRADE_FORBIDDEN_OBJECT_TYPES`; a invariante não muda de código (segue os grupos). Migração `006_power_tool_object_types.sql` (nome da §3.1) com os 12 valores e as 4 elétricas no ramo "sem grau", em um bloco `DO`, idempotente. API sem código novo; `SpcObjectType` intacto (§3.1). Borda: coleta e importação com `T`/`XT`, grau vazio obrigatório, `raw/<tipo>/_/` (`NO_GRADE_DIR`), regra de carregamento da SPEC-016 §4.4 herdada do contrato, cobertura com uma linha por elétrica. Dashboard: ordem, cores e "sem grau". **Parte B:** `KNOWN_OBJECT_TYPES` com 12, `POWER_TOOL_OBJECT_TYPES` derivado do contrato, prefixo `T`/`XT`, `grade_on_other` para elétrica com grau, `tool_grade_coverage` só com as manuais, `derive_model_labels` com as elétricas sempre em `ungraded_object_types`, estrato da extensão por tipo, gerador com os dois parâmetros novos e padrão byte a byte igual, fixture `tiny_model_power_tools` (12 tipos, as 4 elétricas sem grau) e seção no `ml/README.md`. Rastreabilidade CA → arquivo → teste nas Partes A e B do dev-report. Nenhum CA alterado. Decisões de escopo registradas no dev-report e coerentes com a SPEC: (2) `grade_on_other` é a leitura direta do CA-09 ("o mesmo código de problema que um `other`") e da lista fechada da SPEC-036 §4.2; o 422 da coleta com `grade must be empty for a power tool` não contradiz nada (a SPEC só pede 422 sem gravar); (3) uma célula por elétrica com 90 imagens e 6 peças (mínimo 3 no texto) é a meta da §3.3; (4) o CHANGELOG com elétricas: a SPEC-016 §4.8 diz "quando o modelo tem ferramentas", e as elétricas são ferramentas; o CA-14 (passo 5) pede a entrada do CHANGELOG, e a não comparabilidade da `type_accuracy` (ADR-022) vale igual. Concordo com a leitura, sem SPEC_ISSUE; (5) `--with-tools` com os 8 tipos explícitos (`MVP_OBJECT_TYPES` + `TOOL_OBJECT_TYPES`) e exclusivo com `--with-power-tools` (grupo do `argparse`, saída 2) evita que a fixture da SPEC-016 mude ao ser regenerada. **Docs do architect (`fb1842c`):** `docs/architecture.md` §3 (0.6.0, `ObjectType` com 12, grupos), §4 (SPC sem as elétricas), §5 (006 e o aviso de rodar em ordem), §6 (coleta e importação), §7 (`labels.json`) e §10 (arquivo vigente `test_spec_021.py` com 0.6.0), e `docs/dataset-protocol.md` §1.2, §2, §3, §4, §5, §7 e §10.3: conferi cada trecho contra a SPEC §3.3/§4 e o código; fiéis (meta 90/6/3, `raw/<tipo>/_/`, `grade_on_other`, 422 com a mesma mensagem do código, extensão/adiamento, externas só no treino). ADR-019: nenhuma correção de SPEC nesta branch (só status e Histórico pelo orquestrador). |
| 2. Regras inegociáveis | ✅ (RV-01 baixa) | **R-01/R-12:** nenhuma dependência nova; só a versão do `qc-contracts` muda no `uv.lock`; `api/` e `dashboard/` sem torch/timm/onnxruntime (`pyproject.toml` intocados). **R-02/R-14:** só imagens sintéticas (gerador e Pillow em memória); nada sai da LAN; a captura das elétricas exige "sem mãos nem pessoas". **R-03:** busca por URL com senha, `eyJ`, `password=`, `secret=` no diff: nada; o T-01 (literal de URL de exemplo no dev-report) foi corrigido em `57bf279`, e os 2 testes de segredo passam. **R-04:** formato só em `packages/contracts`, minor 0.5.0 → 0.6.0 (`pyproject`, `__version__`, `uv.lock`, histórico do README), coberto pelo ADR-021 (decisão 2 já prevê a 0.6.0 na SPEC-021); banco com migração do `check`; rótulos PT-BR. **R-05:** batch das 4 elétricas idempotente (exploratório da API). **R-06:** elétrica simulada continua `simulated` (exploratório); nada muda no `source`. **R-07:** conferi trailer e arquivos de cada commit. Developer (`d2db2b4`, `991b144`, `de3804f`, `ee20bc8`, `bb82089`, `e880b8a`, `57bf279`): só `packages/contracts`, `infra/migrations`, testes do autor fora de `acceptance/`, `edge/`, `dashboard/`, `uv.lock` e os dev-reports. ML-engineer (`ed54ac2`, `011a49e`, `02c4104`, `b6cf891`, `0963435`, `bf7e2a4`, `7e8a75f`): só `ml/` fora de `acceptance/` e a Parte B do dev-report, só acrescentada (`87 0` no numstat). Tester (`69ca648`, `124e165`): só `*/tests/acceptance/` e os test-reports. Architect (`fb1842c`): só `docs/architecture.md` e `docs/dataset-protocol.md`. Orchestrator (`70ee820`, `cd550ea`, `47ba357`, `d4c2c74`, `04ca3ed`): só `docs/plan.md` e status/Histórico da SPEC. Exceção: o merge `de2afcc` sem trailers (RV-01). **R-11:** extensão do teste só com 3 peças não externas, estrato por tipo; externas só no treino; `type_confusion` com todos os tipos do modelo (12×12 na fixture); nenhuma métrica real reportada. **R-13:** identidade única do projeto (e-mail `noreply` do GitHub), Conventional Commits, nenhuma empresa citada. |
| 3. Corretude | ✅ | Migração: as duas implicações equivalem à expressão de três ramos para os 72 pares (teste do autor que compara no Postgres e CA-03 contra o `InspectionCreate`); valor fora do enum recusado só pelo `check` de tipo. `rerun_003` restaura a 006 no `finally` com conexão `autocommit` (sem risco de transação abortada no teardown). Borda: `_parse_grade` recusa qualquer valor não vazio (inclusive espaço) para as elétricas antes de olhar `GRADE_VALUES`; um campo não string continua `InvalidCollectFieldError`; `_coverage_key` descarta linha de elétrica com grau (não cai em célula nenhuma), como uma de parafuso sem grau; importação e coleta gravam em `raw/<tipo>/_/` pelo mesmo `NO_GRADE_DIR`. `capture.js` com `NO_GRADE` (grau vazio e desabilitado; a checagem do celular só pede grau fora dele), exatamente nas 200 linhas do limite das SPECs 007 e 010 (sem folga para a próxima mudança). ML: `thresholds.py` usa listas explícitas (`GRADED_OBJECT_TYPES` e `other`), então as elétricas ficam fora do `unusable_threshold` e do `grade_review_threshold`, como diz o README; `tool_grade_metrics` filtra por `TOOL_OBJECT_TYPES`; teto de 999 `T-` e 9.999 `XT-` somando manuais e elétricas, com `ValueError` claro para negativo. Sem rota nova, sem I/O novo em handler async, sem SQL novo na API. |
| 4. Testes | ✅ | Test-report PASS, 226 aceites novos cobrindo CA-01 a CA-13 (CA-14 manual, pendente para a dupla, não bloqueia pela Definição de pronto). Os testes exercitam o comportamento real: banco `partqc_test` real (CA-03 com os 72 pares; CA-04 com o cenário de lotes), modelo dummy ONNX na borda, CLI do split em subprocesso (sem pytest em subprocesso), fixture ONNX no CA-12 sem torch, comparação byte a byte no CA-13. **Ajustes de aceites antigos (ponto 6):** os 16 itens alterados em 11 arquivos (`test_spec_002/016/018` do contracts; `test_spec_004/005/016` da API; `test_spec_013/016` do dashboard; `test_spec_010/016` da borda; `test_spec_016` do ML) estão todos na tabela do r1-test-report, cada um com o requisito da SPEC-021; os da §3.1 (forma de piso no `test_spec_018`, `ALLOWED_EXACT` → `test_spec_021.py` com 0.6.0 no mesmo commit, 8 primeiros valores e `unknown` no grupo) seguem o texto literal; os demais trocam só a contagem ou a lista fechada que a SPEC amplia, mantendo as checagens de conteúdo (as 25 células das manuais, as contagens do CA-15, a igualdade com `{o: 0 for o in ObjectType}` do CA-08 da SPEC-005, a ordem relativa da SPEC-016 no gráfico, e, no `test_spec_016` da API, as linhas do MVP mantidas, a 003 de novo sem erro e os `check` estáveis, num banco próprio). Nenhum `test_caNN_` removido ou renomeado; nenhuma garantia antiga enfraquecida. Credenciais de teste geradas em tempo de execução. Rodei de novo (ver "Verificação do reviewer"). RV-03 é sobre um teste do autor. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (291 arquivos). Constantes derivadas do contrato (`POWER_TOOL_OBJECT_TYPES` no `qc_ml`, `GRADE_FORBIDDEN_VALUES` na borda), sem duplicar a regra de grau; a borda declara o próprio `DatasetObjectType`, com teste que o espelha no contrato. READMEs (`packages/contracts`, `edge`, `ml`) atualizados, com o passo a passo da dupla para o CA-14. Docstrings atualizadas (decisão, cobertura, gerador). |
| 6. Segurança | N/A | O autor não é o `security-devops`; o portão `security` da tag é do `security-devops`, à parte. Para ele: nenhuma superfície nova (rota, autenticação, SQL ou dependência); a migração é DDL sem credenciais; entradas novas são só valores de enum validados pelo contrato e pelos regex existentes. |

## Verificação do reviewer

```text
$ uv run ruff check . && uv run ruff format --check .
All checks passed!
291 files already formatted

$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q \
    packages/contracts/tests infra/tests/test_schema_db.py infra/tests/test_migrate_db.py \
    infra/tests/test_migration_files.py api/tests/test_power_tools.py \
    api/tests/acceptance/test_spec_021.py api/tests/acceptance/test_spec_016.py \
    api/tests/acceptance/test_spec_004.py api/tests/acceptance/test_spec_005.py \
    edge/tests/test_power_tools.py edge/tests/test_importer.py edge/tests/acceptance/test_spec_021.py \
    edge/tests/acceptance/test_spec_010.py edge/tests/acceptance/test_spec_016.py \
    dashboard/tests/test_power_tools.py dashboard/tests/acceptance ml/tests/test_power_tools.py \
    ml/tests/acceptance/test_spec_021.py ml/tests/acceptance/test_spec_016.py
2196 passed, 2 skipped, 1 warning in 460.64s   (os 2 skipped exigem torch)

$ uv run pytest -q infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs \
    infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files   (com este relatório no disco)
2 passed
```

## Pontos positivos

- Mudança mínima e fiel ao ADR-021: a invariante e a regra de carregamento da borda já seguiam os grupos do contrato, então as elétricas entram por dados, sem ramo novo no código de validação nem na API.
- A migração 006 tem teste que compara, no próprio Postgres, a expressão gravada com a da SPEC para os 72 pares, e o problema real de repetir a 003 depois da 006 foi percebido, documentado no cabeçalho da 006 e em `docs/architecture.md` §5, e isolado nos testes do banco compartilhado.
- O gerador sintético mantém o padrão byte a byte, e a fixture da SPEC-016 continua reprodutível depois de `KNOWN_OBJECT_TYPES` crescer.
- Os ajustes de aceites antigos trocam listas fechadas por "prefixo + conteúdo", sem perder nenhuma checagem.

## SPEC_ISSUE (se houver)

Nenhum.

Observações não bloqueantes, para o architect avaliar sem urgência: o nome `grade_on_other` agora vale também para as elétricas (mensagem do `qc_ml` cita o tipo; a lista de códigos da SPEC-036 é fechada); e o `capture.js` está exatamente no teto de 200 linhas dos testes das SPECs 007 e 010, então a próxima mudança nele vai precisar de enxugamento ou de uma SPEC que reveja o teto.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
