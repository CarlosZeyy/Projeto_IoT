# SPEC-027 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-027](../../docs/specs/SPEC-027-manutencao-api-banco-simulador.md) |
| Rodada | r2 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...c5c85d6`, com foco em `798fb63..c5c85d6` (o que mudou desde o [r1-security-report](r1-security-report.md)) |
| **Veredicto** | **PASS** |

O SEC-01 da r1 (= RV-01 do r1-review-report) foi fechado exatamente como eu exigi, e a correção não abriu caminho novo. Não há achado bloqueante, alto ou médio nesta rodada. Os SEC-02 a SEC-04 da r1 seguem os destinos que dei a eles (tabela abaixo). O resto do diff `main...HEAD` (migração `002`, log da escrita, parser sem eco, lote com até 4 dígitos) não mudou desde a r1, e as conclusões daquele relatório continuam valendo.

## Superfície analisada

- **Produção:** só `scripts/simulate.py:423-428`, 6 linhas em `_api_url` (1 de código e 5 de comentário). Não há mudança em `api/`, `infra/`, `pyproject.toml`, `uv.lock` ou `.env.example` desde a r1 (`git diff 798fb63..HEAD --stat` nesses caminhos fica vazio).
- **Testes:** `scripts/tests/test_simulate.py` (autor) e `scripts/tests/acceptance/test_spec_027.py` (tester).
- **Documentos:** `docs/plan.md` e o cabeçalho da SPEC, que só mudam de status e de rodada, e os relatórios da r2.
- **Entrada externa:** `--api-url` / `CLOUD_API_URL`.

### Verificações feitas (só leitura)

- **A linha da correção:** é `_ = httpx.URL(url).raw_host.decode("ascii").encode("idna")`, dentro do mesmo `try`/`except (ValueError, httpx.InvalidURL)` que leva a `parser.error(f"invalid --api-url {NOT_SHOWN}")` e ao código 2. Ela usa o `raw_host`, e não o `.host`. A conferência da r1 (`httpx.URL(url).host`, que fecha o `xn--zz`) continua no lugar. A ordem das validações e as mensagens não mudaram. A URL devolvida é a mesma de antes (`url.rstrip("/")`), e o `rstrip` não altera o host, porque a `/` sempre encerra a autoridade.
- **Fuzz com o `simulate.py` real, cada caso em um processo próprio (`python -I`):** 140 URLs `https://`, com chave `"Z" + secrets.token_urlsafe(24)` gerada na hora, combinando 35 hosts com 4 caminhos (vazio, `/pathtok`, `//`, `/%2e%2e/pathtok`). Os hosts foram:
  - os do SEC-01: `exa..mplemark.invalid`, `.examplemark.invalid`, `examplemark.invalid..`, rótulo de 64 caracteres com e sem domínio;
  - os que devem ser aceitos: ponto final simples, rótulo de 63 caracteres, `xn--nxasmq6b`, `XN--NXASMQ6B` e um host de 263 caracteres com rótulos de 63;
  - IPv6: `[::1%25lo]`, `[fe80::1%25eth0]`, `[::ffff:127.0.0.1]`, `[v1.x]`, `[::1`, `::1]` e `[]`;
  - outros: `999.1.1.1`, `0x7f.1`, rótulos começando ou terminando com `-`, `_`, portas `:0`, `:65536` e porta vazia, `%2e%2e`, `%00` e `%e2%82%ac` no host, `xn--`, `xn---`, `.`, `..` e `a.`.

  Resultado: **0 casos ruins**. O código foi sempre 2 (`invalid --api-url (not shown)`) ou 5 (`health check failed: ConnectError`), sem `Traceback` e sem código 1. A chave, os primeiros 12 caracteres dela, `examplemark`, `pathtok` e `qqqq` não aparecem no stdout nem no stderr. Os 4 hosts que davam `exit=1` com `UnicodeError` na r1 agora dão 2. Os hosts válidos chegam ao socket e falham só na rede (código 5), então não há recusa falsa.
- **Resolução numérica abreviada:** um caso `https://1.2.3` ficou fora da contagem. A libc o resolve por `inet_aton` como `1.2.0.3`, um endereço público, e o simulador espera o `HEALTH_TIMEOUT_S` de 90 s. Isso é o comportamento normal de uma URL que o operador escolhe, não está no escopo do SEC-01 e não abre caminho de erro: o resultado seria `ConnectTimeout`, que é um `RequestError` e dá código 5. Interrompi o caso para não tentar conexões com endereços de terceiros.
- **Testes do simulador:** `uv run pytest -q -p no:cacheprovider scripts/tests/test_simulate.py scripts/tests/acceptance/test_spec_027.py` deu **363 passed, 2 skipped** (os 2 precisam de `TEST_DATABASE_URL`) e 1 warning, o `StarletteDeprecationWarning` que já existia. Não rodei a suíte inteira, que o developer (2752 passed com banco), o tester e o reviewer já rodaram.
- **Cobertura dos casos exigidos:** os testes do autor têm os 4 hosts de recusa (o rótulo de 64 aparece com e sem domínio) e os 6 de aceitação que pedi, além do teste da premissa sobre o codec. O tester acrescentou os mesmos casos como extras do CA-11, com caminho real até `socket.create_connection` e `getaddrinfo` com `AI_NUMERICHOST`, sem DNS. Ele também acrescentou o `xn--1-zhc.com`, que separa o `raw_host` do `.host` (o RV-01 baixo do r2-review-report trata disso). A OBS-04 (RV-02 da r1) foi corrigida.
- **R-03 nos testes:** procurei no diff da r2, em `scripts/tests`, por `://usuario:senha@`, `password=`, `X-API-Key` com valor literal, `eyJ`, `sk_`, `service_role`, chave privada e `api_key=` com valor. Não há nenhuma ocorrência. As chaves e os marcadores vêm de `secrets` em tempo de execução.
- **Trailers e identidade:** os 9 commits de `798fb63..HEAD` são de `CarlosZeyy` (noreply). Os `Agent:` conferem com os arquivos tocados: `developer` em `00f121e` (código e teste do autor) e `8c1629b` (dev-report), `tester` em `65ab53e` (aceite e test-report), `reviewer` em `0430f87`, `orchestrator` nos commits de status e `security-devops` só no `02a8449` (meu r1-security-report). Não sou autor de nenhuma mudança de código.

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| — | — | — | — | Nenhum achado novo nesta rodada. | — |

### Destino dos achados da r1

| ID (r1) | Severidade | Estado na r2 |
|---|---|---|
| SEC-01 (= RV-01) | alta | **Fechado.** A correção é exatamente a exigida (`raw_host`, no mesmo `try`, código 2, sem eco). Os testes do autor e os extras do tester cobrem a lista de recusa e de aceitação. O fuzz em processo real não encontrou traceback nem código 1. |
| SEC-02 | baixa | Segue como a r1 determinou: sem mudança nesta SPEC. Na SPEC-015 (CA-14/CA-19), depois de migrar a produção, conferir `select conname, pg_get_constraintdef(oid) from pg_constraint where conrelid = 'inspections'::regclass and conname like 'inspections\_%\_check' order by 1;` contra a tabela do §4.1. |
| SEC-03 | info | Sem ação, como na r1. |
| SEC-04 | info | **Superado.** O caminho do `UnicodeError` até o traceback deixou de existir com o fechamento do SEC-01. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: nenhuma rota ou autenticação mudou. |
| Entradas validadas | ✅ O host passa a ser conferido também na forma que chega ao socket. O item que ficou ❌ na r1 (SEC-01) agora está ✅. O resto segue como na r1. |
| SQL sempre parametrizado | ✅ Nada mudou desde a r1. |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | ✅ Nada mudou desde a r1. |
| CORS | N/A. |
| Logs sem segredos e sem imagem | ✅ A recusa nova usa a mensagem `(not shown)`, que já existia, sem o host, o caminho nem a chave. |
| Dependências novas | N/A: nenhuma. |
| Deploy | N/A nesta SPEC. A pendência do SEC-02 vai para a SPEC-015. |
| R-03 nos testes | ✅ Nenhuma credencial ou chave fictícia literal em URL, conninfo ou header. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. `httpx` 0.28.1 já estava no `uv.lock`. |

## Ações pendentes para o humano

- Nenhuma nesta SPEC. Na SPEC-015 (CA-14/CA-19), incluir a consulta do SEC-02 depois de migrar a produção.

## Declaração

- [x] Não editei código; não sou autor desta SPEC. Só escrevi este relatório. O script de fuzz ficou no scratchpad da sessão, fora do repositório.
