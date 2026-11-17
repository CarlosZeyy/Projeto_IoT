# SPEC-047: Visual do console da borda (só apresentação)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | — (sem `security`: nenhuma rota, header, entrada, segredo ou dado exibido muda; os CAs 09 e 10 conferem isso. Ver §9, pergunta 2) |
| Depende de | Nada a esperar: SPECs 007, 008, 009, 010, 019, 025, 041 e 043 estão `Done` |
| Semana alvo | S6, 17/11/2026 (urgente: pedido do humano para antes da apresentação da noite; merge conforme §7.1) |
| Requisitos cobertos | RF-01, RF-07, RNF-10; R-02, R-03 (nada novo sai da página, e o token continua só na URL de pareamento) |
| ADRs relevantes | ADR-012 (rótulos em PT-BR), ADR-018 (custo zero: nenhuma fonte, CDN ou recurso externo), ADR-016 (merge delegado), ADR-023 decisão 5 e `docs/deployment-plan.md` §5 (merge no dia da apresentação, §7.1) |

## 1. Contexto

Pedido do humano (Carlos) em 2026-11-17, dia da apresentação: o console da borda (`GET /`, `docs/architecture.md` §6.1) "parece um HTML muito simples", só textos e o QR code. Ele quer "um visualzinho um pouco mais agradável", sem nada elaborado, e o quanto antes.

Hoje a página é `edge/src/qc_edge/templates/console.html`, renderizada por `string.Template.substitute` em `console()` (`edge/src/qc_edge/app.py`). Ela já tem um `<style>` inline, recarrega a cada 5 s (`<meta http-equiv="refresh" content="5">`) e não tem JS. Os fragmentos de HTML (avisos, outros IPs, segundo QR, limiares, linhas das tabelas, cobertura e página 403) vêm de funções do `app.py`.

**Fatos conferidos no código em 2026-11-17 (leitura):**

- A resposta do console não tem `Content-Security-Policy`. Os headers são os de `PAGE_HEADERS` (`Cache-Control: no-store`, `Referrer-Policy: no-referrer` e `X-Content-Type-Options: nosniff`), iguais na 200 e na 403.
- `/static` é servido sem token a toda a LAN. Por isso esta SPEC não cria arquivo novo ali (§4.1).
- Vários testes antigos procuram trechos literais do HTML. Alguns afirmam que um texto **não** aparece na página, como `loopback-warning`, `Outros IPs`, `PROVISÓRIO`, `/live?`, `p95` e `L-001`. Um CSS que use esses nomes num seletor, ou até num comentário, quebra esses testes. Outros afirmam que um texto aparece, como `auth_error` (SPEC-009) e `data-connectivity="disabled"` (unitário da borda). Um seletor com esse texto exato faria o teste passar sempre, sem conferir nada. As regras da §4.2 evitam os dois problemas.

## 2. Objetivo

O console da borda ganha um visual de painel simples, com cabeçalho, cartões e indicadores de cor, legível no projetor. Os dados, os rótulos, as rotas, os headers e a segurança continuam os mesmos, e só um arquivo de produção muda: `console.html`.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/templates/console.html`: único arquivo de produção alterado. Estrutura obrigatória na §4.1, regras do CSS na §4.2 e paleta na §4.3.
- Opcional, pelo developer: testes unitários do template em `edge/tests/` (por exemplo, `edge/tests/test_console_template.py`).
- **Aceites antigos que conferem o HTML do console.** Todos têm de passar **sem nenhuma alteração**. Esta SPEC não autoriza o tester a converter nenhuma asserção antiga: se um deles quebrar, é defeito da implementação.
  - `test_spec_007.py`: `test_ca13_console_from_loopback` (`<svg`, URL de pareamento, `stub-v0`, `\b12\b`, ordem das linhas `L-0xx`, `L-001` ausente, 10 linhas `<tr class="inspection"`, meta refresh), `test_ca14_console_refuses_remote_or_proxied`, `test_ca18_no_candidate_falls_back_to_loopback_with_console_warning` (`nenhum ip` só com o aviso), `test_extra_console_ip_parameter_only_accepts_detected_ips` e `test_extra_console_accepts_ipv6_loopback`;
  - `test_spec_008.py`: `test_ca18_console_and_status_show_model_and_thresholds` (o token só aparece em `capture?t=`);
  - `test_spec_009.py`: `test_ca07_auth_error_pauses_publishing` (`auth_error` na página);
  - `test_spec_010.py`: `test_ca15_console_shows_the_coverage_table`, `test_ca15_missing_manifest_is_an_empty_table`, `test_extra_console_highlights_only_complete_cells` e `test_extra_console_survives_an_unreadable_manifest`, que recortam de `<table id="coverage">` até o primeiro `</table>`;
  - `test_spec_019.py`: `test_ca09_valid_tls_reaches_uvicorn_and_both_qr_urls_are_https`, `test_ca14_photo_flow_without_tls_is_as_before` (`/live?` ausente), `test_ca20_console_latency` (regex em `id="live-latency"`), `test_extra_console_with_tls_stays_on_loopback`, `test_extra_emitted_inspection_appears_in_the_console` e `test_extra_console_with_tls_uses_the_chosen_ip_in_both_urls`;
  - `test_spec_020.py`: `test_extra_password_not_in_status_nor_console`;
  - `test_spec_021.py`: `test_extra_console_shows_the_power_tool_rows`;
  - `test_spec_025.py`: `test_ca01_console_answers_loopback_hosts`, `test_ca02_console_refuses_other_hosts_before_detecting_ips`, `test_extra_console_still_refuses_remote_and_proxied_with_a_loopback_host` e `test_extra_console_refusal_keeps_the_page_headers`;
  - `test_spec_036.py`: `test_ca13_coverage_ignores_external_images` (`<p id="external-images">`);
  - `test_spec_041.py`: `test_ca19_console_and_log_say_the_model_is_provisional`, `test_ca19_official_model_has_neither` e `test_extra_console_without_a_model_has_no_notice` (`PROVISÓRIO` só com o modelo provisório);
  - `test_spec_043.py`: `test_ca13_*`, `test_ca14_specific_host_offers_only_itself`, `test_ca15_fallback_keeps_only_the_no_lan_warning` (`loopback-warning`, `no-lan-warning` e `Outros IPs` ausentes fora do caso deles), `test_extra_the_qr_follows_the_chosen_address` (o primeiro `<svg` da página é o QR) e `test_extra_console_from_another_client_is_still_refused`;
  - `test_spec_044.py`: `test_ca08_console_coverage_has_one_row_per_new_tool` e `test_extra_console_targets_text_and_pt_br_only`.
- **Unitários antigos do developer que também conferem o HTML** e devem passar sem mudança: `test_pages.py` (`id="sink-pending">12<`, `id="model-thresholds">—<` e `<script` ausente), `test_live_route.py` (`class="qr"` 1 ou 2 vezes e `<svg` 2 vezes com TLS), `test_cli_cloud.py` (`data-connectivity="disabled"`), `test_collect_route.py`, `test_tools.py`, `test_power_tools.py`, `test_identified_tools.py`, `test_provisional_model.py` e `test_model_integration.py`.

### 3.2 Fora

- **Qualquer arquivo `.py` de `edge/src/`**, inclusive os fragmentos gerados no `app.py` (`_coverage_html`, `_row_html`, `_thresholds_html`, `_live_pairing_html`, `_other_ips_html`, os avisos e `FORBIDDEN_HTML`). Mudar texto ou estrutura deles exige uma SPEC futura, se o humano quiser.
- **Páginas do celular** (`capture.html`, `live.html`, `static/capture.css`, `static/*.js`): ficam fora. Uma SPEC futura, se o humano quiser o mesmo visual nelas.
- **Arquivo CSS novo em `edge/src/qc_edge/static/`**: não entra (decisão na §4.1).
- **Rotas, headers (incluindo uma CSP), token, conteúdo dos QR codes, regra de acesso do console (loopback e `Host`, SPEC-025) e recarga de 5 s**: não mudam (SPECs 007, 019, 025 e 043).
- **JS, tabela recolhível (`<details>`), tema escuro e animações**: não entram (motivos na §4.2).
- **Dashboard Streamlit**: não é tocado (N-10, SPECs 013 e 028).
- **`docs/architecture.md` e `edge/README.md`**: não mudam, porque o conteúdo do console é o mesmo.

## 4. Requisitos detalhados

### 4.1 Estrutura do `console.html`

O CSS fica num **único** `<style>` inline no `<head>`, como hoje, e não num arquivo em `/static`. Motivos:

- é o menor diff;
- não cria uma requisição a mais a cada recarga de 5 s;
- não publica um arquivo novo na LAN;
- mantém o console num só arquivo.

O `<body>` segue este esqueleto. As linhas marcadas com `[igual]` ficam **idênticas** às atuais, caractere por caractere. As classes (`topbar`, `cards`, `card`, `inspections`, `footnote`) são sugestões, e o developer pode trocar os nomes, desde que respeite a §4.2.

```html
<body>
<header class="topbar">
<h1>PartQC — console da borda (<span>$device_id</span>)</h1>                         [igual]
</header>
<main>
$ip_warning                                                                           [igual]
<div class="cards">
<section class="card">
<h2>Pareamento</h2>                                                                   [novo]
<div class="pairing">                                                                 [igual]
<div class="qr">$qr_svg</div>                                                         [igual]
<div>                                                                                 [igual]
<p>Leia o QR code com o celular na mesma rede ou abra:</p>                            [igual]
<p class="url">$capture_url</p>                                                       [igual]
$other_ips                                                                            [igual]
</div>                                                                                [igual]
$live_pairing                                                                         [igual: dentro de .pairing]
</div>
</section>
<section class="card">
<h2>Estado</h2>                                                                       [igual]
<dl>
<dt>Modelo</dt><dd id="model-state">$model_state</dd>                                 [igual]
<dt>Limiares de decisão</dt><dd id="model-thresholds">$thresholds</dd>                [igual]
<dt>Pendentes</dt><dd data-count="$sink_pending" id="sink-pending">$sink_pending</dd> [novo atributo, antes do id]
<dt>Com falha definitiva</dt><dd data-count="$sink_dead" id="sink-dead">$sink_dead</dd> [novo atributo, antes do id]
<dt>Conectividade com a nuvem</dt><dd id="sink-connectivity" data-connectivity="$connectivity_code">$connectivity</dd> [igual]
<dt>Último envio</dt><dd id="sink-last-success">$last_success_at</dd>                  [igual]
<dt>Latência por quadro (vídeo ao vivo)</dt><dd id="live-latency">$live_latency</dd>  [igual]
<dt>Dataset (modo coleta)</dt><dd class="url">$dataset_dir</dd>                       [igual]
</dl>
</section>
</div>
<section class="card">
<h2>Últimas inspeções desta sessão</h2>                                                [igual]
<table class="inspections">
<thead><tr><th>Hora</th><th>Lote</th><th>Tipo</th><th>Grau</th></tr></thead>         [igual]
<tbody>
$rows
</tbody>
</table>
</section>
<section class="card">
<h2>Cobertura do dataset</h2>                                                         [igual]
$coverage                                                                             [igual]
</section>
<p class="footnote">A página atualiza sozinha a cada 5 s.</p>                          [novo]
</main>
</body>
```

O `<head>` mantém, iguais, `<!DOCTYPE html>`, `<html lang="pt-BR">`, `<meta charset="utf-8">`, `<meta http-equiv="refresh" content="5">`, `<meta name="viewport" content="width=device-width, initial-scale=1">` e `<title>PartQC — console da borda</title>`.

- **Textos visíveis novos:** só dois, exatamente `Pareamento` e `A página atualiza sozinha a cada 5 s.`. Nenhum outro texto é criado, removido ou reescrito.
- **Placeholders:** exatamente os 17 atuais (`device_id`, `ip_warning`, `qr_svg`, `capture_url`, `other_ips`, `live_pairing`, `model_state`, `thresholds`, `sink_pending`, `sink_dead`, `connectivity_code`, `connectivity`, `last_success_at`, `live_latency`, `dataset_dir`, `rows` e `coverage`). Só `sink_pending` e `sink_dead` passam a ser usados duas vezes; o `string.Template` aceita isso. Os dois valores são sempre inteiros (`str(stats.pending)` e `str(stats.dead)`), então podem ir num atributo sem escape novo.
- **Ordem:** `$live_pairing` continua dentro do mesmo contêiner de `<div class="qr">$qr_svg</div>`. Com o TLS ligado, os dois QRs ficam lado a lado no cartão de pareamento e quebram linha se faltar largura. Nos `<dd>` com `id`, o `id` é o **último** atributo antes de `>` (exceto em `sink-connectivity`, que fica igual): os unitários usam regex como `id="sink-pending">12<`.

### 4.2 Regras do CSS e do template

1. **Nada externo, nada de JS.** O arquivo não contém `http://`, `https://`, `<script`, `<link`, `<img`, `<iframe`, `<object`, `<embed`, `@import`, `@font-face` nem `url(`. A borda roda sem internet na apresentação (hotspot) e a R-01 vale.
2. **Fontes:** em todo `font-family`, só famílias genéricas: `system-ui`, `ui-sans-serif`, `sans-serif`, `ui-monospace` e `monospace`. Nenhum nome de fonte de fabricante (R-13: nenhuma empresa citada no repositório). O atalho `font:` não é usado; a família vai sempre em `font-family`, que é o que o CA-04 confere.
3. **Legível no projetor:**
   - a regra com o seletor exato `body` declara `font-size` de pelo menos `18px` ou `1.125rem`;
   - o `h1` fica maior que o corpo;
   - a largura do conteúdo é limitada, por exemplo `max-width: 1200px` e centralizado.
4. **QR code:**
   - a regra `.qr svg` continua com largura e altura de pelo menos `260px` e fundo branco (`#fff`, `#ffffff` ou `white`), com uma margem branca em volta (`padding` no `.qr`);
   - nenhum `filter`, `opacity`, `transform` ou `mix-blend-mode` em `.qr` ou no SVG, para a leitura do celular não piorar.
5. **Indicadores de cor** (cores na §4.3):
   - **Conectividade** como selo (`badge`): `online` verde, `offline` e `auth_error` vermelho, `disabled` cinza. Os seletores usam o valor **sem aspas**, `[data-connectivity=online]`, `[data-connectivity=offline]` e `[data-connectivity=disabled]`, e o **prefixo** `[data-connectivity^=auth]` para `auth_error`. Assim, o arquivo não contém `data-connectivity="` fora do próprio `<dd>` nem o texto `auth_error`, e os testes antigos que procuram esses trechos continuam conferindo o valor renderizado (§1).
   - **Pendentes e com falha definitiva** em destaque: o número aparece como selo. `Pendentes` diferente de 0 fica âmbar, `Com falha definitiva` diferente de 0 fica vermelho, e o valor 0 fica neutro ou verde. Os seletores usam `[data-count="0"]`, por exemplo `#sink-pending:not([data-count="0"])`.
   - **Avisos:** `.warning` vira uma caixa âmbar com borda. O seletor é sempre a classe, nunca o `id` do aviso.
   - **Cobertura:** a regra `tr.complete` continua com fundo verde, porque o texto da página diz "Em verde, as células que atingiram as duas metas" (SPEC-010).
6. **Tabelas:** cabeçalho com fundo, linhas zebradas (`tbody tr:nth-child(even)`, sem anular o verde de `tr.complete`), `border-collapse: collapse` e números alinhados à direita, se o developer quiser. A tabela de cobertura fica no último cartão, sem rolagem interna.
7. **Proibido, por causa da recarga de 5 s:**
   - `animation`, `transition` e `@keyframes`, que repetiriam a cada recarga e fariam a tela piscar;
   - `<details>`, que fecharia sozinho a cada recarga;
   - rolagem interna (`overflow: auto` ou `scroll` com altura fixa), cuja posição se perde.
8. **Tema claro só.** Sem `prefers-color-scheme`: o QR precisa de fundo branco, e um projetor mostra melhor texto escuro sobre fundo claro.
9. **Textos que o arquivo nunca contém,** nem em seletor nem em comentário:
   - `loopback-warning`, `no-lan-warning` e `coverage-warning`;
   - `Outros IPs`, `nenhum ip` (em qualquer caixa), `PROVISÓRIO`, `provisório` e `p95`;
   - `/live?`, `capture?t=` e `auth_error`;
   - `<svg` e `L-0`.

   Testes antigos afirmam a ausência deles, ou a presença deles como prova de um estado (§1). Além disso, `class="qr"` aparece **exatamente uma vez** no arquivo, e `data-connectivity="` também exatamente uma vez.
10. **Cifrão:** o único `$` do arquivo é o dos placeholders da §4.1. Um `$` solto faz o `substitute` levantar `ValueError` em toda requisição (500 no console). O `$$` funciona, mas não é necessário.

### 4.3 Paleta (texto escuro sobre fundo claro)

As razões de contraste foram calculadas pela fórmula de luminância relativa do WCAG 2.2. O critério 1.4.3 (nível AA) pede pelo menos 4,5:1 para texto normal (<https://www.w3.org/TR/WCAG22/#contrast-minimum>, consultado em 2026-11-17). O developer pode trocar uma cor por outra com contraste de pelo menos 4,5:1 com o seu par. A exceção é o fundo `#d7f2dd` de `tr.complete`, que é o atual e fica (CA-04).

| Uso | Fundo | Texto | Contraste aproximado |
|---|---|---|---|
| Página | `#f3f5f8` | `#1b1b1b` | 15:1 |
| Cartão | `#ffffff` (borda `#d9dee5`, sombra leve opcional) | `#1b1b1b` | 17:1 |
| Cabeçalho (`.topbar`) | `#1f3a5f` | `#ffffff` | 11:1 |
| Rótulo (`dt`) e texto secundário | `#ffffff` | `#555555` | 7,4:1 |
| Selo verde (`online`, contagem 0, `tr.complete`) | `#d7f2dd` | `#0b5d1e` | 6,8:1 |
| Selo vermelho (`offline`, `auth_error`, falha definitiva diferente de 0) | `#fde2e1` | `#8a1c13` | 7,6:1 |
| Selo âmbar (pendentes diferente de 0) e `.warning` (borda `#e0b000`) | `#fff3cd` | `#6b4e00` | 7,0:1 |
| Selo cinza (`disabled`) | `#e9ecef` | `#343a40` | 9,7:1 |

## 5. Critérios de aceite

A configuração comum a todos os CAs automatizados é:

- borda criada com `create_app` e o stub (`model_version` `stub-v0`);
- `EDGE_PORT=8000` e `EDGE_HOST=0.0.0.0`;
- detecção de IPs da LAN substituída por `["192.168.0.42", "10.0.0.7"]`, a fronteira de rede (`qc_edge.netinfo`);
- console pedido de `("127.0.0.1", 50000)`, com a URL base `http://127.0.0.1:8000`, salvo indicação em contrário;
- `T` é o token de sessão da borda.

- **CA-01** — *Dado* o arquivo `edge/src/qc_edge/templates/console.html`, *quando* lido como texto UTF-8, *então*:
  - não contém, sem diferenciar maiúsculas, nenhum destes trechos: `http://`, `https://`, `<script`, `<link`, `<img`, `<iframe`, `<object`, `<embed`, `@import`, `@font-face` e `url(`;
  - contém exatamente 1 `<style` e 1 `</style>`;
  - não contém `<details`, `animation`, `transition`, `@keyframes`, `prefers-color-scheme` nem `filter`.
- **CA-02** — *Dado* o mesmo arquivo, *quando* carregado em `string.Template`, *então* `is_valid()` é `True`, e `get_identifiers()` devolve exatamente o conjunto dos 17 nomes da §4.1.
- **CA-03** — *Dado* o mesmo arquivo, *quando* lido como texto, *então*:
  - não contém nenhum dos textos da §4.2, item 9, e `nenhum ip` é conferido sem diferenciar maiúsculas;
  - `class="qr"` aparece exatamente 1 vez;
  - `data-connectivity="` aparece exatamente 1 vez.
- **CA-04** — *Dado* o `<style>` do arquivo, *quando* analisado por regex, *então*:
  - a regra cujo seletor é exatamente `body` declara `font-size` de pelo menos `18px` ou `1.125rem`;
  - todo valor de `font-family` tem só tokens do conjunto `{system-ui, ui-sans-serif, sans-serif, ui-monospace, monospace}`, separados por vírgula;
  - a regra `.qr svg` declara `width` e `height` de pelo menos `260px` e `background` `#fff`, `#ffffff` ou `white`;
  - há uma regra com `tr.complete` e `background` `#d7f2dd`;
  - aparecem os seletores `[data-connectivity=online]`, `[data-connectivity=offline]`, `[data-connectivity^=auth]`, `[data-connectivity=disabled]` e `[data-count="0"]`.
- **CA-05** — *Dado* a configuração comum, *quando* `GET /`, *então*:
  - o status é 200;
  - a página contém, cada um pelo menos 1 vez:
    - `<html lang="pt-BR">`, `<meta http-equiv="refresh" content="5">`, `<meta name="viewport" content="width=device-width, initial-scale=1">` e `<title>PartQC — console da borda</title>`;
    - `PartQC — console da borda (<span>` e `<h2>Pareamento</h2>`;
    - `Leia o QR code com o celular na mesma rede ou abra:`;
    - `<h2>Estado</h2>`, `<h2>Últimas inspeções desta sessão</h2>` e `<h2>Cobertura do dataset</h2>`;
    - `<dt>Modelo</dt>`, `<dt>Limiares de decisão</dt>`, `<dt>Pendentes</dt>`, `<dt>Com falha definitiva</dt>`, `<dt>Conectividade com a nuvem</dt>`, `<dt>Último envio</dt>`, `<dt>Latência por quadro (vídeo ao vivo)</dt>` e `<dt>Dataset (modo coleta)</dt>`;
    - `<thead><tr><th>Hora</th><th>Lote</th><th>Tipo</th><th>Grau</th></tr></thead>`;
    - `<table id="coverage">`, `<p id="external-images">` e `A página atualiza sozinha a cada 5 s.`;
  - a página contém exatamente 1 `<style` e nenhum `<script`, `<link`, `<img`, `<iframe` ou `@import`.
- **CA-06** — *Dado* a configuração comum e 12 capturas no modo inspeção com os lotes `L-000` a `L-011`, num sink em memória, *quando* `GET /`, *então*:
  - a página contém `<dd data-count="12" id="sink-pending">12</dd>` e `<dd data-count="0" id="sink-dead">0</dd>`;
  - casa com `id="model-thresholds">—<` e contém `carregado: stub-v0 (sha256 000000000000)`;
  - tem exatamente 10 `<tr class="inspection"`, cujos lotes, na ordem da página, são `L-011` a `L-002`.
- **CA-07** — *Dado* a configuração comum e um sink de teste cujo `stats()` devolve `pending=3`, `dead=2` e `connectivity` igual a cada um de `online`, `offline`, `auth_error` e `disabled` (parametrizado), *quando* `GET /`, *então*:
  - a página contém `<dd id="sink-connectivity" data-connectivity="{código}">{rótulo}</dd>`, com os rótulos `online`, `offline`, `erro de autenticação (envio pausado: confira o DEVICE_API_KEY e reinicie o qc-edge)` e `desativada (nada é enviado à nuvem)`, respectivamente;
  - `data-connectivity="` aparece exatamente 1 vez;
  - a página contém `<dd data-count="3" id="sink-pending">3</dd>` e `<dd data-count="2" id="sink-dead">2</dd>`;
  - fora do caso `auth_error`, a página não contém `auth_error`.
- **CA-08** — QR codes, com e sem TLS:
  - *Dado* a configuração comum sem TLS, *quando* `GET /`, *então* a página contém `<svg` exatamente 1 vez e `class="qr"` exatamente 1 vez, contém `http://192.168.0.42:8000/capture?t=T` e não contém `/live?`.
  - *Dado* o TLS ligado (`EDGE_TLS_CERT` e `EDGE_TLS_KEY` válidos, URL base `https://127.0.0.1:8000`), *quando* `GET /`, *então* `<svg` e `class="qr"` aparecem exatamente 2 vezes cada, e a página contém `id="live-qr"`, `https://192.168.0.42:8000/capture?t=T` e `https://192.168.0.42:8000/live?t=T`.
- **CA-09** — *Dado* os dois cenários do CA-08, *quando* se removem da página todas as ocorrências de `capture?t=T` e, com TLS, também as de `live?t=T`, *então* o texto restante não contém `T` (R-03).
- **CA-10 (erro e entradas externas)** — *Dado* a configuração comum, *quando* `GET /`:
  1. de um cliente da LAN `("192.168.0.50", 50000)`, com a URL base `http://192.168.0.42:8000`;
  2. de loopback com `Host: attacker.example:8000`;
  3. de loopback com `X-Forwarded-For: 203.0.113.9`;

  *então*, nos três casos:
  - o status é 403;
  - o corpo contém `O console só abre no próprio notebook (http://127.0.0.1).` e não contém `T` nem `<style`;
  - os headers `cache-control`, `referrer-policy` e `x-content-type-options` valem `no-store`, `no-referrer` e `nosniff`.

  E *quando* `GET /?ip=<script>alert(1)</script>` de loopback, *então* o status é 200 e a página não contém `<script`. Na resposta 200 do CA-05, os mesmos 3 headers têm os mesmos valores, e não há `content-security-policy` nem `set-cookie`.
- **CA-11 (manual)** — O humano confere o visual no notebook, de preferência ligado ao projetor ou à TV:
  1. sobe a borda com o modelo da demo (`uv run --env-file .env --package qc-edge qc-edge`) e abre `http://127.0.0.1:8000/` no navegador do notebook, com zoom de 100%;
  2. confere o cabeçalho com `PartQC — console da borda (<device_id>)`, o cartão **Pareamento** com o QR e a URL, e o cartão **Estado** com os selos de conectividade e de pendentes;
  3. com uma janela de 1280 px de largura ou mais, confere que não há barra de rolagem horizontal e que o QR e o cartão **Estado** aparecem sem rolar a página;
  4. lê o QR com o celular e abre `/capture`;
  5. faz 1 inspeção e, em até 5 s, vê a linha nova em **Últimas inspeções desta sessão**; o selo de pendentes muda conforme o envio;
  6. a 3 m da tela (ou do fundo da sala, no projetor), lê os rótulos e os números do cartão **Estado**;
  7. a página recarrega a cada 5 s sem piscar nem mudar de lugar.

  Resultado registrado pelo orquestrador no PR e no test-report como "CA-11 confirmado pelo humano em <data>", ou com o problema visto. Um problema visual pequeno, como cor ou espaçamento, entra na mesma rodada; não exige SPEC nova se respeitar a §4.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor), opcional | Regras da §4.2 no template | `edge/tests/` (por exemplo, `test_console_template.py`) |
| Aceite (tester) | Um teste por CA, do CA-01 ao CA-10. O CA-07 é parametrizado pelos 4 estados | `edge/tests/acceptance/test_spec_047.py` |
| Aceites antigos | A lista da §3.1 passa sem alteração (o CI roda a suíte inteira) | — |
| Manual (humano) | CA-11 | descrito no CA-11 |

- **Mocks:** só a detecção de IPs da LAN (`qc_edge.netinfo`) e o sink (`stats()` controlado). Inferência pelo stub, como nos aceites das SPECs 007 e 043.
- **TLS (CA-08):** use o mesmo par certificado e chave de teste dos aceites da SPEC-019. Sem rede nem banco.
- **Leitura do template (CA-01 a CA-04):** caminho `qc_edge.app.TEMPLATES_DIR / "console.html"`, para não depender do diretório de trabalho.

## 7. Riscos e notas para o implementador

### 7.1 Merge no dia da apresentação (decisão humana)

O `docs/deployment-plan.md` §5 e o passo 7A (SPEC-039 §4.8) dizem: "nenhum merge na `main` na véspera nem no dia [da apresentação], porque cada merge dispara um deploy". O registro do CA-18 da SPEC-039 (2026-11-02) diz que o webhook **não** foi configurado, porque o deploy é pelo botão. Esta SPEC só muda `edge/`, que roda no notebook, e não a API nem o dashboard da VPS. Mesmo assim, a regra do plano é incondicional, e só o humano pode abrir uma exceção (§9, pergunta 1). Até essa resposta, o orquestrador não mergeia esta SPEC em 17/11.

### 7.2 Notas para o developer

- **Só `console.html` muda em `edge/src/`.** Um diff em qualquer `.py` de produção é motivo de `CHANGES_REQUESTED`. O reviewer confere com `git diff --stat main...HEAD -- edge/src`.
- **Recarga de 5 s:** é por isso que não há animação, `<details>` nem rolagem interna (§4.2, item 7). Teste no navegador por alguns ciclos.
- **Selo com o texto longo de `auth_error`:** o rótulo tem cerca de 90 caracteres. O selo precisa quebrar linha (`white-space: normal`) e não pode estourar o cartão.
- **URLs longas** (`.url`: URL de pareamento, `live-url` e caminho do dataset) continuam com `word-break: break-all` e fonte monoespaçada genérica.
- **Fragmentos que vêm do `app.py`** (avisos `.warning`, `<ul class="thresholds">`, segundo QR, parágrafo de metas, `<table id="coverage">` e `<p id="external-images">`) só podem ser estilizados por classe ou elemento, sem mexer no Python.
- **Tempo:** a mudança é pequena e o prazo é hoje. Se algo da §4 parecer impedir o visual pedido, registre `SPEC_ISSUE` em vez de contornar.

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS), e os aceites antigos da §3.1 passando sem alteração
- [ ] CA-11 (manual) confirmado pelo humano e registrado no PR
- [ ] review-report APPROVED (sem portão de segurança: SPEC sem as tags `security` e `deploy`, salvo decisão contrária na §9)
- [ ] CI verde; `ruff` limpo
- [ ] Só `edge/src/qc_edge/templates/console.html` alterado em `edge/src/`
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016) e a §7.1

## 9. Perguntas ao humano

1. **Merge hoje (§7.1).** O `docs/deployment-plan.md` §5 proíbe merge na `main` no dia da apresentação. Recomendação:
   - se o webhook do Coolify continua desligado (deploy só pelo botão, como registrado em 2026-11-02), autorizar por escrito uma exceção só para esta SPEC: o merge não publica nada na VPS, ninguém clica em **Deploy**, e o notebook faz `git pull` antes da apresentação;
   - se o webhook foi ligado depois, não mergear hoje: com PASS e APPROVED, rodar a borda na apresentação a partir da branch `spec/SPEC-047-console-visual` e mergear depois.
2. **Portão de segurança.** Recomendação: sem a tag `security`. Nada de rota, header, token, entrada ou dado muda, e os CAs 09 e 10 conferem o token, o 403 e os headers. Com a tag, a SPEC ganha a rodada do security-devops, que é mais segura e mais lenta.
3. **Textos novos.** Recomendação: manter só os dois da §4.1 (`Pareamento` e a nota da recarga de 5 s). Se o humano quiser um subtítulo, por exemplo "Inspeção visual de qualidade", basta incluí-lo na lista da §4.1 ao aprovar.

## Histórico

- 2026-11-17: SPEC criada pelo architect, a pedido do humano (Carlos), para melhorar o visual do console antes da apresentação da noite. Status `Draft`, aguardando aprovação humana.
| 2026-11-17 | Aprovada pelo humano (`Ready`): "Aprovar" (sem a tag `security`, só os dois textos novos da §4.1, numeração 047 com a 046 reservada); exceção ao §5 do deployment-plan: "Autorizo o merge" hoje, sem Deploy no Coolify (webhook não configurado), com `git pull` no notebook antes da apresentação | Pedido do humano | Humano |
