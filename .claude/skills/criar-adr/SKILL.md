---
name: criar-adr
description: Como registrar uma decisão de arquitetura (ADR) no PartQC — template, numeração, status, quando é obrigatório e como substituir um ADR antigo. Use ao decidir ou mudar tecnologia, contrato, regra negociável, hospedagem ou abordagem de ML.
argument-hint: "título da decisão"
---

# Criar um ADR

## Quando é obrigatório

- Mudar qualquer regra **negociável** de `docs/rules.md` (N-xx).
- Mudar o contrato (`packages/contracts`) de forma incompatível (major) ou mudar a regra de defeito (`is_defective`). Ampliação de enum ou novo campo opcional = SPEC aprovada com a tag `contrato` (ADR opcional), conforme R-04 e a skill `contrato-api`.
- Trocar uma tecnologia, um provedor de hospedagem, o backbone ou a loss do modelo.
- Qualquer decisão que outra SPEC precise seguir.
- Respostas do professor que alterem um padrão (`docs/professor-questions.md`).

Mudança em regra **inegociável**: não é ADR. Pare e escale ao humano.

## Passos

1. Liste `docs/adr/`; use o próximo número (`ADR-NNN`, 3 dígitos). Arquivo: `ADR-NNN-slug.md`.
2. Copie `docs/adr/ADR-000-template.md` e preencha:
   - **Contexto** com fatos e fontes (URL e data);
   - **pelo menos 2 opções** com prós e contras;
   - decisão afirmativa;
   - consequências, incluindo o que passa a ser obrigatório;
   - o gatilho para revisitar.
3. **Status inicial:** `Proposto`. Só o humano muda para `Aceito`. Exceção: ADRs gerados na fundação documental a partir de decisões já tomadas pela dupla já nascem `Aceito`.
4. **Substituição:**
   - não edite o conteúdo do ADR antigo;
   - mude o status dele para `Substituído por ADR-NNN`;
   - no novo, cite o antigo em "Relacionados".
5. Propague a decisão:
   - atualize `docs/architecture.md`, `docs/rules.md` (tabela de negociáveis, coluna Fonte) e as SPECs afetadas;
   - SPECs afetadas que estavam `Ready` ou em andamento recebem "Aguardando reaprovação humana".

## Estilo

- Curto: de 1 a 2 páginas. Escreva para alguém que chega daqui a 2 meses sem contexto.
- Fatos externos sempre com fonte e data. Sem "acho que".
