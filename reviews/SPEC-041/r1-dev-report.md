# SPEC-041 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-041](../../docs/specs/SPEC-041-modelo-provisorio-e-piso-do-split.md) |
| Rodada | r1 |
| Autor | ml-engineer (Parte A); o developer acrescenta a Parte B |
| Branch | `spec/SPEC-041-modelo-provisorio` |

## Parte A (ml-engineer)

**Estado: parada por `SPEC_ISSUE`, sem nenhum código escrito.** A SPEC tem uma contradição no CA-09 e no §4.4, que não dá para cumprir ao pé da letra. Pela regra do loop (`reviews/README.md`, "Quando o problema está na SPEC"), registrei e parei. Nenhum arquivo de `ml/` foi alterado, e a suíte não foi rodada, porque não há o que testar.

### SPEC_ISSUE

#### SPEC_ISSUE-01 (bloqueante): `manifest_sha256` é exigida e proibida no `provisional_report.json`

- **O que a SPEC diz:**
  - §4.4: "Chaves **exatamente**: `model_version`, `model_sha256`, `provisional`, `created_at`, `manifest_sha256`, …".
  - §4.4, mesma seção: "Nenhuma chave de métrica do `qc_ml.evaluate.METRIC_KEYS` além de `model_version` e `model_sha256`".
  - CA-09: "tem exatamente as chaves do §4.4, […] nenhuma outra chave de `METRIC_KEYS`".
- **O que o código diz:** `manifest_sha256` está em `METRIC_KEYS` (`ml/src/qc_ml/evaluate.py:73`). A interseção das 17 chaves do §4.4 com `METRIC_KEYS`, calculada com o código atual, é `manifest_sha256`, `model_sha256` e `model_version`.
- **Consequência:** com a chave, o CA-09 falha em "nenhuma outra chave de `METRIC_KEYS`". Sem ela, falha em "exatamente as chaves do §4.4". Escolher um dos lados seria improvisar, e o teste do tester depende dessa escolha.
- **Opções para o architect:**
  - (a) **Recomendada:** manter a chave e acrescentar `manifest_sha256` à exceção do §4.4 e do CA-09. É um hash da entrada, não uma métrica de qualidade, e é o que liga o modelo provisório ao conjunto que o gerou. A intenção do ADR-024 (nenhuma métrica de qualidade) continua valendo.
  - (b) Tirar `manifest_sha256` do §4.4 e do CA-09. O relatório perde a rastreabilidade do conjunto.

#### SPEC_ISSUE-02: o CA-23 pede `agent_suggestion_label` na stderr de um comando que imprime os problemas na stdout

- **O que a SPEC diz:** CA-23: "`python -m qc_ml.data validate` e `python -m qc_ml.split` saem com 2, a stderr contém `agent_suggestion_label`". §4.9: "Nenhuma chamada existente muda".
- **O que o código diz:** `qc_ml.data.main` chama `print_problems(exc.problems)`, que escreve na **stdout** (`ml/src/qc_ml/data.py:1392`). Os testes do autor exigem isso (`ml/tests/test_data.py:107`, `:188` e `:359`). O `qc_ml.split` já escreve na stderr, então essa metade do CA não tem problema.
- **Opções para o architect:**
  - (a) **Recomendada:** ajustar o texto do CA-23: "o `validate` imprime `agent_suggestion_label` na saída padrão, e o `split`, na stderr". Nenhum comportamento existente muda.
  - (b) Manter o texto, e o `validate` passa a repetir na stderr só as linhas desse código, além da stdout. Atende aos dois lados, com um caso especial no código.
  - Mover todos os problemas do `validate` para a stderr não serve: quebra os testes acima, que a SPEC não autoriza mudar.

#### SPEC_ISSUE-03 (ambiguidade menor): `labeler` de `labels_overrides.csv` no `qc_ml.provisional`

- **O que a SPEC diz:** §4.3: "alguma linha com `labeler` diferente de `agent-suggestion`", sem dizer de qual arquivo. O §4.9 cita os dois arquivos, e o ADR-024 (decisão 4) diz que o `qc_ml.provisional` "recusa um conjunto com qualquer outro". O CA-25 cobre só o manifest.
- **O que o código faz:** com `allow_agent_suggestion=True`, uma linha de `labels_overrides.csv` com `labeler=a` troca o grau sem deixar rastro, porque o `DataFrame` só guarda o `labeler` do manifest.
- **Opções para o architect:**
  - (a) **Recomendada:** o §4.3 passa a dizer "linha mantida do manifest". O efeito é pequeno, porque esse modelo não gera métrica, e nada novo precisa sair do `load_manifest`.
  - (b) Contar também as linhas de `labels_overrides.csv` de imagens não excluídas, na mesma mensagem. É mais estrito, e o `load_manifest` precisa expor essas linhas.

### O que já conferi (para a retomada não repetir)

Conferência feita com o código atual, sem alterá-lo, em diretório temporário já apagado, com dados sintéticos e a fixture `tiny_model`. Nenhum treino.

| Item | Resultado |
|---|---|
| CA-01 (números): `items_per_stratum=3`, `images_per_item=3` | 11 peças e 33 imagens em cada split; `warnings` é `[]` |
| CA-05, com o dataset do CA-01 | `n_items_test_by_grade` vale 2 nos 5 graus; as 7 métricas citadas não são `null`; `few test items for other: 1` aparece; nenhum `grade <g> has` |
| CA-05, com `other` em 10 objetos | `few test items for other` não aparece |
| `partqc-mnv3-provisional-v1` e `partqc-provisional-v1` | passam em `VERSION_NAME_PATTERN` e no padrão do contrato |
| `OnnxInferencer` (leitura de `edge/src/qc_edge/onnx_inferencer.py`) | exige só 5 arquivos, todos entre os 7 do §4.2; ainda não executado |

Fora os três itens acima, a leitura de `config.py`, `data.py`, `split.py`, `train.py`, `export.py`, `report.py` e `synthetic.py` não mostrou outra contradição com a Parte A. Os CAs slow e a lista de testes abaixo do piso (§7) ficam para depois da implementação.

### Rastreabilidade

Nenhum CA implementado nesta passagem.

### Checagens do autor

- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
- [x] Nenhuma imagem, `.onnx` ou operação sobre `~/partqc-entrada/`
- [ ] `ruff` e testes: não se aplicam, porque só este relatório mudou
