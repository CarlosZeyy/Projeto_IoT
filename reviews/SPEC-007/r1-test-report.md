# SPEC-007 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-007](../../docs/specs/SPEC-007-edge-gateway-captura.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `d137e67` (branch `spec/SPEC-007-edge-gateway-captura`) |
| **Veredicto** | **PASS** (CAs automatizáveis); CA-20 e CA-21 são manuais e ficam **pendentes para a dupla** (ver abaixo) |

Os testes foram escritos a partir da SPEC (caixa-preta), antes da leitura da implementação. Arquivo: `edge/tests/acceptance/test_spec_007.py`, com **110 testes** (75 ligados a CAs, 35 exploratórios `test_extra_*`).

## Cobertura dos critérios de aceite

Prefixo dos testes: `edge/tests/acceptance/test_spec_007.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_invalid_configuration_exits_2_naming_the_variable` (porta 70000, `Edge_01`, `"edge-01\n"`, token de 10 caracteres; `uvicorn.run` espião não é chamado) | ✅ |
| CA-02 | `test_ca02_generated_tokens_are_long_urlsafe_and_distinct` (token lido da URL do console, ≥ 43, URL-safe, diferentes, aceito em `/api/status`), `test_ca02_configured_40_char_token_is_the_one_accepted` | ✅ |
| CA-03 | `test_ca03_successful_capture` (14 campos, `source=live`, `device_id`, UUID v4, `inspected_at` UTC igual ao relógio injetado, `approved`, `labels_pt`, `captures/<data>/<id>.jpg`, sink com 1 item igual), `test_ca03_device_id_comes_from_the_configuration` | ✅ |
| CA-04 | `test_ca04_verdicts[nut-poor]`, `test_ca04_verdicts[unknown]` | ✅ |
| CA-05 | `test_ca05_sink_error_is_503_and_nothing_is_kept` | ✅ |
| CA-06 | `test_ca06_missing_or_wrong_token_is_401[missing\|wrong]` (captura e status; token na query não autentica a API) | ✅ |
| CA-07 | `test_ca07_image_one_byte_above_3_mib_is_413`, `test_ca07_request_with_content_length_3670017_is_413` (corpo real de 3 670 017 bytes), `test_ca07_declared_content_length_is_refused_before_reading_the_body` (ASGI cru: 413 com 0 leituras do corpo), `test_ca07_jpeg_padded_to_exactly_3_mib_is_accepted` (200; o arquivo salvo é byte a byte o enviado) | ✅ |
| CA-08 | `test_ca08_invalid_images_are_415[...]` (texto `foto.jpg`, GIF, JPEG truncado, PNG 100×1001, 65 marcadores de scan, JPEG 2001×2000) | ✅ |
| CA-09 | `test_ca09_invalid_fields_are_422[...]` (`"lote 1"`, `"../x"`, `"L-001\n"`, 41 caracteres, `mode=foo`, sem `image`, sem `lot_id`, sem `mode`) | ✅ |
| CA-10 | `test_ca10_no_model_is_503` | ✅ |
| CA-11 | `test_ca11_inference_error_is_500_without_side_effects` | ✅ |
| CA-12 | `test_ca12_client_filename_is_ignored[../../evil.jpg, ..\..\evil.jpg, /etc/evil.jpg]` | ✅ |
| CA-13 | `test_ca13_console_from_loopback` (`httpx.ASGITransport(client=("127.0.0.1", 50000))`, socket simulado; `<svg`, URL `http://192.168.0.42:8000/capture?t=<token>`, modelo, `pending`=12, 10 linhas da mais recente para a mais antiga, `refresh` 5 s) | ✅ |
| CA-14 | `test_ca14_console_refuses_remote_or_proxied[lan-client, x-forwarded-for, cf-connecting-ip, forwarded]` | ✅ |
| CA-15 | `test_ca15_capture_page` (input file/`accept`/`capture`, campo de lote, coleta desabilitada, `capture.js` ≤ 200 linhas, nenhum `http(s)://` nos arquivos da página, 401 com o texto PT-BR para `t` errado e ausente) | ✅ |
| CA-16 | `test_ca16_status` | ✅ |
| CA-17 | `test_ca17_captures_are_never_served_and_payload_is_the_contract` (404 em `/captures/...`, `/data/captures/...` e variantes de travessia via `/static`), `test_ca17_no_http_client_import_outside_the_publisher` (AST), `test_ca17_static_checker_detects_violations` (o verificador não é tautológico) | ✅ |
| CA-18 | `test_ca18_udp_probe_address_comes_first`, `test_ca18_fallback_filters_loopback_and_link_local`, `test_ca18_no_candidate_falls_back_to_loopback_with_console_warning` | ✅ |
| CA-19 | `test_ca19_logs_never_contain_the_token_or_the_device_key` (`main()` → espião do `uvicorn.run` que sobe o app com `TestClient` e faz sucesso, 401, 415, `/capture?t=` e status; registros do logger `httpx` do cliente filtrados, como orienta o dev-report), `test_ca19_real_server_output_has_no_secrets` (servidor real em subprocesso, uvicorn em loopback; toda a saída do processo é lida) | ✅ |
| CA-20 | manual: **pendente para a dupla** (roteiro revisado abaixo) | ⏳ |
| CA-21 | manual: **pendente para a dupla** (roteiro revisado abaixo) | ⏳ |
| CA-22 | `test_ca22_busy_slots_answer_503` | ✅ |
| CA-23 | `test_ca23_waiting_requests_get_a_slot`, `test_ca23_slot_is_released_after_an_inference_error`, `test_ca23_invalid_limiter_arguments[slots-0, wait-0, slots-negative, wait-negative]` | ✅ |
| CA-24 | `test_ca24_cli_refuses_the_truncated_images_flag`, `test_ca24_cli_starts_with_the_flag_off` (também confere `proxy_headers=False`, host e porta), `test_ca24_lifespan_refuses_the_truncated_images_flag` (nenhum `BackgroundService` inicia com a flag ligada; com ela desligada, `start`/`stop`) | ✅ |
| CA-25 | `test_ca25_no_production_code_assigns_the_flag` (`git ls-files *.py` sem componente `tests`, AST), `test_ca25_checker_detects_violations` | ✅ |
| CA-26 | `test_ca26_constants`, `test_ca26_pixel_limit_is_checked_before_decoding` (espião em `ImageFile.ImageFile.load` com 0 chamadas no 2001×2000; os dois aceitos por `load_image`), `test_ca26_route_accepts_2000x2000_and_refuses_2001x2000` | ✅ |
| CA-27 | `test_ca27_unreadable_inputs_raise_invalid_image[text, empty, gif]`, `test_ca27_load_image_rules_still_apply`, `test_ca27_flag_is_checked_before_the_probe` | ✅ |

Estabilidade: os testes com threads e tempo (CA-19, CA-22, CA-23 e `test_extra_422_does_not_wait_for_a_busy_slot`) rodaram 15 vezes seguidas, 15/15 verdes.

## Suíte completa

```text
# sem banco (TEST_DATABASE_URL ausente)
uv run pytest -q                      → 1237 passed, 291 skipped, 1 warning in 98.57s

# com banco (TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test)
uv run pytest -q                      → 1528 passed, 1 warning in 160.92s
                                        (1418 do dev-report + 110 deste arquivo)

# só a borda, com cobertura (edge/tests, autor + aceite)
252 passed; cobertura de qc_edge: 98% (app 99%, cli 100%, config 98%, inference 100%,
limits 100%, middleware 94%, netinfo 100%, security 100%, sink 100%)

uv run ruff check .                   → All checks passed!
uv run ruff format --check .          → 95 files already formatted
```

O único aviso é o `StarletteDeprecationWarning` do `TestClient`, que já existia.

## Bugs encontrados

Nenhum bug contra os critérios de aceite.

## Observações (não bloqueiam; para o reviewer e o security-devops)

| ID | Severidade | Assunto | Detalhe |
|---|---|---|---|
| O-01 | informativa (security) | Custo medido da inundação de segmentos dentro dos limites da rota | JPEG 64×48 com 786 262 segmentos APP1 vazios (3 145 725 bytes, aceito pela rota): `load_capture_image` levou **4,05 s** neste notebook (4 núcleos, Pillow 12.3.0), **~1,96 s na sondagem e ~2,0 s no `load_image`**, com pico de RSS de ~130 MB no processo. A §4.6 estima ~0,7 s por leitura (~1,4 s por slot); o valor medido aqui é cerca de 3× maior. Nenhum CA cobre esse número, e a §4.6 deixa a medição para o security-devops. A consequência aceita na §4.6 continua igual: quem tem o token ocupa os 2 slots e as requisições legítimas recebem 503 `server busy`. O tempo por ocupação é que fica maior. Script em memória, fora do repositório. |
| O-02 | baixa (UX) | IPs de bridges do Docker no console | Neste notebook, `detect_lan_ips()` devolve `192.168.1.116` (Wi-Fi, primeiro e usado no QR) e mais cinco IPs `172.17–22.0.1` das bridges do Docker, mostrados como "outros IPs". O QR está certo e a SPEC não pede filtragem; é só ruído para o operador. |
| O-03 | informativa | Corpo grande sem token | Um `Content-Length` acima de 3,5 MiB recebe 413 do middleware antes da checagem do token (sem token: 3,7 MB → 413; 3,3 MB → 401). Isso segue a §4.5 ("um middleware também rejeita ... antes de ler o corpo"), e em nenhum caso o inferenciador é chamado. |
| O-04 | informativa | Corpo do 415 | O `detail` do 415 traz o motivo do `InvalidImageError` (ex.: `invalid image: cannot read image header: UnidentifiedImageError`, ou as dimensões no caso do limite de pixels). Não há stack trace nem dado do cliente além das dimensões. |

## Testes exploratórios (além dos critérios)

Automatizados (`test_extra_*`, todos verdes):

- **Flag ligada depois da subida** → 500 `{"detail": ...}` sem stack trace e sem o nome da flag no corpo; stub com 0 chamadas, nada salvo (§4.5, passo 3).
- **Formatos aceitos:** PNG RGBA, PNG cinza, JPEG CMYK, JPEG cinza, PNG 100×1000 (10:1 exato) e JPEG progressivo → 200, todos salvos como JPEG. PNG salvo é reencodado em JPEG com o mesmo tamanho (§4.5, passo 6).
- **Bomba de descompressão PNG** (20 000×20 000, poucos KB) → 415 em < 2 s, stub com 0 chamadas. PNG 2001×2000 → 415.
- **`lot_id`:** 40 caracteres e `a_B-9` → 200; vazio, `lóte`, `\r` final, espaço antes/depois, NUL, `/` e `%2e%2e` → 422, sem ecoar o valor.
- **`mode=collect`** → 501, nada salvo.
- **Token:** espaço antes/depois, sufixo, prefixo e `Bearer <token>` → 401; header de 20 000 caracteres e token com byte não ASCII → 401 (nunca 500); `?t=` com 5 000 caracteres não ASCII → 401.
- **Corpo chunked** acima do limite (sem `Content-Length`) → 413, nada salvo. Dois arquivos `image` → 400 (`Too many files`), stub com 0 chamadas.
- **Limitador:** um 422 não espera slot quando o único slot está ocupado (< 2 s). `decode_wait_s=NaN` → `ValueError`.
- **Relógio com fuso −03:00** → `inspected_at` normalizado para UTC e diretório do dia pela data UTC.
- **Console:** `?ip=` só aceita IPs detectados (`8.8.8.8`, `<script>` e um nome de host são ignorados e nada é refletido); `::1` → 200.
- **R-02:** durante uma captura e um status, nenhuma chamada a `socket.connect` ou `socket.create_connection`; a resposta não contém os bytes da foto.
- **CLI:** sem `--stub-model` o app sobe sem modelo (503 `model not loaded`); com `--stub-model`, `model_version=stub-v0`. Configuração inválida também sai com 2 citando a variável para `EDGE_HOST=localhost`, `999.1.1.1`, `EDGE_PORT=0`, `abc`, `DEVICE_ID` de 2 e 33 caracteres e token de 31 (o valor do token não aparece na mensagem). Os limites aceitos: token de 32, `DEVICE_ID` de 32, porta 65535, `EDGE_HOST=::`.
- `EDGE_DATA_DIR` é criado; `InMemorySink` é idempotente por `inspection_id` e `connectivity="disabled"`; `StubInferencer()` tem `ModelInfo("stub-v0", "0"*64)` e conta chamadas.

Manuais (scripts no scratchpad, fora do repositório):

- **Simulação da rede (parte possível do CA-20 sem celular):** `qc-edge --stub-model` real com `EDGE_HOST=0.0.0.0`, acessado pelo IP da LAN do notebook (`192.168.1.116`). Nenhum firewall ativo nesta máquina (`systemctl is-active ufw firewalld nftables` → 3× `inactive`).
  - Console por `127.0.0.1` → 200, QR com `http://192.168.1.116:<porta>/capture?t=...`.
  - Console pelo IP da LAN → **403**, sem o token no corpo; console por loopback com `X-Forwarded-For` → 403.
  - `/capture?t=<token>` pelo IP da LAN → 200; sem token → 401.
  - `POST /api/capture` pelo IP da LAN com JPEG 1280×960 → 200 (parafuso/bom/aprovada) em 84 ms.
  - Socket cru com `Content-Length: 3670017` e **nenhum byte de corpo** → `413` em 1 ms (o servidor não espera o corpo).
  - `/api/status` pelo IP da LAN → 200, `pending=1`, `connectivity=disabled`.
  - Saída completa do processo (uvicorn + `qc_edge`): sem o token, sem o `DEVICE_API_KEY`, e o log por requisição registra `GET /capture 200` sem a query.
- **`.env.example` copiado como `.env`** (CA-20, passo 1) carrega sem erro com `uv run --env-file`: o `EDGE_SESSION_TOKEN=` vazio vale como não definido.

## CA-20 e CA-21 (manuais): pendentes para a dupla

Revisei o roteiro de `edge/README.md` ("Teste manual com os celulares", "Firewall no Arch" e "Plano B"). Ele é executável e completo frente ao texto dos CAs:

- CA-20, passos 1–6 da SPEC → README CA-20, passos 1–8. Ele cobre liberar a porta, subir com `--stub-model`, ler o QR em cada celular, registrar câmera traseira direta ou via seletor, 10 fotos com o "Total" abaixo de 3000 ms, 10 linhas no console e o maior arquivo por celular (`find ... -newer <marca>`, comparado com 3 145 728).
- CA-21 → README CA-21 + Plano B, com `nmcli --ask dev wifi connect <SSID>`, recarga do console (5 s), QR novo e 3 fotos por celular.
- Firewall: ufw, firewalld (com `--zone` e `--permanent`) e nftables (`add` vs `insert`, remoção por `handle`), cada um com o "como desfazer", como pede a §7.

Sugestões (opcionais, não bloqueiam):
1. Acrescentar uma linha de diagnóstico para "o celular não abre a página": isolamento de clientes do roteador (citado em `architecture.md` §8) → usar o hotspot.
2. Lembrar que, no hotspot, o celular A acessa o notebook pela própria rede que ele hospeda (funciona, mas confunde quem faz o teste pela primeira vez).

**O que a dupla deve registrar neste relatório (ou numa rodada seguinte), por celular:** modelo do aparelho, navegador e versão, se a câmera traseira abriu direto ou via seletor, o maior "Total" (ms) nas 10 fotos (CA-20) e nas 3 fotos (CA-21), as 10 linhas no console, o tamanho do maior arquivo em `EDGE_DATA_DIR/captures/` (< 3 145 728 bytes) e qualquer erro exibido.

| Item | Celular A (Android, Chrome) | Celular B (navegador padrão) |
|---|---|---|
| CA-20: câmera traseira (direta / seletor) | _a preencher_ | _a preencher_ |
| CA-20: maior "Total" (ms), 10 fotos | _a preencher_ | _a preencher_ |
| CA-20: 10 linhas no console | _a preencher_ | _a preencher_ |
| CA-20: maior arquivo (bytes) | _a preencher_ | _a preencher_ |
| CA-21: 3 fotos pelo hotspot, maior "Total" (ms) | _a preencher_ | _a preencher_ |

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Nenhum token, chave ou credencial fictícia como literal em URL, conninfo ou header: tokens e chaves são gerados em tempo de execução (`secrets`).
- [x] Nenhum teste roda a suíte em subprocesso. O único subprocesso (CA-19) sobe o servidor `qc-edge`.
- [x] Imagens geradas em memória; nenhum binário no Git.
