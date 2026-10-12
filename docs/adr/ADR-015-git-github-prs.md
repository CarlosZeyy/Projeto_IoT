# ADR-015: Versionar num repositório GitHub público, com branch por SPEC, PR com relatórios, CI obrigatório e merge humano

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-004, ADR-008, ADR-010, ADR-011, SPEC-001, SPEC-012, SPEC-015, R-03, R-08, R-09, R-13 |

## Contexto

O loop de agentes (ADR-011) precisa de um lugar onde cada SPEC vire uma unidade revisável, com CI e um portão de merge humano (R-09). O projeto é pessoal e acadêmico: todo o histórico deve usar só a identidade do projeto, a conta GitHub **CarlosZeyy**, configurada localmente no repositório. Nenhuma conta, e-mail, ferramenta ou serviço corporativo é usado, e nenhuma empresa é citada (R-13).

Os deploys do Render e do Streamlit CC são feitos a partir do GitHub (ADR-008), e o modelo ONNX não pode ir para o Git: é binário e regenerável.

Repositório: <https://github.com/CarlosZeyy/Projeto_IoT> (**público**, decisão da dupla em 2026-10-12). "Privado" no sentido do projeto significa apenas **sem vínculo com outros projetos ou organizações** (R-13), não visibilidade restrita.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) GitHub público; branch `spec/SPEC-XXX-slug` por SPEC; Conventional Commits com `Refs: SPEC-XXX`; PR com os relatórios da última rodada; CI (ruff + pytest) obrigatório; merge humano; pesos via GitHub Releases | Trilha completa por SPEC; CI grátis; integra com Render e Streamlit CC; o professor acessa pelo link | Overhead de PR para cada entrega; tudo o que é commitado fica público |
| B Só git local, sem remoto | Zero configuração; nada exposto | Sem CI nem PR; não integra com o deploy; sem backup; não há portão de merge verificável |
| C Push direto na `main` | Mais rápido | Sem revisão antes da integração (viola R-09); histórico misturado entre SPECs; o deploy pega código não revisado |

## Decisão

O código fica no repositório **público** `CarlosZeyy/Projeto_IoT`:

- cada SPEC é desenvolvida na branch `spec/SPEC-XXX-slug` (documentação pura pode usar `docs/slug`);
- os commits seguem Conventional Commits, com `Refs: SPEC-XXX` no corpo;
- o PR leva os relatórios da última rodada e o checklist de R-09;
- o CI (`ruff check` + `pytest`) precisa passar, e o **merge é feito por um humano**;
- os pesos `model.onnx` são distribuídos como anexo de **GitHub Releases** (`model-<versão>`).

## Consequências

- **Positivas:**
  - cada SPEC tem branch, PR, relatórios e CI rastreáveis;
  - a `main` só recebe código que passou pelos portões e é a fonte dos deploys;
  - os pesos ficam fora do Git, mas versionados e recuperáveis.
- **Negativas / custos aceitos:**
  - por ser público, **tudo o que é commitado fica visível para qualquer pessoa**: a R-03 (segredos fora do Git), a R-02/R-14 (nenhuma foto no repositório) e a pasta local `notas-locais/` (fora do Git) passam a ser ainda mais críticas;
  - GitHub Actions com runners padrão é gratuito para repositórios públicos, e o Streamlit CC lê o repositório sem permissão extra;
  - a máquina pode ter outra conta ativa no `gh`: todo push e PR usa o token da conta CarlosZeyy (`GH_TOKEN="$(gh auth token --user CarlosZeyy)"`, skill `features`).
- **O que passa a ser obrigatório:**
  - a identidade git é a local do repositório; agentes não alteram `user.name` nem `user.email`, e `git log --format='%an <%ae>'` só mostra a identidade do projeto (R-13);
  - nunca `--force` na `main`; nunca escrever direto na `main`; a marcação de `Done` vai no commit `chore: start` da próxima SPEC ou num PR `docs:`;
  - `.gitignore` cobre `.env*` (exceto `.env.example`), `ml/data/` e `ml/models/**/*.onnx` (R-03);
  - o workflow de CI roda sem o extra `train` (ADR-010) e inclui o teste de dependências de R-12 e o de paridade ONNX;
  - o professor recebe acesso de leitura, caso o repositório precise ficar visível para a avaliação (pergunta 7 de `docs/professor-questions.md`).

## Quando revisitar

- Se a dupla decidir tornar o repositório privado (nesse caso, rever a cota de Actions e a permissão extra do Streamlit CC).
- Se o professor exigir um repositório público (pergunta 7).
- Se o `model.onnx` passar do limite de tamanho de anexo de Release.
