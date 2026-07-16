# Dataset Qualis Local

O VibeScholar consulta um SQLite dedicado e separado do banco principal:

`data/qualis/qualis.sqlite3`

O arquivo oficial XLSX deve ser obtido e validado manualmente. Esta versão não
faz download, atualização automática, scraping ou chamadas à CAPES.

O arquivo precisa fornecer colunas equivalentes a `ISSN`, `TÍTULO`, `ESTRATO`
e `ÁREA-MÃE`. O quadriênio deve existir em uma coluna ou ser informado por
`--quadrennium`. Um arquivo sem estrato não contém informação suficiente para
construir o dataset e é recusado sem gerar SQLite parcial.

## Importação

Quando o XLSX contém uma coluna de quadriênio:

```powershell
python -m app.scripts.import_qualis_dataset --source data/qualis/qualis.xlsx
```

Quando o quadriênio não está em uma coluna do arquivo:

```powershell
python -m app.scripts.import_qualis_dataset `
  --source data/qualis/qualis.xlsx `
  --quadrennium 2017-2020
```

Um destino diferente pode ser informado com `--database` ou pela variável
`QUALIS_DATABASE_PATH`.

O importador recria o SQLite. Linhas com ISSN ou campos obrigatórios inválidos
são rejeitadas individualmente. Duplicatas idênticas de ISSN, estrato e
quadriênio são consolidadas. Estratos conflitantes permanecem rastreáveis e
produzem `AMBIGUOUS` no lookup.

`NOT_FOUND` significa somente que o ISSN não possui classificação disponível
no dataset importado. Não significa periódico ruim nem rejeição automática.

O XLSX oficial e arquivos temporários não são versionados. A decisão sobre
versionar o SQLite gerado fica fora desta Sprint.
