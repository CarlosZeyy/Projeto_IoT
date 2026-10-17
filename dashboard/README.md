# qc-dashboard

Painel Streamlit do PartQC (SPEC-013, ADR-007). Lê **todos** os dados pela `qc-api`, com a chave de leitura no header `X-API-Key`, e nunca acessa o banco. Os rótulos em PT-BR vêm de `qc_contracts.labels` (ADR-012).

## Páginas

| Página | Arquivo | O que mostra |
|---|---|---|
| Visão geral (padrão) | `views/visao_geral.py` | KPIs, distribuição por grau e por tipo, volume e taxa de defeito no tempo |
| Controle estatístico | `views/controle_estatistico.py` | Carta p por lote de **uma** origem (ADR-013, ADR-017) e tabela dos lotes |
| Histórico | `views/historico.py` | Inspeções paginadas, filtros da página e CSV da página atual |
| Sobre o modelo | `views/sobre_o_modelo.py` | `metrics.json` do modelo contra as metas do PRD (SPEC-012) |

A barra lateral (origem, período, tipo e lote) vale para todas as páginas e é mantida ao trocar de página. A origem padrão é **Real**. Com `Simulado`, ou com `Todos` quando há dados simulados nos filtros, cada página mostra o aviso `Contém dados simulados` (R-06). A Visão geral e o Histórico sempre dizem a origem em vigor logo abaixo do título.

A carta p usa toda a história da origem escolhida: o período da barra lateral não se aplica a ela. A origem da carta acompanha a da barra lateral (`Simulado` lá → `Simulado` aqui; `Real` ou `Todos` → `Real`), e pode ser trocada na própria página.

## Configuração

| Variável | Obrigatória | Descrição |
|---|---|---|
| `API_BASE_URL` | sim | URL base da `qc-api` (ex.: `http://localhost:8001`) |
| `READ_API_KEY` | sim | Chave de leitura (segredo; o mesmo valor configurado na API) |
| `MODEL_METRICS_PATH` | não | `metrics.json` da página "Sobre o modelo"; relativo à raiz do repositório ou absoluto. Padrão: `ml/models/partqc-mnv3-v1/metrics.json` |

Cada valor é lido de `st.secrets` (em produção, Streamlit → Secrets; SPEC-015) e, se a chave não existir lá ou não houver arquivo de secrets, da variável de ambiente de mesmo nome. Sem `API_BASE_URL` ou `READ_API_KEY`, as páginas que leem a API mostram `Configuração ausente` e param. Nunca coloque a chave no Git (R-03).

## Rodar localmente

```bash
uv sync --all-packages
# com a API rodando em http://localhost:8001 (ver api/):
uv run --env-file .env --package qc-dashboard streamlit run dashboard/app.py
```

## Comportamento com a API

- Todas as leituras passam pelas funções de `qc_dashboard.data`, com cache de 30 s (`st.cache_data`). Erros não são cacheados.
- Timeout (10 s), erro de conexão ou HTTP 502/503/504: aviso `API acordando (free tier), tente em ~1 min` e o botão `Tentar novamente`, que limpa o cache e recarrega a página. Nada é repetido automaticamente.
- HTTP 401/403: `Chave de leitura inválida ou ausente (READ_API_KEY).` Outros erros: `Erro da API (HTTP <status>).` Nenhum stack trace na tela, e a chave nunca aparece em log ou mensagem.

## Estrutura

```text
app.py                     st.navigation com as 4 páginas
views/                     uma página por arquivo
src/qc_dashboard/
  config.py                secrets e variáveis de ambiente
  api.py                   cliente HTTP (ApiClient, Filters, erros, get_client)
  data.py                  leituras com cache, uma por endpoint
  filters.py               barra lateral, selo de simulado, mensagens de erro
  charts.py                figuras Plotly puras
  formatting.py            rótulos, números, fuso, CSV
  model_info.py            metrics.json e metas do PRD
tests/                     testes do autor (tests/acceptance/ é do tester)
```

## Dependências (R-12)

Só `streamlit`, `plotly`, `pandas`, `httpx`, `tzdata` e `qc-contracts`. Nada de torch, timm, runtime de inferência, `qc-ml`, driver de banco ou SDK do provedor do banco.

## Testes

```bash
uv run pytest dashboard/tests -q
```

As páginas são testadas com `streamlit.testing.v1.AppTest`, com `api.get_client` trocado por um `ApiClient` sobre `httpx.MockTransport`. Nenhum teste acessa a rede.
