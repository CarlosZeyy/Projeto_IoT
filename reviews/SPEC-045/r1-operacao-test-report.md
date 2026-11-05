# SPEC-045 — Operação (§4.7) — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-045](../../docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md) |
| Rodada | operação depois do merge (§4.7, CAs 13 a 16) |
| Tester | tester |
| Commit testado | `b7f0a9a` (branch `ml/partqc-mnv3-v1`, sobre o merge `50e6e44` do PR #77) |
| **Veredicto** | **PASS** nos CAs 13 e 15 e na parte automatizável do CA-16; CA-14 dispensado pelo humano; **pendentes manuais** do CA-16: Release no GitHub e borda com o celular |

Nenhum agente abriu foto nesta conferência. Tudo foi feito sobre CSV, JSON, o `model.onnx` (só hash e paridade) e as CLIs do projeto. Este relatório traz só contagens, `item_id` e códigos `cNN`.

O nome do arquivo segue o padrão `rN-test-report.md`, porque o hook `guard_paths` só deixa o tester escrever `reviews/SPEC-*/r*-test-report.md`.

## Cobertura dos critérios de aceite

| Critério | Como foi conferido | Resultado |
|---|---|---|
| CA-13 | Conferências (1) a (7) na reimportação de 2026-11-05; (1) e (2) repetidas hoje | ✅ PASS |
| CA-14 | Dispensa do humano (ADR-025, resposta 5, opção 6B), registrada no PR #77 | ➖ dispensado |
| CA-15 | PR #77 mergeado; checagem em CSV e `check_item_integrity` sobre o `split_v1` real; testes do ADR-014 na suíte | ✅ PASS |
| CA-16 (automatizável) | `metrics.json`, latência, CHANGELOG, sha256, arquivos versionados e `test_ca12_local_models_parity` | ✅ PASS |
| CA-16 (manual) | Release no GitHub; `MODEL_DIR`, `GET /api/status` e fotos pela `/capture` | ⏳ pendente (não é falha) |

## CA-13: reimportação (conferida pelo tester em 2026-11-05, por volta de 00:20 BRT)

**Decisão do humano** em 2026-11-05 (por volta de 00:05 BRT), na sessão do orquestrador: "Pode importar tudo e fazer o que der pois todos do grupo ja foram informados". Com isso, fecham-se:

- o SEC-45-01: `O-534` e `O-535` liberadas;
- o SEC-45-02: colegas `c01`, `c02` e `c03` avisados.

Importação (ml-engineer):

- `--dry-run`: would import 223, skipped 0, failed 0;
- real: imported 223, skipped 0, failed 0.

| # | Conferência | Esperado | Obtido | Resultado |
|---|---|---|---|---|
| 1 | `qc_edge.privacy --dataset-dir ml/data` | saída 0 e `0 with private data` | `checked 223 images, 0 with private data` | PASS |
| 2 | `qc_ml.data validate --dataset-dir ml/data` | saída 0 | `manifest ok: 223 images, 114 items, 0 excluded, 0 overridden` | PASS |
| 3a | Linhas do manifest | 223 | 223 (backup 223) | PASS |
| 3b | Linhas `contributor` no `sources.csv` | 223 | 223 (backup 223) | PASS |
| 3c | Por colega, contra o backup | iguais | c01=40, c02=94, c03=89 nos dois | PASS |
| 4 | Peças | 114 | 114 | PASS |
| 4 | screw / other / hammer / wrench | 47 / 23 / 7 / 8 | 47 / 23 / 7 / 8 | PASS |
| 4 | spirit_level / pliers / flat_screwdriver / phillips_screwdriver | 2 / 7 / 8 / 7 | 2 / 7 / 8 / 7 | PASS |
| 4 | allen_key / drill / saw / cordless_screwdriver | 1 / 2 / 1 / 1 | 1 / 2 / 1 / 1 | PASS |
| 4 | nut / adjustable_wrench / angle_grinder | 0 | 0 | PASS |
| 5 | `item_id` com dois tipos | nenhum | nenhum | PASS |
| 6 | Linhas alteradas com `notes` começando por `ADR-025:` | todas | 89 de 89 | PASS |
| 7 | Linhas fora do Anexo A iguais ao backup (`item_id`, tipo e grau) | 0 diferenças | 117 linhas, 0 diferenças | PASS |

Conferências extras:

- o Anexo A foi aplicado linha a linha ao backup: 106 linhas cobertas, 0 divergências;
- graus descartados só em `T-506`, `T-542` e `T-546`;
- `labeler` = `a` nas 223 linhas;
- `angle` sem mudança;
- a ligação ao backup foi feita pelo `input_sha256` do `sources.csv`, único nas 223 linhas.

**Repetição em 2026-11-05 à tarde**, sobre o `ml/data` atual e sem `uv sync`:

```text
$ uv run --package qc-edge python -m qc_edge.privacy --dataset-dir ml/data
checked 223 images, 0 with private data                         (exit=0)
$ uv run --package qc-ml python -m qc_ml.data validate --dataset-dir ml/data
manifest ok: 223 images, 114 items, 0 excluded, 0 overridden    (exit=0)
```

**CA-13: PASS.**

## CA-14: concordância entre rotuladores

**Dispensado pelo humano.** Na pergunta 5 do ADR-025, a resposta foi "Dispensar e declarar" (opção 6B, seção "Respostas do humano (2026-11-04)").

Onde a dispensa está registrada:

- na descrição do PR #77, seção "Concordância entre rotuladores (CA-14): dispensada": todos os graus vêm de um único rotulador (`labeler=a`) e não houve concordância neste modelo;
- na mensagem do commit `849189a`;
- na entrada do `ml/models/CHANGELOG.md` (`b7f0a9a`), item "Nenhuma concordância entre rotuladores" das limitações.

Não existe `ml/reports/agreement.json`, o que é coerente com a dispensa.

**CA-14: dispensado.** Não há o que testar, e a dispensa não reprova a operação.

## CA-15: `split_v1` por PR

PR #77, `MERGED`:

- commit `849189a` (`Agent: ml-engineer`) e merge `50e6e44` (pais `0766abc` e `849189a`);
- arquivos do PR: só `ml/splits/split_v1.csv`, `ml/splits/split_v1.json` e `ml/splits/split_v1.sha256`. `git diff --stat 0766abc 50e6e44` mostra os mesmos 3 arquivos;
- checks do PR: `ruff + pytest`, `docker images + pytest -m docker` e GitGuardian, todos `pass`;
- a descrição traz a saída da CLI (exit 0, sem `below_floor`, sem `--defer-types`). Ela também compara as peças por tipo e por split com a projeção do ADR-025 e conclui que não há diferença.

Checagem do tester, só em CSV/JSON, sobre o `split_v1` versionado e o `ml/data/manifest.csv`:

| Conferência | Obtido | Resultado |
|---|---|---|
| Linhas do `split_v1.csv` × manifest | 223 × 223; mesmo conjunto de imagens; 0 imagem repetida | PASS |
| `item_id` em mais de um split (pelo `item_id` do manifest) | nenhum, nas 114 peças | PASS |
| `item_id` em mais de um split (pelo prefixo do nome do arquivo) | nenhum | PASS |
| `qc_ml.split.check_item_integrity(df, assign_splits(df, split))` (regra do ADR-014, código do projeto) | sem `SplitIntegrityError` | PASS |
| Peças por split | train 84, val 15, test 15 | PASS |
| Imagens por split | train 164, val 29, test 30 | PASS |
| `split_v1.sha256` × SHA-256 do CSV | iguais | PASS |
| `split_v1.json` | 5 `small_stratum`, 0 `below_floor`, `deferred_types: []` | PASS |

Peças de teste por tipo:

- 1 de cada: `pliers`, `flat_screwdriver`, `phillips_screwdriver`, `hammer` e `wrench`;
- 3 de `other` e 7 de `screw`;
- 0 dos tipos com 1 ou 2 peças.

Os testes do ADR-014 sobre dados sintéticos também passaram na suíte `ml`:

- `test_split.py::test_items_never_cross_splits`;
- `test_previous_with_item_in_two_splits`;
- `test_old_images_of_an_item_in_two_splits_is_an_integrity_error`;
- `acceptance/test_spec_011.py::test_ca12_items_never_cross_splits`.

Nenhum teste do repositório lê o `split_v1` versionado; a checagem acima cobre o arquivo real.

**CA-15: PASS.**

## CA-16: modelo oficial `partqc-mnv3-v1`

### Parte automatizável (commits `92cfa72` e `b7f0a9a`)

| # | Conferência | Obtido | Resultado |
|---|---|---|---|
| 1 | `metrics.json` local igual ao do commit `92cfa72` | idêntico byte a byte (`cmp`) | PASS |
| 2 | `labels` do `metrics.json` igual ao `labels.json` | igual (12 tipos, 5 graus, 10 sem grau) | PASS |
| 3 | `type_confusion` completa (R-11) | 12 × 12, 30 imagens. Uma linha e uma coluna por tipo do `labels.json`, na mesma ordem. Nenhum tipo omitido: as linhas sem suporte no teste (`allen_key`, `saw`, `drill`, `cordless_screwdriver`, `spirit_level`) aparecem com zeros. Sem `nut`, que não está no modelo | PASS |
| 4 | IC por bootstrap | `grade_qwk_ci95` [-0,0192; 0,7846], `unusable_recall_ci95` [0,0; 0,0], `defective_recall_ci95` [1,0; 1,0] | PASS |
| 5 | `warnings` | 15 avisos: 2 de bootstrap indefinido, 3 de grau com 1 peça no teste e 10 `few test items` | PASS |
| 6 | Latência da máquina "notebook-borda" | `latency_machine: "notebook-borda"`, p50 19,19 ms, p95 21,31 ms, 100 medições | PASS |
| 7 | CHANGELOG: limitações da decisão 7 do ADR-025 | os 8 itens da decisão 7, mais a concordância dispensada (resposta 5) e 2 notas de escopo. Os 8 itens: fundo × colega, 1 foto por peça, teste de 15 peças, nenhuma porca, tipos com 1 ou 2 peças, tipos e fusões do agente, graus divergentes em peças fundidas e outro domínio de captura | PASS |
| 8 | CHANGELOG: peças de teste junto de cada métrica `atingida` | `defective_recall`: 3 peças defeituosas (2 `poor` e 1 `unusable`) entre 7 parafusos, com a ressalva da `defective_precision` de 0,375. `latency_ms_p95`: 30 imagens das 15 peças. As métricas abaixo da meta também trazem o escopo | PASS |
| 9 | Números do CHANGELOG × `metrics.json` e manifest | conferidos: 8 de 10 imagens de parafuso previstas como defeito (3/8 = 0,375); 6 imagens previstas como `saw` (3 de `pliers` e 3 de `phillips_screwdriver`); 3 imagens de `hammer` previstas como `other`; peças por grau no teste 2/1/1/2/1; 73 das 114 peças com 1 foto ("maioria") | PASS |
| 10 | sha256 do `model.onnx` local | `7d295bb6…0e420`, igual ao do `model.sha256` (formato `^[0-9a-f]{64}\n$`), do `model_sha256` do `metrics.json`, do CHANGELOG e das notas de release | PASS |
| 11 | Nenhum `.onnx` ou `.pt` versionado | nenhum `.pt`, `.pth` ou `.ckpt` no `git ls-files`. Os únicos `.onnx` são as 4 fixtures minúsculas de `ml/tests/fixtures/` (SPEC-012). O `model.onnx` do modelo é ignorado (`.gitignore:58`), e os commits `92cfa72` e `b7f0a9a` não trazem `.onnx` nem `.pt`. Os 2 PNG do commit são as matrizes de confusão geradas pelo `evaluate`, não fotos | PASS |
| 12 | Paridade | `test_ca12_local_models_parity[partqc-mnv3-v1]` PASSED; `python -m qc_ml.parity --model-dir ml/models/partqc-mnv3-v1` → `parity ok (max_abs_diff=3.28e-07)`, exit 0 | PASS |

### Pendentes (manuais; não são falha)

- **Release no GitHub** de `partqc-mnv3-v1`, criada pelo orquestrador. Leva as notas de `ml/models/partqc-mnv3-v1/release-notes.md` (geradas por `qc_ml.report release-notes`) e o `model.onnx` anexado.
- **Borda com o celular** (humano, em casa; depende do CA-15 da SPEC-044):
  1. Copiar o modelo para o `MODEL_DIR` da borda.
  2. Conferir que o `GET /api/status` mostra a versão `partqc-mnv3-v1` e o `sha256` `7d295bb6…0e420`.
  3. Fotografar pela página `/capture` pelo menos um parafuso, um martelo ou uma chave de aperto, e um objeto `other`.
  4. Registrar o resultado.

**CA-16: PASS na parte automatizável; pendente na parte manual.**

## Suíte completa

```text
$ uv run pytest -q ml
1541 passed in 749.75s (0:12:29)                     (exit=0; ambiente com torch, sem uv sync)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
334 files already formatted
```

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

- **PR #77 × `metrics.json`.** As peças de teste por grau (2/1/1/2/1) e por tipo batem com o `counts.test` do `metrics.json`: 15 peças, 30 imagens, todas `contributor`, nenhuma externa.
- **Coerência dos hashes.** O `split_sha256` (`61346ce5…d5fe`) e o `manifest_sha256` (`e31c5c92…2289`) do `metrics.json` são os mesmos do PR #77 e do CHANGELOG.
- **Latência reescrita.** O commit diz que só a latência foi reescrita (`--latency-only`). O `metrics.json` tem um único `latency_machine`, sem medição duplicada.
- **Métricas fracas.** O modelo tem `type_accuracy` 0,5667, `grade_qwk` 0,3979 e `unusable_recall` 0,0. Essas métricas aparecem no CHANGELOG como `abaixo da meta`, sem arredondamento a favor (R-11). Isso não é falha da operação: o CA-16 pede métricas honestas, não metas atingidas.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só este relatório.
- [x] Não abri nenhuma foto. O relatório não traz caminho de foto, `source_ref` nem `notes`.
