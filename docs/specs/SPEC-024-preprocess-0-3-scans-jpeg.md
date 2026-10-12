# SPEC-024: `qc-preprocess` 0.3.0 (limite de scans do JPEG)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-023 (`qc-preprocess` 0.2.0, PR #7) |
| Semana alvo | S2 (antes de a SPEC-007 entrar em `In Dev`) |
| Requisitos cobertos | RNF-06 (entrada externa validada), RNF-07 (pré-processamento idêntico treino/borda), R-12 |
| ADRs relevantes | ADR-004 (pré-processamento compartilhado, paridade treino/borda) |

## 1. Contexto

O security-report da SPEC-023 (`reviews/SPEC-023/r1-security-report.md`, SEC-01, severidade média) mostrou que o `load_image` aceita um **JPEG progressivo com scans repetidos** e que o custo de decodificação cresce com `nº de scans × pixels`:

- cerca de 4 ms por scan a 40 M pixels, com 65 bytes por scan;
- 338 KB levaram 16 s; extrapolando para o corpo máximo da borda (10 MiB), seriam cerca de 10 min de CPU por requisição;
- a imagem é aceita e o resultado é idêntico ao da imagem limpa, então nada acusa o ataque.

O padrão JPEG não limita o número de scans, e o Pillow usa a API libjpeg, que não tem limite próprio (Red Hat Bug 1344214, citado no relatório). Na borda (SPEC-007), poucas requisições assim ocupam a CPU do notebook durante a demo.

Fatos usados nesta SPEC:

- **Scans de um JPEG comum.** A `jpeg_simple_progression` do libjpeg-turbo (o script progressivo padrão, usado também pelo Pillow com `progressive=True`) gera 10 scans para YCbCr de 3 componentes, `2 + 4·n` para `n` componentes (6 em tons de cinza, 18 em CMYK) e `6·n` acima de 4 componentes. Fonte: `src/jcparam.c`, <https://github.com/libjpeg-turbo/libjpeg-turbo/blob/main/src/jcparam.c>, consultado em 2026-10-12. Um JPEG baseline tem 1 scan (ou 1 por componente, se não for intercalado).
- **`FF DA` só aparece como marcador fora dos segmentos de parâmetros.** O marcador SOS é `X'FFDA'` (Tabela B.1). Dentro dos dados codificados por entropia, todo byte `X'FF'` gerado pelo codificador é seguido de um byte `00` de enchimento ("stuffed"), justamente para que nenhum marcador apareça ali (§B.1.1.5, nota 2). Fonte: ITU-T T.81 (ISO/IEC 10918-1), <https://www.w3.org/Graphics/JPEG/itu-t81.pdf>, páginas 32 e 33, consultado em 2026-10-12. Por isso, contar os pares de bytes `FF DA` do arquivo **nunca conta menos** scans do que o decodificador processa. Pode contar a mais quando o par aparece dentro de um segmento de parâmetros (APPn, COM) ou depois do EOI (miniatura EXIF, imagens MPO, gain map), o que, em fotos reais, dá poucas unidades.
- **Assinatura do JPEG no Pillow:** `JpegImagePlugin._accept` reconhece JPEG pelo prefixo `b"\xff\xd8\xff"` (Pillow 12.3.0, travado no `uv.lock`).

O SEC-02 (memória com uploads simultâneos), o SEC-04 (checagem da flag na subida) e o SEC-05 (filtros de `warnings`) do mesmo relatório são da borda e entram na SPEC-007.

## 2. Objetivo

`qc_preprocess` 0.3.0 rejeita com `InvalidImageError`, antes de qualquer decodificação, todo conteúdo com assinatura JPEG que tenha mais de 64 marcadores `FF DA`; para toda imagem aceita, a saída de `preprocess` continua idêntica bit a bit à da 0.2.0.

## 3. Escopo

### 3.1 Dentro

- `packages/preprocess/src/qc_preprocess/image.py` (constante `MAX_JPEG_SCANS`, a verificação nova em `load_image` e a docstring, §4.1).
- `packages/preprocess/src/qc_preprocess/__init__.py` (reexportação de `MAX_JPEG_SCANS` e `__version__ = "0.3.0"`) e `packages/preprocess/pyproject.toml` (versão `0.3.0`).
- `uv.lock` (só a versão do `qc-preprocess`).
- Testes do autor em `packages/preprocess/tests/`, incluindo a asserção de versão do `test_smoke.py`.
- **Tester desta SPEC:** `packages/preprocess/tests/acceptance/test_spec_024.py` e, **só** nas expectativas de versão do `qc-preprocess` (`"0.2.0"` → `"0.3.0"`) e nas menções de versão das docstrings de módulo:
  - `packages/preprocess/tests/acceptance/test_spec_002.py` (CA-01);
  - `packages/preprocess/tests/acceptance/test_spec_023.py` (CA-01, parte do `qc-preprocess`; as linhas do `qc-contracts` continuam `"0.2.0"`);
  - `packages/contracts/tests/acceptance/test_spec_023.py` (CA-01, parte do `qc-preprocess`).

  O developer não toca em `tests/acceptance/`.

### 3.2 Fora

- Limitador de decodificações simultâneas, checagem da flag `LOAD_TRUNCATED_IMAGES` na subida e a regra sobre filtros de `warnings` (SEC-02, SEC-04 e SEC-05): SPEC-007.
- Recusar JPEG progressivo na rota ou baixar o limite de corpo da borda (opção (b) do SEC-01): não adotado (§7).
- `qc-contracts`: não muda (continua 0.2.0).
- `preprocess`, `PreprocessParams`, `transform.py`, `params.py`, `MAX_PIXELS`, `MAX_ASPECT_RATIO` e `ACCEPTED_FORMATS`: não mudam.

## 4. Requisitos detalhados

### 4.1 `qc_preprocess` 0.3.0

- Constante pública `MAX_JPEG_SCANS: int = 64`, definida em `qc_preprocess.image` e reexportada em `qc_preprocess`, com um comentário que cite o motivo (SEC-01) e a contagem conservadora.
- `load_image(data: bytes | Path) -> PIL.Image.Image` mantém a assinatura e todo o comportamento das SPECs 002 e 023, com uma verificação nova:
  - **Posição:** depois da checagem de bytes vazios (`empty image data`) e **antes** do `Image.open`. Assim, a ordem completa fica: flag `LOAD_TRUNCATED_IMAGES` → `Path` inexistente → tipo → vazio → **scans** → `Image.open` → `MAX_PIXELS` → proporção → `.load()` → EXIF e RGB.
  - **Regra:** se `data.startswith(b"\xff\xd8\xff")` (a assinatura que o Pillow usa para JPEG) e `data.count(b"\xff\xda") > MAX_JPEG_SCANS`, levanta `InvalidImageError` com uma mensagem que contém `JPEG scans`, por exemplo `f"too many JPEG scans: {n} scan markers, limit {MAX_JPEG_SCANS}"`.
  - A contagem percorre **o arquivo inteiro**, sem interpretar segmentos. É deliberado: é O(n), não tem estado para um atacante explorar e só erra para mais (§1).
  - Conteúdo sem a assinatura JPEG (PNG, texto, outros formatos) **não** passa por essa regra. Os dados comprimidos de um PNG podem conter o par `FF DA` por acaso, e o PNG não tem scans.
- A docstring de `load_image` passa a listar a condição nova.
- `preprocess`, `PreprocessParams`, `transform.py` e `params.py` **não mudam**. A regra só rejeita imagens, e nenhuma imagem aceita muda de valor. Por isso, o `preprocessing.json` e os modelos já treinados continuam válidos (ADR-004).
- `__version__ = "0.3.0"` e `version = "0.3.0"` no `pyproject.toml`.

**Por que no `load_image` (ADR-004).** Pelo mesmo motivo da SPEC-023 §4.2: o `load_image` é a barreira usada pela borda (SPEC-007, SPEC-010) e pelo ML (SPEC-011, SPEC-012). Com a regra nele, treino e borda rejeitam as mesmas imagens.

**Por que 64.** O maior script padrão do libjpeg-turbo para até 4 componentes tem 18 scans (CMYK), e um JPEG de celular tem 1 scan, mais 1 a 3 marcadores de miniatura EXIF, MPO ou gain map. 64 dá folga de mais de 3× sobre o caso padrão mais longo. No pior caso aceito (40 M pixels), o custo extra fica em cerca de 64 × 4 ms ≈ 0,26 s, contra 16 s no exemplo do relatório.

### 4.2 Consumidores (sem código nesta SPEC)

- SPEC-007: o JPEG com mais de 64 marcadores vira 415, como todo `InvalidImageError` (CA-08 da SPEC-007).
- SPEC-010: herda pelas "mesmas regras da SPEC-007".
- SPEC-011: uma imagem rejeitada aparece como `unreadable_image`.

## 5. Critérios de aceite

As imagens são geradas em memória pelo próprio teste, com Pillow. "JPEG com COM de k pares" é um JPEG válido em que, logo depois do SOI (`FF D8`), se insere um segmento COM (`FF FE` + comprimento de 2 bytes big-endian + payload) cujo payload é `b"\xff\xda" * k`. O decodificador ignora o COM, mas a contagem o inclui. "JPEG progressivo com scans repetidos até m marcadores" é um JPEG gerado com `progressive=True` em que o último scan (do último `FF DA` até o `FF D9` final, exclusive) é repetido antes do `FF D9` até o arquivo ter exatamente m ocorrências de `FF DA`.

- **CA-01** — Dado o pacote instalado, quando se leem `qc_preprocess.__version__` e `importlib.metadata.version("qc-preprocess")`, então ambos valem `"0.3.0"`; e `qc_contracts.__version__` continua `"0.2.0"`.
- **CA-02** — Dado o pacote, quando se importa a constante, então `qc_preprocess.MAX_JPEG_SCANS == qc_preprocess.image.MAX_JPEG_SCANS == 64`, e `MAX_PIXELS == 40_000_000` e `MAX_ASPECT_RATIO == 10` não mudaram.
- **CA-03** — Dado um JPEG baseline RGB 64×48 (1 marcador `FF DA`), um JPEG progressivo RGB 640×480 e um JPEG progressivo em tons de cinza 640×480 (ambos com `progressive=True`), quando passam por `load_image`, então cada um é aceito em modo `RGB` e com o mesmo tamanho.
- **CA-04 (security, limite)** — Dado o JPEG baseline 64×48 do CA-03 com COM de 63 pares (64 marcadores no total), quando passa por `load_image`, então é aceito e `preprocess(load_image(...))` é igual bit a bit (`tobytes()`) a `preprocess(load_image(<o mesmo JPEG sem o COM>))`; e com COM de 64 pares (65 marcadores), então levanta `InvalidImageError` cuja mensagem contém `JPEG scans`.
- **CA-05 (security)** — Dado um JPEG progressivo RGB 256×256 com scans repetidos até 65 marcadores e outro até 1 000 marcadores, quando passam por `load_image`, então cada um levanta `InvalidImageError` cuja mensagem contém `JPEG scans`.
- **CA-06 (security, antes de decodificar)** — Dado os bytes `b"\xff\xd8\xff\xfe"` + comprimento + `b"\xff\xda" * 65` (SOI e um COM, sem quadro nem imagem), quando passam por `load_image`, então levanta `InvalidImageError` cuja mensagem contém `JPEG scans` (prova de que a regra vem antes do `Image.open`); e com `b"\xff\xda" * 10` no mesmo arranjo, então levanta `InvalidImageError` cuja mensagem **não** contém `JPEG scans`.
- **CA-07** — Dado um PNG RGB válido 64×48 com um chunk `tEXt` cujo texto é `"\xff\xda" * 100` (gravado em Latin-1 pelo `PngInfo.add_text`, o que põe 100 pares `FF DA` no arquivo), quando passa por `load_image`, então é aceito com tamanho `(64, 48)` (a regra só vale para conteúdo com assinatura JPEG).
- **CA-08 (ordem)** — Dado `PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True` (via `monkeypatch.setattr`), quando `load_image` recebe o JPEG com COM de 64 pares do CA-04, então levanta `RuntimeError` cuja mensagem contém `LOAD_TRUNCATED_IMAGES` (a flag continua sendo a primeira verificação); e dado `b""`, com a flag em `False`, então levanta `InvalidImageError` cuja mensagem não contém `JPEG scans`.
- **CA-09 (não regressão, ADR-004 e R-12)** — Dado `packages/preprocess/tests/acceptance/test_spec_002.py` e `packages/preprocess/tests/acceptance/test_spec_023.py`, com só as expectativas de versão do `qc-preprocess` trocadas para `"0.3.0"`, quando se roda `uv run pytest -q` nesses dois arquivos, então todos os testes passam. Isso inclui os valores numéricos e o determinismo bit a bit da SPEC-002, as dependências declaradas (só `numpy` e `pillow`, sem torch) e as regras de proporção e da flag da SPEC-023.

Não há CA de "suíte inteira": essa verificação é do CI e do test-report (`docs/architecture.md` §10).

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Limite exato (64 aceito, 65 rejeitado); só JPEG é contado; posição da regra (antes do `Image.open`, com espião em `PIL.Image.open` que não é chamado no caso rejeitado); PNG com pares `FF DA` aceito; asserção de versão do `test_smoke.py` | `packages/preprocess/tests/` |
| Aceite (tester) | Um teste por CA (CA-01 a CA-09), mais a troca das expectativas de versão listadas em §3.1 | `packages/preprocess/tests/acceptance/test_spec_024.py` e os três arquivos de §3.1 |

Sem mocks do código testado: só `monkeypatch` da flag global no CA-08 (configuração). Sem banco e sem rede. Nenhum binário de imagem entra no Git.

## 7. Riscos e notas para o implementador

- Não interprete os segmentos do JPEG para "contar melhor". Um parser que pare num segmento malformado contaria a menos, porque o libjpeg pula bytes estranhos até o próximo marcador e segue decodificando. A contagem ingênua do arquivo inteiro é a garantia (§1).
- `bytes.count` num corpo de 10 MiB leva poucos milissegundos. Não há custo relevante para as imagens aceitas.
- **Opção (b) do SEC-01 não adotada:** recusar JPEG progressivo na rota da borda, ou baixar o corpo para 2 MiB, dependeria de o canvas de cada navegador gerar JPEG baseline, o que esta SPEC não verifica. Além disso, o ML (SPEC-011) lê fotos originais do celular. Com o limite de 64 marcadores, o custo por requisição já fica limitado, e a SPEC-007 limita as decodificações simultâneas (SEC-02).
- O reviewer confere que `git diff main -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py` está vazio e que, nos três arquivos de aceite antigos, só mudaram as expectativas de versão do `qc-preprocess` e as docstrings.
- Gerar o "JPEG progressivo com scans repetidos" depende da estrutura que o Pillow grava (último scan seguido de `FF D9`). Se a decodificação do arquivo com 65 marcadores falhar antes da regra por outro motivo, o teste não prova nada: o CA-05 exige a mensagem `JPEG scans`.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS (tag `security`)
- [ ] CI verde; `ruff` limpo; `uv.lock` atualizado só na versão do `qc-preprocess`
- [ ] `docs/architecture.md` §6.1 e §9 já citam a regra (feito pelo architect nesta SPEC)
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Criação em `Draft`. Decisões do architect: (a) a correção do SEC-01 fica numa SPEC curta só do `qc-preprocess` (0.3.0), e não dentro da SPEC-007, para manter a paridade do ADR-004 (treino e borda rejeitam as mesmas imagens) e não misturar o pacote compartilhado com o código da borda; (b) contagem ingênua de `FF DA` no arquivo inteiro, só para conteúdo com assinatura JPEG; (c) limite de 64; (d) a opção (b) do SEC-01 (recusar JPEG progressivo na rota) não foi adotada. | SEC-01 de `reviews/SPEC-023/r1-security-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | `Draft` → `Ready`, com o limite de 64 marcadores SOS aprovado. | Aprovação humana | Humano (Carlos) |
