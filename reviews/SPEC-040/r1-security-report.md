# SPEC-040 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-040](../../docs/specs/SPEC-040-manutencao-consolidada.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops (Partes A e B, autores: developer e ml-engineer) e reviewer (Parte C, autor: security-devops), como manda a SPEC §6 |
| Diff revisado | `main...110866a` (Partes A e B) e `main...7c31940` (Parte C: commits `f8d313c`, `7af5eb6`, `c2a4753` e `bb2fea4`) |
| **Veredicto** | **PASS:** as duas seções são PASS (SPEC §6). O CA-18 manual continua pendente, então o caminho real pelo proxy da VPS não foi verificado |

| Parte | Revisor | Veredicto |
|---|---|---|
| A e B (`edge/`, `api/`, `dashboard/`, `ml/`) | security-devops | **PASS** |
| C (comentários de `infra/docker/*.Dockerfile` e `.streamlit/config.toml`; `docs/deployment-plan.md`) | reviewer | **PASS** |

## Parte C (reviewer)

**Veredicto da Parte C: PASS.** Nenhum achado bloqueante, alto ou médio. Há 1 achado baixo (SEC-40-C1, o mesmo RV-05 do `r1-review-report.md`) e 2 informativos.

### Superfície analisada

- **Rotas e entradas externas:** nenhuma. A Parte C só muda comentários, documentação e testes do autor.
- **Segredos:** nenhum novo. O plano passa a citar a `READ_API_KEY` no CA-18, sempre pelo ambiente do contêiner e por um descritor.
- **Dependências novas:** nenhuma. `uv.lock`, os `pyproject.toml` e o `.env.example` estão intocados.
- **Configuração de deploy:** nenhuma instrução muda. O diff de `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` e `.streamlit/config.toml` só tem linhas de comentário: filtrei as linhas `+`/`-` que não começam com `#`, e não sobrou nenhuma. Os `.dockerignore` e os compose não mudam.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-40-C1 (= RV-05) | baixa | deploy | `docs/deployment-plan.md:439` | O §7, item 5, ainda manda repetir só "o smoke (passo 11), o CA-16 e o CA-20 da SPEC-039" depois de atualizar o Coolify, sem o CA-18 da SPEC-040. A "Atualização" da §4 e o item 12 da §7 já citam o CA-18. A §4.10 só pedia a frase da "Atualização", então o texto cumpre a SPEC, e o autor registrou a escolha. Quem seguir só o item 5 deixa de conferir o `identity` depois de atualizar o proxy. O efeito é limitado: a falha é transitória, aparece no log, e os itens ficam `pending`. | Nenhuma nesta rodada. Na próxima mudança do plano, acrescentar o CA-18 (passos 1 a 3) a esse item, ou trocar a lista por uma referência à "Atualização". |
| SEC-40-C2 | informativa | deploy | `docs/deployment-plan.md:453` | O teste do autor com o `traefik:v3` local (`v3.7.17`) mostra que `identity` volta sem compressão, mas não prova a versão da VPS. Não repeti esse teste. O plano declara o limite, e só o CA-18 confere o caminho real. Se o proxy comprimir mesmo com `identity`, a borda para de enviar até a correção, sem perder inspeções, e o CA-18 manda voltar a versão da borda. | Executar o CA-18 depois do deploy (humano). |
| SEC-40-C3 | informativa | privacy | `docs/deployment-plan.md:455` | A nota de CDN está certa para o layout atual: `infra/compose.yaml:74` monta `API_BASE_URL` como `https://${PUBLIC_HOST}`, então a chave de leitura também sai pelo subdomínio público. Com proxy de CDN, ela atravessa um TLS terminado por terceiros. A recomendação é não usar proxy, e a anotação fica fora do repositório. Não há como conferir o DNS real daqui. | Anotar a escolha fora do repositório, no passo 3, item 4 (humano). |

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota, comparação em tempo constante | N/A: nenhuma rota |
| Entradas validadas | N/A: nenhuma entrada nova |
| SQL parametrizado | N/A: nenhum SQL de produção. O passo 3 do bloco novo remete à conferência existente do passo 1, item 4 |
| RLS ligado; `DATABASE_URL` e `service_role` fora da API | ✅ Nenhuma mudança. O bloco manda conferir RLS e grants de toda tabela nova, e a `DATABASE_URL` da migração continua só no `.env.migrate` local, nunca no `argv` |
| CORS | N/A |
| Logs sem segredos | ✅ O plano só cita mensagens fixas (`unsupported response encoding`, `unsupported content encoding`, `abandoned_for_s`). O CA-18 manda registrar as saídas com `<subdominio>` e sem a chave |
| Dependências novas | N/A: nenhuma |
| Deploy: variáveis no provedor, health check, plano free | ✅ Os comentários apontam para as Environment Variables do Coolify (ADR-023), coerentes com o `environment` de `infra/compose.yaml:72` e `infra/compose.api.yaml:29`. O passo 4 do bloco confere o `contract_version` no health. Nenhum serviço novo (R-01): a CDN é opcional e não recomendada |
| Reaprovação delegada (ADR-019) | N/A: o diff da SPEC-040 só muda `Status` e `Rodada atual`, e o Histórico não tem reaprovação |

### O que conferi nos comandos e nas fontes

- **CA-18, chave fora do `argv` e do histórico (R-03):** `k=$(docker exec <contêiner do dashboard> printenv READ_API_KEY)` passa só o nome da variável, e `-K <(printf ...)` usa o `printf` embutido do shell. O `-D -` imprime só os headers da resposta, sem `-v`, e o passo 2 termina com `unset k`. `infra/compose.yaml:75` confirma que o contêiner do dashboard tem a variável. Os comandos usam só marcadores. Li os comandos, mas não os executei.
- **Bloco de migração:** os comandos são os do passo 1, item 3, subitens 4 a 6. `0 pending` vem de `infra/migrate.py:380` (`%d applied, %d pending`). `--outbox-path` e `--yes` existem em `edge/src/qc_edge/requeue.py:96` e `:105`. A forma `uv run --package qc-edge python -m qc_edge.requeue` é a do `edge/README.md`.
- **Regra aditiva:** a ressalva do autor sobre a `002` confere com o cabeçalho da migração, que diz que os `check` espelham o contrato.
- **Fontes (consultadas de novo em 2026-10-31):** a referência do Traefik confirma as condições, os valores de `Accept-Encoding`, o padrão de 1024 bytes e o `defaultEncoding`, e a busca por `identity` no texto dela não achou nada, como o plano diz. A página do Coolify mostra `middlewares=gzip` no roteador `https-0-<resource-id>`.
- **R-03 e R-13:** busquei no diff inteiro padrões de JWT, token do Telegram, URL com senha, IP e nome de empresa, e no diff da Parte C também UUID e domínio. Só apareceram `127.0.0.1` e os domínios públicos das fontes.
- **Separação de papéis (R-07):** os commits da Parte C têm `Agent: security-devops` e só tocam os caminhos dela. Não sou autor deles.

**Não verifiquei:** nada na VPS, no Coolify real nem no DNS (CA-18, pendente com o humano), e não rodei os testes marcados com `docker`. O test-report registra 108 passados, e os Dockerfiles só mudam em comentários.

### Dependências novas

Nenhuma.

### Declaração

- [x] Não editei código; não sou autor da Parte C.

## Partes A e B (security-devops)

**Veredicto das Partes A e B: PASS.** Nenhum achado bloqueante, alto ou médio. Há 4 achados baixos e 2 informativos, e nenhum pede rodada nova.

As correções fecham o que a SPEC prometia: a resposta comprimida é recusada antes de qualquer leitura, a varredura deixa de pular pastas em silêncio, e o painel recusa a URL sem exceção na tela. O ponto em aberto é o CA-18: ninguém conferiu o `identity` no proxy real da VPS.

### Superfície analisada

- **Rotas e schemas:** nenhuma mudança. O contrato e o banco estão intocados.
- **Entradas externas:** respostas HTTP da nuvem e do Telegram (`Content-Encoding`), nomes e permissões em `raw/`, `API_BASE_URL`, `metrics.json` e os `split_v<M>.json`.
- **Segredos:** nenhum novo. O `api/README.md` passa a tirar o token do ambiente do contêiner, e os logs novos só têm classe, inteiros e IDs validados.
- **Dependências novas:** nenhuma. `uv.lock`, os `pyproject.toml` e o `.env.example` estão intocados.
- **Configuração de deploy:** as Partes A e B não mudam Dockerfile, compose nem proxy.

### Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-40-A1 (= O-03) | baixa | secrets | `api/src/qc_api/services/alerts.py:502` | `send_message`, chamada sozinha, não instala o filtro do token. Com o logger raiz em INFO, o token aparece no registro do `httpx`. O problema vem da SPEC-017, e nenhum caminho de produção o alcança. Ver "Avaliação da O-03". | Nenhuma nesta rodada. Na próxima mudança de `alerts.py`, chamar `install_token_redaction(config.token)` no início de `send_message`. A chamada é idempotente. |
| SEC-40-A2 (= RV-02) | baixa | input | `dashboard/src/qc_dashboard/api.py:264` | Um `READ_API_KEY` não ASCII vira `InsecureApiUrlError`, e o diagnóstico aponta a variável errada. A falha é fechada: a página mostra a mensagem fixa (`filters.py:311`), a exceção sai com `from None`, e o valor não é exibido. | Nenhuma nesta rodada. Seguir a sugestão do RV-02. |
| SEC-40-A3 | baixa | privacy | `edge/src/qc_edge/privacy.py:171` | Anterior a esta SPEC e fora do diff. Um link simbólico em `raw/` para um JPEG com EXIF passa pelas conferências do `docs/dataset-protocol.md` §8: a varredura sai com 0, o `find -type f` não o lista, e o `find_raw_images` da validação não o segue (este último só pela leitura do código). O `shutil.make_archive` guarda os bytes do alvo, então a foto pode chegar ao backup com os metadados. Exige criar o link à mão, e o protocolo já manda não copiar arquivos à mão para `raw/`. | Nenhuma nesta rodada. Registrar no `docs/plan.md` §3. Numa manutenção da borda, a varredura pode acusar o link como `invalid`. |
| SEC-40-B1 (= RV-03) | baixa | input | `ml/src/qc_ml/report.py:460` | `model_version`, `model_sha256`, `split_file`, `split_sha256`, `manifest_sha256` e `latency_machine` continuam sem conferência. Reproduzi: uma quebra de linha em qualquer um deles forja um título `## ...` na entrada do CHANGELOG. A §4.6 limita a conferência a dois campos, e o código segue esse limite. Não há ganho real para um atacante: quem altera o `metrics.json` já pode alterar as próprias métricas, e a entrada passa por PR. | Nenhuma nesta rodada. Registrar no `docs/plan.md` §3, como o RV-03 sugere. |
| SEC-40-A4 | informativa | privacy | `edge/src/qc_edge/privacy.py:125` | Um arquivo com o nome exato do temporário continua sem leitura, mesmo com EXIF: a varredura sai com 0. O CA-05 (caso g) manda ser assim. O `find ... ! -name '*.jpg'` do `docs/dataset-protocol.md` §8, passo 1, lista esse arquivo (reproduzido), então o protocolo cobre o caso. | Manter esse `find` no protocolo. |
| SEC-40-B2 | informativa | input | `ml/src/qc_ml/split.py:908` | A leitura do `test_extended_types` falha aberta: com o JSON ausente, ilegível ou fora do formato, o tipo pode voltar a ser "novo". A §4.7 e o CA-14 mandam ser assim. Uma nova extensão ainda exige apagar ou corromper o JSON e passar `--extend-test-types` de propósito, e os sorteios antigos não mudam. | Nenhuma. |

### Avaliação da O-03

**Decisão: não bloqueia.** Fica registrada como SEC-40-A1, baixa. Conferi três cenários, em processos novos, para o filtro de um teste anterior não mascarar o resultado:

| Cenário | Registro do `httpx` | Token no log |
|---|---|---|
| `send_message` sozinha, sem filtro, com o logger raiz em INFO | sim | **sim** (a O-03 procede) |
| `send_message` sozinha, sem filtro, com os níveis de produção (`configure_logging` só ajusta o logger `qc_api`; o `httpx` fica em WARNING) | não | não |
| `run_check` real com o logger raiz em DEBUG, com o banco, a configuração, o texto e o transporte substituídos | sim | não (nem a parte depois de `:`) |

- **Caminho de produção:** o único chamador de `send_message` é `run_check`, que instala o filtro antes de qualquer envio (`alerts.py:581`). A subida do laço também instala (`:673`).
- **Cobertura do filtro:** `REDACTED_LOGGERS` inclui todos os loggers que o `httpcore` instalado (1.0.9) declara, além do `httpx`.
- **Leitura do tester no CA-09:** aceito. O filtro faz parte do que a produção executa antes do envio, e o cenário do `run_check` confirma o caminho real.
- **Risco que sobra:** um futuro chamador direto de `send_message`, com logging em INFO. O docstring promete "logged without the token" sem citar essa condição, e por isso sugiro a chamada no início da função. É uma linha, mas o código é da SPEC-017 e esta SPEC não pediu a mudança, então não peço rodada nova.

### Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota, comparação em tempo constante | N/A: nenhuma rota. O `build_request` + `send` do painel mantém a chave e o timeout (teste do autor) |
| Entradas validadas | ✅ Ver "O que conferi". Restam só os campos da SEC-40-B1, fora do limite da §4.6 |
| SQL parametrizado | ✅ Nenhum SQL novo ou alterado |
| RLS ligado; `DATABASE_URL` e `service_role` fora da API | N/A: nenhuma mudança |
| CORS | N/A |
| Logs sem segredos e sem payloads de imagem | ✅ Os logs novos têm só classe de exceção, `strerror`, caminho relativo escapado, inteiro, `lot_id` (validado por `LOT_ID_PATTERN`) e `source`. A CLI do ML imprime só o nome do campo. A SEC-40-A1 não é alcançável em produção |
| Dependências novas | N/A: nenhuma. O `qc-dashboard` já declara `httpx`, e o `idna` vem dele (`uv tree`) |
| Deploy: variáveis no provedor, health check, plano free | ✅ O `api/README.md` segue o ADR-023: o token fica só nas Environment Variables do `partqc-api`, e o `argv` recebe só o nome da variável. Nenhum serviço novo (R-01). Não conferido na VPS: CA-18 |
| Reaprovação delegada (ADR-019) | N/A: o diff da SPEC-040 só muda `Status` e `Rodada atual`, e o Histórico não tem reaprovação |

### O que conferi

- **Compressão, publisher e Telegram (§4.1, §4.5):** rodei 20.000 combinações de `Content-Encoding` (caixa, espaços Unicode, listas, headers repetidos, bytes não ASCII) e comparei cada uma com o decodificador que o `httpx` escolheria de verdade. Nenhum caso foi aceito pela conferência e depois descomprimido. No publisher, `_read_body` é o único leitor de corpo, e o `check_health` não lê. Nenhum outro `httpx.Client` de produção existe na borda nem nos alertas.
- **Varredura (§4.2, R-14):** num dataset sintético fora do repositório, a pasta `0o000` saiu como `raw/nut/good: unreadable`, com código 1 e sem caminho absoluto. Com `--fix`, o resultado foi o mesmo, e os bytes da imagem na pasta não mudaram.
- **Painel (§4.4):** comparei `urlsplit` e `httpx` em 34 URLs feitas para desviar o destino (`\@`, `#@`, `?@`, porta falsa, `http:` sem barras, IDNA). As 12 aceitas têm o mesmo host nos dois parsers, e nenhuma manda `http://` para fora de `localhost` ou `127.0.0.1`. A `is_secure_api_url` só monta o `httpx.Request`; ela não envia nada.
- **Heartbeat (§4.3) e alertas:** o log do heartbeat tem só a classe, sem `exc_info`. O aviso do envio abandonado não abre caminho para forjar linha de log, porque o `lot_id` passa por `LOT_ID_PATTERN` e o `source` é enum.
- **ML (§4.6, §4.7, R-11):** as conferências rodam antes de qualquer linha e não ecoam valores. A leitura dos JSONs só acrescenta tipos "não novos", com o caminho montado a partir da versão inteira.
- **Testes:** com banco, rodei os testes do autor e os aceites da SPEC-040 de `edge/`, `dashboard/`, `api/` e `ml/`, mais o `test_spec_017.py`: **1404 passed**. Nenhum código de produção mudou depois do commit testado (`2fa9248`).
- **R-03 e R-13:** busquei nas linhas adicionadas do diff inteiro padrões de JWT, token do Telegram, URL com senha, chave privada e nome de empresa, e não achei nada. No código e nos READMEs das Partes A e B, as únicas URLs novas são a do Telegram e a `https://xn--zz.com`, esta citada num docstring sobre URL inválida, e não há IP novo.
- **R-02 e R-05:** nenhum envio novo de imagem. A resposta recusada mantém o item `pending`, sem passar por `dead` (CA-03, que rodei).
- **Separação de papéis (R-07):** todo commit tem `Agent:`. Os commits de produção das Partes A e B são do developer e do ml-engineer, cada um nos próprios caminhos, e os aceites só mudam no commit do tester. Não sou autor dessas partes.

**Não verifiquei:**

- nada na VPS nem no Coolify real: o CA-18 continua com o humano;
- a suíte inteira, os testes `docker`, os do broker MQTT real e o treino com torch. Os números da suíte inteira são do test-report;
- o comando `zip`, que não está instalado nesta máquina, e o `tar`. A SEC-40-A3 foi reproduzida só com o `shutil.make_archive`;
- CVEs, porque não há dependência nova.

### Riscos que continuam aceitos

- **SEC-30-03 e SEC-17-03:** fora do escopo ou mantidos pela §3.2 e pela §4.5. Esta SPEC só acrescenta o `abandoned_for_s` e o Restart documentado.
- **Proxy que comprime mesmo com `identity`:** a borda para de enviar, com `unsupported response encoding` no log, e as inspeções ficam no outbox. Só o CA-18 descarta esse caso na VPS.

### Ações pendentes (humano e orquestrador)

- **Humano:** executar o CA-18 depois do deploy pela `main`. O ideal é o merge antes do ensaio do M4 (29/11), e nenhum merge na véspera nem no dia da apresentação (SPEC §7).
- **Orquestrador:** registrar SEC-40-A1, SEC-40-A3 e SEC-40-B1 no `docs/plan.md` §3 como pendências da SPEC-040.

### Dependências novas

Nenhuma.

### Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi esta seção, o veredicto e a tabela de partes deste relatório.
- [x] Não sou autor das Partes A e B. A Parte C é minha, e não a avaliei aqui.
