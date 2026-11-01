# SPEC-042: Manutenção da borda e do treino (telemetria desligada, remoção da CA e lote em uso)

| Campo | Valor |
|---|---|
| Status | In Security |
| Rodada atual | r1 |
| Autor da implementação | ml-engineer (Parte A: `ml/`), depois developer (Parte B: o resto), na mesma rodada |
| Tags | security |
| Depende de | SPEC-019, SPEC-041 |
| Semana alvo | S4 (02–08/11), logo depois do merge da SPEC-019 |
| Requisitos cobertos | RF-02, RF-10, RNF-05; R-02 (mantida, ver §1), R-06, R-12, R-14 |
| ADRs relevantes | ADR-013 (o lote é o subgrupo da carta p), ADR-003 |

> **Escopo decidido pelo humano em 2026-11-01:** "Uma SPEC-042 curta desliga a telemetria no código da borda e do treino, e inclui o aviso de remover a CA dos celulares e o lote em uso visível na tela do vídeo." O texto foi aprovado pelo humano em 2026-11-01.

## 1. Contexto

Três itens deixados pelos portões da SPEC-019, em `docs/architecture.md` §6.1 (página `/live`), §7 (modelo) e §9 (segurança).

**SEC-19-01 (`reviews/SPEC-019/r2-security-report.md`).** O `onnxruntime` 1.31.0 do `uv.lock` tem telemetria ativa no Linux. Ao carregar um modelo, ele grava eventos em `~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db` e consulta o DNS de `mobile.events.data.microsoft.com`. Medições do security-devops, com o processo num namespace de rede sem saída:

| Caso | DNS consultado | Banco local de eventos |
|---|---|---|
| Padrão | sim (4 consultas em cerca de 28 s) | criado |
| `ORT_DISABLE_TELEMETRY=1` no ambiente do processo | nenhum | não criado |
| `onnxruntime.disable_telemetry_events()` logo depois do import | a mesma consulta | criado |

**Decisão do humano em 2026-11-01, relatada pelo orquestrador: isso não é quebra da R-02.** Os eventos vistos não têm imagem, token nem resultado. A leitura do relatório fica confirmada, o achado continua médio, e `docs/rules.md` não muda. O humano decidiu desligar a telemetria mesmo assim.

**SEC-19-02 (mesmo relatório).** O `edge/README.md` ensina a instalar a CA do `mkcert` com confiança total nos celulares pessoais, mas não ensina a tirá-la. Depois da apresentação, eles continuariam confiando em qualquer certificado emitido com o `rootCA-key.pem` do notebook.

**RV-01 (`reviews/SPEC-019/r2-review-report.md`).** A página não mostra o lote em uso. Com um lote confirmado, trocar o texto do campo sem confirmar mantém os quadros no lote anterior, e nem a faixa nem a resposta visível avisam. Uma inspeção pode entrar no subgrupo errado da carta p (ADR-013).

**Fontes externas, consultadas pelo architect em 2026-11-01:**

- Telemetria: não há documentação oficial conhecida. Uma [análise de terceiro da versão 1.29](https://github.com/kibae/onnxruntime-server/releases/tag/v1.29.0) diz que ela é suprimida por `ORT_DISABLE_TELEMETRY`, `ORT_RUNNING_UNIT_TESTS` ou "a CI environment variable", e que o evento de criação de sessão traz também o nome e os metadados do modelo. Isso não foi medido aqui.
- `mkcert`: em [`main.go`](https://raw.githubusercontent.com/FiloSottile/mkcert/master/main.go), `-uninstall` é "Uninstall the local CA (but do not delete it)", e `-CAROOT` imprime a pasta da CA. Em [`cert.go`](https://raw.githubusercontent.com/FiloSottile/mkcert/master/cert.go), a CA se chama `mkcert <usuário>@<máquina>`.
- Remoção nos celulares: [guia da Apple](https://support.apple.com/guide/deployment/distribute-certificates-depcdc9a6a3f/web) e [ajuda do Pixel](https://support.google.com/pixelphone/answer/2844832?hl=en), que avisa que alguns passos só valem no Android 14 ou mais novo.

## 2. Objetivo

Nenhum processo do projeto que importa `onnxruntime` consulta o DNS da telemetria nem cria a fila local; o `edge/README.md` ensina a remover a CA depois da apresentação; e a tela do vídeo mostra o lote em uso, com um aviso quando o campo diverge dele.

## 3. Escopo

### 3.1 Dentro

**Parte A (ml-engineer):**

- `ml/src/qc_ml/__init__.py` (§4.1) e testes do autor em `ml/tests/`.

**Parte B (developer):**

- `edge/src/qc_edge/__init__.py` e o `conftest.py` da raiz (§4.1);
- `.env.example`: um comentário (§4.1);
- `edge/src/qc_edge/templates/live.html` e `edge/src/qc_edge/static/live.js` (§4.3);
- `edge/README.md` (§4.4);
- testes do autor em `edge/tests/`.

**Tester:** `tests/acceptance/test_spec_042.py` (CA-01 a CA-07) e `edge/tests/acceptance/test_spec_042.py` (CA-08 e CA-09), mais o ensaio do CA-10.

### 3.2 Fora

- RV-02, RV-03 e RV-04 da mesma revisão (nitidez do canvas, altura do palco e palavra repetida): baixas. A RV-03 continua a ser conferida no CA-12 da SPEC-019; as outras só entram com uma SPEC nova, se o humano pedir.
- A regra de confirmação do lote (SPEC-019 §4.5): continua igual. Esta SPEC só a torna visível.
- Servidor da borda, rotas e contrato: nada muda em `app.py`, `live.py` ou `packages/contracts`.
- `api/` e `dashboard/`: não têm `onnxruntime` (R-12).
- Bloquear a telemetria na rede, trocar a versão do `onnxruntime` ou usar `disable_telemetry_events()`.
- `docs/rules.md`: não muda.

### 3.3 Trabalho humano

1. **Opcional, depois do merge:** apagar a fila que já existe no notebook (`~/.cache/Microsoft/DeveloperTools/.onnxruntime/`). O código não a remove, e ela traz o caminho da pasta pessoal.
2. Executar o CA-11, junto do CA-12 da SPEC-019.
3. **Depois da apresentação:** seguir a seção nova do README (§4.4).

## 4. Requisitos detalhados

### 4.1 Telemetria desligada

Em `qc_edge/__init__.py` e `qc_ml/__init__.py`, antes do `__version__`:

```python
import os

# SEC-19-01: only this variable, set before onnxruntime loads, stops its telemetry (SPEC-042).
os.environ["ORT_DISABLE_TELEMETRY"] = "1"
```

- **Atribuição direta, sem `setdefault`:** um `ORT_DISABLE_TELEMETRY=0` herdado do shell não religa a telemetria. A variável não é configuração do projeto e não é lida do `.env`.
- **Por que no `__init__`:** todo `qc_edge.*` e `qc_ml.*` passa por ele antes de qualquer outro módulo, inclusive `qc-edge`, `python -m qc_ml.*` e um import indireto do `onnxruntime` pelo `torch` durante o export.
- Os dois `__init__.py` não importam `onnxruntime`, e os módulos que o importam hoje (`onnx_inferencer.py`, `predict.py` e `parity.py`) não mudam.
- **Testes:** o `conftest.py` da raiz faz a mesma atribuição logo depois dos imports dele, porque `edge/tests/acceptance/test_spec_008.py` e `ml/tests/test_pipeline_slow.py` importam `onnxruntime` direto, e o `CI=true` que hoje pode suprimir a telemetria não existe numa execução local.
- **`.env.example`:** um comentário, sem linha `CHAVE=valor`: `# onnxruntime telemetry: the code sets ORT_DISABLE_TELEMETRY to 1 (SPEC-042); nothing to configure.`
- Sem dependência nova, sem log novo, sem chamar `disable_telemetry_events()`.

### 4.2 Medição real da rede (CA-01)

Só roda com `PARTQC_TELEMETRY_TESTS=1`, e o teste é marcado `slow`. Sem a variável, é pulado. Com a variável e sem `unshare` ou `strace`, ou sem permissão para criar o namespace, ele **falha**, para a falta de ferramenta não virar um pulo silencioso.

- **Ambiente limpo (vale para os CAs 01 a 05):** o `env` do subprocesso é montado do zero, só com `PATH` e `HOME=<tmp_path>`, e o interpretador é `sys.executable`. Assim, ficam de fora `CI`, `ORT_RUNNING_UNIT_TESTS`, `ORT_DISABLE_TELEMETRY` e qualquer outra variável de CI. Nunca aponte o `HOME` para a pasta real.
- **Modelo real:** `ml/tests/fixtures/tiny_model/model.onnx`, versionado.
- **Isolamento:** `unshare --user --map-root-user --net`, sem interface com saída. Nada pode sair para a internet.
- **Observação:** `strace -f -qq -s 256 -e trace=network -o <log>`.
- **Consulta:** uma linha do log com `htons(53)`, `io.systemd.Resolve` ou o nome `mobile.events`, seja com pontos, seja no formato de rótulos do DNS (`\6mobile\6events`).
- **Fila:** qualquer `onnxruntime.db` ou pasta `.onnxruntime` sob o `HOME` temporário.
- **Janela:** cada processo fica vivo por 35 s depois de criar a sessão, porque a medição viu 4 consultas em cerca de 28 s. O controle pode terminar assim que vir a consulta.

### 4.3 Lote em uso na tela do vídeo

**`live.html`:** logo depois do `<label>` do lote, e antes do `id="stage"`, um `<p id="lot-in-use" class="status"></p>`, vazio.

**`live.js`:** uma função `showLot()`, chamada no fim de `loadLot` e de `confirmLot` e num novo `lotField.addEventListener("input", showLot)`, porque fechar o teclado do Android pelo gesto de voltar pode não disparar `blur` nem `change`. Ela escreve com `textContent`, nunca com `innerHTML`. Com `campo = lotField.value.trim()`:

| `lot` (confirmado) | `campo` | Texto de `#lot-in-use` | Classe |
|---|---|---|---|
| válido (`LOT_RE`) | igual a `lot` | `Lote em uso: L-001` | `status` |
| válido | diferente | `Lote em uso: L-001 · pressione Enter para aplicar o lote digitado` | `status error` |
| inválido ou vazio (nenhum quadro é enviado) | igual a `lot` | `Lote em uso: nenhum` | `status` |
| inválido ou vazio | diferente | `Lote em uso: nenhum · pressione Enter para aplicar o lote digitado` | `status error` |

**Faixa verde do `EMIT`:** `emittedLines` ganha uma 3ª linha, `Lote: ` + `inspection.lot_id`, o lote que o servidor registrou, e não a variável local. As duas primeiras linhas e o aviso de R-06 não mudam. Continua valendo a regra do `drawBand`: nenhuma linha é cortada.

### 4.4 `edge/README.md`

**Em "Usar":** o passo 1 explica a linha `Lote em uso` e o aviso, e o passo 3 diz que a faixa verde mostra o lote registrado.

**Nova seção `### Depois da apresentação`**, em "Vídeo ao vivo (HTTPS)", logo depois de "Instalar a CA nos celulares", com estes passos, nesta ordem:

1. **Por quê:** enquanto a CA estiver instalada, o celular confia em qualquer certificado emitido com o `rootCA-key.pem` do notebook, inclusive de sites públicos.
2. **iOS:** em Ajustes > Geral > Gerenciamento de Dispositivos (o nome do menu varia com a versão), abra o perfil com `mkcert` no nome e remova-o.
3. **Android:** em Configurações > Segurança e privacidade > Mais configurações de segurança > Criptografia e credenciais > Credenciais do usuário (o caminho varia com o aparelho e a versão), remova só o certificado com `mkcert` no nome. **Não use "Limpar credenciais"**, que apaga todos os certificados instalados pelo usuário.
4. **Notebook,** na raiz do repositório e nesta ordem: `mkcert -uninstall`, que tira a CA dos repositórios de confiança, mas não apaga os arquivos; depois `rm -rf "$(mkcert -CAROOT)"`, que apaga o `rootCA-key.pem`; depois `rm -rf edge/data/tls`.
5. Tire `EDGE_TLS_CERT` e `EDGE_TLS_KEY` do `.env`: com os arquivos apagados, a borda não sobe (código 2).
6. Apague as fotos, conforme o `docs/dataset-protocol.md` §9.

## 5. Critérios de aceite

Os ambientes, o modelo e a definição de consulta e de fila são os do §4.2. Nos CAs 02 e 03, o script confere a variável **antes** de criar a sessão e sai com código 3 se ela não for `1`, para um código errado não disparar a telemetria no runner do CI.

- **CA-01 (R-02, rede real, `PARTQC_TELEMETRY_TESTS=1`)** — *Dado* o isolamento e o `strace` do §4.2, *quando* rodam, em ambiente limpo, (a) o controle, `python -c` com `import onnxruntime` direto e uma sessão real, (b) a borda, `import qc_edge.onnx_inferencer` e uma sessão real por `qc_edge.onnx_inferencer.onnxruntime.InferenceSession`, e (c) o treino, `qc_ml.parity.check_parity(<tiny_model>)`, *então* (a) tem pelo menos 1 consulta **e** a fila criada sob o `HOME` temporário; e (b) e (c), cada um com a janela completa de 35 s, têm 0 consulta e nenhuma fila. Se o controle não mostrar as duas coisas, o teste **falha**, porque a medição não provaria nada.
- **CA-02 (borda, fila, roda no CI)** — *Dado* o ambiente limpo, sem `unshare`, *quando* um subprocesso importa `qc_edge.onnx_inferencer`, cria uma sessão real e faz uma inferência, *então* sai com código 0, e o `HOME` temporário não tem `onnxruntime.db` nem pasta `.onnxruntime`.
- **CA-03 (treino, fila, roda no CI)** — *Dado* o ambiente limpo, sem `unshare`, *quando* um subprocesso chama `qc_ml.parity.check_parity(<tiny_model>)`, *então* sai com código 0, `ok` é `True`, e o `HOME` temporário não tem `onnxruntime.db` nem pasta `.onnxruntime`.
- **CA-04 (valor herdado, sem efeito colateral)** — *Dado* o ambiente limpo mais `ORT_DISABLE_TELEMETRY=0`, *quando* um subprocesso roda `import qc_edge` e outro roda `import qc_ml`, *então*, nos dois, `os.environ["ORT_DISABLE_TELEMETRY"] == "1"` e `"onnxruntime" not in sys.modules`.
- **CA-05 (processos de teste)** — *Dado* o ambiente limpo, *quando* um subprocesso executa o `conftest.py` da raiz com `runpy.run_path`, *então* sai com código 0, `os.environ["ORT_DISABLE_TELEMETRY"] == "1"` e `"onnxruntime" not in sys.modules`.
- **CA-06 (R-12, inventário)** — *Dado* a árvore do repositório, *quando* o `ast` procura `import onnxruntime` e `from onnxruntime` nos `.py` de `api/`, `dashboard/`, `edge/`, `ml/`, `packages/`, `scripts/` e `infra/`, fora de `tests/`, *então* os arquivos encontrados são exatamente `edge/src/qc_edge/onnx_inferencer.py`, `ml/src/qc_ml/predict.py` e `ml/src/qc_ml/parity.py`.
- **CA-07 (`.env.example`)** — *Dado* o `.env.example`, *quando* lido, *então* uma linha começada por `#` cita `ORT_DISABLE_TELEMETRY`, e nenhuma linha começa por `ORT_DISABLE_TELEMETRY=`.
- **CA-08 (README)** — *Dado* o `edge/README.md`, *quando* lido, *então* `### Depois da apresentação` aparece entre `### Instalar a CA nos celulares` e `### Usar`; a seção contém `iOS`, `Android`, `Credenciais do usuário`, `Limpar credenciais`, `mkcert -uninstall`, `mkcert -CAROOT`, `rootCA-key.pem`, `EDGE_TLS_CERT`, `EDGE_TLS_KEY`, `edge/data/tls` e `docs/dataset-protocol.md`; `mkcert -uninstall` vem antes do `rm -rf "$(mkcert -CAROOT)"`; e a seção `### Usar` contém `Lote em uso`.
- **CA-09 (página, forma)** — *Dado* a borda com o token válido, *quando* `GET /live?t=<token>` e `GET /static/live.js` respondem, *então* os dois dão 200; o HTML tem `id="lot-in-use"` antes de `id="stage"`; o JS contém `Lote em uso: `, `nenhum`, `pressione Enter para aplicar o lote digitado`, `addEventListener("input", showLot)`, `inspection.lot_id` e `Lote: `; e o JS não contém `innerHTML`.
- **CA-10 (ensaio em navegador, tester; R-06)** — Com Chrome headless, câmera falsa e `create_app` real com o sink em memória, sem nuvem, e um inferenciador roteirizado com `model_version` provisório, em telas de 390×844 e 320×568:
  1. Sem lote guardado, abrir `/live`: `#lot-in-use` é `Lote em uso: nenhum`, e nenhum quadro é enviado.
  2. Digitar `L-001` sem confirmar: o texto é `Lote em uso: nenhum · pressione Enter para aplicar o lote digitado`, com a classe `error`, e nenhum quadro é enviado.
  3. Pressionar Enter: o texto é `Lote em uso: L-001`, sem a classe `error`, e os quadros levam `lot_id=L-001`.
  4. Digitar `L-0`, sem confirmar e sem sair do campo: o texto é `Lote em uso: L-001 · pressione Enter para aplicar o lote digitado`, e os quadros continuam com `L-001`.
  5. Provocar um `EMIT`: o sink tem `lot_id=L-001`; a faixa verde tem 3 linhas, a 2ª com `(modelo provisório)` e a 3ª `Lote: L-001`; e, repetindo com um lote confirmado de 40 caracteres, `measureText` de cada linha fica dentro de `largura do canvas − 20`.
  6. Digitar `lote 1` e pressionar Enter: o texto é `Lote em uso: nenhum`, a linha de status traz `Informe o lote`, e nenhum quadro é enviado.
  7. Confirmar `L-002` e recarregar a página: o texto é `Lote em uso: L-002`, antes de qualquer digitação.

  **Controle negativo:** o mesmo roteiro, com o `live.js` anterior a esta SPEC, reprova nos 7 passos.
- **CA-11 (manual, dupla)** — No celular, com a `/live` aberta e o lote `L-001` confirmado:
  1. digitar `L-002` no campo;
  2. fechar o teclado sem pressionar Enter (no Android, pelo gesto de voltar);
  3. conferir que a tela mostra `Lote em uso: L-001 · pressione Enter para aplicar o lote digitado`;
  4. inspecionar uma peça e conferir que a faixa verde mostra `Lote: L-001`;
  5. registrar o aparelho, o navegador e a versão.

  Se nenhum celular aceitar o certificado (SPEC-019 §3.3), o CA fica registrado como não atendido, com esse resultado.

## 6. Plano de testes

| Tipo | O que | Onde |
|---|---|---|
| Unitário (autor) | `ml`: a variável depois de `import qc_ml`. `edge`: a variável depois de `import qc_edge`; forma do `showLot` e da 3ª linha, como os testes do `live.js` já fazem | `ml/tests/`, `edge/tests/` |
| Aceite (tester) | CA-01 a CA-07; subprocessos reais, nada mockado | `tests/acceptance/test_spec_042.py` |
| Aceite (tester) | CA-08 e CA-09; banco não é usado | `edge/tests/acceptance/test_spec_042.py` |
| Ensaio (tester), fora da suíte | CA-10, com os resultados e o controle negativo no test-report; roteiro sem commit, como na SPEC-019 | descrito acima |
| Manual (dupla), depois do merge | CA-11 | descrito acima |

**O CA-01 não pode ficar pulado na entrega:** o tester o roda com `PARTQC_TELEMETRY_TESTS=1` no notebook e registra no test-report a contagem de consultas e o estado da fila dos três processos. Um pulo reprova o CA. No CI ele é pulado, porque o controle faz uma consulta real de propósito, e por isso também não roda em toda execução local.

Os testes do `edge/tests/test_live_route.py` e do `test_spec_019.py` que leem o `live.js` continuam válidos, e nenhum teste de aceite anterior precisa de ajuste.

## 7. Riscos e notas para o implementador

- **Variável definida pelo próprio Python:** a medição do §1 pôs a variável no ambiente **antes** de o processo começar, e não com `os.environ` dentro dele. A atribuição chega ao C (`putenv`) antes de o `onnxruntime` carregar, então deve valer, mas isso só o CA-01 prova. Se (b) ou (c) falharem, é `SPEC_ISSUE`: não improvise outra forma.
- **Testes que passam sem provar nada:** o `CI=true` do projeto pode suprimir a telemetria por conta própria, e o `HOME` temporário só vale se o `onnxruntime` o respeitar. Os CAs 02 e 03 não têm controle próprio, porque ele dispararia a telemetria de verdade no CI. Quem prova que a fila apareceria no `HOME` temporário é o controle do CA-01. Se ele não a criar lá (por exemplo, por o processo aparecer como root no namespace), é `SPEC_ISSUE`.
- **O controle no CA-01:** com o `systemd-resolved`, o DNS pode sair do namespace pelo socket em `/run/systemd/resolve/`. A consulta do controle pode, então, chegar ao resolvedor do notebook. A conexão com o coletor continua sem rota. Essa é mais uma razão para ele só rodar sob demanda.
- **Comportamento sem documentação oficial:** ao subir o `onnxruntime` no `uv.lock`, rode o CA-01 de novo. Uma versão nova pode mudar a variável ou o caminho da fila.
- **`live.js`:** `send` e `tick` continuam sem ler `lotField`, `lotField.addEventListener("change", confirmLot)` fica como está, e `showLot` usa o mesmo estilo de função de dois espaços, porque `_js_function`, de `edge/tests/test_live_route.py`, depende dele. O `input` só atualiza o texto: não confirma o lote.

## 8. Definição de pronto

- [ ] CAs 02 a 09 com teste de aceite passando, CA-01 rodado sem pulo e CA-10 ensaiado, com os resultados no test-report (PASS)
- [ ] review-report APPROVED e security-report PASS, com o security-devops conferindo o CA-01 por conta própria
- [ ] CI verde; `ruff` limpo
- [ ] `edge/README.md` e `.env.example` atualizados; `docs/architecture.md` §9 (linha da telemetria e a regra de rodar o CA-01 ao subir o `onnxruntime`) e §10 (`PARTQC_TELEMETRY_TESTS`) pelo architect
- [ ] PR aberto com os relatórios; merge conforme R-09. O CA-11 manual e o §3.3 ficam pendentes no merge, marcados no quadro, e são registrados depois dele

## Histórico

| Data | Mudança | Motivo | Quem pediu |
|---|---|---|---|
| 2026-11-01 | Aprovada pelo humano (`Draft` → `Ready`). | Resposta do humano de 2026-11-01, nesta sessão | Orquestrador, a pedido do humano |
