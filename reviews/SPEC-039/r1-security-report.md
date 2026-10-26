# SPEC-039 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r1 |
| Revisor de segurança | reviewer (o autor é o security-devops, `reviews/README.md`) |
| Diff revisado | `origin/main...0fa823b` (base de merge `ff60d34`, igual à `origin/main`) |
| **Veredicto** | **FAIL** |

Um achado **alto** (SEC-39-01), que é um `SPEC_ISSUE`. O autor implementou a SPEC fielmente: o problema é uma premissa da SPEC e do ADR-023 que o código do Coolify desmente. Para corrigir, o humano (ou o architect, com a aprovação dele) precisa decidir, e por isso o portão não pode passar nesta rodada. Os outros quatro achados são baixos e não bloqueiam.

## Superfície analisada

- **Arquivos do diff:**
  - `infra/compose.yaml`, `infra/Caddyfile`, `infra/docker/caddy.Dockerfile` e `caddy.Dockerfile.dockerignore`;
  - `.env.example` e `docs/deployment-plan.md` (§2, §3, §4 e passo 7A, §6, §7 e §9);
  - os testes do autor e do tester em `infra/tests/`.
- **Fora do diff, conferidos por serem afetados:**
  - `infra/docker/api.Dockerfile`, `dashboard.Dockerfile` e os `.dockerignore` deles (contexto `..`, `COPY . /app`);
  - `.github/workflows/` (nenhuma menção a `coolify` nem a `webhook`).
- **Código do Coolify:** para conferir as premissas da SPEC sobre o que ele faz com o compose, li o código-fonte público (`coollabsio/coolify`, branch `v4.x`, baixado em 2026-10-25 só para leitura, sem acesso à VPS nem ao painel): `app/Jobs/ApplicationDeploymentJob.php` e `bootstrap/helpers/parsers.php`.
- **Verificações que executei:**
  - `uv run ruff check .`: limpo;
  - `uv run pytest -q infra/tests` sem banco: 444 passed e 369 skipped;
  - `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests/acceptance/test_spec_039.py`: 21 passed, sem nenhum contêiner, rede ou imagem `partqc-test*` sobrando (os `partqc-pg*` são preexistentes e não foram tocados);
  - busca de segredos no diff (URLs com senha, `ghp_`, `eyJ`, `sk-`, IPv4, UUID, caminho de webhook): só asserções negativas e valores fictícios montados em tempo de execução;
  - uma simulação local, numa cópia temporária já apagada, com valores fictícios gerados na hora, do que o Coolify faz no compose (detalhes no SEC-39-01).

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-39-01 | **alta** (`SPEC_ISSUE`) | secrets, deploy | `infra/compose.yaml:30` (`caddy`) e `:101` (`dashboard`); SPEC-039 §4.1 item 7 (linha 127), CA-02 (linha 245), §7 (linha 367); ADR-023, decisão 3 | **No Coolify, todo serviço do recurso recebe todas as variáveis de runtime, inclusive `DATABASE_URL`.** A SPEC e o ADR-023 supõem que o `environment` de cada serviço delimita o que ele recebe ("o compose referencia cada segredo como `${NOME:?}` no `environment` do serviço que o usa"; "O dashboard não recebe `DATABASE_URL` (SPEC-028 §4.6)"). O código do Coolify faz outra coisa, fora do modo Raw, que o ADR-023 proíbe:<br>1. `ApplicationDeploymentJob.php`, `deploy_docker_compose_buildpack` (linhas 833 a 839): "Always add .env file to services", com `$service['env_file'] = ['.env']` em **todos** os serviços, sem opção para desligar. O `applicationParser` (`parsers.php`, linhas 2289 a 2297) faz o mesmo ("Auto-inject .env file so Coolify environment variables are available inside containers");<br>2. `generate_runtime_environment_variables` (linhas 1738 a 1830) e `save_runtime_environment_variables` grava nesse `.env` **todas** as variáveis do recurso marcadas como runtime: `DATABASE_URL`, `READ_API_KEY`, `TELEGRAM_BOT_TOKEN` (quando preenchida), `PUBLIC_HOST` e os limites, além de `COOLIFY_*`, `SERVICE_*` e `HOST=0.0.0.0`.<br>Simulei isso localmente: acrescentei `env_file: [.env]` aos três serviços de uma cópia do compose e rodei `docker compose config`. A chave `DATABASE_URL` aparece no `environment` resolvido da `api`, do `dashboard` **e do `caddy`**, e a `READ_API_KEY` também no `caddy`.<br>**Consequência em produção:**<br>- o contêiner do Streamlit, que é público, e o do Caddy passam a ter a string de conexão do banco no ambiente;<br>- quem comprometer qualquer um dos dois (RCE, leitura de `/proc/self/environ`, um erro que exponha o ambiente) obtém acesso de escrita ao banco;<br>- é uma regressão de menor privilégio em relação à SPEC-015, em que o `env_file` do dashboard não tinha `DATABASE_URL`;<br>- contraria o item do checklist §6 "`DATABASE_URL` [...] nunca aparece fora da API", a SPEC-028 §4.6 e a intenção do CA-02.<br>**Nenhum CA detecta isso:** os testes não podem (o compose do repositório está correto), e o CA-16 e o CA-17 (manuais) não olham o `Config.Env` dos contêineres.<br>**Armadilha para quem for corrigir:** sobrescrever com `DATABASE_URL: ""` no `environment` do `dashboard` e do `caddy` **não funciona e piora**. O `applicationParser` (`parsers.php`, linhas 2114 a 2122) troca um valor vazio pelo valor salvo da variável de mesmo nome ("allow database override for backward compatibility"), e gravaria o segredo literal no compose gerado, que fica no contexto de build (SEC-39-02). | **Exige decisão do humano** (a SPEC e o ADR-023 precisam mudar, então o caso está fora dos limites do ADR-019). Opções, sem escolher entre elas:<br>(a) **aceitar o risco formalmente:** emenda no ADR-023 (Consequências) e exceção registrada à SPEC-028 §4.6. Nesse caso, a SPEC-039 acrescenta ao CA-17 uma conferência que registre o fato, por exemplo `docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' <contêiner> \| grep -c '^DATABASE_URL='` no `dashboard` e no `caddy`, e o CA-02 deixa de sugerir que o compose limita o ambiente em produção;<br>(b) **entregar o `DATABASE_URL` só à `api` por arquivo**, e não por variável do recurso. Por exemplo, um arquivo de storage do Coolify montado só no serviço `api` e um `DATABASE_URL_FILE` lido pela API. Isso exige SPEC nova, porque muda o código da API e o ADR-023;<br>(c) outra forma que o architect proponha, desde que conferida contra o código do Coolify, e não só contra a documentação.<br>Em qualquer opção, o CA-17 deve conferir o ambiente real de cada contêiner (`Config.Env`, só os nomes, nunca os valores). |
| SEC-39-02 | baixa | privacy (R-13), deploy | `infra/docker/api.Dockerfile.dockerignore` e `dashboard.Dockerfile.dockerignore` (sem exclusão de `infra/`); `ApplicationDeploymentJob.php`, linhas 855 a 859 | Antes do build, o Coolify grava o compose processado por cima de `infra/compose.yaml`, dentro do contexto de build. O `COPY . /app` da `api` e do `dashboard` leva esse arquivo para `/app/infra/compose.yaml` nas duas imagens. Ele contém as labels do Traefik geradas pelo Coolify, com a regra `Host(...)` do subdomínio real, o UUID do recurso e os valores `COOLIFY_*`. Os segredos continuam como referências `${...}`: o parser mantém a referência ("Keep the ${VAR} reference in compose", `parsers.php`, perto da linha 1839), salvo no caso do valor vazio descrito no SEC-39-01. As imagens não saem da VPS, porque não há registro, então o impacto é pequeno. | Numa manutenção futura (por exemplo, a Parte B da SPEC-038), acrescentar aos dois `.dockerignore` a exclusão de `infra/`, mantendo o que a API precisar. A §4.6 só proíbe remover as linhas de `.env`. Até lá, nada a fazer. |
| SEC-39-03 | baixa | secrets, deploy | `docs/deployment-plan.md:207-210` (passo 5, item 3); `ApplicationDeploymentJob.php`, `modify_dockerfiles_for_compose` (linhas 5486 e seguintes) | Com a configuração `inject_build_args_to_dockerfile` ligada, que é o padrão, o Coolify **reescreve os três Dockerfiles** antes do build e injeta um `ARG` para cada variável de build, inclusive as `COOLIFY_*` (com o subdomínio). Na `api` e no `dashboard`, que têm `RUN`, esses valores aparecem no `docker history`. Para os segredos, o plano já manda desligar o build (só runtime), e o CA-17, passo 2, confere o `docker history`. O risco que resta é o subdomínio no histórico de uma imagem local. | Opcional: o plano pode citar essa injeção ao lado do item 3 do passo 5, para que o humano saiba por que o build dos segredos tem de ficar desligado **antes** do primeiro deploy. Uma variável que nasce com o escopo de build ligado e é usada num deploy deixa o valor numa camada de imagem. Se o painel tiver a opção para desligar a injeção, vale avaliar desligá-la. |
| SEC-39-04 | baixa | deploy | `docs/deployment-plan.md:233-240` (passo 7A) | O ADR-023 registra que "a URL do Coolify tem de ser alcançável pela internet" para o webhook, mas o passo 7A não diz o que fazer se o painel hoje **não** for público (atrás de firewall, só por túnel). Expor o painel só para o webhook é uma mudança nas configurações do servidor (ADR-023, decisão 6) e aumenta a superfície de ataque do Coolify inteiro, inclusive a do portfólio. | Uma frase no passo 7A: "se o painel não for alcançável pela internet, não o exponha por causa do PartQC; mantenha o deploy pelo botão e avise o orquestrador". Se o painel já for público, recomendar 2FA na conta do Coolify. |
| SEC-39-05 | baixa | deploy | SPEC-039 §7 (linha 363); ADR-023, decisão 4 | Com o dashboard indo à API pela URL pública, a `READ_API_KEY` passa pela resolução DNS pública e pelo proxy do Coolify. Ela continua protegida por TLS verificado (a SPEC-028 recusa `http://`). Se o DNS do subdomínio passar por um proxy de CDN, a chave sai da VPS até a CDN e volta. Isso fica fora do repositório e não é defeito do diff. | Nada no código. No CA-17 da SPEC-015, o humano anota (fora do repositório) se o DNS do subdomínio é só resolução, sem proxy de CDN. |

## O que muda no modelo de ameaça (resumo)

- **Exposição de rede:** melhora.
  - Nenhum serviço publica porta, e o `:443` do Caddy fica fechado (CA-12).
  - Pelo código do Coolify (`parsers.php`, rede base com o UUID do recurso), os serviços ficam só na rede do recurso, à qual o `coolify-proxy` se liga. Com "Connect to predefined network" desligado (plano, passo 4), os contêineres do portfólio não alcançam `api:8000` nem `dashboard:8501`. A frase da SPEC §7 ("só o `coolify-proxy` e os contêineres da rede do recurso alcançam o Caddy") se confirma.
- **Traefik → Caddy em HTTP:** o tráfego em texto claro fica na bridge local do Docker, no mesmo host, legível só por quem já é `root` na VPS. Aceitável.
  - O site `:80` aceita qualquer `Host`, mas só é alcançável pela rede do recurso.
  - Sem `trusted_proxies`, o Caddy ignora o `X-Forwarded-For` que recebe e repassa o IP do Traefik. A API e o dashboard não usam IP de cliente nem `X-Forwarded-*` para autenticar ou limitar, então nada muda nesse ponto.
  - O HSTS do Caddy chega ao navegador pelo HTTPS do Traefik.
  - As respostas geradas pelo próprio Traefik (redirecionamento HTTP → HTTPS, `No available server`) saem sem os nossos headers, um custo já aceito no ADR-023.
- **Dashboard → API pela URL pública (hairpin):** a chave de leitura trafega sempre com TLS verificado e ganha uma dependência de DNS (SEC-39-05). Mais importante: com a injeção do `.env` (SEC-39-01), a separação "o dashboard só tem a chave de leitura" deixa de valer em produção.
- **Segredos:** saem dos arquivos editados à mão e passam ao banco do Coolify e a um `.env` gravado por ele.
  - O `.env` de runtime é gravado **depois** do build, e o de build fica em `/artifacts`, fora do contexto (`ApplicationDeploymentJob.php`, comentários nas linhas 914 e 933). O `.dockerignore` (CA-13) passa a ser uma defesa em profundidade, e não a única barreira. É um ponto positivo.
  - O ponto negativo é o SEC-39-01.
- **Deploy automático:**
  - um merge na `main` vira deploy, e o portão da R-09 continua sendo o único controle;
  - o webhook é verificado por HMAC com o segredo, e "Just the push event" impede que PRs de forks disparem deploy;
  - nenhum workflow tem acesso à VPS ou ao Coolify, e nenhum arquivo cita a URL do painel ou o segredo;
  - a superfície nova é o endpoint de webhook do painel (SEC-39-04).

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa dela; comparação em tempo constante | ✅ Não se aplica ao diff: nenhuma rota nova ou alterada. `/docs` e `/openapi.json` continuam sem rota (CA-04, CA-10 e CA-12, e um teste extra com as variantes sob `/api/`). |
| Entradas validadas (corpo, imagem, IDs, `extra="forbid"`) | ✅ Não se aplica: nenhum código da API. O `MAX_BODY_BYTES` continua com o padrão do código (262144). |
| SQL sempre parametrizado | ✅ Não se aplica: nenhum SQL no diff. |
| RLS ligado; `DATABASE_URL` e a `service_role` nunca fora da API | ❌ **SEC-39-01.** No repositório, a `DATABASE_URL` só existe no `environment` da `api`, e o CA-02 confere isso. No Coolify, o `env_file: .env` injetado a entrega também ao `dashboard` e ao `caddy`. O RLS não muda. |
| CORS fechado ou mínimo | ✅ Sem mudança. O Streamlit continua com `enableCORS` e `enableXsrfProtection` padrão, e a SPEC §7 manda parar em vez de desligar essas proteções. |
| Logs sem segredos e sem payloads de imagem | ✅ No repositório: o Caddy continua sem log de acesso, e o compose manda nunca rodar `config` sem `--quiet`. O CA-08 confere que o erro do `:?` não ecoa a chave nem a senha. No Coolify: o build e o `.env` rodam com `hidden`/`skip_command_log` no código, e o CA-15 (passo 4) e o CA-18 (passo 5) conferem o log real. |
| Dependências novas | ✅ Nenhuma. O `uv.lock` não mudou, e a imagem `caddy:2.11.7` é a mesma, fixada pelo mesmo digest e agora usada no `FROM`. |
| Deploy: variáveis no provedor, health check, plano free sem cartão | ✅ com ressalva (SEC-39-01). As variáveis ficam no painel, com os segredos só em runtime, Locked e Literal (plano, passo 5), e `:?` bloqueia o deploy se faltar uma obrigatória. A `api` e o `dashboard` mantêm o healthcheck das imagens, e o `caddy` fica sem healthcheck por decisão do ADR-023. Nenhum custo novo (R-01): o Coolify é Apache-2.0, auto-hospedado e já estava na VPS. |
| Reaprovação delegada (ADR-019) dentro de E-1 a E-5, sem X-6/X-7 | ✅ Não houve reaprovação delegada nesta branch. O Histórico da SPEC termina na aprovação humana de 2026-10-25, e os commits do orquestrador (`befe5b5`, `5928f69`, `4bea144`, `0fa823b`) só mudam o status e a rodada. A correção do SEC-39-01 mexe em regra de segredo (R-03) e em permissões, então **não cabe** no ADR-019 (X-6, X-7): exige o humano. |

### Pontos do foco pedido, conferidos um a um

- **Compose:**
  - sem `ports`, sem `labels` (nenhuma `traefik.*` ou `coolify.*`), sem `networks` e sem `volumes`;
  - só `expose` 80/8000/8501;
  - proibições de `network_mode`, `privileged`, `pid` e `docker.sock` mantidas.

  Conferido no arquivo e pelos CA-01, CA-08 e CA-09.
- **Segredos só por `${VAR:?}` e só em runtime:**
  - `DATABASE_URL` e `READ_API_KEY` são exatamente `${NOME:?}`, e nenhum valor literal;
  - nenhum `ARG`, `ENV` de segredo ou build arg nos Dockerfiles;
  - o plano manda desligar o build dos segredos (veja o SEC-39-03 sobre a injeção de `ARG`).
- **`.env` do Coolify fora das imagens:** coberto duas vezes:
  - pelo Coolify, que grava o `.env` de runtime depois do build;
  - pelos `.dockerignore` (`**/.env*` e `**/.[eE][nN][vV]*` na `api` e no `dashboard`, `*` com `!infra/Caddyfile` no Caddy).

  O CA-13 confere com sentinelas.
- **Caddy:**
  - um único site `:80`, sem bloco global, sem `tls`, `auto_https`, `trusted_proxies` nem `bind`;
  - os 6 headers da SPEC-032 mantidos;
  - `/docs` e `/openapi.json` sem rota;
  - `caddy adapt` sem app `tls` e sem `match.host` (CA-10).
- **Endurecimento:** `read_only`, `tmpfs` com tamanho (`/tmp` 64m nos três; `/data` e `/config` 16m no Caddy), `pids_limit` 256, `cap_drop: [ALL]`, `cap_add` só `NET_BIND_SERVICE` no Caddy e `no-new-privileges:true` nos três. Conferido no arquivo e na execução do CA-12. O CA-16 (manual) confere se o Coolify preserva tudo isso. Pelo código do parser, o payload mantém os campos do serviço.
- **Coexistência com o `coolify-proxy` e o portfólio:**
  - toda linha do plano que cita o `coolify-proxy` com reinício, parada ou edição é uma proibição (linha 299: "Nunca reinicie, pare nem edite");
  - as outras linhas só leem (`docker ps`, `docker inspect`);
  - `prune` amplo, `down -v` e `ufw` continuam proibidos;
  - o `docker image prune` do plano é filtrado por `label=partqc.component`, e o Caddy ganhou essa label.
- **Webhook:**
  - o segredo fica só no campo do Coolify e no webhook do GitHub (plano, linhas 109 e 240), com o mínimo de 16 caracteres, `Enable SSL verification` e "Just the push event";
  - nada nos Secrets do Actions, porque nenhum workflow cita `coolify` ou `webhook`;
  - a URL do painel fica fora do repositório. Os testes do autor recusam caminhos `/webhooks/` no plano.
- **R-01:** nenhum serviço, conta ou dependência nova.
- **R-13:** os únicos domínios no diff são fictícios (`*.example.org`), o GitHub e as fontes do Coolify, só no plano. Não há subdomínio real, IP, UUID do recurso nem URL do painel. Todos os commits estão na identidade do projeto.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. A imagem `caddy:2.11.7@sha256:685ae3d7…` já era usada no compose da SPEC-015 e só mudou de lugar (o `FROM` do `caddy.Dockerfile`). O Coolify não é dependência do repositório: é software preexistente na VPS (Apache-2.0). |

## SPEC_ISSUE

- **SEC-39-01:** a SPEC-039 (§4.1 item 7, CA-02 e §7) e o ADR-023 (decisão 3) supõem que, no Coolify, o `environment` de cada serviço delimita as variáveis que ele recebe. O Coolify injeta `env_file: .env` em todos os serviços e grava nesse `.env` todas as variáveis de runtime do recurso, de modo que `dashboard` e `caddy` recebem `DATABASE_URL`. Para resolver, o humano precisa decidir: aceitar o risco com emenda no ADR, ou mudar a forma de entregar o segredo à API. É uma regra de segredo, fora dos limites do ADR-019. Enquanto não for resolvido, o merge fica impedido (R-09).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório. O código do Coolify foi baixado para uma pasta temporária fora do repositório, só para leitura.
- [x] Não sou autor de nenhum commit desta SPEC.
