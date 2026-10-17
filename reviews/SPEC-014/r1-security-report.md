# SPEC-014 — r1 — Security report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-014](../../docs/specs/SPEC-014-simulador.md) |
| Rodada | r1 |
| Revisor de segurança | security-devops |
| Diff revisado | `main...9843d7b` |
| **Veredicto** | **PASS** |

Não há achado bloqueante, crítico ou alto. São 4 achados baixos e 3 informativos. Nenhum deles exige uma r2. O T-02/RV-02 (eco do argparse) **não bloqueia**. A mitigação operacional vale desde já, e a correção de código vai para uma SPEC futura (ver "Decisão sobre o T-02").

## Superfície analisada

- **Código:** `scripts/simulate.py` é uma CLI cliente que gera itens e os envia à API.
- **Rotas e entradas externas:**
  - o código não cria nenhuma rota nova;
  - entradas externas: `argv`, as variáveis `CLOUD_API_URL`, `SIM_DEVICE_ID` e `SIM_DEVICE_API_KEY`, e as respostas HTTP da API (health, `BatchResult`, `detail` do 422).
- **Segredo:** a chave do dispositivo `sim-01`. Ela vem de `SIM_DEVICE_API_KEY` ou de `--api-key`, e sai só no header `X-API-Key` do `POST /api/v1/inspections/batch`.
- **Rede:**
  - `httpx` 0.28.1, já presente no `qc-api`; o `uv.lock` não mudou;
  - os padrões foram conferidos na versão instalada: `verify=True` e `follow_redirects=False`;
  - nenhum `verify=`, `follow_redirects=` ou `trust_env=` no código.
- **Documentação e configuração:** `README.md`, `.env.example` (só comentários, e `SIM_DEVICE_API_KEY=` vazio) e `pyproject.toml` (`testpaths`).
- **Deploy:** nenhum. Os testes não usam rede real (`MockTransport` e `TestClient`).

### Verificações feitas (só leitura)

- `uv run pytest -q scripts/tests`: `231 passed, 4 skipped` (os testes `db` são pulados sem `TEST_DATABASE_URL`; o reviewer rodou a suíte completa com banco: `2049 passed`). `ruff check scripts`: limpo.
- Teste exploratório chamando `main(argv)` em processo, com chaves geradas na hora por `secrets.token_urlsafe(32)` (o mesmo formato do `register_device.py`), sem nenhuma chave literal:

| Caso | Código | A chave aparece na saída? |
|---|---|---|
| `--api-keyy <CHAVE>` / `--api-keyy=<CHAVE>` (opção digitada errado) | 2 | **sim**, em `unrecognized arguments` (T-02) |
| `<CHAVE>` solta, sem opção | 2 | **sim** (T-02) |
| `--lots <CHAVE>` / `--seed x<CHAVE>` (valor na opção errada) | 2 | **sim**, em `invalid int value: '…'` (mesma classe do T-02) |
| `--api-key <CHAVE começando com ->` | 2 | não; `expected one argument` (SEC-02) |
| `--api-key=<CHAVE começando com ->` | 0 | não |
| `--api-key` sem valor | 2 | não |
| `--source live` / `--sour=live` | 2 | — (R-06 ok; `allow_abbrev=False`) |
| `http://local\nhost:8001` / `https://exa\x01mple.com` | `httpx.InvalidURL` (código 1 pelo `main` real) | não; a mensagem mostra só a posição (RV-01) |
| `http://localhost.evil.test`, `http://[::1]:8001`, `http://127.0.0.1\@evil.test` | 2 | não; o `https://` obrigatório não é contornado |

## Achados

| ID | Severidade | Categoria | Arquivo:linha | Descrição | Correção exigida |
|---|---|---|---|---|---|
| SEC-01 | baixa | secrets | `scripts/simulate.py:215` | **É o T-02/RV-02.** O argparse repete no stderr os tokens que não reconhece (`unrecognized arguments: --api-keyy <CHAVE>`, ou a chave solta). Também repete o valor inválido de uma opção tipada (`argument --lots: invalid int value: '<CHAVE>'`). Só acontece com erro do operador. O valor sai no stderr do mesmo terminal em que foi digitado, e lá já estava visível e no histórico do shell. O simulador nunca trata esse token como chave e não o registra em log nem em arquivo. O valor de `--api-key`/`SIM_DEVICE_API_KEY` reconhecido nunca aparece (CA-13 e o teste exploratório acima). Os CAs da SPEC e a R-03 continuam atendidos. | **Não bloqueia.** Mitigação operacional desde já (ver abaixo). Correção de código numa SPEC futura: sobrescrever `ArgumentParser.error` (subclasse) para não repetir tokens nos erros `unrecognized arguments` (mostrar a contagem, ou só os nomes de opção cortados no `=`) e `invalid … value` (mostrar só o nome da opção). Incluir um teste com uma chave gerada em tempo de execução nos três formatos da tabela. Só `parse_known_args`, como sugere o RV-02, não cobre o caso `invalid int value`. |
| SEC-02 | baixa | input | `scripts/simulate.py:161-167` e `scripts/register_device.py:58` | Achado novo. A chave vem de `secrets.token_urlsafe(32)`, cujo alfabeto inclui `-`, então cerca de 1 chave em 64 começa com `-`. Com uma chave dessas, `--api-key <CHAVE>` falha (código 2, `argument --api-key: expected one argument`), porque o argparse toma o valor como uma opção. Não há vazamento. `--api-key=<CHAVE>` e a variável de ambiente funcionam. | **Não bloqueia.** A mitigação já é o caminho recomendado: usar a variável de ambiente. Na SPEC futura, uma linha no README e no help (`--api-key=<valor>`) basta. Opcionalmente, o architect avalia se o `register_device.py` deve evitar chaves que começam com `-`. |
| SEC-03 | baixa | input | `scripts/simulate.py:349-365` e `:480` | **É o RV-01/T-01.** Uma URL com caractere de controle gera um traceback e o código 1. O `urlsplit` do Python 3.12 remove `\t`, `\r` e `\n` antes de analisar a URL, então `http://local\nhost:8001` passa pela validação como `localhost`. Mas o `httpx` recusa a URL (`InvalidURL`) **antes** de qualquer conexão. Por isso não há como contornar o `https://` obrigatório, e a mensagem não mostra a URL nem a chave. Os tracebacks do Python não mostram variáveis locais. | **Não bloqueia.** SPEC futura, como sugere o RV-01: só ASCII visível na URL, ou `httpx.URL(url)` validado dentro de `_api_url` com `parser.error`. |
| SEC-04 | baixa | input | `scripts/simulate.py:311-313` | **É o RV-03.** Um número com mais de 4 300 dígitos em `--out-of-control-lots` gera `ValueError`, traceback e código 1. Não expõe nada. | **Não bloqueia.** SPEC futura (`[0-9]{1,4}`). |
| SEC-05 | info | secrets | `scripts/simulate.py:161-167`, `README.md` | Uma chave passada em `--api-key` fica em `/proc/<pid>/cmdline`, onde o `ps` de outros usuários locais a vê (no processo `uv` e no `python` filho), e no histórico do shell. O help e o README avisam e recomendam a variável. Os exemplos do README já usam `uv run --env-file .env`. Com a variável, só o próprio usuário e o root leem o `environ`. | Nenhuma mudança de código. Fica como prática operacional (ver abaixo). |
| SEC-06 | info | input | `scripts/simulate.py:563-572` | O `detail` de um 422 é impresso sem escape no stderr (`ensure_ascii=False`). Uma API comprometida poderia mandar sequências de escape de terminal. O servidor é a própria API, por `https://`, então o risco é desprezível. | Nenhuma. Se a SPEC futura tocar `_detail`, pode filtrar caracteres de controle. |
| SEC-07 | info | deploy | `scripts/simulate.py:77-78` | Uma execução válida pode enviar até 500 × 1 000 = 500 000 itens. Não é uma vulnerabilidade, porque exige a chave do dispositivo. Mas consome a cota do banco free e a janela da API no Render. | Nenhuma mudança de código. Para a SPEC-015: contra produção, só execuções pequenas (o roteiro já prevê `--lots 3`). O `deployment-plan.md` deve registrar isso. |

## Pontos de foco pedidos pelo orquestrador

- **Origem da chave:**
  - vem de `SIM_DEVICE_API_KEY` (padrão) ou de `--api-key`, e o argumento tem precedência;
  - não é lida no `--dry-run`;
  - precisa ser só ASCII visível, e a mensagem de erro não a mostra;
  - `SimConfig.api_key` tem `repr=False`.
- **Onde a chave aparece:**
  - só no header `X-API-Key` do POST de lote;
  - nunca no `GET /health` (não há `headers` no cliente nem no GET) nem na URL;
  - as mensagens de `SendError`/`_BatchError` levam só o tipo da exceção ou o status HTTP;
  - o `logger` próprio recebe só essas mensagens e contagens, e o logger do `httpx` não é configurado para DEBUG.
- **Saída:** o resumo tem só `sent`, `created`, `duplicate`, `lots`, `seed` e `source`. O único eco da chave é o SEC-01 (erro do operador).
- **`argv`/`ps` e histórico do shell:** SEC-05. A variável de ambiente é o caminho recomendado e documentado, e é o que os exemplos do README usam.
- **R-06:**
  - `source=Source.SIMULATED` é fixo em `_item`;
  - não existe `--source`, e `allow_abbrev=False` impede prefixos;
  - todo item passa por `InspectionCreate` e o lote por `BatchCreate`;
  - o resumo imprime `source=simulated`;
  - nenhum caminho do código produz `live` (CA-03 com 1 000 itens, e os testes `db` de ponta a ponta).
- **TLS:**
  - `https://` é obrigatório; `http://` só para `localhost`/`127.0.0.1`;
  - a verificação de certificado é o padrão do httpx (`verify=True`), sem nenhuma desativação;
  - URL com usuário ou senha, query ou fragmento é recusada sem repetir o valor;
  - o caso `\n` no host é recusado pelo httpx antes de conectar (SEC-03).
- **Redirecionamentos:**
  - não são seguidos (`follow_redirects=False` é o padrão no 0.28.1);
  - um 3xx encerra a execução com o código 5;
  - a chave nunca é reenviada a outro host.
- **Novas tentativas:**
  - só depois de erro de rede, timeout ou 5xx;
  - no máximo 3 por bloco, com espera de 2, 4 e 8 s, e envio sequencial (um bloco por vez);
  - quando as tentativas se esgotam, a execução para (código 5), sem passar ao próximo bloco;
  - um 4xx nunca é repetido, e um 401/403 encerra na hora;
  - o health é uma única requisição.
  - Pior caso: 4 POSTs por bloco com falha, depois parada. Não há amplificação de carga.
  - Repetir depois de um timeout é seguro, porque o `inspection_id` é estável e a API responde `duplicate` (R-05).
- **Validação de `--api-url`:** ver a tabela de teste exploratório. Sufixo `localhost.`, IPv6, barra invertida com `@` e userinfo são recusados (código 2). Os caracteres de controle são o SEC-03.

## Decisão sobre o T-02 (RV-02 / SEC-01)

**Não bloqueia e não pede uma r2.** Fica para uma SPEC futura, com mitigação operacional imediata.

**Motivos:**

- Exige erro do operador: opção digitada errado, chave sem opção ou chave na opção errada.
- O valor repetido já está na tela e no histórico do shell de quem o digitou. Portanto, o eco no stderr não expõe nada a mais no uso interativo.
- O valor não vai para o Git, para log ou para arquivo.
- O CI não usa chave real: os testes usam `MockTransport` e chaves geradas na hora.
- O comportamento exigido pela SPEC (§4.3 e CA-13) para o valor de `--api-key`/`SIM_DEVICE_API_KEY` está correto.

**Mitigação operacional (vale a partir de agora; vou registrá-la no `docs/deployment-plan.md` como autor da SPEC-015):**

1. Rodar o simulador sempre com a chave no `.env`, por `uv run --env-file .env --package qc-api python scripts/simulate.py …` (como o README já mostra), e nunca com `--api-key` em demo gravada, terminal projetado, CI ou workflow.
2. Se uma chave aparecer numa gravação, num log compartilhado ou num print, rotacioná-la com `scripts/register_device.py --device-id sim-01 --rotate` e atualizar o `.env`.
3. Se for preciso passar a chave na linha de comando, usar `--api-key=<valor>` (por causa do SEC-02), com um espaço no início do comando para que ele não entre no histórico (`HIST_IGNORE_SPACE` no zsh, `HISTCONTROL=ignorespace` no bash).

**Correção de código (SEC-01 a SEC-04, ou seja, RV-01, RV-02 e RV-03, e a nota do SEC-02):**

- É uma mudança pequena e local em `parse_args`, que é código do `developer`.
- A SPEC-015 **não** cobre `scripts/simulate.py`: a allowlist do `security-devops` (SPEC-001 §4.6) e o escopo da SPEC-015 incluem `scripts/smoke_test.py`, mas não o simulador.
- Há duas saídas, e a escolha é do architect com aprovação humana (R-08):
  - **(a) Recomendada:** uma SPEC curta de manutenção do simulador, com autor `developer` e tag `security`, que entregue os quatro itens antes da demo;
  - **(b)** incluir `scripts/simulate.py` no escopo da SPEC-015, com uma parte de autoria do `developer`, o que complica a separação de papéis numa SPEC cujo portão de segurança já é do reviewer.

## Checklist (seção 6 de [reviews/checklist.md](../checklist.md))

| Item | Resultado |
|---|---|
| Autenticação em toda rota que precisa; comparação em tempo constante | N/A para rotas (é cliente, e nenhuma rota foi criada nem alterada). A chave vai só no header `X-API-Key`, por `https://`, e só para o POST de lote. A comparação é da API (SPEC-004). |
| Entradas validadas (tamanho, tipo de imagem, regex, `extra="forbid"`) | ✅ `re.fullmatch` com `DEVICE_ID_PATTERN`/`MODEL_VERSION_PATTERN` do contrato, faixas numéricas, NaN e infinito recusados, `--start` com fuso e limite de `now + 5 min`, URL e chave validadas sem eco. Os itens passam por `InspectionCreate`/`BatchCreate` (`extra="forbid"` do contrato), e a resposta por `BatchResult` com a contagem conferida. Não há imagem. Lacunas baixas: SEC-03 e SEC-04. |
| SQL sempre parametrizado | N/A. O script não acessa o banco; os testes `db` passam pela API (`TestClient`). |
| RLS; `DATABASE_URL` e `service_role` só na API | N/A. O simulador não lê nenhuma das duas. |
| CORS | N/A. |
| Logs sem segredos e sem imagem | ✅ Mensagens com o tipo da exceção ou o status HTTP; erro interno só com a contagem de erros. A chave não aparece em stdout, stderr nem log (CA-13 e testes extras com `caplog`). O SEC-01 é eco do argparse por erro do operador, não um log. |
| Dependências novas | ✅ Nenhuma. O `uv.lock` não mudou. |
| Deploy (variáveis no provedor, health, free sem cartão) | N/A nesta SPEC. As variáveis estão documentadas por nome no `.env.example`, sem valor (R-03). Nota de operação para a SPEC-015: SEC-07. |
| Segredos no diff (R-03 e regra de chaves literais) | ✅ Nenhuma chave, senha ou token literal no diff. Os testes geram chaves em tempo de execução (por exemplo, `f"https://user:{secret}@…"` com `secret` vindo de `secrets`), e o `.env.example` deixa `SIM_DEVICE_API_KEY=` vazio. |
| Privacidade das imagens (R-02, R-14) | ✅ Só o JSON do contrato sai da máquina, sem nenhuma imagem. |
| R-13 | ✅ Todos os commits estão com a identidade `CarlosZeyy` (noreply) e trazem o trailer `Agent:`. Nenhuma ferramenta ou empresa corporativa é citada. |

## Dependências novas

| Pacote | Versão | Licença | Observação (CVE, manutenção) |
|---|---|---|---|
| — | — | — | Nenhuma. `httpx` 0.28.1 (BSD-3-Clause) já era dependência de runtime do `qc-api`. |

## Declaração

- [x] Não editei código; não sou autor desta SPEC.
