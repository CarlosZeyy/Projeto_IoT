# SPEC-013 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `4264813` (código da r2: `b93611c` e `459cfee`) |
| **Veredicto** | **PASS** |

O veredicto é PASS. Os 30 CAs automatizáveis têm teste e passam, a suíte inteira passa com e sem banco, e o ruff está limpo. O CA-26 é manual e fica pendente para a dupla (tabela no fim).

As três correções da r2 foram conferidas:

- **RV-01 / T-02:** corrigido. O eixo e o hover da série mostram `dd/mm/aaaa HH:MM` (minuto e hora) e `dd/mm/aaaa` (dia), tanto na figura quanto no navegador.
- **RV-02 / T-01:** corrigido. A legenda fica abaixo dos eixos e não cobre nenhum título, inclusive o da carta p, em 1280 px e em 400 px.
- **RV-03 / O-02:** corrigido. O aviso do `spc_source` não aparece mais no log do Streamlit real. Num controle com as views da r1, ele aparece.

Encontrei dois bugs novos, e nenhum deles viola um CA:

- **T-03 (média):** em 400 px, a barra de ferramentas do Plotly cobre a palavra da origem no título da carta p (`origem: real`) e parte do título da série. O dev-report diz que ela só aparece com o mouse em cima. Isso não vale para aparelhos sem hover, como celular e navegador headless: nesses aparelhos, o plotly.js do Streamlit deixa a barra sempre visível.
- **T-04 (baixa):** o último rótulo de data do eixo da série é cortado na borda direita.

Correção do registro da r1: as capturas "em 400 px" da r1 saíram, na verdade, com 500 px. O Firefox não deixa a janela ficar mais estreita que isso. Nesta rodada, a largura de 400 px é real: o painel roda dentro de um iframe de 400 px, e as media queries do Streamlit valem para ele.

Arquivo de aceite: `dashboard/tests/acceptance/test_spec_013.py`, com 33 funções `test_caNN_*` e 45 `test_extra_*`. Depois da parametrização, são **118 casos**: 117 passam sem banco, e 1 (`db`) passa com banco. Nenhum `xfail` sobrou. Mudanças em relação à r1:

- **removido:** `test_bug_t02_series_date_axis_in_pt_br` (os 3 casos `xfail`, que davam XPASS);
- **acrescentados** (18 casos):
  - `test_extra_t02_series_date_axis_in_pt_br[bucket × 3, 6 e 30 pontos]` (9 casos): os **dois** eixos x têm `tickformat` e `hoverformat` iguais ao formato da §4.7, sem `tickformatstops` e sem diretivas de nome (`%b`, `%B`, `%a`, `%c`, `%x`, `%p`);
  - `test_extra_t02_series_hover_in_pt_br[minute|hour|day]` (3 casos): nos dois traços, o `hovertemplate` traz a data **só** como `%{x|<formato do bucket>}`, nunca `%{x}` cru, seguida de `Inspeções: %{y}` / `Taxa de defeito: %{y:.1%}`;
  - `test_extra_t02_series_x_is_local_wall_clock[minute|hour]` (2 casos): `21:00Z` vira `18:00`, sem fuso, o que evita que o Plotly desenhe o horário em UTC;
  - `test_extra_t02_series_day_is_the_utc_date` (1 caso): com `bucket=day`, a data é a UTC (`2026-10-17T00:00Z` continua `17/10`, mesmo sendo dia 16 em São Paulo), e o título diz `(UTC)`;
  - `test_extra_t01_legend_never_in_the_title_band` (1 caso): nas 5 figuras (grau, tipo, série por hora, série por dia e carta p), a legenda fica abaixo da área do gráfico, e a carta p mantém o título `Carta p — origem: real`;
  - `test_extra_rv03_spc_origin_sync_logs_no_widget_state_warning` (1 caso): a barra lateral passa por `Simulado → Todos → Real → Simulado`, depois a origem da carta é trocada na página e `Lotes na carta` muda. O rádio segue a barra lateral (decisão 2 da r1), a escolha feita na página é mantida, e o aviso do Streamlit nunca é registrado;
  - `test_extra_rv03_warning_spy_detects_the_r1_pattern` (1 caso): controle do teste anterior. O padrão da r1 (estado gravado + `index=1`) **é** capturado pelo espião.

O espião do RV-03 finge que existe um runtime **só** no módulo `streamlit.elements.lib.policies`, que é a fronteira do framework, não a página testada. Isso é necessário porque o Streamlit só confere essa regra com servidor e registra o aviso uma vez por processo. O espião também zera esse "uma vez por processo".

**Os testes novos falham contra o código da r1.** Rodei o arquivo com um plugin de pytest no scratchpad, que troca `charts` e a view da carta pelas versões de `a713c61`. Resultado: os 12 testes de formato e hover, o da legenda e o do RV-03 falham. Os de relógio local e de data UTC passam nas duas versões, porque esse comportamento não mudou na r2.

## Cobertura dos critérios de aceite

Prefixo: `dashboard/tests/acceptance/test_spec_013.py::`. Todos os testes de CA rodaram de novo na r2, sem nenhuma mudança neles.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_summary_request_url_header_and_model` | ✅ |
| CA-02 | `test_ca02_timeout_and_503_are_unavailable[read-timeout\|503]`, `test_ca02_client_timeout_is_ten_seconds` | ✅ |
| CA-03 | `test_ca03_auth_server_error_and_invalid_body` | ✅ |
| CA-04 | `test_ca04_key_never_in_logs_or_exceptions` | ✅ |
| CA-05 | `test_ca05_missing_configuration` | ✅ |
| CA-06 | `test_ca06_new_session_defaults_to_live_without_badge` | ✅ |
| CA-07 | `test_ca07_all_sources_badge_depends_on_simulated_total` | ✅ |
| CA-08 | `test_ca08_simulated_sidebar_on_every_api_page[3 páginas]` | ✅ |
| CA-09 | `test_ca09_kpis` | ✅ |
| CA-10 | `test_ca10_grade_distribution_order_values_and_colors` | ✅ |
| CA-11 | `test_ca11_day_bucket_request_and_traces` (a figura mudou na r2; os traços `Inspeções`/barra e `Taxa de defeito`/linha continuam) | ✅ |
| CA-12 | `test_ca12_empty_overview` | ✅ |
| CA-13 | `test_ca13_timeout_shows_waking_and_retry_recovers[3 páginas]`, `test_ca13_model_page_badge_check_timeout` | ✅ |
| CA-14 | `test_ca14_p_chart_figure` (a figura mudou na r2: legenda; título, traços e anotação continuam) | ✅ |
| CA-15 | `test_ca15_default_controls_request` (a view mudou na r2: rádio sem `index` quando o valor já está no estado) | ✅ |
| CA-16 | `test_ca16_insufficient_data` | ✅ |
| CA-17 | `test_ca17_excluded_lots_and_table` | ✅ |
| CA-18 | `test_ca18_pagination_and_columns` | ✅ |
| CA-19 | `test_ca19_unknown_simulated_row` | ✅ |
| CA-20 | `test_ca20_history_csv` | ✅ |
| CA-21 | `test_ca21_invalid_lot_is_ignored[3 páginas]` | ✅ |
| CA-22 | `test_ca22_fetch_summary_cache` | ✅ |
| CA-23 | `test_ca23_metrics_against_targets` | ✅ |
| CA-24 | `test_ca24_missing_and_invalid_metrics` | ✅ |
| CA-25 | `test_ca25_no_ml_or_database_dependencies` (`uv export` e o `grep -rIE` do CA, sem pytest em subprocesso) | ✅ |
| CA-26 (manual) | Pendente para a dupla. Executei de novo os passos 1 a 4 e simulei o 5 em 400 px reais (seção própria). `test_extra_real_api_end_to_end` (`db`) automatiza os passos 1 a 4 | ⏳ manual |
| CA-27 | `test_ca27_cut_chart_notices`, `test_ca27_no_cut_notices[equal\|null]` | ✅ |
| CA-28 | `test_ca28_origin_caption_always_visible[visao_geral\|historico]` | ✅ |
| CA-29 | `test_ca29_one_chart_one_origin` | ✅ |
| CA-30 | `test_ca30_spc_cached_between_renders` | ✅ |
| CA-31 | `test_ca31_max_points_control` | ✅ |

## Suíte completa

```text
Sem banco (env -u TEST_DATABASE_URL uv run pytest -q):
2192 passed, 546 skipped, 1 warning in 242.61s

Com banco (TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q):
2738 passed, 1 warning in 418.45s
(o único aviso é o StarletteDeprecationWarning do fastapi.testclient, anterior a esta SPEC)

Só o arquivo de aceite, sem banco: 117 passed, 1 skipped
dashboard/tests com banco e --cov=qc_dashboard: 257 passed
  api.py 100% | charts.py 100% | config.py 100% | data.py 92% | filters.py 99%
  formatting.py 99% | model_info.py 100% | TOTAL 99%

uv run ruff check .          -> All checks passed!
uv run ruff format --check . -> 134 files already formatted
```

O autor relatou 2174 passed + 3 xpassed sem banco e 2720 passed + 3 xpassed com banco. A diferença é a do arquivo de aceite: −3 casos `xfail` (que davam XPASS) e +18 casos novos, ou seja, 2174 + 18 = 2192 e 2720 + 18 = 2738.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-03 | média | §4.4 (título da carta com a origem; R-06, INFO-02 da SPEC-006) e passo 5 do CA-26 ("gráficos legíveis" em ~400 px). Nenhum CA automatizável | 1. Subir a API e o dashboard com dados (ver CA-26). 2. Abrir "Controle estatístico" numa viewport de 400 px num aparelho sem hover (celular, ou Firefox headless). 3. Olhar o título `Carta p — origem: real`. 4. Na Visão geral, olhar o título `Volume e taxa de defeito por hora (hora local)` | Título da carta p legível por inteiro, sem nada por cima, como a correção do RV-02 pretendia | A barra de ferramentas do Plotly (*modebar*) fica **sempre visível** e cobre o fim dos títulos: em 400 px, a câmera fica sobre `real` da carta p (título de x=19 a 174 px, barra a partir de x=152 px). Na série, a barra cobre `(hora local)`, e também `(UTC)` com `bucket=day`. Na Distribuição por grau, ela encosta no fim do título. A legenda não cobre nada: o problema é outro elemento. **Causa:** o plotly.js do Streamlit 1.65 (`static/js/PlotlyChart.*.js`) faz `displayModeBar==="hover" && !hasHover → displayModeBar=true`. Em aparelhos sem `(hover: hover)`, como celulares com toque e o Firefox headless (conferi `matchMedia('(hover: hover)').matches === false`), a barra fica fixa (`modebar--custom`, opacidade 1, sem `:hover`). Isso contradiz a nota do dev-report ("no celular só aparece com um toque no gráfico"). Num desktop com mouse, ela só aparece com o mouse em cima, e em 1280 px não sobrepõe nenhum título. Em 500 px (o que a r1 e o autor chamaram de "400 px"), cobre só o título da série. Capturas no scratchpad: `mob_spc_chart0.png`, `mob_spc_todos.png` e `mob_vg_Real_Hora_chart2.png`. A severidade é a mesma do RV-02: a origem continua no rádio "Origem da carta", mas na página da carta o selo pode aparecer junto de uma carta `live` (RV-04). A captura `mob_spc_todos.png` mostra exatamente isso: o selo "Contém dados simulados" acima da carta `Real`, com `real` coberto no título. Só visual: não automatizei. A confirmação num celular real fica no passo 5 do CA-26 |
| T-04 | baixa | §4.7 (eixos legíveis) e passo 5 do CA-26. Nenhum CA | 1. Visão geral com dados `Real` de ~6 horas. 2. Em 400 px, granularidade `Hora` ou `Minuto`; em 1280 px, granularidade `Minuto`. 3. Olhar o último rótulo do eixo x | Todos os rótulos de data visíveis | O último rótulo (`17/10/2026 17:00` em `Hora`, 400 px; `17/10/2026 18:00` em `Minuto`, 400 px e 1280 px) ultrapassa a borda direita do SVG e é cortado: em 400 px, a 6ª barra fica sem rótulo. Os pontos e o hover continuam com a data completa. É a 2ª observação do dev-report, confirmada e ampliada para 1280 px com `Minuto`. Num HTML estático com o plotly.js do `plotly` 7.1.0, nas larguras do painel (815 e 362 px), nenhum rótulo foi cortado; o corte aparece no Streamlit |

## Testes exploratórios (além dos critérios)

### Versionados

São os 18 casos novos descritos no início. Todos os `test_extra_*` da r1 continuam passando, sem mudança.

### No navegador, com o Streamlit real (fora do Git)

Ambiente, todo encerrado ou removido no fim:

- banco descartável `partqc_ca26r2_test` no Postgres local (porta 55432), com `infra/migrate.py` e `scripts/register_device.py` para `sim-01` e `edge-01`;
- `qc-api` em `127.0.0.1:8011`, health `ok`, contrato `0.3.0`;
- `scripts/simulate.py --lots 8 --lot-size 20 --out-of-control-lots 6 --seed 7` (`sent=160 created=160`) e 90 inspeções `live` pelo `POST /inspections/batch` (6 lotes de 15, `L-005` com 12 defeituosas);
- dashboard em `127.0.0.1:8512`, e Firefox headless controlado pelo protocolo Marionette;
- as chaves foram geradas em tempo de execução, ficaram em arquivos `600` no scratchpad e foram apagadas com `shred` no fim. O banco foi removido (`DROP DATABASE ... WITH (FORCE)`), e as portas 2828, 8011, 8512 e 8513 foram fechadas.

**RV-02 (legenda × títulos).** Medi no DOM, com `getBoundingClientRect`, o título (`.gtitle`), a legenda (`g.legend`), os rótulos dos eixos x e a área dos eixos de cada figura:

| Largura | Figura | Legenda sobre o título | Legenda sobre o título do eixo x / rótulos | Legenda abaixo dos eixos |
|---|---|---|---|---|
| 1280 px | Carta p (`Carta p — origem: real`) | não | não / não | sim |
| 1280 px | Série, `Minuto`/`Hora`/`Dia`, com `Real` e `Todos` | não | não / não | sim |
| 400 px | Carta p | não | não / não | sim (5 itens em 3 linhas, abaixo de `Lote (ordem de início)`) |
| 400 px | Série, `Minuto`/`Hora`/`Dia`, com `Real` e `Todos` | não | não / não | sim |
| 1280 e 400 px | Distribuição por grau e Inspeções por tipo | sem legenda | — | — |

Conclusão: o RV-02 está corrigido. O título que ainda fica coberto em 400 px é pela barra de ferramentas (T-03), não pela legenda.

**RV-01 no navegador.** Os rótulos dos eixos são todos numéricos em PT-BR, por exemplo `17/10/2026 12:00` … `17/10/2026 18:00` em `Hora` e `Minuto`, e `17/10/2026` em `Dia`. O hover, disparado por `mousemove` na área do gráfico, mostra `17/10/2026 12:00` / `Inspeções: 15`, `17/10/2026 18:20` / `Taxa de defeito: 50,0%` e `17/10/2026` / `Inspeções: 250`. Os rótulos e o hover estão na hora local: os lotes começaram às 15:23Z, e o eixo mostra 12:00.

**Rótulos repetidos (o `dtick` fixo da r2).** Gerei 78 figuras pelo `charts.volume_and_defect_rate`: 3 buckets × {2, 5, 10, 11, 12, 13, 15, 18, 20, 24, 31, 48, 96} pontos × 815 e 362 px. Renderizei todas com o plotly.js do `plotly` 7.1.0. Nenhuma tem rótulo repetido no eixo, inclusive logo acima do limite `MAX_PINNED_TICKS = 10`, onde o Plotly passa a escolher os ticks: com 12 pontos por hora em 815 px, os ticks ficam a cada 2 h.

**RV-03 no servidor real.** Em "Controle estatístico", a barra lateral passou por `Simulado → Real → Simulado → Todos → Simulado`. A carta e o rádio da página acompanharam: `simulado`, `real`, `simulado`, `real` (`Todos` nunca chega à carta), `simulado`. Depois, troquei a origem da carta para `Real` na página, fui ao Histórico, pus `Real` na barra lateral e voltei: a carta está em `real`.

- **r2** (`dashboard/app.py`): o log do Streamlit tem só as 6 linhas de inicialização, sem aviso, erro ou traceback.
- **Controle com as views de `a713c61`**, copiadas para o scratchpad e servidas na porta 8513 com a mesma API, mesma sequência: o log registra `The widget with key "spc_source" was created with a default value but also had its value set via the Session State API.`, com stack.

O log da API teve 250 respostas 200 e nenhuma linha de erro.

**CA-26, passo 3, de novo.** Com `Todos`, o selo `Contém dados simulados` aparece nas **4 páginas**, em 1280 px e em 400 px reais. `Origem dos dados: todas (real + simulado)` aparece na Visão geral e no Histórico. Nenhum erro na tela.

### Observações (não bloqueiam)

- **O-06 (informativa, sobre a medição da r1):** o Firefox tem largura mínima de janela de 500 px CSS. O `SetWindowRect` com 400 devolve 500, e `devPixelsPerPx` não muda isso. Nesta rodada, a largura de 400 px é real porque o painel roda num iframe de 400 px. Essa largura é a que o CA-26 pede ("~400 px") e a que o T-03 precisa para aparecer na carta p.
- **O-07 (informativa, fora do escopo da r2):** com `Minuto`, a linha `Taxa de defeito` liga os pontos por cima dos minutos sem inspeção. Entre um lote e o seguinte, ela desenha uma rampa de 0% a 100% que não corresponde a nenhum dado. Isso já existia na r1. A SPEC não pede tratar lacunas, por isso não registro como bug. Se a dupla achar que confunde, é uma decisão de interface (por exemplo, não ligar pontos com lacuna) para o architect.
- **O-01 / RV-04 continuam como aceitos na r1:** o selo aparece com a carta `Real` quando a barra lateral está em `Todos`, visto de novo em 400 px. O T-03 piora a leitura desse caso no celular.

## CA-26 (manual): pendente para a dupla

O CA-26 continua **pendente**. O passo 5 pede um celular de verdade, e é ele que confirma (ou não) o T-03. O que mudou nos passos 3 a 5 depois da r2:

- **Passo 3:** nada muda no comportamento. O selo continua nas 4 páginas com `Todos`; conferido de novo em 1280 px e em 400 px.
- **Passo 4:** a legenda da carta agora fica **abaixo** do eixo x (antes ficava em cima, sobre o título). `L-005` continua em losango vermelho com a anotação, e o título `Carta p — origem: real` não é coberto pela legenda em 1280 px.
- **Passo 5:** as datas do eixo e do hover da série agora estão em PT-BR (`17/10/2026 12:00`), e a legenda não cobre mais os títulos. Na simulação em 400 px, o que ainda atrapalha é a barra de ferramentas sobre o fim dos títulos (T-03) e o último rótulo de data cortado (T-04). No celular, conferir se a barra fica visível sem toque, como o código do plotly.js indica.

Tabela para a dupla preencher (copiar para o PR ou para este relatório):

| Passo | O que conferir | Navegador comum (1280 px) | Celular real (~400 px) | Quem / data |
|---|---|---|---|---|
| 1 | API local com dados de `scripts/simulate.py` e algumas inspeções `live` | | — | |
| 2 | Dashboard local abre sem erro (`streamlit run dashboard/app.py`) | | | |
| 3 | Origem `Todos` → `Contém dados simulados` nas 4 páginas | | | |
| 4 | Carta p com pelo menos 1 ponto vermelho (losango) e anotado com o `lot_id`; título `Carta p — origem: …` legível | | | |
| 5a | KPIs legíveis (5 valores, vírgula decimal) | — | | |
| 5b | Gráficos legíveis: legenda abaixo dos eixos, títulos inteiros, datas `dd/mm/aaaa HH:MM` | — | | |
| 5c | (T-03) A barra de ferramentas do Plotly aparece sem tocar no gráfico? Cobre `origem: …` no título da carta p? | — | | |
| 5d | (T-04) O último rótulo de data da série aparece inteiro? | | | |

## SPEC_ISSUE (se houver)

Nenhum. Todos os CAs são testáveis como estão escritos. O T-03 é um bug de interface: a correção do RV-02 resolveu a legenda, mas não a barra de ferramentas.

## Declaração

- [x] Não alterei código de produção, só `dashboard/tests/acceptance/test_spec_013.py` e este relatório.
- [x] Todos os processos, portas e bancos temporários que abri foram encerrados ou removidos. As chaves geradas para o ambiente local foram apagadas com `shred`. Nenhuma credencial aparece como literal nos testes.
