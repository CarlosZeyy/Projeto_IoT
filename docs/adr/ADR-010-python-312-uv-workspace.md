# ADR-010: Usar Python 3.12 em todo o projeto, com um workspace uv e um único `uv.lock`

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-004, ADR-006, ADR-007, ADR-008, ADR-015, SPEC-001, SPEC-002, SPEC-015, R-12 |

## Contexto

O projeto tem seis pacotes Python com dependências muito diferentes: a API e o dashboard são leves; a borda usa onnxruntime; o ML usa torch e timm. Eles compartilham `qc-contracts` e `qc-preprocess`. Restrições de versão do Python, todas verificadas em 2026-10-12:

| Biblioteca | Python suportado | Fonte |
|---|---|---|
| Google Colab (runtime gratuito) | 3.12.x | <https://research.google.com/colaboratory/runtime-version-faq.html> |
| torch 2.14.1 | 3.10–3.14 | <https://pypi.org/project/torch/> |
| onnxruntime 1.31 | ≥ 3.11 | <https://pypi.org/project/onnxruntime/> |
| timm | classificadores até 3.12 | <https://pypi.org/project/timm/> |
| streamlit 1.65 | 3.10–3.14 | <https://pypi.org/project/streamlit/> |

O notebook da equipe roda Arch Linux, cujo Python do sistema é o 3.14. Usar o Python do sistema faria o ambiente local divergir do Colab.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Python 3.12 gerenciado pelo **uv**, com workspace na raiz (membros `packages/contracts`, `packages/preprocess`, `api`, `edge`, `dashboard`, `ml`) e um único `uv.lock` | Mesma versão do Colab; uma resolução de dependências para tudo; pacotes locais instalados como editáveis; `uv sync --package` instala só o necessário; o uv baixa o 3.12 sem mexer no Python do sistema | A equipe precisa aprender o uv; o Streamlit CC e o Render não leem o `uv.lock` nativamente (é preciso exportar ou instalar o uv no build) |
| B pip + `requirements.txt` por pasta | Universal; zero ferramenta nova | Versões divergentes entre pastas; sem lock transitivo; pacotes locais compartilhados são frágeis |
| C Poetry | Lock e grupos de dependências | Suporte a monorepo/workspace limitado; mais lento; não gerencia a versão do Python |
| D conda | Bom para pilhas de ML | Pesado para a API e o dashboard; não combina com o build do Render; dois gerenciadores convivendo |

## Decisão

Todo o projeto usa **Python 3.12**, instalado e fixado pelo **uv** (`.python-version` e `requires-python = ">=3.12,<3.13"`). A raiz é um **workspace uv** com os seis membros acima e um **`uv.lock` único e versionado**. torch, torchvision e timm ficam no **extra opcional `train`** do `qc-ml`; o CI instala o workspace sem esse extra.

## Consequências

- **Positivas:**
  - ambiente reproduzível com `uv sync` (RNF-08);
  - o CI fica leve, porque não baixa o torch;
  - um contrato único (`qc-contracts`) importado por todos sem publicar no PyPI.
- **Negativas / custos aceitos:**
  - o Streamlit CC recebe um `dashboard/requirements.txt` gerado por `uv export` (`docs/deployment-plan.md` §4), que precisa ser regenerado a cada mudança;
  - quem treina localmente precisa pedir o extra `train` explicitamente.
- **O que passa a ser obrigatório:**
  - um teste de CI que inspeciona as dependências resolvidas de `qc-api` e `qc-dashboard` e falha se aparecer torch, torchvision, timm ou onnxruntime (R-12, SPEC-001);
  - todo `pyproject.toml` declara `requires-python` compatível só com 3.12;
  - mudanças de dependência vêm com o `uv.lock` atualizado no mesmo commit;
  - o build do Render usa `uv sync --package qc-api --frozen --no-dev`;
  - o Python do sistema (3.14) nunca é usado para rodar o projeto.

## Quando revisitar

- Se o Colab passar a usar uma versão de Python diferente da 3.12.
- Se o onnxruntime ou o timm deixarem de oferecer suporte ao 3.12.
- Se o Streamlit CC não conseguir instalar `qc-contracts` a partir do `requirements.txt` exportado (SPEC-015).
