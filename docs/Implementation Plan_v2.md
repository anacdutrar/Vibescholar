# Implementation Plan \- VibeScholar v2 (Revised Architecture)

Implementation plan for VibeScholar v1, a monolithic web platform for scientific writing with local versioning, sentence grounding, and reference suggestion mocks.

## Architectural Guidelines & Resolved Design Decisions

We have updated the design of the application to include the following core enhancements:

1. **Layered Architecture (Router → Service → Repository → DB)**:  
   * We introduce a dedicated repositories layer to isolate database queries from the business logic.  
   * Database operations (including soft delete logic) will be encapsulated within repositories.  
2. **ProjectSettings**:  
   * Every project will have a corresponding ProjectSettings record in the database.  
   * These settings specify preferred languages, min/max years, minimum Qualis score, and open access preferences.  
   * The EvidenceService will parse these settings to filter search suggestions.  
3. **Sentence UUID Stability via Equivalence Matching**:  
   * Sentences are parsed from DocumentVersion.  
   * We reuse the sentence\_uuid from the previous version for equivalent sentences (calculated by checking normalized text comparison). Otherwise, a new UUID is generated.  
4. **Soft Delete**:  
   * The Project, Document, and ProjectReference models will contain a deleted\_at field. Database deletions will be logic-based (soft deleted) rather than hardware-based.  
5. **QualityIssue Version Scope**:  
   * QualityIssue will include document\_version\_id to prevent issues resolved in newer versions from displaying on historical versions.  
6. **NiceGUI-Python Events**:  
   * We will use NiceGUI's native JS bridge (Socket.IO wrapped event triggers) to handle editor interactions cleanly without requiring manual WebSocket boilerplate.

---

## Directory Structure

The project will reside at C:/Users/a.ramos\\Desktop\\VibeScholar and will follow the structure below:  
text  
vibescholar/  
└── app/  
   ├── config/                 \# YAML or configuration template resources  
   ├── core/                   \# Security, configuration, logging setups  
   │   ├── security.py  
   │   ├── config.py  
   │   └── logging.py  
   ├── exceptions/             \# Custom exception classes  
   │   ├── auth.py  
   │   ├── document.py  
   │   └── reference.py  
   ├── models/                 \# SQLAlchemy domain models  
   │   ├── \_\_init\_\_.py  
   │   ├── user.py             \# User and Project  
   │   ├── document.py         \# Document, Sentence, Version, Grounding, Quality  
   │   ├── reference.py        \# ProjectReference and EvidenceSuggestion  
   │   └── project\_settings.py \# ProjectSettings model  
   ├── repositories/           \# Encapsulated query logic  
   │   ├── user\_repository.py  
   │   ├── project\_repository.py  
   │   ├── document\_repository.py  
   │   ├── reference\_repository.py  
   │   └── project\_settings\_repository.py  
   ├── services/               \# Pure business logic layer  
   │   ├── evidence\_service.py  
   │   ├── quality\_analyzer.py  
   │   ├── export\_service.py  
   │   └── import\_service.py   \# DOCX, Markdown, Text parser  
   ├── providers/              \# Search providers (Mock, OpenAlex, Semantic Scholar)  
   │   ├── interfaces.py       \# Provider interface definitions  
   │   ├── mock\_provider.py    \# V1 Mock implementation  
   │   ├── openalex\_provider.py  
   │   └── semantic\_scholar\_provider.py  
   ├── routers/                \# FastAPI API endpoints  
   │   ├── auth.py  
   │   ├── documents.py  
   │   ├── references.py  
   │   └── grounding.py  
   ├── schemas/                \# Pydantic input/output schemas  
   │   ├── request.py  
   │   └── response.py  
   ├── utils/                  \# Helper modules  
   │   ├── markdown.py  
   │   ├── text\_normalizer.py  
   │   ├── sentence\_splitter.py  
   │   └── validators.py  
   ├── gui/                    \# NiceGUI page layouts and component hooks  
   │   └── views.py  
   ├── static/                 \# Static CSS, JS resources  
   ├── templates/              \# HTML layout templates (e.g. Quill Editor frame)  
   └── tests/                  \# Pytest test cases  
---

## Detailed Component Specifications

### 1\. Database Schema & Models

* **ProjectSettings (app/models/project\_settings.py)**:  
  * id (PK, Integer)  
  * project\_id (FK to projects.id)  
  * preferred\_language (String)  
  * minimum\_qualis (String/Float)  
  * publication\_year\_min (Integer)  
  * publication\_year\_max (Integer)  
  * preferred\_sources (Text/JSON)  
  * only\_open\_access (Boolean)  
  * prefer\_doi (Boolean)  
  * max\_suggestions (Integer)  
  * created\_at (DateTime)  
  * updated\_at (DateTime)  
* **Soft Delete Fields**:  
  * Project.deleted\_at, Document.deleted\_at, and ProjectReference.deleted\_at are nullable DateTimes.  
* **Indexes**:  
  * idx\_doc\_versions\_doc\_id on document\_versions(document\_id)  
  * idx\_sentences\_version\_id on sentences(document\_version\_id)  
  * idx\_sentences\_uuid on sentences(sentence\_uuid)  
  * idx\_evidence\_version\_id on evidence\_suggestions(document\_version\_id)  
  * idx\_evidence\_uuid on evidence\_suggestions(sentence\_uuid)  
  * idx\_project\_references\_project\_id on project\_references(project\_id)  
  * idx\_quality\_issues\_version\_id on quality\_issues(document\_version\_id)

### 2\. Core & Utilities

* **Security & Config (app/core/)**:  
  * security.py: Password hashing (bcrypt) and session cookie validation helpers.  
  * config.py: Environment loader with defaults, database URL config.  
  * logging.py: Structured Python logging config writing to console and local vibescholar.log.  
* **Utils (app/utils/)**:  
  * text\_normalizer.py: Normalizes text for matching (lowercase, strips spaces, removes punctuation .,\!?;:).  
  * sentence\_splitter.py: Clean sentence boundaries parser using regex and text formatting checks.  
  * markdown.py: Renders Markdown content safe for Quill HTML loader and vice-versa.  
  * validators.py: DOI, email, password validations.

### 3\. Repositories Layer (app/repositories/)

* Isolates SQLAlchemy sessions and querying. Exposes methods like get\_by\_id, list\_active, save, and custom filters.  
* Filters out records where deleted\_at is not null for soft deleted tables.

### 4\. Core Services & Provider Pattern

* **Providers (app/providers/)**:  
  * interfaces.py: Defines BaseEvidenceProvider.search(query, settings) returning structured suggestions.  
  * mock\_provider.py: Implements searching, applying criteria like publication years, Qualis restrictions, open access flags, and capping results up to max\_suggestions.  
* **Services (app/services/)**:  
  * evidence\_service.py: Dispatches queries to providers based on configuration.  
  * quality\_analyzer.py: Checks version grounding score, generates QualityIssue items scoped to document\_version\_id.  
  * import\_service.py:  
    * Handles text uploads (.docx, .md, .txt).  
    * Converts DOCX via python-docx, Markdown via markdown-it-py (or built-in text sanitization), returning clean Markdown.  
  * export\_service.py: Generates Markdown, DOCX, PDF, BibTeX, APA, and NBR 6023 (ABNT) string outputs.

### 5\. API Routers (app/routers/)

* **Document Import Route (POST /api/documents/import)**:  
  * Receives uploaded file, detects extension, delegates to ImportService, creates the Document object and returns the document ID.  
* **Save Content (PUT /api/documents/{id}/content)**:  
  * Updates Document.content directly (autosave/debounce).  
* **Save Version (POST /api/documents/{id}/version)**:  
  * Commits version snapshot, parses sentences, matches sentence equivalents with the previous version to reuse UUIDs, replicates approved citations, and writes grounding report logs.

### 6\. NiceGUI Interface (app/gui/)

* **Workspace tabs**:  
  * **Editor**: Multi-document selector and Quill iframe canvas. Autosaves on change.  
  * **Evidence Panel**: Sentence outline displaying evidence statuses (UNVERIFIED/SUPPORTED/OUTDATED), mock references tray with search/apply toggles.  
  * **Reference Library**: Interface to add references manually, upload CSV templates, or paste BibTeX libraries.  
  * **Settings**: Modifies the ProjectSettings fields, triggering updates to matching evidence parameters.  
* **Development Seed**:  
  * Automatically initializes SQLite, seeds the database with admin/admin123, a sample project with mock references, and an introductory grounding document showing unverified and supported statements.

---

## Verification Plan

### Automated Tests

* tests/test\_auth.py: Simple session validation.  
* tests/test\_document.py: Document creation, import parse verification, and autosave mapping.  
* tests/test\_versioning.py: Equivalence matching tests, confirming sentence\_uuid stability.  
* tests/test\_settings.py: Confirming evidence queries filter results according to settings fields.

### Manual Verification

1. Run application and verify the admin user auto-seeds.  
2. Select the seeded project and workspace.  
3. Import a .docx document and verify it renders in Quill.  
4. Open **Settings** tab, update Qualis levels, search evidence in the editor side panel, and verify filters are respected.  
5. Save a manual version, modify punctuation in the editor, save again, and check that suggestions remain approved.  
6. Export the final document to BibTeX, ABNT, and DOCX formats.
