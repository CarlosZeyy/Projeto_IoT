# SPEC-028: Manutenção do dashboard (https, acabamento da interface, selo da carta e exibição das métricas)

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-013 (`Done`) |
| Semana alvo | S4 (antes da SPEC-015, recomendado) |
| Requisitos cobertos | RF-09, RF-11, RF-12; R-03, R-06, R-11, R-12 |
| ADRs relevantes | ADR-007, ADR-012, ADR-017 |

## 1. Contexto

Fecha as pendências de código do dashboard deixadas pelos portões da SPEC-013 (`reviews/SPEC-013/r1-review-report.md`, `r2-review-report.md` e `r2-security-report.md`), que foi mergeada com elas registradas. O dashboard continua como em `docs/architecture.md` §1 e §2: lê tudo pela `qc-api`, com a chave de leitura, e nunca acessa o banco (ADR-007). Esta SPEC altera requisitos da SPEC-013 (§4.1, §4.2, §4.4, §4.6 e §4.7); onde ela não diz nada, vale a SPEC-013.

| Pendência | Severidade | O que entra aqui |
|---|---|---|
| SEC-13-01 | média | `API_BASE_URL` precisa ser `https://`, salvo `http://` em `localhost`/`127.0.0.1` (§4.1) |
| RV-08 (= T-03) | média | Sem a barra de ferramentas do Plotly, que cobre o título das figuras em aparelhos de toque (§4.5) |
| RV-09 (= T-04) | baixa | Último rótulo de data da série temporal sem corte (§4.5) |
| RV-04 (= O-01), mais a sugestão do `r2-review-report` | baixa | Na página da carta, o selo segue só a origem da carta, e a origem aparece também num `st.caption` fora da figura (§4.3) |
| RV-05 | baixa | "Sobre o modelo" mostra as métricas mesmo quando a checagem do selo pela API falha (§4.4) |
| RV-07 | baixa | Regra única de exibição das métricas, a mesma do CHANGELOG da SPEC-012 (`docs/architecture.md` §7) (§4.4) |
| SEC-13-02 | baixa | "Tentar novamente" não limpa o cache de todas as sessões (§4.2) |
| SEC-13-03 | baixa | Caminho do `metrics.json` relativo ao repositório na mensagem pública (§4.4) |
| SEC-13-04 | baixa | Execução local com `.streamlit/secrets.toml`, e não com o `.env` completo (§4.6) |
| SEC-13-05 | info | `max_entries` no cache (§4.2) |
| SEC-13-08 | info | `report_image` confere que o caminho fica dentro de `ml/reports/` (§4.4) |

Ficam **sem mudança**, por decisão registrada:

- **SEC-26-02 (parte do dashboard):** o 503 de uma consulta cancelada pelo `statement_timeout` já cai no aviso "API acordando" sem repetição em laço (verificado no `r2-security-report` da SPEC-013). O texto do aviso não muda.
- **SEC-13-06, SEC-13-07 e SEC-13-09:** sem ação (a origem dos dados é validada pelo contrato e pelo banco; o `showErrorDetails` é da SPEC-015 §4.4).
- **RV-10:** os testes do RV-03 da SPEC-013 usam atributos privados do Streamlit; ficam como estão (nota na §7).

**Por que uma SPEC nova.** O dashboard já foi entregue e não há outra SPEC planejada para ele antes da Fase 2. A SPEC-015 é do `security-devops`, cuja lista de caminhos permitidos não inclui `dashboard/src/` nem `dashboard/README.md` (SPEC-015 §7).

## 2. Objetivo

O dashboard recusa uma `API_BASE_URL` que mandaria a chave em claro, as figuras não têm título nem rótulo cobertos ou cortados no celular, a página da carta sinaliza exatamente a origem da figura, a página "Sobre o modelo" funciona sem a API e mostra as métricas pela mesma regra do CHANGELOG.

## 3. Escopo

### 3.1 Dentro

- `dashboard/src/qc_dashboard/config.py`: checagem do esquema de `API_BASE_URL` e `InsecureApiUrlError` (§4.1).
- `dashboard/src/qc_dashboard/filters.py`: mensagem de configuração inválida, botão "Tentar novamente" sem limpar o cache e selo da página da carta (§4.1 a §4.3).
- `dashboard/src/qc_dashboard/data.py`: `max_entries` (§4.2).
- `dashboard/src/qc_dashboard/formatting.py` e `model_info.py`: regra de exibição, caminho relativo e `report_image` (§4.4).
- `dashboard/src/qc_dashboard/charts.py`: margem da série temporal (§4.5).
- `dashboard/views/visao_geral.py`, `controle_estatistico.py` e `sobre_o_modelo.py`: `config` dos gráficos, selo e legenda da carta, página sem a API (§4.3 a §4.5).
- `dashboard/README.md`, `.env.example` (bloco do dashboard) e `.gitignore` (`.streamlit/secrets.toml`) (§4.6).
- Testes do autor em `dashboard/tests/` (fora de `acceptance/`); o autor ajusta os próprios testes que verificavam o `st.cache_data.clear()` do botão, o selo da carta pela barra lateral ou o corte das métricas em que menor é melhor.
- **Tester desta SPEC:** `dashboard/tests/acceptance/test_spec_028.py` e, em `dashboard/tests/acceptance/test_spec_013.py`, só este ajuste (aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10):
  1. `test_extra_real_api_end_to_end`, no laço "Step 3": para `SPC_PAGE`, a asserção do selo com a origem `Todos` passa a exigir a **ausência** do aviso `Contém dados simulados` e a presença do `st.caption` `Origem da carta: real` (a carta segue em `Real` com a barra lateral em `Todos`; §4.3). Para `HISTORY` e `MODEL_PAGE`, nada muda.

  Nenhuma outra linha desse arquivo muda, e nenhum `test_caNN_` da SPEC-013 tem a intenção alterada. Se outro teste antigo falhar por um requisito escrito aqui, vale a regra de §10, com o registro na tabela do test-report.

### 3.2 Fora

- Deploy, `.streamlit/config.toml`, `dashboard/requirements.txt`, instalação editável do `qc-dashboard` e o `https://` nos Secrets do Streamlit CC → SPEC-015.
- Texto do aviso "API acordando" e tratamento do 503: sem mudança (§1).
- Página "Dispositivos" → SPEC-018. Alertas → SPEC-017.
- Mudanças na API ou no contrato (`LotId` nos modelos de resposta, SEC-13-06): não adotadas.

## 4. Requisitos detalhados

### 4.1 `API_BASE_URL` só com `https://` (SEC-13-01, R-03)

- `config.get_settings()`, depois de ler `API_BASE_URL` e `READ_API_KEY` (SPEC-013 §4.1), confere a URL com `urllib.parse.urlsplit`. Ela é aceita se, e só se:
  - o esquema (que o `urlsplit` devolve em minúsculas) é `https` e há um host não vazio; **ou**
  - o esquema é `http` e o host (`.hostname`) é exatamente `localhost` ou `127.0.0.1`, a mesma regra do `scripts/simulate.py` e do `scripts/smoke_test.py` (SPEC-015 §4.5).
- Qualquer outro valor (`http://` com outro host, inclusive `[::1]`; `ftp://`; sem esquema; `https://` sem host) → `InsecureApiUrlError`, subclasse de `ConfigError`, cuja mensagem cita só o nome `API_BASE_URL`, nunca o valor.
- A página mostra `st.error("Configuração inválida: API_BASE_URL precisa usar https:// (http:// só em localhost ou 127.0.0.1).")` e chama `st.stop()`, sem criar o cliente e sem nenhuma requisição. A falta de variável continua com a mensagem `Configuração ausente` da SPEC-013.
- A checagem fica em `get_settings()`, não no `ApiClient`: os testes continuam podendo criar um `ApiClient` com qualquer URL e `httpx.MockTransport`.

### 4.2 Cache e botão "Tentar novamente" (SEC-13-02, SEC-13-05)

- O botão "Tentar novamente" de `filters.render_api_error` passa a chamar **só** `st.rerun()`. Ele não chama `st.cache_data.clear()`: as exceções não são cacheadas (SPEC-013 §4.1), então a nova tentativa já vai à API, e as leituras com sucesso das outras sessões e da própria página continuam no cache. Isso substitui o "(limpa `st.cache_data` e chama `st.rerun()`)" da SPEC-013 §4.1.
- Toda função de `data.py` passa a ser `@st.cache_data(ttl=30, max_entries=256, show_spinner=False)`. Pela documentação, "When a new entry is added to a full cache, the oldest cached entry will be removed" (<https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data>, consultado pelo architect em 2026-10-17). O TTL já limitava a memória a uma janela de 30 s; o teto fecha o caso de muitos filtros diferentes nessa janela.

### 4.3 Página da carta: selo e origem (RV-04, RV-08)

- Na página "Controle estatístico", o selo (o `st.warning("Contém dados simulados")` no topo e a legenda na barra lateral) aparece **se, e só se**, a origem da carta for `Simulado`. Ele não depende mais da origem da barra lateral nem de `needs_simulated_badge`, e a página não faz a checagem do selo pela API (nenhuma requisição a `/api/v1/metrics/summary`). Isso substitui, só nesta página, o "cada página" da SPEC-013 §4.2; a carta continua tendo uma única origem por renderização (SPEC-013 §4.4, R-06).
- A página mostra **sempre**, logo abaixo do título, `st.caption("Origem da carta: <rótulo>")`, com `SOURCE_LABELS_PT[spc.source]` (`real` ou `simulado`), fora da figura. Assim, a origem não depende de nada que a renderização do Plotly possa sobrepor.
- A regra da SPEC-013 de que a origem da carta acompanha a barra lateral (`Simulado` na barra → carta `Simulado`; `Real` ou `Todos` → carta `Real`, decisão 2 do dev-report r1 da SPEC-013) continua, e fica escrita aqui: numa sessão nova, a carta começa em `Real`; o usuário pode trocá-la no rádio "Origem da carta".

### 4.4 "Sobre o modelo" (RV-05, RV-07, SEC-13-03, SEC-13-08)

- **Sem a API (RV-05):** com a origem `Todos`, se a checagem do selo pela API falhar (`ApiUnavailable`, `ApiAuthError`, `ApiError` ou `ConfigError`), a página mostra a mesma mensagem de erro da SPEC-013 §4.1 (inclusive o botão "Tentar novamente" no caso de `ApiUnavailable`) **e** o selo `Contém dados simulados` (por conservadorismo, R-06), e **continua** com o cabeçalho, as tabelas e as imagens, que vêm de arquivos locais. Nessa página, a falha não chama `st.stop()`. Com `Real` ou `Simulado`, a página continua sem nenhuma requisição.
- **Exibição das métricas (RV-07):** todo valor de métrica da página segue a regra de `docs/architecture.md` §7, "Exibição das métricas" (a mesma do CHANGELOG da SPEC-012): 4 casas e vírgula decimal, calculadas a partir de `Decimal(repr(valor))`; corte para baixo (`ROUND_FLOOR`) nas métricas em que maior é melhor; arredondamento para cima (`ROUND_CEILING`) nas métricas em que menor é melhor (`grade_mae`, `false_unknown_rate`, `needs_review_rate`, `latency_ms_p50` e `latency_ms_p95`); nos ICs 95%, `low` para baixo e `high` para cima; inteiros sem casas. O status (`Atingida`/`Abaixo da meta`) continua usando o valor bruto. A lista de direções fica em `model_info` (o dashboard não importa `qc_ml`, R-12); mudou a lista em `architecture.md` §7, muda aqui e na SPEC-012.
- **Caminho na mensagem (SEC-13-03):** em `Nenhum modelo avaliado ainda: metrics.json não encontrado em <path>.`, o `<path>` é o caminho **relativo** à raiz do repositório (`config.REPO_ROOT`), com `/`, quando o arquivo resolvido fica dentro dela; e o caminho absoluto só quando fica fora (por exemplo, um `MODEL_METRICS_PATH` absoluto em outro disco).
- **`report_image` (SEC-13-08):** devolve `None` (e a página mostra `Imagem não disponível`) se o `model_version` não casar `MODEL_VERSION_PATTERN` com `re.fullmatch`, se for formado só por pontos, ou se `(<ml/reports> / model_version / name).resolve()` não estiver dentro de `<ml/reports>.resolve()` (`Path.is_relative_to`). A docstring passa a dizer exatamente isso.

### 4.5 Figuras no celular (RV-08, RV-09)

- Os 4 `st.plotly_chart` (`visao_geral.py`: distribuição por grau, por tipo e série temporal; `controle_estatistico.py`: carta p) recebem `config={"displayModeBar": False}`. A SPEC-013 não pede zoom nem exportação de PNG; o botão de tela cheia do Streamlit fica na barra do elemento e continua.
- Na figura da série temporal (`charts.volume_and_defect_rate`), `layout.margin.r` passa de 10 para **60** px, para que o último rótulo `dd/mm/aaaa HH:MM` caiba; nas outras figuras, a margem não muda. O formato das datas (SPEC-013 §4.7) não muda.

### 4.6 Execução local sem o `.env` completo (SEC-13-04)

- `dashboard/README.md`: a execução local recomendada passa a ser com um arquivo `.streamlit/secrets.toml` na raiz do repositório, só com `API_BASE_URL` e `READ_API_KEY`. O Streamlit lê esse arquivo de `$CWD/.streamlit/secrets.toml`, onde `$CWD` é a pasta de onde se roda o `streamlit run` (<https://docs.streamlit.io/develop/concepts/connections/secrets-management>, consultado pelo architect em 2026-10-17). O README mostra o comando a partir da raiz (`uv run --package qc-dashboard streamlit run dashboard/app.py`) e não usa mais `--env-file .env`, que carregaria também `DATABASE_URL` e `DEVICE_API_KEY` no processo do dashboard.
- `.gitignore` ganha `.streamlit/secrets.toml` (se a SPEC-015 ainda não o tiver acrescentado; a `.streamlit/config.toml` da SPEC-015 continua versionada).
- `.env.example`: o comentário do bloco do dashboard diz que, localmente, essas variáveis vão em `.streamlit/secrets.toml`, e que o `.env` único não deve ser usado para o dashboard.

## 5. Critérios de aceite

Contexto comum: como na SPEC-013 (§5): `api.get_client` substituído por um `ApiClient` com `httpx.MockTransport`, que registra as requisições; `st.cache_data` limpo antes de cada teste; chaves geradas no teste (`secrets.token_urlsafe`), nunca literais.

- **CA-01 (security, SEC-13-01)** — *Dado* `READ_API_KEY` definida e `API_BASE_URL` igual a `http://api.example.org`, `http://[::1]:8001`, `ftp://api.example.org`, `api.example.org`, `https://` ou `https:///x`, *quando* `config.get_settings()` é chamado, *então* levanta `InsecureApiUrlError` (instância de `ConfigError`), e a mensagem contém `API_BASE_URL` e não contém `example.org`; e, *quando* a Visão geral é renderizada com o mesmo valor, *então* há um `st.error` com `Configuração inválida: API_BASE_URL precisa usar https://`, o transporte registra 0 requisições e `at.exception` está vazio. *Dado* `https://api.example.org`, `HTTPS://api.example.org/`, `http://localhost:8001` ou `http://127.0.0.1:8001`, *então* `get_settings()` devolve as configurações sem erro.
- **CA-02 (RV-08)** — *Dado* os controles padrão e dados com pelo menos 1 inspeção e 2 lotes válidos, *quando* a Visão geral e a página de controle estatístico são renderizadas, *então* há 4 elementos `plotly_chart` no total (3 e 1) e o `config` de cada um (no proto do elemento) tem `displayModeBar` igual a `false`.
- **CA-03 (RV-09)** — *Dado* uma série com 3 pontos em `bucket=hour`, *quando* `charts.volume_and_defect_rate` é chamada, *então* `fig.layout.margin.r == 60`; e `charts.grade_distribution`, `charts.by_object_type` e `charts.p_chart` continuam com `margin.r == 10`.
- **CA-04 (R-06, RV-04)** — *Dado* o mock respondendo `total=12` para `summary(source=simulated)`, *quando* a página de controle estatístico é renderizada (a) com a barra lateral em `Todos`, (b) com a barra lateral em `Simulado` e (c) com a barra lateral em `Simulado` e o rádio "Origem da carta" trocado para `Real`, *então*: em (a) e (c), não há `st.warning` com `Contém dados simulados`, há o `st.caption` `Origem da carta: real` e a requisição ao SPC tem `source=live`; em (b), há o aviso, o `st.caption` `Origem da carta: simulado` e a requisição tem `source=simulated`; e, nos três casos, o transporte não registra nenhuma requisição a `/api/v1/metrics/summary`.
- **CA-05 (RV-05)** — *Dado* um `metrics.json` válido (o do CA-23 da SPEC-013) e a origem `Todos` na barra lateral, *quando* "Sobre o modelo" é renderizada com o transporte levantando `httpx.ReadTimeout`, *então* há o aviso `API acordando (free tier), tente em ~1 min`, o botão `Tentar novamente`, o aviso `Contém dados simulados`, a tabela de metas com `Atingida` na linha de acurácia de tipo e a tabela por grau com 5 linhas, e `at.exception` está vazio; *dado* o transporte respondendo 401, *então* há o `st.error` de chave inválida e as mesmas tabelas.
- **CA-06 (R-11, RV-07)** — *Dado* um `metrics.json` válido com `type_accuracy=0.93127`, `grade_qwk=0.75`, `grade_mae=0.12341`, `latency_ms_p95=120.00001`, `false_unknown_rate=0.02` e `grade_qwk_ci95=[0.61239, 0.78761]`, *quando* "Sobre o modelo" é renderizada (origem `Real`), *então* aparecem `0,9312` (acurácia, `Abaixo da meta`), `0,7500` (QWK, `Atingida`), `0,1235` (MAE), `120,0001` (latência p95, `Atingida`), `0,0200` e `[0,6123; 0,7877]` (IC do QWK).
- **CA-07 (SEC-13-02)** — *Dado* a Visão geral com o mock respondendo o resumo e levantando `httpx.ReadTimeout` só na série temporal, e um espião em `st.cache_data.clear`, *quando* a página é renderizada, o mock passa a responder a série e o botão `Tentar novamente` é clicado, *então* o espião tem 0 chamadas, a nova renderização faz 0 requisições a `/api/v1/metrics/summary` (o resumo continua no cache) e 1 a `/api/v1/metrics/timeseries`, e a figura da série aparece.
- **CA-08 (SEC-13-05)** — *Dado* 257 chamadas a `data.fetch_summary` com 257 filtros diferentes (lotes `L-000` a `L-256`) em menos de 30 s, *quando* `fetch_summary` é chamada de novo com o filtro de `L-000`, *então* o transporte recebe uma nova requisição (a entrada mais antiga saiu do cache); e uma nova chamada com o filtro de `L-256` não gera requisição.
- **CA-09 (SEC-13-03)** — *Dado* `MODEL_METRICS_PATH=ml/models/nao-existe-v0/metrics.json` (relativo, dentro do repositório, inexistente), *quando* "Sobre o modelo" é renderizada, *então* aparece exatamente `Nenhum modelo avaliado ainda: metrics.json não encontrado em ml/models/nao-existe-v0/metrics.json.` e o texto da página não contém `str(config.REPO_ROOT)`; *dado* um caminho absoluto inexistente em `tmp_path` (fora do repositório), *então* a mensagem mostra esse caminho absoluto.
- **CA-10 (SEC-13-08)** — *Dado* `config.REPO_ROOT` apontando (no teste) para um diretório temporário com `ml/reports/partqc-ok-v1/type_confusion.png` e com um link simbólico `ml/reports/partqc-link-v1` para um diretório fora de `ml/reports/` que também tem `type_confusion.png`, *quando* `report_image` é chamada, *então* devolve o caminho para `"partqc-ok-v1"` e `None` para `"partqc-link-v1"`, `"..."` e `"../x"`.
- **CA-11 (SEC-13-04)** — *Dado* `dashboard/README.md`, `.env.example` e `.gitignore`, *então* o README contém `.streamlit/secrets.toml` e nenhuma linha dentro de bloco de código contém `--env-file .env`; `git check-ignore .streamlit/secrets.toml` o ignora e `.streamlit/config.toml` não é ignorado; e o bloco do dashboard no `.env.example` (as linhas de comentário imediatamente acima de `API_BASE_URL=`) contém `.streamlit/secrets.toml`.
- **CA-12 (manual)** — Dashboard local, depois desta SPEC: 1. API local com dados de `scripts/simulate.py` e algumas inspeções `live`; 2. dashboard local com `.streamlit/secrets.toml`; 3. num celular (largura ~400 px, sem mouse), abrir a Visão geral com `Hora` e com `Minuto` e a página da carta: nenhuma barra de ferramentas do Plotly aparece, o título `Carta p — origem: real` aparece inteiro e o último rótulo de data da série não é cortado; 4. repetir o passo 3 num navegador de desktop com 1280 px; 5. com a barra lateral em `Todos`, conferir que a página da carta mostra `Origem da carta: real` e não mostra o selo, e que as demais páginas mostram o selo; 6. registrar o resultado (aparelho, navegador, data e quem executou) no test-report.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Esquema da URL (tabela de casos), botão sem `clear`, `max_entries`, selo e legenda da carta, página do modelo sem a API, regra de exibição (direções e IC), caminho relativo, `report_image`, `config` dos gráficos, margem | `dashboard/tests/` |
| Aceite (tester) | Um por CA automatizável; mais o ajuste da §3.1 | `dashboard/tests/acceptance/test_spec_028.py` e `test_spec_013.py` |
| Manual (dupla) | CA-12 | celular e desktop |

Só a fronteira HTTP é mockada (`httpx.MockTransport`), como na SPEC-013. O CA-10 cria o link simbólico em `tmp_path`. Nenhum teste acessa a internet nem a API real. O `config` do `plotly_chart` é lido do proto do elemento no `AppTest` (`at.get("plotly_chart")[i].proto.config`, um JSON).

## 7. Riscos e notas para o implementador

- **Regra de exibição e floats:** a conversão parte de `Decimal(repr(valor))`, como o `fmt_truncated` de hoje. Numa métrica em que menor é melhor, um valor como `0.30000000000000004` aparece como `0,3001`; isso é aceito, porque a direção é a conservadora (nunca a favor da meta).
- **Selo da carta:** a página não chama mais `needs_simulated_badge`. Não troque a regra das outras páginas (Visão geral e Histórico continuam com o selo pelos filtros globais, CA-07 e CA-08 da SPEC-013).
- **`st.stop()` em "Sobre o modelo":** só a checagem do selo deixa de parar a página. Um `metrics.json` ausente ou inválido continua como na SPEC-013 §4.6.
- **RV-10 da SPEC-013:** os testes do RV-03 usam `policies._shown_default_value_warning`, `policies._LOGGER` e `policies.check_session_state_rules`, que são privados do Streamlit 1.65.0 (fixado no `uv.lock`). Se uma atualização do Streamlit quebrá-los com `AttributeError`, a causa é a API privada, não uma regressão. Esta SPEC não atualiza o Streamlit.
- **CA-26 da SPEC-013 (manual, pendente):** o passo 3 dele ("com a origem `Todos`, o aviso de simulado aparece em todas as páginas") descreve o comportamento de antes desta SPEC. Se for executado depois do merge desta, vale o passo 5 do CA-12 daqui para a página da carta.
- **Margem de 60 px:** é a menor que o reviewer da SPEC-013 estimou para o rótulo de 16 caracteres. Se o CA-12 mostrar corte com 60 px, registre `SPEC_ISSUE` com a largura medida, em vez de trocar o formato da data (SPEC-013 §4.7).

## 8. Definição de pronto

- [ ] Todos os CAs automatizados com teste de aceite passando (test-report PASS) e o CA-12 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `dashboard/README.md`, `.env.example` e `.gitignore` atualizados
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | SPEC criada (`Draft`). | RV-04, RV-05 e RV-07 de `reviews/SPEC-013/r1-review-report.md`; RV-08, RV-09 e RV-10 de `reviews/SPEC-013/r2-review-report.md`; SEC-13-01 a SEC-13-05 e SEC-13-08 de `reviews/SPEC-013/r2-security-report.md`; SEC-26-02 (parte do dashboard, sem mudança) de `reviews/SPEC-026/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-18 | `Draft` → `Ready`. Aprovação humana. | Aprovação humana | Humano (Carlos) |
