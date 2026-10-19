# ADR-019: Delegar ao orquestrador a reaprovação de correções pequenas de SPEC, dentro de limites verificáveis e com veto humano

| Campo | Valor |
|---|---|
| Status | Aceito (aprovado pelo humano em 2026-10-19, sem a exclusão de tag security/deploy proposta) |
| Data | 2026-10-19 |
| Decisores | Humano (Carlos) (redigido pelo agente architect) |
| Relacionados | ADR-016 (alterado em parte), ADR-011, ADR-018 (precedente de mudança de regra inegociável por decisão do humano), SPEC-012, R-04, R-07, R-08, R-09, R-10 |

## Contexto

Quando um agente do loop encontra um erro na SPEC, ele registra um `SPEC_ISSUE` e o loop para (`reviews/README.md`, "Quando o problema está na SPEC"). O architect corrige a SPEC, e o humano precisa reaprová-la antes de o loop seguir (R-09, ADR-016, "O que continua com o humano", e a skill `features`, §4). Muitas dessas correções são pequenas: um texto ambíguo esclarecido, ou um CA com a tolerância ajustada a uma medição. Mesmo assim, o loop fica parado até o humano responder, inclusive de madrugada.

Caso que motivou a decisão: na SPEC-012, o CA-13 comparava um valor float32 com `1e-3` exato e quebrou o CI da `main` (run 39191665982). O architect corrigiu o critério para `9e-4 < max_abs_diff < 1.1e-3`, preservando a intenção. O orquestrador registrou a reaprovação apoiado numa instrução genérica de "total autonomia" do humano. O reviewer barrou o registro (SPEC_ISSUE-02 de `reviews/SPEC-012/r2-review-report.md`), porque a R-09 e o ADR-016 reservam as reaprovações ao humano. O próprio reviewer indicou o caminho: um ADR que altere a R-09 e o ADR-016. O humano reaprovou a correção e, em 2026-10-19, decidiu delegar ao orquestrador a reaprovação de **correções pequenas de SPEC**.

**Por que isto é um ADR, se a R-08 e a R-09 são inegociáveis.** O motivo é o mesmo do ADR-016 (R-09) e do ADR-018 (R-01). A mudança **não** partiu de um agente: é uma decisão explícita do humano. O ADR registra o que mudou, os limites e como reverter. O orquestrador altera o texto das regras em `docs/rules.md` e o resumo no `CLAUDE.md` a pedido do humano, e só depois que o humano aceitar este ADR.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) O orquestrador reaprova só as correções que cumprem **todos** os critérios de elegibilidade e **nenhuma** das exclusões; o reviewer audita depois; o humano mantém o veto | O loop não para por ajuste de texto ou de tolerância; cada condição é verificável no diff e no Histórico; o que muda o produto continua com o humano | Um ajuste mal classificado pode chegar à implementação antes de o humano ver; o orquestrador e o architect precisam classificar com rigor |
| B Manter a reaprovação sempre humana (status quo) | Humano em toda mudança de SPEC | O loop para de madrugada à espera de correções triviais; a SPEC-012 deixou a `main` com o CI vermelho até a resposta do humano |
| C Delegar ao orquestrador todas as reaprovações | Nenhuma parada | Mudanças de escopo, de contrato ou de segurança entrariam sem o humano; esvazia a R-08 |
| D O próprio architect aprova a correção que escreveu | Mais rápido | Quem faz aprovaria o que fez (viola a R-07) |
| E Chamar o reviewer para validar a correção antes de retomar o loop | Um agente independente decide antes do código | Uma chamada a mais por `SPEC_ISSUE`; o reviewer já confere tudo no portão de revisão da mesma rodada, antes do merge |

## Decisão

O humano delega ao **orquestrador** a reaprovação de uma **correção pequena de SPEC**. A correção é pequena quando cumpre **todos** os critérios E-1 a E-5 e **nenhuma** das exclusões X-1 a X-9 (a X-8 foi removida pelo humano). **Na dúvida, o orquestrador pergunta ao humano.**

### Critérios de elegibilidade (todos obrigatórios)

- **E-1 Origem:** a correção resolve um `SPEC_ISSUE` com ID, registrado num relatório do loop da própria SPEC (`reviews/SPEC-XXX/rN-*-report.md`).
- **E-2 Autoria:** o architect fez a correção num commit com `Agent: architect` que toca **só** o arquivo da SPEC e o `docs/plan.md`.
- **E-3 Estado:** o humano já aprovou a SPEC, e ela está em andamento no loop (`In Dev`, `In Test`, `In Review`, `In Security`, ou `Blocked` por este `SPEC_ISSUE`).
- **E-4 Natureza:** cada trecho alterado é de um destes tipos:
  1. texto que esclarece o requisito sem mudar o comportamento pedido;
  2. CA com a tolerância, o limite numérico **da verificação** ou a forma de verificação ajustados, preservando a intenção. O Histórico registra o texto antigo, o texto novo e a evidência (medição, run do CI ou relatório);
  3. CA novo que cobre só o comportamento corrigido em (1) ou (2);
  4. a nota de rodada do Plano de testes, que limita a rodada aos testes afetados, e o aviso no topo e as linhas do Histórico.
- **E-5 Abrangência:** a correção toca só os trechos ligados ao `SPEC_ISSUE` citado.

### Exclusões (qualquer uma leva a correção ao humano)

- **X-1** SPEC nova, ou mudança `Draft` → `Ready`.
- **X-2** ADR novo ou alterado, inclusive mudança de status.
- **X-3** Mudança em `docs/rules.md`, ou mudança necessária em `docs/architecture.md`, `docs/PRD.md` ou outro documento que não seja a SPEC e o `docs/plan.md`.
- **X-4** Contrato: mudança em `packages/contracts`, num campo, enum ou schema, na versão do contrato ou na tag `contrato` (R-04).
- **X-5** Escopo novo: requisito, rota, comando, variável de ambiente, assinatura pública, arquivo de produção ou comportamento novos; dependência nova (SPEC em "Depende de" ou pacote); tecnologia nova.
- **X-6** CA enfraquecido em vez de ajustado:
  - CA removido;
  - CA automático transformado em manual;
  - caso de erro retirado;
  - mudança num valor que o produto promete, e não num valor da verificação. Esse valor pode ser uma meta ou um limite do `docs/PRD.md` (RF, RNF, métricas), de `docs/architecture.md` ou do contrato, ou um limite de segurança (tamanho de corpo, taxa, timeout de produção, permissões, autenticação).
- **X-7** Regras inegociáveis: a correção toca um trecho ou um CA que verifica uma regra inegociável, em especial R-02 (imagens na LAN), R-03 (segredos), R-06 (dado simulado), R-11 (integridade de ML e do conjunto de teste) e R-14 (privacidade).
- **X-8** (removida pelo humano em 2026-10-19). A versão proposta excluía as SPECs com a tag `security` ou `deploy`. Na versão aceita, a delegação também vale para elas, mas só nos tipos de E-4. A X-6 continua valendo, inclusive para os limites de segurança, e a X-7 também, para qualquer regra inegociável. Nessas SPECs, o portão de segurança também confere a reaprovação delegada (ver "Como funciona", passo 3). O número X-8 não é reaproveitado.
- **X-9** Marcação de "exige humano":
  - o architect, o reviewer ou o humano marcou o caso como "exige humano";
  - ou o caso depende de uma resposta do professor (`docs/professor-questions.md`);
  - ou o mesmo CA ou trecho já foi corrigido sob este ADR na mesma SPEC. A segunda correção vai ao humano.

### Como funciona

1. **Architect.** Corrige a SPEC e escreve no Histórico a classificação:
   - `Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão)`;
   - ou `Classificação ADR-019: exige humano (X-n: <motivo>)`.

   Depois, marca o topo da SPEC com "**Aguardando reaprovação (ADR-019)**", se a correção for elegível, ou com "**Aguardando reaprovação humana**", nos demais casos. Na dúvida, classifica como `exige humano`. O architect nunca registra a aprovação.
2. **Orquestrador.** Só reaprova uma correção classificada como `elegível`, depois de conferir cada critério e cada exclusão no diff do commit do architect (`git show`). O registro vai num commit só de status, com `Agent: orchestrator`:
   - o aviso do topo vira "Reaprovada pelo orquestrador sob o ADR-019 em <data UTC>";
   - o Histórico ganha a linha `| <data> | Correção do SPEC_ISSUE-NN (<itens>) aprovada pelo orquestrador sob o ADR-019 (commit do architect <sha>). | <relatório e achado que motivaram> | Orquestrador (ADR-019) |`.

   Em seguida, o orquestrador informa o humano na sessão, com o texto antigo, o novo e o motivo, e retoma o loop na mesma rodada, sem esperar a resposta. Se discordar da classificação `elegível` ou tiver dúvida, pede a reaprovação ao humano.
3. **Reviewer e portão de segurança.** No portão de revisão da rodada, o reviewer confere cada reaprovação delegada contra E-1 a E-5 e X-1 a X-9. Quando a SPEC tem a tag `security` ou `deploy`, o portão de segurança faz a mesma conferência no `security-report`, com atenção à X-6 (limites de segurança) e à X-7. Esse portão é o `security-devops` ou, quando ele é o autor da SPEC, o reviewer, que registra a conferência no `security-report`. Se um dos portões achar uma reaprovação fora dos limites, registra um `SPEC_ISSUE` "exige humano", que impede o merge (R-09) até o humano reaprovar. Se o conteúdo da correção estiver certo, esse `SPEC_ISSUE` não pede rodada nova.
4. **PR e resumo.** O corpo do PR tem a seção "Reaprovações sob o ADR-019", com a SPEC, os itens, o commit do architect, o commit da aprovação e o motivo. O comentário de conferência do merge (ADR-016) cita essa seção, e o resumo final ao humano também. Sem reaprovação delegada, a seção diz "nenhuma".
5. **Veto.** O humano pode vetar uma reaprovação delegada a qualquer momento:
   - **Antes do merge:** a SPEC volta a `Blocked`, com "Aguardando reaprovação humana", e o PR não é mergeado até o humano decidir (ADR-016, condição 5).
   - **Depois do merge:** o orquestrador registra o veto no Histórico da SPEC e chama o architect com a decisão do humano. O código que já está na `main` fica como está até o humano escolher entre reverter (`git revert -m 1`, por PR) e corrigir numa SPEC de manutenção.

**O que continua com o humano:**

- a aprovação de SPECs novas (`Draft` → `Ready`) e de ADRs;
- toda reaprovação fora destes limites;
- os escalonamentos (R-10, que não muda);
- o veto.

As correções de "só texto, sem reaprovação" que o humano já dispensou caso a caso (por exemplo, a linha de 2026-10-18 do Histórico da SPEC-012) continuam como antes.

**Alteração do ADR-016.** Na seção "O que continua com o humano", "as reaprovações" passa a excluir as correções pequenas deste ADR. A condição 5 do ADR-016 também bloqueia o merge de uma SPEC marcada "Aguardando reaprovação (ADR-019)". O resto do ADR-016 vale sem mudança.

### Texto novo das regras (aplicado pelo orquestrador depois do aceite)

**R-09**, coluna "Regra":

> **Portão de merge na `main`.** Exige todos os checks do PR verdes (ruff + pytest e o scanner de segredos), `test-report` PASS e `review-report` APPROVED da última rodada, `security-report` PASS (quando a SPEC tem a tag `security` ou `deploy`), CAs manuais registrados (quando a Definição de pronto exigir), nenhum `SPEC_ISSUE` aberto e o PR sem conflito com a `main`. O merge é feito pelo orquestrador sob delegação do humano, com merge commit pela conta CarlosZeyy e a conferência registrada no PR; o humano pode vetar a qualquer momento e mantém a aprovação de SPECs e ADRs e as reaprovações de SPEC. A exceção é a reaprovação de uma correção pequena de `SPEC_ISSUE`, que o orquestrador pode fazer dentro dos limites do ADR-019, com registro no Histórico da SPEC e no PR, conferência do reviewer (e do portão de segurança, quando a SPEC tem a tag `security` ou `deploy`) e veto do humano; na dúvida, o orquestrador pergunta ao humano. PR só de `docs/` exige CI verde e, se trouxer SPEC, ADR ou regra nova ou alterada, aprovação humana do conteúdo. Nunca `--force` nem `--admin`. (Alterada por decisão do humano em 2026-10-17, ADR-016, e em 2026-10-19, ADR-019.)

**R-09**, coluna "Como verificar":

> Checklist R-09 e comentário de conferência no PR; `git log --merges` na `main`; reaprovações sob o ADR-019 conferidas no `review-report` (checklist §1) e, com a tag `security` ou `deploy`, no `security-report` (checklist §6), contra o Histórico da SPEC.

**R-08**, para não contradizer a R-09 ("aprovada por humano"), coluna "Regra":

> **Sem SPEC, sem código.** Todo código implementa uma SPEC com status `Ready` aprovada por humano, com critérios de aceite testáveis. Uma correção pequena de `SPEC_ISSUE` numa SPEC já aprovada pode ser reaprovada pelo orquestrador dentro dos limites do ADR-019. (Alterada por decisão do humano em 2026-10-19, ADR-019.)

**R-08**, coluna "Como verificar":

> O PR precisa citar a SPEC e listar as reaprovações sob o ADR-019, se houver.

## Consequências

- **Positivas:**
  - o loop não para à espera do humano por um ajuste de texto ou de tolerância;
  - cada reaprovação delegada deixa rastro conferível: a classificação do architect, o commit de status do orquestrador, a conferência do reviewer (e do portão de segurança, nas SPECs `security`/`deploy`) e a seção do PR;
  - a R-07 continua valendo: o architect escreve, o orquestrador aprova e os portões auditam, e ninguém aprova o que fez.
- **Negativas / custos aceitos:**
  - **Risco:** uma correção mal classificada é implementada antes de o humano vê-la. **Mitigação:** o reviewer confere no portão da mesma rodada, antes do merge; o humano é avisado na hora e pode vetar; a classificação é conservadora (na dúvida, `exige humano`).
  - **Risco:** CAs afrouxados aos poucos até perder a intenção. **Mitigação:** X-6 e o limite de uma correção delegada por CA ou trecho (X-9).
  - **Risco:** sem a X-8, uma correção numa SPEC `security`/`deploy` enfraquece um controle de segurança sem o humano. **Mitigação:**
    - a X-6 exclui qualquer limite de segurança (tamanho, taxa, timeout de produção, permissões, autenticação);
    - a X-7 exclui qualquer regra inegociável;
    - o portão de segurança faz uma segunda conferência, independente do reviewer.
  - um veto depois do merge pode exigir revert ou uma SPEC de manutenção.
- **O que passa a ser obrigatório:**
  - o texto novo da R-08 e da R-09 em `docs/rules.md`, e o resumo da R-09 no `CLAUDE.md`, aplicados pelo orquestrador a pedido do humano;
  - a classificação ADR-019 no Histórico de toda correção de `SPEC_ISSUE` numa SPEC aprovada;
  - a seção "Reaprovações sob o ADR-019" no corpo dos PRs de SPEC;
  - atualizar, fora de `docs/`: `reviews/README.md` ("Quando o problema está na SPEC" e a tabela de papéis); `reviews/checklist.md` (item novo na §1 e na §6); a skill `features` (§0, §3 e §4); o agente `architect` (marcação da SPEC); e a skill `criar-spec` (passo 10).

**Como revogar.** O humano revoga a delegação a qualquer momento, com uma instrução na sessão. A partir daí, toda reaprovação volta a ser humana, inclusive as que estão pendentes. O architect redige um ADR que substitui este, e o orquestrador restaura o texto anterior da R-08 e da R-09. Até lá, vale a revogação, por ser a regra mais restritiva.

## Quando revisitar

- Se os portões (reviewer ou segurança) barrarem mais de 2 reaprovações delegadas por estarem fora dos limites.
- Se o humano vetar uma reaprovação delegada.
- Se o portão de segurança barrar uma reaprovação delegada numa SPEC `security`/`deploy`: avaliar se a X-8 volta.
- Se o professor pedir que toda mudança de requisito tenha aprovação humana registrada.
