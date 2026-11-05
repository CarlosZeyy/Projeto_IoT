# SPEC-044 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-044](../../docs/specs/SPEC-044-ferramentas-so-identificadas.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...b654f3a` (19 commits, 77 arquivos) |
| Relatórios lidos | [r1-dev-report.md](r1-dev-report.md), [r1-test-report.md](r1-test-report.md) (PASS), [r1-review-report.md](r1-review-report.md) (APPROVED); ADR-025 (`Aceito`) |
| **Veredicto** | **PASS** |

Não há achado bloqueante, alto nem médio. Há três achados baixos, todos operacionais e ligados ao deploy em produção (CA-15), e uma nota informativa sobre privacidade, que fica para o portão da SPEC-045.

## Superfície analisada

- **Rotas:** a SPEC não cria nem altera rota na API, na borda ou no dashboard, e `api/src` não tem diff. A autenticação existente continua igual: `X-Session-Token` na borda, `api_key_hash` por dispositivo e `READ_API_KEY` nas leituras.
- **Contrato (`qc-contracts` 0.7.0):** entram três valores no `ObjectType` e os três vão para `GRADE_FORBIDDEN_OBJECT_TYPES`. O código da invariante de `_InspectionBase` não muda, só o conteúdo do grupo. `extra="forbid"` continua intacto. A mudança é minor e só amplia o que o contrato aceita.
- **Banco (`infra/migrations/007_identified_tool_object_types.sql`):**
  - a migração é DDL estática, sem interpolação e sem credenciais, num único bloco `DO` (drops e adds atômicos), sem `BEGIN`/`COMMIT`;
  - os nomes das restrições são os mesmos da `006`;
  - não toca em RLS, grants, colunas, `is_defective` nem dados;
  - a expressão é literalmente a da SPEC §4.2.
  - **Verificação independente** num banco descartável do contêiner de teste:
    - apliquei de `001` a `006` e inseri todos os pares tipo × grau. O banco aceitou 45 pares, os do contrato 0.6.0;
    - apliquei a `007`, e as 45 linhas continuaram lá: nenhuma linha válida antes deixou de ser válida;
    - apliquei a `007` de novo e o `md5(pg_get_constraintdef)` dos dois `check` ficou igual, o que confirma a idempotência;
    - depois da `007`, o banco aceita 48 pares (45 + `hammer`, `wrench` e `spirit_level` só com `grade` nulo) e recusa `lathe` (fora do enum) com `23514`;
    - `relrowsecurity` continua `t`;
    - apaguei o banco descartável no fim.
  - Em produção, a migração passa pelo `infra/migrate.py`: transação, advisory lock de sessão, porta 6543 recusada, checksum em `schema_migrations` e nenhuma URL nos logs.
- **API:** nenhum SQL novo. As três ferramentas ficam fora do SPC e do `defect_rate` pela regra `grade is not null`, que já existe. `SpcObjectType` não muda, e `object_type=wrench` no filtro do SPC dá 422 (CA-04, que rodei com banco).
- **Borda:**
  - **coleta:** `object_type` é validado pelo enum `DatasetObjectType`; `item_id` pela regex `[SNOT]-\d{3}` com `fullmatch`. `_parse_grade` recusa **qualquer** grau não vazio para as três com 422 antes de gravar (mensagem própria, sem eco do valor) e trata um valor não string como `InvalidCollectFieldError`;
  - **caminho em disco:** `raw/<enum>/_/<item_id>__…` só tem segmentos de enum, regex ou constante, então não há traversal;
  - **importação:** deriva tudo das listas do `qc_edge.collect`, devolve `grade_on_other` e recusa o plano inteiro sem gravar. O limite de tamanho, a contenção do inbox e o regex `X[SNOT]-[0-9]{4}` não mudam;
  - **console:** as linhas novas da tabela de cobertura passam por `html.escape` (`edge/src/qc_edge/app.py`, `_coverage_row_html`), e o texto das metas usa só constantes do contrato;
  - **`capture.js`:** muda só as listas `NO_GRADE` e `PREFIX_TYPES`. Não há `fetch` novo, URL nova nem armazenamento novo, e nada sai da LAN (R-02).
- **Dashboard:** muda só constantes (ordem e três cores hex fixas). Não há `unsafe_allow_html` novo, e `SPC_OBJECT_TYPES` não muda.
- **ML:** muda só constantes e o gerador sintético (polígonos desenhados, sem foto real). Nenhum arquivo de imagem, `.onnx`, `.npz` ou `.csv` foi versionado no diff.
- **Dependências e deploy:**
  - o `uv.lock` muda só a versão editável do `qc-contracts` (0.6.0 → 0.7.0), e `uv lock --check` passa;
  - nenhum `pyproject.toml` de `api/` ou `dashboard/` mudou (R-12);
  - não há diff em `.env.example`, `infra/docker`, `infra/compose.yaml`, `Caddyfile`, `render.yaml` ou `.github/`;
  - não há variável nova.
- **Documentos (ADR-025, SPEC-045, arquitetura, protocolo):**
  - os colegas aparecem só como `c01`, `c02` e `c03`;
  - os caminhos citados (`~/partqc-entrada/…`) ficam fora do repositório e não identificam ninguém;
  - não há nome, e-mail, domínio, IP real nem imagem.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-44-01 | baixa | deploy | `docs/specs/SPEC-044-ferramentas-so-identificadas.md:129` (CA-15); `docs/deployment-plan.md:362-373` | **Ordem do CA-15 × webhook.** O CA-15 lista, nesta ordem, "1. migração", depois "3. deploy do `partqc-api` e do `partqc-web` pelo Coolify". Só que o webhook publica os dois recursos **no merge** (deployment-plan, "Atualização"), então na prática a API 0.7.0 sobe antes ou durante a aplicação da `007`. As duas ordens são seguras: a `007` só amplia os `check`, a API 0.6.0 já recusaria os tipos novos no Pydantic, e nenhum produtor emite os tipos novos antes da borda ser atualizada (o simulador só gera parafusos, porcas e `unknown`; a borda vem por último). No pior caso, um tipo novo recebe 422, vira `dead` e volta pelo `requeue` (passo 6). | Não bloqueia. No CA-15, seguir a seção "Quando o merge traz migração nova ou contrato novo" do deployment-plan: merge (webhook) → `migrate.py --status`, aplicar e `--status` com `0 pending` **logo depois do merge** → consulta do passo 2 → `/health` com `0.7.0` → borda → `requeue`. Registrar o passo 3 como "deploys do webhook conferidos no painel", e não como um deploy disparado à mão depois da migração. |
| SEC-44-02 | baixa | deploy | `dashboard/src/qc_dashboard/api.py:199-210`; `packages/contracts/src/qc_contracts/schemas.py:172`; `api/src/qc_api/repositories/inspections.py:288` | **Janela entre dashboard 0.6.0 e API 0.7.0.** A API sempre devolve `by_object_type` com **todos** os membros do `ObjectType`, inclusive os três novos com 0. Um dashboard ainda em 0.6.0 valida o resumo com `dict[ObjectType, int]` e recusa as chaves novas, então "invalid API response body" aparece no painel até o `partqc-web` terminar o deploy. É transitório, já acontecia na SPEC-021 e não vaza nada (o log tem só o caminho, sem o corpo). Se o deploy do `partqc-web` falhar e o do `partqc-api` passar, o resumo fica fora do ar até alguém agir. | Não bloqueia. No item 2 da "Atualização", conferir que os **dois** deploys terminaram com sucesso. Se o `partqc-web` falhar, refazer o deploy dele antes de seguir para a borda. |
| SEC-44-03 | baixa | deploy | `infra/migrations/007_identified_tool_object_types.sql:20-76`; `docs/deployment-plan.md` §4, passo 1, item 3 | **Re-execução manual de uma migração antiga (pendência do SEC-21-01).** A `007` substitui os `check` com os mesmos nomes. Se alguém colar a `003` ou a `006` no SQL Editor depois da `007`, há dois casos. Sem linhas dos tipos novos, os `check` voltam silenciosamente a 8 ou 12 valores, e todo `POST` com `hammer`, `wrench` ou `spirit_level` passa a falhar com `23514` (indisponibilidade parcial, sem perda de dado). Com essas linhas, o `alter` falha e não muda nada. O runner não tem o problema. A sugestão do SEC-21-01, um aviso no deployment-plan, ainda não foi aplicada. | Nenhuma nesta SPEC. Na próxima manutenção do deploy, o security-devops, no modo autor, acrescenta ao passo 1, item 3, do deployment-plan uma frase: "migrações só pelo `infra/migrate.py`; nunca colar um arquivo de migração isolado no SQL Editor". |
| SEC-44-04 | info | privacy | `docs/adr/ADR-025-treino-com-fotos-dos-colegas.md` (decisão 3; "Contexto") | O ADR-025 registra uma exceção única, aprovada pelo humano, à decisão 6 do ADR-024: o orquestrador viu as 223 fotos dos colegas em 2026-11-04. O texto da R-02 não muda. Esta SPEC não lê nem grava foto real: os testes usam só imagens sintéticas e geradas em memória, e nada de `ml/data/` entrou no diff. A reimportação e o `--privacy-checked` são da SPEC-045. | Nenhuma nesta SPEC. No portão da SPEC-045, conferir que nenhum agente abre fotos (a decisão 6 continua valendo), que os colegas foram avisados com a opção de retirada (§10.7 do protocolo) e que a pasta de entrada é apagada no fim. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ Nenhuma rota nova nem alterada; a autenticação existente está intacta. |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | ✅ Os tipos novos entram por enum, com as regexes de `item_id` em `fullmatch`. O grau vazio é obrigatório para os três: 422 na coleta, `grade_on_other` na importação e no `qc_ml`, e nada é gravado na recusa. O caminho em disco só tem segmentos de enum, regex ou constante. Pillow, limites de tamanho e `extra="forbid"` não mudam. |
| SQL sempre parametrizado | ✅ Não há SQL novo na API. A `007` é DDL estática. Os testes novos usam `%s`; o nome do banco descartável do teste vem de `secrets.token_hex`. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ A `007` não toca em RLS nem em grants (`relrowsecurity` continua `t` na verificação independente). Não há referência nova a credenciais. A migração em produção roda da máquina do humano com o `.env.migrate`, como o deployment-plan já manda. |
| CORS fechado ou mínimo | ✅ Sem mudança. |
| Logs sem segredos e sem payloads de imagem | ✅ Não há log novo em código de produção. O erro de contrato do dashboard registra só o caminho. |
| Dependências novas (licença, manutenção, CVE) | ✅ Nenhuma. O `uv.lock` muda só a versão editável do `qc-contracts`, e `uv lock --check` passa. |
| Deploy (variáveis no provedor, health check, free sem cartão) | ✅ Não há variável nova nem mudança de imagem, compose, proxy ou workflow. A ordem de deploy (SPEC §4.4) e o CA-15 são seguros nas duas ordens possíveis: SEC-44-01 e SEC-44-02. |
| Reaprovação delegada (ADR-019) | ✅ Não houve correção de SPEC nesta branch. Depois do `Ready` (`b63d35f`, aceite humano), o arquivo da SPEC só mudou em `Status` e `Rodada atual` (`e097a9e`, `e42c7d5`, `45d27d1` e `b654f3a`, todos do orquestrador). Nenhum X-6 nem X-7 em jogo. |
| R-02 / R-14 (privacidade das imagens) | ✅ Só imagens sintéticas; nenhum arquivo de imagem versionado; `capture.js` sem envio novo. A exceção do ADR-025 fica fora do código desta SPEC (SEC-44-04). |
| R-03 (segredos) | ✅ Busca nas linhas adicionadas por URL com senha, `eyJ`, `password`, chave privada, IP público e e-mail: nada. Os únicos achados são o `postgresql://postgres@localhost` sem senha nos relatórios, `127.0.0.1`/`192.168.0.42` em testes e `example.org`/`api.test`. Os scanners `test_ca05_no_secret_material_outside_docs` e `test_no_secret_material_in_tracked_files` passam. |
| R-12 | ✅ `api/` e `dashboard/` sem torch/onnxruntime; nenhum `pyproject.toml` deles foi alterado. |
| R-13 | ✅ Os 19 commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, todos com `Agent:`. O CA-15 manda registrar o resultado sem o subdomínio real. |

## Verificação do security-devops

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q \
    infra/tests/test_migrate_db.py infra/tests/test_schema_db.py infra/tests/test_migration_files.py \
    infra/tests/test_deploy_files.py infra/tests/acceptance/test_spec_015.py \
    api/tests/acceptance/test_spec_044.py api/tests/test_identified_tools.py packages/contracts/tests
1580 passed, 16 skipped (PARTQC_DOCKER_TESTS)

$ uv run pytest -q edge/tests/acceptance/test_spec_044.py edge/tests/test_identified_tools.py \
    edge/tests/test_importer.py edge/tests/test_collect.py edge/tests/test_collect_route.py \
    dashboard/tests/acceptance/test_spec_044.py dashboard/tests/test_identified_tools.py \
    ml/tests/acceptance/test_spec_044.py ml/tests/test_identified_tools.py
642 passed

$ uv run ruff check .   -> All checks passed!
$ uv lock --check       -> Resolved 116 packages

# Banco descartável no contêiner de teste (apagado no fim), via psql:
001..006 aplicadas; pares aceitos (16 tipos x 6 graus, inclusive 'lathe'): 45
007 aplicada; linhas existentes: 45 (todas mantidas)
007 de novo; md5(pg_get_constraintdef) dos dois check: igual (idempotente)
pares aceitos depois da 007: 48; hammer|wrench|spirit_level só com NULL; lathe recusado
relrowsecurity(inspections) = t

$ git diff main...HEAD --name-only | grep -iE '\.(jpe?g|png|heic|webp|onnx|npz|csv)$'   -> (vazio)
```

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. Só o `qc-contracts` (pacote do workspace) passa de 0.6.0 para 0.7.0. |

## Ações pendentes para o humano (CA-15, depois do merge)

1. **Logo depois do merge**, na máquina do humano e num checkout atualizado da `main`:
   - `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` mostra a `007` pendente;
   - aplicar com o mesmo comando sem `--status`;
   - rodar `--status` de novo, que deve mostrar `0 pending`.
   Use o pooler em modo session (porta 5432) ou a conexão direta, nunca a 6543.
2. No SQL Editor: `select conname, pg_get_constraintdef(oid) from pg_constraint where conname in ('inspections_object_type_check','inspections_grade_null_iff_unknown');` mostra `spirit_level` nos dois.
3. No painel do Coolify, os deploys do webhook do `partqc-api` e do `partqc-web` terminaram com sucesso, os dois em execução (SEC-44-01, SEC-44-02).
4. `curl -fsS https://<subdominio>/api/v1/health` mostra `"contract_version":"0.7.0"`.
5. Só então atualizar a borda.
6. `uv run --package qc-edge python -m qc_edge.requeue --outbox-path <arquivo>` lista zero `dead`. Se houver `dead`, repetir com `--yes`.
7. Registrar a data e o resultado de cada passo no test-report, sem o subdomínio real.

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
