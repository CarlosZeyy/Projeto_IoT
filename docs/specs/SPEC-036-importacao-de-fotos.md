# SPEC-036: Importação para o dataset de fotos que não vêm da página `/capture` (`python -m qc_edge.importer`)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-035 (formatos de `sources.csv` e do registro), SPEC-030 (`printable_path` e a varredura de privacidade), SPEC-025, SPEC-010 |
| Semana alvo | S3, **antes** do `split_v1` (junto com a SPEC-035) |
| Requisitos cobertos | RF-08, RNF-05; R-02, R-11 (indireto, pelo `item_id`), R-14 |
| ADRs relevantes | ADR-020 (`Aceito`), ADR-003, ADR-004, ADR-014 |

> **Reaprovada pelo orquestrador sob o ADR-019 em 2026-10-24 (UTC)**: correção dos SPEC_ISSUE-01 e 02 de `reviews/SPEC-036/r1-dev-report.md` (§4.2 e CA-15). Classificação ADR-019: SPEC_ISSUE-01 elegível; SPEC_ISSUE-02 elegível. Ver o Histórico.

## 1. Contexto

O ADR-020 admite no dataset fotos de conhecidos e imagens externas licenciadas. Hoje, o único caminho de entrada é a página `/capture` (SPEC-010, `docs/architecture.md` §6.3), e o protocolo proíbe copiar arquivos para `raw/` (`docs/dataset-protocol.md` §8). Esta SPEC cria o segundo caminho: uma CLI da borda que lê os arquivos recebidos numa pasta de entrada, normaliza cada imagem como a página faz e grava a imagem, a linha do manifest e a linha de `sources.csv` (formato da SPEC-035 §4.2).

**Por que na borda, e não no `qc-ml`.** A gravação reaproveita o que a coleta já tem e já foi revisado: o nome e o layout do arquivo (SPEC-010 §4.2), o `flock` do `manifest.csv.lock`, as permissões `0700`/`0600`, o `fsync` dos diretórios (SPEC-025 §4.10), a varredura estrutural do JPEG (`qc_edge.jpeg`, SPEC-025 §4.8) e o escape dos caminhos impressos (SPEC-030 §4.5). Um segundo gravador do manifest no `qc-ml` duplicaria isso e poderia divergir.

**Por que normalizar, e não gravar os bytes sem os segmentos privados** (ADR-020, opção E). Uma foto recebida como documento tem de 12 a 50 MP, quase sempre a rotação na tag EXIF `Orientation` e, às vezes, o vídeo da "foto com movimento" depois do EOI. A rota de coleta recusaria quase todas (3 MiB, 4 M pixels, 415 para a rotação). A página `/capture` grava outra coisa: a foto girada, com o lado maior em até 1280 px, reencodada em JPEG q=0,9. A importação produz o mesmo tipo de arquivo, que é também o tipo de foto que a borda recebe na demo.

## 2. Objetivo

`python -m qc_edge.importer` transforma uma pasta de arquivos recebidos e um plano CSV preenchido pela dupla em imagens de `DATASET_DIR/raw/`, linhas do `manifest.csv` e linhas do `sources.csv`, sem metadados, sem rotação EXIF, com o lado maior em até 1280 px, sem rede e sem tocar nos arquivos de entrada.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/importer.py` (novo): CLI, leitura do plano, validação, normalização e gravação (§4.1 a §4.6).
- `edge/src/qc_edge/jpeg.py`: função `exif_orientation` (§4.3).
- `edge/src/qc_edge/collect.py`: só o necessário para reaproveitar a gravação (funções de arquivo, lock e manifest já existentes) e a cobertura sem as imagens externas (§4.7). O comportamento da rota de coleta não muda.
- `edge/src/qc_edge/app.py` e o template do console: a linha das imagens externas (§4.7).
- `edge/README.md`: seção "Importar fotos de fora da página" (§4.8).
- Testes do autor em `edge/tests/` (fora de `acceptance/`).
- **Tester:** `edge/tests/acceptance/test_spec_036.py`. Nenhum ajuste em testes de aceite antigos é esperado: a rota de coleta e a varredura não mudam, e a cobertura só muda para `item_id` externos, que nenhum teste antigo usa. Se algum falhar por causa de um requisito escrito aqui, vale a regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10.

### 3.2 Fora

- Formato de `sources.csv` e do registro, validação no pipeline, split, relatório e métricas: SPEC-035.
- Detectar pessoas, rostos ou documentos automaticamente: não adotado; checagem humana (`docs/dataset-protocol.md` §10.5), confirmada pela opção `--privacy-checked`.
- Recortar caixas de datasets de detecção, baixar datasets e montar o plano: tarefa da dupla (`docs/dataset-protocol.md` §10.4).
- Aceitar `item_id` externo na rota de coleta: não; a rota continua com `^[SNOT]-\d{3}$` (SPEC-010 §4.1).
- HEIC, WebP e outros formatos: recusados (o `qc_preprocess.load_image` só lê JPEG e PNG). O conhecido envia JPEG (`docs/dataset-protocol.md` §10.2).
- Ferramentas (`T-`, `XT-`): SPEC-016. As fotos de ferramentas ficam na pasta de entrada até lá.
- Apagar os arquivos da pasta de entrada: a CLI nunca apaga; a dupla apaga depois (`docs/dataset-protocol.md` §10.6).

## 4. Requisitos detalhados

### 4.1 CLI

```text
python -m qc_edge.importer --dataset-dir <D> --inbox <I> --plan <P> --privacy-checked
                           [--external-sources <R>] [--dry-run]
```

`main(argv: Sequence[str] | None = None, *, clock: Callable[[], datetime] = <UTC agora>, sleep: Callable[[float], None] = time.sleep) -> int`. O relógio e o `sleep` são injetáveis para os testes.

- **Argumento desconhecido** → código 2, com a regra de não eco da SPEC-025 §4.5 (só nomes de opção no formato permitido; nunca valores).
- **Sem `--privacy-checked`** → código 2 e, na saída de erro, `missing --privacy-checked: check every photo by eye first (docs/dataset-protocol.md section 10.5)`, antes de ler qualquer arquivo.
- `--inbox` tem de ser um diretório existente. O `realpath` de `--inbox` não pode ser igual ao de `--dataset-dir`, nem estar dentro dele, nem contê-lo; senão, código 2 com `inbox must be outside the dataset` (os arquivos recebidos têm EXIF e não podem ir para o backup do dataset, `docs/dataset-protocol.md` §8).
- `--dataset-dir` pode não existir: é criado com `0700` na primeira gravação, como na coleta. No `--dry-run`, nada é criado.
- `--external-sources`: padrão `<raiz do repositório>/ml/external_sources.csv`, calculado a partir de `qc_edge.__file__` (`edge/src/qc_edge/` → raiz). Só é lido se o plano tiver linha `external`; ausente nesse caso → código 2 com `external sources registry not found`.
- **Sem rede (R-02):** a CLI não abre nenhuma conexão.

### 4.2 Plano (`--plan`) e validação (fase 1)

CSV UTF-8 sem BOM, lido com `csv` sobre um arquivo aberto com `newline=""`, no máximo 5 MiB e 5.000 linhas de dados. Cabeçalho **exatamente** `file,item_id,object_type,grade,labeler,angle,origin,contributor,source_id,source_ref,notes`.

A fase 1 valida o plano **inteiro** antes de qualquer gravação. Qualquer problema → código 2, nada gravado, e uma linha por problema na saída de erro, no formato `plan line <n>: <code> (<coluna>)` (`n` = número do registro CSV, cabeçalho = 1). As mensagens nunca repetem o valor da célula.

| Coluna | Regra | `code` |
|---|---|---|
| `file` | caminho relativo a `--inbox`, com `/`, sem componente vazio, `.` ou `..`, sem `\` e sem NUL, até 255 caracteres; o `realpath` fica dentro do `realpath` de `--inbox`; o alvo é arquivo regular e não é link simbólico (`os.lstat`); no máximo `IMPORT_MAX_BYTES = 40 * 1024 * 1024` bytes | `invalid_file`, `file_not_found`, `file_too_large` |
| `item_id` | `contributor`: `re.fullmatch(r"[SNO]-[0-9]{3}", valor, re.ASCII)`; `external`: `re.fullmatch(r"X[SNO]-[0-9]{4}", valor, re.ASCII)`. Ordem das checagens: começa com `T-` ou `XT-` → `tools_not_supported` (ferramentas, fora do MVP); casa o formato da outra origem → `origin_item_mismatch`; não casa nenhum dos dois → `invalid_item_id` | `tools_not_supported`, `origin_item_mismatch`, `invalid_item_id` |
| `object_type` | `screw`, `nut` ou `other` (igualdade exata); coerente com a letra do tipo (`S`/`XS` → `screw`, `N`/`XN` → `nut`, `O`/`XO` → `other`) | `invalid_object_type`, `item_prefix_mismatch` |
| `grade` | como na coleta (SPEC-010 §4.1): um dos 5 graus para `screw`/`nut`, vazio para `other` | `invalid_grade`, `missing_grade`, `grade_on_other` |
| `labeler` | `a` ou `b` | `invalid_labeler` |
| `angle` | `re.fullmatch(r"[0-4]", valor)` antes de `int()` | `invalid_angle` |
| `origin` | `contributor` ou `external` | `invalid_origin` |
| `contributor` | `re.fullmatch(r"c[0-9]{2}", valor)` quando `contributor`; vazio quando `external` | `invalid_contributor` |
| `source_id` | quando `external`: `re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", valor)`, presente no registro, com `license` em `ALLOWED_LICENSES` (SPEC-035 §4.3); vazio quando `contributor` | `invalid_source_id`, `unknown_source_id`, `source_license_not_allowed`, `source_fields_mismatch` |
| `source_ref` | quando `external`: de 1 a 200 caracteres, nenhum nas categorias `Cc`, `Cs`, `Cf`, `Zl` e `Zp`; vazio quando `contributor` | `invalid_source_ref`, `source_fields_mismatch` |
| `notes` | regras da coleta (SPEC-010 §4.1 e SPEC-025 §4.11) | `invalid_notes` |

Validações entre linhas e contra o dataset:

- o mesmo `file` em duas linhas → `duplicate_file`; dois arquivos com o mesmo SHA-256 → `duplicate_input`;
- o mesmo `item_id` com dois `object_type` no plano, ou com outro `object_type` no manifest existente → `item_type_conflict`;
- `manifest.csv` existente com cabeçalho diferente do da SPEC-010 §4.2 → código 2 com `manifest header mismatch`; `sources.csv` existente com cabeçalho diferente do da SPEC-035 §4.2 → código 2 com `sources header mismatch`;
- cabeçalho do plano diferente, arquivo não UTF-8, CSV inválido, registro com número de campos diferente do cabeçalho ou mais de 5.000 linhas → `missing_column`, `unreadable_csv`, `malformed_row` ou `too_many_rows`.

**Coluna mostrada em `plan line <n>: <code> (<coluna>)`.** Para os códigos da tabela acima, é a coluna da linha da tabela em que o código aparece. Para os demais:

| `code` | `<coluna>` |
|---|---|
| `item_type_conflict` | `item_id` |
| `duplicate_file`, `duplicate_input` | `file` |
| `missing_column` | o nome de cada coluna ausente, um problema (uma linha) por coluna, por exemplo `plan line 1: missing_column (notes)`; `-` quando nenhuma coluna falta (ordem errada ou coluna a mais) |
| `malformed_row`, `unreadable_csv`, `too_many_rows` | `-` |
| `source_fields_mismatch` | `source_id` ou `source_ref`, a que estiver preenchida numa linha `contributor` (um problema por coluna, se as duas estiverem) |
| `item_prefix_mismatch` | `object_type` |

**Já importado (retomada):** a fase 1 calcula o SHA-256 de cada arquivo. A linha cujo hash já está no `input_sha256` de uma linha de `sources.csv` cujo `image_path` não está em `exclusions.csv` é marcada para ser **pulada** (não é erro). Assim, rodar o mesmo plano de novo, depois de uma interrupção, só importa o que falta, e uma foto excluída por engano pode ser importada de novo.

`qc_edge.importer.SOURCES_COLUMNS` é igual a `qc_ml.data.SOURCE_COLUMNS` (no singular, o nome criado pela SPEC-035), `qc_edge.importer.ALLOWED_LICENSES` é igual a `qc_ml.data.ALLOWED_LICENSES` e `qc_edge.collect.MANIFEST_COLUMNS` é igual a `qc_ml.data.MANIFEST_COLUMNS` (CA-15).

### 4.3 Normalização da imagem (fase 2)

```python
# qc_edge/jpeg.py
def exif_orientation(data: bytes) -> int        # 1 a 8; 1 quando ausente ou fora da faixa
# qc_edge/importer.py
def normalize_imported_image(data: bytes) -> tuple[bytes, int, int]   # (JPEG, largura, altura)
```

- `exif_orientation` faz a mesma busca do `has_exif_rotation` (SPEC-025 §4.8: `getexif()` só do cabeçalho, valor igual a um inteiro de 1 a 8, inclusive `6.0` e `IFDRational(6, 1)`). Qualquer exceção do Pillow (salvo `MemoryError`) → `JpegStructureError`. Vale `has_exif_rotation(data) == (exif_orientation(data) in range(2, 9))`.
- `normalize_imported_image`, nesta ordem:
  1. **JPEG** (começa com `FF D8 FF`): `o = exif_orientation(data)`; `limpo = strip_private_segments(data)` (tira APP1, APP13, COM e tudo depois do EOI, inclusive o vídeo da "foto com movimento"); `img = qc_preprocess.load_image(limpo)` (limites de 40 M pixels, proporção 10:1 e 64 scans sobre os bytes **limpos**); aplica a `o` com a mesma tabela do `ImageOps.exif_transpose` (2: `FLIP_LEFT_RIGHT`, 3: `ROTATE_180`, 4: `FLIP_TOP_BOTTOM`, 5: `TRANSPOSE`, 6: `ROTATE_270`, 7: `TRANSVERSE`, 8: `ROTATE_90`).
     **PNG** ou qualquer outro conteúdo: `img = qc_preprocess.load_image(data)`, que recusa o que não é JPEG nem PNG.
  2. **Redução:** com `L = max(largura, altura)` e `C = min(largura, altura)`, se `L > 1280`, o lado maior vira 1280 e o menor `(C * 1280 + L // 2) // L` (aritmética inteira), com `Image.Resampling.LANCZOS`. Se `L <= 1280`, o tamanho não muda.
  3. Se o lado menor final for menor que 256 (o `resize_shorter` do `preprocessing.json`) → recusa `image too small`.
  4. **Codificação:** `img.save(buffer, "JPEG", quality=90)`, sem `exif`, `icc_profile`, `progressive` nem `optimize`.
  5. **Conferência:** `jpeg_private_findings(saida) == frozenset()`, `has_exif_rotation(saida)` falso e `qc_preprocess.load_image(saida).size == (largura final, altura final)`. Se alguma falhar → recusa `normalization check failed` (erro de implementação, nunca esperado).
- **Por que tirar os segmentos antes do `load_image`:** o vídeo da "foto com movimento" tem pares `FF DA` por acaso (~16 por MiB), e o `load_image` recusa o arquivo original por scans (`docs/dataset-protocol.md` §3). A remoção é estrutural (SPEC-025 §4.8), e não um corte no primeiro `FF D9`, que a SPEC-011 §7 proíbe: os scans contados depois dela são os que o decodificador processaria. A orientação é lida **antes**, porque mora no APP1.
- **Recusas por linha** (a linha falha, as outras seguem, §4.6): `unsupported image` (`InvalidImageError` do `load_image`, salvo scans), `too many JPEG scans` (mensagem com `JPEG scans`), `unsupported JPEG structure` (`JpegStructureError`), `image too small`, `normalization check failed`.
- O ICC (APP2) do original não é copiado: o Pillow não converte o perfil de cor. Uma foto com perfil diferente de sRGB (por exemplo, Display P3) pode ficar com cores levemente diferentes. É o mesmo efeito de muitos navegadores no canvas, e é aceito.

### 4.4 Gravação (fase 2)

Para cada linha, em ordem, que não foi pulada:

1. Normaliza a imagem (§4.3), fora do lock.
2. Sob `manifest_file_lock(D)` (o mesmo `flock` da coleta e do `privacy --fix`), confere de novo os cabeçalhos do manifest e do `sources.csv` e o `item_type_conflict` (a coleta pode ter gravado entre duas linhas). Cabeçalho divergente aqui → a CLI para com código 1.
3. `ts = clock()` em UTC. Caminho `raw/<object_type>/<grade ou _>/<item_id>__<angle>__<ts:%Y%m%dT%H%M%SZ>.jpg`, como na SPEC-010 §4.2. Se o arquivo já existir **ou** o `image_path` já estiver no manifest (por exemplo, o de uma imagem excluída, cujo arquivo foi apagado; repeti-lo daria `duplicate_image_path` e `excluded_file_present` na SPEC-011): solta o lock, `sleep(1.0)` e tenta de novo com um `ts` novo, até 3 tentativas no total; depois, a linha falha com `capture already exists`.
4. Diretórios que faltam com `0700` e `fsync` do pai; a imagem por arquivo temporário `0600` no mesmo diretório, `fsync`, `rename` e `fsync` do diretório (SPEC-010 §4.2 e SPEC-025 §4.10).
5. Acrescenta a linha do manifest, com as 9 colunas da SPEC-010 §4.2: `captured_at` = `ts` (`%Y-%m-%dT%H:%M:%SZ`, o instante da importação, porque o EXIF da foto foi descartado) e `capture_device = "qc-edge-import"`. Cria o arquivo com o cabeçalho e `0600` se não existir; `fsync`; `fsync` do `DATASET_DIR` quando o arquivo é criado.
6. Acrescenta a linha de `D/sources.csv` (`image_path,origin,contributor,source_id,source_ref,input_sha256`, SPEC-035 §4.2), com as mesmas regras do passo 5.
7. Solta o lock e imprime `imported <file> -> <image_path>`.

- **Falha de E/S** no passo 4 ou 5: apaga a imagem gravada, devolve o manifest ao tamanho anterior (como o `DatasetWriter`), e a CLI para com código 1. No passo 6: devolve o manifest ao tamanho anterior (`ftruncate` e `fsync`), apaga a imagem e para com código 1. Nos dois casos, nenhuma linha de uma imagem fica sem a outra, salvo uma queda de energia entre os passos 5 e 6, que a SPEC-035 acusa como `missing_source` nas externas (SPEC-035 §7).
- **Por que o manifest antes do `sources.csv`:** uma linha de `sources.csv` sem imagem no manifest seria um erro permanente (`source_unknown_image`), porque os dois arquivos só crescem. Já uma linha do manifest sem origem, depois de uma queda de energia, é corrigida pelo procedimento normal de exclusão (`docs/dataset-protocol.md` §10.7).
- **Permissões:** como na coleta (SPEC-010 §4.2, item 5), exatas seja qual for o `umask`; `sources.csv` com `0600`. `DATASET_DIR` e arquivos que já existiam não mudam de modo.
- **`--dry-run`:** faz a fase 1 e o passo 1 de cada linha, imprime `would import <file>` ou `failed <file>: <motivo>`, e não cria nem altera nada sob `--dataset-dir`.

### 4.5 Arquivos de entrada (R-14)

- A CLI só lê os arquivos do plano, dentro de `--inbox`. Ela nunca os altera, renomeia ou apaga, e nunca lê um link simbólico (§4.2).
- Os bytes recebidos, com o EXIF, nunca são gravados sob `--dataset-dir` nem impressos. O SHA-256 do arquivo recebido é o único dado dele que entra no dataset.

### 4.6 Saída e códigos de saída

- Uma linha no stdout por linha do plano: `imported <file> -> <image_path>`, `skipped <file>: already imported`, `failed <file>: <motivo>` ou, no `--dry-run`, `would import <file>`. No fim, `imported <n>, skipped <k>, failed <f>` (no `--dry-run`, `would import <n>, skipped <k>, failed <f>`).
- `<file>` e `<image_path>` passam por `printable_path` (SPEC-030 §4.5). A saída nunca tem caminho absoluto, valor de EXIF nem outra célula do plano.
- **Uma linha com imagem recusada (§4.3) não para a importação:** as outras seguem, e o código no fim é 1. Uma falha de E/S (§4.4) para na hora, com código 1; as linhas anteriores ficam importadas e são puladas numa nova execução.
- Códigos: `0` sem falha; `1` com alguma linha `failed` ou parada por E/S; `2` para argumentos, plano, registro ou cabeçalho (nada gravado).
- Os erros detalhados vão para o `logging`, com a mesma regra de não eco.

### 4.7 Cobertura no console (SPEC-010 §4.4)

- `compute_coverage` ignora as linhas cujo `item_id` casa `re.fullmatch(r"X[SNOT]-[0-9]{4}", item_id)`: as imagens externas não contam para as metas de volume (ADR-020).
- `count_external_images(manifest_path: Path) -> int` devolve quantas linhas do manifest têm `item_id` externo (0 com o manifest ausente). O console mostra, logo depois da tabela de cobertura, `<p id="external-images">Imagens externas (só treino): <n></p>`.
- As fotos de conhecidos contam na cobertura como as da página.

### 4.8 `edge/README.md`

Seção nova "Importar fotos de fora da página", com: para que serve (ADR-020); a pasta de entrada fora de `DATASET_DIR`; o formato do plano com um exemplo de 2 linhas (uma `contributor`, uma `external`); o comando com `--privacy-checked` e `--dry-run`; o que a normalização faz; a retomada (linhas puladas); o lembrete de rodar `python -m qc_edge.privacy` e `python -m qc_ml.data validate` depois; e a referência a `docs/dataset-protocol.md` §10.

## 5. Critérios de aceite

Contexto comum: `DATASET_DIR`, a pasta de entrada e o registro em `tmp_path`; relógio falso em `2026-10-22T14:15:03Z`; `sleep` espião. Todas as imagens são geradas no teste pelo Pillow (nunca fotos reais, R-14). "Registro de teste" = `external_sources.csv` no formato da SPEC-035 §4.3 com a única linha `fonte-teste,Fonte de teste,https://example.org/fonte,CC-BY-4.0,https://creativecommons.org/licenses/by/4.0/,Fonte de teste (example.org),2026-10-20`. "Foto de celular" = JPEG cuja imagem exibida `E` tem 3000×4000 px (quadrante superior esquerdo vermelho `(220, 30, 30)`, resto cinza `(128, 128, 128)`), gravada com os pixels `E.transpose(Image.Transpose.ROTATE_90)` (4000×3000) e EXIF com `Orientation=6` e o IFD GPS (`GPSLatitude`). "Linha de conhecido" = `S-501,screw,fair,a,2,contributor,c01,,,` e notes `dúvida fair/poor`.

- **CA-01 (rotação e redução)** — *Dado* a foto de celular e um plano com a linha de conhecido, *quando* a CLI roda com `--privacy-checked`, *então* sai com 0; o stdout tem `imported <file> -> raw/screw/fair/S-501__2__20261022T141503Z.jpg` e termina com `imported 1, skipped 0, failed 0`; o arquivo gravado é JPEG com 960×1280 px, `jpeg_private_findings` vazio, `has_exif_rotation` falso, `len(Image.open(<arquivo>).getexif()) == 0`, e não contém `b"Exif\x00\x00"`; a média do quadrado de 100×100 px no canto superior esquerdo tem R > 180, G < 70 e B < 70; a média da diferença absoluta entre `qc_preprocess.load_image(<gravado>)` e `qc_preprocess.load_image(<original>).resize((960, 1280), Image.Resampling.LANCZOS)` é no máximo 4 por canal; o manifest tem 1 linha com `captured_at=2026-10-22T14:15:03Z`, `capture_device=qc-edge-import`, `labeler=a`, `angle=2` e `notes=dúvida fair/poor`; e `sources.csv` tem o cabeçalho da SPEC-035 §4.2 e 1 linha com `origin=contributor`, `contributor=c01`, `source_id` e `source_ref` vazios e `input_sha256` igual ao `hashlib.sha256` do arquivo de entrada.
- **CA-02 (foto com movimento)** — *Dado* um JPEG 1000×750 do Pillow com o EXIF GPS e `Orientation=1`, seguido, depois do EOI, de `b"\x00\x00\x00\x18ftypmp42"`, `b"\xff\xda" * 100` e 1 MiB de `b"\x00"` (o teste confere antes que `qc_preprocess.load_image(<arquivo>)` levanta `InvalidImageError` com `JPEG scans`), *quando* é importado como linha de conhecido, *então* sai com 0, o arquivo gravado tem 1000×750 px, não contém `b"ftypmp42"` e tem `jpeg_private_findings` vazio.
- **CA-03 (externa, PNG)** — *Dado* um PNG RGBA 2048×1024 e o registro de teste, *quando* é importado com a linha `XS-0001,screw,perfect,b,0,external,,fonte-teste,dataset/train/0001.png,`, *então* sai com 0; o arquivo gravado é `raw/screw/perfect/XS-0001__0__20261022T141503Z.jpg`, JPEG RGB de 1280×640 px; e a linha de `sources.csv` tem `origin=external`, `contributor` vazio, `source_id=fonte-teste` e `source_ref=dataset/train/0001.png`.
- **CA-04 (security, plano inválido)** — *Dado* o registro de teste e `DATASET_DIR` com um manifest de 1 linha inserida à mão (`S-500` com `object_type=nut`, como no CA-06 da SPEC-010), *quando*, em casos separados (um teste por caso, sempre na linha 2 do plano), a linha tem `file` igual a `../fora.jpg`, a um caminho absoluto, a um link simbólico da pasta de entrada para um JPEG fora dela, a um arquivo inexistente ou a um arquivo esparso de `40 * 1024 * 1024 + 1` bytes; `item_id` igual a `S-50`, `XS-001`, `T-001` ou `XT-0001`; `item_id=N-501` com `screw`; `item_id=S-500` com `screw`; uma linha `external` com `S-501`; uma `contributor` com `XS-0001`; `contributor=c1`; `source_id=nao-registrada`; a fonte do registro com `license=CC-BY-ND-4.0` ou com `license=CC-BY-NC-SA-4.0`; `source_ref` vazio numa `external`; `source_ref` preenchido numa `contributor`; `angle="2\n"`; `notes` com U+2028; `item_id=O-501` com `other` e `grade=good`; o mesmo `file` em duas linhas; dois arquivos com os mesmos bytes; ou o plano sem a coluna `notes`, *então* a CLI sai com 2, a saída de erro tem a linha `plan line 2: <code> (<coluna>)` com, respectivamente, `invalid_file` (3 casos), `file_not_found`, `file_too_large`, `invalid_item_id` (2 casos), `tools_not_supported` (2 casos), `item_prefix_mismatch`, `item_type_conflict`, `origin_item_mismatch` (2 casos), `invalid_contributor`, `unknown_source_id`, `source_license_not_allowed` (2 casos), `invalid_source_ref`, `source_fields_mismatch`, `invalid_angle`, `invalid_notes`, `grade_on_other`, `duplicate_file`, `duplicate_input` (nestes dois, na linha 3) e `missing_column` (linha 1); e o conteúdo de `DATASET_DIR` (nomes e bytes) fica igual ao de antes. *Dado* um `source_ref` com um marcador gerado no teste seguido de U+202E, *então* nem o stdout, nem a saída de erro, nem o log contêm o marcador.
- **CA-05 (security, argumentos)** — *Quando* a CLI roda (a) sem `--privacy-checked`, com um `--plan` inexistente; (b) com `--token=<marcador>`; (c) com `--inbox` igual a `DATASET_DIR/entrada`; (d) com `DATASET_DIR` dentro de `--inbox`; (e) com uma linha `external` e `--external-sources` inexistente; (f) com o manifest existente de cabeçalho diferente; (g) com `sources.csv` existente de cabeçalho diferente, *então* sai com 2 em todos os casos e nada é gravado; a saída de erro contém, respectivamente, `missing --privacy-checked`, (nada com o marcador, nem no log), `inbox must be outside the dataset` (em c e d), `external sources registry not found`, `manifest header mismatch` e `sources header mismatch`.
- **CA-06 (recusas por linha)** — *Dado* um plano de conhecido com 4 linhas: (1) um JPEG 800×600 válido; (2) um arquivo `x.heic` com `b"\x00\x00\x00\x18ftypheic" + b"\x00" * 100`; (3) um JPEG 300×200; (4) outro JPEG 800×600 válido, *quando* a CLI roda, *então* sai com 1; o stdout tem `failed x.heic: unsupported image`, `failed <arquivo 3>: image too small` e duas linhas `imported`, e termina com `imported 2, skipped 0, failed 2`; o manifest e o `sources.csv` têm 2 linhas cada; e nenhum arquivo temporário sobra sob `DATASET_DIR`.
- **CA-07 (retomada e exclusão)** — *Dado* o resultado do CA-03, *quando* a mesma CLI roda de novo, *então* sai com 0, o stdout tem `skipped <file>: already imported` e `imported 0, skipped 1, failed 0`, e o manifest e o `sources.csv` não mudam. *Dado*, depois, a imagem gravada apagada e o `image_path` dela registrado em `exclusions.csv` (`reason=other`), com o relógio no mesmo instante da primeira importação e o `sleep` espião avançando o relógio 1 s por chamada, *quando* a CLI roda de novo, *então* sai com 0 e importa a imagem outra vez, com um `image_path` diferente do excluído (1 s depois), e o manifest não tem `image_path` repetido.
- **CA-08 (nome repetido)** — *Dado* um relógio que só avança quando o `sleep` espião é chamado (1 s por chamada) e um plano com 2 linhas de conhecido com o mesmo `item_id` (`S-501`), o mesmo `angle` (0) e arquivos diferentes, *quando* a CLI roda, *então* sai com 0, os dois arquivos existem, o segundo com o horário 1 s depois do primeiro, e o `sleep` foi chamado 1 vez com `1.0`. *Dado* um relógio que nunca avança, *então* a segunda linha termina com `failed <file>: capture already exists`, o `sleep` foi chamado 2 vezes e a CLI sai com 1.
- **CA-09 (security, atomicidade)** — *Dado* um plano com a linha de conhecido e um espião que levanta `OSError(errno.ENOSPC, ...)` na escrita do `sources.csv`, *quando* a CLI roda, *então* sai com 1, o `manifest.csv` fica igual, byte a byte, ao de antes, nenhuma imagem nem temporário sobra sob `raw/`, e o `sources.csv` não ganha linha. *Dado* o espião na escrita do `manifest.csv`, *então* sai com 1, a imagem não sobra e o `sources.csv` fica igual ao de antes.
- **CA-10 (security, permissões, R-14)** — *Dado* `os.umask(u)` com `u` em `0o022` e `0o277` (uma execução por valor, com o umask original restaurado no fim) e `DATASET_DIR` inexistente, *quando* a linha de conhecido e a linha externa do CA-03 são importadas, *então* `stat.S_IMODE` dá `0o700` para `DATASET_DIR`, `raw/` e os subdiretórios criados, e `0o600` para as 2 imagens, o `manifest.csv`, o `sources.csv` e o `manifest.csv.lock`. *Dado* `DATASET_DIR` já existente com `0o755`, *então* ele continua `0o755`.
- **CA-11 (security, R-02, R-14)** — *Dado* `socket.socket` substituído no teste por uma função que levanta `OSError`, *quando* os planos dos CA-01, CA-02 e CA-03 são importados no mesmo `DATASET_DIR`, com o relógio avançado 1 s entre as execuções, *então* as três execuções saem com 0; `python -m qc_edge.privacy --dataset-dir <D>` sai com 0 e termina com `checked 3 images, 0 with private data`; e os arquivos da pasta de entrada têm os mesmos bytes e o mesmo `st_mtime_ns` de antes.
- **CA-12 (`--dry-run`)** — *Dado* os três arquivos dos CA-01 a CA-03 num plano e `DATASET_DIR` inexistente, *quando* a CLI roda com `--dry-run`, *então* sai com 0, o stdout tem três linhas `would import` e termina com `would import 3, skipped 0, failed 0`, e `DATASET_DIR` continua inexistente.
- **CA-13 (cobertura)** — *Dado* um manifest com 3 linhas de `S-001` (`screw`, `perfect`) e 5 linhas de `XS-0001` a `XS-0005` (`screw`, `perfect`), *quando* `compute_coverage` é chamado, *então* a célula `(screw, perfect)` tem 3 imagens e 1 peça, e `count_external_images` devolve 5; e o console (loopback) contém `<p id="external-images">` com `5`.
- **CA-14 (a rota de coleta não muda)** — *Dado* uma coleta válida (SPEC-010 CA-01) com `item_id=XS-0001`, *quando* é enviada a `POST /api/capture`, *então* a resposta é 422 e `DATASET_DIR` não ganha imagem nem linha.
- **CA-15 (formatos iguais aos do `qc-ml`)** — *Dado* os pacotes `qc-edge` e `qc-ml` instalados (`pytest.importorskip("qc_ml.data")`), *então* `qc_edge.importer.SOURCES_COLUMNS == qc_ml.data.SOURCE_COLUMNS`, `qc_edge.importer.ALLOWED_LICENSES == qc_ml.data.ALLOWED_LICENSES` e `qc_edge.collect.MANIFEST_COLUMNS == qc_ml.data.MANIFEST_COLUMNS`; e, depois de importar os planos dos CA-01 e CA-03, `qc_ml.data.load_manifest(<D>, external_sources=<registro de teste>)` não levanta erro e dá `origin` `contributor` e `external` nas duas linhas.
- **CA-16 (README)** — *Dado* `edge/README.md`, *quando* se isola o trecho da seção cujo título contém `Importar fotos de fora da página` até o próximo título de nível igual ou superior, *então* ele contém `python -m qc_edge.importer`, `--privacy-checked`, `--dry-run`, `sources.csv`, `python -m qc_edge.privacy` e `dataset-protocol.md`.
- **CA-17 (manual)** — 1. um conhecido envia pelo WhatsApp, como **documento**, uma foto de um parafuso tirada em retrato; 2. salvar o arquivo na pasta de entrada (fora de `ml/data`); 3. olhar a foto e conferir que não há pessoa, rosto, documento nem endereço; 4. preencher o plano com uma linha `contributor`; 5. rodar a CLI com `--dry-run` e depois sem ele; 6. abrir o arquivo gravado: está em pé, com o lado maior de 1280 px; 7. `python -m qc_edge.privacy --dataset-dir ml/data` → `0 with private data`; 8. `python -m qc_ml.data validate --dataset-dir ml/data` sem problemas; 9. apagar o arquivo da pasta de entrada. Registrar no test-report o tamanho original e o gravado (sem a foto).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Cada regra do plano; `exif_orientation` (1 a 8, ausente, `6.0`, `IFDRational`, só no XMP); a tabela de rotação; redução (arredondamento inteiro, lado menor < 256); conferência da saída; gravação e rollback; retomada; colisão de nome; cobertura | `edge/tests/` |
| Aceite (tester) | Um por CA automatizável | `edge/tests/acceptance/test_spec_036.py` |
| Manual (dupla) | CA-17 | celular de um conhecido + notebook |

- Mock só de fronteiras: relógio, `sleep`, `socket.socket` (CA-11) e a escrita de arquivo nos casos de erro (CA-09). Sistema de arquivos real em `tmp_path`.
- O CA-04 cria o arquivo de 40 MiB + 1 como arquivo esparso (`os.truncate`), sem ocupar o disco.
- Os JPEGs com EXIF, GPS e trailer são montados no teste, como na SPEC-025 §5. Nunca fotos reais (R-14).

## 7. Riscos e notas para o implementador

- **Memória:** uma foto de 40 M pixels ocupa ~120 MB decodificada, mais a cópia girada e a reduzida. A CLI roda uma imagem por vez, fora do servidor, então não passa pelo limitador de decodificações da borda (SPEC-007 §4.6). Não paralelize a fase 2.
- **Não use o `exif_transpose` do `load_image` para girar:** o `load_image` recebe os bytes **sem** o APP1 e não vê mais a orientação. A rotação vem do `exif_orientation` lido antes. Testar com os 8 valores.
- **Não "conserte" a contagem de scans:** o `load_image` conta os scans sobre os bytes limpos pela varredura estrutural. Não corte no primeiro `FF D9` nem reconte de outro jeito (SPEC-011 §7).
- **Não reaproveite `CollectRequest.from_fields` para validar o `item_id`:** a regex da coleta não aceita `X…` e precisa continuar não aceitando (CA-14). As outras regras (grau, `labeler`, `angle`, `notes`) podem usar as mesmas funções da coleta.
- **Lock por linha:** segurar o `flock` durante o plano inteiro faria a coleta responder 503 `server busy` por minutos (nota da SPEC-011 §7 sobre o `flock`). A normalização fica fora do lock.
- **Resolução do LANCZOS:** a página usa o redimensionamento do navegador, que não é igual ao do Pillow. A paridade que importa (ADR-004) é a do pré-processamento do treino e da borda sobre o arquivo gravado, e não a do arquivo com o canvas.
- **Plano em planilha:** a dupla pode montar o plano numa planilha, mas o `notes` e o `source_ref` que começam com `=`, `+`, `-` ou `@` podem virar fórmula. O README recomenda exportar como CSV UTF-8 e conferir essas células (SEC-10-04 de `reviews/SPEC-010/r1-security-report.md`).

## 8. Definição de pronto

- [ ] Todos os CAs automatizáveis com teste de aceite passando (test-report PASS) e o CA-17 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` atualizado (§4.8)
- [ ] SPEC-035 `Done` antes da primeira importação real (senão, o `validate` acusa os `item_id` externos e o `sources.csv`)
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-20 | SPEC criada (`Draft`). Decisões do architect: (a) CLI na borda (developer), reaproveitando a gravação, o lock, as permissões, o `fsync` e a varredura do JPEG da coleta; (b) normalização igual à da página (rotação aplicada, lado maior em até 1280 px, JPEG q=90, sem metadados), com a orientação lida antes da remoção estrutural dos segmentos, em vez de recusar a rotação EXIF como a rota de coleta; (c) plano CSV validado inteiro antes de gravar, e linhas já importadas puladas pelo SHA-256 do arquivo recebido; (d) imagem recusada não para a importação, falha de E/S para; (e) manifest antes do `sources.csv`, com rollback; (f) `--privacy-checked` obrigatório e pasta de entrada fora do dataset; (g) cobertura do console sem as imagens externas. | Decisão do humano de 2026-10-19 (ADR-020) | Orquestrador, a pedido do humano |
| 2026-10-23 | Confirmada pelo humano, sem mudança de texto, a decisão (b): a importação aplica a rotação EXIF e reencoda (lado maior até 1280 px, JPEG q=90, sem metadados), como no ADR-020, decisão 5. CA-04: caso novo com a fonte do registro em `license=CC-BY-NC-SA-4.0` → `source_license_not_allowed` (agora 2 casos), pela lista de licenças nova da SPEC-035 §4.3 (sem NonCommercial nem ShareAlike), que o §4.2 já referencia. Cabeçalho: ADR-020 `Aceito`. | Decisão do humano de 2026-10-23 | Architect, a pedido do humano |
| 2026-10-23 | Aprovada pelo humano (`Draft` → `Ready`), com as decisões confirmadas: rotação EXIF aplicada e reencode na importação, teto de 30%, faixa 500–999 só como convenção e lista de licenças sem NonCommercial nem ShareAlike. | Mensagem do humano de 2026-10-23 | Orquestrador, a pedido do humano |
| 2026-10-24 | Correção do SPEC_ISSUE-01 (§4.2, último parágrafo, e CA-15). Texto antigo do §4.2: "As constantes `SOURCES_COLUMNS` e `ALLOWED_LICENSES` de `qc_edge.importer` são iguais às de `qc_ml.data` (SPEC-035), e `qc_edge.collect.MANIFEST_COLUMNS` é igual a `qc_ml.data.MANIFEST_COLUMNS` (CA-15)." Texto novo: "`qc_edge.importer.SOURCES_COLUMNS` é igual a `qc_ml.data.SOURCE_COLUMNS` (no singular, o nome criado pela SPEC-035), `qc_edge.importer.ALLOWED_LICENSES` é igual a `qc_ml.data.ALLOWED_LICENSES` e `qc_edge.collect.MANIFEST_COLUMNS` é igual a `qc_ml.data.MANIFEST_COLUMNS` (CA-15)." CA-15, antigo: `qc_edge.importer.SOURCES_COLUMNS == qc_ml.data.SOURCES_COLUMNS`; novo: `qc_edge.importer.SOURCES_COLUMNS == qc_ml.data.SOURCE_COLUMNS`. O nome do lado da borda (`qc_edge.importer.SOURCES_COLUMNS`) não muda, nem a intenção (as duas tuplas com o mesmo conteúdo). Evidência: `ml/src/qc_ml/data.py:78` define `SOURCE_COLUMNS` (SPEC-035, mergeada); `qc_ml.data.SOURCES_COLUMNS` não existe, e o CA-15 ao pé da letra levantaria `AttributeError`. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-4 tipos 1 e 2 (texto que esclarece; forma de verificação do CA-15 ajustada, preservando a intenção); nenhum arquivo, assinatura ou constante nova (X-5); nada em `packages/contracts` (X-4); o CA-15 não verifica regra inegociável (X-7); primeira correção deste trecho e deste CA (X-9). | SPEC_ISSUE-01 de `reviews/SPEC-036/r1-dev-report.md` | Orquestrador (loop da SPEC-036) |
| 2026-10-24 | Correção do SPEC_ISSUE-02 (§4.2): parágrafo e tabela novos "Coluna mostrada em `plan line <n>: <code> (<coluna>)`", logo depois das validações entre linhas. Texto antigo: nenhum (o §4.2 definia o formato `plan line <n>: <code> (<coluna>)`, mas não a coluna de `item_type_conflict`, `duplicate_file`, `duplicate_input`, `missing_column`, `malformed_row`, `unreadable_csv` e `too_many_rows`). Texto novo: `item_type_conflict` → `item_id`; `duplicate_file` e `duplicate_input` → `file`; `missing_column` → o nome de cada coluna ausente, um problema por coluna, e `-` quando nenhuma falta; `malformed_row`, `unreadable_csv` e `too_many_rows` → `-`; `source_fields_mismatch` → `source_id` ou `source_ref`, a que estiver preenchida (um problema por coluna); `item_prefix_mismatch` → `object_type` (como já estava na tabela). O CA-04 não muda: a `<coluna>` esperada em cada caso passa a vir desta tabela (por exemplo, `plan line 3: duplicate_file (file)` e `plan line 1: missing_column (notes)`). Evidência: a escolha é a que o developer implementou (`edge/src/qc_edge/importer.py`, `_read_plan` e `load_plan`, `NO_COLUMN = "-"`), e o relatório mostra que o tester não teria como escrever a linha exata do CA-04 sem ela. Classificação ADR-019: elegível (E-1 a E-5 cumpridos; nenhuma exclusão). E-4 tipo 1: esclarece um formato de saída que o §4.2 já exigia, sem mudar o comportamento pedido (os mesmos códigos, o mesmo código de saída 2 e nada gravado); o valor mostrado é sempre um nome de coluna fixo ou `-`, nunca o valor da célula, e a regra de não eco não muda (X-7); nenhum CA alterado nem enfraquecido (X-6); nenhum requisito, comando ou assinatura novos (X-5); primeira correção deste trecho (X-9). | SPEC_ISSUE-02 de `reviews/SPEC-036/r1-dev-report.md` | Orquestrador (loop da SPEC-036) |
| 2026-10-24 | Correção dos SPEC_ISSUE-01 e 02 (§4.2 e CA-15) aprovada pelo orquestrador sob o ADR-019 (commit do architect 06e13f4). O código da r1 já segue o texto novo; a rodada continua no tester. | `reviews/SPEC-036/r1-dev-report.md`, SPEC_ISSUE-01 e 02 | Orquestrador (ADR-019) |
