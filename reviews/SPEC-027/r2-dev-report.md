# SPEC-027 — r2 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r2 |
| Autor | developer |
| Branch | `spec/SPEC-027-manutencao-api` |
| Commits | `00f121e` (e o commit deste relatório) |

## Resumo

A r2 trata só o SEC-01 do [r1-security-report](r1-security-report.md), que é o RV-01 do [r1-review-report](r1-review-report.md). Ela segue a correção e a lista de testes que o security-report exige do developer.

- **Correção (§2 e §4.3.5):** dentro do mesmo `try` de `_api_url` (`scripts/simulate.py:423-428`), o host passa a ser conferido na forma que chega ao socket: `httpx.URL(url).raw_host.decode("ascii").encode("idna")`. O `UnicodeError` do codec é um `ValueError`, então cai no `except` que já existia: `invalid --api-url (not shown)`, com código 2 e sem traceback.
- **Uso do `raw_host`:** usei o `raw_host`, e não o `.host`, como pede o security-report. O `.host` devolve a forma Unicode de um rótulo `xn--`, e o nameprep do IDNA 2003 poderia recusá-la por engano. A conferência anterior (`_ = httpx.URL(url).host`, decisão 6 da r1) continua no lugar, porque é ela que fecha o `xn--zz`.
- **Fora do escopo:** nenhuma outra mudança de produção. SEC-02 a SEC-04, RV-02 e RV-03 não foram tocados, como determinado.

## Rastreabilidade (critério de aceite → implementação)

Na r2, só mudam as linhas do CA-09 e do CA-11 (as duas são sobre o simulador). As demais linhas são as do [r1-dev-report](r1-dev-report.md) e não mudaram. `sim/` = `scripts/tests/test_simulate.py`.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 a CA-08, CA-10, CA-12 | sem mudança na r2 | os da tabela do r1-dev-report |
| CA-09 (e §4.3.5) | `scripts/simulate.py` (`_api_url`) | os da r1, mais: `sim/::test_api_url_with_label_the_socket_refuses_is_refused[double-dot\|leading-dot\|two-trailing-dots\|label-64\|single-label-64]` (código 2, nenhuma requisição na API falsa, `invalid --api-url (not shown)`, sem `Traceback` e sem trecho do host no stdout ou no stderr), `sim/::test_socket_codec_really_refuses_those_hosts` (confere a premissa: o codec `idna` sobre o `raw_host` recusa esses hosts, já que o `MockTransport` não passa pelo socket), e `sim/::test_visible_ascii_api_url_still_sends`, ampliado para os casos de aceitação |
| CA-11 | `scripts/simulate.py` | o mesmo da r1, mais os testes de recusa acima, que verificam código 2 |

### Casos exigidos pelo SEC-01 → teste

| Host | Esperado | Teste |
|---|---|---|
| `https://exa..mple.com` | recusa | `…socket_refuses_is_refused[double-dot]` |
| `https://.example.com` | recusa | `…[leading-dot]` |
| `https://example.com..` | recusa | `…[two-trailing-dots]` |
| rótulo de 64 caracteres (`https://aaa…(64).example.com` e `https://aaa…(64)`) | recusa | `…[label-64]`, `…[single-label-64]` |
| `https://example.com.` | aceitação | `test_visible_ascii_api_url_still_sends[https://example.com.]` |
| rótulo de 63 caracteres (com e sem `.example.com`) | aceitação | `test_visible_ascii_api_url_still_sends[https://aaa…]` (2 casos) |
| `https://[::1]` (e `https://[::1]:8443`) | aceitação | `test_visible_ascii_api_url_still_sends[https://[::1]]`, `[https://[::1]:8443]` |
| `https://xn--nxasmq6b.com` | aceitação | `test_visible_ascii_api_url_still_sends[https://xn--nxasmq6b.com]` |
| `localhost` (`http://localhost:8001`) | aceitação | `test_visible_ascii_api_url_still_sends[http://localhost:8001]` |
| `127.0.0.1` (`http://127.0.0.1` e `http://127.0.0.1:8001`) | aceitação | `test_visible_ascii_api_url_still_sends[http://127.0.0.1]`, `[http://127.0.0.1:8001]` |

Os casos de aceitação conferem código 0 e exatamente 1 requisição de lote na API falsa.

## Resposta à rodada anterior (a partir de r2)

| Achado (relatório, ID) | O que mudou |
|---|---|
| r1-security-report, SEC-01 (alta) = r1-review-report, RV-01 (média) | `_api_url` confere `httpx.URL(url).raw_host.decode("ascii").encode("idna")` dentro do `try` que já existia. Agora os hosts com rótulo vazio ou com mais de 63 caracteres saem com código 2 e `invalid --api-url (not shown)`, sem traceback e antes de qualquer requisição. Os testes de recusa e de aceitação estão listados acima. |
| r1-security-report, SEC-02 a SEC-04 | Nenhuma mudança, por instrução do orquestrador (o próprio relatório diz que não exigem mudança nesta SPEC). |
| r1-review-report, RV-02 (OBS-04) | É do tester. Não mexi no test-report nem em `tests/acceptance/`. |
| r1-review-report, RV-03 | É sugestão de texto para o architect. Nenhuma ação do developer. |

## Como rodar e verificar

```bash
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run pytest -q scripts/tests/test_simulate.py -k "api_url or socket_codec"
uv run pytest -q
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
```

Resultado das minhas execuções no `00f121e`:

- `ruff check .`: limpo. `ruff format --check .`: 116 arquivos já formatados.
- `pytest -q` sem banco: **2110 passed, 642 skipped**, 0 falhas.
- `pytest -q` com banco (`TEST_DATABASE_URL` local): **2752 passed**, 0 falhas, 0 erros. O único warning é o `StarletteDeprecationWarning`, que já existia.

Outras verificações:

- **Mutação:** troquei a nova linha por `pass` e rodei `-k socket_refuses`. Os 5 casos de recusa falharam. Depois restaurei o arquivo, e o `git diff` ficou limpo antes do commit.
- **Reprodução do SEC-01 com o script real, em processo próprio:** usei uma chave gerada por `secrets` e, sem rede, os hosts `exa..mplemark.invalid/pathtok`, `.examplemark.invalid`, `examplemark.invalid..` e um rótulo de 64 caracteres. Antes da correção, o security-report registrou `exit=1` com `UnicodeError`. Agora os 4 dão `exit=2`, e a última linha é `simulate.py: error: invalid --api-url (not shown)`. Rodei manualmente, fora da suíte, com a saída no scratchpad.

## Decisões tomadas dentro do escopo da SPEC

1. **As duas conferências ficam.** O `.host` (r1, decisão 6) recusa os `xn--` inválidos, como `xn--zz.com`, que o httpx rejeitaria ao montar a requisição. Esse host passa pelo codec `idna` do socket, então só o `raw_host` não o recusaria. O `raw_host` com o codec `idna` recusa o que o socket rejeitaria. Uma conferência não substitui a outra, e as duas usam a mesma mensagem e o mesmo código 2.
2. **Teste da premissa.** O `MockTransport` não passa pelo socket, e por isso os testes de recusa ficariam verdes mesmo se o codec deixasse de recusar esses hosts (a premissa do achado). O `test_socket_codec_really_refuses_those_hosts` deixa essa premissa explícita, sem rede.
3. **Casos extras de aceitação.** `https://[::1]:8443`, `http://127.0.0.1` sem porta e o rótulo de 63 caracteres sem domínio são extras baratos, na mesma linha dos casos exigidos. Nenhum deles muda o comportamento.

## SPEC_ISSUE (se houver)

Nenhuma.

## Checagens do autor

- [x] `uv run ruff check .` e `uv run ruff format --check .` limpos
- [x] Testes unitários do autor passando, com banco e sem banco
- [x] `.env.example` atualizado (se houver variável nova): não há variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma credencial fictícia como literal em URL, conninfo ou header (a chave dos testes vem de `secrets`)
- [x] Nenhum teste novo roda o pytest nem o simulador em subprocesso
