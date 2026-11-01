# SPEC-042 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-042](../../docs/specs/SPEC-042-manutencao-telemetria-ca-lote.md) |
| Rodada | r1 |
| Tester | tester |
| Commit testado | `298a50e` |
| **Veredicto** | **PASS** |

O CA-11 e o §3.3 são manuais e ficam com o humano, depois do merge (SPEC §8). Nenhum bug de produção e nenhum `SPEC_ISSUE`. Duas coisas pedem leitura do orquestrador e do security-devops: a telemetria dispara já no `import onnxruntime`, sem sessão (OBS-01), e eu mesmo a disparei fora do isolamento duas vezes (seção "Disparos fora do isolamento").

## Cobertura dos critérios de aceite

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `tests/acceptance/test_spec_042.py::test_ca01_real_network_measurement_with_control`, com `PARTQC_TELEMETRY_TESTS=1`, sem pulo | ✅ |
| CA-02 | `tests/acceptance/test_spec_042.py::test_ca02_edge_session_and_inference_create_no_queue` | ✅ |
| CA-03 | `tests/acceptance/test_spec_042.py::test_ca03_train_parity_creates_no_queue` | ✅ |
| CA-04 | `tests/acceptance/test_spec_042.py::test_ca04_inherited_zero_does_not_turn_it_back_on` (`qc_edge` e `qc_ml`) | ✅ |
| CA-05 | `tests/acceptance/test_spec_042.py::test_ca05_root_conftest_sets_the_variable` | ✅ |
| CA-06 | `tests/acceptance/test_spec_042.py::test_ca06_onnxruntime_inventory` | ✅ |
| CA-07 | `tests/acceptance/test_spec_042.py::test_ca07_env_example_only_comments_the_variable` | ✅ |
| CA-08 | `edge/tests/acceptance/test_spec_042.py::test_ca08_readme_after_the_presentation` | ✅ |
| CA-09 | `edge/tests/acceptance/test_spec_042.py::test_ca09_page_shape` | ✅ |
| CA-10 | Ensaio em navegador, fora da suíte, com controle negativo (SPEC §6). Resultados abaixo | ✅ |
| CA-11 (manual) | Não automatizado. Fica com a dupla, depois do merge (SPEC §3.3 e §8). O ensaio do CA-10 não o substitui | ⏳ pendente |

## CA-01: medição real da rede

**Montagem, a do §4.2:**

- **Comando:** `unshare --user --map-root-user --net strace -f -qq -s 256 -e trace=network -o <log> <sys.executable> -c <script> <modelo>`.
- **Ambiente:** só `PATH` e `HOME=<tmp_path>`.
- **Modelo:** `ml/tests/fixtures/tiny_model`.
- **Janela:** 35 s depois da sessão em (b) e (c), com o tempo medido no próprio processo e conferido pelo teste (`window_s` ≥ 35).
- **Sonda antes dos três processos:** o namespace só tem a interface `lo`, um `connect` UDP para `192.0.2.1:53` falha com o código 101 (rede inalcançável), e o `strace` registra essa linha. Assim, os "0 consultas" de (b) e (c) têm um observador que comprovadamente enxerga a consulta.

**Última medição em cada ambiente, com os scripts finais:**

| Processo | Ambiente | Código | Linhas no log | Consultas | Fila no `HOME` temporário |
|---|---|---|---|---|---|
| (a) controle | sem torch | -15 (parado por mim ao ver a consulta e a fila, §4.2) | 67 | **14** | **criada:** `.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db` |
| (b) borda | sem torch | 0 | 0 | **0** | **nenhuma** |
| (c) treino | sem torch | 0 (`ok=True`) | 0 | **0** | **nenhuma** |
| (a) controle | com `train` | -15 | 70 | **14** | **criada**, no mesmo caminho |
| (b) borda | com `train` | 0 | 0 | **0** | **nenhuma** |
| (c) treino | com `train` | 0 (`ok=True`) | 0 | **0** | **nenhuma** |

As duas execuções anteriores, antes de eu mudar a ordem da conferência nos scripts (OBS-01), deram o mesmo resultado, com 69 e 70 linhas e 14 consultas no controle e 0 linhas em (b) e (c). O CA-01 rodou 4 vezes, nunca com pulo, e `onnxruntime` é o 1.31.0 do `uv.lock`.

**O risco do §7 não se confirmou:** a atribuição por `os.environ` dentro do processo basta, e a fila aparece no `HOME` temporário mesmo com o processo como root no namespace.

**O que o controle fez na rede,** na execução sem torch em que abri o log: 14 linhas de consulta, sendo 12 com `htons(53)` e 2 com `io.systemd.Resolve`, que falharam por falta de rede (`ENETUNREACH`, `EADDRNOTAVAIL`). O log não tem `sendto`, `sendmsg` nem `htons(443)`. Neste notebook, `/run/systemd/resolve/` não existe, então a saída pelo resolvedor prevista no §7 não tem como ocorrer aqui.

## CA-10: ensaio em navegador

**Ambiente:**

- **Navegador:** Google Chrome 156.0.8078.79, `--headless=new`, controlado por CDP, com `Emulation.setDeviceMetricsOverride` (`mobile: true`, escala 2).
- **Câmera:** a falsa do Chrome (`--use-fake-device-for-media-stream`), sem nenhuma foto.
- **Servidor:** `create_app` real sob `uvicorn`, em `https://127.0.0.1` com certificado autoassinado temporário, `InMemorySink`, sem `DEVICE_API_KEY` nem `CLOUD_API_URL`. Nada foi enviado à nuvem.
- **Inferenciador:** roteirizado, com `model_version=partqc-mnv3-provisional-v1`. Responde `unknown` até eu pedir um `EMIT`.
- **Parâmetros só para encurtar o ensaio:** `LIVE_FPS=5`, `LIVE_WINDOW=3`, `LIVE_MIN_AGREE=2` e `LIVE_EMPTY_FRAMES=1`.

**Como medi:**

- **Digitação:** com `Input.insertText` e `Input.dispatchKeyEvent`, com o campo em foco (Enter real).
- **Lote de cada quadro:** lido do corpo real de cada `POST /api/live/frame`, num invólucro ASGI em volta do app real. Só observa.
- **Faixa:** envolvendo `fillRect` e `fillText` do canvas `overlay`, com o `measureText` de cada linha.
- **Sink:** lido diretamente.

**Resultado: 7 de 7 passos aprovados nas duas telas.** Todas as respostas foram 200.

| Passo | 390×844 | 320×568 |
|---|---|---|
| 1. Sem lote guardado | `Lote em uso: nenhum`, classe `status`, 0 quadros em 1,8 s | idem |
| 2. `L-001` sem confirmar | `Lote em uso: nenhum · pressione Enter para aplicar o lote digitado`, classe `status error`, 0 quadros | idem |
| 3. Enter | `Lote em uso: L-001`, sem `error`; 3 quadros na janela, todos com `L-001` | idem |
| 4. `L-0`, sem sair do campo | `Lote em uso: L-001 · pressione Enter para aplicar o lote digitado`; o foco continua no campo; 8 quadros, todos com `L-001` | idem |
| 5. `EMIT` | sink com `L-001`, `source=simulated`; faixa com `Registrada: parafuso mediano`, `aprovada (modelo provisório)`, `Lote: L-001` | idem |
| 5. Lote de 40 `W` | sink com o lote inteiro; 3 linhas com 269,6, 248,8 e 318,3 px, dentro de 338 px (canvas 358) | 254,6, 248,8 e 238,7 px, dentro de 268 px (canvas 288) |
| 6. `lote 1` + Enter | `Lote em uso: nenhum`; status `Informe o lote: só letras, números, - e _ (até 40).`; 0 quadros | idem |
| 7. `L-002` e recarregar | `Lote em uso: L-002`, antes de qualquer digitação | idem |

**Controle negativo:** o mesmo roteiro, com o `live.js` de `9419a5e` (o anterior a esta SPEC) injetado só no navegador, por `Fetch.fulfillRequest`. **Reprovou nos 7 passos, nas duas telas.** O `#lot-in-use` fica vazio em todos os passos, e a faixa tem só 2 linhas, sem `Lote: `. Os quadros seguem iguais (`L-001` nos passos 3 e 4; nenhum nos passos 1, 2 e 6), o que confirma que a SPEC só torna a regra visível, sem mudá-la (§3.2).

**Limites:** mesma máquina, sem Wi-Fi e sem celular, com `system-ui` resolvendo para Noto Sans. O teclado do Android e o gesto de voltar só são conferidos no CA-11.

**Sobre o ensaio:** o script não é versionado e não faz parte da suíte. O `guard_paths` recusou escrevê-lo no diretório temporário da sessão, por ficar fora do projeto, como na SPEC-019. Por isso, ele ficou em `edge/tests/acceptance/_ca10_rehearsal/`, um caminho permitido, sem commit, e foi apagado antes de rodar a suíte e o ruff. O certificado, o perfil do Chrome, as capturas e a cópia do `live.js` antigo foram gerados por comando no diretório temporário e apagados no fim.

## Suíte completa

Como no CI, sem torch (`uv sync --all-packages --locked`), com `CI=true` e `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test`, sem outra suíte ao mesmo tempo. Depois, restaurei o extra `train` com `uv sync --all-packages --extra train --locked` e conferi o `import torch`.

```text
10222 passed, 167 skipped, 1 warning in 1108.85s (0:18:28)   (exit=0)
ruff check .            All checks passed!
ruff format --check .   315 files already formatted
```

A suíte rodou com os dois arquivos de aceite novos no disco, ainda sem commit, e eles não mudaram depois disso. **Testes novos:** 41 itens, sendo 10 de CA (o CA-04 conta 2) e 31 `test_extra_*`.

**Pulos, todos esperados:**

| Motivo | Quantidade |
|---|---|
| `PARTQC_DOCKER_TESTS` não definida (roda no workflow `docker`) | 108 |
| `could not import 'torch'`, porque o ambiente é sem torch | 49 |
| `PARTQC_MQTT_TESTS` não definida | 6 |
| `PARTQC_TELEMETRY_TESTS` não definida: é o CA-01, rodado à parte acima | 1 |
| Modelo real ausente neste checkout | 3 |

O único aviso é o `StarletteDeprecationWarning` de `fastapi/testclient.py`, que não vem desta SPEC.

**Nenhum teste de aceite anterior precisou de ajuste,** como o §6 previa. Não há tabela de ajustes.

## Bugs encontrados

Nenhum bug de produção.

## Observações, sem bug

**OBS-01 (para o architect e o security-devops): a telemetria dispara já no `import onnxruntime`, sem sessão.**

- **Medição, no isolamento do §4.2, com `HOME` temporário:** `import onnxruntime` seguido de 10 s de espera, sem criar sessão, teve 14 consultas e criou a fila.
- **Divergência de texto:** o §1 diz "ao carregar um modelo", e o preâmbulo do §5 diz que o script "confere a variável antes de criar a sessão [...] para um código errado não disparar a telemetria no runner do CI".
- **Efeito no preâmbulo do §5:** um script que importe `qc_edge.onnx_inferencer` e só depois confira a variável **não** cumpre esse propósito. Com cópias dos pacotes sem a atribuição, ele saiu com código 3, mas já com a fila criada no `HOME` temporário.
- **O que fiz:** nos meus scripts, a conferência vem logo depois de `import qc_edge` ou `import qc_ml`, antes de o `onnxruntime` carregar. Isso cumpre a letra (antes da sessão), o propósito e o texto dos CAs. Com as mesmas cópias, e com tudo dentro do namespace e com `HOME` temporário: código 3, nenhuma fila, nenhum arquivo. O reviewer pode conferir essa ordem em `tests/acceptance/test_spec_042.py`.
- **Por que não é `SPEC_ISSUE`:** todos os CAs continuam testáveis, nenhum requisito se contradiz e a implementação está certa, porque a variável é atribuída antes de qualquer import do `onnxruntime`.
- **O que vale conferir:** o texto que o architect escrever em `docs/architecture.md` §9 deveria dizer "ao importar". E quem rodar `python -c "import onnxruntime"` à mão, fora dos pacotes do projeto, dispara a telemetria mesmo depois desta SPEC, como aconteceu comigo (seção seguinte).

**OBS-02 (baixa, sem CA afetado): com um lote de 40 `W`, a 3ª linha da faixa fica muito pequena.** A fonte cai para 8 px em 390 px e para 6 px em 320 px. Não há corte, e o `measureText` passa no CA-10, mas o texto mal se lê na faixa. Na captura, a linha `Lote em uso` acima do vídeo mostra o lote inteiro, em letra grande. É o pior caso: `Lote: L-001` fica com 18 px nas duas telas.

**OBS-03 (para o reviewer): a regra `#lot-in-use { overflow-wrap: anywhere; }`, declarada no dev-report, não está na SPEC.** Conferi só o efeito: com o lote de 40 `W`, a largura da página fica igual à da tela (390 e 320 px). O CA-09 não é afetado.

**OBS-04: a fila real deste notebook foi escrita às 18:08:37 de 2026-11-01, antes de qualquer comando meu nesta rodada.** Não sei qual processo foi. Pode ser de outro checkout ou de outra sessão.

## Disparos fora do isolamento (erro meu)

O pedido era não usar rede real além do que a SPEC prevê. Disparei a telemetria duas vezes fora do namespace, porque eu ainda não sabia que o `import` sozinho já a dispara:

| Quando (2026-11-01, -03) | Comando | `HOME` | Efeito conferido |
|---|---|---|---|
| 18:23:47 | `.venv/bin/python -c "import onnxruntime as o; print(o.__version__)"`, para conferir a versão, sem a variável, depois do `uv sync` | **real** | A fila real `~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db` passou de 18:08:37 para 18:23:47 |
| Entre 18:26 e 18:27 | 2 subprocessos do experimento com as cópias sem a atribuição (OBS-01), sem `unshare` | temporário, já apagado | Fila criada só no `HOME` temporário; a fila real não mudou |

- **Rede:** os três processos tiveram acesso normal à rede e duraram pouco. Não medi se uma consulta de DNS saiu, então é preciso supor que **pode ter saído** uma consulta para `mobile.events.data.microsoft.com`.
- **Conteúdo:** segundo o §1, os eventos vistos não têm imagem, token nem resultado. O teste não usou nada disso: o primeiro comando só importou o pacote, e os outros pararam no código 3 antes de abrir o modelo. Não li a fila real.
- **O que não fiz:** não apaguei a fila real. Isso é o item opcional do §3.3 e continua com o humano, agora com a entrada das 18:23:47 a mais.
- **Depois disso:** rodei tudo o que podia carregar o `onnxruntime` sem a variável dentro do namespace, com `HOME` temporário. A fila real ficou em 18:23:47 até o fim, inclusive depois da suíte inteira e das repetições do CA-01.

## Testes exploratórios (além dos critérios)

**No arquivo de aceite (`test_extra_*`, todos passando):** o comentário exato do `.env.example`; variável herdada ausente, vazia, `0`, `false`, `off` e `1` terminando em `1`; a variável já vale `1` no instante em que o `onnxruntime` carregaria, partindo de `0` (por `qc_edge.onnx_inferencer`, `qc_edge.cli`, `qc_edge.app`, `qc_ml.parity` e `qc_ml.predict`, sem criar sessão); a atribuição chega ao `getenv` do C; `OnnxInferencer` real com o `tiny_model` e uma imagem não cria fila; ninguém chama `disable_telemetry_events`; só os dois `__init__.py` citam a variável fora dos testes; a ordem dos passos e o aviso do README; o `<p>` vazio logo depois do `<label>`; `showLot()` no fim de `loadLot` e de `confirmLot`; `send` e `tick` sem ler `lotField`; o `input` sem confirmar o lote.

**Comportamento do CA-01 sem as condições (§4.2):**

| Caso | Resultado |
|---|---|
| Sem `PARTQC_TELEMETRY_TESTS`, ou com `0` | pulado |
| Com `1`, sem `unshare` nem `strace` no `PATH` | **falha** |
| Com `1`, só sem `strace` | **falha** |
| Com `1`, com um `unshare` que recusa o namespace (substituto temporário com código 1) | **falha** |

**Proteção dos processos de teste (§4.1), sem `CI`, com `HOME` temporário e dentro do namespace:**

| Arquivo | Resultado | Fila |
|---|---|---|
| `edge/tests/acceptance/test_spec_008.py` | 112 passed, 1 skipped | nenhuma, e nenhum arquivo no `HOME` |
| `ml/tests/test_pipeline_slow.py`, com `train` | 7 passed | nenhuma, e nenhum arquivo no `HOME` |

**Campo do lote, em Chrome, 390×844:**

| Caso | Resultado |
|---|---|
| `  L-010  ` com espaços nas pontas + Enter | `Lote em uso: L-010`, sem aviso; o campo mantém os espaços |
| `<img src=x onerror=...>` digitado | texto com o aviso |
| O mesmo + Enter | `Lote em uso: nenhum`; `#lot-in-use` sem elementos filhos, e o `onerror` não rodou |
| Digitar outro lote e voltar ao confirmado, sem Enter | o aviso aparece e some |
| Sair do campo com `L-013` | confirma: `Lote em uso: L-013`, a regra de sempre |
| Apagar o campo, sem confirmar | `Lote em uso: L-013 · pressione Enter...`, e os quadros seguem com `L-013` |
| Campo vazio + Enter | `Lote em uso: nenhum`, 0 quadros |
| `localStorage` com `lote 1` ou `é-unicode`, ao recarregar | `Lote em uso: nenhum`, sem aviso |
| `localStorage` com `  L-020 `, ao recarregar | `Lote em uso: L-020`, sem aviso |
| 62 caracteres digitados | o `maxlength` corta em 40; `nenhum` com o aviso, porque o lote confirmado era inválido |
| Trocar o lote enquanto a resposta do `EMIT` está a caminho (resposta segurada por 1,5 s no invólucro) | sink com `L-030`; `#lot-in-use` com `L-031`; **a faixa mostra `Lote: L-030`**, o que o servidor registrou, e não a variável local (§4.3) |

## SPEC_ISSUE (se houver)

Nenhum. Ver a justificativa na OBS-01.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
