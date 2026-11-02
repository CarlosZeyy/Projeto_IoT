# SPEC-043 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Revisor de segurança | reviewer (Parte B, autor: security-devops) e security-devops (Parte A, autor: developer), como manda a SPEC §8 |
| Diff revisado | Parte B: `origin/main...b566251`, commits `0bf23bf` e `2ea28a0` |
| **Veredicto** | **Parte B: PASS.** Parte A: pendente. O veredicto final do arquivo depende da seção da Parte A |

| Parte | Revisor | Veredicto |
|---|---|---|
| A (`scripts/`, `infra/migrate.py`, `api/`, `dashboard/`, `edge/`) | security-devops | Pendente |
| B (`docs/deployment-plan.md` e `.env.example`) | reviewer | **PASS** |

## Parte B (reviewer)

**Veredicto da Parte B: PASS.** Nenhum achado bloqueante, alto ou médio. Há 2 achados baixos e 1 informativo.

### Superfície analisada

- **Rotas e entradas externas:** nenhuma. A Parte B só muda documentação e um comentário.
- **Segredos:** nenhum valor novo. O `.env.example` ganhou uma linha de comentário, e a linha de exemplo continua com marcadores. O plano passa a orientar a senha do banco (só letras e números), a troca dela também no `partqc-api` e o tempo de vida do `.env.dbcheck`.
- **Dependências novas:** nenhuma. `uv.lock` e os `pyproject.toml` estão intocados.
- **Configuração de deploy:** nenhum arquivo de `infra/` muda. O plano descreve o que o painel do Coolify faz (Build time, Literal, cópias em Preview deployments, `www.<subdominio>`) e corrige o texto da rede `partqc-api-link`.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-43-B1 | baixa | secrets | `.env.example:88`; `docs/deployment-plan.md:158` | Os textos dizem que `:` na senha quebra a URL e que as ferramentas a recusam. Testei com valores fictícios: uma senha só com `:` a mais é aceita por `is_safe_conninfo` e é interpretada corretamente pela libpq, e o tester tem o mesmo caso em `test_extra_rule_table`. O texto do `.env.example` é o exato da SPEC §4.5, item 8, e o CA-17 o verifica. O erro é a favor da segurança: a regra prática, só letras e números, continua certa. | Nenhuma nesta rodada. Numa próxima edição, tirar o `:` da frase ou trocar por "podem quebrar". Não é `SPEC_ISSUE`: não impede verificar nada nem enfraquece a defesa. |
| SEC-43-B2 | baixa | secrets | `docs/deployment-plan.md:536` | O comando da conferência do `statement_timeout` chama `psycopg.connect` direto, sem `is_safe_conninfo`. Com uma URL mal formada no `.env.dbcheck`, um trecho da senha pode ir para a mensagem e para uma consulta de DNS, o caminho que a SPEC fecha nas três entradas da §4.2. O plano avisa sobre a mensagem, mas a consulta de DNS sai do mesmo jeito. A regra de só letras e números vem antes no procedimento, e a §4.2 limita a recusa a essas três entradas, então a implementação cumpre a SPEC. O mesmo vale para o CA-26 da SPEC-015. | Nenhuma nesta rodada. Numa próxima edição do plano, fazer o comando recusar a URL com `qc_api.conninfo.is_safe_conninfo` antes de conectar. |
| SEC-43-B3 | informativo | secrets | `docs/deployment-plan.md:539`, `:543` | O `.env.dbcheck`, com a senha do banco, pode ficar em disco por até 30 min, porque a §4.5, item 7, pede repetições. Continua com `chmod 600`, coberto pelo `.gitignore` e com o `rm` no fim. O `rm` aparece no subitem 3, antes do parágrafo das repetições, e a saída "parar e registrar `SPEC_ISSUE`" não repete que o arquivo deve ser apagado. | Nenhuma. Ao seguir o passo, apagar o arquivo também quando a conferência terminar em `SPEC_ISSUE`. |

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação nas rotas; comparação em tempo constante | N/A na Parte B: nenhuma rota |
| Entradas validadas | N/A na Parte B. A recusa da URL é da Parte A |
| SQL sempre parametrizado | N/A: nenhum SQL novo em código. O `revoke` e as consultas do plano já existiam |
| RLS ligado; `DATABASE_URL` e `service_role` fora de outros lugares | ✅ O passo 1, item 4, reforça que o `revoke` é obrigatório em todo projeto novo e explica as 56 linhas sem prometer uma contagem. A `DATABASE_URL` continua só no `partqc-api`, no `.env.migrate` e no `.env.dbcheck` temporário |
| CORS | N/A |
| Logs sem segredos e sem imagem | ✅ A §7, item 2, passa a limitar o "sem a senha" à URL bem formada e descreve a recusa, e o aviso de colagem no passo 5 cita o trecho da senha. Ver SEC-43-B2 |
| Dependências novas | ✅ Nenhuma |
| Deploy: variáveis, health check, plano free sem cartão | ✅ O Build time desligado em todas as variáveis endurece o SEC-39-03, e a cópia em Preview não recebe segredo. Health check e custo não mudam |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma correção foi reaprovada por delegação. SPEC_ISSUE-01 (X-7), SPEC_ISSUE-02 (X-6), SPEC-039 e emenda 2 do ADR-023 (X-2, X-3 e X-7) foram classificadas como "exige humano" e têm a reaprovação do humano registrada. Nenhuma muda limite de segurança de produção. A confirmação se apoia nos registros do repositório |

### O que conferi no texto do plano

- **§4.5, itens 1 a 9, e §4.7:** cada frase contra o diff. Nenhum valor real: a varredura das linhas adicionadas não achou UUID, subdomínio nem IP público real, e os únicos IPv4 fora de loopback e de faixas privadas são o `203.0.113.7`, do intervalo de documentação, o `0.0.0.0` e o `128.0.0.1`, um valor de borda de teste (R-13). Não li os `.env*` locais.
- **Rede `partqc-api-link`:** o texto novo aceita `true 2` e, no caso previsto, `true 3` com o `dashboard` do PartQC. Qualquer outro contêiner, a falta da `api` ou do `caddy`, ou `false`, é falha (SPEC-039, CA-20, passo 4). É mais restrito que o texto antigo, sem afrouxar o gatilho sobre os segredos no ADR-023. O item 10 da §7 mantém o risco aceito só para o caso de o `dashboard` voltar à rede.
- **`www.<subdominio>`:** decisão do humano (SPEC §9, item 5). O CA-42 procura o subdomínio com `git grep -F`, então também encontra o nome com `www.`. Conferi o comando no plano.
- **Simulador:** repetir com a mesma seed não cria duplicata (CA-04, com banco, passa nesta revisão), e a seed sai no erro. Conferi no `scripts/simulate.py`.
- **Fontes:** o plano cita literalmente a página do `ALTER ROLE` e a de variáveis do Coolify, com a data de conferência, e declara que o estado inicial das variáveis é uma medição, não documentação. Comparei com a §1 da SPEC, sem abrir as páginas de novo. Nenhum limite de free tier muda.
- **Testes que leem esses arquivos:** CA-16, CA-17 e seus extras passam nesta revisão. Os aceites das SPECs 015, 032, 038, 039 e 040 passaram na suíte do test-report, e depois dela o plano não mudou.

### Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| Nenhum | — | — | — |

### Declaração da Parte B

- [x] Não editei código; não sou autor da Parte B nem de nenhum outro commit desta SPEC.

## Parte A (security-devops)

Pendente: esta seção é do security-devops, depois da revisão.
