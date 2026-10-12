# SPEC-002 — r2 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-002](../../docs/specs/SPEC-002-pacotes-compartilhados.md) |
| Rodada | r2 |
| Reviewer | reviewer |
| Diff revisado | `main...f311f39`, com foco em `4a5f782..f311f39` (o que mudou desde o review r1) |
| Test report | r2-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Motivo do veredicto: o único achado que bloqueava a r1 (RV-01, alta) foi corrigido na causa, com testes do autor e do tester que falham sem a correção. Os dois opcionais aceitos (RV-04 e RV-07) também foram tratados, e nada além do autorizado mudou. Não há achado novo nesta rodada.

## Achados

Nenhum achado novo na r2.

### Situação dos achados da r1

| ID (r1) | Severidade | Situação na r2 | Verificação |
|---|---|---|---|
| RV-01 (T-01) | alta | **Corrigido** (`9f34958`) | `packages/contracts/src/qc_contracts/schemas.py:37-44`: `_to_utc` captura **só** `OverflowError` e relança `ValueError("datetime out of range after UTC normalization") from exc`. Como `UtcDatetime` é o tipo único de data, a correção cobre `InspectionCreate`, `BatchCreate`, `InspectionRead` (`inspected_at`/`received_at`), `TimeseriesPoint`, `SpcPoint` e `LotSummary`, inclusive aninhados (`SpcResponse.points[i]`). Os testes do autor (`packages/contracts/tests/test_schemas.py:575-684`) e do tester (`packages/contracts/tests/acceptance/test_spec_002.py:921-1016`) exigem **um único** erro `value_error` no `loc` exato. Isso inclui `("items", 1, "inspected_at")` no lote, de modo que um item ruim não contamina os outros. Também há testes de não regressão para os extremos que cabem em UTC. O tester confirmou que os 33+2 casos falham em `4a5f782` e que uma rota FastAPI mínima agora devolve 422 em vez de 500. O `xfail` da r1 foi removido; não restam `xfail` nem `xpass`. |
| RV-04 | baixa | **Tratado** (`6dd7c8d`), dentro do opcional autorizado | `packages/contracts/README.md:57` exige `re.fullmatch` (ou schema/`TypeAdapter`) e dá o exemplo `"edge-01\n"`. As constantes não mudaram, e o CA-02 continua passando. A nota nas SPECs 004, 007 e 014 continua com o architect. O mesmo commit documenta a rejeição de datas fora da faixa nas "Regras principais" (linha 62), o que descreve o comportamento do RV-01 e não acrescenta regra. |
| RV-07 | baixa | **Corrigido** (`2b97ca6`), dentro do opcional autorizado | `packages/preprocess/src/qc_preprocess/image.py:62-63`: `except MemoryError: raise` antes do `except Exception`, e a docstring foi atualizada (linha 24). O `img.load()` (linhas 52-57) já não capturava `MemoryError`. O teste do autor substitui `ImageOps.exif_transpose`/`Image.Image.convert`, ou seja, as dependências, e não a função testada. Confirmei que, com `convert` substituído, os helpers `pattern_image`/`encode` continuam funcionando e o `MemoryError` nasce dentro de `load_image` (traceback `load_image → oom`), então o teste não passa por acaso. O teste de aceite do tester é **sem mock**: roda num processo novo, com `RLIMIT_AS` real (60 e 120 MB de folga). Para qualquer ponto em que a alocação falhe (decodificação, cópia do `exif_transpose` ou `convert`), o resultado esperado é `MemoryError`, o que o torna robusto. É restrito a Linux por `skipif`, que é o sistema do CI. |
| RV-02 / SPEC_ISSUE-01 | média | Inalterado, como pedido | O limite de proporção continua com o architect, antes de a SPEC-007 ir para `In Dev`. Fora do escopo desta SPEC. |
| RV-03 / SPEC_ISSUE-02 | média | Inalterado, como pedido | O teto de `latency_ms` continua com o architect, antes de a SPEC-004 ir para `In Dev`. Fora do escopo desta SPEC. |
| RV-05 | baixa | Inalterado, como pedido | O modo lax continua com o architect. O tester registrou mais um efeito (epoch inteiro grande interpretado como milissegundos), que pertence ao mesmo item. Fora do escopo. |
| RV-06 | baixa | Inalterado, como pedido | `LOAD_TRUNCATED_IMAGES` global continua com o architect. Fora do escopo. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | O diff desde `4a5f782` toca só `schemas.py` (`_to_utc`), `image.py` (um `except MemoryError: raise` e a docstring), o README do contrato, os testes do autor, os de aceite, os relatórios e o status em `docs/plan.md` e na SPEC. Nenhum CA, regra, constante ou valor de contrato mudou (R-08 ✅). As versões continuam `0.1.0`, e a justificativa do dev-report (decisão 1) é correta: a `0.1.0` ainda não está na `main` e o CA-01 fixa esse número. A rastreabilidade do dev-report ganhou duas linhas para as correções da r2. Nenhuma decisão nova foi embutida no código. |
| 2. Regras inegociáveis | ✅ | R-01/R-12: `uv.lock` e `pyproject.toml` não mudaram; não há dependência nova. R-02: N/A. R-03: nenhum segredo no diff (busca por `secret`, `password`, `token`, `api_key`, `postgres://`, `eyJ` nas linhas adicionadas, sem ocorrências). R-04: o contrato só mudou em `packages/contracts`, sem mudar o formato do payload. R-05/R-06/R-11: N/A. **R-07:** `9f34958`, `6dd7c8d`, `2b97ca6` e `8335bbf` (developer) tocam só código de produção, `packages/*/tests/` fora de `acceptance/`, o README do contrato e o dev-report. `2807cd4` (tester) toca só `*/tests/acceptance/` e o test-report. `5384741`, `cbd8e84` e `f311f39` (orchestrator) tocam só o status em `docs/plan.md` e na SPEC. Todos os 8 commits têm o trailer `Agent:`. R-13: todos como `Carlos Moises <…CarlosZeyy@users.noreply.github.com>`, em Conventional Commits, com `Refs: SPEC-002`. |
| 3. Corretude | ✅ | O RV-01 foi resolvido na causa, sem engolir exceções: só `OverflowError` é convertido, com `from exc`. O RV-07 restringe o tratamento genérico em vez de ampliá-lo. Os exploratórios do tester (limites finos de offset, `datetime.min`/`max` como objeto, `tzinfo` hostil, fuzzing de 300 imagens) não acharam exceção crua. |
| 4. Testes | ✅ | Test-report PASS, com os 27 CAs reexecutados e as correções da r2 cobertas por testes que falham contra `4a5f782`. Não há mock do que é testado: o mock do RV-07 no teste do autor é de dependência e está justificado (dev-report, decisão 3), e o teste de aceite correspondente não usa mock. Sem rede. Rodei a suíte: `647 passed, 2 skipped` (os 2 skips são do banco, por falta de `TEST_DATABASE_URL`). Cobertura segundo o tester: `qc_contracts` 100%; `qc_preprocess` 99% no total. |
| 5. Qualidade | ✅ | `ruff check` (All checks passed) e `ruff format --check` (41 files already formatted) limpos. Os comentários do `_to_utc` e do `except MemoryError` explicam o porquê. Os testes do autor repetem fixtures JSON dos modelos de resposta (`SPC_POINT`, `LOT_SUMMARY`, `TIMESERIES_POINT`), mas isso fica restrito aos testes e não duplica lógica de produção. README atualizado. |
| 6. Segurança | N/A | A SPEC tem só a tag `contrato`. O RV-07 melhora a semântica do erro (5xx em vez de 4xx na borda). Os riscos de segurança da r1 (RV-02, RV-06) seguem com o architect. |

## Pontos positivos

- A correção do RV-01 é mínima e precisa: um único ponto (`_to_utc`) cobre todos os modelos, porque a r1 já tinha centralizado as datas em `UtcDatetime`.
- Os testes da r2 verificam o **formato** do erro (um único `value_error` no `loc` exato), e não só o tipo da exceção. Isso garante o 422 bem localizado de que a SPEC-004 precisa.
- O tester transformou o `xfail` em testes de regressão amplos (11 modelo/campo × 3 formas de entrada, lote, aninhado e não regressão) e comparou contra o código da r1.
- O teste de aceite do RV-07 provoca falta de memória real num processo isolado, sem mock, e cobre de verdade os dois pontos da correção.
- O developer respeitou à risca o escopo autorizado e deixou com o architect tudo o que o review da r1 destinou a ele.

## SPEC_ISSUE (se houver)

Nenhum novo. Os da r1 continuam abertos com o architect e **não bloqueiam** esta SPEC:

- **SPEC_ISSUE-01** (RV-02): proporção máxima da imagem no `load_image` ou na rota da SPEC-007. Resolver antes de a SPEC-007 ir para `In Dev`.
- **SPEC_ISSUE-02** (RV-03): teto de `latency_ms` no contrato, por causa da coluna `integer`. Resolver antes de a SPEC-004 ir para `In Dev`.
- Também com o architect, sem prazo bloqueante: RV-04 (nota de `re.fullmatch` nas SPECs 004, 007 e 014), RV-05 (modo estrito campo a campo, se ele quiser) e RV-06 (`LOAD_TRUNCATED_IMAGES`).

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
