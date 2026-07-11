# Implementation Plan \- VibeScholar v1

Implementation plan for VibeScholar v1, a monolithic web platform for scientific writing with local versioning, sentence grounding, and reference suggestion mocks.

## User Review Required

We have analyzed the Software Design Document (SDD) and aligned on the following simple, robust solutions to avoid overengineering:

1. **SQL Reserved Word Conflict (references table)**:  
   * **Problem**: REFERENCES is an SQL reserved keyword. Naming a table references causes syntax errors.  
   * **Resolution**: Rename the table to project\_references.  
2. **Circular/Nullability Dependency on Document and DocumentVersion**:  
   * **Problem**: Document has a foreign key to DocumentVersion (current\_version\_id), and DocumentVersion has a foreign key to Document (document\_id).  
   * **Resolution**: Make current\_version\_id nullable in documents. On document creation, insert it first with NULL, create the version, and then update current\_version\_id.  
3. **Invalid Constraint in projects**:  
   * **Problem**: The projects schema has UNIQUE(username, username), but username does not exist in projects.  
   * **Resolution**: Replace this constraint with UNIQUE(user\_id, name) so a user cannot create two projects with the same name.  
4. **NiceGUI JS-to-Python Integration**:  
   * **Resolution**: We will use NiceGUI's native JS execution (ui.run\_javascript) and element event emission. This leverages NiceGUI's built-in Socket.IO layer, meaning **no custom WebSockets or manual connection management** needs to be written. We will bind custom event listeners directly to Python callbacks.

---

## Architecture Decisions & Resolved Questions

### Q1: Sentence Versioning, sentence\_uuid Stability & Equivalence Matching

* **Design**:  
  * Sentence records are derived from DocumentVersion.  
  * When saving a new version:  
    1. We extract the new sentences from the content.  
    2. We normalize the text of each sentence (convert to lowercase, strip extra whitespace, and remove punctuation like .,\!?;:).  
    3. We fetch the sentences from the previous version of the document and normalize their text in the same way.  
    4. **Equivalence Check**: If a new sentence's normalized text matches a previous sentence's normalized text (e.g. "A IA revolucionou a medicina." matching "A IA revolucionou a medicina\!"), we **reuse the exact same sentence\_uuid**.  
    5. If no match is found, we generate a brand new sentence\_uuid using uuid.uuid4().  
    6. EvidenceSuggestion links to document\_version\_id, sentence\_uuid, and reference\_id.  
    7. **Auto-propagation**: We query the database for approved suggestions associated with the matched sentence\_uuids from the previous version. If found, we clone them for the new document\_version\_id, preserving approved references even across minor text edits.

### Q2: QualityIssue Scope (Including document\_version\_id)

* **Design**:  
  * Because sentence\_uuid is reused across multiple versions (whenever the sentence remains equivalent), QualityIssue records must be explicitly scoped to a version.  
  * We will add document\_version\_id to the QualityIssue table to ensure that active issues (like lack of evidence) are bound to a specific version scope, preventing issues resolved in newer versions from displaying on historical versions.

### Q3: Autosave vs Manual Versioning API

* **Design**:  
  * PUT /api/documents/{document\_id}/content \-\> Updates Document.content directly (called by the debounced autosave in the editor).  
  * POST /api/documents/{document\_id}/version \-\> Creates a snapshot in DocumentVersion from the current Document.content, extracts sentences, runs equivalence matching to assign sentence\_uuids, propagates approved suggestions, and updates grounding metrics.

---

## Proposed Changes

We will create a new directory C:/Users/\\a.ramos\\Desktop\\VibeScholar  for the project.

### Project Setup and Database

#### \[NEW\] config.py

* Configuration file loading environment variables (SECRET\_KEY, DATABASE\_URL).  
* Default SQLite database name: vibescholar.db.

#### \[NEW\] main\_db.py

* Setup SQLAlchemy engine (enabling WAL mode for SQLite to prevent locking).  
* Setup SessionLocal and Base.  
* Add DB seeders for a default user (admin/admin123) and basic Mock references.

#### \[NEW\] models/user.py

* User model (id, username, password\_hash, email, timestamps).  
* Project model (id, user\_id, name, description, timestamps, UNIQUE constraint on user\_id \+ name).

#### \[NEW\] models/document.py

* Document model (id, project\_id, title, description, current\_version\_id \[nullable\], grounding\_score, timestamps).  
* DocumentVersion model (id, document\_id, version\_number, content\_snapshot, created\_by, created\_at).  
* Sentence model (id, document\_version\_id, sentence\_uuid, paragraph\_number, sentence\_number, position, text, status).  
* GroundingReport model (id, document\_id, generated\_at, supported\_count, unsupported\_count, partial\_count, outdated\_count, contradictions\_count).  
* QualityIssue model (id, document\_id, document\_version\_id, sentence\_uuid \[nullable\], issue\_type, description, severity, created\_at).

#### \[NEW\] models/reference.py

* ProjectReference model (id, project\_id \[nullable\], title, authors, journal, year, doi, qualis\_score, abstract, availability).  
* EvidenceSuggestion model (id, document\_version\_id, sentence\_uuid, reference\_id, status, created\_at).

#### \[NEW\] models/**init**.py

* Expose all SQLAlchemy models.

### Pydantic Schemas

#### \[NEW\] schemas/request.py

* Pydantic models for user input validation (UserCreate, ProjectCreate, DocumentCreate, ReferenceCreate, EvidenceStatusUpdate).

#### \[NEW\] schemas/response.py

* Pydantic models for formatting responses (UserOut, ProjectOut, DocumentOut, DocumentVersionOut, SentenceOut, ReferenceOut, GroundingReportOut).

---

### Core Services

#### \[NEW\] services/evidence\_service.py

* Mock evidence search service returning 5 simulated references.  
* Checks sentence keywords (e.g. "neural networks", "RAG", "convolucional") to make suggestions feel slightly dynamic, otherwise falls back to a general pool of seed papers.

#### \[NEW\] services/quality\_analyzer.py

* Logic to recalculate document grounding score: supported\_count / total\_sentences.  
* Generates QualityIssue items (e.g., LACK\_OF\_EVIDENCE if sentence is UNVERIFIED).  
* Persists new GroundingReport records.

#### \[NEW\] services/export\_service.py

* Implements export logic formatting references into BibTeX, ABNT, and APA formats.

---

### API Routers

#### \[NEW\] routers/auth.py

* Simple password hashing and login/logout cookie handling.

#### \[NEW\] routers/documents.py

* CRUD for documents.  
* Endpoint PUT /api/documents/{document\_id}/content (autosave \- writes to Document.content without creating a version).  
* Endpoint POST /api/documents/{document\_id}/version (manual save \- creates snapshot version, extracts sentences, runs equivalence matching to assign sentence\_uuids, propagates approved suggestions, and updates grounding report/quality issues).  
* Version restoration, listing, and sentence lookup.

#### \[NEW\] routers/references.py

* CRUD for project and global references.

---

### UI Layer (NiceGUI)

#### \[NEW\] gui\_components/editor.html

* Quill editor HTML page.  
* Emits events back to Python using NiceGUI's standard JavaScript bridge (e.g. triggering an event handler when text changes).

#### \[NEW\] gui\_components/views.py

* Login UI view.  
* Dashboard / Project List view.  
* Main Workspace (Project Workspace):  
  * Document Selector.  
  * Active Editor Component (using iframe Quill).  
  * Sentences highlighting list / side panel.  
  * Evidence Suggestion drawer (Approve/Reject buttons, mock references list).  
  * Grounding Score dashboard & export options.  
  * Reference Library page (manual adding \+ CSV import interface).

---

#### \[NEW\] app.py

* FastAPI core application.  
* Integrates NiceGUI views and FastAPI routers.  
* Startup handler to initialize DB tables and insert seed data if empty.

---

## Verification Plan

### Automated Tests

* We will add validation unit tests (pytest) covering:  
  * Auth flow, project/document creation.  
  * Debounced autosave (updates Document.content only).  
  * Explicit save (creates version, hashes sentences, propagates approvals).  
  * Export utilities.

### Manual Verification

* Run the FastAPI/NiceGUI server.  
* Open the application in the web browser.  
* Perform the complete User Flow:  
  1. Register a new user and log in.  
  2. Create a project.  
  3. Create a document, edit it (confirming autosave in DB does not create a version).  
  4. Write a few sentences, click "Save" manually (confirming version creation and sentence parsing).  
  5. Select a sentence, click "Find Evidences", and see the 5 mocked references.  
  6. Approve/reject references and watch the Grounding Score update.  
  7. Export references/document content to BibTeX/ABNT.

