# SPEC-040: Manutenção consolidada antes da apresentação (respostas comprimidas, varredura de privacidade, URL do painel, alertas, ML e documentação de deploy)

| Campo | Valor |
|---|---|
| Status | Draft |
| Rodada atual | — |
| Autor da implementação | developer (Parte A: `edge/`, `api/`, `dashboard/`), depois ml-engineer (Parte B: `ml/`), depois security-devops (Parte C: comentários de `infra/docker/*.Dockerfile`, `.streamlit/config.toml` e `docs/deployment-plan.md`), na mesma rodada (§6) |
| Tags | security, deploy, infra |
| Depende de | SPECs 016, 017, 018, 036 e 038 **mergeadas antes de esta entrar em `In Dev`** (a Parte A muda o `publisher.py` e o `heartbeat.py` da 018, o `alerts.py` e o `api/README.md` da 017 e o `privacy.py` que a 038 também muda; a Parte B muda o `split.py` e o `report.py` da 016; a Parte C muda o `docs/deployment-plan.md` que a 017 e a 038 também mudam); SPEC-039 (mergeada); SPECs 029, 030, 031 e 037 (`Done`) |
| Semana alvo | S7 (23–29/11): logo depois da SPEC-038 e antes do ensaio da apresentação (M4, 29/11). Nenhum merge dela na véspera nem no dia da apresentação (webhook do ADR-023) |
| Requisitos cobertos | RF-06, RF-07, RF-17, RF-18, RNF-04, RNF-05, RNF-06, RNF-09, RNF-10; R-02, R-03, R-05, R-11, R-14 |
| ADRs relevantes | ADR-009, ADR-014, ADR-016, ADR-019, ADR-020, ADR-022, ADR-023 |

## 1. Contexto

Junta as pendências **baixas**, não bloqueantes, que estavam só registradas no `docs/plan.md` §3 (blocos "Pendências da SPEC-0XX") ou nos relatórios das SPECs 016, 017 e 018 (ainda em branch quando esta SPEC foi escrita), sem SPEC. O humano autorizou o projeto inteiro e pediu testes de segurança e qualidade em tudo (decisão de 2026-10-24). Nenhuma pendência muda o contrato, a API (rotas, status, schemas), o banco nem uma regra negociável. Por isso não há ADR.

Componentes tocados, em `docs/architecture.md`: §4 (bloco "Envio" dos alertas, a partir da SPEC-017), §6.2 (publisher), §6.3 (varredura de privacidade), §7 (CHANGELOG do modelo) e §8/§9 (operação na VPS, ADR-023).

| Pendência | Origem | Severidade | Decisão |
|---|---|---|---|
| SEC-30-01 (= RV-01 = O-01) | `reviews/SPEC-030/r1-security-report.md`, `r1-review-report.md` | baixa | **Entra** (§4.1): o teto de 512 KiB do publisher conta bytes já descomprimidos, e `Content-Encoding: gzip, gzip` derruba o `qc-edge` por memória |
| SEC-30-03 | `reviews/SPEC-030/r1-security-report.md` | baixa | **Fora** (§3.2): prazo total sem a fase dos headers |
| SEC-30-02 (= RV-02 = O-03) | mesmos relatórios | baixa | **Entra** (§4.2): a varredura pula em silêncio subpastas ilegíveis de `raw/` |
| SEC-30-04 (= RV-03 = O-02) | mesmos relatórios | baixa | **Entra** (§4.2): a exceção `.*.tmp` vale para qualquer nome |
| RV-04 da SPEC-030 | `reviews/SPEC-030/r1-review-report.md` | baixa | **Feito pelo architect junto com esta SPEC** (§3.1): `docs/dataset-protocol.md` §8, passo 1 |
| RV-05 da SPEC-030 | `reviews/SPEC-030/r1-review-report.md` | baixa | **Entra** (§4.11, tester): comentário desatualizado em `test_spec_025.py` |
| SEC-29-01 (= RV-04 = O-01) | `reviews/SPEC-029/r1-security-report.md`, `r1-review-report.md` | baixa | **Entra** (§4.4): `API_BASE_URL` com `Cf`/`Zl`/NBSP ou punycode inválido derruba a Visão geral |
| RV-01 da SPEC-029 | `reviews/SPEC-029/r1-review-report.md` | baixa | **Entra** (§4.4): caso NBSP duplicado em `dashboard/tests/test_config.py` |
| RV-02 e RV-03 da SPEC-029, SEC-29-02 | mesmos relatórios | baixa / info | **Fora** (§3.2) |
| RV-01 da SPEC-031 | `reviews/SPEC-031/r1-review-report.md` | baixa | **Fora: já resolvido** pela SPEC-037 §4.6 (`try/finally` em `ml/src/qc_ml/export.py`, conferido na `main` em 2026-10-26) |
| RV-02 da SPEC-031 | `reviews/SPEC-031/r1-review-report.md` | baixa | **Fora, sem ação** (decidido na aprovação da SPEC-037) |
| RV-02 da SPEC-037 | `reviews/SPEC-037/r1-review-report.md` | baixa | **Entra** (§4.6): `n_items_test_by_grade` e `warnings` copiados sem conferir no CHANGELOG |
| RV-01 da SPEC-016 | `reviews/SPEC-016/r1-review-report.md` (branch da 016) | baixa | **Entra** (§4.8): continuação de linha nos exemplos do `ml/README.md` |
| RV-03 da SPEC-016 | `reviews/SPEC-016/r1-review-report.md` | baixa | **Entra** (§4.7): uma ferramenta já estendida poderia ser estendida de novo (ADR-022, decisão 5; R-11) |
| RV-02 e RV-04 da SPEC-016 | mesmo relatório | baixa | **Fora** (§3.2) |
| SEC-16-01 | `reviews/SPEC-016/r1-security-report.md` | baixa | **Entra** (§4.10): ordem de migração, API, borda e `requeue` no plano de deploy |
| SEC-16-02 | mesmo relatório | baixa | **Fora** (§3.2): exemplo na skill `contrato-api` (`.claude/`) |
| RV-03 = SEC-03 da SPEC-018 | `reviews/SPEC-018/r1-review-report.md`, `r1-security-report.md` (branch da 018) | baixa | **Entra** (§4.3): traceback completo ao montar o heartbeat |
| RV-04 da SPEC-018 | `reviews/SPEC-018/r1-review-report.md` | baixa | **Entra** (§4.3): type hint de `_cap` |
| SEC-04 da SPEC-018 | `reviews/SPEC-018/r1-security-report.md` | informativa | **Entra** (§4.10), junto com o SEC-16-01 |
| Observações 4 e 5 do test-report da SPEC-018 | `reviews/SPEC-018/r1-test-report.md` | observação | **Entra** (§4.11, tester): docstring e constantes sem uso em aceites antigos |
| RV-01, RV-02 = SEC-02, SEC-01 da SPEC-018 | relatórios da 018 | baixa | **Fora** (§3.2) |
| SEC-17-02 | `reviews/SPEC-017/r2-security-report.md` (branch da 017) | baixa | **Entra** (§4.5): mesmo problema do SEC-30-01 no cliente do Telegram |
| SEC-17-03 = RV-04 do r2-review da 017 | `reviews/SPEC-017/r2-security-report.md`, `r2-review-report.md` | baixa (risco aceito) | **Entra só a melhoria opcional** (§4.5 e §4.10): idade do envio abandonado no aviso e "Restart" documentado; o risco continua aceito |
| SEC-17-01 | `reviews/SPEC-017/r2-security-report.md` | baixa | **Fora: já resolvido** no `docs/deployment-plan.md` da branch da 017 (conferência de RLS e grants da `alerts_sent`, item 5 da §8) |
| `api/README.md` da SPEC-017 com `infra/.env.api` e checkout na VPS | pedido do orquestrador (ADR-023, decisão "nenhum `.env` é criado à mão na VPS, e nenhum checkout manual é feito nela") | baixa | **Entra** (§4.5) |
| RV-02 da SPEC-039 | `reviews/SPEC-039/r2-review-report.md` | baixa | **Entra** (§4.9): comentários antigos de `env_file`/`infra/.env.dashboard` (a SPEC-038 deixou fora, `reviews/SPEC-038/r1-dev-report.md`) |
| RV-03 da SPEC-039 | `reviews/SPEC-039/r1-review-report.md`, `r2-review-report.md` | baixa | **Architect, só texto** (§3.1), depois do CA-15 manual da SPEC-039 |
| RV-04 da SPEC-039 | mesmos relatórios | baixa | **Entra** (§4.11, tester): helpers sem uso em `test_spec_015.py` |
| SEC-39-05 | `reviews/SPEC-039/r2-security-report.md` | baixa | **Entra** (§4.10): nota sobre proxy de CDN no DNS |
| SEC-39-06 | `reviews/SPEC-039/r2-security-report.md` | baixa | **Fora: já na SPEC-038** (reaprovada pelo humano em 2026-10-26, SPEC_ISSUE-038-B1) |

**Fato novo que muda a correção do SEC-30-01.** O SEC-30-01 dizia que "nem o Caddy nem a API comprimem". Com o ADR-023, há um terceiro salto: o proxy do Coolify (Traefik). A documentação do Coolify mostra o middleware `gzip` no roteador HTTPS gerado para uma aplicação (`traefik.http.routers.https-0-<resource-id>.middlewares=gzip`, <https://coolify.io/docs/knowledge-base/proxy/traefik/custom-middlewares>, consultado em 2026-10-26). Pela referência do Traefik, o middleware `compress` só comprime quando o `Accept-Encoding` da requisição contém `gzip`, `*`, `br` ou `zstd`, o corpo passa de `minResponseBodyBytes` (padrão 1024) e a resposta ainda não tem `Content-Encoding`; com o header ausente, a resposta não é codificada, salvo com `defaultEncoding` configurado (<https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/compress/>, consultado em 2026-10-26). O `httpx` manda `Accept-Encoding: gzip, deflate` por padrão. Logo, hoje, uma resposta de lote com mais de 1 KB **já chega comprimida** à borda na VPS, e só recusar `Content-Encoding` quebraria o envio. Por isso a §4.1 manda `Accept-Encoding: identity` **e** recusa qualquer outra codificação, e o CA-18 (manual) confere o caminho real.

## 2. Objetivo

A borda e o laço de alertas nunca descomprimem uma resposta (pedem `identity` e recusam outra codificação antes de ler o corpo, sem perder nenhuma inspeção); a varredura de privacidade lista como `unreadable` toda subpasta ou arquivo que não consegue ler e só ignora os temporários no formato exato da borda; o painel recusa um `API_BASE_URL` que o `httpx` não consegue montar, sem exceção na tela; o CHANGELOG do modelo não copia contagens nem avisos fora do formato; uma ferramenta já estendida no teste nunca é estendida de novo; e a documentação de deploy cobre o Coolify (alertas, migrações com contrato novo, CDN e comentários dos arquivos de imagem).

## 3. Escopo

### 3.1 Dentro

**Parte A (developer):**

- `edge/src/qc_edge/publisher.py`: `Accept-Encoding: identity` e recusa de `Content-Encoding` (§4.1).
- `edge/src/qc_edge/privacy.py`: subpastas e arquivos ilegíveis (§4.2) e formato exato dos temporários (§4.2).
- `edge/src/qc_edge/heartbeat.py`: registro do erro ao montar o heartbeat e type hint de `_cap` (§4.3).
- `dashboard/src/qc_dashboard/config.py` e `dashboard/src/qc_dashboard/api.py`: validação do host do `API_BASE_URL` e defesa em profundidade (§4.4).
- `api/src/qc_api/services/alerts.py`: `Accept-Encoding: identity`, recusa de `Content-Encoding` e aviso do envio abandonado com a idade (§4.5).
- `api/README.md` (§4.5) e `edge/README.md` (§4.1 e §4.2).
- Testes do autor em `edge/tests/`, `dashboard/tests/` (inclusive o caso NBSP de `dashboard/tests/test_config.py`, RV-01 da 029) e `api/tests/`, fora de `acceptance/`.

**Parte B (ml-engineer):**

- `ml/src/qc_ml/report.py`: conferência de `n_items_test_by_grade` e de `warnings` no `changelog` (§4.6).
- `ml/src/qc_ml/split.py`: tipos já estendidos em qualquer versão anterior nunca são "novos" (§4.7).
- `ml/README.md`: continuação de linha nos dois exemplos (§4.8).
- Testes do autor em `ml/tests/`, fora de `acceptance/`.

**Parte C (security-devops):**

- Comentários do cabeçalho de `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` e `.streamlit/config.toml` (§4.9).
- `docs/deployment-plan.md` (§4.10).
- Testes do autor em `infra/tests/`, fora de `acceptance/`, se precisar.

**Tester:** `edge/tests/acceptance/test_spec_040.py` (CA-01 a CA-06 e a parte de `edge/README.md` do CA-11), `dashboard/tests/acceptance/test_spec_040.py` (CA-07 e CA-08), `api/tests/acceptance/test_spec_040.py` (CA-09, CA-10 e a parte de `api/README.md` do CA-11), `ml/tests/acceptance/test_spec_040.py` (CA-12 a CA-15) e `infra/tests/acceptance/test_spec_040.py` (CA-16 e CA-17). Mais os ajustes da §4.11.

**Testes de aceite de SPECs anteriores** (`docs/architecture.md` §10, aplicação explícita). Além da limpeza da §4.11, o tester ajusta, só nas asserções afetadas e registrando na tabela do test-report, os testes antigos que um requisito desta SPEC invalidar. Os prováveis:

| Arquivo | Por quê | Requisito |
|---|---|---|
| `edge/tests/acceptance/test_spec_030.py` (e `test_spec_025.py`) | um temporário com nome fora do formato do `mkstemp` (ex.: `.x.tmp`) passa a ser `invalid`; o teste troca o nome por um do formato da §4.2, e a intenção ("os temporários da borda são ignorados") continua | §4.2 |
| `api/tests/acceptance/test_spec_017.py` | o aviso `alerts check stopped: a previous send is still running` ganha o sufixo da §4.5; um teste que compare a mensagem inteira passa a conferir o prefixo e o formato; o teste que lê os blocos `bash` do `api/README.md` (`test_extra_docs_never_put_the_token_in_argv`) segue os comandos novos, com a mesma intenção (token nunca no `argv`) | §4.5 |
| `dashboard/tests/acceptance/test_spec_029.py` (e `test_spec_028.py`, `test_spec_013.py`) | se algum aceita como segura uma URL que a §4.4 passa a recusar (NBSP, `Cf`, `Zl`, punycode inválido) | §4.4 |
| `edge/tests/acceptance/test_spec_009.py`, `test_spec_018.py` e `test_spec_030.py` | se algum compara o conjunto exato de headers enviados pelo publisher | §4.1 |

**Architect:**

- **Feito junto com esta SPEC:** `docs/dataset-protocol.md` §8, passo 1 (RV-04 da SPEC-030): sai o "Até o merge da SPEC-030", ficam o código de saída da varredura, o `find ml/data/raw -type f ! -name '*.jpg'` e, até o merge desta SPEC, a conferência de permissões (SEC-30-02).
- **Na rodada, antes do review:** notas "a partir da SPEC-040" em `docs/architecture.md` §4 (bloco "Envio" dos alertas), §6.2 (publisher) e §6.3 (varredura). Ficam para a rodada porque as SPECs 016 a 018 ainda mudam esse arquivo nas branches delas.
- **Depois do CA-15 manual da SPEC-039** (RV-03 da 039): alinhar a frase do CA-15, passo 2, da SPEC-039 ao lugar real da opção "Preserve repository during deployment" registrado pelo humano, com uma linha no Histórico dela. Só texto, sem reaprovação (mesmo precedente das correções só de texto das SPECs 010, 013 e 025).

### 3.2 Fora

- **SEC-30-03 (prazo total sem a fase dos headers, nos status sem leitura do corpo e no `check_health`):** fora, sem SPEC agora. A correção (um `threading.Timer` ou uma thread com `join`, como a SPEC-017 fez no Telegram) mexe no caminho crítico do envio logo antes da apresentação. O ator é o mesmo do SEC-30-01 (a própria API comprometida ou um host com certificado válido para o qual a URL aponta), o efeito é só a thread de envio parada, as inspeções ficam `pending` no outbox durável (R-05), e reiniciar o `qc-edge` resolve. É o mesmo raciocínio do risco aceito no SEC-17-03. Se o humano quiser, entra numa SPEC da borda depois da entrega.
- **RV-01 da SPEC-031:** já resolvido pela SPEC-037 §4.6. **RV-02 da SPEC-031:** sem ação, como decidido na aprovação da SPEC-037.
- **RV-02 da SPEC-029** (`SPEC013_COUNT_ON_MAIN = 118` no CA-02 de `test_spec_029.py`): sem ação. Só importa quando uma SPEC mexer em `test_spec_013.py`, e o test-report dessa SPEC registra o ajuste pela §10. **RV-03 da SPEC-029:** registro de status do orquestrador, fora do loop de SPEC. **SEC-29-02:** informativo, sem desvio de destino.
- **RV-02 da SPEC-016** (nome `inspections_grade_null_iff_unknown`): fica para a SPEC-021, a próxima a mexer nesse `check`, como o próprio relatório sugere. **RV-04 da SPEC-016:** nota de processo, sem código.
- **SEC-16-02** (exemplo de invariante antiga no checklist da skill `contrato-api`): fora desta SPEC, porque `.claude/` não é escrito por nenhum autor do loop nem pelo architect. O orquestrador (ou o humano) atualiza o exemplo para "grupos de grau do ADR-021" numa mudança de processo.
- **RV-01 da SPEC-018** (índice `(device_id, received_at desc)` para o `last_source`): risco desprezível com o volume da demo; reavaliar se o histórico crescer.
- **RV-02 = SEC-02 da SPEC-018** (`check` de faixa nas datas de `devices`): risco desprezível. Exige escrita direta no banco (SQL Editor), que já é o limite de confiança, e custaria uma migração `006` e mais um passo de deploy antes da apresentação. Ver a pergunta 2 do §9.
- **SEC-01 da SPEC-018** (a página pública "Dispositivos" mostra quando o gateway está ligado): ciência da dupla; proteger o dashboard seria uma decisão futura (ADR). As observações de interface do test-report da 018 ("Ligado há" de um dispositivo offline, modo lax do `HEARTBEAT_INTERVAL_S`) ficam para o CA-13 manual da 018.
- **SEC-17-01:** já resolvido no `docs/deployment-plan.md` da branch da 017. **Observações do r2-security da 017** (lista fixa de loggers redigidos, `RuntimeError` no `Thread.start()`, corrida na borda do prazo): sem ação; a semântica do prazo é a do §4.5 da 017.
- **SEC-39-06:** na SPEC-038.
- **Observação do test-report da SPEC-016** (limiar de revisão com validação só de ferramentas): não acontece com dados reais, porque o `split_v1` sempre tem parafuso e porca.
- Compressão no caminho dashboard → API (o `httpx` do dashboard pede `gzip`, e o Traefik pode comprimir): fora. É o caminho da própria VPS, com a chave de leitura, e o dashboard não tem teto de resposta a contornar.
- MQTT: a ponte da SPEC-020 reusa o `HttpPublisher` e herda a §4.1 sem mudança nesta SPEC.

## 4. Requisitos detalhados

### Parte A (developer)

#### 4.1 Publisher: respostas comprimidas (SEC-30-01)

- O `httpx.Client` do `HttpPublisher` é criado com o header padrão `Accept-Encoding: identity`, então toda requisição (`publish_batch`, `send_heartbeat` e `check_health`) o envia com exatamente esse valor.
- Em `publish_batch` e `send_heartbeat`, **antes** de ler o corpo (`_read_body`), a resposta é conferida: cada valor de `response.headers.get_list("content-encoding", split_commas=True)`, depois de `strip()` e em minúsculas, tem de ser vazio ou `identity`. Senão, a resposta é fechada sem ler o corpo, e o método levanta `PublishTransientError` com a mensagem fixa `unsupported response encoding` (constante `UNSUPPORTED_ENCODING` em `qc_edge.publisher`).
- Vale para todo status cujo corpo hoje é lido (2xx e 413/422 no lote; 204 e 413/422 no heartbeat). Um 413/422 comprimido também vira `PublishTransientError` (e não `PublishRejectedError`), porque o resumo exigiria ler o corpo. Os status cujo corpo não é lido (401, 403, 3xx, 5xx) não mudam.
- `check_health` não muda além do header: o corpo continua nunca lido.
- O laço trata o erro como qualquer `PublishTransientError` (backoff e nova tentativa); nenhum item muda de estado (R-05). A mensagem não contém a chave, a URL nem o corpo.
- `edge/README.md`: a seção sobre o envio à nuvem diz que a borda pede `Accept-Encoding: identity` e recusa resposta comprimida com `unsupported response encoding` (os itens ficam `pending`), e que o proxy do Coolify só comprime quando o cliente pede.

#### 4.2 Varredura de privacidade: ilegíveis e temporários (SEC-30-02, SEC-30-04)

- **Subpasta ilegível:** a travessia de `raw/` passa a tratar o erro de listagem (por exemplo, `os.walk(..., onerror=...)`). Cada diretório sob `raw/` (inclusive o próprio `raw/`, se existir) que não pode ser listado vira a linha `<caminho relativo a D>: unreadable` no stdout, com `printable_path`, e um registro `ERROR` `cannot read <caminho>: <strerror ou classe>` no logger `qc_edge.privacy`. O código de saída passa a 1. **`raw/` inexistente** continua como hoje: nenhuma linha `unreadable`, `checked 0 images, 0 with private data` e código 0.
- **Arquivo sem `lstat`:** quando o `os.lstat` de um nome listado falha (subpasta com `r` sem `x`), o arquivo vira `<caminho relativo>: unreadable`, com o mesmo registro `ERROR`, não conta em `checked` e deixa o código em 1 (hoje é descartado em silêncio).
- As linhas `unreadable` saem na ordem crescente do caminho relativo (comparação de `str`), junto com as outras linhas, antes do resumo. Com `--fix`, vale o mesmo, e nada é reescrito numa pasta ilegível.
- **Temporários:** `is_edge_temporary(name)` só devolve `True` quando `re.fullmatch(r"\.(?P<target>.+)\.[a-z0-9_]{8}\.tmp", name)` casa **e** `is_jpeg_name(target)` é verdadeiro. É o nome que `tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp")` gera em `qc_edge.collect.write_private_file_atomically` (8 caracteres de `abcdefghijklmnopqrstuvwxyz0123456789_`, pela classe `_RandomNameSequence` de <https://github.com/python/cpython/blob/3.12/Lib/tempfile.py>, consultado em 2026-10-26), usado pela coleta, pela importação e pelo `--fix`. Qualquer outro nome terminado em `.tmp` é tratado como os outros arquivos (não JPEG → `invalid`, sem leitura).
- `edge/README.md`: a seção da varredura diz que subpastas e arquivos sem permissão aparecem como `unreadable` e deixam o código em 1.

#### 4.3 Heartbeat (RV-03 = SEC-03 e RV-04 da SPEC-018)

- Em `HeartbeatLoop.run_once`, uma exceção inesperada ao montar o heartbeat (o `except Exception` depois de `SinkError` e `ValidationError`) é registrada com `logger.error("heartbeat could not be built: %s", type(exc).__name__)`, sem `exc_info` e sem a mensagem da exceção, no mesmo logger de hoje. Nada é enviado nesse ciclo, e o laço continua.
- `def _cap(value: float) -> int`, com o mesmo comportamento (`int()` trunca, limitado a `[0, MAX_HEARTBEAT_COUNT]`).

#### 4.4 `API_BASE_URL` que o `httpx` não monta (SEC-29-01, RV-01 da SPEC-029)

- `is_secure_api_url(url)` passa a devolver `False` também quando o `httpx` não consegue montar uma requisição para `url`: dentro do `try`, além do `urlsplit`, o autor monta a URL como o `httpx` fará na leitura (por exemplo, `httpx.Request("GET", url)`, ou `httpx.URL(url)` com o `raw_host` codificado, como o `scripts/simulate.py`), e `httpx.InvalidURL` ou `ValueError` (inclusive `UnicodeError` e `idna.IDNAError`) viram `False`. O autor confere qual chamada cobre o `https://xn--zz.com`, que passa no construtor do `httpx.Client` e só falha ao montar a requisição (SEC-29-01). Nada sai da máquina nessa conferência (sem DNS nem conexão).
- `get_settings()` continua levantando `InsecureApiUrlError` (mensagem só com o nome da variável), e a página mostra a mensagem de hoje (`INSECURE_API_URL_MESSAGE`).
- **Defesa em profundidade:** em `get_client()` (construção do `httpx.Client`) e em `ApiClient._get` (montagem da requisição, separada do envio por `build_request` + `send`), um `httpx.InvalidURL` ou `ValueError` levantado **na construção ou na montagem** vira `InsecureApiUrlError("API_BASE_URL is not a valid URL")`, sem a URL nem a chave. Um `ValueError` da leitura da resposta (JSON inválido) continua com o tratamento de hoje.
- As URLs aceitas hoje continuam aceitas (CA-07).
- Teste do autor: o caso NBSP de `dashboard/tests/test_config.py` passa a testar a URL **com** o NBSP (sem o `.replace`) e esperar `False`.

#### 4.5 Alertas no Telegram (SEC-17-02, SEC-17-03) e `api/README.md`

- `_client` passa a criar o `httpx.Client` com o header padrão `Accept-Encoding: identity`.
- Em `_post`, **antes** de ler o corpo, a mesma conferência da §4.1 sobre `Content-Encoding`. Fora de vazio/`identity`, `_post` devolve `(False, f"unsupported content encoding (status={status})")` sem ler o corpo. O envio conta como falha (`delivered = false`, sem nova tentativa, como no §4.3 da SPEC-017), e `send_message` registra `telegram send failed: unsupported content encoding (status=<n>)`, sem o token.
- **Envio abandonado:** cada envio abandonado no prazo guarda o instante do abandono (relógio monotônico). Quando `run_check` para por haver um envio abandonado vivo, o aviso passa a ser `alerts check stopped: a previous send is still running (abandoned_for_s=<n>, lot_id=<lot_id>, source=<source>)`, em que `<n>` é o inteiro (truncado) de segundos desde o abandono do envio abandonado vivo mais antigo, e `lot_id`/`source` são do candidato que não foi reservado nesta verificação. Só inteiros e IDs já validados; nunca o token. O resto do comportamento (no máximo uma thread abandonada, nada reservado enquanto ela vive, espera de até 1 s) não muda.
- **`api/README.md`, seção "Alertas no Telegram"**, reescrita para o Coolify (ADR-023), sem `infra/.env.api`, sem `sed`, sem checkout na VPS e sem `docker compose -f infra/compose.yaml`:
  1. o token vai direto do `@BotFather` para o campo `TELEGRAM_BOT_TOKEN` das Environment Variables do recurso **`partqc-api`** no Coolify (só runtime, Locked, Literal), nunca para o `partqc-web` nem para outro lugar;
  2. o `chat_id` é lido **na VPS**, com o token tirado do ambiente do contêiner da API e entregue ao `curl` por um descritor, como no `docs/deployment-plan.md` §8, item 5 (o `docker exec` recebe só o nome da variável; o token não vai para o `argv` nem para o histórico do shell, e nenhum arquivo é gravado):

     ```bash
     t=$(docker exec <contêiner da api> printenv TELEGRAM_BOT_TOKEN)
     curl -s -K <(printf 'url = "https://api.telegram.org/bot%s/getUpdates"\n' "$t") | python3 -m json.tool | grep -A4 '"chat"'
     unset t
     ```

     com o nome do contêiner pela listagem do plano de deploy (convenções da §4 dele);
  3. ligar, desligar e trocar o token pelas Environment Variables do `partqc-api`, com **Redeploy** (ou **Restart**) só desse recurso;
  4. conferir o log pela aba de logs da `api` no painel ou por `docker logs --tail 200 <contêiner da api> 2>&1 | grep -E 'alerts (enabled|disabled)'`;
  5. a linha "O token nunca aparece" diz que ele fica só nas Environment Variables do `partqc-api` (e no painel do Render, só com a reserva ativa);
  6. se o aviso `alerts check stopped: a previous send is still running` aparecer por muitos minutos seguidos (o `abandoned_for_s` mostra há quanto tempo), **Restart** só do `partqc-api` (SEC-17-03).

### Parte B (ml-engineer)

#### 4.6 CHANGELOG: contagens por grau e avisos (RV-02 da SPEC-037)

`python -m qc_ml.report changelog` passa a conferir, antes de montar qualquer linha (junto com o `check_counts` de hoje):

- **`n_items_test_by_grade`**, quando presente e não vazio: tem de ser um objeto JSON cujas chaves são valores de `qc_contracts.Grade` e cujos valores passam em `is_valid_count`. Chave fora de `Grade`, ou campo que não é objeto → campo inválido `n_items_test_by_grade`; chave válida com valor inválido → `n_items_test_by_grade.<grade>`.
- **`warnings`**, quando presente: tem de ser uma lista de `str` sem nenhum caractere das categorias Unicode `Cc`, `Cf`, `Cs`, `Zl` e `Zp`. Campo que não é lista → `warnings`; item inválido → `warnings.<índice>` (a partir de 0).
- Em erro: código 2, **nada** no stdout e nada acrescentado ao arquivo do `--append`; a saída de erro tem uma linha por campo inválido, `report failed: invalid count in metrics.json: <campo>` para as contagens e `report failed: invalid warning in metrics.json: <campo>` para os avisos, na ordem acima, nunca o valor.
- `release-notes` não muda (não mostra esses campos). Um `metrics.json` válido gera a mesma entrada de hoje.

#### 4.7 Tipo já estendido nunca é "novo" (RV-03 da SPEC-016)

- `type_decision_problems` (e o cálculo dos tipos novos usado por ele) passa a considerar **não novo** todo tipo registrado em `test_extended_types` de qualquer `split_v<M>.json` anterior, além dos tipos com linha em algum split anterior. A CLI lê esses JSONs ao lado dos `split_v<M>.csv` que já lê. Um JSON anterior à SPEC-016 (sem a chave) conta como lista vazia; um JSON ausente, ilegível ou com a chave fora do formato (não lista de `str`) também conta como lista vazia, como no `recorded_deferred_types`.
- Consequência: `--extend-test-types <tipo>` para um tipo já estendido sai com 2 (`object type is not new: <tipo>`), sem gravar nada; sem as listas, as peças novas desse tipo seguem o ADR-014 (só treino e validação), como manda o ADR-022, decisão 5.
- A assinatura pública ganha só um parâmetro opcional, por nome, com padrão vazio (por exemplo, `extended_before: Collection[str] = ()`), para não quebrar as chamadas atuais.

#### 4.8 `ml/README.md` (RV-01 da SPEC-016)

Os dois exemplos de `python -m qc_ml.split` com `--defer-types` e `--extend-test-types` voltam a ter a continuação de linha (` \` e quebra) antes de cada uma dessas opções, como o exemplo do topo do mesmo README.

### Parte C (security-devops)

#### 4.9 Comentários de `env_file` e `infra/.env.dashboard` (RV-02 da SPEC-039)

- `infra/docker/api.Dockerfile` (linha 3) e `infra/docker/dashboard.Dockerfile` (linha 3): "pelo env_file do compose" passa a dizer que os segredos chegam em tempo de execução pelo `environment` do compose, com os valores das Environment Variables do recurso no Coolify (ADR-023), mantendo o `(R-03)`.
- `.streamlit/config.toml` (linha 3): "no infra/.env.dashboard (VPS)" passa a "nas Environment Variables do recurso `partqc-web` no Coolify (VPS, ADR-023)".
- Só comentários mudam. Nenhuma instrução, chave ou valor muda, e os comentários dos `.dockerignore` ficam como estão (O-02 da SPEC-039).

#### 4.10 `docs/deployment-plan.md`

- **Atualização com migração ou contrato novo (SEC-16-01, SEC-04 da 018).** Na §4, "Atualização", um bloco novo com o título `**Quando o merge traz migração nova ou contrato novo**`, com a ordem, numerada:
  1. merge (o webhook publica a API e o dashboard);
  2. logo depois (pode ser durante o build do deploy), na máquina do humano, num checkout atualizado da `main` e com o `.env.migrate`: `uv run --env-file .env.migrate --package qc-api python infra/migrate.py --status` (a migração nova aparece pendente), depois `uv run --env-file .env.migrate --package qc-api python infra/migrate.py` e de novo o `--status` (`0 pending`);
  3. se a migração cria tabela, a conferência de RLS e grants do passo 1, item 4, com a tabela nova;
  4. `curl -fsS https://<subdominio>/api/v1/health`: o `contract_version` é o da SPEC;
  5. só então atualizar a borda (e carregar um modelo com tipos novos);
  6. se alguma inspeção virou `dead` no caminho, `python -m qc_edge.requeue --outbox-path <arquivo>` (lista) e depois com `--yes` (SPEC-034).

  O bloco diz o efeito da janela entre os passos 1 e 2 (as rotas que usam o que a migração cria respondem 500 ou 422; por isso a borda é atualizada por último), que as migrações do projeto só acrescentam (colunas anuláveis, `check` que só aceitam mais, tabelas novas) e que uma migração que não seja só aditiva exige decisão na SPEC dela.
- **Respostas comprimidas (§4.1 e §4.5).** Um item novo na §7 (riscos aceitos): o proxy do Coolify aplica o middleware `gzip` e comprime quando o cliente pede; a borda e o laço de alertas pedem `Accept-Encoding: identity` e recusam outra codificação (`unsupported response encoding`, itens `pending`; `unsupported content encoding`, alerta não entregue), com as duas URLs do §1 desta SPEC e a data. E, na §4, "Atualização", na frase sobre atualizar o Coolify: repetir também o CA-18 desta SPEC (passos 1 a 3).
- **CDN (SEC-39-05).** No passo 3 da §4 (DNS) e num item novo da §7: anotar **fora do repositório** se o registro de `<subdominio>` passa por proxy de CDN. Recomendado: sem proxy (só DNS). Se passar, a chave de leitura (dashboard → API pelo `https://<subdominio>`) e a chave de dispositivo (borda → API) atravessam a CDN, que termina o TLS; fica como risco aceito só com essa anotação.
- **Alertas (SEC-17-03).** Na §8, item 5: se `alerts check stopped: a previous send is still running` aparecer por muitos minutos seguidos (o campo `abandoned_for_s` mostra há quantos segundos), **Restart** só do `partqc-api`.
- **CA manual (CA-18).** Uma subseção "CA manual da SPEC-040" na §9 e uma linha na tabela de CAs manuais, com os passos do CA-18 e a regra de colagem da §9.

### Tester

#### 4.11 Limpeza de testes de aceite antigos (RV-04 da SPEC-039, RV-05 da SPEC-030, observações 4 e 5 da SPEC-018)

Requisito desta SPEC (para a regra da `docs/architecture.md` §10), feito pelo tester e registrado na tabela do test-report:

- `infra/tests/acceptance/test_spec_015.py`: remover `PUBLIC_HOST_RE` e `_env_file_paths`, sem uso.
- `edge/tests/acceptance/test_spec_025.py`: o comentário `the name itself is printed raw (observation O-01 of the r1 test report)` passa a dizer que o nome sai escapado desde a SPEC-030 (§4.5 dela).
- `api/tests/acceptance/test_spec_004.py`: remover as constantes de módulo sem uso (`SPEC016_CONTRACTS`, `SPEC026_CONTRACTS` e outras do mesmo tipo que o `ALLOWED_EXACT` deixou de citar).
- `packages/contracts/tests/acceptance/test_spec_016.py`: a docstring de módulo deixa de dizer que o arquivo é o da SPEC vigente do `qc-contracts` e passa a citar só a versão que a SPEC-016 introduziu (0.4.0), como manda a §10.

Nenhuma asserção muda, nenhum `test_caNN_` é removido nem renomeado, e o reviewer confere no diff.

## 5. Critérios de aceite

### Parte A

Contexto comum dos CA-01 a CA-03: nuvem falsa com `httpx.MockTransport` (que passa pelos decodificadores do `httpx`, como a rede), chave e marcadores gerados com `secrets` no teste, relógio monotônico falso, SQLite real em `tmp_path` e idempotência por `inspection_id` como na SPEC-009 §5. "Bomba gzip" = corpo `gzip` de cerca de 127 KiB que descomprime para 128 MiB; "bomba empilhada" = corpo com `Content-Encoding: gzip, gzip` que descomprime para 128 MiB, ambos gerados em blocos pelo teste.

- **CA-01 (security, SEC-30-01)** — *Dado* um `HttpPublisher` com a nuvem falsa respondendo normalmente, *quando* `publish_batch`, `send_heartbeat` e `check_health` rodam, *então* cada uma das 3 requisições capturadas tem o header `Accept-Encoding` com valor exatamente `identity`.
- **CA-02 (security, SEC-30-01)** — *Dado* a nuvem falsa respondendo ao `publish_batch`, em casos separados, (a) 200 com a bomba gzip, (b) 200 com a bomba empilhada, (c) 200 `Content-Encoding: deflate`, (d) 200 `Content-Encoding: br`, (e) 200 `Content-Encoding: GZIP`, (f) 200 `Content-Encoding: identity, gzip` e (g) 422 com a bomba gzip; e ao `send_heartbeat` (h) 204 `Content-Encoding: gzip` e (i) 422 com a bomba gzip, *quando* cada chamada roda, *então* levanta `PublishTransientError` com a mensagem exatamente `unsupported response encoding` (nunca `PublishRejectedError`), o pico do `tracemalloc` medido só durante a chamada fica abaixo de 8 MiB, e a chave não aparece na mensagem.
- **CA-03 (security, R-05, SEC-30-01)** — *Dado* respostas 200 com o `BatchResult` válido e, em casos separados, sem `Content-Encoding`, com `identity` e com `Identity`, *quando* `publish_batch` roda, *então* devolve um `PublishResult` por item, como hoje. *Dado* um outbox com 2 itens `pending` e a nuvem respondendo ao primeiro lote com a bomba gzip e aos seguintes sem codificação, *quando* `run_once` roda até `stats().pending == 0` (no máximo 10 ciclos), *então* os 2 itens ficam `sent`, a nuvem tem cada `inspection_id` exatamente uma vez, o log tem `unsupported response encoding` e não tem a chave, e nenhum item passou por `dead`.

Contexto comum dos CA-04 e CA-05: `DATASET_DIR` em `tmp_path`, imagens geradas pelo Pillow (nunca fotos reais, R-14), "JPEG com EXIF" = JPEG 64×64 com APP1 `Make = M`. Os casos com modo `0o000`/`0o600` são pulados com `os.geteuid() == 0` e restauram os modos no fim.

- **CA-04 (security, R-14, SEC-30-02)** — *Dado* `raw/screw/fair/S-001__0__20261022T141503Z.jpg` limpo, `raw/nut/good/` com modo `0o000` contendo `N-001__0__20261022T141503Z.jpg` (JPEG com EXIF), `raw/other/fair/` com modo `0o600` contendo `O-001__0__20261022T141503Z.jpg` (JPEG com EXIF) e, em outro caso, uma subpasta `raw/screw/a\nb/` com modo `0o000`, *quando* `python -m qc_edge.privacy --dataset-dir <D>` roda, com e sem `--fix`, *então* o código é 1; o stdout tem as linhas `raw/nut/good: unreadable` e `raw/other/fair/O-001__0__20261022T141503Z.jpg: unreadable` (no outro caso, `raw/screw/a\x0ab: unreadable`, escapada, numa única linha), em ordem crescente de caminho, e termina com `checked 1 images, 0 with private data`; o log tem um `ERROR` `cannot read` para cada uma; e nenhum arquivo muda. *Dado* os modos restaurados, *então* a varredura sem `--fix` sai com 1 e lista as duas imagens com achado. *Dado* `DATASET_DIR` sem `raw/`, *então* o código é 0, o stdout é só `checked 0 images, 0 with private data`, sem `unreadable`.
- **CA-05 (security, R-14, SEC-30-04)** — *Dado* em `raw/screw/fair/`, além de uma imagem limpa, cada um destes arquivos com os bytes de um JPEG com EXIF: (a) um criado por `tempfile.mkstemp(dir=<pasta>, prefix=".S-001__0__20261022T141503Z.jpg.", suffix=".tmp")`, (b) `.tmp`, (c) `.x.tmp`, (d) `.S-001.jpg.ABCDEFGH.tmp`, (e) `.S-001.jpg.abcdefg.tmp` (7 caracteres), (f) `.notas.txt.abcdefgh.tmp` e (g) `.S-001.JPG.abcdefgh.tmp`, *quando* a varredura roda sem `--fix`, *então* (a) e (g) não aparecem no stdout nem contam em `checked`; (b) a (f) aparecem, cada um, como `<caminho>: invalid`; e o código é 1. *Dado* só a imagem limpa e o arquivo (a), *então* o código é 0 e o resumo é `checked 1 images, 0 with private data`.
- **CA-06 (security, R-03, RV-03 e RV-04 da 018)** — *Dado* um `HeartbeatLoop` com um `sink` cujo `stats()` levanta `RuntimeError(M)` (`M` gerado no teste) e um publisher espião, *quando* `run_once` roda, *então* não levanta, o publisher não é chamado, há exatamente um registro `ERROR` com a mensagem `heartbeat could not be built: RuntimeError` e `exc_info` nulo, e nem `M` nem `Traceback` aparecem no texto capturado do log. *E* `typing.get_type_hints(qc_edge.heartbeat._cap) == {"value": float, "return": int}` e `_cap(12.9) == 12`.

Contexto comum dos CA-07 e CA-08: o do CA-02 da SPEC-029 (`AppTest` da Visão geral, `READ_API_KEY` gerada no teste, `httpx.HTTPTransport.handle_request` e `socket.getaddrinfo` espionados, handler no logger raiz, `st.secrets` isolado). As 5 URLs = `https://api.exa​mple.org`, `https://api.exa­mple.org`, `https://api.example.org x`, `https://api.exa mple.org` e `https://xn--zz.com`.

- **CA-07 (security, SEC-29-01)** — *Dado* cada uma das 5 URLs, *quando* `is_secure_api_url` roda, *então* devolve `False`; *quando* a Visão geral roda com ela em `API_BASE_URL`, *então* `at.exception` está vazio, a página mostra `INSECURE_API_URL_MESSAGE`, há 0 requisições e 0 consultas de DNS, e a chave não aparece na árvore da página nem no log. *Dado* `https://api.example.org`, `https://api.example.org:8443/base`, `http://localhost:8001`, `http://127.0.0.1:8001` e `https://bücher.example.org`, *então* `is_secure_api_url` devolve `True` para cada uma.
- **CA-08 (security, SEC-29-01, defesa em profundidade)** — *Dado* `is_secure_api_url` substituído no teste por uma função que sempre devolve `True` e `API_BASE_URL` igual, em casos separados, a `https://xn--zz.com` e a `https://api.exa​mple.org`, *quando* `get_client()` e depois uma leitura do cliente rodam, *então* uma das duas levanta `InsecureApiUrlError`, há 0 requisições e 0 consultas de DNS, e nem a URL nem a chave aparecem na mensagem. *Dado* `API_BASE_URL` válido e o transporte falso respondendo 200 com o corpo `not json`, *quando* a mesma leitura roda, *então* a exceção é a de hoje para resposta inválida, e não `ConfigError`.

Contexto comum dos CA-09 e CA-10: o dos testes da SPEC-017 (`AlertConfig` válida com token gerado por `secrets`, transporte falso ou servidor local em `127.0.0.1`, banco `partqc_test` com a `005`, carta com lotes fora de controle concluídos, nenhuma chamada ao Telegram real).

- **CA-09 (security, R-03, SEC-17-02)** — *Dado* `send_message` com o transporte falso, *quando* roda, *então* a requisição capturada tem `Accept-Encoding: identity`. *Dado* o transporte respondendo 200 com `{"ok": true}` e, em casos separados, (a) `Content-Encoding: gzip` (o JSON comprimido), (b) a bomba empilhada da Parte A, (c) `deflate` e (d) `br`, *então* `send_message` devolve `False`, o log tem `telegram send failed: unsupported content encoding (status=200)`, o pico do `tracemalloc` durante a chamada fica abaixo de 8 MiB e o token (inteiro e a parte depois de `:`) não aparece no log. *Dado* 200 com `{"ok": true}` sem `Content-Encoding` e com `identity`, *então* devolve `True`. *Dado* um lote candidato e o caso (a), *quando* `run_check` roda, *então* a linha do lote em `alerts_sent` fica com `delivered = false`, e uma segunda verificação não manda nova requisição para ele.
- **CA-10 (security, R-03, SEC-17-03)** — *Dado* dois lotes candidatos e um servidor local que goteja os cabeçalhos (como no `test_extra_total_timeout_with_slow_headers` da SPEC-017), *quando* `run_check` roda uma vez, *então* o primeiro envio termina com `telegram send failed: deadline exceeded`; há exatamente um `WARNING` que casa com `^alerts check stopped: a previous send is still running \(abandoned_for_s=(\d+), lot_id=([^,]+), source=(live|simulated)\)$`, com `abandoned_for_s` entre 0 e 3 e `lot_id`/`source` do candidato que não foi reservado; `alerts_sent` tem 1 linha (a do primeiro, `delivered = false`); e o token não aparece no log. O teste espera a thread abandonada terminar no fim.
- **CA-11 (READMEs; R-03)** — *Dado* `api/README.md`, *então* ele não contém `infra/.env.api`, `sed -n` nem `compose -f infra/compose.yaml`; contém `partqc-api`, `docker exec`, `printenv TELEGRAM_BOT_TOKEN`, `-K <(`, `unset t`, `deployment-plan.md`, `abandoned_for_s` e `Restart`; e nenhuma linha dos blocos `bash` passa o token como argumento (a mesma regra do `test_extra_docs_never_put_the_token_in_argv` da SPEC-017: o token só aparece dentro de `$t` usado no `printf` de um `<(...)`). *Dado* `edge/README.md`, *então* ele contém `Accept-Encoding: identity`, `unsupported response encoding` e, na seção da varredura de privacidade, `unreadable` e `subpasta`.

### Parte B

Contexto comum dos CA-12 a CA-14: o do gerador sintético das SPECs 016 e 037 (`metrics.json` válido gerado no teste, sem torch), `python -m qc_ml.report` e `python -m qc_ml.split` pela CLI em `tmp_path`.

- **CA-12 (security, RV-02 da 037, contagens)** — *Dado* um `metrics.json` válido e um `CHANGELOG.md` com conteúdo, e em casos separados `n_items_test_by_grade` igual a (a) `{"good": -1}`, (b) `{"good": "3\n## forjado"}`, (c) `{"good": 2.0}`, (d) `{"good": true}`, (e) `{"bad\nkey": 1}` e (f) `["good", 1]`, *quando* `python -m qc_ml.report changelog --model-dir <M> --append <CHANGELOG.md>` roda, *então* o código é 2, o stdout está vazio, o `CHANGELOG.md` tem os mesmos bytes, a saída de erro tem a linha `report failed: invalid count in metrics.json: n_items_test_by_grade.good` (a a d) ou `report failed: invalid count in metrics.json: n_items_test_by_grade` (e, f), e nem `forjado` nem `bad` aparecem nela. *Dado* `{"good": 2, "fair": 0}`, *então* o código é 0 e a entrada tem `Peças no teste por grau: good: 2, fair: 0.`
- **CA-13 (security, RV-02 da 037, avisos)** — *Dado* o mesmo começo e `warnings` igual a (a) `["ok", "linha\n## forjada"]`, (b) `["a\rb"]`, (c) `["a b"]`, (d) `["a\u001b[31m"]`, (e) `["a‮b"]`, (f) `[3]` e (g) `"texto"`, *quando* o `changelog` roda com `--append`, *então* o código é 2, o stdout está vazio, o arquivo tem os mesmos bytes e a saída de erro tem `report failed: invalid warning in metrics.json: warnings.1` (a), `...: warnings.0` (b a f) ou `...: warnings` (g), sem `forjada`. *Dado* `["few test items for pliers: 1", "acentuação ok"]`, *então* o código é 0 e a entrada tem as linhas `- few test items for pliers: 1` e `- acentuação ok`.
- **CA-14 (R-11, RV-03 da 016)** — *Dado* um `split_v1` sem ferramentas e um `split_v2` gerado com `--extend-test-types pliers` (3 peças `T-` de `pliers`, não externas, com peças no teste), depois todas as imagens de `pliers` do manifest registradas em `exclusions.csv` (e apagadas) e 3 peças `T-` novas de `pliers` acrescentadas, *quando* `python -m qc_ml.split ... --extend-test-types pliers` roda, *então* o código é 2, a saída de erro tem `object type is not new: pliers`, e nenhum `split_v3.*` é gravado. *Quando* roda sem as listas, *então* o código é 0, o `split_v3.csv` é gravado, nenhuma imagem das 3 peças novas de `pliers` está em `test`, e toda imagem que está em `split_v1` ou `split_v2` e continua no manifest mantém o split. *Dado* o mesmo cenário com o `split_v2.json` sem a chave `test_extended_types`, *então* o comportamento é o de hoje (o tipo volta a ser novo), sem erro de leitura.
- **CA-15 (RV-01 da 016)** — *Dado* `ml/README.md`, *então* nos blocos de código cada ocorrência de `--defer-types` e de `--extend-test-types` numa linha que continua um `python -m qc_ml.split` começa a linha (depois dos espaços iniciais), a linha anterior termina com ` \`, e nenhuma linha que contém `python -m qc_ml.split` tem dois espaços seguidos depois do primeiro caractere não branco.

### Parte C

- **CA-16 (R-03, RV-02 da 039)** — *Dado* `infra/docker/api.Dockerfile`, `infra/docker/dashboard.Dockerfile` e `.streamlit/config.toml`, *então* o bloco de comentários do topo de cada um (as linhas iniciais que começam com `#`) não contém `env_file`, `.env.dashboard` nem `.env.api` e contém `Coolify`; e as linhas que não são comentário são idênticas às do início da rodada (copiadas literalmente no teste).
- **CA-17 (deploy, SEC-16-01, SEC-39-05, SEC-17-03, SEC-30-01)** — *Dado* `docs/deployment-plan.md`, *então*: ele contém `**Quando o merge traz migração nova ou contrato novo**`, e o trecho depois desse título, até o próximo título, contém `infra/migrate.py --status`, `0 pending`, `contract_version`, `qc_edge.requeue` e `--yes`, com `migrate.py --status` antes de `contract_version` e `contract_version` antes de `qc_edge.requeue`; contém `CDN` e `SEC-39-05`; contém `abandoned_for_s` e `Restart`; contém `Accept-Encoding: identity`, `unsupported response encoding`, `https://coolify.io/docs/knowledge-base/proxy/traefik/custom-middlewares` e `https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/compress/`; e contém `CA manual da SPEC-040`.
- **CA-18 (manual, VPS e borda)** — Depois do deploy desta SPEC pela `main` (§4, "Atualização" do plano), com a borda de produção atualizada:
  1. na VPS, com a chave de leitura tirada do ambiente do contêiner do dashboard (`k=$(docker exec <contêiner do dashboard> printenv READ_API_KEY)`) e entregue ao `curl` por descritor (`-K <(printf 'header = "X-API-Key: %s"\n' "$k")`), `curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip' 'https://<subdominio>/api/v1/inspections?limit=100'`: registrar se aparece `content-encoding: gzip` (esperado com o middleware do Coolify e corpo acima de 1 KB);
  2. o mesmo com `-H 'Accept-Encoding: identity'`: nenhuma linha `content-encoding` (ou só `identity`); `unset k` no fim;
  3. no notebook da borda, fazer 3 inspeções com a nuvem no ar: em até 2 min as 3 aparecem no Histórico do painel, o log do `qc-edge` não tem `unsupported response encoding`, e a página "Dispositivos" mostra o gateway `online`;
  4. registrar as saídas no dev-report e na §9 do plano, com o subdomínio trocado por `<subdominio>` e sem a chave. Se o passo 2 mostrar `content-encoding: gzip`, parar, voltar a borda à versão anterior e registrar `SPEC_ISSUE` (o proxy ignora `identity`).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor, Parte A) | Header `identity` no cliente; conferência de `Content-Encoding` (vazio, `identity`, maiúsculas, lista, múltiplos headers) nos dois métodos; travessia com `onerror` e `lstat` falho; padrão dos temporários (contra o `write_private_file_atomically` real); log do heartbeat; validação do host no painel e conversão na montagem; `_post` com codificação; idade do envio abandonado | `edge/tests/`, `dashboard/tests/`, `api/tests/` |
| Unitário (autor, Parte B) | Conferência de `n_items_test_by_grade` e `warnings`; leitura de `test_extended_types` dos JSONs anteriores (com e sem a chave, JSON ausente) | `ml/tests/` |
| Unitário (autor, Parte C) | Se preciso, texto dos comentários e do plano | `infra/tests/` |
| Aceite (tester) | Um por CA automatizável | `edge/`, `dashboard/`, `api/`, `ml/` e `infra/tests/acceptance/test_spec_040.py` (§3.1) |
| Manual (humano) | CA-18, na VPS e na borda | descrito no CA |

- **Mocks:** só fronteiras: a nuvem e o Telegram (`httpx.MockTransport` ou servidor local em `127.0.0.1`), o DNS (`socket.getaddrinfo` espionado), o relógio monotônico. O CA-08 substitui `is_secure_api_url` de propósito, para exercitar a defesa em profundidade. Nenhum teste usa a VPS, o Coolify, a rede externa nem o Telegram real.
- **Banco:** os CA-09 e CA-10 usam o `partqc_test` (`db`, `CI=true` com `TEST_DATABASE_URL`), como os testes da SPEC-017.
- **Ordem da rodada:** developer (Parte A) → ml-engineer (Parte B) → security-devops (Parte C) → tester → reviewer → portão de segurança. Cada autor faz commits só nos caminhos da própria parte e acrescenta a sua seção no `reviews/SPEC-040/r<N>-dev-report.md` (`## Parte A (developer)`, `## Parte B (ml-engineer)`, `## Parte C (security-devops)`), sem mudar as outras.
- **Portão de segurança (R-07):** um único `reviews/SPEC-040/r<N>-security-report.md` com duas seções: `## Partes A e B (security-devops)` e `## Parte C (reviewer)`, como na SPEC-038. Cada um só escreve a própria seção, e o veredicto é PASS só com as duas PASS.

## 7. Riscos e notas para o implementador

- **Ordem importa no publisher:** mandar `identity` sem recusar não fecha o SEC-30-01 (um servidor hostil ignora o header), e recusar sem mandar `identity` quebraria o envio na VPS, porque o Traefik do Coolify comprime quando o cliente pede (§1). Os dois juntos, e o CA-18 confere o caminho real. Se uma configuração futura do proxy comprimir mesmo com `identity` (`defaultEncoding`), o envio falha de forma transitória e audível (`unsupported response encoding`), os itens ficam `pending` e nada se perde; por isso o plano manda repetir o CA-18 depois de atualizar o Coolify.
- **Conferir antes do corpo:** a decodificação do `httpx` acontece no `iter_bytes`; conferir o header depois de ler o primeiro bloco não adianta.
- **`os.walk` e o `onerror`:** o erro chega como `OSError` com o caminho absoluto em `filename`; a linha usa o caminho relativo a `D`. Um `FileNotFoundError` do próprio `raw/` não é `unreadable` (`raw/` ausente continua 0).
- **Temporários:** o `--fix` grava pelo mesmo `write_private_file_atomically`, com o nome original do arquivo (que pode terminar em `.JPG` ou `.jpeg`); por isso o alvo do padrão é conferido com `is_jpeg_name`, e não com `.jpg` literal.
- **Painel:** o `httpx` codifica o host com o pacote `idna` só na montagem da requisição; a conferência tem de montar a requisição (sem enviá-la). Nada de rede no `is_secure_api_url`.
- **Alertas:** a estrutura de `_abandoned_sends` muda (instante do abandono); os testes do autor que a inspecionam (`api/tests/test_alerts_deadline.py`) são ajustados pelo próprio developer.
- **Split:** a leitura dos JSONs anteriores não pode mudar nenhuma atribuição antiga nem a regra do `split_v1` (sem listas).
- **Merge com o webhook:** cada merge na `main` publica na VPS. Nenhum merge desta SPEC na véspera nem no dia da apresentação (decisão do humano de 2026-10-25); o ideal é o merge antes do ensaio do M4 (29/11), para o ensaio validar a borda com a §4.1.
- **Até esta SPEC entrar:** continua valendo, antes de cada backup do dataset, a conferência de permissões do `docs/dataset-protocol.md` §8, passo 1.

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED + security-report PASS nas duas seções (Partes A e B pelo security-devops, Parte C pelo reviewer)
- [ ] CI verde; `ruff` limpo; cobertura de `qc_api.services` ≥ 80% (RNF-09)
- [ ] `edge/README.md`, `api/README.md`, `ml/README.md` e `docs/deployment-plan.md` atualizados; notas "a partir da SPEC-040" em `docs/architecture.md` §4, §6.2 e §6.3 (architect)
- [ ] CA-18 (manual) registrado
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## 9. Perguntas para a aprovação (humano)

1. **Respostas comprimidas (§4.1 e §4.5):** manter a mudança no publisher e nos alertas antes da apresentação, sabendo que o proxy do Coolify comprime quando o cliente pede e que o CA-18 manual confere o caminho real? A alternativa é deixar o SEC-30-01 e o SEC-17-02 para depois da entrega, como risco aceito (exigem a própria API comprometida ou um certificado válido). **Recomendação do architect:** manter. A correção é pequena, falha fechada sem perder inspeções, e hoje o envio já recebe respostas comprimidas sem teto real.
2. **Datas de `devices` (RV-02 = SEC-02 da SPEC-018):** deixar fora, como está, ou acrescentar uma migração `006` com a faixa da `002` (`>= 0001-01-01` e `< 10000-01-01`) nas colunas de data de `devices`? **Recomendação do architect:** fora. Só uma escrita direta no banco produz o caso, e a migração acrescenta um passo de deploy antes da apresentação.
3. **Prazo:** aceitar a posição `016 → 018 → 017 → 038 → 040 → portão da Fase 3`, com o merge até o ensaio do M4 (29/11) e, se não couber, a SPEC fica para depois da entrega (sem merge nos dois dias antes da apresentação)? **Recomendação do architect:** sim. Nenhuma pendência daqui bloqueia a demo; a que mais pesa (§4.1) é melhor validada no ensaio.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-26 | SPEC criada (`Draft`). Decisões do architect: (a) `Accept-Encoding: identity` **e** recusa de `Content-Encoding` antes do corpo no publisher e no Telegram, porque o proxy do Coolify comprime quando o cliente pede (fato conferido nas fontes do §1) e só recusar quebraria o envio (§4.1, §4.5); (b) subpasta e arquivo ilegíveis viram `unreadable` com código 1, e os temporários só no formato exato do `mkstemp` (§4.2); (c) heartbeat registra só a classe ao falhar a montagem (§4.3); (d) o painel recusa a URL que o `httpx` não monta, com conversão em `InsecureApiUrlError` na construção e na montagem (§4.4); (e) aviso do envio abandonado com `abandoned_for_s`, mantendo o risco aceito do SEC-17-03 (§4.5); (f) `api/README.md` sem `infra/.env.api` nem checkout na VPS, com o `docker exec … printenv` do plano de deploy (§4.5); (g) CHANGELOG confere `n_items_test_by_grade` e `warnings` (§4.6); (h) tipo já estendido nunca é novo (§4.7); (i) ordem de migração, API e borda e nota de CDN no plano (§4.10); (j) limpeza de aceites antigos pelo tester (§4.11); (k) **ficam fora** o SEC-30-03, o RV-01/RV-02 e o SEC-01 da 018, o RV-02/RV-03 e o SEC-29-02 da 029, o RV-02/RV-04 da 016, o SEC-16-02 e as observações dos portões da 017 (§3.2); o RV-01 da 031 e o SEC-17-01 já estavam resolvidos, e o SEC-39-06 está na SPEC-038. Três partes (developer, ml-engineer, security-devops), com o portão de segurança dividido (§6). Feito junto: `docs/dataset-protocol.md` §8, passo 1 (RV-04 da 030). | Blocos "Pendências da SPEC-029/030/031/037/039" de `docs/plan.md` §3; relatórios das SPECs 016, 017 e 018 lidos nas worktrees das branches delas (`reviews/SPEC-016/r1-*`, `reviews/SPEC-017/r2-*`, `reviews/SPEC-018/r1-*`); `reviews/SPEC-039/r1-review-report.md` e `r2-*`; `reviews/SPEC-038/r1-dev-report.md` (RV-02 da 039 fora da 038) | Orquestrador, a pedido do humano (projeto inteiro autorizado, testes de segurança e qualidade em tudo) |
