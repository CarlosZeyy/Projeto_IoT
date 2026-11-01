# SPEC-019 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `f727326` |
| **Veredicto** | **PASS** (CA-12 e §3.3 manuais pendentes, com o humano depois do merge; há um bug de severidade média fora dos CAs, T-01) |

Testes escritos a partir da SPEC, antes de ler a implementação. Do `r1-dev-report.md` usei só os nomes que a SPEC deixa em aberto (`qc_edge.cli.uvicorn_kwargs` e os `id` do console). Li o código de produção depois, para procurar casos de borda.

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_019.py`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_emits_the_most_recent_frame_of_the_stable_pair` | ✅ |
| CA-02 | `test_ca02_no_emission` (2 casos) | ✅ |
| CA-03 | `test_ca03_removal_needs_three_consecutive_unknowns_then_a_new_part_emits` | ✅ |
| CA-04 | `test_ca04_new_lot_restarts_the_window` | ✅ |
| CA-05 | `test_ca05_refusals_do_not_reach_the_model` (8 casos) | ✅ |
| CA-06 | `test_ca06_one_inspection_per_part` | ✅ |
| CA-07 | `test_ca07_outbox_payload_has_the_contract_and_no_image` | ✅ |
| CA-08 | `test_ca08_session_limit_and_expiry` | ✅ |
| CA-09 | `test_ca09_invalid_tls_exits_2_citing_the_variable` (5 casos), `test_ca09_valid_tls_reaches_uvicorn_and_both_qr_urls_are_https` | ✅ |
| CA-10 | `test_ca10_live_page` | ✅ |
| CA-11 | `test_ca11_invalid_live_config_exits_2` (4 casos) | ✅ |
| CA-12 (manual) | Não automatizado. Fica com a dupla, depois do merge (SPEC §3.3 e §8). O ensaio em `127.0.0.1` abaixo não o substitui | ⏳ pendente |
| CA-13 | `test_ca13_provisional_model_is_simulated_with_the_suffix`, `test_ca13_official_model_is_live_without_the_suffix` | ✅ |
| CA-14 | `test_ca14_photo_flow_without_tls_is_as_before` | ✅ |
| CA-15 | `test_ca15_empty_table_never_emits`, `test_ca15_known_type_without_grade_emits` | ✅ |
| CA-16 | `test_ca16_tie_does_not_emit_and_the_window_rolls` | ✅ |
| CA-17 | `test_ca17_result_is_never_null`; a última frase (30 respostas do CA-06) está em `test_ca06_one_inspection_per_part` | ✅ |
| CA-18 | `test_ca18_failure_to_persist_resets_and_emits_again` | ✅ |
| CA-19 | `test_ca19_failed_inference_does_not_enter_the_window` | ✅ |
| CA-20 | `test_ca20_console_latency` | ✅ |

Nenhum CA é "verificado pela execução da suíte". Nenhum teste de aceite de SPEC anterior precisou de ajuste (`docs/architecture.md` §10), e nenhum arquivo antigo de `tests/acceptance/` foi alterado.

## Suíte completa

Ambiente como no CI, sem torch (`uv sync --all-packages --locked`; `uv.lock` sem mudança, `uv lock --check` limpo), com `CI=true` e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, sem outra suíte com banco ao mesmo tempo.

```text
$ CI=true TEST_DATABASE_URL=... uv run pytest -q
10162 passed, 166 skipped, 1 warning in 1029.59s (0:17:09)

Destes, 175 são de edge/tests/acceptance/test_spec_019.py (175 passed).
Pulados: 108 sem PARTQC_DOCKER_TESTS, 49 sem torch (ambiente do CI), 6 sem PARTQC_MQTT_TESTS,
3 sem modelo real em ml/models/ ou QC_REAL_MODEL_DIR. Nenhum por falta de banco.
```

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
311 files already formatted
```

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | média | §4.4 ("para o overlay também avisar") e §4.5; R-06. Nenhum CA cobre: o CA-13 confere só o JSON | 1. Subir a borda com TLS e um modelo provisório (`MODEL_DIR=~/partqc-provisorio/models/partqc-mnv3-provisional-v1`). 2. Abrir `/live` num navegador com a largura de um celular (390 px CSS, testado com Chromium headless, `Emulation.setDeviceMetricsOverride` e câmera falsa). 3. Informar o lote e olhar a 1ª linha da faixa do overlay. | O overlay avisa que o resultado é de um modelo provisório, em qualquer largura de tela usada na demo | A 1ª linha é desenhada com `fillText`, numa linha só, sem quebra nem redução de fonte, e é cortada na borda do canvas. Em 390 px, o canvas tem 358 px, e `parafuso mediano — aprovada (modelo provisório)` mede 555 px: a tela mostra `parafuso mediano — aprovada (`, sem o aviso. O aviso só aparece nos 2 s da faixa do `EMIT`, em que o veredito tem linha própria. O corte também atinge o modelo oficial: `chave Phillips inutilizável — reprovada` mede 421 px, então parte do veredito fica de fora. Em 780 px (canvas de 512 px), o texto também é cortado (`... aprovada (modelo`). Os dados não mudam: a inspeção continua `simulated` |

Observação sobre o T-01: a causa está em `resultLines` e `drawBand` de `edge/src/qc_edge/static/live.js`. Não há teste automatizado dele, porque a suíte não roda navegador e o CA-13 fala do JSON. Se o orquestrador quiser travar esse comportamento, um CA novo é decisão do architect.

## Testes exploratórios (além dos critérios)

**Automatizados (`test_extra_*`, 68 funções), todos passando:**

| Tema | Casos |
|---|---|
| Máquina de estados | `unknown` em `IDLE`; `stability` passo a passo; média só dos quadros do par; média exatamente no limiar; janela incompleta; `unknown` como par do topo bloqueando um par conhecido com `min_agree`; `unknown` só conta em sequência; volta de `DETECTING` a `IDLE`; `reset`; empate triplo na menor janela; tipo igual com grau diferente é outro par; `WAIT_REMOVAL` segue rolando |
| Bytes em memória (§4.2, com `sys.getrefcount`) | quadro `unknown` e de `WAIT_REMOVAL` não ficam retidos; `reset` e saída da janela soltam o quadro |
| Quadro emitido | bytes em `captures/AAAA-MM-DD/<id>.jpg`, `inspected_at` e `latency_ms` são os do quadro emitido, e `result` é o do atual; `EMIT` num quadro `unknown` traz o quadro estável |
| Sessões | janelas isoladas; 2 peças, 2 inspeções; troca de lote em `WAIT_REMOVAL` emite de novo; quadro recusado (422/415) ou com inferência falha não reinicia a janela nem renova a sessão; expira só com mais de 60 s (60 s → 429; 60,5 s → 200); sessão expirada recomeça; varredura sem nova requisição; relógio para trás; teto mantido com 8 requisições simultâneas |
| Concorrência | 6 threads, 60 quadros na mesma sessão: 1 inspeção e 1 arquivo; `put` lento de uma sessão não segura a outra (gravação fora da trava, §4.3) |
| Falhas | `SinkError` (503) e erro genérico (500) apagam a foto e reiniciam; disco falhando (500), sem gravar nada, com nova emissão depois |
| Imagem | vazia, texto, só cabeçalho, truncada, corrompida, BMP e WEBP → 415; 150 JPEGs mutados com semente fixa → só 200 ou 415, nunca 500; cinza, CMYK, progressivo e com rotação EXIF → 200; 1000×1000 → 200; 1000×1001 → 415; proporção 11:1 → 415; 10:1 → 200; exatamente 1 MiB → 200 |
| Formulário | `session` com 15/65 caracteres, `\n` no fim, acento, barra e vazia → 422; 16/64 → 200; `lot_id` vazio, longo, com `\n`, com acento ou `;` → 422; campo ausente → 422; URL-encoded, JSON, sem boundary, multipart quebrado, `image` como texto, duas imagens, `session` de 1,1 MB, `lot_id` não UTF-8 e 100 campos a mais → 4xx, nunca 500, sem chamar o modelo |
| Limites | `Content-Length` de 1310721 só vale para a rota ao vivo (a captura segue com 3,5 MiB); corpo em blocos acima do limite → 413 durante a leitura |
| Ordem dos erros | token → tamanho → campos → limitador → imagem → modelo → sessões; o limitador é o da captura; 429 não chama o modelo; token na query não autoriza o `POST` |
| Latência | só os últimos 100 quadros; posto do p95 em n = 21; todas as sessões somam; quadro recusado ou com inferência falha não conta |
| Página e configuração | `LIVE_FPS` chega à página; `live.js` sem URL externa e sem token; os `LIVE_*` chegam à máquina da rota; limites do §4.6 (27 casos); modo da chave (7 casos); diretório e arquivo sem leitura → 2 |
| Console com TLS | só loopback; URLs usam o IP escolhido; `Host` sem porta só na 443 (decisão 7 do Histórico) |
| Outros | `--stub-model` serve a rota sem outbox; `unknown` provisório com sufixo e grau nulo; `drill` sem grau emite pela rota; token e sessão fora dos logs da borda; a inspeção emitida aparece no console; `.env.example` e README |

**Ensaio com o modelo provisório real, fora da suíte** (`MODEL_DIR=~/partqc-provisorio/models/partqc-mnv3-provisional-v1`, servidor real em `127.0.0.1`, sem `DEVICE_API_KEY` nem `CLOUD_API_URL`, nada foi enviado à nuvem). Só imagens sintéticas desenhadas com Pillow e a câmera falsa do Chromium; nenhuma foto. O script não é versionado e foi apagado depois. Os números abaixo descrevem o funcionamento da rota e o tempo, e não dizem nada sobre a qualidade do modelo.

| Medição | Resultado |
|---|---|
| Identidade carregada | `model_version = partqc-mnv3-provisional-v1`; sink com `connectivity = disabled` |
| Latência de inferência no console (`live-latency`), JPEG sintético de 640×480, 150 quadros seguidos, HTTP | `última 7 ms · p95 10 ms` |
| Tempo de ida e volta no cliente, mesma máquina, HTTP | p50 9,4 ms; p95 12,7 ms; máximo 14,4 ms |
| Tempo de ida e volta com TLS, servidor em processo próprio (60 quadros, conexão reaproveitada, sem o handshake) | p95 13,7 ms |
| Mesmo fluxo com TLS, servidor no mesmo processo do cliente (75 quadros do ensaio de `EMIT` abaixo, o que disputa o GIL e encarece o número) | p50 21,5 ms; p95 29,5 ms; máximo 32,6 ms. O console mostrou `última 8 ms · p95 10 ms` |
| `POST /api/capture` no modo `inspect` | 200, `source = simulated`, `latency_ms` = 7, veredito com o sufixo, 1 linha no outbox com `simulated` e 1 arquivo em `captures/` |
| `POST /api/live/frame` sem interferência | 150 quadros, todos 200, sufixo em todas as respostas; todos ficaram em `IDLE` (resultado `unknown`, o caminho da mesa vazia), sem nenhuma inspeção e sem nenhum arquivo. Isso não permite conferir o `EMIT` sem interferência |
| `EMIT` com o modelo real (decisão forçada) | Para chegar ao `EMIT`, a inferência real rodou em todos os quadros (`model_info` e `latency_ms` reais), e o tipo e o grau da resposta foram trocados no ensaio. Forma do CA-12, 5 peças, 12 quadros estáveis e 3 de mesa vazia em cada: 1 inspeção por peça, 5 `simulated` na resposta e no outbox, 5 arquivos em `captures/` |
| Página real, Chromium headless, câmera falsa, TLS autoassinado em `127.0.0.1` | Contexto seguro, vídeo aberto, faixa e barra de estabilidade desenhadas (T-01 vem daqui); 1 inspeção `simulated` em 12 s. `LIVE_FPS=5`, inferência de 0,7 s e câmera de 1280×720: no máximo 1 requisição em andamento, 11 quadros em 8 s (os outros descartados), quadros de 640×360 |
| Página em `http://partqc.test` (fora de contexto seguro) | Mostra `O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY).`, não abre a câmera e não envia quadros |
| TLS no servidor real | `https://127.0.0.1` responde, com o certificado validado pelo cliente; HTTP na porta do TLS não é servido; PEM inválido → código 1, sem servir rota e sem o conteúdo no log; chave em `0644` → código 2 citando `EDGE_TLS_KEY`; token fora dos logs |

Limites deste ensaio: mesma máquina, sem Wi-Fi e sem celular. O `mkcert`, a instalação da CA, os navegadores reais e o CA-12 continuam com a dupla (SPEC §3.3).

**Notas sem bug:**

- Sem token e com `Content-Length` acima do limite, a resposta é 413, e não 401, porque o middleware age antes da rota. A `/api/capture` faz o mesmo (SPEC-007 §4.5, passo 1), e o CA-05 testa os casos separados.
- `LIVE_WINDOW=5` sem `LIVE_MIN_AGREE` sai com código 2, porque o padrão 8 passa da janela. Está no §4.6, no `docs/architecture.md` §6.4 e na decisão 8 do dev-report.
- `result.labels_pt.verdict` de um `unknown` com modelo provisório é `desconhecido (modelo provisório)` (decisão 2 do dev-report). O §4.4 pede o sufixo com modelo provisório, e o CA-17 usa um modelo sem ele, então a leitura é coerente.
- Por leitura de código, sem reprodução em navegador: `pagehide` para a câmera, e nada a religa se a página voltar do cache de navegação. Vale conferir no CA-12.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
