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

## Parte B (developer)

**Estado: implementada, sem `SPEC_ISSUE`.** O CA-11 e o §3.3 são manuais e ficam com o humano.

Commits: `5384620`, `d838a1a`, `9684cf3`.

### Resumo

- `edge/src/qc_edge/__init__.py`: a atribuição do §4.1, com o texto da SPEC, antes do `__version__`. O arquivo não importa `onnxruntime`, e `onnx_inferencer.py` não muda.
- `conftest.py` da raiz: a mesma atribuição, logo depois dos imports. `.env.example`: o comentário do §4.1, no fim do bloco `qc-edge`, sem linha `CHAVE=valor`.
- `live.html` e `live.js`: o `#lot-in-use`, o `showLot()` com as 4 linhas da tabela do §4.3, chamado no fim de `loadLot` e de `confirmLot` e no evento `input`, e a 3ª linha da faixa verde, com `inspection.lot_id`. `send`, `tick` e o `change` não mudam.
- `edge/README.md`: a seção `### Depois da apresentação`, os passos 1 e 3 de "Usar" e a SPEC no título.
- `edge/tests/test_telemetry.py` (novo) e `edge/tests/test_live_route.py`: testes do autor.

### Rastreabilidade (critério de aceite → implementação)

Só a metade da Parte B. A metade de `qc_ml` está na Parte A, e os testes de aceite são do tester.

| Critério | Arquivo(s) | Teste unitário do autor |
|---|---|---|
| CA-01 (b), CA-02 | `edge/src/qc_edge/__init__.py` | `edge/tests/test_telemetry.py::test_variable_is_set_before_onnxruntime_loads` (partindo de um `0` herdado). A prova da fila e da rede é do tester |
| CA-04 (`qc_edge`) | `edge/src/qc_edge/__init__.py` | `edge/tests/test_telemetry.py::test_import_forces_the_variable_without_loading_onnxruntime` (variável ausente, vazia, `0` e `1`) |
| CA-05 | `conftest.py` | `edge/tests/test_telemetry.py::test_root_conftest_forces_the_variable_without_loading_onnxruntime` |
| CA-06 (`edge/`) | nenhum import novo de `onnxruntime` | Sem teste do autor; o inventário é do tester |
| CA-07 | `.env.example` | `edge/tests/test_telemetry.py::test_env_example_only_comments_the_variable` |
| CA-08 | `edge/README.md` | Sem teste do autor; a leitura do README é do tester |
| CA-09, CA-10 (HTML) | `edge/src/qc_edge/templates/live.html` | `edge/tests/test_live_route.py::test_lot_in_use_comes_right_after_the_field_and_starts_empty` |
| CA-09, CA-10 (`showLot`) | `edge/src/qc_edge/static/live.js` | `edge/tests/test_live_route.py::test_show_lot_writes_as_text_and_runs_on_every_change_of_the_lot` |
| CA-09, CA-10 (faixa verde) | `edge/src/qc_edge/static/live.js` | `edge/tests/test_live_route.py::test_emitted_band_has_the_lot_the_server_recorded_as_a_third_line` |
| CA-11 | `live.html`, `live.js` | Manual, com o humano |

### Como rodar e verificar

```bash
.venv/bin/python -m pytest edge/tests/test_telemetry.py edge/tests/test_live_route.py -q
uv run --no-sync ruff check . && uv run --no-sync ruff format --check .
CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run --no-sync pytest -q
```

Resultados:

- Suíte inteira, com banco: **10253 passed, 117 skipped**, código 0, em 48 min. Nenhum teste de aceite anterior precisou de ajuste.
- `ruff check` e `ruff format --check` limpos, na árvore inteira.
- Os testes do autor contra os arquivos de produção anteriores: **10 failed**, todos os novos, menos o caso em que a variável já vinha com `1`. Com a implementação: 70 passed nos dois arquivos.

### Conferências fora da suíte

Rodei as duas para antecipar riscos. **Nenhuma substitui o CA-01 nem o CA-10, que continuam com o tester.**

**Medição parcial do §4.2, só do caminho da borda.**

- **Montagem:** ambiente limpo, `unshare --user --map-root-user --net`, `strace -f -qq -s 256 -e trace=network`, `import qc_edge.onnx_inferencer`, uma sessão real do `tiny_model` por `qc_edge.onnx_inferencer.onnxruntime.InferenceSession` e 35 s de vida depois dela.
- **Resultado:** código 0, 0 linhas no log do `strace` e nenhum arquivo sob o `HOME` temporário.
- **Conferência do observador:** no mesmo isolamento, um `socket.socket()` de teste gerou 3 linhas no log.
- **Limite:** não rodei o controle (a), como na Parte A. Esta medição ainda não prova que a fila apareceria nesse `HOME` nem que o controle consultaria o DNS sob `unshare`.

**Roteiro parecido com o do CA-10, em Chromium headless com câmera falsa,** em 390×844 e 320×568, com `create_app` real, sink em memória, inferenciador roteirizado e `model_version` provisório, sem nuvem.

- **Passos 1 a 4, 6 e 7:** texto e classe de `#lot-in-use` iguais aos do CA-10 nas duas telas, e nenhum quadro enviado nos passos 1, 2 e 6.
- **Passo 5:** a faixa verde teve 3 linhas, a 2ª `aprovada (modelo provisório)` e a 3ª `Lote: L-001`, com o campo em `L-0`. Com um lote confirmado de 40 caracteres, `measureText` de cada linha ficou dentro de `largura do canvas − 20`.
- **Limites:** o roteiro não leu o `lot_id` do corpo das requisições: o `L-001` foi conferido só pela `inspection.lot_id` que o servidor devolveu e a faixa mostrou. Também não conferiu o sink e não teve o controle negativo. O roteiro ficou fora do repositório.

### Decisões tomadas dentro do escopo da SPEC

- **`#lot-in-use { overflow-wrap: anywhere; }` no `<style>` do `live.html`. A SPEC não pede essa regra; o reviewer pode conferi-la.** Sem ela, medi um lote confirmado de 40 caracteres largos (`W`) que estendia a página a 616 px de largura numa tela de 320 px, com o aviso fora da área visível. Com ela, a largura da página fica igual à da tela, e o texto quebra. O `<p>` continua exatamente como o §4.3 descreve, e esse `#lot-in-use` no `<head>` não tem `id="`, então não afeta a ordem conferida no CA-09.
- Os comandos do passo 4 da seção nova ficam num bloco `bash`, com o efeito de cada um em comentário, na ordem da SPEC.
- O comentário do `conftest.py` explica o motivo próprio dele (os testes que importam `onnxruntime` direto) em vez de repetir o dos `__init__.py`. A atribuição é a mesma.
- `edge/README.md`: acrescentei SPEC-042 à lista do título, como as SPECs anteriores fizeram.

### SPEC_ISSUE

Nenhum.

### Checagens do autor

- [x] `ruff check .` e `ruff format --check .` limpos
- [x] Testes unitários do autor passando
- [x] `.env.example`: o comentário do §4.1; nenhuma variável nova
- [x] Nenhum arquivo em `tests/acceptance/` criado ou alterado por mim
