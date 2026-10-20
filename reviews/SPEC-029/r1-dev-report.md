# SPEC-029 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-029](../../docs/specs/SPEC-029-manutencao-dashboard-simulador.md) |
| Rodada | r1 |
| Autor | developer |
| Branch | `spec/SPEC-029-manutencao-dashboard-simulador` |
| Commits | só este relatório (implementação **não iniciada**, ver SPEC_ISSUE) |

## Resumo

Implementação parada antes do primeiro commit de código, por uma contradição entre o escopo da §3.1 e o CA-04 (SPEC_ISSUE-01 abaixo). Nenhum arquivo de código ou de teste foi alterado. As partes §4.2 (selo pela origem devolvida) e §4.4 (caso `xn--1-zhc.com`) não dependem da resolução; a §4.3 depende só no ponto descrito.

Premissa da §4.4 conferida: com o `httpx` do `uv.lock`, `httpx.URL("https://xn--1-zhc.com").raw_host.decode("ascii").encode("idna")` funciona e `httpx.URL(...).host.encode("idna")` levanta `UnicodeError`, como a SPEC diz.

## Rastreabilidade (critério de aceite → implementação)

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 | (tester, §4.1) | — |
| CA-02 | (tester, §4.1) | — |
| CA-03 | não iniciado | — |
| CA-04 | não iniciado (bloqueado pela SPEC_ISSUE-01) | — |
| CA-05 | não iniciado | — |

## Resposta à rodada anterior (a partir de r2)

Não se aplica (r1).

## Como rodar e verificar

Nada a verificar nesta rodada. Reprodução da SPEC_ISSUE-01:

```bash
uv run python -c "print(repr('https://api.example.org/\x85'.strip()), '\x85'.isspace())"
# 'https://api.example.org/' True
```

## Decisões tomadas dentro do escopo da SPEC

Nenhuma.

## SPEC_ISSUE (se houver)

### SPEC_ISSUE-01 — CA-04 com `https://api.example.org/\x85` não é atingível mexendo só em `is_secure_api_url`

- **§3.1** limita a mudança em `dashboard/src/qc_dashboard/config.py` a "**só** `is_secure_api_url` (§4.3)".
- **CA-04** exige que `config.get_settings()` levante `InsecureApiUrlError` (e que a Visão geral mostre `Configuração inválida`) para `API_BASE_URL` igual a `https://api.example.org/\x85`.
- Hoje `get_settings()` lê o valor por `_read()`, que faz `str(value).strip()` (SPEC-013 §4.1, "valores vazios contam como ausentes") **antes** de chamar `is_secure_api_url`. U+0085 (NEL) é espaço para o `str.strip()` do Python (`"\x85".isspace()` é `True`), então o valor que chega a `is_secure_api_url` é `https://api.example.org/`, uma URL válida. Resultado: `get_settings()` devolve as configurações sem erro, e o CA-04 falha nesse caso, qualquer que seja a implementação de `is_secure_api_url`.
- O mesmo vale para qualquer `Cc` que o `str.strip()` trata como espaço (`\t`, `\n`, `\x0b`, `\x0c`, `\r`, `\x1c`–`\x1f`, `\x85`) quando está **na ponta** do valor. Os outros casos do CA-04 (`\t` e `\n` no meio, `\x7f` no fim, que não é espaço para o `strip`, porta inválida) funcionam com a mudança só em `is_secure_api_url`.

Resoluções possíveis (a escolha é do architect/humano):

1. **Ampliar a §3.1**: permitir que `get_settings()` (ou `_read()`) aplique a checagem de `Cc` ao valor de `API_BASE_URL` **antes** do `strip()`. Efeito colateral: um `API_BASE_URL` com `\n` ou `\t` só na ponta (ex.: copiado com quebra de linha para o `secrets.toml` ou para o ambiente), hoje aceito, passa a ser recusado com `Configuração inválida`. Precisa dizer se a regra vale também para `READ_API_KEY` (a SPEC não pede).
2. **Trocar o caso do CA-04** por um com U+0085 no meio do valor (ex.: `https://api.exa\x85mple.org`) ou em posição que o `strip()` não remove, mantendo a §3.1 como está. O comportamento "controle na ponta é aparado e a URL aparada é aceita" continua o de hoje (SPEC-013).

Com qualquer das duas, a implementação de `is_secure_api_url` é a da §4.3, sem outra mudança.

## Checagens do autor

- [ ] `uv run ruff check .` e `uv run ruff format --check .` limpos (não rodados: nenhum código alterado)
- [ ] Testes unitários do autor passando (nenhum escrito)
- [x] `.env.example` atualizado (se houver variável nova): nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
