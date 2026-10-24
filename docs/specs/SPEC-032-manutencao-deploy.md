# SPEC-032: Manutenção do deploy (smoke sem abreviação, `.gitignore` sem diferenciar maiúsculas, headers e endurecimento dos contêineres)

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | security-devops |
| Tags | deploy, security, infra |
| Depende de | SPEC-015 (`Done`) |
| Semana alvo | S4–S5 (depois do merge da SPEC-015; a §4.1 e a §4.2 podem ir antes da demo interna, e a §4.3 e a §4.4 entram se o humano mantiver os candidatos) |
| Requisitos cobertos | RNF-01, RNF-05, RNF-06, RNF-10; R-01, R-02, R-03, R-13, R-14 |
| ADRs relevantes | ADR-018, ADR-016 |

## 1. Contexto

Fecha as pendências não bloqueantes dos portões da SPEC-015 (deploy na VPS pessoal, `docs/architecture.md` §1, §8 e §9) que a r2 dela não aplicou. O autor é o `security-devops`; por isso, como na SPEC-015, o portão de segurança é feito pelo **reviewer** (`reviews/README.md`).

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| RV-05 (= T-04) | `reviews/SPEC-015/r2-review-report.md`; `reviews/SPEC-015/r2-test-report.md` (T-04) | baixa | O parser do `scripts/smoke_test.py` aceita abreviações, e `"--=<valor>"` faz o argparse repetir o valor numa mensagem `ambiguous option` (§4.1) |
| RV-04 (parte do `.gitignore`) | `reviews/SPEC-015/r1-review-report.md` | baixa | O `.gitignore` diferencia maiúsculas: `IMG_0001.JPG` ou `FOTO.PNG` não são ignorados (§4.2). A parte dos `.dockerignore` foi corrigida na r2 da SPEC-015 (`reviews/SPEC-015/r2-dev-report.md`) |
| SEC-15-04 (candidato) | `reviews/SPEC-015/r1-security-report.md` | informativo | `-Server`, `-Via`, `Referrer-Policy` e `frame-ancestors` no Caddy (§4.3) |
| SEC-15-05 (candidato) | mesmo relatório | informativo | `pids_limit` e `read_only` com `tmpfs` nos contêineres (§4.4) |

**Candidatos.** O SEC-15-04 e o SEC-15-05 não têm correção exigida: o relatório os deixou "para uma SPEC futura de endurecimento, se o humano quiser". Eles estão aqui em seções próprias para que o humano possa aprová-los ou cortá-los na aprovação desta SPEC, sem mexer na §4.1 e na §4.2. Se forem cortados, saem a §4.3, a §4.4 e os CA-04 a CA-08.

## 2. Objetivo

O smoke recusa abreviações sem repetir valores; o Git ignora fotos, pesos, bancos locais, chaves e `.env` em qualquer caixa; e, se os candidatos forem mantidos, as respostas públicas deixam de identificar o software e não podem ser emolduradas por outro site, e os contêineres rodam com sistema de arquivos só de leitura e limite de processos.

## 3. Escopo

### 3.1 Dentro

- `scripts/smoke_test.py`: só o parser (§4.1).
- `.gitignore`: variantes sem diferenciar maiúsculas (§4.2).
- `infra/Caddyfile`: headers (§4.3).
- `infra/compose.yaml`: `pids_limit`, `read_only` e `tmpfs` (§4.4).
- `.env.example`: as 3 variáveis de limite de processos no bloco `infra/.env` (§4.4).
- `docs/deployment-plan.md`: §2 (limites), riscos e a atualização da tabela de CAs manuais (§4.3 e §4.4).
- Testes do autor em `infra/tests/` (inclusive os de marcador `docker`, §4.14 da SPEC-015).
- **Tester:** `infra/tests/acceptance/test_spec_032.py`.

### 3.2 Fora

- Os achados SEC-15-01 a SEC-15-03 e RV-01 a RV-04 (parte dos `.dockerignore`) da SPEC-015: corrigidos na r2 dela.
- Fixar as actions por SHA (SEC-15-06): sem ação, como o relatório decidiu.
- Limitação de taxa no Caddy (plugin `rate_limit`): continua fora (SPEC-015 §3.2).
- `Content-Security-Policy` completa (`script-src`, `connect-src` etc.): não adotada; só `frame-ancestors`, que é o que o SEC-15-04 sugere. Uma política completa exigiria mapear o que o Streamlit carrega e entra por SPEC nova, se o humano pedir.
- README da raiz e `.claude/agents/security-devops.md`, que ainda citam o Render e o Streamlit CC como caminho principal (observação do `reviews/SPEC-015/r1-review-report.md`): pendência do orquestrador, fora desta SPEC.
- O `.dockerignore` da raiz: continua proibido (SPEC-015 §4.11).

## 4. Requisitos detalhados

### 4.1 Smoke: sem abreviação de opções (RV-05/T-04)

- O `NoEchoArgumentParser` do `scripts/smoke_test.py` é criado com `allow_abbrev=False`, como o de `scripts/simulate.py` (SPEC-027).
- Com isso, `--api`, `--dash` ou `--=<valor>` passam a ser argumentos desconhecidos: código 2, nenhuma requisição, e a saída cita só a contagem (`(not shown)`), nunca o valor, como no RV-02 da SPEC-015 corrigido na r2.
- `--api-url` e `--dashboard-url` por extenso continuam funcionando, e os CA-08 a CA-12 da SPEC-015 continuam valendo.

### 4.2 `.gitignore` sem diferenciar maiúsculas (RV-04)

O Git no Linux diferencia maiúsculas nos padrões do `.gitignore` (`core.ignorecase=false`). Ao lado de cada padrão abaixo, que continua **literalmente** como está, entra uma variante com classes de caracteres (o mesmo padrão adotado nos `.dockerignore` da SPEC-015 r2):

| Grupo | Padrões existentes | Variantes novas |
|---|---|---|
| Segredos (R-03) | `.env`, `.env.*` | `.[eE][nN][vV]`, `.[eE][nN][vV].*` |
| Chaves (R-03) | `*.pem`, `*.key` | `*.[pP][eE][mM]`, `*.[kK][eE][yY]` |
| Fotos (R-02, R-14) | `*.jpg`, `*.jpeg`, `*.png` | `*.[jJ][pP][gG]`, `*.[jJ][pP][eE][gG]`, `*.[pP][nN][gG]`, e as fotos que o `.dockerignore` da SPEC-015 §4.11 já trata: `*.[hH][eE][iI][cC]`, `*.[wW][eE][bB][pP]` |
| Pesos | `ml/models/**/*.onnx`, `.pt`, `.pth` | `ml/models/**/*.[oO][nN][nN][xX]`, `ml/models/**/*.[pP][tT]`, `ml/models/**/*.[pP][tT][hH]` |
| Bancos locais | `*.sqlite`, `*.sqlite3`, `*.db` | `*.[sS][qQ][lL][iI][tT][eE]`, `*.[sS][qQ][lL][iI][tT][eE]3`, `*.[dD][bB]` |

- As exceções vêm **depois** das exclusões do grupo: `!.env.example` continua depois das duas linhas de `.env`; `!docs/**/*.png` e `!ml/reports/**/*.png` continuam, e ganham `!docs/**/*.[pP][nN][gG]` e `!ml/reports/**/*.[pP][nN][gG]`, depois de todas as linhas de fotos.
- Nenhum padrão existente sai nem muda. O CA-06 da SPEC-015 e os testes da SPEC-001 sobre o `.gitignore` continuam valendo.
- A regra não reescreve o histórico nem tira do índice arquivo nenhum: ela só impede commits novos.

### 4.3 Headers do Caddy (SEC-15-04, candidato)

No bloco de headers do site em `infra/Caddyfile`, além do `Strict-Transport-Security "max-age=31536000"` e do `X-Content-Type-Options "nosniff"` de hoje:

- `-Server` e `-Via`: removem os headers que identificam o software (`server: uvicorn`, `via: 1.1 Caddy`, observados pelo tester da SPEC-015). Pela documentação do Caddy, apagar um header (`-Campo`) ativa o `defer` automaticamente, e a operação roda quando a resposta é enviada ao cliente, depois do `reverse_proxy` (<https://caddyserver.com/docs/caddyfile/directives/header>, consultada pelo architect em 2026-10-19; o autor confere de novo e atualiza a data no `deployment-plan.md`).
- `Referrer-Policy "no-referrer"`.
- `Content-Security-Policy "frame-ancestors 'self'"`: só a diretiva de molduras. Os componentes do Streamlit que usam `iframe` vêm da mesma origem e continuam funcionando.
- Sem bloco global, sem domínio literal, sem `includeSubDomains`, `preload`, `/docs` nem `openapi` (CA-30 da SPEC-015). O arquivo continua formatado por `caddy fmt`.

### 4.4 Endurecimento dos contêineres (SEC-15-05, candidato)

Em `infra/compose.yaml`, nos três serviços, além do que a SPEC-015 §4.12 já exige:

1. **`pids_limit`:** `${API_PIDS_LIMIT:-256}`, `${DASHBOARD_PIDS_LIMIT:-256}` e `${CADDY_PIDS_LIMIT:-256}`, escritos literalmente nessas formas, como os limites de memória e CPU. O `.env.example` ganha as 3 variáveis, com o valor `256`, no bloco `infra/.env`. Se o `docker compose config --quiet` recusar a interpolação nesse campo, o autor usa o literal `256`, registra a recusa no dev-report e o CA-05 confere o literal.
2. **`read_only: true`**, com `tmpfs` só onde o processo precisa escrever:
   - `/tmp` nos três serviços;
   - `/home/app` na `api` e no `dashboard`, só se o autor medir que o processo escreve lá (por exemplo, o Streamlit em `~/.streamlit`);
   - cada `tmpfs` com a opção `size` de no máximo `64m`;
   - o usuário `10001` (e o `root` do Caddy) consegue escrever em cada `tmpfs` que usa.

   Os volumes `caddy_data` e `caddy_config` continuam graváveis. O dev-report lista cada `tmpfs`, o motivo (erro ou log observado sem ele) e o comando usado para medir.
3. **Medição:** o autor sobe os três serviços localmente (testes `docker`) e registra no dev-report o número de PIDs de cada contêiner em repouso e com 5 sessões do dashboard abertas, para mostrar que 256 tem folga (pelo menos o dobro do medido). Se não tiver, para e registra `SPEC_ISSUE`.
4. `docs/deployment-plan.md` §2 e §4: os limites novos, o que fazer se um contêiner parar por `pids_limit` (subir o valor no `infra/.env` e rodar `up -d`) e que um `read_only` que quebrar um serviço depois de uma atualização se diagnostica pelo log (`Read-only file system`).

## 5. Critérios de aceite

Os CAs marcados `docker` rodam só com `PARTQC_DOCKER_TESTS=1` (SPEC-015 §4.14), com contextos e cópias temporárias, nunca a árvore real. O host fictício é `partqc.example.org`.

- **CA-01 (security, R-03, RV-05/T-04)** — *Dado* `READ_API_KEY`, `SIM_DEVICE_ID`, `SIM_DEVICE_API_KEY`, `CLOUD_API_URL` e `DASHBOARD_URL` (URLs `https://partqc.example.org`) definidas e um marcador gerado no teste, *quando* `smoke_test.main` é chamado com `["--=" + marcador]`, `["--api=https://" + marcador + ".example.org"]` e `["--dash", "https://" + marcador + ".example.org"]` e um transporte que registra as requisições, *então* cada chamada termina com código 2, o transporte registra 0 requisições, e o marcador não aparece no stdout nem no stderr. *Dado* `["--api-url", "https://partqc.example.org", "--dashboard-url", "https://partqc.example.org"]` com a API e o dashboard falsos corretos, *então* o código é 0 (as opções por extenso continuam aceitas).
- **CA-02 (R-02, R-03, R-14, RV-04)** — *Dado* o `.gitignore` do repositório, *quando* `git check-ignore --no-index -q <caminho>` roda para cada caminho abaixo, *então* os da primeira lista são ignorados e os da segunda não:
  - ignorados: `ml/data/raw/screw/fair/IMG_0001.JPG`, `fotos/FOTO.JPEG`, `fotos/Foto.Png`, `fotos/IMG_0002.HEIC`, `fotos/a.heic`, `fotos/a.WEBP`, `ml/models/v1/MODEL.ONNX`, `ml/models/v1/best.PT`, `edge/OUTBOX.SQLITE3`, `x/LOCAL.DB`, `CERT.PEM`, `id.KEY`, `.ENV`, `.Env.prod`, `infra/.ENV.API`;
  - não ignorados: `.env.example`, `.streamlit/config.toml`, `ml/reports/v1/grade_confusion.png`, `ml/reports/v1/GRADE_CONFUSION.PNG`, `docs/img/Arquitetura.PNG`, `ml/tests/fixtures/tiny_model/model.onnx`.

  E cada linha do `.gitignore` anterior a esta SPEC continua presente, igual.
- **CA-03 (R-03)** — *Dado* os arquivos rastreados, *quando* se compara `git -c core.excludesFile=/dev/null ls-files -ci --exclude-from=<A>` com `git -c core.excludesFile=/dev/null ls-files -ci --exclude-from=<B>`, em que `<A>` é o `.gitignore` atual e `<B>` é uma cópia temporária dele **sem** as linhas que casam `re.search(r"\[[a-z][A-Z]\]", linha)` (as variantes desta SPEC, como `[jJ]`; o `*.py[cod]` de hoje não casa), *então* as duas saídas são iguais (as variantes não passam a ignorar nenhum arquivo já rastreado). O teste não depende do ref `main`, que o checkout do CI pode não ter.
- **CA-04 (SEC-15-04, candidato)** — *Dado* `infra/Caddyfile` como texto, sem comentários, *então* aparecem `-Server`, `-Via`, `Referrer-Policy "no-referrer"`, `Content-Security-Policy "frame-ancestors 'self'"`, `Strict-Transport-Security "max-age=31536000"` e `X-Content-Type-Options "nosniff"`, e as condições do CA-30 da SPEC-015 continuam valendo.
- **CA-05 (docker, SEC-15-04, candidato)** — *Dado* a imagem do Caddy fixada no compose, *quando* `caddy adapt --config /etc/caddy/Caddyfile` roda com `PUBLIC_HOST=partqc.example.org`, *então* sai com 0, sem aviso de formatação, e o JSON tem um handler `headers` cuja resposta apaga `Server` e `Via` e define os 4 headers do CA-04.
- **CA-06 (SEC-15-05, candidato)** — *Dado* `infra/compose.yaml` carregado com `yaml.safe_load`, *então*, em cada serviço: `read_only is True`; `pids_limit` é a string da §4.4, item 1 (ou o inteiro `256`, se o dev-report registrar a recusa da interpolação); `tmpfs` contém um item que começa com `/tmp`; todo item de `tmpfs` tem `size=` com valor de no máximo `64m`; e só a `api` e o `dashboard` podem ter, além de `/tmp`, um item que começa com `/home/app`. E `docker compose -f infra/compose.yaml config --quiet`, com um `infra/.env` de teste (`PUBLIC_HOST=partqc.example.org`) numa cópia temporária, sai com 0.
- **CA-07 (docker, SEC-15-05, candidato)** — *Dado* as imagens da `api` e do `dashboard` construídas pela fixture `build_image` e executadas com as mesmas opções de segurança do compose (`--read-only`, os `tmpfs` do compose, `--pids-limit 256`, `--cap-drop ALL`, `--security-opt no-new-privileges`, usuário `10001:10001`) e, na `api`, as variáveis fictícias que os testes `docker` da SPEC-015 já usam, *quando* os contêineres ficam de pé por até 90 s, *então*: o `dashboard` fica `healthy` e responde `ok` em `/_stcore/health`; a `api` responde em `/api/v1/health` (200 ou 503, sem banco); os logs dos dois não contêm `Read-only file system`, `EROFS` nem `PermissionError`; e, dentro de cada um, `touch /tmp/x` termina com 0 e `touch /app/x` falha.
- **CA-08 (docker, SEC-15-05, candidato)** — *Dado* a imagem do Caddy executada com `--read-only`, o `tmpfs` de `/tmp` do compose, volumes temporários em `/data` e `/config`, `--pids-limit 256`, `--network none`, o `infra/Caddyfile` real e `PUBLIC_HOST=partqc.example.org`, *quando* o contêiner roda por 10 s, *então* continua `running`, e o log não contém `read-only file system`.
- **CA-09 (manual, VPS)** — Depois da atualização da SPEC-015 §4.16 com esta SPEC na `main`:
  1. `docker compose -f infra/compose.yaml ps`: os 3 serviços `running`, `api` e `dashboard` `healthy`;
  2. `curl -sI https://<subdominio>/api/v1/health`: tem `referrer-policy: no-referrer` e `content-security-policy: frame-ancestors 'self'`, e não tem `server:` nem `via:` (se a §4.3 foi mantida);
  3. repetir os passos 1 a 3 do CA-17 da SPEC-015 (painel no desktop e no celular, `wss://.../_stcore/stream` com 101 aberto por 5 min, filtro atualizando os gráficos);
  4. com 3 abas do painel abertas, `docker stats --no-stream`: a coluna `PIDS` de cada serviço fica em no máximo metade do `pids_limit` (se a §4.4 foi mantida);
  5. registrar as saídas no dev-report e no `deployment-plan.md`, com o subdomínio trocado por `<subdominio>` (SEC-15-01).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Parser do smoke (abreviações, `--=`); `.gitignore` (caminhos de exemplo); Caddyfile e compose como texto/YAML; testes `docker` do `read_only` e do `pids_limit` | `infra/tests/` |
| Aceite (tester) | Um por CA automatizável; os `docker` com `PARTQC_DOCKER_TESTS=1` | `infra/tests/acceptance/test_spec_032.py` |
| Manual (humano) | CA-09, na VPS | descrito no CA |

- Nenhum teste usa a VPS, o Supabase, o DNS ou a rede externa. Os testes `docker` seguem a §4.14 da SPEC-015 (contextos temporários, imagens removidas no fim da sessão).
- Credenciais e URLs dos testes são montadas em tempo de execução, sem `usuário:senha@` literal (`reviews/checklist.md` §4).

## 7. Riscos e notas para o implementador

- **`--=<valor>`:** com `allow_abbrev=True` (padrão), o argparse levanta `ambiguous option: --=<valor> could match ...` antes da contagem dos extras, sem aspas no valor, e o `redact_usage_error` não o pega (T-04). Com `allow_abbrev=False`, o mesmo comando cai na contagem (`1 value(s) (not shown)`), como no simulador.
- **`.gitignore`:** um arquivo já rastreado não deixa de ser rastreado por causa de uma regra nova, por isso o CA-03 compara com a `main`, em vez de exigir saída vazia.
- **`read_only` e Streamlit:** o Streamlit e o Python podem tentar escrever em `~/.streamlit`, no cache de bytecode ou em `/tmp`. A imagem já compila o bytecode no build (`UV_COMPILE_BYTECODE=1`), e o usuário `app` não escreve em `/app` (SPEC-015 §4.10). Meça antes de acrescentar `tmpfs`; não acrescente `tmpfs` "por garantia".
- **`pids_limit` conta threads.** O Streamlit cria threads por sessão; 256 é folga para a demo da dupla, mas a §4.4, item 3, exige a medição.
- **Headers:** `frame-ancestors 'self'` não afeta o WebSocket do Streamlit (não é moldura), mas o CA-09, passo 3, confere o painel de ponta a ponta. Se algum componente quebrar, pare e registre `SPEC_ISSUE`.
- Nunca rode `docker compose down -v`, `prune` amplo nem mexa no `ufw` além do que a SPEC-015 §4.15 permite.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS), inclusive os `docker` no workflow `docker`
- [ ] review-report APPROVED + o portão de segurança feito pelo reviewer (autor `security-devops`)
- [ ] CI verde (`ci` e `docker`); `ruff` limpo
- [ ] `docs/deployment-plan.md` e `.env.example` atualizados
- [ ] CA-09 (manual) registrado, se a §4.3 ou a §4.4 foram mantidas
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) `allow_abbrev=False`, a correção sugerida pelo T-04; (b) variantes com classes de caracteres no `.gitignore` sem tirar os padrões literais, e `heic`/`webp` acrescentados para alinhar com a lista de fotos do `.dockerignore` (SPEC-015 §4.11); (c) SEC-15-04 e SEC-15-05 como seções candidatas, que o humano pode cortar na aprovação; (d) `pids_limit` configurável no `infra/.env`, como os limites de memória e CPU, com medição obrigatória. Os relatórios da SPEC-015 foram lidos de uma cópia da branch `spec/SPEC-015-deploy-vps` (o `r2-review-report.md` não estava disponível; o RV-05 foi tomado do T-04 do `r2-test-report.md` e da descrição do orquestrador). | RV-04 de `reviews/SPEC-015/r1-review-report.md`; RV-05 de `reviews/SPEC-015/r2-review-report.md` (= T-04 de `r2-test-report.md`); SEC-15-04 e SEC-15-05 de `reviews/SPEC-015/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). Os candidatos SEC-15-04 e SEC-15-05 **ficam**: §4.3, §4.4 e os CA-04 a CA-08 fazem parte do escopo, e o rótulo "candidato" deixa de valer. Inclui `heic` e `webp` no `.gitignore`. | Aprovação humana | Humano (Carlos) |
| 2026-10-24 | Entra em `In Dev` antes de a SPEC-015 estar `Done` (o código dela está na `main`; faltam os CAs manuais na VPS), por decisão do humano. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
| 2026-10-24 | Merge autorizado pelo humano com o CA-09 manual pendente (só pode ser feito na VPS depois do merge, como na SPEC-015); a SPEC fica `In Security` até o CA-09 ser registrado. | Resposta do humano de 2026-10-24 | Orquestrador, a pedido do humano |
