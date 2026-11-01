# SPEC-042 — r1 — Dev report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-042](../../docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md) |
| Rodada | r1 |
| Autor | ml-engineer (Parte A); o developer acrescenta a Parte B |
| Branch | `spec/SPEC-042-manutencao-telemetria-ca-lote` |

## Parte A (ml-engineer)

**Estado: implementada, sem `SPEC_ISSUE`.** Sem treino e sem métricas de modelo nesta parte.

Commit: `d6304c5`.

### Resumo

- `ml/src/qc_ml/__init__.py`: a atribuição do §4.1, com o texto da SPEC, antes do `__version__`. O arquivo não importa `onnxruntime`, e `parity.py` e `predict.py` não mudam.
- `ml/tests/test_telemetry.py`: testes do autor, em subprocesso e com ambiente montado do zero (`PATH` e `HOME` temporário), sem criar sessão do `onnxruntime`.

### Rastreabilidade (critério de aceite → implementação)

Só a metade de `qc_ml`. A metade de `qc_edge`, o `conftest.py` da raiz e o `.env.example` são da Parte B.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (c), CA-03 | `ml/src/qc_ml/__init__.py` | `ml/tests/test_telemetry.py::test_variable_is_set_before_onnxruntime_loads` (a variável já vale `1` quando `qc_ml.parity` ou `qc_ml.predict` vão carregar o `onnxruntime`, partindo de um `0` herdado). A prova da fila e da rede é do tester |
| CA-04 (`qc_ml`) | `ml/src/qc_ml/__init__.py` | `ml/tests/test_telemetry.py::test_import_forces_the_variable_without_loading_onnxruntime` (variável ausente, vazia, `0` e `1`) |
| CA-06 (`ml/`) | nenhum import novo de `onnxruntime` | Sem teste do autor; o inventário é do tester. Conferi com `git grep`: em `ml/src`, só `predict.py` e `parity.py` |

### Como rodar e verificar

```bash
.venv/bin/python -m pytest ml/tests/test_telemetry.py ml/tests/test_smoke.py -q
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test \
  .venv/bin/python -m pytest ml/tests -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Resultados:

- `ml/tests` inteiro, com o extra `train` (torch 2.14.1): **1385 passed, 2 skipped**. Os dois pulos pedem um `ml/models/*/model.onnx` local, que não existe neste checkout (`test_spec_012.py:650` e `test_parity.py:54`).
- Antes da mudança, 5 dos 6 testes novos falharam. O que passou é o caso em que a variável já vinha com `1`.
- `ruff check` e `ruff format --check` limpos, na árvore inteira.

### Medição parcial do §4.2, só do caminho do treino

Rodei uma vez, para antecipar o risco do §7 (variável definida pelo próprio Python). **Isto não substitui o CA-01, que continua com o tester.**

- **Montagem:** ambiente limpo, `unshare --user --map-root-user --net`, `strace -f -qq -s 256 -e trace=network`, `check_parity(ml/tests/fixtures/tiny_model)` e 35 s de vida depois da sessão.
- **Resultado:** `ok=True`, código 0, 0 linhas no log do `strace` (nenhuma chamada de rede) e nenhum arquivo sob o `HOME` temporário.
- **Conferência do observador:** no mesmo isolamento, um `socket.socket()` de teste apareceu no log, então o `strace` registra chamadas de rede ali. No namespace, só existe o `lo`, desativado.
- **Limite:** não rodei o controle (a), porque ele dispara a telemetria de propósito e é parte do CA-01. Por isso, esta medição **ainda não prova** que a fila apareceria nesse `HOME` temporário nem que o controle consultaria o DNS sob `unshare`. Esse é o outro risco do §7, e só o controle o resolve.

### Decisões tomadas dentro do escopo da SPEC

- O arquivo de teste se chama `test_telemetry.py`, e a Parte B fica livre para ter o seu em `edge/tests/`.
- Acrescentei ao pedido do §6 (a variável depois de `import qc_ml`) a sonda da ordem de carga: um `meta_path` encerra o processo no instante em que o `onnxruntime` ia carregar. Ela roda sem criar sessão, então não dispara telemetria. Se um dos dois módulos deixar de importar o `onnxruntime` no topo, o teste falha, e é preciso revê-lo junto com o CA-06.

### SPEC_ISSUE

Nenhum.

**Observação, sem efeito na implementação:** a linha 198 da SPEC (`| 2026-11-01 | Aprovada pelo humano ...`) é uma linha de tabela solta depois da lista do §8, sem título nem cabeçalho.

### Checagens do autor

- [x] `ruff check .` e `ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example`: sem variável nova nesta parte; o comentário do §4.1 é da Parte B
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
