# SPEC-021 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r2 |
| Revisor de segurança | security-devops |
| Diff revisado | `spec/SPEC-020-mqtt...a65e3b9` (branch empilhada na SPEC-020; base `3da84d2`) |
| Relatórios lidos | [r2-test-report.md](r2-test-report.md) (PASS), [r2-review-report.md](r2-review-report.md) (APPROVED), [r2-dev-report.md](r2-dev-report.md), [r1-dev-report.md](r1-dev-report.md), [r1-test-report.md](r1-test-report.md) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Um achado baixo, operacional, e duas notas informativas.

## Superfície analisada

- **Rotas:** nenhuma rota nova nem alterada na API, na borda ou no dashboard. `api/src` não tem diff. A autenticação das rotas existentes (`X-Session-Token` na borda, `api_key_hash` por dispositivo, `READ_API_KEY` nas leituras) não mudou.
- **Entradas externas novas:** só valores de enum novos (`angle_grinder`, `saw`, `drill`, `cordless_screwdriver`) nos caminhos que já validam por enum e regex:
  - **coleta** (`edge/src/qc_edge/collect.py`): `object_type` é validado contra `DatasetObjectType`; `item_id` por `re.fullmatch(r"[SNOT]-\d{3}")`; o prefixo `T` passa a admitir as 4 elétricas; `_parse_grade` recusa **qualquer** valor não vazio para as elétricas (inclusive espaço), com 422 antes de gravar, e um valor não string continua `InvalidCollectFieldError`;
  - **caminho em disco:** `raw/<object_type.value>/<grade.value | "_">/<item_id>__<angle>__<ts>.jpg`. Todos os segmentos vêm de enum, regex fechada ou constante (`NO_GRADE_DIR = "_"`), então não há traversal; `os.path.lexists` + `make_private_dirs` (0700) sem mudança;
  - **409 na troca de tipo:** `ItemTypeConflictError` compara `item_id` e `object_type` de forma genérica, sob o lock do manifest, então vale para `T-NNN` alternando entre ferramenta manual e elétrica (coberto pelos aceites da borda);
  - **importação** (`edge/src/qc_edge/importer.py`): `_grade_problem` usa `UNGRADED_DATASET_TYPES` (`other` + elétricas) e devolve `grade_on_other`, recusando a linha sem gravar nada. Regex `X[SNOT]-[0-9]{4}`, contenção `is_relative_to` do inbox, limite de 40 MiB e destino `raw/<tipo>/_/` sem mudança;
  - **`qc_ml.data`:** `grade_on_other` para elétrica com grau e prefixo `T`/`XT` com as 4 elétricas, tudo derivado de `GRADE_FORBIDDEN_OBJECT_TYPES` do contrato.
- **Contrato:** `qc-contracts` 0.6.0. A invariante não muda de código e segue os grupos (`GRADE_FORBIDDEN_OBJECT_TYPES` ganha as 4); `extra="forbid"` intacto.
- **Banco:** `006_power_tool_object_types.sql` é só DDL estática (`drop constraint if exists` + `add constraint`) num bloco `DO`. Não apaga linha nem coluna e não mexe em RLS, grants ou `is_defective`. Não tem credenciais e é idempotente. O runner (`infra/migrate.py`) registra versão e checksum em `schema_migrations`. Rodei `infra/tests/test_migrate_db.py` e `test_schema_db.py` no banco de teste: os `check` aceitam exatamente os 72 pares tipo × grau do `InspectionCreate` 0.6.0.
- **SPC e `defect_rate`:** `SpcObjectType` não muda, e as elétricas ficam fora pela regra `grade is not null` já existente. `object_type=drill` no filtro dá 422, coberto pelo CA-04 (`api/tests/acceptance/test_spec_021.py`), que rodei com banco.
- **Dashboard:** só constantes (ordem, cores hex fixas e rótulos do contrato), sem `unsafe_allow_html` novo. Na borda, a linha de cobertura das elétricas passa por `html.escape` (`app.py:725`) e os rótulos vêm de constantes.
- **`capture.js`:** só listas `POWER`/`NO_GRADE` e a lógica de desabilitar o grau. Não há `fetch` novo, URL nova, segredo nem armazenamento novo. O token continua lido da query (comportamento anterior). Nada sai da LAN (R-02).
- **ML e privacidade (R-02, R-14, ADR-020):**
  - imagens só sintéticas (silhuetas de plástico desenhadas pelo gerador, sem pessoas);
  - a fixture `tiny_model_power_tools/parity_fixture.npz` tem `inputs` **idênticos** aos da fixture `tiny_model_tools` já aceita (conferido com `np.array_equal`), gerados por `make_synthetic_dataset(seed=0)`. Não há foto real;
  - nenhum `.jpg/.png/.heic/.webp` versionado;
  - a extensão do teste usa só peças não externas, e as externas (`XT-`) ficam só no treino;
  - a URL nova de fonte nos testes é `example.org`.
- **Dependências e deploy:** `uv.lock` muda só a versão editável do `qc-contracts` (0.5.0 → 0.6.0) e `uv lock --check` passa. Nenhum `pyproject.toml` de `api/` ou `dashboard/` foi alterado (R-12). Não há mudança em `.env.example`, `infra/docker`, `compose.yaml`, Caddyfile ou workflows.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-21-01 | baixa | deploy | `infra/migrations/006_power_tool_object_types.sql:1-67`, `docs/architecture.md` §5 | **Re-execução manual da `003` depois da `006` reverte os `check`.** A 006 substitui os dois `check` da 003 com o mesmo nome. Se alguém colar a 003 de novo no SQL Editor do Supabase depois da 006, há dois casos. Sem linhas de elétricas, a 003 volta silenciosamente aos 8 valores, e todo `POST` de elétrica passa a falhar com `23514` (indisponibilidade parcial, sem perda de dado). Com linhas de elétricas, a 003 falha e não altera nada. O runner `infra/migrate.py` não tem o problema (aplica em ordem e registra checksum), e o risco está documentado no cabeçalho da 006 e em `docs/architecture.md` §5 ("as migrações rodam sempre em ordem"). Não bloqueia. | Nenhuma nesta SPEC. Sugestão para a manutenção do deploy: o passo a passo de produção (`docs/deployment-plan.md`) deve dizer que as migrações só se aplicam pelo runner ou em ordem completa, nunca colando um arquivo antigo isolado. |
| SEC-21-02 | info | process | merge `de2afcc` | Merge da 020 sem `Refs:`/`Agent:`, já registrado como RV-01 (baixa) pelo reviewer. Não muda superfície de segurança: o merge é limpo (`git show --cc` vazio). | Nenhuma (seguir a recomendação do RV-01 nos próximos merges). |
| SEC-21-03 | info | deploy | SPEC-021 §4 | **Ordem de deploy.** Uma API 0.6.0 sem a 006 aplicada recusaria as elétricas no banco (`23514`). Um dashboard 0.5.0 que ler linhas de elétricas de uma API 0.6.0 falharia na validação do `InspectionRead`. A ordem contracts → banco → API → dashboard → borda (§4 da SPEC, skill `contrato-api`) evita os dois casos, e a borda só produz elétricas com um modelo que as tenha (CA-14, humano). | Nenhuma; seguir a ordem no deploy. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ Nenhuma rota nova nem alterada; autenticação existente intacta. |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | ✅ Os tipos novos entram por enum; regex `[SNOT]-\d{3}` / `X[SNOT]-[0-9]{4}` com `fullmatch`; grau vazio obrigatório para as elétricas (422 na coleta, `grade_on_other` na importação e no `qc_ml`), nada gravado na recusa; caminho só com segmentos de enum/regex; tipo real da imagem (Pillow) e limites de tamanho sem mudança; `extra="forbid"` intacto. |
| SQL sempre parametrizado | ✅ Sem SQL novo na API; a 006 é DDL estática, sem interpolação. Os testes novos usam `%s`. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ A 006 não mexe em RLS nem em grants; nenhuma referência nova a credenciais. |
| CORS fechado ou mínimo | ✅ Sem mudança. |
| Logs sem segredos e sem payloads de imagem | ✅ Nenhum log novo em código de produção. |
| Dependências novas (licença, manutenção, CVE) | ✅ Nenhuma; `uv.lock` só com a versão editável do `qc-contracts`; `uv lock --check` ok. |
| Deploy (variáveis no provedor, health check, free sem cartão) | ✅ Sem mudança de configuração de deploy; nenhuma variável nova (`.env.example` intocado); a ordem de deploy está na SPEC §4 (SEC-21-03); a re-execução manual da 003 é a nota SEC-21-01. |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma correção de SPEC nesta branch. O diff da SPEC é só `Status`/`Rodada atual` e uma linha de Histórico do orquestrador (entrada em `In Dev` por decisão do humano de 2026-10-26). Nenhum limite de segurança (X-6) nem CA de regra inegociável (X-7) foi tocado. |
| R-02 / R-14 (privacidade das imagens) | ✅ Só imagens sintéticas; a fixture tem os mesmos `inputs` sintéticos da `tiny_model_tools`; nenhum arquivo de imagem versionado; `capture.js` sem envio novo; externas só no treino (ADR-020). |
| R-03 (segredos) | ✅ Busca no diff por URL com senha, `eyJ`, `password=`, `secret=`, chave privada: nada. As credenciais de teste são geradas em execução (`secrets.token_*`). Os scanners `test_ca05_no_secret_material_outside_docs` e `test_no_secret_material_in_tracked_files` passam (o T-01 da r1 foi corrigido em `57bf279`). |
| R-06 (simulado visível) | ✅ `source` não muda; elétrica simulada continua `simulated` (exploratório do reviewer). |
| R-12 | ✅ `api/` e `dashboard/` sem torch/onnxruntime; nenhum `pyproject.toml` deles alterado. |

## Verificação do security-devops

```text
$ uv run pytest -q infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs \
    infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files \
    infra/tests/test_migration_files.py packages/contracts/tests edge/tests/test_power_tools.py \
    edge/tests/test_importer.py edge/tests/acceptance/test_spec_021.py \
    dashboard/tests/test_power_tools.py dashboard/tests/acceptance/test_spec_021.py \
    ml/tests/test_power_tools.py
1253 passed, 1 skipped (torch ausente)

$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q \
    infra/tests/test_migrate_db.py infra/tests/test_schema_db.py \
    api/tests/test_power_tools.py api/tests/acceptance/test_spec_021.py
272 passed

$ uv run ruff check .        -> All checks passed!
$ uv lock --check            -> Resolved 116 packages
$ git diff spec/SPEC-020-mqtt...HEAD --name-only | grep -iE '\.(jpe?g|png|heic|webp)$'   -> (vazio)
```

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. Só `qc-contracts` (pacote do workspace) passa de 0.5.0 para 0.6.0. |

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
