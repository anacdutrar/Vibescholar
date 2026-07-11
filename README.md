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

O Qwen 3.5 9B foi executado localmente por meio do Ollama. Inicialmente, atuou como analista de requisitos e, posteriormente, assumiu atividades próximas às de Product Owner. O modelo contribuiu para localizar ambiguidades, formular perguntas pertinentes e organizar necessidades do produto.

Na geração da arquitetura completa, foram observadas limitações relacionadas à capacidade da máquina utilizada. Embora o modelo possua contexto oficial informado de até 262.144 tokens, o experimento com Ollama ficou limitado a 4.096 tokens, o que restringiu a continuidade de análises extensas.

Durante as atividades de arquitetura, a temperatura utilizada ficou próxima de `0.5`, com a maior janela de contexto viável no ambiente. Na geração de código, a redução do `presence_penalty` de aproximadamente `1.5` para `0.3` produziu resultados mais adequados ao experimento. Esses valores representam somente observações práticas desse ambiente.

### Gemini 2.5 Flash (Medium)

O Gemini 2.5 Flash, na configuração Medium, foi utilizado por meio do Antigravity. Apresentou baixa latência e foi útil na implementação de correções pontuais. Também executava testes para verificar as alterações realizadas.

Em mudanças muito extensas, entretanto, foi observado que partes do contexto podiam ser perdidas, exigindo tarefas mais delimitadas e validações adicionais.

### Claude Sonnet 4.6 Thinking

O Claude Sonnet 4.6 Thinking também foi utilizado por meio do Antigravity. No período avaliado, apresentou boa organização de código e capacidade de raciocínio sobre as tarefas propostas. Sua participação foi menor devido à limitação de créditos disponíveis no ambiente experimental.

### Codex GPT-5.5

O Codex GPT-5.5 foi empregado na revisão estrutural do projeto, na comparação entre implementação e documentação e na identificação de violações de regras de negócio. Durante o experimento, mostrou boa capacidade para localizar inconsistências distribuídas entre diferentes camadas e apresentou baixa incidência de respostas factualmente incompatíveis com o código analisado.

### Codex GPT-5.6

O Codex GPT-5.6 foi utilizado nos refinamentos finais da implementação. As sugestões apresentaram qualidade técnica consistente no contexto avaliado, acompanhadas, porém, de consumo de créditos significativamente maior.

## Observações

Atualmente, as sugestões de evidências são produzidas por um provider mock com referências acadêmicas predefinidas. Não são realizadas buscas em bases científicas externas.

A arquitetura foi organizada para permitir uma integração futura com motores reais de busca científica, sem que essa integração faça parte do escopo atual do MVP.

O SQLite é adequado para execução local e demonstração. Em uma implantação com múltiplas instâncias ou requisitos maiores de persistência e concorrência, a estratégia de banco de dados deve ser reavaliada.

## Licença

Este projeto é disponibilizado sob a licença MIT. Consulte os termos da licença antes de redistribuir ou modificar o software.

