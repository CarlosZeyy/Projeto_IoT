# SPEC-030: Manutenção da borda (prazo e teto do publisher, salto do relógio, varredura de privacidade e testes)

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-009, SPEC-025 (e SPEC-007, SPEC-010) |
| Semana alvo | S3 (a parte de privacidade, §4.4 e §4.5, antes do próximo backup do dataset no Drive, se possível) |
| Requisitos cobertos | RF-06, RF-07, RF-08, RNF-04, RNF-05, RNF-06, RNF-10; R-02, R-03, R-05, R-14 |
| ADRs relevantes | ADR-002, ADR-004, ADR-009 |

## 1. Contexto

Fecha as pendências não bloqueantes da borda que ficaram sem SPEC: as dos portões da SPEC-009 (outbox e publisher, `docs/architecture.md` §6.2, passo 8) e as da SPEC-025 (varredura `python -m qc_edge.privacy`, §6.3), mais duas de testes. Muda o comportamento descrito em `docs/architecture.md` §6.2 (passo 8) e §6.3, já anotado lá com "a partir da SPEC-030".

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| RV-02 = SEC-09-02 (T-01) | `reviews/SPEC-009/r1-review-report.md`, `r1-security-report.md` | baixa | Prazo total por requisição e teto de bytes na resposta do publisher (§4.1) |
| RV-03 | `reviews/SPEC-009/r1-review-report.md` | baixa | Backoff e health check resistentes a um salto do relógio para trás (§4.2) |
| RV-01 = SEC-09-01 | mesmos relatórios | média / baixa (higiene) | URL de teste com credencial fictícia literal (§4.3) |
| 3 testes de `edge/tests/test_publisher_real_api.py` falham com o extra `train` | `reviews/SPEC-011/r1-dev-report.md` (observação 1), `reviews/SPEC-012/r1-review-report.md` (observações) | sem severidade (fora do CI) | O teste do autor deixa de depender do transporte privado do `TestClient` (§4.3) |
| SEC-25-02 = RV-02 (r1/r2) da SPEC-025 | `reviews/SPEC-025/r2-security-report.md`, `r1-review-report.md`, `r2-review-report.md` | baixa | `.JPG`/`.jpeg` varridos; outros arquivos de `raw/` acusados (§4.4) |
| RV-02 da SPEC-011 | `reviews/SPEC-011/r1-review-report.md`; SPEC-011 §7 | baixa | `.jpeg`, `.png` e `.heic` sob `raw/` passam a ser acusados pela varredura de privacidade (§4.4) |
| SEC-25-01 = RV-03 (r1/r2) da SPEC-025 | `reviews/SPEC-025/r2-security-report.md`, `r1-review-report.md` | baixa | Caminho impresso com escape dos caracteres de controle (§4.5) |
| RV-04 (r1/r2) da SPEC-025 | `reviews/SPEC-025/r1-review-report.md`, `r2-review-report.md` | baixa | Arquivo ilegível aparece no stdout (§4.5) |
| RV-08 da SPEC-025 | `reviews/SPEC-025/r3-review-report.md` | baixa | `_collected` do teste de aceite tira `PYTEST_ADDOPTS` e afins do ambiente (§4.6) |

Os RV-05, RV-06 e RV-07 da SPEC-025 (`reviews/SPEC-025/r1-review-report.md` e `r2-review-report.md`) eram só de texto e foram resolvidos pelo architect direto na SPEC-025 (Histórico de 2026-10-19), sem mudança de comportamento.

## 2. Objetivo

Uma requisição do publisher nunca passa de 15 s (mais uma leitura) nem lê mais de 512 KiB de resposta; um salto do relógio para trás não prende o retry nem o health check; a varredura de privacidade confere toda foto de `raw/` qualquer que seja a caixa da extensão, acusa o que não é JPEG e imprime os caminhos sem controlar o terminal; e nenhum arquivo de teste da borda tem credencial literal em URL.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/publisher.py`: `HttpPublisher` com prazo e teto (§4.1).
- `edge/src/qc_edge/outbox.py`: `fetch_due` com o caso do salto do relógio (§4.2).
- `edge/src/qc_edge/publish_loop.py`: health check com o caso do salto do relógio (§4.2).
- `edge/src/qc_edge/privacy.py`: §4.4 e §4.5.
- `edge/README.md` (seção "Modo coleta", item 3 da §4.12 da SPEC-025, e "Envio para a nuvem"): §4.4 e §4.1.
- Testes do autor em `edge/tests/` (fora de `acceptance/`), inclusive `edge/tests/test_cli_cloud.py` e `edge/tests/test_publisher_real_api.py` (§4.3).
- **Tester desta SPEC:**
  - `edge/tests/acceptance/test_spec_030.py` (testes novos);
  - os ajustes de manutenção listados na §4.6, e nada além deles, em `edge/tests/acceptance/test_spec_009.py` e `edge/tests/acceptance/test_spec_025.py`. É aplicação explícita da regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10.

### 3.2 Fora

- Reenvio de itens `dead` do outbox → SPEC-034.
- `trust_env` do `httpx.Client` (SEC-09-03): sem ação, como o relatório decidiu.
- Logger do Pillow em `INFO` (SEC-25-04), APPn de fabricante como achado (SEC-25-05) e `raw/` como link simbólico (SEC-25-07): informativos sem correção exigida; ficam fora até o humano pedir.
- Regra de `orphan_image` do `qc_ml.data` para `.jpeg`/`.png`/`.heic` (SPEC-011): não muda. A varredura de privacidade antes do backup é a CLI desta SPEC (SPEC-025 §7, "`jpeg_private_findings` × SPEC-011").
- Baixar `CAPTURE_MAX_BYTES`: decisão futura que depende do passo 6 do CA-20 da SPEC-007 (`docs/plan.md` §3).
- Fotos de inspeção (`captures/`): não mudam.

## 4. Requisitos detalhados

### 4.1 Publisher: prazo total e teto de bytes (RV-02/SEC-09-02)

Hoje o `httpx.Client(timeout=5.0)` aplica 5 s a cada operação (conexão, escrita, cada leitura), e não à requisição inteira, e `response.content` lê o corpo sem teto.

```python
REQUEST_DEADLINE_S = 15.0
MAX_RESPONSE_BYTES = 512 * 1024        # acima dos 256 KB que a API ecoa num 422
class HttpPublisher:
    def __init__(self, base_url: str, api_key: str, timeout_s: float = 5.0,
                 transport: httpx.BaseTransport | None = None, *,
                 deadline_s: float = REQUEST_DEADLINE_S,
                 max_response_bytes: int = MAX_RESPONSE_BYTES,
                 monotonic: Callable[[], float] = time.monotonic) -> None
```

- `deadline_s > 0` e `max_response_bytes > 0`; senão `ValueError` (como o `timeout_s`).
- `publish_batch` usa `client.stream("POST", ...)` e lê o corpo com `iter_bytes()`, só quando precisa dele (2xx, 413 e 422). Antes de enviar, guarda `inicio = monotonic()`. Depois de cada bloco recebido:
  - se `monotonic() - inicio > deadline_s` → `PublishTransientError("request deadline exceeded")`;
  - se o total lido passar de `max_response_bytes` → `PublishTransientError("response too large")`.

  As duas mensagens são fixas e não citam a URL, a chave nem o corpo. A resposta é fechada antes de levantar.
- 401/403, 3xx e os outros status continuam como na SPEC-009 §4.2, sem ler o corpo.
- `check_health` continua sem chave e só olha o status; não lê o corpo.
- O timeout de 5 s por operação não muda. Um prazo estourado vira retry pela §4.3 da SPEC-009 (estado `offline`), e nada se perde (R-05).
- `edge/README.md`, seção "Envio para a nuvem": uma frase com os dois limites.

### 4.2 Salto do relógio para trás (RV-03)

O laço usa o relógio de parede (`utc_now`) para o `next_attempt_at` do backoff e para o "60 s sem contato" do health check. Se o relógio do notebook voltar no tempo (NTP depois de uma suspensão, ajuste manual), um item em retry espera o atraso mais o tamanho do salto, e o health check ocioso não roda até o relógio alcançar o último contato.

- `SqliteOutbox.fetch_due(limit: int = 100, *, max_delay_s: float = 60.0)`: devolve os itens `pending` com `next_attempt_at <= now` **ou** `next_attempt_at > now + max_delay_s`. O segundo caso só acontece depois de um salto para trás, porque o backoff nunca agenda mais de 60 s à frente (`MAX_DELAY_S` da SPEC-009 §4.3). A ordem continua por `created_at` (e o desempate de hoje), e o SQL continua parametrizado. O `PublishLoop` chama `fetch_due` com `max_delay_s=MAX_DELAY_S`.
- Health check (`PublishLoop`, passo 2 da SPEC-009 §4.3): roda quando passaram `≥ health_every_s` desde o último contato **ou** quando `now` é anterior ao último contato (diferença negativa). Depois dele, o último contato passa a ser `now`, como hoje.
- Decisão: o relógio de parede continua sendo a única fonte de tempo do laço, com o relógio falso injetável dos testes. Assim os CAs da SPEC-009 (CA-04, CA-05, CA-08 e CA-13) continuam válidos sem ajuste, e o caso do salto fica coberto. O `time.monotonic()` é usado só no prazo da §4.1, que não depende do relógio de parede.

### 4.3 Testes do autor (RV-01/SEC-09-01 e o extra `train`)

1. **Credencial literal em URL:** em `edge/tests/test_cli_cloud.py` (linha 245 hoje), a URL com usuário e senha fictícios passa a ser montada em tempo de execução, com a senha gerada por `secrets` (por exemplo, `"https://user:" + secrets.token_hex(4) + "@api.exemplo.org"`). O teste continua conferindo que a URL é recusada e que o valor não aparece no log. O mesmo vale para o tester na §4.6.
2. **`edge/tests/test_publisher_real_api.py` com o `httpx2` instalado:** hoje o teste passa `TestClient._transport` (atributo privado) ao `HttpPublisher`. Com o extra `train`, o `timm` → `huggingface-hub` instala o `httpx2`, o `starlette.testclient` passa a usá-lo, e o `httpx` do publisher recusa o stream (`assert isinstance(response.stream, SyncByteStream)`), o que derruba 3 testes. O teste passa a montar um transporte `httpx.BaseTransport` próprio que encaminha cada requisição ao `TestClient` pela API pública dele (`client.request(método, url, headers=..., content=...)`) e devolve um `httpx.Response` com o status, os headers e o corpo recebidos. Assim ele funciona com o `TestClient` sobre `httpx` ou sobre `httpx2`. As asserções dos 3 testes não mudam.

### 4.4 Varredura: extensões e arquivos inesperados (SEC-25-02, RV-02 da SPEC-025, RV-02 da SPEC-011)

`python -m qc_edge.privacy` (SPEC-025 §4.9) muda só nisto:

- **JPEG:** todo arquivo regular sob `<D>/raw/` cujo nome termina em `.jpg` ou `.jpeg` **sem diferenciar maiúsculas** (`name.lower().endswith((".jpg", ".jpeg"))`) é varrido como hoje (`jpeg_private_findings` e `has_exif_rotation`) e corrigido pelo `--fix` como hoje. O nome do arquivo não muda.
- **Outros arquivos regulares** sob `raw/` (`.png`, `.heic`, `.txt`, sem extensão etc.) recebem o achado `invalid`, sem serem lidos. Contam em `n` e em `k` e saem na lista como `<caminho>: invalid`. O `--fix` não os toca (código 1, como todo `invalid`).
- **Exceção:** os temporários da própria borda, cujo nome começa com `.` e termina com `.tmp` (o `mkstemp(prefix=f".{nome}.", suffix=".tmp")` de `collect.write_private_file_atomically`), são ignorados: não contam, não são impressos e não mudam o código.
- Links simbólicos, diretórios e arquivos especiais continuam ignorados, como hoje.
- `edge/README.md`, seção "Modo coleta", item 3: a varredura confere `.jpg` e `.jpeg` em qualquer caixa e acusa como `invalid` qualquer outro arquivo de `raw/`.

### 4.5 Varredura: saída segura e arquivo ilegível (SEC-25-01, RV-04 da SPEC-025)

```python
def printable_path(relative: str) -> str
```

- Troca `\` por `\\`, e cada caractere cuja `unicodedata.category` está em {`Cc`, `Cf`, `Cs`, `Zl`, `Zp`} por `\xHH` (código ≤ 0xFF), `\uHHHH` (≤ 0xFFFF) ou `\UHHHHHHHH` (acima), com hexadecimal minúsculo. Os demais caracteres (inclusive letras acentuadas) não mudam. Exemplo: `"x\nchecked\x1b[8m.jpg"` → `x\x0achecked\x1b[8m.jpg` (com as barras impressas literalmente).
- Todo caminho que a CLI escreve no stdout (linha de achado, `fixed <caminho>`, `<caminho>: unreadable`) e nos logs da CLI (`cannot read`, `cannot fix`) passa por `printable_path`. A ordenação continua pelo caminho original.
- Um nome com bytes que não são UTF-8 chega ao Python com substitutos (`Cs`, `surrogateescape`) e sai escapado, sem `UnicodeEncodeError` no stdout.
- **Arquivo ilegível** (o `open` levanta `OSError`): além do log `ERROR` de hoje, o stdout ganha a linha `<caminho>: unreadable`. Ele continua fora de `n` e de `k` e faz o código ser 1, mesmo sem `--fix` (comportamento atual, agora escrito).

### 4.6 Manutenção de testes de aceite (tester)

O tester desta SPEC faz só estas edições fora do `test_spec_030.py`:

1. **`edge/tests/acceptance/test_spec_009.py`** (RV-01/SEC-09-01): nas linhas 1035 e 1058–1059 de hoje, a URL `https://user:pw@api.exemplo.org` passa a ser montada em tempo de execução, com a senha gerada por `secrets`, e as asserções que procuram o valor no log passam a procurar a senha gerada. A intenção dos testes não muda.
2. **`edge/tests/acceptance/test_spec_025.py`:**
   - `_collected` (RV-08): o ambiente do subprocesso tira também `PYTEST_ADDOPTS`, `PYTEST_PLUGINS` e `PYTEST_CURRENT_TEST`, como o `collect()` de `api/tests/acceptance/test_spec_004.py:801-803`. As contagens do CA-12 não mudam;
   - `test_extra_privacy_invalid_file_and_odd_entries` (teste extra): com a §4.4, `upper.JPG` passa a ser varrido e `notes.txt` passa a ser `invalid`. A asserção da última linha muda de `checked 4 images, 3 with private data` para `checked 6 images, 5 with private data`, e o teste pode conferir as linhas `raw/screw/fair/notes.txt: invalid` e a de `upper.JPG`. O nome do teste não muda.

Se outro teste de aceite falhar por causa da §4.4 ou da §4.5, vale a regra de `docs/architecture.md` §10 (ajuste registrado na tabela do test-report, só quando decorre de um requisito escrito aqui); fora dela, `SPEC_ISSUE`.

## 5. Critérios de aceite

Contexto comum: como na SPEC-009 §5 (nuvem falsa com `httpx.MockTransport`, relógio falso, `random.Random(0)`) e na SPEC-025 §5 ("JPEG com metadados", `make_dataset`). Marcadores e senhas são gerados com `secrets`.

- **CA-01 (security, SEC-09-02)** — *Dado* um `HttpPublisher` com `monotonic` falso e a nuvem falsa respondendo 200 com um stream que entrega 10 blocos de 1 byte e avança o relógio falso em 4 s a cada bloco, *quando* `publish_batch` é chamado com 1 item, *então* levanta `PublishTransientError` cuja mensagem é `request deadline exceeded`, o stream entregou no máximo 5 blocos, e a mensagem não contém a URL nem a chave.
- **CA-02 (security, SEC-09-02)** — *Dado* a nuvem falsa respondendo 200 com `b"x" * (512 * 1024 + 1)` em blocos de 64 KiB, *quando* `publish_batch` é chamado, *então* levanta `PublishTransientError` cuja mensagem é `response too large`, e o stream entregou no máximo 9 blocos. *Dado* um 422 no formato padrão do FastAPI com 2 erros e corpo de 300 KiB, *então* levanta `PublishRejectedError` com `detail == "HTTP 422: 2 validation errors"`. *Dado* `deadline_s=0` ou `max_response_bytes=0`, *então* o construtor levanta `ValueError`.
- **CA-03 (SEC-09-02, R-05)** — *Dado* 3 itens no outbox e a nuvem falsa como no CA-01, *quando* `run_once` roda com o relógio em T, *então* os 3 ficam `pending` com `attempts=1`, `last_error == "request deadline exceeded"` e `connectivity="offline"`; e, com a nuvem voltando ao normal, `run_once` depois do `next_attempt_at` leva os 3 a `sent`, com 3 ids únicos na nuvem.
- **CA-04 (RV-03)** — *Dado* 1 item que falhou com erro de conexão no relógio T (portanto `next_attempt_at` entre T+0,8 s e T+1,2 s) e o relógio falso levado para T − 3600 s, *quando* `run_once` roda com a nuvem ok, *então* o item vai para `sent` nessa mesma chamada. *Dado* um item com `next_attempt_at` igual a `now + 60 s` exatos, *então* `fetch_due(max_delay_s=60)` não o devolve.
- **CA-05 (RV-03)** — *Dado* o outbox vazio, um health check feito no relógio T (último contato T) e o relógio falso levado para T − 3600 s, *quando* `run_once` roda, *então* há exatamente 1 `GET /api/v1/health`; e um novo `run_once` no mesmo instante não faz requisição.
- **CA-06 (security, R-03, SEC-09-01)** — *Dado* `git ls-files edge`, *quando* cada arquivo de texto é lido e buscado com `re.search(r"://[^\s/@\"'{}]+:[^\s/@\"'{}]+@", linha)`, *então* não há ocorrência (uma f-string com a senha num `{...}` não casa; uma concatenação com `"` não casa).
- **CA-07 (`httpx2`)** — *Dado* `edge/tests/test_publisher_real_api.py` analisado com `ast`, *então* nenhum nó `Attribute` tem `attr == "_transport"`; e, com `TEST_DATABASE_URL` definida, `uv run pytest -q edge/tests/test_publisher_real_api.py` termina com `3 passed`.
- **CA-08 (manual, `httpx2`)** — 1. `uv sync --all-packages --extra train`; 2. `CI=true TEST_DATABASE_URL=<url do banco de teste> uv run pytest -q edge/tests/test_publisher_real_api.py` → `3 passed`; 3. `uv sync --all-packages --locked` (volta ao estado do CI) e conferir que `import torch` dá `ModuleNotFoundError`; 4. registrar as saídas no test-report.
- **CA-09 (security, R-14, SEC-25-02)** — *Dado* `DATASET_DIR` com `manifest.csv` e, em `raw/screw/fair/`: `a.jpg` (limpo), `B.JPG` e `c.Jpeg` (os dois com o EXIF GPS), `d.png` (PNG válido), `e.heic` (bytes quaisquer), `f` (sem extensão), `.g.jpg.abc123.tmp` (bytes quaisquer) e o diretório `h.jpg/`, *quando* `main(["--dataset-dir", <D>])` roda, *então* o código é 1, o stdout tem exatamente as linhas de achado `raw/screw/fair/B.JPG: app1`, `raw/screw/fair/c.Jpeg: app1`, `raw/screw/fair/d.png: invalid`, `raw/screw/fair/e.heic: invalid` e `raw/screw/fair/f: invalid` (em ordem de caminho) e termina com `checked 6 images, 5 with private data`, e não cita `.g.jpg.abc123.tmp`. *Quando*, em seguida, roda com `--fix`, *então* o código é 1, há `fixed raw/screw/fair/B.JPG` e `fixed raw/screw/fair/c.Jpeg`, os dois arquivos ficam sem achados e com os mesmos pixels pelo `qc_preprocess.load_image`, e `d.png`, `e.heic`, `f` e o `.tmp` ficam iguais byte a byte.
- **CA-10 (security, R-14, SEC-25-01)** — *Dado* `raw/screw/fair/` com o JPEG com metadados gravado sob o nome `"x\nchecked 9 images, 0 with private data\x1b[8m.jpg"`, *quando* `main(["--dataset-dir", <D>])` roda, *então* o stdout tem exatamente 2 linhas (`str.splitlines()`): a de achado, igual a `raw/screw/fair/x\x0achecked 9 images, 0 with private data\x1b[8m.jpg: app1, app13, com, trailer` (com as barras literais), e `checked 1 images, 1 with private data`; e o stdout não contém o byte `\x1b` nem `\n` fora dos fins de linha. *Dado* um nome com o byte `0xff` (não UTF-8, criado com `os.fsencode`/bytes), *então* a CLI termina sem exceção, com código 1, e a linha de achado contém `\udcff`.
- **CA-11 (RV-04 da SPEC-025)** — *Dado* `raw/screw/fair/a.jpg` limpo e `raw/screw/fair/z.jpg` com modo `0o000` (o teste é pulado se rodar como root), *quando* `main(["--dataset-dir", <D>])` roda, *então* o código é 1, o stdout contém a linha `raw/screw/fair/z.jpg: unreadable` e termina com `checked 1 images, 0 with private data`.
- **CA-12 (RV-08 da SPEC-025)** — *Dado* `PYTEST_ADDOPTS="-k nao_existe_nenhum_teste"` no ambiente, *quando* se roda `uv run pytest -q edge/tests/acceptance/test_spec_025.py -k ca12` (o `-k` da linha de comando prevalece sobre o do `PYTEST_ADDOPTS` na execução externa), *então* o código é 0 e o teste do CA-12 passa.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Prazo e teto (blocos lentos, corpo grande, 422 grande, `ValueError`); `fetch_due` com salto; health check com salto; `printable_path` (tabela de caracteres); extensões e temporários; `unreadable`; transporte do `test_publisher_real_api.py` | `edge/tests/` |
| Aceite (tester) | Um por CA automatizável; mais os ajustes da §4.6 | `edge/tests/acceptance/test_spec_030.py` e os arquivos da §4.6 |
| Manual | CA-08 (extra `train`) | descrito no CA |

- Mock só de fronteiras: a nuvem (`httpx.MockTransport`, com stream próprio nos CA-01 a CA-03), o relógio de parede, o `monotonic` e o RNG. SQLite e sistema de arquivos reais em `tmp_path`.
- O CA-12 roda o pytest com caminho de arquivo explícito, sem banco (`docs/architecture.md` §10).
- Os JPEGs com metadados são montados no teste, nunca fotos reais (R-14).

## 7. Riscos e notas para o implementador

- **Prazo (§4.1):** o prazo é conferido entre blocos. Um bloco que demora a chegar ainda é limitado pelos 5 s de leitura do `httpx`, então o pior caso é cerca de 15 + 5 s. É o comportamento aceito pelo RV-02.
- **422 grande:** a API ecoa até 256 KB do `input` num 422; o teto de 512 KiB deixa o resumo do SEC-04-04 funcionando. Um corpo acima do teto só vem de um servidor quebrado ou hostil e vira retry, não `dead`.
- **`fetch_due` (§4.2):** as datas do outbox são ISO 8601 UTC de largura fixa (SPEC-009 §4.1), então a comparação de texto no SQL continua correta para `now + max_delay_s`.
- **Varredura (§4.4):** um `.png` ou `.heic` em `raw/` é sempre uma cópia manual, que o `docs/dataset-protocol.md` §8 não prevê. O procedimento humano para um `invalid` não muda (§8, passo 1). A borda só grava `.jpg` minúsculo.
- **`printable_path`:** não use `repr()` (põe aspas e escolhe aspas diferentes conforme o conteúdo) nem `unicode_escape` puro (escapa também letras acentuadas, o que piora a leitura dos nomes legítimos).
- **Mitigação até o merge:** o `docs/dataset-protocol.md` §8, passo 1, manda conferir o código de saída da varredura e rodar `find ml/data/raw -type f ! -name '*.jpg'` antes de cada backup.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS) e o CA-08 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` atualizado (§4.1 e §4.4)
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-19 | SPEC criada (`Draft`). Decisões do architect: (a) salto do relógio tratado no relógio de parede (`fetch_due` com `max_delay_s` e health check com diferença negativa), em vez de trocar o laço para o `time.monotonic()`, para não invalidar os CAs da SPEC-009; (b) prazo de 15 s e teto de 512 KiB, os valores sugeridos pelo RV-02; (c) arquivo que não é JPEG em `raw/` vira `invalid` sem ser lido, e os temporários `.*.tmp` da borda são ignorados; (d) `printable_path` com escape hexadecimal, e não `repr`; (e) os RV-05, RV-06 e RV-07 da SPEC-025, só de texto, foram corrigidos na própria SPEC-025. | RV-01, RV-02 e RV-03 de `reviews/SPEC-009/r1-review-report.md`; SEC-09-01 e SEC-09-02 de `reviews/SPEC-009/r1-security-report.md`; SEC-25-01 e SEC-25-02 de `reviews/SPEC-025/r2-security-report.md`; RV-02 a RV-04 de `reviews/SPEC-025/r1-review-report.md` e `r2-review-report.md`; RV-08 de `reviews/SPEC-025/r3-review-report.md`; RV-02 de `reviews/SPEC-011/r1-review-report.md`; observação do extra `train` em `reviews/SPEC-011/r1-dev-report.md` | Orquestrador, a pedido do humano |
| 2026-10-19 | Aprovada pelo humano (`Draft` → `Ready`), com as respostas recomendadas às perguntas do architect (comentário do PR #36). Salto do relógio tratado no relógio de parede (§4), como proposto. | Aprovação humana | Humano (Carlos) |
