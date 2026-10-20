# SPEC-015 — r2 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-015](../../docs/specs/SPEC-015-deploy.md) |
| Rodada | r2 |
| Tester | tester |
| Commit testado | `cd81b83` (correções em `44c8d87`, `0bc09a6`, `25b36f7` e `ec29293`; relatório do autor em `f52e463`) |
| **Veredicto** | **PASS** (CAs automatizados); CAs manuais continuam pendentes do humano |

O texto da SPEC não mudou desde a r1, e os CAs são os mesmos. Nesta rodada, conferi as correções de RV-01 a RV-04 (que incluem T-01 a T-03 da r1) e de SEC-15-01 a SEC-15-03, repeti os testes que o autor indicou e rodei a suíte completa. No arquivo de aceite `infra/tests/acceptance/test_spec_015.py`, só acrescentei testes extras para as correções e ampliei casos de testes extras existentes. Nenhum `test_caNN_` mudou de intenção ou de asserção, salvo uma verificação a mais no fim do `test_ca36_*`, descrita abaixo. O arquivo agora tem 85 funções e 141 itens: 125 sem Docker e 16 marcados `docker`.

## Confirmação das correções

| Achado | Correção conferida | Como |
|---|---|---|
| RV-01 (cache do `uv` na imagem) | ✅ | Teste novo `test_extra_uv_cache_is_not_in_the_image[api\|dashboard]`: `/home/app/.cache`, `/root/.cache/uv` e `/root/.cache` não existem, não há diretório `archive-v0` do `uv` no sistema de arquivos e `/home/app` tem no máximo 1 MiB. Medição minha num build a partir de `copy_tracked_tree` (tags minhas, já removidas): **API 206 MB** (`.venv` 42 MiB) e **dashboard 671 MB** (`.venv` 518 MiB). Batem com os 205 MB e 670 MB do `deployment-plan.md` §2. |
| RV-02 / T-01 (eco do argparse no smoke) | ✅, com um caso residual (T-04, abaixo) | Testes novos `test_extra_smoke_unknown_arguments_are_never_echoed`, via `main`, e `test_extra_smoke_cli_subprocess_never_echoes`, pelo `python scripts/smoke_test.py` real. São 9 linhas de comando com um valor gerado por `secrets` em tempo de execução: opção de chave inexistente nas formas `=<valor>` e `<valor>`, posicional, posicionais depois das URLs, opção parecida com `--api-url`, opção sem valor e URL de dashboard com o host secreto. Todas saem com código 2, sem o valor nem o host na saída e sem requisição. A senha fictícia do teste antigo de URL com usuário também passou a ser gerada em tempo de execução. |
| RV-03 / T-02 (porta 6543 comparada como texto) | ✅ | `test_extra_port_6543_variants_refused` ganhou 5 casos, todos recusados com código 2, sem a senha na saída e com 0 conexões no listener real da 6543: `:06543`, `port=+6543`, `port=' 06543'`, `PGPORT=06543` e multi-host `:5432,…:006543`. |
| RV-04 / T-03 (`.dockerignore` diferencia maiúsculas) | ✅ | Os sentinelas extras do CA-36 ganharam 13 nomes, e nenhum deles entra nas duas imagens: `FOTO.JPG`, `IMG_0001.HEIC`, `Foto.Png`, `x.Jpeg`, `y.WEBP`, `OUTBOX.SQLITE3`, `local.DB`, `infra/.ENV.API`, `secrets/.Env`, `MODEL.ONNX`, `model.PT`, `server.PEM` e `server.Key`. Um `ml/reports/…/GRADE_CONFUSION.PNG` continua dentro da imagem do dashboard. `test_extra_dockerignore_mandatory_patterns` passou a conferir as variantes com classes de caracteres e que `!ml/reports/…` e `!.env.example` vêm depois de todas as exclusões que eles abrem. |
| SEC-15-01 (saídas com host ou IP) | ✅ (texto) | A §9 do `deployment-plan.md` lista as saídas a editar antes de colar e as que podem ser coladas como saem. Os CAs de texto (CA-25, CA-27, CA-38, CA-41) continuam passando. |
| SEC-15-02 (CA-42 com falso "nenhuma linha") | ✅ | Extraí o comando do CA-42 do `deployment-plan.md` e o rodei, sem alterá-lo, num repositório descartável (já apagado). Usei um `infra/.env` com o valor entre aspas simples, espaço e CRLF, `example.org` e um IP de documentação. O comando achou as duas linhas, e com valores vazios avisou "vazio" sem rodar o `git grep`. |
| SEC-15-03 (`DATABASE_URL` no `.env.prod`) | ✅ (texto) | O item 5 da §8 usa um `.env.dbcheck` temporário, com `chmod 600` e `rm`. O nome é coberto por `.env.*`: o CA-06 testa o padrão, e o `.dockerignore` tem `**/.env*`. |

### Ajuste num teste de CA (sem mudar a intenção)

- `test_ca36_build_context_filters_sentinels`: depois das asserções do CA-36, que não mudaram, acrescentei uma verificação exploratória marcada no código. Ela confere que `ml/reports/partqc-sentinel-v0/GRADE_CONFUSION.PNG` existe na imagem do dashboard, porque a exceção `!ml/reports/**/*.[pP][nN][gG]` é parte da correção do RV-04. As asserções do CA continuam as mesmas.

Nenhum teste de aceite de outra SPEC foi alterado.

## Cobertura dos critérios de aceite

Os testes de CA são os mesmos da r1 (mapa completo em `r1-test-report.md`), e todos passam nesta rodada.

| Critério | Teste de aceite (`infra/tests/acceptance/test_spec_015.py::`) | Resultado r2 |
|---|---|---|
| CA-01, CA-02, CA-05, CA-06, CA-07 | `test_ca01_*`, `test_ca02_*`, `test_ca05_*` (3), `test_ca06_*` (9 itens), `test_ca07_*` | ✅ |
| CA-08 a CA-12 (smoke, repetidos) | `test_ca08_*`, `test_ca09_*` (2), `test_ca10_*` (6), `test_ca11_*` (3), `test_ca12_*` (5 + 1) | ✅ |
| CA-20 (repetido) | `test_ca20_cli_refuses_port_6543` (2), `test_ca20_cli_spec_literal_multi_host`, `test_ca20_functions_raise_before_connecting` | ✅ |
| CA-21 a CA-24 (`db`) | `test_ca21_*` (5), `test_ca22_*` (4), `test_ca23_*`, `test_ca24_*` | ✅ |
| CA-25, CA-27, CA-38, CA-41 (texto do plano, repetidos) | `test_ca25_*`, `test_ca27_*`, `test_ca38_*`, `test_ca41_*` (2) | ✅ |
| CA-28 a CA-32, CA-39 | `test_ca28_*` (3), `test_ca29_*`, `test_ca30_*`, `test_ca31_*`, `test_ca32_*` (4), `test_ca39_*` | ✅ |
| CA-33 a CA-37 (`docker`, repetidos) | `test_ca33_*`, `test_ca34_*`, `test_ca35_*` (2), `test_ca36_*` (2), `test_ca37_*` (3) | ✅ executados |
| CA-13 a CA-19, CA-26, CA-40, CA-42, CA-43 | manuais | ⏳ pendentes do humano |

## Suíte completa

```text
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
220 files already formatted

$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
5029 passed, 52 skipped, 1 warning in 310.71s (0:05:10)
  - 52 skips = 30 testes `docker` (14 do autor + 16 deste arquivo, motivo "set PARTQC_DOCKER_TESTS=1 to run")
    + 22 preexistentes (torch ausente e o CA-16 manual da SPEC-008); o aviso é o StarletteDeprecationWarning
    preexistente

$ PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true TEST_DATABASE_URL=... \
    uv run pytest infra/tests/acceptance/test_spec_015.py -m docker -v
16 passed, 125 deselected in 15.29s

$ PARTQC_DOCKER_TESTS=1 PARTQC_DOCKER_BUILD_NETWORK=host CI=true TEST_DATABASE_URL=... uv run pytest -m docker -q
30 passed, 3 skipped, 5048 deselected, 1 warning in 9.54s
  - o mesmo comando do workflow `docker`; os 3 skips são os módulos de ML sem torch, pulados na coleta
```

Os builds rápidos vêm do cache do BuildKit. O cache é endereçado por conteúdo, então cada imagem reflete os Dockerfiles e os `.dockerignore` desta rodada. A medição de tamanho acima foi um build separado.

- **Só o CI prova:** o build com a rede bridge padrão do runner, sem `PARTQC_DOCKER_BUILD_NETWORK`. Nesta máquina, a rede bridge não funciona sem reboot.
- **Nem o CI prova:** o `compose up` com a rede `partqc`, o DNS interno e o alias do subdomínio. Isso fica para os CAs 13, 17, 40 e 43, na VPS.
- **Limpeza:** as imagens de teste foram removidas pela fixture; as duas imagens de medição (`partqc-tester-*:size`) e a cópia de contexto foram removidas por mim; o repositório descartável do CA-42 foi apagado. Não sobrou nenhuma imagem nova em relação ao início da rodada, e nenhum contêiner de outro projeto foi tocado.

## Bugs encontrados

| ID | Severidade | Critério | Passos para reproduzir | Esperado | Obtido |
|---|---|---|---|---|---|
| T-04 | baixa | §4.5 ("nenhuma chave é impressa"); resíduo do RV-02, fora dos cenários do CA-12 | Gerar um valor (`V=$(python3 -c "import secrets; print(secrets.token_hex(10))")`) e rodar `READ_API_KEY=<valor> SIM_DEVICE_ID=sim-01 SIM_DEVICE_API_KEY=<valor> uv run --package qc-api python scripts/smoke_test.py "--=$V"` | Código 2, sem o valor no stderr, como nos demais erros de uso | Código 2 e `smoke_test.py: error: ambiguous option: --=<valor> could match --help, --api-url, --dashboard-url`, com o valor repetido. A mensagem "ambiguous option" do argparse não põe o valor entre aspas, então o `redact_usage_error` não o pega, e o `parse_known_args` levanta esse erro antes da contagem dos extras. O `scripts/simulate.py` não tem o problema porque cria o parser com `allow_abbrev=False` (com o mesmo comando, ele responde `unrecognized arguments: 1 value(s) (not shown)`). Exige digitar `--=` colado ao valor, por isso a severidade é baixa. Correção sugerida: `allow_abbrev=False` no `NoEchoArgumentParser` do smoke, como no simulador, ou redigir também a mensagem "ambiguous option". O teste automatizado não inclui esse caso, para não reprovar a suíte por um achado fora dos CAs. |

T-01, T-02 e T-03 da r1 estão corrigidos (ver a tabela de confirmação).

## Testes exploratórios (além dos critérios)

- **Smoke, outras formas de erro de uso** (valor gerado em tempo de execução, conferido pelo script real): nenhuma repete o valor.
  - `-<valor>` e `-- <valor>` → `unrecognized arguments: 1 value(s) (not shown)`.
  - `--he=<valor>` → `ignored explicit argument (not shown)`.
  - `--a=<valor>` e `--api-url=<url> --api-url=<valor>` → `invalid --api-url (not shown)`.
  - `--d <valor>` → `unrecognized arguments: 1 value(s) (not shown)`.
  - A única forma que repete o valor é `--=<valor>` (T-04).
- **Executor:** um nome de porta não numérico não é tomado como 6543; o teste do autor cobre isso, e não repeti. As 10 formas de 6543 do teste extra são recusadas antes de conectar.
- **Imagens:** os testes extras da r1 continuam passando nas imagens novas. São eles o endurecimento (UID/GID 10001, `/app` só leitura, `.venv` de dono root, só `.env.example` entre os `.env*`, nenhuma variável de segredo, porta exposta única), a ausência de `*.onnx`/`*.jpg`/`*.sqlite3` e os 14 sentinelas extras da r1, além dos 13 novos.
- **CA-42:** comando executado num repositório descartável (ver SEC-15-02 acima).
- Não repeti a subida manual de API, dashboard e Caddy da r1. As mudanças desta rodada não tocam o `Caddyfile`, o `compose.yaml` nem o código da API e do dashboard. O comando e o healthcheck das imagens não mudaram, e o CA-37 e os testes de imagem os conferem de novo.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Nenhum valor que pareça segredo aparece neste relatório nem nos testes: os valores de exemplo são `<valor>` ou gerados com `secrets` em tempo de execução. O `r1-test-report.md` não foi editado.
