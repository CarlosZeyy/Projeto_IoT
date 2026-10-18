# SPEC-013 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-013-dashboard` |
| Commits | `b93611c`, `459cfee` (e o commit deste relatório) |

## Resumo

A r2 corrige os dois achados obrigatórios do `r1-review-report.md` e o opcional, sem mexer em nada mais:

- **RV-01 (T-02, §4.7):** o gráfico "Volume e taxa de defeito" passa a mostrar datas numéricas em PT-BR no eixo e no hover: `dd/mm/aaaa HH:MM` em `minute` e `hour` e `dd/mm/aaaa` em `day`. O dia continua sendo a data UTC, e o título continua dizendo `(UTC)`.
- **RV-02 (T-01):** a legenda de todas as figuras sai da faixa do título e vai para baixo dos eixos. O título `Carta p — origem: <rótulo>` não fica mais coberto, nem em 1280 px nem em 400 px.
- **RV-03 (O-02, opcional):** o rádio "Origem da carta" não recebe mais `index` quando o valor já está no `st.session_state`. Some do log o aviso do Streamlit, que vinha com stack.

Os achados RV-04 a RV-07 não foram tocados, como o orquestrador pediu.

## Rastreabilidade (critério de aceite → implementação)

Nenhum CA mudou de implementação nesta rodada. A tabela da r1 (`r1-dev-report.md`) continua valendo. Abaixo estão só os requisitos tocados na r2 e os CAs que passam pelo código alterado. `G` = `dashboard/tests/test_charts.py`, `P` = `dashboard/tests/test_pages.py`.

| Requisito / critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| §4.7, datas `dd/mm/aaaa HH:MM` no eixo e no hover (RV-01) | `dashboard/src/qc_dashboard/charts.py` (`DATE_FORMAT`, `BUCKET_DATE_FORMATS`, `volume_and_defect_rate`) | `G::test_series_dates_are_numeric_pt_br[minute/hour/day]`, `G::test_series_date_format_matches_table_format` |
| §4.7, rótulos sem repetição com poucos buckets (RV-01) | `charts.py` (`BUCKET_MS`, `MAX_PINNED_TICKS`, `_pinned_dtick`) | `G::test_series_few_buckets_pin_one_tick_per_bucket[minute/hour/day]`, `G::test_series_many_buckets_let_plotly_choose_ticks`, `G::test_series_single_point_and_empty` |
| §4.4 e §4.7, título legível sem a legenda por cima (RV-02) | `charts.py` (`_base_layout`) | `G::test_legend_never_shares_the_title_band` |
| §4.4, rádio "Origem da carta" (RV-03) | `dashboard/views/controle_estatistico.py` | `P::test_spc_origin_sync_does_not_pass_a_default_with_state` |
| CA-11, CA-14, CA-29 (figuras alteradas) | `charts.py` | `G::test_volume_and_defect_rate_traces`, `G::test_p_chart`, `P::test_spc_simulated_origin` (sem mudança, passam) |
| CA-08, CA-15 (origem da carta) | `views/controle_estatistico.py` | `P::test_spc_follows_simulated_sidebar`, `P::test_spc_defaults` (sem mudança, passam) |

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-review-report.md` RV-01 / `r1-test-report.md` T-02 (alta) | Em `volume_and_defect_rate`, os **dois** eixos x do `make_subplots` recebem `tickformat` e `hoverformat` iguais ao formato do bucket: `"%d/%m/%Y %H:%M"` em `minute`/`hour` (o mesmo `formatting.DATETIME_FORMAT` das tabelas) e `"%d/%m/%Y"` em `day`. Os dois `hovertemplate` trocam `%{x}` por `%{x\|<formato>}`, então o hover não depende do `hoverformat`. Os formatos são só numéricos, porque o Plotly não traduz nomes de mês sem carregar um locale. Ajuste extra, no mesmo sentido: com poucos buckets no eixo (até `MAX_PINNED_TICKS = 10`), o `dtick` fica fixo em 1 bucket (60 000 ms, 3 600 000 ms ou 86 400 000 ms). Sem isso, o Plotly punha ticks a cada 30 s ou a cada 12 h, e o formato sem segundos (ou sem hora, no `day`) repetia o mesmo rótulo em ticks vizinhos. Acima de 10 buckets, o Plotly escolhe os ticks. O teste do tester `test_bug_t02_series_date_axis_in_pt_br[minute\|hour\|day]` agora dá **XPASS**. O `xfail` fica para o tester tirar (R-07), e ele também pode cobrir o hover, como o reviewer pediu. |
| `r1-review-report.md` RV-02 / `r1-test-report.md` T-01 (média) | `_base_layout`, usado pelas 4 figuras: a legenda continua horizontal, mas fica ancorada no **rodapé do contêiner** (`yref="container"`, `y=0`, `yanchor="bottom"`, `xref="paper"`, `x=0`, `xanchor="left"`). O Plotly reserva essa altura embaixo dos eixos (`_reservedMargin`), então a legenda não cobre o título do eixo x, e numa tela estreita ela quebra linhas **para baixo**, longe do título. Conferi com o Firefox headless, em 1280 px e em 400 px, em HTML estático gerado pelo `plotly` 7.1.0 (plotly.js 3.x), com a carta p (12 lotes, 1 fora de controle), a série por hora (30 e 3 buckets) e a série por dia (3 buckets). Nos dois tamanhos, o título `Carta p — origem: real` e o da série aparecem inteiros, e a legenda fica embaixo do eixo x. O plotly.js embutido no Streamlit 1.65 tem o mesmo caminho de `_reservedMargin` para legendas em `container`. A conferência dentro do Streamlit e no celular fica com o tester e com a dupla (CA-26), como o reviewer pediu. |
| `r1-review-report.md` RV-03 / `r1-test-report.md` O-02 (baixa, opcional) | O rádio `spc_source` recebe `index` só quando `KEY_ORIGIN` ainda não está no `st.session_state`. Quando `_sync_origin_with_sidebar` (ou o próprio widget) já pôs o valor lá, o valor do estado manda, e o Streamlit não chama mais o aviso "created with a default value but also had its value set via the Session State API". O aviso aparece uma vez por processo e só com servidor, então o teste espiona os argumentos de `policies.check_session_state_rules`. Ele **falha sem a correção** (conferido com `git stash` da view) e passa com ela. O comportamento da decisão 2 da r1 não muda: `P::test_spc_follows_simulated_sidebar` passa sem alteração. |
| RV-04, RV-05, RV-06, RV-07 (baixas) | Nada, por instrução do orquestrador: vão para o architect ou para a SPEC-015. |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest dashboard/tests -q
uv run ruff check . && uv run ruff format --check .
# conferência visual: painel local, com a API em http://localhost:8001
uv run --env-file .env --package qc-dashboard streamlit run dashboard/app.py
```

Resultados desta rodada (código dos dois commits):

```text
uv run ruff check .            -> All checks passed!
uv run ruff format --check .   -> 134 files already formatted
uv run pytest dashboard/tests -q -> 238 passed, 1 skipped, 3 xpassed
uv run pytest -q (sem banco)   -> 2174 passed, 546 skipped, 3 xpassed, 1 warning
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
                               -> 2720 passed, 3 xpassed, 1 warning
```

Os 3 `xpassed` são o `test_bug_t02_*` do tester, que agora passa. O `1 warning` já estava na r1 (`r1-test-report.md`, linhas 67 e 70).

## Notas para o tester

- O T-02 virou XPASS nos 3 buckets. Para cobrir o hover, os dois traços da série têm `hovertemplate` começando por `%{x|%d/%m/%Y %H:%M}<br>` (`minute`/`hour`) ou `%{x|%d/%m/%Y}<br>` (`day`), e os eixos `xaxis` e `xaxis2` têm `hoverformat` igual ao `tickformat`.
- Para conferir o RV-02 no Streamlit: título e legenda das 4 figuras em 1280 px e em 400 px (Visão geral e Controle estatístico).
- Observação visual, fora do escopo dos achados: em 400 px, a barra de ferramentas do Plotly (*modebar*), que só aparece com o mouse sobre o gráfico, fica sobre o título, como já acontecia na r1. Ela some quando o mouse sai, e no celular só aparece com um toque no gráfico. Não mudei nada aqui, porque esconder a barra é uma escolha de interface que a SPEC não pede. Se a dupla achar que atrapalha, é uma linha (`config={"displayModeBar": False}` no `st.plotly_chart`), mas isso cabe ao reviewer ou ao architect decidir.
- Também em 400 px, com só 3 buckets por hora, o Plotly inclina os rótulos `dd/mm/aaaa HH:MM`, e o último pode ser cortado na borda direita. Os pontos e o hover continuam com a data completa.

## Decisões tomadas dentro do escopo da SPEC

1. **Formatos só numéricos** (`%d/%m/%Y %H:%M`), sem `tickformatstops`, para que o eixo tenha sempre o formato da §4.7 e o `tickformat` possa ser conferido em teste.
2. **`dtick` fixo com poucos buckets** (`MAX_PINNED_TICKS = 10`): evita rótulos repetidos sem limitar séries longas. O limite é uma constante do módulo.
3. **Legenda no rodapé do contêiner** em todas as figuras (não só na carta p), para o painel ter um visual só e porque a série tinha o mesmo problema em 400 px.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (e a suíte inteira, com e sem banco)
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
