# SPEC-004 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-004](../../docs/specs/SPEC-004-api-ingestao.md) |
| Rodada | r2 (primeira revisão desta SPEC: a r1 parou no FAIL do tester, então o diff foi revisado por inteiro) |
| Reviewer | reviewer |
| Diff revisado | `docs/pendencias-pos-024...33e9e36` (branch empilhada sobre o PR #10) |
| Test report | [r2-test-report.md](r2-test-report.md) (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante, alto ou médio. Ficam 2 achados baixos, que não bloqueiam.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | baixa | `api/src/qc_api/middleware.py:120-121` (com `api/src/qc_api/routers/inspections.py:45-58`) | O `logger.exception("unhandled exception")` registra a mensagem da exceção e de toda a cadeia. A rota só converte `psycopg.DataError` (classe `22`). Uma `IntegrityError` de `check` (classe `23`) chegaria a esse log com o `DETAIL: Failing row contains (...)`, ou seja, com todos os valores do payload, a mesma classe de vazamento do T-02. Hoje esse caminho é inalcançável: as `check` do `001_init.sql` espelham o contrato (análise do tester na r2, que conferi por amostragem). Mas basta uma migração futura divergir do contrato para que ele volte a existir, e só falharia em produção. | Nada a fazer nesta SPEC (o §7 manda capturar só a classe `22`). Na próxima SPEC que mexer em migração ou na API (SPEC-005, ou um achado do security-devops), avaliar um tratamento de `IntegrityError` em volta da escrita que registre só a rota, o `device_id` e o SQLSTATE, como já é feito com o `DataError`. |
| RV-02 | baixa | `packages/contracts/tests/acceptance/test_spec_023.py:4-5`; `tests/acceptance/test_spec_022.py:3` | As docstrings de módulo ainda dizem que os arquivos cobrem o CA-13 (SPEC-023) e o CA-15 (faixa "CA-01 to CA-16", SPEC-022). Depois do §3.1, esses CAs são verificados pelo CI e pelo test-report, como diz o próprio comentário deixado no lugar. O tester agiu certo ao não mexer nelas, porque o §3.1 só autorizava tocar em imports e helpers. | Corrigir as duas docstrings na próxima SPEC que tocar esses arquivos, com autorização explícita na §3.1 dela. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os arquivos do §3.1 existem, e não há nada fora do escopo (sem rotas de leitura, sem `render.yaml`). Nenhum CA foi alterado. As duas tabelas de rastreabilidade (r1 e r2) cobrem os 28 CAs e os requisitos sem CA. As decisões do dev-report estão dentro do texto da SPEC (avaliação abaixo). Os commits do orquestrador que marcam a SPEC-003, a SPEC-023 e a SPEC-024 como `Done` (`2395762`) seguem a convenção "Done no primeiro commit da próxima branch". |
| 2. Regras inegociáveis | ✅ | **R-01:** nenhuma dependência nova (o `uv.lock` muda só a versão do `qc-api`). **R-02:** nenhuma rota aceita imagem. O OpenAPI só declara `application/json`, e multipart e binário dão 422. **R-03:** a busca no diff por URL com senha, `password=`, `eyJ`, `service_role` e `token = "..."` não achou nada. As URLs dos testes não têm senha, ou a senha é montada em tempo de execução (`urlunsplit`). O `.env.example` documenta `MAX_BODY_BYTES` e `LOG_LEVEL`. **R-04:** não há payload fora de `qc_contracts`: as rotas usam `InspectionCreate`, `BatchCreate`, `BatchResult`, `InspectionCreated` e `HealthResponse`. **R-05:** `ON CONFLICT (inspection_id) DO NOTHING RETURNING`, com CA-04, CA-12 e CA-15. **R-06:** `source` é gravado como veio, sem default. **R-07:** os 16 commits têm `Agent:`. Os commits `developer` só tocam produção, `api/tests/` (fora de `acceptance/`), `scripts/`, README, `.env.example` e o próprio relatório. Os commits `tester` (`d6d9e2b`, `e6b0fc8`, `7bc3372`, `e8f4b3b`) só tocam `*/tests/acceptance/` e os test-reports. Os commits `orchestrator` só tocam `docs/plan.md` e o status das SPECs. **R-11:** N/A. **R-12:** `api/pyproject.toml` sem torch, timm ou onnxruntime, e Python `>=3.12,<3.13`. **R-13:** os autores são `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits com `Refs: SPEC-004`. |
| 3. Corretude | ✅ | O SQL é todo parametrizado (`%s`). A escrita usa uma única transação (`with db_connection(...) as conn, conn.transaction()`), e o `DataError` desfaz tudo, inclusive o `last_seen_at`. O 403 é checado antes de qualquer escrita. Os handlers são `def` (threadpool), e os middlewares e o handler de validação, que são `async`, não fazem I/O bloqueante. Os 401, 403, 413, 422, 503 e 500 têm o corpo `{"detail": ...}` e nenhum traceback. As datas são normalizadas para UTC pelo contrato, e o CA-03 confere `15:00Z`. Não há `except Exception: pass`: o `except Exception` do `register_device.py:119` loga e sai com 2. O caso RV-01 é o único que deixei registrado. |
| 4. Testes | ✅ | Test-report PASS. Cada CA tem um teste de aceite que exercita o comportamento de verdade: banco real, `TestClient` com lifespan, `subprocess` para o script e uvicorn real para o 413 e para o T-01/T-02. O tester mostrou que os testes da r2 falham no código da r1 (33 de 35). Não há rede externa: a "app sem banco" usa a porta 1 local. Rodei a suíte com banco: **1277 passed** em 166 s, `qc_api` com 97% de cobertura (a RNF-09 cita `qc_api.services`, que ainda não existe). **Regras novas da §4:** nenhum teste roda a suíte inteira em subprocesso. Os únicos `pytest` em subprocesso são o `--collect-only` do CA-27/CA-28, com caminhos explícitos e sem fixture de banco, e o CA-09 da SPEC-024, que já existia e também usa caminhos explícitos. Também não há credencial fictícia como literal em URL ou conninfo: o `"p" + "w"` do aceite e o `"pw" + token_hex` do autor são montados em tempo de execução. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos (74 arquivos). Não há `print` em produção: o `sys.stdout.write` do script é a saída do CLI, como prevê o §7. As funções públicas têm type hints. Nenhuma lógica de `qc_contracts` foi duplicada: o script usa `DEVICE_ID_PATTERN` e as rotas usam os schemas do pacote. O README ganhou a seção "API local e registro de dispositivo", e o `infra/migrate.py` citado nela existe. |
| 6. Segurança | N/A aqui | A SPEC tem a tag `security`, mas o autor dela não é o `security-devops`, então o portão fica com ele (incluindo a O-01 do tester). Para registro, os itens de código da §6 que conferi estão ok: a autenticação vale nas duas rotas de escrita, com `compare_digest`; há limite de corpo e `extra="forbid"` (no contrato); o SQL é parametrizado; não há CORS; e os logs não têm chave, hash, URL nem corpo (CA-18, T-02). |

## Avaliação das decisões do dev-report r1 (itens 1 a 7)

1. **Chave ausente, vazia ou com mais de 256 caracteres → 401 sem consultar o banco.** Aceita. É a ordem literal do §4.3, e o §4.5 diz "503 (banco indisponível **ao autenticar**)". Quando a autenticação não precisa do banco, não há 503 a dar. O CA-16 ("qualquer chave") usa uma chave não vazia de 43 caracteres, que chega ao banco. O comportamento está documentado em `test_app_no_db.py::test_missing_key_without_database_is_401`.
2. **JSON malformado e inteiro gigante recusados antes da autenticação (400/422 sem chave).** Aceita. A precedência do §4.5 vale "para JSON bem formado", e o CA-26 aceita 400. É o comportamento do FastAPI, que decodifica o corpo antes de resolver as dependências. A resposta não revela nada além de "o corpo não é JSON", e nada é gravado (O-02 do tester).
3. **`BodyTooLargeError` como subclasse de `HTTPException`.** Aceita e correta. Conferi no código que o FastAPI relança `HTTPException` no parse do corpo, e o `ExceptionMiddleware` a converte em 413. O fallback do middleware cobre o caso em que a resposta ainda não começou. O CA-09 e o teste com uvicorn real (chunked de 311 296 bytes) confirmam.
4. **500 por middleware próprio, em vez de `add_exception_handler(Exception, ...)`.** Aceita. Evita o traceback duplicado. A ordem da pilha é `ServerError → RequestLog → UnhandledError → BodySizeLimit → ExceptionMiddleware → router`, e com ela o log por requisição vê o 413 e o 500.
5. **Routers com o prefixo `/api/v1`.** Aceita. O resultado é o mesmo do §4.2 (prefixo `/api/v1`), e o log registra o template da rota, nunca o caminho cru. Um caminho sem rota vai para o log como `repr` truncado em 200 caracteres, o que impede a injeção de linhas.
6. **Settings com `case_sensitive=True`, `extra="ignore"`, `DATABASE_URL` com `min_length=1` e `hide_input_in_errors=True`.** Aceita. Cumpre o §4.1 ("só do ambiente" e "erro nunca mostra valores"), e uma variável vazia vale como ausente, o que é o esperado. O CA-20 confere.
7. **`require_read_key` compara bytes UTF-8.** Aceita e necessária. Com `str` não ASCII, o `compare_digest` levanta `TypeError`, o que daria 500. Continua sendo comparação em tempo constante.

Os itens 8 a 10 também estão ok: a URL inválida no script não é ecoada, a versão do `pyproject.toml` acompanha o `__version__` e os testes não têm credenciais literais. Na r2, a correção do T-01/T-02 (`errors.py:68-82`) delega ao handler padrão e só usa o fallback sem `input`/`ctx` quando ele falha (`ValueError` ou `RecursionError`). Assim o §4.5 ("422 padrão") continua valendo à risca, e só o que antes era 500 muda. Testei de forma independente: chave com surrogate solto, `lot_id` com surrogate e `text/plain` não UTF-8 dão 422. O Pydantic recusa o surrogate já no parse, então ele nunca chega ao `loc` do fallback.

## Tarefas de manutenção do tester (§3.1)

- **Remoção dos meta-testes (CA-27, `d6d9e2b`).** O diff se limita ao que o §3.1 autoriza:
  - sai `test_ca15_ruff_and_full_suite_without_ci_and_db_url` de `tests/acceptance/test_spec_022.py`. Ficam `_clean_env`, `_run_pytest`, `re`, `sys` e `subprocess`, que ainda são usados;
  - sai `test_ca13_ruff_and_full_suite` de `packages/contracts/tests/acceptance/test_spec_023.py`, junto com o helper `_clean_env` e os imports `os`, `subprocess` e `sys`, que ficaram sem uso;
  - cada teste removido vira o comentário de uma linha da SPEC, com o texto exato (`CA-15` e `CA-13`).

  O CA-27 confere a contagem (main − 1), a ausência dos dois nomes, a igualdade entre os testes coletados e os definidos e o texto do comentário. Ficou só o RV-02.
- **Migração das expectativas de versão (CA-28, `e6b0fc8`).** Conferi arquivo por arquivo contra a tabela do §3.1:
  - **pisos:** `(0, 1, 0)` nos dois `test_spec_002.py` e `(0, 2, 0)` nos demais;
  - **asserções exatas:** só no CA-01 de `preprocess/test_spec_024.py` (`qc-preprocess` 0.3.0) e no de `contracts/test_spec_023.py` (`qc-contracts` 0.2.0), como manda o `architecture.md` §10;
  - **docstrings:** as dos dois `test_spec_002.py` não citam mais versão;
  - **CA-09 da SPEC-024:** saíram as asserções textuais de `"0.3.0"`/`"0.2.0"`, ficou a checagem dos nomes e entraram as regex do RV-02 da SPEC-024;
  - **o que mais mudou:** só `import re`, onde faltava.

  Nenhum outro CA desses arquivos mudou, e nenhum `pyproject.toml`, `__init__.py` ou `uv.lock` de pacote compartilhado foi tocado. Portanto, "o outro pacote não mudou", conferido no diff como pede o §10.
- **Interpretação do CA-28(b): aceita.** O CA-28(b) exige, "em cada um dos 5 arquivos", a coerência "para cada pacote cuja versão verificava antes", sem excluir o pacote que continua exato. A linha a mais (`<mod>.__version__ == importlib.metadata.version("<dist>")`) é o item 1 da forma do §10, que a última frase da §3.1 permite. Ela não afrouxa a asserção exata, que ficou intacta. Não é `SPEC_ISSUE`, porque a leitura literal do CA é a do tester. Sugestão de redação para futuras SPECs, sem efeito agora: dizer explicitamente que a coerência também entra no arquivo que mantém a versão exata.
- O CA-15 da SPEC-022 e o CA-13 da SPEC-023 ficam verificados pela execução da suíte. Ruff limpo e 1277 testes passando, na execução do tester e na minha.

## Pontos positivos

- A precedência 413 → 503 → 401 → 422 → 403 → 422 está documentada no código (`routers/inspections.py:3`) e testada em cada degrau, inclusive o 413 antes do banco e da autenticação, com uvicorn real.
- `DatabaseUnavailableError` com `from None` e o 422 do `DataError` com `from None`: nenhuma mensagem do servidor (host, valores) chega à resposta ou ao log.
- A correção da r2 é mínima e conservadora: delega ao padrão e só usa o fallback quando ele falha. O dev comparou campo a campo com uma app sem o handler (`test_encodable_errors_keep_the_default_422`).
- O tester foi além do T-01 e achou duas variantes que a r1 não listava (NaN/Infinity e surrogate solto, que também davam 500). Elas já ficam cobertas pela correção e por testes. Ele também mostrou que os testes novos falham no código antigo.
- O script de registro grava a chave só depois do commit, usa `ON CONFLICT DO NOTHING` (sem corrida no "já existe") e nunca ecoa a URL.
- A medição de duração do tester mostrou o ganho da remoção dos meta-testes: de 324 s para cerca de 90 s sem banco.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
