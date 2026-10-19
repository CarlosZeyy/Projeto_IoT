# ADR-016: Delegar ao orquestrador o merge dos PRs na `main`, sob condições verificadas e com veto humano

| Campo | Valor |
|---|---|
| Status | Aceito. Alterado em parte por ADR-019 (Proposto em 2026-10-19; a alteração só vale depois de o humano aceitar o ADR-019): a reaprovação de correções pequenas de `SPEC_ISSUE` sai de "O que continua com o humano", nos limites do ADR-019, e a condição 5 também cobre "Aguardando reaprovação (ADR-019)" |
| Data | 2026-10-17 |
| Decisores | Humano (Carlos) (redigido pelo agente architect) |
| Relacionados | ADR-011, ADR-015, R-07, R-09, R-10, R-13 |

## Contexto

A R-09 de `docs/rules.md` exige CI verde, os relatórios do loop com veredicto positivo e **o merge feito por um humano**. ADR-011 ("o merge é sempre humano") e ADR-015 ("o merge é feito por um humano") repetem essa exigência.

Em 2026-10-17, já há várias SPECs no loop e PRs empilhados à espera do merge. Cada PR parado atrasa o `chore: start` da SPEC seguinte e aumenta o risco de conflito com a `main`. As condições do portão (CI, veredictos dos relatórios, CAs manuais, `SPEC_ISSUE`) são verificáveis e podem ser conferidas e registradas pelo orquestrador. Para ganhar agilidade, o humano decidiu delegar o merge ao orquestrador (sessão principal).

Fatos que limitam as opções:

- O projeto usa **uma única conta GitHub**, CarlosZeyy (R-13). Ela abre os PRs e também faria a aprovação.
- O GitHub não deixa o autor aprovar o próprio PR: "Pull request authors cannot approve their own pull requests." Fonte: <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews> (verificado em 2026-10-17). Por isso, um "approve" formal no GitHub não é possível, e o merge humano nunca foi visível na plataforma: o histórico mostra a mesma conta nos dois casos.

**Por que isto é um ADR, se a R-09 é inegociável.** Pela `docs/rules.md`, uma regra inegociável não muda durante o projeto, e um agente que a veja como obstáculo deve parar e escalar, sem contornar. Esta mudança **não** partiu de um agente: é uma decisão explícita do humano, tomada em 2026-10-17. O ADR serve para registrar o que mudou, as condições que continuam obrigatórias e como reverter. O texto da R-09 em `docs/rules.md` e o resumo no `CLAUDE.md` são alterados pelo orquestrador a pedido do humano, e não pelo architect.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) O orquestrador faz o merge quando **todas** as condições da seção Decisão valem, registra a conferência no PR, e o humano mantém o veto | Remove o gargalo; cada condição é verificável e fica registrada no PR; o humano continua decidindo o que entra no loop (SPEC e ADR `Ready`) | O humano deixa de ser o último par de olhos antes da `main`; depende de o orquestrador conferir com rigor |
| B Manter o merge humano (status quo) | Um humano no último portão | É o gargalo atual: PRs empilham, os conflitos aumentam e o cronograma (MVP em 08/11) aperta |
| C Auto-merge do GitHub, condicionado aos checks obrigatórios | Mecânico; nenhum agente decide | O GitHub só enxerga os checks: não lê os veredictos dos relatórios, os CAs manuais nem os `SPEC_ISSUE`; uma revisão obrigatória é impossível com uma conta só |
| D Criar uma segunda conta GitHub para aprovar | Approve formal na plataforma | Viola a R-13 (só a conta CarlosZeyy) |

## Decisão

O humano delega ao **orquestrador** o merge dos PRs na `main`. O orquestrador só faz o merge quando **todas** as condições abaixo valem no commit de topo (head) do PR:

1. **CI verde:** todos os checks do PR passaram e nenhum está pendente. Isso inclui o job `ruff + pytest` do workflow `ci` (`ruff check`, `ruff format --check`, `pytest`) e o scanner de segredos que monitora o repositório.
2. **Relatórios da última rodada:** `test-report` PASS e `review-report` APPROVED.
3. **Segurança:** `security-report` PASS quando a SPEC tem a tag `security` ou `deploy`. Na SPEC-015, esse relatório é do `reviewer` (ADR-011).
4. **CAs manuais:** registrados com o resultado e com quem os executou, quando a Definição de pronto da SPEC os exigir. O orquestrador não executa nem marca um CA manual que caiba ao humano.
5. **Nenhum `SPEC_ISSUE` aberto** nos relatórios da SPEC, e a SPEC não está `Blocked`, `Escalated` nem "Aguardando reaprovação humana".
6. **Sem conflito:** o PR mergeia na `main` sem conflito. As demais caixas da Definição de pronto também estão marcadas, inclusive as de ordem de merge (por exemplo, SPEC-025 `Done` antes do merge da SPEC-009).
7. **Nada novo depois da aprovação:** depois do último `review-report` e `security-report`, a branch só recebeu commits de relatório e de status, nenhum de código ou de teste.

**Como o merge é feito:**

- com merge commit (sem squash e sem rebase), para preservar na `main` os trailers `Agent:` de cada commit, que são a evidência da R-07;
- pela conta CarlosZeyy: `GH_TOKEN="$(gh auth token --user CarlosZeyy)" gh pr merge <N> --merge --match-head-commit <sha conferido>`;
- antes do merge, o orquestrador registra no corpo do PR, ou num comentário, a lista das condições acima com a evidência de cada uma (veredictos, nome dos checks, SHA conferido) e a frase "Merge feito pelo orquestrador sob delegação do humano (ADR-016)".

**PRs de documentação** (só `docs/`, branch `docs/slug`) seguem a mesma regra, sem os relatórios do loop. Eles exigem CI verde e, quando trazem uma SPEC ou um ADR novo ou alterado, ou uma mudança em `docs/rules.md`, a **aprovação humana do conteúdo**. Essa aprovação vem de uma mensagem do próprio humano na sessão, nunca do relatório de um subagente, e o orquestrador a registra no PR com a data. O PR que introduz este ADR também se enquadra aqui.

**O que continua com o humano:**

- a aprovação de SPECs (`Draft` → `Ready`) e de ADRs (`Proposto` → `Aceito`), as reaprovações e os escalonamentos (R-10);
- o **veto**, a qualquer momento: uma instrução na sessão ou o rótulo `hold` no PR. Um PR com veto não é mergeado até o humano liberar.

**Nunca** usar `--force` nem `--admin`, nem desligar uma proteção ou check para conseguir mergear. Se uma condição falha, o orquestrador não faz o merge e informa o humano.

## Consequências

- **Positivas:**
  - fim do gargalo de merge; a SPEC seguinte começa da `main` atualizada, com menos conflitos;
  - cada merge tem a conferência escrita no PR, com mais evidência do que o merge humano tinha antes (a mesma conta, sem registro);
  - a R-07 continua valendo: o orquestrador não implementa, não testa e não aprova. Ele confere veredictos que foram dados por agentes independentes e só executa o merge.
- **Negativas / custos aceitos:**
  - **Risco:** um defeito que passou pelos três portões chega à `main`, e daí ao deploy, sem um olhar humano. **Mitigação:** as condições 1 a 7, o `--match-head-commit` (o que entra é exatamente o que foi conferido) e o merge commit, que permite reverter (`git revert -m 1`) por um PR comum.
  - **Risco:** o orquestrador conferir mal, por exemplo ler um veredicto de uma rodada antiga. **Mitigação:** a conferência escrita no PR cita a rodada e o arquivo de cada relatório, e o humano pode auditá-la depois.
  - **Risco:** uma decisão de conteúdo (SPEC, ADR, regra) entrar sem o humano. **Mitigação:** ela continua exigindo a aprovação humana explícita, e um agente nunca a substitui.
  - os documentos que dizem "merge humano" (ADR-011, ADR-015, `reviews/README.md`, a skill `features`, as Definições de pronto das SPECs) passam a ser lidos à luz deste ADR (hierarquia de `docs/README.md`). Nas SPECs existentes, a caixa "merge humano" é cumprida pelo merge delegado conforme a R-09 nova, sem reaprovação.
- **O que passa a ser obrigatório:**
  - o texto novo da R-09 em `docs/rules.md` e o resumo no `CLAUDE.md` (alterados pelo orquestrador a pedido do humano);
  - o comentário de conferência em todo PR mergeado pelo orquestrador;
  - atualizar `reviews/README.md` (diagrama, tabela de papéis e passo 9) e a skill `features` (passo de merge e "Depois do merge"), que estão fora de `docs/`.

**Como revogar.** O humano revoga a delegação a qualquer momento, com uma instrução na sessão. A partir daí, o orquestrador para de mergear, inclusive PRs já conferidos. Em seguida, o architect redige um ADR que substitui este (status `Substituído por ADR-NNN`) e o orquestrador restaura na R-09 o "merge feito por um humano". Até a R-09 voltar ao texto antigo, vale a revogação, por ser a regra mais restritiva.

## Quando revisitar

- Se um merge delegado deixar a `main` com o CI vermelho ou levar ao deploy uma regressão que um portão deveria ter barrado.
- Se o professor pedir que o merge seja humano ou que a separação de papéis seja demonstrada com aprovação na plataforma.
- Se o projeto passar a ter uma segunda pessoa com acesso de escrita que possa aprovar PRs sem violar a R-13.
