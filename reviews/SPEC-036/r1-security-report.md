# SPEC-036 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-036](../../docs/specs/SPEC-036-importacao-de-fotos.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...60ba044` (`origin/main` = `31979b9`; a `main` local está atrás e não inclui o PR #45) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante, alto ou médio. Os três achados são baixos e não pedem rodada nova. Ficam como pendências de manutenção (SEC-36-01 e SEC-36-03 na próxima manutenção da borda; SEC-36-02 já está no escopo da SPEC-032). As duas reaprovações delegadas (ADR-019) estão dentro dos limites.

## Superfície analisada

- **CLI nova** `python -m qc_edge.importer` (`edge/src/qc_edge/importer.py`). Ela recebe entradas não confiáveis: fotos reais de terceiros (com EXIF, GPS, XMP, ICC e vídeo de "foto com movimento") e imagens de datasets públicos baixadas da internet, além de um plano CSV e do registro `ml/external_sources.csv`. Ela também escreve em `DATASET_DIR` (imagens, `manifest.csv` e `sources.csv`).
- `edge/src/qc_edge/jpeg.py`: a função nova `exif_orientation`, e o `has_exif_rotation` passa a delegar a ela.
- `edge/src/qc_edge/collect.py`: gravadores e leitores extraídos (`read_csv_rows`, `read_manifest_entries`, `append_csv_row`, `rollback_append`, `valid_notes`, `has_forbidden_char`), mais a cobertura sem os externos e `count_external_images`.
- `edge/src/qc_edge/app.py`: uma linha nova no console (loopback), com um inteiro.
- `edge/README.md`: o procedimento, conferido contra `docs/dataset-protocol.md` §8 e §10.
- O diff não traz rota HTTP nova, mudança de autenticação, SQL, RLS, CORS, variável de ambiente, dependência nem configuração de deploy.

### O que conferi, além dos relatórios

| Ponto | Evidência |
|---|---|
| **Metadados nunca chegam ao dataset (R-14)** | A saída é sempre reencodada (`image.save(..., "JPEG", quality=90)` sem `exif`/`icc_profile`/`xmp`), e o passo 5 confere `jpeg_private_findings == frozenset()`, `has_exif_rotation` falso e o tamanho. Li o `JpegImagePlugin._save` do Pillow 12.3.0 instalado: `exif`, `xmp` e `icc_profile` vêm só dos argumentos do `save`; só o `comment` herda de `im.info` (ver SEC-36-01). Sondas fora do repositório, só com imagens geradas pelo Pillow: um JPEG com GPS, `Make`, XMP, COM e `Orientation=6` sai girado, sem `Exif`, sem XMP e sem COM; PNGs com `eXIf` (GPS e `Make`), com iTXt `XML:com.adobe.xmp` e com tEXt `Comment` saem sem nenhum desses bytes. |
| **Arquivos de entrada só lidos, nunca por link simbólico** | Fase 1: `lstat` recusa link no último componente, `realpath` dentro do `realpath` de `--inbox` recusa link de diretório que sai dela, e o tamanho é conferido pelo `lstat`, sem ler. Fase 2: `os.open(realpath, O_RDONLY \| O_NOFOLLOW \| O_NONBLOCK)`, `fstat` regular, leitura limitada a `IMPORT_MAX_BYTES + 1` e o **SHA-256 conferido contra o da fase 1**. Uma troca de diretório entre as fases (TOCTOU), que já exigiria escrita na pasta de entrada pelo próprio usuário, não grava nada diferente do que foi validado. |
| **Pasta de entrada fora do dataset** | `realpath` comparado nos dois sentidos (`is_relative_to`), inclusive por link simbólico (testes do autor e do tester). |
| **Caminho de saída sem travessia** | O `image_path` é montado só com valores validados por igualdade exata ou regex `fullmatch` com `re.ASCII` (`object_type`, `grade`, `item_id`, `angle` inteiro) e o timestamp. Nenhum valor do plano livre (`notes`, `source_ref`, `file`) entra no caminho. |
| **Escrita no dataset** | Reaproveita os gravadores da SPEC-025: `open_private_file` com `O_NOFOLLOW`, temporário por `mkstemp` no mesmo diretório, `os.replace`, `0700`/`0600` exatos (CA-10 com `umask` `0o022` e `0o277`), `flock` por linha. O rollback (CA-09) desfaz o manifest e a imagem. |
| **Bombas de descompressão e DoS** | O `exif_orientation` só abre o cabeçalho, e qualquer exceção do Pillow (inclusive `DecompressionBombError`) vira `unsupported JPEG structure`. O `load_image` aplica 40 M pixels, proporção 10:1 e 64 scans sobre os bytes limpos. Uma imagem por vez. FIFO não bloqueia (`O_NONBLOCK`). Plano limitado a 5 MiB e 5.000 linhas. |
| **Sem eco de valores (R-14, R-03)** | O stderr da fase 1 só tem códigos e nomes de coluna fixos (a tabela da correção 02). O stdout só tem `printable_path(file)`, `printable_path(image_path)` e motivos fixos. Os logs só têm número de linha, motivo fixo e `strerror`. Argumentos desconhecidos passam pelo `describe_arguments` (SPEC-025 §4.5). |
| **Sem rede (R-02)** | O `importer.py` não importa `socket`, `http`, `urllib`, `requests` nem `ssl`, e o CA-11 roda as três importações com `socket.socket` levantando `OSError`. |
| **Segredos (R-03)** | Busca por padrões de chave, token, senha, JWT, chave privada e URL com credencial no diff: nada. Nenhuma variável de ambiente nova. |
| **Console** | `app.py` interpola só um `int` (`count_external_images`), sem texto do manifest: sem XSS. |
| **Caracteres invisíveis (RV-03)** | Os U+202E, U+2028, U+00AD e U+FEFF literais do diff estão só em strings de teste (`edge/tests/`), nunca em código de produção. |
| **README e protocolo** | O `edge/README.md` e o `docs/dataset-protocol.md` §10.6 mandam a pasta de entrada para fora de `ml/data/` (exemplo `~/partqc-entrada/`), exigem a conferência visual antes de `--privacy-checked`, mandam rodar `qc_edge.privacy` e `qc_ml.data validate` depois e apagar os arquivos recebidos. O §8 deixa a pasta de entrada fora do backup. |

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-36-01 | baixa | privacy, input | `edge/src/qc_edge/importer.py:323-327` | No Pillow 12.3.0, o `JpegImagePlugin._save` usa `info.get("comment", im.info.get("comment"))`, ou seja, herda o `comment` da imagem aberta. Um PNG com um chunk tEXt/iTXt de chave `comment` (minúscula), que o `PngImagePlugin` coloca em `im.info["comment"]`, sai com um segmento COM. A conferência do passo 5 detecta (`com`) e a linha falha com `normalization check failed`. **Nada vaza**, porque a falha é fechada, mas a SPEC chama esse motivo de "erro de implementação, nunca esperado", e uma imagem legítima de dataset público com esse chunk seria recusada sem explicação. No caminho JPEG, isso não acontece: o COM é removido antes do `load_image`. Confirmado por sonda com PNG gerado pelo Pillow; as chaves `Comment` e `XML:com.adobe.xmp` não são herdadas. | Não bloqueia. Na próxima manutenção da borda: descartar os metadados herdados antes do `save` (por exemplo, `image.info.clear()` ou `image.info.pop("comment", None)`), mantendo a conferência do passo 5, e um teste com PNG de tEXt `comment` importado sem COM. |
| SEC-36-02 | baixa | privacy | `edge/src/qc_edge/importer.py:659-664`; `.gitignore:26-28` | A CLI só recusa a pasta de entrada dentro do `DATASET_DIR`. Ela aceita uma pasta dentro da árvore do Git (por exemplo, `entrada/` na raiz ou em `ml/`). O `.gitignore` diferencia maiúsculas (`core.ignorecase` não definido): `git check-ignore --no-index` **não** ignora `entrada/IMG_1234.JPG`, `entrada/a.HEIC` nem `entrada/plano.csv`. Nessa situação, uma foto com GPS e EXIF poderia ser commitada (R-14). A orientação do `edge/README.md` e do `docs/dataset-protocol.md` §10.6 (`~/partqc-entrada/`, fora do repositório) evita o caso, e a parte do `.gitignore` já é a §4.2 da SPEC-032 (`Ready`). | Não bloqueia. Ação humana: manter a pasta de entrada e o plano **fora** do repositório, como no README. Recomendo entregar a SPEC-032 antes da primeira importação real (ou, no mínimo, antes de qualquer pasta de entrada perto do repositório). Opcional, numa manutenção da borda: recusar também `--inbox` dentro da raiz do repositório (o mesmo `parents[3]` do `DEFAULT_EXTERNAL_SOURCES`). |
| SEC-36-03 | baixa | privacy (logs) | `edge/src/qc_edge/jpeg.py:126`; `edge/src/qc_edge/importer.py:972-974` | O-05 do test-report = RV-04 do review-report. Se o logger raiz estiver em DEBUG, o `PIL.TiffImagePlugin` loga os valores das tags do IFD0 ao ler a orientação. Medi com sonda: aparecem `Make`, `Artist` (que pode ter o nome de quem fotografou) e o ponteiro do IFD GPS, mas **não** as coordenadas. A CLI configura INFO quando não há handler, e o teste com o processo real confirma stdout e stderr limpos. Só ocorre se alguém chamar `main()` num processo já em DEBUG. O mesmo comportamento já existia no `has_exif_rotation` (SPEC-025). | Não bloqueia. Na próxima manutenção da borda: `logging.getLogger("PIL").setLevel(logging.INFO)` no `main` do importador e no da varredura de privacidade, com teste em DEBUG que não encontra um marcador de `Make`/`Artist` no log. |

### Avaliação das observações e achados dos outros portões

| Item | Avaliação |
|---|---|
| O-01 (hard link de fora da pasta de entrada) | Aceito. Só o próprio usuário cria o hard link, e a CLI não é fronteira de privilégio. O arquivo de fora não é alterado, e só a imagem normalizada e conferida entra no dataset. Sem achado. |
| O-02 (células com cara de fórmula) | Aceito. O `manifest.csv` e o `sources.csv` são locais, a regra é a da SPEC-010 para `notes` (SEC-10-04), e o README e o `docs/dataset-protocol.md` §5 e §10.6 avisam. Sem achado. |
| O-03 / RV-01 (diretório vazio após rollback) | Sem impacto de segurança: diretório `0700`, sem dado, ignorado pela varredura e pelo `validate`. |
| O-04 (controles e bidi em `file`) | Conferido: todo eco passa por `printable_path`. Sem achado. |
| O-05 / RV-04 | Ver SEC-36-03. |
| RV-02 (dupla gravação em execuções simultâneas) | Integridade, não privacidade: a foto gravada é a mesma, normalizada e sem metadados, com o mesmo `item_id` (sem vazamento entre splits), e o `qc_ml.data validate` acusa `duplicate_input`. Concordo que é baixo e fica para uma manutenção. |
| RV-03 (caracteres invisíveis literais nos testes) | Concordo que é baixo: higiene contra "Trojan Source" na revisão. Conferi que nenhum arquivo de produção do diff tem esses caracteres. A regra `PLE2502` do ruff, sugerida pelo reviewer, fecha o caso. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação aplicada; comparação em tempo constante | N/A: nenhuma rota nova nem alterada. O console só ganhou um inteiro, e a rota de coleta não mudou (CA-14: `XS-0001` → 422). |
| Entradas validadas: tamanho, tipo real da imagem, regex de IDs, `extra="forbid"` | ✅ Plano: cabeçalho exato, até 5 MiB e 5.000 linhas, UTF-8 estrito, regex `fullmatch` com `re.ASCII`, igualdade exata nos enums e filtro de categorias Unicode em `notes` e `source_ref`. Arquivo: até 40 MiB (pelo `lstat`, sem ler), regular, sem link, dentro da pasta de entrada. Imagem: tipo real pelo Pillow (`load_image` só aceita JPEG e PNG), limites de pixels, proporção e scans, e conferência da saída. `extra="forbid"`: N/A (sem Pydantic). Ver SEC-36-01. |
| SQL sempre parametrizado | N/A: sem banco. |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | N/A: sem banco. |
| CORS fechado ou mínimo | N/A: sem mudança no CORS. |
| Logs sem segredos e sem payloads de imagem | ✅ Os logs do `qc_edge` só têm número de linha, motivos fixos e `strerror`, nunca valor de célula, caminho absoluto, EXIF nem bytes. Ver SEC-36-03 (DEBUG do Pillow, fora do caminho normal). |
| Dependências novas | ✅ Nenhuma: `uv.lock` e `pyproject.toml` fora do diff. O Pillow 12.3.0 já estava no lock. |
| Deploy: variáveis no provedor, health check, free sem cartão | N/A: sem mudança de deploy nem variável nova. |
| Reaprovação delegada (ADR-019) | ✅ Ver abaixo. |

### Reaprovação delegada (ADR-019) [R-08, R-09]

Conferi `git show 06e13f4` (architect), `git show 6020c0c` (orquestrador) e `git show 463f4f0` (`Blocked`) contra o Histórico da SPEC.

| Critério | SPEC_ISSUE-01 (§4.2, último parágrafo, e CA-15) | SPEC_ISSUE-02 (§4.2, tabela "Coluna mostrada") |
|---|---|---|
| E-1 Origem | ✅ SPEC_ISSUE-01 de `r1-dev-report.md` | ✅ SPEC_ISSUE-02 de `r1-dev-report.md` |
| E-2 Autoria | ✅ `06e13f4`, `Agent: architect`, só `docs/specs/SPEC-036-importacao-de-fotos.md` | ✅ o mesmo commit |
| E-3 Estado | ✅ aprovada pelo humano em 2026-10-23; `Blocked` por estes SPEC_ISSUE em `463f4f0` | ✅ idem |
| E-4 Natureza | ✅ tipos 1 e 2: só o nome real da constante do `qc_ml` (`SOURCE_COLUMNS`); a mesma intenção | ✅ tipo 1: fixa a coluna de um formato de saída que o §4.2 já exigia |
| E-5 Abrangência | ✅ só o parágrafo, o CA-15, o aviso do topo e o Histórico | ✅ só o parágrafo e a tabela novos, o aviso do topo e o Histórico |
| X-1 a X-5 | ✅ nenhuma: sem SPEC ou ADR novos, sem outro documento, sem contrato, sem constante, arquivo ou assinatura novos | ✅ nenhuma: sem código, comando ou requisito novos |
| **X-6 (limites de segurança)** | ✅ nenhum limite muda: 40 MiB, 5 MiB, 5.000 linhas, 1280 px, 256 px, 40 M pixels, 64 scans, `0700`/`0600` e `--privacy-checked` estão iguais no texto antes e depois. Nenhum CA removido nem enfraquecido | ✅ idem; o CA-04 (security) não mudou de texto e ficou mais preciso |
| **X-7 (regras inegociáveis)** | ✅ o CA-15 verifica a igualdade de formato entre pacotes, não uma regra inegociável | ✅ a regra de não eco ("As mensagens nunca repetem o valor da célula"), as regras de `file` e o marcador do CA-04 (R-14) estão intactos. A tabela só nomeia colunas fixas ou `-`. Conferi no código que o stderr nunca leva valor de célula |
| X-9 | ✅ primeira correção deste trecho e deste CA | ✅ primeira correção deste trecho |
| Registro | ✅ texto antigo, texto novo, evidência e classificação no Histórico; aviso do topo e linha de aprovação no formato do ADR-019, passo 2 (`6020c0c`) | ✅ idem |

Conclusão: as duas correções estão dentro dos limites do ADR-019. Não abro nenhum `SPEC_ISSUE` "exige humano". O PR precisa da seção "Reaprovações sob o ADR-019", com `06e13f4` e `6020c0c`.

## Verificações executadas

```text
$ uv run ruff check .                 -> All checks passed!
$ uv run ruff format --check .        -> 234 files already formatted
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
6327 passed, 54 skipped, 1 warning in 441.32s (os 54 skips de sempre: Docker, extra `train` e modelo real)
```

Sondas (scripts no scratchpad da sessão, fora do repositório, só com imagens geradas pelo Pillow; nada de `~/partqc-entrada/`):

- `normalize_imported_image` sobre um JPEG com GPS, `Make`, XMP, COM e `Orientation=6`, e sobre PNGs com `eXIf` (GPS, `Make`), iTXt XMP, tEXt `Comment` e tEXt `comment`: nenhum metadado na saída; o único caso recusado é o tEXt `comment` (SEC-36-01).
- O mesmo JPEG com o logger raiz em DEBUG: o `PIL.TiffImagePlugin` loga `Make` e `Artist`, e do GPS só o ponteiro (SEC-36-03).
- `git check-ignore --no-index` para `entrada/IMG_1234.JPG`, `entrada/a.HEIC`, `entrada/plano.csv` (não ignorados) e `entrada/a.jpg` (ignorado) (SEC-36-02).

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova (`uv.lock` e `pyproject.toml` fora do diff). |

## Ações pendentes para o humano

1. **CA-17 (manual)**, exigido pela Definição de pronto antes do merge: fazer o roteiro com uma foto real de um conhecido e registrar só o tamanho original e o gravado (nunca a foto).
2. Manter a pasta de entrada e o plano **fora do repositório** (`~/partqc-entrada/`), e apagar os arquivos recebidos depois do `privacy` e do `validate` (`docs/dataset-protocol.md` §10.6). Até a SPEC-032, o `.gitignore` não protege `*.JPG`, `*.HEIC` nem o plano (SEC-36-02).
3. Antes de cada backup no Drive, o checklist do `docs/dataset-protocol.md` §8, como sempre.

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
