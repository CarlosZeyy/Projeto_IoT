# SPEC-NNN: Título

| Campo | Valor |
|---|---|
| Status | Draft \| Ready \| In Dev \| In Test \| In Review \| In Security \| Done \| Blocked \| Escalated |
| Rodada atual | — \| r1 \| r2 \| r3 |
| Autor da implementação | developer \| ml-engineer \| security-devops |
| Tags | contrato, security, deploy, infra (as tags `security`/`deploy` ativam o portão de segurança) |
| Depende de | SPEC-xxx |
| Semana alvo | Sx |
| Requisitos cobertos | RF-xx, RNF-xx |
| ADRs relevantes | ADR-xxx |

## 1. Contexto

Por que esta entrega existe e onde ela se encaixa em `docs/architecture.md`.

## 2. Objetivo

Uma frase com o resultado observável.

## 3. Escopo

### 3.1 Dentro

- Itens concretos: arquivos/módulos esperados, rotas, comandos.

### 3.2 Fora

- O que **não** fazer aqui (e em qual SPEC isso entra).

## 4. Requisitos detalhados

Interfaces, assinaturas, rotas, schemas, variáveis de ambiente e comportamento em erro. Referencie `architecture.md` em vez de duplicar; detalhe aqui só o que for específico.

## 5. Critérios de aceite

Cada critério deve ser **testável e independente**. O tester escreve um teste por critério.

- **CA-01** — *Dado* ..., *quando* ..., *então* ....
- **CA-02** — ...

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | | `<comp>/tests/` |
| Aceite (tester) | Um por CA | `<comp>/tests/acceptance/test_spec_NNN.py` |
| Manual (dupla), se houver | | descrito aqui |

Não crie CA de "suíte inteira" (`ruff` + `pytest -q` = 0) como teste automatizado: o CI e o test-report já verificam isso (`docs/architecture.md` §10).

Se a SPEC aumenta a versão de um pacote, siga as "Expectativas de versão" de `docs/architecture.md` §10. O CA fixa a versão nova, e a §3.1 autoriza o tester a converter só as asserções exatas do arquivo de aceite da SPEC vigente anterior.

## 7. Riscos e notas para o implementador

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED (+ security-report PASS, se tag `security`/`deploy`)
- [ ] CI verde; `ruff` limpo
- [ ] Documentação afetada atualizada (README, `.env.example`, `architecture.md` via architect se necessário)
- [ ] PR aberto com os relatórios; merge humano
