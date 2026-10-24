# ADR-021: Aceitar tipos de objeto sem grau no contrato e contar no SPC só as inspeções com grau

| Campo | Valor |
|---|---|
| Status | Proposto |
| Data | 2026-10-24 |
| Decisores | Dupla (redigido pelo agente architect, a pedido do humano, que liberou as Fases 2 e 3 em 2026-10-24) |
| Relacionados | ADR-001, ADR-005, ADR-013 (complementado, não substituído), ADR-014, ADR-020, ADR-022, SPEC-002, SPEC-003, SPEC-005, SPEC-006, SPEC-008, SPEC-013, SPEC-016, SPEC-017, SPEC-021, SPEC-026, R-04, R-06, R-11 |

## Contexto

- O contrato vigente (`qc-contracts` 0.3.0, `docs/architecture.md` §3.2) exige `grade` nulo **se e somente se** `object_type == unknown`. O banco espelha a regra (`check ((object_type = 'unknown') = (grade is null))`, `docs/architecture.md` §5).
- O PRD §4.2 pede **identificação** obrigatória das 5 ferramentas manuais e grau "só se houver dados suficientes" (critério da SPEC-016). O PRD §4.3 e §4.4 pedem só identificação das 4 ferramentas elétricas, porque o estado interno delas está fora do escopo. Uma ferramenta identificada sem grau precisa de `grade = null` com `object_type != unknown`, o que o contrato atual recusa (pergunta 1 da SPEC-016, bloqueante, e pergunta 1 da SPEC-021).
- Se uma ferramenta tem grau depende dos dados (critério por tipo). Esse resultado só existe depois da coleta e pode mudar de um modelo para o outro. Fixar no contrato quais ferramentas têm grau obrigaria a mudar o contrato a cada modelo.
- O SPC conta hoje os registros com `object_type != unknown` (§3.4), e a taxa de defeito do resumo usa `total − unknown_count` no denominador (SPEC-005). Uma inspeção de ferramenta sem grau entraria nas duas contas como "não defeituosa" e diluiria `p`.
- A skill `contrato-api` classifica como **minor** um valor novo de enum. Ela não classifica a mudança de invariante. Aqui, todo payload válido na 0.3.0 continua válido na 0.4.0 e com o mesmo significado: a regra só passa a aceitar `grade = null` para os valores **novos** do enum. `is_defective` não muda.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Três grupos de tipos no contrato: **com grau obrigatório** (`screw`, `nut`), **sem grau** (`unknown` e as ferramentas elétricas) e **grau opcional** (as ferramentas manuais). O modelo declara no `labels.json` quais tipos ele não gradua (`ungraded_object_types`). O SPC e a taxa de defeito passam a contar as inspeções **com grau** (`grade is not null`) | Nenhum payload antigo muda de validade nem de significado; o contrato não muda quando o critério de dados muda; para os dados do MVP, o SPC e a taxa de defeito dão exatamente o mesmo resultado de hoje | A invariante fica mais longa; o banco precisa de um `check` com três ramos; a carta de um lote de ferramentas sem grau fica vazia |
| B Campo novo `graded: bool` no `InspectionCreate` | Explícito | Campo obrigatório novo = mudança **major** (skill `contrato-api`); redundante com `grade is null` |
| C Só aceitar no contrato as ferramentas que cumprem o critério de grau | Invariante intacta | Contraria o PRD (identificação obrigatória das 5 manuais e das 4 elétricas); as elétricas nunca teriam grau |
| D Lista fixa no contrato das ferramentas manuais sem grau | Invariante simples | Muda o contrato a cada modelo em que o critério de dados mudar; exige migração do banco junto |
| E Grau falso (`perfect`) para tipos sem grau | Nada muda no contrato | Mente nos dados (R-11) e entra no SPC como peça boa |

## Decisão

1. **Grupos de tipos** em `qc_contracts` (constantes públicas, `frozenset`): `GRADE_REQUIRED_OBJECT_TYPES = {screw, nut}` (grau obrigatório), `GRADE_FORBIDDEN_OBJECT_TYPES = {unknown}` mais as ferramentas elétricas quando entrarem (SPEC-021), e `GRADE_OPTIONAL_OBJECT_TYPES` = as ferramentas manuais (SPEC-016). Todo membro de `ObjectType` está em exatamente um grupo. A invariante passa a ser: tipo com grau obrigatório ⇒ `grade` não nulo; tipo sem grau ⇒ `grade` nulo; tipo com grau opcional ⇒ qualquer um dos dois. `grade_score` e `grade_confidence` continuam nulos **se e somente se** `grade` é nulo.
2. **Versão:** a mudança é **minor** (0.3.0 → 0.4.0 na SPEC-016; 0.6.0 na SPEC-021, na ordem proposta em `docs/plan.md`), porque só amplia o que é aceito para valores novos do enum. O banco recebe uma migração com o `check` equivalente.
3. **SPC e taxa de defeito:** os registros considerados passam a ser os com `grade is not null` (antes, `object_type != unknown`). Com os dados do MVP, as duas regras selecionam as mesmas linhas. O resumo (`MetricsSummary`) mantém os campos e o significado de `unknown_count` (só `object_type = unknown`); o denominador de `defect_rate` passa a ser o número de inspeções com grau. O filtro `object_type` do SPC aceita os tipos com grau obrigatório e os com grau opcional, numa enumeração declarada (não derivada do `ObjectType`).
4. **Modelo:** o `labels.json` ganha a chave opcional `ungraded_object_types` (lista, padrão `[]`), com os tipos do modelo que ele não gradua. Ela só pode conter tipos de `GRADE_OPTIONAL_OBJECT_TYPES` ou de `GRADE_FORBIDDEN_OBJECT_TYPES`. Na borda, um tipo dessa lista sai com `grade`, `grade_score` e `grade_confidence` nulos. Todo tipo de `GRADE_FORBIDDEN_OBJECT_TYPES` presente no modelo (as elétricas) tem de estar na lista.
5. `is_defective` e a ADR-013 não mudam: `grade = None` não é defeito e não entra no SPC.

## Consequências

- **Positivas:**
  - as ferramentas entram no contrato sem esperar os dados; o critério de grau da SPEC-016 decide, a cada modelo, só o `labels.json`;
  - a carta p e a taxa de defeito do MVP não mudam de valor;
  - a regra "sem grau não entra no SPC" vale do mesmo jeito para `unknown`, para as ferramentas sem grau e para as elétricas.
- **Negativas / custos aceitos:**
  - um leitor com o contrato 0.3.0 recusa uma inspeção de ferramenta (valor novo do enum). Por isso a ordem de deploy da skill `contrato-api` (contracts → banco → API → dashboard → borda) vale inteira, e a SPEC-034 (reenvio de `dead`) tem de estar `Done` antes;
  - a carta de um lote só de ferramentas sem grau fica sem pontos (`message` da SPEC-006), o que é o comportamento certo;
  - uma ferramenta manual pode aparecer com e sem grau em modelos diferentes; o dashboard mostra "sem grau" no lugar do grau.
- **O que passa a ser obrigatório:**
  - `qc_contracts` com os três grupos, a invariante nova e testes de cada ramo (SPEC-016; SPEC-021 para as elétricas);
  - migração do banco com o `check` equivalente e teste de equivalência com o contrato (como a SPEC-003);
  - SPC (`lot_selection`) e taxa de defeito (`defect_rate`) com `grade is not null`, e enum `SpcObjectType` declarado (SPEC-016);
  - borda: `labels.json.ungraded_object_types` lido e validado, e decisão sem grau para esses tipos (SPEC-016);
  - qualquer SPEC que crie um tipo novo diz em qual grupo ele entra.

## Quando revisitar

- Se uma ferramenta elétrica passar a ter grau (o PRD §4.4 hoje exclui).
- Se o professor pedir cartas separadas por tipo como padrão, em vez do filtro `object_type`.
- Se um leitor externo ao repositório passar a consumir a API (a mudança de invariante teria de ser comunicada como quebra para ele).
