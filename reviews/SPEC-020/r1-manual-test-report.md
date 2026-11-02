# SPEC-020 e SPEC-018 — r1 — Test report dos CAs manuais contra a produção

| Campo | Valor |
|---|---|
| SPECs | [SPEC-020](../../docs/specs/SPEC-020-mqtt.md) (CA-12) e [SPEC-018](../../docs/specs/SPEC-018-heartbeat-dispositivos.md) (CA-13) |
| Rodada | r1, manual |
| Tester | agente `tester`, sem celular e sem navegador |
| Data | 2026-11-02, horários em UTC |
| Commit testado | `d5c77b2` na borda, na ponte e no simulador. A versão publicada na VPS não foi conferida (sem SSH) |
| Onde | Borda, ponte e broker em `127.0.0.1`, contra a API de produção em `https://<subdominio>` |
| Modelo | `partqc-mnv3-provisional-v1`, sha256 `3169691d0ea5…` (ADR-024) |
| Imagens | As públicas de `~/partqc-provisorio/data`, enviadas com o `send.py` da §6 de `reviews/SPEC-041/r1-e2e-test-report.md` |
| **Veredicto** | **CA-12 da SPEC-020: PASS. CA-13 da SPEC-018: PASS.** Com as ressalvas da §5. Um bug de severidade baixa e três observações |

> **Ressalva obrigatória (R-11, ADR-024).** O modelo é provisório e as inspeções saem como `source=simulated`, o que é o esperado. Este relatório verifica transporte e estado dos dispositivos. Nenhum número dele mede a qualidade do modelo, e nenhum pode ser apresentado como métrica.

## Cobertura dos critérios de aceite

| Critério | Como foi verificado | Resultado |
|---|---|---|
| SPEC-020 CA-12 | Fluxo real com `EDGE_PUBLISHER=mqtt`; conferência por `GET /api/v1/inspections` e pelo `mosquitto_sub` (§1) | ✅ PASS |
| SPEC-018 CA-13 | `GET /api/v1/devices` com a chave de leitura e as funções da página "Dispositivos" sobre a resposta real (§2) | ✅ PASS |

## 1. SPEC-020 CA-12

| Passo | Horário | O que aconteceu | Resultado |
|---|---|---|---|
| 1. Broker local | 14:18 | Imagem `eclipse-mosquitto:2` (`sha256:a46a9080d48c`, versão 2.1.2), com a `edge/mosquitto/partqc.conf` do repositório, trocando só a porta (11883) e o `password_file`. Escuta só em `127.0.0.1:11883` | ✅ |
| 1. Sem anônimo | 14:21 | Sem usuário e com senha errada: `Connection error: Not authorized`. No broker: `disconnected: not authorised` | ✅ |
| 2. Ponte e borda | 14:18 | Log da borda: `publisher: mqtt (broker 127.0.0.1:11883, answer timeout 15 s; ...)`, `device_id=edge-01`, sem `--stub-model`. Conectividade `online`, pendentes 0 | ✅ |
| 3. 10 inspeções | 14:19:37 a 14:19:41 | Lote `PROD-MQTT-01`: 10 respostas 200 em `POST /api/capture` | ✅ |
| 4. As 10 na nuvem | 14:19:51 | `total=10`, 10 ids distintos, 0 faltando e 0 sobrando em relação às respostas da borda. Todas `simulated`, `edge-01` e com o modelo provisório. A ponte registrou lotes de 4 e de 6 com `ok` | ✅ |
| 5. Derrubar a ponte | 14:20:06 | SIGINT (equivale ao Ctrl+C); a ponte saiu com código 0 | ✅ |
| 5. 3 inspeções | 14:20:17 | Lote `PROD-MQTT-02`: 3 respostas 200 | ✅ |
| 5. Pendentes | 14:20:43 | `/api/status` com `pending=3` e `connectivity=offline`. Console com `Pendentes` 3 e conectividade `offline`. Na nuvem: `total=0`. Log: `no answer from the mqtt bridge within 15 s`. A rota de dispositivos também mostrou `outbox_pending=3` | ✅ |
| 5. Religar a ponte | 14:20:55 | Lotes de 2 (14:21:11) e de 1 (14:21:14) com `ok`. Às 14:21:15: pendentes 0 e `online` | ✅ |
| 5. As 3 na nuvem | 14:21:26 | `total=3`, 3 ids distintos, 0 faltando e 0 sobrando, com atraso máximo de 56,8 s. No outbox: 13 linhas `sent`, nenhuma `dead` | ✅ |
| 6. `mosquitto_sub` com usuário | durante tudo | Lotes no tópico `partqc/v1/edge-01/batch`, sem imagem (abaixo) | ✅ |

O `mosquitto_sub` ficou ligado do início ao fim, com `-V mqttv5 -t 'partqc/v1/#'` e o usuário do broker. Ele guardou o payload em hexadecimal, para conferir os bytes:

| Item | Resultado |
|---|---|
| Mensagens | 7 em `.../batch`, 6 em `.../reply/<sessão>` e 2 em `.../health`, estas sem payload |
| Contrato | Os 7 lotes validaram como `BatchCreate`, com só as 14 chaves do contrato em cada item |
| Tamanho | No máximo 2 879 bytes por lote e 469 por resposta |
| Imagem | Nenhuma assinatura de JPEG, PNG, base64, `data:image`, `JFIF` ou multipart em nenhuma mensagem |
| Itens | 19 publicações de 13 ids distintos: os 3 de `PROD-MQTT-02` saíram 3 vezes cada (2 sem resposta e 1 com `ok`), e a nuvem guardou uma vez cada (R-05) |

Um item de lote, como passou no tópico:

```json
{"inspection_id": "70826458-ed96-4413-bc21-b24ca16edf59", "device_id": "edge-01", "lot_id": "PROD-MQTT-01", "inspected_at": "2026-11-02T14:19:37.901720Z", "object_type": "screw", "grade": "perfect", "grade_score": 0.5591344423592091, "type_confidence": 0.918967068195343, "grade_confidence": 0.7955381870269775, "needs_review": false, "model_version": "partqc-mnv3-provisional-v1", "model_sha256": "3169691d0ea5e458f4585208a28354464ebc39149a1fbf4fa3ef2f72a89cee58", "latency_ms": 12, "source": "simulated"}
```

As 13 fotos ficaram só na pasta temporária da borda, com modo `0600`, e foram apagadas no fim.

## 2. SPEC-018 CA-13

**Base, antes do teste (14:18:08):** `edge-01` `online=false`, com o último heartbeat às 04:32:29. `sim-01` `online=false`, `last_source=simulated`, `last_seen_at` 04:31:29.

| Passo | O que foi visto | Resultado |
|---|---|---|
| 1 e 2. Borda ligada, online, com modelo e filas | 14:19:54: `online=true`, `model_version=partqc-mnv3-provisional-v1`, `outbox_pending=6` (um lote a caminho), `outbox_dead=0`. 14:20:45, com a ponte fora: `outbox_pending=3`. Com a fila vazia, a linha da página: `edge-01`, `online`, `simulado`, `partqc-mnv3-provisional-v1`, `Pendentes` 0, `Com falha` 0 | ✅ |
| 3. Borda desligada, `offline` em até 3 min | **1ª medida**, leitura a cada 16 s, parada às 14:22:08: `online` em t+170 s e `offline` em t+187 s. A virada ficou entre as duas leituras, o que não decide o limite de 180 s. **2ª medida**, leitura a cada 4 s, parada às 14:26:46: `online` em t+172,9 s e **`offline` em t+176,8 s** | ✅ |
| 4. `sim-01` como simulado | 14:25:42 a 14:25:48, `--lots 1 --lot-size 20`, código 0: `sent=20 created=20 duplicate=0 lots=1 seed=1307403150 source=simulated`. Às 14:25:48: `last_source=simulated`, `last_seen_at` 14:25:45 (antes, 04:31:29), `online=false`, sem heartbeat | ✅ |

- **O `last_seen_at` é a prova do passo 4.** O `sim-01` já estava `simulated` antes do teste, então o campo novo é o que mostra o efeito desta rodada.
- **A virada bate com a regra da SPEC:** na 2ª medida, o último heartbeat foi às 14:26:39,49, e 180 s depois dá 14:29:39,49, entre as duas leituras de borda (data do servidor 14:29:37 e 14:29:41).

**O que a página mostraria.** Sem navegador, `formatting.device_rows` e `formatting.has_simulated_device`, as funções usadas por `dashboard/views/dispositivos.py`, rodaram sobre a resposta real, depois da 1ª medida e da rodada do simulador:

```text
{"Dispositivo": "edge-01", "Situação": "offline", "Origem": "simulado", "Último sinal": "02/11/2026 11:22", "Modelo": "partqc-mnv3-provisional-v1", "Versão": "0.0.0", "Pendentes": "0", "Com falha": "0", "Ligado há": "0 h 03 min"}
{"Dispositivo": "sim-01", "Situação": "offline", "Origem": "simulado", "Último sinal": "nunca", "Modelo": "—", "Versão": "—", "Pendentes": "—", "Com falha": "—", "Ligado há": "—"}
simulated badge: True
```

`GET /api/v1/devices` sem chave respondeu 401 em produção, a conferência sugerida em `reviews/SPEC-018/r1-security-report.md`.

## Suíte completa

Não rodei a suíte nem o ruff. Esta rodada é manual, e nenhum código mudou: o único arquivo alterado é este relatório.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| MAN-01 | baixa | nenhum CA afetado | 1. Suba a ponte com um `CLOUD_API_URL` real. 2. Envie um lote. 3. Leia o log da ponte | Só contagens, `result` e tópico (`edge/README.md`, seção "Transporte MQTT") | Também a URL completa, em linhas do `httpx`: `INFO HTTP Request: POST https://<subdominio>/api/v1/inspections/batch "HTTP/1.1 200 OK"` |

Sobre o MAN-01:

- **Causa provável:** o `logging.basicConfig(level=logging.INFO)` de `edge/src/qc_edge/mqtt_bridge.py` também liga o logger do `httpx`.
- **Alcance:** 6 linhas no log da ponte e nenhuma no log da borda. A URL não é segredo, e o CA-09 da SPEC-020 continua valendo: nenhuma chave, senha ou payload apareceu.
- **Risco:** colar esse log no repositório público publica o subdomínio, o que a R-13 pede para evitar.

## Testes exploratórios (além dos critérios)

| ID | O que foi visto | Para quem |
|---|---|---|
| OBS-01 | **Duas rodadas do simulador no mesmo dia UTC caem no mesmo lote.** O `lot_id` só tem a data e o número (`SIM-20261102-001`). O lote já tinha 50 linhas de uma rodada anterior e foi a 70. Segue o texto da SPEC-014, então não é bug, mas muda o `n` do lote simulado na carta. A carta padrão não é afetada, porque usa `live` | architect |
| OBS-02 | **`uv run --env-file` não aceita caminho com espaço.** O uv 0.13.6 separa o valor nos espaços: com o checkout em `Área de trabalho`, o erro é `No environment file found at: trabalho/Projeto_IoT_AI_Agent/.env.prod`. Os comandos do repositório usam caminho relativo (`.env`, `.env.prod`) e não sofrem com isso | dupla |
| OBS-03 | **Depois de religar a ponte, a fila levou 19 s para sair**, com o tempo de resposta padrão de 15 s. Um pedido publicado antes de a ponte assinar o tópico se perde e espera o tempo inteiro, e o backoff é por item. A demonstração deve contar com isso. O comportamento segue o README | dupla |

Também foi conferido:

- **Segredos:** uma contagem em todos os logs, com os 5 valores vigentes, deu 0 ocorrências de cada. O subdomínio só apareceu no log da ponte (MAN-01).
- **Erros:** nenhum traceback nos logs da borda e da ponte.
- **`Versão` `0.0.0`:** continua na rota e na página, como na OBS-02 de `reviews/SPEC-041/r1-e2e-test-report.md`.

## SPEC_ISSUE

Nenhum.

## 3. Dados deixados na produção

Nada foi apagado, conforme o pedido, e tudo está marcado como simulado:

| O quê | Quantidade |
|---|---|
| `PROD-MQTT-01` | 10 inspeções, `simulated`, `edge-01` |
| `PROD-MQTT-02` | 3 inspeções, `simulated`, `edge-01` |
| `SIM-20261102-001` | 20 inspeções novas, `simulated`, `sim-01`, somadas às 50 que já existiam (OBS-01) |
| `edge-01` e `sim-01` | Campos de heartbeat e `last_seen_at` atualizados |

## 4. Desvios e operação

1. **Segunda medida do passo 3 do CA-13, fora do roteiro.** A primeira não decidia o limite de 3 min, porque o intervalo entre as leituras era grande demais, por escolha minha. Repeti com mais uma subida da borda, cerca de 2 heartbeats, 1 health check e 6 leituras, 5 delas concentradas no fim da janela, em vez de declarar o limite só pela regra.
2. **Links simbólicos para os `.env`.** Por causa da OBS-02, o `--env-file` recebeu um caminho absoluto em `/tmp/claude-1000/`, com um link para cada arquivo de ambiente. Os valores não foram copiados nem impressos. Toda saída da nuvem e dos logs passou por um script que mascara o subdomínio, as chaves e os IPs. Os links foram apagados.
3. **Arquivos temporários pelo shell.** A guarda de caminhos (`.claude/hooks/guard_paths.py`) recusa `Write` fora do repositório, e por isso nem tentei usá-lo ali. Os wrappers, o `send.py` e os scripts de apoio foram criados com o `Bash`, sob `/tmp/claude-1000/`, como o pedido previa. **Nenhum caminho foi negado pela guarda.** O isolamento da worktree recusou alguns comandos compostos, e eu os dividi em comandos simples, como a mensagem de recusa pedia.
4. **Senha do broker na linha de comando.** Como no ensaio da SPEC-041, ela é descartável e passou por `-b` e `-P` nos contêineres locais, o ponto já apontado no SEC-02 de `reviews/SPEC-020/r1-security-report.md`. O broker não existe mais.
5. **Imagem do Mosquitto, e não o pacote do Arch**, por instrução, porque o pacote deu problema antes. A versão é a mesma (2.1.2), mas o binário e o empacotamento são outros.
6. **Lotes `PROD-MQTT-…`, por instrução.** O README sugere `ENSAIO-…` para o modelo provisório. A origem continua `simulated`, então os dados ficam fora do SPC padrão, da taxa `live` e dos alertas.
7. **`uv run --frozen`**, para não mudar o `uv.lock`.

**Limpeza feita:** borda, ponte, broker e assinante parados, sem contêiner do teste sobrando, portas 18000 e 11883 livres. A pasta temporária (outbox, fotos, arquivo de senhas, token e logs) foi apagada. O `partqc-pg` e `~/partqc-provisorio` não foram tocados.

## 5. O que não pôde ser verificado

- **Celular e câmera:** as "peças" foram imagens públicas enviadas à rota real. Foto de verdade, página `/capture` e LAN ficaram de fora. O CA diz "manual, dupla", e o passo pelo celular continua sendo só da dupla.
- **Painel na tela:** nem a página "Dispositivos" nem o histórico foram abertos. A conferência foi pela rota da API e pelas funções da página, então o selo desenhado, o cache de 30 s e a publicação do Streamlit na VPS não foram vistos.
- **Tráfego entre a ponte e a API:** sem proxy nem captura de pacotes nesta rodada. A ausência de imagem foi conferida no tópico MQTT e no outbox (payload de no máximo 480 bytes). A ponte repassa esses mesmos lotes, validados pelo contrato, mas o que saiu dela para a API não foi observado diretamente.
- **Versão na VPS:** sem SSH, não dá para afirmar que a API publicada corresponde a `d5c77b2`.
- **Pacote `mosquitto` do Arch** (desvio 5).

## Declaração

- [x] Não alterei código de produção, só este relatório.
