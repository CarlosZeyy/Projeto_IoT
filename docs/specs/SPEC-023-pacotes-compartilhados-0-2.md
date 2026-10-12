# SPEC-023: Pacotes compartilhados 0.2.0 (teto de `latency_ms`, proporção da imagem e flag de JPEG truncado)

| Campo | Valor |
|---|---|
| Status | In Review |
| Rodada atual | r1 |
| Autor da implementação | developer |
| Tags | contrato, security |
| Depende de | SPEC-002 (mergeada no PR #5) |
| Semana alvo | S2 (antes de a SPEC-004 e a SPEC-007 entrarem em `In Dev`; pode correr em paralelo com a SPEC-003) |
| Requisitos cobertos | RF-06 (registro na nuvem sem 500 por valor fora da coluna), RNF-06 (entrada externa validada), RNF-07 (pré-processamento idêntico treino/borda), R-04, R-12 |
| ADRs relevantes | ADR-004 (pré-processamento compartilhado, paridade treino/borda), ADR-006 (Postgres/psycopg), ADR-013 (regra de defeito, inalterada) |

## 1. Contexto

O review da SPEC-002 (`reviews/SPEC-002/r1-review-report.md` e `r2-review-report.md`) deixou com o architect duas lacunas de requisito e três observações. Esta SPEC implementa as que exigem código nos pacotes compartilhados; as demais ficam decididas em §4.4, sem código.

1. **SPEC_ISSUE-02 (RV-03):** `latency_ms` só tem `ge=0` no contrato (`architecture.md` §3.2), mas a coluna é `integer` (§5), que vai de −2 147 483 648 a +2 147 483 647; um valor fora disso gera erro no `insert` ("Attempts to store values outside of the allowed range will result in an error", <https://www.postgresql.org/docs/16/datatype-numeric.html>, consultado em 2026-10-12), com SQLSTATE `22003` `numeric_value_out_of_range` (<https://www.postgresql.org/docs/16/errcodes-appendix.html>, consultado em 2026-10-12). Hoje um payload com `latency_ms = 2³¹` passa pelo contrato e vira 500 na SPEC-004.
2. **SPEC_ISSUE-01 (RV-02):** `load_image` limita a área (40 M pixels), mas não a proporção. Como `preprocess` redimensiona antes de cortar (`architecture.md` §6.2, passo 2), um PNG de 5,5 KB com 100×400 000 px gerou pico de 1,6 GB, e um de 20×2 000 000 px estourou 3 GB (`reviews/SPEC-002/r1-test-report.md`, R-A). Na borda, qualquer portador do token de sessão derrubaria o notebook por OOM via `POST /api/capture` (SPEC-007).
3. **RV-06:** `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` é um atributo de módulo, com padrão `False`, que "User code may change" (<https://pillow.readthedocs.io/en/stable/reference/ImageFile.html>, consultado em 2026-10-12). Se algum módulo do processo o ligar, um JPEG truncado passa pelo `load_image` (verificado pelo tester da SPEC-002, R-B).

## 2. Objetivo

`qc_contracts` 0.2.0 rejeita `latency_ms` acima de 2 147 483 647 com `ValidationError`, e `qc_preprocess` 0.2.0 rejeita, pelo cabeçalho e antes de decodificar, imagens com proporção acima de 10:1, e se recusa a rodar com `LOAD_TRUNCATED_IMAGES` ligada; a saída de `preprocess` para toda imagem aceita continua idêntica bit a bit à da 0.1.0.

## 3. Escopo

### 3.1 Dentro

- `packages/contracts/src/qc_contracts/schemas.py` (constante `MAX_LATENCY_MS` e o `le=` de `latency_ms`, §4.1) e `__init__.py` (reexportação e `__version__ = "0.2.0"`).
- `packages/contracts/pyproject.toml` (versão `0.2.0`) e `packages/contracts/README.md` (regras principais e linha `0.2.0` no "Histórico de versões", §4.1).
- `packages/preprocess/src/qc_preprocess/image.py` (§4.2) e `__init__.py` (reexportação de `MAX_ASPECT_RATIO` e `__version__ = "0.2.0"`); `packages/preprocess/pyproject.toml` (versão `0.2.0`).
- `uv.lock` (só as duas versões).
- Testes do autor em `packages/contracts/tests/` e `packages/preprocess/tests/`, incluindo a atualização das asserções de versão em `test_smoke.py`.
- **Tester desta SPEC:** `packages/contracts/tests/acceptance/test_spec_023.py`, `packages/preprocess/tests/acceptance/test_spec_023.py` e, nos dois `tests/acceptance/test_spec_002.py`, **só** a expectativa de versão do CA-01 da SPEC-002 (`"0.1.0"` → `"0.2.0"`) e a menção de versão na docstring do módulo. O developer não toca em `tests/acceptance/`.

### 3.2 Fora

- Uso do teto e da regra de regex nas rotas e scripts: SPEC-004 (422 para `latency_ms` > teto, `register_device.py`), SPEC-007 (`DEVICE_ID`, `lot_id`, 415 para proporção), SPEC-014 (`--device-id`, `--model-version`). Essas SPECs já foram ajustadas pelo architect.
- Restrição de `latency_ms` no banco: o tipo `integer` já impõe o mesmo teto; o CA-23 da SPEC-003 fixa esse limite por teste.
- Modo estrito do Pydantic, `frozen`/`validate_assignment` nos modelos: não adotados (§4.4).
- PNG de 16 bits (`I;16`) saturado na conversão para RGB (R-C do test-report da SPEC-002): sem ação, porque a página do celular reencoda em JPEG de 8 bits.
- Qualquer mudança em `preprocess`, `PreprocessParams`, `preprocessing.json`, enums, regexes ou demais campos do contrato.

## 4. Requisitos detalhados

### 4.1 `qc_contracts` 0.2.0

- Constante pública `MAX_LATENCY_MS: int = 2_147_483_647` (= 2³¹ − 1, o máximo da coluna `integer` de `architecture.md` §5), definida em `qc_contracts.schemas` e reexportada em `qc_contracts`.
- `latency_ms` na base comum (`_InspectionBase`), portanto em `InspectionCreate` e `InspectionRead`: inteiro com `0 ≤ latency_ms ≤ MAX_LATENCY_MS` (`Field(ge=0, le=MAX_LATENCY_MS)`). Acima do teto → `ValidationError` com um único erro do tipo `less_than_equal` no `loc` `("latency_ms",)` (em `BatchCreate`, `("items", i, "latency_ms")`).
- Nada mais muda no contrato: os 14 campos, as regexes (inclusive os valores de `DEVICE_ID_PATTERN`, `LOT_ID_PATTERN`, `MODEL_VERSION_PATTERN` e `SHA256_PATTERN`, fixados pelo CA-02 da SPEC-002), as invariantes, `extra`, o modo de coerção e os modelos de resposta.
- `__version__ = "0.2.0"` e `version = "0.2.0"` no `pyproject.toml`.
- `packages/contracts/README.md`:
  - em "Regras principais", um item novo: `latency_ms` é inteiro de `0` a `MAX_LATENCY_MS` (2 147 483 647, o limite da coluna `integer` do banco);
  - em "Regras principais", um item novo: os modelos usam o modo padrão (lax) do Pydantic, sem `strict` (decisão da SPEC-023 §4.4);
  - no "Histórico de versões", a linha `| 0.2.0 | 2026-10 | teto de latency_ms (MAX_LATENCY_MS = 2³¹ − 1, coluna integer do banco) (SPEC-023) |`, mantendo a linha `0.1.0`.

**Classificação da mudança (skill `contrato-api`).** A tabela da skill não tem linha para "estreitar a validação de um campo". Classifico como **minor** (0.1.0 → 0.2.0), sem ADR, porque:
- o formato do payload não muda (mesmo campo, mesmo tipo, mesma obrigatoriedade) e há um símbolo público novo (`MAX_LATENCY_MS`);
- os únicos valores que deixam de ser aceitos (2³¹ a 2⁶³) já não podiam ser gravados: na versão 0.1.0, eles terminariam em 500 no `insert`;
- nenhum produtor existe ainda (borda e simulador são SPECs futuras), e a 0.1.0 nunca foi publicada.

A R-04 é atendida por esta SPEC com a tag `contrato` e pelo aumento de versão.

### 4.2 `qc_preprocess` 0.2.0

- Constante pública `MAX_ASPECT_RATIO: int = 10`, definida em `qc_preprocess.image` e reexportada em `qc_preprocess`. `MAX_PIXELS` e `ACCEPTED_FORMATS` não mudam.
- `load_image(data: bytes | Path) -> PIL.Image.Image` mantém a assinatura e todo o comportamento da SPEC-002 §4.5, com duas verificações novas, nesta ordem dentro da função:
  1. **Primeira verificação, antes de qualquer leitura** (antes até do teste de `Path` inexistente): se `PIL.ImageFile.LOAD_TRUNCATED_IMAGES` for verdadeiro no momento da chamada (lido a cada chamada, nunca guardado no import), levanta `RuntimeError` com uma mensagem que contém `LOAD_TRUNCATED_IMAGES`. **Não** é `InvalidImageError`: a falha é de configuração do processo, não da imagem, e a borda deve responder 5xx, não 415. A função **não** altera a flag (ela é global e a borda processa em várias threads).
  2. **Proporção, pelo cabeçalho:** logo depois da checagem de `MAX_PIXELS` (que continua antes do `.load()`), e também antes do `.load()`, com `w, h = img.size`: se `min(w, h) == 0` ou `max(w, h) > MAX_ASPECT_RATIO * min(w, h)` (aritmética inteira), levanta `InvalidImageError` com uma mensagem que contém `aspect ratio`, por exemplo `f"image is {w}x{h} pixels; aspect ratio above {MAX_ASPECT_RATIO}:1"`. A proporção 10:1 exata é aceita.
- A docstring de `load_image` passa a listar as duas condições novas.
- `preprocess`, `PreprocessParams` e `transform.py`/`params.py` **não mudam**. Para toda imagem que o `load_image` aceita, a saída de `preprocess` é bit a bit a mesma da 0.1.0; por isso o `preprocessing.json` e os modelos já treinados continuam válidos.
- `__version__ = "0.2.0"` e `version = "0.2.0"` no `pyproject.toml`.

**Por que no `load_image`, e não só na rota da borda (ADR-004).** O `load_image` já é a barreira de validação usada pela borda (SPEC-007, SPEC-010) e pelo ML (`unreadable_image` da SPEC-011, avaliação da SPEC-012). Com a regra nele, treino e borda rejeitam exatamente as mesmas imagens, e nenhuma imagem aceita muda de valor. A alternativa, mudar a ordem resize→crop, alteraria os valores numéricos e quebraria a paridade com os modelos treinados.

**Por que 10:1.** As fotos de celular têm proporção de 4:3 a cerca de 21:9 (≈ 2,3:1), e a página de captura só reduz o tamanho, sem mudar a proporção. Com 10:1 e o teto de 40 M pixels, a maior imagem aceita (2 000×20 000) é redimensionada para 256×2 560 antes do crop, cerca de 2 MB em RGB de 8 bits, em vez dos 786 MB do caso 100×400 000.

### 4.3 Consumidores (sem código nesta SPEC)

- SPEC-003: o CA-23 fixa no banco o mesmo teto (2 147 483 647 aceito; 2 147 483 648 → SQLSTATE `22003`).
- SPEC-004: `latency_ms` acima do teto → 422 (não 500); `contract_version` passa a ser `qc_contracts.__version__`.
- SPEC-007: imagem com proporção acima de 10:1 → 415; `RuntimeError` do `load_image` não é tratado como 415.
- A regra "regex fora dos schemas só com `re.fullmatch`" está em `architecture.md` §3.2 e nas SPECs 004, 007 e 014.

### 4.4 Decisões registradas, sem código

- **RV-05, modo lax do Pydantic: mantido (risco aceito).**
  - Depois da coerção, todas as faixas, regexes e invariantes continuam valendo, e nenhum valor fora do domínio é aceito. O único efeito material, o teto de `latency_ms`, está resolvido em §4.1.
  - `ConfigDict(strict=True)` no modelo quebraria a validação do corpo na API: no modo Python, o modo estrito aceita só instâncias de `datetime` (e de `UUID` e enums), não strings. Fonte: tabela de conversão do Pydantic, <https://pydantic.dev/docs/validation/latest/concepts/conversion_table/>, consultada em 2026-10-12. O reviewer da SPEC-002 confirmou isso na prática.
  - Os dois produtores previstos, a borda (SPEC-007/008) e o simulador (SPEC-014), montam o payload pelo próprio `InspectionCreate`, então a coerção não muda o que eles enviam.
  - **Efeitos aceitos:**
    - `needs_review` aceita `"yes"` e `1` como `true`;
    - `latency_ms` aceita `true` como `1` e `120.0` como `120`;
    - os floats aceitam strings numéricas;
    - `inspected_at` aceita um inteiro epoch, interpretado pela heurística do Pydantic (um epoch muito grande é lido como milissegundos). Continuam valendo a regra dos 5 min no futuro e a normalização para UTC.
  - **Gatilho para revisitar:** um produtor que não use `qc_contracts` (por exemplo, o MQTT da SPEC-020 ou um cliente de terceiros) ou um incidente causado por um dado coerido. Nesse caso, o modo estrito seria aplicado **campo a campo** (`Field(strict=True)` em `needs_review` e `latency_ms`), nunca no modelo, numa versão minor nova.
- **Modelos mutáveis** (`frozen`/`validate_assignment`): não adotados, pelos mesmos motivos. Os modelos são criados e serializados em seguida, sem reatribuição.
- **RV-04, regex com o módulo `re`:**
  - as constantes não mudam;
  - `architecture.md` §3.2 passa a exigir `re.fullmatch` (ou o próprio schema / `TypeAdapter`) em toda validação por regex fora dos schemas;
  - as SPECs 004, 007 e 014 ganharam a regra explícita e um caso de aceite com `\n` final.
- **RV-06:** implementado em §4.2, item 1. Além disso, `architecture.md` §9 registra que nenhum componente liga essa flag.

## 5. Critérios de aceite

`P` é o payload base válido do CA-05 da SPEC-002. "PNG só com cabeçalho" é um PNG com assinatura e `IHDR` válidos e sem `IDAT`, gerado no teste. As imagens são geradas em memória pelo próprio teste.

- **CA-01** — Dado os dois pacotes instalados, quando se leem `qc_contracts.__version__`, `importlib.metadata.version("qc-contracts")`, `qc_preprocess.__version__` e `importlib.metadata.version("qc-preprocess")`, então os quatro valem `"0.2.0"`.
- **CA-02** — Dado os pacotes, quando se importam as constantes, então `qc_contracts.MAX_LATENCY_MS == qc_contracts.schemas.MAX_LATENCY_MS == 2**31 - 1 == 2147483647`, `qc_preprocess.MAX_ASPECT_RATIO == qc_preprocess.image.MAX_ASPECT_RATIO == 10` e `qc_preprocess.MAX_PIXELS == 40_000_000`.
- **CA-03** — Dado `P` com `latency_ms=2147483647`, quando validado por `InspectionCreate.model_validate` e por `InspectionCreate.model_validate_json` (JSON de `P`), então é aceito e `latency_ms == 2147483647`. Com `latency_ms=2147483648` ou `latency_ms=2**63`, cada forma levanta `ValidationError` com exatamente 1 erro, de tipo `less_than_equal` e `loc == ("latency_ms",)`.
- **CA-04** — Dado um `InspectionRead` montado a partir de `P` com `received_at` e `is_defective=False`, quando `latency_ms=2147483648`, então levanta `ValidationError` com `loc == ("latency_ms",)`; com `2147483647`, é aceito.
- **CA-05** — Dado um `BatchCreate` com 3 itens válidos em que o 2º tem `latency_ms=2147483648`, quando validado, então levanta `ValidationError` com exatamente 1 erro, em `("items", 1, "latency_ms")`.
- **CA-06** — Dado `packages/contracts/README.md`, quando lido, então a tabela "Histórico de versões" tem uma linha com `0.2.0` que cita `SPEC-023`, a linha `0.1.0` continua presente, e o texto contém `MAX_LATENCY_MS`.
- **CA-07** — Dado PNGs válidos RGB de 100×1000 e 1000×100 e um JPEG de 40×400, quando passam por `load_image`, então cada um é aceito, em modo `RGB` e com o mesmo tamanho; e `preprocess(load_image(<PNG 100×1000>))` tem `shape == (1, 3, 224, 224)` e `dtype == float32`.
- **CA-08 (security)** — Dado PNGs válidos de 100×1001, 1001×100, 100×400 000 e 20×2 000 000 (os dois últimos com exatamente 40 M pixels, dentro de `MAX_PIXELS`), quando passam por `load_image`, então cada um levanta `InvalidImageError` cuja mensagem contém `aspect ratio`.
- **CA-09 (security)** — Dado um PNG só com cabeçalho de 100×1001, quando passa por `load_image`, então levanta `InvalidImageError` cuja mensagem contém `aspect ratio` (prova de que a regra vem do cabeçalho, antes de decodificar); e dado um PNG só com cabeçalho de 100×1000, então levanta `InvalidImageError` cuja mensagem **não** contém `aspect ratio` (falha na decodificação, porque a proporção é aceita).
- **CA-10** — Dado um JPEG 400×40 com EXIF `Orientation = 6`, quando passa por `load_image`, então é aceito com tamanho `(40, 400)`; e dado um JPEG 401×40 com EXIF `Orientation = 6`, então levanta `InvalidImageError` com `aspect ratio`.
- **CA-11 (security)** — Dado `PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True` (via `monkeypatch.setattr`, que restaura o valor), quando `load_image` recebe um JPEG válido 64×48, um JPEG válido truncado na metade ou `Path("nao_existe.jpg")`, então cada chamada levanta `RuntimeError` cuja mensagem contém `LOAD_TRUNCATED_IMAGES`, a exceção **não** é instância de `ValueError` e, depois da chamada, a flag continua `True` (a função não a altera). Com a flag de volta a `False`, o JPEG válido é aceito e o truncado levanta `InvalidImageError`.
- **CA-12 (não regressão, ADR-004 e R-12)** — Dado `packages/contracts/tests/acceptance/test_spec_002.py` e `packages/preprocess/tests/acceptance/test_spec_002.py`, com só a expectativa de versão do CA-01 trocada para `"0.2.0"`, quando se roda `uv run pytest -q` nesses dois arquivos, então todos os testes passam. Isso inclui os valores numéricos dos CA-20 e CA-21, o determinismo bit a bit do CA-22, as dependências declaradas do CA-18 (só `pydantic`) e do CA-26 (só `numpy` e `pillow`, sem torch) e a rejeição do CA-24.
- **CA-13** — Dado o repositório desta SPEC, quando se rodam `uv run ruff check .`, `uv run ruff format --check .` e `uv run pytest -q`, então os três terminam com código 0.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Limite de `latency_ms` (no teto, acima, `2**63`, em `InspectionRead` e no lote); limites de proporção nas duas orientações; ordem das verificações (cabeçalho antes do `.load()`, flag antes de tudo); a flag não é alterada; asserções de versão do `test_smoke.py` | `packages/contracts/tests/`, `packages/preprocess/tests/` |
| Aceite (tester) | Um teste por CA: CA-01, 02 (parte do contrato), 03 a 06 e 13 no pacote de contratos; CA-01, 02 (parte do preprocess) e 07 a 12 no pacote de preprocess. Mais a troca da expectativa de versão do CA-01 nos dois `test_spec_002.py` | `packages/contracts/tests/acceptance/test_spec_023.py`, `packages/preprocess/tests/acceptance/test_spec_023.py` e os dois `test_spec_002.py` |

Sem mocks: o CA-11 só liga uma flag global do Pillow com `monkeypatch` (configuração, não substituição do código testado). Sem banco e sem rede. Nenhum binário de imagem entra no Git.

## 7. Riscos e notas para o implementador

- Gerar o PNG válido de 20×2 000 000 px em memória usa cerca de 40 MB (modo `L`) e leva poucos segundos. Ele não é decodificado pelo `load_image`, porque a regra é aplicada antes do `.load()`.
- Não converta a comparação de proporção para `float`: `max(w, h) > MAX_ASPECT_RATIO * min(w, h)` com inteiros evita erro de arredondamento no limite exato.
- O `exif_transpose` só troca largura e altura, então a proporção é a mesma antes e depois. Checar pelo cabeçalho é suficiente (CA-10).
- Na borda (SPEC-007), o `RuntimeError` da flag não deve ser capturado como `InvalidImageError`: ele indica erro de configuração do servidor.
- A tabela da skill `contrato-api` não classifica o "estreitamento de validação". A classificação desta SPEC (minor, §4.1) vale como precedente até o humano decidir se a skill ganha essa linha.
- O reviewer confere que `git diff main -- packages/preprocess/src/qc_preprocess/transform.py packages/preprocess/src/qc_preprocess/params.py` está vazio e que, em `test_spec_002.py`, só mudaram a expectativa de versão e a docstring.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS)
- [ ] review-report APPROVED e security-report PASS (tag `security`)
- [ ] CI verde; `ruff` limpo; `uv.lock` atualizado só nas duas versões
- [ ] `packages/contracts/README.md` com as regras e o histórico de versões
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | Criação em `Draft`. Decisões do architect: (a) teto de `latency_ms` = 2³¹ − 1, igual ao tipo `integer`, em vez de um teto "realista" (por exemplo, 10 min), para não criar um modo de falha novo na borda; (b) proporção máxima 10:1 no `load_image`, pelo cabeçalho, sem mudar `preprocess`; (c) `load_image` recusa rodar com `LOAD_TRUNCATED_IMAGES` ligada (`RuntimeError`); (d) modo lax mantido como risco aceito; (e) versão minor 0.2.0 nos dois pacotes, sem ADR (§4.1). | SPEC_ISSUE-01, SPEC_ISSUE-02, RV-04, RV-05 e RV-06 de `reviews/SPEC-002/r1-review-report.md` e `r2-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-12 | `Draft` → `Ready`. Aprovação humana com teto 2³¹−1 e tag `security`. | Aprovação humana | Humano (Carlos) |
