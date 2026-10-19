# Checklist do reviewer (e do portão de segurança)

Marque cada item como ✅ ok, ❌ achado (com severidade) ou N/A no `review-report`. Itens marcados com **[R-xx]** são regras inegociáveis: ❌ = **bloqueante**.

## 1. Escopo e SPEC

- [ ] O diff implementa **todos** os requisitos e critérios de aceite da SPEC, e nada além do escopo dela.
- [ ] Nenhum critério de aceite foi alterado, removido ou "interpretado" pelo autor. **[R-08]**
- [ ] Há uma linha de rastreabilidade (critério → arquivo/teste) no dev-report.
- [ ] Decisões novas que não estão na SPEC ou nos ADRs foram registradas como `SPEC_ISSUE` ou como proposta de ADR, e não simplesmente embutidas no código.
- [ ] Reaprovação delegada (ADR-019): toda correção de SPEC reaprovada pelo orquestrador nesta branch cumpre E-1 a E-5 e nenhuma exclusão X-1 a X-9 (a X-8 foi removida); conferir o `git show` do commit do architect e a classificação e a linha de aprovação no Histórico. Fora dos limites = `SPEC_ISSUE` "exige humano", que impede o merge até a reaprovação humana; se o conteúdo estiver certo, não pede rodada nova. **[R-08, R-09]**

## 2. Regras inegociáveis

- [ ] Nenhum serviço ou dependência paga, ou que exija cartão. **[R-01]**
- [ ] Nenhuma imagem é enviada para fora da LAN. **[R-02]**
- [ ] Nenhum segredo no diff: busca por `key`, `secret`, `token`, `password`, `postgres://`, `eyJ` (JWT); `.env.example` atualizado se surgiu variável nova. **[R-03]**
- [ ] Formato de payload alterado **só** em `packages/contracts`, com aumento de versão e ADR/SPEC correspondente. **[R-04]**
- [ ] Escritas na API são idempotentes por `inspection_id`. **[R-05]**
- [ ] `source` é respeitado e visível; o simulador sempre usa `simulated`. **[R-06]**
- [ ] O autor não escreveu os testes em `tests/acceptance/`, e o tester não alterou código de produção. Conferir os trailers `Agent:` e os arquivos de cada commit: `git log --format='%h %s%n%(trailers:key=Agent)' main..HEAD` + `git show --stat <hash>`. Commit sem trailer `Agent:` = achado bloqueante. **[R-07]**
- [ ] ML: o split é por `item_id`, o teste não foi usado para escolhas e as métricas batem com os artefatos. **[R-11]**
- [ ] `qc-api` e `qc-dashboard` sem torch, timm ou onnxruntime; Python 3.12; `uv.lock` atualizado se as dependências mudaram. **[R-12]**
- [ ] Commits com a identidade do projeto (CarlosZeyy) e no padrão Conventional Commits. **[R-13]**

## 3. Corretude

- [ ] Casos de borda tratados: vazio, nulo, limites (0, 1, máximo), fuso horário, unicode, imagem corrompida, timeout.
- [ ] Erros retornam o código HTTP correto com `{"detail": ...}`, sem stack trace.
- [ ] Nada de `except Exception: pass`; exceções esperadas são tratadas e as inesperadas são logadas.
- [ ] Concorrência: nenhum I/O bloqueante dentro de handler async; SQLite com uma conexão por thread, ou protegido.
- [ ] Datas sempre com fuso (UTC) no armazenamento e no transporte.

## 4. Testes

- [ ] O test-report é `PASS` e cobre todos os critérios de aceite.
- [ ] Os testes falhariam se a funcionalidade quebrasse (não são tautológicos e não fazem mock do que está sendo testado).
- [ ] Sem dependência de rede externa nos testes (usar `httpx.MockTransport`, um banco de teste ou fixtures).
- [ ] Cobertura mínima nos módulos exigidos pela RNF-09.
- [ ] Ajustes em testes de aceite de SPECs anteriores seguem `docs/architecture.md` §10, "Testes de aceite de SPECs anteriores": cada um está na tabela do test-report, decorre diretamente de um requisito da SPEC nova, mantém a intenção do CA antigo e nenhum `test_caNN_` foi removido. Ajuste fora da tabela é bloqueante.
- [ ] Nenhum teste roda a suíte inteira em subprocesso (`docs/architecture.md` §10). Testes que chamam o pytest em subprocesso passam caminhos explícitos e não usam o `migrated_db` da sessão.
- [ ] Nenhuma credencial fictícia aparece como literal em URL ou conninfo (`postgresql://u:senha@…`, `password=…`): o scanner de segredos do repositório público a marca como vazamento. Monte o valor em tempo de execução.

## 5. Qualidade

- [ ] `ruff check` e `ruff format --check` limpos.
- [ ] Nomes claros, funções pequenas, sem código morto nem `print`.
- [ ] Type hints nas funções públicas.
- [ ] Sem duplicação de lógica que já existe em `qc_contracts` ou `qc_preprocess`.
- [ ] README ou docs atualizados se o modo de rodar mudou.

## 6. Segurança (portão `security`/`deploy`)

- [ ] Autenticação aplicada em toda rota que precisa dela; comparação em tempo constante.
- [ ] Entradas validadas: tamanho do corpo, tipo real da imagem (Pillow), regex de IDs, `extra="forbid"`.
- [ ] SQL **sempre parametrizado**, sem f-string em query.
- [ ] RLS ligado; `DATABASE_URL` e a `service_role` nunca aparecem fora da API.
- [ ] CORS fechado ou mínimo; nenhum `allow_origins=["*"]` com credenciais.
- [ ] Logs sem segredos e sem payloads de imagem.
- [ ] Dependências novas: mantidas, com licença compatível, sem CVE crítica conhecida (`uv pip audit` ou consulta manual).
- [ ] Deploy: variáveis definidas no provedor, health check configurado, plano free sem cartão.
- [ ] Reaprovação delegada (ADR-019), nas SPECs com tag `security` ou `deploy`: toda correção de SPEC reaprovada pelo orquestrador nesta branch cumpre E-1 a E-5 e nenhuma exclusão; em especial, não muda limite de segurança (tamanho, taxa, timeout de produção, permissões, autenticação; X-6) nem trecho ou CA de regra inegociável (X-7). Fora dos limites = `SPEC_ISSUE` "exige humano", que impede o merge até a reaprovação humana. **[R-08, R-09]**
