# ADR-023: Publicar a API e o dashboard pelo Coolify da VPS pessoal (recurso Docker Compose a partir do GitHub), com TLS e domínio no proxy do Coolify e o Caddy só como roteador interno

| Campo | Valor |
|---|---|
| Status | Aceito (aprovado pelo humano em 2026-10-25: Caddy como roteador interno, deploy automático por webhook). Emenda 1 (dois recursos no Coolify, SEC-39-01) aceita pelo humano em 2026-10-25, com a `READ_API_KEY` aceita no Caddy |
| Data | 2026-10-25 |
| Decisores | Humano (Carlos) (redigido pelo agente architect) |
| Relacionados | ADR-018 (substituído em parte), ADR-008 (banco e keep-alive, sem mudança), ADR-006, ADR-007, ADR-016, ADR-019, SPEC-015, SPEC-032, SPEC-038, SPEC-039, SPEC-017, SPEC-028, R-01, R-03, R-13, N-05 |

## Contexto

O ADR-018 pôs a `qc-api` e o `qc-dashboard` na VPS pessoal do humano, atrás de um Caddy do próprio compose, que obtinha o certificado e publicava as portas 80 e 443, com a premissa "as portas 80 e 443 estão livres". Em 2026-10-25, o humano informou que a VPS é gerenciada pelo **Coolify**. O portfólio dele já roda lá, publicado pelo Coolify com o domínio configurado no painel, e o proxy é o padrão do Coolify, que ocupa as portas 80 e 443. A premissa do ADR-018 não vale, e o `infra/compose.yaml` da `main` (SPEC-015) **não sobe** nessa VPS: ele publica `80:80` e `443:443`, que já estão em uso. Por isso, os CAs manuais da SPEC-015 e o CA-09 da SPEC-032 estão travados. O próprio ADR-018 previa este gatilho: "Se outro projeto do humano precisar das portas 80/443: compartilhar um proxy único, com ADR novo".

Fatos do Coolify, conferidos pelo architect em **2026-10-25** na documentação oficial e no repositório oficial (`coollabsio/coolify`, branch `v4.x`):

| Fato | Fonte |
|---|---|
| O Traefik é o proxy integrado padrão. O Coolify configura os entry points `http` e `https` nas portas 80 e 443, o resolvedor `letsencrypt` (desafio HTTP) e um único contêiner `coolify-proxy` por servidor, ligado às redes dos recursos roteados. Mudar a configuração principal do Traefik exige reiniciar o proxy | <https://coolify.io/docs/knowledge-base/proxy/traefik/overview> |
| Num recurso Docker Compose, cada serviço HTTP público recebe o domínio na página **Domains**: escolhe-se o serviço e informa-se o protocolo, o host, a porta interna e um caminho opcional. "The suffix tells the Coolify proxy which container port receives the request". O Coolify gera as labels do proxy para esses domínios. Labels de proxy escritas à mão só no modo **Raw (deploy file as-is)** | <https://coolify.io/docs/knowledge-base/docker/compose> |
| "Do not publish a service with `ports:` unless it must be reachable directly on a server interface. A published host port bypasses domain-based proxy routing and can expose an internal service." No código, o `applicationParser` **mantém** o `ports` do arquivo (não o remove) | mesma página; `bootstrap/helpers/parsers.php` (<https://github.com/coollabsio/coolify/blob/v4.x/bootstrap/helpers/parsers.php>) |
| `SERVICE_URL_<ID>` e `SERVICE_FQDN_<ID>` geram um domínio (o último segmento numérico é a porta), e "Coolify manages the generated URL and FQDN values from the resource's domain configuration" | <https://coolify.io/docs/knowledge-base/docker/compose> |
| **Roteamento por caminho:** um domínio com caminho (`https://host/api`) vira uma regra `Host(...) && PathPrefix(...)`. Por padrão, o Coolify **remove o prefixo** antes de encaminhar (`/api/users` chega como `/users`); a opção "Keep paths as-is" está documentada só para aplicações, e a página diz não saber se vale para Compose. No código, o middleware `stripprefix` só entra quando o caminho não é `/` e depende de uma configuração do recurso (`is_stripprefix_enabled`, padrão `true`) | <https://coolify.io/docs/core/networking/domains>; `fqdnLabelsForTraefik` em <https://github.com/coollabsio/coolify/blob/v4.x/bootstrap/helpers/docker.php> |
| O redirecionamento HTTP → HTTPS gerado pelo Coolify é um middleware `redirectscheme` aplicado quando a configuração "Force HTTPS" do recurso está ligada (`is_force_https_enabled`). A página de domínios não documenta o padrão nem o código de status | mesmas fontes |
| **Healthchecks:** num Compose a partir do Git, ficam no Dockerfile ou no compose (a página "Healthcheck" do painel não vale). Com o Traefik, "Traefik removes unhealthy containers from routing", e o proxy pode responder `404` ou `No available server` | <https://coolify.io/docs/knowledge-base/health-checks> |
| **Variáveis:** uma referência `${VAR}` no compose faz o Coolify criar a variável no painel do recurso; `${VAR:?}` a torna obrigatória e bloqueia o deploy se estiver vazia; "Coolify keeps an existing value when the Compose definition is loaded again". Cada variável tem escopo de build e de runtime independentes, pode ser **Locked** e ter interpolação **Literal** (mantém `$`). "Traditional Docker build arguments can appear in image metadata" | <https://coolify.io/docs/applications/build-packs/docker-compose>, <https://coolify.io/docs/knowledge-base/environment-variables> |
| No deploy, o Coolify grava as variáveis de runtime num `.env` no diretório de trabalho e no diretório de configuração do recurso (com `tee`, sem `chmod` no trecho lido) e roda `docker compose --env-file <...>/.env --project-name <uuid> --project-directory <workdir> -f <arquivo> up -d`. A documentação não diz onde fica esse arquivo | `app/Jobs/ApplicationDeploymentJob.php` (<https://github.com/coollabsio/coolify/blob/v4.x/app/Jobs/ApplicationDeploymentJob.php>) |
| O `-p` da linha de comando prevalece sobre o `name:` do arquivo; um `build.context` relativo é resolvido a partir do diretório do projeto | <https://docs.docker.com/compose/how-tos/project-name/>, <https://docs.docker.com/reference/compose-file/build/> |
| A pasta do recurso é definida por **Base Directory** e **Docker Compose Location** (relativa à primeira). Para um arquivo do repositório montado por bind, é preciso ligar "Preserve repository during deployment" e o arquivo tem de existir antes do deploy ("If Docker receives a missing file source, it can create a directory at that path"). No código, um bind curto sem configuração salva é tratado como diretório por padrão | <https://coolify.io/docs/applications/build-packs/docker-compose>; `parsers.php` |
| Repositório público: basta a URL HTTPS, sem credencial; "Connecting a public repository by URL does not configure automatic deployments" (exige webhook) | <https://coolify.io/docs/applications/ci-cd/github/public-repository> |
| **Deploy automático (webhook manual):** vale para aplicações criadas por URL pública. No Coolify: **Webhooks > Manual Git Webhooks**, seção GitHub, **Webhook secret** (mínimo de 16 caracteres, com gerador) e **Save changes**; copiar a URL GitHub mostrada ali. No GitHub: **Settings > Webhooks > Add webhook**, com essa URL como Payload URL, content type `application/json`, o mesmo segredo, **Enable SSL verification** ligado e **Just the push event**. No recurso: **Advanced > Deployment > Auto deploy = Deploy on push (webhooks)**. Só um push na branch configurada no recurso dispara o deploy. A URL do Coolify tem de ser alcançável pela internet. Falhas repetidas de assinatura são limitadas por endereço, e a resposta do webhook não revela quais aplicações casam | <https://coolify.io/docs/applications/deployments/manual-webhooks>, <https://coolify.io/docs/applications/ci-cd/github/auto-deploy> |
| **GitHub App** (alternativa): registra um app na conta do GitHub, com leitura de conteúdo, metadados e e-mails, e o Coolify guarda o App ID, as credenciais, o segredo do webhook e a chave privada | <https://coolify.io/docs/applications/sources/github/app> |
| **Watch Paths** filtram os deploys por arquivos alterados (um padrão por linha, `!` para negar), só nos eventos de webhook com a lista de arquivos. A documentação não diz se os caminhos são relativos à raiz ou ao Base Directory | <https://coolify.io/docs/applications/deployments/automatic-deployments> |
| A documentação **não diz** o que acontece com a versão em execução quando um deploy falha, nem se deploys simultâneos entram em fila. No código, o build (`docker compose ... build`) roda antes do `up -d`, então um erro de build para antes de recriar os contêineres | mesmas páginas; `ApplicationDeploymentJob.php` |
| Atualização gradual (rolling update) não é suportada em Compose; o rollback do painel usa imagens antigas guardadas e a documentação não diz como se aplica a Compose | <https://coolify.io/docs/knowledge-base/rolling-updates>, <https://coolify.io/docs/applications/deployments/rollbacks> |
| Licença Apache-2.0; auto-hospedado: "Free and open source" | <https://github.com/coollabsio/coolify> |
| O Caddy não ativa o HTTPS automático sem nenhum nome de host na configuração ou quando escuta só na porta HTTP | <https://caddyserver.com/docs/automatic-https> |

**Fatos acrescentados pela emenda 1** (SEC-39-01 de `reviews/SPEC-039/r1-security-report.md`). Conferidos pelo architect em **2026-10-25** no código-fonte oficial, na branch `v4.x` e na tag `v4.5.0` (a última versão publicada), porque a documentação não os descreve:

| Fato | Fonte |
|---|---|
| **O `environment` de um serviço não delimita o que ele recebe.** Fora do modo Raw, o Coolify acrescenta `env_file: ['.env']` a **todos** os serviços do recurso, sem opção para desligar: "Always add .env file to services", com `$service['env_file'] = ['.env']` num `map()` sobre todos os serviços (só o ramo Raw não passa por ali). O `applicationParser` faz o mesmo ("Auto-inject .env file so Coolify environment variables are available inside containers"), mantendo os `env_file` do arquivo e acrescentando o `.env`. Nesse `.env`, o Coolify grava **todas** as variáveis de runtime do recurso, sem filtro por serviço (`generate_runtime_environment_variables` e `save_runtime_environment_variables`). A página de Compose não cita o `env_file` | `deploy_docker_compose_buildpack` em `app/Jobs/ApplicationDeploymentJob.php` e `applicationParser` em `bootstrap/helpers/parsers.php` (<https://github.com/coollabsio/coolify/blob/v4.x/app/Jobs/ApplicationDeploymentJob.php>, <https://github.com/coollabsio/coolify/blob/v4.x/bootstrap/helpers/parsers.php>; os mesmos trechos existem na tag `v4.5.0`); <https://coolify.io/docs/knowledge-base/docker/compose> |
| Sobrescrever com valor vazio (`DATABASE_URL: ""`) no serviço que não deve receber o segredo **não funciona**: o parser troca a string vazia pelo valor salvo da variável de mesmo nome ("Empty string - allow database override for backward compatibility") e gravaria o valor literal no compose gerado | `applicationParser`, `parsers.php` (`v4.x` e `v4.5.0`) |
| As variáveis de **build** viram `ARG` em cada estágio dos Dockerfiles do compose, inclusive as `COOLIFY_*`, enquanto a configuração `inject_build_args_to_dockerfile` não for `false` explicitamente | `modify_dockerfiles_for_compose` e `generate_env_variables` (filtro `is_buildtime`), `ApplicationDeploymentJob.php` (`v4.x`) |
| **Redes:** cada recurso tem a rede `<uuid>` (`docker network create --attachable`), à qual o Coolify liga o `coolify-proxy`, e o Traefik é instruído a usar essa rede para chegar ao serviço (`addTraefikDockerNetworkLabel($serviceLabels, $baseNetwork->first())`). As redes declaradas no topo do arquivo são mantidas, com `name:` literal ou com uma variável (`validateComposeNetworkNameField`; "only Docker Compose reads this value"), e o parser liga **todas** as redes do topo a **todos** os serviços do recurso (salvo os com `network_mode`) | `applicationParser`, `parsers.php` e `deploy_docker_compose_buildpack`, `ApplicationDeploymentJob.php` (`v4.x` e `v4.5.0`) |
| "Connect to predefined network" liga os serviços à rede do destino (`coolify`), compartilhada pelos recursos do servidor. A documentação diz para usá-la "only when the Compose services must communicate with resources on the selected Coolify destination" e avisa que "Names can be prefixed to prevent collisions" | `parsers.php` (`connect_to_docker_network`); <https://coolify.io/docs/knowledge-base/docker/compose> |
| Ao parar um recurso Compose, o Coolify desliga o `coolify-proxy` da rede `<uuid>` e tenta removê-la (`docker network disconnect`, `docker network rm`, sem conferir se há outros contêineres ligados) | `deleteConnectedNetworks` em `app/Models/Application.php` e `app/Actions/Application/StopApplication.php` (`v4.x`) |
| **Webhook manual com vários recursos:** o Coolify seleciona todas as aplicações do mesmo repositório e branch e confere a assinatura com o segredo de **cada** uma (`manual_webhook_secret_github`, HMAC com `hash_equals`). Uma aplicação com segredo diferente é pulada com o registro `invalid_signature`, e as outras continuam | `app/Http/Controllers/Webhook/Github.php` (`v4.x`) |

**O que não está claro na documentação, e o teste humano que confirma** (todos viram CAs manuais da SPEC-039 ou da SPEC-015):

1. Se o `build.context: ..` funciona com Base Directory `/infra` (o código usa `--project-directory` igual ao diretório de trabalho, o que indica que sim). Teste: o primeiro deploy termina com sucesso e as três imagens existem (SPEC-039, CA-15).
2. Se o Coolify preserva `mem_limit`, `cpus`, `pids_limit`, `read_only`, `tmpfs`, `cap_drop`, `cap_add` e `security_opt` do arquivo. Teste: `docker inspect` dos contêineres (SPEC-039, CA-16).
3. O código do redirecionamento HTTP → HTTPS e o padrão do "Force HTTPS". Teste: CA-13, passo 2, da SPEC-015 (aceita 301, 302, 307 ou 308 para `https://`).
4. Se o Traefik do Coolify acrescenta `Server`, `Via` ou um HSTS próprio. Teste: CA-13, passo 4, da SPEC-015 e o CA-09 da SPEC-032.
5. Onde fica o `.env` com os segredos e com que permissão. Teste: `stat` no diretório do recurso (SPEC-039, CA-17).
6. Se o log de deploy do Coolify mostra valores de variáveis. Teste: o humano lê o log no painel e nunca o cola em lugar público sem conferir (SPEC-039, CA-15).
7. Se o contêiner do dashboard alcança a URL pública da própria VPS (hairpin). Teste: CA-17 da SPEC-015 (o painel carrega dados).
8. O que acontece com a versão em execução quando um deploy falha. Teste: o log de deploy de cada merge e o smoke da atualização. Uma falha vira rollback por branch (decisão 5). O CA-18 da SPEC-039 confere o disparo pelo webhook.
9. (emenda 1) Se a versão instalada do Coolify se comporta como o código lido: o `.env` de cada recurso só chega aos serviços dele, a rede `partqc-api-link` é criada como `internal` pelo recurso da API e mantida como `external` no outro, e o Caddy chega à `api` por ela. Teste: `Config.Env` de cada contêiner, só os nomes, e `docker network inspect` (SPEC-039, CA-20), e o smoke (CA-15 da SPEC-015).

## Opções consideradas

**Onde fica o TLS:** só há uma opção compatível com a VPS: o proxy do Coolify, que já ocupa 80/443 e serve o portfólio. Mexer nele (portas, configuração, outro proxy) afetaria os outros projetos. A decisão abaixo é sobre o papel do Caddy.

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) **Caddy como roteador interno.** O Coolify publica um único domínio, `https://<subdominio>`, no serviço `caddy` (porta interna 80). O Caddy escuta só HTTP em `:80`, sem portas publicadas e sem TLS, e mantém as regras de hoje: `/api/*` para a API, o resto para o Streamlit, `/docs` e `/openapi.json` fora, e os headers de segurança. O Caddyfile vai embutido numa imagem própria (`infra/docker/caddy.Dockerfile`), sem bind | As regras de roteamento e de segurança continuam no repositório, versionadas e testadas no CI (`caddy adapt`, testes `docker` das SPECs 015, 032 e 038); um único domínio no painel, no caminho `/`, sem depender do comportamento não documentado do `stripprefix` em Compose; a API e o dashboard continuam sem domínio próprio; o `handle_errors` da SPEC-038 continua valendo; a imagem do Caddy fica imutável por commit, como a da API e a do dashboard | Um salto a mais (Traefik → Caddy → serviço) e um contêiner de até 256 MB; os erros gerados pelo próprio Traefik (Caddy fora do ar) saem sem os nossos headers; uma imagem e um `.dockerignore` a mais |
| B **Caddy sai.** Dois domínios no Coolify: `https://<subdominio>` no `dashboard` (8501) e `https://<subdominio>/api` na `api` (8000), com "Keep paths as-is"; headers por labels de middleware do Traefik | Um contêiner e um salto a menos; o Coolify gerencia tudo | Depende de o "Keep paths as-is" valer para Compose (não documentado): com o prefixo removido, `/api/v1/...` chega como `/v1/...` e a API responde 404; headers e `-Server` passam a depender de labels do Traefik, que o CI não consegue testar sem o Traefik; perdem sentido os testes do Caddy das SPECs 015, 032 e 038 e o `handle_errors`; a política de borda sai do repositório para o painel |
| C **Raw compose** com labels do Traefik escritas à mão | Controle total do roteamento | O arquivo passa a depender de nomes internos do Coolify (entry points, resolvedor, rede); "Coolify cannot repair missing proxy or networking configuration in an as-is deployment"; frágil a cada atualização do Coolify |
| D Manter o Caddy com TLS próprio (outra porta, ou TCP passthrough no Traefik) | Mudaria pouco o compose | Contraria o pedido (domínio e certificado no painel do Coolify), exige mexer na configuração do proxy compartilhado e duplica a emissão de certificados |

**Como o Caddyfile chega ao contêiner (dentro da opção A):** embutido numa imagem própria (escolhido) ou por bind `./Caddyfile` com "Preserve repository during deployment". O bind foi descartado porque o Coolify trata um bind curto como diretório por padrão e exige o arquivo antes do deploy. Um erro aí cria um diretório no lugar do arquivo, e o Caddy não sobe.

**Segredos (dentro da opção A):** variáveis do recurso no painel do Coolify, referenciadas no compose como `${NOME:?}` no `environment` (escolhido), ou arquivos `env_file` criados à mão na VPS. Estes foram descartados: seriam um `.env` editado à mão fora do checkout, num diretório que o Coolify reescreve a cada deploy, e o caminho relativo do `env_file` depende do diretório do projeto que o Coolify escolhe.

**Isolamento dos segredos entre os serviços (emenda 1).** Como o Coolify entrega o `.env` do recurso a todos os serviços dele (fatos da emenda 1), um único recurso daria a `DATABASE_URL`, a `READ_API_KEY` e o `TELEGRAM_BOT_TOKEN` ao Streamlit público e ao Caddy, contra o checklist §6 ("`DATABASE_URL` nunca fora da API") e a SPEC-028 §4.6. Opções:

| Opção | O que garante | Custo e o que quebra | Manutenção a cada atualização do Coolify |
|---|---|---|---|
| a) Aceitar o risco, com exceção registrada | Nada: o dashboard e o Caddy ficam com acesso de escrita ao banco pelo ambiente | Nenhum código; exceção à SPEC-028 §4.6 e ao checklist §6; o CA-02 deixa de valer em produção | Nenhuma |
| b) Segredo da API por arquivo (storage do Coolify montado só na `api`, `DATABASE_URL_FILE`) | Só a `api` lê o arquivo | Código novo na API (SPEC nova do developer), o mesmo para o `TELEGRAM_BOT_TOKEN`; o conteúdo do arquivo fica no painel, fora das variáveis; bind de arquivo é o caso que o ADR já evitou para o Caddyfile (diretório criado no lugar do arquivo); a `READ_API_KEY` continua no Caddy | Depende de como o Coolify trata os storages de Compose |
| **c) Dois recursos (escolhida):** `partqc-api` só com a `api`; `partqc-web` com o `caddy` e o `dashboard`. O Caddy chega à `api` por uma rede dedicada `partqc-api-link` (`internal`), criada pelo compose do `partqc-api` e declarada `external` no `partqc-web` | Cada `.env` só chega aos serviços do próprio recurso: a `DATABASE_URL` e o `TELEGRAM_BOT_TOKEN` existem só na `api`. O arquivo do `partqc-web` nem referencia esses nomes, então o Coolify nem cria as variáveis nele | Nenhum código da API ou do dashboard; um compose a mais (`infra/compose.api.yaml`); dois recursos no painel, com a `READ_API_KEY` repetida nos dois; ordem no primeiro deploy (`partqc-api` antes); o Caddy recebe a `READ_API_KEY` (aceito: ele já a vê no header de cada requisição) | Conferir o `Config.Env` dos contêineres e a rede (SPEC-039, CA-20) |
| c') Dois recursos com "Connect to predefined network" | O mesmo isolamento dos segredos | A `api` passa a ser alcançável por todos os contêineres da rede `coolify` (o próprio Coolify e os outros projetos), inclusive o `/docs`, sem passar pelo Caddy; o nome `api` pode colidir com o de outro projeto, e o Caddy mandaria requisições com chaves para ele | Nomes com prefixo variável |
| c'') Dois recursos com a rede `<uuid>` do `partqc-api` como `external` (`name: ${VAR}`) | O mesmo isolamento | Uma variável a mais com o UUID; a rede é removida pelo Coolify ao parar o recurso da API (`deleteConnectedNetworks`) | Reserva, se a rede própria da opção c não for mantida pelo Coolify |
| c''') Três recursos (o Caddy sozinho) | Tira também a `READ_API_KEY` do Caddy | Três recursos, duas redes de ligação e mais ordem de deploy, para um ganho pequeno (o Caddy vê a chave em trânsito) | Maior |
| d) Modo Raw | O Coolify não acrescenta o `env_file` | Sem labels geradas: o arquivo teria de escrever as do Traefik com nomes internos do Coolify (opção C, já descartada) | Frágil |

## Decisão

A `qc-api` e o `qc-dashboard` passam a ser publicados pelo **Coolify** já instalado na VPS pessoal, como **dois recursos "Docker Compose" a partir do repositório público no GitHub** (emenda 1), os dois com branch `main` e Base Directory `/infra`:

- `partqc-api`: Docker Compose Location `/compose.api.yaml`, só o serviço `api`, sem domínio;
- `partqc-web`: Docker Compose Location `/compose.yaml`, os serviços `caddy` e `dashboard`.

O **TLS e o domínio** ficam no proxy do Coolify (Traefik), configurados no campo de domínio do serviço `caddy` do `partqc-web` como `https://<subdominio>:80`. **Nenhum serviço do PartQC publica portas**, e o **Caddy fica só como roteador interno** em HTTP, com o Caddyfile embutido numa imagem própria. O Supabase continua sendo o banco (ADR-006, ADR-008), e o Render continua como reserva fria da API (ADR-018).

Regras que passam a valer (detalhadas na SPEC-039; as demais regras do ADR-018 continuam):

1. **Rede:**
   - nenhum serviço tem `ports`, e o compose não declara labels `traefik.*` nem `coolify.*` (o Coolify gera as dele);
   - só o serviço `caddy` tem domínio no Coolify, no caminho `/`. A `api` e o `dashboard` não têm domínio;
   - a rede própria `partqc` e o alias do subdomínio saem; os serviços usam a rede do projeto (e o Coolify acrescenta a dele);
   - (emenda 1) o Caddy chega à `api`, que está no outro recurso, pela rede `partqc-api-link`, com `internal: true`, criada pelo `infra/compose.api.yaml` e declarada `external` no `infra/compose.yaml`. O `reverse_proxy api:8000` do Caddyfile não muda. O Coolify liga essa rede também ao `dashboard` (todas as redes do topo vão a todos os serviços do recurso), o que repete o alcance que ele já tinha no recurso único;
   - nunca ligar "Connect to predefined network" em nenhum dos dois recursos.
2. **Caddy:**
   - site `:80`, sem nome de host e sem TLS (o HTTPS automático não se ativa);
   - mantém o roteamento, o bloqueio de `/docs` e `/openapi.json` e os headers da SPEC-032; o `handle_errors` da SPEC-038 entra no mesmo bloco;
   - **sem healthcheck**, porque o Traefik tira da rota um contêiner `unhealthy`, e a falha da API (por exemplo, com o Supabase pausado) derrubaria também o painel;
   - sem estado persistente: `/data` e `/config` em `tmpfs`, porque os certificados agora ficam no proxy do Coolify. Os volumes `caddy_data` e `caddy_config` saem.
3. **Segredos e variáveis (R-03; reescrita pela emenda 1):**
   - **no Coolify, quem delimita as variáveis de um serviço é o recurso, e não o `environment`:** todo serviço recebe o `.env` com todas as variáveis de runtime do seu recurso. Por isso, os segredos ficam divididos entre os dois recursos:
     - `partqc-api`: `DATABASE_URL`, `READ_API_KEY`, `MAX_BODY_BYTES`, `LOG_LEVEL`, os limites `API_*` e, por decisão do humano de 2026-10-25, as variáveis `ALERTS_*` e `TELEGRAM_*` da SPEC-017, com os padrões dela, que deixam os alertas desligados;
     - `partqc-web`: `PUBLIC_HOST`, `READ_API_KEY` (o mesmo valor), `MODEL_METRICS_PATH` e os limites `DASHBOARD_*` e `CADDY_*`;
   - a `DATABASE_URL`, o `TELEGRAM_BOT_TOKEN` e as demais variáveis de alertas **nunca** existem no `partqc-web`. O `infra/compose.yaml` nem cita esses nomes, para o Coolify não criar as variáveis nesse recurso;
   - o `caddy` recebe a `READ_API_KEY` e o `PUBLIC_HOST` pelo `.env` do `partqc-web`. Custo aceito: a chave de leitura passa pelo Caddy, no header, em toda requisição do dashboard;
   - proibido tentar "apagar" uma variável num serviço com valor vazio (`NOME: ""`): o Coolify a troca pelo valor salvo;
   - os segredos ficam com escopo **só de runtime** (fora do build), **Locked** e interpolação **Literal**, desde antes do primeiro deploy: uma variável com o build ligado vira `ARG` nos Dockerfiles e pode ficar numa camada de imagem;
   - nenhum `.env` é criado à mão na VPS, e nenhum checkout manual é feito nela;
   - o compose referencia cada segredo como `${NOME:?}` no `environment` do serviço que o usa, nunca com valor. Isso continua valendo na execução local, e o CA-02 da SPEC-039 o confere; em produção, o isolamento vem da divisão em recursos (CA-19 e CA-20 da SPEC-039);
   - o `.dockerignore` por Dockerfile passa a proteger também o `.env` que o Coolify grava no diretório de cada recurso (`infra/.env` dentro do contexto de build). Na `api` e no `dashboard`, ele também exclui `infra/`, onde o Coolify grava o compose processado (SEC-39-02).
4. **Dashboard → API:** `API_BASE_URL=https://${PUBLIC_HOST}` continua, e a recusa de `http://` da SPEC-028 também. Sem o alias, o nome resolve pelo DNS público, e a conexão volta à própria VPS pelo proxy do Coolify, com TLS verificado.
5. **Deploy automático e rollback** (decisão do humano de 2026-10-25, que substitui o deploy manual proposto na primeira versão e a decisão 8 do ADR-018):
   - **cada merge na `main` dispara o deploy**, por **webhook manual** com segredo do GitHub para o Coolify (Auto deploy = Deploy on push). O GitHub App foi descartado: daria ao Coolify um app com acesso à conta do GitHub e uma chave privada, para um repositório que já é público;
   - sem Watch Paths: todo merge publica (o cache do build deixa barato o merge só de documentação), porque a documentação não diz se os caminhos são relativos à raiz ou ao Base Directory, e um padrão errado deixaria de publicar em silêncio;
   - **o segredo do webhook (R-03)** fica só em dois lugares: o campo Webhook secret do Coolify e as configurações de webhook do repositório no GitHub. Nunca no Git, nos Secrets do Actions, em issue, PR ou log. Gerado com o gerador do Coolify ou com `secrets.token_urlsafe(32)`. Se vazar: um segredo novo nos dois lugares, na mesma sessão;
   - (emenda 1) **um único webhook no GitHub e o mesmo segredo nos dois recursos**, os dois com Auto deploy na branch `main`: o Coolify confere cada recurso com o próprio segredo, e um segredo diferente geraria um `invalid_signature` a cada entrega. Cada merge dispara dois deploys, um por recurso;
   - a URL do webhook contém o endereço do painel do Coolify, que também não entra no repositório (R-13);
   - **o que isso exige do processo:**
     - a `main` precisa estar sempre publicável. Um merge é um deploy em produção;
     - o merge continua só com o portão da R-09: CI verde (`ci` e `docker`, que constrói as imagens), PASS e APPROVED (e o security-report, quando a SPEC tem a tag `security`/`deploy`). PRs só de `docs/` também disparam um deploy, sem efeito no comportamento;
     - uma SPEC que acrescente variável obrigatória (`${NOME:?}`) ao compose só é mergeada depois de o humano criar a variável no painel. Senão, o Coolify bloqueia o deploy (ADR-023, Contexto);
     - mudanças de contrato seguem "API primeiro": o merge da API vai à produção sozinho, e a borda só é atualizada depois;
     - nenhum merge na véspera nem no dia da apresentação (`docs/deployment-plan.md` §5);
   - **deploy com falha:** a documentação não diz o que acontece com a versão em execução. Pelo código, um erro de build para antes do `up -d`. Depois de cada merge, quem mergeou confere o log de deploy e roda o smoke. Se falhou ou se o smoke reprovar, faz o rollback por branch e abre uma correção por PR;
   - **rollback:** uma branch temporária `deploy/rollback` no commit anterior, selecionada nos dois recursos (emenda 1), e a volta para a `main` depois. Enquanto o recurso aponta para `deploy/rollback`, os pushes na `main` não disparam deploy (a branch não casa). Ao voltar para a `main`, clicar em Deploy. O rollback por imagens do painel não está documentado para Compose;
   - nenhum segredo de acesso à VPS (SSH, token da API do Coolify) vai para o GitHub, e o Actions não entra na VPS.
6. **Coexistência:** nunca reiniciar, parar nem reconfigurar o `coolify-proxy` nem as configurações do servidor no Coolify por causa do PartQC. As proibições de firewall e de `prune` do ADR-018 continuam.
7. **Identidade (R-13):** o subdomínio fica só no painel do Coolify (campo de domínio e `PUBLIC_HOST`). A documentação continua com `<subdominio>`.

Texto proposto para a **N-05** de `docs/rules.md` (aplicado pelo orquestrador, a pedido do humano, depois do aceite):

> | N-05 | Hospedagem | API e dashboard na VPS pessoal do humano, publicados pelo Coolify já instalado nela (recurso Docker Compose a partir do repositório público; domínio e TLS no proxy do Coolify; Caddy só como roteador interno), num subdomínio pessoal; banco no Supabase Free; Render como reserva fria da API | ADR-023 (substitui em parte o ADR-018; banco: ADR-008) |

A R-01 não muda: o Coolify é software livre auto-hospedado, já estava instalado na VPS pessoal preexistente e não gera custo.

## Consequências

- **Positivas:**
  - a nuvem passa a subir na VPS real sem tocar no proxy nem no portfólio;
  - o certificado e a renovação ficam com o Coolify; o volume de certificados do Caddy e o risco do `down -v` somem do PartQC;
  - os segredos saem dos arquivos editados à mão na VPS;
  - as regras de borda (rotas, `/docs`, headers, `handle_errors`) continuam testáveis no CI.
- **Negativas / custos aceitos:**
  - o PartQC depende de comportamentos do Coolify, alguns não documentados (§ Contexto, itens 1 a 7), conferidos à mão em cada atualização relevante do Coolify;
  - os erros gerados pelo próprio proxy do Coolify (contêiner do Caddy parado ou removido da rota) e o redirecionamento HTTP → HTTPS saem sem os nossos headers;
  - os segredos ficam no banco do Coolify e num `.env` gravado por ele no disco da VPS, legível pelo `root`. A VPS é de um único usuário (o humano);
  - o rollback por branch temporária é mais lento que o `git checkout` na VPS;
  - com o deploy automático, um merge é um deploy em produção: um erro que passe pelo CI chega ao painel sem passo humano no meio, e o GitHub precisa alcançar a URL do painel do Coolify pela internet;
  - a VPS e o proxy do Coolify continuam sendo um ponto único de falha, compartilhado com o portfólio. A mitigação continua a mesma: outbox na borda e reserva no Render;
  - os testes de aceite das SPECs 015, 032 e 038 que descrevem o compose e o Caddyfile antigos são ajustados pelo tester da SPEC-039 (regra de `docs/architecture.md` §10);
  - (emenda 1) dois recursos para configurar e acompanhar, com a `READ_API_KEY` repetida (a troca da chave é feita nos dois) e o segredo do webhook repetido; o `partqc-api` tem de existir antes do primeiro deploy do `partqc-web`, e depois de uma limpeza que apague a rede `partqc-api-link`, porque o `partqc-web` falha sem ela; a `READ_API_KEY` também fica no ambiente do Caddy;
  - (emenda 1) o isolamento depende de um comportamento do Coolify que a documentação não descreve (o `env_file` por recurso), conferido no código e, na VPS, pelo CA-20 da SPEC-039, que é repetido a cada atualização do Coolify.
- **O que passa a ser obrigatório:**
  - a SPEC-039 (manutenção do deploy para o Coolify, `security-devops`) `Done` **antes** dos CAs manuais da SPEC-015 e do CA-09 da SPEC-032;
  - a SPEC-015 com os passos humanos e os CAs manuais refeitos para o Coolify, e o `docs/deployment-plan.md` reescrito (feito junto com este ADR, aguardando aprovação);
  - a SPEC-038, Parte B, ajustada ao Caddy em `:80` e aos comandos do Coolify (nota na própria SPEC), e mergeada depois da SPEC-039;
  - uma SPEC que acrescente variáveis à API ou ao dashboard também as declara no `environment` do compose como `${NOME}` (a mudança do compose é do `security-devops`), em vez de citar o `infra/.env.api`. As da SPEC-017 já entram pela SPEC-039, como opcionais e desligadas por padrão;
  - o webhook com segredo configurado no Coolify e no GitHub, e o CA-18 da SPEC-039 (um merge de teste dispara o deploy, e o log não mostra segredos);
  - (emenda 1) os dois recursos e a rede `partqc-api-link` (SPEC-039 §4.1 e §4.1A); o CA-19 (simulação do `env_file` do Coolify no CI) e o CA-20 (manual: `Config.Env` de cada contêiner, só os nomes) da SPEC-039; o CA-20 de novo depois de cada atualização do Coolify;
  - (emenda 1) uma variável nova da API entra só no `infra/compose.api.yaml` e no `partqc-api`; uma do dashboard, só no `infra/compose.yaml` e no `partqc-web`. Nenhum segredo da API entra no `infra/compose.yaml`;
  - depois do aceite: o status do ADR-018 vira "Substituído em parte por ADR-023", e a N-05 recebe o texto acima (pelo orquestrador);
  - `docs/architecture.md` §1, §2, §8 e §9 anotados "a partir da SPEC-039".

## Quando revisitar

- Se a SPEC-039 mostrar que o Coolify não respeita o compose (build com `context: ..`, limites ou endurecimento descartados): avaliar o layout com Base Directory `/` ou a opção C, com ADR novo.
- Se um merge com CI verde quebrar a produção mais de uma vez, ou perto da apresentação: avaliar desligar o Auto deploy (voltar ao botão) ou adotar Watch Paths, com emenda deste ADR.
- Se o segredo do webhook vazar ou o GitHub registrar entregas não assinadas aceitas.
- Se o humano tirar o Coolify da VPS ou trocar o proxy dele (por exemplo, para o Caddy do Coolify).
- Se o Traefik do Coolify passar a acrescentar headers que conflitem com os do Caddy (HSTS com `includeSubDomains`, por exemplo).
- Se for preciso um caminho público novo fora de `/api/*` e do Streamlit (por exemplo, publicar o `/docs`, decisão 4 do ADR-018).
- Os gatilhos do ADR-018 sobre a VPS (upgrade pago, queda de mais de 24 h, pergunta 8 ao professor, pausa do Supabase) continuam.
- (emenda 1) Se o CA-20 da SPEC-039 mostrar `DATABASE_URL` ou `TELEGRAM_BOT_TOKEN` fora da `api`, ou se o Coolify não mantiver a rede `partqc-api-link` (`internal`, ligada à `api`, ao `caddy` e ao `dashboard`): parar o `partqc-web`, trocar a senha do banco se ela vazou e avaliar a opção c'' ou a b, com emenda deste ADR.
- (emenda 1) Se o Coolify passar a oferecer variáveis por serviço ou deixar de acrescentar o `env_file` a todos os serviços: avaliar a volta a um único recurso.

## Histórico

| Data | Mudança | Quem decidiu |
|---|---|---|
| 2026-10-25 | ADR redigido (`Proposto`): Coolify, TLS no proxy dele, Caddy como roteador interno, deploy manual pelo botão | Architect, a pedido do humano |
| 2026-10-25 | Decisões do humano sobre o PR #55: (1) **opção A aprovada** (Caddy como roteador interno); (2) **deploy automático por webhook a cada merge na `main`**, no lugar do deploy manual: webhook manual com segredo (só no painel do Coolify e nas configurações do repositório no GitHub, R-03), sem GitHub App e sem Watch Paths; a `main` sempre publicável, merge só pelo portão da R-09, rollback por branch mantido (decisão 5, fontes de 2026-10-25 no Contexto); (3) as variáveis `ALERTS_*` e `TELEGRAM_*` da SPEC-017 entram já pela SPEC-039 como opcionais, com os padrões da 017 (alertas desligados), para a 017 não precisar mudar o compose (decisão 3); (4) o 502 com headers (`handle_errors`) fica na SPEC-038, e a SPEC-039 entra agora, direto na `main`. O status continua `Proposto` até o aceite formal | Humano (Carlos) |
| 2026-10-25 | **Emenda 1 (proposta, aguardando aprovação humana)**, para o SEC-39-01 (`reviews/SPEC-039/r1-security-report.md`): fora do Raw, o Coolify entrega o `.env` com todas as variáveis de runtime do recurso a todos os serviços, então a premissa da decisão 3 ("o `environment` do serviço que o usa" delimita o segredo) não vale. Mudanças: fatos novos no Contexto (código-fonte `v4.x` e `v4.5.0`, consultado em 2026-10-25) e item 9 do que não está claro; tabela de opções do isolamento; Decisão com **dois recursos** (`partqc-api` só com a `api`; `partqc-web` com o `caddy` e o `dashboard`); decisão 1 com a rede `partqc-api-link` e a proibição de "Connect to predefined network"; decisão 3 reescrita (variáveis por recurso, `READ_API_KEY` aceita no Caddy, proibição do valor vazio, build desligado antes do primeiro deploy, `infra/` fora das imagens da `api` e do `dashboard`); decisão 5 com o mesmo segredo de webhook nos dois recursos e o rollback nos dois; consequências, obrigações e gatilhos novos. Antes, a decisão 3 dizia que os segredos ficavam "nas variáveis do recurso" e eram referenciados "no `environment` do serviço que o usa" | Architect, a pedido do orquestrador (SPEC_ISSUE SEC-39-01) |
| 2026-10-25 | Emenda 1 aceita pelo humano: dois recursos (`partqc-api` e `partqc-web`) ligados pela rede `partqc-api-link`; `READ_API_KEY` aceita no Caddy; o painel do Coolify é público, então o 2FA do usuário é ligado antes do webhook. | Respostas do humano de 2026-10-25 | Orquestrador, a pedido do humano |
