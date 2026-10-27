# SPEC-021 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-021](../../docs/specs/SPEC-021-ferramentas-eletricas.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-021-ferramentas-eletricas` |
| Commits | o commit deste relatório (só documentação: `reviews/SPEC-021/r1-dev-report.md` e este arquivo) |

## Resumo

Correção do bug T-01 de `reviews/SPEC-021/r1-test-report.md`, único motivo do FAIL da r1. Nenhum código de produção nem teste mudou.

## Resposta à rodada anterior

| Achado (relatório, ID) | O que mudou |
|---|---|
| `r1-test-report.md`, T-01 | A "Observação fora do escopo" da Parte A em `r1-dev-report.md` citava, entre crases, a URL Postgres de exemplo com usuário e senha, e o scanner de segredos acusava o arquivo. A linha foi reescrita sem o literal ("URL de banco de exemplo, com usuário e senha embutidos") e marcada como resolvida pelo merge da SPEC-020 na branch (`de2afcc`), que corrigiu o relatório da 020. |

## Rastreabilidade

Sem mudança em relação à r1 (`r1-dev-report.md`, Partes A e B).

## Como rodar e verificar

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest -q infra/tests/acceptance/test_spec_015.py::test_ca05_no_secret_material_outside_docs \
    infra/tests/test_deploy_files.py::test_no_secret_material_in_tracked_files
```

Resultado: os 2 testes passam (sem banco); ruff limpo.

## SPEC_ISSUE (se houver)

Nenhum.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Os 2 testes de segredo do T-01 passando
- [x] `.env.example` sem mudança (nenhuma variável nova)
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
