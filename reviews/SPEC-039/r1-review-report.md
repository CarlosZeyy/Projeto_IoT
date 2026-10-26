# SPEC-039 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-039](../../docs/specs/SPEC-039-manutencao-deploy-coolify.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...4bea144` (base `ff60d34`, igual à `origin/main`; branch sem conflito) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** na primeira passada; **CHANGES_REQUESTED** depois da correção do SEC-39-01 (veja o adendo no fim) |

O portão de segurança desta SPEC (autor `security-devops`, tags `deploy` e `security`) é feito pelo reviewer numa chamada separada, no `r1-security-report.md`. A seção 6 abaixo registra só o que conferi nesta revisão.

## Achados

Nenhum achado bloqueante, alto ou médio. Quatro achados baixos, todos de texto e fora do código que a SPEC muda:

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `docs/plan.md:78`; `docs/architecture.md:28` | A linha da SPEC-039 no plano e a nota "a partir da SPEC-039" da arquitetura ainda dizem "ADR-023 `Proposto`", mas o ADR está `Aceito` desde 2026-10-25. Não são arquivos do autor: o plano é do orquestrador (este branch só mudou a coluna de status), e a arquitetura é do architect, que não entrou neste diff. | No commit de `Done` da SPEC-039 (início da próxima branch), o orquestrador troca para `Aceito` na linha do plano e pede ao architect a mesma troca em `architecture.md` §1. |
| RV-02 | baixa | `infra/docker/api.Dockerfile:3`, `infra/docker/dashboard.Dockerfile:3`, `.streamlit/config.toml:3` | Os comentários ainda dizem que os segredos chegam "pelo env_file do compose" ou pelo `infra/.env.dashboard (VPS)`. A partir desta SPEC, eles chegam pelo `environment` do compose, com valores das variáveis do recurso no Coolify. É só comentário, sem efeito, e a SPEC §3.2 deixa explicitamente fora os Dockerfiles. O tester confirmou e ampliou o O-01 do dev-report. | Uma linha em cada arquivo numa manutenção futura, por exemplo na Parte B da SPEC-038, que já mexe no deploy. Os comentários dos `.dockerignore` (O-02) podem ficar: o padrão `**/.env*` continua correto, e a §4.6 manda não mexer nessas linhas. |
| RV-03 | baixa | `docs/deployment-plan.md:195` vs. `docs/specs/SPEC-039-manutencao-deploy-coolify.md:323` | O autor moveu **Preserve repository during deployment** de "Advanced" para "General > Build pipeline" no plano, com base na página do build pack Docker Compose conferida em 2026-10-25 (decisão registrada no dev-report). O CA-15, passo 2, da SPEC ainda diz "em Advanced, [...] 'Preserve repository during deployment' [está] desligado". A instrução (desligado) é a mesma e o CA-07 continua satisfeito, então não há ambiguidade sobre o que conferir, só sobre onde fica a opção na interface. | O humano segue o plano ao executar o CA-15 e registra no resultado onde a opção estava. Se o architect revisar a SPEC depois dos CAs manuais, alinha a frase do CA-15 ao plano. Não exige rodada nova nem reaprovação agora. |
| RV-04 | baixa | `infra/tests/acceptance/test_spec_015.py:1548`, `:1564` | `PUBLIC_HOST_RE` e `_env_file_paths` ficaram sem uso depois dos ajustes da §3.1. O tester os manteve de propósito, para não mexer em linhas fora da tabela (o ruff não acusa nomes de módulo sem uso). | Remover numa próxima SPEC que ajuste esse arquivo, registrando a remoção na tabela de ajustes do test-report dela. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Ver detalhes abaixo. |
| 2. Regras inegociáveis | ✅ | Ver detalhes abaixo. |
| 3. Corretude | ✅ | Ver detalhes abaixo. |
| 4. Testes | ✅ | Ver detalhes abaixo. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (239 arquivos); RV-02 e RV-04 são baixos. |
| 6. Segurança | ✅ (parcial; portão completo no `r1-security-report.md`) | Ver detalhes abaixo. |

### 1. Escopo e SPEC

- Todos os itens da §3.1 foram entregues, e nada além deles:
  - `infra/compose.yaml` (§4.1);
  - `infra/Caddyfile` (§4.2);
  - `infra/docker/caddy.Dockerfile` e `infra/docker/caddy.Dockerfile.dockerignore` (§4.3);
  - `.env.example` (§4.4);
  - `docs/deployment-plan.md` (§4.5);
  - os testes do autor (`infra/tests/test_coolify_deploy.py`, mais os ajustes em `test_deploy_files.py` e `test_docker_images.py`);
  - os testes de aceite do tester.
- Os arquivos da §3.2 não foram tocados: `render.yaml`, os Dockerfiles e `.dockerignore` da API e do dashboard, os workflows, o `migrate.py` e o código da API e do dashboard.
- Conferi o compose item por item contra a §4.1:
  - itens 1 a 5 e 9: nenhum `ports`, `expose` 80/8000/8501, sem labels, sem `networks` nem `volumes` no topo ou nos serviços. O `caddy` tem `build` sem `image`, nenhum `environment`, `volumes` ou `healthcheck`, os 3 `tmpfs` exatos e `depends_on` em lista;
  - itens 6 e 7: os dicionários de `environment` são idênticos aos da SPEC, inclusive as 8 variáveis da SPEC-017 com os padrões dela;
  - item 8: `DATABASE_URL` e `READ_API_KEY` na forma `${NOME:?}`, sem padrão nem mensagem;
  - item 10: cabeçalho com Base Directory, Compose Location, domínio só no `caddy`, variáveis no painel e `config --quiet`, sem URL nem domínio.
- Caddyfile (§4.2): um único site `:80`, sem bloco global, sem nenhum token proibido. Os headers e as rotas não mudaram, e os comentários citam o Coolify, o ADR-023 e o `handle_errors` da SPEC-038.
- Dockerfile do Caddy (§4.3): exatamente as três instruções na ordem, com a imagem fixada por tag e digest. O `.dockerignore` tem exatamente `*` e `!infra/Caddyfile`.
- O compose e o Caddyfile são coerentes com o ADR-023: decisões 1 (rede), 2 (Caddy interno sem TLS, sem healthcheck e sem estado), 3 (segredos por `${NOME:?}` no `environment`) e 4 (`API_BASE_URL=https://${PUBLIC_HOST}`, sem alias). Nenhum arquivo do repositório referencia o webhook nem o painel do Coolify (decisão 5).
- Nenhum CA foi alterado ou interpretado. O dev-report traz a rastreabilidade CA → arquivo → teste do autor para os 13 CAs automatizados, e o roteiro dos CAs manuais 14 a 18.
- As decisões do autor no plano (grupo da interface do "Preserve repository", versão de referência do Coolify, texto dos alertas e do `TELEGRAM_BOT_TOKEN` no passo 5) cabem na §4.5 ("confere", "completa") e na §4.1, item 6. A diferença de texto com o CA-15 está no RV-03.
- **ADR-019:** não houve reaprovação delegada nesta branch. O Histórico da SPEC termina na aprovação humana de 2026-10-25, e os commits do orquestrador (`befe5b5`, `5928f69`, `4bea144`) só mudam o status e a rodada.

### 2. Regras inegociáveis

- **R-01:** nenhuma dependência nem serviço novo. O Coolify é software livre auto-hospedado, já instalado na VPS pessoal (ADR-023; `docs/deployment-plan.md` §2), e a imagem base do Caddy é a mesma de antes.
- **R-02 e R-14:** o contexto do Caddy só admite o Caddyfile. Um teste extra do tester planta foto, `.git/config`, `notas-locais/`, `secrets.toml` e `infra/.env.api` no contexto e confirma que nenhum deles chega à imagem.
- **R-03:** nenhum segredo no diff.
  - Busquei `postgres://`, `postgresql://`, `eyJ`, `password=`, `secret=`, `token=`, `ghp_`, `sk-`, IPv4 e UUIDs. As URLs de banco que aparecem são todas fictícias, montadas em tempo de execução com senha gerada por `secrets` (f-string ou concatenação), no host `db.example.org`.
  - O compose não tem nenhum valor literal de segredo.
  - O `.env.example` foi atualizado (nenhuma variável nova, só o texto dos blocos).
  - O `.env` que o Coolify grava em `infra/.env` fica fora das três imagens (CA-13 com sentinelas).
- **R-04:** não se aplica. O formato do payload não mudou.
- **R-05 e R-06:** não se aplicam (nenhum código da API, do simulador ou do dashboard).
- **R-07:** conferi cada commit com `git show --stat` e o trailer `Agent:`. Todos os 6 commits têm o trailer:
  - `c167a17` e `d53707a`, do `security-devops`: produção, docs e `infra/tests/` fora de `acceptance/`, mais o dev-report;
  - `91e2c90`, do `tester`: só `infra/tests/acceptance/` e o test-report;
  - `befe5b5`, `5928f69` e `4bea144`, do `orchestrator`: só o status em `docs/plan.md` e na SPEC.

  Ninguém cruzou a fronteira, e o reviewer não é autor de nenhum commit.
- **R-11 e R-12:** não se aplicam. O `uv.lock` e as dependências não mudaram.
- **R-13:**
  - autor de todos os commits `Carlos Moises <...+CarlosZeyy@users.noreply.github.com>`, todos em Conventional Commits com `Refs: SPEC-039`;
  - os únicos domínios no diff são `partqc.example.org`, `outro.example.org` e `db.example.org` (fictícios), `github.com` (o repositório público e as fontes), `coolify.io` (fontes, só no plano) e `sslip.io`, que só aparece em asserções negativas dos testes;
  - não há subdomínio real, IP, UUID do recurso, URL do painel nem segredo do webhook;
  - nenhuma empresa é citada.

### 3. Corretude

- O `docker compose config` na forma que o Coolify usa é executado de fato pelos CA-08 e CA-09 (do autor e do tester, que passaram aqui):
  - o `context: ..` resolve para a raiz do repositório com `--project-directory <cópia>/infra`;
  - o `-p` prevalece sobre o `name:`;
  - o `:?` falha sem ecoar segredos.
- **Caddy sem healthcheck e API com healthcheck:** com o Supabase pausado, a API fica `unhealthy`, mas o Traefik só roteia para o `caddy`, que não tem healthcheck. O painel não sai do ar, como decide o ADR-023.
- **`X-Forwarded-*`:** o Caddy repassa `X-Forwarded-For` com o IP do Traefik e `X-Forwarded-Proto: http`. Conferi que a API e o dashboard não usam IP do cliente nem `X-Forwarded-*` para nada (nenhuma ocorrência de `forwarded`, `client.host` ou `proxy_headers` no código), então a mudança de topologia não afeta autenticação nem limites. O risco do XSRF/WebSocket do Streamlit está na SPEC §7 e é conferido no CA-17 da SPEC-015.
- **Site `:80` aceita qualquer `Host`:** é esperado pela SPEC §7, porque o Caddy não tem porta publicada e só o proxy do Coolify e a rede do recurso o alcançam. Um teste extra do tester confirma o comportamento.
- **Estado do Caddy:** os 3 `tmpfs` evitam os volumes anônimos do `VOLUME /data /config` da imagem oficial. O CA-12 e um teste extra conferem `.Mounts == []` e a escrita em `/data` e `/config`.

### 4. Testes

- O test-report é PASS e cobre os CAs 01 a 13, com os testes `docker` **executados**. O tester mostrou que CA-01, CA-02, CA-04, CA-05 e CA-06 falham contra os arquivos da `origin/main`, ou seja, os testes não são tautológicos.
- **Reproduzi aqui**, sem `TEST_DATABASE_URL` e sem `CI`:
  - `uv run pytest -q infra/tests` deu 444 passed e 369 skipped (banco e docker);
  - `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests` deu 78 passed, sem nenhum teste docker pulado;
  - depois, não sobrou nenhum contêiner, rede ou imagem `partqc-test*`/`partqc-acc*`. Os dois contêineres `partqc-pg*` presentes na máquina são preexistentes e não foram tocados.
- Nenhum teste usa rede externa, a VPS, o Coolify ou o Supabase. As imagens base vêm do registro no build, como na SPEC-015. Nenhum teste roda a suíte inteira em subprocesso.
- **Ajustes de aceites antigos (§10):** conferi o diff de `test_spec_015.py` e `test_spec_032.py` linha a linha contra a tabela da SPEC §3.1 e a do test-report:
  - todo ajuste está nas duas tabelas e cita o requisito;
  - todo ajuste mantém a intenção do CA antigo: a proibição de segredo literal no CA-29 continua, só passa a aceitar as referências `${NOME:?}` da §4.1, item 8; a falha sem `DATABASE_URL` substitui a falha sem `.env.api`, como manda a tabela;
  - nenhum `test_caNN_` foi removido nem renomeado;
  - os dois renomes atingem só testes `test_extra_` cujo único objeto eram os volumes que saíram. A §3.1 permite explicitamente removê-los ou trocá-los;
  - os 3 itens da tabela que continuaram passando sem ajuste estão registrados;
  - nenhum ajuste está fora da tabela.
- Nenhuma credencial fictícia aparece como literal em URL ou conninfo: chaves, senhas e marcadores vêm de `secrets`.
- A cobertura mínima da RNF-09 não se aplica: não há módulo Python de produção no diff.

### 6. Segurança (o que conferi; o portão completo vai no `r1-security-report.md`)

- **Superfície exposta:** nenhum serviço publica porta. Só o `caddy` recebe domínio, o `:443` do Caddy está fechado (o CA-12 confere a recusa), e `/docs` e `/openapi.json` continuam sem rota, inclusive nas variantes sob `/api/` (teste extra).
- **Endurecimento:** mantido nos 3 serviços:
  - `read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit`, `mem_limit` e `cpus`;
  - `cap_add` só no Caddy, só `NET_BIND_SERVICE`;
  - `tmpfs` com tamanho.

  Se o Coolify preserva esses campos é conferido no CA-16 (manual).
- **Segredos:**
  - os obrigatórios são declarados com `:?`, então o deploy não sobe com variável vazia;
  - nenhum é declarado como build arg;
  - o plano manda deixar em runtime, Locked e Literal `DATABASE_URL`, `READ_API_KEY` e `TELEGRAM_BOT_TOKEN`;
  - `DATABASE_URL` só existe na `api`.
- **Webhook:** o segredo e a URL ficam fora do repositório. Nenhum workflow cita `coolify` ou `webhook`, e o plano só manda guardar o segredo no Coolify e no GitHub, nunca nos Secrets do Actions.
- **Dependências novas:** nenhuma. A imagem `caddy:2.11.7` é a mesma, fixada pelo mesmo digest.

## Pontos positivos

- O compose ficou menor e mais fechado do que o anterior: sem portas, sem volume de certificados, sem `env_file` editado à mão e com os segredos obrigatórios bloqueando o deploy em vez de subir vazios.
- O CA-09 do autor e do tester simula a linha de comando real do Coolify (`--env-file` fora da cópia, `-p`, `--project-directory`), o que tira do campo da suposição o item 1 do Contexto do ADR-023 até onde dá para testar sem o Coolify.
- Os testes `docker` do Caddy usam a imagem construída do `caddy.Dockerfile`, e não a imagem base com bind, então o que se testa é o que vai para a VPS.
- Os relatórios são precisos: o dev-report lista as 17 falhas antigas esperadas antes do tester, e o test-report documenta cada ajuste com o antes e o depois.

## SPEC_ISSUE (se houver)

Nenhum. O RV-03 é uma diferença de texto sobre a localização de uma opção na interface do Coolify, sem impacto no que o CA-15 confere (a opção desligada), e não exige decisão nem reaprovação.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.

---

## Depois da correção do SEC-39-01

| Campo | Valor |
|---|---|
| Origem | SEC-39-01 (`r1-security-report.md`, FAIL do portão de segurança depois do APPROVED acima) |
| Diff revisado | `1e96f2e..34aaf75`: architect `4239a2f`, reaprovação humana `94282f5`, implementação `78f6ceb` e `2960059` (adendo do dev-report), testes `fe5bb12` (adendo do test-report, PASS), status `9d31e4c` e `34aaf75` |
| **Veredicto final** | **CHANGES_REQUESTED** (um achado bloqueante, RV-05; a correção é de uma linha e só do tester) |

### Achados novos

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-05 | **bloqueante** (§10: ajuste fora da tabela) | `infra/tests/acceptance/test_spec_032.py:878-889` | Ao inserir o helper `_resolved_services`, o tester o pôs **entre** o decorador `@pytest.mark.docker` e o `def test_extra_compose_config_resolves_pids_and_override`. O marcador passou para o helper, onde não tem efeito, e o teste antigo da SPEC-032 **perdeu o marcador `docker`**. Conferi:<br>- sem `PARTQC_DOCKER_TESTS`, o teste roda (1 passed) e chama `docker compose`, contra a SPEC-015 §4.14. Numa máquina sem Docker, `uv run pytest` passa a falhar em vez de pular, e o job `ci` passa a executar Docker;<br>- com `-m docker` (o job `docker` do CI), o teste é **desmarcado** (`1 deselected`) e deixa de rodar onde deveria.<br>A tabela de ajustes do test-report (linha do `test_extra_compose_config_resolves_pids_and_override`) registra só a troca do `config` por `_resolved_services`, e não a perda do marcador. Pelo checklist §4, um ajuste em teste de aceite antigo fora da tabela é bloqueante, e este muda quando o teste roda. É o único caso: varri os testes de `infra/tests/` e `infra/tests/acceptance/`, e nenhum outro decorador `docker` está num helper nem há outro teste com Docker sem o marcador. | O tester move o `@pytest.mark.docker` da linha 878 para logo acima do `def test_extra_compose_config_resolves_pids_and_override` e confere com `uv run pytest --collect-only -q -m docker` que o teste volta a ser coletado (e que, sem a variável, ele é pulado). Não precisa de linha nova na tabela, porque o resultado volta a ser o da `main`. |
| RV-06 | baixa | `docs/specs/SPEC-039-manutencao-deploy-coolify.md:14`; `docs/architecture.md:28` | O aviso no topo da SPEC diz "Reaprovada pelo humano [...]" e, na mesma frase, "Até a reaprovação, o status continua `Blocked`", que ficou obsoleta. A nota da arquitetura ainda diz "com a emenda 1 aguardando aprovação", mas a emenda foi aceita em `94282f5`. | O orquestrador e o architect corrigem no commit de `Done`, junto com o RV-01. |

### Situação dos achados da primeira passada

| ID | Situação |
|---|---|
| RV-01 | **Tratado em parte.** O `docs/plan.md:78` já diz "ADR-023 `Aceito`". O `docs/architecture.md:28` mudou, mas continua desatualizado (agora pela emenda 1). O resto ficou no RV-06. |
| RV-02 | **Continua** (baixa). O `infra/docker/api.Dockerfile:3`, o `dashboard.Dockerfile:3` e o `.streamlit/config.toml:3` ainda citam o `env_file` e o `infra/.env.dashboard`. Os Dockerfiles continuam fora da §3.2. |
| RV-03 | **Continua** (baixa). O plano (`docs/deployment-plan.md:209`) põe o "Preserve repository" em General > Build pipeline. O CA-15, passo 2 (`SPEC:392`), ainda diz "em Advanced". A instrução (desligado) é a mesma. |
| RV-04 | **Continua** (baixa). `PUBLIC_HOST_RE` e `_env_file_paths` seguem sem uso em `test_spec_015.py:1548` e `:1564`. |

### O que conferi no delta

- **Coerência com a emenda 1 do ADR-023, a §4.1 e a §4.1A:**
  - `infra/compose.api.yaml` tem `name: partqc-api`, só a `api`, o `environment` idêntico ao do item 6, `networks: [default, link]`, o mesmo endurecimento e, no topo, exatamente `link: {name: partqc-api-link, internal: true}`. O texto não contém `PUBLIC_HOST` nem `MODEL_METRICS_PATH`;
  - `infra/compose.yaml` tem só `caddy` e `dashboard`. O `caddy` tem `networks: [default, link]` e `depends_on: [dashboard]`, e o `dashboard` não tem `networks`. No topo, exatamente `link: {name: partqc-api-link, external: true}`. O texto, inclusive os comentários, não contém `DATABASE_URL`, `TELEGRAM_` nem `ALERTS_`;
  - nenhum valor vazio (`NOME: ""`), nenhuma porta, label, volume ou `env_file`;
  - os cabeçalhos dos dois arquivos explicam o recurso, a Compose Location, o domínio só no `caddy`, as variáveis por recurso e a ordem do primeiro deploy;
  - o `.env.example` e o plano trazem a divisão da §4.1A, a ordem `partqc-api` → `partqc-web`, o SEC-39-03 (injeção de `ARG` com o build ligado) e o SEC-39-04 (painel não público: só o botão; público: 2FA).
- **SEC-39-02:** os dois `.dockerignore` ganharam só a linha `infra/`, sem exceção `!infra`. Conferi que nem a API, nem o dashboard, nem os Dockerfiles leem nada de `infra/`, e que `infra/` não é membro do workspace.
- **CA-19:** a simulação reescreve cada arquivo como o Coolify faz (`env_file: [".env"]` em todos os serviços, gravado no mesmo caminho). O `.env` de cada recurso tem só os nomes que a regex acha no arquivo original, e o `config` roda na forma do Coolify.
  - As asserções olham chaves **e** valores no serviço resolvido.
  - As mensagens de falha só citam nomes. As comparações de valor na `api` usam `(... == ...) is True`, para o pytest não imprimir o segredo fictício.
  - **O controle negativo é real.** Com os três serviços num único recurso, o layout da primeira passada, a mesma simulação mostra a `DATABASE_URL` no `caddy` e no `dashboard`. O CA-19 não passa por vacuidade.
- **CA-13:** `test -e /app/infra` passou a falhar na `api` e no `dashboard`, além das sentinelas de `.env`. O teste do Caddy não mudou.
- **Tabela da §10 (segunda passada):** os 14 ajustes nos aceites das SPECs 015 e 032 decorrem da última linha da tabela da §3.1 (a `api` lida de `compose.api.yaml`, `config` nos dois arquivos, a rede `link`). Eles mantêm a intenção dos CAs antigos, e nenhum `test_caNN_` foi removido. A exceção é o RV-05. O renome do `test_ca12_*` é de um teste desta própria SPEC, fora da regra da §10.
- **R-07:** todos os commits do delta têm o trailer `Agent:` e respeitam os papéis:
  - `architect` (`4239a2f`): só docs (SPEC, ADR, plano, arquitetura, `deployment-plan.md`);
  - `orchestrator` (`2ff6021`, `94282f5`, `9d31e4c`, `34aaf75`): status, mais o registro da aprovação humana no ADR-023, na SPEC, no plano e na N-05 de `docs/rules.md`, com o texto aprovado pelo humano (mesmo precedente da N-05 do ADR-023);
  - `security-devops` (`78f6ceb`, `2960059`): produção, testes do autor fora de `acceptance/`, o plano e o adendo do dev-report;
  - `tester` (`fe5bb12`): só `infra/tests/acceptance/` e o adendo do test-report;
  - `reviewer` (`b12e515`): só o security-report.
- **ADR-019:** a correção foi classificada "exige humano" (X-2, X-3, X-5, X-7) e **reaprovada pelo humano** (`94282f5`, Histórico da SPEC e do ADR-023). Não houve reaprovação delegada.
- **R-03 e R-13:** nenhum segredo no delta. A busca por URLs com senha, `eyJ`, `ghp_`, `sk-`, IPv4, UUID e caminho `/webhooks/` só achou placeholders e valores fictícios montados em tempo de execução. Os domínios são só os fictícios `*.example.org`/`example.com`, mais `github.com`, `coolify.io`, `caddyserver.com` e `docs.github.com` como fontes nos docs, e `sslip.io` em asserção negativa. Não há subdomínio, IP, UUID, URL do painel nem segredo do webhook, e nenhuma empresa é citada.
- **Execução**, sem `TEST_DATABASE_URL`, sem `CI` e sem VPS:
  - `ruff check` e `ruff format --check`: limpos;
  - `uv run pytest -q infra/tests tests`: 835 passed e 385 skipped;
  - `PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker infra/tests`: 91 passed;
  - limpeza: não sobrou contêiner, rede (inclusive a `partqc-api-link`), imagem `partqc.test=1` nem volume novo. Os `partqc-pg*` são preexistentes e não foram tocados.

### SPEC_ISSUE

Nenhum. O RV-05 é um defeito de teste, corrigível pelo tester sem mudar a SPEC.

### Declaração

- [x] Não editei código nem testes; só acrescentei este adendo ao relatório.
- [x] Não sou autor de nenhum commit de implementação ou de teste desta SPEC. O `b12e515` é o security-report, que também é do papel de reviewer.
