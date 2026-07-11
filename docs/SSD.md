\# Software Design Document (SDD) – VibeScholar v1

\*\*Versão:\*\* 1.0-FINAL  
\*\*Status:\*\* CONGELADO PARA DESENVOLVIMENTO  
\*\*Data de Aprovação:\*\* \[DATA\]  
\*\*Aprovação de Arquitetura:\*\* Principal Software Architect

\---

\#\# 1\. Visão do Produto

\#\#\# 1.1 Objetivo do VibeScholar  
Desenvolver uma plataforma web monolítica (Single Instance) que acompanhe pesquisadores durante todo o processo de  
escrita científica, reduzindo o tempo gasto procurando referências que fundamentem afirmações presentes em  
artigos, TCCs, dissertações e teses. O sistema analisa a qualidade da fundamentação científica de documentos em  
produção acadêmica, garantindo integridade dos dados via versionamento explícito sem dependência de infraestrutura  
complexa (como Redis ou Bancos Vetoriais).

\#\#\# 1.2 Público-Alvo  
| Segmento | Descrição |  
|-----------|-----------|  
| Estudantes de Graduação | Autores iniciantes com necessidade de organização básica e salvamentos frequentes |  
| Estudantes de Mestrado | Pesquisa mais complexa, múltiplos projetos simultâneos |  
| Estudantes de Doutorado | Documentos extensos (50k+ palavras), análise detalhada via Grounding Report |  
| Professores | Supervisão de trabalhos acadêmicos |  
| Pesquisadores | Produção científica contínua e revisão sistemática |

\#\#\# 1.3 Problema que Resolve  
Hoje o pesquisador escreve uma afirmação como: \*"Redes neurais convolucionais apresentam excelentes resultados  
para detecção de objetos"\*. Nesse momento ele precisa interromper completamente sua escrita para procurar artigos,  
verificar qualidade, analisar citações e decidir quais sustentam aquela afirmação. Isso quebra o fluxo de escrita.  
O VibeScholar minimiza essa interrupção através de sugestões contextuais integradas ao editor, mas sem comprometer  
a integridade do banco local (SQLite).

\#\#\# 1.4 Casos de Uso Principais  
| ID | Caso de Uso | Descrição | Prioridade |  
|----|-------------|-----------|------------|  
| UC01 | Criar Projeto | Usuário cria novo projeto acadêmico | Alta |  
| UC02 | Criar/Importar Documento | Cria documento novo ou importa DOCX/PDF (V1: Simulação de conversão) | Alta |  
| UC03 | Editar Texto | Usuário escreve/edita conteúdo do documento (Autosave no DB) | Alta |  
| UC04 | Buscar Evidências | Sistema sugere referências para afirmação selecionada (Mock V1) | Alta |  
| UC05 | Aprovar Referência | Usuário aprova/rejeita sugestão de referência no contexto da versão atual | Alta |  
| UC06 | Gerar Grounding Report | Sistema calcula métricas de fundamentação e persiste relatório explícito | Média  
|  
| UC07 | Exportar Documento | Gera arquivo em formatos acadêmicos (BibTeX, ABNT) | Alta |  
| UC08 | Ver Dashboard | Usuário visualiza estatísticas do projeto (último Grounding Report) | Média |

\#\#\# 1.5 Fluxo Principal do Usuário  
\`\`\`  
Login → Selecionar Projeto → Abrir Documento → Editar Texto (Autosave no DB)  
    ↓  
Clicar em "Encontrar Evidências" (ao passar cursor sobre sentença)  
    ↓  
Sistema sugere 5 referências simuladas (Mock V1)  
    ↓  
Usuário aprova/rejeita referência  
    ↓  
Salvo Manualmente → Cria DocumentVersion \+ Atualiza Content e Sentenças  
    ↓  
Grounding Report atualizado no dashboard  
\`\`\`

\---

\#\# 2\. Requisitos Funcionais

\#\#\# 2.1 Projetos (Projeto Acadêmico)

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| RF01 | Criar Projeto | Formulário com nome, descrição opcional, data automática |  
| RF02 | Listar Projetos | Exibir todos projetos do usuário em ordem cronológica inversa |  
| RF03 | Editar Projeto | Permitir renomear projeto e atualizar descrição |  
| RF04 | Deletar Projeto | Confirmação antes de remover, sem recuperação automática |

\#\#\# 2.2 Documentos

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| RF05 | Criar Documento Novo | Formulário com título e conteúdo inicial (Markdown) |  
| RF06 | Importar DOCX/PDF | Converter para Markdown interno, manter estrutura básica |  
| RF07 | Listar Documentos do Projeto | Exibir lista com status de fundamentação (% apoiado \- último relatório) |  
| RF08 | Deletar Documento | Confirmação obrigatória, versão atual é removida (histórico preservado em versions) |

\#\#\# 2.3 Editor e Draft Management (Autosave Direto no DB)

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF09\*\* | \*\*Renderizar Conteúdo\*\* | Exibir texto com formatação básica (negrito, itálico, listas) via iframe  
Quill |  
| \*\*RF10\*\* | \*\*Autosave no Banco\*\* | \*\*Atualização direta em \`Document.content\` a cada 2-3 segundos (debounce).  
Não cria versão. Garante persistência sem latência de rede.\*\* |  
| RF11 | Indicador de Status | Mostrar badge visual por sentença (UNVERIFIED/SUPPORTED/OUTDATED) baseado na última  
versão salva |

\#\#\# 2.4 Versionamento

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF12\*\* | \*\*Criar Versão Manual\*\* | \*\*Botão "Salvar" explícito cria snapshot em \`DocumentVersion\` e atualiza  
\`Document.content\`. Autosave não gera versão.\*\* |  
| RF13 | Restaurar Versão Anterior | Selecionar versão específica e restaurar conteúdo completo (cria nova versão  
incremental) |  
| RF14 | Histórico de Versões | Listar todas versões criadas para documento específico |

\#\#\# 2.5 Biblioteca de Referências

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| RF15 | Adicionar Referência Manual | Formulário com todos metadados bibliográficos |  
| RF16 | Importar Bibliografia CSV/JSON | Carregar lista de referências em formato estruturado |  
| RF17 | Editar Referência | Permitir atualizar título, autores, DOI, etc. |  
| RF18 | Remover Referência | Confirmação antes de remover da biblioteca global/projeto |

\#\#\# 2.6 Busca e Evidências (Mock V1)

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF19\*\* | \*\*Buscar Referências por Sentença\*\* | Retornar até 5 referências simuladas para afirmação  
selecionada. Vincula sugestão a \`DocumentVersion\` atual. |  
| RF20 | Filtros de Busca | Nacionais/Internacionais, Qualis mínimo, Ano (V1: Mock apenas) |  
| \*\*RF21\*\* | \*\*Aprovar Referência\*\* | Associar referência à sentença específica na versão salva. Chave estrangeira  
para \`document\_version\_id\`. |  
| RF22 | Rejeitar Sugestão | Remover sugestão sem persistir no histórico de versões antigas |

\#\#\# 2.7 Fundamentação e Grounding

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF23\*\* | \*\*Calcular Grounding Score\*\* | % de sentenças com evidência aprovada persistida em \`GroundingReport\`.  
Coluna \`Document.grounding\_score\` é leitura (cache). |  
| RF24 | Gerar Quality Issues | Listar problemas detectados (falta evidência, desatualizado) no último relatório |  
| \*\*RF25\*\* | \*\*Visualizar Dashboard\*\* | Métricas agregadas do projeto e documentos baseadas nos últimos relatórios  
persistidos. |

\#\#\# 2.8 Exportação

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| RF26 | Exportar Documento BibTeX | Formato bibliográfico padrão ACM/IEEE |  
| RF27 | Exportar Documento ABNT | Formatação conforme normas brasileiras (NBR 6023\) |  
| RF28 | Exportar Documento APA | Estilo acadêmico americano padrão |

\#\#\# 2.9 Autenticação e Segurança (V1 \- Sessões)

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF29\*\* | \*\*Login Simples\*\* | Usuário \+ Senha (hash bcrypt). Utilização de Cookies HttpOnly (\`SECRET\_KEY\`) para  
sessão. Proteção CSRF nativa. Rate Limiting ativado. |  
| RF30 | Registro Novo Usuário | Formulário com validação básica de email |  
| RF31 | Rotação Forçada | Alerta visual para senha expirada (V2: Implementar) |

\#\#\# 2.10 Configurações do Sistema

| RF | Descrição | Critérios de Aceite |  
|----|-----------|---------------------|  
| \*\*RF32\*\* | \*\*Definir Preferências de Busca\*\* | Filtros padrão por projeto (Qualis, anos, etc.) \- Persistidos no  
banco. |  
| \*\*RF33\*\* | \*\*Configurar Backup Automático\*\* | Ativar/desativar backup diário do SQLite para arquivo externo  
(.sql). |

\---

\#\# 3\. Requisitos Não Funcionais

\#\#\# 3.1 Performance

| NFR | Descrição | Meta V1 | Justificativa |  
|-----|-----------|---------|---------------|  
| \*\*NFR01\*\* | Tempo de Resposta API | \<200ms para endpoints simples, \<1s para buscas complexas (Mock) | SQLite \+  
Cache em memória não precisa otimização extrema V1. Autosave não bloqueia DB (WAL mode). |  
| NFR02 | Tamanho do Banco | Sem limite rígido de 50MB. Política de retenção via script/arquivo. | SQLite lida bem  
com volumes acadêmicos se houver backup externo diário. |

\#\#\# 3.2 Escalabilidade

| NFR | Descrição | Meta V1 | Justificativa |  
|-----|-----------|---------|---------------|  
| \*\*NFR03\*\* | Usuários Simultâneos | Até 50 usuários concorrentes (Single Instance) | Single user \+ SQLite  
adequado para MVP acadêmico. Sessões gerenciadas pelo servidor local. |  
| NFR04 | Volume de Documentos | Até 1.000 documentos no banco único | SQLite OK, PostgreSQL V2+ se necessário. |

\#\#\# 3.3 Segurança

| NFR | Descrição | Implementação |  
|-----|-----------|---------------|  
| \*\*NFR05\*\* | Hash de Senhas | bcrypt com work factor 12 (padrão) \- Sessões via Cookies HttpOnly. |  
| NFR06 | Validação de Inputs | Pydantic schemas em todos endpoints API. |  
| NFR07 | XSS Protection | Sanitização automática no frontend via NiceGUI/Quill. |

\#\#\# 3.4 Portabilidade e Backup

| NFR | Descrição | Implementação |  
|-----|-----------|---------------|  
| \*\*NFR08\*\* | Banco de Dados Único SQLite | Arquivo \`.db\` portátil, backup manual ou script automático (cron). |  
| NFR09 | Exportação de Dados | Script para exportar todo banco em JSON/SQL dump. |

\#\#\# 3.5 Offline e Limitações V1

| NFR | Descrição | Status V1 |  
|-----|-----------|------------|  
| \*\*NFR10\*\* | Funcionalidade Offline | Não implementado (requer backend sempre online). Drafts não persistidos se  
a sessão cair sem salvar. |  
| NFR11 | Integração IA Real | Mock apenas, sem chamadas externas reais. |  
| NFR12 | APIs Externas | Nenhuma chamada externa na V1 (OpenAlex, etc.). |

\#\#\# 3.6 Manutenção e Testabilidade

| NFR | Descrição | Implementação |  
|-----|-----------|---------------|  
| \*\*NFR13\*\* | Logs de Erro | Console logging básico via Python \`logging\`. |  
| NFR14 | Unit Tests | pytest para serviços core, mocks para IA. |  
| NFR15 | Documentação Inline | Docstrings em todos módulos públicos. |

\---

\#\# 4\. Modelo de Domínio

\#\#\# 4.1 Entidades Principais e Responsabilidades

\#\#\#\# User (Usuário)  
\*\*Responsabilidades:\*\*  
\- Autenticação no sistema via Sessões Cookies.  
\- Proprietário de projetos e documentos.  
\- Configurações globais do usuário.

\*\*Relacionamentos:\*\*  
\- \`User\` → 0..N \`Project\`.  
\- \`User\` → 1 \`Session\` (implícito na gestão de login).

\#\#\#\# Project (Projeto)  
\*\*Responsabilidades:\*\*  
\- Agrupar documentos relacionados a uma pesquisa específica.  
\- Configurações próprias de biblioteca e filtros de busca.

\*\*Relacionamentos:\*\*  
\- \`Project\` → 0..N \`Document\`.  
\- \`Project\` → 0..N \`Reference\`.

\#\#\#\# Document (Documento)  
\*\*Responsabilidades:\*\*  
\- Armazenar conteúdo principal do documento científico (\`content\`).  
\- Metadados de título, descrição, status geral de fundamentação (\`grounding\_score\` \- cache).  
\- Pontar para versão ativa (\`current\_version\_id\`).  
\- \*\*Regra Crítica:\*\* \`Document.content\` é sempre a fonte da verdade atual (incluindo autosave), mas apenas as  
versões explícitas criam histórico.

\*\*Relacionamentos:\*\*  
\- \`Document\` → 1..N \`Sentence\`.  
\- \`Document\` → 0..N \`DocumentVersion\`.  
\- \`Document\` → 0..N \`GroundingReport\`.

\#\#\#\# DocumentVersion (Versão do Documento)  
\*\*Responsabilidades:\*\*  
\- Armazenar snapshot completo de conteúdo em ponto específico no tempo (\`content\_snapshot\`).  
\- Permitir restauração de versão anterior sem sobrescrever atual.  
\- Histórico auditável com autor e timestamp.  
\- \*\*Fonte da Verdade Histórica.\*\*

\#\#\#\# Sentence (Sentença/Frase)  
\*\*Responsabilidades:\*\*  
\- Representar unidade mínima de fundamentação científica dentro do contexto de uma \`DocumentVersion\`.  
\- Status de evidência (\`UNVERIFIED\`, \`SUPPORTED\`, \`OUTDATED\`).  
\- Posicionamento no documento para rastreamento visual.

\*\*Relacionamentos:\*\*  
\- \*\*\`Sentence\` → 0..N \`EvidenceSuggestion\`\*\*.  
\- \*\*Regra Crítica:\*\* Sentença é dado DERIVADO. Nunca editar manualmente. Reconstruído automaticamente a partir de  
conteúdo do documento ao salvar versão (Explicit Save).

\#\#\#\# Reference (Referência Bibliográfica)  
\*\*Responsabilidades:\*\*  
\- Metadados completos da publicação científica.  
\- Indicador Qualis, DOI, ano, tipo (journal/conferência).  
\- Compartilhamento global ou específico por projeto.

\*\*Relacionamentos:\*\*  
\- \`Reference\` → 0..N \`EvidenceSuggestion\`.

\#\#\#\# EvidenceSuggestion (Sugestão de Evidência)  
\*\*Responsabilidades:\*\*  
\- Associar referência específica a sentença específica \*\*dentro do contexto da versão\*\*.  
\- Status da associação (\`PENDING\`, \`APPROVED\`, \`REJECTED\`).  
\- Histórico de decisões do usuário sobre sugestão.

\*\*Relacionamentos:\*\*  
\- \*\*\`EvidenceSuggestion\` → 1..N \`DocumentVersion\` (FK: document\_version\_id)\*\*.  
\- \`EvidenceSuggestion\` → 1..N \`Reference\`.  
\- \*\*Regra Crítica:\*\* Vinculação direta à versão (\`document\_version\_id\`) para garantir estabilidade dos IDs de  
sentença.

\#\#\#\# GroundingReport (Relatório de Fundamentação)  
\*\*Responsabilidades:\*\*  
\- Métricas agregadas do documento em ponto temporal específico.  
\- Score total, contagem por categoria de problema.  
\- Histórico de análises para tracking de evolução.

\*\*Relacionamentos:\*\*  
\- \`GroundingReport\` → 1..N (um relatório por análise no tempo).  
\- \*\*Regra Crítica:\*\* Não calcular dinamicamente a cada query. Gerar explícitamente e persistir.

\#\#\#\# QualityIssue (Problema de Qualidade)  
\*\*Responsabilidades:\*\*  
\- Problemas específicos detectados (falta evidência, desatualizado, contraditório).  
\- Descrição detalhada para feedback ao usuário.  
\- Severidade e impacto na qualidade geral.

\*\*Relacionamentos:\*\*  
\- \`QualityIssue\` → 1..N por documento.  
\- \*\*Regra Crítico:\*\* Issue é específico de sentença ou nível do documento. Não duplicar dados com GroundingReport.

\#\#\# 4.2 Diagrama ER Simplificado (Texto)

\`\`\`  
User ───┬─── Project ───┬──── Document ───┬──── Sentence ───┬── EvidenceSuggestion  
        │              │                   │                  │  
        │              ├─── Reference      │                  │  
        │              │                   │                  │  
        │              └────────┴──────────┘                  │  
        │                                                     GroundingReport ← QualityIssue (opcional)  
        │  
        └──── DocumentVersion (histórico de versões do document, FK para EvidenceSuggestion)  
\`\`\`

\#\#\# 4.3 Regras de Negócio Críticas

| ID | Regra | Descrição | Violação Resultante |  
|----|-------|-----------|---------------------|  
| \*\*RB01\*\* | \`Document.content\` vs \`DocumentVersion\` | \`Document.content\` sempre igual ao conteúdo da versão mais  
recente em \`DocumentVersion\`. Autosave atualiza content sem criar versão. Nunca editar \`Document.content\`  
diretamente sem commit atômico. | Inconsistência de dados, backup corrompido |  
| \*\*RB02\*\* | Reconstrução de Sentenças | Sentenças são regeneradas automaticamente a cada mudança no documento (ao  
salvar explícito). Não regenerar durante autosave para evitar travamento SQLite. Nunca editar manualmente. | Dados  
desalinhados entre UI e banco |  
| RB03 | Status de EvidenceSuggestion | Apenas PENDING → APPROVED/REJECTED. Não permitir REJECTED → PENDING sem  
nova busca. Histórico inconsistente. | |  
| RB04 | GroundingReport Geração | Gerar explícitamente após cada análise, não dinamicamente na query. Performance  
degradada em queries complexas. | |  
| \*\*RB05\*\* | Reference Reutilização | Uma referência pode ser sugerida para múltiplas sentenças. Não duplicar no  
banco (FK única). Ineficiência de armazenamento. | |

\---

\#\# 5\. Diagrama Entidade-Relacionamento (DER) Completo

\#\#\# 5.1 Tabelas e Colunas Detalhadas

\`\`\`sql  
\-- Tabela: users  
CREATE TABLE users (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    username VARCHAR(255) NOT NULL UNIQUE,  
    password\_hash VARCHAR(255) NOT NULL,  
    email VARCHAR(255),  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    updated\_at DATETIME DEFAULT CURRENT\_TIMESTAMP  
);

\-- Tabela: projects  
CREATE TABLE projects (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    user\_id INTEGER NOT NULL,  
    name VARCHAR(255) NOT NULL,  
    description TEXT,  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (user\_id) REFERENCES users(id),  
    UNIQUE(username, username) \-- Para login simples  
);

\-- Tabela: documents  
CREATE TABLE documents (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    project\_id INTEGER NOT NULL,  
    title VARCHAR(255) NOT NULL,  
    description TEXT,  
    current\_version\_id INTEGER NOT NULL,  
    grounding\_score FLOAT DEFAULT 0.0, \-- Cache de leitura  
    last\_analyzed\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    updated\_at DATETIME DEFAULT CURRENT\_TIMESTAMP, \-- Para rastrear autosave  
    FOREIGN KEY (project\_id) REFERENCES projects(id),  
    UNIQUE(project\_id, id) \-- Garante única por projeto  
);

\-- Tabela: document\_versions  
CREATE TABLE document\_versions (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    document\_id INTEGER NOT NULL,  
    version\_number INTEGER NOT NULL,  
    content\_snapshot TEXT NOT NULL,  \-- Markdown/JSON estruturado \- Fonte da Verdade Histórica  
    created\_by VARCHAR(100) NOT NULL,  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (document\_id) REFERENCES documents(id),  
    UNIQUE(document\_id, version\_number)  
);

\-- Tabela: sentences  
CREATE TABLE sentences (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    document\_version\_id INTEGER NOT NULL, \-- FK para DocumentVersion  
    paragraph\_number INTEGER NOT NULL,  
    sentence\_number INTEGER NOT NULL,  
    position REAL NOT NULL,  \-- Posição no documento para rastreamento visual  
    text TEXT NOT NULL,      \-- Texto da sentença  
    status VARCHAR(20) DEFAULT 'UNVERIFIED',  
    FOREIGN KEY (document\_version\_id) REFERENCES document\_versions(id),  
    UNIQUE(document\_version\_id, paragraph\_number, sentence\_number)  
);

\-- Tabela: references  
CREATE TABLE references (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    project\_id INTEGER,  \-- NULL \= Global, \!=NULL \= Projeto específico  
    title VARCHAR(255) NOT NULL,  
    authors TEXT NOT NULL,  \-- JSON ou texto formatado  
    journal VARCHAR(255),  
    year INTEGER,  
    doi VARCHAR(100),  
    qualis\_score FLOAT,  
    abstract TEXT,  
    availability VARCHAR(20) DEFAULT 'FECHADO',  \-- ABERTO/FECHADO  
    FOREIGN KEY (project\_id) REFERENCES projects(id)  
);

\-- Tabela: evidence\_suggestions  
CREATE TABLE evidence\_suggestions (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    document\_version\_id INTEGER NOT NULL, \-- FK para DocumentVersion (Estabilidade de ID)  
    sentence\_uuid VARCHAR(255) NOT NULL, \-- UUID da sentença na versão específica  
    reference\_id INTEGER NOT NULL,  
    status VARCHAR(20) DEFAULT 'PENDING',  \-- PENDING/APPROVED/REJECTED  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (document\_version\_id) REFERENCES document\_versions(id),  
    FOREIGN KEY (reference\_id) REFERENCES references(id),  
    UNIQUE(document\_version\_id, sentence\_uuid, reference\_id) \-- Impede duplicatas da mesma ref na mesma  
sentença/version  
);

\-- Tabela: grounding\_reports  
CREATE TABLE grounding\_reports (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    document\_id INTEGER NOT NULL,  
    generated\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    supported\_count INTEGER DEFAULT 0,  
    unsupported\_count INTEGER DEFAULT 0,  
    partial\_count INTEGER DEFAULT 0,  
    outdated\_count INTEGER DEFAULT 0,  
    contradictions\_count INTEGER DEFAULT 0,  
    FOREIGN KEY (document\_id) REFERENCES documents(id),  
    UNIQUE(document\_id, generated\_at)  
);

\-- Tabela: quality\_issues  
CREATE TABLE quality\_issues (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    document\_id INTEGER NOT NULL,  
    sentence\_uuid VARCHAR(255),  \-- NULL \= issue de nível do documento ou UUID da sentença na versão atual  
    issue\_type VARCHAR(50),  \-- LACK\_OF\_EVIDENCE, CONTRADICTION, OUTDATED  
    description TEXT,  
    severity FLOAT DEFAULT 1.0,  \-- 1-3 (baixa, média, alta)  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (document\_id) REFERENCES documents(id),  
    FOREIGN KEY (sentence\_uuid) REFERENCES sentences(sentence\_uuid) \-- Opcional se necessário join direto  
);

\-- Tabela: search\_history  
CREATE TABLE search\_history (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    user\_id INTEGER NOT NULL,  
    project\_id INTEGER,  \-- NULL \= busca global  
    query TEXT NOT NULL,  
    filters JSON,  \-- Filtros usados na busca  
    results\_count INTEGER DEFAULT 0,  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (user\_id) REFERENCES users(id),  
    FOREIGN KEY (project\_id) REFERENCES projects(id)  
);

\-- Tabela: export\_history  
CREATE TABLE export\_history (  
    id INTEGER PRIMARY KEY AUTOINCREMENT,  
    user\_id INTEGER NOT NULL,  
    document\_id INTEGER,  \-- NULL \= exportação global  
    format VARCHAR(20),  \-- BibTeX/ABNT/APA/IEEE  
    file\_path TEXT,  
    created\_at DATETIME DEFAULT CURRENT\_TIMESTAMP,  
    FOREIGN KEY (user\_id) REFERENCES users(id),  
    FOREIGN KEY (document\_id) REFERENCES documents(id)  
);  
\`\`\`

\#\#\# 5.2 Relacionamentos e Cardinalidade

| Relacionamento | Tabela Pai | Tabela Filho | Cardinalidade | Justificativa |  
|----------------|------------|--------------|---------------|---------------|  
| User → Project | users | projects | 1:N | Um usuário pode ter múltiplos projetos de pesquisa |  
| Project → Document | projects | documents | 1:N | Projeto contém documentos relacionados |  
| \*\*DocumentVersion\*\* | document\_versions | sentences | 1:N | Histórico completo de versões do documento.  
Sentenças vinculadas à versão, não ao documento vazio. |  
| DocumentVersion → EvidenceSuggestion | document\_versions | evidence\_suggestions | 1:N | Sugestões vinculadas  
diretamente à versão para estabilidade de ID. |

\#\#\# 5.3 Índices Recomendados

\`\`\`sql  
CREATE INDEX idx\_documents\_project ON documents(project\_id);  
CREATE INDEX idx\_sentences\_version ON sentences(document\_version\_id); \-- Indexado na versão, não no documento  
genérico  
CREATE INDEX idx\_references\_project ON references(project\_id);  
CREATE INDEX idx\_evidence\_version ON evidence\_suggestions(document\_version\_id);  
CREATE INDEX idx\_search\_history\_user ON search\_history(user\_id, created\_at DESC);  
\`\`\`

\---

\#\# 6\. Fluxo Geral dos Dados

\#\#\# 6.1 Diagrama de Fluxo Completo (Texto)

\`\`\`  
\[Usuário\] → \[Login/Auth Session Cookie\]  
    ↓  
\[Selecionar Projeto\] → \[Listar Projetos\]  
    ↓  
\[Abrir Documento\] → \[Document.current\_version\_id\] → \[document\_versions.id\]  
    ↓  
\[Editar Texto no Editor Quill (Autosave no DB)\]  
    ↓ (Evento de Edição)  
\[Backend: Atualiza Document.content via Debounce (2-3s)\]  
    ↓ (Não persiste em Draft, apenas atualiza content direto)  
\[Sistema Extrai Sentenças do Content?\] \-\> Não. Espera Salvamento Explícito.  
    ↓ \[Usuário clica em "Salvar"\]  
\[Backend: Commit Transaction\]  
    ↓  
  ┌──────────────┬─────────────────┐  
  │ Salva no DB  │ Cria Versão     │  
  ├──────────────┼─────────────────┤  
  │ documents.content \= Draft (já atualizado)            │ document\_versions.insert(snapshot)  
  │ sentences.delete() \+ insert()                        │ evidence\_suggestions (vinculado à nova versão)  
  └──────────────┴─────────────────┘  
    ↓  
\[Sistema Sugere Evidências para Sentenças UNVERIFIED na Nova Versão\]  
    ↓ (EvidenceService.search())  
\[Retorna Top 5 Referências Mockadas\]  
    ↓  
\[Usuário Aprova/Rejeita Referência\]  
    ↓  
\[EvidenceSuggestion.status \= APPROVED/REJECTED\]  
    ↓  
\[QualityIssue: Atualiza se necessário\]  
    ↓  
\[Gera GroundingReport novo (se score mudou)\]  
    ↓  
\[Salva em DocumentVersion (versão manual ou automática do commit)\]  
\`\`\`

\#\#\# 6.2 Diagrama de Dados em Repouso

\`\`\`  
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐  
│   User      │────▶│   Project    │────▶│   Document      │  
└─────────────┘     └──────────────┘     └────────┬────────┘  
                                                   │  
                                         ┌─────────┴─────────┐  
                                         │  current\_version\_id│  
                                         └─────────┬─────────┘  
                                                   │  
                                          ┌────────▼────────┐  
                                          │ DocumentVersion │  
                                          │ content\_snapshot │ (Fonte Verdade)  
                                          └────────┬─────────┘  
                                                  │  
                                        ┌─────────┴─────────┐  
                                        │    Sentences      │ (Vinculadas a Version)  
                                        │ text, status     │  
                                        └────────┬─────────┘  
                                                 │  
                                    ┌────────────▼───────────┐  
                                    │ EvidenceSuggestions     │  
                                    │ document\_version\_id, sentence\_uuid, reference\_id  
                                    └─────────────────────────┘  
\`\`\`

\---

\#\# 7\. Fluxo de Cada Funcionalidade Detalhado

\#\#\# 7.1 Criação de Documento (UC05)

\*\*Passos:\*\*  
1\. Usuário seleciona projeto existente ou cria novo via UC01.  
2\. Formulário: título, descrição opcional.  
3\. Backend valida inputs via Pydantic schema \`DocumentCreate\`.  
4\. Cria registro em \`documents.tabela\` com \`current\_version\_id \= NULL\` inicialmente (ou aponta para versão 1).  
5\. Salva conteúdo inicial (Markdown) no campo \`content\` de \`documents\`.  
6\. Cria primeira versão em \`document\_versions\` com \`version\_number \= 1\`.  
7\. Extrai sentenças iniciais do conteúdo e insere em \`sentences\`.

\*\*Código Backend (Pseudocódigo):\*\*  
\`\`\`python  
def create\_document(project\_id: int, title: str, content: str):  
    doc \= Document(  
        project\_id=project\_id,  
        title=title,  
        description="",  \# Opcional  
        current\_version\_id=None  
    )

    version \= DocumentVersion(  
        document\_id=doc.id,  
        version\_number=1,  
        content\_snapshot=content,  
        created\_by="system"  
    )

    db.add(doc)  
    db.add(version)  
    db.commit()

    \# Extrair sentenças do conteúdo e salvar em sentences tabela  
    extract\_sentences(content, doc.id, version\_id=version.id)  
\`\`\`

\#\#\# 7.2 Salvamento Automático (RF10 \- Autosave Direto no DB)

\*\*Passos:\*\*  
1\. Detectar mudança no editor via evento/intervalo (NiceGUI polling ou WebSocket futuro).  
2\. Converter Delta → Markdown \*\*apenas na memória\*\*.  
3\. Atualizar \`documents.content\` diretamente no banco de dados (via transação rápida/debounce).  
4\. Não persistir em \`document\_versions\`.  
5\. Atualizar estado local da aplicação para refletir a edição visualmente.

\*\*Regra:\*\* Autosave é atualização direta do conteúdo atual (\`Document.content\`). Nunca sobrescrever versões  
existentes sem confirmação explícita do usuário ("Salvar").

\#\#\# 7.3 Versionamento Manual (RF12)

\*\*Passos:\*\*  
1\. Usuário clica em "Salvar" no editor.  
2\. Backend busca estado atual do \`Document.content\` na memória/DB.  
3\. Cria novo registro em \`document\_versions\` com \`version\_number \= max \+ 1\`.  
4\. Copia conteúdo atual (do Content) para \`content\_snapshot\` do novo version.  
5\. Atualiza \`documents.current\_version\_id\` para o novo snapshot.  
6\. Extrai novas sentenças e insere/regenera em \`sentences\`.

\*\*Regra:\*\* Versões manuais criam snapshot completo, não incremental (delta). Autosave nunca cria versões.

\#\#\# 7.4 Restauração de Versão Anterior (RF13)

\*\*Passos:\*\*  
1\. Usuário seleciona versão específica no histórico.  
2\. Backend busca registro em \`document\_versions\` pelo ID da versão.  
3\. Atualiza \`documents.content \= version.content\_snapshot\`.  
4\. Cria nova versão com número incrementado para manter integridade temporal (versão de restauração).

\*\*Regra:\*\* Restaurar sempre cria nova versão, não sobrescreve histórico diretamente.

\#\#\# 7.5 Busca de Evidências (RF19)

\*\*Passos:\*\*  
1\. Usuário posiciona cursor sobre sentença e clica em "Encontrar Evidências".  
2\. Backend recebe ID da sentença via API ou evento do editor (contexto da versão atual).  
3\. Chama \`EvidenceService.search(sentence\_text)\`.  
4\. Mock retorna 5 referências pré-definidas (simuladas).  
5\. Cria registros em \`evidence\_suggestions\` com status PENDING vinculados ao \`document\_version\_id\` atual.

\*\*Mock V1:\*\* Retorna sempre mesmas 5 referências para qualquer sentença, exceto palavras-chave específicas.

\#\#\# 7.6 Aprovação de Referência (RF21/RF22)

\*\*Passos:\*\*  
1\. Usuário clica em "Aprovar" ou "Rejeitar" na sugestão.  
2\. Backend atualiza \`evidence\_suggestions.status\` para APPROVED ou REJECTED.  
3\. Se aprovado: Cria \`QualityIssue\` se necessário (ex: falta evidência resolvida).

\*\*Regra:\*\* Aprovação não cria nova versão do documento automaticamente, apenas atualiza metadados na versão  
corrente.

\#\#\# 7.7 Geração de Grounding Report (RF23)

\*\*Passos:\*\*  
1\. Após aprovação/rejeição ou análise manual.  
2\. Backend calcula: \`supported\_count\`, \`unsupported\_count\`, etc.  
3\. Insere/atualiza registro em \`grounding\_reports\` com timestamp atual.  
4\. Atualiza coluna \`documents.grounding\_score\` (média ponderada \- cache).

\*\*Regra:\*\* Não calcular dinamicamente na query SQL. Sempre persistir relatório explícito.

\#\#\# 7.8 Exportação de Documento (RF26/RF27/RF28)

\*\*Passos:\*\*  
1\. Usuário seleciona formato de exportação (BibTeX, ABNT, APA).  
2\. Backend busca referências associadas ao documento via \`evidence\_suggestions\`.  
3\. Usa biblioteca \`pybtex\` ou similar para gerar string formatada.  
4\. Cria arquivo temporário em \`/tmp/\` ou gera conteúdo direto para download.

\*\*Regra:\*\* Nunca persistir arquivos exportados no banco SQLite (limitação do SDD). Usar sistema de arquivos  
temporário.

\#\#\# 7.9 Importação de Documento (RF06)

\*\*Passos:\*\*  
1\. Usuário seleciona arquivo DOCX/PDF para upload.  
2\. Backend converte via biblioteca \`python-docx\` ou \`pdfplumber\`.  
3\. Extrai texto e formata como Markdown interno.  
4\. Segue fluxo de criação de documento (UC05).

\*\*Regra:\*\* Converter sempre para formato internal (Markdown), não armazenar DOCX/PDF bruto no banco.

\---

\#\# 8\. API REST Completa

\#\#\# 8.1 Autenticação e Projetos

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| \*\*POST\*\* | \`/api/auth/login\` | Login simples (Sessão Cookie) | \`{username, password}\` | \`{user\_id, username}\` \+  
Set-Cookie | 401 Unauthorized |  
| GET | \`/api/projects\` | Listar projetos do usuário | \- | \`\[{id, name, created\_at}\]\` | \- |  
| POST | \`/api/projects\` | Criar novo projeto | \`{name, description}\` | Project object \+ 201 Created | 400 Bad  
Request |

\#\#\# 8.2 Documentos e Versões

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| GET | \`/api/projects/{project\_id}/documents\` | Listar documentos do projeto | \- | \`\[{id, title,  
grounding\_score}\]\` | \- |  
| POST | \`/api/projects/{project\_id}/documents\` | Criar documento novo | \`{title, content}\` | Document object \+  
201 Created | 400 Bad Request |  
| GET | \`/api/documents/{document\_id}\` | Obter detalhes do documento (última versão) | \- | Document completo com  
versões | 404 Not Found |  
| \*\*PUT\*\* | \`/api/documents/{document\_id}/content\` | \*\*Salvar Documento (Cria Versão)\*\* | \`{markdown\_content}\` |  
Success message \+ new version info | 400 Bad Request |  
| POST | \`/api/documents/{document\_id}/version\` | Criar nova versão manual explícita | \`{description}\` | Version  
object \+ 201 Created | \- |  
| GET | \`/api/documents/{document\_id}/versions\` | Listar histórico de versões | \- | \`\[{id, version\_number,  
created\_at}\]\` | \- |  
| POST | \`/api/documents/{document\_id}/restore/{version\_id}\` | Restaurar versão específica | \- | Success message \+  
new version info | 404 Not Found |

\#\#\# 8.3 Sentenças e Evidências

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| GET | \`/api/documents/{document\_id}/sentences\` | Listar sentenças do documento (última versão) | \- | \`\[{id,  
text, status}\]\` | \- |  
| POST | \`/api/sentences/search/evidence\` | Buscar evidências para sentença atual | \`{}\` (mock) | \`\[{reference\_id,  
title, authors}\]\` | 404 Not Found |  
| \*\*PUT\*\* | \`/api/evidence-suggestions/{suggestion\_id}\` | Aprovar/Rejeitar sugestão | \`{status:  
APPROVED\\|REJECTED}\` | Success message \+ updated suggestion | \- |

\#\#\# 8.4 Referências e Biblioteca

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| GET | \`/api/references\` | Listar referências (global ou projeto) | \`{project\_id: optional}\` | \`\[{id, title,  
authors}\]\` | \- |  
| POST | \`/api/references\` | Adicionar nova referência manual | Reference object | Reference \+ 201 Created | 400  
Bad Request |  
| PUT | \`/api/references/{reference\_id}\` | Editar referência existente | Partial Update | Updated reference | 404  
Not Found |  
| DELETE | \`/api/references/{reference\_id}\` | Remover referência | \- | Success message \+ 204 No Content | 404 Not  
Found |

\#\#\# 8.5 Grounding e Qualidade

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| GET | \`/api/documents/{document\_id}/grounding\` | Obter relatório de fundamentação (último) | \- | \`\[{supported,  
unsupported}, score\]\` | 404 Not Found |  
| POST | \`/api/documents/{document\_id}/analyze\` | Forçar reanálise do documento | \`{}\` (trigger) | GroundingReport  
object \+ 201 Created | \- |

\#\#\# 8.6 Exportação e Histórico

| Método | Rota | Descrição | Payload | Resposta | Erros |  
|--------|------|-----------|---------|----------|-------|  
| GET | \`/api/documents/{document\_id}/export/bibtex\` | Exportar em BibTeX | \- | File download (BibTeX) | 404 Not  
Found |  
| GET | \`/api/documents/{document\_id}/export/abnt\` | Exportar em ABNT | \- | File download (ABNT) | 404 Not Found |

\#\#\# 8.7 Códigos de Erro Padrão

| Código HTTP | Descrição | Quando Usar |  
|-------------|-----------|--------------|  
| 200 OK | Sucesso da operação | Resposta padrão |  
| \*\*201 Created\*\* | Recurso criado com sucesso (ex: nova versão) | POST/PUT que cria recurso |  
| 400 Bad Request | Payload inválido (schema Pydantic) | Validação falhou |  
| 401 Unauthorized | Credenciais inválidas ou ausentes | Login falhou, sessão expirada |  
| \*\*403 Forbidden\*\* | Acesso não autorizado ao recurso | Usuário sem permissão no projeto |  
| 404 Not Found | Recurso não encontrado | ID inexistente |  
| 500 Internal Server Error | Erro inesperado no servidor | Bug, exceção não tratada |

\---

\#\# 9\. Estrutura Definitiva do Projeto (V1)

\`\`\`text  
vibescholar/  
├── app.py                     \# Entry Point FastAPI \+ NiceGUI (Sessões Cookies)  
├── config.py                  \# Configurações globais (DB path, SECRET\_KEY)  
├── main\_db.py                 \# Inicialização DB e Seeders  
│  
├── models/                    \# SQLAlchemy Models (Domínio \+ Infra)  
│   ├── \_\_init\_\_.py           \# Importa todos os modelos publicamente  
│   ├── user.py               \# User, Project (auth \- Session support)  
│   ├── document.py           \# Document, Sentence, GroundingReport, QualityIssue  
│   └── reference.py          \# Reference, EvidenceSuggestion (FK para Version)  
│  
├── schemas/                   \# Pydantic Schemas (Validação de Inputs)  
│   ├── request.py            \# DTOs para criação/editação  
│   └── response.py           \# DTOs para outputs formatados  
│  
├── services/                  \# Lógica de Negócio Pura  
│   ├── evidence\_service.py    \# MockEvidenceService (V1), OpenAlexFuture (V2)  
│   ├── export\_service.py      \# BibTeX, ABNT, APA (Strategy pattern)  
│   └── quality\_analyzer.py    \# Cálculo de métricas de qualidade  
│  
├── routers/                   \# Roteamento API FastAPI  
│   ├── auth.py               \# Login simples / Sessão Cookie  
│   ├── documents.py          \# CRUD documentos, sentenças (Commit explícito)  
│   ├── references.py         \# CRUD referências  
│   └── grounding.py          \# GroundingReport endpoints  
│  
├── gui\_components/            \# Componentes NiceGUI (Interface)  
│   ├── editor.html           \# Quill/TinyMCE via iframe (Asset estático)  
│   └── evidence\_panel.html   \# Painel de sugestões (Template básico)  
│  
└── utils/                     \# Utilitários e Helpers  
    ├── markdown.py           \# Processamento Markdown \<-\> Texto Puro  
    └── exporters.py          \# Formatação bibliográfica (pybtex)  
\`\`\`

\---

\#\# 10\. Responsabilidade de Cada Pasta

\#\#\# 10.1 models/  
\*\*Pode:\*\*  
\- Definir classes SQLAlchemy representando entidades do domínio.  
\- Estabelecer relacionamentos via \`relationship()\`.  
\- Adicionar métodos de classe para lógica de acesso a dados.

\*\*Não Pode:\*\*  
\- Contar lógica de negócio (ex: cálculo de score) → vai em services/.  
\- Renderizar HTML/UI → vai em gui\_components/.  
\- Validar inputs complexos → vai em schemas/.

\#\#\# 10.2 schemas/  
\*\*Pode:\*\*  
\- Definir Pydantic models para validação de requests/responses.  
\- Converter entre dados do banco e API payloads.

\*\*Não Pode:\*\*  
\- Executar lógica de negócio (ex: calcular score) → services/.  
\- Acessar banco diretamente → models/services/.

\#\#\# 10.3 services/  
\*\*Pode:\*\*  
\- Implementar lógica de negócio pura (mocks, cálculos, integrações).  
\- Usar injeção de dependência via FastAPI \`Depends()\`.

\*\*Não Pode:\*\*  
\- Renderizar UI → gui\_components/.  
\- Definir modelos do banco → models/.  
\- Expor endpoints HTTP diretamente → routers/.

\#\#\# 10.4 routers/  
\*\*Pode:\*\*  
\- Mapear endpoints HTTP para handlers de serviço.  
\- Validar permissões básicas (user\_id, project\_id).

\*\*Não Pode:\*\*  
\- Contar lógica de negócio complexa → services/.  
\- Renderizar HTML/UI → gui\_components/.  
\- Definir modelos do banco → models/.

\#\#\# 10.5 gui\_components/  
\*\*Pode:\*\*  
\- Renderizar componentes NiceGUI (editor, painéis).  
\- Carregar arquivos estáticos (HTML/CSS/JS externos) para o editor Quill.

\*\*Não Pode:\*\*  
\- Contar lógica de backend Python → services/models/.  
\- Persistir dados no banco → models/services/.

\#\#\# 10.6 utils/  
\*\*Pode:\*\*  
\- Funções utilitárias reutilizáveis (conversão Markdown, formatação BibTeX).  
\- Helpers para processamento de texto.

\*\*Não Pode:\*\*  
\- Definir entidades do domínio → models/.  
\- Implementar lógica de negócio principal → services/.

\---

\#\# 11\. Fluxo do Editor Completo

\#\#\# 11.1 Arquitetura do Editor (Quill \+ Delta \+ Markdown)

\`\`\`  
┌─────────────────────────────────────────────────────────────┐  
│                    NiceGUI Interface                         │  
│                                                              │  
│   ┌──────────────────────────────────────────────────────┐  │  
│   │              iframe com Quill.js (Rich Text)         │  │  
│   │                                                        │  │  
│   │   Usuário edita → Delta JSON no DOM do iframe        │  │  
│   │                                                        │  │  
│   └──────────────────────────────────────────────────────┘  │  
│                      ↓ (Evento de Salvamento)                │  
└─────────────────────────────────────────────────────────────┘  
                              ↓  
┌─────────────────────────────────────────────────────────────┐  
│                    Backend FastAPI                           │  
│                                                              │  
│   ┌──────────────────┐  ┌─────────────────────────────────┐ │  
│   │ Delta → Markdown │  │ Extração de Sentenças Automática │ │ (Apenas ao Salvar)  
│   │ (markdownify)    │  │ (regex ou parser simples)        │ │  
│   └──────────────────┘  └─────────────────────────────────┘ │  
│                                                              │  
│   ↓ Persistência                                             │  
│   ┌───────────────────────────────────────────────────────┐│  
│   │ documents.content \= Markdown (texto estruturado)      ││  
│   │ sentences.text \= Extraído do Markdown                  ││  
│   └───────────────────────────────────────────────────────┘│  
└─────────────────────────────────────────────────────────────┘  
                              ↓  
┌─────────────────────────────────────────────────────────────┐  
│                    Lógica de Grounding                       │  
│                                                              │  
│   Sentenças UNVERIFIED → EvidenceService.search()           │  
│   Sugestões aprovadas → QualityIssue resolvido              │  
│   GroundingReport recalculado                                │  
└─────────────────────────────────────────────────────────────┘  
\`\`\`

\#\#\# 11.2 Por que Markdown e não Delta Bruto?

| Critério | Delta JSON | Markdown | Decisão |  
|----------|-------------|-----------|---------|  
| Edição no Editor | Nativo (Quill) | Via iframe/overlay | Quill usa Delta, mas convertemos para UI |  
| Processamento IA | Difícil (formato binário) | Fácil (texto plano) | \*\*Markdown\*\* |  
| Extração de Sentenças | Complexa (parsear JSON estruturado) | Simples (regex em texto) | \*\*Markdown\*\* |  
| Exportação BibTeX/ABNT | Dificulta formatação | Facilita geração de strings | \*\*Markdown\*\* |  
| Versionamento/Diffs | Difícil comparar versões binárias | Fácil diff entre textos | \*\*Markdown\*\* |

\#\#\# 11.3 Extração Automática de Sentenças

\`\`\`python  
\# Pseudocódigo para extração no backend (Executado apenas ao Salvar)  
def extract\_sentences(markdown\_content: str, version\_id: int):  
    sentences \= \[\]

    \# Dividir por parágrafos e depois por linhas/sentenças  
    paragraphs \= markdown.split('\\n\\n')  
    paragraph\_number \= 1

    for i, para in enumerate(paragraphs):  
        if not para.strip():  
            continue

        sentence\_number \= 0

        \# Split em sentenças (pontos finais com espaços)  
        raw\_sentences \= re.split(r'(?\<=\[.\!?\])\\s+', para)

        for sent in raw\_sentences:  
            sent\_cleaned \= sent.strip()

            if len(sent\_cleaned) \> 50:  \# Ignora fragmentos muito curtos  
                sentence\_number \+= 1

                sentences.append(Sentence(  
                    text=sent\_cleaned,  
                    paragraph\_number=paragraph\_number,  
                    sentence\_number=sentence\_number,  
                    status='UNVERIFIED'  \# Default inicial  
                ))

        paragraph\_number \+= 1

    return sentences  
\`\`\`

\#\#\# 11.4 Renderização no Frontend

\*\*Fluxo de Leitura:\*\*  
1\. Backend retorna \`documents.content\` (Markdown) em resposta API.  
2\. NiceGUI renderiza Markdown como HTML seguro via \`markdownify()\`.  
3\. Quill carrega conteúdo inicial via API REST.  
4\. Editor mantém estado local e sincroniza com backend a cada edição.

\*\*Regra:\*\* Nunca retornar Delta JSON para frontend de leitura. Sempre Markdown → HTML → UI.

\---

\#\# 12\. Arquitetura Preparada para IA Futura (V2+)

\#\#\# 12.1 Integração com OpenAlex/Semantic Scholar/Crossref

\*\*Preparação Atual:\*\*  
\- \`EvidenceService\` é substituído por implementação real sem mudar assinatura do método.  
\- Mock retorna dados fixos; V2+ chama API externa via \`requests\` ou async HTTP client.

\`\`\`python  
\# Pseudocódigo para troca de implementação  
def get\_evidence\_service():  
    if config.USE\_MOCK:  
        return MockEvidenceService()  \# V1  
    else:  
        return OpenAlexEvidenceService()  \# V2+  
\`\`\`

\*\*Impacto:\*\* Nenhuma refatoração necessária. Apenas substituir objeto retornado por factory function.

\#\#\# 12.2 Integração com RAG e Embeddings

\*\*Preparação Atual:\*\*  
\- \`Sentence\` armazena texto em formato limpo (Markdown extraído).  
\- Futuramente: Adicionar coluna \`embedding\_vector\` ao modelo \`Sentence\` se usar SQLite-Vec.  
\- Ou separar para banco vetorial externo (ChromaDB/Weaviate)

\`\`\`python  
\# Modelo preparado para embeddings futuros  
class Sentence(Base):  
    text \= Column(Text)  \# Texto plano atual  
    embedding\_vector \= Column(Float, nullable=True)  \# NULL até V2+

\# Query futura com RAG:  
def search\_semantic(sentence\_embedding: List\[float\]):  
    if config.USE\_RAG:  
        return db.query(Sentence).filter(  
            cosine\_similarity(embedding\_vector, sentence\_embedding) \> threshold  
        ).all()  
\`\`\`

\#\#\# 12.3 Integração com LLMs para Análise

\*\*Preparação Atual:\*\*  
\- \`QualityAnalyzer\` calcula métricas via mock (contagens simples).  
\- V2+: Chama API de LLM para análise semântica profunda.

\`\`\`python  
\# Pseudocódigo para troca de implementação  
def analyze\_quality(sentence: str):  
    if config.USE\_LLM:  
        return llm\_analyze(sentence)  \# V2+  
    else:  
        return mock\_analyze(sentence)  \# V1  
\`\`\`

\#\#\# 12.4 Integração com MCP (Model Context Protocol)

\*\*Preparação Atual:\*\*  
\- Endpoints REST expõem dados de forma padronizada.  
\- V2+: Criar wrapper que expõe endpoints como ferramentas MCP via FastAPI middleware.

\*\*Regra:\*\* Não preparar estrutura específica para MCP agora. Apenas garantir que API seja RESTful e bem  
documentada.

\#\#\# 12.5 Banco Vetorial Futuro

\*\*Preparação Atual:\*\*  
\- SQLite atual não suporta vetores nativos (sem sqlite-vec).  
\- V2+: Migrar embeddings para ChromaDB/Weaviate via script de migração.  
\- Dados relacionais permanecem em SQLite; vetores em banco externo.

\`\`\`python  
\# Estratégia híbrida futura  
class Sentence(Base):  \# Metadados no SQLite  
    text \= Column(Text)

\# Banco vetorial separado (ChromaDB):  
\# embeddings/sentence\_embeddings.pkl ou ChromaDB instance  
\`\`\`

\---

\#\# 13\. Architecture Decision Records (ADR)

\#\#\# ADR001: SQLite vs PostgreSQL/MySQL

\*\*Decisão:\*\* SQLite  
\*\*Data:\*\* \[DATA\]  
\*\*Status:\*\* Congelado para V1

\*\*Contexto:\*\* Projeto acadêmico com único desenvolvedor, necessidade de portabilidade e simplicidade inicial.

\*\*Alternativas Consideradas:\*\*  
\- \*\*PostgreSQL:\*\* Melhor performance em escala, mas requer instalação, configuração de serviços, backup mais  
complexo.  
\- \*\*MySQL/MariaDB:\*\* Similar a PostgreSQL, overhead desnecessário para V1.

\*\*Decisão Técnica:\*\* SQLite é suficiente para \<50MB de dados e \<50 usuários concorrentes (NFR ajustado). Arquivo  
único \`.db\` facilita deploy local e demonstração em Hugging Face Spaces. Backup externo gerencia o volume. \*\*Modo  
WAL ativado para suportar autosave frequente.\*\*

\---

\#\#\# ADR002: FastAPI vs Flask/Django/Quart

\*\*Decisão:\*\* FastAPI  
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* Python, tipagem forte, integração com NiceGUI, async support futuro.

\*\*Alternativas Consideradas:\*\*  
\- \*\*Flask:\*\* Simples mas sem validação automática (Pydantic) e documentação Swagger nativa.  
\- \*\*Django:\*\* Muito pesado para MVP acadêmico, ORM complexo demais.  
\- \*\*Quart:\*\* Async similar a FastAPI mas menos maduro e comunidade menor.

\*\*Decisão Técnica:\*\* FastAPI oferece validação automática via Pydantic, documentação Swagger/Redoc nativa,  
performance excelente e integração fácil com async (futuro RAG/LLMs).

\---

\#\#\# ADR003: SQLAlchemy ORM vs Raw SQL/AIOM

\*\*Decisão:\*\* SQLAlchemy ORM  
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* Python, tipagem forte, necessidade de relacionamentos claros.

\*\*Alternativas Consideradas:\*\*  
\- \*\*Raw SQL:\*\* Flexibilidade mas sem tipagem automática e validação.  
\- \*\*AIOM (AsyncIO Models):\*\* Melhor para async mas mais complexo para V1.

\*\*Decisão Técnica:\*\* SQLAlchemy oferece balanceamento ideal entre simplicidade e poder. Relacionamentos explícitos  
ajudam na manutenção futura.

\---

\#\#\# ADR004: NiceGUI vs React/Vue/Streamlit

\*\*Decisão:\*\* NiceGUI  
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* Python puro, prototipagem rápida, integração com FastAPI backend.

\*\*Alternativas Consideradas:\*\*  
\- \*\*React/Vue:\*\* Requer setup de build (npm), separação frontend/backend complexa para V1.  
\- \*\*Streamlit:\*\* Focado em apps de dados, não editores ricos como Quill.

\*\*Decisão Técnica:\*\* NiceGUI permite renderização rápida com Python e suporte nativo a componentes web via  
iframe/HTML. Ideal para MVP local sem necessidade de build chain complexo.

\---

\#\#\# ADR005: Autenticação Sessão vs JWT (V1)

\*\*Decisão:\*\* Cookies HttpOnly (Sessões Servidor)  
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* Aplicação Single Instance, SQLite, MVP Acadêmico.

\*\*Alternativas Consideradas:\*\*  
\- \*\*JWT Stateless:\*\* Requer validação de token em cada requisição, gerenciamento de expiração complexo para logout  
imediato sem backend centralizado.  
\- \*\*Sessão (Cookies):\*\* Gerenciado pelo servidor FastAPI (\`SECRET\_KEY\`), ideal para apps locais onde o usuário não  
precisa carregar sessão em múltiplos dispositivos simultaneamente sem login manual repetido.

\*\*Decisão Técnica:\*\* Para V1, sessões via Cookies são mais simples e seguras para um ambiente local/acadêmico.  
Rate Limiting protege contra ataques de força bruta. JWT reservado para V2 se escalar para multi-instance ou  
mobile app off-line complexo. \*\*CSRF Protection ativada.\*\*

\---

\#\#\# ADR006: Autosave vs Commit Explícito (Draft)

\*\*Decisão:\*\* Autosave com Debounce em Document.content \+ Versionamento Explícito   
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* O sistema utiliza SQLite como banco de dados e deve preservar a integridade das versões do documento sem gerar escrita excessiva. 

\*\*Alternativas Consideradas:\*\*  
\- \*\*Salvar uma nova DocumentVersion a cada alteração:\*\* Descartado por gerar excesso de versões e aumentar o custo de escrita.   
\- \*\*Draft em memória ou Redis:\*\* Descartado por adicionar complexidade desnecessária ao MVP e dificultar a recuperação do estado atual após reinicialização da aplicação.   
\- \*\*Autosave direto em Document.content com debounce:\*\* Escolhido por oferecer simplicidade e preservar sempre o estado atual do documento. 

\*\*Decisão Técnica:\*\*   
Durante a edição, o sistema atualiza apenas o campo \`Document.content\` utilizando debounce de aproximadamente 2–3 segundos.  
Esse salvamento automático representa apenas o estado atual do documento e nunca cria uma nova \`DocumentVersion\`.  
Uma nova \`DocumentVersion\` é criada exclusivamente quando o usuário executa a ação "Salvar Versão" ou "Restaurar Versão".   
Dessa forma:

\- \`Document.content\` representa sempre a versão de trabalho atual.  
\- \`DocumentVersion\` representa apenas snapshots históricos.  
\- O histórico permanece limpo, enquanto o usuário nunca perde o estado atual do documento entre edições. 

\---

\#\#\# ADR007: Vinculação de Evidências (Sentence ID vs Version)

\*\*Decisão:\*\* FK para \`DocumentVersion\` \+ UUID da Sentença  
\*\*Data:\*\* \[DATA\]

\*\*Contexto:\*\* Edição frequente do texto, regeneração de sentenças.

\*\*Alternativas Consideradas:\*\*  
\- \*\*FK para Document.id:\*\* Perde-se o contexto temporal se a versão mudar (IDs mudam).  
\- \*\*FK para Version.id \+ UUID:\*\* Garante que uma evidência aprovada em um snapshot específico permaneça válida e  
rastreável, mesmo com edições futuras.

\*\*Decisão Técnica:\*\* \`EvidenceSuggestion\` vincula-se diretamente ao registro de \`DocumentVersion\`. A sentença  
dentro da versão é identificada por um índice ou UUID gerado no momento do commit. Isso evita perda de histórico  
de fundamentação quando o texto é editado e novas versões são criadas.  
