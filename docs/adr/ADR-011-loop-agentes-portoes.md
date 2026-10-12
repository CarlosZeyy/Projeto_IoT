# ADR-011: Desenvolver com um loop de 6 agentes, papéis separados e portões de qualidade

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-015, SPEC-001, SPEC-015, R-07, R-08, R-09, R-10, R-13 |

## Contexto

A dupla vai usar agentes de IA (Claude Code) para escrever boa parte do código, num prazo curto (MVP em 08/11). O risco é ter código que ninguém revisou, testes escritos por quem implementou e decisões tomadas em silêncio.

Por padrão, um subagente do Claude Code pode criar outros subagentes, até um limite de profundidade. Fonte: <https://code.claude.com/docs/en/sub-agents> (verificado em 2026-10-12). Sem restrição, um agente poderia delegar a própria revisão.

O uso de agentes ainda depende da resposta do professor, e a pergunta 4 de `docs/professor-questions.md` é **bloqueante**.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) 6 agentes (`architect`, `developer`, `ml-engineer`, `tester`, `reviewer`, `security-devops`), orquestrados pela sessão principal com a skill `features`, máximo de 3 rodadas, relatórios em `reviews/SPEC-XXX/` e merge humano | Separação de papéis verificável (R-07); trilha de auditoria por rodada; o humano decide no fim | Mais tokens e tempo por SPEC; overhead de relatórios |
| B Invocação manual, um agente por vez, sem processo | Simples; controle total | Sem garantia de que teste e revisão aconteçam; nada registrado |
| C Workflow totalmente automatizado (do agente ao merge) | Rápido | Sem humano no portão (viola R-09); erros se propagam sem freio |
| D Só 4 agentes (sem `ml-engineer` e `security-devops`) | Menos configuração | O developer acumula ML e deploy; ninguém faz o portão de segurança independente nas SPECs `security`/`deploy` |

## Decisão

O desenvolvimento segue o loop de `reviews/README.md`: a **sessão principal orquestra** (skill `features`) e chama o autor, depois o `tester`, o `reviewer` e, quando a SPEC tem a tag `security` ou `deploy`, o `security-devops`. Os subagentes **não recebem a ferramenta `Agent`** (não chamam outros subagentes). Cada SPEC tem no **máximo 3 rodadas** (R-10). Cada etapa grava `rN-*-report.md` em `reviews/SPEC-XXX/`, e o **merge é sempre humano** (R-09).

## Consequências

- **Positivas:**
  - quem faz não testa nem aprova (R-07);
  - toda SPEC entregue tem relatórios versionados que a dupla pode mostrar ao professor;
  - os impasses são escalados em vez de arrastados.
- **Negativas / custos aceitos:**
  - cada SPEC leva de 3 a 4 chamadas de agente por rodada;
  - o hook de guarda de caminhos (SPEC-001) age sobre `Write`/`Edit`, mas **não impede escritas feitas via `Bash`**. A mitigação é o `reviewer` conferir no `git log` da branch quais arquivos cada commit alterou, contra a etapa que o produziu (por exemplo, nenhum commit da etapa de teste muda código de produção). Como todos os commits usam a mesma identidade git (R-13), o autor no `git log` não distingue os agentes: por isso todo commit de agente leva o trailer `Agent: <papel>`, e o reviewer cruza esse trailer com os arquivos tocados (`reviews/checklist.md`, R-07). Commit sem trailer é achado bloqueante.
- **O que passa a ser obrigatório:**
  - o frontmatter dos 6 agentes não inclui a ferramenta `Agent`;
  - o hook de guarda de caminhos é entregue na SPEC-001;
  - os relatórios seguem os templates de `reviews/templates/` e têm veredicto preenchido;
  - na SPEC-015, em que o `security-devops` é o autor, o portão de segurança é feito pelo `reviewer`;
  - nenhum código antes de uma SPEC `Ready` aprovada (R-08), e nenhum código antes da resposta à pergunta 4, ou da declaração do uso de IA no relatório conforme a política da instituição.

## Quando revisitar

- Quando o professor responder a pergunta 4: se proibir o uso de agentes, este ADR é substituído e o loop vira um processo manual.
- Se mais de 2 SPECs do MVP chegarem a `Escalated`.
- Se o Claude Code passar a oferecer um bloqueio nativo de escrita por caminho que também cubra o `Bash`.
