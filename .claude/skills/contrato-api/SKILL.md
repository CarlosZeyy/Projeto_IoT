---
name: contrato-api
description: Regras para usar e evoluir o contrato compartilhado (pacote qc-contracts) entre borda, API e dashboard do PartQC — versionamento, compatibilidade, enums, rótulos PT-BR e regra de defeito. Use ao implementar qualquer payload trocado entre componentes ou ao propor mudança de schema.
---

# Contrato compartilhado (`packages/contracts` → `qc_contracts`)

A fonte de verdade descritiva é `docs/architecture.md` §3. O código em `qc_contracts` **implementa** essa seção. Se divergirem, é bug: reporte.

## Uso (todos os componentes)

- Importe os schemas e enums de `qc_contracts`. Nunca redefina um payload localmente (dict "na mão", outra classe Pydantic com os mesmos campos).
- A regra de defeito é **só** `qc_contracts.is_defective(grade)`. No banco, ela é espelhada pela coluna gerada `is_defective` (a SPEC-003 garante a equivalência por teste).
- Rótulos PT-BR para a interface: `qc_contracts.labels` (`GRADE_LABELS_PT`, `OBJECT_TYPE_LABELS_PT`, `SOURCE_LABELS_PT`).
- Versão do contrato: `qc_contracts.__version__` (semver). A API a expõe em `/api/v1/health` (`contract_version`).

## Evolução

| Mudança | Tipo | Exige |
|---|---|---|
| Novo campo **opcional** com default | minor (0.x → 0.x+1) | SPEC com a tag `contrato` |
| Novo valor de enum (ex.: ferramentas da Fase 2) | minor | SPEC com a tag `contrato` + migração do `check` no banco + rótulo PT-BR |
| Remover ou renomear campo, mudar tipo, tornar obrigatório | **major** | ADR + SPEC + plano de migração de borda, API e dashboard **no mesmo PR** |
| Mudar a regra `is_defective` | **major** | ADR (altera ADR-013) |

**Ordem de deploy de uma mudança:** pacote `contracts` → banco (migração) → API → dashboard → borda. A API deve aceitar a versão anterior da borda durante a transição, e é a SPEC que define essa janela.

## Checklist

- [ ] `extra="forbid"` em todos os modelos de entrada
- [ ] Validadores das invariantes (ex.: `grade is None ⇔ object_type == unknown`; `grade_score` e `grade_confidence` nulos junto com `grade`)
- [ ] Datas com fuso, normalizadas para UTC
- [ ] Testes de serialização ida e volta e de cada invariante em `packages/contracts/tests/`
- [ ] `__version__` atualizado e registrado no histórico do `packages/contracts/README.md`
