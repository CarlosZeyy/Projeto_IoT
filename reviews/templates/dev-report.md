# SPEC-XXX — rN — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-XXX](../../docs/specs/SPEC-XXX-slug.md) |
| Rodada | rN |
| Autor | developer \| ml-engineer \| security-devops |
| Branch | `spec/SPEC-XXX-slug` |
| Commits | `abc1234`, `def5678` |

## Resumo

O que foi feito, em 3 a 6 linhas.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | `api/src/qc_api/...` | `api/tests/test_x.py::test_y` |

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|

## Como rodar e verificar

```bash
uv sync --package qc-xxx
uv run pytest api/tests -q
```

## Decisões tomadas dentro do escopo da SPEC

Escolhas locais (nomes, estrutura interna). Nada que altere contrato, regra ou ADR.

## SPEC_ISSUE (se houver)

Ambiguidade ou contradição encontrada na SPEC. O orquestrador deve acionar o architect.

## Checagens do autor

- [ ] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [ ] Testes unitários do autor passando
- [ ] `.env.example` atualizado (se houver variável nova)
- [ ] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
