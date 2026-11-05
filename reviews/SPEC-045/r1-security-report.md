# SPEC-045 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-045](../../docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...32517f9` (11 commits, 25 arquivos; merge-base `555c4b6`). Inclui o `32517f9` do architect, só de docs, que chegou durante este portão |
| Relatórios lidos | [r1-dev-report.md](r1-dev-report.md), [r1-test-report.md](r1-test-report.md) (PASS), [r1-review-report.md](r1-review-report.md) (APPROVED); ADR-025 (`Aceito`, com as respostas do humano); `reviews/SPEC-044/r1-security-report.md` (SEC-44-04) |
| **Veredicto** | **PASS** |

Não há achado bloqueante nem alto. Há um achado médio e um baixo, ambos sobre a **operação depois do merge** (§4.7), um baixo já resolvido na branch (SEC-45-03, pelo `32517f9`) e uma nota informativa. Nenhum deles muda o código entregue nesta rodada. O médio (SEC-45-01) é pré-condição do passo 3 do §4.7 e não do merge.

## Superfície analisada

- **Rotas, autenticação, banco, CORS, deploy:** nada mudou. Não há diff em `api/`, `edge/`, `dashboard/`, `infra/`, `.github/`, `packages/`, `.gitignore`, `pyproject.toml` nem `uv.lock`.
- **Código (`ml/src/qc_ml/split.py`, `synthetic.py`, `ml/scripts/make_tiny_fixture.py`):** CLI local e offline, sem rede e sem segredo.
  - `--defer-types` no `split_v1`: os valores passam primeiro pela checagem contra `KNOWN_OBJECT_TYPES` (`unknown object type: …`, comportamento que já existia, com precedência). A linha nova `deferred type without images: <tipo>` só ecoa valores já validados.
  - O `make_split` agora recusa valores desconhecidos também sem `previous`, o que fecha a API da função.
  - Nada é gravado antes das checagens (saída 2 sem `split_v1.*`, CA-08). O piso é conferido depois do adiamento.
  - Nenhum SQL, `subprocess` ou `eval` novo em código de produção, e nenhum log novo com caminho pessoal ou dado de foto.
- **Artefatos binários versionados:** só a fixture `ml/tests/fixtures/tiny_model_no_nut/`.
  - O `model.onnx` tem 2,6 kB. Conferi que o `sha256sum` é igual ao `model.sha256` (`c1f16d23…8766`).
  - O `parity_fixture.npz` abre com `allow_pickle=False` e não tem objeto serializado. Ele contém 4 arrays numéricos: `inputs` (8×3×224×224, `float32`), `type_probs` e `grade_probs` (8×5) e `model_sha256`. As entradas vêm do `make_synthetic_dataset(seed=0)`, segundo a docstring do script: nenhuma foto real (R-02, R-14).
  - Nenhum JPEG, PNG, HEIC ou CSV foi versionado, e nenhum arquivo de `ml/data/`, `ml/splits/` ou `ml/models/` entrou.
- **Testes:** só datasets sintéticos em `tmp_path`. Os `subprocess.run` chamam `sys.executable` com uma lista de argumentos (sem `shell=True`) ou `git ls-files`/`git check-ignore`, com timeout. Nenhum teste lê `ml/data/`, `~/partqc-entrada/` ou o backup, nem usa `Path.home()` ou `expanduser`.
- **Documentação da operação (`ml/README.md`, §4.7):** é o ponto que o SEC-44-04 deixou para este portão (seção abaixo).

## O que o SEC-44-04 deixou para este portão

| Conferência | Resultado |
|---|---|
| Nenhum agente abre fotos na operação do §4.7 | ✅ A decisão 3 do ADR-025 está repetida no README, na seção "Privacidade (decisão 3)": nenhum agente abre, converte em miniatura ou descreve foto de `ml/data/`, da pasta de entrada ou do backup. Os scripts leem só CSV e saídas de texto. As conferências do CA-13 são todas por CLI ou por CSV (`qc_edge.privacy`, `qc_ml.data validate`, contagens). A importação só registra `plan line N not imported: <motivo>`, sem nome de arquivo. A SPEC (§4.5, §7) manda passar ao humano a conferência que pareça exigir olhar a foto. |
| Pasta de entrada e originais com destino definido | ✅ Passo 1: `ml/data/` vai para `~/partqc-backup/ml-data-antes-adr-025/`, com modo `0700`. Conferi que `~` não é repositório Git (`git -C ~ rev-parse` falha). Passo 8: o humano apaga a pasta de entrada `~/partqc-entrada/colegas/` e o backup depois do merge do `split_v1`. A importação recusa plano e pasta de entrada dentro de um repositório Git (`inside_git_repository`, SPEC-038). O plano corrigido e os scripts da operação ficam fora do repositório (§4.5; nenhum script do Anexo A no diff). A pasta de entrada fica guardada além do "apagados depois da importação" da decisão 6 do ADR-020, até o merge do `split_v1`. Essa extensão está na SPEC aprovada pelo humano e é necessária para refazer a importação se o CA-13 falhar. |
| Nada de foto, `ml/data/` ou caminho pessoal no Git | ✅ `git ls-files ml/data` vazio. `git check-ignore` cobre `manifest.csv`, `sources.csv`, `raw/hammer/_/T-601…jpg` e `labels_second.csv` (CA-12, que também rodei: 38 passed). O diff não tem caminho absoluto pessoal (`/home/…`, nome da pasta local do repositório), só os caminhos genéricos com `~` que a SPEC já usa. Não há nome de colega: só os códigos `c01` a `c03`. |
| Dispensa da rotulagem dupla registrada | ✅ Está na resposta 5 do ADR-025 (opção 6B), no Histórico da SPEC (linha do `Ready`), no passo 5 do README (o PR do split, o relatório, o CHANGELOG e os slides declaram a dispensa) e no CA-14 do test-report. Com o `32517f9`, está também no `docs/dataset-protocol.md` (§6 e §7) e no `docs/plan.md` (fluxo sem a etapa "concordância"). O texto antigo que contradizia a dispensa saiu (SEC-45-03). |
| Aviso aos colegas (pendente com o humano) registrado | ⚠️ Está registrado como pendência no ADR-025 (resposta 3, "Sim, eu aviso"), mas o §4.7 do README não o traz como passo nem como pré-condição: SEC-45-02. A conferência de `O-534` e `O-535` no tamanho real, também pendente, é citada no passo 3 como se já estivesse feita: SEC-45-01. |

## Achados

| ID | Severidade | Categoria (auth, input, secrets, deps, deploy, privacy) | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-45-01 | média | privacy | `ml/README.md:263`; `docs/specs/SPEC-045-treino-com-fotos-dos-colegas.md:111`; `docs/adr/ADR-025-treino-com-fotos-dos-colegas.md:167` | O passo 3 diz que o `--privacy-checked` "vale [...] pela resposta 3 do ADR-025 sobre `O-534` e `O-535`". Pelas respostas registradas no ADR-025, porém, a conferência dessas duas fotos no tamanho real (mãos parciais) **continua pendente com o humano**. "Não bloqueiam a implementação" vale para o código, não para a reimportação. Rodar o passo 3 antes dessa conferência marca como conferidas duas fotos que nenhum humano olhou com esse fim depois do aviso do agente (R-14, `docs/dataset-protocol.md` §10.5). Hoje as duas fotos já estão no `ml/data/` pela primeira importação, então o merge não piora a exposição: o risco está em congelar essas fotos no teste do `split_v1`. | **Antes do passo 2 do §4.7** (e não só antes do 3), o humano registra o resultado da conferência de `O-534` e `O-535`, por exemplo no diário ou no PR. O orquestrador não autoriza a importação com `--privacy-checked` sem esse registro. Se uma das duas sair, o `plano-v2.csv` deixa de ter 223 linhas, e as contagens do Anexo A e do CA-13 mudam. Nesse caso, o ml-engineer para e registra `SPEC_ISSUE` para o architect (§7 da SPEC), sem ajustar o plano por conta própria. Não exige rodada nova desta SPEC. |
| SEC-45-02 | baixa | privacy | `ml/README.md:249-274` (§4.7); `docs/adr/ADR-025-treino-com-fotos-dos-colegas.md:167` | O aviso a `c01`, `c02` e `c03` sobre o envio das fotos ao provedor do modelo, com a opção de retirada (§10.2 e §10.7 do protocolo), está pendente com o humano e não aparece no passo a passo da operação. A retirada continua possível depois do `split_v1` (`excluded_previous_image`). Só que o teste tem cerca de 15 peças, e uma retirada depois do congelamento encolhe um teste que já não sustenta nenhuma meta. Além disso, a Release e os slides (CA-16) publicam métricas tiradas dessas fotos. | O humano faz o aviso **antes do passo 6** (`split_v1`), e o orquestrador o registra no PR do split, como a dispensa da concordância, e no diário. O architect pode incluir esse "passo 0 (humano)" no §4.7 na próxima mudança de docs. Não exige rodada nova. |
| SEC-45-03 | baixa (**resolvido** no `32517f9`) | privacy (docs) | `docs/dataset-protocol.md` §4, §6, §7, §11; `docs/architecture.md` §3, §7, §10; `docs/plan.md`; SPEC-045 §4.3 | É o RV-02 da revisão. Até o `c10f59a`, o protocolo dizia "ADR-025, `Proposto`" e que o `split_v1` sai "depois [...] da rotulagem dupla". Isso contradizia a dispensa (resposta 5) e podia levar a operação a esperar uma etapa que não vai acontecer. O `32517f9` (trailer `Agent: architect`, identidade do projeto, só `docs/`) resolve. (1) Troca `Proposto` por `Aceito`. (2) Acrescenta a dispensa no §6 do protocolo. (3) Tira a espera da rotulagem dupla do §7 e do fluxo do `docs/plan.md`. (4) Atualiza o contrato 0.7.0 na arquitetura. (5) Troca, no §4.3 da SPEC, "com o aviso de hoje no log" por "com um aviso no log" (RV-01), com uma linha no Histórico. Antes do commit, li essa mudança na árvore de trabalho: o commit é igual a ela, com o mesmo número de linhas nos 3 arquivos, mais o `docs/plan.md`. A troca no §4.3 é editorial: não vem de `SPEC_ISSUE` e não é reaprovação sob o ADR-019. Ela não mexe em limite de segurança (X-6) nem em trecho ou CA de regra inegociável (X-7). A decisão 3, o §4.5, o §4.7 e as regras de privacidade da §11 continuam iguais (só o status entre parênteses mudou). | Nenhuma. |
| SEC-45-04 | info | privacy | `ml/README.md:264` (passo 4); `reviews/SPEC-045/` (test-report da operação, futuro) | O test-report da operação (CA-13) vai para o Git. A importação e as CLIs de conferência não imprimem nome de arquivo da pasta de entrada, mas um script ad hoc da operação pode imprimir. | O test-report da operação registra só contagens, códigos `cNN`, `item_id` e as saídas das CLIs. Nunca registra a coluna `file` do plano, `source_ref`, caminho absoluto da pasta de entrada ou do backup, nem trecho de `notes` copiado do plano original. |

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | N/A: nenhuma rota nova ou alterada (sem diff em `api/`, `edge/`, `dashboard/`). |
| Entradas validadas (tamanho, tipo real da imagem, regex de IDs, `extra="forbid"`) | ✅ A única entrada nova é o `--defer-types` no `split_v1`, validado contra `KNOWN_OBJECT_TYPES` antes de qualquer uso, com a mensagem `unknown object type` primeiro. O tester cobriu unicode, maiúsculas, espaço, duplicata e lista vazia. Nada é gravado em caso de erro. Contrato e schemas sem mudança. |
| SQL sempre parametrizado | N/A: nenhum SQL no diff. |
| RLS ligado; `DATABASE_URL` e `service_role` só na API | N/A: nenhuma mudança de banco nem de variável. A única conninfo do diff (`postgresql://postgres@localhost:55432/partqc_test`, no test-report) é o banco local de teste, sem senha. |
| CORS fechado ou mínimo | N/A. |
| Logs sem segredos e sem payloads de imagem | ✅ O aviso novo do `--extend-test-types` é um texto fixo, e a linha `deferred type without images` só ecoa tipos já validados. Nenhum log com caminho pessoal ou conteúdo de foto. |
| Segredos (R-03) | ✅ A busca no diff (chaves, tokens, JWT, `service_role`, URL com senha, chave privada) não achou nada. Não há variável nova, e `.env.example` não muda. Não li nenhum `.env*`. |
| Privacidade das imagens (R-02, R-14) | ✅ No código e nos testes. Na operação, com as pré-condições do SEC-45-01 e do SEC-45-02. Nenhuma foto real versionada. A fixture é sintética, e `ml/data/` está fora do Git e ignorado (CA-12). |
| Dependências novas: mantidas, licença, CVE | ✅ Nenhuma: `uv.lock` e os `pyproject.toml` sem diff. |
| Deploy: variáveis no provedor, health check, plano free sem cartão | N/A: não há configuração de deploy no diff. O registro do CA-15 da SPEC-044 (`reviews/SPEC-044/r1-test-report.md`) não expõe domínio, segredo nem URL de conexão. |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma reaprovação sob o ADR-019 nesta branch: depois do `Ready`, os commits na SPEC só mudam o status. A correção editorial do architect no §4.3 (`32517f9`, SEC-45-03) também não é reaprovação delegada e não toca em X-6 nem em X-7. |
| R-13 (identidade, nada corporativo) | ✅ O diff não menciona empresa nem serviço corporativo. Os autores são a identidade local do projeto. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma dependência nova. |

## Verificação própria

- `uv run pytest -q -p no:cacheprovider ml/tests/acceptance/test_spec_045.py`: 38 passed em 27,8 s.
- `git ls-files ml/data`: vazio. `git check-ignore` dos 4 caminhos (`manifest.csv`, `sources.csv`, `raw/hammer/_/T-601…jpg`, `labels_second.csv`): todos ignorados.
- `sha256sum` de `tiny_model_no_nut/model.onnx` igual ao `model.sha256`. O `parity_fixture.npz` abre com `allow_pickle=False`.
- `git -C ~ rev-parse`: o diretório pessoal não é repositório Git, então o backup do passo 1 não fica sob controle de versão.
- Buscas no diff: nenhum arquivo de imagem, CSV ou de `ml/data`/`ml/splits`/`ml/models`; nenhum caminho absoluto pessoal; nenhum padrão de segredo; nenhuma menção corporativa.

## Ações pendentes para o humano

1. Conferir `O-534` e `O-535` no tamanho real e registrar o resultado **antes** dos passos 2 e 3 do §4.7 (SEC-45-01).
2. Avisar `c01`, `c02` e `c03`, com a opção de retirada, **antes** do `split_v1` (passo 6), e deixar o aviso registrado para o PR do split (SEC-45-02).
3. Depois do merge do `split_v1`, apagar `~/partqc-entrada/colegas/` e o backup do passo 1 (passo 8).

## Declaração

- [x] Não editei código, testes, SPECs nem ADRs. Só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
- [x] Não abri nenhuma foto e não li `ml/data/`, `~/partqc-entrada/`, o backup ou qualquer `.env*`.
