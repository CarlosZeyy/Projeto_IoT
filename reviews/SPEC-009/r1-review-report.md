# SPEC-009 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-009](../../docs/specs/SPEC-009-edge-outbox-publisher.md) |
| Rodada | r1 (retomada após o SPEC_ISSUE-01; SPEC com o CA-12 ajustado e o CA-19 novo, reaprovada pelo humano) |
| Reviewer | reviewer |
| Diff revisado | `origin/main...6c09180` (a `main` local está desatualizada) |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante nem alto. Os três achados abaixo (um médio e dois baixos) não bloqueiam e podem ir para o backlog ou para a próxima SPEC que mexer na borda. A SPEC tem a tag `security`, então o portão do security-devops (`r1-security-report.md`) continua obrigatório antes do merge (R-09). O autor da SPEC não é o `security-devops`, e por isso este relatório não substitui aquele.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `edge/tests/test_cli_cloud.py:245`, `edge/tests/acceptance/test_spec_009.py:1035` | Uma credencial fictícia aparece como literal em URL: `"https://user:pw@api.exemplo.org"`, no teste do autor e no teste de aceite. O `reviews/checklist.md` §4 proíbe isso porque o scanner de segredos do repositório público marca o padrão `usuário:senha@host` como vazamento. Há precedente: a SPEC-022 nasceu de um alerta por `postgres:postgres@`, e a SPEC-004 r2 montou o valor em tempo de execução (`"p" + "w"`). O literal já está num commit publicado (`4008e78`, no `origin/spec/SPEC-009-edge-outbox-publisher`). Se o scanner acusar o PR, o check fica vermelho e a R-09 bloqueia o merge. | O developer (em `test_cli_cloud.py`) e o tester (em `test_spec_009.py`) montam a URL em tempo de execução, por exemplo `"https://user:" + secrets.token_hex(4) + "@api.exemplo.org"`, o que também confere de verdade que o valor nunca aparece no log. Orquestrador: ao abrir o PR, confira o resultado do scanner. Se ele acusar, o achado passa a bloquear pela R-09. |
| RV-02 | baixa | `edge/src/qc_edge/publisher.py:134`, `:150`, `:162`, `:165` | Este é o **T-01** do tester, que confirmei no código. `httpx.Client(timeout=5.0)` aplica 5 s a cada operação (conexão, escrita, cada leitura e pool), não à requisição inteira. Um servidor que manda 1 byte a cada 3 s prende o `publish_batch` sem limite, e o `stop()` volta depois de 10 s com a thread viva. Ponto relacionado: `response.content` lê o corpo inteiro sem teto, então um servidor hostil também consegue fazer a borda alocar memória sem limite. **Por que a severidade é baixa:** (1) só acontece com um servidor quebrado ou hostil atrás de `CLOUD_API_URL`, que é `https://` para a nossa própria API, então o TLS autentica o host, e o Caddy/uvicorn não gotejam bytes; (2) a captura não é afetada, porque o lock do outbox não fica preso durante o HTTP, e cada `put` continua sendo confirmado; (3) a thread é daemon, o `stop()` devolve o controle ao lifespan em 10 s e o processo termina; (4) reiniciar o `qc-edge` resolve, e nada se perde, porque o item continua `pending` e a idempotência por `inspection_id` (R-05) absorve o reenvio. O que muda é a garantia "timeout de 5 s" do `docs/architecture.md` §6.2, passo 8: hoje ela vale por leitura, não por requisição. | Em uma SPEC de manutenção da borda (ou como pendência do security-devops), adicionar um prazo total por requisição: `client.stream(...)` com `iter_bytes()`, conferindo `time.monotonic()` contra um deadline (ex.: 15 s) e um teto de bytes (ex.: 512 KiB, acima dos 256 KB do eco do 422) entre os blocos. Estourar qualquer um dos dois vira `PublishTransientError`. Também vale registrar na §6.2 que o limite de 5 s é por operação. |
| RV-03 | baixa | `edge/src/qc_edge/publish_loop.py:197`, `edge/src/qc_edge/outbox.py:185`, `:231` | Os intervalos do laço usam o relógio de parede (`utc_now`): o `next_attempt_at` do backoff e o "60 s sem contato" do health check. Se o relógio do notebook voltar no tempo (correção do NTP depois de uma suspensão, ou ajuste manual), um item em retry que estava agendado para "agora + 60 s" passa a esperar o atraso **mais** o tamanho do salto, e o health check ocioso também não roda até o relógio alcançar o último contato (`now - last` negativo). Isso não perde dado e se corrige sozinho, mas pode atrasar o CA-17 ("em até 90 s") numa demo em que o relógio foi ajustado. | Usar `time.monotonic()` para o intervalo do health check. No `fetch_due`, tratar como vencido o item cujo `next_attempt_at` esteja mais de `MAX_DELAY_S` no futuro (isso só acontece depois de um salto para trás), ou reagendá-lo para `now`. O relógio injetável continua para `created_at` e para os testes. |

**Observação (não é achado; comportamento previsto pela SPEC):** se a API recusar **todos** os itens com 422 (por exemplo, uma divergência de versão do contrato com `extra="forbid"`), a bissecção faz 199 requisições num ciclo, e os 100 itens viram `dead`. As linhas continuam no arquivo, então nada se perde, mas elas só voltam a subir com o reenvio de `dead`, que a §3.2 deixa para uma SPEC futura. Sugiro que essa SPEC futura entre no plano antes da primeira mudança de contrato com a borda já em operação. Fica registrado também para o security-devops.

## Pontos pedidos pelo orquestrador

- **R-05 (idempotência):** ✅
  - o `put` faz `INSERT ... ON CONFLICT (inspection_id) DO NOTHING` com commit antes de retornar (`outbox.py:163-170`);
  - `mark_sent`, `mark_dead` e `mark_retry` só tocam linhas `pending`, então um item `sent` nunca volta;
  - `created` e `duplicate` contam igual (`publish_loop.py:229`);
  - a "resposta perdida" do CA-08 vira retry, depois `duplicate`, depois `sent`. Com isso a nuvem tem 200 gravações únicas, conferidas pela nuvem falsa e, contra a API real, por `test_publisher_real_api.py::test_batch_created_then_duplicate`;
  - se o `mark_sent` falhar depois de um envio bem-sucedido, o item recebe retry e o reenvio é absorvido como `duplicate`.
- **R-06 (`--stub-model`):** ✅ A implementação segue a §4.4 corrigida.
  - `_build_sink` (`cli.py:106-112`) devolve `InMemorySink()` e `[]` antes de qualquer referência a `OUTBOX_PATH`, então o arquivo não é aberto, criado nem validado;
  - o `WARNING` contém `--stub-model` e não cita valores.
  - O CA-19 (itens 1 a 6 e o caso da pasta inexistente) exercita isso de ponta a ponta. Ele confere:
    - um snapshot byte a byte das 2 linhas originais;
    - um servidor HTTP local real que não recebe nada;
    - um espião no construtor do `PublishLoop`;
    - a publicação posterior com só os 2 ids originais.
  - O `source` sai como foi gravado (`test_extra_source_is_published_as_stored_r06`).
- **R-03 (chave fora do log):** ✅
  - a chave só existe no `HttpPublisher`, e `_describe` troca qualquer ocorrência dela por `***` (`publisher.py:179-182`);
  - o 401/403 vira só `HTTP <status>`, a recusa vira só o resumo do SEC-04-04, e a exceção inesperada vai para `last_error` só pelo nome da classe;
  - o health check sai sem `X-API-Key`, e redirecionamentos não são seguidos, então a chave não vaza para outro host;
  - os testes conferem a ausência da chave em `caplog` no nível DEBUG, em `last_error` e no ponta a ponta com HTTP real;
  - a busca por `eyJ`, `postgres://…:…@`, `password=`, `secret=`, `sk_` e chaves privadas no diff não achou nada. As chaves dos testes vêm de `secrets`. A exceção é o RV-01, uma URL de teste e não uma chave.
- **R-07 (trailers):** ✅ Cruzei os 14 commits de `origin/main..HEAD`. Todos têm o trailer `Agent:` e a identidade `CarlosZeyy` (R-13).
  - `developer` (`afd34f2`, `10ac85d`, `4008e78`, `28b1f6a`, `6419e43`, `7fcee19`, `f14b5b1`): só produção, `edge/tests/` fora de `acceptance/`, README, `.env.example` e o dev-report;
  - `tester` (`8fde7a3`): só `edge/tests/acceptance/test_spec_009.py` e o test-report;
  - `architect` (`47c4223`): só a SPEC, a `architecture.md` §6.1/§6.2 e o `plan.md`;
  - `orchestrator`: só o status da SPEC e o `plan.md`, mais o `Done` da SPEC-008 no primeiro commit da branch.
  - Ninguém cruzou a fronteira.
- **T-01:** avaliado no RV-02. Concordo com a severidade **baixa** e acrescento o corpo sem teto, que tem o mesmo modelo de ameaça.
- **`DEVICE_API_KEY` validada sempre que definida, também no modo stub:** **concordo; não é achado.**
  - A §4.4 manda que "a validação de `CLOUD_API_URL` e `DEVICE_API_KEY` na subida (CA-11) é a mesma com ou sem a flag", e a implementação cumpre isso literalmente: `cli.py:98-104` roda antes da escolha do sink.
  - O formato exigido (ASCII visível, de `0x21` a `0x7E`) não está na SPEC. Mesmo assim, é uma validação defensiva e está registrada nas decisões do dev-report.
  - Essa regra recusa só valores que nunca autenticariam. Ela também evita o `UnicodeEncodeError` do `httpx`, que cairia no caminho "exceção inesperada" a cada ciclo e cuja mensagem cita o caractere da chave.
  - As chaves do `register_device.py` (`token_urlsafe`) passam.
  - O efeito colateral (uma chave com espaço no `.env` impede até a subida com `--stub-model`) é o comportamento que a §4.4 pede, e a mensagem cita só o nome da variável.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Todos os requisitos das §4.1 a §4.4 estão implementados: schema e índice idênticos à §4.1, assinaturas da §4.1/§4.2/§4.3 e a tabela da §4.4 em `_build_sink`. Nada fora do escopo: o reenvio de `dead` e a limpeza de `sent` ficaram de fora, como a §3.2/§7 pede. Nenhum CA foi alterado pelo autor. As mudanças no CA-12 e o CA-19 vêm do architect, com reaprovação humana no Histórico. A rastreabilidade CA → arquivo → teste está no dev-report. As decisões fora da SPEC (campos do `OutboxItem`, desempate por `rowid`, validações extras de URL e chave, outbox não fechado no lifespan, 3xx transitório) estão registradas e não contradizem a SPEC. O SPEC_ISSUE-01 foi resolvido pela opção (d) e conferido no código. |
| 2. Regras inegociáveis | ✅ | R-01: sem dependência nova (`httpx` já era do `qc-edge`, `sqlite3` é da biblioteca padrão; `uv.lock` intacto). R-02: o corpo é sempre `BatchCreate` JSON, e o CA-10 confere as chaves exatas do §3.2 e as duas rotas. R-03, R-05, R-06 e R-07: ver acima. R-04: `packages/contracts` não foi tocado. R-11: N/A. R-12: nada muda em `api/` ou `dashboard/`. R-13: commits Conventional com `Refs: SPEC-009` e a identidade do projeto. |
| 3. Corretude | ✅ (com RV-02 e RV-03, baixos) | O SQL é todo parametrizado. O SQLite usa uma conexão com `threading.Lock`, que não fica preso durante o HTTP. O `put` roda no worker thread da captura (`anyio.to_thread`), e `/api/status` e o console são `def` (threadpool), então não há I/O bloqueante no event loop. O único bloqueio é o `stop()` no fim do lifespan (≤ 10 s, no desligamento). As datas são UTC de largura fixa, e um relógio *naive* é recusado. As bordas estão tratadas: lote de 1 a 100, resposta 2xx que não bate com o lote, 3xx, corpo não JSON, `detail` de tipos variados, caracteres de controle (Cc, inclusive C1), falha transitória e 401 no meio da bissecção, e exceção inesperada no health check e no `mark_*`. Não há `except: pass`: os dois `except Exception` registram com stack trace. |
| 4. Testes | ✅ (com RV-01, médio) | O test-report é PASS e cobre do CA-01 ao CA-19. O CA-17 é manual, com roteiro no README. Os testes não são tautológicos: o SQLite é real, o `SIGKILL` é real no CA-09, há um servidor HTTP local real no CA-12/CA-19 e no ponta a ponta, um espião no construtor do laço e um teste do autor contra a API real no banco (422 `Value cannot be stored` isolado pela bissecção). Só as fronteiras da §6 são substituídas. Sem rede externa. O CA-16 roda o pytest em subprocesso com 2 arquivos explícitos e `-k "not test_ca16"`, sem banco. Cobertura de `qc_edge.outbox`: 97% (autor) e 99% (com o aceite), acima dos 80% da RNF-09. Não houve ajuste em teste de aceite de SPEC anterior: o diff só toca `test_spec_009.py` em `acceptance/`, e o test-report diz "Nenhum". **Rodei:** `CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q` → **4427 passed, 1 skipped, 1 warning** em 265 s. O skip é o CA-16 manual da SPEC-008, e o aviso é o `StarletteDeprecationWarning`, que já existia. O resultado é idêntico ao do test-report. |
| 5. Qualidade | ✅ | **Rodei:** `uv run ruff check .` e `uv run ruff format --check .` limpos (166 arquivos). Os nomes são claros, as funções são curtas, há type hints nas funções públicas e nenhum `print`. Não há duplicação de `qc_contracts`: `BatchCreate`, `BatchResult`, `InspectionCreate` e `MAX_BATCH_SIZE` vêm do pacote. O `edge/README.md` ganhou a seção "Envio para a nuvem", com a tabela da §4.4, o roteiro do CA-17 e a nota sobre outboxes da r1. `.env.example` atualizado, sem variável nova. Detalhe sem severidade: `test_publisher_real_api.py:52` usa o atributo privado `TestClient._transport`. |
| 6. Segurança | N/A (portão do security-devops) | A SPEC tem a tag `security`, mas o autor é o `developer`, então o `r1-security-report.md` é do security-devops. Para ele: RV-02 (T-01 e o corpo sem teto), a observação da recusa geral e o RV-01 (scanner). |

## Pontos positivos

- A correção do SPEC_ISSUE-01 garante a R-06 por construção: o stub nunca encosta num arquivo durável. O CA-19 prova isso com um snapshot byte a byte e um servidor real que não recebe nada.
- A bissecção para no primeiro erro transitório e aplica o retry a tudo o que ainda não foi resolvido. Assim, a borda não acumula timeouts de 5 s com a nuvem fora, e um 401 no meio da bissecção deixa os itens restantes como estavam.
- O resumo da recusa (SEC-04-04) é aplicado de forma estrita: o corpo do 422 nunca chega a `str`, `repr`, `args`, `__cause__` ou `__context__` da exceção (`from None`).
- `CLOUD_API_URL` recusa credencial, query, fragmento e hosts parecidos com loopback (`localhost.exemplo.org`, `127.0.0.2`). Além disso, `follow_redirects=False` impede que a chave vá para outro host.
- O teste do autor contra a API real no banco confere o contrato de verdade (`created`/`duplicate`, 401 e 422), não só a imitação da nuvem falsa.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
