# SPEC-012 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-012](../../docs/specs/SPEC-012-ml-treino-export.md) |
| Rodada | r2 (SPEC_ISSUE-01, conserto do CI) |
| Tester | tester |
| Commit testado | `51f08d8`, mais o ajuste do teste de aceite do CA-13 feito neste commit |
| **Veredicto** | **PASS** |

O veredicto é PASS por quatro motivos:
- o CA-13 tem teste de aceite com o texto novo (`ok = False` e `9e-4 < max_abs_diff < 1.1e-3`), e ele passa;
- os demais CAs não mudaram nesta rodada, e os testes de aceite deles continuam passando (sem torch: 49 passam e 15 são pulados, como na r1);
- a suíte inteira passa no ambiente do CI, sem torch e com Postgres 16;
- o ruff está limpo (`check` e `format --check`).

O escopo da r2 (SPEC §6, "Rodada r2", e Histórico de 2026-10-19) é só ajustar os dois testes do CA-13. Nada em `ml/src/`, na fixture ou em outro teste mudou: o `git diff main` da branch toca só `docs/plan.md`, a SPEC, `ml/tests/test_parity.py` e o dev report, além do meu teste de aceite e deste relatório.

## Ajuste do teste de aceite do CA-13

| Arquivo | Teste | Antes → depois | Motivo |
|---|---|---|---|
| `ml/tests/acceptance/test_spec_012.py` | `test_ca13_perturbed_fixture_fails_parity` | `assert result.max_abs_diff >= 1e-3` → `assert 9e-4 < result.max_abs_diff < 1.1e-3` | Novo texto do CA-13 (SPEC_ISSUE-01, Histórico de 2026-10-19). No CI da `main` (run 39191665982), o teste falhou com `max_abs_diff = 0.0009999759495258331` |

`assert result.ok is False` continua igual, e nenhuma outra linha do arquivo mudou. A intenção do CA também não muda: uma perturbação 10 vezes acima da tolerância é detectada, e o `max_abs_diff` a reflete. O teste não foi removido nem renomeado.

Medi localmente o valor que o teste observa, que fica bem dentro da faixa nova:

| Perturbação em `type_probs[0, 0]` | `ok` | `max_abs_diff` |
|---|---|---|
| `+1e-3` (o CA) | `False` | `0.0010000057518482208` |
| `−1e-3` (exploratório) | `False` | `0.000999990850687027` |

O caso `−1e-3` mostra a fragilidade da asserção antiga mesmo nesta máquina: o valor medido fica abaixo de `1e-3` exato. Rodei o teste do CA-13 3 vezes seguidas, e ele passou em todas.

## Outras comparações de float com limite exato

Revisei todas as asserções de `ml/tests/acceptance/test_spec_012.py` que comparam floats. **Não encontrei outra comparação frágil.** O que conferi:

- **Saída do onnxruntime, onde existe ruído de CPU:** o CA-12 usa `max_abs_diff < 1e-4`, com ruído real de ~1e-8 (folga de 4 ordens de grandeza). O CA-10 (*slow*) e o teste extra de `grade_probs` usam `np.allclose(..., atol=1e-5)` para somas de linha. Nenhum desses testes compara com o valor exato da perturbação.
- **Limiares do CA-16, do CA-17, do CA-18 e do teste extra (`== 0.52`, `== 0.50`, `== 0.12`, `== 0.85`, `== 0.35`, `== 0.60`):** são valores das grades de 2 casas da §4.6, escolhidos por aritmética float64 pura (numpy, sem onnxruntime), sem ruído de plataforma. As entradas ficam a pelo menos `0.0025` de cada ponto da grade, por exemplo `0.503 + 0.005·i` contra `0.52`, `p_unusable = 0.125` contra `0.12`/`0.13` e `0.3025 + 0.005·i` contra `0.35`. Uma diferença de arredondamento não muda a escolha.
- **Faixas do CA-19 (`0.50 <= type_threshold <= 0.85` etc.):** são inclusivas e comparam valores de 2 casas da grade, então o extremo da grade passa.
- **Métricas (CA-23, CA-17, CA-18 e extras):** usam `pytest.approx` (padrão `rel=1e-6`, ou `abs=1e-4` onde o CA fixa 4 casas).
- **`EarlyStopper` (extra):** `0.50005` e `0.50009` contra `min_delta = 1e-4` dão folga de `1e-5`, muito acima do épsilon float64.
- **Paridade `qc_ml.decision` × `qc_edge.decision` (extra):** os scores usam `approx(abs=1e-9)`. As decisões booleanas usam 500 vetores Dirichlet aleatórios com seed fixa, e a chance de um cair exatamente num limiar é desprezível.
- **Testes *slow* com torch (CA-02, CA-03, CA-09 e extras):** usam `torch.allclose` (o `atol` mais a tolerância relativa padrão de `1e-5`) ou `approx(abs=1e-6)`, que é a tolerância que o próprio CA-09 fixa. Eles não rodam no CI.

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-13 | `ml/tests/acceptance/test_spec_012.py::test_ca13_perturbed_fixture_fails_parity` | ✅ |
| CA-01 a CA-12, CA-14 a CA-27 | sem mudança desde a r1 (ver `r1-test-report.md`) | ✅ sem torch (os *slow* são pulados com `importorskip("torch")`, como no CI) |
| CA-28 | manual | pendente com a dupla (como na r1) |

Arquivo de aceite sem torch: **49 passed, 15 skipped** (os 14 *slow* e o CA-12 para `ml/models/*/`, porque não existe `model.onnx` local).

## Suíte completa

Ambiente: sem torch, `CI=true`, `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, banco no contêiner `partqc-pg-host` (postgres:16). Só uma suíte com banco rodou por vez.

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
4772 passed, 22 skipped, 1 warning in 290.91s (0:04:50)

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
210 files already formatted
```

Com o Postgres 16, as 3 falhas do dev report (FK e mensagem do Postgres 18.6 em pt_BR) não aparecem. Elas eram do ambiente do autor, não do código.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-01 | baixa | nenhum (fora do escopo da r2) | 1. Copiar `ml/tests/fixtures/tiny_model/` para um diretório temporário. 2. Na `parity_fixture.npz` da cópia, pôr `type_probs[0, j] = NaN`, onde `j = argmax(type_probs[0])` (é `1`). 3. Rodar `check_parity(copia)`. | `ok = False`: a referência não é finita, então a paridade não pode ser afirmada | `ParityResult(ok=True, max_abs_diff=8.94e-08, argmax_equal=True, sha256_match=True, message='parity ok')` |

Causa provável: em `ml/src/qc_ml/parity.py:87`, `max(max_abs_diff, float(np.max(...)))` descarta o `NaN`, porque `max(x, nan)` do Python devolve `x`. Com o `NaN` fora da posição do argmax, o `ok` sai `False` só porque o argmax muda (o `np.argmax` trata `NaN` como máximo). Isso acontece por acaso, não por verificação do `NaN`.

Impacto: a fixture é gerada pelo export a partir do torch. Um `NaN` ali indicaria um modelo já quebrado, e o CA-12 e o CA-13 não são afetados. É parecido com a O-01 da r1 e o RV-03 da revisão da r1 (`NaN` em `choose_thresholds`), mas está em outro módulo. O conserto exige mudar `ml/src/`, o que a §6 da r2 proíbe. Por isso registro o bug para uma SPEC ou rodada futura, e ele **não bloqueia** o veredicto, porque não viola nenhum CA.

## Testes exploratórios (além dos critérios)

Todos foram feitos sobre uma cópia da fixture em diretório temporário:

| Caso | `ok` | `max_abs_diff` | Resultado |
|---|---|---|---|
| `type_probs[0, 0] += 5e-5` (abaixo da tolerância) | `True` | `5.0008e-05` | correto |
| `type_probs[0, 0] += 2e-4` (2 vezes a tolerância) | `False` | `2.0001e-04` | correto |
| `grade_probs[7, 4] += 1e-3` (outra saída, última linha) | `False` | `0.0009999871253967285` | correto, e de novo abaixo de `1e-3` exato |
| `type_probs[0, 0] −= 1e-3` | `False` | `0.000999990850687027` | correto, abaixo de `1e-3` exato |
| `NaN` fora do argmax | `False` | `8.94e-08` | `ok` correto, mas por causa do argmax (ver T-01) |
| `NaN` no argmax | `True` | `8.94e-08` | **T-01** |

O teste do CA-13 também passou 3 vezes seguidas (sem flakiness).

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
