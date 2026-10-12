---
name: features
description: Procedimento do orquestrador para entregar uma SPEC pelo loop de agentes do PartQC (branch → autor → tester → reviewer → security → PR). Use quando o humano pedir para implementar, entregar ou "rodar o loop" de uma SPEC, por exemplo "/features SPEC-004" ou "implemente a SPEC-007".
argument-hint: SPEC-XXX
---

# Loop de entrega de uma SPEC

Você é o **orquestrador** (sessão principal). Você conduz; você **não** implementa, testa ou aprova. Referência completa: `reviews/README.md`.

SPEC alvo: `$ARGUMENTS`. Se vier vazio, pergunte ao humano qual SPEC entregar.

## 0. Pré-condições (pare se alguma falhar)

1. Localize o arquivo `docs/specs/$ARGUMENTS-*.md` e leia a SPEC inteira.
2. **Status:**
   - deve ser `Ready`;
   - se for `Draft`, peça a aprovação do humano antes de seguir;
   - se estiver marcada como "Aguardando reaprovação humana", peça a reaprovação.
3. As dependências ("Depende de") devem estar `Done` em `docs/plan.md`. Se não estiverem, informe e pergunte se deve seguir mesmo assim.
4. `git status` limpo e `main` atualizada (`git pull --ff-only` se houver remoto).
5. Identifique o **autor**:
   - campo "Autor da implementação" da SPEC;
   - `ml-engineer` para `ml/`;
   - `security-devops` para a SPEC-015.

## 1. Preparação

```bash
git switch -c spec/<SPEC-ID>-<slug> main     # se a branch já existir, use git switch
```

Atualize o status da SPEC para `In Dev`, com "Rodada atual: r1", no arquivo da SPEC **e** em `docs/plan.md`. Se houver SPECs já mergeadas e ainda não marcadas como `Done`, marque-as neste mesmo commit. Commit: `chore: start <SPEC-ID>` com o trailer `Agent: orchestrator`.

## 2. Rodada N (começa em r1, máximo r3)

1. **DEV:** chame o subagente autor com:
   > Implemente `docs/specs/<arquivo>`. Rodada rN. Branch atual: `spec/...`. [Se N>1: trate os achados de `reviews/<SPEC-ID>/r(N-1)-*.md`.] Escreva `reviews/<SPEC-ID>/rN-dev-report.md`.

   Se a resposta trouxer `SPEC_ISSUE`, vá para a seção 4.
2. **TEST:**
   1. Status `In Test`.
   2. Chame o `tester` com:
      > Teste `docs/specs/<arquivo>` na rodada rN. Dev report: `reviews/<SPEC-ID>/rN-dev-report.md`. Escreva `reviews/<SPEC-ID>/rN-test-report.md`.
   3. `FAIL`: N+1 e volte ao passo 1.
3. **REVIEW:**
   1. Status `In Review`.
   2. Chame o `reviewer` com a SPEC e os relatórios rN.
   3. `CHANGES_REQUESTED`: N+1 e volte ao passo 1.
4. **SECURITY:** só se as tags da SPEC incluírem `security` ou `deploy`.
   1. Status `In Security`.
   2. Chame o `security-devops` (modo 1) ou, se ele foi o autor, o `reviewer` com a instrução de gerar o `rN-security-report.md`.
   3. `FAIL`: N+1 e volte ao passo 1.

**Entre as etapas:**
- Confira que o relatório esperado existe e tem o veredicto preenchido.
- Não repasse a um agente o raciocínio interno de outro; passe só os caminhos dos arquivos.
- Lembre cada agente de usar o trailer `Agent: <papel>` nos commits.
- Nunca pule uma etapa. Nunca chame o mesmo agente para dois papéis da mesma SPEC.

## 3. Saída do loop

- **Sucesso:**
  1. Rode `uv run ruff check . && uv run pytest -q` como verificação final (não corrija nada; se falhar, é uma nova rodada).
  2. `GH_TOKEN="$(gh auth token --user CarlosZeyy)" git push -u origin <branch>`. **Sempre** com o token da conta CarlosZeyy (R-13): a conta ativa do `gh` na máquina pode ser outra. Use o mesmo prefixo `GH_TOKEN=...` no `gh pr create`.
  3. `gh pr create --title "<SPEC-ID>: <título>" --body-file <arquivo temporário no scratchpad>`. O corpo leva:
     - resumo;
     - link da SPEC;
     - tabela com os relatórios da última rodada e os veredictos;
     - checklist R-09;
     - a linha de atribuição exigida pelo sistema.
  4. Informe ao humano o link do PR e o que testar manualmente, se houver.
  5. **Diário de entregas (local, nunca commitado):** se existir `notas-locais/diario-de-entregas.md`, acrescente uma entrada no formato do modelo do próprio arquivo:
     - nome da feature (SPEC e título), data e PR;
     - o que entrega e como funciona, em linguagem simples, para quem não programa;
     - os arquivos principais e o papel de cada um;
     - como ver funcionando e os termos novos.

     Escreva a partir do dev-report, do diff e dos relatórios. Não copie código longo; explique-o. A pasta `notas-locais/` está no `.git/info/exclude`: **nunca** a adicione ao Git.
- **Depois do merge** (quando o humano avisar):
  1. Nada é commitado direto na `main`. A marcação de `Done` (no arquivo da SPEC e em `docs/plan.md`) vai no commit `chore: start` da **próxima** SPEC.
  2. Se não houver próxima SPEC, abra um PR curto `docs: mark <SPEC-ID> done`.
- **Rodada 3 falhou (R-10):**
  1. Status `Escalated`.
  2. Escreva ao humano um resumo de no máximo 15 linhas: o que travou, os achados recorrentes e de 2 a 3 opções (ajustar a SPEC, aceitar com issue, mudar a abordagem).
  3. Pare.

## 4. SPEC_ISSUE

1. Pare o loop e mude o status para `Blocked`.
2. Chame o `architect` com o relatório que levantou o problema.
3. Apresente ao humano a correção proposta e peça a reaprovação.
4. Aprovada a correção, retome na **mesma rodada**.
