# SPEC-007 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-007](../../docs/specs/SPEC-007-edge-gateway-captura.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-007-edge-gateway-captura` |
| Commits | `537a3ca` (feat(edge): settings, interfaces, limites), `57b8c23` (feat(edge): app, console, página e CLI), `1d80c1f` (test(edge): testes do autor), `6a6b101` (docs(edge): README, `.env.example`), `9f344f1` (fix(edge): o aviso de argumentos desconhecidos não registra valores), mais o commit deste relatório |

## Resumo

- Base do `qc-edge`: `EdgeSettings` (`config.py`), interfaces `Inferencer`/`InspectionSink`/`BackgroundService` com `StubInferencer` e `InMemorySink` (`inference.py`, `sink.py`), `load_capture_image` com os limites próprios da rota (`limits.py`), `detect_lan_ips` (`netinfo.py`) e o token de sessão (`security.py`).
- `create_app` (`app.py`) com as rotas do §4.4:
  - `POST /api/capture` (modo `inspect`), na ordem 401 → 413 → 422 → 503 `server busy` → 415 → 503 `model not loaded`;
  - limitador de decodificações (`BoundedSemaphore`), foto salva só no disco local e `sink.put` antes da resposta;
  - `GET /api/status`, o console só para loopback com o QR em SVG, e a página `/capture` com `capture.js` (172 linhas, sem recurso externo).
- Middlewares ASGI (`middleware.py`): 413 por `Content-Length` (e por contagem em corpo chunked), 500 genérico sem stack trace e uma linha de log por requisição, **sem a query string**.
- CLI `qc-edge` (`cli.py`, console script): sai com código 2 em configuração inválida, com o nome da variável, e com código 1 se `LOAD_TRUNCATED_IMAGES` estiver ligada. Roda o `uvicorn` com `proxy_headers=False` e `access_log=False`.
- `edge/README.md` traz: como rodar, variáveis, rotas e limites, firewall no Arch (ufw, firewalld, nftables, com como desfazer), plano B (hotspot, `nmcli`), plano C e o roteiro dos CA-20/CA-21.
- Dependência nova do `qc-edge`: `pydantic-settings>=2`, que já estava no `uv.lock` pelo `qc-api` (2.15.0, MIT). Nenhum pacote novo foi resolvido. `qrcode` já era dependência declarada.

## Rastreabilidade (critério de aceite → implementação)

Abreviações dos testes do autor (todos em `edge/tests/`): `cfg/` = `test_config.py`, `sec/` = `test_security.py`, `net/` = `test_netinfo.py`, `inf/` = `test_inference_sink.py`, `lim/` = `test_limits.py`, `cap/` = `test_capture_route.py`, `lmt/` = `test_limiter.py`, `pg/` = `test_pages.py`, `cli/` = `test_lifespan_cli.py`, `st/` = `test_static_rules.py`. Os arquivos de produção estão em `edge/src/qc_edge/`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `config.py` (`EdgeSettings`, `pattern=DEVICE_ID_PATTERN`), `cli.py` (`main`, saída 2 com `NOME: motivo`) | `cfg/::test_invalid_values_name_the_variable`; `cli/::test_invalid_configuration_exits_2_naming_the_variable` (porta 70000, `Edge_01`, `"edge-01\n"`, token de 10 caracteres) |
| CA-02 | `security.py` (`resolve_session_token`, `token_matches`), `app.py` (`app.state.session_token`) | `sec/::test_generated_tokens_are_long_urlsafe_and_distinct`, `::test_configured_token_is_used`; `pg/::test_configured_token_is_the_one_accepted` |
| CA-03 | `app.py` (`read_capture_form`, `inspect`, `_CaptureStore.save`) | `cap/::test_success` |
| CA-04 | `app.py` (`_verdict`, só com `is_defective`) | `cap/::test_verdicts` |
| CA-05 | `app.py` (`SinkError` → 503, `_CaptureStore.remove`) | `cap/::test_sink_error_is_503_and_the_photo_is_removed` |
| CA-06 | `app.py` (`require_header_token`, antes de ler o corpo) | `cap/::test_invalid_token_is_401`, `::test_token_is_checked_before_size_and_fields`; `pg/::test_status` |
| CA-07 | `limits.py` (constantes), `app.py` (`read_capture_form`: 413 do campo), `middleware.py` (`BodySizeLimitMiddleware`) | `cap/::test_image_above_the_limit_is_413`, `::test_image_exactly_at_the_limit_is_accepted`, `::test_declared_content_length_above_the_limit_is_413`, `::test_chunked_body_above_the_limit_is_413` |
| CA-08 | `limits.py` (`load_capture_image`), `app.py` (415) | `cap/::test_invalid_images_are_415` (texto, GIF, truncado, PNG 100×1001, 65 marcadores de scan, 2001×2000) |
| CA-09 | `app.py` (`re.fullmatch(LOT_ID_PATTERN, ...)`, `CaptureMode(mode)`) | `cap/::test_invalid_fields_are_422`, `::test_missing_image_is_422`, `::test_image_sent_as_text_field_is_422`, `::test_lot_id_of_40_chars_is_accepted` |
| CA-10 | `app.py` (`inferencer is None` → 503) | `cap/::test_no_model_is_503_after_image_validation` |
| CA-11 | `app.py` (`InferenceError` → 500) | `cap/::test_inference_error_is_500_without_side_effects` |
| CA-12 | `app.py` (`_CaptureStore`: nome sempre `<inspection_id>.jpg`) | `cap/::test_client_filename_is_ignored` |
| CA-13 | `app.py` (`console`, `deque(maxlen=10)`), `templates/console.html` | `pg/::test_console_from_loopback` |
| CA-14 | `app.py` (`_is_local_console_request`) | `pg/::test_console_refuses_non_local_or_proxied` (inclui `Forwarded`), `::test_console_accepts_ipv6_loopback` |
| CA-15 | `templates/capture.html`, `static/capture.js`, `static/capture.css`, `app.py` (`capture_page_route`) | `pg/::test_capture_page`, `::test_page_files_are_self_contained` |
| CA-16 | `app.py` (`api_status`) | `pg/::test_status`, `::test_status_without_model_and_with_last_success` |
| CA-17 | `app.py` (só `/static` é montado; `InspectionCreate` do contrato), nenhum import de cliente HTTP | `pg/::test_captures_are_never_served`; `cap/::test_success` (chaves = 14 campos); `st/::test_no_http_client_outside_the_publisher` |
| CA-18 | `netinfo.py` (`detect_lan_ips`, `is_fallback`), `app.py` (aviso `no-lan-warning` no console) | `net/::*`; `pg/::test_console_without_model_and_without_lan` |
| CA-19 | `middleware.py` (`RequestLogMiddleware` sem query), `cli.py` (`access_log=False`), `config.py` (`SecretStr`, `hide_input_in_errors`) | `cli/::test_logs_never_contain_the_token_or_the_device_key` |
| CA-20 | manual: roteiro em `edge/README.md` ("Teste manual com os celulares") | — |
| CA-21 | manual: roteiro em `edge/README.md` (Plano B + CA-21) | — |
| CA-22 | `app.py` (`BoundedSemaphore`, `acquire(timeout=decode_wait_s)`) | `lmt/::test_busy_slots_answer_503_and_do_nothing` |
| CA-23 | `app.py` (`finally: release()`, `_validate_limiter`) | `lmt/::test_waiting_requests_get_a_slot`, `::test_slot_is_released_after_errors`, `::test_invalid_limiter_arguments` |
| CA-24 | `app.py` (`lifespan`, checagem antes dos serviços), `cli.py` (checagem antes do `uvicorn.run`, saída 1) | `cli/::test_flag_exits_1_without_starting_the_server`, `::test_startup_refuses_the_truncated_images_flag`, `::test_main_runs_uvicorn_without_proxy_headers` |
| CA-25 | nenhum código atribui a flag (só leitura em `limits.py`, `app.py`, `cli.py`) | `st/::test_truncated_images_flag_is_never_assigned` (só `edge/src`; o CA cobre o repositório e é do tester) |
| CA-26 | `limits.py` (`_probe_size`, `CAPTURE_MAX_PIXELS`) | `lim/::test_constants`, `::test_up_to_the_pixel_limit_is_decoded`, `::test_above_the_pixel_limit_is_refused_before_decoding` (espião em `ImageFile.ImageFile.load`); `cap/::test_2000x2000_is_accepted`, `::test_invalid_images_are_415[2001x2000]` |
| CA-27 | `limits.py` (flag → sondagem → `load_image`; único `except Exception` em volta do `Image.open`) | `lim/::test_unreadable_header_is_invalid_image`, `::test_gif_is_invalid_image`, `::test_probe_exceptions_become_invalid_image`, `::test_load_image_rules_still_apply`, `::test_flag_is_checked_before_the_probe` |

Requisitos sem CA próprio, também cobertos:

- §4.1: padrões, `.env` vazio e diretório criado (`cfg/::test_defaults`, `::test_empty_variables_count_as_unset`, `::test_data_dir_*`, `::test_error_never_shows_the_value`).
- §4.2: lifespan com `start()` em ordem e `stop()` em ordem inversa (`cli/::test_background_services_start_in_order_and_stop_in_reverse`).
- §4.3: `--stub-model` (`cli/::test_stub_model_flag`, `::test_stub_inferencer_is_never_the_default`).
- §4.5, passo 3: flag ligada depois da subida → 500, e não 415 (`cap/::test_flag_enabled_after_startup_is_500_not_415`).
- §4.5, passos 6 e 7: PNG reencodado em JPEG (`cap/::test_png_is_saved_as_jpeg`); data do diretório em UTC (`cap/::test_day_directory_uses_the_utc_date`); foto gravada antes do `sink.put` (`cap/::test_sink_put_happens_before_the_response`).
- §4.5, modo `collect` → 501 (`cap/::test_collect_mode_is_501`).
- §4.6: a decodificação acontece dentro do slot, e o 422 não espera slot (`lmt/::test_decode_happens_inside_the_slot`, `::test_422_does_not_wait_for_a_slot`).

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages --frozen
uv run pytest -q edge/tests                      # 142 testes do autor, sem banco, ~4 s
export TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test
uv run pytest -q                                 # suíte inteira
uv run --package qc-edge qc-edge --stub-model    # console em http://127.0.0.1:8000/
```

Também subi o `qc-edge --stub-model` de verdade (uvicorn em `127.0.0.1:18765`, `EDGE_DATA_DIR` temporário). O console respondeu 200, o console com `X-Forwarded-For` respondeu 403, o log mostrou a URL do console sem o token e o desligamento parou o app limpo.

## Decisões tomadas dentro do escopo da SPEC

1. **Leitura do formulário numa dependência assíncrona (`read_capture_form`), com o handler `capture` síncrono (`def`).**
   - A rota não declara campos `Form`/`File`. Assim o FastAPI não lê o corpo antes da autenticação: o token é conferido antes do parse do multipart. Depois vêm o 413 do campo `image` (lido até `CAPTURE_MAX_BYTES + 1` bytes) e o 422 dos campos, na ordem do §4.5.
   - O formulário (e o arquivo temporário do Starlette) é fechado na própria dependência.
   - A decodificação, a inferência, a gravação e o `sink.put` rodam no handler síncrono, no threadpool.
   - `request.form(max_files=1, max_fields=16)`: os 16 campos deixam folga para os campos do modo coleta (SPEC-010).
2. **Corpo dos erros próprios.** Todos os erros seguem `{"detail": "<texto>"}`:
   - 401 `invalid session token`;
   - 413 `image too large` (campo) ou `request body too large` (middleware);
   - 422 `missing or invalid <campo>`. É uma string, e não a lista padrão do FastAPI, porque a validação é manual (item 1). O valor enviado não é ecoado;
   - 415 `invalid image: <motivo do InvalidImageError>`;
   - 501 `collect mode is not available yet`;
   - 500 genérico `internal server error`.
3. **O `InspectionCreate` é montado (e validado pelo contrato) antes de gravar a foto.** O resultado observável dos passos 6 e 7 é o mesmo. A diferença é que um resultado inválido do inferenciador (ex.: grau com `unknown`) vira 500 genérico sem deixar foto órfã (`cap/::test_invalid_inference_result_leaves_no_file`).
4. **Remoção da foto.** Depois de um `SinkError`, ou de qualquer outra exceção no `put`, a foto é apagada e o diretório do dia também, se ficou vazio. Um lock cobre "criar o diretório e o arquivo" e "apagar o arquivo e o diretório", então uma limpeza nunca remove o diretório em que outra requisição está gravando.
5. **`detect_lan_ips` combina as duas fontes.** O IP da sondagem UDP vem primeiro, e os IPv4 de `getaddrinfo(gethostname())` vêm depois. Quando a sondagem falha, eles são a única fonte, o que é o fallback do §4.3. Isso alimenta os "outros IPs como links" do console (ex.: Wi-Fi e ancoragem USB ao mesmo tempo). Além dos filtros pedidos (duplicados, `127.0.0.0/8`, `169.254.0.0/16`), descarta `0.0.0.0` e o que não for IPv4. O CA-18 vale nos três casos. O aviso de "nenhum IP" sai no log **e** no console (`id="no-lan-warning"`).
6. **`main(argv=None)` usa `parse_known_args`.** Argumentos desconhecidos são ignorados, com um aviso no log que lista só os nomes das opções (`-x`, `--opt`), nunca valores (nem posicionais nem `--opt=valor`). Assim `main()` funciona quando chamado de dentro do pytest (cujo `sys.argv` tem as opções do pytest), como pedem os CA-01 e CA-24. Para não aceitar abreviações, `allow_abbrev=False`.
7. **Access log do uvicorn desligado (`access_log=False`).** Ele imprimiria `GET /capture?t=<token>`, violando o §4.3 ("o token nunca aparece em log"). No lugar dele, o `RequestLogMiddleware` registra método, rota (o template, ou o caminho com `repr`, truncado), status e duração, sem a query.
8. **`app.state.session_token`** guarda o token em memória, para o console e para os testes (CA-02). Não é exposto por nenhuma rota além do console (loopback).
9. **Atributos de teste:** `StubInferencer.calls` (contagem de chamadas, thread-safe) e `InMemorySink.items` (cópia da lista, em ordem de chegada). O `InMemorySink.put` ignora um `inspection_id` repetido (idempotente, §4.2).
10. **`EdgeSettings`:**
    - lê só do ambiente, sem `.env`, como a API; o README e o `.env.example` orientam `uv run --env-file .env ...`;
    - `env_ignore_empty=True`, para as linhas vazias do `.env.example` valerem como não definidas;
    - `hide_input_in_errors=True` e `SecretStr` para o token e o `DEVICE_API_KEY`;
    - os limiares são tipados como `float | None`, e as faixas ficam para a SPEC-008;
    - um `EDGE_DATA_DIR` que não pode ser criado, ou que é um arquivo, é erro da variável (saída 2).
11. **Templates com `string.Template` + `html.escape`**, sem acrescentar Jinja2. O `capture.html` é estático: o token é lido de `?t=` pelo JS.
12. **Cabeçalhos das páginas** do console, de `/capture` e dos 401/403 HTML: `Cache-Control: no-store`, `Referrer-Policy: no-referrer` (o token está na URL) e `X-Content-Type-Options: nosniff`. O app não publica `/docs`, `/redoc` nem `/openapi.json`.
13. **O token vai na URL do QR com `urllib.parse.quote`.** Para o token gerado (URL-safe), não muda nada. Só importa se alguém definir um `EDGE_SESSION_TOKEN` com caracteres especiais. O import é `urllib.parse`, e não `urllib.request` (CA-17).
14. **Hora no console:** horário local do notebook, só na interface. O transporte e o nome do diretório usam UTC.
15. **`capture.js` aceita só a imagem reencodada.** Se o `toBlob` devolver `null`, a página mostra "Não foi possível preparar a foto. Tente de novo." e não envia nada. Se o `createImageBitmap` com `imageOrientation` falhar, usa o fallback com `<img>`. O `localStorage` é envolvido em `try` (modo privado). O botão fica desabilitado durante o envio e volta mesmo em erro inesperado.
16. **Módulo extra `middleware.py`**, além dos listados no §3.1. Segue o padrão do `qc_api.middleware` (sem importar do `qc-api`, que não é dependência da borda).
17. **`qc_edge.__version__` continua `0.0.0`**: a SPEC não pede aumento.

### Observações para o tester

- **CA-19:** o `TestClient` usa o `httpx`, cujo logger (`httpx`, nível INFO) registra a URL completa da requisição, **inclusive `?t=<token>`**. Esse log é do cliente de teste, e não do servidor. Ao capturar logs com `caplog`, filtre os registros do logger `httpx` (veja `cli/::test_logs_never_contain_the_token_or_the_device_key`).
- **CA-03:** um relógio fixo injetado não pode estar mais de 5 min no futuro, porque o `InspectionCreate` rejeita (o handler devolveria 500).
- **CA-13/14:** o `TestClient(app, client=("127.0.0.1", 50000))` do Starlette também simula a origem, além do `httpx.ASGITransport(client=...)`.
- **CA-18:** o console chama `qc_edge.netinfo.detect_lan_ips()` pelo módulo, então dá para fazer `monkeypatch` tanto em `netinfo.socket` quanto em `netinfo.detect_lan_ips`.
- `libjpeg_turbo` do Pillow no `uv.lock`: 3.1.4.1 (Pillow 12.3.0, sem mudança nesta SPEC).

## SPEC_ISSUE (se houver)

Nenhum. Uma observação, sem bloqueio: o ADR-003 diz que a borda "aceita no máximo 10 MB", e o §4.7 desta SPEC fixa 3 MiB na rota. Como o ADR fala em teto, o limite menor não o contradiz. Se a dupla quiser, o texto do ADR pode citar o §4.7 numa revisão futura.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (94 arquivos)
- [x] Testes unitários do autor passando: 142 em `edge/tests`. Suíte inteira **com** `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`: **1418 passed** (2 min 33 s), 1 aviso já existente (`StarletteDeprecationWarning` do `TestClient`)
- [x] `.env.example`: nenhuma variável nova (todas as do §6.4 já estavam lá). Os comentários do bloco `qc-edge` agora trazem as regras (IP literal, porta, token com no mínimo 32 caracteres, `DEVICE_ID`, `EDGE_DATA_DIR`) e o `--env-file`, sem valores secretos. O `.gitignore` já cobria `edge/data/`
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma credencial literal em URL, conninfo ou header nos testes (os tokens de teste são montados em tempo de execução, ex.: `"T0k" + "e" * 37`); nenhum teste roda a suíte em subprocesso; as imagens dos testes são geradas em memória (Pillow), sem binários no Git
- [x] R-02: nenhum módulo de `qc_edge` importa `httpx`, `requests` ou `urllib.request`; as fotos só são gravadas em `EDGE_DATA_DIR/captures/` e nenhuma rota serve essa pasta
- [x] R-12: nada de torch; dependência nova só no `qc-edge` (`pydantic-settings`, já no lock)
