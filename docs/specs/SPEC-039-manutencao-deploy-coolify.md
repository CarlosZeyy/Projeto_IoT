# SPEC-039: Manutenção do deploy para o Coolify (compose sem portas publicadas, Caddy como roteador interno e segredos no painel)

| Campo | Valor |
|---|---|
| Status | Blocked |
| Rodada atual | r1 |
| Autor da implementação | security-devops |
| Tags | deploy, security, infra |
| Depende de | ADR-023 `Aceito`; SPEC-015 e SPEC-032 (código mergeado; faltam os CAs manuais, que esperam esta SPEC) |
| Semana alvo | Agora (decisão do humano de 2026-10-25): entra no loop logo que aprovada e vai direto para a `main`, antes dos CAs manuais da SPEC-015 (a `main` atual não sobe na VPS) e antes da Parte B da SPEC-038 |
| Requisitos cobertos | RNF-01, RNF-06, RNF-10, RF-15; R-01, R-02, R-03, R-13, R-14 (R-02 e R-14 pelos contextos de build, CA-13) |
| ADRs relevantes | ADR-023, ADR-018, ADR-008, ADR-006, ADR-016, ADR-019 |

## 1. Contexto

A VPS pessoal é gerenciada pelo Coolify, cujo proxy (Traefik, contêiner `coolify-proxy`) ocupa as portas 80 e 443 e já publica o portfólio do humano. O `infra/compose.yaml` da SPEC-015 publica `80:80`, `443:443` e `443:443/udp` no Caddy, que também obtém o certificado. Nessa VPS, o deploy falha. O **ADR-023** decide:

- publicar pelo Coolify, como recurso "Docker Compose" a partir do repositório público;
- o TLS e o domínio ficam no proxy do Coolify, e nenhum serviço publica portas;
- o Caddy fica só como roteador interno em HTTP, com o Caddyfile embutido numa imagem;
- os segredos ficam nas variáveis do recurso no painel.

Esta SPEC muda o código que o ADR exige. Ela não reescreve a SPEC-015, que está mergeada: os requisitos abaixo substituem os trechos indicados da SPEC-015 (§4.12, §4.13) e da SPEC-032 (§4.4, só no Caddy). As fontes do Coolify, com a data de consulta, ficam no ADR-023.

Arquitetura: `docs/architecture.md` §1 (hospedagem), §2 (`infra/`), §8 (nuvem na VPS) e §9 (ameaças da VPS), todos anotados "a partir da SPEC-039".

Como na SPEC-015 e na SPEC-032, o autor é o `security-devops`, e o portão de segurança é feito pelo **reviewer** (`reviews/README.md`). Os agentes não têm acesso à VPS nem ao Coolify: os CAs manuais (§5) são do humano.

## 2. Objetivo

O mesmo commit da `main` sobe na VPS como recurso Docker Compose do Coolify:

- nenhuma porta publicada pelo PartQC;
- `https://<subdominio>` servido pelo proxy do Coolify até o Caddy interno, que mantém as rotas, o bloqueio de `/docs` e os headers;
- os segredos só nas variáveis do Coolify, nunca no Git, num arquivo editado à mão ou numa imagem (R-03);
- cada merge na `main` publicado automaticamente pelo webhook do Coolify, com o segredo do webhook fora do Git.

## 3. Escopo

### 3.1 Dentro

- `infra/compose.yaml` (§4.1).
- `infra/Caddyfile` (§4.2).
- `infra/docker/caddy.Dockerfile` e `infra/docker/caddy.Dockerfile.dockerignore`, novos (§4.3).
- `.env.example`: o bloco `infra/.env` e o comentário do bloco do dashboard (§4.4).
- `docs/deployment-plan.md`: conferir e completar o passo a passo do Coolify, já reescrito pelo architect com o ADR-023, com as versões e as datas (§4.5).
- Testes do autor em `infra/tests/` (fora de `acceptance/`), inclusive os de marcador `docker` (SPEC-015 §4.14). O autor ajusta os próprios testes das SPECs 015, 032 e 038 que exigem o compose ou o Caddyfile antigos (`infra/tests/test_deploy_files.py`, `infra/tests/test_docker_images.py` e os demais).
- **Tester:** `infra/tests/acceptance/test_spec_039.py`.

**Testes de aceite de SPECs anteriores** (`docs/architecture.md` §10, aplicação explícita). Os requisitos da §4 invalidam as asserções abaixo. O tester as ajusta só no que o requisito citado muda, sem mudar a intenção do CA antigo, e registra cada ajuste na tabela do test-report:

| Arquivo | Teste | O que muda | Requisito |
|---|---|---|---|
| `infra/tests/acceptance/test_spec_015.py` | `test_ca29_compose_structure` | sem `ports` no `caddy`; `caddy` com `build` (sem `image`), sem `environment`, sem `volumes` e com `expose: ["80"]`; sem rede `partqc`, sem alias e sem volumes no topo; `env_file` dá lugar ao `environment` da §4.1, itens 6 e 7; o resto (proibições, limites, endurecimento, `restart`, `logging`) continua | §4.1 |
| `infra/tests/acceptance/test_spec_015.py` | `test_extra_compose_network_is_bridge_and_no_extra_capabilities` | sem a parte da rede; a parte das capacidades continua | §4.1, item 4 |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca30_caddyfile` | o único endereço de site é `:80` (não `{$PUBLIC_HOST}`); as demais condições continuam | §4.2 |
| `infra/tests/acceptance/test_spec_015.py` | fixture `compose_copy`, `test_ca33_compose_config_resolves`, `test_extra_compose_single_quoted_dollar_is_literal` | as variáveis vão todas no `infra/.env` da cópia (sem `.env.api` e `.env.dashboard`); sem alias do `caddy`; a ausência de `DATABASE_URL` no `infra/.env` substitui a ausência do `infra/.env.api` | §4.1, itens 6 e 7 |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca34_caddy_adapt` | a imagem passa a ser a construída de `infra/docker/caddy.Dockerfile` (ou a do `FROM` dela, com o Caddyfile montado); sem `match.host` | §4.2, §4.3 |
| `infra/tests/acceptance/test_spec_015.py` | `test_ca39_env_example`, `test_extra_env_example_matches_compose_defaults` | o texto do bloco `infra/.env`; as linhas de variáveis continuam | §4.4 |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca04_caddyfile_headers` | as condições do CA-30 da SPEC-015 com o endereço `:80` | §4.2 |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca05_caddy_adapt_headers`, `test_extra_caddy_adapt_single_header_handler_is_deferred`, `test_extra_headers_through_reverse_proxy` | a origem da imagem do Caddy (§4.3) e o endereço `:80` (sem `PUBLIC_HOST`) | §4.2, §4.3 |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca06_compose_hardening`, `test_extra_compose_tmpfs_mount_points_are_exact` | o `caddy` passa a ter `tmpfs` também em `/data` e `/config`, com `size=16m` | §4.1, item 5 |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_compose_keeps_caddy_volumes_writable`, `test_extra_caddy_with_compose_capabilities_writes_only_volumes` | são testes extras cujo único objeto são os volumes `caddy_data`/`caddy_config`, que saem: podem ser removidos ou trocados pela escrita em `/data` e `/config` no `tmpfs` | §4.1, item 5 |
| `infra/tests/acceptance/test_spec_032.py` | fixture `compose_copy`, `test_ca06_compose_config_quiet`, `test_extra_compose_config_resolves_pids_and_override` | as variáveis num único `infra/.env` | §4.1 |
| `infra/tests/acceptance/test_spec_032.py` | `test_ca08_caddy_runs_read_only` | a imagem da §4.3 e `tmpfs` em `/data` e `/config` no lugar dos volumes temporários | §4.1, §4.3 |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_env_example_pids_variables_in_the_infra_block` | o título do bloco (§4.4), que continua começando com `# ----------` e contendo `infra/.env` | §4.4 |

Se outro teste de aceite antigo falhar por causa de um requisito desta SPEC, vale a mesma regra.

### 3.2 Fora

- Configurar o recurso no Coolify, o domínio, as variáveis e o deploy: passos humanos, descritos no `docs/deployment-plan.md` §4 e verificados pelos CAs manuais desta SPEC e da SPEC-015.
- **`handle_errors` do Caddy (Parte B da SPEC-038, §4.9):** continua na SPEC-038, que entra depois desta e escreve o bloco dentro do site `:80` (nota no topo da SPEC-038). Esta SPEC não muda o comportamento do 502.
- O webhook do deploy automático é configurado pelo humano no painel do Coolify e no GitHub (§4.8, CA-18). Nenhum arquivo do repositório o referencia. Continuam proibidos o Actions entrando na VPS, um token da API do Coolify nos Secrets e o registro de imagens (ADR-023, decisão 5).
- Mudanças no proxy do Coolify, nas configurações do servidor no Coolify, no firewall ou no Docker da VPS: fora (ADR-023, decisão 6).
- Código da API e do dashboard: nenhuma mudança. A recusa de `http://` da SPEC-028 continua.
- `infra/render.yaml`, os Dockerfiles da API e do dashboard, os `.dockerignore` deles, os workflows e o `infra/migrate.py`: sem mudança. A §4.6 só confere que os `.dockerignore` cobrem o `.env` que o Coolify grava.
- As variáveis da SPEC-017 (alertas) **já entram aqui** (§4.1, item 6), por decisão do humano de 2026-10-25. Fica fora o texto do `deployment-plan.md` sobre como ligar os alertas (bot, `chat_id`, CA-13 da 017), ajustado quando a SPEC-017 for mergeada.
- Rate limit no Caddy ou no Traefik, CSP completa e publicação do `/docs`: continuam fora (SPEC-015 §3.2, SPEC-032 §3.2).

## 4. Requisitos detalhados

### 4.1 `infra/compose.yaml`

Substitui a SPEC-015 §4.12, itens 2, 3, 5, 6, 7 e 8, e a tabela dos arquivos da VPS. Os demais itens da §4.12 e a SPEC-032 §4.4 continuam, salvo onde este item diz o contrário.

1. **Projeto e serviços:** `name: partqc` continua (vale na execução local; no Coolify, o `--project-name <uuid>` prevalece). Os serviços continuam exatamente `caddy`, `api` e `dashboard`, sem `container_name`.
2. **Portas:** **nenhum** serviço tem `ports`. O `caddy` tem `expose: ["80"]`, a `api` tem `expose: ["8000"]` e o `dashboard` tem `expose: ["8501"]`. Continuam proibidos `network_mode`, `privileged`, `pid` e volumes com `docker.sock`.
3. **Labels:** nenhum serviço declara `labels` com chave que comece com `traefik.` ou `coolify.`. O Coolify gera as dele, e o compose não as escreve.
4. **Rede:** sem a chave `networks` no topo e nos serviços. Os três usam a rede padrão do projeto. O alias `${PUBLIC_HOST}` sai: o dashboard resolve a URL pública pelo DNS e volta à VPS pelo proxy do Coolify (ADR-023, decisão 4).
5. **`caddy`:**
   - `build: {context: .., dockerfile: infra/docker/caddy.Dockerfile}`, sem `image`;
   - sem `environment`, sem `env_file`, sem `volumes` e sem `healthcheck`. Um healthcheck faria o Traefik tirar o Caddy da rota quando ficasse `unhealthy` (ADR-023, decisão 2);
   - `tmpfs` com exatamente `/tmp:size=64m`, `/data:size=16m` e `/config:size=16m`. Sem certificados, o Caddy não guarda estado, e o `tmpfs` também evita os volumes anônimos do `VOLUME /data` e `VOLUME /config` da imagem oficial;
   - `read_only: true`, `cap_drop: [ALL]`, `cap_add: [NET_BIND_SERVICE]`, `security_opt`, `restart`, `logging`, `mem_limit`, `cpus` e `pids_limit` como hoje;
   - `depends_on: [api, dashboard]`, sem `condition`.
6. **`api`:** `build` como hoje, sem `env_file` e com `environment` exatamente igual a:

   ```yaml
   DATABASE_URL: "${DATABASE_URL:?}"
   READ_API_KEY: "${READ_API_KEY:?}"
   MAX_BODY_BYTES: "${MAX_BODY_BYTES:-262144}"
   LOG_LEVEL: "${LOG_LEVEL:-INFO}"
   ALERTS_ENABLED: "${ALERTS_ENABLED:-false}"
   TELEGRAM_BOT_TOKEN: "${TELEGRAM_BOT_TOKEN:-}"
   TELEGRAM_CHAT_ID: "${TELEGRAM_CHAT_ID:-}"
   ALERTS_LOT_IDLE_MINUTES: "${ALERTS_LOT_IDLE_MINUTES:-10}"
   ALERTS_LOOKBACK_HOURS: "${ALERTS_LOOKBACK_HOURS:-24}"
   ALERTS_CHECK_INTERVAL_S: "${ALERTS_CHECK_INTERVAL_S:-60}"
   ALERTS_MAX_PER_HOUR: "${ALERTS_MAX_PER_HOUR:-10}"
   ALERTS_INCLUDE_SIMULATED: "${ALERTS_INCLUDE_SIMULATED:-false}"
   ```

   - Os padrões de `MAX_BODY_BYTES` e `LOG_LEVEL` são os do código (`qc_api.config`).
   - As 8 variáveis de alertas são as da SPEC-017 §4.6, com os mesmos padrões. Com `ALERTS_ENABLED=false`, os alertas ficam desligados, e as duas variáveis do Telegram vazias não são validadas. Assim, a SPEC-017, já implementada noutra branch, não precisa mudar o compose (decisão do humano de 2026-10-25).
   - Antes do merge da SPEC-017, a API ignora essas variáveis (`extra="ignore"` em `qc_api.config`).
   - Se a implementação da 017 usar outro nome ou outro padrão, o autor para e registra `SPEC_ISSUE`.
   - `TELEGRAM_BOT_TOKEN` é segredo: quando preenchida no painel, fica só em runtime, Locked e Literal, como `DATABASE_URL`.
7. **`dashboard`:** `build` como hoje, sem `env_file` e com `environment` exatamente igual a:

   ```yaml
   API_BASE_URL: "https://${PUBLIC_HOST:?}"
   READ_API_KEY: "${READ_API_KEY:?}"
   MODEL_METRICS_PATH: "${MODEL_METRICS_PATH:-}"
   ```

   O dashboard não recebe `DATABASE_URL` (SPEC-028 §4.6).
8. **Segredos (R-03):** nenhum valor de `environment` é literal. Os únicos valores permitidos são os das listas dos itens 6 e 7. `DATABASE_URL` e `READ_API_KEY` usam a forma obrigatória `${NOME:?}`, sem valor padrão nem mensagem. No Coolify, essas referências criam as variáveis do recurso, e o `:?` bloqueia o deploy se faltarem (ADR-023, Contexto).
9. **Volumes:** sem a chave `volumes` no topo (`caddy_data` e `caddy_config` saem).
10. **Comentários:** o cabeçalho do arquivo explica o uso no Coolify (Base Directory `/infra`, Docker Compose Location `/compose.yaml`, domínio só no `caddy`, variáveis no painel) e a conferência local com `config --quiet`. Sem URL de documentação do Coolify nem nenhum outro domínio no arquivo: o `test_extra_no_real_host_hints_in_deploy_files` da SPEC-015 só aceita os domínios da lista dele.

**Arquivos de ambiente:** nenhum na VPS. Localmente, a conferência usa um `infra/.env` (ignorado pelo Git e pelo contexto de build) com valores fictícios de todas as variáveis acima.

### 4.2 `infra/Caddyfile`

Substitui a SPEC-015 §4.13, primeiro item:

- **Endereço:** o único endereço de site é exatamente `:80`, sem nome de host, sem `{$PUBLIC_HOST}` e sem `http://`. Sem bloco de opções globais. Sem nome de host e escutando só a porta HTTP, o Caddy não ativa o HTTPS automático (ADR-023, Contexto).
- **Sem mudança:**
  - o bloco `header` com as 6 linhas da SPEC-032 §4.3;
  - `handle /api/* { reverse_proxy api:8000 }` e `handle { reverse_proxy dashboard:8501 }`;
  - nenhuma rota para `/docs` nem `/openapi.json`;
  - sem `handle_path`, `tls`, `acme_ca`, `local_certs`, `log`, `includeSubDomains`, `preload` e domínio ou IPv4 literal.
- **Proibido:** `auto_https`, `trusted_proxies` e `bind`. O primeiro é desnecessário com `:80`, e os outros dois mudariam o comportamento sem requisito.
- Os comentários do arquivo dizem que o TLS e o domínio são do proxy do Coolify (ADR-023), que o Caddy só recebe HTTP dele na rede do recurso e que o `handle_errors` entra pela SPEC-038.
- O arquivo continua formatado por `caddy fmt`.

### 4.3 Imagem do Caddy: `infra/docker/caddy.Dockerfile` e `.dockerignore`

- `infra/docker/caddy.Dockerfile`, nesta ordem e com nada além disto (comentários permitidos):
  1. um único `FROM caddy:2.11.7@sha256:685ae3d7c34d9b5f8caeddc5d14051db7bbd88ff1f5a2fa0c16bd8ca328fb7af`, a mesma imagem fixada hoje no compose. Atualizá-la segue a linha "Imagens base" do `deployment-plan.md` §2;
  2. `COPY infra/Caddyfile /etc/caddy/Caddyfile`;
  3. `LABEL partqc.component="caddy"`.

  Sem `RUN`, `USER`, `ENV`, `ARG`, `EXPOSE`, `HEALTHCHECK`, `ENTRYPOINT` e `CMD`: valem os da imagem oficial (`caddy run --config /etc/caddy/Caddyfile --adapter caddyfile`). O `LABEL` faz o `docker image prune -f --filter label=partqc.component` da atualização cobrir também as imagens do Caddy.
- `infra/docker/caddy.Dockerfile.dockerignore`, com exatamente duas linhas não comentadas, nesta ordem: `*` e `!infra/Caddyfile`. Só o Caddyfile entra no contexto: nem o `.env` gravado pelo Coolify (§4.6), nem fotos, nem `.git`.
- O contexto de build é a raiz do repositório (`context: ..`), como nos outros dois serviços.

### 4.4 `.env.example`

- O título do bloco `# ---------- infra/.env (VPS, infra/compose.yaml) ----------` passa a ser `# ---------- Coolify (variáveis do recurso) e infra/.env (conferência local) ----------`.
- O comentário do bloco passa a dizer, no lugar do texto sobre os três arquivos da VPS:
  - na VPS, estas variáveis, as do bloco `qc-api` (`DATABASE_URL` do pooler em modo transaction, `READ_API_KEY` e os opcionais `MAX_BODY_BYTES` e `LOG_LEVEL`), as opcionais de alertas `ALERTS_*` e `TELEGRAM_*` (desligadas por padrão, SPEC-017) e o `MODEL_METRICS_PATH` opcional ficam nas **variáveis do recurso no Coolify**, com os segredos só em runtime, Locked e Literal, e nunca num arquivo criado à mão;
  - `API_BASE_URL` não é variável: o compose a monta a partir de `PUBLIC_HOST`;
  - localmente, um `infra/.env` com valores fictícios de todas elas serve só para `docker compose -f infra/compose.yaml config --quiet`.
- As linhas `PUBLIC_HOST=<subdominio>`, os limites e os `*_PIDS_LIMIT` continuam iguais. A frase "rode \"up -d\"" do comentário dos `*_PIDS_LIMIT` passa a dizer "ajuste a variável no Coolify e faça Redeploy".
- No bloco `qc-dashboard`, a frase "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vão no infra/.env.dashboard, e API_BASE_URL vem do infra/compose.yaml" passa a dizer "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vêm das variáveis do recurso no Coolify, e API_BASE_URL vem do infra/compose.yaml". As linhas acima de `API_BASE_URL=` continuam citando `.streamlit/secrets.toml` (CA-11 da SPEC-028).
- O arquivo não cita mais `infra/.env.api` nem `infra/.env.dashboard`.

### 4.5 `docs/deployment-plan.md`

O architect reescreveu o plano para o Coolify junto com o ADR-023 (estrutura e passos). O autor:

- confere cada comando contra o compose e o Caddyfile desta SPEC;
- completa a linha "Coolify" da §2 com a versão informada pelo humano e a data;
- confere de novo as fontes que fixar, atualizando "Verificado em";
- mantém as frases que os testes das SPECs 015 e 032 exigem (`test_ca25_*`, `test_ca27_*`, `test_ca38_*`, `test_extra_deployment_plan_documents_limits_and_diagnosis` e os do autor).

O plano tem de conter (CA-07):

- os nomes da interface `Base Directory`, `Docker Compose Location`, `Domains`, `Environment Variables`, `Preserve repository`, `Raw`, `Connect to predefined network`, `Manual Git Webhooks`, `Deploy on push` e `Just the push event`, com a instrução de cada um;
- o seletor `com.docker.compose.project=<uuid>` nos comandos da VPS;
- `coolify-proxy` só em frases de proibição ou de conferência sem alteração.

### 4.6 `.env` do Coolify fora das imagens (R-03)

O Coolify grava o `.env` com as variáveis de runtime no diretório de trabalho do recurso. Com Base Directory `/infra`, ele fica em `infra/.env`, dentro do contexto de build (`context: ..`). O `**/.env*` dos `.dockerignore` da API e do dashboard (SPEC-015 §4.11) e o `*` do Caddy (§4.3) o excluem. Nenhum dos três arquivos perde essas linhas, e o CA-13 confere com uma sentinela nesse caminho.

### 4.7 Equivalência dos comandos dos CAs manuais da SPEC-032 (CA-09) no Coolify

O CA-09 da SPEC-032 foi escrito com `docker compose -f infra/compose.yaml`. No Coolify, ele é executado com os mesmos passos e a mesma intenção, trocando só os comandos:

| Passo do CA-09 | Comando na VPS com o Coolify |
|---|---|
| 1 (`ps`) | `docker ps --filter label=com.docker.compose.project=<uuid> --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'`: 3 contêineres `Up`, a `api` e o `dashboard` `(healthy)` e nenhuma porta publicada |
| 2 (`curl -sI`) | igual |
| 3 (CA-17 da SPEC-015, passos 1 a 3) | igual (o CA-17 já está na forma do Coolify) |
| 4 (`docker stats --no-stream`) | `docker stats --no-stream $(docker ps -q --filter label=com.docker.compose.project=<uuid>)` |
| 5 (registro) | igual |

O `<uuid>` é o UUID do recurso no Coolify (está na URL da página do recurso no painel), e não vai para o repositório.

### 4.8 Deploy automático por webhook (decisão do humano de 2026-10-25; ADR-023, decisão 5)

Passo humano. O autor escreve o roteiro no `deployment-plan.md` §4 (passo 7A) e na "Atualização" (fontes com data no ADR-023):

1. **Coolify:** **Webhooks > Manual Git Webhooks**, seção GitHub:
   - em **Webhook secret**, um segredo de pelo menos 16 caracteres (o gerador do painel, ou `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`), salvo com **Save changes**;
   - copiar a URL GitHub mostrada ali.
2. **GitHub:** no repositório, **Settings > Webhooks > Add webhook**, com:
   - Payload URL igual à URL copiada e content type `application/json`;
   - o mesmo segredo em Secret e **Enable SSL verification** ligado;
   - **Just the push event** e **Active**.
3. **Recurso:**
   - **Advanced > Deployment > Auto deploy = Deploy on push (webhooks)**, com a branch `main`;
   - sem Watch Paths (ADR-023, decisão 5).
4. **Segredo (R-03):** só no campo do Coolify e no webhook do GitHub. Nunca no Git, nos Secrets do Actions, em issue, PR, print ou log. A URL do webhook (endereço do painel do Coolify) também não entra no repositório (R-13). Se o segredo vazar, troca-se nos dois lugares na mesma sessão.
5. **Processo:**
   - a `main` fica sempre publicável: o merge, feito pelo portão da R-09, é o deploy;
   - depois de cada merge, quem mergeou confere no painel o deploy disparado pelo webhook (o commit do merge) e roda o smoke;
   - se o deploy falhar ou o smoke reprovar, vale o rollback por branch (`deployment-plan.md` §6), e a correção vem por PR;
   - variável obrigatória nova no compose só é mergeada depois de criada no painel;
   - nenhum merge na véspera nem no dia da apresentação.

O CA-07 confere o roteiro no plano, e o CA-18 confere o webhook na prática.

## 5. Critérios de aceite

Os CAs marcados `docker` rodam só com `PARTQC_DOCKER_TESTS=1` (SPEC-015 §4.14), com contextos e cópias temporárias (`copy_tracked_tree`), nunca a árvore real. O host fictício é `partqc.example.org`. As credenciais fictícias são montadas em tempo de execução (`reviews/checklist.md` §4), e as chaves são geradas com `secrets.token_urlsafe`.

### Automatizados

- **CA-01 (§4.1)** — *Dado* `infra/compose.yaml` carregado com `yaml.safe_load`, *então*:
  - `name == "partqc"`, e os serviços são exatamente `{"caddy", "api", "dashboard"}`;
  - nenhum serviço tem `ports`, `container_name`, `network_mode`, `privileged`, `pid`, `networks` ou `env_file`;
  - `expose` é `["80"]`, `["8000"]` e `["8501"]`, respectivamente;
  - nenhum serviço tem `labels` com chave (ou item `chave=valor`) que comece com `traefik.` ou `coolify.`;
  - o topo não tem `networks` nem `volumes`;
  - `caddy.build == {"context": "..", "dockerfile": "infra/docker/caddy.Dockerfile"}`, e o `caddy` não tem `image`, `environment`, `volumes` nem `healthcheck`;
  - `caddy.tmpfs == ["/tmp:size=64m", "/data:size=16m", "/config:size=16m"]`, e `caddy.depends_on` cita `api` e `dashboard` sem `condition`;
  - `api.build` e `dashboard.build` são os de hoje (`infra/docker/api.Dockerfile` e `infra/docker/dashboard.Dockerfile`, contexto `..`).
- **CA-02 (R-03, §4.1)** — *Dado* o mesmo arquivo, *então*:
  - `api.environment` é exatamente o dicionário do item 6, e `dashboard.environment` é exatamente o do item 7;
  - o `caddy` não tem `environment`;
  - nenhum `environment` tem a chave `DATABASE_URL` fora da `api`;
  - todo valor de `environment` casa `^(https://)?\$\{[A-Z_]+(:\?|:-[^}]*)\}$`;
  - os valores de `DATABASE_URL` e `READ_API_KEY` são exatamente `${DATABASE_URL:?}` e `${READ_API_KEY:?}`.
- **CA-03 (§4.1, SPEC-015 §4.12 item 4, SPEC-032 §4.4)** — *Dado* o mesmo arquivo, *então*:
  - em todos os serviços: `restart == "unless-stopped"`, `"no-new-privileges:true"` em `security_opt`, o `logging` da SPEC-015, `read_only is True`, `mem_limit`, `cpus` e `pids_limit` iguais às strings das SPECs 015 e 032, e `cap_drop == ["ALL"]`;
  - só o `caddy` tem `cap_add`, igual a `["NET_BIND_SERVICE"]`;
  - `api.tmpfs == dashboard.tmpfs == ["/tmp:size=64m"]`.
- **CA-04 (§4.2, R-13)** — *Dado* `infra/Caddyfile` como texto, sem as linhas de comentário, *então*:
  - o único endereço de site é `:80` (a única linha de abertura de bloco no nível zero é `:80 {`), sem bloco global;
  - não aparecem `PUBLIC_HOST`, `http://`, `https://`, `tls`, `auto_https`, `trusted_proxies`, `bind`, `acme_ca`, `local_certs`, `handle_path`, `log`, `includeSubDomains`, `preload`, `/docs` nem `openapi`;
  - aparecem `handle /api/*` com `reverse_proxy api:8000` e um `handle` sem matcher com `reverse_proxy dashboard:8501`;
  - aparecem as 6 linhas de header do CA-04 da SPEC-032;
  - nenhum token casa a regex de domínio nem a de IPv4 do CA-30 da SPEC-015.
- **CA-05 (§4.3)** — *Dado* `infra/docker/caddy.Dockerfile` lido como instruções (continuações juntadas, comentários fora), *então*:
  - as instruções são exatamente, nesta ordem, `FROM caddy:2.11.7@sha256:685ae3d7c34d9b5f8caeddc5d14051db7bbd88ff1f5a2fa0c16bd8ca328fb7af`, `COPY infra/Caddyfile /etc/caddy/Caddyfile` e `LABEL partqc.component="caddy"`.

  *Dado* `infra/docker/caddy.Dockerfile.dockerignore`, *então* as linhas não vazias e não comentadas são exatamente `["*", "!infra/Caddyfile"]`. E o compose não contém a string `caddy:2.` (a versão do Caddy só existe no Dockerfile).
- **CA-06 (§4.4)** — *Dado* `.env.example`, *então*:
  - existe a linha de título do item 1 da §4.4;
  - o bloco que ela abre (até a próxima linha que começa com `# ----------`) contém `Coolify`, `Locked`, `Literal`, `ALERTS_` e `config --quiet`, as linhas `PUBLIC_HOST=<subdominio>`, os 6 limites e os 3 `*_PIDS_LIMIT=256`;
  - o arquivo não contém `infra/.env.api`, `infra/.env.dashboard` nem `rode "up -d"`;
  - as condições do CA-39 da SPEC-015 e do CA-05 da SPEC-015 sobre o `.env.example` continuam valendo.
- **CA-07 (§4.5)** — *Dado* `docs/deployment-plan.md`, *então*:
  - ele contém `Base Directory`, `` `/infra` ``, `Docker Compose Location`, `` `/compose.yaml` ``, `https://<subdominio>:80`, `Environment Variables`, `Locked`, `Literal`, `Preserve repository`, `Connect to predefined network`, `com.docker.compose.project=<uuid>`, `Manual Git Webhooks`, `Deploy on push`, `Just the push event` e `Enable SSL verification`;
  - toda linha que contém `Webhook secret` ou `segredo do webhook` contém também `Coolify` ou `GitHub`, e nenhuma linha do arquivo contém `secrets.` seguido de um nome com `WEBHOOK` (o segredo nunca vai para os Secrets do Actions);
  - toda linha que contém `coolify-proxy` e uma das palavras `restart`, `reinici`, `stop`, `parar` ou `editar` contém também `Nunca` ou `nunca`;
  - toda linha que contém `Raw` contém também `Nunca`, `nunca` ou `não`;
  - as condições dos CAs 25, 27, 38 e 41 da SPEC-015 continuam valendo.
- **CA-08 (docker, §4.1, R-03)** — *Dado* uma cópia temporária do repositório com `infra/.env` contendo `PUBLIC_HOST=partqc.example.org`, uma `DATABASE_URL` fictícia (`postgresql://<user>:<password>@db.example.org:6543/postgres`, montada no teste) e uma `READ_API_KEY` gerada, e um ambiente de processo sem essas variáveis nem as de limite, *quando* se roda `docker compose -f <cópia>/infra/compose.yaml config --format json`, *então*:
  - o código é 0;
  - `services.dashboard.environment.API_BASE_URL == "https://partqc.example.org"`;
  - `services.api.environment.DATABASE_URL` é a URL fictícia, e `READ_API_KEY` é igual na `api` e no `dashboard`;
  - `MAX_BODY_BYTES == "262144"`, `LOG_LEVEL == "INFO"` e `MODEL_METRICS_PATH == ""`;
  - na `api`, `ALERTS_ENABLED == "false"`, `TELEGRAM_BOT_TOKEN == ""`, `TELEGRAM_CHAT_ID == ""`, `ALERTS_LOT_IDLE_MINUTES == "10"`, `ALERTS_LOOKBACK_HOURS == "24"`, `ALERTS_CHECK_INTERVAL_S == "60"`, `ALERTS_MAX_PER_HOUR == "10"` e `ALERTS_INCLUDE_SIMULATED == "false"`; nenhuma variável `ALERTS_*` ou `TELEGRAM_*` aparece no `dashboard` nem no `caddy`;
  - nenhum serviço resolvido tem `ports`;
  - o `mem_limit` da `api` corresponde a 512 MiB.

  *Dado* o mesmo `infra/.env` sem `PUBLIC_HOST`, sem `DATABASE_URL` ou sem `READ_API_KEY` (um caso por variável), *então* o código é diferente de 0, o stderr contém o nome da variável que falta, e o stderr não contém o valor da `READ_API_KEY` nem a senha fictícia.
- **CA-09 (docker, §4.1; invocação do Coolify)** — *Dado* a mesma cópia **sem** `infra/.env` e um arquivo `coolify.env` fora da cópia com as três variáveis do CA-08, *quando* se roda `docker compose --env-file <coolify.env> --project-name partqc-coolify-test --project-directory <cópia>/infra -f <cópia>/infra/compose.yaml config --format json` (a forma que o Coolify usa, ADR-023), *então*:
  - o código é 0 e `name == "partqc-coolify-test"`;
  - para `api`, `dashboard` e `caddy`, `build.context` é o caminho absoluto da raiz da cópia, e `build.dockerfile` termina com `infra/docker/<serviço>.Dockerfile`;
  - `services.dashboard.environment.API_BASE_URL == "https://partqc.example.org"`.
- **CA-10 (docker, §4.2)** — *Dado* a imagem construída de `infra/docker/caddy.Dockerfile` (fixture `build_image`), *quando* se roda nela `caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile` com `--network none` e sem `PUBLIC_HOST` no ambiente, *então*:
  - o código é 0 e o stderr não tem aviso de formatação;
  - `apps.http.servers` tem exatamente 1 servidor, com `listen == [":80"]`, e `apps` não tem a chave `tls`;
  - nenhum `match` em nenhuma profundidade tem `host`;
  - os handlers `reverse_proxy` são exatamente 2: um com `upstreams == [{"dial": "api:8000"}]`, numa rota com `path == ["/api/*"]`, e outro com `upstreams == [{"dial": "dashboard:8501"}]`, numa rota sem matcher de `path`;
  - o handler `headers` define os 4 headers e apaga `Server` e `Via` (CA-05 da SPEC-032).
- **CA-11 (docker, §4.3)** — *Dado* a imagem do CA-10, *então*:
  - `docker run --rm --entrypoint cat <imagem> /etc/caddy/Caddyfile` devolve exatamente os bytes de `infra/Caddyfile` da cópia;
  - `docker image inspect` mostra `Config.Labels["partqc.component"] == "caddy"`, `Config.Healthcheck` ausente ou nulo, e `Config.Cmd` igual ao da imagem do `FROM` (inspecionada no mesmo teste).
- **CA-12 (docker, §4.1, §4.2)** — *Dado* uma rede Docker do teste com:
  - a imagem da `api` (SPEC-015, `build_image`) com o nome de rede `api`, uma `DATABASE_URL` fictícia inalcançável e uma `READ_API_KEY` gerada;
  - a do `dashboard` com o nome `dashboard`, `API_BASE_URL=https://partqc.example.org` e a mesma chave;
  - a do Caddy (CA-10) com o nome `caddy`, executada com as opções do compose: `--read-only`, os 3 `tmpfs` da §4.1 item 5, `--cap-drop ALL`, `--cap-add NET_BIND_SERVICE`, `--security-opt no-new-privileges`, `--pids-limit 256`, sem `-p` e sem volume;

  *quando*, depois de o `dashboard` ficar `healthy` (até 90 s), se fazem requisições HTTP/1.1 a `http://caddy:80` com `Host: partqc.example.org`, a partir de um contêiner na mesma rede, *então*:
  - `GET /api/v1/health` responde 200 ou 503, com corpo JSON que tem a chave `status`;
  - `GET /_stcore/health` responde 200 com o corpo `ok`;
  - essas duas respostas têm `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `Content-Security-Policy: frame-ancestors 'self'`, e nenhuma tem `Server` nem `Via`;
  - o corpo de `GET /docs` não contém `swagger` (sem diferenciar maiúsculas), e o de `GET /openapi.json` não contém `"openapi"`;
  - uma conexão TCP a `caddy:443` é recusada;
  - o log do Caddy não contém `read-only file system`, e o contêiner continua `running`.
- **CA-13 (docker, R-03, §4.6)** — *Dado* contextos montados com `build_image(..., extra_files=...)` com as sentinelas `infra/.env` e `.env`, as duas contendo `DATABASE_URL=` seguido de um marcador gerado no teste, *quando* se constroem as imagens da `api`, do `dashboard` e do Caddy, *então*:
  - na `api` e no `dashboard`, `test -e /app/infra/.env` e `test -e /app/.env` falham, e `grep -rl <marcador> /app` não imprime nada;
  - no Caddy, `find / -xdev -name '.env*'` não imprime nada e `test -e /app` falha;
  - o CA-36 da SPEC-015 continua valendo.

### Manuais (humano, na VPS e no painel do Coolify)

Antes de colar qualquer saída, troque o subdomínio por `<subdominio>`, o IP por `<IP>` e o UUID do recurso por `<uuid>` (R-13; `docs/deployment-plan.md` §9).

- **CA-14 (manual)** — Conferência antes do primeiro deploy:
  1. no painel do Coolify, registrar a versão (rodapé ou Settings) no `deployment-plan.md` §2;
  2. `docker ps --filter name=coolify-proxy --format '{{.Image}} {{.Ports}}'` mostra uma imagem `traefik` com as portas 80 e 443 publicadas;
  3. `docker inspect -f '{{.State.StartedAt}}' coolify-proxy` é anotado (fora do repositório) para o CA-40 da SPEC-015.
- **CA-15 (manual; ADR-023, itens 1 e 6 do Contexto)** — Recurso e primeiro deploy, pelos passos 4 a 7 do `deployment-plan.md` §4:
  1. o recurso foi criado como **Public Repository**, com a URL HTTPS do repositório, branch `main`, build pack **Docker Compose**, Base Directory `/infra` e Docker Compose Location `/compose.yaml`;
  2. em Advanced, o modo de deploy do compose **não** é Raw, e "Connect to predefined network" e "Preserve repository during deployment" estão desligados. O primeiro deploy é pelo botão **Deploy**; o webhook é configurado depois e conferido no CA-18;
  3. em Domains, só o serviço `caddy` tem domínio, igual a `https://<subdominio>:80`;
  4. o deploy termina com sucesso, e o log mostra o build das três imagens. O humano lê o log no painel e confirma que nenhum valor de segredo aparece; se aparecer, não colar o log em lugar nenhum e registrar `SPEC_ISSUE`;
  5. `docker ps --filter label=com.docker.compose.project=<uuid> --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'` mostra 3 contêineres `Up`, com a `api` e o `dashboard` `(healthy)`, e a coluna de portas sem nenhum `0.0.0.0:` nem `[::]:`.

  Se o passo 4 falhar no build por causa do `context: ..`, parar e registrar `SPEC_ISSUE` com a linha do erro (ADR-023, "Quando revisitar").
- **CA-16 (manual; ADR-023, item 2 do Contexto)** — O Coolify preserva o endurecimento. Para cada contêiner do passo 5 do CA-15, `docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.CapAdd}} {{.HostConfig.SecurityOpt}} {{json .HostConfig.Tmpfs}} {{json .HostConfig.PortBindings}} {{.HostConfig.RestartPolicy.Name}}' <contêiner>` mostra, com os padrões:
  - `api`: `536870912 1000000000 256 true [ALL]`, sem `CapAdd`, com `no-new-privileges:true`, `/tmp` com `size=64m`, `PortBindings` vazio (`{}` ou `null`) e `unless-stopped`;
  - `dashboard`: o mesmo, com `1073741824` de memória;
  - `caddy`: `268435456 500000000 256 true [ALL] [NET_BIND_SERVICE]`, `no-new-privileges:true`, `/tmp` (`size=64m`), `/data` e `/config` (`size=16m`), `PortBindings` vazio e `unless-stopped`.

  Se o humano tiver mudado algum limite no painel, vale o valor dele. Um item diferente do esperado sem mudança no painel → `SPEC_ISSUE` com a saída.
- **CA-17 (manual, R-03; ADR-023, item 5 do Contexto)** — Segredos:
  1. no painel, `DATABASE_URL` e `READ_API_KEY` estão com o build desligado (só runtime), **Locked** e **Literal**;
  2. para cada imagem dos 3 contêineres, `docker history --no-trunc <imagem> | grep -c -e DATABASE_URL -e READ_API_KEY` → `0`;
  3. `docker exec <contêiner da api> find /app -maxdepth 2 -name '.env*'` e o mesmo no `dashboard` → nenhuma linha, ou só `/app/.env.example` (o CA-43, passo 1, da SPEC-015);
  4. `sudo find /data/coolify/applications/<uuid> -maxdepth 2 -name .env -exec stat -c '%a %U:%G %n' {} \;` → registrar os modos e donos no `deployment-plan.md` §7, item 7, sem o caminho completo. Se algum modo permitir leitura a "outros" (último dígito diferente de 0), registrar isso no mesmo item e avisar o humano. Não mudar a permissão à mão, porque o Coolify reescreve o arquivo a cada deploy.
- **CA-18 (manual, R-03; §4.8)** — Deploy automático por webhook:
  1. com o webhook configurado pela §4.8 e o Auto deploy em **Deploy on push (webhooks)**, mergear na `main` um PR de teste pelo portão da R-09 (por exemplo, o PR que registra os CAs 14 a 17 no `deployment-plan.md`);
  2. em até 5 min, a lista de deploys do recurso mostra um deploy novo disparado pelo webhook, com o commit do merge. Em **Settings > Webhooks > Recent Deliveries** do GitHub, a entrega `push` desse commit tem resposta 2xx;
  3. os commits da branch do PR, enviados antes do merge, não geraram nenhum deploy (só a `main` dispara);
  4. o deploy termina com sucesso, a listagem do CA-15 (passo 5) mostra os 3 contêineres `Up`, com a `api` e o `dashboard` `(healthy)`, e o smoke (CA-15 da SPEC-015) dá 8 × `PASS`;
  5. no log desse deploy, uma busca no navegador pelos 8 primeiros caracteres do segredo do webhook, da `DATABASE_URL` (a parte da senha), da `READ_API_KEY` e, se preenchida, da `TELEGRAM_BOT_TOKEN` → 0 ocorrências. Se houver alguma, não copiar o log, trocar o segredo afetado e registrar `SPEC_ISSUE`;
  6. `git grep -n -i "webhook"` no checkout local mostra só documentação: nenhuma linha com uma URL do painel do Coolify nem com um valor de segredo (o CA-42 da SPEC-015 confere o host do painel, se o humano o informar como mais um valor);
  7. registrar no dev-report e no `deployment-plan.md` §9 o resultado, o SHA curto do commit e a data, sem a URL do webhook nem o UUID.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Compose como YAML; Caddyfile e Dockerfile como texto; `.dockerignore`; `.env.example` e plano como texto; `config` local e na forma do Coolify (docker); `adapt`, imagem e execução do Caddy (docker); ajustes nos próprios testes das SPECs 015, 032 e 038 | `infra/tests/` |
| Aceite (tester) | CA-01 a CA-13 (CA-08 a CA-13 marcados `docker`) e os ajustes da tabela da §3.1 | `infra/tests/acceptance/test_spec_039.py` |
| Manual (humano) | CA-14 a CA-18 e, depois deles, os CAs manuais da SPEC-015 e o CA-09 da SPEC-032 (§4.7) | VPS, painel do Coolify e GitHub; registro no dev-report e no `deployment-plan.md` §9 |

- Nenhum teste usa a VPS, o Coolify, o DNS, o Supabase ou a rede externa. As imagens base vêm do Docker Hub e do GHCR no build, como na SPEC-015.
- Os testes `docker` seguem a SPEC-015 §4.14: contextos em `tmp_path`, imagens removidas no fim da sessão. Um test-report com os testes `docker` só pulados não vale como PASS desses CAs.
- O CA-12 não mocka nada dentro da rede do teste: a API responde 503 sem banco, o que basta para conferir o caminho Caddy → API.

## 7. Riscos e notas para o implementador

- **Dashboard → API sem o alias:** o contêiner do dashboard resolve `<subdominio>` pelo DNS público e volta à VPS pelo `coolify-proxy` (hairpin). Se o CA-17 da SPEC-015 mostrar "API acordando" com a API saudável, parar e registrar `SPEC_ISSUE`. A alternativa, que exige decisão, é um `extra_hosts: ["${PUBLIC_HOST}:host-gateway"]` no `dashboard`. Nunca trocar a URL por `http://api:8000`: a SPEC-028 recusa `http://` fora do loopback.
- **Healthcheck no Caddy:** não acrescente nenhum. Com o Traefik, um contêiner `unhealthy` sai da rota, e o site inteiro cairia (ADR-023).
- **`X-Forwarded-*`:** o Caddy recebe HTTP do Traefik e, sem `trusted_proxies`, repassa `X-Forwarded-Proto: http` às origens. A API não monta URLs absolutas, e o Streamlit continua com `enableCORS` e `enableXsrfProtection` padrão (SPEC-015 §4.4). Se o painel quebrar por XSRF ou WebSocket no CA-17 da SPEC-015, parar e registrar `SPEC_ISSUE`; nunca desligar essas proteções.
- **`tmpfs` em `/data` e `/config`:** o Caddy grava ali o `instance.uuid` e o `autosave.json`. Com 16m, sobra muito. Se o log mostrar falta de espaço, registre `SPEC_ISSUE` com a linha, em vez de aumentar por conta própria.
- **Sem `PUBLIC_HOST` no Caddy:** o site `:80` aceita qualquer `Host`. Só o `coolify-proxy` (pela regra `Host(...)` que o Coolify gera) e os contêineres da rede do recurso alcançam o Caddy, que não tem porta publicada.
- **Domínios em comentários:** nada de `coolify.io`, `sslip.io` ou outro domínio nos arquivos de `infra/` (o `test_extra_no_real_host_hints_in_deploy_files` da SPEC-015 recusa). As fontes ficam no ADR-023 e no `deployment-plan.md`.
- **Variáveis com padrão:** o Coolify cria no painel as variáveis com `${NOME:-padrão}`, com o padrão do arquivo (ADR-023, Contexto). Se o humano apagar o valor no painel, o compose usa o padrão.
- **Deploy automático:** o merge desta SPEC na `main` já dispara o deploy, se o webhook existir. Na primeira publicação, o webhook é configurado só depois do CA-15 (primeiro deploy pelo botão), para que um deploy falho não aconteça antes de as variáveis estarem no painel. Uma mudança futura que torne obrigatória uma variável nova (`${NOME:?}`) bloqueia o deploy automático até o humano criá-la no painel.
- **Ordem com a SPEC-038:** a Parte B da 038 escreve o `handle_errors` dentro do bloco `:80` deste Caddyfile. Esta SPEC precisa estar mergeada antes de a 038 entrar em `In Dev`.
- Nunca rode `docker compose down -v`, `prune` amplo, nem mexa no `ufw` ou no `coolify-proxy` (ADR-023, decisão 6).

## 8. Definição de pronto

- [ ] CA-01 a CA-13 com teste de aceite passando (test-report PASS, com os testes `docker` executados), e os ajustes da §3.1 na tabela do test-report
- [ ] review-report APPROVED + o portão de segurança feito pelo reviewer (autor `security-devops`)
- [ ] CI verde (`ci` e `docker`); `ruff` limpo
- [ ] `.env.example` e `docs/deployment-plan.md` atualizados
- [ ] CA-14 a CA-18 (manuais) registrados no dev-report e no `deployment-plan.md` §9. Eles só podem ser feitos depois do merge, como na SPEC-015 e na SPEC-032; até lá, a SPEC fica `In Security`
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-25 | SPEC criada (`Draft`). Decisões do architect, com o ADR-023 (`Proposto`): (a) nenhum serviço com `ports`, nenhuma label `traefik.*`/`coolify.*`, sem a rede própria e sem o alias; (b) Caddy em `:80`, sem TLS e sem healthcheck, com `tmpfs` em `/data` e `/config` no lugar dos volumes; (c) Caddyfile embutido numa imagem própria (`caddy.Dockerfile`, contexto só com o Caddyfile), em vez de bind com "Preserve repository"; (d) segredos por `${NOME:?}` no `environment`, sem `env_file`, e os opcionais com o padrão do código; (e) Base Directory `/infra` e Docker Compose Location `/compose.yaml`, com o CA-09 simulando a invocação do Coolify; (f) o `handle_errors` continua na SPEC-038; (g) equivalência dos comandos do CA-09 da SPEC-032 (§4.7). | Fato novo do humano em 2026-10-25: a VPS é gerenciada pelo Coolify, cujo proxy ocupa 80/443 | Orquestrador, a pedido do humano |
| 2026-10-25 | Decisões do humano sobre o PR #55: (1) opção A do ADR-023 aprovada (Caddy como roteador interno); (2) **deploy automático por webhook** a cada merge na `main`: §3.2 ajustada, §4.8 nova (webhook manual com segredo só no Coolify e no GitHub, sem Watch Paths, processo com a `main` sempre publicável e rollback por branch), CA-07 com os nomes da interface do webhook, CA-15 com o primeiro deploy pelo botão, **CA-18 novo** (manual: um merge de teste dispara o deploy, só a `main` dispara, e o log não mostra segredos); (3) as 8 variáveis de alertas da SPEC-017 (`ALERTS_*`, `TELEGRAM_*`), com os padrões dela (alertas desligados), entram já no `environment` da `api` (§4.1, item 6; CA-08); o `.env.example` as cita no comentário, e o texto do plano sobre os alertas fica para o merge da 017; (4) o `handle_errors` fica na SPEC-038, e esta SPEC entra agora, direto na `main` (Semana alvo). Fontes novas no ADR-023 (consultadas em 2026-10-25). A SPEC continua `Draft` até a aprovação formal. | Decisão do humano | Humano (Carlos) |
| 2026-10-25 | Aprovada pelo humano (`Draft` → `Ready`) com o ADR-023: Caddy como roteador interno, deploy automático por webhook, variáveis da SPEC-017 opcionais no compose (nomes e padrões conferidos contra o código da 017), o 502 com headers fica na SPEC-038; entra agora, direto na `main`. | Resposta do humano de 2026-10-25 (PR #55) | Orquestrador, a pedido do humano |
