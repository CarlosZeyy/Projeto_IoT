# SPEC-019 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `018f64b` |
| **Veredicto** | **PASS** (CA-12 e §3.3 manuais pendentes, com o humano depois do merge) |

Os CAs não mudaram desde a r1. Os testes de aceite continuam os escritos a partir da SPEC, antes da leitura da implementação. Nesta rodada li o `live.js`, porque o T-01 e os RV-03 e RV-04 são de comportamento da página.

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
| CA-12 (manual) | Não automatizado. Fica com a dupla, depois do merge (SPEC §3.3 e §8). O ensaio abaixo não o substitui | ⏳ pendente |
| CA-13 | `test_ca13_provisional_model_is_simulated_with_the_suffix`, `test_ca13_official_model_is_live_without_the_suffix` | ✅ |
| CA-14 | `test_ca14_photo_flow_without_tls_is_as_before` | ✅ |
| CA-15 | `test_ca15_empty_table_never_emits`, `test_ca15_known_type_without_grade_emits` | ✅ |
| CA-16 | `test_ca16_tie_does_not_emit_and_the_window_rolls` | ✅ |
| CA-17 | `test_ca17_result_is_never_null`; a última frase (30 respostas do CA-06) está em `test_ca06_one_inspection_per_part` | ✅ |
| CA-18 | `test_ca18_failure_to_persist_resets_and_emits_again` | ✅ |
| CA-19 | `test_ca19_failed_inference_does_not_enter_the_window` | ✅ |
| CA-20 | `test_ca20_console_latency` | ✅ |

Nenhum teste de aceite de SPEC anterior foi alterado (`docs/architecture.md` §10). O único ajuste é o do RV-02, num teste exploratório desta própria SPEC.

## RV-02 (resolvido)

`test_extra_token_and_image_do_not_reach_the_logs` excluía só o logger `httpx`. O filtro agora exclui `httpx` e `httpx2`, e os demais loggers continuam conferidos. O teste passou a exigir também pelo menos um registro de `qc_edge`, para o filtro nunca o esvaziar sem aviso.

| Ambiente | Antes da correção | Depois da correção |
|---|---|---|
| Com o extra `train` (`torch` 2.14.1, `httpx2` 2.13.1), arquivos da SPEC | **1 failed, 346 passed**: o token aparece no log do `httpx2`, a URL de teste do `TestClient` | **347 passed** |
| Sem torch, como no CI, arquivos da SPEC | não medido nesta rodada (a r1 passou nesse ambiente) | **347 passed** |

Isso confirma a leitura do `r1-review-report.md`: o registro é do cliente de teste, e não da borda. Os logs da borda continuam sem o token e sem a sessão.

## Suíte completa

Ambiente como no CI, sem torch (`uv sync --all-packages --locked`; `uv lock --check` limpo, `uv.lock` sem mudança), com `CI=true` e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, sem outra suíte com banco ao mesmo tempo.

```text
$ CI=true TEST_DATABASE_URL=... uv run pytest -q -rs
10165 passed, 166 skipped, 1 warning in 2238.39s (0:37:18)

$ uv run pytest edge/tests/acceptance/test_spec_019.py -q
175 passed, 1 warning

$ uv run pytest api/tests -m db -q        # o banco de teste estava em uso de fato
667 passed, 664 deselected, 1 warning

$ uv run pytest edge/tests/test_live.py edge/tests/test_live_route.py edge/tests/test_live_config.py \
    edge/tests/acceptance/test_spec_019.py -q --cov=qc_edge.live --cov=qc_edge.limits --cov=qc_edge.security
347 passed, 1 warning
live.py 99%, limits.py 94%, security.py 96% (só estes arquivos de teste)
```

Pulados: 166, o mesmo total da r1. Guardei só o fim da listagem de `-rs`, então não refaço aqui a divisão por motivo; o trecho guardado mostra os pulados sem `PARTQC_DOCKER_TESTS`.

Com o extra `train` (`uv sync --all-packages --extra train --locked`), depois da correção e de novo ao restaurar o extra:

```text
$ uv run pytest edge/tests/test_live.py edge/tests/test_live_route.py edge/tests/test_live_config.py \
    edge/tests/acceptance/test_spec_019.py -q
347 passed
```

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
311 files already formatted
```

O extra `train` foi restaurado no `.venv` deste worktree ao terminar (`torch` 2.14.1, `timm` 1.0.30).

## Bugs encontrados

Nenhum.

## Verificação do T-01 / RV-01 (exigida pelo `r1-review-report.md`)

**Resultado: o corte não se repete.** Em 390 px, com vídeo em paisagem e em retrato, o veredito e o aviso `(modelo provisório)` ficam inteiros, na faixa do resultado e na verde do `EMIT`, e o rótulo oficial mais longo também.

**Ambiente:** Google Chrome 156.0.8078.79, `--headless=new`, controlado por CDP, com `Emulation.setDeviceMetricsOverride` (`mobile: true`, escala 2) e câmera falsa com `--use-file-for-fake-video-capture`, alimentada por vídeos sintéticos (`ffmpeg testsrc2`; nenhuma foto). Servidor real com TLS autoassinado em `https://127.0.0.1`, `LIVE_FPS=5`, sem `DEVICE_API_KEY` nem `CLOUD_API_URL`: nada foi enviado à nuvem.

**Duas formas de rodar:**

- **T-01 literal:** `qc-edge` real, `MODEL_DIR=~/partqc-provisorio/models/partqc-mnv3-provisional-v1`, nada forçado. O vídeo sintético só produz `unknown`, então este caso mostra `desconhecido (modelo provisório)`.
- **Matriz:** o mesmo modelo ONNX real roda em todos os quadros, e o tipo e o grau da resposta são trocados depois da inferência, como no ensaio da r1, para chegar aos rótulos pedidos. Para o modelo oficial, usei uma cópia do mesmo ONNX num diretório `partqc-mnv3-v1`. O `model_version`, o sufixo, o `source` e a página vêm do código real. A troca e a cópia existem só no ensaio.

**Como medi, por três caminhos independentes:**

1. Envolvendo `fillText`, `fillRect` e `clearRect` do canvas `overlay`, para cada desenho: a linha não pode sair de `largura − 10` px nem da faixa na vertical, nem encostar na seguinte. O texto da linha precisa ser o esperado, com o veredito e o aviso inteiros.
2. Por pixels (`getImageData` na faixa): nenhum pixel de texto nas 3 colunas das bordas do canvas.
3. A olho, em capturas de tela de 4 casos da r2: `parafuso mediano` provisório em paisagem 4:3 e em retrato 9:16, `chave Phillips` oficial na faixa verde em retrato 3:4, e `desconhecido` provisório do T-01 literal em retrato 3:4.

Também conferi que a faixa fica na tela sem rolar a página, o `source` e o veredito no JSON e que todas as respostas foram 200.

**Controle negativo:** rodei o mesmo roteiro com o `live.js` da r1 (`46a357d`), injetado só no navegador. **6 de 6 casos foram reprovados**, e as larguras confirmam o T-01 e as estimativas do review, então o roteiro detecta o defeito.

| Canvas (390 px) | r1: `parafuso mediano — aprovada (modelo provisório)` | r1: `chave Phillips inutilizável — reprovada` |
|---|---|---|
| 358×269 (paisagem 4:3) | fonte 22, 555 px, cortado | fonte 22, 421 px, cortado |
| 358×477 (retrato 3:4) | fonte 31, 782 px, cortado | fonte 31, 594 px, cortado |
| 358×636 (retrato 9:16) | fonte 41, 1034 px, cortado | fonte 41, 785 px, cortado |

**T-01 literal, r2, 390 px, 4 vídeos:** 0 problemas. 21 ou 22 quadros por vídeo, todos 200, estado `IDLE`, contexto seguro e câmera `live`. O console mostrou o aviso de provisório e `última 24 ms · p95 35 ms`, com o navegador na mesma máquina; é uma leitura só, e não uma medida da RNF-02.

| Canvas | 2ª linha, com o aviso | Fonte | Largura |
|---|---|---|---|
| 358×269 (paisagem 4:3) | `desconhecido (modelo provisório)` | 18 px | 287 px |
| 358×201 (paisagem 16:9) | idem | 18 px | 287 px |
| 358×477 (retrato 3:4) | idem | 21 px | 334 px |
| 358×636 (retrato 9:16) | idem | 21 px | 334 px |

**Matriz, r2: 92 casos, 0 com problema.** São 4 vídeos (paisagem 4:3 e 16:9; retrato 3:4 e 9:16) × 6 telas (390×844, 360×800, 412×915, 320×568, 780×900 e 844×390) × 3 rótulos (`parafuso mediano` provisório; `chave Phillips inutilizável` provisório e oficial) = 72 casos. Em 390×844, mais 5 rótulos em cada vídeo = 20 casos: `chave de fenda inutilizável` provisório, `desconhecido` provisório e oficial, `esmerilhadeira` provisório e `parafusadeira` oficial, os dois sem grau. Ao todo, 260 amostras e 1988 desenhos conferidos. Cada um dos 84 casos que emitem teve 1 inspeção, com `simulated` no provisório e `live` no oficial; os 8 de `desconhecido`, nenhuma.

Em 390 px, faixa do resultado (`fonte / largura em px`, canvas de 358 px; limite de 338 px):

| Vídeo | Canvas | `parafuso mediano` | `aprovada (modelo provisório)` | `chave Phillips inutilizável` (oficial) | `reprovada` (oficial) |
|---|---|---|---|---|---|
| Paisagem 4:3 | 358×269 | 18 / 163 | 18 / 249 | 18 / 226 | 18 / 86 |
| Paisagem 16:9 | 358×201 | 18 / 163 | 18 / 249 | 18 / 226 | 18 / 86 |
| Retrato 3:4 | 358×477 | 22 / 199 | 22 / 304 | 22 / 276 | 22 / 105 |
| Retrato 9:16 | 358×636 | 29 / 263 | 24 / 332 | 26 / 326 | 29 / 139 |

Em 390 px, faixa verde do `EMIT`:

| Vídeo | `Registrada: parafuso mediano` | `aprovada (modelo provisório)` | `Registrada: chave Phillips inutilizável` | `reprovada (modelo provisório)` |
|---|---|---|---|---|
| Paisagem 4:3 e 16:9 | 22 / 329 | 22 / 304 | 18 / 332 | 22 / 313 |
| Retrato 3:4 | 22 / 329 | 24 / 332 | 18 / 332 | 23 / 327 |
| Retrato 9:16 | 22 / 329 | 24 / 332 | 18 / 332 | 23 / 327 |

Menor fonte por tela: 18 px na faixa do resultado em todas. Na faixa verde, 14 px em 320×568, 16 px em 360×800, 17 px em 390×844 (`Registrada: chave de fenda inutilizável`), 19 px em 412×915 e 22 px em 780×900 e 844×390.

**Limites:** mesma máquina, sem Wi-Fi e sem celular, com `system-ui` resolvendo para Noto Sans. A regra mede em tempo de execução, então outra fonte muda os tamanhos, mas o aparelho real só é conferido no CA-12. Os números não dizem nada sobre a qualidade do modelo.

## Testes exploratórios (além dos critérios)

**RV-03, lote confirmado, com teclas reais (`Input.insertText` e `Input.dispatchKeyEvent`):**

| Passo | Resultado |
|---|---|
| Página nova, sem lote guardado, por 1,5 s | 0 quadros, com a mensagem de lote |
| `L-001` e sair do campo | os quadros levam `L-001` |
| `L-0`, ainda em digitação, com o campo em foco, por 1,5 s | 7 quadros, todos com `L-001`; o campo mostra `L-0` |
| `L-002` + Enter | 8 quadros com `L-002`, e o campo perde o foco |
| `L-003` com espaços nas pontas e sair do campo | quadros com `L-003`, igual ao gravado no `localStorage` |
| `lote 1` (inválido) e sair do campo | 0 quadros, com a mensagem de lote |
| `L-004` e sair do campo | volta a enviar |
| Inspeções do ensaio, por lote | `L-001`, `L-003`, `L-004`: nunca `L-0` nem `lote 1`. `L-002` não emitiu porque teve só 8 quadros antes da troca, menos que a janela de 10 |

**RV-04, cache de navegação (Chrome com `--enable-features=BackForwardCache`):**

| Passo | Resultado |
|---|---|
| Ida e volta real no histórico (`/live` → outra página da borda → voltar) | `pageshow` com `persisted: true`, seguido de recarga (`reload`). Câmera `live`, 16 quadros em 3,5 s, token na URL e lote `L-BF` mantidos, sem mensagem de erro |
| `pagehide` e `pageshow(persisted)` despachados à mão | recarrega, câmera `live`, 17 quadros em 3,5 s, token e lote mantidos |

A restauração real dependeu dessa opção do Chrome, então não garante o que cada celular faz. Conferir no CA-12 continua útil.

**Outros casos da página, com o modelo provisório e o rótulo longo:**

| Caso | Resultado |
|---|---|
| Tela muito estreita, 280×653 e 240×320, vídeo 9:16 | nada cortado; menor fonte de 12 px e de 10 px |
| Girar a tela com a página aberta (390×844 → 844×390 → 390×844) | o canvas é redesenhado (512×910 e 358×636), nada cortado, e a faixa termina em 340 px e 294 px |

**Notas sem bug:**

- **Texto levemente borrado:** o canvas usa o tamanho em px CSS, sem a escala do aparelho, e as capturas com escala 2 mostram as letras um pouco borradas. Continuam legíveis. A SPEC não fala disso.
- **Barra de estabilidade fora da tela:** com vídeo em retrato em tela baixa, como 844×390, o canvas passa da altura da tela, e a barra só aparece rolando a página. A faixa termina em 340 px de 390 px, e em 320×568 termina em 273 px, então o veredito e o aviso ficam visíveis. Confirma a observação do `r2-dev-report.md`.
- **`desconhecido` repetido:** no modelo oficial, a faixa mostra `desconhecido` em duas linhas, o que decorre do §4.4. Com o modelo provisório, a 2ª linha tem o aviso.
- **Sem o `EMIT` espontâneo:** como na r1, o vídeo sintético só produz `unknown` no modelo real, então o `EMIT` com o modelo real só foi visto com a decisão forçada.

**Sobre o ensaio:** os scripts não são versionados e não fazem parte da suíte. O `guard_paths` recusou escrevê-los no diretório temporário da sessão, por ficar fora do projeto. Por isso, ficaram em `edge/tests/acceptance/_t01_rehearsal/`, um caminho permitido, sem commit, e foram apagados antes de rodar a suíte e o ruff. Os vídeos, o certificado, a chave de teste e as capturas foram gerados por comando no diretório temporário e apagados no fim.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
