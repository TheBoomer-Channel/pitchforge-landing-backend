"""Document Catalog — 27 documents across 8 categories for optional planning generation.

TASK-065: Users select which documents to generate via checkboxes in the Planning UI.
The pipeline accepts a `documents` list and generates only the selected ones.
"""

CATEGORIES = [
    {
        "id": "01_product",
        "label": "Product",
        "icon": "📋",
        "description": "Product vision, requirements, and functional specification",
        "documents": [
            {"id": "product_vision", "label": "Product Vision", "description": "Purpose, problem, market, value proposition, differentiators, initial scope", "priority": "P0"},
            {"id": "prd", "label": "PRD", "description": "Features, users, use cases, functional & non-functional requirements, acceptance criteria", "priority": "P0"},
            {"id": "memoria_funcional", "label": "Memoria Funcional", "description": "Modules, functional flows, states, business rules, expected behavior, exceptions", "priority": "P0"},
            {"id": "user_stories", "label": "User Stories / Backlog", "description": "Epics, user stories Given/When/Then, priorities P0/P1/P2", "priority": "P0"},
            {"id": "use_cases", "label": "Casos de Uso", "description": "Actors, preconditions, main flow, errors, expected results", "priority": "P1"},
        ],
    },
    {
        "id": "02_domain",
        "label": "Domain",
        "icon": "🧩",
        "description": "Domain model, entities, and business glossary",
        "documents": [
            {"id": "domain_model", "label": "Domain Model", "description": "Entities, relationships, business concepts", "priority": "P0"},
            {"id": "domain_glossary", "label": "Domain Glossary", "description": "Domain terms, definitions, synonyms — avoids business/dev miscommunication", "priority": "P1"},
        ],
    },
    {
        "id": "03_technical",
        "label": "Technical",
        "icon": "⚙️",
        "description": "Architecture, stack, database, and API specification",
        "documents": [
            {"id": "memoria_tecnica", "label": "Memoria Técnica", "description": "General architecture, components, technologies, infrastructure", "priority": "P0"},
            {"id": "sad", "label": "SAD (Software Architecture)", "description": "C4 diagrams, components, dependencies, communication, patterns used", "priority": "P0"},
            {"id": "adr", "label": "ADR (Architecture Decisions)", "description": "Key technical decisions: why PostgreSQL, why FastAPI, why each technology", "priority": "P1"},
            {"id": "database_design", "label": "Database Design", "description": "Tables, entities, relationships, indexes, migrations", "priority": "P0"},
            {"id": "api_spec", "label": "API Specification (OpenAPI)", "description": "Endpoints, request/response, errors, authentication", "priority": "P0"},
        ],
    },
    {
        "id": "04_ai",
        "label": "AI",
        "icon": "🤖",
        "description": "AI architecture, prompts, evaluation, and safety",
        "documents": [
            {"id": "ai_architecture", "label": "AI Architecture", "description": "Models used, providers, AI pipeline, fallback, costs, limits", "priority": "P0"},
            {"id": "prompt_engineering", "label": "Prompt Engineering Spec", "description": "Versioned prompts, instructions, output formats, validations", "priority": "P1"},
            {"id": "ai_evaluation", "label": "AI Evaluation", "description": "Test dataset, metrics, accuracy, known errors, regressions", "priority": "P2"},
            {"id": "ai_safety", "label": "AI Safety & Reliability", "description": "What AI can/cannot decide, limits, human review checkpoints", "priority": "P2"},
        ],
    },
    {
        "id": "05_integration",
        "label": "Integration",
        "icon": "🔌",
        "description": "External APIs, webhooks, and client integration guides",
        "documents": [
            {"id": "integration_guide", "label": "Integration Guide", "description": "External APIs, webhooks, connectors, integration flows", "priority": "P1"},
            {"id": "client_guide", "label": "Client Integration Guide", "description": "How to get API keys, examples, SDK, use cases (external doc)", "priority": "P2"},
        ],
    },
    {
        "id": "06_operations",
        "label": "Operations",
        "icon": "🛡️",
        "description": "Security, deployment, infrastructure, and runbooks",
        "documents": [
            {"id": "security", "label": "Security Document", "description": "Authentication, authorization, encryption, GDPR, retention", "priority": "P1"},
            {"id": "deployment", "label": "Deployment & Infrastructure", "description": "Environments, CI/CD, Docker, config, backups", "priority": "P1"},
            {"id": "runbook", "label": "Runbook Operativo", "description": "Monitoring, common errors, recovery, incidents", "priority": "P2"},
        ],
    },
    {
        "id": "07_business",
        "label": "Business",
        "icon": "💼",
        "description": "Pricing, go-to-market, and competitive analysis",
        "documents": [
            {"id": "pricing", "label": "Pricing & Packaging", "description": "Plans, limits, consumption, variable costs", "priority": "P0"},
            {"id": "gtm", "label": "Go To Market", "description": "ICP, channels, messaging, competition, positioning", "priority": "P1"},
            {"id": "competitor_analysis", "label": "Competitor Analysis", "description": "Differentiators, pain points, competitor pricing (from Research)", "priority": "P0"},
        ],
    },
    {
        "id": "08_quality",
        "label": "Quality",
        "icon": "✅",
        "description": "QA planning, test cases, and validation strategy",
        "documents": [
            {"id": "qa_plan", "label": "QA Plan", "description": "Functional, integration, API, and load testing strategy", "priority": "P1"},
            {"id": "test_cases", "label": "Test Cases", "description": "Concrete cases: normal flow, errors, edge cases", "priority": "P1"},
        ],
    },
]

# ── Pre-built selections ──────────────────────────────

MVP_MINIMUM_IDS = [
    "product_vision", "prd", "memoria_funcional", "user_stories",
    "domain_model",
    "memoria_tecnica", "sad", "database_design", "api_spec",
    "ai_architecture",
]

ALL_DOC_IDS = [
    doc["id"]
    for cat in CATEGORIES
    for doc in cat["documents"]
]


def get_document_label(doc_id: str) -> str:
    """Get human-readable label for a document ID."""
    for cat in CATEGORIES:
        for doc in cat["documents"]:
            if doc["id"] == doc_id:
                return doc["label"]
    return doc_id


def resolve_documents(selection: list[str] | None) -> list[str]:
    """Resolve document selection shortcuts.

    - None or empty → all documents
    - ['mvp'] → MVP minimum (10 docs)
    - ['all'] → all 27 docs
    - ['prd', 'sad', ...] → only those specified
    """
    if not selection:
        return ALL_DOC_IDS
    if "mvp" in selection:
        return MVP_MINIMUM_IDS
    if "all" in selection:
        return ALL_DOC_IDS
    # Filter valid IDs
    return [d for d in selection if d in ALL_DOC_IDS]
