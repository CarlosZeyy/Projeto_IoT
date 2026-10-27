# SPEC-038 — r1 — Test report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-038](../../docs/specs/SPEC-038-manutencao-borda-deploy.md) |
| Rodada | r1 (Parte A do developer, `c1317fb` e `e0f1090`; Parte B do security-devops, `e601f98` e `bc9df6f`), com a correção do SPEC_ISSUE-038-B1 (`3631c81`, reaprovada pelo humano em 2026-10-26) |
| Tester | tester |
| Commit testado | `34a1efe` |
| **Veredicto** | **PASS** |

Escrevi os testes a partir da SPEC (critérios de aceite, §4 e nota do topo) antes de ler a implementação. Depois li o código para os exploratórios. A Parte B segue a nota do topo (ADR-023): site `:80`, imagem de `infra/docker/caddy.Dockerfile` e opções do CA-12 da SPEC-039.

## Cobertura dos critérios de aceite

Arquivos: `edge/tests/acceptance/test_spec_038.py` (70 testes, CA-01 a CA-11 e extras) e `infra/tests/acceptance/test_spec_038.py` (79 testes, dos quais 13 `docker`, CA-12 a CA-17 e extras).

| Critério | Teste de aceite | Resultado |
|---|---|---|
| CA-01 | `edge/.../test_spec_038.py::test_ca01_listing_skips_the_invalid_row_without_echo` (5 casos: `created_at`, `attempts` e `inspection_id` com `M`; `created_at` BLOB; `last_error` BLOB). Confere também o texto fixo do aviso da §4.1 | ✅ |
| CA-02 | `::test_ca02_requeue_and_loop_never_stop_on_an_invalid_row` | ✅ |
| CA-03 | `::test_ca03_invalid_pending_row_goes_dead_and_the_other_is_sent` (casos a, b, c; reenvio em a e b) | ✅ |
| CA-04 | `::test_ca04_value_and_type_errors_exit_1_without_message_or_traceback` (`dead_items` → `ValueError`; `requeue_dead` → `TypeError`) | ✅ |
| CA-05 | `::test_ca05_unreadable_file_is_not_called_not_an_outbox` (com e sem `--yes`); `::test_ca05_files_that_are_not_an_outbox_keep_their_message` (4096 × `b"x"` e tabela `other`, com e sem `--yes`) | ✅ |
| CA-06 | `::test_ca06_png_with_comment_is_imported_without_it` (`tEXt`, `zTXt`, `iTXt`; a fixture confere o chunk e o `info["comment"]`) | ✅ |
| CA-07 | `::test_ca07_pil_logger_never_shows_exif_tags` (premissa conferida: com o `PIL` em DEBUG, `exif_orientation` registra `M1`); `::test_ca07_a_higher_pil_level_is_not_lowered` | ✅ |
| CA-08 | `::test_ca08_rollback_removes_the_directories_of_the_row` (a `sources.csv`, b `manifest.csv`, c imagem); `::test_ca08_directory_that_existed_stays` | ✅ (ver O-01) |
| CA-09 | `::test_ca09_two_runs_of_the_same_plan_store_the_photo_once`; `::test_ca09_a_hash_excluded_meanwhile_is_imported_again` (com `load_plan`/`run_import` diretos) | ✅ |
| CA-10 | `::test_ca10_inbox_or_plan_inside_a_git_repository_is_refused` (casos a–e × `.git` diretório e arquivo = 10); `::test_ca10_inbox_and_plan_outside_the_repository_are_accepted` (2) | ✅ |
| CA-11 | `::test_ca11_readme_sections` | ✅ |
| CA-12 | `infra/.../test_spec_038.py::test_ca12_previous_caddyfile_conditions_still_hold` (chama o CA-30 da SPEC-015, o CA-04 da SPEC-032 e o CA-04 da SPEC-039), `::test_ca12_one_handle_errors_without_argument_inside_the_site`, `::test_ca12_handle_errors_has_the_six_header_lines`, `::test_ca12_handle_errors_never_forwards_or_renders` (4), `::test_ca12_handle_errors_uses_no_err_placeholder_but_the_status_code`, `::test_ca12_site_header_block_outside_handle_errors_has_the_six_lines`, `::test_ca12_no_environment_placeholder_in_the_whole_file` e o controle negativo `::test_ca12_control_the_placeholder_check_detects_a_planted_line` (5 linhas plantadas numa cópia em memória, acusadas; a mesma linha comentada, não) | ✅ |
| CA-13 (docker) | `::test_ca13_caddy_adapt_puts_the_headers_in_the_error_routes` | ✅ |
| CA-14 (docker) | `::test_ca14_502_from_caddy_has_the_headers_and_an_empty_body` | ✅ (ver O-02) |
| CA-15 | `::test_ca15_gitignore_ignores_the_new_formats` (18), `::test_ca15_gitignore_keeps` (8), `::test_ca15_lines_of_the_start_of_the_round_kept_in_order` (cópia literal do `.gitignore` de `e601f98^`), `::test_ca15_no_tracked_file_is_ignored` | ✅ |
| CA-16 | `::test_ca16_dockerignore_has_the_nine_lines_before_the_exception` (api, dashboard); *(docker)* `::test_ca16_sentinels_never_reach_the_images` (as 9 sentinelas do CA na raiz do contexto e mais 4 em pastas copiadas, com controle positivo `pyproject.toml`) e `::test_ca16_ca36_of_spec_015_still_holds` | ✅ |
| CA-17 | `::test_ca17_env_example_warns_against_zero_or_minus_one`, `::test_ca17_deployment_plan` | ✅ |
| CA-18 (manual, VPS) | Não automatizável. Os passos estão em `docs/deployment-plan.md` §9, "CA manual da SPEC-038" | ⏳ pendente (humano, depois do merge e da atualização na VPS) |

## Suíte completa

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
8213 passed, 136 skipped, 1 warning in 759.74s (0:12:39)
(warning preexistente do fastapi.testclient; os 136 pulados são os docker e os de torch)

$ env -u TEST_DATABASE_URL -u CI PARTQC_DOCKER_TESTS=1 uv run pytest -q -m docker
108 passed, 5 skipped (torch), 8236 deselected in 219.86s

$ uv run pytest -q edge/tests/test_outbox.py edge/tests/test_requeue.py \
    edge/tests/acceptance/test_spec_{009,034,038}.py --cov=qc_edge.outbox --cov=qc_edge.requeue
355 passed; qc_edge/outbox.py 99%, qc_edge/requeue.py 98%   (RNF-09: ≥ 80%)

$ uv run ruff check .          -> All checks passed!
$ uv run ruff format --check . -> 273 files already formatted
```

Limpeza do Docker: a lista de contêineres, redes, imagens e volumes antes e depois de todas as execuções `docker` é idêntica. Meus contêineres usam `partqc-test-acc038-*` e `--network none`, e o `build_image` remove as imagens no fim da sessão. A árvore de trabalho só tem os 4 arquivos deste commit.

## Testes de aceite de SPECs anteriores ajustados (`docs/architecture.md` §10)

Os dois primeiros estão na §3.1 da SPEC. Os dois últimos entram pela nota do topo ("vale a mesma regra para um teste de aceite da SPEC-039 que a §4.9 invalide"). Nenhuma outra linha desses arquivos mudou, e nenhum teste foi renomeado ou removido.

| Arquivo | Teste | Antes → depois | Requisito |
|---|---|---|---|
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_caddyfile_headers_are_in_one_header_block_and_no_full_csp` | 1 bloco `header` no texto todo, com as 6 linhas; `Content-Security-Policy` 1 vez → 1 bloco `header` fora do `handle_errors` e 1 dentro dele, cada um com as 6 linhas; `Content-Security-Policy` 2 vezes. O resto não mudou (sem CSP completa; nenhum `header` dentro do `handle /api/*`) | SPEC-038 §4.9 e a tabela da §3.1 |
| `infra/tests/acceptance/test_spec_032.py` | `test_extra_caddy_adapt_single_header_handler_is_deferred` (docker) | 1 handler `headers` em todo o JSON → 1 handler `headers` nas `routes` dos servidores, adiado (`deferred: true`); os handlers de `errors` ficam fora da contagem | SPEC-038 §4.9 e a tabela da §3.1 |
| `infra/tests/acceptance/test_spec_039.py` | `test_extra_caddyfile_comments_and_format` | `assert "handle_errors" not in _caddy_text()` → exatamente 1 bloco `handle_errors {` no texto sem comentários. A contagem de 1 bloco `header` no `:80` passa a ser feita no site sem o corpo do `handle_errors`. Comentários (Coolify, ADR-023, SPEC-038, `handle_errors`) e o formato (tabs, sem espaço no fim) continuam iguais | SPEC-038 §4.9 (nota do topo: `handle_errors` no site `:80`) |
| `infra/tests/acceptance/test_spec_039.py` | `test_extra_caddy_adapt_has_no_automatic_https_and_no_redirect` (docker) | `static_response` == [] e 1 `headers` adiado, contados no JSON inteiro → contados só nas `routes` do servidor. Para manter a intenção ("nenhum redirecionamento"), todo `static_response` de `errors` também é conferido: sem status 3xx e sem `Location`. O resto (`automatic_https`, `tls_connection_policies` e `https://` ausentes) não mudou | SPEC-038 §4.9 (o `respond` do `handle_errors` vira um `static_response` em `errors`); nota do topo |

## Bugs encontrados

Nenhum.

## Observações (não bloqueiam)

- **O-01 (CA-08 caso c, espião da imagem).** A imagem é gravada por um objeto de arquivo com buffer (`os.fdopen(...).write`, em `write_private_file_atomically`). Os bytes dela não passam pelo `os.write`, que é o espião do CA-09 da SPEC-036. No meu primeiro teste, o espião não viu a escrita (`hits == []`). Por isso o espião do CA-08 também faz o `os.fsync` de um arquivo regular que casa com o alvo levantar `ENOSPC`, porque é ali que um disco cheio aparece numa escrita com buffer. Diretórios nunca casam. O teste confere que o espião disparou (`hits` não vazio) nos 3 casos. O efeito é uma falha de E/S na escrita da imagem (passo 4), como pede o CA.
- **O-02 (CA-14, cliente HTTP).** Um cliente que fecha a escrita logo depois de enviar a requisição (`printf ... | nc`) recebe `499` em vez do `502`, de forma intermitente: o servidor do Go vê o EOF e cancela a requisição antes de o `reverse_proxy` falhar. Mesmo nesse caso, a resposta tem os 4 headers, não tem `Server` e tem corpo vazio, ou seja, o `handle_errors` vale. Isso é do cliente, não do Caddyfile: o proxy do Coolify não fecha a escrita. O cliente do teste mantém a conexão aberta até chegarem os headers (`mkfifo` + busybox `nc`, dentro do contêiner), e assim o `502` sai sempre.
- **O-03 (§4.4, logger filho).** O `limit_pil_logging()` sobe só o logger `PIL`, como a §4.4 manda. Com o `PIL.TiffImagePlugin` em `DEBUG` explícito (só por configuração manual, porque nenhuma CLI do projeto faz isso), `python -m qc_edge.privacy` ainda registra o `Make` (conferido num script fora do repositório). Fica fora do texto da SPEC. Registro como informativo para o portão de segurança.
- **Nota do dev-report.** Concordo com a observação do developer sobre um `inspection_id` válido para o `uuid.UUID` mas fora da forma canônica (maiúsculas ou chaves): pela §4.1, ele é válido. Não testei além disso.

## Testes exploratórios (além dos critérios)

Todos automatizados nos dois arquivos (`test_extra_*`), passando, exceto quando indicado.

**Parte A, outbox e CLI de reenvio (security):**

- Linha `dead` adulterada com controles e bidi (`\x1b[31m…‮\n`), `inspection_id` de 80 mil caracteres, `attempts` REAL (3.5) e `created_at` que estoura na conversão para UTC (`0001-01-01T00:00:00+05:00`). Em todos os casos, a linha é pulada com um único aviso de texto fixo, e o marcador, o ESC e o U+202E não aparecem no stdout, no stderr nem no log, sem traceback.
- Afinidade do SQLite (§7): `attempts = "7"` vira `7` e a linha continua válida; `last_error` NULL é válido, e `12345` em `last_error` é guardado como texto e é válido. Nenhum aviso.
- Linha inválida no meio de um lote de 5: os outros 4 sobem no mesmo ciclo, e ela vira `dead`.
- `python -m qc_edge.requeue` num processo real com uma linha inválida: sai com 0, o aviso vai para o stderr, sem traceback e sem o marcador.
- Diretório como `--outbox-path`: código 2, nada criado dentro dele, sem traceback.
- Diretório só de leitura, sem o `-shm`: código 2 com `cannot open --outbox-path (OperationalError)`, nunca `not an outbox file` (o caso que a §4.2 cita). Com e sem `--yes` (script fora do repositório).

**Parte A, importação (security):**

- PNG com outros chunks de texto (`Comment`, `Author`, `Description`, `GPS`, `XML:com.adobe.xmp`, em `tEXt` e `iTXt`) e PNG com chunk `eXIf` (`Make` com o marcador): importados sem o marcador e com `jpeg_private_findings` vazio. JPEG de entrada com segmento COM: sai sem ele.
- Rollback com `DATASET_DIR` inexistente e falha na imagem da primeira linha: `raw/` não fica. Falha no `manifest.csv` seguida de nova execução: importa normalmente.
- `exclusions.csv` com outro cabeçalho criado entre a fase 1 e a fase 2 (sob o lock): código 1, nada gravado (§4.6).
- **Dupla importação concorrente real:** 3 processos `python -m qc_edge.importer` iniciados juntos com o mesmo plano. Os 3 saem com 0, um com `imported 1` e dois com `skipped 1`, e ficam 1 linha no manifest, 1 no `sources.csv` e 1 arquivo.
- **Repositório Git real (worktree, `.git` arquivo):** `--inbox` = `edge/tests/acceptance` desta worktree é recusado com 2, sem `DATASET_DIR` e com o `git status` igual. `--plan` = `ml/external_sources.csv` é recusado com 2, e o arquivo continua com os mesmos bytes.
- Variantes do `.git`: link simbólico pendurado, `.git` na própria pasta de entrada e `.git` como link para um diretório. Todas recusadas.
- Ordem da §4.7: a pasta de entrada dentro do dataset é acusada antes do repositório Git, e a pasta de entrada antes do plano. `--dataset-dir` e `--external-sources` dentro de um repositório são aceitos.

**Parte B (security):**

- 502 do Caddy sem API e sem dashboard para `/api/v1/inspections?limit=1`, `/_stcore/health`, outro `Host` (`outro.example.org`) e `Host: 127.0.0.1`: sempre os 4 headers, sem `Server`/`Via`, corpo vazio, nenhum header duplicado. A resposta inteira não contém `dial tcp`, `lookup`, `api:8000`, `dashboard:8501` nem `caddy`. `HEAD` também dá 502 sem `Server`. Com 15 erros seguidos, o contêiner continua `running` e sem `panic` no log.
- Controle negativo do CA-14: o mesmo Caddyfile sem o bloco `handle_errors` (cópia temporária montada só de leitura) devolve o 502 com `Server` e sem HSTS. Isso prova que o teste distingue os dois casos.
- `caddy fmt /etc/caddy/Caddyfile` na imagem gera exatamente os bytes do arquivo.
- Nenhum `{env.`/`{$` no texto sem comentários (CA-12). O detector acusa as 5 formas plantadas (`respond`, `header`, `{$VAR:padrao}`, entre aspas e entre crases) e ignora a mesma linha comentada.
- `.gitignore`: as 9 linhas aparecem só na forma com classes, uma vez cada, no grupo "Dados e imagens" e antes de `!docs/**/*.png`, sem forma literal. Outras grafias ignoradas (`x.HeIf`, `a/b/c/d/e.mP4`, `IMG.DnG`, `x.TiFf`, `y.JfIf`, `deep/z.AvIf`, `docs/img/a.mov`). Sem excesso: `x.mp3`, `x.heifx`, `a.tiffany`, `movie.txt`, `docs/img/a.png` e `x.mpeg` não são ignorados.
- `.dockerignore` da API e do dashboard: cada regra do início da rodada (copiada literalmente) continua presente e na mesma ordem. As únicas regras novas são as 9 com `**/`, logo depois de `**/*.[wW][eE][bB][pP]`. O do Caddy continua `*` e `!infra/Caddyfile`.
- **Aviso do `pids_limit` (SEC-32-03):** com `pids_limit: "${P:-256}"`, o `docker compose config` resolve `P=0` sem o campo e `P=-1` como `-1`, os dois sem aviso. Isso confirma o texto da §4.11 no `.env.example` e no plano. Também conferi o texto exato da §4.11 no `.env.example` e o texto do risco no plano conforme a nota do topo (redirecionamento e erros do proxy do Coolify).

## SPEC_ISSUE

Nenhum. O SPEC_ISSUE-038-B1 já foi resolvido (`3631c81`, reaprovado pelo humano) e está coberto pelo CA-12.

## Pendências

- **CA-18 (manual, VPS):** pendente. Fica com o humano, depois do merge e da atualização na VPS (passos em `docs/deployment-plan.md` §9).

## Declaração

- [x] Não alterei código de produção, só arquivos em `*/tests/acceptance/` e este relatório.
- [x] Nenhuma imagem real (todas geradas pelo Pillow), nada lido de `~/partqc-entrada/`, nenhum valor com cara de segredo (marcadores gerados com `secrets`; host `partqc.example.org`).
