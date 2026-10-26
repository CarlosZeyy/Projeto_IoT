# SPEC-039: Manutenção do deploy para o Coolify (compose sem portas publicadas, Caddy como roteador interno e segredos no painel)

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r2 |
| Autor da implementação | security-devops |
| Tags | deploy, security, infra |
| Depende de | ADR-023 `Aceito`, com a emenda 1 (dois recursos, SEC-39-01) aceita pelo humano em 2026-10-25; SPEC-015 e SPEC-032 (código mergeado; faltam os CAs manuais, que esperam esta SPEC) |
| Semana alvo | Agora (decisão do humano de 2026-10-25): entra no loop logo que aprovada e vai direto para a `main`, antes dos CAs manuais da SPEC-015 (a `main` atual não sobe na VPS) e antes da Parte B da SPEC-038 |
| Requisitos cobertos | RNF-01, RNF-06, RNF-10, RF-15; R-01, R-02, R-03, R-13, R-14 (R-02 e R-14 pelos contextos de build, CA-13) |
| ADRs relevantes | ADR-023, ADR-018, ADR-008, ADR-006, ADR-016, ADR-019 |

> **Reaprovada pelo humano em 2026-10-25** (correção do SEC-39-01 em 2026-10-25, com a emenda 1 do ADR-023; classificação ADR-019 no Histórico). Com a reaprovação, a SPEC saiu de `Blocked` e voltou ao loop; o status atual é o da tabela acima.

## 1. Contexto

A VPS pessoal é gerenciada pelo Coolify, cujo proxy (Traefik, contêiner `coolify-proxy`) ocupa as portas 80 e 443 e já publica o portfólio do humano. O `infra/compose.yaml` da SPEC-015 publica `80:80`, `443:443` e `443:443/udp` no Caddy, que também obtém o certificado. Nessa VPS, o deploy falha. O **ADR-023** decide:

- publicar pelo Coolify, como **dois** recursos "Docker Compose" a partir do repositório público (emenda 1): `partqc-api`, só com a `api`, e `partqc-web`, com o `caddy` e o `dashboard`;
- o TLS e o domínio ficam no proxy do Coolify, e nenhum serviço publica portas;
- o Caddy fica só como roteador interno em HTTP, com o Caddyfile embutido numa imagem, e chega à `api` pela rede `partqc-api-link`;
- os segredos ficam nas variáveis de cada recurso no painel, divididos de modo que a `DATABASE_URL` e o `TELEGRAM_BOT_TOKEN` só existam no `partqc-api`.

**Por que dois recursos (SEC-39-01).** Fora do modo Raw, o Coolify acrescenta `env_file: ['.env']` a todos os serviços de um recurso e grava nesse `.env` todas as variáveis de runtime do recurso. Num recurso único, o Streamlit público e o Caddy receberiam a `DATABASE_URL`, contra a SPEC-028 §4.6 e o checklist §6. O `environment` de cada serviço só delimita as variáveis na execução local. As fontes (código-fonte do Coolify, `v4.x` e `v4.5.0`, consultado em 2026-10-25) e as opções descartadas estão no ADR-023, emenda 1.

Esta SPEC muda o código que o ADR exige. Ela não reescreve a SPEC-015, que está mergeada: os requisitos abaixo substituem os trechos indicados da SPEC-015 (§4.12, §4.13) e da SPEC-032 (§4.4, só no Caddy). As fontes do Coolify, com a data de consulta, ficam no ADR-023.

Arquitetura: `docs/architecture.md` §1 (hospedagem), §2 (`infra/`), §8 (nuvem na VPS) e §9 (ameaças da VPS), todos anotados "a partir da SPEC-039".

Como na SPEC-015 e na SPEC-032, o autor é o `security-devops`, e o portão de segurança é feito pelo **reviewer** (`reviews/README.md`). Os agentes não têm acesso à VPS nem ao Coolify: os CAs manuais (§5) são do humano.

## 2. Objetivo

O mesmo commit da `main` sobe na VPS como os dois recursos Docker Compose do Coolify (`partqc-api` e `partqc-web`):

- nenhuma porta publicada pelo PartQC;
- `https://<subdominio>` servido pelo proxy do Coolify até o Caddy interno, que mantém as rotas, o bloqueio de `/docs` e os headers;
- os segredos só nas variáveis do Coolify, nunca no Git, num arquivo editado à mão ou numa imagem (R-03);
- a `DATABASE_URL` e o `TELEGRAM_BOT_TOKEN` só no ambiente do contêiner da `api` (SPEC-028 §4.6), conferido no CI pela simulação do Coolify (CA-19) e na VPS pelo `Config.Env` (CA-20);
- cada merge na `main` publicado automaticamente pelo webhook do Coolify, com o segredo do webhook fora do Git.

## 3. Escopo

### 3.1 Dentro

- `infra/compose.yaml` (recurso `partqc-web`) e `infra/compose.api.yaml`, novo (recurso `partqc-api`) (§4.1, §4.1A).
- `infra/Caddyfile` (§4.2).
- `infra/docker/caddy.Dockerfile` e `infra/docker/caddy.Dockerfile.dockerignore`, novos (§4.3).
- `infra/docker/api.Dockerfile.dockerignore` e `infra/docker/dashboard.Dockerfile.dockerignore`: só a linha `infra/` (§4.6, SEC-39-02).
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
| `infra/tests/acceptance/test_spec_015.py` e `test_spec_032.py` | todo teste que lê o serviço `api` de `infra/compose.yaml` ou que roda `config` só nesse arquivo (inclusive os citados acima) | o serviço `api` passa a ser lido de `infra/compose.api.yaml`, e o `config` é feito nos dois arquivos; o `caddy` passa a ter `depends_on: [dashboard]` e `networks: [default, link]`, e a `api`, `networks: [default, link]`; a rede `link` (`partqc-api-link`) substitui a ausência de redes nas asserções; as asserções sobre o `caddy` e o `dashboard` continuam em `infra/compose.yaml` | §4.1, §4.1A |

Se outro teste de aceite antigo falhar por causa de um requisito desta SPEC, vale a mesma regra.

### 3.2 Fora

- Configurar os dois recursos no Coolify, o domínio, as variáveis e o deploy: passos humanos, descritos no `docs/deployment-plan.md` §4 e verificados pelos CAs manuais desta SPEC e da SPEC-015.
- **`handle_errors` do Caddy (Parte B da SPEC-038, §4.9):** continua na SPEC-038, que entra depois desta e escreve o bloco dentro do site `:80` (nota no topo da SPEC-038). Esta SPEC não muda o comportamento do 502.
- O webhook do deploy automático é configurado pelo humano no painel do Coolify e no GitHub (§4.8, CA-18). Nenhum arquivo do repositório o referencia. Continuam proibidos o Actions entrando na VPS, um token da API do Coolify nos Secrets e o registro de imagens (ADR-023, decisão 5).
- Mudanças no proxy do Coolify, nas configurações do servidor no Coolify, no firewall ou no Docker da VPS: fora (ADR-023, decisão 6).
- Código da API e do dashboard: nenhuma mudança (a divisão em dois recursos não exige código; a entrega do segredo por arquivo, opção b do ADR-023, emenda 1, foi descartada). A recusa de `http://` da SPEC-028 continua.
- `infra/render.yaml`, os Dockerfiles da API e do dashboard, os workflows e o `infra/migrate.py`: sem mudança. Os `.dockerignore` da API e do dashboard só ganham a linha `infra/` (§4.6).
- As variáveis da SPEC-017 (alertas) **já entram aqui** (§4.1, item 6), por decisão do humano de 2026-10-25. Fica fora o texto do `deployment-plan.md` sobre como ligar os alertas (bot, `chat_id`, CA-13 da 017), ajustado quando a SPEC-017 for mergeada.
- Rate limit no Caddy ou no Traefik, CSP completa e publicação do `/docs`: continuam fora (SPEC-015 §3.2, SPEC-032 §3.2).

## 4. Requisitos detalhados

### 4.1 `infra/compose.yaml` e `infra/compose.api.yaml`

Substitui a SPEC-015 §4.12, itens 2, 3, 5, 6, 7 e 8, e a tabela dos arquivos da VPS. Os demais itens da §4.12 e a SPEC-032 §4.4 continuam, salvo onde este item diz o contrário. Cada arquivo é um recurso do Coolify (§4.1A).

1. **Projetos e serviços:**
   - `infra/compose.yaml` (recurso `partqc-web`): `name: partqc` continua, e os serviços são exatamente `caddy` e `dashboard`;
   - `infra/compose.api.yaml` (recurso `partqc-api`), novo: `name: partqc-api`, com exatamente o serviço `api`;
   - o `name:` vale na execução local; no Coolify, o `--project-name <uuid>` de cada recurso prevalece. Nenhum serviço tem `container_name`.
2. **Portas:** **nenhum** serviço tem `ports`. O `caddy` tem `expose: ["80"]`, a `api` tem `expose: ["8000"]` e o `dashboard` tem `expose: ["8501"]`. Continuam proibidos `network_mode`, `privileged`, `pid` e volumes com `docker.sock`.
3. **Labels:** nenhum serviço dos dois arquivos declara `labels` com chave que comece com `traefik.` ou `coolify.`. O Coolify gera as dele, e o compose não as escreve.
4. **Redes:** a rede própria `partqc` e o alias `${PUBLIC_HOST}` saem. O dashboard resolve a URL pública pelo DNS e volta à VPS pelo proxy do Coolify (ADR-023, decisão 4). A única rede declarada é a de ligação entre os recursos:
   - `infra/compose.api.yaml`, no topo, exatamente `networks: {link: {name: partqc-api-link, internal: true}}`. O compose do `partqc-api` cria a rede; `internal` impede que ela sirva de saída para fora (a `api` sai para o Supabase pela rede padrão);
   - `infra/compose.yaml`, no topo, exatamente `networks: {link: {name: partqc-api-link, external: true}}`;
   - a `api` e o `caddy` têm `networks: [default, link]`. O `dashboard` não tem a chave `networks` (usa só a padrão). No Coolify, o parser liga todas as redes do topo a todos os serviços do recurso, então o `dashboard` também entra na `link` lá (ADR-023, emenda 1; aceito, §7);
   - o `default` explícito mantém a `api` com saída para a internet e o `caddy` na mesma rede do `dashboard` na execução local.
5. **`caddy`:**
   - `build: {context: .., dockerfile: infra/docker/caddy.Dockerfile}`, sem `image`;
   - sem `environment`, sem `env_file`, sem `volumes` e sem `healthcheck`. Um healthcheck faria o Traefik tirar o Caddy da rota quando ficasse `unhealthy` (ADR-023, decisão 2);
   - `tmpfs` com exatamente `/tmp:size=64m`, `/data:size=16m` e `/config:size=16m`. Sem certificados, o Caddy não guarda estado, e o `tmpfs` também evita os volumes anônimos do `VOLUME /data` e `VOLUME /config` da imagem oficial;
   - `read_only: true`, `cap_drop: [ALL]`, `cap_add: [NET_BIND_SERVICE]`, `security_opt`, `restart`, `logging`, `mem_limit`, `cpus` e `pids_limit` como hoje;
   - `depends_on: [dashboard]`, sem `condition`. A `api` está no outro recurso: sem ela, o Caddy sobe e responde 502 em `/api/*`.
6. **`api`** (em `infra/compose.api.yaml`): `build` como hoje, `networks` do item 4, os mesmos `restart`, `cap_drop`, `security_opt`, limites, `read_only`, `tmpfs` e `logging` de hoje, sem `env_file` e com `environment` exatamente igual a:

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
7. **`dashboard`** (em `infra/compose.yaml`): `build` como hoje, sem `env_file` e com `environment` exatamente igual a:

   ```yaml
   API_BASE_URL: "https://${PUBLIC_HOST:?}"
   READ_API_KEY: "${READ_API_KEY:?}"
   MODEL_METRICS_PATH: "${MODEL_METRICS_PATH:-}"
   ```

   O dashboard não recebe `DATABASE_URL` (SPEC-028 §4.6). No Coolify, isso só vale porque a `api` está noutro recurso (§4.1A).
8. **Segredos (R-03):**
   - nenhum valor de `environment` é literal. Os únicos valores permitidos são os das listas dos itens 6 e 7;
   - `DATABASE_URL` e `READ_API_KEY` usam a forma obrigatória `${NOME:?}`, sem valor padrão nem mensagem. No Coolify, essas referências criam as variáveis do recurso, e o `:?` bloqueia o deploy se faltarem (ADR-023, Contexto);
   - o texto de `infra/compose.yaml`, inclusive os comentários, não contém `DATABASE_URL`, `TELEGRAM_` nem `ALERTS_`. Assim, o Coolify nunca cria essas variáveis no `partqc-web` (ele cria as variáveis a partir das referências do arquivo);
   - o texto de `infra/compose.api.yaml` não contém `PUBLIC_HOST` nem `MODEL_METRICS_PATH`;
   - nenhum serviço tem `NOME: ""` para "apagar" uma variável: no Coolify, o valor vazio é trocado pelo valor salvo (ADR-023, emenda 1).
9. **Volumes:** sem a chave `volumes` no topo dos dois arquivos (`caddy_data` e `caddy_config` saem).
10. **Comentários:** o cabeçalho de cada arquivo explica o uso no Coolify:
    - o nome do recurso, Base Directory `/infra` e a Docker Compose Location (`/compose.yaml` ou `/compose.api.yaml`);
    - o domínio só no `caddy` do `partqc-web`, e o `partqc-api` sem domínio;
    - as variáveis no painel de cada recurso (§4.1A) e a ordem do primeiro deploy (`partqc-api` antes, porque ele cria a rede `partqc-api-link`);
    - a conferência local com `config --quiet` nos dois arquivos.

    Sem URL de documentação do Coolify nem nenhum outro domínio nos arquivos: o `test_extra_no_real_host_hints_in_deploy_files` da SPEC-015 só aceita os domínios da lista dele.

**Arquivos de ambiente:** nenhum na VPS. Localmente, a conferência usa um único `infra/.env` (ignorado pelo Git e pelo contexto de build) com valores fictícios de todas as variáveis acima, lido pelos dois arquivos (os dois ficam em `infra/`).

### 4.1A Isolamento dos segredos entre os recursos (SEC-39-01; ADR-023, emenda 1)

Fora do modo Raw, o Coolify acrescenta `env_file: ['.env']` a todos os serviços de um recurso e grava nesse `.env` todas as variáveis de runtime do recurso. O que limita as variáveis de um contêiner em produção é, portanto, o recurso a que ele pertence. Por isso:

| Variável | `partqc-api` (`infra/compose.api.yaml`) | `partqc-web` (`infra/compose.yaml`) |
|---|---|---|
| `DATABASE_URL` (segredo) | sim | **nunca** |
| `TELEGRAM_BOT_TOKEN` (segredo), `TELEGRAM_CHAT_ID` e os demais `ALERTS_*` | sim | **nunca** |
| `READ_API_KEY` (segredo) | sim | sim, o mesmo valor |
| `MAX_BODY_BYTES`, `LOG_LEVEL`, `API_MEM_LIMIT`, `API_CPUS`, `API_PIDS_LIMIT` | sim | não |
| `PUBLIC_HOST`, `MODEL_METRICS_PATH`, `DASHBOARD_*` e `CADDY_*` | não | sim |

- O `caddy` recebe a `READ_API_KEY` e o `PUBLIC_HOST` pelo `.env` do `partqc-web`. Custo aceito no ADR-023 (emenda 1): o Caddy já recebe essa chave no header de cada requisição do dashboard.
- Os dois recursos ficam com "Connect to predefined network" desligado e fora do modo Raw. A rede `partqc-api-link` é a única ligação entre eles.
- Primeiro deploy, e depois de qualquer limpeza que apague a rede: `partqc-api` antes do `partqc-web`. Sem a rede, o deploy do `partqc-web` falha com a mensagem de rede externa inexistente, e basta fazer o deploy do `partqc-api` e repetir o do `partqc-web`.
- Os segredos ficam só em runtime desde antes do primeiro deploy: com o build ligado, o Coolify injeta a variável como `ARG` nos Dockerfiles (SEC-39-03).

### 4.2 `infra/Caddyfile`

Substitui a SPEC-015 §4.13, primeiro item:

- **Endereço:** o único endereço de site é exatamente `:80`, sem nome de host, sem `{$PUBLIC_HOST}` e sem `http://`. Sem bloco de opções globais. Sem nome de host e escutando só a porta HTTP, o Caddy não ativa o HTTPS automático (ADR-023, Contexto).
- **Sem mudança:**
  - o bloco `header` com as 6 linhas da SPEC-032 §4.3;
  - `handle /api/* { reverse_proxy api:8000 }` e `handle { reverse_proxy dashboard:8501 }`. Com os dois recursos, o nome `api` resolve pela rede `partqc-api-link` (§4.1, item 4), e o Caddyfile não muda por isso;
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
  - na VPS, estas variáveis, as do bloco `qc-api` (`DATABASE_URL` do pooler em modo transaction, `READ_API_KEY` e os opcionais `MAX_BODY_BYTES` e `LOG_LEVEL`), as opcionais de alertas `ALERTS_*` e `TELEGRAM_*` (desligadas por padrão, SPEC-017) e o `MODEL_METRICS_PATH` opcional ficam nas **variáveis dos recursos no Coolify**, com os segredos só em runtime, Locked e Literal, e nunca num arquivo criado à mão;
  - a divisão da §4.1A: `DATABASE_URL`, `ALERTS_*`, `TELEGRAM_*`, `MAX_BODY_BYTES`, `LOG_LEVEL` e os limites `API_*` só no recurso `partqc-api` (`infra/compose.api.yaml`); `PUBLIC_HOST`, `MODEL_METRICS_PATH` e os limites `DASHBOARD_*` e `CADDY_*` só no `partqc-web` (`infra/compose.yaml`); a `READ_API_KEY` nos dois, com o mesmo valor;
  - `API_BASE_URL` não é variável: o compose a monta a partir de `PUBLIC_HOST`;
  - localmente, um `infra/.env` com valores fictícios de todas elas serve só para o `config --quiet` dos dois arquivos (`docker compose -f infra/compose.api.yaml config --quiet` e `docker compose -f infra/compose.yaml config --quiet`).
- As linhas `PUBLIC_HOST=<subdominio>`, os limites e os `*_PIDS_LIMIT` continuam iguais. A frase "rode \"up -d\"" do comentário dos `*_PIDS_LIMIT` passa a dizer "ajuste a variável no Coolify e faça Redeploy".
- No bloco `qc-dashboard`, a frase "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vão no infra/.env.dashboard, e API_BASE_URL vem do infra/compose.yaml" passa a dizer "Na VPS, READ_API_KEY e MODEL_METRICS_PATH vêm das variáveis do recurso partqc-web no Coolify, e API_BASE_URL vem do infra/compose.yaml". As linhas acima de `API_BASE_URL=` continuam citando `.streamlit/secrets.toml` (CA-11 da SPEC-028).
- O arquivo não cita mais `infra/.env.api` nem `infra/.env.dashboard`.

### 4.5 `docs/deployment-plan.md`

O architect reescreveu o plano para o Coolify junto com o ADR-023 (estrutura e passos). O autor:

- confere cada comando contra o compose e o Caddyfile desta SPEC;
- completa a linha "Coolify" da §2 com a versão informada pelo humano e a data;
- confere de novo as fontes que fixar, atualizando "Verificado em";
- mantém as frases que os testes das SPECs 015 e 032 exigem (`test_ca25_*`, `test_ca27_*`, `test_ca38_*`, `test_extra_deployment_plan_documents_limits_and_diagnosis` e os do autor).

O plano tem de conter (CA-07):

- os nomes da interface `Base Directory`, `Docker Compose Location`, `Domains`, `Environment Variables`, `Preserve repository`, `Raw`, `Connect to predefined network`, `Manual Git Webhooks`, `Deploy on push` e `Just the push event`, com a instrução de cada um;
- os dois recursos (`partqc-api`, com `/compose.api.yaml`, e `partqc-web`, com `/compose.yaml`), a tabela de variáveis por recurso da §4.1A, a rede `partqc-api-link` e a ordem do primeiro deploy;
- o seletor `com.docker.compose.project=<uuid>` nos comandos da VPS (o `<uuid>` de cada recurso) e a listagem dos contêineres dos dois recursos por `label=partqc.component`;
- `coolify-proxy` só em frases de proibição ou de conferência sem alteração;
- no passo 5 (variáveis), o motivo de os segredos ficarem só em runtime **antes** do primeiro deploy: com o build ligado, o Coolify injeta cada variável como `ARG` nos Dockerfiles (inclusive as `COOLIFY_*`), e um valor usado num build pode ficar numa camada de imagem (SEC-39-03);
- no passo 7A (webhook), o mesmo segredo nos dois recursos e um único webhook no GitHub, e as duas frases do SEC-39-04: se o painel do Coolify não for alcançável pela internet, ele não é exposto por causa do PartQC (fica o deploy pelo botão, e o humano avisa o orquestrador); se já for público, a conta do Coolify usa 2FA.

### 4.6 `.env` do Coolify fora das imagens (R-03)

O Coolify grava o `.env` com as variáveis de runtime no diretório de trabalho de cada recurso. Com Base Directory `/infra`, ele fica em `infra/.env`, dentro do contexto de build (`context: ..`). O `**/.env*` dos `.dockerignore` da API e do dashboard (SPEC-015 §4.11) e o `*` do Caddy (§4.3) o excluem. Nenhum dos três arquivos perde essas linhas, e o CA-13 confere com uma sentinela nesse caminho.

**`infra/` fora das imagens da API e do dashboard (SEC-39-02).** Antes do build, o Coolify grava o compose processado (com as labels do proxy, a regra `Host(...)` do subdomínio e o UUID do recurso) por cima do arquivo em `infra/`, dentro do contexto. Os `.dockerignore` da API e do dashboard ganham a linha `infra/`, no bloco "Documentação, relatórios e testes", e nada mais muda neles. `infra/` não é membro do workspace (`pyproject.toml`, `members`), e nem a API nem o dashboard leem arquivos de lá. As regras da SPEC-015 §4.11 (nunca excluir `pyproject.toml`, `uv.lock`, `packages/` e os demais) continuam.

### 4.7 Equivalência dos comandos dos CAs manuais da SPEC-032 (CA-09) no Coolify

O CA-09 da SPEC-032 foi escrito com `docker compose -f infra/compose.yaml`. No Coolify, ele é executado com os mesmos passos e a mesma intenção, trocando só os comandos:

| Passo do CA-09 | Comando na VPS com o Coolify |
|---|---|
| 1 (`ps`) | `docker ps --filter label=partqc.component --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'`: 3 contêineres `Up` (os dos dois recursos), a `api` e o `dashboard` `(healthy)` e nenhuma porta publicada |
| 2 (`curl -sI`) | igual |
| 3 (CA-17 da SPEC-015, passos 1 a 3) | igual (o CA-17 já está na forma do Coolify) |
| 4 (`docker stats --no-stream`) | `docker stats --no-stream $(docker ps -q --filter label=partqc.component)` |
| 5 (registro) | igual |

O filtro `label=partqc.component` usa a label das três imagens (o contêiner herda as labels da imagem) e lista os contêineres dos dois recursos de uma vez. Para um recurso só, vale `--filter label=com.docker.compose.project=<uuid>`, em que `<uuid>` é o UUID daquele recurso no Coolify (está na URL da página do recurso no painel) e não vai para o repositório.

**Dois recursos nos textos das SPECs 015, 032 e 038.** Onde os passos humanos e os CAs manuais dessas SPECs dizem "o recurso", "as variáveis do recurso" ou `<uuid>`, valem os dois recursos da §4.1A: a variável fica no recurso da tabela, a listagem é a do passo 1 acima, e o CA-42 da SPEC-015 confere os dois UUIDs (`docs/deployment-plan.md` §9).

### 4.8 Deploy automático por webhook (decisão do humano de 2026-10-25; ADR-023, decisão 5)

Passo humano. O autor escreve o roteiro no `deployment-plan.md` §4 (passo 7A) e na "Atualização" (fontes com data no ADR-023):

1. **Coolify:** **Webhooks > Manual Git Webhooks**, seção GitHub, **nos dois recursos**:
   - em **Webhook secret**, um segredo de pelo menos 16 caracteres (o gerador do painel, ou `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`), salvo com **Save changes**. O **mesmo** valor nos dois recursos: o Coolify confere cada recurso com o próprio segredo, e um segredo diferente geraria um `invalid_signature` a cada entrega (ADR-023, emenda 1);
   - copiar a URL GitHub mostrada ali (é a mesma para os dois recursos; se não for, parar e registrar `SPEC_ISSUE`).
2. **GitHub:** no repositório, **Settings > Webhooks > Add webhook**, com:
   - Payload URL igual à URL copiada e content type `application/json`;
   - o mesmo segredo em Secret e **Enable SSL verification** ligado;
   - **Just the push event** e **Active**;
   - um único webhook para os dois recursos.
3. **Recursos (os dois):**
   - **Advanced > Deployment > Auto deploy = Deploy on push (webhooks)**, com a branch `main`;
   - sem Watch Paths (ADR-023, decisão 5).
4. **Segredo (R-03):** só nos campos do Coolify e no webhook do GitHub. Nunca no Git, nos Secrets do Actions, em issue, PR, print ou log. A URL do webhook (endereço do painel do Coolify) também não entra no repositório (R-13). Se o segredo vazar, troca-se nos dois lugares na mesma sessão.
5. **Processo:**
   - a `main` fica sempre publicável: o merge, feito pelo portão da R-09, é o deploy;
   - depois de cada merge, quem mergeou confere no painel os dois deploys disparados pelo webhook (um por recurso, com o commit do merge) e roda o smoke;
   - se o deploy falhar ou o smoke reprovar, vale o rollback por branch (`deployment-plan.md` §6), e a correção vem por PR;
   - variável obrigatória nova no compose só é mergeada depois de criada no painel, no recurso do arquivo que a referencia;
   - nenhum merge na véspera nem no dia da apresentação.
6. **Painel alcançável pela internet (SEC-39-04):** o webhook exige que o GitHub alcance a URL do painel. Se o painel não for alcançável pela internet hoje, ele **não** é exposto por causa do PartQC (seria mudar o servidor, ADR-023, decisão 6): fica o deploy pelo botão **Deploy**, nos dois recursos, depois de cada merge, e o humano avisa o orquestrador. Se o painel já for público, a conta do Coolify usa 2FA.

O CA-07 confere o roteiro no plano, e o CA-18 confere o webhook na prática.

## 5. Critérios de aceite

Os CAs marcados `docker` rodam só com `PARTQC_DOCKER_TESTS=1` (SPEC-015 §4.14), com contextos e cópias temporárias (`copy_tracked_tree`), nunca a árvore real. O host fictício é `partqc.example.org`. As credenciais fictícias são montadas em tempo de execução (`reviews/checklist.md` §4), e as chaves são geradas com `secrets.token_urlsafe`.

### Automatizados

- **CA-01 (§4.1)** — *Dado* `infra/compose.yaml` e `infra/compose.api.yaml` carregados com `yaml.safe_load`, *então*:
  - em `infra/compose.yaml`, `name == "partqc"` e os serviços são exatamente `{"caddy", "dashboard"}`; em `infra/compose.api.yaml`, `name == "partqc-api"` e os serviços são exatamente `{"api"}`;
  - nenhum serviço tem `ports`, `container_name`, `network_mode`, `privileged`, `pid` ou `env_file`;
  - `expose` é `["80"]` no `caddy`, `["8000"]` na `api` e `["8501"]` no `dashboard`;
  - nenhum serviço tem `labels` com chave (ou item `chave=valor`) que comece com `traefik.` ou `coolify.`;
  - nenhum dos dois arquivos tem `volumes` no topo;
  - o topo de `infra/compose.api.yaml` tem `networks == {"link": {"name": "partqc-api-link", "internal": True}}`, e o de `infra/compose.yaml` tem `networks == {"link": {"name": "partqc-api-link", "external": True}}`;
  - `api.networks == ["default", "link"]`, `caddy.networks == ["default", "link"]`, e o `dashboard` não tem a chave `networks`;
  - `caddy.build == {"context": "..", "dockerfile": "infra/docker/caddy.Dockerfile"}`, e o `caddy` não tem `image`, `environment`, `volumes` nem `healthcheck`;
  - `caddy.tmpfs == ["/tmp:size=64m", "/data:size=16m", "/config:size=16m"]`, e `caddy.depends_on == ["dashboard"]`, sem `condition`;
  - `api.build` e `dashboard.build` são os de hoje (`infra/docker/api.Dockerfile` e `infra/docker/dashboard.Dockerfile`, contexto `..`).
- **CA-02 (R-03, §4.1, §4.1A)** — *Dado* os mesmos arquivos, *então*:
  - `api.environment` é exatamente o dicionário do item 6, e `dashboard.environment` é exatamente o do item 7;
  - o `caddy` não tem `environment`;
  - nenhum `environment` tem a chave `DATABASE_URL` fora da `api`;
  - todo valor de `environment` casa `^(https://)?\$\{[A-Z_]+(:\?|:-[^}]*)\}$`;
  - os valores de `DATABASE_URL` e `READ_API_KEY` são exatamente `${DATABASE_URL:?}` e `${READ_API_KEY:?}`;
  - o texto de `infra/compose.yaml` (com os comentários) não contém `DATABASE_URL`, `TELEGRAM_` nem `ALERTS_`, e o de `infra/compose.api.yaml` não contém `PUBLIC_HOST` nem `MODEL_METRICS_PATH`;
  - nenhum valor de `environment` é a string vazia.
- **CA-03 (§4.1, SPEC-015 §4.12 item 4, SPEC-032 §4.4)** — *Dado* os mesmos arquivos, *então*:
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
  - o bloco que ela abre (até a próxima linha que começa com `# ----------`) contém `Coolify`, `Locked`, `Literal`, `ALERTS_`, `config --quiet`, `partqc-api`, `partqc-web` e `compose.api.yaml`, as linhas `PUBLIC_HOST=<subdominio>`, os 6 limites e os 3 `*_PIDS_LIMIT=256`;
  - o arquivo não contém `infra/.env.api`, `infra/.env.dashboard` nem `rode "up -d"`;
  - as condições do CA-39 da SPEC-015 e do CA-05 da SPEC-015 sobre o `.env.example` continuam valendo.
- **CA-07 (§4.5)** — *Dado* `docs/deployment-plan.md`, *então*:
  - ele contém `Base Directory`, `` `/infra` ``, `Docker Compose Location`, `` `/compose.yaml` ``, `` `/compose.api.yaml` ``, `partqc-api`, `partqc-web`, `partqc-api-link`, `https://<subdominio>:80`, `Environment Variables`, `Locked`, `Literal`, `Preserve repository`, `Connect to predefined network`, `com.docker.compose.project=<uuid>`, `label=partqc.component`, `Config.Env`, `Manual Git Webhooks`, `Deploy on push`, `Just the push event`, `Enable SSL verification` e `2FA`;
  - alguma linha contém `ARG` e `build` (SEC-39-03), e toda linha que contém `Connect to predefined network` contém também `desligad` ou `Nunca`/`nunca`;
  - toda linha que contém `Webhook secret` ou `segredo do webhook` contém também `Coolify` ou `GitHub`, e nenhuma linha do arquivo contém `secrets.` seguido de um nome com `WEBHOOK` (o segredo nunca vai para os Secrets do Actions);
  - toda linha que contém `coolify-proxy` e uma das palavras `restart`, `reinici`, `stop`, `parar` ou `editar` contém também `Nunca` ou `nunca`;
  - toda linha que contém `Raw` contém também `Nunca`, `nunca` ou `não`;
  - as condições dos CAs 25, 27, 38 e 41 da SPEC-015 continuam valendo.
- **CA-08 (docker, §4.1, R-03)** — *Dado* uma cópia temporária do repositório com `infra/.env` contendo `PUBLIC_HOST=partqc.example.org`, uma `DATABASE_URL` fictícia (`postgresql://<user>:<password>@db.example.org:6543/postgres`, montada no teste) e uma `READ_API_KEY` gerada, e um ambiente de processo sem essas variáveis nem as de limite, *quando* se roda `docker compose -f <cópia>/infra/compose.api.yaml config --format json` e `docker compose -f <cópia>/infra/compose.yaml config --format json`, *então*:
  - os dois códigos são 0;
  - `services.dashboard.environment.API_BASE_URL == "https://partqc.example.org"`;
  - `services.api.environment.DATABASE_URL` é a URL fictícia, e `READ_API_KEY` é igual na `api` e no `dashboard`;
  - `MAX_BODY_BYTES == "262144"`, `LOG_LEVEL == "INFO"` e `MODEL_METRICS_PATH == ""`;
  - na `api`, `ALERTS_ENABLED == "false"`, `TELEGRAM_BOT_TOKEN == ""`, `TELEGRAM_CHAT_ID == ""`, `ALERTS_LOT_IDLE_MINUTES == "10"`, `ALERTS_LOOKBACK_HOURS == "24"`, `ALERTS_CHECK_INTERVAL_S == "60"`, `ALERTS_MAX_PER_HOUR == "10"` e `ALERTS_INCLUDE_SIMULATED == "false"`; nenhuma variável `DATABASE_URL`, `ALERTS_*` ou `TELEGRAM_*` aparece no `dashboard` nem no `caddy`;
  - no resultado de `infra/compose.api.yaml`, `networks.link.name == "partqc-api-link"` e `networks.link.internal is True`; no de `infra/compose.yaml`, `networks.link.name == "partqc-api-link"` e `networks.link.external is True`; os `networks` resolvidos da `api` e do `caddy` têm as chaves `default` e `link`;
  - nenhum serviço resolvido tem `ports`;
  - o `mem_limit` da `api` corresponde a 512 MiB.

  *Dado* o mesmo `infra/.env` sem uma variável obrigatória (um caso por par: `infra/compose.api.yaml` sem `DATABASE_URL` ou sem `READ_API_KEY`; `infra/compose.yaml` sem `PUBLIC_HOST` ou sem `READ_API_KEY`), *então* o código é diferente de 0, o stderr contém o nome da variável que falta, e o stderr não contém o valor da `READ_API_KEY` nem a senha fictícia. *Dado* o `infra/.env` **sem** `DATABASE_URL`, *então* o `config` de `infra/compose.yaml` tem código 0 (o `partqc-web` não precisa dela).
- **CA-09 (docker, §4.1; invocação do Coolify)** — *Dado* a mesma cópia **sem** `infra/.env` e dois arquivos fora da cópia, `api.env` (`DATABASE_URL` e `READ_API_KEY` do CA-08) e `web.env` (`PUBLIC_HOST` e a mesma `READ_API_KEY`), *quando* se roda, na forma que o Coolify usa (ADR-023), `docker compose --env-file <api.env> --project-name partqc-api-coolify-test --project-directory <cópia>/infra -f <cópia>/infra/compose.api.yaml config --format json` e `docker compose --env-file <web.env> --project-name partqc-web-coolify-test --project-directory <cópia>/infra -f <cópia>/infra/compose.yaml config --format json`, *então*:
  - os dois códigos são 0, com `name == "partqc-api-coolify-test"` e `name == "partqc-web-coolify-test"`;
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
- **CA-12 (docker, §4.1, §4.2)** — *Dado* duas redes Docker do teste, `web` e `link` (esta com `--internal`, como a `partqc-api-link`), com:
  - a imagem da `api` (SPEC-015, `build_image`) só na rede `link`, com o nome de rede `api`, uma `DATABASE_URL` fictícia inalcançável e uma `READ_API_KEY` gerada;
  - a do `dashboard` só na rede `web`, com o nome `dashboard`, `API_BASE_URL=https://partqc.example.org` e a mesma chave;
  - a do Caddy (CA-10) nas duas redes, com o nome `caddy`, executada com as opções do compose: `--read-only`, os 3 `tmpfs` da §4.1 item 5, `--cap-drop ALL`, `--cap-add NET_BIND_SERVICE`, `--security-opt no-new-privileges`, `--pids-limit 256`, sem `-p` e sem volume;

  *quando*, depois de o `dashboard` ficar `healthy` (até 90 s), se fazem requisições HTTP/1.1 a `http://caddy:80` com `Host: partqc.example.org`, a partir de um contêiner na rede `web`, *então*:
  - `GET /api/v1/health` responde 200 ou 503, com corpo JSON que tem a chave `status`;
  - `GET /_stcore/health` responde 200 com o corpo `ok`;
  - essas duas respostas têm `Strict-Transport-Security: max-age=31536000`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` e `Content-Security-Policy: frame-ancestors 'self'`, e nenhuma tem `Server` nem `Via`;
  - o corpo de `GET /docs` não contém `swagger` (sem diferenciar maiúsculas), e o de `GET /openapi.json` não contém `"openapi"`;
  - uma conexão TCP a `caddy:443` é recusada;
  - o log do Caddy não contém `read-only file system`, e o contêiner continua `running`.
- **CA-13 (docker, R-03, §4.6)** — *Dado* contextos montados com `build_image(..., extra_files=...)` com as sentinelas `infra/.env` e `.env`, as duas contendo `DATABASE_URL=` seguido de um marcador gerado no teste, *quando* se constroem as imagens da `api`, do `dashboard` e do Caddy, *então*:
  - na `api` e no `dashboard`, `test -e /app/infra/.env`, `test -e /app/.env` e `test -e /app/infra` falham (SEC-39-02), e `grep -rl <marcador> /app` não imprime nada;
  - no Caddy, `find / -xdev -name '.env*'` não imprime nada e `test -e /app` falha;
  - o CA-36 da SPEC-015 continua valendo.
- **CA-19 (docker, R-03, §4.1A; simulação do `env_file` do Coolify, SEC-39-01)** — *Dado* duas cópias temporárias do repositório, uma por recurso (como o Coolify, que faz um checkout por recurso), e em cada uma:
  - o arquivo do recurso (`infra/compose.api.yaml` na primeira, `infra/compose.yaml` na segunda) reescrito como o Coolify faz fora do Raw: `env_file: [".env"]` em **todos** os serviços (o YAML carregado, alterado e gravado de novo no mesmo caminho);
  - um `infra/.env` com **exatamente** as variáveis que o arquivo **original** do recurso referencia, com os nomes extraídos do texto pela regex `\$\{([A-Z0-9_]+)` (o Coolify cria as variáveis do recurso a partir das referências), e valores fictícios: a `DATABASE_URL` do CA-08, uma `READ_API_KEY` e um `TELEGRAM_BOT_TOKEN` gerados com `secrets.token_urlsafe`, `PUBLIC_HOST=partqc.example.org` e os padrões do arquivo nas demais;

  *quando* se roda, em cada cópia, `docker compose --env-file <cópia>/infra/.env --project-name <nome do teste> --project-directory <cópia>/infra -f <arquivo reescrito> config --format json`, *então*:
  - os dois códigos são 0;
  - o conjunto de nomes referenciados por `infra/compose.yaml` não contém `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` nem nenhum nome que comece com `ALERTS_`;
  - no resultado do `partqc-web`, o `environment` do `caddy` e o do `dashboard` não têm as chaves `DATABASE_URL`, `TELEGRAM_BOT_TOKEN` nem `TELEGRAM_CHAT_ID`, e nenhum valor deles contém a senha fictícia, a `DATABASE_URL` fictícia ou o `TELEGRAM_BOT_TOKEN` gerado;
  - no resultado do `partqc-api`, `services.api.environment.DATABASE_URL` é a URL fictícia e `TELEGRAM_BOT_TOKEN` é o valor gerado;
  - a `READ_API_KEY` pode aparecer no `environment` do `caddy` (§4.1A); o teste não a exige nem a proíbe ali;
  - o teste só captura a saída do `config`, sem imprimi-la nem incluí-la nas mensagens de asserção, porque ela contém os valores fictícios.

### Manuais (humano, na VPS e no painel do Coolify)

Antes de colar qualquer saída, troque o subdomínio por `<subdominio>`, o IP por `<IP>` e o UUID do recurso por `<uuid>` (R-13; `docs/deployment-plan.md` §9).

- **CA-14 (manual)** — Conferência antes do primeiro deploy:
  1. no painel do Coolify, registrar a versão (rodapé ou Settings) no `deployment-plan.md` §2;
  2. `docker ps --filter name=coolify-proxy --format '{{.Image}} {{.Ports}}'` mostra uma imagem `traefik` com as portas 80 e 443 publicadas;
  3. `docker inspect -f '{{.State.StartedAt}}' coolify-proxy` é anotado (fora do repositório) para o CA-40 da SPEC-015.
- **CA-15 (manual; ADR-023, itens 1 e 6 do Contexto, e emenda 1)** — Recursos e primeiro deploy, pelos passos 4 a 7 do `deployment-plan.md` §4:
  1. os dois recursos foram criados como **Public Repository**, com a URL HTTPS do repositório, branch `main`, build pack **Docker Compose** e Base Directory `/infra`: o `partqc-api` com Docker Compose Location `/compose.api.yaml`, e o `partqc-web` com `/compose.yaml`;
  2. em Advanced, nos dois, o modo de deploy do compose **não** é Raw, e "Connect to predefined network" e "Preserve repository during deployment" estão desligados. O primeiro deploy de cada um é pelo botão **Deploy**, primeiro o `partqc-api` e depois o `partqc-web`; o webhook é configurado depois e conferido no CA-18;
  3. em Domains, só o serviço `caddy` do `partqc-web` tem domínio, igual a `https://<subdominio>:80`; o `partqc-api` não tem nenhum;
  4. os dois deploys terminam com sucesso, e os logs mostram o build das três imagens (a da `api` no `partqc-api`; a do `caddy` e a do `dashboard` no `partqc-web`). O humano lê os logs no painel e confirma que nenhum valor de segredo aparece; se aparecer, não colar o log em lugar nenhum e registrar `SPEC_ISSUE`;
  5. `docker ps --filter label=partqc.component --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'` mostra 3 contêineres `Up`, com a `api` e o `dashboard` `(healthy)`, e a coluna de portas sem nenhum `0.0.0.0:` nem `[::]:`.

  Se o passo 4 falhar no build por causa do `context: ..`, parar e registrar `SPEC_ISSUE` com a linha do erro (ADR-023, "Quando revisitar").
- **CA-16 (manual; ADR-023, item 2 do Contexto)** — O Coolify preserva o endurecimento. Para cada contêiner do passo 5 do CA-15, `docker inspect -f '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.CapAdd}} {{.HostConfig.SecurityOpt}} {{json .HostConfig.Tmpfs}} {{json .HostConfig.PortBindings}} {{.HostConfig.RestartPolicy.Name}}' <contêiner>` mostra, com os padrões:
  - `api`: `536870912 1000000000 256 true [ALL]`, sem `CapAdd`, com `no-new-privileges:true`, `/tmp` com `size=64m`, `PortBindings` vazio (`{}` ou `null`) e `unless-stopped`;
  - `dashboard`: o mesmo, com `1073741824` de memória;
  - `caddy`: `268435456 500000000 256 true [ALL] [NET_BIND_SERVICE]`, `no-new-privileges:true`, `/tmp` (`size=64m`), `/data` e `/config` (`size=16m`), `PortBindings` vazio e `unless-stopped`.

  Se o humano tiver mudado algum limite no painel, vale o valor dele. Um item diferente do esperado sem mudança no painel → `SPEC_ISSUE` com a saída.
- **CA-17 (manual, R-03; ADR-023, item 5 do Contexto)** — Segredos:
  1. no painel, nos dois recursos, `DATABASE_URL` (só no `partqc-api`) e `READ_API_KEY` (nos dois) estão com o build desligado (só runtime), **Locked** e **Literal**;
  2. para cada imagem dos 3 contêineres, `docker history --no-trunc <imagem> | grep -c -e DATABASE_URL -e READ_API_KEY` → `0`;
  3. `docker exec <contêiner da api> find /app -maxdepth 2 -name '.env*'` e o mesmo no `dashboard` → nenhuma linha, ou só `/app/.env.example` (o CA-43, passo 1, da SPEC-015);
  4. para o `<uuid>` de cada recurso, `sudo find /data/coolify/applications/<uuid> -maxdepth 2 -name .env -exec stat -c '%a %U:%G %n' {} \;` → registrar os modos e donos no `deployment-plan.md` §7, item 7, sem o caminho completo. Se algum modo permitir leitura a "outros" (último dígito diferente de 0), registrar isso no mesmo item e avisar o humano. Não mudar a permissão à mão, porque o Coolify reescreve o arquivo a cada deploy;
  5. o ambiente real de cada contêiner é conferido no CA-20.
- **CA-18 (manual, R-03; §4.8)** — Deploy automático por webhook:
  1. com o webhook configurado pela §4.8 e o Auto deploy em **Deploy on push (webhooks)** nos dois recursos, mergear na `main` um PR de teste pelo portão da R-09 (por exemplo, o PR que registra os CAs 14 a 17 e 20 no `deployment-plan.md`);
  2. em até 5 min, a lista de deploys de **cada** recurso mostra um deploy novo disparado pelo webhook, com o commit do merge. Em **Settings > Webhooks > Recent Deliveries** do GitHub, a entrega `push` desse commit tem resposta 2xx;
  3. os commits da branch do PR, enviados antes do merge, não geraram nenhum deploy (só a `main` dispara);
  4. os dois deploys terminam com sucesso, a listagem do CA-15 (passo 5) mostra os 3 contêineres `Up`, com a `api` e o `dashboard` `(healthy)`, e o smoke (CA-15 da SPEC-015) dá 8 × `PASS`;
  5. nos logs desses deploys, uma busca no navegador pelos 8 primeiros caracteres do segredo do webhook, da `DATABASE_URL` (a parte da senha), da `READ_API_KEY` e, se preenchida, da `TELEGRAM_BOT_TOKEN` → 0 ocorrências. Se houver alguma, não copiar o log, trocar o segredo afetado e registrar `SPEC_ISSUE`;
  6. `git grep -n -i "webhook"` no checkout local mostra só documentação: nenhuma linha com uma URL do painel do Coolify nem com um valor de segredo (o CA-42 da SPEC-015 confere o host do painel, se o humano o informar como mais um valor);
  7. registrar no dev-report e no `deployment-plan.md` §9 o resultado, o SHA curto do commit e a data, sem a URL do webhook nem o UUID.

  Se o painel não for alcançável pela internet (§4.8, item 6), este CA é registrado como "não aplicável: deploy pelo botão", com a data, e o webhook não é configurado.
- **CA-20 (manual, R-03; §4.1A, SEC-39-01)** — Isolamento dos segredos por contêiner, depois do CA-15 e de novo depois de cada atualização do Coolify. Nenhum passo imprime valores: os nomes são cortados antes do `grep`, e o resto só conta ocorrências.
  1. No painel, a lista de Environment Variables do `partqc-web` não tem `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` nem nenhuma `ALERTS_*`, e a do `partqc-api` não tem `PUBLIC_HOST`.
  2. Para cada contêiner da listagem do CA-15 (passo 5):

     ```bash
     docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' <contêiner> | cut -d= -f1 | grep -xE 'DATABASE_URL|READ_API_KEY|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID' | sort | tr '\n' ' '
     ```

     → na `api`: `DATABASE_URL READ_API_KEY TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID`; no `dashboard`: `READ_API_KEY`; no `caddy`: `READ_API_KEY` ou nada.
  3. No `caddy` e no `dashboard`, `docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' <contêiner> | grep -ci 'supabase'` → `0` (pega a string de conexão mesmo sob outro nome).
  4. `docker network inspect partqc-api-link -f '{{.Internal}} {{len .Containers}}'` → `true 3`, e `docker network inspect partqc-api-link -f '{{range .Containers}}{{println .Name}}{{end}}'` lista exatamente os contêineres da `api`, do `caddy` e do `dashboard` do PartQC (registrar só "3 contêineres do PartQC": os nomes têm o UUID).
  5. Registrar no dev-report e no `deployment-plan.md` §9 as saídas dos passos 2 a 4 com o papel de cada contêiner (`api`, `dashboard`, `caddy`), sem os nomes dos contêineres.

  Se o passo 1, 2 ou 3 falhar: parar o `partqc-web` (**Stop**), trocar a senha do banco no Supabase e atualizar a `DATABASE_URL` no `partqc-api` (se a `DATABASE_URL` apareceu fora da `api`), ou trocar o token do bot (se o `TELEGRAM_BOT_TOKEN` apareceu), e registrar `SPEC_ISSUE` (ADR-023, "Quando revisitar"). Se só o passo 4 falhar, registrar `SPEC_ISSUE` com a saída.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Os dois composes como YAML; Caddyfile e Dockerfile como texto; `.dockerignore`; `.env.example` e plano como texto; `config` local e na forma do Coolify (docker); simulação do `env_file` do Coolify (docker); `adapt`, imagem e execução do Caddy (docker); ajustes nos próprios testes das SPECs 015, 032 e 038 | `infra/tests/` |
| Aceite (tester) | CA-01 a CA-13 e CA-19 (CA-08 a CA-13 e CA-19 marcados `docker`) e os ajustes da tabela da §3.1 | `infra/tests/acceptance/test_spec_039.py` |
| Manual (humano) | CA-14 a CA-18 e CA-20 e, depois deles, os CAs manuais da SPEC-015 e o CA-09 da SPEC-032 (§4.7) | VPS, painel do Coolify e GitHub; registro no dev-report e no `deployment-plan.md` §9 |

- Nenhum teste usa a VPS, o Coolify, o DNS, o Supabase ou a rede externa. As imagens base vêm do Docker Hub e do GHCR no build, como na SPEC-015.
- Os testes `docker` seguem a SPEC-015 §4.14: contextos em `tmp_path`, imagens removidas no fim da sessão. Um test-report com os testes `docker` só pulados não vale como PASS desses CAs.
- O CA-12 não mocka nada dentro das redes do teste: a API responde 503 sem banco, o que basta para conferir o caminho Caddy → API pela rede de ligação.
- O CA-19 não executa o Coolify: ele reproduz no arquivo o `env_file` que o código do Coolify acrescenta (ADR-023, emenda 1) e confere o resultado com o `config` do Compose. A conferência na VPS é o CA-20.

## 7. Riscos e notas para o implementador

- **Dashboard → API sem o alias:** o contêiner do dashboard resolve `<subdominio>` pelo DNS público e volta à VPS pelo `coolify-proxy` (hairpin). Se o CA-17 da SPEC-015 mostrar "API acordando" com a API saudável, parar e registrar `SPEC_ISSUE`. A alternativa, que exige decisão, é um `extra_hosts: ["${PUBLIC_HOST}:host-gateway"]` no `dashboard`. Nunca trocar a URL por `http://api:8000`: a SPEC-028 recusa `http://` fora do loopback.
- **Healthcheck no Caddy:** não acrescente nenhum. Com o Traefik, um contêiner `unhealthy` sai da rota, e o site inteiro cairia (ADR-023).
- **`X-Forwarded-*`:** o Caddy recebe HTTP do Traefik e, sem `trusted_proxies`, repassa `X-Forwarded-Proto: http` às origens. A API não monta URLs absolutas, e o Streamlit continua com `enableCORS` e `enableXsrfProtection` padrão (SPEC-015 §4.4). Se o painel quebrar por XSRF ou WebSocket no CA-17 da SPEC-015, parar e registrar `SPEC_ISSUE`; nunca desligar essas proteções.
- **`tmpfs` em `/data` e `/config`:** o Caddy grava ali o `instance.uuid` e o `autosave.json`. Com 16m, sobra muito. Se o log mostrar falta de espaço, registre `SPEC_ISSUE` com a linha, em vez de aumentar por conta própria.
- **Sem `PUBLIC_HOST` no Caddyfile:** o site `:80` aceita qualquer `Host`. Só o `coolify-proxy` (pela regra `Host(...)` que o Coolify gera) e os contêineres das redes do `partqc-web` e da `partqc-api-link` alcançam o Caddy, que não tem porta publicada.
- **Quem alcança a `api` (ADR-023, emenda 1):** na `partqc-api-link`, o `caddy` e o `dashboard` (o Coolify liga ao `dashboard` todas as redes do topo do arquivo); na rede do `partqc-api`, só o `coolify-proxy`. Inclui o `/docs` e o `/openapi.json` internos da API, como no recurso único. Nunca ligar "Connect to predefined network", que abriria a `api` a todos os contêineres da rede `coolify`.
- **Segredos por recurso:** nunca crie `DATABASE_URL`, `TELEGRAM_*` nem `ALERTS_*` no `partqc-web`, nem cite esses nomes no `infra/compose.yaml`. Nunca use `NOME: ""` para "apagar" uma variável de um serviço: o Coolify troca o valor vazio pelo valor salvo e grava o segredo no compose gerado (ADR-023, emenda 1).
- **Ordem dos deploys:** o `partqc-web` depende da rede `partqc-api-link`, criada pelo `partqc-api`. Nos merges, os dois deploys rodam em paralelo, e a rede já existe. Ao parar o `partqc-api`, o Coolify remove a rede `<uuid>` dele (`deleteConnectedNetworks`); a `partqc-api-link` o Docker não remove enquanto o `caddy` e o `dashboard` estiverem ligados a ela. Se uma limpeza apagar a `partqc-api-link`, faça o deploy do `partqc-api` antes do `partqc-web`.
- **Atualização do Coolify:** o isolamento depende do comportamento conferido no código (`env_file` por recurso, redes do topo mantidas). Depois de cada atualização do Coolify, repetir o smoke, o CA-16 e o CA-20.
- **Domínios em comentários:** nada de `coolify.io`, `sslip.io` ou outro domínio nos arquivos de `infra/` (o `test_extra_no_real_host_hints_in_deploy_files` da SPEC-015 recusa). As fontes ficam no ADR-023 e no `deployment-plan.md`.
- **Variáveis com padrão:** o Coolify cria no painel de cada recurso as variáveis com `${NOME:-padrão}` do arquivo dele, com o padrão do arquivo (ADR-023, Contexto). Se o humano apagar o valor no painel, o compose usa o padrão.
- **Deploy automático:** o merge desta SPEC na `main` já dispara o deploy, se o webhook existir. Na primeira publicação, o webhook é configurado só depois do CA-15 (primeiro deploy pelo botão), para que um deploy falho não aconteça antes de as variáveis estarem no painel. Uma mudança futura que torne obrigatória uma variável nova (`${NOME:?}`) bloqueia o deploy automático do recurso do arquivo até o humano criá-la no painel desse recurso.
- **Ordem com a SPEC-038:** a Parte B da 038 escreve o `handle_errors` dentro do bloco `:80` deste Caddyfile. Esta SPEC precisa estar mergeada antes de a 038 entrar em `In Dev`.
- Nunca rode `docker compose down -v`, `prune` amplo, nem mexa no `ufw` ou no `coolify-proxy` (ADR-023, decisão 6).

## 8. Definição de pronto

- [ ] CA-01 a CA-13 e CA-19 com teste de aceite passando (test-report PASS, com os testes `docker` executados), e os ajustes da §3.1 na tabela do test-report
- [ ] review-report APPROVED + o portão de segurança feito pelo reviewer (autor `security-devops`)
- [ ] CI verde (`ci` e `docker`); `ruff` limpo
- [ ] `.env.example` e `docs/deployment-plan.md` atualizados
- [ ] CA-14 a CA-18 e CA-20 (manuais) registrados no dev-report e no `deployment-plan.md` §9. Eles só podem ser feitos depois do merge, como na SPEC-015 e na SPEC-032; até lá, a SPEC fica `In Security`
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-25 | SPEC criada (`Draft`). Decisões do architect, com o ADR-023 (`Proposto`): (a) nenhum serviço com `ports`, nenhuma label `traefik.*`/`coolify.*`, sem a rede própria e sem o alias; (b) Caddy em `:80`, sem TLS e sem healthcheck, com `tmpfs` em `/data` e `/config` no lugar dos volumes; (c) Caddyfile embutido numa imagem própria (`caddy.Dockerfile`, contexto só com o Caddyfile), em vez de bind com "Preserve repository"; (d) segredos por `${NOME:?}` no `environment`, sem `env_file`, e os opcionais com o padrão do código; (e) Base Directory `/infra` e Docker Compose Location `/compose.yaml`, com o CA-09 simulando a invocação do Coolify; (f) o `handle_errors` continua na SPEC-038; (g) equivalência dos comandos do CA-09 da SPEC-032 (§4.7). | Fato novo do humano em 2026-10-25: a VPS é gerenciada pelo Coolify, cujo proxy ocupa 80/443 | Orquestrador, a pedido do humano |
| 2026-10-25 | Decisões do humano sobre o PR #55: (1) opção A do ADR-023 aprovada (Caddy como roteador interno); (2) **deploy automático por webhook** a cada merge na `main`: §3.2 ajustada, §4.8 nova (webhook manual com segredo só no Coolify e no GitHub, sem Watch Paths, processo com a `main` sempre publicável e rollback por branch), CA-07 com os nomes da interface do webhook, CA-15 com o primeiro deploy pelo botão, **CA-18 novo** (manual: um merge de teste dispara o deploy, só a `main` dispara, e o log não mostra segredos); (3) as 8 variáveis de alertas da SPEC-017 (`ALERTS_*`, `TELEGRAM_*`), com os padrões dela (alertas desligados), entram já no `environment` da `api` (§4.1, item 6; CA-08); o `.env.example` as cita no comentário, e o texto do plano sobre os alertas fica para o merge da 017; (4) o `handle_errors` fica na SPEC-038, e esta SPEC entra agora, direto na `main` (Semana alvo). Fontes novas no ADR-023 (consultadas em 2026-10-25). A SPEC continua `Draft` até a aprovação formal. | Decisão do humano | Humano (Carlos) |
| 2026-10-25 | Aprovada pelo humano (`Draft` → `Ready`) com o ADR-023: Caddy como roteador interno, deploy automático por webhook, variáveis da SPEC-017 opcionais no compose (nomes e padrões conferidos contra o código da 017), o 502 com headers fica na SPEC-038; entra agora, direto na `main`. | Resposta do humano de 2026-10-25 (PR #55) | Orquestrador, a pedido do humano |
| 2026-10-25 | **Correção do SPEC_ISSUE SEC-39-01** (r1-security-report), com a emenda 1 do ADR-023. Fato: fora do Raw, o Coolify acrescenta `env_file: ['.env']` a todos os serviços do recurso e grava nele todas as variáveis de runtime do recurso (código-fonte `v4.x` e `v4.5.0`, consultado em 2026-10-25), então a `DATABASE_URL` chegaria ao `dashboard` e ao `caddy`. Mudanças: **dois recursos** no Coolify (§1, §2, §4.1A nova): `partqc-api` (`infra/compose.api.yaml`, novo, só a `api`) e `partqc-web` (`infra/compose.yaml`, `caddy` e `dashboard`), ligados pela rede `partqc-api-link` (`internal`, criada pelo `partqc-api`, `external` no `partqc-web`); §4.1 reescrita para os dois arquivos (antes: um arquivo com os três serviços, sem `networks`, e `caddy.depends_on: [api, dashboard]`), com a proibição de citar `DATABASE_URL`, `TELEGRAM_` e `ALERTS_` no `infra/compose.yaml` e de usar `NOME: ""`; §3.1 com o arquivo novo, a linha `infra/` nos `.dockerignore` da API e do dashboard e a linha nova da tabela de ajustes; §3.2 sem código da API; §4.4 com a divisão por recurso; §4.5 com o que o plano tem de dizer (dois recursos, SEC-39-03 e SEC-39-04); §4.6 com o SEC-39-02 (`infra/` fora das imagens da API e do dashboard); §4.7 com a listagem por `label=partqc.component` e a regra dos dois recursos nos textos das SPECs 015, 032 e 038; §4.8 com o mesmo segredo de webhook nos dois recursos e o item 6 (painel não público → deploy pelo botão; público → 2FA); CA-01, CA-02, CA-03, CA-06, CA-07, CA-08, CA-09, CA-12 e CA-13 ajustados aos dois arquivos; **CA-19 novo** (docker: simulação do `env_file` do Coolify, cada recurso com o `.env` só das variáveis que o arquivo dele referencia); CA-15, CA-17 e CA-18 para os dois recursos; **CA-20 novo** (manual: `Config.Env` de cada contêiner, só os nomes, `supabase` fora do `caddy` e do `dashboard`, rede `partqc-api-link` `internal` com 3 contêineres; repetido a cada atualização do Coolify); §6, §7 e §8 atualizadas. O SEC-39-05 fica como nota (CA-17 da SPEC-015, fora do repositório). Nenhum código da API ou do dashboard muda. **Classificação ADR-019: exige humano** (X-2: emenda do ADR-023; X-3: `docs/architecture.md` muda; X-5: arquivo de produção novo e rede nova; X-7: R-03, segredos). **Aguardando reaprovação humana.** | SEC-39-01 a SEC-39-04 de `reviews/SPEC-039/r1-security-report.md` | Orquestrador (SPEC_ISSUE), redigido pelo architect |
| 2026-10-25 | Correção do SEC-39-01 (dois recursos, emenda 1 do ADR-023) reaprovada pelo humano (commit do architect 4239a2f), com a `READ_API_KEY` aceita no Caddy, o SEC-39-02 já nesta rodada e o painel do Coolify público (2FA antes do webhook; CA-18 aplicável). A rodada r1 continua: o security-devops implementa os dois recursos. | Respostas do humano de 2026-10-25 | Orquestrador, a pedido do humano |
| 2026-10-26 | Aviso do topo: a frase "Até a reaprovação, o status continua `Blocked`", obsoleta desde a reaprovação de 2026-10-25, passa a dizer que a SPEC saiu de `Blocked` e voltou ao loop. O campo "Depende de" troca "emenda 1 [...] aguardando aprovação humana" por "emenda 1 [...] aceita pelo humano em 2026-10-25". Na mesma correção, a nota da hospedagem em `docs/architecture.md` §1 passa a dizer que a emenda 1 do ADR-023 foi aceita em 2026-10-25. Texto, sem mudança de requisito, de CA ou do campo Status. | RV-06 do adendo de `reviews/SPEC-039/r1-review-report.md` | Orquestrador |
