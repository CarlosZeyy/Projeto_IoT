# SPEC-010 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-010](../../docs/specs/SPEC-010-modo-coleta.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...8b20d4e` (30 arquivos, +3852/−148) |
| **Veredicto** | **PASS** |

Não há achado bloqueante, alto ou médio. São 4 achados baixos e 4 informativos. Nenhum exige r2. As decisões sobre o RV-03 e o RV-04 do review-report estão nas seções próprias, mais abaixo.

## Superfície analisada

- **Rota `POST /api/capture` com `mode=collect`** (`edge/src/qc_edge/app.py`):
  - token (`X-Session-Token`) conferido antes do parse do corpo, com `token_matches` (`secrets.compare_digest` em bytes);
  - `BodySizeLimitMiddleware` (3,5 MiB), `max_files=1`, `max_fields=16` e campo `image` limitado a 3 MiB (413);
  - `load_capture_image` (4 M pixels, depois `load_image`) dentro do limitador de decodificações, nos dois modos;
  - `lot_id` ignorado no modo coleta.
- **Validação dos campos que viram caminho ou linha do CSV** (`collect.py`, `CollectRequest.from_fields`): `item_id`, `angle`, `object_type`, `grade`, `labeler` e `notes`, além do `capture_device` (header `User-Agent`).
- **Gravação** (`DatasetWriter`): `threading.Lock` mais `fcntl.flock`, `_make_dirs`, `_open_file` (`O_CREAT|O_EXCL|O_NOFOLLOW`), `mkstemp`, `fsync` e `rename`, append com `ftruncate` na falha, e modos `0700`/`0600`.
- **Privacidade:** `jpeg.py` (JPEG gravado como chegou), `capture.js` (reencode via canvas), `docs/dataset-protocol.md` §3, §8 e §9.
- **R-02:** imports de `collect.py` (sem cliente HTTP), `collect()` sem `Inferencer` nem `InspectionSink`, `StaticFiles` só em `STATIC_DIR`, console só em loopback.
- **Console:** `_coverage_html` (escape de HTML) e caminho absoluto do `DATASET_DIR` (só loopback).
- **Configuração:** `DATASET_DIR` em `EdgeSettings`, `.env.example` e `.gitignore` (`ml/data/` coberto).
- **Dependências:** nenhuma mudança em `pyproject.toml` nem em `uv.lock`.

### Verificações executadas (só leitura, num diretório temporário do scratchpad, já apagado)

- `uv run pytest edge -q`: **484 passed** (uma execução).
- Script de sondagem do `DatasetWriter` e do `CollectRequest`:
  - recusam `item_id="S-001\x00"`, `item_id="S-١٢٣"` (dígitos arábicos; o `re.ASCII` fecha a brecha), `angle="٢"`, `object_type="Screw"` e `labeler="a\n"` (422);
  - `notes` com U+2028 e U+202E é aceito (SEC-10-03);
  - `capture_device` com U+0085 e TAB é gravado como chegou (SEC-10-03);
  - `notes='=HYPERLINK(...)'` é gravado com o `=` inicial (SEC-10-04);
  - com `raw/` trocado por symlink para fora do dataset, a imagem foi gravada no destino do link (SEC-10-05);
  - com `manifest.csv` trocado por symlink, a escrita falhou com `ELOOP` (500), e a imagem já gravada foi removida (sem órfã).
- JPEG com EXIF GPS e 200 KB de dados depois do EOI (imitando um Motion Photo): `load_capture_image` aceita, e `write_capture_jpeg` gravaria os bytes inteiros (SEC-10-01).
- Busca por segredos no diff: nada encontrado. Autoria: nenhum commit da branch tem `Agent: security-devops`.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-10-01 | baixa | privacy | `edge/src/qc_edge/jpeg.py:24-25`; `collect.py:518` | **RV-03 (EXIF e dados depois do EOI).** Um JPEG enviado direto à rota (fora da página) é gravado no dataset byte a byte: EXIF (GPS, fabricante e modelo, data local), XMP e qualquer trailer depois do EOI. Um Motion Photo pequeno o bastante para caber nos 3 MiB e passar no limite de 64 `FF DA` levaria até o vídeo, que pode ter áudio. Confirmei que esse arquivo é aceito. Pela página `/capture`, isso não acontece: o `capture.js` **sempre** passa a foto pelo canvas (`toBlob`, JPEG q=0,9), que descarta metadados e trailer. O envio direto exige o token de sessão, que só aparece no console em loopback. O cenário realista é a própria dupla automatizar o envio de fotos antigas do app da câmera (o §3 do protocolo menciona essas fotos). O dataset vai para o Drive pessoal e para o Colab (§8). Não é violação do R-02, porque o §8 prevê esse backup, mas leva a localização junto, sem necessidade (R-14: "só a área da peça interessa"). | **Não bloqueia.** Vai para o **architect**, como mudança futura da regra "JPEG: bytes recebidos" do §4.2, passo 4. Sugestão: no modo coleta, gravar o JPEG sem perda, só até o EOI e sem os segmentos APP1 (EXIF/XMP) e APP13. Outra opção é a SPEC-011 acusar, na validação, as imagens com EXIF GPS ou com trailer. Deve ser decidido **antes do primeiro backup** do dataset no Drive. Até lá, a mitigação é de procedimento: coletar só pela página `/capture`. Vale registrar isso no `edge/README.md` (seção "Modo coleta") na mesma mudança. Para as fotos de inspeção (`captures/`), o risco é desprezível, porque elas nunca saem do notebook (§9). |
| SEC-10-02 | baixa | integrity | `collect.py:521` (`os.rename`), `:454` (`_make_dirs`) e `:542` | **RV-04 (falta `fsync` do diretório).** Concordo com a análise do reviewer: em btrfs, uma queda de energia logo depois de uma coleta pode deixar no manifest uma linha que aponta para uma imagem que não persistiu. O caso inverso também existe: um crash entre o `rename` e o append deixa uma imagem órfã, sem linha. Não é um problema de confidencialidade nem de controle de acesso, e só um evento físico (queda de energia ou crash) o dispara, nunca um cliente da rede. A SPEC não pede `fsync` de diretório. | **Não bloqueia.** Vai para o **architect**, como item opcional. O lugar natural é a **SPEC-025**, que já revisa a escrita de arquivos da borda (`captures/`, permissões e limitador): `os.open(dir, O_RDONLY\|O_DIRECTORY)` + `os.fsync` depois do `rename` e da criação de diretórios, antes do append. O controle compensatório está na **SPEC-011**: o pipeline deve acusar as duas inconsistências, linha sem arquivo (já previsto na skill `ml-pipeline`) e arquivo `.jpg` sem linha, em vez de ignorar a segunda. |
| SEC-10-03 | baixa | input | `app.py:384` (`capture_device`); `collect.py:65` | **Separadores de linha que o CSV não protege.** O `capture_device` vem do `User-Agent` sem filtro. O h11 aceita `obs-text` (0x80–0xFF), o Starlette decodifica em latin-1, e por isso controles C1 como U+0085 (NEL) chegam ao manifest. O `notes` recusa `Cc`/`Cs`, mas aceita U+2028/U+2029 (categorias `Zl`/`Zp`) e controles bidi (`Cf`, como U+202E). O `csv.writer` só põe aspas por causa de `\r`, `\n`, vírgula e aspas. O `csv`/`pandas` leem o arquivo certo (verificado: 1 linha pelo `DictReader`), mas o `str.splitlines()` conta 3 linhas onde existem 2. Os U+202E podem disfarçar o texto de `notes` numa tela. A origem é sempre quem tem o token. | **Não bloqueia.** Vai para a **SPEC-011**: ler o manifest só com `csv`/`pandas`, nunca com quebra por linhas (`splitlines`, `wc -l`, `grep`). Vai também para o **architect**, numa revisão futura da SPEC-010: aplicar ao `capture_device` o mesmo filtro de `Cc` do `notes` (trocando por espaço ou removendo) e incluir `Zl`, `Zp` e os controles bidi na lista de categorias recusadas em `notes`. |
| SEC-10-04 | baixa | input | `collect.py:465` (`notes`), `:464` (`capture_device`) | **Injeção de fórmula em CSV.** Os valores de `notes` e `capture_device` que começam com `=`, `+`, `-` ou `@` são gravados como vieram (verificado com `=HYPERLINK(...)`). O §7 da SPEC manda não alterar `notes` além do quoting, e o consumidor é o pandas, que não avalia fórmulas. O risco só existe se alguém abrir o `manifest.csv` numa planilha com avaliação de fórmulas, e a entrada vem de quem tem o token. | **Não bloqueia.** Vai para o **architect**: acrescentar uma linha ao `docs/dataset-protocol.md` §5/§8 ("não abrir o `manifest.csv` em planilha; se abrir, importar todas as colunas como texto"). Vai também para a **SPEC-011**: se o pipeline exportar CSV para planilha (relatórios de concordância, por exemplo), neutralizar as células que começam com esses caracteres (prefixo `'`). |
| SEC-10-05 | info | input | `collect.py:343-355`, `:450-455`, `:513` | **Symlinks.** Os componentes finais estão protegidos. O `manifest.csv` e o `.lock` abrem com `O_NOFOLLOW` (verifiquei o `ELOOP`, e a imagem foi removida no rollback). A imagem é checada com `lexists` sob os dois locks. O `mkstemp` cria com `O_EXCL` e `0600`. O `rename` substitui um link sem segui-lo. Os diretórios intermediários (`raw/`, `raw/<tipo>/`, `<grau>/`) são seguidos se forem symlinks (verificado), e o `read_bytes()` do manifest também segue o link (só leitura). Para explorar isso, é preciso escrever dentro do `DATASET_DIR`, que nasce `0700`, ou seja, ter o mesmo usuário. Isso não cruza fronteira de privilégio, e apontar `ml/data` para um disco externo é um uso legítimo. A janela entre o `lexists` e o `rename` está coberta pelos dois locks contra outra borda. Fora deles, só o próprio usuário poderia criar o arquivo. | Nenhuma. |
| SEC-10-06 | info | availability | `collect.py:431` | **`flock` bloqueante sem timeout.** Se outro processo do mesmo usuário segurar o `manifest.csv.lock`, cada coleta espera indefinidamente, segurando o `threading.Lock` e um slot do limitador. Com isso, o modo inspeção passa a responder 503 "server busy" depois do `decode_wait_s`, e o console espera o `threading.Lock` (rota síncrona, no threadpool; não trava o event loop). Hoje nenhum outro processo usa esse lock. | Nenhuma nesta SPEC. Nota para a **SPEC-011**: se o pipeline ou um script de backup tomar o `flock`, deve segurá-lo só pelo tempo da cópia do manifest. |
| SEC-10-07 | info | availability | `app.py:505-517` | **Sem cota de disco nem limite de taxa.** Quem tem o token pode encher o disco do notebook com coletas válidas (cada uma ≤ 3 MiB). O limitador controla a concorrência, não o volume. É o mesmo modelo de ameaça das capturas de inspeção (SPEC-007), com o token restrito à dupla. | Nenhuma. |
| SEC-10-08 | baixa | privacy | `docs/dataset-protocol.md` §5, §8 | **Não há procedimento para tirar do dataset uma foto com pessoa (R-14).** O §9 manda apagar na hora uma foto de inspeção com pessoa identificável, mas o dataset não tem equivalente. Além disso, o §5 proíbe reescrever a linha original do manifest. Apagar só a imagem deixa uma linha órfã, que faz a SPEC-011 falhar (SEC-10-02). Hoje, quem achar uma foto assim não tem um caminho documentado que não quebre o pipeline, e a foto pode acabar indo para o backup no Drive. | **Não bloqueia.** Vai para o **architect**, junto com a **SPEC-011**: documentar no `docs/dataset-protocol.md` (§5 ou §8) um caminho de remoção. Por exemplo, um `exclusions.csv` (`image_path,reason`) aplicado pelo pipeline, ao lado do `labels_overrides.csv`, ou a permissão explícita de apagar a linha nesse único caso. O caminho deve incluir apagar a imagem também do backup no Drive. |

## Decisão sobre o RV-03 (EXIF)

**Não bloqueia; vira o SEC-10-01, para o architect.** Motivos:

1. O fluxo previsto, a página `/capture`, já remove EXIF e trailer. Confirmei no código que o `capture.js` nunca envia o arquivo original: `prepare()` sempre desenha no canvas e reencoda.
2. O desvio exige o token de sessão, ou seja, um ato deliberado da dupla. Não é possível para um terceiro na LAN.
3. Não há violação do R-02 (o §8 prevê o backup no Drive pessoal) nem da parte de "pessoas identificáveis" do R-14. O dano é a localização da casa de um membro da dupla, num armazenamento privado da própria dupla.
4. A correção muda a regra "bytes recebidos" do §4.2, passo 4, e por isso é mudança de SPEC, não de r2.

A janela para decidir é **antes do primeiro backup do dataset no Drive**. Depois disso, as fotos com GPS já estariam fora do notebook.

## Decisão sobre o RV-04 (`fsync` do diretório)

**Não bloqueia; vira o SEC-10-02.** É uma questão de durabilidade e integridade sob falha física, sem vetor remoto e sem impacto em confidencialidade ou acesso. A SPEC-011, que já acusa linhas sem arquivo, é um controle compensatório suficiente para a entrega. A correção (`fsync` do diretório pai depois do `rename` e do `mkdir`) é barata e deve ser feita junto com a revisão da escrita de arquivos da borda na **SPEC-025**, a critério do architect.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | ✅ O modo coleta herda o `require_header_token` antes do `request.form()` (`secrets.compare_digest` em bytes, com limite de tamanho). O CA-14 cobre 401 sem token e com token errado, sem gravar nada. Console só em loopback; `/capture` com token na query e `Referrer-Policy`/`no-store` herdados. |
| Entradas validadas: tamanho, tipo real, regex, `extra="forbid"` | ✅ 413 no corpo e no campo; 415 com `load_capture_image` (pixels + Pillow) no limitador; `re.fullmatch` com `re.ASCII` em `item_id`; `fullmatch("[0-4]")` antes do `int()`; igualdade exata em `object_type`, `grade` e `labeler`; `notes` ≤ 200 sem `Cc`/`Cs`; nome de arquivo sempre montado pelo servidor. Não há modelo Pydantic de entrada (é `multipart`), e os campos desconhecidos são ignorados, com no máximo 16. Ressalvas baixas: SEC-10-03 e SEC-10-04. |
| SQL parametrizado | N/A (a SPEC não acessa banco). |
| RLS; `DATABASE_URL`/`service_role` só na API | N/A. |
| CORS fechado ou mínimo | ✅ Nenhum `CORSMiddleware` adicionado. |
| Logs sem segredos e sem payloads de imagem | ✅ Os logs têm só `image_path`, `item_id`, `item_images` e os detalhes fixos dos erros. Não registram `notes`, `User-Agent`, token nem bytes. O `RequestLogMiddleware` (SPEC-007) registra a rota sem query. |
| Dependências novas | ✅ Nenhuma (sem mudança em `pyproject.toml` nem em `uv.lock`). |
| Deploy | N/A (só borda/LAN). `DATASET_DIR` está documentado no `.env.example`, com aviso de mantê-lo fora do Git; `ml/data/` está no `.gitignore`. |
| R-02 (nada sai da LAN) | ✅ `collect.py` não importa cliente HTTP; `collect()` não chama `Inferencer` nem `sink` (CA-12); nenhuma rota serve `DATASET_DIR` (CA-13; `StaticFiles` só em `STATIC_DIR`); a resposta tem só o caminho relativo. |
| R-14 / §9 (permissões e privacidade) | ✅ Modos exatos `0700`/`0600` com `chmod`/`fchmod` explícito, sem alterar o que já existia (CA-18 e testes extras com umask `000`/`277`). Lembrete "Sem pessoas no quadro" na página. Ressalvas baixas: SEC-10-01 e SEC-10-08. |
| Escrita concorrente | ✅ `threading.Lock` + `flock` (CA-08 e CA-09, mais o teste do tester com dois apps); `O_NOFOLLOW` no manifest e no lock; temporário `0600` + `fsync` + `rename`; rollback por `ftruncate` e remoção da imagem. Ressalvas: SEC-10-02 (durabilidade) e SEC-10-06 (info). |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. |

## Encaminhamentos

| Achado | Destino | Quando |
|---|---|---|
| SEC-10-01 (EXIF/trailer) | architect (mudança futura do §4.2, passo 4, da SPEC-010) ou SPEC-011 (validação) | Antes do primeiro backup do dataset no Drive |
| SEC-10-02 (`fsync` do diretório; órfãs) | architect → SPEC-025 (escrita da borda); SPEC-011 acusa linha sem arquivo e arquivo sem linha | Opcional; antes do treino final |
| SEC-10-03 (C1, `Zl`/`Zp`, bidi) | SPEC-011 (ler só com `csv`/`pandas`); architect (filtro no `capture_device` e em `notes`) | Na SPEC-011 |
| SEC-10-04 (fórmula em CSV) | architect (nota no `dataset-protocol.md`); SPEC-011 (exportações para planilha) | Na SPEC-011 |
| SEC-10-08 (remoção de foto com pessoa) | architect + SPEC-011 (`exclusions.csv` ou regra equivalente) | Antes do primeiro backup do dataset no Drive |
| SEC-10-05, 06, 07 | Nenhum (informativos) | — |

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs; só escrevi este relatório. Os comandos que rodei foram de leitura (`git`, `grep`, `uv tree`, `uv run pytest edge -q` uma vez) e duas sondagens em diretório temporário do scratchpad, já apagado.
- [x] Não sou autor de nenhum commit desta SPEC (nenhum commit da branch tem `Agent: security-devops`).
