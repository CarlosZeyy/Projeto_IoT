# SPEC-043 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-043](../../docs/specs/SPEC-043-manutencao-pos-deploy.md) |
| Rodada | r1 |
| Revisor de segurança | reviewer (Parte B, autor: security-devops) e security-devops (Parte A, autor: developer), como manda a SPEC §8 |
| Diff revisado | Parte B: `origin/main...b566251`, commits `0bf23bf` e `2ea28a0`. Parte A: `main...5fd95ed`, commits `ab4be60`, `d98a115`, `3a79ba6` e `fa4f38f` |
| **Veredicto** | **PASS** (Parte A: PASS, pelo security-devops; Parte B: PASS, pelo reviewer) |

| Parte | Revisor | Veredicto |
|---|---|---|
| A (`scripts/`, `infra/migrate.py`, `api/`, `dashboard/`, `edge/`) | security-devops | **PASS** |
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

**Veredicto da Parte A: PASS.** Nenhum achado bloqueante, alto ou médio. Há 1 achado baixo e 1 informativo. Não avaliei a Parte B, de que sou autor.

A base do diff é `d5c77b2`. A `main` local está um merge atrás da `origin/main` (PR #72, só `reviews/SPEC-020/`), o que não muda essa base nem o diff.

### Superfície analisada

- **Rotas:** nenhuma nova. Autenticação, CORS e RLS não mudam. A regra de acesso ao console (SPEC-025) também não: o diff só troca a lista de endereços oferecidos e o aviso.
- **Entradas externas:** a `DATABASE_URL`, nas três entradas, e o `?ip=` do console, que continua aceitando só um valor de `ips`.
- **Segredos:** a URL do banco e a chave do simulador. A mensagem nova do simulador interpola só a classe da exceção ou `HTTP <código>` (`scripts/simulate.py:615`, `:619`).
- **Imagens:** o diff não toca no caminho delas (R-02, R-14).
- **Dependências novas:** nenhuma. `uv.lock` e os `pyproject.toml` estão intocados.
- **Configuração de deploy:** nenhum arquivo muda na Parte A. Com URL mal formada, a API sai com código 3, e o contêiner fica reiniciando com a mesma mensagem constante, como o humano decidiu (SPEC §9, item 2).

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-43-A1 | baixa | secrets | `api/src/qc_api/conninfo.py:45-51` | **Caminho que resta para um trecho da senha.** Uma senha de forma `<A>@<B>?application_name=<C>` é aceita pelo `is_safe_conninfo`, porque o `@` real e o host real caem no valor do parâmetro, que a regra não examina. Medido com valores fictícios e DNS bloqueado: o host vira `<B>`, a resolução recebe `<B>`, o `psycopg.pool` registra `failed to resolve host '<B>'`, e o `migrate.py` mostra `<B>:default port`. Com `/` no lugar de `@`, o trecho vai para o `dbname`, e com `?user=`, para o `user` (OBS-04 do test-report). Portanto, a frase "uma senha com `@` sempre leva `@` ao host", da seção "Corretude" do review-report, tem essa exceção. Na varredura, das 56 862 URLs, nenhuma combinação engana a regra sem `?<parâmetro válido>=` literal na senha; a isso se soma uma URL sem `@`, com senha só de dígitos, que vira `port`. É o limite de heurística que a §7 da SPEC admite. Uma senha só de letras e números não chega a nenhum desses casos, então a regra do plano fecha o caminho. | Nenhuma nesta rodada. Numa manutenção futura, avaliar recusar `@` em todo parâmetro que não seja `password`, o que pega todos os casos com `@` real na query. Muda a tabela da §4.2, então exige SPEC. |
| SEC-43-A2 | informativo | secrets | `api/src/qc_api/config.py:35-39`, `:57-62` | O `hide_input_in_errors` só vale para `str()` e `repr()`. Medido: `ValidationError.errors()` e `.json()` trazem a URL inteira em `input`. Nenhum código de produção chama isso para o `Settings`: o único `exc.errors()` é o de requisição (`errors.py:80`), que já tira o `input`, e a subida registra só o `str()`. | Nenhuma. Se um dia alguém registrar esse erro, usar `errors(include_input=False)`. |

### Outros caminhos procurados para a senha

| Caminho | Resultado |
|---|---|
| Subida real em `uvicorn`, com `log_level=debug`, `LOG_LEVEL=DEBUG` e as 4 **M** | Código 3, cita `DATABASE_URL`, sem sentinela e sem nenhuma consulta de DNS |
| Mensagem do parser, que repete trecho da string (medido: `unexpected spaces found in "<trecho>"`) | Nunca chega à saída: `is_safe_conninfo` e os `main` a descartam, e `_effective_ports` retorna `[]` |
| Pontos de conexão de produção (`git grep`) | Só `create_pool`, `migrate._connect` e `register_device.store_key`. Os três passam pela recusa. `create_pool` só é chamado em `main.py:64`, com o `Settings` já validado |
| Encadeamento de exceções | A recusa acontece fora de `except`. Medido no `Settings`: sem `__cause__` nem `__context__`. O CA-09 cobre o `__cause__` no `migrate.py` |
| Porta 6543 com URL mal formada | Mensagem constante, sem a URL (CA-08 e CA-09) |
| Logs do `psycopg` e do `psycopg_pool` | Trazem `host`, `port` e `hostaddr`, nunca a conninfo. O `LOG_LEVEL` só muda o logger `qc_api`, então o `DEBUG` deles não aparece |
| Log da API (`health.py`, `middleware.py`, `alerts.py`) | Só a classe da exceção nos erros de banco. Sem mudança no diff |
| Entrada estranha: caractere nulo, surrogate, espaço inicial, esquema `postgresql+psycopg` | Recusada, sem exceção |
| Conexão direta fora das três entradas | Só o comando do plano, já registrado no SEC-43-B2 (Parte B) |

**Regressão:** uma URL bem formada continua subindo, com `/health` em 503, e sem a senha no log (CA-07). Os formatos com pooler na porta 6543 e com `?sslmode=require` são aceitos (CA-05).

### Demais itens da Parte A

- **DEP-01:** é só no cliente, e nenhum limite do servidor muda. As repetições depois de um timeout são seguras pela R-05 (CA-04, com banco, passa nesta revisão).
- **E2E-02:** o `is_loopback` só recebe `EDGE_HOST` já validado como IPv4 (`edge/src/qc_edge/config.py:231`), e o aviso novo é constante. Com `EDGE_HOST` específico, a borda deixa de detectar e oferecer IPs da LAN. O limite do RV-04 falha fechado: o console responde 403, sem expor o token.
- **OBS-01 e E2E-01:** o aviso novo é genérico e não mostra detalhe interno. A coluna `Origem` e o selo (R-06) continuam.
- **R-03 no diff:** a busca nas linhas adicionadas não achou segredo. Os testes montam as credenciais em tempo de execução, e o scanner da SPEC-015 passa. Os literais fictícios do CA-05, na SPEC, são o RV-06.
- **R-07 e R-13:** 23 commits, todos com `Agent:` e com a identidade do projeto. O código de produção é só do developer, e `tests/acceptance/` só do tester.

### Reaprovações (ADR-019)

| Correção | Commit | Classificação | Reaprovação registrada | Conferência de segurança |
|---|---|---|---|---|
| SPEC_ISSUE-01 (CA-08 e CA-09) | `4944e15`, só a SPEC | Exige humano (X-7) | Histórico e aviso do topo da SPEC; `37b6f3b` | ✅ A recusa continua sem conectar e sem mostrar a senha, e só muda a classe do erro na URL com 6543. O código da Parte A veio depois da reaprovação |
| SPEC_ISSUE-02 (§2, §6, §7 e CA-12) | `6a1c203`, a SPEC e o `plan.md` | Exige humano (X-6) | Histórico e aviso do topo da SPEC; `4cc311e` | ✅ Reduz só o resultado visual prometido. Nenhum limite de segurança muda, e a R-06 continua no CA-11, intacto |
| SPEC-039 (DEP-03) | `abe73ae`; registro em `1ed98eb` | Exige humano (X-2, X-3 e X-7) | Histórico e aviso do topo da SPEC-039 | ✅ `true 2` é mais restrito que o texto anterior. Outro contêiner, a falta da `api` ou do `caddy`, ou `false`, continuam sendo falha, e os passos 1 a 3 sobre os segredos não mudam |
| Emenda 2 do ADR-023 | `abe73ae`; registro em `1ed98eb` | Sem delegação (X-2) | Status e Histórico do ADR; SPEC-043 §9, item 4 | ✅ O gatilho sobre os segredos e a rede `internal` com `api` e `caddy` continua. Só a presença do `dashboard`, já aceita na emenda 1, deixa de dispará-lo |

Nenhuma correção foi reaprovada pelo orquestrador sob delegação, e nenhum `SPEC_ISSUE` "exige humano" ficou sem registro. A conferência se apoia nos registros do repositório: não tenho acesso às mensagens do humano.

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação nas rotas; comparação em tempo constante | N/A: nenhuma rota nova nem mudança de autenticação |
| Entradas validadas | ✅ URL recusada antes de conectar nas três entradas, com `fullmatch`. Ver SEC-43-A1 |
| SQL sempre parametrizado | N/A: nenhum SQL novo |
| RLS ligado; `DATABASE_URL` e `service_role` fora de outros lugares | ✅ Sem mudança. O `dashboard` não importa `qc_api` nem recebe a URL |
| CORS | N/A: sem mudança |
| Logs sem segredos e sem imagem | ✅ Ver a tabela de caminhos, SEC-43-A1 e SEC-43-A2 |
| Dependências novas | ✅ Nenhuma |
| Deploy: variáveis, health check, plano free sem cartão | ✅ Nenhum arquivo muda na Parte A. Ver "Pendências humanas" |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma delegada; as quatro têm registro de reaprovação humana |

### Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| Nenhum | — | — | — |

### Como verifiquei

- **Testes em `5fd95ed`:** os cinco `test_spec_043.py`, `test_conninfo.py`, `test_config.py`, `test_register_device.py`, `test_migrate_malformed_url.py` e o scanner de segredos da SPEC-015 (`ca05`), com `CI=true` e o Postgres local: **288 passed, 137 deselected**. `ruff check` limpo. Não repeti a suíte inteira, que está no test-report.
- **Medições próprias:** só com sentinelas fictícias de `secrets.token_hex` e DNS bloqueado por espião, sem rede externa. A varredura combinou 26 separadores em duas posições, em 3 formatos de URL, comparando `host`, `port`, `dbname` e `user` com o esperado. Ela cobre os separadores escolhidos, e não prova a ausência de outra combinação. A guarda de caminhos nega o `Write` fora do repositório, então os scripts rodaram em linha, pelo `Bash`, sem arquivo.
- **Limites respeitados:** não li nenhum `.env*`, não acessei a VPS nem o Coolify, e não executei nada em produção.

### Pendências humanas

- **SPEC §3.3, item 1:** o orquestrador relata, sem o valor, que a senha atual tem só letras e números no Coolify e no `.env.migrate`. Não verifiquei esse fato. Falta a segunda metade do item: se um trecho de uma senha apareceu fora do terminal (chat, print, log compartilhado, relatório), a senha tem de ter sido trocada depois disso.
- **CA-18, passo 1:** é o que confirma que a API sobe com a URL real. Se ela não subir, é `SPEC_ISSUE`, sem afrouxar a regra (SPEC §7).

### SPEC_ISSUE

Nenhum. O SEC-43-A1 está dentro do limite que a §7 declara, e a implementação segue a tabela da §4.2.

### Declaração da Parte A

- [x] Não editei código nem testes; só escrevi esta seção e o cabeçalho deste relatório.
- [x] Não sou autor da Parte A. Sou autor da Parte B (`0bf23bf` e `2ea28a0`), que não avaliei aqui e que tocou só em `docs/deployment-plan.md`, `.env.example` e no dev-report.
