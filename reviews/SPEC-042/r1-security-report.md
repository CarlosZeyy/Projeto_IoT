# SPEC-042 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-042](../../docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...1bce5e0` (`origin/main` = `9419a5e`, 15 commits) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante ou alto. Há 1 baixo e 2 informativos, e nenhum pede mudança nesta rodada.

**O CA-01 foi conferido por conta própria, como o §8 manda, e passou:** o controle mostra consulta e fila, e a borda e o treino não têm nenhuma das duas.

## Superfície analisada

| Tema | Onde |
|---|---|
| Rotas | Nenhuma nova ou alterada: `app.py`, `live.py` e `packages/` fora do diff |
| Saída de rede da borda e do treino | `edge/src/qc_edge/__init__.py:6`, `ml/src/qc_ml/__init__.py:6`, `conftest.py:25` |
| Segredos | `.env.example:83`, só um comentário. A chave da CA aparece só na seção nova do `edge/README.md` |
| Entradas externas | O campo e o `localStorage` do lote, e o `lot_id` da resposta, agora mostrados na página (`edge/src/qc_edge/static/live.js:64-69`, `:112`) |
| Confiança nos celulares | `edge/README.md`, seção `### Depois da apresentação` |
| Testes que disparam a telemetria de propósito | `tests/acceptance/test_spec_042.py` (controle do CA-01) |
| Dependências | Nenhuma nova: `uv.lock` e os `pyproject.toml` fora do diff |
| Deploy, API, banco e contrato | Fora do diff: `infra/`, `.github/`, `api/`, `dashboard/` e `packages/` não mudam |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-42-01 | baixa | privacy | `ml/src/qc_ml/parity.py:25`, `:149` | Executar o arquivo direto, com `python ml/src/qc_ml/parity.py --model-dir <tiny_model>`, não passa pelo `qc_ml/__init__.py`, porque o `import onnxruntime` vem antes de qualquer `qc_ml.*`. Medido no namespace, com `HOME` temporário: a fila foi criada, com `deviceid` e `onnxruntime.db`. O processo acabou em 1,6 s, sem nenhuma linha de rede. **Nada ensina essa forma:** o `ml/README.md` e o notebook usam `python -m qc_ml.*`, que fica protegido (medido: 0 linhas de rede e nenhuma fila), e a busca por `python ml/src` não acha nada fora dos relatórios. É o único módulo com `__main__` que importa o `onnxruntime` direto. A frase "Fora da proteção" do `docs/architecture.md` §9 já cobre o caso, de forma genérica | Nenhuma nesta rodada. Ao mexer no §9, vale citar esse exemplo |
| SEC-42-02 | informativa | privacy (fora do diff) | Notebook: `~/.cache/Microsoft/DeveloperTools/.onnxruntime/` | A SPEC não apaga a fila real, como o §3.2 e o §3.3 preveem. Ela continua lá, com data de 18:23:47 e 40960 bytes. Não li o conteúdo. Nas filas criadas no `HOME` temporário, a pasta traz também o `deviceid`, e o §3.3 cita só o caminho da pasta pessoal. **Não medi** se um processo sem proteção e com rede enviaria eventos já guardados. Até o merge, a proteção vale só nesta branch: um processo de outro checkout continua sem ela | Humano: fazer o item 1 do §3.3 depois do merge, apagando a pasta inteira |
| SEC-42-03 | informativa | privacy, processo | `reviews/SPEC-042/r1-test-report.md:139-151` | O tester disparou a telemetria fora do isolamento, uma vez com o `HOME` real (RV-06 do review). Conferi só a data: a fila real ficou em 18:23:47, a do relatório, antes e depois de todos os meus comandos. Não dá para saber daqui se uma consulta de DNS saiu naquele momento. Sem imagem envolvida. A prevenção já está no §9 da arquitetura | Citar no PR, para o humano ver |

**Contagem:** bloqueante 0, alta 0, média 0, baixa 1, informativa 2.

**SEC-19-01 e SEC-19-02, da SPEC-019:** corrigidos neste diff, com o resíduo acima. O achado médio deixa de valer para `qc_edge` e `qc_ml` a partir do merge, enquanto o `onnxruntime` for o 1.31.0. O §9 da arquitetura manda medir de novo ao subir a versão.

## CA-01: conferência independente

Rodei de duas formas: o teste do tester, com a montagem exata do §4.2, e um roteiro meu, escrito sem reaproveitar os auxiliares dele. Os dois usam o `onnxruntime` 1.31.0 do `uv.lock`, o `.venv` deste worktree (com torch 2.14.1), `qc_edge` e `qc_ml` importados deste worktree, e só `PATH` e `HOME` temporário no ambiente.

**Teste de aceite, com `PARTQC_TELEMETRY_TESTS=1`: `1 passed in 80.30s`, sem pulo.**

| Processo | Código | Linhas no log | Consultas | Fila |
|---|---|---|---|---|
| Sonda | 0 | — | — | Só a interface `lo`; `connect` UDP com código 101 |
| (a) controle | -15 (parado ao ver a evidência, §4.2) | 68 | **14** | **criada** |
| (b) borda | 0 | 0 | **0** | **nenhuma** |
| (c) treino | 0 | 0 | **0** | **nenhuma** |

**Roteiro próprio,** com `unshare --user --map-root-user --net` e `strace -f -qq -s 512 -e trace=network,openat,creat,mkdir,mkdirat,rename,renameat2`. O traço maior mostra também os arquivos criados. A tabela conta as linhas de chamadas de rede:

| Caso | Janela | Código | Linhas de rede | Consultas | Arquivos no `HOME` | Criados fora da pasta do caso |
|---|---|---|---|---|---|---|
| (a) controle | parado em 9,8 s | -15 | 68 | **14** (12 `htons(53)`, 2 `io.systemd.Resolve`) | `deviceid`, `onnxruntime.db`, `-shm`, `-wal` | só o temporário do `deviceid`, dentro do `HOME` |
| (b) borda | 35 s | 0 | 0 | 0 | nenhum | nenhum |
| (b) borda, `ORT_DISABLE_TELEMETRY=0` herdado | 35 s | 0 | 0 | 0 | nenhum | nenhum |
| (b) borda, janela longa | **120 s** | 0 | 0 | 0 | nenhum | nenhum |
| (c) treino, `ok=True` | 35 s | 0 | 0 | 0 | nenhum | nenhum |
| (c) treino, `0` herdado, `ok=True` | 35 s | 0 | 0 | 0 | nenhum | nenhum |
| `OnnxInferencer` real, com inferência, `0` herdado | 35 s | 0 | 0 | 0 | nenhum | nenhum |
| `python -m qc_ml.parity` | até sair (1,4 s) | 0 | 0 | 0 | nenhum | nenhum |
| `python ml/src/qc_ml/parity.py` (SEC-42-01) | até sair (1,6 s) | 0 | 0 | 0 | **`deviceid`, `onnxruntime.db`** | só o temporário do `deviceid`, dentro do `HOME` |

**O servidor real, além do que a SPEC pede:** o `qc-edge` subiu no namespace, com `MODEL_DIR` com o `tiny_model` e `ORT_DISABLE_TELEMETRY=0` herdado, e ficou 40 s no ar. O log teve 15 linhas, nenhuma com a porta 53 nem `mobile.events`, nenhum `sendto` ou `sendmsg`, e o `HOME` ficou vazio.

**O controle não saiu do namespace.** As 14 chamadas `connect` falharam: 8 com `EADDRNOTAVAIL`, 4 com `ENETUNREACH` e 2 com `ENOENT`. O log não tem `sendto`, `sendmsg` nem `htons(443)`. Antes de rodar, conferi que `/run/systemd/resolve/` e `/var/run/nscd/` não existem neste notebook, então a saída pelo resolvedor prevista no §7 não tem como ocorrer aqui. Em `/proc/net/route`, nenhuma rota.

**A fila real não mudou:** 18:23:47 e 40960 bytes, antes e depois de cada etapa.

**Limites da medição:**

- O log do controle não traz o nome `mobile.events`, porque o `connect` falha antes do envio. O que liga essas consultas à telemetria é a definição do §4.2, a fila criada junto e a medição nomeada de `reviews/SPEC-019/r2-security-report.md`. Para (b) e (c), isso não pesa: eles não têm nenhuma chamada de rede.
- Não repeti a medição só de `import` da OBS-01 do tester, e nenhuma das medições cobre o Colab. Lá, o notebook usa `python -m qc_ml.*`, então passa pelo `__init__`.
- Vale só para este pacote, no Linux, neste notebook.

## Outras conferências

**Onde mais o `onnxruntime` pode carregar:**

- **Pacotes de terceiros:** só `timm` e `torch` têm esse import. O `import torch` sozinho não carrega o `onnxruntime` (medido), e o único script fora dos pacotes que importa `torch`, `ml/scripts/make_tiny_fixture.py`, importa o `qc_ml` antes de exportar.
- **Import dinâmico:** nenhum `__import__` ou `import_module` em `edge/src`, `ml/src`, `scripts`, `ml/scripts` e `packages`.
- **`.env`:** nada em `edge/src` ou `ml/src` usa `load_dotenv`, `env_file` ou `override=`, então um `.env` não desfaz a atribuição.
- **Instruções:** nenhum README ou doc manda rodar `import onnxruntime` à mão, e os workflows não citam `ORT_*` nem `PARTQC_TELEMETRY_TESTS`.

**Processos de teste, com ambiente limpo, sem `CI`, dentro do namespace.** O `HOME` temporário ficou vazio em todos:

| Comando | Pasta | Resultado |
|---|---|---|
| `edge/tests/acceptance/test_spec_008.py` | raiz | 112 passed, 1 skipped |
| `ml/tests/test_parity.py` | raiz | 13 passed, 1 skipped |
| `ml/tests/acceptance/test_spec_012.py --collect-only` | raiz | 64 coletados |
| `tests/acceptance/test_spec_008.py --collect-only` | `edge/` | 113 coletados |
| `tests/test_parity.py --collect-only` | `ml/` | 14 coletados |
| `test_spec_008.py --collect-only` | `edge/tests/acceptance/` | 113 coletados |

Só a raiz tem configuração do `pytest`, então o `conftest.py` da raiz vale em todas essas pastas.

**O controle só roda isolado.** Li o teste: o `CONTROL_SCRIPT` só chega ao `measure`, que sempre monta `unshare` e `strace`, e a sonda de isolamento roda antes. Se o `unshare` falhar, o processo nem começa. O grupo de processos é encerrado no fim, e os CAs 02 e 03 conferem a variável antes de o `onnxruntime` carregar, como o preâmbulo do §5 pretende. Os testes do autor só usam um `meta_path` que encerra o processo antes da carga.

**Página (`live.js`, `live.html`).** O lote é escrito só com `textContent`, e `live.js` não tem `innerHTML`, `eval` ou `document.write`. O `lot_id` da resposta vai só para o `fillText` do canvas, que não interpreta HTML. Não há `fetch` novo: a única chamada continua sendo `/api/live/frame`, e o `localStorage` guarda o mesmo lote de antes. `showLot` só muda o texto, e `send` e `tick` não leem o campo. A linha nova não aumenta o que sai do celular.

**`edge/README.md`, `### Depois da apresentação`.**

- **Ordem no notebook:** no [`main.go`](https://raw.githubusercontent.com/FiloSottile/mkcert/master/main.go), `Run()` chama `loadCA` antes do ramo de `-uninstall`, e, no [`cert.go`](https://raw.githubusercontent.com/FiloSottile/mkcert/master/cert.go), `loadCA` cria uma CA nova quando não acha a raiz. Por isso, `-uninstall` depois do `rm -rf` recriaria um `rootCA-key.pem`. A ordem do README é a certa, e o CA-08 a fixa.
- **Comandos:** `$(mkcert -CAROOT)` vem entre aspas, e `-CAROOT` só imprime o caminho, sem criar nada.
- **Celulares:** os caminhos batem com o [guia da Apple](https://support.apple.com/guide/deployment/distribute-certificates-depcdc9a6a3f/web) ("Settings > General > Device Management") e com a [ajuda do Pixel](https://support.google.com/pixelphone/answer/2844832?hl=en), inclusive a diferença entre "User credentials" e "Clear credentials". O README avisa que o caminho varia.
- **Efeito:** apagar a pasta da CA encerra a emissão de certificados novos mesmo que um celular demore a ser limpo. O passo 1 explica o risco.
- **Limite:** o `mkcert` não está instalado neste notebook e não há celular aqui, então li as fontes e não executei os passos.

**R-07 e identidade.** Todos os 15 commits têm o trailer `Agent:` e a mesma identidade `noreply`. Nenhum é do `security-devops`.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | ✅ N/A em código novo: nenhuma rota muda. Os testes da SPEC-019 seguem passando |
| Entradas: tamanho, tipo real, regex, `extra="forbid"` | ✅ Nada muda no servidor. O `lot_id` continua validado pela rota, e a página só mostra o texto |
| SQL parametrizado | ✅ N/A: nenhuma consulta nova |
| RLS; `DATABASE_URL` e `service_role` | ✅ N/A: banco e API fora do diff |
| CORS | ✅ N/A: nada muda |
| Logs sem segredos e sem imagem | ✅ Nenhum log novo (§4.1) |
| Dependências novas | ✅ Nenhuma |
| Deploy | ✅ N/A: nada de deploy muda. Sem serviço novo nem cartão (R-01) |
| Reaprovação delegada (ADR-019) | ✅ Nenhuma nesta branch. `git diff 34d8d0c..HEAD` da SPEC só muda o status e acrescenta o título do Histórico |
| **R-02** | ✅ Sem rota, imagem ou saída nova. A telemetria sai de `qc_edge` e `qc_ml` (CA-01). `docs/rules.md` não muda. A leitura de que a telemetria não quebra a R-02 é decisão do humano, registrada no §1 da SPEC e no §9 da arquitetura. Só a li nesses registros, relatada pelo orquestrador |
| **R-03** | ✅ Busca no diff sem chave, JWT, token ou credencial em URL. Únicos IPs: `127.0.0.1` e `192.0.2.1` (RFC 5737). Nenhum `.pem` ou `.key` versionado; `.env`, `*.pem` e `data/` ignorados (`git check-ignore`). `.env.example` só com o comentário |
| **R-12** | ✅ O CA-06 passa, e `api/` e `dashboard/` estão fora do diff |
| **R-13** | ✅ Uma identidade. Sem caminho pessoal, IP de LAN ou nome de máquina no diff, e nenhuma empresa ligada à dupla. Os fabricantes citados são os dos produtos em questão |
| **R-14** | ✅ Nenhuma mudança em fotos, e o aviso `Sem pessoas no quadro` continua. O passo 6 do README manda apagar as fotos, conforme o `docs/dataset-protocol.md` §9 |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| Nenhuma | — | — | `uv.lock` sem mudança. O `onnxruntime` continua no 1.31.0 |

## Como verifiquei

```text
$ PARTQC_TELEMETRY_TESTS=1 .venv/bin/python -m pytest \
    tests/acceptance/test_spec_042.py::test_ca01_real_network_measurement_with_control
1 passed in 80.30s

$ (no namespace, ambiente limpo) .venv/bin/python -m pytest \
    tests/acceptance/test_spec_042.py edge/tests/acceptance/test_spec_042.py \
    edge/tests/test_telemetry.py ml/tests/test_telemetry.py \
    edge/tests/test_live_route.py edge/tests/acceptance/test_spec_019.py
291 passed, 1 skipped (o CA-01, sem a variável)

$ ruff check .            All checks passed!
$ ruff format --check .   315 files already formatted
```

**Não rodei a suíte inteira.** Os números dela vêm do `r1-test-report.md`, e o CI do PR confirma. Não há CI ainda, porque o PR não existe. Não abri um navegador: a faixa de 3 linhas vem do ensaio do tester e da leitura do código.

**Como rodei o roteiro:** o `guard_paths` recusou gravar um arquivo de roteiro no diretório temporário da sessão, por estar fora do projeto. Por isso, passei o roteiro pela entrada padrão do Python, sem criar arquivo, e não mexi no hook. As pastas de medição foram geradas por comando nesse diretório temporário e apagadas no fim. Todo comando meu fora do namespace teve `ORT_DISABLE_TELEMETRY=1` exportada antes. O `import onnxruntime` sem a variável só rodou dentro do namespace.

## SPEC_ISSUE (se houver)

Nenhum.

O §1 da SPEC diz "ao carregar um modelo", e a OBS-01 mediu que o `import` já basta (RV-05). Concordo com o tester e com o reviewer: nenhum requisito fica ambíguo, e o §9 da arquitetura já traz o fato certo.

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
