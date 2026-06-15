"""Codegen Pipeline — orchestrates project scaffold, data model, API, and frontend generation.

Takes a PlanningOutput and produces a full MVP project directory.
"""

import json
import logging
import py_compile
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import PlanningOutput
from .project import scaffold_project
from .datamodel import generate_models
from .api import generate_api_stubs
from .frontend import generate_frontend
from .speckit import generate_speckit_artifacts

logger = logging.getLogger(__name__)


class CodegenPipeline:
    """Generates a complete MVP project from planning specs."""

    async def run(
        self,
        planning: PlanningOutput,
        output_dir: str,
        generate_speckit: bool = True,
    ) -> dict:
        """Run all codegen steps and produce a complete MVP project.
        
        CodeGen 2.0 pipeline:
        0. Spec-kit artifacts (SPEC.md, PLAN.md, TASK-XXX.md)
        1. Project scaffold (Docker, CI/CD, Alembic, tests, i18n, theme)
        2. Data models (SQLModel + schemas + CRUD routes)
        3. API stubs (FastAPI routes)
        4. Frontend (React + i18n + themeSwitch + 10K components)
        """
        start = time.monotonic()
        out = Path(output_dir)

        if out.exists():
            shutil.rmtree(out)

        logger.info(f"🏗️ CodeGen 2.0 started for: {planning.idea}")
        logger.info(f"   Output: {out}")

        results = {"generated_files": [], "stats": {}}

        # 0. Spec-kit artifacts
        if generate_speckit:
            logger.info("  Step 0/5: Spec-kit artifacts (SPEC.md, PLAN.md, TASK-*.md)...")
            speckit_results = generate_speckit_artifacts(planning, str(out))
            results["stats"]["speckit_files"] = speckit_results["task_count"] + 2
            results["speckit"] = speckit_results

        # 1. Project scaffold
        logger.info("  Step 1/5: Project scaffold (Docker, CI/CD, Alembic, tests, i18n)...")
        scaffold = scaffold_project(str(out), planning.technical, planning.financial)
        results["stats"]["scaffold_files"] = scaffold["files_created"]
        results["generated_files"].extend([
            str(out / f.relative_to(out)) 
            for f in out.rglob("*") 
            if f.is_file() and ".pyc" not in str(f)
        ])

        # 2. Data model -> SQLModel + CRUD
        logger.info("  Step 2/5: Data model entities -> SQLModel + CRUD routes...")
        model_files = generate_models(planning.technical, str(out))
        results["stats"]["model_files"] = len(model_files)
        results["generated_files"].extend(model_files)

        # 3. API stubs
        logger.info("  Step 3/5: API stubs from endpoint specs...")
        api_files = generate_api_stubs(planning.technical, str(out))
        results["stats"]["api_files"] = len(api_files)
        results["generated_files"].extend(api_files)

        # 4. Frontend (to frontend/ subdirectory)
        logger.info("  Step 4/5: Frontend (React + i18n + themeSwitch + 10K components)...")
        frontend_base = out / "frontend"
        frontend_files = generate_frontend(planning.functional, planning.technical, str(frontend_base))
        results["stats"]["frontend_files"] = len(frontend_files)
        results["generated_files"].extend(frontend_files)

        # 5. Validation gate
        logger.info("  Step 5/5: Validation gate (structure check)...")
        validation = _validate_project(str(out))
        results["validation"] = validation

        # Write project manifest
        manifest = {
            "idea": planning.idea,
            "generated_at": datetime.utcnow().isoformat(),
            "duration_ms": int((time.monotonic() - start) * 1000),
            "stats": results["stats"],
            "total_files": len(results["generated_files"]),
            "codegen_version": "2.0",
            "validation": validation,
        }
        (out / "project.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False)
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(f"✅ CodeGen 2.0 complete in {duration_ms}ms — {len(results['generated_files'])} files")

        return {
            "output_dir": str(out),
            "duration_ms": duration_ms,
            "total_files": len(results["generated_files"]),
            "stats": results["stats"],
            "validation": validation,
        }

    async def run_and_save(self, planning: PlanningOutput, output_dir: str) -> dict:
        """Alias for run()."""
        return await self.run(planning, output_dir)

    async def run_and_zip(self, planning: PlanningOutput, output_dir: str) -> str:
        """Run codegen and create zip archive."""
        result = await self.run(planning, output_dir)
        out = Path(output_dir)
        zip_path = out.parent / f"{out.name}.zip"
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", out)
        logger.info(f"  📦 Zipped: {zip_path}")
        return str(zip_path)


def _validate_project(project_dir: str) -> dict:
    """Validation gate: verify project structure is complete and correct.
    
    Checks:
    1. Required directories exist
    2. Required files exist
    3. Generated Python files have valid syntax
    """
    out = Path(project_dir)
    required_dirs = [
        "app/models", "app/schemas", "app/routes", "app/core",
        ".github/workflows", "alembic/versions", "tests",
        "frontend/src/pages", "frontend/src/components",
        "frontend/src/i18n", "frontend/src/hooks",
    ]
    required_files = [
        "docker-compose.yml", "Makefile", "README.md", "Dockerfile",
        ".env.example", ".gitignore",
        "app/config.py", "app/database.py", "app/main.py",
        "app/core/security.py", "app/core/auth.py", "app/core/errors.py",
        "alembic.ini", "alembic/env.py",
        "tests/conftest.py", "tests/test_health.py",
        ".github/workflows/ci.yml",
        "frontend/package.json", "frontend/tsconfig.json",
        "frontend/vite.config.ts", "frontend/index.html",
        "frontend/src/main.tsx", "frontend/src/App.tsx",
        "frontend/src/i18n/en.json", "frontend/src/i18n/es.json",
        "frontend/src/components/ThemeToggle.tsx",
        "frontend/src/components/LanguageSwitcher.tsx",
        "frontend/src/hooks/useTheme.ts",
    ]
    
    missing_dirs = [d for d in required_dirs if not (out / d).exists()]
    missing_files = [f for f in required_files if not (out / f).exists()]
    
    # Python syntax validation
    syntax_errors = []
    python_files = list(out.rglob("*.py"))
    for py_file in python_files:
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as e:
            syntax_errors.append({
                "file": str(py_file.relative_to(out)),
                "error": str(e),
            })
    
    structure_ok = len(missing_dirs) == 0 and len(missing_files) == 0
    syntax_ok = len(syntax_errors) == 0
    
    result = {
        "success": structure_ok and syntax_ok,
        "total_required": len(required_dirs) + len(required_files),
        "missing_dirs": missing_dirs,
        "missing_files": missing_files,
        "python_files_checked": len(python_files),
        "syntax_errors": syntax_errors,
    }
    
    if not result["success"]:
        issues = []
        if missing_dirs:
            issues.append(f"{len(missing_dirs)} dirs missing")
        if missing_files:
            issues.append(f"{len(missing_files)} files missing")
        if syntax_errors:
            issues.append(f"{len(syntax_errors)} syntax errors")
        logger.warning(f"Validation issues: {', '.join(issues)}")
    else:
        logger.info(f"✅ Validation gate passed — all {len(python_files)} Python files compile")
    
    return result
