# SPEC-024 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-024](../../docs/specs/SPEC-024-preprocess-0-3-scans-jpeg.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `docs/pendencias-pos-003-023...cf18f7e` (branch empilhada sobre o PR #8). Código: `36f7f2c` (developer). Aceite: `e675372` (tester). |
| **Veredicto** | **PASS** |

Motivo do veredicto: nenhum achado bloqueante ou alto. A regra fecha o SEC-01 da SPEC-023. O custo de um JPEG com scans repetidos deixa de ser ilimitado (~10 min por requisição) e passa a ter um teto medido de **~2 s** por requisição, dentro do corpo de 10 MiB da borda e a 40 M pixels. Não achei como contornar a contagem. Os três achados abaixo são baixos ou informativos e vão para o architect e para a SPEC-007. Nenhum exige mudar o código desta SPEC.

**Recomendação sobre o limite: manter 64.** A justificativa está em "Limite: 64 ou menor".

## Superfície analisada

- `packages/preprocess/src/qc_preprocess/image.py`: a regra nova (`image.py:60-67`), a posição dela na ordem das verificações, as constantes e a docstring.
- `__init__.py`, `pyproject.toml` e `uv.lock`: só a versão do `qc-preprocess` muda (0.3.0), sem dependência nova.
- Testes do autor (`test_jpeg_scans.py`) e de aceite (`test_spec_024.py` e os 3 arquivos com a troca de versão): imagens sintéticas geradas em memória e nenhum binário versionado (`git diff --numstat` sem entradas binárias).
- Fora da superfície, porque não existem nesta SPEC: rotas, autenticação, CORS, SQL, logging, segredos e deploy.

Ambiente das sondagens: Pillow 12.3.0 (travado no `uv.lock`), libjpeg-turbo 3.1.4.1 empacotado na wheel, máquina de 4 núcleos. Os scripts e arquivos temporários ficaram fora do repositório. `uv run pytest -q packages/preprocess/tests` deu **234 passed**.

### A contagem fecha o SEC-01?

Sim. Conferi as três premissas da §1 da SPEC:

1. **Todo JPEG que chega ao libjpeg passa pela regra.** O `JpegImagePlugin._accept` do Pillow 12.3.0 é exatamente `prefix.startswith(b"\xff\xd8\xff")`, igual à condição da regra. Com `formats=("JPEG", "PNG")`, o único caminho até o libjpeg é o `jpeg_factory`, que só é alcançado por esse `_accept`. O PNG não decodifica JPEG embutido, porque o Pillow ignora as miniaturas do `eXIf`.
2. **A contagem nunca fica abaixo do número de scans processados.** O libjpeg só reconhece um marcador como `0xFF`, seguido de zero ou mais bytes `0xFF` de enchimento e do código. Por isso todo SOS processado corresponde a um par `FF DA` numa posição própria do arquivo. Um par não se sobrepõe a outro, porque `FF ≠ DA`, então `bytes.count` acha todos. O tester cobriu o caso `FF FF DA` (`test_extra_fill_bytes_do_not_add_markers`).
3. **Todo o fluxo decodificado é contado.** O Pillow decodifica a partir do mesmo buffer que foi contado (o tile começa no offset 0). No MPO, o `MpoImagePlugin` força o offset do quadro 0 para 0, e só esse quadro é decodificado. As miniaturas EXIF, os quadros MPO e os gain maps depois do EOI são contados e não são decodificados: o erro é só para mais.

### Tentativas de contorno

| Vetor | Resultado |
|---|---|
| JPEG com codificação aritmética (SOF9/SOF10, scans curtos que, sem dados, continuam decodificando com zeros) | **Fechado no ambiente atual.** O libjpeg-turbo da wheel do Pillow não decodifica aritmético: um progressivo aritmético válido (o `djpeg` do sistema o decodifica) vira `OSError: broken data stream`, e o `load_image` levanta `InvalidImageError` em ~10 ms, com 10 ou 64 marcadores. Ver SEC-24-02, item (c). |
| JPEG sem perdas (SOF3) | Aceito (2000×2000 decodificado). O custo é por pixel e fica limitado por `MAX_PIXELS`; os scans contam como qualquer SOS. |
| JPEG embutido (miniatura APP1, MPO, gain map, JPEG dentro de COM) | Não é decodificado (só o quadro 0, a partir do offset 0) e é contado. Sem contorno. |
| Assinatura deslocada, `FF D8 00`, conteúdo PNG | Não chega ao decodificador JPEG: o `Image.open` levanta `UnidentifiedImageError` ou vai para o PNG. Coberto pelo `test_extra_signature_must_be_at_start` e pelo CA-07. |
| Scans "baratos de bytes, caros de CPU" (EOBRUN sobre todos os blocos) | É o pior caso real, e continua limitado a 64 scans. Ver a tabela abaixo. |
| Inundação de segmentos e chunks sem nenhum scan (COM/APPn no JPEG, chunks desconhecidos ou `tEXt` no PNG) | Não é contorno da regra, é um caminho irmão. Custa de 1,5 a 2,4 s e até ~360 MB por chamada. Ver SEC-24-02. |

### Custo real do pior caso aceito (insumo do SPEC_ISSUE-01)

Montei progressivos de 6000×6600 (39,6 M pixels) com o script padrão do Pillow e repeti cada um dos 10 scans até 64 marcadores, **respeitando o corpo de 10 MiB da borda** (SPEC-007). Para cada arquivo, a tabela mostra o scan mais caro:

| Conteúdo | Arquivo-base | Base (10 scans) | Pior caso aceito (64 marcadores, ≤ 10 MiB) |
|---|---|---|---|
| Cor sólida, 4:2:0 (scans de 61 bytes) | 0,22 MiB | 0,28 s | **1,89 s** |
| Cor sólida, 4:4:4 | 0,44 MiB | 0,38 s | **1,99 s** |
| Gradiente, q=60, 4:4:4 | 0,96 MiB | 0,37 s | 1,72 s (só 50 marcadores cabem em 10 MiB) |
| Ruído, q=30, 4:2:0 | 9,41 MiB | 0,54 s | 0,60 s (só 27 marcadores cabem) |

O custo marginal fica em ~30 ms por scan a 40 M pixels. Isso é cerca de 7× os 4 ms da §4.1, e o pior caso aceito na borda é de **~2 s**, e não de 0,26 s.

O caso de 4,79 s do test-report (último scan de um progressivo texturizado de 9,3 MB repetido até 64) **não cabe no corpo da borda**. No meu análogo de 9,41 MiB, o último scan tem 5,5 MiB, e 54 cópias dão um corpo de ~308 MiB, que vira 413 antes do `load_image`. Esse número só vale para o caminho do ML (SPEC-011), que lê arquivos locais da própria dupla e não é superfície de ataque. Os ~5 s do RV-01 superestimam o resíduo de ataque, mas a conclusão do reviewer se mantém: a §4.1 precisa ser corrigida.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-24-01 | baixa (não bloqueia; **architect**, texto da SPEC) | input (DoS de CPU, documentação) | `docs/specs/SPEC-024-preprocess-0-3-scans-jpeg.md:18` e `:74` | **O resíduo está mal estimado (confirma o SPEC_ISSUE-01).** A §4.1 diz "64 × 4 ms ≈ 0,26 s". O medido é ~30 ms por scan a 40 M pixels, e o pior caso aceito na borda (≤ 10 MiB) fica em ~2 s por requisição nesta máquina, ou ~7× uma foto legítima de 40 M pixels. Os ~5 s citados pelo tester e pelo reviewer exigem um corpo bem acima de 10 MiB, que a borda recusa com 413. O código implementa corretamente a regra aprovada, e o SEC-01 está fechado (de ~10 min para ~2 s, um teto fixo). | Corrigir a §1 e a §4.1 com os números medidos (~30 ms por scan; ~2 s no pior caso dentro de 10 MiB; ~5 s só sem limite de corpo, no caminho local do ML) e registrar no histórico que o humano reconfirmou o limite. **Não exige r2 nem mudança de código:** a recomendação é manter o 64 (ver abaixo). |
| SEC-24-02 | baixa (não bloqueia; **SPEC-007**) | input (CPU e memória na borda) | `image.py` (`Image.open` → `img.load()`), comportamento herdado da SPEC-002 | **Custo por decodificação no pior caso aceito, para dimensionar o limitador.** Fora dos scans, um corpo de 10 MiB com segmentos vazios repetidos, todos aceitos pelo `load_image`, custa: 2,6 M segmentos COM, 1,52 s e 242 MB de pico; 2,6 M segmentos APP1, **2,37 s e 362 MB**; 870 mil chunks PNG desconhecidos, 1,73 s e 148 MB; 700 mil `tEXt`, 1,14 s. O custo vem do laço em Python do parser do Pillow e da lista `applist`/`private_chunks`. É linear no corpo e da mesma ordem do resíduo dos scans, então não é um contorno, e sim o piso de custo que a regra não cobre. Somado ao SEC-02 da SPEC-023 (~300 MB por imagem de 40 M pixels), o pior caso por slot do semáforo fica em **~2,5 s de CPU e ~360 MB**. | Na SPEC-007, sem mudar o `qc-preprocess`: (a) dimensionar o `BoundedSemaphore` (padrão 2) e o `decode_wait_s` (10 s) com ~2,5 s e ~360 MB por decodificação. Com 2 slots, são ~720 MB de pico, e um atacante que mantenha os dois slots ocupados faz uma requisição legítima esperar até os 10 s do `decode_wait_s` e depois receber 503. É uma degradação aceitável no notebook, dadas as pré-condições (token e hotspot); (b) **opcional e recomendado:** limites próprios da rota de captura, já que o `capture.js` reencoda para no máximo 1280 px (SPEC-007 §4.4): por exemplo, pixels ≤ 4 M (checados pelo cabeçalho, antes do `.load()`) e corpo ≤ 3 MiB. Isso divide por ~10 o custo por scan e por ~3 o das inundações, sem depender de o canvas gerar baseline (a objeção da §7 desta SPEC era à recusa de progressivo, e não a limites de tamanho). Os limites do `load_image` continuam valendo para o ML; (c) ao subir a versão do Pillow no `uv.lock`, repetir a checagem de que o libjpeg empacotado não decodifica aritmético (`features.version("libjpeg_turbo")` e um progressivo aritmético recusado). Se passar a decodificar, o custo por scan sem dados pode subir, e o limite precisa ser medido de novo. |
| SEC-24-03 | informativa (**architect**: SPEC-011 e `docs/dataset-protocol.md`) | input (falso positivo, disponibilidade) | `image.py:60-67` | **Falso positivo com dados depois do EOI.** A contagem ingênua, que é correta para a segurança (§7), também conta os pares `FF DA` que aparecem por acaso em dados binários anexados ao JPEG. Em dados aleatórios, são ~16 pares por MiB: com 6 MiB anexados, medi 95 marcadores e a rejeição. Um caso real é a "foto com movimento" (Motion Photo do Android), que anexa um vídeo MP4 de alguns MB depois do EOI. Com o limite de 64, ela é recusada a partir de ~3-4 MiB de vídeo; com 32, a partir de ~1,5-2 MiB. Na borda, o `capture.js` reencoda via canvas, então isso não acontece. No ML (SPEC-011), que lê as fotos originais do celular, a foto vira `unreadable_image`. A falha é visível e não silenciosa, mas pode tirar fotos do dataset. Não muda nada na segurança. | No `docs/dataset-protocol.md`: desligar "foto com movimento" (e recursos parecidos) na câmera usada na captura. Na SPEC-011: o relatório de dados lista as rejeições por motivo, com a mensagem `JPEG scans` separada, para o problema aparecer cedo. Não truncar a contagem no primeiro `FF D9`: esse par pode aparecer dentro de um APPn/COM, e a contagem ficaria abaixo do número de scans, o que reabriria o contorno. |

## Limite: 64 ou menor

**Recomendação: manter 64.** Motivos:

1. **O teto real é aceitável.** Dentro do corpo da borda, o pior caso medido é de ~2 s por requisição, com 2 decodificações simultâneas no máximo (SPEC-007 §4.6) e com as pré-condições do SEC-01 (token de sessão do QR e acesso ao hotspot da dupla).
2. **Baixar o limite rende pouco.** Com 32, o resíduo dos scans cairia para ~1 s, mas as inundações de segmentos (SEC-24-02) já custam de 1,5 a 2,4 s sem nenhum scan. O pior caso da rota continuaria em ~2,4 s, agora pela inundação de APP1.
3. **Baixar o limite custa em outro lugar.** O limite está no pacote compartilhado (ADR-004): mudá-lo afeta o ML e aumenta os falsos positivos do SEC-24-03. A margem sobre o maior script padrão (18 scans, CMYK) cairia de 3,5× para 1,8×.
4. **Existe uma alavanca melhor.** Se a dupla quiser mais margem, o caminho é o SEC-24-02 (b): limites próprios da rota de captura na SPEC-007 (pixels e corpo), que cortam scans e inundações juntos e não tocam no `qc-preprocess`.

Se o humano preferir 32, isso é uma SPEC nova (0.3.x/0.4.0), como o reviewer já registrou, e não uma r2 desta.

## Destino de cada achado

| Achado | Bloqueia a SPEC-024? | Destino |
|---|---|---|
| SEC-24-01 (= SPEC_ISSUE-01 / RV-01) | Não | Architect: corrigir a §1 e a §4.1; humano reconfirma o 64 |
| SEC-24-02 | Não | SPEC-007 (dimensionamento do limitador; limites próprios da rota, opcionais; checagem do aritmético ao atualizar o Pillow) |
| SEC-24-03 | Não | Architect: `docs/dataset-protocol.md` e SPEC-011 |
| SEC-01 da SPEC-023 | — | **Fechado** por esta SPEC (resíduo limitado e medido) |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: nenhuma rota nesta SPEC |
| Entradas validadas: tamanho, tipo real da imagem (Pillow), regex de IDs, `extra="forbid"` | ✅ A regra roda antes do `Image.open`, sobre a mesma assinatura que o Pillow usa, e não tem estado. A contagem custa ~7,5 ms em 10 MiB. Sem contorno encontrado. Os resíduos estão em SEC-24-02 e SEC-24-03 |
| SQL sempre parametrizado | N/A |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | N/A |
| CORS fechado ou mínimo | N/A |
| Logs sem segredos e sem payloads de imagem | ✅ Nenhum log novo. A mensagem traz só a contagem e o limite (`too many JPEG scans: N scan markers, limit 64`), sem bytes da imagem |
| Dependências novas mantidas, com licença compatível e sem CVE crítica | ✅ Nenhuma. O `uv.lock` muda só a versão do `qc-preprocess` |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A |
| Privacidade das imagens (R-02, R-14) | ✅ Sem I/O de rede; imagens de teste sintéticas, geradas em memória; nenhum binário no Git |
| Segredos (R-03) | ✅ Nenhum padrão de chave, token, senha ou JWT no diff. Os relatórios citam só `postgresql://postgres@localhost:55432/partqc_test`, sem senha, e nenhuma credencial fictícia literal em URL/conninfo |
| Separação de papéis e identidade (R-07, R-13) | ✅ Todos os commits como `Carlos Moises <179777237+CarlosZeyy@users.noreply.github.com>`, com `Refs: SPEC-024` e `Agent:` coerente com os arquivos tocados (developer: produção e testes do autor; tester: `tests/acceptance/`; orchestrator: status) |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| (nenhuma) | — | — | O `uv.lock` muda só `qc-preprocess` 0.2.0 → 0.3.0 |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
