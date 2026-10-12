# SPEC-023 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-023](../../docs/specs/SPEC-023-pacotes-compartilhados-0-2.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `spec/SPEC-003-schema-banco...2b09cda` (branch empilhada sobre a SPEC-003). Código da SPEC: `3caaaf0` e `d3e1679` (developer); aceite: `606ac7a` (tester). |
| **Veredicto** | **PASS** |

Motivo do veredicto: não há achado bloqueante nem alto. As três defesas da SPEC estão corretas e cumprem o que prometem:

- o teto de `latency_ms` barra no contrato todo valor que o `integer` do banco recusaria, sem caminho de contorno pelo modo lax;
- a regra de proporção vem do cabeçalho, antes de qualquer decodificação, e fecha o OOM do R-A da SPEC-002;
- a checagem de `LOAD_TRUNCATED_IMAGES` falha fechada a cada chamada, sem tocar na flag.

Achei dois riscos médios **anteriores** a esta SPEC, que ela não introduz e que estão fora do seu escopo (§3.2 e "nada mais muda" da §4.1/§4.2):

- SEC-01: um JPEG progressivo com scans repetidos consome minutos de CPU no `load_image` e é **aceito**;
- SEC-03: a mesma classe de falha do `latency_ms` (valor aceito pelo contrato que vira 500 no banco) existe nos campos `float` gravados em colunas `real`.

Os dois vão para o architect, com prazo antes de a SPEC-004 e a SPEC-007 entrarem em `In Dev`. Não bloqueiam esta SPEC: a SPEC-023 só melhora o estado anterior, e corrigir qualquer um deles exige requisito novo.

## Superfície analisada

- `packages/preprocess/src/qc_preprocess/image.py` (`load_image`): a flag global, a ordem das verificações, a regra de proporção, os limites de pixels, os formatos aceitos, o tratamento de exceções e o comportamento com threads.
- `packages/contracts/src/qc_contracts/schemas.py`: `MAX_LATENCY_MS` e `latency_ms` em `_InspectionBase`; por extensão, os demais campos numéricos que vão para colunas do `infra/migrations/001_init.sql` (base da SPEC-003).
- `uv.lock` e os `pyproject.toml`: só a versão dos dois pacotes mudou, sem dependência nova.
- Testes de aceite e do autor: nenhum binário de imagem entra no Git, e todas as imagens são sintéticas e geradas em memória (R-14).
- Fora da superfície, porque não existem nesta SPEC: rotas, autenticação, CORS, SQL, logging, segredos e deploy.

Reprodução e sondagens (somente leitura no repositório; scripts e arquivos temporários ficaram fora dele):

- `uv run pytest -q packages/contracts/tests packages/preprocess/tests --deselect <CA-13>`: **559 passed**. O CA-13 (suíte inteira) foi conferido pelo tester e pelo reviewer.
- Versões: Pillow 12.3.0, libjpeg-turbo 3.1.4.1, zlib 1.3.2, pydantic 2.14.1 e pydantic-core 2.50.1. `Image.MAX_IMAGE_PIXELS = 89 478 485`.
- **Pico de memória das maiores imagens aceitas** (2 000×20 000, 40 M pixels a 10:1; processo novo, `ru_maxrss` antes e depois de `load_image` + `preprocess`). A base do processo era de 46 MB:

  | Imagem | Arquivo | Pico |
  |---|---|---|
  | JPEG CMYK com EXIF `Orientation = 6` | 1,9 MB | 343 MB |
  | PNG RGBA com eXIf 6 | 198 KB | 342 MB |
  | PNG LA com eXIf 6 | 78 KB | 341 MB |
  | JPEG RGB progressivo | 235 KB | 343 MB |
  | PNG cinza de 16 bits | 78 KB | 265 MB |

  O tempo de cada caso ficou entre 0,45 e 0,63 s. O teto por requisição é de ~300 MB (ver SEC-02). O caso de 227 MB do test-report é o do modo mais leve.
- **Proporção extrema** (R-A da SPEC-002): conferi o CA-08/CA-09 e o espião do autor em `ImageFile.load`. A rejeição acontece antes de qualquer alocação de pixels.
- **JPEG progressivo com scans repetidos** (SEC-01): parti de um JPEG progressivo gerado com `jpegtran -scans` (um scan DC e um scan AC 1–63) e repeti K vezes o último scan (`SOS` + dados) antes do `EOI`. Resultado:

  | Imagem | K | Arquivo | Tempo do `load_image` | Resultado |
  |---|---|---|---|---|
  | 2 000×2 000 | 1 000 | 22 KB | 0,34 s | aceita |
  | 2 000×20 000 | 1 000 | 143 KB | 3,26 s | aceita |
  | 2 000×20 000 | 4 000 | 338 KB | 16,38 s | aceita |

  O custo é linear: ~4 ms por scan a 40 M pixels, com 65 bytes por scan.
- **Colunas `real`** (SEC-03): fiz uma consulta só de leitura no Postgres 16.15 de teste (`select %s::real`, com o parâmetro `float` do psycopg, que é o mesmo cast `float8 → float4` de um `insert`). O contrato aceita `1e-46`, `7e-46`, `1e-50` e `5e-324` em `Probability`/`GradeScore`, e todos falham com `NumericValueOutOfRange` (`22003`, "value out of range: underflow"). `1.4e-45` e `1e-40` passam (subnormais de `float4`).
- **`latency_ms` contra 500:** todas as entradas abaixo terminam em `ValidationError` (`less_than_equal`, `int_parsing`, `int_from_float`, `finite_number` ou `json_invalid`) e nunca em outra exceção:
  - inteiros JSON de 400, 4 300, 5 000 e 250 000 dígitos (acima de ~4 300 dígitos, o pydantic-core devolve `json_invalid`);
  - no modo Python: `" 2147483648 "`, `"0x7fffffff"`, `2147483647.5` e `inf`.

  `True`, `2147483647.0`, `"2147483647"` e `"2_147_483_647"` viram inteiros dentro da faixa: o modo lax é o risco aceito da §4.4 e não ultrapassa o teto.
- **Quem liga `LOAD_TRUNCATED_IMAGES`:** `grep` no código do projeto (fora de testes) e em todo o `site-packages` do `.venv` (inclusive `onnxruntime` 1.31.0). Nenhuma atribuição fora do próprio Pillow. Ressalva: `torch`/`timm` (extra `train`) não estão instalados neste ambiente, então não foram inspecionados.
- Segredos: `git diff` sem padrões de chave, token, senha ou JWT. Identidade e trailers `Agent:` corretos em todos os commits.

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 | média (não bloqueia; **architect, antes da SPEC-007 `In Dev`**) | input (DoS de CPU) | `packages/preprocess/src/qc_preprocess/image.py:73` (`img.load()`), comportamento herdado da SPEC-002 | **JPEG progressivo com scans repetidos.** O padrão JPEG não limita o número de scans progressivos. O libjpeg-turbo só emite um *warning* para progressão inválida, e o Pillow usa a API libjpeg, que não tem limite de scans. O limite existe só na API TurboJPEG (`TJFLAG_LIMITSCANS`). Cada scan percorre todos os blocos da imagem, então o custo é `nº de scans × pixels`. Medi ~4 ms por scan a 40 M pixels, com 65 bytes por scan: **338 KB levam 16 s**, e a extrapolação linear para o corpo máximo da borda (10 MB, ~150 mil scans) dá **~10 min de CPU por requisição**. Durante esse tempo, o buffer de coeficientes do modo progressivo fica alocado. A imagem é **aceita** e o resultado é idêntico ao da imagem limpa, então nada acusa o ataque. Na SPEC-007, o handler é síncrono no threadpool, e poucas requisições assim ocupam a CPU do notebook e travam a inferência na demonstração. Pré-condições: token de sessão (QR) e acesso à LAN, que é o hotspot da dupla (§8). Por isso a severidade é média, e não alta. Referência: Red Hat Bug 1344214, "libjpeg: CPU overconsumption using extraneous progressive scans". | Decisão do architect (requisito novo). Opções, combináveis: (a) **`qc_preprocess` 0.3.0:** antes do `Image.open`, percorrer os segmentos do JPEG e rejeitar com `InvalidImageError` acima de N marcadores `SOS`. Um JPEG progressivo comum tem cerca de 10 scans; N entre 32 e 100 cobre encoders reais. Isso vale também para o ML e não muda nenhuma imagem aceita hoje; (b) **SPEC-007:** a página reencoda via canvas (baseline), então a rota pode recusar JPEG progressivo (`img.info.get("progressive")`) e usar limites próprios mais baixos (corpo ≤ 2 MB, lado maior ≤ ~1 280 px × 10:1), o que reduz o custo por scan em ~10×; (c) **SPEC-007:** semáforo de decodificação (ver SEC-02). Recomendo (a) + (c). |
| SEC-02 | baixa (recomendação para a **SPEC-007**) | input (memória) | `image.py` (limites `MAX_PIXELS` e `MAX_ASPECT_RATIO`) | Com 40 M pixels e 10:1, a maior imagem aceita custa até **~300 MB** por chamada (pico de 343 MB, contra 46 MB de base, nos casos JPEG CMYK e PNG RGBA/LA com EXIF 6). Isso é o esperado e está bem limitado por requisição. Mas o handler da SPEC-007 roda no threadpool do Starlette (até 40 threads), e N uploads simultâneos custam N × 300 MB. A SPEC-023 não piora nada: ela reduziu o pior caso de >3 GB para ~300 MB. | Na SPEC-007: limitar as decodificações simultâneas (por exemplo, `threading.BoundedSemaphore(2)` em volta de `load_image` + `preprocess`, com 503 ou espera quando o limite for atingido) e testar 4 uploads paralelos da maior imagem aceita. |
| SEC-03 | média (não bloqueia; **architect, antes da SPEC-004 `In Dev`**, de preferência antes do merge da SPEC-003) | input (500 no banco) | `packages/contracts/src/qc_contracts/schemas.py:58-59` (`Probability`, `GradeScore`); `infra/migrations/001_init.sql:27-29` (colunas `real`) | **Mesma classe do SPEC_ISSUE-02, em outros campos.** `type_confidence`, `grade_confidence` e `grade_score` aceitam qualquer `float` finito em `[0, 1]` ou `[0, 4]`. As colunas são `real` (`float4`), e o cast `float8 → float4` do Postgres falha com `22003` "underflow" para todo valor em `(0, ~7e-46]` (verificado no Postgres 16.15). Na SPEC-004, isso vira 500 (§4.5: "exceção inesperada → 500"). No lote, um único item envenena o lote inteiro, e o outbox da borda reenviaria esse lote para sempre. Uma borda legítima **não** produz esses valores, porque as saídas do ONNX são `float32` e `Σ i·p_i` de `float32` dá um múltiplo exato do menor subnormal de `float4`. O risco vem de um portador de chave de dispositivo com bug ou hostil, e o dano fica restrito ao próprio dispositivo. Nem a review nem o security-report da SPEC-003 apontaram isso. | Decisão do architect. Opções: (a) **SPEC-003:** trocar as três colunas para `double precision`. É o mais barato, não muda o contrato, a SPEC-003 ainda está em PR e o `between` continua igual; (b) **SPEC-004:** tratar `psycopg.errors.DataError` (classe 22) como 422, como rede de segurança geral, com um caso de aceite `grade_score=1e-50`; (c) contrato minor: rejeitar `0 < x < 1e-30` ou arredondar para `float32`. Recomendo (a) + (b). |
| SEC-04 | informativa (**SPEC-007**) | input (configuração) | `image.py:35` × `image.py:73` | Janela entre a leitura de `LOAD_TRUNCATED_IMAGES` e o `img.load()`, que a consulta de novo. Quem altera a flag é sempre código do próprio processo, nunca a entrada. Então um atacante remoto não consegue explorar essa janela, e a checagem cumpre o papel de defesa em profundidade a que se propõe (§1, item 3). A garantia principal é a regra do `architecture.md` §9. No ambiente atual, nenhuma dependência instalada liga a flag. | Na SPEC-007: (a) no startup, depois de importar todos os módulos da borda (inclusive `onnxruntime`), verificar que `ImageFile.LOAD_TRUNCATED_IMAGES is False` e recusar subir se não for; (b) um teste que procura, no repositório, atribuições a `LOAD_TRUNCATED_IMAGES` fora de `tests/`. Na SPEC-011: repetir o `grep` com o extra `train` (`torch`/`timm`) instalado, porque eles não foram inspecionados aqui. |
| SEC-05 | informativa (**SPEC-007**) | input (concorrência) | `image.py:49` (`warnings.catch_warnings`), herdado da SPEC-002 | No Python 3.12, `warnings.catch_warnings` altera o estado global de filtros e não é seguro entre threads: duas chamadas simultâneas podem restaurar o filtro uma da outra. Para a segurança do `load_image`, isso é inócuo, porque o limite efetivo é a checagem explícita `MAX_PIXELS` (40 M), feita antes do `.load()` e abaixo do limiar do `DecompressionBombWarning` (89 478 485). Acima de 2× esse limiar, o Pillow levanta `DecompressionBombError` de qualquer modo. O efeito colateral possível é deixar o filtro `error` ligado de forma global no processo, o que é mais restritivo e não muda nada para o `load_image`. | Nenhuma ação nesta SPEC. Na SPEC-007, nenhuma decisão de segurança deve depender de filtros de `warnings`. |

## Notas para a SPEC-004 (sem achado)

- O teto do contrato fecha o caminho `latency_ms → 22003`. O CA-24 da SPEC-004 deve cobrir a forma JSON (2147483648 → 422).
- Na rota real, o FastAPI decodifica o corpo com `json.loads` do Python antes do Pydantic. Um inteiro com mais de 4 300 dígitos levanta `ValueError` ali (limite de conversão `int`/`str` do Python 3.12), e não `JSONDecodeError`. Pelo código do FastAPI, isso deveria virar 400 "There was an error parsing the body". Vale um caso de aceite que confirme 4xx, e não 500, com o corpo ainda abaixo de 256 KB.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | N/A: nenhuma rota nesta SPEC |
| Entradas validadas: tamanho, tipo real da imagem (Pillow), regex de IDs, `extra="forbid"` | ✅ Teto de `latency_ms` sem contorno pelo modo lax; formatos restritos a JPEG/PNG pelo conteúdo (`formats=`), o que também deixa fora de alcance os plugins com CVE de 2026 (PSD, PDF, EPS, JPEG2000, McIdas); limites de pixels e de proporção pelo cabeçalho; flag de truncado recusada. Riscos remanescentes anteriores à SPEC: SEC-01 e SEC-03 |
| SQL sempre parametrizado | N/A: sem SQL nesta SPEC (a sondagem do SEC-03 usou parâmetro) |
| RLS ligado; `DATABASE_URL`/`service_role` só na API | N/A |
| CORS fechado ou mínimo | N/A |
| Logs sem segredos e sem payloads de imagem | ✅ Nenhum log novo. As mensagens de exceção trazem só as dimensões e o nome da flag, sem bytes da imagem |
| Dependências novas mantidas, com licença compatível e sem CVE crítica | ✅ Nenhuma dependência nova. O Pillow 12.3.0 (já existente) é a versão com as correções de 2026 |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A |
| Privacidade das imagens (R-02, R-14) | ✅ Sem I/O de rede; imagens de teste sintéticas, geradas em memória; nenhum binário no Git |
| Segredos (R-03) | ✅ Nenhum no diff |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| (nenhuma) | — | — | O `uv.lock` muda só a versão de `qc-contracts` e `qc-preprocess` (0.1.0 → 0.2.0) |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
