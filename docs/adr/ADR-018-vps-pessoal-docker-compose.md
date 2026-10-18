# ADR-018: Hospedar a API e o dashboard na VPS pessoal do humano, com Docker Compose e Caddy; o Supabase continua sendo o banco e o Render vira reserva fria

| Campo | Valor |
|---|---|
| Status | Proposto |
| Data | 2026-10-18 |
| Decisores | Humano (Carlos) (redigido pelo agente architect) |
| Relacionados | ADR-008 (substituído em parte), ADR-006, ADR-007, ADR-010, ADR-015, ADR-016 (precedente de mudança de regra inegociável por decisão do humano), ADR-017, SPEC-015, SPEC-028, R-01, R-02, R-03, R-12, R-13, N-05 |

## Contexto

O ADR-008 pôs a API no Render free, o dashboard no Streamlit Community Cloud e o banco no Supabase Free, todos sem cartão (R-01). Em 2026-10-18, antes de a SPEC-015 (deploy) entrar no loop, o humano decidiu publicar a API e o dashboard na **VPS pessoal** dele. A VPS já existia antes do projeto, hospeda outros projetos pessoais (entre eles o portfólio dele, que já usa o Supabase como banco e a VPS para o resto) e é paga uma vez a cada 2 anos. O projeto não muda o plano dela nem gera custo novo. Docker e Docker Compose v2 já estão instalados, e as portas 80 e 443 estão livres (informações do humano, 2026-10-18). A memória e o número de CPUs ainda não foram informados.

Fatos que pesam na decisão (conferidos pelo architect em 2026-10-18, salvo outra data indicada):

| Fato | Fonte |
|---|---|
| O web service free do Render dorme após 15 min sem tráfego, leva cerca de 1 min para acordar e tem 750 h por mês por workspace | <https://render.com/docs/free> |
| O plano free do Render tem 512 MB de RAM e 0,1 CPU (conferido em 2026-10-17) | <https://render.com/docs/compute-plans> |
| O Supabase pausa projetos Free com pouca atividade num período de 7 dias; "a few database requests each day" bastam para evitar a pausa | <https://supabase.com/docs/guides/platform/free-project-pausing> |
| Num repositório público, os workflows agendados do GitHub Actions são desligados depois de 60 dias sem atividade no repositório | <https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows> |
| As portas que o Docker publica passam por fora do `ufw`: "traffic to and from that container gets diverted before it goes through the ufw firewall settings" | <https://docs.docker.com/engine/network/packet-filtering-firewalls/> |
| O HTTPS automático do Caddy exige o DNS do domínio apontando para o servidor, as portas 80 e 443 abertas externamente e o diretório de dados gravável e persistente; o Caddy redireciona HTTP para HTTPS | <https://caddyserver.com/docs/automatic-https> |
| Na imagem oficial do Caddy, "it's very important to persist the data directory" (`/data`, com os certificados e as chaves); a tag estável atual é `2.11.7` | <https://hub.docker.com/_/caddy> |
| O `reverse_proxy` do Caddy suporta WebSocket e repassa os headers de entrada, inclusive o `Host`, sem modificação | <https://caddyserver.com/docs/caddyfile/directives/reverse_proxy> |
| A lista de diretivas padrão do Caddyfile não tem limitação de taxa (`rate_limit` só existe como plugin, num build próprio) | <https://caddyserver.com/docs/caddyfile/directives> |
| Com o BuildKit, que é o builder padrão do Docker Engine, um arquivo `<nome do Dockerfile>.dockerignore` ao lado do Dockerfile tem precedência sobre o `.dockerignore` da raiz do contexto | <https://docs.docker.com/build/concepts/context/>, <https://docs.docker.com/build/buildkit/> |
| O Let's Encrypt emite no máximo 5 certificados por conjunto exato de nomes a cada 7 dias, e todo certificado emitido vai para os logs públicos de Certificate Transparency | <https://letsencrypt.org/docs/rate-limits/>, <https://letsencrypt.org/docs/ct-logs/> |

Dois problemas abertos do ADR-008 ficam resolvidos com a VPS: a instalação do `qc-contracts` local pelo `requirements.txt` no Streamlit Community Cloud nunca foi comprovada (ADR-010, SPEC-015 §4.3 antiga), e o `REPO_ROOT` do dashboard instalado de forma não editável aponta para fora do repositório (RV-06 de `reviews/SPEC-013/r1-review-report.md`).

**Por que isto é um ADR, se a R-01 é inegociável.** O texto atual da R-01 diz "Só free tiers e software livre", e uma VPS não é free tier. Pela `docs/rules.md`, uma regra inegociável não muda durante o projeto, e um agente que a veja como obstáculo deve parar e escalar. Esta mudança **não** partiu de um agente: é uma decisão explícita do humano, de 2026-10-18, que considera que a VPS não fere o espírito da regra, porque é pessoal, já existia e não tem custo adicional para o projeto. O procedimento é o mesmo do ADR-016 com a R-09: o ADR registra o que mudou e as condições, e o texto da R-01 em `docs/rules.md` e o resumo no `CLAUDE.md` são alterados pelo orquestrador a pedido do humano, e não pelo architect. **Texto proposto para a R-01:**

> **Custo adicional R$ 0.** Só free tiers, software livre e a VPS pessoal já existente do humano (ADR-018), sem nenhum upgrade ou recurso pago por causa do projeto. Nenhum serviço novo que exija cartão de crédito. (Alterada por decisão do humano em 2026-10-18, ADR-018.)
>
> Como verificar: o reviewer confere toda dependência ou serviço novo contra o `docs/deployment-plan.md`; a VPS aparece lá como recurso pessoal preexistente, sem custo para o projeto.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) API e dashboard na VPS pessoal, com Docker Compose e um Caddy próprio num subdomínio pessoal; banco no Supabase; Render como reserva fria da API | Sem hibernação nem cold start; a mesma imagem roda localmente e na VPS; resolve o RV-06 e a dúvida do `requirements.txt`; TLS automático; API e dashboard na mesma origem; o humano já opera a VPS | Ponto único de falha numa máquina compartilhada com outros projetos; o deploy e as atualizações viram passo humano (os agentes não têm acesso); sem proteção contra DDoS de provedor; exige mudar o texto da R-01 |
| B Manter o ADR-008 (Render + Streamlit Community Cloud) | Nenhum servidor para manter; R-01 sem mudança | Cold start de cerca de 1 min na API; 512 MB e 0,1 CPU; a instalação do `qc-contracts` no Streamlit CC continua sem prova; o RV-06 depende de instalação editável |
| C Tudo na VPS, inclusive o Postgres (sem o Supabase) | Sem a pausa do banco; um provedor só | Backup, atualização e exposição do banco por conta da dupla numa VPS compartilhada; reescreve o ADR-006 e a SPEC-003 (RLS, pooler, migrações), já entregues |
| D VPS atrás de um proxy reverso já existente no host, em vez de um Caddy próprio | Um proxy só para todos os projetos | Não há proxy nas portas 80/443 (estão livres); acoplaria o PartQC à configuração de outros projetos e tiraria o proxy do repositório |
| E Expor a VPS por um túnel de terceiros (ex.: Cloudflare Tunnel) | Sem abrir portas | Mais um provedor e mais uma conta, para algo que o Caddy com as portas livres já resolve |

## Decisão

A `qc-api` e o `qc-dashboard` rodam na **VPS pessoal** do humano com **Docker Compose** (`infra/compose.yaml`), atrás de um **Caddy** do próprio compose. O Caddy obtém o certificado do Let's Encrypt e é o único serviço com portas publicadas (80 e 443). Tudo fica num **único subdomínio pessoal**: `/api/*` vai para a API e o resto (inclusive o WebSocket `/_stcore/stream`) vai para o Streamlit. O **Supabase continua sendo o banco**, com a regra do ADR-006: a API usa o pooler em modo transaction (porta 6543), e as migrações rodam da máquina do humano com `.env.migrate` (pooler em modo session). O **Render** passa a ser a **reserva fria** da API (`infra/render.yaml`, publicado só num incidente). O **Streamlit Community Cloud** e o **Koyeb** saem do plano.

Regras que passam a valer (detalhadas na SPEC-015):

1. **Imagens:**
   - base `python:3.12.<patch>-slim-<debian>` e `uv` da imagem oficial, ambos com versão fixada;
   - instalação com `uv sync --package <pkg> --frozen --no-dev`, sem `--no-editable` (assim, o `REPO_ROOT` do dashboard é a raiz do checkout dentro da imagem);
   - usuário não root e `HEALTHCHECK`;
   - nenhuma imagem contém torch, torchvision, timm, onnx ou onnxruntime (R-12), e a do dashboard não contém driver de banco.
2. **Contexto de build:** um `.dockerignore` por Dockerfile, em `infra/docker/`, exclui `.git`, todo `.env*` (os arquivos de segredo da VPS ficam dentro do checkout), dados, fotos, pesos do modelo e `notas-locais/` (R-02, R-03, R-14).
3. **Rede:**
   - só o Caddy publica portas; a API e o dashboard ficam só na rede do compose;
   - cada serviço tem limite de memória e de CPU, lidos do `infra/.env` com padrões (API 512 MB, o mesmo envelope do Render e do ADR-017; dashboard 1 GB; Caddy 256 MB), para não disputar a máquina com os outros projetos;
   - os passos humanos de firewall na VPS só conferem ou acrescentam regras, nunca apagam nem reiniciam as de outros projetos.
4. **Rotas públicas:** só `/api/*` chega à API. `/docs` e `/openapi.json` da FastAPI **não** são publicados: ficam acessíveis só localmente. Publicá-los exige uma decisão humana (o humano ainda vai confirmar este item).
5. **Dashboard → API:** o dashboard usa a URL pública `https://<subdominio>`, e a recusa de `http://` da SPEC-028 fica intacta. Para o tráfego não sair da VPS, o Caddy recebe na rede do compose um alias com o nome do subdomínio. O TLS é verificado normalmente.
6. **Identidade (R-13):** o subdomínio e o IP da VPS não entram no repositório. A documentação usa `<subdominio>`, e o valor real fica em `PUBLIC_HOST`, no `infra/.env` da VPS (ignorado pelo Git).
7. **Keep-alive:** o healthcheck do contêiner da API chama `/api/v1/health` a cada 60 s, e esse endpoint faz `SELECT 1` no Supabase. O workflow `keepalive.yml` do ADR-008 continua, como verificação externa a cada 3 dias.
8. **Deploy:** feito só pelo humano, na VPS, com `git pull --ff-only` e `docker compose -f infra/compose.yaml up -d --build`. Nenhum segredo de acesso à VPS (chave SSH, token) vai para o GitHub, e não há deploy automático pelo Actions.

## Consequências

- **Positivas:**
  - fim do cold start e da hibernação da API e do dashboard; o RNF-10 continua coberto pelo outbox nas quedas e atualizações;
  - a imagem do dashboard leva o `metrics.json` e os PNGs de `ml/reports/` do commit publicado, o que resolve o RV-06 sem configuração;
  - o `dashboard/requirements.txt` e o passo de CI que o comparava deixam de existir;
  - a mesma imagem é construída no CI, na máquina da dupla e na VPS;
  - o limite de 512 MB da API, base do dimensionamento do ADR-017, continua valendo (padrão do `mem_limit` na VPS e limite do Render).
- **Negativas / custos aceitos:**
  - a VPS é um ponto único de falha e é compartilhada com outros projetos. Mitigação: limites por serviço, outbox na borda e a reserva no Render;
  - não há proteção contra DDoS de provedor nem limitação de taxa no Caddy padrão. A rajada anônima no pool (SEC-04-02) continua como risco aceito;
  - o subdomínio aparece nos logs públicos de Certificate Transparency. A regra da R-13 é manter o nome fora do repositório, e não escondê-lo do mundo;
  - perder o volume `caddy_data` força uma nova emissão do certificado, e repetir isso pode esbarrar no limite de 5 certificados por semana. Nunca usar `docker compose down -v`;
  - operar a VPS (atualização do sistema e do Docker, disco) é responsabilidade do humano, fora do loop de agentes;
  - os trechos de ADR-002, ADR-006, ADR-007, ADR-009, ADR-010 e ADR-015 que citam o Render, o Streamlit Community Cloud ou a hibernação como caminho principal passam a ser lidos à luz deste ADR (hierarquia de `docs/README.md`).
- **O que passa a ser obrigatório:**
  - o texto novo da R-01 em `docs/rules.md` e no `CLAUDE.md`, e a linha N-05 da tabela de negociáveis com a fonte ADR-018 (pelo orquestrador, a pedido do humano);
  - a SPEC-015 reescrita: Dockerfiles, `.dockerignore`, compose, Caddyfile, workflow das imagens e passos humanos na VPS;
  - nenhum arquivo versionado contém o subdomínio real ou o IP da VPS. O `docs/deployment-plan.md` usa `<subdominio>`;
  - todo serviço novo continua sendo conferido contra o `docs/deployment-plan.md`, com fonte e data (R-01).

## Quando revisitar

- Se a VPS precisar de upgrade de plano ou de recurso pago por causa do projeto (R-01): voltar ao Render (reserva) ou a outro serviço sem cartão, com ADR novo.
- Se a VPS ficar fora do ar por mais de 24 h, ou no dia da demo: ativar a reserva no Render (`docs/deployment-plan.md`).
- Se outro projeto do humano precisar das portas 80/443: compartilhar um proxy único, com ADR novo.
- Se o professor não aceitar a VPS pessoal como a frente "Cloud" da disciplina (pergunta 8 de `docs/professor-questions.md`).
- Se o humano decidir publicar o `/docs` da API.
- Se o Supabase pausar o projeto apesar do healthcheck e do keep-alive.
