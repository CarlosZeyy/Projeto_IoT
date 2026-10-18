# SPEC-028 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-028](../../docs/specs/SPEC-028-manutencao-dashboard.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-028-manutencao-dashboard` |
| Commits | `95177e6`, `0813f47`, `879dd0d`, `9cdd4dd`, `2ad0de7` (e o commit deste relatório) |

## Resumo

Fecha as pendências de código do dashboard deixadas pela SPEC-013. `get_settings()` recusa uma `API_BASE_URL` sem `https://` (salvo `http://` em `localhost`/`127.0.0.1`) com `InsecureApiUrlError`, e as páginas mostram `Configuração inválida` sem nenhuma requisição. O botão "Tentar novamente" só chama `st.rerun()`, e as leituras de `data.py` têm `max_entries=256`. Na página da carta, o selo segue só a origem da carta, sem requisição de selo, e `Origem da carta: <rótulo>` aparece logo abaixo do título. "Sobre o modelo" continua com as tabelas quando a checagem do selo falha, mostra as métricas pela regra de `docs/architecture.md` §7, mostra o caminho relativo na mensagem de arquivo ausente e confina o `report_image` a `ml/reports/`. As 4 figuras ficam sem a barra do Plotly, e a série ganha `margin.r = 60`. README e `.env.example` passam a recomendar o `.streamlit/secrets.toml`.

Nenhuma dependência nova, nenhum `uv.lock` alterado, `packages/contracts` intocado, nenhum arquivo em `tests/acceptance/` criado ou alterado.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (SEC-13-01) | `dashboard/src/qc_dashboard/config.py` (`is_secure_api_url`, `InsecureApiUrlError`, `INSECURE_API_URL_MESSAGE`); `filters.py` (`show_config_error`, `api_guard`) | `test_config.py::test_insecure_api_url_is_refused` (12 casos, inclusive os 6 do CA), `::test_secure_api_url_is_accepted` (os 4 do CA e mais 3), `::test_insecure_url_from_secrets_is_refused`, `::test_missing_key_wins_over_insecure_url`, `::test_insecure_message_text`; `test_pages.py::test_insecure_url_stops_api_pages` (3 páginas, 0 requisições), `::test_insecure_url_on_the_app`, `::test_localhost_http_is_accepted_by_the_pages` |
| CA-02 (RV-08) | `charts.py` (`PLOTLY_CONFIG`, `plotly_config()`); `views/visao_geral.py`, `views/controle_estatistico.py` | `test_pages.py::test_every_chart_hides_the_mode_bar` (3 + 1, `proto.config`); `test_charts.py::test_plotly_config_hides_the_mode_bar` |
| CA-03 (RV-09) | `charts.py` (`SERIES_MARGIN_RIGHT = 60`, `MARGIN_RIGHT = 10`, `volume_and_defect_rate`) | `test_charts.py::test_series_right_margin_fits_the_last_date_label` |
| CA-04 (R-06, RV-04) | `filters.py` (`render_chart_badge`, `spc_origin_caption`, `show_badge`); `views/controle_estatistico.py` | `test_pages.py::test_spc_badge_ignores_all_sources_sidebar` (a), `::test_spc_badge_with_simulated_chart` (b e c), `::test_spc_origin_caption_is_right_under_the_title`, `::test_spc_origin_caption_stays_when_the_api_fails`; `test_filters_data.py::test_chart_badge_follows_only_the_chart_origin`, `::test_spc_origin_caption` |
| CA-05 (RV-05) | `filters.py` (`render_badge_or_error`, `show_error`, `show_api_error`); `views/sobre_o_modelo.py` | `test_pages.py::test_model_page_without_api_timeout` (com o "Tentar novamente" clicado), `::test_model_page_without_api_errors` (401 e 500), `::test_model_page_without_configuration` (ausente e insegura), `::test_model_page_real_or_simulated_needs_no_api`; `test_filters_data.py::test_badge_or_error_does_not_raise_and_is_conservative`, `::test_badge_or_error_without_configuration` |
| CA-06 (R-11, RV-07) | `formatting.py` (`fmt_quantized`, `fmt_rounded_up`, `fmt_truncated`); `model_info.py` (`LOWER_IS_BETTER`, `fmt_metric(value, key)`, `target_rows`, `other_metric_rows`) | `test_pages.py::test_model_page_display_rule` (os valores exatos do CA); `test_model_info.py::test_lower_is_better_list_matches_architecture`, `::test_lower_is_better_metrics_round_up`, `::test_higher_is_better_metrics_round_down`, `::test_interval_is_never_narrower`, `::test_rows_use_the_direction_of_each_metric`, `::test_status_uses_the_raw_value`; `test_formatting.py::test_fmt_rounded_up_never_rounds_down`, `::test_fmt_quantized_modes` |
| CA-07 (SEC-13-02) | `filters.py` (`_retry` só com `st.rerun()`) | `test_pages.py::test_retry_keeps_the_cache` (espião em `st.cache_data.clear`, 0 resumos e 1 série na nova renderização); `test_filters_data.py::test_retry_only_reruns` |
| CA-08 (SEC-13-05) | `data.py` (`CACHE_MAX_ENTRIES = 256` nas 6 funções) | `test_filters_data.py::test_full_cache_drops_the_oldest_entry` (257 lotes), `::test_every_cached_read_has_max_entries` |
| CA-09 (SEC-13-03) | `model_info.py` (`display_path`); `views/sobre_o_modelo.py` | `test_pages.py::test_model_page_missing_file_relative_path`, `::test_model_page_missing_file_absolute_path`; `test_model_info.py::test_display_path_relative_inside_the_repository`, `::test_display_path_absolute_outside_the_repository`, `::test_display_path_follows_the_patched_root` |
| CA-10 (SEC-13-08) | `model_info.py` (`report_image`) | `test_model_info.py::test_report_image_refuses_links_out_of_reports` (link para fora, `...`, `../x`, `..`, `.`), `::test_report_image_refuses_a_file_link_out_of_reports`, `::test_report_image` (o da SPEC-013) |
| CA-11 (SEC-13-04) | `dashboard/README.md`, `.env.example`; `.gitignore` já tinha `.streamlit/secrets.toml` (linha 18) | Sem teste do autor (é texto); conferido à mão: `git check-ignore -v .streamlit/secrets.toml` → `.gitignore:18`, `git check-ignore .streamlit/config.toml` → código 1 (não ignorado), nenhum `--env-file .env` no README, e as linhas de comentário imediatamente acima de `API_BASE_URL=` citam `.streamlit/secrets.toml` |
| CA-12 (manual) | — | Passos abaixo, para a dupla |

### CA-12 (manual): passos

1. Subir a API local (`uv run --package qc-api uvicorn qc_api.main:app --reload --port 8001`) com dados de `scripts/simulate.py` e algumas inspeções `live`.
2. Na raiz do repositório, criar `.streamlit/secrets.toml` só com `API_BASE_URL = "http://localhost:8001"` e `READ_API_KEY = "<a chave de leitura da API>"`, e rodar, a partir da raiz, `uv run --package qc-dashboard streamlit run dashboard/app.py`. Conferir que o `.env` **não** foi carregado (o comando não tem `--env-file`).
3. Num celular (largura de ~400 px, sem mouse), abrir a Visão geral com a granularidade `Hora` e depois com `Minuto`, e a página "Controle estatístico". Conferir que nenhuma barra de ferramentas do Plotly aparece, que o título `Carta p — origem: real` aparece inteiro e que o último rótulo de data da série (`dd/mm/aaaa HH:MM`) não é cortado.
4. Repetir o passo 3 num navegador de desktop com 1280 px.
5. Com a barra lateral em `Todos` (e dados simulados no período), conferir que a página da carta mostra `Origem da carta: real` logo abaixo do título e **não** mostra `Contém dados simulados`, e que a Visão geral, o Histórico e "Sobre o modelo" mostram o selo.
6. Registrar no test-report o aparelho, o navegador, a data e quem executou. Se o último rótulo ainda for cortado com 60 px, registrar a largura medida como `SPEC_ISSUE` (§7 da SPEC), sem trocar o formato da data.

## Testes de aceite de SPECs anteriores que falham por requisito desta SPEC

Regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10. Não editei nenhum deles (R-07).

| Arquivo | Teste | Asserção que falha | Requisito que a invalida |
|---|---|---|---|
| `dashboard/tests/acceptance/test_spec_013.py` | `test_extra_real_api_end_to_end` (marcador `db`; só roda com `TEST_DATABASE_URL`) | No laço "Step 3", para `SPC_PAGE` com a barra lateral em `Todos`: `assert contains(values(at.main.warning), BADGE), path.stem` | §4.3 (o selo da página da carta aparece se, e só se, a carta for `Simulado`; com `Todos`, a carta segue em `Real`) e CA-04 (a). É exatamente o ajuste já previsto na §3.1, item 1: para `SPC_PAGE`, exigir a ausência do aviso e a presença do `st.caption` `Origem da carta: real`. Para `HISTORY` e `MODEL_PAGE`, a asserção continua passando |

Nenhum outro teste de aceite falha. Conferi em especial os que tocam o comportamento alterado e que **continuam passando**: `test_ca08_simulated_sidebar_on_every_api_page` (a carta segue `Simulado` com a barra lateral em `Simulado`), `test_ca29_one_chart_one_origin`, `test_ca13_model_page_badge_check_timeout` (o aviso e o botão continuam, com 1 requisição), `test_ca24_missing_and_invalid_metrics` (o caminho em `tmp_path` fica fora do repositório e continua absoluto), `test_extra_four_places_never_rounded_up` (o QWK é "maior é melhor", corte para baixo), `test_extra_retry_while_still_down_is_bounded` (`<= 2` tentativas; o comentário "after clearing the cache" ficou desatualizado, mas a asserção continua válida) e `test_extra_settings_from_environment` (`http://localhost:8001` é aceito).

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest dashboard/tests -q
# suíte inteira, sem banco e com banco + CI:
uv run pytest -q
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultados nesta máquina (antes do commit deste relatório):

- `uv run ruff check .`: `All checks passed!`; `uv run ruff format --check .`: `148 files already formatted`.
- `uv run pytest -q` sem `TEST_DATABASE_URL` e sem `CI`: 3160 passed, 643 skipped, 0 failed.
- `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q`: 3802 passed, **1 failed** (`test_extra_real_api_end_to_end`, o da tabela acima), 0 skipped.
- `uv run pytest dashboard -q` sem banco: 336 passed, 1 skipped (o `db`).

## Decisões tomadas dentro do escopo da SPEC

1. **Mensagens de configuração separadas.** `api_guard` passa o `ConfigError` para `show_config_error`, que mostra `INSECURE_API_URL_MESSAGE` para `InsecureApiUrlError` e `CONFIG_MISSING_MESSAGE` para o resto. Com `READ_API_KEY` ausente **e** uma URL insegura, vale `Configuração ausente` (a falta de variável é checada primeiro, como a §4.1 diz: "A falta de variável continua com a mensagem `Configuração ausente`"). A exceção tem texto fixo em inglês, só com o nome da variável (logs e código em inglês, ADR-012); o texto PT-BR da tela vem da constante.
2. **`urlsplit` que levanta `ValueError`** (ex.: `http://[::1`) conta como URL recusada (`InsecureApiUrlError`), e não como erro inesperado. A SPEC manda recusar "qualquer outro valor".
3. **Erros sem `st.stop()`.** `render_api_error` virou `show_api_error` + `st.stop()`; `render_badge_or_error` (usada só em "Sobre o modelo") chama `render_badge` e, se a checagem falhar com `ConfigError`, `ApiUnavailable`, `ApiAuthError` ou `ApiError`, mostra a mesma mensagem de `api_guard` (inclusive o botão "Tentar novamente" no `ApiUnavailable`) e o selo, e devolve o controle à página. As outras páginas continuam com `api_guard`.
4. **Legenda da carta antes e depois da leitura.** A legenda `Origem da carta` fica num `st.empty()` criado logo depois do título. Ela é escrita com a origem escolhida antes da leitura e reescrita com `SOURCE_LABELS_PT[spc.source]` depois dela. Assim, a origem continua visível mesmo quando a API falha ("sempre", §4.3), e o texto final é o do `spc.source`, como a SPEC pede. O selo da carta sai do `api_guard`, porque não faz requisição.
5. **`PLOTLY_CONFIG` em `charts.py`.** O `config` dos 4 gráficos é uma constante única (`MappingProxyType`) com `plotly_config()`, que devolve uma cópia, em vez de 4 dicionários literais nas páginas. É apresentação de figura, como o resto de `charts.py`, que continua sem Streamlit.
6. **Margem da série.** `_base_layout` continua com 10 px (`MARGIN_RIGHT`), e `volume_and_defect_rate` sobrescreve só `margin.r` para 60 (`SERIES_MARGIN_RIGHT`) depois dela. As outras margens da série não mudam.
7. **Regra de exibição.** `fmt_metric(value, key)` decide a direção pela chave (`LOWER_IS_BETTER`). Sem chave (as precisões, os recalls e os F1 da tabela por grau), o corte é para baixo, porque todas são "maior é melhor". Os ICs usam `low` para baixo e `high` para cima, qualquer que seja a chave. `support` e `latency_runs` continuam com `fmt_int`, como na SPEC-013. `fmt_truncated` foi mantida (agora delega para `fmt_quantized` com `ROUND_FLOOR`).
8. **`display_path`.** Resolve o caminho (`config.resolve_repo_path` + `Path.resolve()`) e, se ele cair dentro de `config.REPO_ROOT.resolve()`, devolve o relativo em `as_posix()`. Fora do repositório, devolve o caminho absoluto como foi configurado (sem `resolve()`), o mesmo texto da SPEC-013 para um caminho absoluto, que é o que o CA-24 da SPEC-013 e o CA-09 desta SPEC comparam.
9. **`report_image`.** A ordem é: tipo e `re.fullmatch(MODEL_VERSION_PATTERN)`, só pontos, `resolve().is_relative_to(<ml/reports>.resolve())` e, por fim, `is_file()`. Devolve o caminho sem `resolve()` (`ml/reports/<versão>/<nome>`), como antes. Um link simbólico que continua dentro de `ml/reports/` é aceito, e um link de **arquivo** para fora é recusado (testado).
10. **Isolamento dos testes do autor do `.streamlit/secrets.toml` local.** O README agora recomenda esse arquivo na raiz do repositório, que é a pasta de onde o pytest roda, e o Streamlit o leria nos testes. O `conftest.py` do autor ganhou um fixture autouse que troca `st.secrets` por um objeto "sem arquivo de secrets", mas **só fora de `tests/acceptance/`** (o fixture confere `request.node.path`), para não mexer no ambiente dos testes do tester. O `MockApi` do autor ganhou `timing_out` (rotas que dão timeout enquanto as outras respondem), usado no teste do CA-07.
11. **README sem nomes da lista do CA-25 da SPEC-013.** O CA-25 faz `grep` de `DATABASE_URL` (entre outros nomes) em todo o `dashboard/`, README incluído. Por isso o README fala em "connection string do banco e a chave do dispositivo de borda", sem os nomes das variáveis. O `.env.example`, que fica fora de `dashboard/`, cita `DATABASE_URL` e `DEVICE_API_KEY`, como a §4.6 pede. O exemplo de `secrets.toml` no README traz `READ_API_KEY = ""`, sem valor, nem placeholder que um scanner pudesse confundir com chave.

## Notas para o tester e o reviewer

- **CA-01 na página:** a checagem fica em `get_settings()`, que só é chamada por `api.get_client()`. Um teste que troque `api.get_client` por um cliente fixo nunca chega à checagem. Para o CA-01 na Visão geral, deixe o `get_client` real e intercepte a rede (por exemplo, `httpx.HTTPTransport.handle_request` ou `httpx.Client.send`, como o CA-05 da SPEC-013), ou envolva o mock chamando `config.get_settings()` antes. Meus testes usam a primeira opção.
- **`.streamlit/secrets.toml` local:** com esse arquivo na raiz (como o README recomenda) e o pytest rodando da raiz, os testes de aceite que dependem de "sem configuração" (ex.: o CA-05 da SPEC-013) podem passar a ler o arquivo: o `_isolated` deles troca `HOME` e o CA-05 faz `chdir`, mas o `st.secrets` guarda o conteúdo depois da primeira leitura no processo, então, se outro teste já o tiver lido a partir da raiz, o `chdir` posterior não o isola (o caminho `$CWD/.streamlit/secrets.toml` é calculado na leitura, conferi com `config.get_option("secrets.files")`). No CI não há esse arquivo. Fica a sugestão de isolar `st.secrets` no fixture do tester, se ele quiser blindar os testes na máquina da dupla.
- **CA-04 (a):** com a barra lateral em `Todos` e a carta em `Real`, a página não chama mais `needs_simulated_badge`. Por isso a legenda da barra lateral também não aparece (o selo é o par `st.warning` + `st.sidebar.caption`, §4.3).

## SPEC_ISSUE

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando (`dashboard/tests`, fora de `acceptance/`)
- [x] `.env.example` atualizado (nenhuma variável nova; comentário do bloco do dashboard atualizado, §4.6)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma credencial literal em URL, conninfo ou header nos testes (chaves por `secrets.token_hex`; URLs de teste sem userinfo)
- [x] Nenhum teste roda a suíte em subprocesso; nenhum teste depende de internet (só `httpx.MockTransport` e `httpx.Client.send` interceptado)
- [x] R-12: nenhuma dependência nova no `qc-dashboard`; `uv.lock` intocado
