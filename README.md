# VibeScholar

O VibeScholar é uma aplicação local acadêmica desenvolvida como MVP para apoiar a produção de textos científicos. O sistema reúne edição, organização, versionamento e análise heurística de documentos em uma interface construída integralmente em Python.

Está disponível, temporariamente no Render: h[ttps://vibescholar.onrender.com/dashboard](https://vibescholar.onrender.com/)

## Objetivo

O VibeScholar tem como objetivo auxiliar pesquisadores durante a produção de artigos científicos. A plataforma identifica sentenças que podem necessitar de fundamentação científica e oferece recursos para consultar, avaliar e organizar evidências associadas ao texto.

Além da análise de sentenças, o sistema centraliza projetos, documentos e referências, permitindo acompanhar a evolução do conteúdo e manter um histórico explícito de versões.

## Funcionalidades

- autenticação e cadastro de usuários;
- gerenciamento de projetos acadêmicos;
- criação, importação e gerenciamento de documentos;
- editor de texto integrado;
- salvamento automático de rascunhos;
- versionamento e carregamento de versões anteriores como rascunho;
- segmentação e organização de sentenças por parágrafo;
- detecção heurística de citações aparentes;
- análise do estado de fundamentação das sentenças;
- busca, aprovação e rejeição de sugestões de evidências;
- sugestões de evidências fornecidas por um provider mock;
- biblioteca de referências por projeto;
- configurações de preferência para referências;
- exportação de documentos em formatos acadêmicos suportados pela aplicação;
- exclusão lógica de projetos e documentos.

## Tecnologias utilizadas

- **Python:** linguagem principal do projeto, utilizada tanto no backend quanto na construção da interface.
- **FastAPI:** framework responsável pela API HTTP, escolhido pela simplicidade de desenvolvimento, desempenho e geração automática de documentação da API.
- **NiceGUI:** biblioteca usada na interface web por sua integração direta com Python e pela rapidez de construção de interfaces para MVPs.
- **SQLAlchemy:** camada de persistência e mapeamento objeto-relacional, empregada para abstrair o acesso ao banco e organizar repositories e transações.
- **SQLite:** banco relacional utilizado no MVP por exigir pouca infraestrutura e permitir execução local imediata.
- **Pydantic:** utilizado na validação e serialização dos dados recebidos e retornados pela API.
- **Uvicorn:** servidor ASGI usado para executar a aplicação FastAPI e sua integração com o NiceGUI.

## Estrutura do projeto

```text
VibeScholar/
├── README.md
├── .gitignore
├── docs/                       # Documentação de requisitos e projeto
└── Vibescholar/
    ├── app.py                  # Launcher da aplicação
    ├── requirements.txt        # Dependências Python
    ├── conftest.py             # Configuração de testes
    └── app/
        ├── app.py              # Integração FastAPI e NiceGUI
        ├── core/               # Configurações e infraestrutura
        ├── models/             # Modelos SQLAlchemy
        ├── providers/          # Providers de evidências
        ├── repositories/       # Acesso e persistência de dados
        ├── routers/            # Endpoints FastAPI
        ├── schemas/            # Schemas Pydantic
        ├── services/           # Regras e casos de uso
        ├── ui/                 # Páginas, componentes e estado NiceGUI
        ├── utils/              # Funções utilitárias
        └── tests/              # Testes automatizados
```

## Instalação

### Pré-requisitos

- Python 3.11 ou superior;
- Git.

Clone o repositório e acesse o diretório da aplicação:

```bash
git clone <URL_DO_REPOSITORIO>
cd VibeScholar/Vibescholar
```

Crie um ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente no Windows:

```powershell
.venv\Scripts\Activate.ps1
```

No Linux ou macOS:

```bash
source .venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Defina uma chave de sessão antes de executar a aplicação. No PowerShell:

```powershell
$env:SECRET_KEY="uma-chave-local-segura"
```

No Linux ou macOS:

```bash
export SECRET_KEY="uma-chave-local-segura"
```

Execute a aplicação:

```bash
python app.py
```

Por padrão, a interface fica disponível em `http://127.0.0.1:8080`. O banco SQLite e as tabelas necessárias são inicializados automaticamente quando ainda não existem.

## Testes

Com o ambiente virtual ativo e a partir do diretório `Vibescholar/`, execute:

```bash
pytest app/tests/test_backend.py
```

## Processo de desenvolvimento assistido por IA

Este projeto também foi conduzido como um experimento acadêmico sobre o uso de diferentes modelos de inteligência artificial em atividades do ciclo de desenvolvimento de software. As ferramentas foram aplicadas em etapas distintas, incluindo levantamento de requisitos, arquitetura, implementação, testes e revisão estrutural.

As avaliações abaixo registram observações obtidas durante esse experimento específico. Elas dependem do hardware, das versões, dos limites de contexto, das configurações e das plataformas utilizadas; portanto, não constituem recomendações universais de configuração ou desempenho.

### Qwen 3.5 9B

O Qwen 3.5 9B foi executado localmente por meio do Ollama. Inicialmente, atuou como analista de requisitos e, posteriormente, assumiu atividades próximas às de Product Owner. O modelo contribuiu para localizar ambiguidades, formular perguntas pertinentes e organizar necessidades do produto. O SDD localizado em docs foi construido por ele.

Na geração da arquitetura completa, foram observadas limitações relacionadas à capacidade da máquina utilizada. O modelo possua contexto oficial informado de até 262.144 tokens, o experimento com Ollama fo limitava ao inicial de 4.096 tokens, o que trouxe necessidade de correção em ambiente de execussão.

Durante as atividades de arquitetura, a temperatura utilizada ficou de `0.5`, com a maior janela de contexto viável no ambiente. Na geração de código, a redução do `presence_penalty` de  `1.5` para `0.3` produziu resultados mais adequados ao experimento. Esses valores representam somente observações práticas desse ambiente.

Foram utilizados prompts como:

```text Você atuará como Principal Software Architect, com experiência em arquitetura corporativa, DDD, modelagem de domínio, engenharia de software e sistemas orientados à evolução de longo prazo.
Sua função nesta etapa NÃO é reescrever o documento.
Sua função é realizar uma revisão arquitetural crítica e independente do Software Design Document anexado.
Considere que este documento será a única fonte de verdade (Single Source of Truth) para a implementação do sistema."
```

Para correções do SDD.

### Gemini 2.5 Flash (Medium)

O Gemini 2.5 Flash, na configuração Medium, foi utilizado por meio do Antigravity. Apresentou baixa latência e foi útil na implementação de back/frontend e foi o principal criador do planos de implementação encontrados nos docs. Também executava testes para verificar as alterações realizadas.

Em mudanças muito extensas, entretanto, foi observado que partes do contexto podiam ser perdidas, exigindo tarefas mais delimitadas e validações adicionais.

### Claude Sonnet 4.6 Thinking

O Claude Sonnet 4.6 Thinking também foi utilizado por meio do Antigravity. No período avaliado, apresentou boa organização de código e capacidade de raciocínio sobre as tarefas propostas, ajudou na infraestrutura e no backend. Sua participação foi menor devido à limitação de créditos disponíveis no ambiente experimental.

Tanto para o claude quanto para o gemini, foram utilizados os mesmos prompts, com o claude focado na implementação, e pedindo para que ele continuasse de onde o Gemini parou.

Exemplos de prompt:

```text Revise o Implementation Plan e incorpore as seguintes melhorias arquiteturais antes do início da implementação.

As alterações abaixo não modificam a arquitetura, apenas completam lacunas importantes.

1. Adicionar ProjectSettings

O projeto deve possuir uma entidade de configuração própria.

Criar:

models/project_settings.py

Modelo:

ProjectSettings
---------------
id
project_id (FK)

preferred_language

minimum_qualis

publication_year_min
publication_year_max

preferred_sources

only_open_access

prefer_doi

max_suggestions

created_at
updated_at

Essas configurações pertencem ao Projeto e serão utilizadas pelo EvidenceService para filtrar sugestões.

2. Adicionar tela Settings no Workspace

O Workspace deve possuir quatro áreas principais:

Workspace

Editor

Evidence

Reference Library

Settings

A aba Settings permitirá configurar:

idioma
Qualis mínimo
intervalo de anos
bases habilitadas
Open Access
DOI obrigatório
número máximo de sugestões
3. Atualizar o EvidenceService

Hoje está:

search(sentence)

Alterar para:

search(sentence, project_settings)

O serviço deverá aplicar os filtros definidos nas configurações do projeto antes de retornar sugestões.

O MockEvidenceService também deverá respeitar esses filtros.

4. Criar camada Repository

O plano atualmente coloca boa parte da lógica diretamente nos routers.

Adicionar uma camada:

repositories/

user_repository.py

project_repository.py

document_repository.py

reference_repository.py

Fluxo desejado:

Router

↓

Service

↓

Repository

↓

SQLAlchemy

Isso facilita testes e futuras migrações.

5. Criar pasta utils

Adicionar:

utils/

markdown.py

text_normalizer.py

sentence_splitter.py

validators.py

Evita duplicação de código.

6. Criar pasta exceptions

Adicionar:

exceptions/

auth.py

document.py

reference.py

Para centralizar erros da aplicação.

7. Criar pasta core

Adicionar:

core/

security.py

config.py

logging.py

Toda configuração da aplicação deve ficar centralizada.

8. Adicionar Logging

Implementar logging estruturado para:

login
criação de projetos
criação de versões
aprovação de evidências
exportações

Usar o módulo logging do Python.

9. Adicionar Soft Delete

Nenhuma entidade principal deve ser removida fisicamente.

Adicionar:

deleted_at

nas entidades:

Project
Document
Reference

Exclusões devem ser lógicas.

10. Índices do banco

Adicionar índices para:

document_versions(document_id)

sentences(document_version_id)

sentences(sentence_uuid)

evidence_suggestions(document_version_id)

evidence_suggestions(sentence_uuid)

project_references(project_id)

quality_issues(document_version_id)
11. Importação de referências

A biblioteca de referências deve permitir:

entrada manual
BibTeX
CSV

Mesmo que o parser seja simples no MVP.

12. Exportação

Adicionar:

Markdown
DOCX
PDF
BibTeX
APA
ABNT
13. Seed de desenvolvimento

Criar automaticamente:

admin

admin123

com

projeto exemplo
documento exemplo
referências mock

Assim o avaliador consegue testar rapidamente.

14. Configuração futura das APIs

Mesmo usando MockEvidenceService no MVP, criar desde já a estrutura:

providers/

interfaces.py

mock_provider.py

openalex_provider.py

semantic_scholar_provider.py

Apenas o Mock será implementado.

15. Estrutura final

A estrutura final esperada do projeto passa a ser:

app/

config/

core/

exceptions/

models/

repositories/

services/

providers/

routers/

schemas/

utils/

gui/

static/

templates/

tests/

adicionar também função de importação de documento:
Uma nova rota:

POST /api/documents/import

Aceitando

.docx
.md
.txt

Fluxo:

Upload

↓

Detecta extensão

↓

Converte para Markdown

↓

Cria Document

↓

Abre no Editor
Serviço

Criaria

services/import_service.py

com algo como

ImportService

import_docx()

import_markdown()

import_txt()
Bibliotecas

DOCX

python-docx

Markdown

markdown-it-py

TXT

open(...)

Na UI

Adicionar um botão

Novo Documento

Importar Documento

Quando clicar

Selecionar arquivo

↓

DOCX
TXT
Markdown

↓

Importar 
```

e para implementação:

```text
Você atuará como Engenheiro de Software Sênior responsável pela implementação do projeto VibeScholar.

Leia os documentos da pasta docs considerando a seguinte prioridade:

1. Implementation_Plan_v1 (fonte principal)
2. Implementation_Plan_v2 (complementa arquitetura)
3. Software Design Document (resolver ambiguidades)

Regras obrigatórias:

- Não altere a arquitetura.
- Não simplifique o escopo.
- Não adicione funcionalidades não especificadas.
- Em caso de conflito siga V1 → V2 → SDD.
- Gere código pronto para execução.
- Sempre preserve consistência entre os arquivos.
- Ao terminar exatamente o escopo solicitado, pare e aguarde o próximo prompt.

Primeira parte:
Implemente toda a infraestrutura do projeto.

Escopo:

- estrutura completa de diretórios
- pyproject.toml ou requirements.txt
- app.py
- configuração do FastAPI
- integração NiceGUI
- configuração SQLite
- SQLAlchemy
- SessionLocal
- Base
- engine
- logging
- security
- config
- criação automática das tabelas
- seed do banco
- usuário admin
- referências mock

Também implemente todos os modelos SQLAlchemy:

- User
- Project
- ProjectSettings
- Document
- DocumentVersion
- Sentence
- GroundingReport
- QualityIssue
- ProjectReference
- EvidenceSuggestion

Implemente também todos os Schemas Pydantic.

Não implemente Services.

Não implemente Routers.

Não implemente Interface.

Ao terminar pare. 
```

### Codex GPT-5.5

O Codex GPT-5.5 foi empregado na revisão estrutural do projeto, na comparação entre implementação e documentação e na identificação de violações de regras de negócio. Durante o experimento, mostrou boa capacidade para localizar inconsistências distribuídas entre diferentes camadas e apresentou baixa incidência de respostas factualmente incompatíveis com o código analisado.

### Codex GPT-5.6

O Codex GPT-5.6 foi utilizado nos refinamentos finais da implementação. As sugestões apresentaram qualidade técnica consistente no contexto avaliado, acompanhadas, porém, de consumo de créditos significativamente maior.

Exemplo de prompt(uma vez que o contexto já estava carregado):

```text
Corrija exclusivamente três problemas: exclusão de projeto, erro 500 na busca mock de evidências e apresentação das sentenças por
  parágrafo.

  Não faça refatoração geral, não implemente integração externa e não altere funcionalidades que já estão operacionais.

  ## Arquivos inicialmente permitidos

  * `app/ui/pages/dashboard.py`
  * `app/ui/pages/workspace.py`
  * `app/ui/api_client.py`
  * `app/routers/grounding.py`
  * `app/services/grounding_service.py`
  * `app/services/evidence_service.py`
  * `app/providers/mock_provider.py`
  * `app/repositories/reference_repository.py`
  * `app/repositories/document_repository.py`, somente se necessário para consultar sugestões existentes
  * seeders atualmente usados para criar referências mock
  * testes relacionados

  Não altere models, migrations ou estrutura do banco sem demonstrar uma incompatibilidade objetiva.

  # 1. Exclusão de projeto e ciclo de vida dos elementos NiceGUI

  ## Problema confirmado

  * clicar na lixeira abre o diálogo;
  * o diálogo desaparece antes da confirmação;
  * o dashboard parece sofrer refresh;
  * a exclusão de documento já funciona e pode servir de referência.

  O log também apresenta:


  An element has been deleted but is still being used.

  Em outro fluxo do dashboard, o callback executa um refresh e depois tenta manipular um botão que já foi destruído pelo
  `@ui.refreshable`.

  ## Investigue

  * se o diálogo de projeto é criado dentro de `dashboard_content`, que é `@ui.refreshable`;
  * se clicar na lixeira também seleciona o card;
  * se há chamada de `dashboard_content.refresh()` ao abrir o diálogo;
  * se uma atualização do state provoca refresh;
  * se o callback tenta habilitar, desabilitar, fechar ou modificar elementos depois de um refresh que os destruiu;
  * se o botão possui callbacks duplicados;
  * se o card inteiro possui evento de clique que também é disparado pela lixeira.

  ## Correção obrigatória

  * criar um único diálogo persistente de exclusão fora do conteúdo recriado por `@ui.refreshable`;
  * criar esse diálogo no escopo estável de `dashboard_page`;
  * manter o projeto pendente de exclusão em um estado mutável simples, por exemplo:


  project_pending_delete = {"project": None}

  * clicar na lixeira deve apenas:

    * impedir a propagação para o card;
    * guardar o projeto;
    * atualizar o texto do diálogo;
    * abrir o diálogo;
  * não selecionar projeto;
  * não navegar;
  * não alterar `current_project`;
  * não executar refresh;
  * cancelar deve somente limpar o projeto pendente e fechar o diálogo;
  * confirmar deve chamar DELETE de forma assíncrona;
  * somente após DELETE bem-sucedido:

    * fechar o diálogo;
    * limpar o projeto pendente;
    * limpar `current_project` e `current_document` se necessário;
    * executar exatamente um `await dashboard_content.refresh()`.

  ## Regra de ciclo de vida

  Depois de executar `await dashboard_content.refresh()`, não manipule componentes que pertenciam à versão anterior do conteúdo,
  incluindo:

  * botão de excluir;
  * botão de confirmar;
  * botão de criar;
  * labels ou dialogs criados dentro do refreshable.

  Não faça chamadas como `.enable()`, `.disable()`, `.close()` ou `.set_text()` em elementos destruídos pelo refresh.

  Adicione logs:

  * `project.delete.dialog_open`;
  * `project.delete.cancel`;
  * `project.delete.confirm`;
  * resposta do DELETE;
  * início e fim do único refresh;
  * quantidade de callbacks disparados por clique.

  # 2. Busca de evidências — causa exata confirmada

  ## Erro confirmado

  O endpoint retorna 500 porque tenta inserir:

  document_version_id = 16
  sentence_uuid = b646f53a-cae0-4b35-89f3-f07f28d5370e
  reference_id = -3
  status = PENDING


  O SQLite retorna:


  FOREIGN KEY constraint failed


  O traceback aponta para:

  * `GroundingService.search_sentence_evidence`;
  * `ReferenceRepository.create_suggestion`;
  * `db.commit()`.

  A causa é o mock provider gerar IDs artificiais ou negativos que não correspondem a registros persistidos em `project_references`.

  ## Correção obrigatória

  * nunca persistir `EvidenceSuggestion.reference_id` com:

    * ID negativo;
    * ID `None`;
    * ID inexistente;
  * o mock provider pode produzir dados de referência sem ID, mas antes de criar uma sugestão cada referência deve:

    * ser localizada no banco por DOI ou combinação estável de título/ano;
    * ou ser persistida em `project_references`;
    * receber um ID real do banco;
  * somente depois criar a `EvidenceSuggestion`;
  * todas as sugestões devem referenciar registros reais e ativos;
  * não usar IDs inventados como `-1`, `-2` ou `-3`;
  * referências mock podem ser globais com `project_id=None` ou pertencentes ao projeto, conforme o modelo já permite;
  * não criar duplicata para a combinação:

    * `document_version_id`;
    * `sentence_uuid`;
    * `reference_id`;
  * sugestões já aprovadas ou rejeitadas não devem reaparecer como novas;
  * executar `db.rollback()` obrigatoriamente se o `commit()` falhar;
  * a sessão deve continuar utilizável após a falha;
  * não retornar 500 bruto para erro conhecido;
  * sentença inexistente deve retornar 404;
  * ausência de sugestões deve retornar 200 com `[]`.

  ## Comportamento mock esperado

  Para qualquer sentença textual válida:

  1. tentar correspondência temática;
  2. aplicar configurações do projeto;
  3. usar fallback acadêmico genérico se não houver correspondência;
  4. retornar de 3 a 5 sugestões, desde que existam referências compatíveis;
  5. se os filtros do usuário eliminarem todas, retornar uma lista vazia controlada ou informar que os filtros eliminaram os
  resultados.

  Garanta um pool persistido de pelo menos 12 referências mock, cobrindo:

  * inteligência artificial;
  * escrita científica;
  * integridade acadêmica;
  * recuperação de informação;
  * visão computacional;
  * redes neurais;
  * metodologia científica.

  ## Logging obrigatório

  Registrar:

  * `sentence_id`;
  * `sentence_uuid`;
  * `document_version_id`;
  * `project_id`;
  * configurações aplicadas;
  * quantidade de referências candidatas;
  * IDs reais encontrados ou criados;
  * IDs descartados;
  * sugestões já existentes;
  * quantidade final retornada;
  * rollback em caso de erro.

  Não registrar conteúdo sensível nem stack trace para respostas normais de domínio.

  ## Testes obrigatórios

  1. sentença válida retorna entre 3 e 5 sugestões;
  2. todos os `reference_id` retornados existem no banco;
  3. nenhum `reference_id` é negativo;
  4. nenhuma sugestão possui `reference_id=None`;
  5. segunda busca não cria duplicatas;
  6. sugestões rejeitadas não reaparecem como novas;
  7. sugestões aprovadas continuam associadas, mas não reaparecem como pendentes;
  8. sentença inexistente retorna 404;
  9. filtros sem resultado retornam resposta controlada;
  10. falha de integridade executa rollback e não deixa a sessão em `PendingRollbackError`.

  # 3. Apresentação das sentenças por parágrafo

  Não implemente clique direto no Quill nesta etapa.

  Use os dados já existentes de `paragraph_number`.

  ## Comportamento esperado

  * agrupar sentenças por `paragraph_number`;
  * adicionar um seletor:

    * Todos os parágrafos;
    * Parágrafo 1;
    * Parágrafo 2;
    * etc.;
  * ao selecionar um parágrafo, mostrar somente as sentenças dele;
  * exibir a quantidade, como:

    * `3 sentenças neste parágrafo`;
  * não fazer nova chamada HTTP ao trocar o filtro;
  * não recarregar a página;
  * não recriar o workspace inteiro;
  * preservar o filtro enquanto o componente atual continuar ativo;
  * caso `paragraph_number` seja nulo, agrupar como `Sem parágrafo identificado`.

  ## Evidências visíveis na sentença

  Para cada sentença, mostrar:

  * texto resumido;
  * status atual;
  * quantidade de evidências aprovadas;
  * títulos resumidos das referências aprovadas, se a API já fornecer esses dados;
  * indicador de citação aparente, quando existir;
  * botão:

    * `Buscar evidências`, se não houver aprovadas;
    * `Ver / adicionar evidências`, se houver ao menos uma aprovada.

  Se a resposta atual de sentenças não contiver referências aprovadas, prefira enriquecer a resposta no service/repository já
  existente. Não faça uma requisição HTTP por sentença, pois isso criaria problema N+1.

  # Regras gerais

  * callbacks NiceGUI com HTTP devem ser assíncronos;
  * usar `httpx.AsyncClient`;
  * não aumentar timeout;
  * não usar `time.sleep`;
  * não usar timers ou background tasks para esconder erros;
  * não usar `except Exception: pass`;
  * não executar o servidor dentro do Codex;
  * não excluir, mover ou renomear arquivos;
  * não alterar autenticação, exportação, importação, configurações ou exclusão de documentos nesta etapa.

  # Validação

  Execute:

  * `python -m py_compile` nos arquivos alterados;
  * `python -m compileall -b app`;
  * remover somente os `.pyc` gerados fora de `__pycache__`;
  * testes backend;
  * teste de exclusão sem refresh prematuro;
  * teste de ciclo de vida garantindo que nenhum elemento destruído seja manipulado;
  * testes de busca mock e integridade referencial;
  * teste de não duplicação;
  * teste do agrupamento por parágrafo.

  Ao final informe:

  1. causa exata do diálogo desaparecer;
  2. onde o diálogo persistente foi criado;
  3. quantos refreshes ocorrem na exclusão;
  4. causa exata da foreign key inválida;
  5. origem do `reference_id=-3`;
  6. como referências mock passam a obter IDs reais;
  7. quantidade de sugestões retornadas;
  8. comportamento em buscas repetidas;
  9. como evidências aprovadas aparecem na UI;
  10. como o filtro por parágrafo funciona;
  11. arquivos alterados;
  12. confirmação de que nenhum arquivo foi excluído.
```

## Observações

Atualmente, as sugestões de evidências são produzidas por um provider mock com referências acadêmicas predefinidas. Não são realizadas buscas em bases científicas externas.

A arquitetura foi organizada para permitir uma integração futura com motores reais de busca científica, sem que essa integração faça parte do escopo atual do MVP.

O SQLite é adequado para execução local e demonstração. Em uma implantação com múltiplas instâncias ou requisitos maiores de persistência e concorrência, a estratégia de banco de dados deve ser reavaliada.

## Licença

Este projeto é disponibilizado sob a licença MIT. Consulte os termos da licença antes de redistribuir ou modificar o software.

