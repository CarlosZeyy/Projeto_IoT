# SPEC-032 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-032](../../docs/specs/SPEC-032-manutencao-deploy.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `6b3b46b` |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta) antes de ler o diff de produção. Depois li o diff (`a544d0a..6b3b46b`) e o dev-report. Arquivo: `infra/tests/acceptance/test_spec_032.py`, com 89 testes: 78 sem Docker e 11 com o marcador `docker`.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `infra/tests/acceptance/test_spec_032.py::test_ca01_smoke_refuses_abbreviations_without_echo` | ✅ |
| CA-02 | `::test_ca02_gitignore_ignores_in_any_case` (15 caminhos), `::test_ca02_gitignore_keeps` (6 caminhos), `::test_ca02_previous_gitignore_lines_unchanged` | ✅ |
| CA-03 | `::test_ca03_variants_do_not_ignore_tracked_files` | ✅ |
| CA-04 | `::test_ca04_caddyfile_headers` (inclui as condições do CA-30 da SPEC-015) | ✅ |
| CA-05 (docker) | `::test_ca05_caddy_adapt_headers` | ✅ |
| CA-06 | `::test_ca06_compose_hardening` (YAML) e `::test_ca06_compose_config_quiet` (docker, `config --quiet` numa cópia temporária) | ✅ |
| CA-07 (docker) | `::test_ca07_dashboard_runs_read_only`, `::test_ca07_api_runs_read_only` | ✅ |
| CA-08 (docker) | `::test_ca08_caddy_runs_read_only` | ✅ |
| CA-09 (manual, VPS) | Não automatizável: é passo do humano na VPS (roteiro na §9 do `docs/deployment-plan.md`) | pendente (humano) |

Como os testes de CA foram montados:

- **CA-01:** carrega `scripts/smoke_test.py` como módulo. As 5 variáveis ficam definidas (URLs `https://partqc.example.org`), o marcador é gerado com `secrets` e o transporte é um `httpx.MockTransport` que registra as requisições. As três chamadas do CA terminam com código 2, sem nenhuma requisição e sem o marcador no stdout nem no stderr. Com `--api-url`/`--dashboard-url` por extenso e uma API e um dashboard falsos corretos, o código é 0. Mutação: com uma cópia do script com `allow_abbrev=True`, o CA-01 e mais 9 testes extras do smoke falham.
- **CA-02:** `git -c core.excludesFile=/dev/null -c core.ignorecase=false check-ignore --no-index -q`, ou seja, só o `.gitignore` do repositório, com a distinção de maiúsculas do Linux. Rodei também o comando exato do CA, sem `-c`, nos 21 caminhos, com o mesmo resultado. O `.gitignore` anterior à SPEC (commit `a544d0a`) está copiado literalmente no teste, porque o checkout do CI pode não ter o histórico. Cada linha não vazia dele continua presente.
- **CA-03:** compara `git -c core.excludesFile=/dev/null ls-files -ci --exclude-from=<A>` com o mesmo comando usando `<B>`, uma cópia temporária sem as linhas que casam `\[[a-z][A-Z]\]`. Confere que `*.py[cod]` continua em `<B>`. O teste não depende do ref `main`.
- **CA-05:** `caddy adapt --config /etc/caddy/Caddyfile` na imagem fixada no compose, com `PUBLIC_HOST=partqc.example.org` e `--network none`. Termina com 0, sem `not formatted` nem `caddy fmt` no stderr, e há um handler `headers` com `response.delete ⊇ {Server, Via}` e `response.set` com os 4 headers do CA-04.
- **CA-06:** usa `yaml.safe_load`. Nos 3 serviços: `read_only is True`, `pids_limit` igual à string literal da §4.4, um item de `tmpfs` começando com `/tmp`, `size=` ≤ `64m` em todo item e `/home/app` só na `api` e no `dashboard`. Hoje não há nenhum `/home/app`. A parte do Docker roda `docker compose -f infra/compose.yaml config --quiet` numa cópia temporária da árvore rastreada (`copy_tracked_tree`) e termina com 0. O teste também confere que a árvore real não muda (`git status`) e que nenhum `infra/.env` foi criado nela. Ver a observação O-T-01 sobre os arquivos `.env.api` e `.env.dashboard` da cópia.
- **CA-07:** usa as imagens da fixture `build_image`, executadas com `--read-only`, os `tmpfs` lidos do próprio compose, `--pids-limit 256`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user 10001:10001` e `--network none`. A API recebe o `DATABASE_URL` fictício dos testes `docker` da SPEC-015 (`<user>:<password>@db.example.org`) e uma `READ_API_KEY` gerada. O dashboard fica `healthy` em menos de 90 s, e `/_stcore/health` responde `200 ok`. A API responde em `/api/v1/health`, com 503 sem banco. Nenhum dos dois logs tem `Read-only file system`, `EROFS` nem `PermissionError`. `touch /tmp/x` termina com 0 e `touch /app/x` falha. As requisições HTTP e o `touch` rodam com `docker exec`, porque o contêiner não tem rede.
- **CA-08:** imagem do Caddy com `--read-only`, o `tmpfs` do compose, volumes anônimos em `/data` e `/config`, `--pids-limit 256`, `--network none`, o `infra/Caddyfile` real montado `ro` e `PUBLIC_HOST=partqc.example.org`. Depois de 10 s, o estado é `running` e o log não tem `read-only file system`.

## Suíte completa

Por instrução do orquestrador, **sem banco de teste**: `TEST_DATABASE_URL` e `CI` ficaram fora do ambiente, porque outro agente estava usando o `partqc_test`. Os testes com marcador `db` ficaram `skipped`, e nenhum deles é desta SPEC, que não toca a API nem o banco em código.

```text
$ env -u TEST_DATABASE_URL -u CI -u PARTQC_DOCKER_TESTS uv run pytest -q
5732 passed, 743 skipped, 1 warning in 465.50s (0:07:45)
(o warning é o StarletteDeprecationWarning do fastapi.testclient, já existente)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker
47 passed, 4 skipped, 6424 deselected, 1 warning in 104.47s
(36 testes docker do autor e da SPEC-015 + 11 meus; os 4 skipped são de ML, sem torch)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q infra/tests/acceptance/test_spec_032.py
89 passed in 56.00s

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
237 files already formatted
```

A suíte inteira rodou antes de eu renomear dois testes extras (só os nomes mudaram). Depois disso, rodei de novo o arquivo inteiro, com Docker (89 passed), e o ruff no repositório. O total de 5732 é igual aos 5654 do dev-report somados aos meus 78 testes sem Docker. Os 743 skipped são os 732 do dev-report mais os meus 11 testes `docker`. Docker Engine 29.9.2, Compose 5.6.1, rede bridge padrão, sem `PARTQC_DOCKER_BUILD_NETWORK`. No fim, não sobrou nenhum contêiner, rede, volume nem imagem `partqc-acc032-*` ou `partqc.test=1`: as fixtures removem contêineres com `rm -f -v`, as redes e as imagens, e conferi com `docker ps -a`, `docker network ls` e `docker images --filter label=partqc.test=1`.

Não precisei ajustar nenhum teste de aceite de SPEC anterior (`docs/architecture.md` §10). Os testes da SPEC-015 (CA-06, CA-08 a CA-12, CA-29, CA-30, CA-33, CA-34) continuam passando sem mudança.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa (não bloqueante; decorre do texto do CA-05, não é erro de implementação) | CA-05 / §4.3 (relacionado ao O-01 do dev-report) | 1. Subir a imagem `caddy:2.11.7` fixada com `--network none`, `--read-only`, `tmpfs` e volumes como no CA-08, o `infra/Caddyfile` deste commit e `PUBLIC_HOST=http://partqc.example.org` (mesmo bloco de site, só que em HTTP, para ler a resposta sem certificado). 2. De dentro do contêiner, `GET /api/v1/health` com `Host: partqc.example.org` (a origem `api` não existe, então o Caddy gera um 502). 3. Repetir com o `Caddyfile` anterior à SPEC (`git show a544d0a:infra/Caddyfile`). | §4.3: os novos headers entram "além do `Strict-Transport-Security` e do `X-Content-Type-Options` de hoje". Ou seja, nada do que já saía deixa de sair. | **Antes da SPEC:** o 502 gerado pelo Caddy saía com `Strict-Transport-Security: max-age=31536000` e `X-Content-Type-Options: nosniff`. **Depois:** o mesmo 502 sai só com `Server: Caddy`, `Date` e `Content-Length`, sem nenhum dos 4 headers. O `-Server` torna o bloco inteiro `deferred`, e o caminho de erro do Caddy não passa pelo `ResponseWriter` adiado. O dev-report registra o 502 sem os 4 headers (O-01, risco aceito 9 do plano), mas não diz que o HSTS e o `nosniff` saíam nele antes, ou seja, que isso é uma regressão. O impacto prático é pequeno: o navegador aprende o HSTS em qualquer resposta HTTPS normal, e o 502 tem corpo vazio. Como o CA-05 exige **um** handler `headers` que apague `Server`/`Via` **e** defina os 4 headers, separar HSTS e `nosniff` num bloco não adiado violaria o CA como está escrito. Por isso a decisão é do architect/humano, junto com o O-01. |

Nenhum CA falhou.

## Testes exploratórios (além dos critérios)

Todos os testes `test_extra_*` abaixo estão no arquivo de aceite e passam.

**Smoke (§4.1):**
- Mais 12 formas recusadas com código 2, sem nenhuma requisição e sem o marcador na saída: `--api-u`, `--dashboard=<url>`, `--dashboard-u`, `--d=<m>`, `--a <m>`, `--=<m>` antes de opções válidas, `--dash=<m>` depois de opções válidas, `--h=<m>`, `--he <m>`, `--API-URL`, `--=` com valor unicode (`ção-<m>`) e `-- <m>`.
- A mensagem cita só a contagem (`(not shown)`) e nunca `ambiguous` (§4.1).
- `--api-url=<url> --dashboard-url=<url>`, com `=`, e `--help` continuam funcionando.
- A entrada real (`python scripts/smoke_test.py ...`, em subprocesso) recusa os 3 casos do CA-01 com código 2, sem o marcador e sem `Traceback`.
- Na linha de comando, à mão: `--=` vazio, `-a <m>` e `-x=<m>` terminam com 2 e `N value(s) (not shown)`. `--api-url` sem valor dá `expected one argument`, sem eco.

**`.gitignore` (§4.2):**
- Mais 17 caminhos ignorados, todos conferidos com `git check-ignore --no-index`: `.eNv`, `sub/dir/.ENV.local`, `.env.Example` e `.ENV.EXAMPLE` (a exceção é literal, então essas variantes ficam ignoradas, que é o lado seguro), `a.JpG`, `deep/x/y/z.jPeG`, `Captura.WebP`, `IMG.Heic`, `docs/img/foto.JPG` (em `docs/`, só PNG volta a ser incluído), `ml/models/a/b/c/w.Pth`, `ml/models/a/m.OnNx`, `x.Sqlite`, `x.SQLite3`, `server.Key`, `chain.Pem`, `entrada/IMG_1234.JPG` e `entrada/a.HEIC`.
- 9 caminhos que não podem ser ignorados: `docs/img/A.PnG`, `ml/reports/x/Curve.pNg`, `ml/onnx_export.py`, `edge/src/qc_edge/db.py`, `api/src/qc_api/keys.py`, `notes.keynote`, `README.md`, `foto.jpg.txt` e `ml/MODEL.ONNX` (pesos só são ignorados em `ml/models/`).
- Cada variante da tabela da §4.2 aparece junto do padrão literal, inclusive `heic` e `webp`. `!.env.example` vem depois das 4 linhas de `.env`, e as 4 exceções de PNG vêm depois das 8 linhas de fotos. As linhas antigas mantêm a ordem relativa.
- Hoje nenhum arquivo rastreado é ignorado pelo `.gitignore` atual (`ls-files -ci` vazio).
- O O-02 do dev-report está confirmado: `entrada/plano.csv` não é ignorado (fora da §4.2).

**Caddyfile (§4.3):**
- Há um único bloco `header`, com as 6 linhas e válido para o site inteiro (não fica dentro de `handle /api/*`). Não há CSP completa (`default-src`, `script-src` etc., §3.2), e a indentação é só com tabs.
- No `caddy adapt`, há um único handler `headers`, com `deferred: true`.
- **De ponta a ponta (docker):** montei uma rede `--internal` com as imagens reais da `api` e do `dashboard`, endurecidas como no CA-07, e o Caddy com o `Caddyfile` real e `PUBLIC_HOST=http://partqc.example.org`. Antes, confirmei que as origens se identificam: acessadas direto, `api:8000` e `dashboard:8501` mandam `server`. Por trás do Caddy, `/api/v1/health` (503), `/_stcore/health` (200) e `/` (200) saem **sem** `server` e sem `via`, e com `referrer-policy: no-referrer`, `content-security-policy: frame-ancestors 'self'`, `strict-transport-security: max-age=31536000` e `x-content-type-options: nosniff`.
- **O-01 reproduzido:** o 502 gerado pelo Caddy, com a origem fora do ar, e o redirecionamento automático `308` da porta 80, com `PUBLIC_HOST=partqc.example.org`, saem com `Server: Caddy` e sem os 4 headers. O dev-report está correto. Comparando com o `Caddyfile` anterior, saiu o achado T-01.

**Contêineres (§4.4):**
- Dentro da `api` e do `dashboard`, executados como no CA-07: `pids.max` = `256`, raiz montada `ro`, `/tmp` como `tmpfs` com `size=65536k`, `noexec` e `nosuid`, uid `10001`, e `/home/app` não gravável. Nenhum dos serviços precisou de `tmpfs` em `/home/app`, o que confirma a medição do autor.
- O Caddy com as capacidades do compose (`--cap-drop ALL --cap-add NET_BIND_SERVICE`, `no-new-privileges`) fica `running` depois de 10 s. `/tmp`, `/data` e `/config` são graváveis, `/etc` não, e `pids.max` = `256`.
- `compose config --format json` resolve `pids_limit` = 256 e `read_only` = true nos 3 serviços. `DASHBOARD_PIDS_LIMIT=512` no `infra/.env` muda só o dashboard. `API_PIDS_LIMIT=abc` faz o `config` falhar, sem repetir o valor no stdout.
- **O-T-02 (informativo):** `API_PIDS_LIMIT=0` faz o `compose config` **descartar** o `pids_limit` (sem limite), e `-1` também significa sem limite, os dois sem aviso. O plano manda subir o valor, não zerar. Fica registrado como cuidado de operação, e não é bug da SPEC.
- O `.env.example` tem `API_PIDS_LIMIT=256`, `DASHBOARD_PIDS_LIMIT=256` e `CADDY_PIDS_LIMIT=256` dentro do bloco `# ---------- infra/.env ...`, cada um uma única vez. O `deployment-plan.md` cita `pids_limit`, `read_only`, `Read-only file system`, as 3 variáveis, `up -d`, `Referrer-Policy` e `frame-ancestors` (§4.4, item 4).

**Observações sem defeito:**
- **O-T-01 (CA-06, redação):** com **só** o `infra/.env` de teste na cópia temporária, o `docker compose config --quiet` termina com 1 (`env file .../infra/.env.api not found`). Isso acontece porque os `env_file` da `api` e do `dashboard` são obrigatórios desde a SPEC-015 §4.12 (CA-29). O CA-06 não proíbe outros arquivos, então o teste cria também o `.env.api` e o `.env.dashboard` com valores fictícios, como a fixture do CA-33 da SPEC-015. Com eles, o comando termina com 0. Não registrei como SPEC_ISSUE, porque o CA é testável numa leitura direta. Se o architect revisar a SPEC, vale citar os 3 arquivos.
- Nenhum segredo, host real ou IP nos testes nem neste relatório. As chaves e os marcadores são gerados em tempo de execução, e as URLs usam `partqc.example.org`.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
