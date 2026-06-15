"""Spec-kit Writer — genera SPEC.md, PLAN.md, y TASK-XXX.md desde PlanningOutput.

Aprendizajes aplicados:
- spec-kit (github/spec-kit): Chain of artifacts (Spec->Plan->Tasks->Implement)
- Obsidian-skills: Markdown con frontmatter parseable (Status, Priority, Dependencies)
- Devkit: Formato TASK-XXX.md compatible con TaskManager y DevAgent
- MemPalace: Verbatim templates — sin perdida de informacion
"""

import logging
from datetime import datetime
from pathlib import Path

from ..models import PlanningOutput, TechnicalSpec, FunctionalSpec

logger = logging.getLogger(__name__)

NL = "\n"


def generate_speckit_artifacts(planning: PlanningOutput, output_dir: str) -> dict:
    """Genera SPEC.md, PLAN.md, y TASK-XXX.md desde PlanningOutput."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    spec_path = out / "SPEC.md"
    spec_content = _generate_spec(planning)
    spec_path.write_text(spec_content)
    logger.info(f"  SPEC.md ({len(spec_content)} chars)")

    plan_path = out / "PLAN.md"
    plan_content = _generate_plan(planning)
    plan_path.write_text(plan_content)
    logger.info(f"  PLAN.md ({len(plan_content)} chars)")

    task_files = _generate_tasks(planning, out)

    return {
        "spec": str(spec_path),
        "plan": str(plan_path),
        "tasks": task_files,
        "task_count": len(task_files),
    }


def _generate_spec(planning: PlanningOutput) -> str:
    """Genera SPEC.md con funcionalidades, requerimientos y criterios."""
    prd = planning.prd
    func = planning.functional
    tech = planning.technical
    fin = planning.financial
    idea = planning.idea[:80]
    gen_time = planning.generated_at.isoformat()

    # Pre-compute all complex strings
    features_list = "".join(
        f"- **{f.get('id', 'F?')}**: {f.get('name', 'Feature')} [{f.get('priority', 'P1')}] — {f.get('description', '')}{NL}"
        for f in func.core_features[:10]
    )

    nfr_list = "".join(
        f"| {nfr.get('category', 'N/A')} | {nfr.get('requirement', 'N/A')} |{NL}"
        for nfr in func.non_functional_reqs[:8]
    )

    stories_list = "".join(f"- {s}{NL}" for s in prd.user_stories[:8])
    criteria_list = "".join(f"- {c}{NL}" for c in prd.success_criteria[:5])

    risks_list = "".join(
        f"- **{r.get('risk', '')}** (impact: {r.get('impact', 'medium')}) -> {r.get('mitigation', '')}{NL}"
        for r in prd.risks[:5]
    )

    target_audience = NL.join(
        f"- **{seg.get('segment', 'Unknown')}**: {seg.get('pain', '')} (Size: {seg.get('size', 'N/A')})"
        for seg in prd.target_audience[:4]
    )

    user_journeys = NL.join(
        f"#### {j.get('scenario', 'Journey')}{NL}" +
        NL.join(f"{i+1}. {s}" for i, s in enumerate(j.get('steps', [])))
        for j in func.user_journeys[:3]
    )

    ui_principles = NL.join(f"- {p}" for p in func.ui_principles[:5])
    data_privacy = NL.join(f"- {n}" for n in func.data_privacy_notes[:5])

    stack_table = NL.join(
        f"| {s.get('layer', '')} | {s.get('technology', '')} | {s.get('rationale', '')} |"
        for s in tech.stack_table[:8]
    )

    api_endpoints = NL.join(
        f"- **{ep.get('method', 'GET')}** `{ep.get('path', '/')}` — {ep.get('description', '')} ({ep.get('auth', 'public')})"
        for ep in tech.api_endpoints[:15]
    )

    data_model = NL.join(
        f"#### {e.get('entity', 'Entity')}{NL}" +
        NL.join(
            f"- `{f.get('name', 'field')}`: {f.get('type', 'str')}" +
            (f" — {f.get('notes', '')}" if f.get('notes') else '')
            for f in e.get('fields', [])[:8]
        )
        for e in tech.data_model[:6]
    )

    pricing_tiers = NL.join(
        f"- **{t.name}**: ${t.price_monthly:.0f}/mo — {t.description}"
        for t in fin.pricing_tiers[:4]
    )

    dependencies = NL.join(f"- {d}" for d in prd.dependencies[:5])
    constraints = NL.join(f"- {c}" for c in prd.constraints[:5])
    assumptions = NL.join(f"- {a}" for a in prd.assumptions[:5])

    return f"""# SPEC: {idea}

> **Spec-Driven Development** | Status: ACTIVE | Generated: {gen_time}
> Este documento es generado automaticamente por PitchForge CodeGen.

---

## Product Overview

**{prd.product_name or idea}** — {prd.tagline or 'A new startup idea'}

### Problem Statement

{prd.problem_statement or 'Not specified'}

### Proposed Solution

{prd.proposed_solution or 'Not specified'}

### Target Audience

{target_audience}

---

## Functional Requirements

### Core Features

{features_list or '- No features specified yet'}

### User Stories

{stories_list or '- No stories yet'}

### User Journeys

{user_journeys}

---

## Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
{nfr_list or '| N/A | N/A |'}

### UI Principles

{ui_principles}

### Data Privacy

{data_privacy}

---

## Technical Architecture

**Stack:** {tech.stack_recommendation or 'Modern web stack'}

### Technology Stack

{stack_table}

### API Endpoints

{api_endpoints}

### Data Model

{data_model}

---

## Financial Model

**Pricing:** {fin.pricing_rationale or 'Contact for pricing'}

### Pricing Tiers

{pricing_tiers}

### Key Metrics

- Break-even: Month {fin.break_even_month or 'TBD'} (~{fin.break_even_users or '?'} users)
- Estimated infra cost: ${tech.estimated_infra_cost_monthly or 50:.0f}/mo

---

## Success Criteria

{criteria_list or '- Not specified'}

---

## Risks & Mitigations

{risks_list or '- No major risks identified'}

---

## Dependencies & Constraints

### Dependencies

{dependencies}

### Constraints

{constraints}

### Assumptions

{assumptions}

---

## Out of Scope (v1)

- Advanced analytics dashboard
- Mobile native apps
- Enterprise SSO integration
- Multi-region deployment

---

*Generated by PitchForge CodeGen 2.0 — {gen_time}*
"""


def _generate_plan(planning: PlanningOutput) -> str:
    """Genera PLAN.md con arquitectura, componentes, orden de implementacion."""
    tech = planning.technical
    idea = planning.idea[:80]
    gen_time = planning.generated_at.isoformat()

    # Pre-compute all complex strings
    phases_list = ""
    for phase in tech.development_phases[:6]:
        phase_name = phase.get('phase', 'Phase')
        duration = phase.get('duration', 'TBD')
        phases_list += f"### {phase_name} ({duration}){NL}{NL}"
        phases_list += "".join(f"- {t}{NL}" for t in phase.get('tasks', [])[:8])
        phases_list += NL

    tech_stack = NL.join(
        f"- **{s.get('layer', '')}**: {s.get('technology', '')} — {s.get('rationale', '')}"
        for s in tech.stack_table[:8]
    )

    third_party = NL.join(f"- {d}" for d in tech.third_party_deps[:8])
    security = NL.join(f"- {s}" for s in tech.security_requirements[:6])

    return f"""# PLAN: {idea} — Plan de Implementacion

> **Derivado de SPEC.md** | Generado: {gen_time}

---

## Arquitectura General

```
Frontend (React)  -->  API (FastAPI)  -->  PostgreSQL (SQLModel)
                           |
                        Redis (Cache/Q)

i18n * ThemeSwitch * 10K UI * CI/CD * Alembic
```

## Technology Stack

{tech_stack}

---

## Development Phases

{phases_list}

---

## Implementation Order

1. **Foundation**: Docker, configs, CI/CD, estructura de proyecto
2. **Data Layer**: Modelos SQLModel, schemas Pydantic, migracion Alembic
3. **API Layer**: Endpoints CRUD, auth, paginacion, error handling
4. **Frontend Layer**: Paginas React, componentes, i18n, tema
5. **Testing**: Unit tests (pytest + vitest), integration tests
6. **Polish**: SEO, a11y, performance, lighthouse audit

---

## Validation Gates

1. **Import Check**: La app carga sin errores
2. **Type Check**: Los type hints son consistentes
3. **Test Suite**: pytest y vitest pasan
4. **Docker Build**: docker compose build completa sin errores
5. **Health Check**: GET /health devuelve 200

---

## Deployment

```bash
make dev
```

### Estimated Costs

- **Infra mensual**: ${tech.estimated_infra_cost_monthly or 50:.0f}
- **Horas desarrollo**: {tech.estimated_effort or '4-6 semanas con 1-2 devs'}

### Third-party Dependencies

{third_party}

---

## Security Considerations

{security}

---

*Generated by PitchForge CodeGen 2.0 — {gen_time}*
"""


def _generate_tasks(planning: PlanningOutput, output_dir: Path) -> list[str]:
    """Genera archivos TASK-XXX.md desde development_phases.

    Cada task usa formato DevAgent (TaskManager):
    - Status, Priority, Dependencies, Estimate, Description, Acceptance Criteria
    """
    tech = planning.technical
    func = planning.functional
    tasks_dir = output_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    task_idx = 0

    # Fase 0: Foundation (siempre)
    foundation_tasks = [
        ("Initialize project structure", "Set up Docker, CI/CD, configs, README",
         ["Docker compose works", "GitHub Actions CI passes", "README exists"]),
        ("Configure database and migrations", "Set up PostgreSQL, SQLModel, Alembic",
         ["Models created", "Alembic migration runs", "DB schema matches spec"]),
        ("Implement authentication", "JWT auth with login, register, refresh",
         ["POST /auth/login works", "Token validation works", "Protected routes return 401"]),
    ]
    for title, desc, criteria in foundation_tasks:
        task_idx += 1
        tid = f"TASK-{task_idx:03d}"
        task_md = _task_template(tid, title, "P0", [], "1h", desc, criteria, "foundation")
        path = tasks_dir / f"{tid.lower()}.md"
        path.write_text(task_md)
        generated.append(str(path))

    # Fases del TechnicalSpec
    for phase in tech.development_phases[:6]:
        phase_name = phase.get('phase', 'Phase')
        tasks = phase.get('tasks', [])
        duration = phase.get('duration', '1h')
        for task_name in tasks:
            task_idx += 1
            tid = f"TASK-{task_idx:03d}"
            priority = "P0" if task_idx <= 5 else "P1"
            criteria = [
                "Implementation passes tests",
                "Code review approved",
                "Docker build succeeds",
            ]
            task_md = _task_template(
                tid, task_name, priority,
                [], duration, task_name, criteria, phase_name
            )
            path = tasks_dir / f"{tid.lower()}.md"
            path.write_text(task_md)
            generated.append(str(path))

    # Feature tasks from functional spec
    for f in func.core_features[:8]:
        task_idx += 1
        tid = f"TASK-{task_idx:03d}"
        fname = f.get('name', 'Feature')
        fdesc = f.get('description', '')
        fcriteria = f.get('acceptance_criteria', ['Works end-to-end'])
        priority = f.get('priority', 'P1')
        task_md = _task_template(
            tid, f"Implement: {fname}", priority,
            [], f.get('effort', 'medium'), fdesc, fcriteria, "features"
        )
        path = tasks_dir / f"{tid.lower()}.md"
        path.write_text(task_md)
        generated.append(str(path))

    logger.info(f"  Generated {len(generated)} task files in {tasks_dir}")
    return generated


def _task_template(
    task_id: str,
    title: str,
    priority: str,
    dependencies: list[str],
    estimate: str,
    description: str,
    criteria: list[str],
    phase: str,
) -> str:
    """Template para un archivo TASK-XXX.md estandar DevAgent."""
    dep_line = ", ".join(dependencies) if dependencies else "none"
    criteria_lines = NL.join(f"- [ ] {c}" for c in criteria)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    return f"""# {task_id}: {title}

**Status**: pending
**Priority**: {priority}
**Dependencies**: {dep_line}
**Estimate**: {estimate}
**Phase**: {phase}
**Created**: {date_str}

## Description

{description}

## Acceptance Criteria

{criteria_lines}

## Notes

- Generated automatically by PitchForge CodeGen 2.0
- Review and adjust criteria before starting implementation
- Update status to `in_progress` when starting work
"""
