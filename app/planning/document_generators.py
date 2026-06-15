"""Document Generators — LLM-powered generation for all 27 document types.

TASK-065: Each document type has a template prompt that the LLM fills
using the research report data (competitors, market validation, etc.).
"""

import json
import logging
from app.research.models import ResearchReport
from app.services.llm import llm

logger = logging.getLogger(__name__)

# ── Prompt templates per document type ─────────────────

DOCUMENT_PROMPTS = {
    "product_vision": """You are a product strategist. Based on the research below, write a **Product Vision Document** for this startup.

**Research Summary:** {research_summary}

**Competitors found:** {competitor_names}

**Market validation:** {market_validation}

Generate a JSON object with these fields:
- purpose: Why this product exists (1-2 sentences)
- problem_statement: The core problem being solved
- target_market: Who it's for (specific segment)
- value_proposition: Unique value vs alternatives
- differentiators: List of 3-5 key differentiators vs competitors
- initial_scope: What's in scope for MVP
- out_of_scope: What's explicitly out of scope for MVP
- success_metrics: 3-5 measurable KPIs

Return ONLY valid JSON, no markdown.""",

    "user_stories": """You are a product owner. Based on the research below, write a **User Stories Backlog** for this startup.

**Idea:** {idea}
**Research Summary:** {research_summary}
**Competitor pain points:** {pain_points}

Generate a JSON object with:
- epics: List of 3-5 epics (high-level feature groups), each with:
  - id: EPIC-001, EPIC-002, etc.
  - title: Short name
  - description: 1-2 sentences
- stories: List of 10-15 user stories, each with:
  - id: US-001, US-002, etc.
  - epic_id: Which epic it belongs to
  - as_a: User role
  - i_want: What they want to do
  - so_that: Why (business value)
  - acceptance_criteria: List of 2-4 Given/When/Then criteria
  - priority: P0 / P1 / P2
  - effort_estimate: S / M / L / XL

Return ONLY valid JSON, no markdown.""",

    "use_cases": """You are a systems analyst. Based on the research below, write **Use Cases** for this startup's core functionality.

**Idea:** {idea}
**Research Summary:** {research_summary}
**MVP Features:** {mvp_features}

Generate a JSON object with:
- use_cases: List of 3-5 use cases, each with:
  - id: UC-001, UC-002, etc.
  - name: Descriptive name
  - actor: Who performs this action
  - preconditions: What must be true before
  - main_flow: Array of numbered steps (5-10 steps)
  - alternative_flows: Array of {condition: "...", steps: [...]}
  - error_scenarios: Array of {error: "...", handling: "..."}
  - postconditions: What is true after success

Return ONLY valid JSON, no markdown.""",

    "domain_model": """You are a domain modeling expert. Based on the startup idea below, create a **Domain Model** defining the core business entities and their relationships.

**Idea:** {idea}
**Research Summary:** {research_summary}

Generate a JSON object with:
- entities: List of 5-10 core business entities, each with:
  - name: Entity name (e.g., User, Project, Order)
  - description: What it represents in the business
  - key_attributes: Array of {name: "...", type: "...", description: "..."}
  - relationships: Array of {with: "OtherEntity", type: "one-to-many"/"many-to-many"/"one-to-one", description: "..."}
- core_concepts: List of 3-5 abstract business concepts (e.g., Subscription, Billing Cycle)
- domain_events: List of 3-5 key domain events (e.g., UserRegistered, ProjectCreated)

Return ONLY valid JSON, no markdown.""",

    "domain_glossary": """You are a technical writer. Create a **Domain Glossary** for the startup below, defining all domain-specific terms.

**Idea:** {idea}

Generate a JSON object with:
- terms: List of 10-20 domain terms, each with:
  - term: The term
  - definition: Clear, concise definition (1-3 sentences)
  - category: "core" / "technical" / "business" / "integration"
  - synonyms: Array of alternative terms or abbreviations
  - used_in: Which context this term appears in

Return ONLY valid JSON, no markdown.""",

    "sad": """You are a software architect. Based on the startup idea and tech stack below, create a **Software Architecture Document (SAD)** following the C4 model.

**Idea:** {idea}
**Research Summary:** {research_summary}

Generate a JSON object with:
- architecture_style: Overall style (e.g., "modular monolith", "microservices", "event-driven")
- c4_level1_system_context: Description of the system and its external actors/users
- c4_level2_containers: Array of containers (apps, services, databases), each with:
  - name: Container name
  - type: "web-app" / "api" / "database" / "worker" / "cache" / "cdn"
  - technology: Specific technology recommendation
  - description: What it does
  - interacts_with: Array of container names it talks to
- c4_level3_components: Array of key components within the main API, each with:
  - name: Component name
  - responsibility: What it handles
  - technology: Framework/library
- design_patterns: Array of patterns used (e.g., "Repository", "CQRS", "Event sourcing")
- cross_cutting: Array of cross-cutting concerns (auth, logging, monitoring, etc.)

Return ONLY valid JSON, no markdown.""",

    "adr": """You are a software architect. Create **Architecture Decision Records (ADRs)** for the startup below, justifying key technology choices.

**Idea:** {idea}

Generate a JSON object with:
- decisions: Array of 5-8 architecture decisions, each with:
  - id: ADR-001, ADR-002, etc.
  - title: Decision title (e.g., "Use PostgreSQL as primary database")
  - context: Why this decision was needed
  - decision: What was decided
  - alternatives_considered: Array of {name: "...", pros: [...], cons: [...]}
  - consequences: Positive and negative consequences
  - status: "accepted" / "proposed" / "superseded"

Return ONLY valid JSON, no markdown.""",

    "database_design": """You are a database architect. Based on the domain model and idea below, create a **Database Design Document**.

**Idea:** {idea}
**Research Summary:** {research_summary}

Generate a JSON object with:
- tables: Array of 5-12 tables, each with:
  - name: Table name (snake_case)
  - description: What it stores
  - columns: Array of {name: "...", type: "VARCHAR(255)"/"INTEGER"/"BOOLEAN"/"TIMESTAMP"/"JSONB"/"UUID", nullable: true/false, primary_key: true/false, description: "..."}
  - indexes: Array of {name: "...", columns: [...], unique: true/false}
  - foreign_keys: Array of {column: "...", references: "other_table.column"}
- database_type: "PostgreSQL" / "MongoDB" / "SQLite" / etc.
- migration_strategy: How to handle schema evolution
- estimated_growth: Rough table size estimates (rows at 1K/10K/100K users)

Return ONLY valid JSON, no markdown.""",

    "api_spec": """You are an API designer. Based on the startup below, create an **API Specification** with endpoints.

**Idea:** {idea}
**Research Summary:** {research_summary}
**MVP Features:** {mvp_features}

Generate a JSON object with:
- base_url: Suggested base URL
- auth_method: "JWT Bearer" / "API Key" / "OAuth2"
- endpoints: Array of 8-15 endpoints, each with:
  - method: GET/POST/PUT/DELETE
  - path: /api/v1/resource
  - description: What it does
  - auth_required: true/false
  - rate_limit: e.g., "100/hour"
  - request_body: JSON schema (or null for GET)
  - response_200: JSON schema
  - error_responses: Array of {code: 400/401/404/429/500, description: "..."}
- pagination: How lists are paginated
- versioning: API versioning strategy

Return ONLY valid JSON, no markdown.""",

    "ai_architecture": """You are an AI architect. Based on the startup idea below, design the **AI Architecture** for features that require LLM/ML.

**Idea:** {idea}
**Research Summary:** {research_summary}

Generate a JSON object with:
- ai_features: Array of AI-powered features, each with:
  - name: Feature name
  - description: What AI does
  - model_recommendation: e.g., "GPT-4o", "Claude 3.5 Sonnet", "Mistral Large"
  - provider: "OpenAI" / "Anthropic" / "self-hosted" / "mixed"
  - fallback_model: Backup model if primary fails
  - prompt_strategy: How prompts are structured
  - estimated_tokens_per_call: Rough estimate
  - estimated_monthly_cost: Rough cost at 1K/10K users
- pipeline_design: How AI calls are orchestrated (sync/async/queue)
- rate_limiting: How to handle API rate limits
- caching_strategy: How to cache AI responses
- cost_optimization: Strategies to reduce costs
- safety_measures: Content filtering, output validation, human review triggers

Return ONLY valid JSON, no markdown.""",

    "prompt_engineering": """You are a prompt engineer. Document the **Prompt Engineering Specification** for the AI features of this startup.

**Idea:** {idea}

Generate a JSON object with:
- prompts: Array of 3-5 prompt templates, each with:
  - id: PROMPT-001, etc.
  - name: Descriptive name
  - purpose: What this prompt does
  - version: "1.0"
  - system_prompt: The system instruction
  - user_prompt_template: Template with {placeholders}
  - output_format: Expected JSON schema or format
  - validation_rules: How to validate the output
  - examples: Array of {input: ..., expected_output: ...}
  - last_updated: Current date

Return ONLY valid JSON, no markdown.""",

    "ai_evaluation": """You are an ML engineer. Create an **AI Evaluation** framework for the startup's AI features.

**Idea:** {idea}

Generate a JSON object with:
- evaluation_framework: Overall approach to evaluation
- test_datasets: Array of 2-3 datasets, each with:
  - name: Dataset name
  - size: Number of test cases
  - source: Where data comes from
  - description: What it tests
- metrics: Array of metrics used, each with:
  - name: Metric name (e.g., "accuracy", "BLEU", "ROUGE", "human_eval")
  - target: Target value
  - current: Current value (if known)
- regression_tests: Array of regression test scenarios
- known_issues: Array of known failure modes
- evaluation_frequency: How often to evaluate

Return ONLY valid JSON, no markdown.""",

    "ai_safety": """You are an AI safety specialist. Create an **AI Safety & Reliability Document** for the startup.

**Idea:** {idea}

Generate a JSON object with:
- autonomous_decisions: Array of things AI CAN decide automatically
- human_review_required: Array of things that require human review
- hard_limits: Array of things AI must NEVER do
- content_safety: How to filter harmful/inappropriate content
- bias_mitigation: Strategies to reduce bias
- transparency: How AI decisions are explained to users
- monitoring: How AI behavior is monitored in production
- incident_response: Process if AI produces harmful output
- compliance: Relevant regulations (GDPR, EU AI Act, etc.)

Return ONLY valid JSON, no markdown.""",

    "integration_guide": """You are an integration architect. Write an **Integration Guide** documenting all external integrations for this startup.

**Idea:** {idea}

Generate a JSON object with:
- integrations: Array of 3-6 integrations, each with:
  - name: Integration name
  - type: "API" / "Webhook" / "SDK" / "OAuth"
  - provider: Service provider
  - purpose: Why this integration exists
  - authentication: How auth works
  - key_endpoints: Array of important API endpoints
  - webhooks: Array of webhook events received
  - error_handling: How errors are managed
  - rate_limits: Known rate limits
- integration_flow_diagram: Text description of data flow
- fallback_strategies: What happens if integration fails

Return ONLY valid JSON, no markdown.""",

    "client_guide": """You are a developer advocate. Write a **Client Integration Guide** for developers who want to integrate with this startup's API.

**Idea:** {idea}

Generate a JSON object with:
- getting_started: Steps to get started (array of {step: 1, description: "..."})
- authentication: How to get and use API keys
- quickstart_examples: Array of code examples in 2+ languages, each with:
  - language: "python" / "javascript" / "curl"
  - code: The code snippet
  - description: What it does
- sdks: Array of available SDKs
- rate_limits: Clear rate limit documentation
- error_codes: Common error codes and their meanings
- support_channels: How to get help

Return ONLY valid JSON, no markdown.""",

    "security": """You are a security engineer. Create a **Security Document** covering all security aspects of this startup.

**Idea:** {idea}

Generate a JSON object with:
- authentication: Auth methods and policies
- authorization: Role-based access control design
- encryption: Data at rest and in transit encryption
- secrets_management: How secrets/keys are managed
- gdpr_compliance: GDPR-relevant measures
- data_retention: How long data is kept and when deleted
- threat_model: Key threats and mitigations
- security_endpoints: Security-related API endpoints
- incident_response: Security incident process
- audit_logging: What is logged and how

Return ONLY valid JSON, no markdown.""",

    "deployment": """You are a DevOps engineer. Write a **Deployment & Infrastructure Document**.

**Idea:** {idea}

Generate a JSON object with:
- environments: Array of {name: "dev"/"staging"/"production", purpose: "...", url: "..."}
- ci_cd_pipeline: Description of CI/CD flow
- containerization: Docker setup description
- orchestration: How containers are managed
- infrastructure_providers: Array of {service: "...", purpose: "..."}
- configuration_management: How config/env vars are managed
- backup_strategy: How and when backups happen
- scaling_strategy: How the system scales
- monitoring: Array of monitoring tools
- estimated_monthly_cost: Rough infrastructure cost

Return ONLY valid JSON, no markdown.""",

    "runbook": """You are an SRE. Create a **Runbook Operativo** for production operations.

**Idea:** {idea}

Generate a JSON object with:
- monitoring_dashboard: Key metrics to watch
- alert_thresholds: Array of {metric: "...", warning: "...", critical: "...", action: "..."}
- common_incidents: Array of {symptom: "...", cause: "...", resolution: [...], prevention: "..."}
- recovery_procedures: Array of {scenario: "...", steps: [...], estimated_time: "..."}
- escalation_policy: Who to contact and when
- maintenance_procedures: Array of routine maintenance tasks
- rollback_procedures: How to rollback deployments

Return ONLY valid JSON, no markdown.""",

    "gtm": """You are a marketing strategist. Write a **Go To Market (GTM) Document** for this startup.

**Idea:** {idea}
**Research Summary:** {research_summary}
**Competitors:** {competitor_names}

Generate a JSON object with:
- icp: Ideal Customer Profile (industry, size, budget, pain points)
- positioning: Market positioning statement
- messaging: Key messages for each audience segment
- channels: Array of {channel: "...", strategy: "...", priority: "high"/"medium"/"low"}
- launch_plan: Array of pre-launch and post-launch activities with timeline
- competitive_positioning: How to position vs each competitor
- pricing_strategy: Pricing approach (freemium, tiered, usage-based, etc.)
- success_metrics: Launch success KPIs
- risks: GTM risks and mitigations

Return ONLY valid JSON, no markdown.""",

    "qa_plan": """You are a QA lead. Write a **QA Plan** covering testing strategy for this startup.

**Idea:** {idea}
**MVP Features:** {mvp_features}

Generate a JSON object with:
- testing_strategy: Overall approach (shift-left, risk-based, etc.)
- test_levels: Array of {level: "unit"/"integration"/"api"/"e2e"/"load", tool: "...", coverage_target: "...", owner: "..."}
- test_environments: Where tests run
- test_data_management: How test data is managed
- regression_strategy: How regression testing works
- automation_approach: What to automate and tools to use
- bug_triage: How bugs are prioritized
- release_criteria: What must pass before release
- testing_schedule: When each test level runs in the SDLC

Return ONLY valid JSON, no markdown.""",

    "test_cases": """You are a QA engineer. Write **Test Cases** for the core features of this startup.

**Idea:** {idea}
**MVP Features:** {mvp_features}

Generate a JSON object with:
- test_cases: Array of 10-15 test cases, each with:
  - id: TC-001, TC-002, etc.
  - feature: Which feature this tests
  - title: Descriptive title
  - type: "functional" / "integration" / "api" / "e2e" / "edge_case"
  - priority: "high" / "medium" / "low"
  - preconditions: What must be set up
  - steps: Array of numbered steps
  - expected_result: What should happen
  - test_data: Any specific data needed
  - automation_status: "automated" / "manual" / "planned"

Return ONLY valid JSON, no markdown.""",

    "mcp_spec": """You are an MCP integration specialist. Write an **MCP Specification** for this startup's tools.

**Idea:** {idea}

Generate a JSON object with:
- server_name: e.g., "startup-factory-mcp"
- description: What the MCP server provides
- tools: Array of MCP tools, each with:
  - name: Tool name
  - description: What it does
  - input_schema: JSON Schema for inputs
  - output_schema: JSON Schema for outputs
  - example: Example usage
- resources: Array of exposed resources
- prompts: Array of prompt templates

Return ONLY valid JSON, no markdown.""",
}

# ── Generator ──────────────────────────────────────────


async def generate_document(report: ResearchReport, doc_id: str) -> dict:
    """Generate a single document using LLM, based on the research report."""
    if doc_id not in DOCUMENT_PROMPTS:
        raise ValueError(f"Unknown document type: {doc_id}")

    # Build context from research report
    competitor_names = [c.name for c in report.competitors[:5]]
    pain_points = []
    for c in report.competitors[:5]:
        if c.pain_points:
            pain_points.extend(c.pain_points[:3])

    market_validation_str = ""
    if report.market_validation:
        mv = report.market_validation
        parts = []
        if mv.reddit_posts_found:
            parts.append(f"Reddit posts: {mv.reddit_posts_found}")
        if mv.hn_mentions:
            parts.append(f"HN mentions: {mv.hn_mentions}")
        if mv.gh_similar_projects:
            parts.append(f"GitHub projects: {mv.gh_similar_projects}")
        if mv.overall_sentiment:
            parts.append(f"Sentiment: {mv.overall_sentiment}")
        market_validation_str = ", ".join(parts)

    context = {
        "idea": report.idea,
        "research_summary": report.summary or "No summary available",
        "competitor_names": ", ".join(competitor_names) if competitor_names else "None found",
        "pain_points": ", ".join(pain_points[:10]) if pain_points else "None found",
        "market_validation": market_validation_str or "No market validation data",
        "mvp_features": ", ".join(report.recommended_mvp_features[:8]) if report.recommended_mvp_features else "Not specified",
    }

    prompt_template = DOCUMENT_PROMPTS[doc_id]
    prompt = prompt_template.format(**context)

    try:
        response = await llm.chat(prompt, max_tokens=3000, temperature=0.3)
        # Try to parse as JSON
        # Strip markdown code blocks if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()

        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"LLM returned non-JSON for {doc_id}, returning raw text")
        return {"raw_response": response, "format": "text"}
    except Exception as e:
        logger.error(f"Failed to generate {doc_id}: {e}")
        raise
