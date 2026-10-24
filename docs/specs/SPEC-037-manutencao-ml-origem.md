# SPEC-037: Manutenção do ML (contagens do `metrics.json` nas notas do Release e no CHANGELOG, teto com underflow, cabeçalho exato, gerador sintético e avisos do export)

| Campo | Valor |
|---|---|
| Status | In Dev |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer |
| Tags | — |
| Depende de | SPEC-035 (PR #44; `Done` antes de esta entrar em `In Dev`), SPEC-031 |
| Semana alvo | S3–S4. **`Done` antes do primeiro GitHub Release de um modelo** (SPEC-012 §4.9), porque as notas do Release mostram os créditos das fontes externas na página pública (SPEC-035 §4.6). Não bloqueia o `split_v1` |
| Requisitos cobertos | RNF-07; R-11 (métricas e contagens reportadas como foram medidas) |
| ADRs relevantes | ADR-020 (`Aceito`), ADR-014, ADR-004 |

## 1. Contexto

Fecha as pendências não bloqueantes dos portões r1 das SPECs 035 e 031. Nada muda no contrato, na borda, nas chaves do `metrics.json`, nos artefatos de `docs/architecture.md` §7, no split das peças próprias nem na regra de decisão. A skill `ml-pipeline` continua valendo inteira.

| Pendência | Origem | Severidade | O que entra aqui |
|---|---|---|---|
| RV-01 (= T-01) | `reviews/SPEC-035/r1-review-report.md` e `reviews/SPEC-035/r1-test-report.md` | média | As contagens do `metrics.json` são conferidas antes de aparecer nas notas do Release e na seção `### Dados` do CHANGELOG: só `int` não negativo, sem `bool` (§4.1) |
| RV-02 | `reviews/SPEC-035/r1-review-report.md` | baixa | `--max-external-fraction` que vira `0.0` no `float` (underflow) sai com 2, sem traceback (§4.2) |
| RV-03 | `reviews/SPEC-035/r1-review-report.md` | baixa | `<invalid source_id>` no CHANGELOG registrado como comportamento (§4.3) |
| RV-04 | `reviews/SPEC-035/r1-review-report.md` | baixa | Cabeçalho exato de `sources.csv` e de `ml/external_sources.csv`, com o código `unexpected_header` (§4.4) |
| RV-05 | `reviews/SPEC-035/r1-review-report.md` | baixa | O gerador sintético recusa a combinação que faz peças de conhecido colidirem com peças próprias (§4.5) |
| RV-01 | `reviews/SPEC-031/r1-review-report.md` | baixa | Avisos capturados do `torch.onnx.export` são registrados também quando o export levanta exceção (§4.6) |
| RV-02 | `reviews/SPEC-031/r1-review-report.md` | baixa | Sem ação (§3.2) |

**Por que antes do primeiro Release.** Pela decisão do humano de 2026-10-23, os créditos das fontes externas aparecem na própria página do GitHub Release, gerada pelo `release-notes` (SPEC-035 §4.6). Hoje, um valor de `counts.train.by_source` que não é inteiro sai literalmente nas notas: com uma quebra de linha, ele cria uma linha de fonte forjada e pendura o crédito da fonte real nela (T-01). O `metrics.json` é gerado pelo pipeline e vai para o Git por PR, então o caso exige um arquivo editado à mão ou corrompido. Mesmo assim, a página é pública, e a premissa "cada fonte ocupa exatamente uma linha" (SPEC-035 §4.6) tem de valer pelo código, não pela origem do arquivo.

**Relação com a SPEC-035.** As §4.1, §4.3 e §4.4 são **texto vigente que complementa** a SPEC-035 §4.2, §4.3 e §4.6, sem alterar o arquivo dela (mesmo precedente da SPEC-031 §4.4 em relação à SPEC-012). Quem lê a SPEC-035 lê também esta seção.

## 2. Objetivo

O `release-notes` e o `changelog` saem com 2, sem gravar nada, quando uma contagem do `metrics.json` não é inteiro não negativo; o `split` sai com 2 quando o teto vira zero; `sources.csv` e o registro só são aceitos com o cabeçalho exato; o gerador sintético nunca produz `item_id` repetido com rótulo diferente; e os avisos do export ficam no log também quando o export falha.

## 3. Escopo

### 3.1 Dentro

- `ml/src/qc_ml/report.py`: conferência das contagens no `release-notes` e na seção `### Dados` do `changelog` (§4.1); a linha de fonte com `<invalid source_id>` continua como está (§4.3).
- `ml/src/qc_ml/split.py`: `_fraction_argument` (§4.2).
- `ml/src/qc_ml/data.py`: cabeçalho exato de `sources.csv` e do registro, com o código `unexpected_header` (§4.4). O manifest, o `labels_overrides.csv` e o `exclusions.csv` **não** mudam.
- `ml/src/qc_ml/synthetic.py`: validação dos parâmetros de `make_synthetic_dataset` (§4.5).
- `ml/src/qc_ml/export.py`: `export_onnx` com `try`/`finally` (§4.6).
- `ml/README.md`: na seção "Origem das imagens", uma frase sobre o cabeçalho exato dos dois arquivos (§4.4).
- Testes do autor em `ml/tests/` (fora de `acceptance/`).
- **Tester:** `ml/tests/acceptance/test_spec_037.py`. Nenhum ajuste em testes de aceite antigos é esperado: os testes das SPECs 011, 012, 031 e 035 usam contagens inteiras e os cabeçalhos exatos. Se algum falhar por causa de um requisito escrito aqui, vale a regra "Testes de aceite de SPECs anteriores" de `docs/architecture.md` §10.

### 3.2 Fora

- **RV-02 da SPEC-031** (`tests/test_dependency_isolation.py` compara conjuntos de nomes e não acusa um requisito repetido): **sem ação**. O CA-04 da SPEC-031 já exige uma única entrada `"torch<2.15"` no extra `train`, que é a única entrada com efeito na R-12. Um nome repetido entre os outros quatro (`torchvision`, `timm`, `onnx`, `coral-pytorch`) não muda o que o `qc-api` e o `qc-dashboard` resolvem. O arquivo é teste de autor do developer, fora de `ml/**`: corrigi-lo exigiria uma passada de outro papel nesta SPEC, como na SPEC-031 §4.8, para um benefício pequeno. Se o arquivo for tocado de novo por outra SPEC, a sugestão do reviewer (`len` da lista igual ao do conjunto de nomes) entra nela. Ver a pergunta 2 do §9.
- Normalização PEP 503 dos nomes no mesmo teste: sem ação (os nomes atuais não precisam; RV-02 da SPEC-031).
- Coerência entre contagens (por exemplo, a soma de `by_source` igual a `by_origin.external`, ou `e_train <= n_train`): fora. Esta SPEC confere o **tipo** de cada contagem que é exibida, e não a aritmética entre elas: o pipeline grava as duas a partir da mesma tabela (`split_counts`, SPEC-035 §4.6).
- Fim de linha CRLF em `sources.csv` e no registro: continua aceito (o módulo `csv` normaliza, e os gravadores usam `\n`). Sem ação.
- O valor de `--max-external-fraction` com mais dígitos do que o `float` representa (por exemplo, `0.30000000000000000001` vira o teto `0.3`): sem mudança de comportamento, só registrado na §4.2.
- O cabeçalho do manifest, do `labels_overrides.csv` e do `exclusions.csv`: continua a regra da SPEC-011 §4.1 (só coluna obrigatória ausente é erro).
- Mostrar a origem das imagens no dashboard: fora, como na SPEC-035 §3.2.

## 4. Requisitos detalhados

### 4.1 Contagens do `metrics.json` (RV-01 da SPEC-035; complementa a SPEC-035 §4.6)

**Contagem válida** = valor JSON que o `json.loads` devolve como `int` e que não é `bool`, com valor `>= 0`. Qualquer outro valor é inválido, inclusive `true`/`false`, número negativo, número com parte decimal (`1.5`) ou escrito como decimal (`11.0`), `null`, texto (`"11"`) e ausência do campo quando ele é exigido.

**Campos conferidos:**

| Comando | Campo (nome usado na mensagem) | Quando |
|---|---|---|
| `release-notes` | `counts.train.by_source.<id>`, um por fonte | sempre que `counts.train.by_source` for um objeto não vazio. São os únicos números do `metrics.json` que entram nas notas; os demais campos não são conferidos por este comando |
| `changelog` | `counts.train.n_images` | quando a seção `### Dados` é gerada (algum split tem `by_origin`, SPEC-035 §4.6) |
| `changelog` | `counts.train.by_origin.external`, `counts.val.by_origin.external`, `counts.test.by_origin.external` | idem. O `by_origin` do split tem de ser um objeto com a chave `external`; split ausente, `by_origin` ausente ou que não é objeto, e chave ausente tornam o campo inválido |
| `changelog` | `counts.train.by_source.<id>`, um por fonte | idem, quando `counts.train.by_source` for um objeto não vazio |

- `<id>` na mensagem é o `source_id` como as linhas de fonte o mostram: o próprio valor quando casa `re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", valor)` (SPEC-035 §4.3) e `<invalid source_id>` nos outros casos.
- **Por que o `changelog` exige os campos ausentes.** A linha `- Validação e teste: <e_val> e <e_test> imagens externas (ADR-020).` afirma a integridade do split (R-11). Com a seção gerada, um campo ausente mostrado como `0` afirmaria algo que não foi medido. Um `metrics.json` sem `by_origin` em nenhum split (anterior à SPEC-035) continua sem a seção e sem conferência, como hoje (CA-13 da SPEC-035).
- **Erro:** código 2. A saída de erro tem uma linha com `invalid count in metrics.json: <campo>` para **cada** campo inválido (pode vir depois do prefixo do comando, `report failed:` ou `release-notes failed:`, seguido de um espaço). A mensagem **nunca** contém o valor inválido. O stdout fica vazio. No `release-notes`, o `--output` não é criado nem alterado; no `changelog`, o arquivo do `--append` não é criado nem alterado.
- **Ordem no `release-notes`:** a conferência das contagens vem depois da leitura do `model.sha256`, do `metrics.json` e do registro, e **antes** da conferência das fontes ausentes do registro. Com alguma contagem inválida, as linhas `source not in registry: …` não são impressas.
- Nada mais muda nos dois comandos: o texto gerado com contagens válidas é o mesmo, byte a byte, de hoje (CA-13 e CA-16 a CA-19 da SPEC-035).

### 4.2 `--max-external-fraction` com underflow (RV-02 da SPEC-035)

- `_fraction_argument` (o `type` do `argparse`) passa a conferir também o valor **depois** da conversão para `float`: se `float(valor)` não estiver em `(0, 1]`, levanta `argparse.ArgumentTypeError`. Com isso, `1e-400` (que vira `0.0`) sai com 2 pela regra da SPEC-035 §4.4 ("outro valor sai com 2"), sem traceback e sem gravar nada.
- Valores pequenos que o `float` representa (por exemplo, `1e-300`) continuam aceitos, e o `split_v<N>.json` grava o `float` usado em `max_external_fraction`.
- Comportamento registrado, sem mudança: o teto usado é `float(Decimal(texto))`. Um texto com mais precisão do que o `float` tem (por exemplo, `0.30000000000000000001`) é usado como `0.3`, e é esse valor que vai para o `split_v<N>.json` e para a comparação exata do §4.4 da SPEC-035.
- `make_split` não muda (já levanta `ValueError` fora de `(0, 1]`).

### 4.3 `<invalid source_id>` no CHANGELOG (RV-03 da SPEC-035; complementa a SPEC-035 §4.6)

Texto vigente da linha de fonte da seção `### Dados`: um `source_id` de `counts.train.by_source` que não casa o formato do §4.3 da SPEC-035 aparece como `` `<invalid source_id>` ``, e nunca com o valor literal. Como nenhum id fora do formato está no registro, a linha é `` - `<invalid source_id>`: <n> imagens, licença não encontrada no registro ``. O `changelog` continua saindo com 0 nesse caso (só marca a linha, como para qualquer fonte fora do registro). A ordem das linhas continua a ordem dos `source_id` **originais** (a do `sorted` sobre as chaves do `metrics.json`). É o comportamento atual do código (decisão 7 do `reviews/SPEC-035/r1-dev-report.md`); esta SPEC só o fixa num CA. O `release-notes` continua como a SPEC-035 §4.6 já define (sai com 2, `source not in registry: <invalid source_id>`).

### 4.4 Cabeçalho exato de `sources.csv` e do registro (RV-04 da SPEC-035; complementa a SPEC-035 §4.2 e §4.3)

**Decisão:** a SPEC-035 diz cabeçalho "**exatamente**" `image_path,origin,contributor,source_id,source_ref,input_sha256` e `source_id,title,url,license,license_url,attribution,retrieved_at`, e esta SPEC torna isso verificável, com um código próprio. O texto não vira "colunas obrigatórias".

Justificativa:

1. **Coluna repetida.** O `parse_csv` monta cada linha com `dict(zip(cabeçalho, valores))`, então, com um nome de coluna repetido, vale o **último** valor. No registro, que a dupla edita à mão e revisa por PR, uma segunda coluna `license` no fim faria o código ler `CC0-1.0` enquanto a coluna que aparece primeiro no diff diz `CC-BY-NC-4.0`. É um caminho para contornar a lista fechada de licenças (ADR-020, decisão 3) sem que o revisor perceba.
2. **Coluna extra ignorada em silêncio.** Uma coluna a mais no registro (por exemplo, `license_note`) seria descartada, e quem a escreveu poderia achar que ela vai para os créditos.
3. **Mesmo formato dos dois lados.** O importador da SPEC-036 já recusa um `sources.csv` existente com outro cabeçalho (`sources header mismatch`). Com o leitor aceitando colunas reordenadas, um arquivo que passou no `validate` faria a próxima importação parar. Com a mesma regra nos dois lados, o problema aparece no `validate`.
4. **Custo baixo.** Os gravadores (o importador e o gerador sintético) e o `ml/external_sources.csv` do repositório já usam o cabeçalho exato (CA-14 da SPEC-035). O manifest continua com a regra da SPEC-011, porque o leitor do manifest é anterior e tem testes próprios que dependem dela.

Regra:

- Ao ler `sources.csv` (no `load_manifest` e no `load_sources`) e o registro (no `load_manifest` e no `load_external_sources`), se **nenhuma** coluna obrigatória faltar e o cabeçalho (a lista de campos do registro CSV 1) for diferente da tupla exata, o arquivo ganha **um** problema `unexpected_header`, com `file` igual a `sources.csv` ou `external_sources.csv`, `line = 1`, `image_path = None` e uma mensagem que cita a lista esperada, sem repetir o cabeçalho lido. Isso cobre coluna extra, coluna repetida, coluna vazia (vírgula no fim) e ordem diferente.
- Se faltar alguma coluna obrigatória, vale só o `missing_column` de hoje (um por coluna), sem `unexpected_header`. Um arquivo com BOM continua dando `missing_column` na primeira coluna.
- O `unexpected_header` tem o **mesmo efeito** do `missing_column` em cada arquivo: as linhas não são validadas uma a uma; em `sources.csv`, o `missing_source` não é gerado (decisão 2 do `reviews/SPEC-035/r1-dev-report.md`); no registro, nenhuma fonte é carregada, e as linhas `external` do `sources.csv` acusam `unknown_source_id`, como hoje com o `missing_column` no registro.
- O problema entra na mesma `ManifestError` e no resumo `count unexpected_header: <n>` do `validate`. No `release-notes` e no `changelog`, um registro com `unexpected_header` sai com 2, como qualquer problema do registro (SPEC-035 §4.6).
- `ml/README.md`, seção "Origem das imagens": uma frase dizendo que `sources.csv` e `ml/external_sources.csv` têm de ter o cabeçalho exato, na ordem, sem coluna a mais, e que outro cabeçalho é recusado com `unexpected_header`.

### 4.5 Gerador sintético sem colisão de `item_id` (RV-05 da SPEC-035)

- Em `make_synthetic_dataset`, com `contributor_items_per_stratum > 0`, se o último número de peça própria de alguma letra for `>= 501` (o primeiro número das peças de conhecido, SPEC-035 §4.7), levanta `ValueError` com uma mensagem que cita `items_per_stratum` e `contributor_items_per_stratum`. O último número próprio é `items_per_stratum × 5` para `S` e `N` e, com `include_other`, `items_per_stratum` para `O`. Com os limites atuais, só `S` e `N` alcançam a colisão (`items_per_stratum >= 101`); a regra vale para as três letras, para continuar certa se os limites mudarem.
- A conferência acontece junto das outras validações de parâmetros, **antes** de criar o diretório ou qualquer arquivo.
- Com `contributor_items_per_stratum = 0`, nada muda (não há peças de conhecido para colidir). Os arquivos gerados com parâmetros válidos são os mesmos, byte a byte, de hoje (CA-15 da SPEC-035).

### 4.6 Avisos do export quando o `torch.onnx.export` falha (RV-01 da SPEC-031; complementa a SPEC-031 §4.3, item 2)

- Em `export_onnx`, a chamada a `_log_export_warnings(caught)` passa para o `finally` de um `try` que envolve o `torch.onnx.export`. Assim, os avisos capturados até a falha (por exemplo, o aviso de depreciação que explicaria a quebra do caminho TorchScript) viram registros `WARNING` no logger `qc_ml.export` antes de a exceção sair.
- A exceção do `torch.onnx.export` sai **sem conversão** (a mesma classe e a mesma mensagem de hoje). Os avisos continuam sem ser reemitidos, e o export continua com `dynamo=False`.
- Os avisos são registrados uma única vez por chamada, com sucesso ou com falha. No caminho de sucesso, o comportamento é o de hoje (CA-05 da SPEC-031).
- A posição exata do `try` (dentro ou em volta do `with warnings.catch_warnings(record=True)`) fica com o autor, desde que a lista capturada exista quando o `finally` roda. O registro dos avisos fora do bloco `catch_warnings` é preferível: um aviso emitido pelo próprio `logging` não fica preso na lista.

## 5. Critérios de aceite

Contexto comum dos CA-01 a CA-05: um diretório de modelo `<dir>` em `tmp_path` com `model.sha256` igual a `"0123456789abcdef" * 4 + "\n"` e um `metrics.json` escrito pelo teste, aqui chamado de **"metrics base"**:

```json
{"model_version": "partqc-test-v1",
 "counts": {
   "train": {"n_images": 55, "by_origin": {"capture": 44, "contributor": 0, "external": 11}, "by_source": {"synthetic": 11}},
   "val":   {"n_images": 20, "by_origin": {"capture": 20, "contributor": 0, "external": 0},  "by_source": {}},
   "test":  {"n_images": 22, "by_origin": {"capture": 22, "contributor": 0, "external": 0},  "by_source": {}}}}
```

O registro `<reg>` é o registro sintético da SPEC-035 §4.7 (o `external_sources.csv` gravado por `make_synthetic_dataset(..., external_items_per_stratum=1)`, ou gravado pelo teste com os mesmos valores). "Editado" = o teste muda só o campo descrito no metrics base. `<marcador>` é um texto gerado no teste (por exemplo, com `uuid4().hex`).

- **CA-01 (RV-01, `release-notes`)** — *Dado* o metrics base, *quando* `python -m qc_ml.report release-notes --model-dir <dir> --external-sources <reg> --output <tmp>/notes.md` roda, *então* sai com 0 e o arquivo tem a linha `` - `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images | Licença: https://creativecommons.org/publicdomain/zero/1.0/ | Fonte: https://example.org/synthetic ``. *Dado* o metrics base com `counts.train.by_source.synthetic` editado, em casos separados, para ``"11 imagens\n- `forged`: 9"`` (texto JSON com quebra de linha), `true`, `-3`, `1.5`, `11.0`, `null` e `"11"`, *quando* o mesmo comando roda, *então* sai com 2, o stdout fica vazio, `<tmp>/notes.md` não existe, a saída de erro contém `invalid count in metrics.json: counts.train.by_source.synthetic` e não contém `forged`. *Dado* o primeiro desses casos com `<tmp>/notes.md` já contendo `antigo\n`, *então* o arquivo continua com `antigo\n`. *Dado* o valor `0`, *então* sai com 0 e a linha da fonte começa com `` - `synthetic`: 0 imagens, CC0-1.0. ``.
- **CA-02 (RV-01, `release-notes`, ordem das conferências)** — *Dado* o metrics base com `counts.train.by_source` editado para `{"bad<marcador>‮": "x\ny", "synthetic": 11}`, *quando* `release-notes` roda com `--output <tmp>/notes.md`, *então* sai com 2, o stdout fica vazio, `<tmp>/notes.md` não existe, a saída de erro contém `invalid count in metrics.json: counts.train.by_source.<invalid source_id>` e não contém `<marcador>`, `‮` nem `source not in registry`.
- **CA-03 (RV-01, `changelog`)** — *Dado* `<tmp>/CHANGELOG.md` com o conteúdo `# CHANGELOG\n` e o metrics base, *quando* `python -m qc_ml.report changelog --model-dir <dir> --external-sources <reg> --append <tmp>/CHANGELOG.md` roda, *então* sai com 0, o stdout tem a linha `- Treino: 11 imagens externas de 55 (0,2000).` e o arquivo cresce. *Dado* o mesmo arquivo `# CHANGELOG\n` e o metrics base editado, em casos separados, (a) `counts.train.by_source.synthetic` = ``"11 imagens\n- `forged`: 9"``, (b) `counts.train.n_images` = `"x\nINJ<marcador>"`, (c) `counts.val.by_origin.external` = `true`, (d) `counts.test.by_origin.external` = `-1`, (e) `counts.train.by_origin.external` = `1.5`, (f) `counts.val.by_origin` sem a chave `external`, (g) `counts.test` sem `by_origin` e (h) `counts.train` sem `n_images`, *quando* o mesmo comando roda, *então* sai com 2, o stdout fica vazio, o arquivo continua com `# CHANGELOG\n`, a saída de erro contém `invalid count in metrics.json: <campo>`, com `<campo>` igual a, respectivamente, (a) `counts.train.by_source.synthetic`, (b) `counts.train.n_images`, (c) `counts.val.by_origin.external`, (d) `counts.test.by_origin.external`, (e) `counts.train.by_origin.external`, (f) `counts.val.by_origin.external`, (g) `counts.test.by_origin.external` e (h) `counts.train.n_images`, e não contém `forged` nem `<marcador>`.
- **CA-04 (RV-01, `metrics.json` anterior à SPEC-035)** — *Dado* o metrics base sem a chave `by_origin` em nenhum split e com `counts.train.n_images` = `"x"`, *quando* o `changelog` roda como no CA-03, *então* sai com 0 e a entrada não tem a linha `### Dados`.
- **CA-05 (RV-03, `<invalid source_id>` no CHANGELOG)** — *Dado* o metrics base com `counts.train.by_source` editado para `{"bad<marcador>‮": 1, "synthetic": 11}`, *quando* o `changelog` roda com `--external-sources <reg>` (sem `--append`), *então* sai com 0; as linhas da seção `### Dados` que começam com `` - ` `` são exatamente duas, nesta ordem: `` - `<invalid source_id>`: 1 imagens, licença não encontrada no registro `` e `` - `synthetic`: 11 imagens, CC0-1.0. Crédito: Synthetic test images ``; e o stdout não contém `<marcador>` nem `‮`.
- **CA-06 (RV-02, teto com underflow)** — *Dado* `make_synthetic_dataset(<root>)` com os parâmetros padrão (sem externas) e um `<splits>` vazio, *quando* `python -m qc_ml.split --dataset-dir <root> --splits-dir <splits> --external-sources <tmp>/inexistente.csv --max-external-fraction <x>` roda, *então*: com `<x>` igual a `1e-400` e a `2e-324`, sai com 2, a saída de erro não contém `Traceback`, e `<splits>` continua vazio; com `1e-300`, sai com 0 e o `split_v1.json` tem `max_external_fraction == 1e-300`; e, num `<splits>` vazio novo, com `0.30000000000000000001`, sai com 0 e o `split_v1.json` tem `max_external_fraction == 0.3`.
- **CA-07 (RV-04, cabeçalho de `sources.csv`)** — *Dado* `make_synthetic_dataset(<root>, contributor_items_per_stratum=1, external_items_per_stratum=1)` (o dataset do CA-02 da SPEC-035) com o `sources.csv` reescrito pelo teste com `csv.writer`, mantendo as mesmas linhas, em casos separados: (a) com uma coluna `notes` a mais no fim (vazia em todas as linhas); (b) com as colunas `origin` e `contributor` trocadas de posição no cabeçalho e nos valores; (c) com uma segunda coluna `origin` no fim, igual à primeira em todas as linhas; *quando* `load_manifest(<root>, external_sources=<root>/external_sources.csv)` é chamado, *então* levanta uma `ManifestError` em que os problemas com `file == "sources.csv"` são exatamente um, com `code == "unexpected_header"` e `line == 1`, e nenhum problema tem `code` igual a `missing_source` ou `missing_column`; e, no caso (a), `python -m qc_ml.data validate --dataset-dir <root> --external-sources <root>/external_sources.csv` sai com 2 e imprime `count unexpected_header: 1`. *Dado* o cabeçalho sem a coluna `input_sha256` (como no CA-04 da SPEC-035), *então* há `missing_column` com `file == "sources.csv"` e nenhum `unexpected_header`.
- **CA-08 (RV-04, cabeçalho do registro)** — *Dado* o dataset do CA-07 com o `external_sources.csv` reescrito pelo teste com `csv.writer`, com a mesma fonte `synthetic`, em casos separados: (a) com uma coluna `notes` a mais no fim; (b) com as colunas `title` e `url` trocadas de posição no cabeçalho e nos valores; (c) com `license = CC-BY-NC-4.0` na coluna `license` original e uma segunda coluna `license` no fim, com `CC0-1.0`; *quando* `load_manifest` é chamado como no CA-07, *então* levanta uma `ManifestError` com um problema `code == "unexpected_header"`, `file == "external_sources.csv"` e `line == 1`; `load_external_sources(<arquivo>)` levanta `ManifestError` com o mesmo problema; e `release-notes` com o metrics base e esse registro sai com 2, com o stdout vazio. *Dado* o registro com o cabeçalho exato, *então* `load_external_sources` não levanta erro e devolve a fonte `synthetic`.
- **CA-09 (RV-05, gerador)** — *Dado* `make_synthetic_dataset(<root>, items_per_stratum=101, images_per_item=1, contributor_items_per_stratum=1)`, *então* levanta `ValueError` e `<root>/manifest.csv` não existe. *Dado* `items_per_stratum=100, images_per_item=1, contributor_items_per_stratum=1`, *então* não levanta erro, o manifest tem 1.111 `item_id` distintos (500 `S-`, 500 `N-` e 100 `O-` próprios, mais 5 `S-`, 5 `N-` e 1 `O-` de conhecido), cada `item_id` aparece com um único par (`object_type`, `grade`), e `load_manifest(<root>, external_sources=<tmp>/inexistente.csv)` não levanta erro. *Dado* `items_per_stratum=101, images_per_item=1, contributor_items_per_stratum=0`, *então* não levanta erro e o manifest tem 1.111 linhas.
- **CA-10 (RV-01 da SPEC-031, estático)** — *Dado* `ml/src/qc_ml/export.py` analisado com `ast`, *então*, na função `export_onnx`, existe um nó `Try` cujo `finalbody` tem uma chamada a `_log_export_warnings` e cujo `body` contém, em qualquer profundidade, a chamada `torch.onnx.export`; e nenhuma chamada a `_log_export_warnings` em `export_onnx` está fora de um `finalbody`.
- **CA-11 (RV-01 da SPEC-031, com torch)** — *Dado* torch instalado (`pytest.importorskip("torch")`, marcador `slow`), `warnings.simplefilter("error")` ativo no teste e `torch.onnx.export` substituído (com `monkeypatch`) por uma função que chama `warnings.warn("<marcador1>", DeprecationWarning)` e depois levanta `RuntimeError("<marcador2>")`, *quando* `export_onnx` é chamado com a mesma rede mínima do CA-05 da SPEC-031 e um caminho em `tmp_path`, *então* levanta `RuntimeError` cuja mensagem contém `<marcador2>`, e o `caplog` tem exatamente um registro `WARNING` do logger `qc_ml.export` com a mensagem `torch.onnx.export: <marcador1>`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | Função de conferência das contagens (tabela de valores válidos e inválidos, inclusive `bool` e inteiro grande); mensagem sem o valor; ordem das conferências no `release-notes`; `_fraction_argument` com underflow e com subnormal representável; `unexpected_header` nos dois arquivos, com BOM e com coluna faltando; gerador com a colisão e no limite; export com aviso e exceção (com torch, `slow`) | `ml/tests/` |
| Aceite (tester) | Um por CA; CLIs via `main(argv)` ou subprocesso; o CA-11 marcado `slow` | `ml/tests/acceptance/test_spec_037.py` |

- Nada é mockado além do sistema de arquivos temporário e, no CA-11, do `torch.onnx.export` (fronteira com a biblioteca). Sem internet, sem dados reais e sem banco.
- Os CA-01 a CA-05 não precisam de torch nem de rodar o pipeline: o `metrics.json` é escrito pelo teste.
- O CA-09 gera cerca de 1.100 imagens sintéticas pequenas por caso, na ordem do CA-07 da SPEC-035. Se o tempo de CI pesar, o tester pode gerar o dataset uma vez por módulo (`scope="module"`).
- A parte `slow` (CA-11) roda localmente com `uv sync --all-packages --extra train`, registrada no test-report, e o `.venv` volta ao estado do CI depois (como na SPEC-031). Nesse ambiente, rode só `ml/tests`.

## 7. Riscos e notas para o implementador

- **Uma função só para as contagens.** Use a mesma função de conferência no `release-notes` e no `changelog`, e chame-a antes de montar qualquer linha. O `source_lines` (SPEC-035 §7) continua sendo a única fonte das linhas de fonte dos dois comandos.
- **`bool` é `int` em Python.** `isinstance(True, int)` é verdadeiro: confira `isinstance(v, bool)` antes, como o `_is_number` do próprio `report.py` já faz.
- **Nunca ecoar o valor.** A mensagem de erro cita o caminho do campo, e o `<id>` passa pelo `shown_source_id`. Um valor com quebra de linha na saída de erro também forjaria linhas.
- **Cabeçalho exato só nos dois arquivos novos.** O `parse_csv` é compartilhado com o manifest, o `labels_overrides.csv` e o `exclusions.csv`. A conferência nova fica no `_read_sources` e no `_read_registry` (ou num parâmetro do `parse_csv` que só eles passam), sem mudar o comportamento dos outros três.
- **Gerador:** os testes de autor e de aceite existentes usam `items_per_stratum <= 20` com peças de conhecido; nenhum deve passar a falhar.
- **Export:** não troque a exceção do `torch.onnx.export` por `ExportError`. O `write_model_dir` e a CLI já tratam qualquer exceção (saída 2), e a mensagem original é a evidência da quebra do exportador.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); a parte `slow` do CA-11 rodada localmente com torch e registrada
- [ ] review-report APPROVED
- [ ] CI verde (sem torch); `ruff` limpo
- [ ] `ml/README.md` atualizado (§4.4)
- [ ] PR aberto com os relatórios; merge conforme R-09 (delegado ao orquestrador, ADR-016)
- [ ] `Done` antes do primeiro GitHub Release de um modelo

## 9. Perguntas para a aprovação (humano)

1. **Cabeçalho (RV-04):** exigir o cabeçalho exato em `sources.csv` e no registro, com o código `unexpected_header` (§4.4), ou trocar "exatamente" por "com as colunas obrigatórias" e não mudar o código? **Recomendação do architect:** cabeçalho exato. Ele mantém o texto já aprovado na SPEC-035, fecha o caso da coluna `license` repetida no registro e alinha o leitor ao importador da SPEC-036.
2. **RV-02 da SPEC-031:** deixar sem ação (§3.2) ou incluir uma passada do developer em `tests/test_dependency_isolation.py`, para acusar um requisito repetido no extra `train`? **Recomendação do architect:** sem ação. O CA-04 da SPEC-031 já cobre o `torch`, e a passada traria um segundo papel autor para um benefício pequeno.
3. **Posição no loop:** depois da 036 (`031 → 035 → 036 → 037 → 032 → 034`), ou logo depois da 035? **Recomendação do architect:** depois da 036. A 036 bloqueia a importação de fotos e o `split_v1`, enquanto o prazo da 037 é o primeiro Release, que só vem depois do treino real.

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-24 | SPEC criada (`Draft`). Decisões do architect: (a) as contagens exibidas do `metrics.json` aceitam só `int` não negativo, sem `bool`; no `changelog`, os campos da seção `### Dados` passam a ser exigidos quando a seção é gerada, para não mostrar como 0 algo que não foi medido (§4.1); (b) `_fraction_argument` confere o `float` depois da conversão, sem mudar o `make_split` (§4.2); (c) `<invalid source_id>` do CHANGELOG fixado como comportamento (§4.3); (d) cabeçalho exato com `unexpected_header` nos dois arquivos da SPEC-035, em vez de "colunas obrigatórias" (§4.4); (e) `ValueError` no gerador quando peças de conhecido colidiriam com próprias (§4.5); (f) `_log_export_warnings` no `finally`, com a exceção original saindo sem conversão (§4.6); (g) RV-02 da SPEC-031 sem ação (§3.2). As §4.1, §4.3 e §4.4 complementam a SPEC-035 sem alterar o arquivo dela. | RV-01 (= T-01) a RV-05 de `reviews/SPEC-035/r1-review-report.md` e `reviews/SPEC-035/r1-test-report.md`; RV-01 e RV-02 de `reviews/SPEC-031/r1-review-report.md` | Orquestrador, a pedido do humano |
| 2026-10-24 | Aprovada pelo humano (`Draft` → `Ready`) com as recomendações do §9: cabeçalho exato com `unexpected_header` (RV-04), sem ação no RV-02 da SPEC-031 e posição no loop logo depois da 036. | Respostas do humano de 2026-10-24 (PR #45) | Orquestrador, a pedido do humano |
