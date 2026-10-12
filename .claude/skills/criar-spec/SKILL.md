---
name: criar-spec
description: Como escrever ou alterar uma SPEC do PartQC (template, numeração, critérios de aceite testáveis, tags, dependências, atualização do quadro em docs/plan.md). Use ao criar uma SPEC nova, quebrar um requisito do PRD em entregas ou corrigir um SPEC_ISSUE.
argument-hint: "título da SPEC ou SPEC-XXX a alterar"
---

# Criar ou alterar uma SPEC

## Passos

1. **Numeração:**
   - liste `docs/specs/` e use o próximo número livre (`SPEC-NNN`, 3 dígitos);
   - nome do arquivo: `SPEC-NNN-slug-curto.md` (slug em PT-BR, minúsculas, hífens, sem acentos).
2. Copie `docs/specs/SPEC-000-template.md` e preencha **todos** os campos. Status inicial: `Draft`.
3. **Contexto:** cite a seção de `docs/architecture.md` e os RF/RNF do `docs/PRD.md` cobertos.
4. **Escopo:** liste o "Dentro" com arquivos, módulos, rotas e comandos concretos, e o "Fora" dizendo **em qual SPEC** cada item entra.
5. **Requisitos detalhados:**
   - assinaturas de funções públicas, rotas com status HTTP, variáveis de ambiente e o comportamento em cada erro;
   - **não duplique** o contrato: referencie `architecture.md` §3;
   - se a SPEC muda o contrato, adicione a tag `contrato`; ADR obrigatório para mudança incompatível (major) do contrato ou da regra de defeito; ampliação de enum ou campo opcional = SPEC aprovada com a tag `contrato` (ADR opcional), conforme R-04 e a skill `contrato-api`.
6. **Critérios de aceite:** veja as regras de qualidade abaixo.
7. **Plano de testes:**
   - unitários (autor) e aceite (tester, `<comp>/tests/acceptance/test_spec_NNN.py`);
   - diga o que é mockado (só fronteiras externas) e qual banco ou fixture usar.
8. **Tags:**
   - `security` em toda SPEC que toca autenticação, entradas externas, segredos, rede ou banco;
   - `deploy` para deploy;
   - `contrato` se toca `packages/contracts`;
   - `infra` para ferramentas e repositório.
9. Atualize o quadro em `docs/plan.md` (linha nova ou alterada, com o status igual ao do arquivo).
10. **Alteração de SPEC existente:**
    - adicione ou atualize a seção `## Histórico` no fim (data, mudança, motivo, quem pediu);
    - se a SPEC estava `Ready` ou em andamento, marque "**Aguardando reaprovação humana**".

## Regras de qualidade dos critérios de aceite

- **Formato:** `CA-NN — Dado <estado>, quando <ação>, então <resultado observável>`.
- Cada CA é **verificável por um teste automatizado**, com valores concretos (status HTTP, campos, contagens, limites). Proibido: "funciona bem", "rápido", "amigável".
- Inclua pelo menos um CA de **erro** para cada entrada externa (inválida, sem autenticação, grande demais).
- Os CAs de segurança e de regras inegociáveis aplicáveis (R-02, R-03, R-05, R-06, R-11, R-12) devem ser explícitos.
- Um CA não pode depender de serviço externo real (internet, Supabase de produção).
- Quando algo só pode ser verificado à mão (por exemplo, a câmera do celular), escreva o CA como **manual**, com passos numerados, e marque `(manual)`.

## Checklist final

- [ ] Todos os campos do cabeçalho preenchidos
- [ ] "Fora" aponta para outras SPECs
- [ ] Todo CA tem Dado/Quando/Então com valores concretos
- [ ] Tags corretas (portão de segurança)
- [ ] Sem contradição com `rules.md`, `architecture.md` e os ADRs aceitos
- [ ] `docs/plan.md` atualizado
