# SPEC-040 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-040](../../docs/specs/SPEC-040-manutencao-consolidada.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops (Partes A e B, autores: developer e ml-engineer) e reviewer (Parte C, autor: security-devops), como manda a SPEC §6 |
| Diff revisado | `main...7c31940` (Parte C: commits `f8d313c`, `7af5eb6`, `c2a4753` e `bb2fea4`) |
| **Veredicto** | **Pendente:** a Parte C é PASS, e falta a seção das Partes A e B (SPEC §6: PASS só com as duas PASS) |

| Parte | Revisor | Veredicto |
|---|---|---|
| A e B (`edge/`, `api/`, `dashboard/`, `ml/`) | security-devops | pendente |
| C (comentários de `infra/docker/*.Dockerfile` e `.streamlit/config.toml`; `docs/deployment-plan.md`) | reviewer | **PASS** |

## Parte C (reviewer)

**Veredicto da Parte C: PASS.** Nenhum achado bloqueante, alto ou médio. Há 1 achado baixo (SEC-40-C1, o mesmo RV-05 do `r1-review-report.md`) e 2 informativos.

### Superfície analisada

- **Rotas e entradas externas:** nenhuma. A Parte C só muda comentários, documentação e testes do autor.
- **Segredos:** nenhum novo. O plano passa a citar a `READ_API_KEY` no CA-18, sempre pelo ambiente do contêiner e por um descritor.
- **Dependências novas:** nenhuma. `uv.lock`, os `pyproject.toml` e o `.env.example` estão intocados.
- **Configuração de deploy:** nenhuma instrução muda. O diff de `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` e `.streamlit/config.toml` só tem linhas de comentário: filtrei as linhas `+`/`-` que não começam com `#`, e não sobrou nenhuma. Os `.dockerignore` e os compose não mudam.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-40-C1 (= RV-05) | baixa | deploy | `docs/deployment-plan.md:439` | O §7, item 5, ainda manda repetir só "o smoke (passo 11), o CA-16 e o CA-20 da SPEC-039" depois de atualizar o Coolify, sem o CA-18 da SPEC-040. A "Atualização" da §4 e o item 12 da §7 já citam o CA-18. A §4.10 só pedia a frase da "Atualização", então o texto cumpre a SPEC, e o autor registrou a escolha. Quem seguir só o item 5 deixa de conferir o `identity` depois de atualizar o proxy. O efeito é limitado: a falha é transitória, aparece no log, e os itens ficam `pending`. | Nenhuma nesta rodada. Na próxima mudança do plano, acrescentar o CA-18 (passos 1 a 3) a esse item, ou trocar a lista por uma referência à "Atualização". |
| SEC-40-C2 | informativa | deploy | `docs/deployment-plan.md:453` | O teste do autor com o `traefik:v3` local (`v3.7.17`) mostra que `identity` volta sem compressão, mas não prova a versão da VPS. Não repeti esse teste. O plano declara o limite, e só o CA-18 confere o caminho real. Se o proxy comprimir mesmo com `identity`, a borda para de enviar até a correção, sem perder inspeções, e o CA-18 manda voltar a versão da borda. | Executar o CA-18 depois do deploy (humano). |
| SEC-40-C3 | informativa | privacy | `docs/deployment-plan.md:455` | A nota de CDN está certa para o layout atual: `infra/compose.yaml:74` monta `API_BASE_URL` como `https://${PUBLIC_HOST}`, então a chave de leitura também sai pelo subdomínio público. Com proxy de CDN, ela atravessa um TLS terminado por terceiros. A recomendação é não usar proxy, e a anotação fica fora do repositório. Não há como conferir o DNS real daqui. | Anotar a escolha fora do repositório, no passo 3, item 4 (humano). |

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota, comparação em tempo constante | N/A: nenhuma rota |
| Entradas validadas | N/A: nenhuma entrada nova |
| SQL parametrizado | N/A: nenhum SQL de produção. O passo 3 do bloco novo remete à conferência existente do passo 1, item 4 |
| RLS ligado; `DATABASE_URL` e `service_role` fora da API | ✅ Nenhuma mudança. O bloco manda conferir RLS e grants de toda tabela nova, e a `DATABASE_URL` da migração continua só no `.env.migrate` local, nunca no `argv` |
| CORS | N/A |
| Logs sem segredos | ✅ O plano só cita mensagens fixas (`unsupported response encoding`, `unsupported content encoding`, `abandoned_for_s`). O CA-18 manda registrar as saídas com `<subdominio>` e sem a chave |
| Dependências novas | N/A: nenhuma |
| Deploy: variáveis no provedor, health check, plano free | ✅ Os comentários apontam para as Environment Variables do Coolify (ADR-023), coerentes com o `environment` de `infra/compose.yaml:72` e `infra/compose.api.yaml:29`. O passo 4 do bloco confere o `contract_version` no health. Nenhum serviço novo (R-01): a CDN é opcional e não recomendada |
| Reaprovação delegada (ADR-019) | N/A: o diff da SPEC-040 só muda `Status` e `Rodada atual`, e o Histórico não tem reaprovação |

### O que conferi nos comandos e nas fontes

- **CA-18, chave fora do `argv` e do histórico (R-03):** `k=$(docker exec <contêiner do dashboard> printenv READ_API_KEY)` passa só o nome da variável, e `-K <(printf ...)` usa o `printf` embutido do shell. O `-D -` imprime só os headers da resposta, sem `-v`, e o passo 2 termina com `unset k`. `infra/compose.yaml:75` confirma que o contêiner do dashboard tem a variável. Os comandos usam só marcadores. Li os comandos, mas não os executei.
- **Bloco de migração:** os comandos são os do passo 1, item 3, subitens 4 a 6. `0 pending` vem de `infra/migrate.py:380` (`%d applied, %d pending`). `--outbox-path` e `--yes` existem em `edge/src/qc_edge/requeue.py:96` e `:105`. A forma `uv run --package qc-edge python -m qc_edge.requeue` é a do `edge/README.md`.
- **Regra aditiva:** a ressalva do autor sobre a `002` confere com o cabeçalho da migração, que diz que os `check` espelham o contrato.
- **Fontes (consultadas de novo em 2026-10-31):** a referência do Traefik confirma as condições, os valores de `Accept-Encoding`, o padrão de 1024 bytes e o `defaultEncoding`, e a busca por `identity` no texto dela não achou nada, como o plano diz. A página do Coolify mostra `middlewares=gzip` no roteador `https-0-<resource-id>`.
- **R-03 e R-13:** busquei no diff inteiro padrões de JWT, token do Telegram, URL com senha, IP e nome de empresa, e no diff da Parte C também UUID e domínio. Só apareceram `127.0.0.1` e os domínios públicos das fontes.
- **Separação de papéis (R-07):** os commits da Parte C têm `Agent: security-devops` e só tocam os caminhos dela. Não sou autor deles.

**Não verifiquei:** nada na VPS, no Coolify real nem no DNS (CA-18, pendente com o humano), e não rodei os testes marcados com `docker`. O test-report registra 108 passados, e os Dockerfiles só mudam em comentários.

### Dependências novas

Nenhuma.

### Declaração

- [x] Não editei código; não sou autor da Parte C.
