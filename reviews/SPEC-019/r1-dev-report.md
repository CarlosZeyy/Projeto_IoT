# SPEC-019 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-019-modo-ao-vivo` |
| Commits | `dad275d`, `387cae4`, `1003693`, `92e515c`, além do commit deste relatório |

## Resumo

Implementação completa da SPEC, depois de os SPEC_ISSUE-01 a 12 serem corrigidos e reaprovados (Histórico da SPEC, e a seção "SPEC_ISSUE" abaixo). O modo vídeo ao vivo tem HTTPS opcional (`EDGE_TLS_CERT`/`EDGE_TLS_KEY`), a máquina de estados e as sessões em `qc_edge/live.py`, a rota `POST /api/live/frame`, a página `GET /live` e o console com o segundo QR (só com TLS) e a latência por quadro. A inspeção emitida passa pelo mesmo caminho da captura (`record_inspection`, extraída do modo `inspect`), com o `source` da SPEC-041. Sem mudança de contrato e sem dependência nova. Nada de `tests/acceptance/`, de `docs/architecture.md` nem de `docs/specs/` foi alterado.

## Rastreabilidade (critério de aceite → implementação)

Os testes ficam em `edge/tests/`. Abreviações: `test_live.py` (máquina, sessões, latência, imagem), `test_live_route.py` (rota, página, console) e `test_live_config.py` (HTTPS, argumentos do uvicorn, variáveis).

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `qc_edge/live.py` | `test_live.py::test_emits_the_most_recent_frame_of_the_stable_pair` |
| CA-02 | `qc_edge/live.py` | `test_live.py::test_no_emission_below_agreement_or_confidence` |
| CA-03 | `qc_edge/live.py` | `test_live.py::test_removal_needs_consecutive_unknowns_then_a_new_part_emits`, `test_wait_removal_never_emits_and_keeps_rolling_for_stability` |
| CA-04 | `qc_edge/live.py` (`LiveSessions.feed`), `qc_edge/app.py` | `test_live_route.py::test_new_lot_starts_the_window_over`, `test_live.py::test_changing_the_lot_resets_the_machine` |
| CA-05 | `qc_edge/app.py` (`read_live_form`), `qc_edge/limits.py` (`load_live_image`), `qc_edge/middleware.py` (`path_limits`) | `test_live_route.py::test_refusals_do_not_reach_the_model_nor_a_session`, `test_content_length_limit_of_the_route_only`, `test_middleware_counts_a_chunked_body_with_the_limit_of_the_path` |
| CA-06 | `qc_edge/app.py` (`live_frame_step`, `record_inspection`) | `test_live_route.py::test_one_inspection_per_part` |
| CA-07 | `qc_edge/app.py` | `test_live_route.py::test_outbox_payload_has_the_contract_and_no_image` |
| CA-08 | `qc_edge/live.py` (`LiveSessions`) | `test_live_route.py::test_session_limit_and_expiry`, `test_live.py::test_new_session_over_the_maximum_is_refused_until_one_expires` |
| CA-09 | `qc_edge/config.py`, `qc_edge/cli.py` (`uvicorn_kwargs`), `qc_edge/app.py` | `test_live_config.py::test_tls_only_certificate_exits_2`, `test_tls_key_with_group_or_other_permission_exits_2`, `test_tls_path_that_is_not_a_readable_file_exits_2`, `test_uvicorn_arguments_with_tls`; `test_live_route.py::test_console_with_tls_has_two_https_qr_codes` |
| CA-10 | `qc_edge/app.py` (`live_page_route`), `templates/live.html`, `static/live.js` | `test_live_route.py::test_page_requires_the_token_and_has_the_headers`, `test_page_has_the_lot_the_script_and_the_fps`, `test_html_is_not_served_as_a_static_file`, `test_page_files_are_self_contained_and_follow_the_section` |
| CA-11 | `qc_edge/config.py` | `test_live_config.py::test_invalid_live_values_exit_2_naming_the_variable` |
| CA-12 | manual, depois do merge; passo a passo em `edge/README.md`, seção "Vídeo ao vivo (HTTPS)" | não automatizado (ver "Como rodar e verificar": ensaio com câmera falsa) |
| CA-13 | `qc_edge/app.py` | `test_live_route.py::test_provisional_model_is_simulated_with_the_suffix`, `test_official_model_is_live_without_suffix` |
| CA-14 | `qc_edge/cli.py`, `qc_edge/app.py` | `test_live_config.py::test_uvicorn_arguments_without_tls`; `test_live_route.py::test_console_without_tls_is_as_before`, `test_capture_route_is_unchanged_without_tls` |
| CA-15 | `qc_edge/live.py` | `test_live.py::test_empty_table_never_emits_but_counts_for_stability`, `test_known_type_without_grade_emits` |
| CA-16 | `qc_edge/live.py` | `test_live.py::test_tie_at_the_top_does_not_emit_and_the_window_rolls` |
| CA-17 | `qc_edge/app.py` (`_labels_pt`) | `test_live_route.py::test_unknown_result_has_null_grade_and_desconhecido` |
| CA-18 | `qc_edge/app.py` (`live_frame_step`) | `test_live_route.py::test_sink_error_answers_503_removes_the_photo_and_emits_again`, `test_other_recording_failure_answers_500_and_resets`, `test_full_disk_answers_500_and_resets` |
| CA-19 | `qc_edge/app.py` (`live_frame_step`) | `test_live_route.py::test_inference_error_does_not_enter_the_window` |
| CA-20 | `qc_edge/live.py` (`FrameLatency`, `p95_nearest_rank`), `templates/console.html` | `test_live_route.py::test_console_latency`, `test_live.py::test_p95_rank_matches_the_exact_formula_for_every_size` |

## Nomes que a SPEC deixa a cargo da implementação (para o tester)

- **Argumentos do uvicorn (CA-09 e CA-14):** `qc_edge.cli.uvicorn_kwargs(settings) -> dict`, função pura, sem o `app`. `ssl_certfile` e `ssl_keyfile` são `str`. O `cli.main` só faz `uvicorn.run(app, **uvicorn_kwargs(settings))`, então o espião em `cli.uvicorn.run` também vê os valores.
- **Máquina (CA-01 a 03, 15 e 16):** `qc_edge.live.LiveStateMachine`, com a assinatura do §4.2. `LiveStep` (mesmo módulo) é um dataclass com `state`, `stability` e `emit`, e `emit` é a tupla `(InferenceResult, bytes, datetime)`.
- **Sessões (CA-04 e CA-08):** a rota é a interface. `app.state.live_sessions` expõe o `LiveSessions`, que tem `len()`.
- **Configuração:** campos de `EdgeSettings` com o nome da variável, e a propriedade `tls_enabled`. Todas as variáveis novas estão em `EDGE_ENV_VARS` de `edge/tests/conftest.py`, e o `clean_edge_env` as limpa.
- **Console:** o elemento `id="live-latency"` mostra `—` ou `última 100 ms · p95 300 ms`. Com TLS, `id="live-url"` traz a URL do segundo QR, e `<div class="qr" id="live-qr">`, o QR.
- **Lote e sessão:** o campo de lote da página tem `id="lot_id"` e `name="lot_id"`.

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
uv run pytest edge/tests/test_live.py edge/tests/test_live_route.py edge/tests/test_live_config.py -q
```

**Ensaio do autor, fora da suíte (não substitui o CA-12):** com o Chrome em modo headless, `--use-fake-device-for-media-stream` (câmera falsa, sem nenhuma imagem real), um certificado autoassinado em `https://127.0.0.1` e `--stub-model`:

- a página abriu a câmera, pediu o lote antes de enviar, mandou quadros de 640×480, desenhou o rótulo, a confiança, o estado e a barra de estabilidade, e mostrou a inspeção registrada;
- em 16 quadros, houve exatamente uma inspeção no sink e um arquivo JPEG em `captures/`, e o console mostrou a latência;
- em `http://partqc.test` (nome que não é contexto seguro), a página mostrou `O vídeo ao vivo exige HTTPS (configure EDGE_TLS_CERT e EDGE_TLS_KEY).`, sem erro de script;
- sem TLS, a URL do console começa com `http://`, e o console não contém `/live?`; o token não apareceu no log;
- com `EDGE_TLS_CERT`/`EDGE_TLS_KEY` apontando para um PEM inválido, o `uvicorn` saiu com código 1 (`ssl.SSLError`), sem o conteúdo do arquivo no log; só com `EDGE_TLS_CERT`, a borda saiu com código 2, citando as duas variáveis.

Isso não diz nada sobre os celulares reais, nem sobre o `mkcert`, que não está instalado nesta máquina: o §3.3, passo 1, e o CA-12 continuam com o humano, depois do merge.

## Decisões tomadas dentro do escopo da SPEC

As decisões locais 2 (relógio para trás), 3 (limpeza no `lifespan`) e 7 (`Host` sem porta na 443 com TLS) foram aceitas no Histórico da SPEC; as outras viraram requisito nos SPEC_ISSUE-07, 08 e 10. Além delas:

1. **Rótulos da inspeção emitida na página (§4.5):** a resposta só traz `labels_pt` do quadro atual, e o emitido pode ser outro (CA-01), mas a página tem de mostrar a inspeção por 2 s. Para não acrescentar chave à resposta do §4.4 nem repetir no JS a regra de defeito, a rota da página manda em `data-labels` as tabelas de rótulos e o veredito de cada grau, calculados com `qc_contracts`, já com o sufixo de provisório quando for o caso.
2. **Sufixo no resultado `unknown` com modelo provisório:** `result.labels_pt.verdict` é `desconhecido (modelo provisório)`, como na captura (§4.4, "montado como na captura", e SPEC-041 §4.7). O texto "são `desconhecido`" do §4.4 vale para o caso sem provisório, que é o do CA-17. Se o architect ler de outro jeito, é um ajuste de uma linha em `_labels_pt`.
3. **Onde o lote é comparado:** em `LiveSessions.feed`, e não em `admit`. Assim, um quadro com lote novo cuja inferência falha não reinicia a janela (§4.4: "o estado da sessão não muda"), e uma janela nunca mistura dois lotes, mesmo com duas requisições simultâneas.
4. **Sessão é criada antes da inferência:** a ordem do §4.4 põe o 429 antes da inferência, então a vaga é reservada em `admit`, e o quadro que falha na inferência conta como atividade da sessão.
5. **Sessão que venceu entre `admit` e `feed`, com a vaga tomada:** responde 429. Só ocorre com um salto do relógio, porque a inferência leva milissegundos.
6. **Arquivo que "não abre" (§4.1):** a borda abre com `O_NONBLOCK`, confere com `fstat` que é arquivo regular e fecha, sem ler nada. Um FIFO não trava a subida, e um diretório é recusado. Um link simbólico vale pelo alvo, inclusive para o modo da chave.
7. **Mensagem de um TLS incompleto:** `EDGE_TLS_CERT and EDGE_TLS_KEY must be set together`, sempre sob `EDGE_TLS_KEY`, porque os validadores de campo só enxergam os campos anteriores. O texto cita as duas.
8. **`LIVE_WINDOW` reduzido sem `LIVE_MIN_AGREE`:** com `LIVE_WINDOW=5` e o padrão 8, a borda sai com código 2, citando `LIVE_MIN_AGREE` (o §4.6 pede de 1 a `LIVE_WINDOW`). O `.env.example` e o README avisam.
9. **Quadros após o `EMIT`:** os bytes já guardados na janela são descartados no próprio passo `EMIT`, porque nada mais pode ser emitido até o próximo `IDLE` (§4.2, "só guarda os bytes dos quadros que podem ser emitidos").
10. **Página sem token na URL ou sem lote válido:** a página mostra a mensagem e não envia quadros. No 401, ela para a câmera. Cada quadro tem um prazo de 15 s no navegador, para uma requisição presa não travar o envio, já que só uma fica em andamento.
11. **`app.state.live_sessions`:** exposto para os testes, como `session_token`. Nenhuma rota o usa por esse caminho.
12. **Mensagem do console fora do loopback:** com TLS, o texto do 403 cita `https://127.0.0.1`. Sem TLS, continua igual ao `FORBIDDEN_HTML`.

## SPEC_ISSUE

**Nenhum aberto.** Os 12 registrados nesta rodada, antes da implementação, foram corrigidos pelo architect (commit `77e3e12`) e reaprovados (Histórico da SPEC, 2026-11-01): 01 a 09 pelo orquestrador, sob o ADR-019, e 10, 11 e 12 pelo humano.

| ID | Assunto | Situação |
|---|---|---|
| SPEC_ISSUE-01 | `DecisionResult` não existia | Resolvido: `InferenceResult`, implementado |
| SPEC_ISSUE-02 | `(unknown, None)` podia gerar `EMIT` | Resolvido: condição 2 do §4.2 e CA-15, implementados |
| SPEC_ISSUE-03 | Empate no par mais frequente | Resolvido: condição 1 do §4.2 e CA-16, implementados |
| SPEC_ISSUE-04 | Quando `result` era `null` | Resolvido: sempre objeto, e CA-17, implementados |
| SPEC_ISSUE-05 | Falha ao gravar no passo `EMIT` | Resolvido: `reset` da sessão e CA-18, implementados |
| SPEC_ISSUE-06 | Página do `/live` em `static/`, respondendo sem token | Resolvido: `templates/live.html` e CA-10, implementados |
| SPEC_ISSUE-07 | Janela guardava bytes que nunca seriam gravados | Resolvido: só os quadros que podem ser emitidos, implementado |
| SPEC_ISSUE-08 | Formato e limite de corpo da rota | Resolvido: só JPEG, `path_limits` no middleware e CA-05, implementados |
| SPEC_ISSUE-09 | CA-08 não exercitava a janela de cada sessão | Resolvido: inatividade pelo `clock` do `create_app`, implementada |
| SPEC_ISSUE-10 | CA-12 pedia latência no console | Resolvido: `id="live-latency"` e CA-20, implementados |
| SPEC_ISSUE-11 | Definição de pronto citava só o §6.1 | Resolvido na SPEC; §6.1 e §6.4 da `architecture.md` ficam com o architect (§8) |
| SPEC_ISSUE-12 | Erro de inferência, trava, `WAIT_REMOVAL`, lote, QR do `/live` e textos | Resolvido: itens (a) a (g), implementados |

## Observações para os próximos papéis

- **Architect (§8 da SPEC):** faltam as variáveis novas no §6.4 da `docs/architecture.md`. O §6.1 já lista as duas rotas, mas o texto do `GET /` ainda cita só `http://`.
- **Security-devops:** a decisão 7 do Histórico (`Host` sem porta) está em `qc_edge/security.py::is_allowed_console_host`, com `tls=True` só na porta 443, e, com TLS, o `Host` sem porta na 80 deixa de valer. Vale conferir também que os logs da rota usam as mensagens `capture accepted` e `capture refused`, sem token e sem imagem. O `rootCA-key.pem` está citado no README como arquivo que nunca sai do notebook.
- **Tester:** nenhum teste de aceite de SPEC anterior precisou de ajuste: a suíte inteira passa sem mudança em `tests/acceptance/`. O `app.py` deixou de ter `_capture_url` (agora `_page_url`), função privada que nenhum teste usa.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando. Suíte inteira, com `CI=true` e `TEST_DATABASE_URL`: 10056 passed, 117 skipped. Depois dela, acrescentei 2 testes em `test_live_route.py` (CA-07 e CA-14), só de teste, e rodei `edge/` de novo, também com o banco: 3351 passed, 7 skipped
- [x] `.env.example` atualizado (`EDGE_TLS_CERT`, `EDGE_TLS_KEY`, `LIVE_*`, com comentário), e `edge/README.md` com a seção "Vídeo ao vivo (HTTPS)"
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Sem dependência nova; `uv.lock` não mudou
