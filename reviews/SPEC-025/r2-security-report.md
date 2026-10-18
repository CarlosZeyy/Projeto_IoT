# SPEC-025 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r2 (o primeiro portão de segurança desta SPEC: avaliei a SPEC inteira, r1 e r2) |
| Revisor de segurança | security-devops |
| Diff revisado | `main...0de460d` (38 arquivos, +6315/−209) |
| Relatórios lidos | `r1-dev-report.md`, `r2-dev-report.md`, `r1-test-report.md`, `r2-test-report.md` (PASS), `r1-review-report.md`, `r2-review-report.md` (APPROVED) |
| **Veredicto** | **PASS** |

Não há achado bloqueante, alto nem médio. Ficam 2 achados baixos e 5 informativos (SEC-25-01 a SEC-25-07). Nenhum deles exige r3: todos pedem emenda de SPEC (architect) ou são endurecimento opcional.

## Pendências de outras SPECs: estado

| Pendência | Estado | Evidência |
|---|---|---|
| **SEC-01 da SPEC-007** (DNS rebinding no console) | **Fechado** | No servidor real (`qc-edge --stub-model`, `EDGE_HOST=127.0.0.1`, porta livre): `Host` `127.0.0.1:<p>`, `localhost:<p>`, `LOCALHOST:<p>` e `[::1]:<p>` → 200 com `<svg`. `attacker.example:<p>`, `127.0.0.1` sem porta, `127.0.0.1:<p+1>`, `localhost.:<p>`, `127.0.0.1.nip.io:<p>`, `192.168.0.42:<p>`, `Host` vazio, sem `Host` (HTTP/1.0), dois headers `Host` e `X-Forwarded-For` → 403, e nenhum corpo tem o token. O log do servidor não tem `attacker` nem o token. A checagem (`app.py:681-697`) vem antes de `detect_lan_ips()` e de qualquer render (CA-02, espião com 0 chamadas). As rotas com token não mudaram (`/api/status` com `Host: 10.0.0.7:<p>` → 200). |
| **SEC-10-01 da SPEC-010** (EXIF/GPS e trailer no dataset) | **Fechado** | No servidor real, um JPEG com EXIF GPS e o trailer `ftypmp42` enviado em `mode=collect` ficou gravado sem `Exif\0\0`, sem `ftypmp42` e terminando em `FF D9`. O mesmo JPEG em `mode=inspect` ficou igual byte a byte em `captures/`, como a §3.2 manda. Com `Orientation=6`, a coleta respondeu 415 `invalid image: EXIF orientation not supported` e nada foi gravado. A varredura (`python -m qc_edge.privacy`) acusou `app1, trailer` e saiu com 1. O `--fix` e a recusa por `orientation` passam nos CA-15 e CA-19 (rodei). A remoção é estrutural (`jpeg.py:_walk`), e a ordem rotação → remoção, dentro do slot e antes do disco, está em `collect.py:dataset_image_bytes`. Os resíduos SEC-25-01 e SEC-25-02 (baixos) não reabrem o item. |
| **SEC-10-02 da SPEC-010** (`fsync` de diretórios) | **Fechado** | `fsync_dir` do pai de cada diretório criado (`fsutil.make_private_dirs(sync=True)`), do diretório da imagem depois do `os.replace` e antes da linha do manifest (`collect.write_private_file_atomically`), e de `DATASET_DIR` quando o manifest é criado. O `--fix` usa o mesmo caminho. O `OSError` vira `WARNING` com o caminho relativo. CA-17 passa (rodei). |
| **SEC-10-03 da SPEC-010** (`notes` e `capture_device`) | **Fechado** | `FORBIDDEN_TEXT_CATEGORIES = {Cc, Cs, Cf, Zl, Zp}`. `notes` dá 422 antes do disco. `capture_device_from_user_agent` troca por espaço e só **depois** corta em 60. CA-18 passa (rodei), inclusive o `User-Agent` em bytes com `\x85` e `\t`. |
| SEC-03, SEC-04, SEC-05, SEC-06 (`captures/`) e SEC-07 da SPEC-007 | Fechados | Ver o checklist abaixo. |

## Superfície analisada

- **Rotas:** `GET /` (console, `Host`); `POST /api/capture` (handler `async`, `anyio.Semaphore`, uma única `to_thread.run_sync`), nos dois modos; `/capture`, `/api/status` e `/static/*` (sem mudança).
- **Entradas externas:** header `Host`, corpo JPEG/PNG da coleta (APPn, COM, trailer, `Orientation`), `notes`, `User-Agent`, argumentos da CLI `qc-edge` e de `python -m qc_edge.privacy`, nomes de arquivo em `raw/` lidos pela varredura.
- **Configuração:** `EDGE_HOST` só IPv4, `EDGE_DATA_DIR` com `0700`, `.env.example`.
- **Sistema de arquivos:** modos `0700`/`0600` com qualquer `umask`, `O_EXCL | O_NOFOLLOW`, temporário + `os.replace`, `flock` compartilhado entre a coleta e o `--fix`.
- **Documentação operacional:** `edge/README.md` (firewall por sub-rede, Segurança na operação, Modo coleta), `docs/dataset-protocol.md` §8.
- **Dependência:** `anyio>=4.15` declarada no `qc-edge`.
- **Deploy:** nenhum. A borda roda só na LAN; `infra/` e `render.yaml` não foram tocados.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-25-01 (= RV-03 da r1 do review e O-01 da r1 do tester) | baixa | privacy (integridade da saída) | `edge/src/qc_edge/privacy.py:138`, `:143` (stdout) e `:115`, `:129` (log) | **A CLI imprime o caminho relativo cru. Confirmado.** Um arquivo `raw/screw/fair/x\nchecked 9 images, 0 with private data\x1b[8m.jpg` (com metadados) gerou a saída `raw/screw/fair/x` / `checked 9 images, 0 with private data` / `<ESC>[8m.jpg: app1, trailer` / `checked 2 images, 1 with private data`. Num terminal, o `ESC[8m` (texto oculto) segue ligado e esconde a linha de achado e o resumo verdadeiro, então o operador vê só o resumo falso, limpo. O código de saída continua 1, e o resumo verdadeiro continua sendo a última linha do stdout. **Por que é baixa:** só alguém que põe arquivos em `raw/` escolhe o nome. A rota de coleta gera o nome a partir de campos validados por regex, então não há vetor remoto. Sobra a cópia manual feita pela própria dupla, cujos nomes de câmera (`IMG_…`, `PXL_…`) não têm controles. A varredura é o controle antes do backup (R-14), e é por isso que o caso fica registrado. | **Não exige r3.** Para o architect, numa SPEC de manutenção da borda: o caminho impresso no stdout e nos logs da CLI escapa os caracteres das categorias `Cc`, `Cf`, `Cs`, `Zl` e `Zp` (por exemplo, `\x1b` → `\\x1b`, como o `unicode_escape`), ou o arquivo vira o achado `invalid` sem que o nome seja impresso. Um CA com `\n` e `ESC` no nome. **Mitigação até lá (humano):** no passo 1 do `docs/dataset-protocol.md` §8, conferir também o código de saída (`echo $?` → `0`), e não só a última linha. |
| SEC-25-02 (= RV-02 da r1 do review e O-04 da r1 do tester) | baixa | privacy (R-14) | `edge/src/qc_edge/privacy.py:54` e `:76` | **`.JPG` e `.jpeg` não são varridos.** A §4.9 pede `*.jpg`, e o código segue a SPEC. O passo 4 do `docs/dataset-protocol.md` §8 compacta `ml/data/` **inteiro**. Uma foto copiada à mão com a extensão em maiúsculas (`IMG_0001.JPG`, padrão do iPhone e de várias câmeras) ou com `.jpeg` iria para o Drive com o GPS e sem nenhum achado, e o resumo diria `0 with private data`. O README (item 3) avisa que a varredura confere "os arquivos `*.jpg`", mas o protocolo não. A coleta pela rota sempre gera `.jpg`. | **Não exige r3.** Para o architect, na mesma emenda: casar a extensão sem diferenciar maiúsculas (`.jpg` e `.jpeg`) e listar como `invalid` qualquer outro arquivo regular em `raw/` (fora os temporários `.tmp` da própria borda). **Mitigação até lá (humano):** no §8, só copiar para `raw/` arquivos renomeados para `.jpg` em minúsculas e, antes do backup, conferir que `find ml/data/raw -type f ! -name '*.jpg'` não lista nada. |
| SEC-25-03 (= O-02 da r1 do tester) | informativa | secrets | `edge/src/qc_edge/argv.py:19` | Uma palavra minúscula de até 31 caracteres com cara de opção (`--[a-z][a-z0-9-]{0,30}`) é registrada como nome de opção. A regra é a da §4.5. Os segredos do projeto não cabem no formato: o token de sessão e o `DEVICE_API_KEY` são `secrets.token_urlsafe(32)` (43 caracteres, em geral com maiúsculas ou `_`). O log fica no stderr local. Conferi no processo real: `qc-edge --token=<marcador>` sai com 2 e registra só `--token`. `--dataset-dir=<marcador>` registra só a mensagem fixa. | Nenhuma. |
| SEC-25-04 (= O-01 da r2 do dev) | informativa | privacy (logs) | `edge/src/qc_edge/cli.py` (`configure_logging`) e `privacy.py:165` | O `PIL.TiffImagePlugin` registra em `DEBUG` os valores das tags EXIF (orientação, GPS). **Na produção esses registros nem são criados:** o `qc-edge` só configura o logger `qc_edge` (INFO), o `dictConfig` do uvicorn não mexe na raiz (que fica em `WARNING`) e a CLI de varredura usa `basicConfig(level=INFO)`. O único log do Pillow acima de `DEBUG` nesses módulos (`TiffImagePlugin.py:1508`) é de arquivo TIFF, inalcançável com `formats=("JPEG",)`. No servidor real, o log de uma inspeção e de uma coleta com GPS não teve o valor. | Endurecimento opcional, numa SPEC futura: `logging.getLogger("PIL").setLevel(logging.INFO)` na subida do `qc-edge` e na CLI. Regra de operação: não ligar `DEBUG` na raiz com fotos reais. |
| SEC-25-05 | informativa | privacy | `edge/src/qc_edge/jpeg.py:39` | Por decisão da §4.8 e da §7, ficam no arquivo o APP0, o APP2 (ICC e MPF), o APP3 a APP12, o APP14 e o APP15. O GPS fica só no APP1 (EXIF/XMP), que sai. Um perfil ICC ou um APPn de fabricante (dados de câmera de alguns Android) pode trazer texto descritivo do aparelho, mas não localização. O caminho normal (página `/capture`, canvas) não envia nenhum deles. | Nenhuma nesta SPEC. Se a dupla passar a copiar fotos do app da câmera com frequência, a SPEC-011 ou uma emenda pode listar esses APPn como achado informativo. |
| SEC-25-06 | informativa | auth | `edge/src/qc_edge/app.py:692` | Uma requisição em forma absoluta, `GET http://attacker.example:<p>/` com `Host: 127.0.0.1:<p>`, recebe 200, porque o uvicorn usa o header `Host`. Não é explorável por DNS rebinding: o navegador nunca manda a forma absoluta a um servidor de origem e sempre manda o nome religado no `Host` (que recebe 403, como medi). Só um processo local manda a forma absoluta, e ele já pode escolher o `Host`. | Nenhuma. |
| SEC-25-07 (= O-02 da r1 do dev) | informativa | privacy | `edge/src/qc_edge/privacy.py:74` | O `os.walk(raw, followlinks=False)` não segue links abaixo de `raw/`, mas segue `raw` se ele mesmo for um link. Nesse caso, o `--fix` reescreve arquivos fora de `<D>`. Exige escrever no `DATASET_DIR` (`0700`), ou seja, a mesma conta. | Nenhuma nesta SPEC. Opcional numa emenda: recusar com código 2 um `raw` que seja link. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ As rotas com token não mudaram (`token_matches`, `compare_digest` sobre bytes). O console, a única rota que entrega o token sem pedir o token, agora exige loopback, nenhum header de proxy e **exatamente um** `Host` de loopback na porta configurada, sem `strip()`, prefixo ou resolução (`security.py:is_allowed_console_host`). Medido no servidor real (tabela acima). A recusa loga só `console refused: host not allowed`. |
| Entradas validadas (tamanho, tipo real da imagem, regex, `extra="forbid"`) | ✅ A ordem 401 → 413 → 422 → 503 → 415 não mudou. As regras de tamanho, pixels e scans valem sobre os bytes **recebidos**, e a saída da remoção nunca tem mais marcadores que a entrada. `JpegStructureError` tem mensagem fixa, e `has_exif_rotation` não devolve nem loga o valor. `notes` e `capture_device` seguem a §4.11. `EDGE_HOST` é `IPv4Address`: `::`, `::1` e `localhost` saem com 2 no processo real, e a mensagem não ecoa o valor. CLI: `QuietArgumentParser` nunca deixa o `argparse` imprimir argumentos (`--token=<marcador>` → só `--token`). |
| SQL parametrizado | N/A (a borda não usa banco nesta SPEC) |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A |
| CORS fechado ou mínimo | N/A (a SPEC não muda CORS; o console é só loopback) |
| Logs sem segredos e sem payload de imagem | ✅ Conferido no log do servidor real: sem token, sem o `Host` do atacante e sem valores de GPS. Os caminhos logados são relativos e gerados pela borda. Ressalvas: SEC-25-01 (nome cru na CLI) e SEC-25-04 (`DEBUG` do Pillow, não ativo). |
| Dependências novas | ✅ Ver a tabela. |
| Deploy | N/A. **Bind:** com `EDGE_HOST=127.0.0.1`, o `ss -ltn` mostrou só `127.0.0.1:<p>`, sem socket `[::]`. Um valor IPv6 não sobe (código 2), e o `0.0.0.0` padrão é um socket só AF_INET. **Firewall do README:** todos os comandos de liberação têm origem (`from <sub-rede>`, `source address=`, `ip saddr`); não há `--permanent`, `ufw allow 8000/tcp` nem `--add-port`. O firewalld é só runtime, a persistência do ufw é avisada com o `delete` correspondente, e o README traz `ip -4 route show scope link`, as bridges do Docker e a frase "não rodar na Wi-Fi do campus". O Plano B refaz a regra com a sub-rede do hotspot. |
| Permissões (R-14) | ✅ Com o servidor real sob `umask 000`: `EDGE_DATA_DIR`, `captures/` e `captures/<dia>/` com `0700`, a foto com `0600`; `DATASET_DIR`, `raw/`, `raw/screw/` e `raw/screw/fair/` com `0700`, a imagem, o `manifest.csv` e o `manifest.csv.lock` com `0600`. O CA-09 (`0o022`, `0o077`, `0o000`, `0o277`) e o CA-15 (`--fix` com `0o022` e `0o277`) passam. Os arquivos são criados com `O_CREAT | O_EXCL | O_NOFOLLOW` + `fchmod`, e o temporário do `--fix` recebe `fchmod 0600` antes de ser escrito. |
| R-02 | ✅ No diff de `edge/src`, nenhum `socket`, `httpx` nem `urlopen` novo. `privacy.py` e `has_exif_rotation` só leem bytes locais. O exploratório do tester espionou `socket.connect`/`getaddrinfo` numa coleta, numa inspeção e num `--fix`. Nenhuma rota serve fotos. |
| R-03 | ✅ Nenhum segredo literal no diff. Os marcadores dos testes vêm de `secrets`. O `.env.example` recomenda deixar `EDGE_SESSION_TOKEN` vazio. |
| R-07 | ✅ Nenhum commit `Agent: security-devops` na branch, então não sou autor de nada nesta SPEC. Os commits são `developer`, `tester`, `reviewer`, `architect` e `orchestrator`, todos com a identidade CarlosZeyy (R-13). |

Testes que rodei (sem a suíte inteira): `uv run pytest -q edge/tests/acceptance/test_spec_025.py -k "ca01 or ca02 or ca03 or ca04 or ca05 or ca06 or ca09 or ca10 or ca11 or ca13 or ca14 or ca15 or ca16 or ca17 or ca18 or ca19"` → 51 passed. A sonda no servidor real usou porta livre em `127.0.0.1` e diretório temporário. O processo foi encerrado e o diretório apagado no fim. O token foi lido da resposta em tempo de execução, nunca escrito como literal.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| `anyio` (direta no `qc-edge`; já era transitiva via starlette/httpx) | `>=4.15`, lock 4.15.1 | MIT | Mantida (release 2026-09-05). OSV (`api.osv.dev`, consultado em 2026-10-18): nenhuma vulnerabilidade para 4.15.0 nem para 4.15.1. Os avisos conhecidos (GHSA-3w57-8xmc-8v26, GHSA-5p39-cfhj-2xmp e GHSA-82r6-8w77-94w6) são de versões anteriores e de APIs não usadas aqui (`run_process`, process pool, `TLSStream`). Sem torch nem onnxruntime em `api/` ou `dashboard/` (R-12). |

## Ações pendentes para o humano

1. Até a emenda do SEC-25-01 e do SEC-25-02: antes de cada backup no Drive, conferir o **código de saída** da varredura (`0`) e que `find ml/data/raw -type f ! -name '*.jpg'` não lista nada.
2. Decidir com o architect se o SEC-25-01 e o SEC-25-02 entram na próxima SPEC de manutenção da borda, junto com os RV-02, RV-04 a RV-07 do review.

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
