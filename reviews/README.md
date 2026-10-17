# Loop de entrega (Loop Engineering)

Cada SPEC passa por um ciclo com papéis separados. Quem faz não aprova o que fez (R-07). O orquestrador é a **sessão principal do Claude Code**, guiada pela skill `features`. Os subagentes não chamam outros subagentes.

```text
            ┌─────────────── CHANGES_REQUESTED / FAIL (rodada N+1, máx. 3) ───────────────┐
            ▼                                                                             │
 SPEC Ready ─► DEV (developer | ml-engineer | security-devops*) ─► TEST (tester) ─► REVIEW (reviewer) ─► SECURITY (security-devops)** ─► PR ─► merge (orquestrador, ADR-016) ─► Done
                    rN-dev-report.md                                rN-test-report.md   rN-review-report.md   rN-security-report.md
```

\* `security-devops` só é autor da SPEC-015 (deploy). Nesse caso, o portão de segurança é feito pelo `reviewer` com a seção de segurança do checklist, **nunca** pelo próprio autor.
\** Só quando a SPEC tem a tag `security` ou `deploy`.

## Papéis por SPEC

| Papel | Quem | Não pode |
|---|---|---|
| Autor | `developer` (padrão), `ml-engineer` (SPECs de `ml/`) ou `security-devops` (SPEC-015) | Escrever os testes de aceite; aprovar |
| Tester | `tester` | Editar código de produção; aprovar a revisão |
| Reviewer | `reviewer` | Editar código ou testes |
| Security | `security-devops` (se não for o autor) | Editar código |
| Orquestrador | Sessão principal | Implementar, testar ou aprovar no lugar dos agentes; pular etapa |
| Humano | Dupla | — (aprova SPECs e ADRs, decide escalonamentos e pode vetar merges; o merge é delegado ao orquestrador, ADR-016) |

## Passo a passo do orquestrador

1. **Pré-condições:**
   - a SPEC está `Ready`;
   - as dependências estão `Done`;
   - a árvore de trabalho está limpa.
2. **Branch e status:** criar a branch `spec/SPEC-XXX-slug` a partir da `main` atualizada e mudar o status da SPEC para `In Dev` (no arquivo e em `docs/plan.md`).
3. **DEV:**
   1. Chamar o autor com: o caminho da SPEC, o número da rodada e, a partir da r2, os relatórios da rodada anterior.
   2. O autor implementa, roda `ruff` e os próprios testes unitários, faz commits e escreve `reviews/SPEC-XXX/rN-dev-report.md`.
4. **TEST:**
   1. Status `In Test`.
   2. Chamar o `tester` com a SPEC e o dev-report.
   3. O tester escreve os testes de aceite em `<componente>/tests/acceptance/`, roda a **suíte inteira** e escreve `rN-test-report.md`.
   4. Resultado `FAIL`: volta ao passo 3, na rodada N+1.
5. **REVIEW:**
   1. Status `In Review`.
   2. Chamar o `reviewer` com a SPEC, o diff (`git diff main...HEAD`) e os relatórios.
   3. O reviewer escreve `rN-review-report.md`.
   4. Resultado `CHANGES_REQUESTED`: volta ao passo 3, na rodada N+1.
6. **SECURITY:** só com a tag `security` ou `deploy`.
   1. Status `In Security`.
   2. Chamar o `security-devops` (ou o `reviewer`, se o autor foi o security-devops), que escreve `rN-security-report.md`.
   3. Resultado `FAIL`: volta ao passo 3, na rodada N+1.
7. **Limite (R-10):** se a rodada 3 não fechar, mudar o status para `Escalated`, parar e apresentar ao humano um resumo do impasse com opções.
8. **PR:**
   1. Fazer push da branch e abrir o PR (`gh pr create`) com o título `SPEC-XXX: <título>`.
   2. No corpo: resumo, link da SPEC, os relatórios da última rodada e o checklist do portão de merge (R-09).
   3. Status da SPEC: permanece `In Review` (ou `In Security`) até o merge.
9. **Merge:** o orquestrador confere as condições da R-09 e faz o merge sob delegação (ADR-016), registrando a conferência no PR; o humano pode vetar (rótulo `hold` ou instrução na sessão). A marcação de `Done` (na SPEC e em `docs/plan.md`) entra no primeiro commit da próxima SPEC. Nada é commitado direto na `main`.

**Rastreio de papéis:** como todos os commits usam a mesma identidade git (R-13), cada commit de agente leva o trailer `Agent: <papel>`. O reviewer confere com `git log --format='%h %s%n%(trailers:key=Agent)' main..HEAD` e cruza com `git show --stat`: arquivos de `tests/acceptance/` só podem aparecer em commits `Agent: tester`, e código de produção só em commits do autor.

**Commits do architect:** o `architect` não tem shell, então quem commita os arquivos dele é o orquestrador, com `Agent: architect` e `Refs: SPEC-XXX`. Esse commit é esperado e não é desvio de papel, desde que contenha só arquivos de `docs/` (exceto `docs/rules.md` sem pedido explícito do humano) e nenhum arquivo de outro papel. As mudanças de status feitas pelo próprio orquestrador vão em commits separados, com `Agent: orchestrator`.

## Arquivos de cada SPEC

```text
reviews/SPEC-XXX/
  r1-dev-report.md
  r1-test-report.md
  r1-review-report.md
  r1-security-report.md   (se aplicável)
  r2-...                  (se houve nova rodada)
```

Os modelos estão em [templates/](templates/). Os relatórios são **versionados** junto com o código da SPEC.

## Veredictos

| Relatório | Valores | Critério |
|---|---|---|
| test-report | `PASS` / `FAIL` | `PASS` só se **todos** os critérios de aceite têm teste e todos passam, a suíte inteira passa e o ruff está limpo |
| review-report | `APPROVED` / `CHANGES_REQUESTED` | `APPROVED` só sem nenhum achado de severidade **bloqueante** ou **alta**; achados médios ou baixos podem virar issue |
| security-report | `PASS` / `FAIL` | `PASS` só sem achados bloqueantes ou altos |

Severidades:

- **Bloqueante:** viola uma regra inegociável ou um critério de aceite.
- **Alta:** bug provável ou falha de segurança.
- **Média:** manutenibilidade ou risco moderado.
- **Baixa:** estilo ou sugestão.

## Quando o problema está na SPEC

Se qualquer agente concluir que a SPEC está errada, ambígua ou contradiz `architecture.md` ou um ADR, ele **não improvisa**: registra no relatório como `SPEC_ISSUE`. O orquestrador então para o loop e chama o `architect` para propor a correção. Uma SPEC alterada precisa de nova aprovação humana, e o loop reinicia na rodada atual.
