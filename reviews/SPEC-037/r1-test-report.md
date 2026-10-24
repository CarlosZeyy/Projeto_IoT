# SPEC-037 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-037](../../docs/specs/SPEC-037-manutencao-ml-origem.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `249e918` (código em `0637c7d`) |
| **Veredicto** | **PASS** |

Os testes foram escritos a partir da SPEC (caixa-preta), antes de ler a implementação, em `ml/tests/acceptance/test_spec_037.py`. Os CLIs rodam por `python -m` em subprocesso; o `metrics.json` dos CA-01 a CA-05 é o "metrics base" do §5, escrito pelo teste; o `<reg>` é o `external_sources.csv` gravado por `make_synthetic_dataset(..., external_items_per_stratum=1)`. Nada é mockado além do sistema de arquivos temporário e, no CA-11, do `torch.onnx.export`. Sem internet, sem banco, sem imagem real e sem nada de `ml/data/`.

## Cobertura dos critérios de aceite

Arquivo: `ml/tests/acceptance/test_spec_037.py`.

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `test_ca01_release_notes_valid_base`, `test_ca01_release_notes_invalid_count` (7 casos: texto com quebra de linha, `true`, `-3`, `1.5`, `11.0` escrito como decimal, `null`, `"11"`), `test_ca01_release_notes_invalid_count_keeps_output`, `test_ca01_release_notes_zero_count` | ✅ |
| CA-02 | `test_ca02_release_notes_counts_before_missing_sources` | ✅ |
| CA-03 | `test_ca03_changelog_valid_base`, `test_ca03_changelog_invalid_count` (casos a a h) | ✅ |
| CA-04 | `test_ca04_changelog_without_by_origin_not_checked` | ✅ |
| CA-05 | `test_ca05_changelog_invalid_source_id_line` | ✅ |
| CA-06 | `test_ca06_underflow_refused` (`1e-400`, `2e-324`), `test_ca06_representable_values_accepted` (`1e-300`, `0.30000000000000000001`) | ✅ |
| CA-07 | `test_ca07_sources_unexpected_header` (a coluna extra, com o `validate` CLI; b ordem trocada; c `origin` repetida), `test_ca07_sources_missing_column_without_unexpected_header` | ✅ |
| CA-08 | `test_ca08_registry_unexpected_header` (a coluna extra; b `title`/`url` trocadas; c `license` repetida com `CC-BY-NC-4.0`/`CC0-1.0`; cada um com `load_manifest`, `load_external_sources` e `release-notes`), `test_ca08_registry_exact_header_loads` | ✅ |
| CA-09 | `test_ca09_generator_refuses_collision`, `test_ca09_generator_limit_is_accepted`, `test_ca09_generator_without_contributor_unchanged` | ✅ |
| CA-10 | `test_ca10_export_warnings_logged_in_finally` | ✅ |
| CA-11 | `test_ca11_export_logs_warnings_when_it_raises` (`slow`; pulado sem torch, rodado localmente com torch 2.14.1) | ✅ |

**Controles negativos** (para mostrar que os testes acusam o defeito):

- Com o código da base (`ecb5723`, `ml/src` extraído para um diretório temporário e posto à frente no `PYTHONPATH`, sem tocar a worktree), os testes de aceite acusam 39 falhas: todos os casos inválidos dos CA-01, CA-02 e CA-03, o underflow do CA-06, os três casos dos CA-07 e CA-08, a colisão do CA-09 e 13 testes extras. Os CA-04 e CA-05 passam na base, como esperado (a SPEC só fixa um comportamento que já existia).
- CA-10: a mesma checagem por `ast` aplicada ao `export.py` da base falha (`no Try with torch.onnx.export in body and _log_export_warnings in finalbody`).
- CA-11: com torch, o `export_onnx` da base, sob `torch.onnx.export` substituído por um que avisa e levanta, sai com a exceção e **não** registra nenhum aviso; o da `0637c7d` registra exatamente `torch.onnx.export: <marcador>`.

## Suíte completa

Sem `TEST_DATABASE_URL` e sem `CI=true`, por instrução do orquestrador (o banco de teste pode estar em uso por outro agente). Os testes de banco foram pulados; o orquestrador roda a suíte com banco antes do PR. Esta SPEC não toca a API nem o banco.

```text
# workspace sem torch (estado do CI), na worktree, HEAD 249e918 + test_spec_037.py
$ env -u CI -u TEST_DATABASE_URL uv run pytest -q
5486 passed, 726 skipped, 1 warning in 477.47s (0:07:57)
  (skips: TEST_DATABASE_URL ausente, PARTQC_DOCKER_TESTS ausente, torch ausente, model.onnx local ausente)

# parte slow (CA-11), com o extra train (torch 2.14.1+cu130), só ml/tests
$ uv sync --all-packages --extra train --locked
$ env -u CI -u TEST_DATABASE_URL uv run --no-sync pytest -q ml/tests
837 passed, 2 skipped in 398.15s (0:06:38)
  (skips: ml/models/*/model.onnx real ausente, que não vai para o Git)
$ uv sync --all-packages --locked        # .venv de volta ao estado do CI; torch ausente (conferido)

# só os testes desta SPEC, sem torch
$ uv run pytest -q ml/tests/acceptance/test_spec_037.py
68 passed, 2 skipped (CA-11 e o extra de sucesso do export, ambos slow/torch)

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
233 files already formatted
```

Contagem dos testes desta SPEC: 70 coletados (39 de CA, contando cada caso parametrizado, e 31 extras), 2 deles `slow`.

## Ajustes em testes de aceite de SPECs anteriores

Nenhum. Nenhum teste de aceite das SPECs 011, 012, 031 e 035 falhou, nem foi alterado.

## Bugs encontrados

Nenhum.

## Testes exploratórios (além dos critérios)

Todos automatizados como `test_extra_*` no mesmo arquivo e passando.

| Caso | Resultado |
|---|---|
| Contagem inteira enorme (`10**31`) e `-0` no `by_source` (`release-notes`) | aceitas (são `int` `>= 0` para o `json.loads`); a linha mostra o valor inteiro |
| `1e2`, `1E1` (decimais em notação exponencial) e `false` | recusados com `invalid count in metrics.json: counts.train.by_source.synthetic`, saída 2, stdout vazio |
| `release-notes` com `n_images` e `by_origin.external` inválidos, mas `by_source` válido | sai com 0 e a linha da fonte é a do CA-01 (o §4.1 só manda conferir o `by_source` nesse comando) |
| `changelog` com cinco campos inválidos ao mesmo tempo (`n_images`, `val`/`test` `external`, duas fontes) | uma linha por campo, sem repetição, todos listados |
| `changelog` sem o split `val`; `by_origin` como lista; `by_origin` `null` ou lista nos três splits | o campo `counts.<split>.by_origin.external` é acusado (a seção é gerada porque a chave existe); saída 2 |
| Texto da seção `### Dados` com o metrics base | igual ao da SPEC-035 (CA-13): `Validação e teste: 0 e 0`, `Treino: 11 ... (0,2000)` e a linha `synthetic` |
| `release-notes` com fonte de id válido fora do registro e contagem inválida (`zz-fora`) | só `invalid count ... counts.train.by_source.zz-fora`; nenhuma linha `source not in registry`; o valor não aparece |
| `--max-external-fraction` `0`, `-0.1`, `1.0000001`, `nan`, `inf`, `-inf`, `abc`, `1e-400x` | saída 2, sem `Traceback`, `<splits>` vazio |
| `--max-external-fraction 1` | aceito; `max_external_fraction == 1.0` |
| `sources.csv` com vírgula no fim do cabeçalho (coluna vazia) | um único `unexpected_header` em `sources.csv` |
| `sources.csv` com BOM | `missing_column`, sem `unexpected_header` (§4.4) |
| `sources.csv` e registro com CRLF | continuam aceitos (§3.2) |
| Mensagem do `unexpected_header` com uma coluna extra de nome aleatório | não ecoa o cabeçalho lido; cita as sete colunas esperadas |
| Manifest com uma coluna a mais | continua aceito (regra da SPEC-011, §3.2) |
| `changelog` com registro de cabeçalho inexato | saída 2, stdout vazio |
| Gerador com `include_other=False`, `items_per_stratum=101`, `contributor_items_per_stratum=1`, num `root` aninhado inexistente | `ValueError` citando `items_per_stratum` e `contributor_items_per_stratum`; o `root` não é criado (validação antes do `mkdir`) |
| `ml/README.md` | cita `unexpected_header`, `sources.csv` e `external_sources.csv` (§4.4) |
| Export com sucesso, sob `simplefilter("error")`, com um aviso emitido pelo `torch.onnx.export` (`slow`) | o aviso é registrado uma única vez; o `model.onnx` é criado |

Observações da leitura da implementação (depois dos testes), sem defeito:

- A ordem das linhas de erro segue a tabela do §4.1 (decisão 1 do dev-report); os testes de aceite não dependem da ordem.
- O `release-notes` confere o registro antes das contagens (decisão 6); compatível com o §4.1 ("depois da leitura ... do registro").
- Um `counts.train.by_source` que não é objeto continua com o erro da SPEC-035 (decisão 5), sem listar os outros campos; nada é gravado.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
