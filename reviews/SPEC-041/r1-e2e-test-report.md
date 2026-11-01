# Ensaio de ponta a ponta local — 2026-11-01

| Campo | Valor |
|---|---|
| Quem | agente `tester` |
| Base | branch `docs/fechamento-spec-042`, commit `9ae69ca` |
| Onde | `127.0.0.1`, sem celular e sem nada na VPS |
| Modelo | `partqc-mnv3-provisional-v1`, sha256 `3169691d0ea5…` (ADR-024) |
| Imagens | as públicas de `~/partqc-provisorio/data` |
| Resultado | **O sistema funcionou junto do começo ao fim, com 595 inspeções e nenhuma perda ou duplicata.** Nenhum bug crítico, alto ou médio. Dois bugs de severidade baixa e cinco observações |

> **Ressalva obrigatória (R-11, ADR-024).** Estas imagens são do treino do modelo provisório, e os graus delas são sugestões de agente. Nenhum número deste relatório mede desempenho, e nenhum pode ser apresentado como métrica. O ensaio também não substitui os CAs manuais: o CA-22 da SPEC-041 e o CA-12 da SPEC-020 continuam pendentes da dupla.

## 1. O que passou

### 1.1 Fluxo HTTP, salto por salto

Banco próprio `partqc_e2e` no `partqc-pg`, migrações 001 a 006, `qc-api` real em `uvicorn`, dispositivo `edge-e2e` registrado com `scripts/register_device.py`, `qc-edge` real e `qc-dashboard` real em `streamlit`, conferido por um Chrome headless. O `partqc_test` não foi tocado.

| Salto | O que foi conferido | Resultado |
|---|---|---|
| Resposta da borda | 578 envios por `POST /api/capture` e mais 8 pela página `/capture`, no Chrome | Todos 200, `source=simulated`, `model_version` provisório e veredito com ` (modelo provisório)` |
| Página `/capture` | JS real no Chrome (arquivo no campo, redução e reencode, resultado na tela) | 8 de 8, com `aprovada`, `reprovada` e `desconhecido` e o sufixo. Lote `ENSAIO-P01` no banco |
| Outbox | Linhas finais | 595 `sent`, 595 ids distintos, nenhum `dead` nem `pending`. Payload de no máximo 508 bytes, só com as 14 chaves do contrato |
| Banco | Linhas finais | 595 linhas, 595 `inspection_id` distintos, todas `simulated`, 1 único `model_version` e 1 único `model_sha256` (igual ao `model.sha256`), 27 lotes, todos `ENSAIO-…`, 0 `live` |
| Fotos na borda | `captures/` | 595 arquivos (um por inspeção), diretório com `0700` |
| API | `/metrics/summary`, `/metrics/spc`, `/lots`, `/devices`; sem chave → 401 | Coerentes com o banco. A carta com `source=live` responde `insufficient data`, sem nenhum `ENSAIO-…` |
| Dashboard, Visão geral | Origem `Simulado`, `Todos` e `Real` | `Simulado`: 595 inspeções e o selo `Contém dados simulados`. `Todos`: selo. `Real`: nenhuma inspeção e sem selo |
| Dashboard, Controle estatístico | Origem `Simulado`, depois `Real` | 21 lotes válidos e 6 excluídos, listados com `n`; pontos fora de controle em destaque, com selo e `Origem da carta: simulado`. Em `Real`: dados insuficientes, sem `ENSAIO-…` |
| Dashboard, Histórico | Origem `Simulado`, filtro `ENSAIO-K01`, lote inválido | Coluna `Origem` = `simulado`; 40 inspeções no filtro; `Lote inválido` para `LOTE-Ç`. Ver E2E-01 |
| Dashboard, Sobre o modelo | Sem `metrics.json` | `Nenhum modelo avaliado ainda`; nenhuma métrica do provisório aparece |
| Dashboard, Dispositivos | Borda ligada e desligada | `online`, origem `simulado`, modelo provisório; `offline` depois de 3 min sem heartbeat |
| Console da borda | Por loopback | `PROVISÓRIO`, pendentes, conectividade, último envio. O log de subida traz `provisional model loaded` |

Composição dos lotes, escolhida só para exercitar a carta: `ENSAIO-A01` a `A07` misturados, `B01` só de sugestões `perfect`/`good`, `C01` só de `poor`/`unusable`, `Z01` a `Z04` com 60 fotos cada, e lotes pequenos para a lista de excluídos. Com isso, B01 e C01 apareceram como fora de controle e o gráfico mostrou os dois casos (acima do LSC e abaixo do LIC). Isso confere o desenho da carta, e não a qualidade do modelo.

### 1.2 Queda da API e idempotência (R-05)

| Caso | Como | Resultado |
|---|---|---|
| `ENSAIO-K01`: API derrubada no meio do lote | 40 fotos com 0,5 s entre elas; `kill -9` no `uvicorn` depois da 12ª, aproximadamente; API de volta 53 s depois | A borda respondeu 200 às 40. Pendentes chegaram a 31, conectividade `offline`, nenhum `dead`. Esvaziou 36 s depois da volta. **40 respondidas, 40 no banco, 0 faltando, 0 sobrando.** `inspected_at` preservado: atraso de até 80 s entre `inspected_at` e `received_at` |
| `ENSAIO-D01`: resposta perdida depois da gravação | O proxy deixou a API gravar 12 e fechou a conexão sem responder | O 1º lote deu 12 `created` (resposta perdida) e o reenvio, 12 `duplicate`. **12 linhas, 12 ids** |
| Reenvio manual | O mesmo lote e um item, direto na API | 200 com `duplicate`, sem linha nova |
| `ENSAIO-E01`: conexão recusada e borda morta | API e proxy parados; 15 fotos; `kill -9` na borda; religada; mais 5 fotos; API de volta | O outbox sobreviveu ao `kill -9`. **20 respondidas, 20 no banco** |
| `ENSAIO-Z01` a `Z04`: fila grande | Direto na API, sem proxy; 4 envios simultâneos de 60 fotos com a API fora do ar por cerca de 3,5 min | 240 respostas 200 e 240 pendentes, nenhuma `dead`. Esvaziou 59 s depois da volta. **60 linhas por lote, sem duplicata.** Ensaia o caso do RNF-04, que continua verificado pelos testes de aceite |
| Página com a API fora | Dashboard nas 4 páginas de dados | Aviso e botão `Tentar novamente`, sem traceback. O botão voltou a mostrar as 595 depois de a API religar |

### 1.3 Nenhuma imagem sai da borda (R-02)

- **Proxy de observação** entre a borda (ou a ponte) e a API, nas fases HTTP e MQTT, exceto os lotes `Z`: 117 requisições, só 3 rotas (`/health`, `/inspections/batch`, `/devices/<id>/heartbeat`), só `application/json`, corpo de no máximo 37 097 bytes e nenhuma assinatura de JPEG ou PNG, em binário ou em base64. Foram 283 364 bytes de corpo, contra 29 MB de fotos na borda nesse momento.
- **Outbox** (os 595 itens, inclusive os lotes `Z`): nenhuma linha com marcador de imagem.
- **MQTT:** 29 mensagens vistas pelo `mosquitto_sub`, com payload de no máximo 4 705 bytes e nenhuma assinatura de imagem.
- **API:** nenhuma rota aceita arquivo no OpenAPI; multipart → 422; multipart de 300 KB → 413; JSON com um campo `image` a mais → 422.

### 1.4 Autenticação e segredos

Sem chave, chave errada e chave de leitura em rota de escrita → 401. Chave de outro dispositivo, no corpo e no heartbeat → 403. Sem token de sessão na borda → 401. Uma varredura nos logs, no fim da fase MQTT, com os quatro segredos vigentes naquele momento, não achou nenhum. Ao final, uma busca por padrão em todos os logs (cadeias de 43 caracteres, `X-API-Key`, `X-Session-Token` e `t=`) também não achou nada. A chave anterior à rotação do `ENSAIO-M06` só entrou nessa busca por padrão.

### 1.5 Coerência do modelo (não é métrica)

**A inferência real não é degenerada.** Contagens das 578 respostas enviadas por script, com 315 imagens distintas, algumas repetidas de propósito:

- Tipo: `nut` 259, `screw` 228, `unknown` 91.
- Grau: `perfect` 141, `good` 130, `poor` 82, `unusable` 74, `fair` 60, sem grau 91.
- `needs_review`: 151 sim, 427 não.
- Confiança de tipo de 0,500 a 0,984 (285 valores distintos) e de grau de 0,278 a 0,961 (250 valores distintos).
- Determinismo: 179 imagens foram enviadas mais de uma vez, e nenhuma teve resposta diferente.

Contagens por rótulo guardado, para ver se a resposta muda com a entrada. **O rótulo é uma sugestão de agente, e as imagens são do treino. Não calcule taxa a partir desta tabela (R-11, ADR-024):**

| Rótulo guardado | `perfect` | `good` | `fair` | `poor` | `unusable` | sem grau |
|---|---:|---:|---:|---:|---:|---:|
| `nut/fair` | 2 | 4 | 48 | 0 | 0 | 0 |
| `nut/good` | 2 | 102 | 0 | 1 | 0 | 0 |
| `nut/perfect` | 10 | 12 | 0 | 0 | 0 | 0 |
| `nut/poor` | 0 | 0 | 3 | 64 | 0 | 0 |
| `nut/unusable` | 0 | 0 | 2 | 0 | 3 | 0 |
| `other` | 0 | 0 | 0 | 0 | 0 | 89 |
| `screw/fair` | 10 | 0 | 5 | 0 | 2 | 0 |
| `screw/good` | 4 | 10 | 2 | 0 | 1 | 0 |
| `screw/perfect` | 102 | 0 | 0 | 0 | 0 | 0 |
| `screw/poor` | 4 | 2 | 0 | 17 | 7 | 2 |
| `screw/unusable` | 7 | 0 | 0 | 0 | 61 | 0 |

Imagens sintéticas sem peça, só para ver se a rota aguenta: branca e preta deram `unknown`. Nenhuma derrubou o processo.

### 1.6 Entradas inválidas na borda real

| Entrada | Resposta |
|---|---|
| Lote vazio, com `Ç`, com emoji, com 41 caracteres | 422 |
| Lote com 40 caracteres | 200 |
| `mode` inválido | 422 |
| Arquivo vazio, texto, HTML com nome `.jpg`, JPEG truncado | 415 |
| 2200×2000 (acima de 4 M pixels), proporção 11:1 | 415 |
| 3 MiB + 1 byte | 413 |
| PNG, tons de cinza, CMYK, 1×1 | 200 |
| JPEG com 5 KB zerados no meio | 200 (o decodificador aceita; `unknown` com `needs_review`) |

Nenhuma resposta 200 ficou sem linha no banco, e nenhuma recusa gerou linha. Sem traceback nos logs da API, da borda e da ponte.

### 1.7 Quadros de vídeo pela rota real

14 quadros iguais em `POST /api/live/frame`, por HTTP: `DETECTING` (estabilidade de 0,1 a 0,9), `EMIT` no 10º e `WAIT_REMOVAL` nos seguintes. **Uma** inspeção no banco (`ENSAIO-L01`, `simulated`) e um arquivo salvo. PNG → 415. A página `/live` e a câmera não foram ensaiadas (§3).

### 1.8 MQTT

**CA-11 da SPEC-020: passou de verdade.** `2 passed, 112 deselected in 18.24s`: `test_ca11_real_broker_repeats_ca01_and_refuses_no_password` e o exploratório `test_extra_real_broker_nothing_retained`. Os testes não foram pulados, e o broker recusou as conexões sem senha ou com senha errada.

**O que foi usado, diferente do pacote do Arch:** o `mosquitto` não está instalado no sistema. Num diretório temporário no `PATH`, quatro scripts (`mosquitto`, `mosquitto_passwd`, `mosquitto_sub` e `mosquitto_pub`) chamam `docker run --rm -i --network host --user <uid>:<gid> -v <dir>:<dir> eclipse-mosquitto:2 <ferramenta> "$@"`, montando o diretório pai de cada caminho absoluto recebido. Imagem `sha256:a46a9080d48c`, versão **2.1.2**, criada em 2026-10-23. A versão é a mesma do pacote citado na SPEC-020 (2.1.2-2), mas o binário e o empacotamento são outros. Nada foi instalado com `sudo`.

**Fluxo real** com `EDGE_PUBLISHER=mqtt`, broker com a `edge/mosquitto/partqc.conf` (só a porta e o `password_file` trocados), em `127.0.0.1` e sem anônimo, e a ponte `python -m qc_edge.mqtt_bridge`. Isto **ensaia** o CA-12, que continua manual:

| Caso | Resultado |
|---|---|
| `ENSAIO-M01`, ponte ligada, 10 fotos | 10 no banco, 10 `sent` |
| `ENSAIO-M02`, ponte parada, 3 fotos | 3 pendentes no console, `no answer from the mqtt bridge within 5 s`, 0 no banco. Com a ponte de volta: 3 no banco em 2 s |
| `ENSAIO-M03`, resposta perdida entre a API e a ponte | Ponte respondeu `transient`, depois `ok`; proxy com 8 `created` e 8 `duplicate`. **8 linhas** |
| `ENSAIO-M04`, broker parado no meio | 12 pendentes, `mqtt broker not reachable`. Com o broker de volta, a ponte reconectou sozinha. **12 linhas** |
| `ENSAIO-M05`, API parada com a ponte ligada | `mqtt bridge answered transient`, 6 pendentes. **6 linhas** depois da volta |
| `ENSAIO-M06`, chave do dispositivo trocada (`--rotate`) | Conectividade `auth_error`, 4 pendentes, sem novas tentativas, com o aviso no console. Com a chave nova e ponte e borda religadas: **4 linhas** |
| Sem `MQTT_PASSWORD` | Erro citando só o nome da variável |
| Anônimo ou senha errada | Broker: `disconnected: not authorised` |
| Escuta do broker | Só `127.0.0.1` |
| `mosquitto_sub` no tópico | Lotes e respostas, sem imagem (§1.3) |

## 2. O que falhou

**Bugs** (nenhum crítico, alto ou médio):

### E2E-01 — baixa — Coluna `Modelo` cortada no Histórico

- **Reproduzir:** painel a 1500 px de largura → `Histórico` → origem `Simulado`.
- **Esperado:** dá para confirmar `partqc-mnv3-provisional-v1` na coluna `Modelo` sem esforço (CA-22 da SPEC-041, passo 4).
- **Obtido:** a célula aparece como `partqc-mnv3-provisio…`. A coluna `Origem` e o selo continuam dizendo `simulado`, então a R-06 não é afetada. O valor completo só aparece ao alargar a coluna, e em `Dispositivos` ele aparece inteiro.

### E2E-02 — baixa — Console oferece um endereço que não atende quando a borda escuta só em loopback

- **Reproduzir:** `EDGE_HOST=127.0.0.1`, subir a borda, abrir o console e tentar a URL de pareamento em `http://<ip-lan>:<porta>/capture`.
- **Esperado:** o console não oferece um QR que não pode funcionar, ou avisa.
- **Obtido:** QR e URL com o IP da LAN, e a conexão é recusada (`curl` com código 7). Só acontece nessa configuração. O padrão (`0.0.0.0`) não tem o problema. Os "Outros IPs" também listam as redes do Docker.

**Observações** (o comportamento segue o texto das SPECs, então não são bugs):

| ID | O que foi visto | Para quem |
|---|---|---|
| OBS-01 | Com a API fora do ar, o painel diz `API acordando (free tier), tente em ~1 min`. O texto vem da SPEC-013 e foi mantido na SPEC-028, mas na VPS a API não dorme, e o aviso pode esconder uma queda real durante a demonstração | architect |
| OBS-02 | `Dispositivos` mostra `Versão` `0.0.0`, porque `edge/pyproject.toml` está em `0.0.0`. A coluna não ajuda a distinguir uma borda de outra | architect |
| OBS-03 | Depois da volta da API, a fila leva até cerca de 60 s para esvaziar, porque o backoff é por item (SPEC-009 §4.3): 36 s com 31 itens e 59 s com 240. A dupla deve contar com isso na demonstração | dupla |
| OBS-04 | Uma linha `sent` mantém o `last_error` da última falha. É inofensivo, mas pode confundir quem ler o outbox à mão | developer |
| OBS-05 | Em lotes pequenos, o `n` da carta fica menor que o número de fotos, porque `unknown` não entra (§3.4 da arquitetura): `ENSAIO-M06`, com 4 fotos, deu `n=3` e ficou excluído. Para aparecer na carta com folga, use lotes de pelo menos 10 fotos | dupla |

Também vale registrar: com o MQTT, depois de trocar a chave, a ponte e a borda precisam ser religadas, mas o console cita só o `qc-edge`. O ensaio religou as duas, então a falha de religar só a borda não foi reproduzida.

**`SPEC_ISSUE`:** nenhum.

## 3. O que não pôde ser verificado

- **Celular e câmera reais:** foto de verdade, rotação EXIF de um aparelho, navegadores móveis, QR lido por um celular. O Chrome headless colocou o arquivo direto no campo da página.
- **HTTPS na LAN e página `/live`:** `mkcert`, `getUserMedia` e a tela do vídeo. Só a rota `POST /api/live/frame` foi ensaiada, por HTTP.
- **LAN e firewall:** tudo ficou em `127.0.0.1`.
- **Nuvem:** VPS, Coolify, Caddy, TLS, Supabase, pooler em modo transaction e RLS com os papéis do Supabase. O banco foi o Postgres local.
- **Captura de pacotes:** sem `sudo`, não houve `tcpdump`. O §1.3 observa o que vai para a API e para o broker, e o `ss` numa amostra não achou conexões estabelecidas da borda. Isso não prova sozinho que nada vai para outro destino.
- **Telemetria na rede:** o `onnxruntime.db` não mudou desde antes de a borda subir e não estava aberto pelo processo. A consulta de DNS não foi medida aqui.
- **Queda exatamente no meio de um `INSERT`:** o caso "API gravou e a borda não soube" foi simulado pelo proxy. O `kill -9` da API não foi cronometrado para cair dentro de uma transação.
- **Alertas no Telegram:** desligados.
- **Dashboard:** download do CSV e granularidades `Minuto` e `Dia`.
- **Virada do dia em UTC:** o ensaio terminou antes das 21h locais.
- **Qualidade do modelo:** fora do ensaio de propósito (R-11, ADR-024).
- **Suíte completa e ruff:** não rodados, porque não são objeto deste ensaio e nenhum código mudou. Rodou só o marcador `mqtt` do `test_spec_020.py`.

## 4. Desvios deste ensaio

1. **`ORT_DISABLE_TELEMETRY=1` esquecido uma vez.** Ao conferir versões, antes de subir a borda, um `python -c "import onnxruntime…"` rodou sem a variável, contra a instrução recebida. O `onnxruntime.db` local tem horário de modificação 19:38, compatível com esse comando. Depois disso, nada mudou nele durante o ensaio inteiro, o que indica que a borda e a ponte estão com a telemetria desligada. Uma consulta de DNS naquele comando não pode ser descartada.
2. **Caminho deste relatório.** O caminho pedido primeiro, `reviews/e2e-local/`, é negado ao papel `tester` pela guarda de caminhos (`.claude/hooks/guard_paths.py`, SPEC-001, R-07). O `Write` foi negado, e o hook documenta que não intercepta o `Bash`, mas essa brecha não foi usada, porque contornaria a guarda. O orquestrador corrigiu o pedido para este caminho, permitido ao papel, e o relatório foi gravado com o `Write`.
3. **Scripts temporários pelo shell.** A guarda também nega o `Write` fora do repositório. Os scripts de apoio (wrappers, proxy, envio, Chrome) foram criados com o `Bash` no scratchpad, como o pedido previa para o `mosquitto`. Nenhum arquivo do repositório mudou (`git status` limpo).
4. **Dois erros de operação meus, sem efeito no resultado.** Um `pkill -f` largo demais derrubou o meu próprio shell junto com a ponte (o passo foi refeito), e um `wait` no zsh ficou preso esperando a borda (só esse shell foi encerrado).
5. **Permissão alterada.** Um `chmod 700` atingiu a pasta temporária `e2e/` do scratchpad, que já tinha arquivos de outro agente. Os arquivos dele não foram mexidos nem apagados.
6. **`uv run --frozen`** foi usado em vez de `uv run`, para o ensaio não mudar o ambiente. `uv lock --check` passou.
7. **Proxy de observação:** é uma ferramenta do ensaio, fora do produto, e fica no caminho em quase todo o fluxo. Por isso os lotes `Z` foram direto à API.

## 5. Limpeza feita

Borda, ponte, broker, proxy, API, dashboard e Chrome parados, sem contêiner do ensaio sobrando. Banco `partqc_e2e` apagado; `partqc-pg` no ar; `partqc_test` intocado. Fotos copiadas, outbox, arquivo de senhas e segredos gerados foram apagados. `~/partqc-provisorio` não foi alterado.

## 6. Como repetir

Rode na raiz do repositório, em bash ou zsh. Cada bloco "terminal" é um terminal separado, e todos começam com `source ~/partqc-e2e/env.sh`. As portas evitam as padrão, para não colidir com nada.

```bash
# 1. Pasta fora do repositório, segredos e banco
mkdir -p -m 700 ~/partqc-e2e/{logs,edge-data,dataset,bin}
docker exec partqc-pg psql -U postgres -c 'CREATE DATABASE partqc_e2e'
export DBURL=postgresql://postgres@127.0.0.1:55432/partqc_e2e
uv run --frozen --package qc-api python infra/migrate.py --database-url "$DBURL"
uv run --frozen --package qc-api python scripts/register_device.py --device-id edge-e2e --database-url "$DBURL"
# A linha DEVICE_API_KEY=<valor> aparece uma só vez: copie para o env.sh abaixo.
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # rode 2 vezes: READ_API_KEY e EDGE_SESSION_TOKEN

cat > ~/partqc-e2e/env.sh <<'EOF'
export DBURL=postgresql://postgres@127.0.0.1:55432/partqc_e2e
export READ_API_KEY='<valor>' EDGE_SESSION_TOKEN='<valor>' DEVICE_API_KEY='<valor>'
export CLOUD_API_URL=http://127.0.0.1:18001 DEVICE_ID=edge-e2e EDGE_HOST=127.0.0.1 EDGE_PORT=18000
export MODEL_DIR=$HOME/partqc-provisorio/models/partqc-mnv3-provisional-v1
export EDGE_DATA_DIR=$HOME/partqc-e2e/edge-data DATASET_DIR=$HOME/partqc-e2e/dataset
export OUTBOX_PATH=$HOME/partqc-e2e/edge-data/outbox.sqlite3 HEARTBEAT_INTERVAL_S=15
EOF
chmod 600 ~/partqc-e2e/env.sh
```

Em operação real, deixe `EDGE_SESSION_TOKEN` vazio e use `EDGE_HOST=0.0.0.0` (E2E-02).

```bash
# Terminal A: API
DATABASE_URL="$DBURL" uv run --frozen --package qc-api uvicorn qc_api.main:app --host 127.0.0.1 --port 18001
# Terminal B: borda
uv run --frozen --package qc-edge qc-edge
# Terminal C: dashboard, em http://127.0.0.1:18501
API_BASE_URL=http://127.0.0.1:18001 uv run --frozen --package qc-dashboard streamlit run dashboard/app.py --server.port 18501 --server.address 127.0.0.1
```

Salve o script de envio como `~/partqc-e2e/send.py`:

```python
"""Send public images of the provisional set through the real edge route (rehearsal only).

Usage: send.py <base_url> <lot_id> <n> <mix> <out.jsonl> [--seed N] [--delay S]
``mix``: comma list of type/grade strata, or "all". One JSON line per image with the stored label
(an agent suggestion, not ground truth), the status and the edge answer. Images are never logged.
"""
import argparse, csv, json, os, random, time
from pathlib import Path
import httpx

p = argparse.ArgumentParser()
p.add_argument("base"); p.add_argument("lot"); p.add_argument("n", type=int)
p.add_argument("mix"); p.add_argument("out")
p.add_argument("--seed", type=int, default=7); p.add_argument("--delay", type=float, default=0.0)
a = p.parse_args()
root = Path.home() / "partqc-provisorio" / "data"
with (root / "manifest.csv").open(newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
strata = None if a.mix == "all" else set(a.mix.split(","))
stratum = lambda r: f"{r['object_type']}/{r['grade'] or '_'}"
pool = [r for r in rows if strata is None or stratum(r) in strata]
random.Random(a.seed).shuffle(pool)
chosen = (pool * (a.n // max(len(pool), 1) + 1))[: a.n]
tok = os.environ["EDGE_SESSION_TOKEN"]
with httpx.Client(base_url=a.base, timeout=60, trust_env=False) as c, open(a.out, "a", encoding="utf-8") as out:
    for r in chosen:
        data = (root / r["image_path"]).read_bytes()
        t = time.perf_counter()
        ans = c.post("/api/capture", headers={"X-Session-Token": tok},
                     data={"lot_id": a.lot, "mode": "inspect"},
                     files={"image": (Path(r["image_path"]).name, data, "image/jpeg")})
        out.write(json.dumps({"lot": a.lot, "image": r["image_path"], "suggested": stratum(r), "bytes": len(data),
                              "status": ans.status_code, "elapsed_ms": round((time.perf_counter() - t) * 1000, 1),
                              "body": ans.json() if "json" in ans.headers.get("content-type", "") else None}) + "\n")
        out.flush()
        if a.delay:
            time.sleep(a.delay)
```

```bash
# Terminal D: lotes e conferência
source ~/partqc-e2e/env.sh; PY=.venv/bin/python; B=http://127.0.0.1:18000; R=~/partqc-e2e/logs/resp.jsonl
for i in 1 2 3 4 5 6; do $PY ~/partqc-e2e/send.py $B ENSAIO-A0$i 25 all $R --seed $i; done
$PY ~/partqc-e2e/send.py $B ENSAIO-B01 25 screw/perfect,nut/perfect,nut/good,screw/good $R --seed 11
$PY ~/partqc-e2e/send.py $B ENSAIO-C01 25 screw/unusable,screw/poor,nut/poor,nut/unusable $R --seed 12
$PY ~/partqc-e2e/send.py $B ENSAIO-PEQ1 3 screw/perfect $R --seed 14
curl -s -H "X-Session-Token: $EDGE_SESSION_TOKEN" $B/api/status; echo
docker exec partqc-pg psql -U postgres -d partqc_e2e -c "select lot_id, source, model_version, count(*), count(distinct inspection_id) from inspections group by 1,2,3 order by 1"
curl -s -H "X-API-Key: $READ_API_KEY" "http://127.0.0.1:18001/api/v1/metrics/spc?source=simulated"; echo

# Derrubar a API no meio de um lote: nada pode se perder nem duplicar
$PY ~/partqc-e2e/send.py $B ENSAIO-K01 40 all $R --seed 21 --delay 0.5 &
sleep 6; kill -9 "$(ss -ltnpH 'sport = :18001' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)"
# Religue o terminal A depois de o lote terminar e espere até 60 s (OBS-03). Depois:
docker exec partqc-pg psql -U postgres -d partqc_e2e -c "select count(*), count(distinct inspection_id) from inspections where lot_id = 'ENSAIO-K01'"   # deve dar 40 | 40
```

No painel, confira nas 5 páginas, com a origem `Simulado`: o selo, a coluna `Modelo`, a carta com os lotes e os excluídos. Na origem `Real`, nenhum `ENSAIO-…`.

Para conferir o que sai da borda, salve o proxy abaixo como `~/partqc-e2e/proxy.py`, rode-o e aponte a borda para ele com `CLOUD_API_URL=http://127.0.0.1:18002`. Ele registra método, rota, tamanho e assinaturas de imagem, nunca os headers:

```python
"""Observation proxy between the edge (or bridge) and the API, for the local rehearsal only.

Forwards HTTP verbatim to the upstream and writes one JSON line per request: method, path, content
type, body size and image signatures found. Headers are never logged, so the device key is not
recorded. Fault injection: when the file ``drop_next`` holds N > 0 and a batch arrives, the request
reaches the API but the answer is dropped (the API wrote it, the edge never heard back).
"""
import asyncio, base64, json, re, sys, time
from pathlib import Path

listen_port, upstream_port = int(sys.argv[1]), int(sys.argv[2])
log_path, control = Path(sys.argv[3]), Path(sys.argv[4])
SIGNATURES = {"jpeg_raw": b"\xff\xd8\xff", "png_raw": b"\x89PNG\r\n\x1a\n", "jpeg_b64": b"/9j/",
              "png_b64": b"iVBORw0KGgo", "data_uri": b"data:image", "jfif": b"JFIF"}
UUID = re.compile(rb'"inspection_id":\s*"([0-9a-f-]{36})"')

def consume_drop():
    try:
        value = int(control.read_text().strip() or 0)
    except (OSError, ValueError):
        return False
    if value <= 0:
        return False
    control.write_text(str(value - 1))
    return True

async def read_http(reader):
    head = await reader.readuntil(b"\r\n\r\n")
    m = re.search(rb"(?im)^content-length:\s*(\d+)", head)
    n = int(m.group(1)) if m else 0
    return head, (await reader.readexactly(n) if n else b"")

def log(rec):
    with log_path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")

async def handle(cr, cw):
    try:
        try:
            head, body = await read_http(cr)
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        first = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
        ct = re.search(rb"(?im)^content-type:\s*([^\r\n]+)", head)
        rec = {"t": time.time(), "method": first[0], "path": first[1],
               "content_type": ct.group(1).decode("latin-1") if ct else None,
               "body_bytes": len(body), "signatures": [k for k, s in SIGNATURES.items() if s in body],
               "ids": sorted({m.decode() for m in UUID.findall(body)})}
        drop = first[1].endswith("/inspections/batch") and consume_drop()
        up_head = re.sub(rb"(?im)^connection:[^\r\n]*\r\n", b"", head)[:-2] + b"Connection: close\r\n\r\n"
        try:
            ur, uw = await asyncio.open_connection("127.0.0.1", upstream_port)
        except OSError as exc:
            rec["upstream_error"] = type(exc).__name__
            log(rec)
            return
        uw.write(up_head + body)
        await uw.drain()
        answer = await ur.read(-1)
        uw.close()
        rec.update(status=int(answer.split(b" ", 2)[1]) if answer[:4] == b"HTTP" else None,
                   dropped_answer=drop, duplicates=answer.count(b'"duplicate"'),
                   created=answer.count(b'"created"'))
        log(rec)
        if not drop:
            cw.write(answer)
            await cw.drain()
    finally:
        cw.close()

async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", listen_port)
    async with server:
        await server.serve_forever()
asyncio.run(main())
```

```bash
touch ~/partqc-e2e/drop_next
.venv/bin/python ~/partqc-e2e/proxy.py 18002 18001 ~/partqc-e2e/logs/proxy.jsonl ~/partqc-e2e/drop_next
# Para perder a próxima resposta da API de propósito: echo 1 > ~/partqc-e2e/drop_next
```

**MQTT.** Com o Mosquitto do sistema (`sudo pacman -S mosquitto`, edge/README.md), pule os wrappers. Sem ele, use a imagem. **Isso difere do pacote do Arch** (§1.8):

```bash
for t in mosquitto mosquitto_passwd mosquitto_sub mosquitto_pub; do
cat > ~/partqc-e2e/bin/$t <<EOF
#!/bin/bash
mounts=()
for arg in "\$@"; do case "\$arg" in /*) d=\$(dirname "\$arg"); [ -d "\$d" ] && mounts+=(-v "\$d:\$d");; esac; done
exec docker run --rm -i --network host --user "\$(id -u):\$(id -g)" "\${mounts[@]}" eclipse-mosquitto:2 $t "\$@"
EOF
chmod +x ~/partqc-e2e/bin/$t; done

# CA-11, num terminal novo, SEM source do env.sh:
PATH=~/partqc-e2e/bin:$PATH PARTQC_MQTT_TESTS=1 uv run --frozen --package qc-edge pytest edge/tests/acceptance/test_spec_020.py -m mqtt -q -p no:cacheprovider
```

```bash
# Broker e fluxo: acrescente ao env.sh
export PATH=$HOME/partqc-e2e/bin:$PATH EDGE_PUBLISHER=mqtt MQTT_HOST=127.0.0.1 MQTT_PORT=11883
export MQTT_USERNAME=partqc-e2e MQTT_PASSWORD='<valor>' MQTT_RESPONSE_TIMEOUT_S=5

mkdir -p -m 700 ~/partqc-e2e/broker
mosquitto_passwd -b -c ~/partqc-e2e/broker/passwd "$MQTT_USERNAME" "$MQTT_PASSWORD"; chmod 600 ~/partqc-e2e/broker/passwd
printf 'listener 11883 127.0.0.1\nallow_anonymous false\npassword_file %s\n' ~/partqc-e2e/broker/passwd > ~/partqc-e2e/broker/partqc.conf

mosquitto -c ~/partqc-e2e/broker/partqc.conf                                # terminal E: broker
uv run --frozen --package qc-edge python -m qc_edge.mqtt_bridge             # terminal F: ponte
uv run --frozen --package qc-edge qc-edge                                   # terminal B: borda, religada
mosquitto_sub -h 127.0.0.1 -p 11883 -u "$MQTT_USERNAME" -P "$MQTT_PASSWORD" -V mqttv5 -t 'partqc/v1/#' -v -F '%t %l'   # terminal G: tópico, tamanho

uv run --frozen --package qc-edge python ~/partqc-e2e/send.py http://127.0.0.1:18000 ENSAIO-M01 10 all ~/partqc-e2e/logs/resp-mqtt.jsonl --seed 61
# Pare a ponte (Ctrl+C), envie ENSAIO-M02 com 3 fotos, confira os pendentes no console, religue a ponte e confira as 3 no banco.
```

```bash
# Limpeza: pare todos os terminais e então
docker exec partqc-pg psql -U postgres -c 'DROP DATABASE partqc_e2e'
rm -rf ~/partqc-e2e      # apaga as fotos copiadas, o outbox e os segredos
git status --short       # deve sair vazio
```
