# SPEC-039 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r2 |
| Revisor de segurança | reviewer (o autor é o security-devops, `reviews/README.md`) |
| Diff revisado | `b12e515..4aacaa1`: a correção do SEC-39-01 e a r2, depois do `r1-security-report.md`. A base de merge é `ff60d34`, igual à `origin/main`, e o diff completo `origin/main...4aacaa1` também foi relido nos arquivos de produção. |
| **Veredicto** | **PASS** |

O SEC-39-01 está fechado no repositório e no CI. O que os testes não alcançam é o Coolify instalado na VPS, e isso fica com o CA-20 (manual). Os SEC-39-02, 03 e 04 também estão fechados. O SEC-39-05 continua aberto como observação baixa: o Histórico da SPEC diz que ele virou nota, mas a nota não existe em nenhum arquivo. Há um achado baixo novo (SEC-39-06). Nenhum achado bloqueante, alto ou médio, e nenhum `SPEC_ISSUE`.

## Superfície analisada

- **Produção:**
  - `infra/compose.api.yaml` (novo): recurso `partqc-api`, só a `api`, com a rede `partqc-api-link` `internal`;
  - `infra/compose.yaml`: recurso `partqc-web`, com `caddy` e `dashboard` e a rede `partqc-api-link` `external`;
  - a linha `infra/` nos `.dockerignore` da API e do dashboard;
  - `.env.example`.
- **Documentação:**
  - SPEC-039 §4.1, §4.1A, §4.8, CA-19 e CA-20;
  - ADR-023, emenda 1;
  - `docs/deployment-plan.md` §3, §4 (passos 4 a 7A), §6, §7 e §9;
  - `docs/architecture.md` §1, §2, §8 e §9;
  - N-05 em `docs/rules.md`.
- **Código do Coolify:** o mesmo código-fonte público que li na r1 (`coollabsio/coolify`, branch `v4.x`, baixado em 2026-10-25 numa pasta temporária fora do repositório, só para leitura), mais `bootstrap/helpers/docker.php`. Não houve nenhum acesso à VPS nem ao painel.
- **Verificações que executei**, sem `TEST_DATABASE_URL` e sem `CI`:
  - `uv run ruff check .` e `ruff format --check .`: limpos (239 arquivos);
  - `uv run pytest -q infra/tests`: 453 passed e 383 skipped (banco e docker);
  - `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests`: 92 passed, nenhum teste docker pulado;
  - limpeza: não sobrou nenhum contêiner, rede (inclusive `partqc-api-link`) ou imagem do teste. Os contêineres `partqc-pg*` já existiam e não foram tocados.

## SEC-39-01 contra o comportamento real do Coolify

Conferi cada comportamento que causou o achado contra a correção:

| Comportamento do Coolify (código) | Efeito com dois recursos | Resultado |
|---|---|---|
| `env_file: ['.env']` em todos os serviços **do recurso** (`ApplicationDeploymentJob.php:833`, `parsers.php:2289`) | O `.env` é por recurso. O `partqc-web` só tem `caddy` e `dashboard`, e o `.env` dele não tem nenhuma variável da API. | ✅ |
| O `.env` com **todas** as variáveis de runtime do recurso (`generate_runtime_environment_variables`) | O Coolify cria as variáveis a partir das referências `${...}` do arquivo do recurso (`parsers.php`, por volta da linha 1839). O `infra/compose.yaml` não contém `DATABASE_URL`, `TELEGRAM_` nem `ALERTS_`, nem em comentário (§4.1 item 8, CA-02 e um teste extra). Então essas variáveis só existiriam no `partqc-web` se alguém as criasse à mão. O plano proíbe isso (passo 5, item 3) e o CA-20, passos 1 a 3, confere. | ✅ |
| Valor vazio trocado pelo valor salvo (`parsers.php:2115`) | Nenhum `NOME: ""` nos dois arquivos (§4.1 item 8 e um teste extra). A proibição está no ADR e no plano. | ✅ |
| As redes do topo vão para **todos** os serviços do recurso (`parsers.php`, laço sobre `topLevel['networks']`, linhas 1700 a 1715) | O `dashboard` também entra na `partqc-api-link`. A SPEC aceita isso (§4.1 item 4) e o plano registra (§7 item 10). No `partqc-api`, o único serviço é a `api`. | ✅ aceito |
| O dashboard sem `networks` próprio ganha, no Coolify, só a rede do topo e a `<uuid>`, e não a `default` | A rede `<uuid>` é criada com `docker network create --attachable`, sem `--internal` (`ApplicationDeploymentJob.php:949`), então o dashboard continua com saída para o hairpin `https://<subdominio>`. O Caddy e o dashboard se encontram na `<uuid>` e na `link`. | ✅ |
| Redes declaradas no topo são mantidas com `name`, `internal` e `external` (`parsers.php:1158`); o Coolify só cria a rede `<uuid>` | A `partqc-api-link` é criada só pelo compose do `partqc-api`, com `internal: true`. No `partqc-web` ela é `external`, e o deploy falha fechado se ela não existir. Um nome igual criado fora do projeto também falha, porque o compose recusa a rede sem os rótulos dele. Nenhum dos dois casos abre uma rede sem `internal`. | ✅ |
| O `coolify-proxy` é ligado só à rede `<uuid>` de cada recurso (`ApplicationDeploymentJob.php:953`), e o Traefik usa essa rede (`traefik.docker.network`) | O proxy não entra na `partqc-api-link`, e o CA-20, passo 4, espera exatamente 3 contêineres nela. O proxy alcança a `api` pela `<uuid>` do `partqc-api`, mas não a roteia: um serviço sem domínio não recebe nenhuma label `traefik.*` (`defaultLabels` em `docker.php:651` só põe `coolify.*`). | ✅ |
| "Connect to predefined network" poria a `api` na rede `coolify`, compartilhada com o portfólio | Desligado nos dois recursos (plano passo 4, CA-15 passo 2), com o motivo escrito e a proibição em §7. | ✅ |

**O CI confere o que é possível conferir sem o Coolify:**
- o CA-19 reproduz o `env_file` e o `.env` por recurso, com as variáveis extraídas das referências de cada arquivo, e confere que nenhum nome ou valor da API chega ao `caddy` ou ao `dashboard`;
- o controle negativo do tester (`test_ca19_negative_control_one_resource_would_leak`) mostra que o teste pegaria o vazamento com um recurso único;
- o CA-12 e um teste extra confirmam que a `api` só é alcançável pela rede de ligação, que é `--internal`.

**Na VPS:** o CA-20 é o teste certo. Ele confere:
- o `Config.Env` de cada contêiner, cortando os nomes antes do `grep`, sem imprimir valores;
- `supabase` fora do `caddy` e do `dashboard`, o que pega a string de conexão mesmo sob outro nome;
- a `partqc-api-link` com `Internal=true` e exatamente 3 contêineres.

Ele diz o que fazer se falhar (parar o `partqc-web`, trocar a senha do banco ou o token) e é repetido a cada atualização do Coolify.

**A rede `partqc-api-link` não expõe a `api` a nada além do `caddy` e do `dashboard`:**
- ela é `internal`, então não serve de saída nem de entrada pelo host;
- ninguém publica porta;
- o proxy não entra nela;
- nenhum outro recurso a declara;
- entrar nela exige acesso ao Docker da VPS, que já é `root`.

O `dashboard` alcança a `api` direto, inclusive o `/docs` interno, mas a API continua exigindo as chaves de sempre. É o mesmo alcance que ele tinha no recurso único, e o humano aceitou.

## Riscos da emenda

| Risco | Avaliação |
|---|---|
| Dois recursos | Mais configuração, mas cada segredo fica num lugar só (tabela da §4.1A e plano §3). A `READ_API_KEY` repetida exige trocá-la nos dois recursos, e o plano (§8) diz a ordem e o efeito (401 por alguns segundos). |
| Ordem de deploy | `partqc-api` primeiro, porque ele cria a rede. Fora de ordem, o deploy do `partqc-web` falha fechado (rede externa inexistente), sem abrir nada. Em cada merge, os dois deploys correm juntos. A recriação da `api` dá alguns segundos de 502 em `/api/*`, sem efeito de segurança (a borda reenvia pelo outbox). |
| Mesmo segredo de webhook nos dois recursos | Necessário, porque o Coolify confere a assinatura de cada aplicação com o segredo dela (ADR-023, emenda 1, `Github.php`). O segredo continua só nos campos do Coolify e no GitHub, e a troca é feita nos três lugares na mesma sessão (plano, passo 7A, item 5). O ganho de segurança de ter segredos diferentes seria nulo: é o mesmo repositório e a mesma branch. |
| `READ_API_KEY` no ambiente do Caddy | Aceito pelo humano: o Caddy já vê a chave no header de cada requisição do dashboard. O Caddyfile não usa nenhum placeholder de ambiente (`{env.*}` ou `{$...}`), então a chave não aparece em resposta nem em log. Nenhum teste impede esse uso no futuro (SEC-39-06). |
| Painel do Coolify público, com 2FA | O humano informou que o painel é público. O passo 7A manda ligar o 2FA (TOTP, com os códigos de recuperação fora da VPS) antes do webhook, e manda não expor o painel se ele não fosse público. O endpoint do webhook confere HMAC com `hash_equals` e limita as falhas por endereço (fato do ADR-023). Com "Just the push event", PRs de forks não disparam deploy. |
| O isolamento depende de um comportamento não documentado | Registrado nas Consequências do ADR-023, com gatilho em "Quando revisitar", o CA-20 a cada atualização do Coolify e as opções c'' e b de reserva. |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-39-01 | — (era alta) | secrets | `infra/compose.api.yaml`, `infra/compose.yaml`; SPEC §4.1A, CA-19, CA-20 | **Fechado.** Veja a seção acima. A confirmação final no Coolify instalado é o CA-20 (manual, depois do merge), que para o `partqc-web` e manda trocar os segredos se falhar. | — |
| SEC-39-02 | — (era baixa) | privacy | `infra/docker/api.Dockerfile.dockerignore:85`, `dashboard.Dockerfile.dockerignore:85` | **Fechado.** `infra/` agora está fora das imagens, sem negação que reabra. O CA-13 confere que `/app/infra` não existe nas imagens da `api` e do `dashboard`, e as imagens sobem saudáveis no CA-12. | — |
| SEC-39-03 | — (era baixa) | secrets | `docs/deployment-plan.md:230` | **Fechado.** O passo 5, item 4, explica a injeção de `ARG` e manda desligar o build dos segredos **antes** do primeiro deploy. A §4.1A da SPEC e a decisão 3 do ADR dizem o mesmo. | — |
| SEC-39-04 | — (era baixa) | deploy | `docs/deployment-plan.md:252`; SPEC §4.8 item 6 | **Fechado.** O plano diz o que fazer com o painel não público (deploy pelo botão, sem expor) e com o painel público (2FA antes do webhook). O CA-18 trata o caso "não aplicável". | — |
| SEC-39-05 | baixa (continua) | deploy | SPEC-039:481 (Histórico) | O Histórico diz "O SEC-39-05 fica como nota (CA-17 da SPEC-015, fora do repositório)", mas nenhum arquivo traz essa nota. Busquei "CDN" e "SEC-39-05" em `docs/`: só aparece a linha do Histórico. O risco continua pequeno: a `READ_API_KEY` vai sempre com TLS verificado. | Uma frase no `deployment-plan.md` §7 (ou na lista do CA-17 da SPEC-015): "anotar fora do repositório se o DNS do subdomínio passa por proxy de CDN; se passar, a chave de leitura do dashboard sai da VPS até a CDN". Pode entrar junto com o registro dos CAs manuais, sem rodada nova. |
| SEC-39-06 | baixa (novo) | secrets | `infra/Caddyfile`; testes em `infra/tests/acceptance/test_spec_039.py` (CA-04) e `infra/tests/test_coolify_deploy.py` | Com a emenda, o ambiente do Caddy tem a `READ_API_KEY` e o `PUBLIC_HOST`. Hoje o Caddyfile não usa nenhum placeholder de ambiente. Mas nenhum teste impede que uma mudança futura, como o `handle_errors` da SPEC-038 com um `respond` ou um header, use `{env.READ_API_KEY}` ou `{$READ_API_KEY}` e devolva a chave ao cliente. | Na Parte B da SPEC-038, que já mexe no Caddyfile, acrescentar ao CA do Caddyfile que o texto sem comentários não contém `{env.` nem `{$`. Não bloqueia esta SPEC. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa dela; comparação em tempo constante | ✅ Não se aplica ao diff: nenhuma rota nova. `/docs` e `/openapi.json` continuam sem rota no Caddy (CA-04, CA-10, CA-12 e o teste extra das variantes). |
| Entradas validadas | ✅ Não se aplica: nenhum código da API ou do dashboard. |
| SQL sempre parametrizado | ✅ Não se aplica. |
| RLS ligado; `DATABASE_URL` e a `service_role` nunca fora da API | ✅ **Corrigido (SEC-39-01).** A `DATABASE_URL` existe só no `infra/compose.api.yaml` e no recurso `partqc-api`. O CA-02 confere o compose, o CA-19 simula o Coolify e o CA-20 confere na VPS. O RLS não muda. |
| CORS fechado ou mínimo | ✅ Sem mudança. As proteções de CORS e XSRF do Streamlit continuam no padrão. |
| Logs sem segredos e sem payloads de imagem | ✅ O Caddy continua sem log de acesso. O `config` dos testes não é impresso (CA-19, último item). O CA-15 (passo 4), o CA-18 (passo 5) e o CA-20 conferem sem imprimir valores. |
| Dependências novas | ✅ Nenhuma. O `uv.lock` não mudou, e a imagem do Caddy é a mesma, pelo mesmo digest. |
| Deploy: variáveis no provedor, health check, plano free sem cartão | ✅ As variáveis ficam no painel, divididas por recurso, com os segredos só em runtime, Locked e Literal, e `:?` bloqueia o deploy se faltar uma obrigatória. A `api` e o `dashboard` mantêm o healthcheck, e o `caddy` fica sem healthcheck (ADR-023). Nenhum custo novo (R-01): um segundo recurso no mesmo Coolify, na mesma VPS. |
| Reaprovação delegada (ADR-019) | ✅ A correção do SEC-39-01 foi classificada como "exige humano" (X-2, X-3, X-5 e X-7) e **reaprovada pelo humano** (`94282f5`; Histórico, linha de 2026-10-25). A única mudança de texto depois disso (`68e3d96`, RV-06) só troca "aguardando aprovação" por "aceita pelo humano" em três lugares, sem tocar em requisito, CA, limite de segurança ou regra inegociável. Não houve nenhuma reaprovação delegada fora dos limites. |

### Coexistência e separação de papéis

- Nenhuma instrução nova reinicia, para ou edita o `coolify-proxy`. As proibições de `prune` amplo, `down -v`, `ufw` e "Connect to predefined network" continuam.
- O plano proíbe remover à mão a `partqc-api-link`.
- A parada é feita pelo botão **Stop** de cada recurso, primeiro o `partqc-web`.
- **R-07:**
  - produção (`78f6ceb`) do `security-devops`;
  - aceite (`fe5bb12`, `3bde2a2`) do `tester`, só em `infra/tests/acceptance/` e no test-report;
  - SPEC, ADR e arquitetura (`4239a2f`, `68e3d96`) do `architect`;
  - status e N-05 do `orchestrator`.

  Todos os commits têm o trailer. Não sou autor de nenhum commit de produção, de teste ou de SPEC.
- **R-13:** os únicos domínios do diff são fictícios (`*.example.org`), o GitHub e as fontes do Coolify, só nos documentos. Não há subdomínio real, IP, UUID de recurso nem URL do painel. A busca de segredos no diff só encontrou valores fictícios montados em tempo de execução.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. |

## SPEC_ISSUE

Nenhum.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório. O código do Coolify foi lido numa pasta temporária fora do repositório.
- [x] Não sou autor de nenhum commit desta SPEC além dos meus relatórios.
