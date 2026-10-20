# SPEC-015 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r1 (depois da retomada do SPEC_ISSUE-01) |
| Revisor de segurança | reviewer (o autor é o security-devops; `reviews/README.md`) |
| Diff revisado | `origin/main...3e20108` (`origin/main` = `e948a06`). O código de produção é o de `aa4af32`; os commits seguintes só trazem relatórios, testes de aceite e status |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. Há **3 achados baixos**, todos nos passos humanos do `deployment-plan.md`, e **3 informativos** de endurecimento. Do ponto de vista de segurança, **nenhum achado desta rodada, e nenhum dos RV-01 a RV-04 da revisão de código, precisa ser corrigido antes da primeira subida na VPS**. Recomendo que o humano leia os SEC-15-01 e SEC-15-02 antes de executar os CAs manuais, porque eles mudam a forma de registrar as saídas.

Pontos centrais confirmados:

- **Só o Caddy fica exposto.** No compose, só o `caddy` tem `ports` (80, 443 e 443/udp), e a `api` e o `dashboard` usam só `expose`. Nenhum serviço tem `network_mode: host`, `privileged`, `pid: host` ou o `docker.sock` montado (CA-29). **Conferi na imagem fixada** do Caddy (`caddy:2.11.7@sha256:685ae3…`), com o `infra/Caddyfile` real e o mesmo endurecimento do compose (`--cap-drop ALL --cap-add NET_BIND_SERVICE`, `no-new-privileges`), lendo o `/proc/net/tcp` do contêiner: o endpoint de administração do Caddy escuta **só em `127.0.0.1:2019`**, dentro do namespace do próprio contêiner. A imagem não define `CADDY_ADMIN`, e o compose também não. A `api` e o `dashboard`, na mesma rede `partqc`, não alcançam a API de administração, então um processo comprometido num deles não reconfigura o proxy. As portas 80 e 443 são as únicas outras em escuta. O contêiner e a imagem que criei foram removidos.
- **Rotas, Host e TLS.** O site é exatamente `{$PUBLIC_HOST}`. Sem bloco global, não há `on_demand_tls`, `tls internal` nem CA de staging. Um `Host` diferente recebe uma resposta vazia do próprio Caddy, sem chegar à API (exploração do tester), e um SNI diferente não tem certificado. `/api/*` vai para a API sem remover o prefixo, e o resto vai para o Streamlit. `/docs` e `/openapi.json` da FastAPI (`api/src/qc_api/main.py:63`) não são alcançáveis pelo Caddy: `/docs` cai no Streamlit, `/api/docs` e `/api/v1/docs` dão 404, e as variantes de travessia de caminho dão 400 (exploração do tester). Os headers são HSTS de 1 ano, sem `includeSubDomains` nem `preload` (o domínio tem outros projetos), e `nosniff`. O redirecionamento de HTTP para HTTPS é o padrão do Caddy, e o Caddy não registra acessos (sem a diretiva `log`).
- **Contêineres:**
  - a `api` e o `dashboard` rodam como `10001:10001`, com `/app` e o `.venv` de dono root e sem escrita para o usuário (CA-37 e extra do tester);
  - os três têm `cap_drop: [ALL]` e `no-new-privileges`, e só o Caddy recebe `NET_BIND_SERVICE`;
  - os limites de memória e CPU por serviço e a rotação de log (`10m` × 3) protegem os outros projetos da VPS.
- **Segredos:**
  - o `DATABASE_URL` e a `READ_API_KEY` chegam só pelo `env_file` (`infra/.env.api` e `infra/.env.dashboard`, com `chmod 600`, ignorados pelo Git e pelo contexto de build). Nenhum `environment` do compose e nenhum `ENV`/`ARG` das imagens tem segredo (CA-28 e CA-29);
  - o dashboard não recebe `DATABASE_URL` nem chave de dispositivo;
  - a CA-36 (executada) e o `find /app -name '.env*'` do tester mostram que só o `.env.example` entra nas imagens, e `.git`, `.claude/` e `notas-locais/` ficam de fora;
  - a armadilha do `docker compose config` sem `--quiet` está documentada, e toda linha do plano com esse subcomando tem `--quiet` (CA-38).
- **Workflows:**
  - **`docker.yml`:** usa `pull_request`, e não `pull_request_target`. Tem `permissions: {contents: read}`, nenhum `secrets.`, nenhum `docker login`/`push`, e o Postgres efêmero com `trust` só no runner. O PR de um fork roda o build sem acesso a segredo nem a token com escrita;
  - **`keepalive.yml`:** tem `permissions: {}`, só `schedule` e `workflow_dispatch` como gatilhos e nenhum gatilho de PR. O secret entra no passo por `env:`, e não interpolado no script, o que evita injeção. O `curl` grava a saída em `/dev/null` e descarta o stderr, e o passo imprime só o código de saída. Assim, nem um erro de DNS leva o host ao log público (teste extra do tester com um `curl` falso).
- **`infra/migrate.py`:**
  - a recusa da 6543 roda antes de qualquer conexão, nas três entradas (`apply_migrations`, `pending_migrations` e CLI), com mensagem constante, sem a URL;
  - o lock é tomado com `pg_try_advisory_lock(%s)` parametrizado e prazo, e o `pg_advisory_unlock` do `finally` continua;
  - a única consulta sem parâmetro é o próprio arquivo de migração, que vem do repositório e roda só na máquina do humano (§7). Não há f-string em SQL. O `_INSERT_APPLIED` é parametrizado;
  - a regex só com dígitos ASCII fecha o truque de nomes com dígitos Unicode;
  - as mensagens com `DETAIL`/`LINE` (SEC-03 da SPEC-003) continuam aceitas, porque as migrações nunca rodam no Actions nem na VPS.
- **Smoke:** a verificação TLS é a padrão, sem `verify=False`. As chamadas à API **não** seguem redirecionamento, então a `X-API-Key` nunca acompanha um 3xx para outro host. As chamadas ao dashboard seguem redirecionamento, mas não levam chave (só o `User-Agent`). Os motivos de falha não trazem URL, host nem chave (CA-12).

## Superfície analisada

- **Proxy e rede:** `infra/Caddyfile`, `infra/compose.yaml` (portas, rede, alias, capacidades, limites, `env_file`, volumes) e a imagem `caddy:2.11.7` fixada por digest, executada localmente com `--network none`.
- **Imagens:** `infra/docker/{api,dashboard}.Dockerfile` e os `.dockerignore` por Dockerfile. Construí as duas imagens localmente (na revisão de código) e inspecionei o usuário, o `HOME` e o conteúdo de `/home/app/.cache`.
- **Configuração do dashboard:** `.streamlit/config.toml` (`showErrorDetails = "none"`; CORS e XSRF nos padrões ligados).
- **Workflows:** `.github/workflows/docker.yml` e `keepalive.yml`, comparados com o `ci.yml`.
- **Reserva:** `infra/render.yaml` (`sync: false`, sem `value` nos segredos; plano `free`).
- **Executor de migrações:** `infra/migrate.py` (§4.7).
- **Smoke:** `scripts/smoke_test.py`.
- **Documentação operacional:** `docs/deployment-plan.md` §3, §4, §6, §7, §8 e §9, e `.env.example`, lidos procurando onde um passo humano pode vazar um segredo, o subdomínio ou o IP.
- **Fora do escopo desta SPEC, sem mudança no diff:** o código da API e do dashboard (SPECs 004, 005, 006, 013, 026 e 028), inclusive a autenticação por chave, o limite de corpo e o CORS. O smoke só confere esses comportamentos em produção.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-15-01 | baixa | privacy (R-13) | `docs/deployment-plan.md:232` e `:393-409` (§9); SPEC §5, CA-13 item 2, CA-17 item 6, CA-43 item 5 | **Saídas dos CAs manuais que contêm o subdomínio real.** O plano manda registrar as saídas "sem o subdomínio real nem o IP", mas não diz quais saídas o trazem. Várias trazem: o `%{redirect_url}` do CA-13, item 2 (`https://<real>/api/v1/health`), o `printenv API_BASE_URL` do CA-17, item 6 (`https://<real>`), o `dig +short` do passo 3 (o IP), e o `docker compose logs caddy` dos passos 7.3 e do CA-43, item 5. O log de ACME do Caddy cita o nome do certificado (`identifiers`), e uma falha de ACME traz o IP. A linha 232 só proíbe colar os logs **da API**. Como o dev-report e o PR são públicos, um copiar e colar sem edição viola a R-13 (o CA-42 pegaria o caso depois, já no histórico do Git). | Não bloqueia nem exige r2. Numa próxima edição do plano (ou numa r2, se houver), acrescentar à §9 uma frase com a lista das saídas que trazem o host ou o IP e trocá-los por `<subdominio>`/`<IP>` antes de colar, e estender a regra da linha 232 aos logs do Caddy. **Até lá, o humano deve editar essas saídas antes de colá-las.** |
| SEC-15-02 | baixa | privacy (R-13) | `docs/deployment-plan.md:408` (CA-42) | **O comando do CA-42 pode dar falso "nenhuma linha".** Ele busca o valor cru de `PUBLIC_HOST` no `infra/.env`. Se o humano escrever o valor entre aspas (`PUBLIC_HOST='…'` ou com aspas duplas, o que o próprio plano recomenda para valores com `$`) ou com espaço no fim, o `git grep -F` procura as aspas também e não acha o subdomínio, mesmo que ele esteja no repositório. O CA-42 é a última barreira da R-13 antes do merge da SPEC. | Não bloqueia. Na execução do CA-42, o humano confere antes que a linha do `infra/.env` não tem aspas nem espaços (a §4, passo 5, item 2, já pede o valor "sem `https://` e sem barra"), ou usa um valor limpo, por exemplo `h=$(sed -n 's/^PUBLIC_HOST=//p' infra/.env \| tr -d "'\" ")`, seguido de `test -n "$h" && git grep -nF -e "$h"`. Fazer o mesmo cuidado com o IPv4. O plano registra isso na próxima edição. |
| SEC-15-03 | baixa | secrets (R-03) | `docs/deployment-plan.md:365-369` (§8, item 1.5) | **A URL de produção da API num arquivo de uso geral.** Para conferir o `statement_timeout` pelo caminho da API, o plano sugere acrescentar a `DATABASE_URL` do modo transaction (com a senha do banco) ao `.env.prod`. Esse arquivo também é carregado, com `--env-file`, nos processos do smoke e do `simulate.py`, que não precisam dela. O arquivo é ignorado pelo Git (`.env.*`), e nenhum dos dois scripts lê ou imprime a variável. Mesmo assim, a senha passa a existir num segundo arquivo local, de vida longa, e no ambiente de processos que não precisam dela. | Não bloqueia. Recomendação para a execução do CA-26: usar um arquivo próprio e temporário (por exemplo, `.env.dbcheck`, também coberto por `.env.*`), apagá-lo depois da conferência e não acrescentar a `DATABASE_URL` ao `.env.prod`. O plano ajusta o exemplo na próxima edição. |
| SEC-15-04 | informativo | deploy | `infra/Caddyfile:7-10` | As respostas levam `server: uvicorn` e `via: 1.1 Caddy` (observado pelo tester), e não há `Referrer-Policy` nem `frame-ancestors`/`X-Frame-Options`. Identificar o software não é segredo, e o dashboard só mostra dados, sem ação de escrita, então o risco de clickjacking é desprezível. A §4.13 não pede esses headers. | Nenhuma nesta SPEC. Se o humano quiser endurecer, uma SPEC futura acrescenta `-Server`, `-Via`, `Referrer-Policy "no-referrer"` e `Content-Security-Policy "frame-ancestors 'self'"`, testada contra o WebSocket do Streamlit. |
| SEC-15-05 | informativo | deploy | `infra/compose.yaml:54-101` | Os contêineres não têm `read_only: true` nem `pids_limit`. Com os limites de memória e CPU, `cap_drop: [ALL]`, `no-new-privileges` e usuário sem escrita em `/app`, um processo comprometido já tem pouca margem. Um `pids_limit` limitaria também um *fork bomb* contra a VPS compartilhada. | Nenhuma nesta SPEC. Fica como candidato para uma SPEC futura de endurecimento: `pids_limit` (por exemplo, 256) e `read_only` com `tmpfs` onde o Streamlit e o Python precisarem escrever. |
| SEC-15-06 | informativo | deps | `.github/workflows/docker.yml:42,44` | As actions estão fixadas por tag (`actions/checkout@v7` e `astral-sh/setup-uv@v10.3.0`), e não por SHA. É o mesmo padrão do `ci.yml`, e o job não tem segredo nem permissão de escrita, então uma tag movida não teria o que roubar além do próprio CI. | Nenhuma. Se a dupla passar a fixar por SHA, fazer nos dois workflows juntos. |

### Classificação de segurança dos achados da revisão de código

| Achado | Severidade de segurança | Corrigir antes da primeira subida na VPS? |
|---|---|---|
| **RV-01** (cache do `uv` nas camadas das imagens) | **Nenhuma** (informativo de disponibilidade). Conferi o conteúdo do `/home/app/.cache/uv`: `archive-v0`, `wheels-v7`, `simple-v27`, `sdists-v10`, `builds-v0` e `interpreter-v4`, ou seja, wheels e metadados de índices **públicos**, de dono root e sem escrita para o usuário `app`. Nenhum arquivo do contexto (`.env*`, dados, `.git`) vai para o cache, porque o contexto já vem filtrado pelo `.dockerignore`. As imagens não vão para registro nenhum (são construídas e usadas só na VPS). O único efeito é cerca de 0,4 GB a mais por geração da imagem do dashboard, no disco compartilhado com os outros projetos. | **Não, por segurança.** A revisão de código recomenda corrigir antes da subida por causa do disco, e eu concordo com isso como boa prática, não como requisito do portão. |
| **RV-02 / T-01** (argparse do smoke repete o argumento desconhecido) | **Baixa** (secrets). Só vaza algo se o humano digitar uma chave numa opção que o smoke não tem. O plano já manda passar as chaves só pelo arquivo de ambiente (§4, passo 11, e §8, item 4). | **Não.** |
| **RV-03 / T-02** (porta `06543` passa pela recusa) | **Baixa** (disponibilidade e integridade do lock). Exige escrever a porta com zero à esquerda. O dano é perder o lock de sessão pelo pooler em modo transaction, num cenário em que só um humano migra. Nenhum segredo vaza: a mensagem traz só `host:port`. | **Não.** |
| **RV-04 / T-03** (`.dockerignore` diferencia maiúsculas) | **Baixa** (privacy). Na VPS, o contexto é um `git clone` mais os três `infra/.env*` em minúsculas. Um `.ENV.API` em maiúsculas não é lido pelo compose. Uma foto `.JPG` commitada por engano já teria saído da LAN pelo GitHub antes de chegar à imagem, e a imagem não sai da VPS. | **Não.** |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ Nenhuma rota nova nem mudança na autenticação da API. O Caddy repassa o `X-API-Key` sem tocá-lo e não cria rota sem chave além das que a API já tem (`/api/v1/health`). Em produção, o 401 sem chave é conferido pelo smoke (`write_requires_key`, `read_requires_key`) e pelo CA-13, item 3 (manual, pendente). |
| Entradas validadas (corpo, tipo de imagem, regex de IDs, `extra="forbid"`) | ✅ / N/A. Nenhum endpoint novo. O smoke valida URL e `SIM_DEVICE_ID` com a regex do contrato antes de qualquer requisição. O executor aceita só nomes `^[0-9]{3}_[a-z0-9_]+\.sql$`. O limite de corpo continua sendo o da API (`MAX_BODY_BYTES`, SPEC-004), e o Caddy não o afrouxa. |
| SQL sempre parametrizado | ✅ `infra/migrate.py`: lock, unlock e `_INSERT_APPLIED` com `%s`. As únicas strings sem parâmetro são constantes ou o arquivo de migração versionado, que roda só na máquina do humano. |
| RLS ligado; `DATABASE_URL` e `service_role` nunca fora da API | ✅ A `DATABASE_URL` da API fica só no `infra/.env.api` (e no painel do Render, se a reserva for ativada). A de migração fica só no `.env.migrate` local. O dashboard não a recebe (compose e CA-29). A `service_role` não aparece em lugar nenhum (CA-05). A conferência do RLS e dos grants em produção é o CA-14 (manual, pendente). Ressalva no SEC-15-03. |
| CORS fechado ou mínimo | ✅ O CORS da API não mudou, e o smoke falha se aparecer `access-control-allow-origin` (CA-10). O Streamlit mantém `enableCORS` e `enableXsrfProtection` ligados (CA-07). |
| Logs sem segredos e sem payloads de imagem | ✅ O Caddy não tem log de acesso. O keep-alive não leva o host ao log público. O log do `psycopg.pool` (host e usuário do pooler, sem senha) é risco aceito e documentado (§7, item 2). O `showErrorDetails = "none"` não expõe o traceback ao navegador. Ressalva no SEC-15-01 (logs do Caddy com o subdomínio). |
| Dependências novas: mantidas, licença compatível, sem CVE crítica | ✅ Nenhum pacote Python novo (`uv.lock` sem mudança). As imagens base e a ferramenta de build são fixadas por tag **e** digest (ver "Dependências novas"). As actions estão fixadas por tag (SEC-15-06). |
| Deploy: variáveis no provedor, health check configurado, plano free sem cartão | ✅ Os segredos ficam nos `env_file` da VPS ou no Render com `sync: false`. Há `HEALTHCHECK` nas duas imagens (o da API é também o keep-alive do Supabase) e `healthCheckPath` no `render.yaml`, com `plan: free`. A confirmação de "sem cartão" e de "VPS preexistente, sem mudança de plano" é o CA-18 (manual, pendente). |
| Reaprovação delegada (ADR-019) em SPEC `security`/`deploy` | ✅ Não houve reaprovação delegada nesta branch. A única correção da SPEC (`758a570`, CA-05, que verifica a R-03) foi classificada como "exige humano (X-7)" e reaprovada **pelo humano** em 2026-10-19 (Histórico). O texto novo não enfraquece a R-03: os padrões de JWT, chave privada e `service_role` ficam sem exceção, o escopo inclui `reviews/` e todas as suítes de teste, e as três regras de permissão só aceitam marcadores, nomes de variável ou cinco credenciais fictícias fixas. Conferi que uma senha real numa URL continua reprovando o CA (exemplo negativo do `test_extra_ca05_scanner_flags_planted_credentials`). |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| Imagem `python` (Debian trixie slim) | `3.12.15-slim-trixie@sha256:a6e34c…` | PSF (Python) + licenças do Debian | Imagem oficial do Docker Hub, mantida, fixada por digest. Atualizar a tag e o digest por PR quando sair um patch (procedimento no `deployment-plan.md` §2). Não rodei scanner de CVE na imagem (sem ferramenta instalada e sem rede de serviço externo nesta sessão). Fica a recomendação de atualizar o patch antes da demo. |
| Binário `uv` (`ghcr.io/astral-sh/uv`) | `0.13.2@sha256:b9fddc…` | MIT / Apache-2.0 | Só é usado no build. Fica na imagem final em `/bin/uv` e `/bin/uvx` (cerca de 43 MB), sem efeito em tempo de execução. |
| Imagem `caddy` | `2.11.7@sha256:685ae3…` | Apache-2.0 | Imagem oficial, mantida, fixada por digest. Roda como root, mitigado por `cap_drop: [ALL]` + `NET_BIND_SERVICE` e `no-new-privileges`. A API de administração fica só em `127.0.0.1:2019` dentro do contêiner (conferido). |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
- [x] O contêiner `partqc-reviewer-caddy` e a imagem do Caddy que baixei para a conferência foram removidos. Nenhum contêiner ou imagem de outro projeto foi tocado.
