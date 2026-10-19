# Regras do projeto

Este documento vale para humanos e agentes. Em caso de conflito com qualquer outro documento, **este prevalece**, e o conflito deve ser reportado ao humano.

- **Inegociável:** não muda durante o projeto. Se uma regra destas parecer impedir o trabalho, pare e escale para o humano. Não contorne.
- **Negociável:** pode mudar, mas só por meio de um ADR novo ou atualizado (skill `criar-adr`) e com aprovação humana.

---

## Regras inegociáveis

| ID | Regra | Como verificar |
|---|---|---|
| R-01 | **Custo adicional R$ 0.** Só free tiers, software livre e a VPS pessoal já existente do humano (ADR-018), sem nenhum upgrade ou recurso pago por causa do projeto. Nenhum serviço novo que exija cartão de crédito. (Alterada por decisão do humano em 2026-10-18, ADR-018.) | O reviewer confere toda dependência ou serviço novo contra o `docs/deployment-plan.md`; a VPS aparece lá como recurso pessoal preexistente, sem custo para o projeto. |
| R-02 | **Imagens não saem da rede local.** Só o resultado da inspeção (JSON do contrato) vai para a nuvem. As fotos ficam no notebook. | Nenhum endpoint da API aceita imagem; o security-devops revisa o tráfego da borda. |
| R-03 | **Segredos nunca entram no Git.** Toda variável fica documentada em `.env.example`. A chave `service_role` do Supabase existe **só** no servidor da API. | `.gitignore` cobre `.env*` (exceto `.example`); o reviewer roda uma busca por padrões de chave no diff. |
| R-04 | **Contrato primeiro.** Os schemas trocados entre borda, API e dashboard vivem em `packages/contracts`. Qualquer mudança exige ADR (ou atualização de SPEC aprovada) e aumento da versão do pacote. Ver a skill `contrato-api`. | O reviewer recusa um diff que altere o formato de payload fora do pacote. |
| R-05 | **Idempotência.** Toda inspeção tem `inspection_id` (UUID v4) gerado na borda. Reenviar o mesmo ID não duplica o registro. | Teste de aceite obrigatório na API. |
| R-06 | **Dado simulado nunca se passa por real.** Todo registro tem `source` (`live`/`simulated`), e o dashboard mostra isso de forma visível. Por padrão, o SPC usa só `live`. | Teste de aceite no dashboard e na API. |
| R-07 | **Separação de papéis.** Quem implementa não testa (os testes de aceite) nem aprova. O tester não altera código de produção. O reviewer e o security-devops não editam código. Nenhum agente aprova trabalho de que foi autor. | Relatórios em `reviews/SPEC-XXX/`; trailer `Agent: <papel>` em cada commit, cruzado com os arquivos tocados; hook de guarda de caminhos (SPEC-001). |
| R-08 | **Sem SPEC, sem código.** Todo código implementa uma SPEC com status `Ready` aprovada por humano, com critérios de aceite testáveis. | O PR precisa citar a SPEC. |
| R-09 | **Portão de merge na `main`.** Exige todos os checks do PR verdes (ruff + pytest e o scanner de segredos), `test-report` PASS e `review-report` APPROVED da última rodada, `security-report` PASS (quando a SPEC tem a tag `security` ou `deploy`), CAs manuais registrados (quando a Definição de pronto exigir), nenhum `SPEC_ISSUE` aberto e o PR sem conflito com a `main`. O merge é feito pelo orquestrador sob delegação do humano, com merge commit pela conta CarlosZeyy e a conferência registrada no PR; o humano pode vetar a qualquer momento e mantém a aprovação de SPECs e ADRs. PR só de `docs/` exige CI verde e, se trouxer SPEC, ADR ou regra nova ou alterada, aprovação humana do conteúdo. Nunca `--force` nem `--admin`. (Alterada por decisão do humano em 2026-10-17, ADR-016.) | Checklist R-09 e comentário de conferência no PR; `git log --merges` na `main`. |
| R-10 | **Limite do loop.** No máximo 3 rodadas dev → test → review por SPEC. Na 4ª, o orquestrador para e escala para o humano com um resumo do impasse. | Numeração `r1`, `r2`, `r3` dos relatórios. |
| R-11 | **Integridade de ML.** O split é feito por `item_id` (peça física), nunca por foto. O conjunto de teste final não é usado para nenhuma escolha (limiar, época, hiperparâmetro). As métricas são reportadas como foram medidas, sem arredondar para cima nem omitir classes. | Skill `ml-pipeline`; teste que verifica que nenhum `item_id` aparece em dois splits. |
| R-12 | **Dependências separadas e versões fixadas.** `api/` e `dashboard/` nunca dependem de torch, torchvision, timm ou onnxruntime. Python **3.12** em todo o projeto; `uv.lock` versionado. | Teste de CI que inspeciona as dependências resolvidas de `qc-api` e `qc-dashboard`. |
| R-13 | **Identidade do projeto.** Projeto pessoal e acadêmico: commits apenas com a conta GitHub **CarlosZeyy** (identidade configurada localmente no repositório). Nenhum serviço, e-mail, ferramenta ou MCP corporativo, e nenhuma menção a empresas no repositório. | `git log --format='%an <%ae>'`. |
| R-14 | **Privacidade.** Só a área da peça interessa. Fotos com pessoas identificáveis não entram no dataset, e as imagens capturadas ficam localmente (ver R-02). | Protocolo de captura (`docs/dataset-protocol.md`). |

## Regras negociáveis (padrão atual e onde está definido)

| ID | Tema | Padrão atual | Fonte |
|---|---|---|---|
| N-01 | Backbone do modelo | MobileNetV3-Large (timm), com EfficientNet-B0 como alternativa | ADR-004 |
| N-02 | Loss do modelo | Cross-entropy com label smoothing 0,1 nas **duas** cabeças (tipo e grau); CORN como ablação da cabeça de grau | ADR-005 |
| N-03 | Limiares da rubrica de grau | Rubrica v0 em `docs/dataset-protocol.md`, calibrada no piloto | ADR-001 |
| N-04 | Limiares de decisão na borda | Vêm do `decision.json` do modelo, com override por variável de ambiente | SPEC-008 |
| N-05 | Hospedagem | API e dashboard na VPS pessoal do humano (Docker Compose + Caddy, um subdomínio pessoal); banco no Supabase Free; Render como reserva fria da API | ADR-018 (banco: ADR-008) |
| N-06 | Subgrupo do SPC | Lote informado pelo operador; `min_lot_size` = 5 | ADR-013 |
| N-07 | Conteúdo das Fases 2 e 3 | Ver `docs/PRD.md`, seção de escopo | ADR-001 |
| N-08 | Transporte borda → nuvem | HTTP; MQTT opcional na Fase 3 | ADR-009 |
| N-09 | Modo de captura | Foto por disparo; vídeo ao vivo na Fase 3 | ADR-003 |
| N-10 | Visual do dashboard | Streamlit + Plotly; layout livre dentro da SPEC-013 | ADR-007 |
| N-11 | Protocolo de captura | 3 a 5 ângulos por peça por estágio, fundo liso | `docs/dataset-protocol.md` |

## Convenções (obrigatórias, mas de baixo impacto)

- **Idioma:** documentação em PT-BR. Código, identificadores, enums da API, mensagens de log e commits em inglês. A interface mostra rótulos em PT-BR (tabela de tradução em `packages/contracts`). Ver ADR-012.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), com os trailers `Refs: SPEC-004` e, em commits de agentes, `Agent: <papel>`. Nada é commitado direto na `main`.
- **Branches:** `spec/SPEC-XXX-slug-curto`. Documentação pura pode ir em `docs/slug`.
- **Estilo:** `ruff check` e `ruff format`; type hints em funções públicas; nada de `print` em código de produção (use `logging`).
- **Testes:** `pytest`; testes de cada componente em `<componente>/tests/`; testes de aceite do tester em `<componente>/tests/acceptance/`.
- **Datas e horas:** sempre UTC com fuso explícito (`datetime` com tzinfo) no armazenamento e no transporte; conversão para o fuso local só na interface.
