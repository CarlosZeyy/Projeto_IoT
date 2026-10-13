# SPEC-007 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-007](../../docs/specs/SPEC-007-edge-gateway-captura.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...b61d560` (36 arquivos) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante ou alto. Há 1 achado médio (SEC-01, DNS rebinding no console), que não bloqueia este merge, mas precisa estar resolvido **antes do merge da SPEC-009**. Os outros são baixos ou informativos. A decisão sobre o RV-01 (custo medido por slot) está na seção "Decisão sobre o RV-01".

## Superfície analisada

- **Rotas** (`edge/src/qc_edge/app.py`):
  - `GET /` (console, só loopback e sem headers de proxy);
  - `GET /capture?t=` (página do celular);
  - `/static/*`;
  - `POST /api/capture` e `GET /api/status` (`X-Session-Token`).
  - Conferi também que `/docs`, `/redoc` e `/openapi.json` estão desligados.
- **Token de sessão** (`security.py`, `config.py`, `cli.py`): geração, comparação, exposição no QR e no console, log, histórico e `Referer`.
- **Entradas:**
  - `middleware.py`: `Content-Length` e corpo chunked;
  - `read_capture_form`: token antes do parse, `max_files=1`, `max_fields=16`, 413 do campo e 422 com `fullmatch`;
  - `limits.py`: sondagem, 4 M pixels e `load_image`;
  - limitador (`BoundedSemaphore`).
- **Flag `LOAD_TRUNCATED_IMAGES`:** `lifespan`, `cli.main` e `load_capture_image`; o CA-25 faz a verificação estática.
- **R-02 e R-14:** gravação em `EDGE_DATA_DIR/captures/`, rotas que poderiam servir fotos, imports de cliente HTTP e o objeto entregue ao sink.
- **Rede:** bind (`EDGE_HOST`), `proxy_headers=False`, firewall e hotspot do `edge/README.md`.
- **Dependências:** `pydantic-settings>=2` no `qc-edge`. Nenhum pacote novo foi resolvido no `uv.lock`.

### O que rodei (só leitura; scripts e diretórios temporários no scratchpad, fora do repositório)

- `uv run pytest -q edge/tests` → **252 passed**.
- **Medição do pior caso por slot** (RV-01), com 9 entradas hostis dentro dos limites da rota, cada uma num processo novo para medir o pico de RSS.
- **Servidor real** (`qc-edge --stub-model`, só em `127.0.0.1`, porta livre, `EDGE_DATA_DIR` temporário, processo encerrado no fim):
  - travessias de caminho;
  - headers de proxy;
  - header `Host` estranho;
  - carga de 2, 6 e 45 inundações simultâneas;
  - busca do token no log.
- **O mesmo servidor com `EDGE_HOST=::`** (RV-03).
- **`pip-audit`** sobre os 28 pacotes do `uv export --package qc-edge`.
- Os tokens foram gerados em tempo de execução (`secrets.token_urlsafe`), sem literal.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 | **média** (não bloqueia esta SPEC; prazo: antes do merge da SPEC-009) | auth | `edge/src/qc_edge/app.py:469-491` e `507-512` (`console`, `_is_local_console_request`) | **O console não valida o header `Host`, o que permite DNS rebinding.** Medido no servidor real: `GET /` vindo de `127.0.0.1` com `Host: attacker.example:<porta>` responde **200 com o token no corpo**. Cenário: enquanto o `qc-edge` roda, o operador abre no navegador do notebook uma página hostil cujo domínio é "religado" para `127.0.0.1`. A página passa a ter a mesma origem que o console, lê o token e, ainda na mesma origem, pode chamar `POST /api/capture` e `GET /api/status`. Com isso, injeta inspeções falsas. Hoje elas param no `InMemorySink`. A partir da SPEC-009, subiriam para a nuvem como `source=live`, com o modelo real (SPEC-008), e contaminariam o SPC. As fotos **não** vazam, porque nenhuma rota as serve (R-02 intacto). A checagem de loopback e de headers de proxy do §4.4 não pega esse caso, porque a conexão vem mesmo do loopback. A proteção do navegador contra acesso a rede local depende do navegador e da versão, então não dá para contar com ela. | **Architect, mudança de SPEC** (o §4.4 lista as condições exatas do console, e os testes do CA-13 usam o `Host` padrão do cliente de teste). Proposta: o console só responde se o `Host` for `127.0.0.1:<porta>`, `localhost:<porta>` ou `[::1]:<porta>`; senão, 403. Opcionalmente, as rotas com token também aceitam só os IPs de `detect_lan_ips()` e esses nomes de loopback. Pode entrar como emenda da SPEC-008 ou numa SPEC de manutenção da borda. Precisa estar `Done` **antes do merge da SPEC-009**, que é quando dado injetado chega à nuvem. Acrescentar a linha à tabela do `architecture.md` §9. |
| SEC-02 | baixa (aceito; segue para o architect só como atualização de números) | input / DoS | SPEC §4.6, 2º item do "Dimensionamento"; `docs/architecture.md` §9; `edge/src/qc_edge/limits.py:62-101` | **RV-01: o custo medido por slot é ~4 s de CPU e ~90 MB acima da base (pico de 133 MB no processo), contra ~1,4 s e ~110 MB estimados.** Detalhes e decisão na seção "Decisão sobre o RV-01". | Nada no código. O architect atualiza a §4.6 e o `architecture.md` §9 com os valores medidos (inclusive o efeito do GIL). Opcional, depois do passo 6 do CA-20: baixar o `CAPTURE_MAX_BYTES` (o custo cai de forma linear). |
| SEC-03 | baixa (aceito; segue para o architect, SPEC-010) | DoS | `edge/src/qc_edge/app.py:425-437` | **RV-02: as capturas que esperam slot ocupam threads do threadpool (limite de 40), que é compartilhado com o console, o `/api/status` e o `/capture`.** Medido com os padrões (2 slots, 10 s) e 45 inundações simultâneas: `/api/status` em **1,97 s** (0,3–0,4 s com 2 a 6 inundações). A captura legítima recebe 503 `server busy` em **18,7 s**, e não nos 10 s esperados, porque também espera uma thread livre. A degradação tem limite (`decode_wait_s` mais a fila do pool) e exige o token. É a "consequência aceita" da §4.6, estendida às outras rotas síncronas. | Aceito nesta SPEC. Quando a SPEC-010 reutilizar o limitador no modo coleta, o architect avalia esperar o slot fora do threadpool (`anyio.Semaphore` na dependência assíncrona, com a decodificação depois despachada para a thread) ou `limit_concurrency` no uvicorn. Atualizar o texto da "consequência aceita" na §4.6 para citar o console e o `/api/status`. |
| SEC-04 | informativa (reclassificado: sem impacto de segurança) | deploy / config | `edge/src/qc_edge/config.py:162-169`; `edge/README.md:30`; `edge/src/qc_edge/cli.py:284-295` | **RV-03, conferido no servidor real: com `EDGE_HOST=::`, o uvicorn (via asyncio) abre o socket com `IPV6_V6ONLY` e não aceita IPv4.** Isso vale mesmo com `net.ipv6.bindv6only=0` nesta máquina. `http://127.0.0.1:<porta>/` recebe *connection refused*, e `http://[::1]:<porta>/` responde 200. Pela CLI, então, o `::ffff:127.0.0.1` nunca chega ao app. A falha é fechada nos dois casos: um socket dual-stack daria 403, e o `::` não aceita IPv4. O problema é funcional: com `::`, a URL do log não abre e o celular, que usa o IPv4 do QR, não conecta. | Não bloqueia. Para o architect, junto da próxima SPEC da borda (SPEC-008): escolher entre restringir `EDGE_HOST` a IPv4 ou acrescentar ao `edge/README.md` "com `::`, só IPv6: o console abre em `http://[::1]:<porta>/` e o celular precisa de IPv6; use `0.0.0.0`". Aceitar o IPv4 mapeado **não** é necessário. |
| SEC-05 | baixa | deploy / rede | `edge/README.md:62-105` | **As regras de firewall abrem a porta 8000 para qualquer origem e interface,** inclusive a Wi-Fi do campus, se o notebook estiver nela. Valem `ufw allow 8000/tcp` e `firewall-cmd --add-port` na zona ativa, que costuma ser `public`. O `--permanent` mantém a porta aberta depois da sessão. O bind padrão `0.0.0.0` também escuta nas bridges do Docker (RV-04). O token mitiga, e sem ele nada é decodificado (o 401 vem antes do parse do corpo, conferido). | Documentação, para a próxima SPEC que tocar o `edge/README.md` (SPEC-008, via architect): (a) restringir a regra à sub-rede da LAN ou do hotspot, ex.: `sudo ufw allow from 192.168.x.0/24 to any port 8000 proto tcp` e `firewall-cmd --zone=<zona da interface>`; (b) preferir a regra só de runtime e desfazê-la ao fim da sessão; (c) não rodar o `qc-edge` com a porta aberta numa rede que não seja da dupla. |
| SEC-06 | baixa | privacy (R-14) | `edge/src/qc_edge/app.py:201-216` | **As fotos são gravadas com as permissões do umask** (aqui, `0644` nos arquivos e `0755` nos diretórios). Qualquer outra conta local do notebook pode lê-las. Também não há política de retenção: as fotos se acumulam em `captures/`. O notebook é de uso pessoal, e as fotos não saem da máquina, então o R-02 está cumprido. | Para o architect, junto da SPEC-010 (que grava o dataset) ou numa SPEC de manutenção: criar `captures/` (e o `DATASET_DIR`) com `0700` e os arquivos com `0600`, e documentar no `docs/dataset-protocol.md` a retenção e a limpeza das fotos de inspeção (R-14). |
| SEC-07 | informativa | secrets | `edge/README.md:21` e `32`; `.env.example` | **Exposição do token por desenho:**<br>• o QR e a URL em texto ficam no console;<br>• a URL `?t=` fica no histórico do navegador do celular;<br>• um `EDGE_SESSION_TOKEN` fixo sobrevive aos reinícios.<br>Os controles estão certos:<br>• `Cache-Control: no-store`, `Referrer-Policy: no-referrer` (header e meta) e nenhum recurso externo;<br>• o access log está desligado e o log foi conferido (148 linhas do servidor real, sem o token);<br>• `SecretStr` e `hide_input_in_errors`;<br>• `compare_digest` sobre bytes, com teto de 512 caracteres;<br>• `token_urlsafe(32)`, ou seja, 256 bits. | Sem correção de código. Recomendações operacionais, que podem ir para o `edge/README.md` na SPEC-008: (a) deixar `EDGE_SESSION_TOKEN` vazio, para que um token novo seja gerado a cada subida; (b) **não projetar o console** na apresentação, ou reiniciar o `qc-edge` depois disso; (c) hotspot sempre com senha WPA2/WPA3, já pedida no Plano B. |

## Verificações específicas pedidas

### Token de sessão

- **Geração:** `secrets.token_urlsafe(32)` (43 caracteres, 256 bits), ou `EDGE_SESSION_TOKEN` com no mínimo 32 caracteres (`SecretStr`).
- **Comparação:** `secrets.compare_digest` sobre bytes. Valor ausente, vazio ou com mais de 512 caracteres é recusado antes. Não ASCII dá 401, e não 500 (test-report).
- **Rotas protegidas:** `/api/capture`, `/api/status` e `/capture`. No `/api/capture`, o token é conferido **antes** do parse do multipart (`read_capture_form`). Sem token, nenhum byte do corpo é decodificado.
- **QR e console:** o token só aparece no console de loopback. Ver SEC-01 (DNS rebinding) e SEC-07.
- **Log:** sem token (CA-19, e conferi de novo no servidor real). O aviso de argumentos desconhecidos lista só os nomes das opções (`9f344f1`).
- **Histórico e `Referer`:** `no-referrer` e `no-store`. O histórico do celular guarda a URL (SEC-07).

### Console

- **Origem:** `request.client.host ∈ {127.0.0.1, ::1}`, sem `X-Forwarded-For`, `Forwarded` nem `CF-Connecting-IP`, e uvicorn com `proxy_headers=False`. No servidor real, o `X-Forwarded-For` deu 403 sem o token no corpo.
- **`X-Real-IP`:** não está na lista e não precisa, porque com `proxy_headers=False` o uvicorn não usa nenhum header para o endereço do cliente.
- **`?ip=`:** só é aceito se estiver na lista detectada.
- **Escape:** `html.escape` em todos os campos. O `capture.js` só usa `textContent`.
- **Lacuna:** o header `Host` (SEC-01).

### Limites e limitador

- **Sem token:**
  - `Content-Length` acima de 3,5 MiB → 413 antes de ler o corpo;
  - abaixo disso → 401 antes do parse. O custo é desprezível.
- **Com token:**
  - campo `image` acima de 3 MiB → 413;
  - corpo chunked contado no middleware;
  - `max_files=1`, `max_fields=16`;
  - 4 M pixels pela sondagem, antes de decodificar;
  - depois, `load_image`.
- **Limitador:** um `BoundedSemaphore` por app, `release` em `finally` e o único ponto de chamada de `load_capture_image` dentro do slot.

### `LOAD_TRUNCATED_IMAGES`

- A flag é conferida em três pontos: no `lifespan` (antes dos serviços), em `cli.main` (depois de montar o inferenciador e o sink, antes do `uvicorn.run`, com saída 1) e em `load_capture_image` (antes da sondagem).
- Se ela for ligada depois da subida, a resposta é 500 genérico, e não 415.
- O CA-25 faz uma varredura AST de todo `*.py` versionado fora de `tests/`.
- **Risco residual:** uma biblioteca de terceiros importada **depois** da subida (import tardio dentro de um handler) poderia ligar a flag. Isso continua coberto pela checagem de cada chamada no `load_image` e no `load_capture_image`, e a janela residual é a que o §7 já aceita. A SPEC-008 deve importar o `onnxruntime` antes da checagem da CLI, como o §4.3 já manda.

### R-02 e R-14

- Só `/static` é montado.
- No servidor real, todas estas rotas deram **404**:
  - `/captures/<dia>/<id>.jpg` e `/data/captures/<dia>/<id>.jpg`;
  - `/static/../captures/...`;
  - `/static/%2e%2e/...` e `/static/..%2fapp.py`;
  - uma travessia crua por socket até o caminho absoluto do `EDGE_DATA_DIR`;
  - `/docs`, `/openapi.json` e `/static/`.
- Nenhum módulo de `qc_edge` importa `httpx`, `requests` ou `urllib.request`.
- O sink recebe só o `InspectionCreate`, com os 14 campos do contrato.
- `edge/data/` está no `.gitignore` (`git check-ignore`: regra `data/`, linha 25).

### Travessia no armazenamento

- O nome é sempre `<uuid4>.jpg`, gerado no servidor.
- O diretório vem da data UTC do `clock()`. O nome e o content-type do cliente são ignorados.
- O arquivo é aberto com `open("xb")`, e um lock cobre criar e apagar.
- Conferido: com o upload `../../evil.jpg`, o único arquivo criado foi `captures/<dia>/<id>.jpg`.

### Exposição na rede

- **Bind:** padrão `0.0.0.0`, como manda o `architecture.md` §8.
- **Hotspot:** com senha, no Plano B do README.
- **Túneis:** proibidos e citados no README.
- **Firewall:** ver SEC-05. Com `::`, ver SEC-04.

### Commits e R-13

- Todos os commits estão com a identidade do projeto.
- Os trailers `Agent:` batem com os arquivos tocados:
  - `developer`: produção, `edge/tests/` fora de `acceptance/` e docs;
  - `tester`: só `acceptance/` e o test-report;
  - `orchestrator`: status e plano.

## Decisão sobre o RV-01 (custo por slot)

Medição deste revisor: notebook de 4 núcleos, Pillow 12.3.0, libjpeg-turbo 3.1.4.1. Todas as entradas cabem em 3 145 728 bytes, ou seja, passam pelo 413.

| Entrada hostil (≤ 3 MiB) | Sondagem | `load_capture_image` (sondagem + `load_image`) | Pico de RSS do processo (base ~43 MB) | Resultado |
|---|---|---|---|---|
| JPEG, 786 k segmentos APP1 vazios | 1,98 s | **3,95 s** | **133 MB** | 200 |
| JPEG, bytes de preenchimento `FF` | 1,86 s | 3,82 s | 48 MB | 200 |
| PNG, chunks privados vazios (CRC válido) | 1,49 s | 3,05 s | 70 MB | 200 |
| JPEG, segmentos COM vazios | 1,30 s | 2,54 s | 98 MB | 200 |
| PNG, chunks `tEXt` mínimos | 1,15 s | 2,15 s | 42 MB | 200 |
| JPEG, lixo `00` entre marcadores | 0,00 s | 0,00 s | 43 MB | 415 |
| JPEG progressivo 2000×2000 de ruído (1,7 MB) | 0,00 s | 0,20 s | +~10 MB | 200 |
| JPEG baseline 2000×2000 de ruído (1,9 MB) | 0,00 s | 0,09 s | +~3 MB | 200 |
| PNG RGBA 2000×2000 | 0,00 s | 0,07 s | +~20 MB | 200 |

O pior caso é a inundação de APP1. Ela custa **~4 s de CPU e ~90 MB acima da base por requisição**, confirmando o tester (4,05 s) e o reviewer (3,94 s e 133 MB). O custo vem do laço de marcadores em Python do Pillow, executado duas vezes (na sondagem e no `load_image`). A decodificação de pixels, cortada pelos 4 M pixels, ficou abaixo de 0,2 s.

**Efeito com 2 slots** (servidor real, padrões 2 e 10 s, stub):

- **Memória:** com dois slots ocupados, fica em ~180 MB acima da base, contra ~720 MB sem os limites da rota. Fica bem dentro do notebook.
- **CPU:** o laço segura o GIL, então os dois slots **se serializam**. Duas inundações simultâneas levam ~8,5 s cada e ocupam **~1 núcleo**, e não 2.
- **Requisição legítima:**
  - com 2 inundações em curso: 200 em 6,7 s, acima dos 3 s da RNF-03 só enquanto dura o ataque;
  - com 6 ou mais: 503 `server busy` em ~10 s.
- **Console e `/api/status`:** continuam respondendo (0,3–0,5 s) até a fila passar de 40 threads (SEC-03).

**Decisão: aceito com 2 slots. A SPEC-007 não precisa mudar antes do merge.** Motivos:

1. A ameaça e a consequência são as que a §4.6 já aceita. Exige o token **e** estar no hotspot da dupla, que tem senha. O resultado é 503 nas capturas, nunca a queda do notebook. A memória, que era o risco de OOM, ficou dentro da estimativa.
2. A diferença de 1,4 s para 4 s só muda quantas requisições por segundo bastam para manter os slots ocupados (~0,5 por slot em vez de ~1,4). Para um atacante com script, as duas taxas são triviais, e a classe do risco não muda.
3. O GIL limita o impacto a ~1 núcleo, seja qual for o número de slots. Por isso, subir para 3 ou 4 slots não ajudaria, e baixar para 1 dobraria a fila das requisições legítimas sem reduzir o pior caso por requisição.

**Encaminhamentos (não bloqueiam):**

- **Architect, só documentação:** trocar na §4.6 e no `architecture.md` §9 o "~1,4 s e ~110 MB estimados" por "~4 s de CPU e ~90 MB acima da base (133 MB de pico) **medidos**, com os 2 slots serializados pelo GIL (~1 núcleo)". Citar este relatório.
- **Architect, opcional, depois do passo 6 do CA-20:** se o maior arquivo real dos dois celulares ficar bem abaixo de 3 MiB, baixar `CAPTURE_MAX_BYTES` (e `CAPTURE_MAX_REQUEST_BYTES`) com folga de ~2× sobre o maior medido. O custo da inundação cai na mesma proporção (ex.: 1 MiB → ~1,3 s). Isso é uma mudança de SPEC, que pode entrar com a SPEC-008 ou a SPEC-010.
- **Futuro, opcional:** um limite de segmentos e marcadores no `qc-preprocess` (SPEC própria do pacote, porque o §7 proíbe interpretar segmentos à mão na borda).

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ `compare_digest` sobre bytes; token antes do parse do corpo; console só loopback e sem headers de proxy. Ressalva: SEC-01 (`Host`), média, com prazo antes da SPEC-009 |
| Entradas validadas: tamanho, tipo real, regex, `extra="forbid"` | ✅ 413 por `Content-Length`, chunked e campo; tipo pelo conteúdo (sondagem do Pillow e `load_image`); 4 M pixels antes de decodificar; `lot_id` com `fullmatch`; `DEVICE_ID` com `pattern`; `mode` por enum. O `InspectionCreate` do contrato tem `extra="forbid"`. O formulário é manual, sem modelo Pydantic, e campos extras são ignorados (limite de 16) |
| SQL parametrizado | N/A (a borda não acessa banco nesta SPEC) |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A. O `DEVICE_API_KEY` é só lido (`SecretStr`), não é usado e não vai para o log |
| CORS fechado ou mínimo | ✅ Nenhum middleware CORS: o `POST` com `X-Session-Token` de outra origem esbarra no preflight. Ver SEC-01 para o caso de mesma origem por rebinding |
| Logs sem segredos e sem payloads de imagem | ✅ Access log desligado; `RequestLogMiddleware` sem query; servidor real: 148 linhas sem o token; 415 com o motivo, sem bytes da imagem |
| Dependências novas: mantidas, licença, CVE | ✅ Só `pydantic-settings` 2.15.0 (MIT), já no lock. `pip-audit` sobre os 28 pacotes do `qc-edge`: nenhuma vulnerabilidade conhecida |
| Deploy: variáveis no provedor, health check, free sem cartão | N/A (só LAN, nenhum recurso de nuvem). R-01 ok. Rede: SEC-04 e SEC-05 |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| `pydantic-settings` (nova só para o `qc-edge`) | 2.15.0 | MIT | Já resolvida no `uv.lock` pelo `qc-api`; nenhum pacote novo. Mantida (ecossistema Pydantic). `pip-audit` sem achados |
| Contexto (sem mudança nesta SPEC) | starlette 1.7.0, fastapi 0.143.0, python-multipart 0.0.32, uvicorn 0.54.0, Pillow 12.3.0 (libjpeg-turbo 3.1.4.1), qrcode 8.2 | — | `pip-audit` sem achados. O Pillow não mudou, então a reconferência do JPEG aritmético do `architecture.md` §9 não se aplica |

## Ações pendentes

- **Architect:**
  - SEC-01: validação do `Host` no console, com prazo antes do merge da SPEC-009;
  - SEC-02: atualização dos números da §4.6 e do §9, e a redução opcional de `CAPTURE_MAX_BYTES` depois do CA-20;
  - SEC-03: espera do slot fora do threadpool, na SPEC-010;
  - SEC-04: `EDGE_HOST` e IPv6, na SPEC-008;
  - SEC-05 e SEC-07: texto do `edge/README.md`, na SPEC-008;
  - SEC-06: permissões e retenção das fotos, na SPEC-010.
- **Humano:**
  - executar o CA-20 e o CA-21 (que bloqueiam o merge, conforme o review-report) e registrar o tamanho do maior arquivo de cada celular, que alimenta a decisão opcional do SEC-02;
  - na apresentação, não projetar o console e usar o hotspot com senha (SEC-07).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Só escrevi este relatório. As medições rodaram em scripts e diretórios temporários no scratchpad, e os servidores de teste foram encerrados.
- [x] Não sou autor de nenhum commit desta SPEC.
