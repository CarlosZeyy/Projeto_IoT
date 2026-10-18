# SPEC-013: Dashboard Streamlit

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r2 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-005, SPEC-006, **SPEC-026** (tem de estar `Done` antes de esta SPEC entrar em `In Dev`: teto da carta p e `qc-contracts` 0.3.0) (e SPEC-002, pelos schemas e rótulos; SPEC-012, pelo formato do `metrics.json`) |
| Semana alvo | S4 |
| Requisitos cobertos | RF-09, RF-10, RF-11, RF-12, RF-13; R-06, R-12 |
| ADRs relevantes | ADR-007, ADR-012, ADR-013, ADR-017, ADR-008 |

## 1. Contexto

O supervisor de qualidade e o avaliador acompanham o processo pelo dashboard (`docs/architecture.md` §1 e §2). Ele roda no Streamlit Community Cloud (SPEC-015) e lê **tudo** pela `qc-api` (SPEC-005 e SPEC-006), com a chave de leitura; nunca acessa o banco. Os payloads são os de `qc_contracts` 0.3.0 (`MetricsSummary`, `TimeseriesPoint`, `SpcResponse`, `LotSummary`, `InspectionRead`, `Page`, `HealthResponse`) e os rótulos PT-BR vêm de `qc_contracts.labels` (ADR-012). A carta p chega cortada nos últimos `max_points` lotes válidos, com `valid_lots_total` e `excluded_lots_total` (ADR-017, SPEC-026, `docs/architecture.md` §3.4). A página "Sobre o modelo" lê o `metrics.json` versionado no repositório (SPEC-012).

## 2. Objetivo

`uv run --package qc-dashboard streamlit run dashboard/app.py` abre um painel de 4 páginas (Visão geral, Controle estatístico, Histórico, Sobre o modelo) que mostra os indicadores da API, com dados simulados sempre sinalizados.

## 3. Escopo

### 3.1 Dentro

- `dashboard/app.py`: `st.set_page_config(page_title="PartQC", layout="wide")` e `st.navigation` com as 4 páginas (títulos com acento); a padrão é Visão geral.
- `dashboard/views/visao_geral.py`, `controle_estatistico.py`, `historico.py`, `sobre_o_modelo.py`.
- `dashboard/src/qc_dashboard/` (layout `src/` da SPEC-001): `config.py` (segredos), `api.py` (cliente HTTP), `data.py` (funções com cache), `filters.py` (barra lateral e selo), `charts.py` (figuras Plotly puras), `formatting.py` (rótulos, números, fuso, CSV), `model_info.py` (`metrics.json` e metas).
- Testes em `dashboard/tests/` e `dashboard/tests/acceptance/test_spec_013.py`.
- `.env.example`: `API_BASE_URL`, `READ_API_KEY` (se ainda não estiver) e `MODEL_METRICS_PATH`, comentados.

### 3.2 Fora

- Deploy, `dashboard/requirements.txt` e secrets no Streamlit CC: SPEC-015.
- Endpoints e cálculo da carta p: SPEC-005 e SPEC-006 (o dashboard não recalcula nada).
- Página "Dispositivos": SPEC-018. Alertas: SPEC-017. Login de usuários: fora do escopo (PRD §4.4).

## 4. Requisitos detalhados

### 4.1 Configuração e cliente da API

- `config.get_settings() -> Settings(api_base_url, read_api_key, model_metrics_path)`: lê `st.secrets` e, se a chave não existir ou não houver arquivo de secrets, as variáveis de ambiente de mesmo nome. Sem `API_BASE_URL` ou `READ_API_KEY` → `ConfigError`, e a página mostra `st.error("Configuração ausente: defina API_BASE_URL e READ_API_KEY.")` e chama `st.stop()`.
- `MODEL_METRICS_PATH`: padrão `ml/models/partqc-mnv3-v1/metrics.json`, relativo à raiz do repositório (resolvida a partir de `dashboard/`).
- `api.ApiClient(base_url, read_api_key, *, timeout=10.0, transport=None)` com `httpx.Client`; header `X-API-Key` em toda chamada; rotas sob `/api/v1`. Métodos: `health()`, `summary(params)`, `timeseries(params, bucket)`, `spc(source, object_type, baseline_lots, min_lot_size, max_points)`, `inspections(params, limit, offset)` (`Page[InspectionRead]`) e `lots(params)` (`Page[LotSummary]`, SPEC-005), devolvendo os modelos de `qc_contracts` (via `model_validate`).
- Erros: timeout, erro de conexão e HTTP 502/503/504 → `ApiUnavailable`; 401/403 → `ApiAuthError`; outro ≥ 400 ou corpo inválido → `ApiError(status)`. A chave nunca aparece em logs, mensagens ou exceções.
- `api.get_client()` (com `st.cache_resource`) é o **único** ponto de criação do cliente; quem o usa o chama como `api.get_client()` (atributo do módulo), o que permite injetar um cliente com `httpx.MockTransport` nos testes.
- `data.py`: uma função por endpoint com `@st.cache_data(ttl=30)`, recebendo só parâmetros hasheáveis (nunca a chave). Exceções não são cacheadas. As páginas leem dados da API **só** por essas funções, inclusive a carta p e a checagem do selo, para que toda leitura passe pelo cache. Assim, o painel não repete as agregações a cada interação, que competem com a ingestão pelo pool da API (SEC-05-01 de `reviews/SPEC-005/r1-security-report.md` e SEC-06-01 de `reviews/SPEC-006/r1-security-report.md`).
- `filters.render_api_error(exc)`: `ApiUnavailable` → `st.warning("API acordando (free tier), tente em ~1 min")` + `st.button("Tentar novamente")` (limpa `st.cache_data` e chama `st.rerun()`); `ApiAuthError` → `st.error("Chave de leitura inválida ou ausente (READ_API_KEY).")`; `ApiError` → `st.error("Erro da API (HTTP <status>).")`; depois `st.stop()`. Nenhum stack trace na tela.

### 4.2 Barra lateral global e selo de simulado (R-06)

- `filters.render_sidebar() -> Filters` (chamada no topo de cada página; valores em `st.session_state`, mantidos entre páginas):
  - **Origem:** rádio `Real` / `Simulado` / `Todos`, padrão **Real** → `source=live` / `simulated` / sem parâmetro;
  - **Período:** intervalo de datas locais (padrão: últimos 7 dias), convertido para `from`/`to` em UTC (início do 1º dia e início do dia seguinte ao último, em `America/Sao_Paulo`);
  - **Tipo:** `Todos`, `parafuso`, `porca`, `desconhecido`;
  - **Lote:** texto opcional; fora de `^[A-Za-z0-9_-]{1,40}$` → `st.sidebar.error("Lote inválido")` e o filtro é ignorado.
- **Selo:** `filters.needs_simulated_badge(filters) -> bool` é verdadeiro se a origem for `Simulado`, ou se for `Todos` e `summary` com os mesmos filtros e `source=simulated` tiver `total > 0`. Quando verdadeiro, cada página mostra no topo `st.warning("Contém dados simulados")` (o texto exato é verificado nos testes) e uma legenda igual na barra lateral.
- **Origem sempre visível** (R-06; INFO-01 de `reviews/SPEC-005/r1-security-report.md`): sem `source`, o resumo e a série somam as duas origens, e a resposta não diz quais entraram. Por isso, `filters.source_caption(filters) -> str` devolve `Origem dos dados: real`, `Origem dos dados: simulado` ou `Origem dos dados: todas (real + simulado)`, e a Visão geral e o Histórico mostram esse texto com `st.caption` logo abaixo do título, **sempre**, com ou sem o selo.

### 4.3 Visão geral (`views/visao_geral.py`)

- KPIs (`st.metric`): `Inspeções` (`total`), `Taxa de defeito` (`defect_rate`, ex.: `12,5%`), `Desconhecidos` (`unknown_count`), `Para revisão` (`needs_review_count`), `Grau médio` (`mean_grade_score`, 2 casas, ajuda "0 = perfeito … 4 = inutilizável"); `null` → `—`.
- `charts.grade_distribution(by_grade)`: barras com os 5 graus **sempre** na ordem perfeito → inutilizável (zeros incluídos), rótulos PT-BR, cor por grau (§4.7) e o valor escrito sobre cada barra.
- `charts.by_object_type(by_object_type)`: barras horizontais (parafuso, porca, desconhecido).
- `charts.volume_and_defect_rate(points, bucket)`: 2 painéis com eixo x compartilhado: barras `Inspeções` (`total`) e linha `Taxa de defeito` (%). Seletor `Minuto` / `Hora` / `Dia` (padrão `Hora`) → `bucket=minute|hour|day`.
- `total == 0` → `st.info("Nenhuma inspeção encontrada para os filtros selecionados.")` e nenhum gráfico.

### 4.4 Controle estatístico (`views/controle_estatistico.py`)

- Controles: **Origem da carta** `Real` (padrão) / `Simulado` (R-06: o SPC usa `live` por padrão; `Todos` não existe aqui); **Tipo** `Todos` / `parafuso` / `porca` (`unknown` nunca entra no SPC); `baseline_lots` (2–100, padrão 20); `min_lot_size` (1–500, padrão 5) — as faixas aceitas pela SPEC-006; **Lotes na carta** (`max_points`, 2–500, padrão 100), a faixa da SPEC-026. Origem `Simulado` → selo de §4.2.
- **Uma carta, uma origem** (R-06; INFO-02 de `reviews/SPEC-006/r1-security-report.md`): a página faz **uma** requisição ao SPC por renderização, com uma única `source`, e desenha **uma** figura. As cartas `live` e `simulated` nunca aparecem sobrepostas na mesma figura nem lado a lado na mesma página.
- A carta usa toda a história da origem escolhida (ADR-017): o **Período** da barra lateral não se aplica aqui, e a página diz isso com `st.caption("A carta p usa todo o histórico da origem escolhida; o período da barra lateral não se aplica.")`.
- **Carta cortada** (ADR-017): se `valid_lots_total` não for `null` e for maior que `len(points)`, a página mostra `st.caption("Mostrando os últimos <len(points)> de <valid_lots_total> lotes válidos. A linha central usa os primeiros <baseline_lots> lotes válidos do histórico.")`. Com `null` (API anterior à 0.3.0), nenhum aviso de corte é mostrado.
- `charts.p_chart(spc) -> go.Figure`, com título `Carta p — origem: <rótulo>` (`SOURCE_LABELS_PT[spc.source]`, ex.: `Carta p — origem: simulado`) e x = `lot_id` na ordem dos `points`:
  - `p do lote`: linhas + marcadores;
  - `LC`: `cl` de cada ponto (= `p_bar`);
  - `LSC` e `LIC`: `ucl` e `lcl` por lote, com `line_shape="hv"` e traço tracejado;
  - `Fora de controle`: só os pontos com `out_of_control`, marcador vermelho `#D62728`, símbolo `diamond`, tamanho 12, e uma anotação com o `lot_id` por ponto;
  - eixos `Lote (ordem de início)` e `Proporção de defeituosos (p)` (formato %); hover em PT-BR com lote, n, defeituosas, p, LSC, LIC, início e fim (hora local).
- Tabela: `Lote`, `Início`, `Fim`, `n`, `Defeituosas`, `p`, `LC`, `LSC`, `LIC`, `Fora de controle` (`Sim`/`Não`).
- `excluded_lots` não vazio → `st.info("Lotes excluídos (n < <min_lot_size>): L-009 (n=3), ...")`. Se `excluded_lots_total` não for `null` e for maior que `len(excluded_lots)`, a mensagem termina, depois de um espaço, com `e mais <excluded_lots_total − len(excluded_lots)> lote(s) excluído(s) mais antigo(s).`
- `points == []` → `st.info("Dados insuficientes para a carta p: são necessários pelo menos 2 lotes com n ≥ <min_lot_size>.")` e nenhum gráfico (a `message` da API não é mostrada crua, por estar em inglês).

### 4.5 Histórico (`views/historico.py`)

- Filtros da página, somados aos globais: **Grau** (`Todos` + 5), **Defeituosa** (`Todos`/`Sim`/`Não` → `defective`), **Dispositivo** (texto). Tamanho de página 25/50/100 (padrão 50). Botões `Anterior`/`Próxima` e a legenda `Página X de Y — Z inspeções`. Mudar qualquer filtro volta ao `offset=0`.
- Tabela com as colunas, nesta ordem: `Data/hora`, `Lote`, `Dispositivo`, `Tipo`, `Grau`, `Nota de grau`, `Conf. tipo`, `Conf. grau`, `Revisão`, `Defeituosa`, `Origem`, `Modelo`. Rótulos PT-BR (`GRADE_LABELS_PT`, `OBJECT_TYPE_LABELS_PT`, `SOURCE_LABELS_PT`); booleanos `Sim`/`Não`; `null` → `—`.
- `formatting.history_csv(items) -> bytes`: as mesmas colunas, `utf-8-sig`, separador `;`, vírgula decimal, data/hora ISO 8601 com o fuso de São Paulo, vazio no lugar de `—`. `st.download_button("Baixar CSV (página atual)", file_name="partqc_historico_p<página>.csv")`.
- Página vazia → `st.info("Nenhuma inspeção encontrada.")`.

### 4.6 Sobre o modelo (`views/sobre_o_modelo.py`)

- `model_info.load_metrics(path) -> dict` valida as chaves de topo da SPEC-012 §4.7 (inclusive `grade_qwk_ci95`, `unusable_recall_ci95`, `defective_recall_ci95`, `n_items_test_by_grade` e `warnings`). Arquivo ausente → `st.info("Nenhum modelo avaliado ainda: metrics.json não encontrado em <path>.")`; JSON inválido ou chave faltando → `st.error("metrics.json inválido: <motivo>")`.
- Cabeçalho: versão, `sha256` (12 primeiros caracteres), data da avaliação (hora local) e arquivo do split.
- Tabela "Métricas × metas do PRD" (`model_info.PRD_TARGETS`): `type_accuracy` ≥ 0,95; `grade_qwk` ≥ 0,75; `grade_off_by_one_accuracy` ≥ 0,90; `unusable_recall` ≥ 0,90; `defective_recall` ≥ 0,90; `latency_ms_p95` ≤ 300. Status `Atingida` / `Abaixo da meta` / `—` (null). Em seguida, as demais métricas sem meta e a tabela por grau com os 5 graus. Valores com 4 casas e vírgula decimal, sem arredondar para cima.
- Imagens `ml/reports/<model_version>/type_confusion.png` e `grade_confusion.png`, se existirem; senão, `st.caption("Imagem não disponível")`.
- Legenda fixa: "Métricas medidas no conjunto de teste, que não é usado para nenhuma escolha (R-11). As metas do PRD são iniciais."

### 4.7 Visual e acessibilidade

- Cores por grau, iguais em todo o painel (`charts.GRADE_COLORS`): perfeito `#1A9850`, bom `#66BD63`, mediano `#E0B000`, ruim `#F46D43`, inutilizável `#A50026`. Tipos em cores neutras (`#4C78A8`, `#72B7B2`, `#9D9D9D`). A cor nunca é o único canal: valores escritos nas barras e símbolo próprio nos pontos fora de controle.
- Eixos, legendas, títulos e mensagens em PT-BR; números com vírgula decimal (`formatting.fmt_pct(0.125) == "12,5%"`).
- Datas: UTC no transporte; conversão para `America/Sao_Paulo` **só** na interface (`formatting.to_local`), formato `dd/mm/aaaa HH:MM`. Com `bucket=day`, o eixo mostra a data UTC e o título indica `(UTC)`.

### 4.8 Dependências (R-12)

`qc-dashboard` depende só de `streamlit`, `plotly`, `pandas`, `httpx` e `qc-contracts` (e `tzdata`, se necessário). Proibidos: torch, torchvision, timm, onnxruntime, `qc-ml`, psycopg, SDK do Supabase ou qualquer acesso direto ao banco.

## 5. Critérios de aceite

Nos testes de página, `api.get_client` é substituído por um `ApiClient` com `httpx.MockTransport`, que devolve respostas montadas com os modelos de `qc_contracts` e registra as requisições; `st.cache_data` é limpo antes de cada teste.

- **CA-01** — *Dado* `ApiClient("https://api.test", "k-123", transport=mock)`, *quando* `summary(Filters(source="live"))` é chamado, *então* a requisição é `GET https://api.test/api/v1/metrics/summary?source=live` com o header `X-API-Key: k-123`, e o retorno é um `MetricsSummary`.
- **CA-02** — *Dado* um transporte que levanta `httpx.ReadTimeout` (ou responde 503), *quando* qualquer método é chamado, *então* levanta `ApiUnavailable`; o `timeout` do cliente é 10,0 s.
- **CA-03** — *Dado* respostas 401, 500 e 200 com corpo `{"foo": 1}`, *quando* `summary` é chamado, *então* levanta, respectivamente, `ApiAuthError`, `ApiError(status=500)` e `ApiError`.
- **CA-04 (R-03)** — *Dado* `caplog` em `DEBUG` e a chave `k-secret-123`, *quando* uma chamada com sucesso e outra com 401 são feitas, *então* o texto `k-secret-123` não aparece nos logs nem em `str()` das exceções.
- **CA-05** — *Dado* nenhum secret e nenhuma variável `API_BASE_URL`/`READ_API_KEY`, *quando* `AppTest.from_file("dashboard/app.py")` roda, *então* há um `st.error` com `Configuração ausente`, nenhuma requisição e nenhuma exceção.
- **CA-06 (R-06)** — *Dado* uma sessão nova, *quando* a Visão geral é renderizada, *então* a origem selecionada é `Real`, toda requisição registrada tem `source=live` e não há `st.warning` com `Contém dados simulados`.
- **CA-07 (R-06)** — *Dado* a origem `Todos` e o mock respondendo `total=12` para `source=simulated`, *quando* a Visão geral é renderizada, *então* há um `st.warning` com o texto `Contém dados simulados`; *dado* `total=0` para `simulated`, *então* esse aviso não aparece.
- **CA-08 (R-06)** — *Dado* a origem `Simulado` na barra lateral, *quando* qualquer uma das páginas de API é renderizada, *então* o aviso `Contém dados simulados` aparece e as requisições têm `source=simulated`.
- **CA-09** — *Dado* `MetricsSummary(total=40, defective=5, defect_rate=0.125, unknown_count=3, needs_review_count=4, mean_grade_score=1.8456, ...)`, *quando* a Visão geral é renderizada, *então* os 5 `st.metric` mostram `40`, `12,5%`, `3`, `4` e `1,85`.
- **CA-10** — *Dado* `by_grade={"good": 10, "perfect": 5}`, *quando* `charts.grade_distribution` é chamada, *então* o eixo x é `["perfeito", "bom", "mediano", "ruim", "inutilizável"]`, y é `[5, 10, 0, 0, 0]` e as cores seguem `GRADE_COLORS` na mesma ordem.
- **CA-11** — *Dado* o seletor de granularidade em `Dia`, *quando* a página é renderizada, *então* a requisição de série temporal tem `bucket=day`, e a figura tem os traços `Inspeções` (barras) e `Taxa de defeito` (linha).
- **CA-12** — *Dado* `total=0`, *quando* a Visão geral é renderizada, *então* aparece `Nenhuma inspeção encontrada para os filtros selecionados.` e nenhum gráfico Plotly.
- **CA-13** — *Dado* um transporte que levanta `httpx.ReadTimeout`, *quando* qualquer página é renderizada, *então* aparece o aviso `API acordando (free tier), tente em ~1 min` e um botão `Tentar novamente`, e `at.exception` está vazio; ao clicar no botão com a API já respondendo, os dados aparecem.
- **CA-14** — *Dado* um `SpcResponse` com 4 pontos (`L-001`…`L-004`, `p_bar=0.18`, `source="live"`) em que só `L-003` tem `out_of_control=true`, *quando* `charts.p_chart` é chamada, *então* o traço `Fora de controle` tem `x == ["L-003"]` e cor `#D62728`, há exatamente 1 anotação com o texto `L-003`, `LSC` e `LIC` têm `line.shape == "hv"` e y iguais a `ucl` e `lcl`, todos os y de `LC` são 0,18, e o título da figura é `Carta p — origem: real`.
- **CA-15** — *Dado* os controles padrão, *quando* a página de controle estatístico é renderizada, *então* a requisição é `GET /api/v1/metrics/spc` com `source=live`, `baseline_lots=20`, `min_lot_size=5`, `max_points=100` e sem `object_type` nem `from`/`to`; com o tipo `porca`, inclui `object_type=nut`.
- **CA-16** — *Dado* `points=[]` e `p_bar=null`, *quando* a página é renderizada, *então* aparece um `st.info` com `pelo menos 2 lotes` e nenhum gráfico Plotly.
- **CA-17** — *Dado* `excluded_lots=[{"lot_id": "L-009", "n": 3}]`, *quando* a página é renderizada, *então* um `st.info` contém `L-009 (n=3)`; e a tabela tem 4 linhas, com `Sim` em `Fora de controle` só para `L-003`.
- **CA-18** — *Dado* uma `Page` com `total=120` e `limit=50`, *quando* o Histórico é renderizado e `Próxima` é clicado, *então* a legenda inicial contém `Página 1 de 3`, as colunas são exatamente as de §4.5 e a requisição seguinte tem `offset=50`.
- **CA-19** — *Dado* um item com `object_type=unknown`, `grade=null`, `source=simulated` e `inspected_at=2026-11-03T15:00:00Z`, *quando* o Histórico é renderizado, *então* a linha mostra `desconhecido`, `—`, `simulado` e `03/11/2026 12:00`.
- **CA-20** — *Dado* 2 itens, um com `type_confidence=0.875`, *quando* `history_csv` é chamada, *então* os bytes começam com o BOM UTF-8, a 1ª linha é o cabeçalho de §4.5 separado por `;`, há 2 linhas de dados, o valor aparece como `0,875` e a data como `2026-11-03T12:00:00-03:00`.
- **CA-21** — *Dado* o lote `L 01` (com espaço) na barra lateral, *quando* a página é renderizada, *então* aparece `Lote inválido` e nenhuma requisição contém `lot_id`.
- **CA-22** — *Dado* duas chamadas a `data.fetch_summary` com os mesmos filtros em menos de 30 s, *quando* executadas, *então* o transporte recebe 1 requisição; depois de `st.cache_data.clear()`, recebe outra.
- **CA-23** — *Dado* `MODEL_METRICS_PATH` apontando para um `metrics.json` válido com `type_accuracy=0.96` e `grade_qwk=0.70` e sem PNGs, *quando* "Sobre o modelo" é renderizada, *então* a linha de acurácia de tipo tem `Atingida`, a de QWK tem `Abaixo da meta` e `0,7000`, a tabela por grau tem 5 linhas e aparece `Imagem não disponível`.
- **CA-24** — *Dado* `MODEL_METRICS_PATH` para um arquivo inexistente e, depois, para um arquivo com `{"x": 1}`, *quando* a página é renderizada, *então* aparece `Nenhum modelo avaliado ainda` e, no segundo caso, `metrics.json inválido`.
- **CA-25 (R-12)** — *Dado* o `uv.lock`, *quando* `uv export --package qc-dashboard --frozen --no-hashes` roda, *então* a saída não contém `torch`, `torchvision`, `timm`, `onnxruntime`, `qc-ml`, `psycopg` nem `supabase`; e `grep -rIE "psycopg|DATABASE_URL|supabase|onnxruntime|import torch" dashboard --exclude-dir=tests` não encontra nada.
- **CA-26 (manual)** — 1. Subir a API local com dados de `scripts/simulate.py` (SPEC-014) e de algumas inspeções `live`; 2. rodar o dashboard local; 3. conferir que, com a origem `Todos`, o aviso de simulado aparece em todas as páginas; 4. conferir a carta p com pelo menos um ponto vermelho e anotado; 5. abrir no celular (largura ~400 px) e conferir que KPIs e gráficos ficam legíveis. Resultado registrado no test-report.
- **CA-27 (ADR-017)** — *Dado* um `SpcResponse` com 100 pontos, `valid_lots_total=130`, `baseline_lots=20`, `excluded_lots` com 50 itens e `excluded_lots_total=60`, *quando* a página de controle estatístico é renderizada, *então* há um `st.caption` com `Mostrando os últimos 100 de 130 lotes válidos` e o `st.info` dos excluídos termina com `e mais 10 lote(s) excluído(s) mais antigo(s).`; *dado* o mesmo `SpcResponse` com `valid_lots_total=100` (ou `null`) e `excluded_lots_total=50` (ou `null`), *então* nenhum desses dois textos aparece.
- **CA-28 (R-06, origem sempre visível)** — *Dado* a origem `Real`, depois `Simulado` e depois `Todos` (com `total=0` para `simulated`, de modo que o selo não apareça), *quando* a Visão geral e o Histórico são renderizados, *então* cada um mostra um `st.caption` com, respectivamente, `Origem dos dados: real`, `Origem dos dados: simulado` e `Origem dos dados: todas (real + simulado)`.
- **CA-29 (R-06, uma carta por origem)** — *Dado* a origem da carta `Simulado`, *quando* a página de controle estatístico é renderizada, *então* o transporte registra exatamente 1 requisição a `/api/v1/metrics/spc`, com `source=simulated`; a página tem exatamente 1 gráfico Plotly; o título da figura é `Carta p — origem: simulado`; e aparece o `st.caption` que diz que o período da barra lateral não se aplica.
- **CA-30 (cache da carta)** — *Dado* os controles padrão, *quando* a página de controle estatístico é renderizada duas vezes em menos de 30 s, *então* o transporte recebe 1 requisição a `/api/v1/metrics/spc`; depois de `st.cache_data.clear()`, recebe outra.
- **CA-31 (`max_points`)** — *Dado* o controle **Lotes na carta** em `10`, *quando* a página é renderizada, *então* a requisição tem `max_points=10`; e o controle não aceita valores fora de 2…500.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Cliente (MockTransport), formatação, fuso, CSV, figuras, `load_metrics` | `dashboard/tests/` |
| Aceite (tester) | Um por CA; páginas com `streamlit.testing.v1.AppTest` e cliente mockado; figuras pelas funções de `charts` | `dashboard/tests/acceptance/test_spec_013.py` |
| Manual (dupla) | CA-26 | descrito no CA |

Só a fronteira HTTP é mockada. Nenhum teste acessa a internet nem a API real.

## 7. Riscos e notas para o implementador

- O cold start do Render (cerca de 1 min) estoura o timeout de 10 s: é o caso do aviso "API acordando". Não aumente o timeout para mascarar isso.
- A checagem do selo com `Todos` custa 1 requisição a mais (cacheada); é o preço da R-06.
- `st.navigation` exige uma versão recente do Streamlit; fixe-a pelo `uv.lock`. Os testes de página usam `AppTest.from_file` direto em cada arquivo de `views/`.
- As metas de `PRD_TARGETS` repetem as da SPEC-012 (o dashboard não pode importar `qc_ml`, que traz onnxruntime). Mudou a meta no PRD → mude nos dois lugares.
- Com o layout `src/`, as páginas em `dashboard/views/` importam `qc_dashboard` como pacote instalado; no Streamlit CC isso depende de o `dashboard/requirements.txt` (SPEC-015) instalar o próprio `qc-dashboard`. Se não instalar, registre `SPEC_ISSUE`; não mova o código para fora de `src/`.
- Se o `metrics.json` da versão atual ainda não existir no repositório (antes do treino v1), a página mostra o estado vazio; isso não é erro.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `.env.example` e README do dashboard atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-17 | Mudanças: (a) passa a depender da SPEC-026, que tem de estar `Done` antes de esta SPEC entrar em `In Dev`, e cita o ADR-017; (b) §1: contrato 0.3.0 e carta cortada; (c) §4.1: `spc(...)` ganha `max_points`, e as páginas leem dados só pelas funções cacheadas de `data.py`; (d) §4.2: legenda de origem sempre visível na Visão geral e no Histórico; (e) §4.4: controle **Lotes na carta** (`max_points`, 2–500, padrão 100), título da figura com a origem, uma carta e uma requisição por origem, aviso de carta cortada, total de excluídos e aviso de que o período não se aplica à carta; (f) CA-14 e CA-15 alterados (título; `max_points=100` e sem `from`/`to`); CAs novos CA-27 a CA-31. Nenhum outro CA muda. SPEC marcada como "Aguardando reaprovação humana". | SEC-06-01 e INFO-02 de `reviews/SPEC-006/r1-security-report.md`; SEC-05-01 e INFO-01 de `reviews/SPEC-005/r1-security-report.md`; ADR-017 | Orquestrador, a pedido do humano |
| 2026-10-17 | Alteração reaprovada pelo humano. | Aprovação humana | Humano (Carlos) |
