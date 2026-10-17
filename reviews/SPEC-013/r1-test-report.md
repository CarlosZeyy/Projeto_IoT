# SPEC-013 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `0d87266` |
| **Veredicto** | **PASS** |

O veredicto é PASS porque os 30 CAs automatizáveis têm teste e passam, a suíte inteira passa com e sem banco e o ruff está limpo. O CA-26 é manual e fica pendente para a dupla. Executei localmente os passos 1 a 4 e parte do 5 (abaixo). Encontrei dois bugs. Nenhum deles viola um CA, então nenhum muda o veredicto, mas os dois violam a §4.7: o T-01 (baixa) e o T-02 (média). Recomendo corrigir o T-02 antes do merge.

Arquivo de aceite: `dashboard/tests/acceptance/test_spec_013.py`, com 33 funções `test_caNN_*`, 38 `test_extra_*` e 1 `test_bug_t02_*` (`xfail`). São **103 casos** depois da parametrização: 99 passam sem banco, 1 é `db` e passa com o banco, e os 3 casos de `xfail` documentam o T-02. Escrevi os testes a partir da SPEC, antes de ler a implementação. Depois de ler o código, só mudei o CA-21 (um defeito do meu teste, explicado no fim da cobertura) e acrescentei testes exploratórios.

Como os testes funcionam:

- as páginas rodam por `streamlit.testing.v1.AppTest.from_file` em cada arquivo de `dashboard/views/` (e em `app.py` no CA-05);
- `api.get_client` é trocado por um `ApiClient` real sobre `httpx.MockTransport`, com corpos montados pelos modelos de `qc_contracts` 0.3.0 e registro de cada requisição;
- as chaves são geradas em tempo de execução, e nenhuma chave aparece como literal em URL, conninfo ou header;
- nenhum teste usa a internet nem roda o pytest em subprocesso;
- usei um fixture próprio (`FakeApi`), não o `mock_api` do autor. Do `conftest.py` do autor só valem o autouse que limpa os caches e o meu fixture, que limpa de novo.

## Cobertura dos critérios de aceite

Prefixo dos testes: `dashboard/tests/acceptance/test_spec_013.py::`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_summary_request_url_header_and_model`: URL exata `https://api.test/api/v1/metrics/summary?source=live`, `GET`, `X-API-Key` e retorno `MetricsSummary` | ✅ |
| CA-02 | `test_ca02_timeout_and_503_are_unavailable[read-timeout\|503]`: os 6 métodos levantam `ApiUnavailable`. `test_ca02_client_timeout_is_ten_seconds`: o timeout que o httpx aplica à requisição é 10,0 s (connect/read/write/pool) | ✅ |
| CA-03 | `test_ca03_auth_server_error_and_invalid_body`: 401 → `ApiAuthError`; 500 → `ApiError` com `status == 500`; 200 `{"foo": 1}` → `ApiError`, e nenhum dos dois `ApiError` é subclasse de auth ou unavailable | ✅ |
| CA-04 | `test_ca04_key_never_in_logs_or_exceptions`: `caplog` em DEBUG na raiz; a chave não aparece nos registros, nos `args`, em `str`/`repr`, na cadeia formatada da exceção nem no `repr` do cliente | ✅ |
| CA-05 | `test_ca05_missing_configuration`: `AppTest.from_file("dashboard/app.py")` com `cwd` e `HOME` sem `secrets.toml` e `httpx.HTTPTransport.handle_request` interceptado; resultado: um único `st.error` exato, nenhuma requisição, nenhuma exceção, nenhum gráfico | ✅ |
| CA-06 | `test_ca06_new_session_defaults_to_live_without_badge` | ✅ |
| CA-07 | `test_ca07_all_sources_badge_depends_on_simulated_total`: com `total=12`, aparece o selo, e a checagem usa os mesmos filtros da página, só com `source=simulated`; com `total=0`, não aparece | ✅ |
| CA-08 | `test_ca08_simulated_sidebar_on_every_api_page[visao_geral\|controle_estatistico\|historico]` | ✅ |
| CA-09 | `test_ca09_kpis`: rótulos e valores `40`, `12,5%`, `3`, `4` e `1,85`, na ordem | ✅ |
| CA-10 | `test_ca10_grade_distribution_order_values_and_colors` | ✅ |
| CA-11 | `test_ca11_day_bucket_request_and_traces` | ✅ |
| CA-12 | `test_ca12_empty_overview` | ✅ |
| CA-13 | `test_ca13_timeout_shows_waking_and_retry_recovers[3 páginas de API]`: aviso exato e botão; `at.exception` vazio; **1 requisição por renderização** (sem laço); depois do clique com a API de volta, os dados aparecem. `test_ca13_model_page_badge_check_timeout`: "Sobre o modelo" com `Todos` (ver a nota 4 em "Avaliação das decisões do autor") | ✅ |
| CA-14 | `test_ca14_p_chart_figure`: LSC e LIC diferentes por lote (n diferentes), para que a checagem de y não seja trivial | ✅ |
| CA-15 | `test_ca15_default_controls_request`: os parâmetros são **exatamente** `{source, baseline_lots, min_lot_size, max_points}`; com `porca`, entra `object_type=nut` e continuam ausentes `from`/`to` | ✅ |
| CA-16 | `test_ca16_insufficient_data`: texto exato; nenhum gráfico; a `message` da API, em inglês, não aparece | ✅ |
| CA-17 | `test_ca17_excluded_lots_and_table`: colunas exatas, 4 linhas, `Sim` só em `L-003` | ✅ |
| CA-18 | `test_ca18_pagination_and_columns` | ✅ |
| CA-19 | `test_ca19_unknown_simulated_row` | ✅ |
| CA-20 | `test_ca20_history_csv`: o CSV é lido com `csv.reader`; a 2ª linha tem `Grau` vazio, nenhum `—` e a data com troca de dia (`2026-11-04T02:30Z` → `2026-11-03T23:30:00-03:00`) | ✅ |
| CA-21 | `test_ca21_invalid_lot_is_ignored[3 páginas de API]` | ✅ |
| CA-22 | `test_ca22_fetch_summary_cache` | ✅ |
| CA-23 | `test_ca23_metrics_against_targets`: `metrics.json` montado por mim com as 32 chaves da SPEC-012 §4.7 | ✅ |
| CA-24 | `test_ca24_missing_and_invalid_metrics`: texto exato com o caminho; `{"x": 1}` → `metrics.json inválido`, sem traceback | ✅ |
| CA-25 | `test_ca25_no_ml_or_database_dependencies`: roda `uv export --package qc-dashboard --frozen --no-hashes` (que não é pytest) e o `grep -rIE` exato do CA (código 1, saída vazia) | ✅ |
| CA-26 (manual) | Pendente para a dupla (o passo 5 exige um celular). Executei localmente os passos 1 a 4 e simulei o 5 em 400 px; ver a seção própria. Automatizei os passos 1 a 4 em `test_extra_real_api_end_to_end` (`db`) | ⏳ manual |
| CA-27 | `test_ca27_cut_chart_notices` (caption exato, inclusive a frase da linha central; o `info` termina com `" e mais 10 lote(s) excluído(s) mais antigo(s)."`) e `test_ca27_no_cut_notices[equal\|null]` | ✅ |
| CA-28 | `test_ca28_origin_caption_always_visible[visao_geral\|historico]` | ✅ |
| CA-29 | `test_ca29_one_chart_one_origin`: 1 requisição SPC com `simulated` naquela renderização, 1 figura, título exato, caption do período e selo | ✅ |
| CA-30 | `test_ca30_spc_cached_between_renders` | ✅ |
| CA-31 | `test_ca31_max_points_control`: padrão 100; `has_min`/`min` = 2 e `has_max`/`max` = 500 no proto do widget; 10 é enviado; 1 e 501 nunca chegam à API | ✅ |

Ajuste no CA-21 depois de ler o código: na 1ª versão, eu mudava o lote para `L 01` depois de uma renderização e exigia requisições novas. Como o filtro inválido é ignorado, as leituras são idênticas às anteriores e vêm do cache (o comportamento correto, pelo CA-22). O teste agora limpa o cache antes da renderização com o lote inválido, e assim prova que as requisições feitas não levam `lot_id`. O erro era do teste, não da implementação.

## Suíte completa

```text
Sem banco (env -u TEST_DATABASE_URL uv run pytest -q):
2163 passed, 546 skipped, 3 xfailed, 1 warning in 222.98s

Com banco (TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q):
2709 passed, 3 xfailed, 1 warning in 378.05s
(o único aviso é o StarletteDeprecationWarning do fastapi.testclient, anterior a esta SPEC)

Só dashboard/tests, com banco e --cov=qc_dashboard (antes do T-02 ser adicionado): 228 passed
  api.py 100% | charts.py 100% | config.py 100% | data.py 92% | filters.py 99%
  formatting.py 99% | model_info.py 100% | TOTAL 99%

uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 134 files already formatted
```

O autor relatou 2064 passed e 545 skipped sem banco, e 2609 passed com banco. A diferença são os meus 103 casos: +99 passed, +1 skipped (o `db`) e +3 xfailed sem banco; +100 passed e +3 xfailed com banco.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-02 | média | §4.7 (eixos em PT-BR; datas `dd/mm/aaaa HH:MM` na interface). Nenhum CA | 1. Na Visão geral, com dados, ver o gráfico "Volume e taxa de defeito" (qualquer granularidade). 2. Ou: `charts.volume_and_defect_rate(points, "hour")` e olhar o eixo x | Datas do eixo (e do hover) em PT-BR, por exemplo `16/10/2026 21:00` | O Plotly usa o formato padrão em inglês: os ticks saem como `Oct 16, 2026` / `Oct 17, 2026` (visto na captura em 400 px). Causa: `volume_and_defect_rate` passa `datetime`/`date` em x sem `tickformat` (nem `hoverformat`) no eixo x, e o `hovertemplate` usa `%{x}` cru. Teste que reproduz: `test_bug_t02_series_date_axis_in_pt_br[minute\|hour\|day]` (`xfail(strict=False)`, falha no assert; vira XPASS quando for corrigido) |
| T-01 | baixa | §4.7 (legibilidade) e passo 5 do CA-26. Nenhum CA | 1. Subir a API e o dashboard com dados (ver CA-26 abaixo). 2. Abrir "Controle estatístico" em 1280 px e em 400 px. 3. Abrir a Visão geral em 400 px | O título da figura `Carta p — origem: real` legível, sem sobreposição | A legenda horizontal (`legend y=1.02`, em `charts._base_layout`) fica sobre o título: no desktop, `p do lote` cobre parte de `origem: real`; em 400 px, a legenda quebra em 3 linhas e cobre o título da carta p e o do gráfico "Volume e taxa de defeito por hora (hora local)". O título é o lugar da figura que diz a origem (R-06). A origem continua visível no rádio "Origem da carta" e no selo, por isso a severidade é baixa. Só visual: não automatizei |

## Testes exploratórios (além dos critérios)

### Versionados (`test_extra_*`, todos passam)

- **Chave de leitura (R-03):**
  - nunca aparece no conteúdo das 3 páginas de API (todos os protos de `main` e `sidebar`) nem no log, inclusive no caminho do 401;
  - com um **socket local real** (`http.server` em 127.0.0.1, sem internet) e os loggers do httpx e do httpcore em DEBUG, a chave não aparece nos logs nem na exceção (`test_extra_key_not_logged_by_the_real_http_stack`). O CA-04 com `MockTransport` não exercita o httpcore;
  - `Settings` não mostra a chave no `repr`.
- **Erros sem stack trace:**
  - 500 e 422 → `Erro da API (HTTP <status>).`; 403 → mensagem da chave;
  - 502, 503 e 504 (corpo HTML) → "API acordando", sem o corpo na tela;
  - `ConnectError` → `ApiUnavailable`; 200 com corpo que não é JSON → `ApiError`;
  - em todos os casos, 1 requisição por renderização.
- **Repetição sem laço:**
  - erro não é cacheado: depois de um timeout, a chamada seguinte vai à API;
  - clicar em "Tentar novamente" com a API ainda fora gera no máximo 2 tentativas (a reexecução do clique e o `st.rerun()` depois de limpar o cache) e para. A renderização seguinte faz 1.
- **TTL de 30 s:** com o relógio do cache do Streamlit (`cache_utils.TTLCACHE_TIMER`) trocado por um relógio falso, 29 s depois ainda é cache, e 31 s depois sai uma requisição nova (`test_extra_cache_expires_after_30_seconds`).
- **Período:**
  - o padrão é hoje − 6 … hoje (7 dias locais), com `from` e `to` à 00:00 de São Paulo convertidas para UTC;
  - uma data só vira um intervalo de 1 dia (script);
  - na página da carta, mudar o período não gera requisição nova ao SPC (os parâmetros da carta não mudam).
- **Lote:**
  - `Lóte`, 41 caracteres, `L/01`, `L 01`, `L-01;DROP` e dígitos arábicos → `Lote inválido`, sem `lot_id`;
  - `L_01-a` é enviado;
  - espaços e `\n` em volta são removidos antes da regex, e só `L-01` limpo sai (ver a observação O-04).
- **Carta p:**
  - os controles não oferecem `Todos` na origem nem `desconhecido` no tipo;
  - as faixas são `baseline_lots` 2–100 (padrão 20) e `min_lot_size` 1–500 (padrão 5);
  - com a barra lateral em `Todos`, o SPC continua com `live` ou `simulated` e 1 figura;
  - uma resposta 0.2.0 (sem `max_points`, `valid_lots_total` e `excluded_lots_total`) desenha a carta sem nenhum aviso de corte;
  - sem pontos fora de controle, não há anotação;
  - losango de tamanho 12, LSC e LIC tracejados, eixos em PT-BR e eixo y em %.
- **Visão geral:**
  - `mean_grade_score` e `defect_rate` nulos → `—`; a ajuda é "0 = perfeito … 4 = inutilizável";
  - `Minuto` → `minute`; o padrão é `Hora`;
  - barras horizontais por tipo; `bucket=day` com `(UTC)` no título.
- **Histórico:**
  - Grau `ruim` → `grade=poor`, com o `offset` de volta a 0;
  - `Sim` → `defective=true`;
  - 25 por página → `limit=25` e `offset=0`;
  - dispositivo `edge-02` é enviado; página vazia mostra a mensagem;
  - o botão de download tem o rótulo exato;
  - por script: `Anterior` volta pelo cache; na última página, `Próxima` fica desabilitada; um dispositivo inválido mostra `Dispositivo inválido` e não é enviado.
- **Persistência entre páginas:** em `app.py` com `switch_page`, `Simulado` escolhido na Visão geral vale no Histórico: as requisições saem com `simulated` e o selo aparece.
- **Sobre o modelo:**
  - cabeçalho com a versão, o sha de 12 caracteres, a data local (`20/11/2026 10:30`) e o split;
  - legenda fixa da R-11 e lista de avisos;
  - 4 casas sem arredondar para cima, sem artefato de float: `0.95999` → `0,9599`, `0.70` → `0,7000`, `0.29` → `0,2900`, `0.57` → `0,5700`, `0.30000000000000004` → `0,3000`, `0.12345` → `0,1234`;
  - limites `0.95 ≥ 0.95` e `300 ≤ 300` → `Atingida`; `null` → `—`;
  - JSON malformado, `[]`, documento parcial e falta de `n_items_test_by_grade` → `metrics.json inválido`;
  - `model_version="../../etc"` não monta caminho de imagem.
- **R-12:** importar os 7 módulos de `qc_dashboard` num processo novo não carrega `torch`, `onnxruntime`, `timm`, `psycopg`, `qc_ml` nem `supabase`.
- **Rótulos:** os rótulos de grau vêm de `qc_contracts.GRADE_LABELS_PT`; os títulos da navegação têm acento; `page_title="PartQC"`, `layout="wide"`; a página padrão é a Visão geral.
- **API real em processo** (`test_extra_real_api_end_to_end`, `db`). O `create_app` da `qc-api` roda sobre o Postgres de teste. Uso o `clean_db`, não o `migrated_db` diretamente, e o `TestClient` fica atrás do `MockTransport`. São 6 lotes `live` pelo `POST /inspections/batch` (`L-005` com 9 de 10 defeituosas) e 3 lotes `simulated`. Resultado:
  - KPIs 60 (`Real`) e 90 (`Todos`, com selo);
  - selo em Controle, Histórico e Sobre o modelo com `Todos`;
  - carta `live` com `L-001`…`L-006` e só `L-005` vermelho e anotado;
  - carta `simulated` só com `S-001`…`S-003`;
  - Histórico com 50 linhas `real` e `Página 1 de 2 — 60 inspeções`;
  - a chave não aparece na página.

### Por script no scratchpad (fora do Git)

- Barra lateral em `Simulado` e a origem da carta mudada para `Real`: a figura é `Carta p — origem: real`, mas o selo `Contém dados simulados` aparece. Com a barra lateral em `Todos` e dados simulados no período, a carta `Real` também mostra o selo e custa 1 `summary` a mais. Ver O-01.
- Ao mudar a origem da barra lateral com a página da carta aberta, o Streamlit registra no log do servidor, uma vez por processo e com stack: `The widget with key "spc_source" was created with a default value but also had its value set via the Session State API.` Ver O-02.
- `max_points` de 1, 501, 0 e −5 é limitado à faixa: nenhuma exceção, e a API nunca recebe o valor.
- Timeout só na série temporal, com o resumo OK: os KPIs e os 2 gráficos aparecem, e o aviso de "API acordando" e o botão ficam no lugar da série.

### Avaliação das decisões do autor (pedido do orquestrador)

1. **A origem da carta acompanha a barra lateral** (decisão 2). Com essa leitura, o CA-08 (`Simulado` na barra lateral → SPC com `simulated`), o CA-15 (padrão `Real`) e o CA-29 (1 requisição, 1 figura) são todos atendidos, e `Todos` nunca chega à carta. Não encontrei CA que ela quebre. A §4.4 ("`Real` (padrão)") e o CA-08 só se conciliam assim, ou com outra regra que o architect escreva. Por isso registro a decisão como observação para o reviewer e o architect, não como `SPEC_ISSUE`. O efeito colateral está na O-01.
2. **O selo em "Sobre o modelo"** (decisão 3) segue a letra da §4.2 ("cada página") e do CA-26 ("em todas as páginas"). Com `Todos`, custa 1 `summary` cacheado. Com o timeout dessa checagem, a página mostra o aviso de "API acordando", o que dá sentido ao "qualquer página" do CA-13 nela. Com `Real` ou `Simulado`, ela não chama a API, então não há aviso a mostrar. Considero o CA-13 atendido nas páginas que leem a API.
3. **Corte na 4ª casa** (decisão 9). `ROUND_FLOOR` sobre `Decimal(repr(x))` é a leitura literal de "sem arredondar para cima", e o `repr` evita o artefato binário (`0.70` → `0,7000`, não `0,6999`). Ao comparar, o status usa o valor bruto, o que é coerente com o valor exibido. A divergência com o CHANGELOG da SPEC-012 (CA-25 dela arredonda `0.93127` para `0,9313`, e o painel mostra `0,9312`) é real, mas é entre SPECs. Fica para o architect e não falha nenhum CA desta.

### Observações (não bloqueiam; para o reviewer, o security-devops e o architect)

- **O-01 (baixa, R-06 no sentido conservador):** na página da carta, o selo é decidido pela barra lateral **ou** pela origem da carta. Logo, uma carta só `live` pode aparecer com "Contém dados simulados" (barra lateral em `Simulado`, ou em `Todos` com dados simulados no período, que não se aplica à carta). Não é o erro que a R-06 proíbe (simulado passando por real), mas o aviso não descreve a figura. Segue a letra da §4.2 e da §4.4. Sugestão ao architect: na página da carta, o selo segue só a origem da carta.
- **O-02 (baixa):** o aviso de log do Streamlit acima, causado por `_sync_origin_with_sidebar`, que escreve em `st.session_state["spc_source"]` e cria o rádio com `index`. Não aparece na tela.
- **O-03 (baixa, para o security-devops):** "Tentar novamente" chama `st.cache_data.clear()`, que no Streamlit é global (todas as sessões). Quem clica repetidas vezes com a API fora limpa o cache de todos os visitantes. O botão só existe enquanto a API falha, e a SPEC manda exatamente isso (§4.1). Como os erros não são cacheados, limpar não é necessário para tentar de novo.
- **O-04 (informativa):** o lote é validado depois de `strip()`. `"L-01\n"` e `" L-01 "` viram `L-01`, um valor limpo; nada fora da regex é enviado.
- **O-05 (informativa):** `uv run --package qc-dashboard ...` reconstruiu o `qc-dashboard` editável no ambiente ("Uninstalled 1 / Installed 2"). Rodei `uv sync --all-packages` no fim, e o lock não mudou.

## CA-26 (manual): execução local pelo tester

O CA-26 continua **pendente para a dupla**, porque o passo 5 pede um celular de verdade. O que deu para fazer na máquina, sem internet e sem nada no Git:

1. Banco descartável `partqc_ca26_test` no Postgres local (porta 55432), `infra/migrate.py` e `scripts/register_device.py` para `sim-01` e `edge-01`. As chaves só ficaram num arquivo do scratchpad, removido no fim com `shred`. A `qc-api` rodou em `localhost:8011` (health `ok`, contrato `0.3.0`).
2. `scripts/simulate.py --lots 8 --lot-size 20 --out-of-control-lots 6 --seed 7` (`sent=160 created=160`) e 90 inspeções `live` (6 lotes de 15, `L-005` com 12 defeituosas) pelo `POST /inspections/batch`.
3. Dashboard com `streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8511`. Firefox headless, controlado pelo protocolo Marionette (o `--screenshot` sozinho sai em branco, antes da renderização). Com o clique em `Todos` na barra lateral, o texto `Contém dados simulados` aparece nas **4 páginas**, em 1280 px e em 400 px. `Origem dos dados: todas (real + simulado)` aparece na Visão geral e no Histórico. Não houve nenhum erro nem traceback na página ou nos logs da API e do Streamlit.
4. Carta p `live`: `L-005` em losango vermelho, com a anotação `L-005`; LC em ~24,4%, LSC tracejada em ~57,7% e LIC em 0%. A tabela tem `Sim` só em `L-005`, com datas `16/10/2026 21:34` e porcentagens com vírgula.
5. Em 400 px (simulação de celular): os KPIs ficam empilhados e legíveis (`90`, `24,4%`, `0`, `6`, `1,21`), e as barras por grau têm os valores escritos e as cores da §4.7. Problemas: a legenda cobre os títulos dos gráficos (T-01), e o eixo x da série está em inglês (T-02).

Para a dupla: repetir os passos 3 a 5 num navegador comum e num celular real, e registrar o resultado no PR.

## SPEC_ISSUE (se houver)

Nenhum. As tensões de leitura (a origem da carta × CA-08 e o "qualquer página" do CA-13) têm uma leitura que atende a todos os CAs, e estão registradas como observação para o architect, acima.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
