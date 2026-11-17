# SPEC-047 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-047](../../docs/specs/SPEC-047-console-visual.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-047-console-visual` |
| Commits | `7d43bb2` (template e testes unitários), mais o commit deste relatório |

## Resumo

O console da borda ganhou um visual de painel, com CSS só no `<style>` inline de `edge/src/qc_edge/templates/console.html`, o único arquivo de produção alterado (`git diff --stat main...HEAD -- edge/src` mostra só ele). Entraram uma faixa de cabeçalho azul-escura, dois cartões lado a lado (Pareamento e Estado) que viram uma coluna em tela estreita, e mais dois cartões (Últimas inspeções e Cobertura). Conectividade, pendentes e falhas definitivas aparecem como selos de cor, e as tabelas ficaram zebradas sem anular o verde de `tr.complete`. A página termina com a nota da recarga de 5 s. Não há JS, recurso externo, animação, `<details>` nem rolagem interna. Os 17 placeholders são os mesmos, e só `sink_pending` e `sink_dead` são usados duas vezes, no `data-count`.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `edge/src/qc_edge/templates/console.html` | `edge/tests/test_console_template.py::test_no_external_resource_nor_script`, `::test_nothing_that_blinks_on_reload` |
| CA-02 | idem | `::test_placeholders_are_exactly_the_17_of_the_spec` (também confere que todo `$` é um placeholder, §4.2 item 10) |
| CA-03 | idem | `::test_texts_the_old_tests_rely_on_never_appear` |
| CA-04 | idem (`<style>`) | `::test_fonts_are_only_generic_families`, `::test_readable_on_a_projector`, `::test_qr_keeps_its_size_and_white_background`, `::test_complete_coverage_cells_stay_green`, `::test_badge_selectors_are_present` |
| CA-05 | idem | `::test_rendered_console_has_the_cards_and_badges` (cartões, `<h2>`, nota de 5 s, sem `<script`) |
| CA-06 | idem (`data-count` antes do `id`) | `::test_zero_counts_render_as_neutral_badges`; ordem e lotes: unitário antigo `test_pages.py::test_console_from_loopback`, que passa sem mudança |
| CA-07 | idem | `::test_rendered_console_has_the_cards_and_badges` (parametrizado pelos 4 estados: rótulo, `data-connectivity` 1 vez, `data-count` 3 e 2, `auth_error` só no próprio caso) |
| CA-08 | idem (`$live_pairing` continua dentro de `.pairing`) | sem TLS: `::test_rendered_console_has_the_cards_and_badges` (`<svg` 1 vez, QR dentro do cartão Pareamento); com TLS: unitário antigo `test_live_route.py`, que passa sem mudança |
| CA-09 | sem mudança de código (o token só aparece na URL) | `::test_rendered_console_has_the_cards_and_badges` (sem TLS) |
| CA-10 | sem mudança de código (rota, `FORBIDDEN_HTML` e headers intactos) | coberto pelos unitários e aceites antigos (`test_pages.py`, `test_spec_025.py`), que passam |
| CA-11 | manual (humano) | — |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest edge -q
```

Para ver o visual sem subir a borda na LAN, renderizei a página com o `TestClient` (stub, IPs falsos e sink em `auth_error`) e tirei um screenshot com o Firefox headless a 1280 px. Cabeçalho, cartões, selos e a tabela de cobertura apareceram como esperado. Não houve barra de rolagem horizontal, e o QR e o cartão Estado couberam na primeira tela. Esse screenshot não substitui o CA-11.

## Decisões tomadas dentro do escopo da SPEC

- **Layout dos cartões:** grid com `repeat(auto-fit, minmax(min(100%, 30rem), 1fr))`, sem media query. Com 1200 px de largura útil, Pareamento e Estado ficam lado a lado; em tela estreita, empilham.
- **Pareamento:** `.pairing` continua em flex com quebra, e os blocos de texto usam `flex: 1 1 12rem`. Com TLS, o QR de vídeo e o texto dele descem para uma segunda linha dentro do mesmo cartão. O `.qr` ganhou `padding: 12px` e fundo branco.
- **`dl` do Estado:** a coluna dos rótulos tem largura fixa de `13rem` e quebra linha, para sobrar largura aos valores. Os rótulos (`dt`) usam `#555555` em negrito.
- **Selos:** a base dos três selos usa os `id` (`#sink-pending`, `#sink-dead` e `#sink-connectivity`). Os seletores de valor são `#sink-connectivity[data-connectivity=...]`, que contêm literalmente os seletores pedidos no CA-04. O `id` foi necessário para vencer a especificidade da base. O selo usa `white-space: normal`, e o texto longo de `auth_error` quebra dentro do cartão (conferido no screenshot).
- **Zebra:** `tbody tr:nth-child(even):not(.complete) td`, para não anular o verde de `tr.complete td { background: #d7f2dd; ... }`.
- **Números à direita:** só nas colunas 3 e 4 da tabela de cobertura e no total do rodapé, com `tabular-nums`.
- **Fontes:** `system-ui, ui-sans-serif, sans-serif` no corpo e `ui-monospace, monospace` em `.url`. O corpo tem `18px`, o `h1` tem `1.6em` e o `h2` tem `1.2em`.
- **Cores:** todas da paleta da §4.3, com dois tons claros de apoio: `#e9eef5` no fundo do cabeçalho das tabelas e `#f6f8fa` na zebra. Os dois ficam sob texto `#1b1b1b`, com contraste acima de 14:1.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`edge/tests/test_console_template.py`: 14 passed)
- [x] `uv run pytest edge -q`: 3750 passed, 11 skipped (MQTT real, banco e modelo real, como antes). Todos os aceites antigos da §3.1 passam sem alteração
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhum `.py` de `edge/src/` alterado
