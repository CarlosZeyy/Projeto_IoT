# SPEC-030 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-030](../../docs/specs/SPEC-030-manutencao-borda-publisher-privacidade.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...c63c057` (12 commits, de `84045fc` a `c63c057`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Há 4 achados baixos e nenhum `SPEC_ISSUE`. Três deles confirmam os RV-01 a RV-03 do reviewer, e o SEC-30-03 é novo. Todos têm a mesma natureza: o código cumpre a SPEC, e o que sobra é um resíduo que a SPEC não cobriu ou que vem da SPEC-025. Nenhum precisa de correção de código antes do próximo backup do dataset nem antes da operação real. Para o backup, recomendo uma conferência operacional (ver "Pontos pedidos pelo orquestrador", item 2).

## Superfície analisada

- **Saída da borda para a nuvem (R-02, R-03, R-05):** `edge/src/qc_edge/publisher.py` (`publish_batch` com `client.stream`, `_read_body` com prazo e teto, `check_health` sem leitura do corpo), `edge/src/qc_edge/publish_loop.py` (health check depois de um salto do relógio) e `edge/src/qc_edge/outbox.py` (`fetch_due` com `max_delay_s`, SQL parametrizado).
- **Varredura de privacidade do dataset (R-14):** `edge/src/qc_edge/privacy.py` (`printable_path`, `is_jpeg_name`, `is_edge_temporary`, `_files`, `scan`, logs de `cannot read` e `cannot fix`).
- **Testes:** credencial em URL montada em tempo de execução (`test_cli_cloud.py`, `test_spec_009.py`), o `TestClientTransport` do `test_publisher_real_api.py`, o banco próprio do CA-07 (`<base>_acc030`, com `sql.Identifier` e a guarda `"test" in name`) e os subprocessos com o ambiente limpo.
- **Fora do diff (conferido):** nada mudou em rotas, autenticação da API, RLS, CORS, `infra/`, `.github/`, `pyproject.toml`, `uv.lock` ou `.env.example`. O `infra/Caddyfile` não tem `encode`, e a API não usa `GZipMiddleware`, então a API legítima responde sem compressão. Isso é relevante para o SEC-30-01.

Verificações próprias, com scripts no scratchpad da sessão, fora do repositório e só com `tmp`/scratchpad, nunca `ml/data/`:

1. corpo com compressão contra o teto, pelo `HttpPublisher` real com `httpx.MockTransport` e `tracemalloc`;
2. servidor local em `127.0.0.1` que entrega os headers da resposta byte a byte, contra o prazo;
3. subpastas de `raw/` sem permissão, contra a varredura.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-30-01 | baixa | input | `edge/src/qc_edge/publisher.py:161`, `:179`, `:210` | **RV-01 / O-01, severidade final baixa, com um agravante que os relatórios não mediram.** O teto conta os bytes **decodificados** (`iter_bytes`, como a §4.1 manda), e o `httpx` descomprime cada bloco bruto inteiro antes da primeira conferência. Reproduzi o pico de ~141 MiB do tester com `Content-Encoding: gzip`: 127 KiB de gzip viram 128 MiB e são recusados no 1º bloco. **Agravante:** o `httpx` aplica as codificações empilhadas que a resposta declarar. Com `Content-Encoding: gzip, gzip`, **378 bytes** viraram 128 MiB num único bloco (pico de 270 MiB, `response too large` no 1º bloco). A taxa é de ~350 000:1, contra ~1 000:1 do gzip simples. Por extrapolação, um bloco bruto de 64 KiB nesse formato chega a dezenas de GiB, o que mata o processo `qc-edge` por falta de memória. Por isso o pico **não** fica limitado a "um bloco vezes ~1000". **A sugestão do reviewer, sozinha, não fecha o problema:** com `Accept-Encoding: identity` no cliente, o mesmo corpo `gzip, gzip` deu o mesmo pico de 270 MiB, porque o `httpx` decodifica pelo header da **resposta**, e um servidor hostil o ignora. No ambiente travado só há os decodificadores `gzip`, `deflate` e `identity`: `brotli`, `brotlicffi` e `zstandard` não estão no `uv.lock` (`httpx` 0.28.1). **Por que é baixa:** quem consegue responder no `CLOUD_API_URL` precisa ser a própria API, comprometida, ou um host com certificado válido para o qual o operador apontou a URL por engano (só `https://` ou loopback, `follow_redirects=False`). Esse ator já recebe o `X-API-Key` e as inspeções, e pode responder `created` para todo item, o que faria a borda marcá-los como `sent` e perder os dados. Derrubar o processo não acrescenta capacidade relevante a ele. O impacto é só de disponibilidade: o outbox SQLite é durável (R-05), e nada sai da LAN (R-02). O risco também não é regressão: antes desta SPEC, o `response.content` lia o corpo inteiro, já descomprimido e sem teto nenhum. | **Nenhuma nesta SPEC.** Para a próxima SPEC da borda (registrar em `docs/plan.md` §3): (a) antes de ler o corpo, recusar com `PublishTransientError` (mensagem fixa) toda resposta com `Content-Encoding` que não seja ausente ou `identity`, e mandar `Accept-Encoding: identity` em `publish_batch` e `check_health`. Isso não quebra nada, porque nem o Caddy nem a API comprimem. Ou então (b) contar o teto pelo `iter_raw` e descomprimir com `zlib.decompressobj().decompress(data, max_length)`. Um teste deve cobrir `gzip` e `gzip, gzip`. Se `brotli` ou `zstandard` entrarem um dia no `uv.lock`, o caminho (a) continua valendo, e o (b) teria de tratar cada um. |
| SEC-30-02 | baixa | privacy | `edge/src/qc_edge/privacy.py:130` e `:135-138` | **RV-02 / O-03, severidade final baixa.** Há dois caminhos silenciosos, e não só um. (1) Uma subpasta de `raw/` que o `os.walk` não lista (modo `0o000`) é pulada, porque o `os.walk` não tem `onerror`. (2) Uma subpasta listável mas sem permissão de travessia (modo `0o600`, `r` sem `x`) entrega os nomes, mas o `os.lstat` falha, e o `except OSError: continue` descarta o arquivo, também sem linha nem log. Reproduzi os dois juntos, com um arquivo que daria `invalid` em cada pasta: a saída foi `checked 0 images, 0 with private data`, com código `0`. O comportamento vem da SPEC-025, e a §4.5 desta SPEC fala só de **arquivo** ilegível. **Por que é baixa:** a borda cria as pastas com `0700` e os arquivos com `0600`, sempre do mesmo usuário (SPEC-010), então o caso exige uma permissão anômala criada à mão. Além disso, a compactação do passo 4 do `docs/dataset-protocol.md` §8, feita pelo mesmo usuário, também não lê essas pastas, e o `tar` ou o `zip` reportam o erro. Assim, a foto não vai para o Drive por esse caminho. O resíduo realista é uma sequência humana: a compactação acusa "Permission denied", o operador corrige a permissão (`chmod`) e compacta de novo **sem** repetir a varredura. Também vale a compactação feita como outro usuário ou com `sudo`. | **Nenhuma de código nesta SPEC.** Para a próxima SPEC da borda: `os.walk(..., onerror=...)` e a falha do `lstat` passam a listar `<pasta ou arquivo>: unreadable` (com `printable_path`) e deixam o código em `1`, como o arquivo ilegível da §4.5. Conferência operacional até lá: ver "Pontos pedidos pelo orquestrador", item 2. |
| SEC-30-03 | baixa | input | `edge/src/qc_edge/publisher.py:179-198`, `:221-228` | **Novo.** O prazo total só é conferido depois de cada bloco do **corpo**. Ele não cobre a fase dos headers, nem os status cujo corpo não é lido (401, 403, 3xx, 5xx), nem o `check_health`. Um servidor que entrega os headers um byte de cada vez, com intervalo menor que o timeout de leitura de 5 s, prende a requisição até o limite de headers do `httpcore` (`MAX_INCOMPLETE_EVENT_SIZE = 100 KiB`). São ~100 000 leituras de até 5 s, ou seja, dias. Reproduzi em escala menor contra um servidor local em `127.0.0.1`, com `timeout_s=2` e `deadline_s=3`: 8 bytes de header, um por segundo, deram `HTTP 503` depois de **8,0 s**, sem `request deadline exceeded`. Com status 200, a exceção só saiu quando chegou o primeiro bloco do corpo, também aos 8,0 s. Portanto, a frase do objetivo da SPEC ("nunca passa de 15 s, mais uma leitura") e a nota da §7 ("pior caso de cerca de 15 + 5 s") valem só para a fase do corpo. Não é bug contra os CAs: a §4.1 define a conferência "depois de cada bloco recebido". **Por que é baixa:** o ator é o mesmo do SEC-30-01, e o efeito é a thread de envio parada. A captura continua, e as inspeções ficam `pending` no outbox até um reinício (R-05). Não há vazamento. | **Nenhuma nesta SPEC.** Para a próxima SPEC da borda: um prazo total que valha também para a fase dos headers e para o `check_health`. Uma opção é um `threading.Timer` com o `deadline_s` que fecha a resposta ou o cliente e converte o erro em `request deadline exceeded`. Um teste deve usar um servidor local que entrega os headers devagar, e a frase do objetivo deve ser ajustada se a solução for outra. |
| SEC-30-04 | baixa | privacy | `edge/src/qc_edge/privacy.py:118-120`, `:132` | **RV-03 / O-02, concordo com a baixa.** Qualquer nome `.*.tmp` em qualquer pasta de `raw/` é ignorado, não só o padrão do `mkstemp` da borda. Um arquivo copiado à mão com esse formato de nome iria no `.zip` do passo 4 sem ser conferido. Isso é exatamente o texto da §4.4, aprovado pelo humano, decisão (c). O `find ml/data/raw -type f ! -name '*.jpg'` do §8 ainda lista esse arquivo. | **Nenhuma nesta SPEC.** Se o humano quiser fechar: restringir ao padrão do `mkstemp` numa SPEC futura, como sugere o RV-03. Até lá, manter o `find` do §8 (item 2 abaixo). |

## Pontos pedidos pelo orquestrador

### 1. Severidade final do RV-01 e do RV-02

| Item | Severidade final | Bloqueia o merge? | Correção antes do próximo backup do dataset? | Correção antes da operação real? |
|---|---|---|---|---|
| RV-01 → SEC-30-01 | **baixa** | não | não: não tem relação com o dataset (é o publisher) | não. O atacante precisa controlar a resposta da API no HTTPS, e quem tem esse poder já faz algo pior (recebe a chave e descarta itens com `created`). Fica para a próxima SPEC da borda, com a correção (a) ou (b) do achado, e não com o `Accept-Encoding: identity` sozinho. |
| RV-02 → SEC-30-02 | **baixa** | não | **código: não. Operação: sim, uma conferência de 1 linha** (item 2) | não. A operação real (inspeção, `captures/`) não usa a varredura. |

### 2. Conferência operacional antes de cada backup, até a correção do SEC-30-02

No passo 1 do `docs/dataset-protocol.md` §8, além da varredura com código `0`:

```bash
find ml/data/raw \( ! -readable -o -type d ! -executable \) -print   # não pode listar nada
```

Outra forma de cumprir o mesmo objetivo: se a compactação do passo 4 acusar qualquer "Permission denied", ou se alguma permissão for corrigida, volte ao passo 1 antes de subir o arquivo. **Atenção ao RV-04 do reviewer:** quando o trecho "Até o merge da SPEC-030" for reescrito, ele não deve sair sem deixar no lugar essa conferência e o `find ... ! -name '*.jpg'`. O `find` continua sendo o único aviso para o SEC-30-04 e passa a ser também o aviso para o SEC-30-02. A mudança no `dataset-protocol.md` é de documentação, e quem a faz é o architect, ou o orquestrador no commit de `Done`, se o ADR-019 permitir. Eu não edito.

### 3. O resto do diff

- **§4.2 (salto do relógio):** o SQL continua parametrizado, com `now_text`, `horizon` e `limit` como parâmetros e só texto fixo na query. O backoff nunca agenda mais de 60 s à frente (`min(60, ...)`), e nenhum outro caminho escreve `next_attempt_at` no futuro. Por isso, o ramo `next_attempt_at > now + max_delay_s` só pega linhas depois de um salto e nunca reativa `sent` nem `dead` (o `status = 'pending'` continua no `WHERE`). Um `max_delay_s` hostil não é entrada externa, e o tester viu o `TypeError` antes do SQL. O pior caso é um health check a mais por ciclo depois de um salto, sem chave e sem corpo.
- **§4.1 (fora o SEC-30-01 e o SEC-30-03):** `DEADLINE_EXCEEDED` e `RESPONSE_TOO_LARGE` são constantes, levantadas fora do `except httpx.HTTPError`. Elas não têm `__cause__` nem `__context__` com a URL ou a chave. A resposta é fechada antes de levantar. Um 413 ou 422 acima do teto vira retry, nunca `dead`, e nada se perde (R-05). Um `DecodingError` de gzip malformado é `httpx.HTTPError`, e por isso transitório e com a chave mascarada pelo `_describe`. O `check_health` por `stream` não lê o corpo e não manda a chave.
- **§4.4 e §4.5:** o arquivo que não é JPEG é marcado `invalid` sem `open` (conferido por leitura: o ramo `else` não chama `_read`). Os JPEGs continuam abertos com `O_NOFOLLOW`. `printable_path` cobre `Cc`, `Cf`, `Cs`, `Zl` e `Zp` e escapa o `\`, de modo que não há ambiguidade entre nomes. Ele é aplicado no stdout e nos dois logs (`cannot read`, `cannot fix`). O `strerror` do log vem do sistema, não do nome. A ordenação segue o caminho original. Nada abre conexão (R-02).
- **§4.3 e testes:** não há credencial literal em URL em `edge/` (CA-06, e a minha busca no diff). O `TestClientTransport` usa só a API pública do `TestClient`. O banco do CA-07 é criado e apagado com `sql.Identifier` e só quando o nome contém `test`. Os subprocessos tiram `TEST_DATABASE_URL` e `PYTEST_*` do ambiente.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A. Nenhuma rota mudou. O `X-API-Key` continua só no `publish_batch`, e o `check_health` não o manda. |
| Entradas validadas | ✅ com resíduos baixos. A resposta da nuvem tem prazo e teto conforme a §4.1, e os nomes de arquivo de `raw/` saem escapados. O `deadline_s` e o `max_response_bytes` não positivos dão `ValueError`. Resíduos: SEC-30-01 (compressão) e SEC-30-03 (fase dos headers). Imagem, IDs e `extra="forbid"`: N/A (nenhum payload mudou). |
| SQL parametrizado | ✅ `fetch_due` (`outbox.py:192-198`) só com placeholders `?`. Os `drop`/`create database` do teste usam `psycopg.sql.Identifier`. |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A. A única conninfo no diff é a de teste local, sem senha, nos relatórios. |
| CORS | N/A. |
| Logs sem segredos e sem imagem | ✅ As mensagens novas são constantes. Os logs da varredura citam só o caminho relativo escapado e o `strerror`. Nenhum conteúdo de segmento (GPS, aparelho) nem corpo de resposta vai para log. |
| Dependências novas | ✅ Nenhuma (`pyproject.toml` e `uv.lock` sem mudança). `unicodedata` e `time` são da biblioteca padrão. |
| Deploy | N/A. Nada em `infra/` nem em `.github/`. |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma nesta branch. Os commits do orquestrador na SPEC-030 mudam só `Status` e `Rodada` (`git diff origin/main...HEAD -- docs/specs`), e o da SPEC-029 é a marcação de `Done`. |
| R-02 | ✅ O corpo continua sendo só o `BatchCreate` JSON, e a varredura não abre conexão. |
| R-03 (busca de padrões de chave no diff) | ✅ Nenhum literal com cara de chave, token ou senha. Senhas e chaves fictícias saem de `secrets.token_*` em tempo de execução, e as URLs com credencial são concatenações que a regex do CA-06 não pega. |
| R-05 | ✅ O prazo e o teto viram retry (CA-03, 3 `sent` com 3 ids únicos). |
| R-07 / R-13 | ✅ 12 commits com a identidade do projeto, `Refs: SPEC-030` e `Agent:`. Os do `developer` tocam só `edge/src`, `edge/tests` fora de `acceptance/`, `edge/README.md` e o dev-report. O do `tester` toca só `edge/tests/acceptance/` e o test-report. Nenhum commit é `security-devops`. |
| R-14 | ✅ com resíduos baixos. A varredura confere `.jpg`/`.jpeg` em qualquer caixa e acusa todo o resto, e um nome não forja o resumo. Resíduos: SEC-30-02 (pasta ilegível, anterior à SPEC) e SEC-30-04 (exceção `.*.tmp`, como a SPEC define). |

Suíte e qualidade, rodadas por mim (sem o extra `train`):

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5707 passed, 52 skipped, 1 warning in 758.54s (0:12:38)   # os 52 são os testes `docker` (PARTQC_DOCKER_TESTS=1)
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
224 files already formatted
```

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. `unicodedata` e `time` são da biblioteca padrão do Python 3.12. O `httpx` continua em 0.28.1. |

## Ações para depois do merge (não bloqueiam)

- Orquestrador: registrar em `docs/plan.md` §3, na "Próxima SPEC da borda": SEC-30-01 (recusar `Content-Encoding` diferente de `identity`, ou teto pelo `iter_raw`; o `Accept-Encoding: identity` sozinho não basta), SEC-30-02 (`onerror` e falha do `lstat` como `unreadable`), SEC-30-03 (prazo também na fase dos headers e no `check_health`) e, se o humano quiser, SEC-30-04.
- Architect ou orquestrador (ADR-019), junto do RV-04: no `docs/dataset-protocol.md` §8, passo 1, trocar o trecho "Até o merge da SPEC-030" por um texto que mantenha o código de saída da varredura, o `find ... ! -name '*.jpg'` e a conferência de permissões do item 2 acima.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Escrevi só este relatório. Os scripts de verificação ficaram no scratchpad da sessão, fora do repositório, e usaram só pastas temporárias, nunca `ml/data/`.
- [x] Não sou autor de nenhum commit desta SPEC (nenhum commit com `Agent: security-devops` no diff).
- [x] Nenhum valor que pareça segredo aparece neste relatório.
