# SPEC-019 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-019-modo-ao-vivo` |
| Commits | `5d94c44`, `93699cf`, `c7da4f4`, além do commit deste relatório |

## Resumo

Esta rodada só mexe na página: `edge/src/qc_edge/static/live.js`, os testes do autor e dois itens do `edge/README.md`. O servidor, a rota, a resposta, o contrato e as variáveis não mudam.

- **RV-01 (T-01), obrigatório:** o veredito tem linha própria, cada linha reduz a fonte até caber na largura do canvas, e a faixa acomoda as três linhas. Medido no Chrome headless: 60 casos, sem nenhum texto cortado (na r1, 54 dos 60 tinham corte).
- **RV-03 e RV-04:** tratados, porque são pequenos e ficam dentro do §4.5.
- **RV-02:** é do tester, e a RV-05, do orquestrador. Nenhuma das duas foi tocada.

## Rastreabilidade (critério de aceite → implementação)

Os CAs não mudaram. Os testes ficam em `edge/tests/`: `test_live.py` (máquina, sessões, latência, imagem), `test_live_route.py` (rota, página, console) e `test_live_config.py` (HTTPS, argumentos do uvicorn, variáveis).

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
| CA-12 | manual, depois do merge; passo a passo em `edge/README.md`, seção "Vídeo ao vivo (HTTPS)" | não automatizado (ver "Medições no navegador") |
| CA-13 | `qc_edge/app.py` (JSON); `static/live.js` (aviso visível no overlay, RV-01) | `test_live_route.py::test_provisional_model_is_simulated_with_the_suffix`, `test_official_model_is_live_without_suffix`, `test_overlay_gives_the_verdict_its_own_line_and_fits_every_line` |
| CA-14 | `qc_edge/cli.py`, `qc_edge/app.py` | `test_live_config.py::test_uvicorn_arguments_without_tls`; `test_live_route.py::test_console_without_tls_is_as_before`, `test_capture_route_is_unchanged_without_tls` |
| CA-15 | `qc_edge/live.py` | `test_live.py::test_empty_table_never_emits_but_counts_for_stability`, `test_known_type_without_grade_emits` |
| CA-16 | `qc_edge/live.py` | `test_live.py::test_tie_at_the_top_does_not_emit_and_the_window_rolls` |
| CA-17 | `qc_edge/app.py` (`_labels_pt`) | `test_live_route.py::test_unknown_result_has_null_grade_and_desconhecido` |
| CA-18 | `qc_edge/app.py` (`live_frame_step`) | `test_live_route.py::test_sink_error_answers_503_removes_the_photo_and_emits_again`, `test_other_recording_failure_answers_500_and_resets`, `test_full_disk_answers_500_and_resets` |
| CA-19 | `qc_edge/app.py` (`live_frame_step`) | `test_live_route.py::test_inference_error_does_not_enter_the_window` |
| CA-20 | `qc_edge/live.py` (`FrameLatency`, `p95_nearest_rank`), `templates/console.html` | `test_live_route.py::test_console_latency`, `test_live.py::test_p95_rank_matches_the_exact_formula_for_every_size` |

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| Review r1, **RV-01** = test r1, **T-01** (bloqueante, R-06) | `5d94c44`. `resultLines` dá ao veredito uma linha própria, como `emittedLines` já fazia. `drawBand` usa `fitFont`, que mede cada linha com `ctx.measureText` e reduz a fonte até caber em `width - 20`, nas duas faixas. A altura da faixa passa a `max(56, 22 × linhas, altura / 6)`, e as linhas ficam centradas nas fileiras (`textBaseline = "middle"`), porque a conta antiga foi feita para duas linhas e, com três, deixaria a primeira encostada no topo da faixa (por cálculo, não medido). Sem mudança na SPEC, na rota ou nos rótulos |
| Review r1, **RV-03** (baixa) | `93699cf`. **Tratado.** O quadro envia o lote confirmado no evento `change`, e não o valor do campo no meio da digitação. Enter tira o foco do campo, para confirmar também nos teclados que só disparam `change` ao sair dele. Um lote inválido confirmado continua sem enviar quadros, com a mensagem de sempre. Fica dentro do §4.5 ("o campo de lote"), sem requisito novo. O README explica o comportamento |
| Review r1, **RV-04** (baixa), e a nota do test r1 | `c7da4f4`. **Tratado.** `pageshow` com `event.persisted` recarrega a página. A nota do relatório era só de leitura, e aqui o defeito **foi reproduzido**: o Chrome restaurou a página do cache mesmo com `no-store`, e o vídeo ficou parado (ver as medições) |
| Review r1, **RV-02** (baixa) | **Não tratado por mim:** é do tester, em `tests/acceptance/` (R-07) |
| Review r1, **RV-05** (baixa) | **Não tratado por mim:** é do registro do orquestrador no PR. Não há o que mudar no código |

## Medições no navegador (RV-01, RV-03, RV-04)

Ensaio do autor, fora da suíte. Rodei o mesmo roteiro no código da r1 (`46a357d`) e no da r2, para confirmar que ele detecta o defeito.

**Ambiente:** Google Chrome 156.0.8078.79, `--headless=new`, controlado por CDP, com `Emulation.setDeviceMetricsOverride` (`mobile: true`, escala 2) e câmera falsa alimentada por arquivos sintéticos (`ffmpeg testsrc2`, nenhuma foto). Servidor real da borda em `https://127.0.0.1`, com certificado autoassinado, rota e página reais, `LIVE_FPS=5` e sink em memória (nada foi para a nuvem). O inferenciador é roteirizado, para escolher os rótulos, e informa o `model_version` `partqc-mnv3-provisional-v1` ou `partqc-mnv3-v1`, então o sufixo sai do código real. O modelo ONNX não roda neste ensaio.

**Como medi:** o roteiro envolve `fillText`, `fillRect` e `clearRect` do canvas `overlay` e registra, para cada linha desenhada, texto, fonte, posição e `measureText`. Um caso falha se uma linha sair de `largura − 10` px, sair da faixa na vertical, encostar na linha seguinte, ou se o veredito esperado, com o aviso, não estiver inteiro numa linha que cabe. Cada caso confere a faixa do resultado e, quando há emissão, a verde do `EMIT` (52 de 60; `desconhecido` não emite). Conferi também, a olho, as capturas de tela de 4 casos: 3 da r2 e 1 da r1.

**Matriz:** 4 vídeos (paisagem 4:3 e 16:9; retrato 3:4 e 9:16) × 4 telas (390×844, 320×568, 780×900 e 844×390). Em todas: `parafuso mediano` provisório, `chave Phillips inutilizável` provisório e `chave Phillips inutilizável` oficial. Só em 390×844, também: `desconhecido` provisório e oficial, e `furadeira` provisório sem grau. Total: 60 casos.

| Resultado | r1 | r2 |
|---|---|---|
| Casos com algum problema | **54 de 60** | **0 de 60** |
| Casos com o veredito ou o aviso sem caber numa linha | 54 | 0 |
| Corte vertical ou linhas encostadas | 0 | 0 |
| Faixas verdes do `EMIT` conferidas | 52 de 52 | 52 de 52 |
| Menor fonte, faixa do resultado | 22 px | 18 px |
| Menor fonte, faixa do `EMIT` | 22 px | 14 px (`Registrada: chave Phillips inutilizável` em 320 px) |

Os 6 casos que passaram na r1 foram `desconhecido` oficial em 390 px com vídeo em paisagem (texto curto) e `chave Phillips` oficial no canvas de 512 px com vídeo em paisagem.

Larguras e orientações do `r1-review-report.md`. O canvas medido é 358×269, e não 358×268. As larguras medidas na r1 confirmam as estimativas do relatório. Na r2, a coluna traz a fonte e a largura da linha do veredito, sempre dentro do limite de `largura − 20`:

| Canvas (vídeo) | Texto de `parafuso mediano`, provisório | Largura na r1 (uma linha) | Na r2: veredito, com o aviso | Na r2: 1ª linha |
|---|---|---|---|---|
| 358×269 (390 px, paisagem 4:3) | fonte 22 | 555 px, cortado | 18 px, 249 px | 18 px, 163 px |
| 358×477 (390 px, retrato 3:4) | fonte 31 | 782 px, cortado | 22 px, 304 px | 22 px, 199 px |
| 358×636 (390 px, retrato 9:16) | fonte 41 | 1034 px, cortado | 24 px, 332 px | 29 px, 263 px |
| 512×384 (780 px, paisagem 4:3) | fonte 25 | 631 px, cortado | 18 px, 249 px | 18 px, 163 px |
| 512×288 (780 px, paisagem 16:9) | fonte 22 | 555 px, cortado | 18 px, 249 px | 18 px, 163 px |

Rótulo mais longo do modelo oficial, `chave Phillips inutilizável — reprovada`, em 390 px:

| Canvas | r1 | r2 (1ª linha / veredito) |
|---|---|---|
| 358×269 | 421 px, cortado | `chave Phillips inutilizável` 226 px / `reprovada` 86 px |
| 358×477 | 594 px, cortado | 276 px / 106 px |
| 358×636 | 785 px, cortado | 326 px / 139 px |

Na faixa verde, a 1ª linha mais longa, `Registrada: chave Phillips inutilizável`, media 406 px com vídeo em paisagem e era cortada em 358 px na r1. Na r2, ela mede 332 px em 358 px e 258 px em 288 px.

**RV-03, medido com teclas reais, sem sair do campo (`Input.insertText`):**

| Passo | r1 | r2 |
|---|---|---|
| Campo com `L-0`, ainda em digitação, durante 1,5 s (7 quadros) | os quadros levam `L-0` | os quadros levam `L-001` |
| `L-002` + Enter | `L-002`, e o campo continua com o foco | `L-002`, e o campo perde o foco |
| `L-003` e sair do campo | `L-003`, gravado no `localStorage` | igual |
| `lote 1` (inválido) e sair do campo | 0 quadros, com a mensagem de lote | igual |

**RV-04, medido com ida e volta real no histórico do Chrome, com `no-store`:**

| Medição | r1 | r2 |
|---|---|---|
| `pageshow.persisted` depois de voltar | `true`: o Chrome restaurou do cache | a página recarrega |
| Faixa da câmera depois de voltar | `ended`, e a tela fica parada | `live` |
| Quadros depois de voltar | nenhum novo (o contador ficou em 2, o valor de antes de sair) | 12 em 2,5 s, a 5 fps |
| `pagehide` e `pageshow(persisted)` despachados à mão | continua `ended`, com 0 quadros em 7,5 s | recarrega (`reload`), câmera `live`, 12 quadros em 2,5 s, token na URL e lote `L-001` mantidos |

A restauração real usou `--enable-features=BackForwardCache`, então ela não garante o que cada celular faz. Conferir no CA-12 continua útil.

**Limites destas medições:** mesma máquina, sem Wi-Fi e sem celular, com a fonte `system-ui` desta máquina. Como a medição acontece em tempo de execução, outra fonte muda os tamanhos, e não a regra. O roteiro não é versionado, porque a suíte não roda navegador, e nem ele, nem as capturas, nem o certificado de teste ficaram no repositório. Isso não substitui a verificação exigida do tester na r2 (`r1-review-report.md`, "Como fechar") nem o CA-12.

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest edge/tests/test_live.py edge/tests/test_live_route.py edge/tests/test_live_config.py -q
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

## Decisões tomadas dentro do escopo da SPEC

As decisões do `r1-dev-report.md` continuam valendo. Além delas:

1. **Fonte por linha:** cada linha da faixa tem a própria redução, como o relatório sugere, em vez de todas seguirem a mais longa. Assim, um veredito curto, como `reprovada`, continua grande. Por isso os tamanhos variam dentro da faixa no retrato.
2. **Altura da faixa de três linhas:** o piso sobe de 56 para 66 px só na faixa do resultado, o que dá uma fonte de 18 px. A faixa do `EMIT`, com duas linhas, continua com 56 px.
3. **Sem piso de fonte:** a fonte reduz até caber, como o relatório pede, porque um texto pequeno inteiro é melhor que um aviso cortado (R-06). A menor medida foi 14 px, em 320 px de largura.
4. **Enter tira o foco do campo do lote (RV-03):** o relatório só pede o `change`, mas passar a depender dele criaria um problema novo nos teclados em que Enter não o dispara: o lote digitado não valeria, e o operador não saberia por quê.
5. **Recarregar, e não religar a câmera (RV-04):** como o relatório sugere. A página recarregada ganha uma sessão nova, e a anterior expira em 60 s (§4.3). O lote volta do `localStorage`.

## Observações para os próximos papéis

- **Tester:** nenhum teste de aceite precisou de ajuste. O RV-02 é seu, e o `r1-review-report.md` pede a repetição do procedimento do T-01, com vídeo em paisagem e em retrato. A câmera falsa aceita `--use-file-for-fake-video-capture` com um `.y4m` gerado pelo `ffmpeg`, e o Chrome está em `/usr/bin/google-chrome-stable`.
- **Reviewer e tester, dois pontos que vi e não mudei, por estarem fora do RV-01 e da SPEC:**
  - Num `desconhecido` do modelo oficial, a faixa repete a palavra em duas linhas (`desconhecido` / `desconhecido`), porque o §4.4 define os dois rótulos com esse valor. Na r1 era `desconhecido — desconhecido`.
  - Com vídeo em retrato numa tela baixa (320×568, ou 844×390 com o celular deitado), o palco passa da altura da tela: a barra de estabilidade, no pé do vídeo, só aparece rolando a página. A faixa, com o veredito e o aviso, fica sempre visível (o topo do palco está em 188 px, e a faixa mais alta nessas telas termina em 340 px).
- **Security-devops:** esta rodada não toca rota, token, limites, logs ou TLS. No RV-04, a página recarregada usa a mesma URL, com o token, e o `Referrer-Policy` e o `no-store` da rota continuam iguais.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando. Suíte inteira, com `CI=true` e `TEST_DATABASE_URL`, sem outra suíte com banco ao mesmo tempo: 10165 passed, 166 skipped (1300 s), no commit `c7da4f4`. Na r1, com o mesmo ambiente, o tester mediu 10162 passed e 166 skipped; os 3 a mais são os testes novos do autor
- [x] `.env.example`: sem variável nova nesta rodada, então não mudou
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Sem dependência nova; `uv.lock` não mudou
