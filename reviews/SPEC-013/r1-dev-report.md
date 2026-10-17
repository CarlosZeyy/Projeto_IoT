# SPEC-013 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-013](../../docs/specs/SPEC-013-dashboard.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-013-dashboard` |
| Commits | `bebbbee`, `4eeee93`, `3b91738`, `ee62125`, `3aa8896` (e o commit deste relatório) |

## Resumo

- **Configuração e cliente (§4.1):** `config.get_settings()` lê `st.secrets` e, sem a chave ou sem arquivo de secrets, a variável de ambiente; sem `API_BASE_URL`/`READ_API_KEY` → `ConfigError`. `ApiClient` (httpx, `timeout=10.0`, `X-API-Key` em toda chamada, rotas sob `/api/v1`) devolve os modelos de `qc_contracts` e mapeia os erros para `ApiUnavailable` / `ApiAuthError` / `ApiError(status)`, sem a chave em log, mensagem ou `repr`. `api.get_client()` (`st.cache_resource`) é o único ponto de criação. `data.py` tem uma função `st.cache_data(ttl=30)` por endpoint, só com argumentos hasheáveis (nunca a chave).
- **Barra lateral e R-06 (§4.2):** origem (padrão `Real`), período (últimos 7 dias locais → `from`/`to` UTC), tipo e lote (regex do contrato com `re.fullmatch`; inválido → `Lote inválido` e filtro ignorado). Os valores são mantidos entre páginas. Selo `Contém dados simulados` no topo e na barra lateral; legenda `Origem dos dados: ...` sempre abaixo do título da Visão geral e do Histórico.
- **Páginas (§4.3 a §4.6):** `app.py` com `st.set_page_config` e `st.navigation` (Visão geral é a padrão). Visão geral com 5 KPIs, distribuição por grau, por tipo e série com seletor `Minuto`/`Hora`/`Dia`. Controle estatístico com **uma** requisição SPC e **uma** figura por renderização, avisos de corte e de excluídos (campos 0.3.0, ADR-017) e o aviso de que o período não se aplica. Histórico paginado com filtros da página, tabela PT-BR e CSV da página. Sobre o modelo lê o `metrics.json` (chaves da SPEC-012 §4.7), compara com `PRD_TARGETS` e mostra os PNGs se existirem.
- **Visual (§4.7):** `charts.GRADE_COLORS`, cores neutras por tipo, valores escritos nas barras, losango vermelho com anotação nos pontos fora de controle, vírgula decimal (Plotly com `separators=",."`), fuso `America/Sao_Paulo` só na interface; `bucket=day` usa a data UTC e o título diz `(UTC)`.
- **Dependências (§4.8, R-12):** `qc-dashboard` depende de `streamlit`, `plotly`, `pandas`, `httpx`, `tzdata` (novo, permitido pela §4.8) e `qc-contracts`. `uv.lock` muda só nessa aresta.

## Rastreabilidade (critério de aceite → implementação)

Abreviações de arquivo: `src/` = `dashboard/src/qc_dashboard/`, `views/` = `dashboard/views/`. Testes do autor em `dashboard/tests/`: `A` = `test_api.py`, `C` = `test_config.py`, `F` = `test_formatting.py`, `G` = `test_charts.py`, `M` = `test_model_info.py`, `D` = `test_filters_data.py`, `P` = `test_pages.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `src/api.py` (`ApiClient`, `Filters.to_query`) | `A::test_summary_request_and_model`, `A::test_every_method_hits_its_route`, `A::test_filters_to_query_with_every_field` |
| CA-02 | `src/api.py` (`_get`, `DEFAULT_TIMEOUT`) | `A::test_transport_errors_are_unavailable`, `A::test_gateway_statuses_are_unavailable`, `A::test_default_timeout_is_ten_seconds` |
| CA-03 | `src/api.py` | `A::test_auth_statuses`, `A::test_other_errors_keep_the_status`, `A::test_invalid_body_is_api_error` |
| CA-04 | `src/api.py` (mensagens sem chave, `__repr__`, `from None`) | `A::test_key_never_in_logs_exceptions_or_repr` |
| CA-05 | `app.py`, `src/config.py`, `src/api.py` (`get_client`), `src/filters.py` (`api_guard`) | `P::test_app_without_configuration_shows_error`, `C::test_missing_settings_raise_config_error`, `A::test_get_client_without_settings_raises_config_error` |
| CA-06 | `src/filters.py` (`render_sidebar`, `render_badge`), `views/visao_geral.py` | `P::test_overview_defaults_to_live`, `D::test_badge_real_and_simulated_need_no_request` |
| CA-07 | `src/filters.py` (`needs_simulated_badge`) | `P::test_overview_all_sources_badge`, `P::test_overview_all_sources_without_simulated_data`, `D::test_badge_all_asks_for_simulated_with_same_filters` |
| CA-08 | `src/filters.py`, as 3 páginas de API (ver decisão 2 sobre a carta) | `P::test_filters_persist_across_pages`, `P::test_spc_follows_simulated_sidebar`, `P::test_model_page_simulated_badge` |
| CA-09 | `views/visao_geral.py`, `src/formatting.py` (`fmt_int`, `fmt_pct`, `fmt_decimal`) | `P::test_overview_defaults_to_live`, `F::test_fmt_pct`, `F::test_fmt_numbers` |
| CA-10 | `src/charts.py` (`grade_distribution`, `GRADE_COLORS`) | `G::test_grade_colors`, `G::test_grade_distribution_order_zeros_and_colors` |
| CA-11 | `views/visao_geral.py` (`vg_bucket`), `src/charts.py` (`volume_and_defect_rate`) | `P::test_overview_bucket_day`, `G::test_volume_and_defect_rate_traces`, `G::test_volume_and_defect_rate_day_uses_utc_date` |
| CA-12 | `views/visao_geral.py` | `P::test_overview_empty` |
| CA-13 | `src/filters.py` (`render_api_error`, botão `Tentar novamente`) | `P::test_timeout_then_retry[visao_geral/controle_estatistico/historico]`, `P::test_badge_check_timeout_on_model_page`, `P::test_error_messages` |
| CA-14 | `src/charts.py` (`p_chart`) | `G::test_p_chart`, `G::test_p_chart_title_follows_source`, `G::test_p_chart_without_out_of_control_has_no_annotation` |
| CA-15 | `views/controle_estatistico.py`, `src/api.py` (`spc`) | `P::test_spc_defaults`, `P::test_spc_type_and_max_points`, `A::test_spc_without_object_type_omits_it` |
| CA-16 | `views/controle_estatistico.py` | `P::test_spc_insufficient_data` |
| CA-17 | `views/controle_estatistico.py`, `src/formatting.py` (`spc_rows`) | `P::test_spc_defaults`, `F::test_spc_rows` |
| CA-18 | `views/historico.py` | `P::test_history_table_pagination_and_csv`, `P::test_history_filter_change_resets_offset` |
| CA-19 | `src/formatting.py` (`history_rows`, `fmt_datetime`) | `P::test_history_unknown_simulated_row`, `F::test_history_rows_columns_and_unknown_item`, `F::test_to_local_and_fmt_datetime` |
| CA-20 | `src/formatting.py` (`history_csv`) | `F::test_history_csv` |
| CA-21 | `src/filters.py` (`valid_lot_id`, `render_sidebar`) | `P::test_overview_invalid_lot_is_ignored`, `P::test_overview_valid_lot_is_sent`, `D::test_valid_lot_id` |
| CA-22 | `src/data.py` | `D::test_fetch_summary_is_cached`, `D::test_fetch_spc_and_inspections_are_cached`, `D::test_errors_are_not_cached` |
| CA-23 | `views/sobre_o_modelo.py`, `src/model_info.py` | `P::test_model_page_valid`, `M::test_target_rows`, `M::test_grade_rows_always_five`, `M::test_report_image` |
| CA-24 | `views/sobre_o_modelo.py`, `src/model_info.py` (`load_metrics`) | `P::test_model_page_missing_and_invalid`, `M::test_load_missing_file`, `M::test_load_invalid_metrics` |
| CA-25 | `dashboard/pyproject.toml`, `uv.lock` | Conferido à mão: `uv export --package qc-dashboard --frozen --no-hashes` sem nenhum dos nomes proibidos e o `grep -rIE` do CA sem resultado (exit 1). O teste de raiz `tests/test_dependency_isolation.py` continua passando |
| CA-26 (manual) | — | Não executado por mim (dupla/tester) |
| CA-27 | `views/controle_estatistico.py` | `P::test_spc_cut_notices`, `P::test_spc_no_cut_notices[100-50]`, `P::test_spc_no_cut_notices[None-None]` |
| CA-28 | `src/filters.py` (`source_caption`), `views/visao_geral.py`, `views/historico.py` | `D::test_source_caption`, `P::test_overview_defaults_to_live`, `P::test_overview_all_sources_badge`, `P::test_filters_persist_across_pages`, `P::test_history_table_pagination_and_csv` |
| CA-29 | `views/controle_estatistico.py` | `P::test_spc_simulated_origin`, `P::test_spc_defaults` (caption do período) |
| CA-30 | `src/data.py` (`fetch_spc`) | `P::test_spc_one_request_per_render_and_cache`, `D::test_fetch_spc_and_inspections_are_cached` |
| CA-31 | `views/controle_estatistico.py` (`number_input` 2…500) | `P::test_spc_type_and_max_points` |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run pytest dashboard/tests -q
# painel local, com a API em http://localhost:8001:
uv run --env-file .env --package qc-dashboard streamlit run dashboard/app.py
```

## Notas para o tester

- `dashboard/tests/conftest.py` vale também para `dashboard/tests/acceptance/`. Ele tem um fixture **autouse** que limpa `st.cache_data` e `st.cache_resource` antes e depois de cada teste, e os fixtures opcionais `mock_api` (um `ApiClient` sobre `httpx.MockTransport`, já instalado em `api.get_client`, que registra as requisições), `no_config_env` e `factory` (construtores de `MetricsSummary`, `InspectionRead`, `SpcResponse` e de um `metrics.json` completo). Use-os ou não, como preferir.
- Chaves dos widgets (para `at.radio(key=...)`, `at.session_state[...]`): barra lateral `flt_source` (`Real`/`Simulado`/`Todos`), `flt_period`, `flt_type` (`Todos`/`parafuso`/`porca`/`desconhecido`), `flt_lot`; Visão geral `vg_bucket` (`Minuto`/`Hora`/`Dia`); Controle estatístico `spc_source` (`Real`/`Simulado`), `spc_type` (`Todos`/`parafuso`/`porca`), `spc_baseline_lots`, `spc_min_lot_size`, `spc_max_points`; Histórico `hist_grade`, `hist_defective`, `hist_device`, `hist_page_size` (25/50/100), botões `hist_prev`/`hist_next`; botão de erro `api_retry`. As opções dos widgets são os próprios textos PT-BR (ex.: `set_value("porca")`).
- `AppTest.from_file` resolve caminhos relativos a partir do arquivo de teste; os meus testes usam caminhos absolutos (`dashboard/views/<página>.py` e `dashboard/app.py`). O gráfico Plotly aparece em `at.get("plotly_chart")`, com a figura em JSON em `.proto.spec`.
- Voltar a uma página já vista do Histórico (ex.: `Anterior`) é servido pelo cache, sem requisição nova.

## Decisões tomadas dentro do escopo da SPEC

1. **Onde a configuração é exigida.** O `ConfigError` sai de `api.get_client()` (a primeira leitura da API) e vira `st.error("Configuração ausente: ...")` + `st.stop()` pelo `filters.api_guard()`. Assim, um teste que troca `api.get_client` não precisa definir `API_BASE_URL`/`READ_API_KEY`, e a página "Sobre o modelo", que não lê a API (salvo para o selo com `Todos`), funciona só com `MODEL_METRICS_PATH` (`config.get_model_metrics_path()`). `config.get_settings()` continua levantando `ConfigError` como a §4.1 diz.
2. **Origem da carta × CA-08.** O CA-08 pede que, com `Simulado` na barra lateral, toda página de API faça as requisições com `source=simulated`; a §4.4 e o CA-15 pedem `Real` como padrão da **Origem da carta**. Para atender aos dois, a origem da carta acompanha a barra lateral: na primeira renderização da sessão e sempre que a origem da barra lateral muda, ela vira `Simulado` (se a barra lateral estiver em `Simulado`) ou `Real` (em `Real` ou `Todos`). Com a barra lateral no padrão, o padrão da carta é `Real` (CA-15). A escolha feita na própria página vale enquanto a barra lateral não mudar. `Todos` nunca existe na carta, e continua sendo uma requisição e uma figura por renderização (CA-29). O reviewer pode preferir levar isso ao architect; não registrei como `SPEC_ISSUE` porque nenhum CA fica sem atendimento.
3. **Selo em todas as páginas.** A §4.2 diz "cada página" e o CA-26 diz "em todas as páginas", então "Sobre o modelo" também chama `render_sidebar()` e o selo. Com `Todos`, isso custa a mesma requisição cacheada de `summary`. No Controle estatístico, o selo aparece também quando a origem da carta é `Simulado`. O selo usa os mesmos filtros da página: no Histórico, os globais mais grau, defeituosa e dispositivo.
4. **CA-13 em "qualquer página".** As três páginas de API mostram o aviso e o botão com timeout. "Sobre o modelo" só faz requisição para o selo com `Todos`; nesse caso também mostra o aviso (`P::test_badge_check_timeout_on_model_page`). Com `Real` ou `Simulado` ela não chama a API, então não há o que expirar (o CA-08 já trata essa página como não sendo "de API").
5. **`Filters`** é uma dataclass congelada definida em `api.py` (o cliente a recebe) e reexportada por `filters.py`: `source`, `from_`, `to`, `object_type`, `lot_id`, `device_id`, `grade`, `defective`, todos opcionais; enums aceitam a string; datas exigem fuso e são normalizadas para UTC. `Filters(source="live")` gera só `?source=live`.
6. **`Page[T]` no cache.** O `st.cache_data` faz pickle do retorno, e um `Page[InspectionRead]` parametrizado não é serializável por pickle. O cliente devolve `InspectionPage(Page[InspectionRead])` e `LotPage(Page[LotSummary])`, subclasses vazias, que continuam sendo instâncias de `Page[...]` (`A::test_page_subclasses_survive_pickling`).
7. **Filtro de dispositivo.** A §4.5 diz só "texto". Validei com `DEVICE_ID_PATTERN` (`re.fullmatch`), como o lote: um valor inválido mostra `Dispositivo inválido` e é ignorado, em vez de virar um 422 da API ("Erro da API (HTTP 422)").
8. **Números nas tabelas.** Carta: `p`, `LC`, `LSC`, `LIC` em porcentagem com 1 casa (`16,0%`). Histórico na tela: nota de grau com 2 casas e confianças com 3 (`0,875`). CSV: o valor exato, sem expoente, com vírgula.
9. **"Sem arredondar para cima" (§4.6).** `fmt_truncated` usa `ROUND_FLOOR` em 4 casas (`0.95999` → `0,9599`). Observação para o architect: o CA-25 da SPEC-012 mostra `0.93127` como `0,9313` no CHANGELOG (arredondado), e o painel mostra `0,9312`. Os dois documentos podem divergir na 4ª casa; segui a SPEC-013.
10. **Formato do `metrics.json`.** `load_metrics` exige as 32 chaves de topo da SPEC-012 §4.7 e tolera chaves extras. A tabela por grau lê `grade_per_class` como grau (`perfect`…) → `{precision, recall, f1, support}` e `n_items_test_by_grade` como grau → inteiro, a leitura direta da SPEC-012. Se o formato vier diferente, a tabela continua com 5 linhas e mostra `—`, sem erro. `warnings` não vazio vira uma lista em "Avisos da avaliação". O `model_version` só monta o caminho dos PNGs se casar com `MODEL_VERSION_PATTERN` (não aponta para fora de `ml/reports/`).
11. **Persistência entre páginas.** O Streamlit dá a um widget de outra página uma identidade diferente (inclui o hash da página), então cada widget começa do último valor guardado em `st.session_state["_mem_<key>"]`.
12. **Botão `Tentar novamente`:** `if st.button(...): st.cache_data.clear(); st.rerun()`, como na §4.1. Nada é repetido sozinho (SEC-26-02 de `reviews/SPEC-026/r1-security-report.md`).

## Para a SPEC-015 (deploy)

- `config.REPO_ROOT` é calculado a partir de `dashboard/src/qc_dashboard/config.py` (`parents[3]`), o que vale com a instalação editável do workspace. Se o `dashboard/requirements.txt` instalar o `qc-dashboard` de forma não editável, o padrão de `MODEL_METRICS_PATH` e o caminho dos PNGs apontariam para fora do repositório; nesse caso, use instalação editável ou um `MODEL_METRICS_PATH` absoluto. Não é `SPEC_ISSUE` desta SPEC (a §7 já trata a instalação do pacote como assunto da SPEC-015).
- Para erros que não são da API (bug), o Streamlit mostra o traceback por padrão; `client.showErrorDetails` é configuração de deploy.

## Testes de aceite de SPECs anteriores

Nenhum quebrou: a suíte inteira passa com e sem banco (abaixo). Esta SPEC não altera contrato, API nem banco.

## SPEC_ISSUE (se houver)

Nenhum. As duas tensões de leitura (decisões 2 e 4) foram resolvidas sem deixar CA sem atendimento e estão descritas acima para o reviewer.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos (133 arquivos)
- [x] Testes unitários do autor passando: `dashboard/tests` com 128 testes
- [x] Suíte inteira sem banco (`env -u TEST_DATABASE_URL uv run pytest -q`): 2064 passed, 545 skipped
- [x] Suíte inteira com banco (`TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`): 2609 passed
- [x] O único aviso da suíte é o `StarletteDeprecationWarning` do `fastapi.testclient` (testes da API), anterior a esta SPEC
- [x] `.env.example` atualizado (`API_BASE_URL`, `READ_API_KEY` comentada sem valor, `MODEL_METRICS_PATH`) e `dashboard/README.md` criado
- [x] Nenhuma chave fictícia literal em URL ou header nos testes (geradas com `secrets.token_hex`); nenhum teste roda a suíte em subprocesso; nenhum teste usa a rede
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
