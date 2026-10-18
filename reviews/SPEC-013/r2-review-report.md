# SPEC-013 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `main...b07784d`, com foco em `a713c61..b07784d` (o que mudou desde o r1-review-report) |
| Test report | r2-test-report.md (PASS, com os bugs T-03 médio e T-04 baixo e o CA-26 manual pendente) |
| **Veredicto** | **APPROVED** |

A r2 fecha os três achados que a r1 pediu (RV-01 alto, RV-02 médio, RV-03 baixo) e não muda mais nada. O código de produção alterado se resume a `charts.py` (formato das datas, `dtick` e posição da legenda) e a uma expressão em `controle_estatistico.py` (o `index` do rádio). Nenhum CA, ADR, contrato ou dependência mudou. Os dois bugs novos do tester são reais, e eu os confirmei. O T-03 (RV-08) é **médio**, pelo mesmo critério que usei no RV-02. O T-04 (RV-09) é **baixo**. Nenhum dos dois é bloqueante ou alto, então o veredicto é APPROVED. As justificativas e o plano de contingência para uma eventual r3 estão em "Decisões pedidas pelo orquestrador".

O portão R-09 continua aberto pelo **CA-26 manual**, que a dupla ainda precisa executar num celular real. Isso já constava da r1 e não muda.

Contagem desta rodada: 0 bloqueantes, 0 altos, 1 médio (RV-08) e 6 baixos (2 novos, RV-09 e RV-10, e 4 que vêm da r1 sem mudança, RV-04 a RV-07). Fechados: RV-01, RV-02 e RV-03.

## Verificação dos achados da r1

| Achado r1 | Situação | Evidência |
|---|---|---|
| RV-01 (alta), datas em inglês na série | **Corrigido** | `charts.py:69-72`: `BUCKET_DATE_FORMATS`, só com diretivas numéricas, e `minute`/`hour` reaproveitando `formatting.DATETIME_FORMAT`, o mesmo formato das tabelas. `charts.py:157-158` e `:166`/`:178`: os dois `hovertemplate` usam `%{x\|<formato>}`, sem `%{x}` cru. `charts.py:184`: `update_xaxes` sem `row`/`col` aplica `tickformat` e `hoverformat` aos **dois** eixos do `make_subplots`. Com `day`, o eixo continua com a data UTC e o título mantém `(UTC)` (§4.7). O `dtick` fixo (`charts.py:185-187` e `:196-203`) é um ajuste extra no mesmo requisito: evita rótulos repetidos com poucos buckets. Confere com o eixo, porque o `tick0` padrão do Plotly (2000-01-01 00:00) cai em hora cheia, e as horas locais de São Paulo também (UTC−3, sem horário de verão). O tester confirmou no navegador (`17/10/2026 12:00`, hover incluído) e varreu 78 figuras sem rótulo repetido. O `xfail` virou teste normal, com o hover coberto (`test_extra_t02_*`, 15 casos). |
| RV-02 (média), legenda sobre o título | **Corrigido** | `charts.py:82-102`: legenda com `yref="container"`, `y=0` e `yanchor="bottom"`, no rodapé. O tester mediu no DOM, em 1280 px e em 400 px reais (iframe), e a legenda não cobre nenhum título, nem o título nem os rótulos do eixo x. A aplicação vale para as 4 figuras (decisão 3 do dev-report, que aceito: é o mesmo problema e dá um visual só). O que ainda cobre o título em 400 px é outro elemento, a barra de ferramentas do Plotly (RV-08). |
| RV-03 (baixa), aviso do Streamlit no log | **Corrigido** | `controle_estatistico.py:90-98`: o `index` só é passado quando `KEY_ORIGIN` ainda não está no `st.session_state`. Sem o `index`, a seleção de origem continua igual: `_sync_origin_with_sidebar` grava no estado antes da criação do rádio, e, quando a chave do widget some ao trocar de página, o `option_index` volta a ler o valor guardado por `filters.remember`. O tester conferiu no servidor real, inclusive na volta de outra página, e mostrou o aviso num controle com a view da r1. `test_spc_follows_simulated_sidebar` e o CA-08/CA-15 passam sem mudança. |
| RV-04 a RV-07 (baixas) | **Sem mudança**, como a r1 decidiu | Continuam sendo sugestões ao architect (RV-04, RV-05, RV-07) e à SPEC-015 (RV-06). Não foram tocados, o que está correto. |

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-08 | média | `dashboard/views/controle_estatistico.py:143`, `dashboard/views/visao_geral.py:37`, `:38` e `:53` (`st.plotly_chart` sem `config`); `dashboard/src/qc_dashboard/charts.py:92` (`margin.t=50`) | **T-03 do tester, confirmado.** Os 4 `st.plotly_chart` usam o `displayModeBar` padrão (`"hover"`). Conferi no bundle do Streamlit 1.65.0 (`static/js/PlotlyChart.*.js`): `o.displayModeBar==="hover"&&!r&&(o.displayModeBar=!0)`, ou seja, em aparelhos sem `(hover: hover)` (celular com toque) a barra fica **sempre** visível. Em 400 px, ela cobre `real` no título `Carta p — origem: real` e o fim do título da série (`(hora local)` ou `(UTC)`). A nota do dev-report ("no celular só aparece com um toque") está errada. Num desktop com mouse, em 1280 px, a barra não sobrepõe nenhum título. A consequência para a R-06 é a mesma do RV-02 da r1: o título é um canal **redundante** da origem, e o caso em que ele faz falta é o selo conservador sobre uma carta `live` (RV-04). Não há dado simulado passando por real (ver a decisão abaixo). Por isso, mantenho a severidade média, a mesma do RV-02. | Não bloqueia. Recomendo levar a uma SPEC futura de acabamento da interface, ou à r3 só se o passo 5 do CA-26 reprovar no celular. Correção exata em "Plano para uma eventual r3". |
| RV-09 | baixa | `dashboard/src/qc_dashboard/charts.py:92` (`margin.r=10`) e `:184` | **T-04 do tester, confirmado pela leitura.** Os rótulos `dd/mm/aaaa HH:MM` são longos (16 caracteres). Com só 10 px de margem à direita, o último rótulo da série é cortado na borda: em 400 px com `Hora`/`Minuto` e em 1280 px com `Minuto`. Pontos, hover e tabela continuam com a data completa, e o formato está certo, então nada da §4.7 fica sem atender. É cosmético. | Não bloqueia. Mesma via do RV-08. Correção exata em "Plano para uma eventual r3". |
| RV-10 | baixa | `dashboard/tests/acceptance/test_spec_013.py:1926-1944` e `dashboard/tests/test_pages.py:254-284` | Os dois testes do RV-03 (o do tester e o do autor) espionam atributos privados do Streamlit: `policies._shown_default_value_warning`, `policies._LOGGER` e `policies.check_session_state_rules`. Hoje funcionam (o Streamlit está fixado em 1.65.0 no `uv.lock`), e o controle `test_extra_rv03_warning_spy_detects_the_r1_pattern` garante que o espião não é tautológico. Mas, numa atualização do Streamlit que renomeie esses símbolos, os testes falham com `AttributeError`, sem dizer o que mudou. | Nenhuma mudança agora. Quando alguém atualizar o Streamlit e esses testes quebrarem, a causa é a API privada, não uma regressão do RV-03. Fica registrado aqui para quem fizer a atualização. |
| RV-04 a RV-07 | baixa | ver `r1-review-report.md` | Sem mudança desde a r1, como decidido. | Os mesmos encaminhamentos da r1: architect (RV-04, RV-05, RV-07) e SPEC-015 (RV-06). |

## Decisões pedidas pelo orquestrador

### T-03 (RV-08): pode ir para uma SPEC futura sem violar a R-06?

**Sim.** A R-06 exige que o dado simulado tenha sempre `source=simulated` **e seja visível como tal**. Na página da carta, o modebar não esconde nenhum dado simulado:

1. **Carta `simulated`:** o selo `Contém dados simulados` aparece **sempre**, porque `controle_estatistico.py:115` chama `render_badge(selected, simulated=source is Source.SIMULATED)`. O selo é um `st.warning` no topo da página, fora da figura, e o modebar não o alcança. O rádio "Origem da carta" mostra `Simulado`. Então, mesmo com `simulado` coberto no título, a origem simulada fica visível por dois canais normativos: o selo da §4.2 (que a §4.4 manda usar: "Origem `Simulado` → selo de §4.2") e o próprio controle.
2. **Carta `live`:** o que some é a palavra `real`. Isso só confunde quando o selo aparece por causa da barra lateral (RV-04, sidebar em `Todos` ou `Simulado` com a carta trocada para `Real`). Mesmo nesse caso, o rádio continua mostrando `Real`. É um aviso conservador sobre dado real, não dado simulado passando por real, que é o erro que a R-06 proíbe.
3. **Visão geral:** a origem vem do `st.caption` "Origem dos dados: ..." (§4.2, CA-28), que fica fora da figura e não é afetado.
4. **Contrato com a SPEC:** a §4.4 pede que a figura tenha o título `Carta p — origem: <rótulo>`, e ela tem. CA-14 e CA-29 conferem o título no `spec` da figura e passam. O modebar é um elemento do plotly.js sobreposto na renderização, não um título errado.
5. **Alcance:** só aparelhos de toque em larguras estreitas. Em 1280 px, que é a forma principal de apresentação do painel, não há sobreposição.

Por isso, o T-03 tem o mesmo peso que o RV-02 tinha na r1, que eu classifiquei como médio. Médio não bloqueia (regra do veredicto). Classificar o T-03 como alto agora, com a mesma consequência, seria incoerente com a r1.

Existe um segundo motivo para **não** gastar a r3 agora. O CA-26 é manual, ainda está pendente e é pré-condição do merge (R-09). Se eu pedir a r3 para o T-03 e, depois, o celular real revelar outro problema no passo 5, não sobra rodada (R-10), e a SPEC escala. Aprovar agora deixa a r3 **de reserva** para um defeito confirmado no aparelho real, com o escopo já definido abaixo.

Encaminhamento: o orquestrador registra o RV-08 e o RV-09 como pendência para uma SPEC futura de acabamento da interface do dashboard (via architect), salvo se a dupla optar pela r3 conforme o plano abaixo.

### T-04 (RV-09)

**Baixo, não bloqueia.** O formato exigido pela §4.7 está implementado, e só o último rótulo é cortado na borda. A informação completa continua nos pontos, no hover e na tabela. Vai pela mesma via do RV-08.

### Plano para uma eventual r3 (só se o orquestrador ou a dupla a abrir)

Abrir a r3 apenas se o passo 5 do CA-26 (linhas 5b, 5c e 5d da tabela do test-report) for julgado **reprovado** pela dupla no celular real, ou se a dupla decidir corrigir antes do merge. O escopo é **fechado** nestes dois itens. Nenhum outro arquivo de produção muda.

1. **RV-08 (developer):** passar `config={"displayModeBar": False}` nos 4 `st.plotly_chart` (`visao_geral.py:37`, `:38` e `:53`; `controle_estatistico.py:143`). Os gráficos não perdem nenhuma função exigida pela SPEC: ela não pede zoom nem exportação PNG, e o botão de tela cheia do Streamlit fica na barra do elemento, que é separada do plotly.js. Teste unitário do autor: o campo `config` do proto de cada `plotly_chart` (`at.get("plotly_chart")[i].proto.config`) tem `displayModeBar: false`. Tester: um teste de aceite com a mesma checagem nas 4 figuras e, no navegador sem hover em 400 px, a conferência de que o título `Carta p — origem: real` aparece inteiro.
2. **RV-09 (developer):** em `_base_layout` (`charts.py:92`), aumentar `margin.r` (por exemplo, para 40 px) **ou** ligar `automargin` no eixo x da série, para que o último rótulo caiba. Conferir em 400 px com `Hora` e `Minuto` e em 1280 px com `Minuto`. Não precisa de teste automatizado. O tester registra a conferência.

Nada mais entra na r3: RV-04 a RV-07, RV-10 e O-07 ficam de fora. Se a r3 não resolver, a R-10 manda escalar ao humano.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | A §4.7 agora está atendida na série (RV-01 fechado), e a §4.4 continua atendida (título com a origem, legenda fora da faixa do título). O diff da r2 só toca o que a r1 autorizou: `charts.py` (RV-01, RV-02), `controle_estatistico.py` (RV-03), os testes do autor, os testes de aceite, os relatórios e o status da SPEC e do plano. O `dtick` fixo e a legenda em todas as figuras são decisões dentro do mesmo requisito, registradas no dev-report (decisões 1 a 3) e aceitas acima. Nenhum CA alterado (R-08 ✅). Rastreabilidade da r2 no dev-report. |
| 2. Regras inegociáveis | ✅ | **R-01/R-12:** `pyproject.toml` e `uv.lock` intocados na r2; sem dependência nova. **R-02:** N/A. **R-03:** a busca por `key`/`secret`/`token`/`password`/`postgres://`/`eyJ` no diff `a713c61..HEAD` só encontra a `TEST_DATABASE_URL` local sem senha nos relatórios, a mesma da r1. **R-04:** `packages/contracts` intocado. **R-05:** N/A. **R-06:** origem padrão, selo, legenda de origem e "uma carta, uma origem" sem mudança, com CAs 6, 7, 8, 28 e 29 passando. A análise do modebar está acima: não viola. **R-07:** `b93611c` e `459cfee` (`Agent: developer`) só tocam produção e `dashboard/tests/` fora de `acceptance/`; `1358faa` (`developer`) só o dev-report; `b373052` (`Agent: tester`) só `dashboard/tests/acceptance/test_spec_013.py` e o test-report; `90d97b5`, `4264813` e `b07784d` (`orchestrator`) só o status em `docs/plan.md` e na SPEC. Todos com `Agent:` e `Refs: SPEC-013` lidos pelo git como trailers. **R-10:** esta é a r2; a r3 fica de reserva. **R-11:** N/A. **R-13:** todos os commits como `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, Conventional Commits. |
| 3. Corretude | ✅ (com RV-08 e RV-09) | Datas: o eixo da série recebe hora local sem fuso (`to_local(...).replace(tzinfo=None)`) ou a data UTC em `day`, como na r1; o `_pinned_dtick` mede o intervalo em UTC, com `bucket_start` sempre com fuso, então não há comparação entre `datetime` com e sem fuso. Bordas: lista vazia e um único ponto cobertos (`test_series_single_point_and_empty`); bucket desconhecido cai no `DATETIME_FORMAT` e não fixa o `dtick`. O rádio sem `index` não muda a origem em nenhum caminho (primeira renderização, troca na barra lateral, volta de outra página). Sem async, sem I/O novo. |
| 4. Testes | ✅ (com RV-10) | Test-report PASS, 30 CAs automatizáveis cobertos, nenhum `xfail` restante. O tester mostrou que os testes novos **falham** contra o código da r1 (formato, hover, legenda e RV-03), e que o espião do RV-03 detecta o padrão antigo (controle positivo). Rodei: `uv run pytest dashboard/tests -q` → **256 passed, 1 skipped** (o `db`, sem `TEST_DATABASE_URL`), igual ao do tester (117 + 1 no arquivo de aceite). Sem rede externa e sem credencial literal em URL. A dependência de API privada do Streamlit está no RV-10 (baixo). |
| 5. Qualidade | ✅ | `ruff check` limpo e `ruff format --check` com 134 arquivos formatados, conferidos por mim. As constantes novas (`DATE_FORMAT`, `BUCKET_DATE_FORMATS`, `BUCKET_MS`, `MAX_PINNED_TICKS`) são `MappingProxyType` imutáveis e comentadas; `_pinned_dtick` é pequena e pura; o formato de data reaproveita `formatting.DATETIME_FORMAT`, sem duplicar a regra. Sem `print`, com type hints. README sem mudança necessária. |
| 6. Segurança | N/A aqui | A SPEC tem a tag `security`, e o portão é do security-devops, depois desta revisão. A r2 não muda nada de cliente, cache, chave ou configuração. As notas da r1 para ele continuam valendo. |

## Pontos positivos

- A correção do RV-01 foi além do pedido no ponto certo: o formato sem segundos repetia rótulos com o `dtick` automático do Plotly, e o `dtick` fixo por bucket resolve isso sem limitar séries longas. O tester validou isso numa varredura de 78 figuras.
- O formato do eixo reaproveita a constante das tabelas, então a data do gráfico e a da tabela não podem divergir (`test_series_date_format_matches_table_format`).
- O tester corrigiu o próprio registro da r1 (os "400 px" eram 500 px no Firefox) e passou a medir em 400 px reais num iframe. Foi essa medição que encontrou o T-03. A causa veio com o trecho exato do plotly.js, que eu confirmei no bundle instalado.
- Os testes do RV-03 têm um controle positivo, o que evita um espião que nunca dispara.

## SPEC_ISSUE (se houver)

Nenhum. O RV-08 e o RV-09 não são defeitos da SPEC: a §4.4 e a §4.7 estão atendidas na letra, e os dois são acabamento de renderização. A sugestão ao architect, se ele abrir a SPEC de acabamento, é dizer explicitamente que as figuras não mostram a barra de ferramentas do Plotly (ou onde ela fica) e que os rótulos de data não podem ser cortados em ~400 px. Opcionalmente, pode repetir a origem da carta num `st.caption` fora da figura, como a Visão geral já faz, para que a R-06 não dependa de nada que a renderização possa sobrepor.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
