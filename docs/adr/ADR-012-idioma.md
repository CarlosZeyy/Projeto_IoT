# ADR-012: Escrever a documentação em PT-BR e o código em inglês, com rótulos PT-BR na interface

| Campo | Valor |
|---|---|
| Status | Aceito |
| Data | 2026-10-12 |
| Decisores | Dupla (redigido pelo agente architect) |
| Relacionados | ADR-007, ADR-015, SPEC-002, SPEC-007, SPEC-013, R-04 |

## Contexto

O projeto é avaliado num curso brasileiro: o relatório, os slides e a documentação são lidos pelo professor em português. O código, porém, usa bibliotecas, mensagens de erro e exemplos em inglês, e os enums trafegam no contrato JSON entre borda, API e dashboard (R-04). Misturar idiomas dentro do código (por exemplo `grau = "ruim"` num lugar e `grade = "poor"` em outro) gera erros de comparação e traduções duplicadas.

## Opções consideradas

| Opção | Prós | Contras |
|---|---|---|
| A (escolhida) Documentação em PT-BR; código, identificadores, enums, logs e commits em inglês; interface com rótulos PT-BR vindos de uma tabela única em `qc_contracts.labels` | O contrato é estável e sem acentos; uma só fonte de tradução; documentação natural para o avaliador | Dois idiomas no repositório; cuidado ao citar enums no texto em português |
| B Tudo em português, incluindo o código e os enums | Uniforme para a dupla | Acentos em identificadores e JSON; destoa das bibliotecas; enums como `inutilizável` são frágeis |
| C Tudo em inglês, incluindo a documentação | Uniforme para o código | O avaliador e o operador leem em português; a interface teria de ser traduzida de qualquer forma |

## Decisão

A documentação (`docs/`, `reviews/`, SPECs, ADRs) é escrita em **PT-BR**, com acentuação correta. Código, identificadores, valores de enums da API, mensagens de log e mensagens de commit ficam em **inglês**. A interface (página `/capture`, console da borda e dashboard) mostra **rótulos PT-BR** obtidos de `qc_contracts.labels`, a mesma tabela para todos os componentes.

## Consequências

- **Positivas:**
  - o JSON do contrato não muda por causa de tradução;
  - mudar um rótulo da interface é uma edição em um só lugar;
  - commits e código seguem as convenções do ecossistema Python.
- **Negativas / custos aceitos:**
  - a borda e o dashboard dependem de `qc-contracts` também para os textos;
  - os docs citam valores em inglês entre crases (`unusable`) ao lado do rótulo em português.
- **O que passa a ser obrigatório:**
  - todo valor de enum novo tem rótulo PT-BR em `qc_contracts.labels` no mesmo PR, com aumento de versão do contrato (R-04, skill `contrato-api`);
  - um teste garante que todo membro de `ObjectType`, `Grade`, `Source` e `CaptureMode` tem rótulo (SPEC-002);
  - nenhum texto de interface fica fixo no HTML/JS ou no Streamlit para os enums: ele vem da tabela;
  - as mensagens de erro da API (`{"detail": ...}`) ficam em inglês; a tradução, se houver, é feita na interface.

## Quando revisitar

- Se o professor exigir o código ou os commits em português.
- Se a interface precisar de um segundo idioma de exibição (por exemplo, inglês na apresentação).
