# SPEC-025 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-025](../../docs/specs/SPEC-025-manutencao-borda-host-rede.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `main...56ace80` (37 arquivos, +6248/−209); foco em `d62d096..56ace80` (17 arquivos, +1358/−47), o que mudou desde o review r1 |
| Test report | [r2-test-report.md](r2-test-report.md) (PASS) |
| **Veredicto** | **APPROVED** |

Não há achado bloqueante nem alto. Ficam 6 achados baixos: RV-02 a RV-05 da r1, que continuam abertos, e RV-06 e RV-07, novos. Nenhum `SPEC_ISSUE` fica aberto.

**O SPEC_ISSUE-01 (RV-01 da r1) está resolvido** como a emenda `f4be335` define (opção c), com reaprovação humana registrada no histórico da SPEC (`046e2fd`). O código da r2 faz exatamente o que a §4.8 e a §4.9 emendadas pedem, e nada além disso:

- na coleta, a rotação EXIF dá 415 antes do disco;
- na varredura, gera o achado `orientation`, que o `--fix` não reescreve;
- o README ganhou o item 4 da §4.12.

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 (r1) | — (**resolvido**) | `edge/src/qc_edge/jpeg.py:91-113`, `edge/src/qc_edge/collect.py:401-419`, `edge/src/qc_edge/privacy.py:95-103` e `:139` | **SPEC_ISSUE-01 fechado pela opção (c).** A §4.8 manda checar `has_exif_rotation` primeiro e, se ela for falsa, chamar `strip_private_segments`. `JpegStructureError` em qualquer dos dois passos dá o 415 `unsupported JPEG structure`, e as duas recusas acontecem dentro do slot e antes do disco. O código faz isso: `ExifOrientationNotSupportedError` não herda de `JpegStructureError` e não é capturada pelo `except` de `dataset_image_bytes`. A §4.9 manda chamar `has_exif_rotation` só se `jpeg_private_findings` não levantar, transformar qualquer erro em só `invalid` e fazer o `--fix` pular `invalid` e `orientation`, com código 1. O código faz isso também. O PNG continua fora dos dois passos e é reencodado a partir da imagem já girada. O modo `inspect` não mudou. Conferi a paridade do ADR-004 de forma independente, além dos testes. No Pillow 12.3.0 do lock, `exif_transpose` faz `load()` e depois `{2: …, 8: …}.get(getexif().get(274, 1))`. Num JPEG, `getexif` só lê orientação do APP1: EXIF ou, sem a tag no EXIF, `tiff:Orientation` do XMP. Daí: (1) quando `has_exif_rotation` é falsa, a remoção não pode criar uma rotação e os dados de entropia não mudam, então o `load_image` não muda; (2) quando ela é verdadeira, nada é removido. | Nada a fazer. |
| RV-02 (r1) | baixa | `edge/src/qc_edge/privacy.py` (filtro `*.jpg`) | Sem mudança na r2: a varredura ignora `.JPG` e `.jpeg`. | **Para o architect**, numa emenda de manutenção da borda (fora desta SPEC). A sugestão da r1 continua valendo. |
| RV-03 (r1) | baixa | `edge/src/qc_edge/privacy.py` (linha do achado) | Sem mudança: o caminho relativo é impresso cru (`\n`, ANSI). | **Para o security-devops**, que vem agora, e depois para o architect, se ele quiser emendar. |
| RV-04 (r1) | baixa | `edge/src/qc_edge/privacy.py` (`_read`, l. 89, e o laço de `scan`) | Sem mudança: um arquivo ilegível dá código 1 e não aparece no stdout. | **Para o architect**: registrar o caso na §4.9 numa emenda. Opcional: imprimir `<caminho>: unreadable`. |
| RV-05 (r1) | baixa | `edge/src/qc_edge/jpeg.py` (`_walk`, "expected a marker") | Sem mudança: bytes soltos entre segmentos e `FF 00` fora da entropia dão `invalid`. | **Para o architect**: registrar o caso na lista da §4.8. Com a r2, o `docs/dataset-protocol.md` §8 já manda refotografar pela página um arquivo `invalid` ou `orientation`, o que cobre metade da sugestão da r1. |
| RV-06 | baixa | `docs/specs/SPEC-025-manutencao-borda-host-rede.md:180` (§4.8) | **Decisão 1 do dev-report e O-r2-01 do tester.** A §4.8 diz "for **um inteiro** de 2 a 8. São **exatamente os valores** que o `ImageOps.exif_transpose` aplica". Num EXIF montado à mão com tipo RATIONAL, SRATIONAL, FLOAT ou DOUBLE, o Pillow devolve `6.0` ou `IFDRational(6, 1)`, e o `exif_transpose` gira. O `in frozenset(range(2, 9))` (`jpeg.py:48` e `:111`) usa o mesmo hash e a mesma igualdade do `dict.get`, então a paridade é exata por construção. O `test_extra_odd_tiff_types_follow_the_loader` (18 tipos) mostra a equivalência tipo a tipo. **Aceito a decisão, sem SPEC_ISSUE:** "inteiro de 2 a 8" é legível como o valor (6.0 é o inteiro 6), e só essa leitura deixa as duas frases verdadeiras ao mesmo tempo. A leitura `isinstance(v, int)` violaria a garantia normativa da frase anterior (ADR-004) e reabriria o próprio SPEC_ISSUE-01. Essa leitura também é a mais conservadora para a privacidade: recusa mais e nunca grava uma foto girada. Nenhum CA depende do caso. O `except TypeError → False` (`jpeg.py:112`) também é coerente: um valor sem hash faria o `exif_transpose` levantar, e o `load_capture_image` já teria recusado a foto com 415. | **Para o architect**, numa emenda futura, só de texto: "for um valor igual a um inteiro de 2 a 8 (a mesma busca do `exif_transpose`)". Não precisa de r3. |
| RV-07 | baixa | `docs/specs/SPEC-025-manutencao-borda-host-rede.md:12` (cabeçalho) | **ADR-004 ausente do cabeçalho.** A emenda `f4be335` cita o ADR-004 na §4.8, na §4.9, no CA-19 e nas notas, mas o campo "ADRs relevantes" continua "ADR-002, ADR-003". | **Para o architect**, na mesma emenda do RV-06: incluir o ADR-004 no cabeçalho. |

Destino das pendências baixas: nenhuma justifica uma r3, que seria a última pela R-10. Sugiro que o orquestrador as registre no fechamento da SPEC, na seção de pendências do PR ou do diário. Os RV-02, RV-04, RV-05, RV-06 e RV-07 vão para uma SPEC futura de manutenção da borda, do architect, como a SPEC-025 fez com as pendências da SPEC-010. O RV-03 passa antes pelo security-devops, que decide se ele vira um SEC-25-xx.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | **Só mudou o que a emenda autorizou.** `jpeg.py` ganhou `has_exif_rotation` (§3.1, §4.8). `collect.py` ganhou `ExifOrientationNotSupportedError` e a ordem nova em `dataset_image_bytes`, e o `try/except` do `write` foi movido para lá, sem mudar o 415 estrutural. `privacy.py` ganhou `orientation` e `UNFIXABLE_FINDINGS` (§4.9). Em `app.py`, só a docstring mudou. O README ganhou o item 4 da §4.12 e uma linha na tabela de respostas. O `.env.example`, os pacotes, o contrato, o `qc_preprocess`, o `uv.lock` e os `pyproject.toml` não mudaram. Os documentos fora da SPEC (`architecture.md` §6.3, `dataset-protocol.md` §8 passo 1 e o histórico em `plan.md`) foram mudados pelo próprio architect no `f4be335`, com reaprovação humana em `046e2fd`. Os commits do orquestrador (`5641815`, `046e2fd`, `9e3a63f`, `56ace80`) só mudam o status e o histórico. A rastreabilidade do dev-report cobre os CAs tocados (11, 13, 15 e 19). As decisões 2 a 6 seguem a §4.8 e a §4.9 sem estender requisito. A decisão 1 está avaliada no RV-06. |
| 2. Regras inegociáveis | ✅ | **R-01/R-12:** nenhuma dependência nova; `api/` e `dashboard/` não foram tocados. **R-02:** `has_exif_rotation` só lê bytes em memória, e a varredura continua sem rede. **R-03:** a busca no diff r2 por `password`, `secret`, `api_key`, conninfo com senha, `eyJ` e `token = "…"` não achou nada; os marcadores dos testes vêm de `secrets`. **R-04:** sem mudança de contrato. **R-07:** os 9 commits desde a r1 têm `Agent:`. O `architect` (`f4be335`) tocou só `docs/`. O `developer` (`2c4f4b8`, `fb20890`, `40f7597`, `7fc90c0`) tocou só `edge/src`, `edge/tests` fora de `acceptance/` (inclusive o `conftest.py`, cujas fixtures novas não são usadas pelo `test_spec_025.py`), o README e o dev-report. O `tester` (`b5b12f8`) tocou só `edge/tests/acceptance/test_spec_025.py` e o test-report. **R-09:** nenhum `SPEC_ISSUE` aberto. **R-13:** todos os commits são de `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits com `Refs: SPEC-025`; nenhuma empresa citada. **R-14:** a foto com rotação nunca é gravada no dataset com metadados. O WARNING da recusa (`collect refused: invalid image: EXIF orientation not supported`) não traz o valor, e o exploratório do tester confirma que nenhum log `qc_edge` tem a latitude nem a orientação. |
| 3. Corretude | ✅ | Paridade do ADR-004 conferida no código do Pillow (RV-01). **Casos de borda revisados:** (1) MPO: `jpeg_factory` fica registrado como `JPEG`, então `formats=("JPEG",)` também abre o MPO, e o tester cobre MPO com `Orientation=6`; (2) dois APP1 EXIF; (3) XMP `"60"`; (4) APP1 depois do 1º SOS. Nos três últimos, a função e o loader leem o mesmo `getexif()`, e a coerência vem da construção, não da coincidência. `MemoryError` é propagado, e qualquer outra exceção do Pillow (inclusive `DecompressionBombError` no `open`) vira `JpegStructureError` com mensagem fixa. A checagem roda na mesma `to_thread.run_sync`, dentro do slot (CA-08), sem I/O no event loop. O custo é uma releitura do cabeçalho, sem decode (dev O-02). A ordem dos achados (`app1, orientation`) é alfabética, como a §4.9 pede. |
| 4. Testes | ✅ | Test-report PASS: 197 testes, 53 dos 19 CAs. **Ajustes da r2:** (1) CA-11: entrou `orientation` na lista de trechos exigidos da seção "Modo coleta", como manda o texto emendado. (2) CA-13: `same_loaded(stored_meta, data)` confere o tamanho e `np.array_equal` pelo `load_image`, ao lado da asserção do `Image.open` da r1. (3) CA-15: `loaded_before` é capturado antes da 1ª execução, e depois do `--fix` são conferidos a forma e os pixels pelo `load_image`. Nenhuma asserção da r1 foi removida. (4) CA-19: as cinco funções seguem o texto ponto a ponto, inclusive a pré-condição `(48, 64)`, `max_concurrent_decodes=1` para provar a liberação do slot e o `captures/` igual byte a byte. **Sensibilidade:** contra o código da r1, 32 falhas, e o test-report explica por que o CA-13 e o CA-15 passam nos dois lados. **Rodei:** `uv run ruff check .` e `ruff format --check .` limpos (148 arquivos); `uv run pytest -q edge/tests` deu 904 passed. Nenhum teste antigo de outra SPEC foi ajustado nesta rodada, como a §4.7 emendada prevê. |
| 5. Qualidade | ✅ | `has_exif_rotation` é curta, tem type hints e documenta o contrato e as exceções. A constante `_ROTATION_VALUES` tem um comentário que explica a equivalência com o `dict.get`. `UNFIXABLE_FINDINGS` evita duas checagens espalhadas. As docstrings de módulo foram atualizadas. O README deixou de dizer, sem ressalva, que "os pixels não mudam" e lista os achados possíveis. |
| 6. Segurança | N/A aqui | O portão é do security-devops, que vem em seguida. Ficam com ele: a dev O-01 (logs `DEBUG` do `PIL.TiffImagePlugin` com valores de tags, que não são criados nos níveis da produção), o RV-03 e as observações O-02 e O-03 do tester na r1. |

## Avaliação das decisões do dev-report r2

- **1. Valores que contam como rotação:** aceita. Ver o RV-06.
- **2. Checagem em `dataset_image_bytes`, antes do disco:** aceita. É o ponto da §4.8, e o 415 não cria nem o `DATASET_DIR`.
- **3. `ExifOrientationNotSupportedError(CollectError)`:** aceita. Sai pelo `except CollectError` que já existia, com o detalhe fixo da SPEC.
- **4. `orientation` entra no `k` e sempre vem com `app1`:** aceita. É o que o CA-19 exige (`2 with private data`).
- **5. Complementos do README:** aceita. Não contradizem a §4.12 e deixam mais claro o código 1 com `orientation`.
- **6. Teste de log no nível `INFO`:** aceita.

## Pontos positivos

- A correção é mínima e localizada. A paridade com o loader vem da construção (mesma API do Pillow e mesma busca por hash), não de uma lista de casos.
- Os exploratórios do tester usam um critério de oráculo independente (`rotates_in_load_image`: o `load_image` antes e depois da remoção). Eles cobrem os 7 valores, o XMP, 18 tipos TIFF e estruturas incomuns, na rota, na varredura e no `--fix`.
- O caminho normal (página `/capture`) continua igual byte a byte, e o `dataset-protocol.md` diz à dupla o que fazer com uma foto `orientation`.

## SPEC_ISSUE (se houver)

Nenhum aberto. O SPEC_ISSUE-01 da r1 foi resolvido pela emenda `f4be335`, reaprovada pelo humano. A tensão de texto da §4.8 (RV-06) não é `SPEC_ISSUE`: a implementação satisfaz as duas frases na leitura por valor e a garantia normativa do ADR-004. Ela fica como sugestão de redação para o architect.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
