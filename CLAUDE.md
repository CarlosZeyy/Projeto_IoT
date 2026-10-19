# PartQC — Inspeção visual de qualidade (IoT + Cloud + Indústria 4.0)

Projeto acadêmico de uma dupla. O celular fotografa parafusos e porcas; o notebook (gateway de borda) classifica o **tipo** e o **grau de estado** (perfeito, bom, mediano, ruim, inutilizável) com um modelo ONNX; a nuvem (FastAPI e Streamlit na VPS pessoal com Docker Compose, banco no Supabase) guarda o histórico e mostra os indicadores e a carta p (SPC). Custo adicional R$ 0 (ADR-018). Entrega entre 30/11 e 04/12/2026.

## Leia antes de qualquer tarefa

1. [docs/rules.md](docs/rules.md): regras **inegociáveis** (R-01…R-14) e negociáveis. Prevalece sobre todo o resto.
2. [docs/architecture.md](docs/architecture.md): componentes, contrato v0, API, banco, borda e artefatos do modelo.
3. A SPEC da tarefa, em [docs/specs/](docs/specs/), e os ADRs que ela cita, em [docs/adr/](docs/adr/).

Índice completo: [docs/README.md](docs/README.md).

## Regras inegociáveis (resumo — o texto oficial está em docs/rules.md)

- R-01 Custo adicional R$ 0: free tiers, software livre e a VPS pessoal já existente (ADR-018); nenhum serviço novo que exija cartão.
- R-02 Imagens não saem da LAN; só os resultados sobem.
- R-03 Segredos fora do Git (`.env.example` documenta).
- R-04 Mudança de contrato só em `packages/contracts`, com ADR e aumento de versão.
- R-05 Idempotência por `inspection_id`.
- R-06 Dado simulado sempre `source=simulated` e visível.
- R-07 Quem faz não testa nem aprova.
- R-08 Sem SPEC `Ready`, sem código.
- R-09 Merge exige CI + PASS + APPROVED (+ security) + sem SPEC_ISSUE; feito pelo orquestrador sob delegação e veto do humano (ADR-016); correção pequena de SPEC_ISSUE reaprovada pelo orquestrador nos limites do ADR-019.
- R-10 Máximo de 3 rodadas, depois escalar.
- R-11 Split por `item_id`; teste intocado.
- R-12 `api/` e `dashboard/` sem torch/onnxruntime; Python 3.12; `uv.lock`.
- R-13 Commits só com a identidade do projeto (conta GitHub CarlosZeyy), nenhuma ferramenta, e-mail ou serviço corporativo, nenhuma empresa citada.
- R-14 Privacidade das fotos.

## Mapa do repositório

```text
CLAUDE.md                  este arquivo
docs/                      PRD, arquitetura, regras, plano, dataset, deploy, ADRs, SPECs
reviews/                   processo do loop, checklist, templates e relatórios por SPEC
.claude/agents/            architect, developer, ml-engineer, tester, reviewer, security-devops
.claude/skills/            criar-spec, criar-adr, features (orquestração), ml-pipeline, contrato-api
packages/contracts/        qc-contracts: enums e schemas Pydantic compartilhados   (SPEC-002)
packages/preprocess/       qc-preprocess: pré-processamento idêntico treino/borda  (SPEC-002)
api/                       qc-api: FastAPI na nuvem                                (SPEC-004/005/006)
edge/                      qc-edge: gateway de borda na LAN                        (SPEC-007/008/009/010)
dashboard/                 qc-dashboard: Streamlit                                 (SPEC-013)
ml/                        qc-ml: dados, treino, avaliação, ONNX                   (SPEC-011/012)
scripts/                   simulate.py, register_device.py                         (SPEC-004/014)
infra/                     migrations SQL, docker/, compose.yaml, Caddyfile, render.yaml (reserva)  (SPEC-003/015)
```

As pastas de código são criadas pelas SPECs indicadas. Até a SPEC-001 estar `Done`, o repositório contém só documentação.

## Como trabalhamos (loop de agentes)

- A **sessão principal é o orquestrador.** Para entregar uma SPEC, siga a skill `features` (`/features SPEC-XXX`): branch → autor → `tester` → `reviewer` → (`security-devops`) → PR. Processo completo em [reviews/README.md](reviews/README.md).
- O orquestrador **não implementa, não testa e não aprova**. Ele delega aos subagentes, lê os relatórios e decide o próximo passo.
- Os subagentes **não** chamam outros subagentes.
- Uma SPEC nova ou alterada vem do `architect` (skill `criar-spec`). Uma decisão nova vira ADR (skill `criar-adr`). Ambas exigem aprovação humana.
- Ao encontrar ambiguidade ou contradição, registre `SPEC_ISSUE` e pare. Não improvise.

## Convenções

- **Idioma:** documentação em PT-BR; código, enums, logs e commits em inglês; a interface mostra rótulos em PT-BR (ADR-012).
- **Ambiente:** Python 3.12 via **uv** (workspace na raiz).
  - `uv sync --all-packages` instala o workspace **sem** torch; `uv sync --all-packages --extra train` inclui o treino (torch/timm, pesado); `uv sync --package qc-api` instala só um pacote.
  - Para rodar: `uv run --package <pkg> <cmd>`.
- **Qualidade:** `uv run ruff check .`, `uv run ruff format .`, `uv run pytest`.
- **Git:**
  - branch `spec/SPEC-XXX-slug`;
  - Conventional Commits com `Refs: SPEC-XXX` no corpo;
  - **nunca** commitar direto na `main`: tudo entra por PR, inclusive a marcação de `Done` (que vai no primeiro commit da próxima branch de SPEC);
  - todo commit feito por um agente leva o trailer `Agent: <papel>` (developer, ml-engineer, tester, reviewer, security-devops, architect, orchestrator). É assim que o reviewer verifica a separação de papéis (R-07), já que a identidade git é única;
  - nunca `--force` na `main`;
  - a identidade git é a local do repositório (não altere `user.name`/`user.email`).
  - push e PR **sempre** com a conta CarlosZeyy: prefixe os comandos com `GH_TOKEN="$(gh auth token --user CarlosZeyy)"`, porque a conta ativa do `gh` na máquina pode ser outra. Antes do primeiro push da sessão, confira com `GH_TOKEN=... gh api user --jq .login` (deve retornar `CarlosZeyy`).
- **Datas:** UTC com fuso explícito.
- **Testes:** `<componente>/tests/` (autor) e `<componente>/tests/acceptance/` (tester).
- **Dados e modelos:** `ml/data/` e `ml/models/**/*.onnx` não vão para o Git.
- **Notas locais:** `notas-locais/` (resumo de mudanças e diário de entregas) é só da dupla e é ignorada via `.git/info/exclude`. Nunca a adicione ao Git. O orquestrador atualiza o diário a cada SPEC entregue (skill `features`).

## Comandos úteis

Válidos depois da SPEC-001; até lá, não existem.

```bash
uv sync --all-packages                     # workspace sem torch (o que o CI usa)
uv sync --all-packages --extra train       # + torch/timm para treinar localmente (pesado)
uv sync --package qc-api                   # só a API
uv run pytest -q                           # toda a suíte
uv run --package qc-edge qc-edge           # sobe o gateway de borda na LAN
uv run --package qc-api uvicorn qc_api.main:app --reload --port 8001
uv run --package qc-dashboard streamlit run dashboard/app.py
```
