# SPEC-XXX — rN — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-XXX](../../docs/specs/SPEC-XXX-slug.md) |
| Rodada | rN |
| Tester | tester |
| Commit testado | `abc1234` |
| **Veredicto** | **PASS** \| **FAIL** |

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `api/tests/acceptance/test_spec_xxx.py::test_ca01_...` | ✅ / ❌ |

## Suíte completa

```text
(colar o resumo do pytest: N passed, M failed, cobertura dos módulos relevantes)
(colar o resumo do ruff)
```

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | alta | CA-03 | 1. ... 2. ... | ... | ... |

## Testes exploratórios (além dos critérios)

Casos de borda testados e o resultado.

## SPEC_ISSUE (se houver)

## Declaração

- [ ] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
