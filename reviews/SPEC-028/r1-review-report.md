# SPEC-028 — r1 — Review report

| Campo | Valor |
|---|---|
| SPEC | [SPEC-028](../../docs/specs/SPEC-028-manutencao-dashboard.md) |
| Rodada | r1 |
| Reviewer | reviewer |
| Diff revisado | `main...7c23456` |
| Test report | r1-test-report.md (PASS) |
| **Veredicto** | **APPROVED** |

Nenhum achado bloqueante ou alto. Há 1 achado médio e 2 baixos, nenhum deles exige mudança nesta rodada. O CA-12 (manual) continua pendente: a Definição de pronto o exige, então ele precisa estar registrado no test-report antes do merge (R-09).

## Achados

| ID | Severidade | Arquivo:linha | Descrição | Sugestão |
|---|---|---|---|---|
| RV-01 | média | `dashboard/tests/acceptance/test_spec_013.py:332` (`_isolated`) e `:1598` (`test_extra_settings_from_environment`) | Desde esta SPEC, o README (§4.6) recomenda um `.streamlit/secrets.toml` na raiz do repositório, que é também a pasta de onde se roda o `uv run pytest`. O fixture `_isolated` da SPEC-013 troca `HOME`, mas não isola o `st.secrets`. **Reproduzi:** com um `.streamlit/secrets.toml` (valores fictícios) no diretório de trabalho, `pytest dashboard/tests` dá 1 falha: `test_extra_settings_from_environment` (`assert 'local-placeholder' == 'k-…'`), porque o `st.secrets` tem precedência sobre o ambiente. O CI não é afetado (lá não existe o arquivo), e os testes do autor e os da SPEC-028 já se isolam. Na máquina da dupla, seguir o README quebra a suíte local. Corrigir isso exige mexer no `_isolated` de `test_spec_013.py`, fora do único ajuste autorizado pela §3.1, e o tester agiu certo ao não mexer (registrou como observação). | Não mudar nesta SPEC. O orquestrador registra a pendência: uma SPEC futura do dashboard (ou um ajuste do architect) autoriza trocar `st.secrets` no `_isolated` de `test_spec_013.py`, como o `NoSecretsFile` do `test_spec_028.py`. Até lá, a dupla roda a suíte local sem o `.streamlit/secrets.toml` na raiz (renomeado ou fora da pasta). |
| RV-02 | baixa | `dashboard/views/controle_estatistico.py:121-128` | O selo é decidido pela origem **pedida** (`source`, antes da leitura), e a legenda final usa a origem **devolvida** (`spc.source`). Hoje a API ecoa o `source` da query, então os dois coincidem. Se um dia divergirem (bug na API), a página mostraria `Origem da carta: simulado` sem o aviso `Contém dados simulados`, contra a R-06. | Defesa em profundidade, numa próxima manutenção: depois da leitura, se `spc.source is Source.SIMULATED` e o selo não foi mostrado, mostrá-lo no `badge_slot` (ou basear o selo também em `spc.source`). |
| RV-03 | baixa | `dashboard/tests/acceptance/test_spec_013.py:1306` | O comentário de `test_extra_retry_while_still_down_is_bounded` ("the st.rerun() after clearing the cache") ficou desatualizado com a §4.2. A asserção (`<= 2` tentativas) continua válida, e o dev-report já apontou isso. Mudar esse comentário ficaria fora do ajuste autorizado pela §3.1. | Junto com o RV-01, na mesma pendência de `test_spec_013.py`. |

### Ajuste no teste de aceite da SPEC-013 (conferido)

Conferido contra `docs/architecture.md` §10 ("Testes de aceite de SPECs anteriores") e a SPEC-028 §3.1, item 1, no diff de `39669ca` (`Agent: tester`, um único arquivo, 7 linhas a mais e 2 a menos):

- **Asserção:** para `SPC_PAGE`, `assert not contains(values(at.main.warning), BADGE)` e `assert "Origem da carta: real" in values(at.main.caption)`. Para `HISTORY` e `MODEL_PAGE`, a asserção original continua sem mudança. É exatamente o que a §3.1, item 1, prescreve, e a mudança decorre da §4.3 e do CA-04 (a). A intenção do passo (R-06: com `Todos`, toda página que pode mostrar dado simulado avisa) continua verificada nas outras duas páginas. Na página da carta, a carta é `Real`, e o passo verifica a origem visível.
- **Comentário do laço:** a linha `# Step 3: with 'Todos', the badge is on every page.` virou um comentário de 2 linhas que cita a exceção da carta. Esse comentário faz parte do próprio laço "Step 3" que a §3.1 autoriza ajustar, não muda nenhuma asserção nem a intenção do teste, e está na tabela do test-report com o requisito (§4.3). Mantê-lo teria deixado o comentário contradizendo a asserção. **Aceito, sem achado.**
- Nenhuma outra linha do arquivo mudou (`git diff main...HEAD -- dashboard/tests/acceptance/test_spec_013.py`: um só hunk, nas linhas 1754 a 1771). Nenhum `test_caNN_` foi alterado, renomeado ou removido. O teste passa com `CI=true` e `TEST_DATABASE_URL`.

## Checklist ([reviews/checklist.md](../checklist.md))

| Seção | Resultado | Observação |
|---|---|---|
| 1. Escopo e SPEC | ✅ | As seções §4.1 a §4.6 estão implementadas, e os CA-01 a CA-11 têm um teste de aceite cada; o CA-12 é manual e está pendente (DoD). A rastreabilidade está no dev-report. Nada fora do escopo: `.gitignore` já tinha `.streamlit/secrets.toml` (linha 18), sem mudança; o diff não toca `packages/contracts`, API nem `uv.lock`. As decisões do dev-report (mensagens separadas, `ValueError` do `urlsplit` tratado como URL recusada, legenda num `st.empty()` antes e depois da leitura, `PLOTLY_CONFIG`, `display_path`, a ordem do `report_image` e o fixture do autor) cabem no texto da SPEC e não mudam nenhum CA. Nenhum SPEC_ISSUE. |
| 2. Regras inegociáveis | ✅ | R-01/R-12: nenhuma dependência nova, e `pyproject.toml` e `uv.lock` intocados. R-02/R-04/R-05: N/A, sem mudança de payload. R-03: a busca por padrões de chave no diff não achou nada; as chaves dos testes vêm de `secrets.token_*`; o exemplo de `secrets.toml` do README tem `READ_API_KEY = ""`; `.env.example` foi atualizado (§4.6). R-06: o selo da carta segue a origem da carta, e "Sobre o modelo" mostra o selo, por conservadorismo, quando a checagem falha. R-07: commits `95177e6`, `0813f47`, `879dd0d`, `9cdd4dd`, `2ad0de7` e `1881ec2` com `Agent: developer`, só em `dashboard/src`, `dashboard/views`, `dashboard/tests` (fora de `acceptance/`), README, `.env.example` e o dev-report. `39669ca` e `2dcb046` com `Agent: tester`, só em `dashboard/tests/acceptance/` e no test-report. `1a70772`, `882e80f` e `7c23456` com `Agent: orchestrator`, só em status de SPEC e `docs/plan.md`. Todos os commits têm trailer. O fixture autouse do `dashboard/tests/conftest.py` (do autor) se desliga dentro de `acceptance/`. R-11: a exibição nunca fica a favor da meta, e o status usa o valor bruto. R-13: autor `CarlosZeyy` (noreply) e Conventional Commits. |
| 3. Corretude | ✅ | `is_secure_api_url`: o `urlsplit` devolve esquema e `hostname` em minúsculas; userinfo (`http://localhost:8001@example.org`), sufixo (`localhost.example.org`), `[::1]`, `0.0.0.0`, URL malformada e ausência de host são recusados, e a mensagem cita só o nome da variável. O retry chama só `st.rerun()`, e como os erros não são cacheados, o laço continua limitado. A legenda da carta continua visível quando a API falha. `render_badge_or_error` não chama `st.stop()`, e os erros de arquivo ausente ou inválido continuam parando a página (§7). Na regra de exibição, `LOWER_IS_BETTER` bate com a lista da §7 da arquitetura; o IC tem `low` com FLOOR e `high` com CEILING; a tabela por grau usa FLOOR (precisão, recall e F1); `support`, itens e `latency_runs` são inteiros. `report_image`: `fullmatch` mais a recusa de nomes só com pontos, depois `resolve().is_relative_to(reports.resolve())`, o que bloqueia link de diretório e de arquivo para fora. `display_path` mostra o relativo quando o caminho resolvido fica dentro de `REPO_ROOT.resolve()` e o configurado quando fica fora, como a §4.4 manda. Ver o RV-02 (baixa). |
| 4. Testes | ✅ | Test-report PASS. Cada CA automatizável tem um teste que o exercita de fato: no CA-01, o `get_client` é o real e `httpx.HTTPTransport.handle_request` é interceptado, então o teste falharia se a checagem saísse do `get_settings`; o CA-07 tem um espião em `st.cache_data.clear` e conta as requisições por rota; o CA-08 usa 257 lotes; o CA-10 usa um symlink real em `tmp_path`. Nenhum teste usa a rede. Nenhuma credencial literal em URL. O ajuste em teste antigo está na tabela e foi conferido acima. Ver o RV-01 (média) e o RV-03 (baixa). |
| 5. Qualidade | ✅ | `uv run ruff check .`: All checks passed. `uv run ruff format --check .`: 149 files already formatted. Há type hints nas funções públicas novas, nenhum `print` e nenhuma duplicação de `qc_contracts`: os rótulos vêm de `SOURCE_LABELS_PT` e a validação de versão de `MODEL_VERSION_PATTERN`. O README do dashboard foi atualizado (https, secrets local, retry, `max_entries`, selo da carta e "Sobre o modelo" sem a API). |
| 6. Segurança | N/A (portão do `security-devops`) | A SPEC tem a tag `security`, e o autor da implementação é o `developer`: o `security-report` cabe ao `security-devops`. Do lado da revisão: os itens SEC-13-01, 02, 03, 04, 05 e 08 estão implementados como a SPEC pede. |

### Verificação executada

```text
$ CI=true TEST_DATABASE_URL=postgresql://postgres@localhost:55432/partqc_test uv run pytest -q
3855 passed, 1 warning in 234.72s
$ uv run ruff check . && uv run ruff format --check .
All checks passed!
149 files already formatted
# reprodução do RV-01 (a partir de um diretório temporário fora do repositório, com
# .streamlit/secrets.toml fictício; nenhum arquivo do repositório foi tocado):
$ uv run --project <repo> pytest -q <repo>/dashboard/tests
1 failed, 387 passed, 1 skipped   # test_spec_013.py::test_extra_settings_from_environment
```

## Pontos positivos

- A checagem do esquema ficou em `get_settings()`, como a SPEC pede, e o teste de aceite do CA-01 a exercita pelo caminho real (`get_client` → `get_settings`), interceptando o transporte, em vez de mockar a fábrica.
- A legenda `Origem da carta` está num `st.empty()` logo abaixo do título, é escrita antes da leitura e reescrita com `spc.source`, e continua visível quando a API falha.
- `report_image` recusa também um link simbólico de **arquivo** para fora de `ml/reports/`, além do link de diretório do CA-10.
- O autor isolou os próprios testes do `.streamlit/secrets.toml` local sem tocar o ambiente de `tests/acceptance/`, e listou no dev-report o teste antigo que a SPEC invalida, sem editá-lo.

## SPEC_ISSUE (se houver)

Nenhum.

## Declaração

- [x] Não editei código nem testes; só escrevi este relatório.
- [x] Não sou autor de nenhum commit desta SPEC.
