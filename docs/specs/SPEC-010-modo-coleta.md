# SPEC-010: Modo coleta de dataset

> **Aguardando reaprovação humana** (alteração de 2026-10-12: `re.fullmatch` em `item_id` e validação exata dos campos que viram caminho; ver Histórico).

| Campo | Valor |
|---|---|
| Status | Ready |
| Rodada atual | — |
| Autor da implementação | developer |
| Tags | security |
| Depende de | SPEC-007 |
| Semana alvo | S2 |
| Requisitos cobertos | RF-08, RNF-05 |
| ADRs relevantes | ADR-001, ADR-003, ADR-014 |

## 1. Contexto

Implementa `docs/architecture.md` §6.3: o celular vira a câmera de montagem do dataset, seguindo `docs/dataset-protocol.md` §3 (captura), §4 (metas) e §5 (manifest). As imagens e o manifest ficam só no notebook (R-02, R-14); o pipeline de ML (SPEC-011) consome esse manifest e falha se ele for inconsistente, por isso a validação acontece já na captura.

## 2. Objetivo

No modo coleta, cada foto vira um arquivo em `DATASET_DIR/raw/...` e uma linha válida em `DATASET_DIR/manifest.csv`, sem inferência e sem nada enviado à nuvem, e o console mostra a cobertura em relação às metas.

## 3. Escopo

### 3.1 Dentro

- `edge/src/qc_edge/collect.py`: `CollectRequest`, `DatasetWriter`, `CoverageReport`, `compute_coverage()`.
- `POST /api/capture` com `mode=collect` (substitui o 501 da SPEC-007).
- Campos de coleta em `capture.html`/`capture.js` (o limite de 200 linhas do JS da SPEC-007 continua valendo).
- Tabela de cobertura no console (`GET /`).
- `DATASET_DIR` em `EdgeSettings` (padrão `ml/data`, `docs/dataset-protocol.md` §8) e no `.env.example`; seção "Modo coleta" no `edge/README.md`.

### 3.2 Fora

- Correções de rótulo (`labels_overrides.csv`), dupla rotulagem e validações do pipeline → SPEC-011.
- Ferramentas (`T-…`, Fase 2) → SPEC-016. Até lá, `item_id` com prefixo `T` é recusado.
- Inferência e outbox → SPECs 008 e 009 (não são chamados aqui).

## 4. Requisitos detalhados

### 4.1 Campos (`multipart/form-data`, header `X-Session-Token` como na SPEC-007)

| Campo | Regra | Erro |
|---|---|---|
| `image` | mesmas regras da SPEC-007 (≤ 10 MiB → senão 413; JPEG/PNG pelo conteúdo + `load_image` → senão 415) | 413 / 415 |
| `mode` | `collect` | 422 |
| `item_id` | `^[SNOT]-\d{3}$` | 422 |
| `object_type` | `screw` \| `nut` \| `other` (classe do modelo; `unknown` não é aceito) | 422 |
| `grade` | um dos 5 valores de `Grade` para `screw`/`nut`; **ausente ou vazio** para `other` | 422 |
| `labeler` | `a` \| `b` | 422 |
| `angle` | inteiro 0–4 | 422 |
| `notes` | opcional, ≤ 200 caracteres, sem caracteres de controle (incluindo `\r`, `\n`, `\t`) | 422 |
| `lot_id` | ignorado neste modo (não é validado nem gravado) | — |

Coerência do prefixo: `S` → `screw`, `N` → `nut`, `O` → `other`; `T` ou prefixo que não bate com `object_type` → 422.

Campos que viram nome de arquivo ou caminho (`item_id`, `object_type`, `grade`, `angle`, §4.2): `item_id` é validado com `re.fullmatch(r"[SNOT]-\d{3}", valor)` (ou o `pattern` do Pydantic), **nunca** com `re.match`/`re.search`, que aceitam um `\n` final (`architecture.md` §3.2); `angle` é validado com `re.fullmatch(r"[0-4]", valor)` **antes** de `int()` (que aceitaria `"2\n"` e `" 2"`); `object_type`, `grade` e `labeler`, por igualdade exata com os valores permitidos, sem `strip()`. Qualquer falha → 422, antes de tocar o disco.

### 4.2 Gravação

1. Sob um lock de processo (`threading.Lock`) **e** um lock de arquivo (`fcntl.flock` em `DATASET_DIR/manifest.csv.lock`):
   1. se `manifest.csv` existe e o cabeçalho é diferente do esperado → 500 `{"detail": "manifest header mismatch"}`, nada gravado;
   2. se o `item_id` já existe no manifest com outro `object_type` → 409 `{"detail": "item_id already registered with another object_type"}` (o mesmo item com outro `grade` é permitido: estágios de corrosão);
   3. `ts = clock()` (UTC); caminho relativo `raw/<object_type>/<grade ou _>/<item_id>__<angle>__<ts:%Y%m%dT%H%M%SZ>.jpg`; arquivo já existente → 409 `{"detail": "capture already exists, try again"}`;
   4. grava a imagem em arquivo temporário no mesmo diretório e renomeia (JPEG: bytes recebidos; PNG: reencodado em JPEG q=90);
   5. acrescenta a linha ao manifest (cria o arquivo com o cabeçalho se não existir); falha aqui → apaga a imagem e responde 500.
2. Manifest: UTF-8 sem BOM, `csv.writer` com `QUOTE_MINIMAL` e `lineterminator="\n"`, colunas **exatamente** na ordem de `docs/dataset-protocol.md` §5: `image_path,item_id,object_type,grade,labeler,angle,captured_at,capture_device,notes`.
   - `image_path`: o caminho relativo acima, com `/`; `grade`: vazio para `other`; `captured_at`: `ts` em `%Y-%m-%dT%H:%M:%SZ` (mesmo instante do nome do arquivo); `capture_device`: os 60 primeiros caracteres do header `User-Agent` (vazio se ausente).
3. Resposta 200: `{"mode": "collect", "image_path": "...", "item_id": "...", "angle": n, "item_images": <linhas do manifest com esse item_id>}`.
4. Não chama `Inferencer` nem `InspectionSink`; funciona com `inferencer=None`.

### 4.3 Página de captura

- Ativar "coleta" no seletor de modo mostra: `item_id` (texto, validado no cliente pela mesma regex), `object_type` (select com rótulos PT-BR: parafuso, porca, outro), `grade` (select com os 5 rótulos PT-BR de `qc_contracts.labels`, desabilitado e vazio quando `other`), `labeler` (a/b), `angle` (0–4) e `notes`.
- Todos persistidos em `localStorage` entre fotos; depois de cada sucesso, `angle` avança 1; depois do 4 volta a 0 e a página mostra "Peça completa — troque o item_id".
- Cartão de resultado: "Salvo: <item_id>, ângulo <n> (fotos desta peça: <item_images>)". Lembrete fixo: "Sem pessoas no quadro" (R-14).

### 4.4 Cobertura no console

```python
@dataclass(frozen=True)
class CoverageCell: object_type: str; grade: str | None; images: int; items: int; target_images: int; target_items: int
def compute_coverage(manifest_path: Path) -> list[CoverageCell]
```

Linhas: `screw` × 5 graus e `nut` × 5 graus (metas 120 imagens e 12 peças por célula, mínimo 8) e `other` (metas 150 imagens e 30 objetos), conforme `docs/dataset-protocol.md` §4. O console mostra a tabela (`<table id="coverage">`) com "imagens/meta" e "peças/meta", destacando as células que atingiram as duas metas, e o total de imagens. Manifest ausente → tabela zerada.

## 5. Critérios de aceite

- **CA-01** — *Dado* `DATASET_DIR` vazio e o relógio em `2026-10-22T14:15:03Z`, *quando* envio JPEG válido com `item_id=S-012`, `object_type=screw`, `grade=fair`, `labeler=a`, `angle=2`, `notes="dúvida fair/poor"` e `User-Agent` de 80 caracteres, *então* recebo 200 com `image_path="raw/screw/fair/S-012__2__20261022T141503Z.jpg"` e `item_images=1`; o arquivo existe; `manifest.csv` tem o cabeçalho de §4.2 e 1 linha com `captured_at=2026-10-22T14:15:03Z` e `capture_device` com 60 caracteres.
- **CA-02** — *Dado* `item_id=O-004`, `object_type=other` e `grade` vazio, *então* 200, arquivo em `raw/other/_/O-004__0__<ts>.jpg` e coluna `grade` vazia no manifest.
- **CA-03** — *Dado* `object_type=other` com `grade=good`, ou `object_type=screw` sem `grade`, ou `grade=excellent`, *então* 422 e nada gravado.
- **CA-04** — *Dado* `item_id=N-001` com `object_type=screw`, ou `item_id=T-001` com qualquer tipo, ou `object_type=unknown`, *então* 422.
- **CA-05** — *Dado* `item_id` igual a `S-12`, `s-012`, `S-0123` ou `../S-001`, ou `angle` igual a 5, -1 ou `x`, ou `labeler=c`, ou `notes` com 201 caracteres ou com `\n`, ou `item_id="S-012\n"`, `angle="2\n"` ou `object_type="screw\n"` (com os demais campos do CA-01), *então* 422 e nenhum arquivo criado fora de `DATASET_DIR`; nos três últimos casos, com `DATASET_DIR` vazio, ele continua vazio (nem imagem, nem `manifest.csv`).
- **CA-06** — *Dado* um manifest com uma linha (inserida direto no arquivo) de `O-007` com `object_type=screw`, *quando* envio `O-007` como `other`, *então* recebo 409 com o detalhe de §4.2, nenhuma imagem é gravada e o manifest não muda. (Com o prefixo amarrado ao tipo, o conflito só surge em manifest editado à mão; a regra existe para proteger a SPEC-011.)
- **CA-07** — *Dado* `S-012` já com uma foto `fair`, *quando* envio `S-012` como `poor`, *então* 200 e `item_images=2` (mudança de estágio é permitida).
- **CA-08** — *Dado* duas requisições idênticas no mesmo segundo do relógio (mesmo item e ângulo), *então* a primeira recebe 200 e a segunda 409, com 1 linha no manifest.
- **CA-09** — *Dado* duas requisições concorrentes (2 threads, itens `S-001` e `N-001`), *quando* terminam, *então* `manifest.csv` tem o cabeçalho e exatamente 2 linhas, ambas lidas por `csv.DictReader` com as 9 colunas e os valores enviados.
- **CA-10** — *Dado* `notes='tem "aspas", vírgula'`, *então* a linha é escrita com quoting CSV correto e `csv.DictReader` devolve o texto idêntico.
- **CA-11** — *Dado* `manifest.csv` existente com cabeçalho diferente, *quando* envio uma coleta válida, *então* 500 `{"detail": "manifest header mismatch"}`, o arquivo não muda e nenhuma imagem é gravada.
- **CA-12** — *Dado* `inferencer=None` e um `StubInferencer` contando chamadas em outro caso, *quando* faço 3 coletas válidas, *então* todas retornam 200, o stub tem 0 chamadas e o sink continua vazio (nada vai para a nuvem — R-02).
- **CA-13 (R-02)** — *Dado* uma coleta feita, *então* `GET /raw/screw/fair/<arquivo>`, `GET /ml/data/manifest.csv` e `GET /manifest.csv` retornam 404.
- **CA-14** — *Dado* coleta sem token ou com token errado, *então* 401 e nada gravado; com imagem de 10 485 761 bytes, 413; com texto renomeado para `.jpg`, 415.
- **CA-15** — *Dado* um manifest com 130 linhas de `screw/perfect` em 9 itens, 40 de `nut/poor` em 3 itens e 10 de `other` em 10 itens, *quando* chamo `compute_coverage`, *então* as células têm `(130, 9)`, `(40, 3)` e `(10, 10)` com metas `(120, 12)`, `(120, 12)` e `(150, 30)`, e as outras 8 células de grau são `(0, 0)`; e o console (loopback) contém `<table id="coverage">` com "130/120".
- **CA-16** — *Dado* `GET /capture?t=<válido>`, *então* o HTML contém os campos `item_id`, `object_type`, `grade`, `labeler`, `angle` e `notes`, e o seletor de modo com "coleta" habilitado.
- **CA-17 (manual)** — 1. ligar `qc-edge` sem modelo; 2. no celular, ativar "coleta", preencher `S-001`, parafuso, perfeito, `a`, ângulo 0; 3. tirar 5 fotos: o ângulo avança 0→4 e aparece "Peça completa"; 4. recarregar a página: os campos continuam preenchidos; 5. trocar para "outro": o grau fica desabilitado; 6. conferir no notebook 5 arquivos em `raw/screw/perfect/` e 5 linhas no manifest, e a tabela de cobertura com `5/120` e `1/12`.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | validação, caminhos, manifest, cobertura, lock | `edge/tests/` |
| Aceite (tester) | Um por CA; `tmp_path` como `DATASET_DIR`; relógio falso; threads para CA-09 | `edge/tests/acceptance/test_spec_010.py` |
| Manual (dupla) | CA-17 com um celular real | notebook + celular |

## 7. Riscos e notas para o implementador

- `fcntl.flock` é só POSIX; serve para o Arch Linux da equipe (RNF-08). O lock em thread cobre o caso de um único processo.
- Ler o manifest inteiro a cada coleta é aceitável (≤ ~2 000 linhas); se pesar, mantenha um índice `item_id → object_type` em memória, recarregado quando o `mtime` mudar.
- O manifest é consumido pelo pipeline (pandas), não por planilha; não altere o conteúdo de `notes` além do quoting CSV.

## 8. Definição de pronto

- [ ] Todos os CAs com teste de aceite passando (test-report PASS); CA-17 registrado
- [ ] review-report APPROVED + security-report PASS
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados
- [ ] PR aberto com os relatórios; merge humano

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-10-12 | §4.1 exige `re.fullmatch` em `item_id`, `re.fullmatch` em `angle` antes de `int()` e igualdade exata (sem `strip()`) em `object_type`, `grade` e `labeler`, por virarem nome de arquivo ou caminho. O CA-05 ganhou os casos `item_id="S-012\n"`, `angle="2\n"` e `object_type="screw\n"` (422, `DATASET_DIR` intacto). Nenhum outro requisito muda. SPEC marcada como "Aguardando reaprovação humana". | RV-04 de `reviews/SPEC-002/r1-review-report.md` (regra geral em `architecture.md` §3.2) | Humano, via orquestrador |
