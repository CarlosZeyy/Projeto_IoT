# SPEC-016 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-016](../../docs/specs/SPEC-016-ferramentas-manuais.md) |
| Rodada | r1 (Parte A do developer, Parte B do ml-engineer com o adendo "Ajuste depois da reaprovação") |
| Revisor de segurança | security-devops (autores: developer e ml-engineer) |
| Diff revisado | `spec/SPEC-036-importacao-de-fotos...add9172`, sem os commits vindos da `main` pelo merge `63fdf0e`: os 28 commits de `git log --no-merges HEAD ^origin/main ^spec/SPEC-036-importacao-de-fotos` (`ebef723` a `add9172`). Depois do merge, só `docs/`, `reviews/` e `*/tests/acceptance/` mudam |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os dois achados abaixo são baixos e não bloqueiam. Não há `SPEC_ISSUE`. A reaprovação delegada do SPEC_ISSUE-T1 está dentro dos limites do ADR-019.

## Superfície analisada

- **Contrato (`qc-contracts` 0.4.0, R-04):** `ObjectType` ganha as 5 ferramentas no fim do enum; os grupos `GRADE_REQUIRED/FORBIDDEN/OPTIONAL_OBJECT_TYPES` (`frozenset`, disjuntos, união = enum); a invariante de `_InspectionBase` só **afrouxa** (ferramenta com ou sem grau) e mantém as regras de `grade_score`/`grade_confidence`. As mensagens citam a regra, sem valores. `extra="forbid"`, regex, tetos (`MAX_BATCH_SIZE`, `MAX_LATENCY_MS`, `MAX_FUTURE_SKEW`) e `is_defective` não mudam. Versão em `__version__`, `pyproject.toml`, `uv.lock` e no histórico do README. A mudança é minor de verdade: todo payload 0.3.0 continua válido, com o mesmo significado.
- **Compatibilidade com a borda em operação:** API 0.4.0 aceita toda borda 0.3.0 (o conjunto aceito só cresce). Uma borda 0.4.0 contra uma API ou um banco ainda sem a `003` teria cada ferramenta recusada com 422 (`Value cannot be stored`, sem eco de valor; ou a 422 do contrato) e marcada `dead`. O `python -m qc_edge.requeue` (SPEC-034, já na `main` e nesta branch) a devolve depois da atualização. Uma borda 0.3.0 que recebesse um `labels.json` com ferramentas ou com `ungraded_object_types` falha fechado no carregamento (`ModelLoadError`: valor fora de `ALLOWED_OBJECT_TYPES` e chave desconhecida).
- **Banco (`infra/migrations/003_tool_object_types.sql`):** um único bloco `do $$ … $$`, sem `BEGIN`/`COMMIT` (a transação é do `infra/migrate.py`), `drop constraint if exists` + `add constraint` nos dois `check`. Reexecutar não dá erro. Os dois `check` novos só aceitam mais, então toda linha válida antes continua válida. A restrição de grau, escrita como duas implicações, é equivalente à expressão da §4.2 nos 8 valores admitidos, e um valor fora do enum continua recusado pelo `inspections_object_type_check` (conferido pelo teste do autor no Postgres, 48 pares). **Nenhum** `grant`, `revoke`, política, `enable row level security` nem papel aparece na migração: RLS e permissões ficam como as da `001`. Nenhuma credencial no arquivo.
- **API:** nenhuma rota nova; autenticação, CORS, limites de corpo e de página sem mudança. O SPC (`lot_selection`) e a taxa de defeito (resumo e série) trocam `object_type <> %(unknown)s` por `grade is not null`, como fragmento constante (`sql.SQL`) ou literal no SQL fixo; os valores continuam em `%(…)s`. `nullif` mantém o denominador zero sem erro. `SpcObjectType` é um `StrEnum` declarado, com `screw`, `nut` e as 5 ferramentas: `unknown` e qualquer outro valor dão 422 pelo FastAPI, com o handler da SPEC-027 (sem 500 nem traceback). A recusa do banco (classe 22/23) continua logando só rota, `device_id` e SQLSTATE.
- **Borda:**
  - `labels.json` aceita a chave opcional `ungraded_object_types` e recusa: não lista ou lista com não strings (inclusive `null`), repetição, valor fora de `object_types`, `other`, `screw` ou `nut`, e a ausência de um tipo de grau proibido presente no modelo. Toda chave desconhecida continua recusada. As mensagens não ecoam o valor; a única lista impressa é a constante dos tipos permitidos.
  - A decisão sem grau só pode sair para um tipo validado no carregamento, e o `InspectionCreate` revalida os grupos antes do outbox.
  - Coleta: o prefixo `T` só aceita as 5 ferramentas (`item_prefix_matches`, sobre a letra de um `item_id` já validado por `re.fullmatch`), e o grau é obrigatório. O caminho `raw/<object_type>/<grade>/…` continua montado só com valores de enum, sem *path traversal*. `capture.js` espelha a regra do servidor, sem confiar nela.
  - Importação: os padrões passam a `[SNOT]-[0-9]{3}` e `X[SNOT]-[0-9]{4}` (fullmatch), o código `tools_not_supported` sai e o grau das ferramentas é obrigatório (`missing_grade`). As regras de privacidade da SPEC-036 continuam iguais e valem para as ferramentas pelo mesmo caminho:
    - `--privacy-checked` obrigatório;
    - pasta de entrada fora do `DATASET_DIR`;
    - normalização com remoção de EXIF, ICC e segmentos privados, e a conferência do passo 5;
    - só o SHA-256 da entrada no dataset;
    - fonte registrada para `XT-`;
    - validação do plano **inteiro** antes de gravar (é o que o CA-11 novo verifica no caso (c)).

    Os achados baixos SEC-36-01 a SEC-36-03 da SPEC-036 continuam como estavam: esta SPEC não toca esses trechos e não piora nenhum deles.
  - O tráfego borda → nuvem não muda: só o JSON do contrato sobe (R-02). O `httpx` continua só no publisher.
- **Dashboard:** rótulos, cores, `sem grau` no histórico e no CSV (o texto continua passando pelo `_csv_text`) e o filtro do SPC com `SPC_OBJECT_TYPES` declarado. O dashboard não importa `qc_api` nem pacotes de ML (R-12).
- **ML:** `XT-` nunca em `val`/`test` (R-11, ADR-020/022), em camadas:
  - na extensão, o externo vai para o treino fora dos estratos;
  - `_check_external_history` olha o split anterior e o histórico;
  - `check_item_integrity`;
  - `rows_for(val|test)` levanta `SplitIntegrityError` se aparecer imagem externa.

  A extensão não muda nenhuma atribuição anterior, e o adiamento tira as imagens do CSV. O critério de grau conta volume de dados não externos e não excluídos (não usa split nem resultado de modelo). A fixture `tiny_model_tools/parity_fixture.npz` (849 KB) tem só tensores `float32` (8×3×224×224) gerados pelo `make_synthetic_dataset(seed=0)` e as saídas do modelo: nenhuma foto real no Git (R-14).
- **Segredos e identidade (R-03, R-13):** busca no diff dos 28 commits por URL com credencial, JWT (`eyJ`), `service_role`, chave privada, `password=`, `secret=`, `ghp_`, `AKIA` e nomes corporativos: nenhuma ocorrência (só as citações dos padrões no próprio review-report). `.env.example` sem variável nova. Os 28 commits têm o autor `Carlos Moises <…CarlosZeyy@users.noreply.github.com>` e os trailers `Refs: SPEC-016` e `Agent:`. O único SQL em f-string do diff está num teste (`infra/tests/test_schema_db.py::test_grade_check_equals_the_spec_expression_on_the_enum`), montado a partir do catálogo (`pg_get_constraintdef`) e de uma constante do teste, com os pares em parâmetros. Fora da produção.
- **Dependências:** nenhuma nova. O `uv.lock` muda só a versão do `qc-contracts` (`0.3.0` → `0.4.0`).

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-16-01 | baixa | deploy | `docs/deployment-plan.md` (sem seção de atualização de contrato); `.claude/skills/contrato-api/SKILL.md` (ordem de deploy) | A ordem contracts → banco (`003`) → API → dashboard → borda está só na skill `contrato-api` e no §7 da SPEC. O plano de deploy, que é o roteiro do humano, não diz que a `003` tem de ser aplicada (pelo `.env.migrate`, `infra/migrate.py --status` e depois `infra/migrate.py`) **antes** de a borda usar um modelo com ferramentas. Sem isso, a falha é recuperável e não vaza nada: o banco recusa com `23514`, a API responde 422 `Value cannot be stored` (o log tem só rota, dispositivo e SQLSTATE), a inspeção vira `dead` e o `qc_edge.requeue` a devolve. Mesmo assim, é uma armadilha operacional na primeira mudança de contrato com a borda em operação. | Nada nesta SPEC. Pôr a ordem no checklist do PR e no resumo ao humano (ver "Ações pendentes para o humano"). Numa SPEC de manutenção de deploy (por exemplo, a SPEC-038), o `docs/deployment-plan.md` pode ganhar uma seção "Atualizar o contrato" com a ordem e o `requeue`. |
| SEC-16-02 | baixa | input (documentação de revisão) | `.claude/skills/contrato-api/SKILL.md`, checklist ("Validadores das invariantes (ex.: `grade is None ⇔ object_type == unknown`; …)") | O exemplo de invariante no checklist da skill ainda é o da 0.3.0. Um autor ou revisor que siga o checklist ao pé da letra pode "corrigir" o validador de volta, e isso recusaria ferramentas sem grau. O código e os testes (CA-02, CA-03) barram a regressão, por isso o risco é baixo. | Nada nesta SPEC (a skill não está no escopo dela). O orquestrador ou o architect pode atualizar o exemplo para "grupos de grau do ADR-021" numa mudança de documentação. |

Concordo com o RV-03 do review-report do ponto de vista da R-11: se todas as fotos antigas de uma ferramenta estendida forem excluídas, essa ferramenta poderia ser estendida uma segunda vez. O cenário é improvável e não abre caminho para imagem externa no teste, nem para mudar a atribuição de peça antiga. Fica baixo, sem novo achado.

## Reaprovação delegada (ADR-019; checklist §6)

Conferida no `git show 6d25aaf` (architect) e no `git show f564584` (orquestrador), contra a linha do Histórico da SPEC. As reaprovações dos SPEC_ISSUE-1 e 2 (`83d64a1`) foram **humanas** (`be3d2ec`), não delegadas. O SPEC_ISSUE-2 mudou a regra de estrato da extensão do split (X-7, R-11) e foi corretamente classificado como "exige humano".

| Critério | Resultado |
|---|---|
| E-1 Origem | ✅ SPEC_ISSUE-T1 com ID em `reviews/SPEC-016/r1-test-report.md` |
| E-2 Autoria | ✅ `6d25aaf` com `Agent: architect`, toca só `docs/specs/SPEC-016-ferramentas-manuais.md` e `docs/plan.md`. A atualização de `docs/architecture.md` foi para outro commit (`c2c337a`) e não tem relação com o CA-11 |
| E-3 Estado | ✅ SPEC aprovada pelo humano (PR #45) e `Blocked` por este SPEC_ISSUE (`734f2c8`) |
| E-4 Natureza | ✅ CA-11: forma de verificação ajustada à regra vigente da SPEC-036 §4.2 (tipo 2). A nota de rodada do §6, o aviso do topo e o Histórico são do tipo 4 |
| E-5 Abrangência | ✅ com a ressalva do RV-04 (o rótulo da nota anterior do §6 é ajuste de nota de rodada, necessário para a coerência) |
| X-1 a X-4 | ✅ nenhuma SPEC nova, ADR, regra, contrato ou outro documento |
| X-5 | ✅ nenhum comportamento novo: o plano misto sair com 2 sem gravar já era exigido pela SPEC-036 §4.2 e pelo CA-04 dela. `git diff --stat d7d1810 f564584` mostra só `docs/` |
| X-6 (limites de segurança) | ✅ nenhum CA removido, nenhum caso de erro retirado (o caso de erro ganhou o plano misto). Nenhum limite de segurança mudou: tamanho (`IMPORT_MAX_BYTES`), taxa, timeout, permissões e autenticação não aparecem na correção |
| X-7 (regra inegociável) | ✅ o CA-11 não verifica a R-14: o `--privacy-checked` aparece nele só como parte do comando e continua igual, fora da correção. Também não verifica a R-11 (o `XT-` só no treino é o CA-20, intocado). A recusa por `item_prefix_mismatch` é regra de rótulo, e não de privacidade |
| X-9 | ✅ nenhuma marcação "exige humano"; primeira correção delegada do CA-11 e da nota de rodada nesta SPEC |
| Registro | ✅ `f564584` (`Agent: orchestrator`) só de status: aviso do topo "Reaprovada pelo orquestrador sob o ADR-019 em 2026-10-24 (UTC)" e linha do Histórico com o sha `6d25aaf` |

Nenhuma reaprovação fora dos limites. Nenhum `SPEC_ISSUE` "exige humano".

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ sem mudança: nenhuma rota nova, nenhuma dependência de autenticação alterada. As rotas de escrita aceitam ferramentas só pelo contrato |
| Entradas validadas (tamanho, tipo real da imagem, regex, `extra="forbid"`) | ✅ contrato com `extra="forbid"` e tetos intactos; `SpcObjectType` fechado (422). Na borda, `labels.json` validado no carregamento, `item_id` por `re.fullmatch` com prefixo × tipo e grau obrigatório na coleta e na importação. O tipo real da imagem e a normalização da SPEC-036 ficam iguais |
| SQL sempre parametrizado | ✅ só fragmentos constantes (`grade is not null`) e valores em `%(…)s`; nenhuma f-string em SQL de produção |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | ✅ a `003` não toca RLS, `grant`/`revoke` nem papéis; nenhuma credencial nova ou exposta |
| CORS fechado ou mínimo | ✅ sem mudança |
| Logs sem segredos e sem payloads de imagem | ✅ nenhum log novo com valor de entrada. A recusa do banco loga só SQLSTATE; os erros de `labels.json`, coleta e importação citam a regra, não o valor |
| Dependências novas | ✅ nenhuma (só a versão do pacote do workspace no `uv.lock`) |
| Deploy (variáveis no provedor, health check, plano free sem cartão) | ✅ nenhuma variável, serviço ou configuração de deploy nova (R-01). O `/api/v1/health` passa a mostrar `contract_version = 0.4.0`. A ordem de aplicação da `003` fica como ação humana (SEC-16-01) |
| Reaprovação delegada (ADR-019) | ✅ SPEC_ISSUE-T1 dentro de E-1 a E-5, sem exclusão; nada em X-6 nem X-7 (tabela acima) |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. `qc-contracts` (workspace) passa de 0.3.0 para 0.4.0 |

## Verificação

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
251 files already formatted
$ uv tree --package qc-api / --package qc-dashboard | grep -iE "torch|onnxruntime|timm"
(nada)
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run --locked pytest -q -p no:cacheprovider
7293 passed, 75 skipped, 1 warning in 618.29s (0:10:18)
```

Rodado no ambiente do CI (sem o extra `train`), com o `partqc_test` e nenhuma outra suíte com banco ao mesmo tempo.

## Ações pendentes para o humano

1. **No deploy desta SPEC, nesta ordem:**
   1. merge;
   2. a partir do checkout local com o `.env.migrate`, rodar `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` (a `003_tool_object_types.sql` aparece pendente) e depois `uv run --env-file .env.migrate --package qc-api python infra/migrate.py` (sai com 0);
   3. atualizar a API e o dashboard na VPS;
   4. conferir com `curl -fsS https://<subdominio>/api/v1/health` que o `contract_version` é `0.4.0`;
   5. só então atualizar a borda e carregar um modelo com ferramentas.

   Se alguma ferramenta tiver virado `dead` no meio do caminho, rodar `python -m qc_edge.requeue` (SPEC-034) depois do passo 4 (SEC-16-01).
2. **Coleta das ferramentas (§3.3, R-14):** fundo liso, sem mãos nem pessoas no quadro. Na importação, conferir cada foto a olho antes de passar `--privacy-checked`, manter a pasta de entrada fora da árvore do Git (SEC-36-02) e registrar a licença e a fonte de cada `XT-` antes de importar.
3. CA-21 (manual) depois da coleta; não bloqueia o merge.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC (autores: developer, ml-engineer, tester, architect e orchestrator).
