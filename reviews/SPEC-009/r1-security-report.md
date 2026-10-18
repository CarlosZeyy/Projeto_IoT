# SPEC-009 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-009](../../docs/specs/SPEC-009-edge-outbox-publisher.md) |
| Rodada | r1 (retomada após o SPEC_ISSUE-01) |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...98d5b85` (a `main` local está desatualizada) |
| Relatórios lidos | [r1-dev-report.md](r1-dev-report.md), [r1-test-report.md](r1-test-report.md) (PASS), [r1-review-report.md](r1-review-report.md) (APPROVED) |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. O RV-01 do review **não bloqueia** este portão (SEC-09-01 abaixo). Os outros achados são baixos ou informativos e podem ir para o backlog da manutenção da borda.

## Superfície analisada

A SPEC não cria rota nova na borda nem na API. O que muda é a saída da borda para a nuvem e um arquivo durável novo na borda.

| Superfície | Onde | O que conferi |
|---|---|---|
| Cliente HTTP da borda → API | `edge/src/qc_edge/publisher.py` | `X-API-Key` só no `POST /api/v1/inspections/batch`. O health check sai sem a chave. `follow_redirects=False`, então um 3xx não leva a chave a outro host. A verificação de TLS do `httpx` fica no padrão (`verify=True`), e não há `verify=False` em `edge/src`. É o único módulo do `qc_edge` que importa `httpx`. |
| Configuração | `edge/src/qc_edge/config.py` (`check_cloud_api_url`), `cli.py` (`_build_sink`) | Testei 20 URLs fora da suíte. `https://` é obrigatório. Recusadas: credencial, query, fragmento, espaço, caractere de controle e porta inválida. Os hosts parecidos com loopback (`127.0.0.1.evil.com`, `localhost.evil.com`, `127.1`, `0x7f000001`, `[::1]`) também são recusados com `http://`, e `http://evil.com\@127.0.0.1` cai como credencial. A `DEVICE_API_KEY` precisa ser ASCII visível. Os erros citam só o nome da variável (`hide_input_in_errors`). |
| Resposta da nuvem (entrada externa) | `publisher.py` (`_parse_results`, `refusal_summary`) | O 2xx é validado como `BatchResult`, com os mesmos ids na mesma ordem; senão vira erro transitório. 413/422 viram só o resumo do SEC-04-04. O corpo nunca chega a log, `last_error` ou exceção (`from None`). Conferi à mão: o `detail` em lista vira contagem, o `detail` em objeto vira `HTTP 422`, os caracteres de controle C0/C1 escapados no JSON viram `?`, e um JSON de 100 000 `[` cai em `HTTP 422` (`RecursionError` tratado). |
| Outbox SQLite | `edge/src/qc_edge/outbox.py` | Todo o SQL é parametrizado (`?`), sem f-string em query. O `payload` é só o `InspectionCreate` (R-02) e é revalidado pelo contrato antes do envio. As pastas novas recebem `0700` e o arquivo novo `0600`, pelo `fsutil` da SPEC-025. O caminho padrão, `edge/data/outbox.sqlite3` (e os arquivos `-wal`/`-shm`), está no `.gitignore` (`data/`, linha 25). |
| Logs | `publisher.py`, `publish_loop.py`, `cli.py` | `_redact` troca a chave por `***` em toda mensagem vinda do `httpx`. O 401/403 vira só `HTTP <status>`. A exceção inesperada vai para `last_error` só pelo nome da classe. Fora da suíte, com uma `ConnectError` cuja mensagem citava o header, o log não trouxe a chave, e o health check confirmou que nenhuma chave é enviada. |
| R-06 (`--stub-model`) | `cli.py:106-112` | `InMemorySink()` sem laço, antes de qualquer referência a `OUTBOX_PATH`. O CA-19 confere isso de ponta a ponta. |
| Console | `app.py`, `templates/console.html` | `connectivity_code` e o rótulo passam por `html.escape`, e nenhum dado vindo da nuvem é mostrado no console. |
| Dependências / deploy | `uv.lock`, `pyproject.toml` | Nenhuma mudança. Nenhuma configuração de deploy foi tocada. `.env.example` só ganhou comentários, sem variável nova nem valor. |
| Pré-requisito SEC-01 (SPEC-007) | `docs/specs/SPEC-025-manutencao-borda-host-rede.md` em `origin/main` | `Status: Done`. A dependência da §8 está cumprida. |

**Rodei:** `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` → **4427 passed, 1 skipped, 1 warning** em 266 s. É o mesmo resultado do test-report e do review: o skip é o CA-16 manual da SPEC-008, e o aviso é o `StarletteDeprecationWarning`, que já existia.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-09-01 (= RV-01) | baixa (higiene; **não bloqueia**) | secrets | `edge/tests/test_cli_cloud.py:245`; `edge/tests/acceptance/test_spec_009.py:1035`, `:1058-1059`; `reviews/SPEC-009/r1-review-report.md` (texto do RV-01) | Uma URL de teste leva usuário e senha fictícios como literal. **Não é segredo:** o valor nunca autenticou em nada, e é justamente a entrada que o código precisa recusar. Não exige rotação. O risco é só o alarme do scanner, que travaria a R-09. **Avaliação do GitGuardian:** o detector de URL com credencial (*Basic Auth String*) descarta senhas com menos de 4 caracteres e nomes de usuário genéricos ([docs](https://docs.gitguardian.com/secrets-detection/secrets-detection-engine/detectors/generics/basic_auth_string)). A senha aqui tem 2 caracteres, então o esperado é que ele **não** acuse. O caso da SPEC-022 era outro: `postgres:postgres@` tem senha de 8 caracteres. **Se acusar mesmo assim:** um commit novo **não** resolve, porque o GitGuardian analisa cada commit do PR, e não só o estado final ([docs](https://docs.gitguardian.com/secrets-detection/secrets-detection-in-sdlc/detect-secrets-in-real-time-in-github)). O literal está em três commits: `4008e78` (developer, já publicado em `origin/spec/SPEC-009-edge-outbox-publisher`), `8fde7a3` (tester) e `3eae517` (reviewer, no texto do relatório). Os dois últimos ainda são só locais. | **Antes do merge:** nada obrigatório. **Recomendado (conformidade com o `reviews/checklist.md` §4):** um commit novo basta. O developer troca o literal em `test_cli_cloud.py`, e o tester em `test_spec_009.py`, montando a senha em tempo de execução (ex.: `secrets.token_hex(4)`). **Não é preciso limpar o histórico da branch**, porque não houve vazamento. Reescrever invalidaria os hashes citados nos três relatórios e exigiria `--force-with-lease` na branch, sem ganho de segurança: o `4008e78` já está público e continuaria no GitHub. **Se o check do GitGuardian falhar:** o humano marca o incidente como falso positivo no painel do GitGuardian e roda o check de novo. Assim o check deixa de acusar sem reescrita (ver o link acima). Só se o humano preferir que nenhum commit carregue o literal: reescrever os três commits antes do push dos dois locais e registrar a reescrita na descrição do PR (lição do RV-04 da SPEC-022). |
| SEC-09-02 (= RV-02 / T-01) | baixa | input / disponibilidade | `edge/src/qc_edge/publisher.py:134`, `:150-165` | Confirmo o RV-02. `timeout=5.0` vale por operação, não por requisição, e `response.content` lê o corpo sem teto. Só um servidor hostil ou quebrado atrás de `CLOUD_API_URL` explora isso, e ele precisa de um certificado TLS válido para o nosso host. Nesse caso, ele prende a thread de publicação ou faz a borda alocar memória. A captura não é afetada: o lock do outbox não fica preso durante o HTTP, e cada `put` é confirmado. Nada se perde (R-05). | Backlog (SPEC de manutenção da borda): prazo total por requisição e teto de bytes (`client.stream` + `iter_bytes`, ex.: 15 s e 512 KiB). Estourar qualquer um dos dois vira `PublishTransientError`. |
| SEC-09-03 | informativa | deploy / config | `edge/src/qc_edge/publisher.py:134` | O `httpx.Client` usa `trust_env=True` (padrão). Por isso, `HTTPS_PROXY`/`ALL_PROXY` e `SSL_CERT_FILE`/`SSL_CERT_DIR` do ambiente do notebook valem para o envio. Com proxy, a chave atravessa um túnel `CONNECT`, e o TLS é ponta a ponta. Trocar o bundle de CAs exige controle do ambiente local, o que já seria um comprometimento da borda. Sem ação agora. | Nenhuma. Se uma SPEC futura quiser isolar a borda do ambiente, use `trust_env=False` e documente a variável de proxy explícita. |
| SEC-09-04 | informativa | integridade dos dados | `edge/src/qc_edge/publish_loop.py:218-228` | Esta é a observação do review: se a API recusar todos os itens com 422 (por exemplo, numa divergência de contrato com `extra="forbid"`), a bissecção faz até 199 requisições num ciclo, e os 100 itens viram `dead`. Nada se perde, porque as linhas ficam no arquivo, mas o reenvio de `dead` está fora do escopo (§3.2). A rajada vai para a nossa própria API e é limitada a um ciclo por lote. | Planejar a SPEC de reenvio de `dead` antes da primeira mudança de contrato com a borda já em operação (R-04). |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação aplicada em toda rota; comparação em tempo constante | ✅ / N/A. Nenhuma rota nova na borda. `/api/status` e o console continuam com o token de sessão e o `Host` loopback (SPEC-007/025). Do lado cliente, a chave só vai no `POST` do lote, nunca no health check nem em redirecionamento. A comparação da chave é da API (SPEC-004) e não mudou. |
| Entradas validadas (tamanho, tipo, regex, `extra="forbid"`) | ✅ (com o SEC-09-02, baixo). `CLOUD_API_URL` e `DEVICE_API_KEY` são validadas na subida. A resposta da nuvem é validada pelo contrato (`BatchResult`, ids e ordem). O `payload` do outbox é revalidado como `InspectionCreate` antes do envio, e o inválido vira `dead`. O tamanho do lote é de 1 a 100 (`MAX_BATCH_SIZE`). Imagem: N/A, nenhuma imagem entra nesse caminho. |
| SQL sempre parametrizado | ✅ Todas as queries de `outbox.py` usam `?`. O único `executescript` é o schema constante. |
| RLS; `DATABASE_URL`/`service_role` só na API | ✅ / N/A. A borda não fala com o Supabase, só com a API, via `X-API-Key`. O teste do autor contra a API real (`test_publisher_real_api.py`) usa `TEST_DATABASE_URL` do ambiente, é pulado sem ela e nunca usa o Supabase. |
| CORS | N/A (sem mudança) |
| Logs sem segredos e sem payload de imagem | ✅ Chave redigida, corpo da recusa nunca registrado, exceção inesperada só pelo nome da classe. Conferido pela suíte (CA-07, CA-18, CA-19) e fora dela. |
| Dependências novas | ✅ Nenhuma. O `uv.lock` e os `pyproject.toml` estão intactos, o `httpx` 0.28.1 já era dependência do `qc-edge` e o `sqlite3` é da biblioteca padrão. |
| Deploy (variáveis no provedor, health check, free sem cartão) | N/A. Nenhuma configuração de deploy foi tocada. As variáveis da borda (`DEVICE_API_KEY`, `CLOUD_API_URL`, `OUTBOX_PATH`) vivem no `.env` local do notebook e estão documentadas só por nome em `.env.example` (R-03). |
| Privacidade das imagens (R-02, R-14) | ✅ O corpo é sempre `BatchCreate` em JSON (`application/json`, nunca multipart), e o CA-10 confere as chaves exatas do §3.2. O outbox guarda só o JSON do contrato. |
| R-06 (`--stub-model`) | ✅ Garantida por construção (`InMemorySink`, `OUTBOX_PATH` intocado, nenhum laço), conferida no CA-19. |
| R-13 | ✅ Os 16 commits de `origin/main..HEAD` usam a identidade do projeto e levam o trailer `Agent:`. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. |

## Ações pendentes para o humano

1. Ao abrir o PR, confira o check **GitGuardian Security Checks**. Se acusar a URL de teste do SEC-09-01, marque o incidente como falso positivo no painel do GitGuardian (não é credencial real, então não precisa de rotação) e rode o check de novo.
2. Antes da primeira subida com chave e URL, apague um `outbox.sqlite3` local criado pelo build antigo da r1 com `--stub-model`, se houver (SPEC-009 §7).
3. Registre o CA-17 manual (demo offline), conforme a §8.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
