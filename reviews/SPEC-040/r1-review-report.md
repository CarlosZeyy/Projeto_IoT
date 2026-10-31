# SPEC-040 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-040](../../docs/specs/SPEC-040-manutencao-consolidada.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...7c31940` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante, alto ou médio. Há 5 achados baixos, que não bloqueiam e não pedem rodada nova.

Para o merge (R-09), ainda faltam a seção `## Partes A e B (security-devops)` do `r1-security-report.md` e a decisão sobre o CA-18 manual (ver "Pendências para o portão").

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 (= O-01 do test-report) | baixa | `api/README.md:33` | O README diz que, no aviso `alerts check stopped`, "o lote é o que ficou sem reserva". Isso só vale na primeira verificação. `find_alerts` (`api/src/qc_api/services/alerts.py:359`) não tira da lista os lotes já gravados, e `run_check` confere o envio abandonado (`:597`) antes de `reserve_alert` (`:607`). Numa verificação seguinte, o aviso pode citar um lote que já está em `alerts_sent` com `delivered = false`, como o tester reproduziu. O código cumpre a letra da §4.5 ("não foi reservado nesta verificação"), e nada é reservado nem enviado. Só o texto pode levar o operador a achar que esse lote ainda vai sair. | Decisão sobre a O-01: mudar o texto, sem mudar o código. Por exemplo: "o lote é o primeiro candidato desta verificação, que não foi reservado nela; numa verificação seguinte, ele pode já estar em `alerts_sent`". Cabe na próxima mudança do README. |
| RV-02 | baixa | `dashboard/src/qc_dashboard/api.py:264` | Um `READ_API_KEY` com caractere não ASCII faz o `httpx.Client` levantar `UnicodeEncodeError`, que é um `ValueError`. O `except` converte isso em `InsecureApiUrlError("API_BASE_URL is not a valid URL")`, e a página mostra `INSECURE_API_URL_MESSAGE` (`filters.py:311`). O diagnóstico aponta a variável errada. Reproduzi em `get_client()` com `READ_API_KEY=chavé` e `API_BASE_URL=https://api.example.org`; não rodei a página nesse caso. O código cumpre a letra da §4.4 ("`ValueError` levantado na construção"), a falha é fechada e a chave não aparece. Pelo diff, antes essa exceção não era convertida. | Na próxima manutenção do painel, conferir o formato da chave em `get_settings()`, como o `check_api_key` da borda, com um `ConfigError` próprio que cite só o nome da variável. |
| RV-03 | baixa | `ml/src/qc_ml/report.py:460` | Pendência residual, já apontada pelo ml-engineer. A §4.6 limita a conferência a dois campos, e o código segue esse limite. Só que `model_version` entra direto em `## {version} — ...`, e `model_sha256`, `split_file`, `split_sha256`, `manifest_sha256`, `latency_machine` e os valores não numéricos da tabela também são copiados sem conferência. Uma quebra de linha nesses campos forja linhas pelo mesmo mecanismo do RV-02 da SPEC-037. O risco é pequeno: exige um `metrics.json` adulterado, e a entrada passa por PR. | Registrar no `docs/plan.md` §3 como pendência da SPEC-040, para uma manutenção do ML depois da entrega. |
| RV-04 | baixa | `docs/architecture.md:182`, `docs/dataset-protocol.md:168-169`, `docs/plan.md:145,186-199` | Textos que ficam desatualizados com o merge, fora do que a SPEC pedia. A `architecture.md` ainda diz "na VPS, no `infra/.env.api`", contra o ADR-023. A `dataset-protocol.md` diz "hoje, qualquer `.*.tmp`" e "até o merge da SPEC-040". O `plan.md` ainda trata a SPEC-040 como `Draft` e lista como abertas as pendências que ela fecha. | Correção só de texto pelo architect (`architecture.md` e `dataset-protocol.md`) e pelo orquestrador (`plan.md`), no fechamento da SPEC. |
| RV-05 (= SEC-40-C1) | baixa | `docs/deployment-plan.md:439` | O §7, item 5, manda repetir só o smoke, o CA-16 e o CA-20 da SPEC-039 depois de atualizar o Coolify, sem o CA-18 desta SPEC, que a "Atualização" da §4 e o item 12 da §7 já citam. A §4.10 só pedia a frase da "Atualização", e o autor registrou a escolha. | Acrescentar o CA-18 (passos 1 a 3) a esse item, ou trocar a lista por uma referência à "Atualização", na próxima mudança do plano. |

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | Toda linha "Entra" da tabela da §1 tem implementação. Nenhum CA foi alterado: o diff da SPEC só muda `Status` e `Rodada atual`, sem reaprovação delegada (ADR-019). O RV-03 da 039 é do architect e só vem depois do CA-15 manual da 039, ainda pendente. A rastreabilidade está no dev-report, nas três partes. Os acréscimos fora da letra da SPEC, que os autores registraram (três frases no `ml/README.md`, o passo do `ALERTS_ENABLED=false` no `api/README.md`, a ressalva sobre a `002` no plano), corrigem texto que ficaria errado. Não peço a retirada de nenhum. |
| 2. Regras inegociáveis | ✅ | **R-01:** nenhum serviço novo. **R-02, R-04, R-06:** o diff não toca em payload, contrato nem envio de imagem. **R-03:** a busca por padrões de chave no diff não achou nada; os testes geram os segredos com `secrets`. **R-05:** a resposta recusada mantém o item `pending` (CA-03). **R-07:** todo commit tem `Agent:`; ver abaixo. **R-11:** nenhuma atribuição antiga muda, e o tipo já estendido não volta a ganhar teste (CA-14). **R-12:** `uv.lock` e os `pyproject.toml` intocados. **R-13:** autor e e-mail do projeto em todos os commits, e nenhuma empresa citada no diff. |
| 3. Corretude | ✅ | Ver "O que conferi no código". Achados só de diagnóstico e texto (RV-01, RV-02). |
| 4. Testes | ✅ | Test-report PASS, com todos os CAs automatizáveis cobertos. Contei os testes coletados: 331 (101 `test_ca*`), como o relatório diz. Ver "Testes" abaixo. |
| 5. Qualidade | ✅ | `ruff check` e `ruff format --check` limpos, rodados por mim. Sem código morto. O `print` novo em `report.py` é a saída de erro da CLI, no padrão existente. `_is_plain_encoding` se repete em `publisher.py` e `alerts.py`: são 4 linhas sobre um header HTTP, sem módulo comum entre os pacotes. Aceito. |
| 6. Segurança | ✅ | Parte C: seção `## Parte C (reviewer)` do `r1-security-report.md`, PASS. Partes A e B: com o security-devops. |

## O que conferi no código

- **Publisher e alertas (§4.1, §4.5):** a conferência usa `get_list("content-encoding", split_commas=True)`, com `strip().lower()`, o mesmo modo como o `httpx` escolhe os decodificadores. Por isso, nenhum valor passa pela conferência e depois é decodificado. Ela roda antes de `iter_bytes`. `_read_body` é o único caminho de leitura do lote e do heartbeat, e o `PublishTransientError` não é capturado pelo `except httpx.HTTPError`. `check_health` nunca lê o corpo. Os únicos `httpx.Client` da borda e do Telegram recebem o header. Nem o Caddyfile nem a API comprimem (sem `encode` e sem `GZipMiddleware`), então o Traefik é o único salto que comprime, como diz a §1.
- **Varredura (§4.2):** o erro de listagem usa `exc.filename` relativo a `D`, só o `FileNotFoundError` do próprio `raw/` conta como ausente, e a ordenação vale para todas as linhas. O padrão dos temporários é o da SPEC, com `fullmatch` e `is_jpeg_name`. A saída só mostra caminhos escapados e relativos.
- **Painel (§4.4):** rodei `is_secure_api_url` nas 10 URLs do CA-07 e em mais 21 casos (maiúsculas, `user@`, porta, rótulos `xn--`, IPv6). Nos 21 casos, toda URL aceita também monta a requisição no `ApiClient`. `https://api.example.org x`, com espaço comum, segue aceita e termina em erro de conexão, sem exceção na tela, como o dev-report registrou. A terceira URL do CA-07 tem U+2028, e a quarta, NBSP (conferi os bytes da SPEC). Os dois filtros de texto passam por validação (`valid_lot_id` e `DEVICE_ID_PATTERN` em `historico.py`), então uma entrada do usuário não chega ao `except` de `_get` como erro de URL.
- **Alertas (§4.5):** `_abandoned_for_s` usa o relógio monotônico e o envio vivo mais antigo. O `lot_id` segue `^[A-Za-z0-9_-]{1,40}$`, então o aviso não abre caminho para forjar linhas de log.
- **ML (§4.6, §4.7):** as conferências rodam antes de qualquer linha, sem ecoar os valores. A leitura dos JSONs só acrescenta tipos "não novos" na decisão: não há sorteio novo, e `make_split` não muda. O ADR-022, decisão 5, fica cumprido.

## Testes

- **Suíte inteira:** minha execução deu **1 failed, 9515 passed, 143 skipped**, com banco. A falha, `infra/tests/acceptance/test_spec_032.py::test_extra_smoke_cli_subprocess_refuses_abbreviations`, veio do meu comando, não do código: rodei `.venv/bin/python -m pytest` sem o `.venv/bin` no `PATH`, e o teste chama `python`, que resolveu para o Python do sistema, sem `httpx`. Com o `.venv/bin` no `PATH`, o teste passa, e `uv run pytest` no arquivo dele dá 78 passed, 11 skipped. O teste e o `scripts/smoke_test.py` não estão neste diff. Somando, são 9516, o total do test-report. Não repeti a suíte inteira pelo `uv run`.
- **Não rodei:** os testes `docker`, os do broker MQTT real e o treino com torch. Os números de `docker` (108 passed) e da cobertura (`qc_api.services` 99%) são do test-report.
- **Separação de papéis (R-07):** os arquivos `tests/acceptance/` só mudam em `4f523d1` (`Agent: tester`), e esse commit não toca em produção. Os commits de produção são do developer e do ml-engineer, cada um nos próprios caminhos, e a Parte C é do security-devops. O `docs/architecture.md` é do architect.
- **Aceites antigos (`docs/architecture.md` §10):** conferi o diff de cada arquivo contra as tabelas do test-report. Todas as linhas alteradas estão lá, inclusive a renomeação do `test_extra_ca02_*`, que é um teste extra. Cada ajuste decorre da §4.1, da §4.2 ou da §4.11, e nenhum `test_caNN_` foi removido nem renomeado. As constantes removidas de `test_spec_004.py` e os helpers de `test_spec_015.py` não têm mais uso.
- **Qualidade dos testes:** li os aceites de CA-02, CA-03, CA-08, CA-10, CA-14 e CA-17. Eles exercitam o código real, e só as fronteiras são falsas. O CA-08 troca `is_secure_api_url` de propósito, como a §6 manda. Nas buscas pelo diff, não achei pytest em subprocesso, credencial literal em URL ou conninfo, nem socket fora dos servidores locais; os testes de Telegram usam transporte falso ou redirecionam para `127.0.0.1`. Não repeti as 24 mutações do tester.

## Decisões sobre as observações do test-report

- **O-01:** vira o RV-01.
- **O-02** (`manifest.csv.lock` criado pelo `--fix`): é anterior a esta SPEC. Comparar os bytes de `raw/` é a leitura certa de "nenhum arquivo muda".
- **O-03** (`send_message` sem o filtro mostra o token no log do `httpx`): vem da SPEC-017, e o único chamador é `run_check`, que instala o filtro (`alerts.py:581`) antes de enviar (`:609`). Fica para o security-devops avaliar nas Partes A e B.
- **O-04, O-05 e O-06:** aceito as leituras. A da O-05 é a única que pode ser cumprida, e nenhuma muda o que o CA promete.

## Pendências para o portão (R-09)

- **Seção `## Partes A e B (security-devops)`:** ainda não existe, e o veredicto global do `r1-security-report.md` depende dela.
- **CA-18 manual:** só pode rodar depois do deploy pela `main`, mas a Definição de pronto o lista. O precedente é o da SPEC-038, marcada `Done (CA-18 manual na VPS pendente)`. É o único teste do caminho real: o `identity` pelo proxy da VPS não foi verificado por ninguém. Se o proxy comprimir mesmo assim, a borda para de enviar, sem perder inspeções, e o CA-18 manda voltar a versão dela.
- **Prazo (SPEC §7):** nenhum merge na véspera nem no dia da apresentação.

## Pontos positivos

- A correção das respostas comprimidas fecha os dois lados (pedir `identity` e recusar outra codificação) e falha sem perder inspeções.
- Os autores registraram cada leitura e cada acréscimo no dev-report, inclusive o que o reviewer poderia pedir para retirar.
- O security-devops testou o `identity` num Traefik local e declarou no plano o limite desse teste. As fontes citadas conferem: consultei as duas de novo hoje.
- O tester testou os próprios testes com mutações e separou o que é leitura dele do que está escrito na SPEC.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
