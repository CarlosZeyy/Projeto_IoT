# SPEC-047 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-047](../../docs/specs/SPEC-047-console-visual.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `8d07355` (template em `7d43bb2`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta), antes da leitura do `console.html`. A borda não foi subida na LAN. O console foi lido em processo, por `httpx.ASGITransport` com o cliente `("127.0.0.1", 50000)` e por `TestClient` para as capturas, como nos aceites das SPECs 007, 019 e 043. A única fronteira trocada é `qc_edge.netinfo.detect_lan_ips` (`["192.168.0.42", "10.0.0.7"]`), e no CA-07 o sink tem um `stats()` controlado. O par TLS é o mesmo par falso dos aceites das SPECs 019 e 043. O token é gerado na execução.

## Cobertura dos critérios de aceite

Arquivo: `edge/tests/acceptance/test_spec_047.py` (27 testes: 17 dos CAs, contando os parâmetros, e 10 exploratórios).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_no_external_resource_no_script_nothing_that_blinks` | ✅ |
| CA-02 | `test_ca02_template_is_valid_with_exactly_the_17_placeholders` | ✅ |
| CA-03 | `test_ca03_texts_old_tests_rely_on_never_appear` | ✅ |
| CA-04 | `test_ca04_style_rules` (`body` 18px; `font-family` só genéricas e sem o atalho `font:`; `.qr svg` 260×260 e `#fff`; `tr.complete td` `#d7f2dd`; os 5 seletores de selo) | ✅ |
| CA-05 | `test_ca05_rendered_console_keeps_texts_and_gains_the_cards` | ✅ |
| CA-06 | `test_ca06_counts_model_and_last_ten_inspections` (12 capturas `L-000`…`L-011` num `InMemorySink`; 10 linhas `L-011`…`L-002`) | ✅ |
| CA-07 | `test_ca07_connectivity_and_count_badges[online/offline/auth_error/disabled]` | ✅ (4/4) |
| CA-08 | `test_ca08_one_qr_without_tls`, `test_ca08_two_qrs_with_tls` | ✅ |
| CA-09 | `test_ca09_token_only_in_the_pairing_urls[no-tls/tls]` | ✅ (2/2) |
| CA-10 | `test_ca10_refusals_keep_text_and_headers[lan-client/foreign-host/x-forwarded-for]`, `test_ca10_ip_parameter_with_markup_is_not_reflected`, `test_ca10_console_headers_on_200` | ✅ (5/5) |
| CA-11 (manual) | — (o humano confere no notebook/projetor) | ⏳ pendente do humano; não conta como falha nesta rodada |

## Aceites antigos (§3.1)

- `git diff --stat main -- '*/tests/acceptance/'` está vazio: nenhum aceite antigo foi alterado, nem por mim nem pelo developer. O único arquivo novo em `tests/acceptance/` é o `test_spec_047.py`.
- Todos os aceites da lista da §3.1 (SPECs 007, 008, 009, 010, 019, 020, 021, 025, 036, 041, 043 e 044) e os unitários antigos da §3.1 passam sem mudança na suíte completa abaixo.
- Não houve ajuste de asserção de SPEC anterior (`docs/architecture.md` §10): a tabela de ajustes fica vazia.
- `git diff --stat main...HEAD -- edge/src` mostra só `edge/src/qc_edge/templates/console.html` (54+, 16−).

## Suíte completa

Com `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test` (container `partqc-pg`). Uma primeira execução teve a saída perdida porque a sessão foi interrompida, e esta é a execução completa que valeu:

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
11212 passed, 116 skipped in 1363.39s (0:22:43)

Os 116 skips são todos opt-in já existentes antes desta SPEC: imagens Docker
(PARTQC_DOCKER_TESTS), MQTT real (PARTQC_MQTT_TESTS), medição de rede real
(PARTQC_TELEMETRY_TESTS) e modelo real (QC_REAL_MODEL_DIR). Os testes com banco rodaram.

$ uv run pytest -q edge/tests/acceptance/test_spec_047.py
27 passed
```

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
336 files already formatted
```

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Automatizados (`test_extra_*`, todos passam):

| Caso | Regra | Resultado |
|---|---|---|
| Todo `$` do arquivo é um dos 17 placeholders (um `$` solto faria o `substitute` dar 500) | §4.2 item 10 | ✅ |
| `.qr` e `.qr svg` sem `filter`, `opacity`, `transform` ou `mix-blend-mode`; `.qr` com `padding` e fundo branco | §4.2 item 4 | ✅ |
| Nenhum `overflow` com `auto` ou `scroll` | §4.2 item 7 | ✅ |
| A zebra (`nth-child`) com fundo exclui `.complete` (`tbody tr:nth-child(even):not(.complete) td`), sem anular o verde | §4.2 item 6 | ✅ |
| Nos `<dd>` com `id`, o `id` é o último atributo; `sink-connectivity` igual ao de antes; `data-count` antes do `id` | §4.1 | ✅ |
| `$live_pairing` continua dentro do `<div class="pairing">`, depois do `.qr` | §4.1 | ✅ |
| `Pareamento` e a nota de 5 s aparecem exatamente 1 vez cada | §4.1 | ✅ |
| As regras do selo de conectividade não usam `white-space: nowrap`/`pre` (o rótulo de `auth_error`, de ~90 caracteres, quebra) | §7.2 | ✅ |

Manuais (script descartável, fora do repositório):

- Console com `EDGE_HOST` `0.0.0.0`, `127.0.0.1` e `10.0.0.7`, com 2 IPs e com o fallback: 200 em todos, 1 `<svg`, e o aviso `.warning` só no caso do loopback. Num primeiro ensaio, simulei `detect_lan_ips` devolvendo `[]`, o que deu 500 (`IndexError` em `ips[0]`, `app.py`). **Não é defeito:** pelo contrato, `detect_lan_ips` nunca devolve lista vazia (o fallback é `["127.0.0.1"]`), e o trecho não muda nesta SPEC. Ficou registrado só para o reviewer não repetir o ensaio.
- `GET /?ip=` com `10.0.0.7`, `%00`, 5000 dígitos e `ip` repetido: 200 em todos, sem `<script`.
- `DEVICE_ID` com `$`, acento ou HTML: recusado na configuração (`^[a-z0-9-]{3,32}$`), então não chega ao template. Os valores dos placeholders não são reinterpretados pelo `string.Template`.
- Leitura da paleta no `<style>`: todas as cores de texto e fundo são as da §4.3, mais `#e9eef5` (cabeçalho das tabelas) e `#f6f8fa` (zebra), ambos sob `#1b1b1b`, com contraste acima de 14:1. O `h2` usa `#1f3a5f` sobre `#ffffff` (cerca de 11:1). Sem `prefers-color-scheme`, sem media query.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
