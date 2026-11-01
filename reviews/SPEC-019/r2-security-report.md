# SPEC-019 — r2 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-019](../../docs/specs/SPEC-019-modo-ao-vivo.md) |
| Rodada | r2 |
| Revisor de segurança | security-devops |
| Diff revisado | `origin/main...94973a9` (`origin/main` = `70cc351`) |
| **Veredicto** | **PASS** |

Nenhum achado bloqueante ou alto. Há 1 médio, 1 baixo e 2 informativos. As reaprovações delegadas estão dentro dos limites, e a decisão local 7 não amplia o console.

**O ponto que o humano precisa ver é o SEC-19-01.** Ele não vem deste diff e não leva imagem, mas o `onnxruntime` tenta enviar telemetria da borda a um serviço externo, com o caminho da pasta pessoal e um identificador do aparelho. O PASS não resolve isso: a decisão é do humano.

## Superfície analisada

| Tema | Onde |
|---|---|
| Rotas novas | `GET /live?t=<token>` e `POST /api/live/frame` (`edge/src/qc_edge/app.py:563`, `:729`, `:821`, `:856`) |
| Rotas alteradas | `GET /`, com TLS e o segundo QR (`app.py:864`, `:1018`); o limite por caminho no middleware (`edge/src/qc_edge/middleware.py`, `app.py:496`) |
| Segredos | `EDGE_TLS_KEY` (`edge/src/qc_edge/config.py`), token de sessão na URL do `/live`, `.env.example`, `edge/README.md` |
| Entradas externas | multipart da rota de quadros, `load_live_image` (`edge/src/qc_edge/limits.py`), `session` e `lot_id` |
| Memória e disco | janela de quadros (`edge/src/qc_edge/live.py:104`, `:117-118`), `captures/`, outbox |
| Página | `edge/src/qc_edge/static/live.js`, `edge/src/qc_edge/templates/live.html` |
| Dependências novas | nenhuma; `uv.lock` e os `pyproject.toml` não mudam. O `mkcert` é ferramenta do humano, fora do repositório |
| Deploy, API, banco e contrato | fora do diff: `infra/`, `.github/`, `api/`, `dashboard/` e `packages/` não mudam |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-19-01 | **média** | privacy, deps (fora do diff) | `edge/pyproject.toml:11`, `uv.lock:773` (`onnxruntime` 1.31.0, desde `7f24d93`) | O `onnxruntime` do pacote tem telemetria ativa no Linux. Ao carregar o modelo, ele grava eventos em `~/.cache/Microsoft/DeveloperTools/.onnxruntime/onnxruntime.db` e consulta o DNS de `mobile.events.data.microsoft.com`. Os eventos guardados trazem o caminho do executável (com o nome do usuário e a pasta do projeto), um identificador ligado ao aparelho, o sistema, a CPU e a memória. **Sem imagem, token ou resultado** nos eventos vistos, por isso não trato como R-02. Detalhes abaixo | **Agora, sem código:** `export ORT_DISABLE_TELEMETRY=1` no ambiente, antes de subir o `qc-edge` ou o treino. **Permanente:** decisão do humano; se quiser, uma SPEC de manutenção que defina a variável antes de importar o `onnxruntime` e a documente no `.env.example`. Não cabe nesta SPEC (R-08). Não bloqueia: o comportamento já está na `main`, e barrar este merge não o reduz |
| SEC-19-02 | baixa | privacy, deploy | `edge/README.md:408` | O README ensina a instalar a CA do `mkcert` com confiança total nos celulares pessoais, mas não ensina a tirá-la. Depois da apresentação, os celulares continuam confiando em qualquer certificado emitido com o `rootCA-key.pem` do notebook, inclusive de sites públicos. O README do `mkcert` avisa que esse arquivo dá "complete power to intercept secure requests". O próprio README da borda já proíbe copiar a chave, então o risco fica limitado a um vazamento do notebook | Acrescentar ao `edge/README.md`, numa próxima manutenção, um passo "Depois da apresentação": remover o perfil ou certificado dos dois celulares e apagar a pasta de `mkcert -CAROOT`, junto da limpeza de `captures/` (`docs/dataset-protocol.md` §9). O humano pode fazer isso mesmo sem a mudança no texto |
| SEC-19-03 | informativa | input | `edge/src/qc_edge/app.py:566` | O Starlette passa para disco um upload acima de 1 MiB. Por isso, uma imagem **recusada** (acima de 1 048 576 bytes, até o limite da requisição) fica durante a requisição num arquivo anônimo (`O_TMPFILE`, `0600`) em `/tmp`. Medi 4 aberturas, uma para cada envio acima desse tamanho que chegou ao parser, e nenhuma com a imagem de exatamente 1 048 576 bytes. Um quadro **aceito** nunca toca o disco fora de `captures/`, então o §4.2 está cumprido. Exige o token, a página não gera quadro desse tamanho, e a `/api/capture` faz o mesmo | Nenhuma |
| SEC-19-04 | informativa | deploy (TLS) | `edge/src/qc_edge/cli.py` (`uvicorn_kwargs`) | Com os padrões do `uvicorn`, TLS 1.0 e 1.1 são recusados, e o navegador negocia TLS 1.3. No TLS 1.2, suítes ECDHE com CBC ainda são aceitas; NULL, MD5, anônimas e troca RSA não negociam. RC4, DES e 3DES também não, mas o cliente de teste nem as oferece, então esses três não provam nada sobre o servidor. Adequado para uma LAN da dupla | Nenhuma |

**Contagem:** bloqueante 0, alta 0, média 1, baixa 1, informativa 2.

### SEC-19-01 em detalhe

**O que medi.** Rodei o processo num namespace de rede só com loopback, então nada podia sair:

| Caso | DNS consultado | Banco local de eventos |
|---|---|---|
| Padrão | `mobile.events.data.microsoft.com` (4 consultas em cerca de 28 s) | criado |
| `ORT_DISABLE_TELEMETRY=1` no ambiente | nenhum | não criado |
| `onnxruntime.disable_telemetry_events()` chamada logo depois de importar | a mesma consulta | criado |

A função da API **não** resolve, pelo menos chamada nesse ponto. Só a variável de ambiente resolveu, e ela precisa estar no ambiente do processo.

**O que não medi.** Não vi um envio acontecer, porque o ensaio não tinha rede, por decisão. Na fila local só restam os 6 eventos das minhas execuções de hoje, e não os dos ensaios anteriores do dia. Isso é coerente com envios já feitos, mas é indício, e não prova. Vi só eventos `ProcessInfo`, em dezenas de inferências, e nenhum por quadro. Não posso garantir que outro tipo de evento não exista em outra situação.

**Por que não trato como R-02.** O título da regra é sobre imagens, o item do checklist é "nenhuma imagem é enviada para fora da LAN", e nada de imagem aparece nos eventos. Mas a regra também diz "só o resultado da inspeção (JSON do contrato) vai para a nuvem", e isso só cobre a telemetria numa leitura literal. **A leitura final é do humano.** Se ele considerar R-02, o achado passa a bloqueante.

**Por que os testes não mostraram isso.** Segundo uma análise externa, não oficial, da versão 1.29 (ver as fontes), a telemetria também é suprimida por uma variável `CI`. O projeto roda com `CI=true`. O resultado do pacote 1.31.0 acima é medição minha.

Fontes: [notas da versão 1.29.0 de um projeto derivado](https://github.com/kibae/onnxruntime-server/releases/tag/v1.29.0), análise de terceiro, sem documentação oficial encontrada; e o binário do pacote instalado, que contém o endereço e o nome `ORT_DISABLE_TELEMETRY`.

## Reaprovações delegadas (checklist §6; ADR-019; ADR-024, resposta 11)

Conferi com `git show` de `77e3e12`, `ddd28a2`, `9183d41`, `f86ce51` e `d76cbc5`, sem partir das conclusões do reviewer.

**Comuns às 01 a 09:**

- **E-1:** 01 a 05 em `f86ce51`; 06 a 09 no adendo `ddd28a2`, anterior à aprovação em `9183d41`, como o Histórico condiciona.
- **E-2:** `77e3e12` tem `Agent: architect` e toca só o arquivo da SPEC.
- **E-3:** SPEC aprovada e `Blocked` desde `d76cbc5`.
- **Depois da aprovação:** `git diff 9183d41..HEAD` da SPEC só muda as linhas de status e de rodada.
- **X-1 a X-4:** nada de SPEC nova, ADR, regra ou contrato. O `docs/architecture.md` (`312e35f`) decorre do §8 e da 11, reaprovada pelo humano.
- **X-9:** ninguém marcou "exige humano", nenhuma depende do professor, e é a primeira correção de cada trecho.
- **CAs de regra inegociável:** CA-07 (R-02) e CA-13 (R-06) **não** aparecem no diff de `77e3e12`.

| ID | Conferência de segurança | Conclusão |
|---|---|---|
| 01 | Só o nome do tipo. Nenhum limite | Dentro |
| 02 | Tira uma emissão: a mesa vazia deixa de gerar inspeção. Mais estrita. CA-15 novo, nenhum caso sai | Dentro |
| 03 | Tira uma emissão: empate não emite. Mais estrita. CA-16 novo | Dentro |
| 04 | Resposta da borda ao celular, fora do contrato. O trecho do sufixo de R-06 não muda, e o código o mantém num `unknown` (no servidor real, `desconhecido (modelo provisório)`). Se alguém ler o "são `desconhecido`" como toque na R-06, a regra fica igual, e a resposta 11 cobre | Dentro |
| 05 | Toca a idempotência só de leitura. Confirmei que a tentativa que falha não grava nada: `SqliteOutbox.put` só lança `SinkError` quando a transação SQLite falha (`edge/src/qc_edge/outbox.py:277-297`), e a foto é apagada (`app.py:668-674`). A R-05 não muda | Dentro |
| **06 (X-6)** | **Autenticação fica mais estrita.** O texto antigo punha o HTML em `static/`, servido sem token, o que contradizia o "sem token → 401". O valor prometido não muda, e o caso de erro continua. Os casos antigos do CA-10 ficam, e entram os headers e o 404. Medido em servidor real: 401 sem token, com token errado e com token de 600 caracteres; `/static/live.html`, caminho com `..` e `%2e%2e` e `/templates/live.html` → 404; headers nas duas respostas; `live.js` sem token. Sem X-5: mesmo arquivo em outra pasta, e o `live.js` já estava em `static/` | **Dentro** |
| **07 (X-7)** | Toca trecho de R-02 e R-14, então só cabe pela **resposta 11 do ADR-024**. Condições: só texto (sem), regra mais rígida (sim, menos imagens em memória), nenhum CA removido (sim), sem escopo novo (sim), SPEC-019 fora da `main` (sim, `origin/main` = `70cc351`). O texto antigo sobre "só em memória" e sobre o descarte continua. O código cumpre: quadros guardados por estado, abaixo. **Pendência:** a condição "o orquestrador avisa o humano" não deixa rastro no Git, então não consigo confirmá-la | **Dentro**, com o aviso a registrar no PR |
| **08 (X-6)** | **Nenhum limite muda:** 1 048 576, 1 310 720 e 1 000 000 são iguais no texto antigo e no novo. O texto antigo já prometia os 1 310 720 bytes, e o código sem o `path_limits` teria 3,5 MiB, então o efeito real é apertar. Os 6 casos antigos do CA-05 ficam, com os mesmos códigos, e entram 2. PNG → 415 restringe a entrada. Medido em servidor real: `Content-Length` 1310721 → 413; blocos acima do limite → 413; imagem de 1048577 → 413, e de 1048576 → 200. Sem desvio pelo caminho: `/api/live%2Fframe` e a query caem no limite; barra no fim → 307 e barra dupla → 404, sem chegar à rota. A captura continua com 3,5 MiB | **Dentro** |
| 09 | Forma de verificação. Os 60 s e o 429 não mudam, e a intenção do CA-08 continua. A inatividade usa o `clock` que já existia | Dentro |

As 10, 11 e 12 foram ao humano. Confiro o registro no Histórico, e não a resposta, que só ele pode confirmar. A 12 foi classificada como elegível e teve o caminho mais rígido. Os itens dela não afrouxam limite: (a) e (b) acrescentam controles, e (f) define "ilegível" sem mudar a regra.

**Conclusão: nenhuma reaprovação fora dos limites, então não há `SPEC_ISSUE` "exige humano".**

**Pendente no PR (orquestrador):** a seção "Reaprovações sob o ADR-019" cita `77e3e12` e `9183d41` e registra o aviso ao humano da 07. É a RV-05 do `r1-review-report.md`, ainda aberta no `r2-review-report.md`. Sem esse aviso, a condição da resposta 11 não se cumpre, e a 07 teria de ir ao humano.

## Decisão local 7 contra a SPEC-025 §4.1

**Conclusão: conforme. Com TLS, o `Host` sem porta só vale na 443, e só para os três nomes de loopback.** O `tls` vem da configuração (`app.py:425`), nunca do cliente. A comparação continua exata, sem `strip`, resolução de nome ou prefixo (`edge/src/qc_edge/security.py:43`). O DNS rebinding continua barrado, porque um nome hostil nunca passa, e com TLS o certificado também não cobriria esse nome. O log de recusa segue sem o valor do `Host`, e as outras duas checagens não mudaram.

Medido com o servidor real, em sockets de verdade, incluindo as portas 80 e 443. `sim` = 200; `não` = 403:

| Servidor | `127.0.0.1`, `localhost`, `[::1]` sem porta | Os mesmos com `:<porta>` | `evil.test`, `evil.test:<porta>`, `localhost.`, `127.0.0.1.nip.io`, `127.0.0.1:1` |
|---|---|---|---|
| HTTPS 443 | sim | sim | não |
| HTTPS 80 | não | sim | não |
| HTTP 80 | sim | sim | não |
| HTTP 443 | não | sim | não |
| HTTPS 18446 | não | sim | não |
| HTTP 18447 | não | sim | não |

**Sem TLS, nada muda:** HTTP 80, HTTP 443 e a porta comum seguem a regra da SPEC-025. `test_spec_025.py` passa sem ajuste.

**Dois desvios da letra da SPEC-025, os dois sem efeito de segurança:**

1. Com TLS na porta 80, o `Host` sem porta é recusado, e a letra o aceitaria com `port == 80`. É mais estrito e correto: o navegador em `https://127.0.0.1:80/` envia a porta (conferido: 200).
2. Com TLS, o texto do 403 diz `https://127.0.0.1`. Continua sem token.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota; comparação em tempo constante | ✅ `/live` e a rota de quadros usam `token_matches` (`compare_digest`). O token é conferido antes de ler o corpo: blocos sem token → 401. Token na query ou no formulário não autoriza o `POST` (401). `/static/live.js` não tem segredo, e a página renderizada não leva o token |
| Entradas: tamanho, tipo real, regex, `extra="forbid"` | ✅ Medido em servidor real: PNG, GIF, SVG, vazio e JPEG cortado → 415; 1001×1000 → 415, e 1000×1000 → 200; cabeçalho declarando 65000×65000 → 415 em menos de 1 s, sem decodificar; `session` curta, com `\n` ou com `../` → 422; `lot_id` com espaço ou HTML → 422; campos demais → 400. `extra="forbid"` continua no contrato, que não muda |
| SQL parametrizado | ✅ N/A em produção: nenhuma consulta nova. As duas únicas no diff são `SELECT` fixos de teste |
| RLS; `DATABASE_URL` e `service_role` | N/A: banco e API fora do diff |
| CORS | ✅ Sem `CORSMiddleware`. Preflight de outra origem → 405, sem `Access-Control-Allow-Origin`. O header do token força o preflight |
| Logs sem segredos e sem imagem | ✅ Sentinelas no token, na `session`, na URL enviada em HTTP puro à porta TLS e no comentário de cada JPEG: nenhum aparece nos logs reais. A linha de sucesso só traz IDs e rótulos validados. PEM inválido → código 1, sem o conteúdo no log |
| Dependências novas | ✅ Nenhuma. SEC-19-01 é de dependência antiga |
| Deploy | N/A: nada de deploy muda. Sem serviço novo nem cartão (R-01) |
| Reaprovação delegada | ✅ Seção acima, com o aviso a registrar no PR |
| **R-02** (tráfego da borda) | ✅ Sem imagem na saída. Num navegador real, todas as requisições da página foram para a própria origem (`live`, `capture.css`, `live.js`, `favicon.ico`, `api/live/frame`). Outbox: 14 campos do contrato, no máximo 430 bytes por linha, e `InspectionCreate` válido. Dos 75 quadros com sentinela, só os 5 emitidos estão em disco, todos em `captures/`. Ver SEC-19-01 sobre a telemetria |
| **R-03** | ✅ Busca no diff sem chave, JWT ou credencial em URL. Nenhum `.pem` ou `.key` versionado por esta SPEC. `edge/data/tls/*.pem` e `rootCA-key.pem` ignorados (`git check-ignore`). `.env.example` só com nomes. Chave: `0644`, `0640`, `0604` e link para `0644` → código 2; `0600`, `0400` e link para `0600` sobem. Diretório e FIFO → código 2, sem travar. Console e `/api/status` não mostram os caminhos |
| **R-06** | ✅ Modelo provisório real: `source = simulated` na resposta e no outbox, e o sufixo no veredito. A visibilidade no overlay foi verificada pelo tester e pelo reviewer |
| **R-14** | ✅ `Sem pessoas no quadro` na página e no README. `captures/` e o dia em `0700`, fotos em `0600`. Quadros guardados na janela (retidos / na janela): `IDLE` 0/0; 5 bons 5/5; mais 1 `unknown` 5/6; depois do `EMIT` 0/10; `WAIT_REMOVAL` 0/10; volta a `IDLE` 0/0; troca de lote 1/1; sessão expirada: nenhuma. Um JPEG enviado direto à rota é gravado como chegou, o que a SPEC-025 §3.2 já prevê para o modo `inspect`; a página reencoda pelo canvas |
| **R-13** | ✅ Uma só identidade, e-mail `noreply`; nenhuma empresa ligada à dupla no diff |

**Página no navegador (TLS real, câmera falsa):** contexto seguro, TLS 1.3, 25 quadros, todos com o token só no header. Nenhum `Referer` em 29 requisições, nenhum cookie, e o `localStorage` só tem o lote. Nenhuma exceção de script. Uma inspeção para uma peça.

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| Nenhuma | — | — | `uv.lock` sem mudança. `mkcert` (BSD-3-Clause, conforme a SPEC) é ferramenta do humano, fora do repositório |

## Como verifiquei

```text
$ uv run pytest (.venv deste worktree, sem o marcador db, com ORT_DISABLE_TELEMETRY=1)
  edge/tests/test_live.py edge/tests/test_live_route.py edge/tests/test_live_config.py
  edge/tests/acceptance/test_spec_019.py test_spec_025.py test_spec_007.py test_spec_041.py
713 passed
$ ruff check edge            All checks passed!
$ ruff format --check edge   84 files already formatted
```

Não rodei a suíte inteira. Desde o commit em que o tester mediu 10165 passed e 166 skipped (`018f64b`), só mudaram o filtro de um teste, relatórios e status. O CI do PR confirma.

**Ensaio, fora da suíte, sem nada versionado.** `qc-edge` real, `~/partqc-provisorio/models/partqc-mnv3-provisional-v1` com inferência ONNX real, outbox real e TLS com um certificado descartável em `127.0.0.1`. Tudo num namespace de rede só com loopback, sem `DEVICE_API_KEY` nem `CLOUD_API_URL`. Com `strace` nas conexões e nas criações de arquivo. Só imagens sintéticas e câmera falsa, sem nenhuma foto. Chrome headless controlado por CDP.

**Limites:**

- **`EMIT` forçado:** os quadros sintéticos só produzem `unknown`, então, para chegar ao `EMIT`, o ensaio troca tipo e grau depois da inferência real. `source`, sufixo, gravação e outbox vêm do código real.
- **Sem celular, Wi-Fi nem `mkcert`:** o navegador usou certificado autoassinado, ignorando a validação. A confiança na CA e a câmera real continuam no §3.3 e no CA-12.
- **Conexões vistas:** além do loopback, só o teste de rota UDP do `netinfo` (`connect`, que não envia pacote), o DNS do nome da máquina no console (código da SPEC-007) e o DNS da telemetria (SEC-19-01).
- **Erros do meu roteiro:** das 92 conferências da primeira passada, 1 falhou por engano meu (conferi headers de página em `/captures`, que é 404). Uma passada da página mostrou 2 inspeções porque duas execuções do roteiro dividiram a mesma pasta; repetida sozinha, deu 1.
- **Telemetria das minhas execuções:** ver SEC-19-01. As primeiras rodadas usaram a pasta pessoal, e deixaram 6 eventos na fila local. Até 3 importações do `onnxruntime` para investigar rodaram fora do namespace, antes de eu saber do comportamento, sem a variável.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
