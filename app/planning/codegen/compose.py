"""Compose Orchestrator — parallel feature codegen with curated context.

TASK-066 — Core of Compose Mode CodeGen 3.0.
Replaces monolithic generation with N parallel subagents (one per feature).
Follows the MiMo-Code pattern: Spec → Plan → Dispatch → Review → Merge.
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..models import PlanningOutput, FeatureAnchor
from .feature_extractor import extract_features
from .curated_context import curate_context, CodegenContext
from .project import scaffold_project
from .datamodel import generate_models
from .api import generate_api_stubs
from .frontend import generate_frontend

logger = logging.getLogger(__name__)


class FeatureResult(BaseModel):
    """Result of generating a single feature."""
    anchor: str
    files_created: int = 0
    file_paths: list[str] = Field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    duration_ms: int = 0


class ComposeResult(BaseModel):
    """Aggregate result of parallel feature generation."""
    features: dict[str, FeatureResult] = Field(default_factory=dict)
    total_files: int = 0
    duration_ms: int = 0
    passed: int = 0
    failed: int = 0


class ComposeOrchestrator:
    """Orchestrates N parallel feature codegens with curated context.
    
    MVI (Minimum Viable Implementation):
    1. Scaffold project first (sequential, shared base)
    2. Extract features from PRD with [Fn] anchors
    3. Dispatch N parallel generations using asyncio.gather
    4. Link shared registries (__init__.py, App.tsx routes)
    5. Return aggregate results
    
    Each subagent receives only curate_context() output — no contamination.
    """
    
    def __init__(self, max_parallel: int = 8):
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)
    
    async def run(
        self,
        planning: PlanningOutput,
        output_dir: str,
    ) -> ComposeResult:
        """Execute Compose Mode codegen for all PRD features in parallel."""
        start = time.monotonic()
        out = Path(output_dir)
        
        logger.info(f"🚀 Compose Mode CodeGen 3.0 started for: {planning.idea}")
        logger.info(f"   Output: {out}")
        
        # 0. Scaffold shared project base
        logger.info("  Step 0: Scaffold shared project base...")
        scaffold = scaffold_project(str(out), planning.technical, planning.financial)
        logger.info(f"  ✅ Scaffold: {scaffold['files_created']} files")
        
        # 1. Extract features from PRD
        features = extract_features(planning.prd)
        if not features:
            logger.warning("  ⚠️ No features found in PRD, falling back to monolithic codegen")
            return await self._fallback_monolithic(planning, str(out))
        
        logger.info(f"  📋 {len(features)} features extracted: {', '.join(f.anchor for f in features)}")
        
        # 2. Generate shared data models (all entities, once)
        logger.info("  Step 1: Generate shared data models...")
        model_files = generate_models(planning.technical, str(out))
        logger.info(f"  ✅ Models: {len(model_files)} files")
        
        # 3. Dispatch parallel feature generation (API only — no frontend)
        logger.info(f"  Step 2: Dispatch {len(features)} parallel API generations...")
        
        async def _generate_one(feature: FeatureAnchor) -> FeatureResult:
            async with self._semaphore:
                return await self._generate_feature(feature, planning, str(out))
        
        feature_results = await asyncio.gather(*[
            _generate_one(f) for f in features
        ])
        
        # 4. Generate frontend once after all API features (avoids N× duplication)
        logger.info("  Step 3: Generate unified frontend...")
        try:
            frontend_files = generate_frontend(
                planning.functional, planning.technical,
                str(out / "frontend")
            )
            logger.info(f"  ✅ Frontend: {len(frontend_files)} files")
        except Exception as e:
            logger.warning(f"  ⚠️ Frontend generation failed: {e}")
        
        # 5. Link shared registries
        logger.info("  Step 3: Link shared registries...")
        self._link_registries(str(out), feature_results)
        
        # 6. Build result
        results_dict = {r.anchor: r for r in feature_results}
        
        duration_ms = int((time.monotonic() - start) * 1000)
        passed = sum(1 for r in feature_results if r.success)
        failed = sum(1 for r in feature_results if not r.success)
        total_files = sum(r.files_created for r in feature_results)
        
        result = ComposeResult(
            features=results_dict,
            total_files=total_files,
            duration_ms=duration_ms,
            passed=passed,
            failed=failed,
        )
        
        logger.info(
            f"✅ Compose Mode complete in {duration_ms}ms — "
            f"{passed} passed, {failed} failed, {total_files} files"
        )
        
        return result
    
    async def _generate_feature(
        self,
        feature: FeatureAnchor,
        planning: PlanningOutput,
        output_dir: str,
    ) -> FeatureResult:
        """Generate code for a single feature with curated context."""
        t0 = time.monotonic()
        
        try:
            # Curate minimal context for this feature
            ctx = curate_context(feature, planning.technical, output_dir)
            
            logger.debug(
                f"  [{feature.anchor}] Generating: entities={len(ctx.relevant_entities)}, "
                f"endpoints={len(ctx.relevant_endpoints)}, dirs={ctx.scope_dirs}"
            )
            
            out = Path(output_dir)
            files = []
            
            # Generate API stubs for this feature's endpoints only
            if ctx.relevant_endpoints:
                filtered_tech = planning.technical.model_copy()
                filtered_tech.api_endpoints = ctx.relevant_endpoints
                filtered_tech.data_model = ctx.relevant_entities
                
                # NOTE: API files written to isolated feature file when possible.
                # File collisions are mitigated by the linker step for __init__.py.
                # Known MVI limitation: features with overlapping route paths may collide.
                api_files = generate_api_stubs(filtered_tech, str(out))
                files.extend(api_files)
            
            duration_ms = int((time.monotonic() - t0) * 1000)
            
            return FeatureResult(
                anchor=feature.anchor,
                files_created=len(files),
                file_paths=files,
                success=True,
                duration_ms=duration_ms,
            )
            
        except Exception as e:
            logger.error(f"  [{feature.anchor}] Failed: {e}")
            return FeatureResult(
                anchor=feature.anchor,
                success=False,
                error=str(e),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
    
    async def _fallback_monolithic(
        self,
        planning: PlanningOutput,
        output_dir: str,
    ) -> ComposeResult:
        """Fallback to monolithic generation when no features found."""
        from .orchestrator import CodegenPipeline
        pipeline = CodegenPipeline()
        result = await pipeline.run(planning, output_dir)
        
        return ComposeResult(
            total_files=result["total_files"],
            duration_ms=result["duration_ms"],
            passed=1 if result["validation"]["success"] else 0,
            failed=0 if result["validation"]["success"] else 1,
        )
    
    def _link_registries(
        self,
        output_dir: str,
        feature_results: list[FeatureResult],
    ) -> None:
        """Auto-generate shared registries (__init__.py, route imports, App.tsx).
        
        The "Share Nothing" post-processing step:
        After parallel generation, scan generated files and auto-wire imports.
        Prevents merge conflicts on shared files.
        """
        out = Path(output_dir)
        
        # Link routes __init__.py
        routes_dir = out / "app" / "routes"
        if routes_dir.exists():
            route_files = sorted(
                f.stem for f in routes_dir.glob("*.py")
                if f.stem not in ("__init__",)
            )
            if route_files:
                init_content = '"""Auto-generated route registry — Compose Mode."""\n\n'
                for rf in route_files:
                    init_content += f"from . import {rf}\n"
                (routes_dir / "__init__.py").write_text(init_content)
                logger.info(f"  🔗 Linked {len(route_files)} route modules")
        
        # Link models __init__.py
        models_dir = out / "app" / "models"
        if models_dir.exists():
            model_files = sorted(
                f.stem for f in models_dir.glob("*.py")
                if f.stem not in ("__init__",)
            )
            if model_files:
                init_content = '"""Auto-generated model registry — Compose Mode."""\n\n'
                for mf in model_files:
                    init_content += f"from .{mf} import *  # noqa: F403\n"
                (models_dir / "__init__.py").write_text(init_content)
                logger.info(f"  🔗 Linked {len(model_files)} model modules")


__all__ = [
    "ComposeOrchestrator",
    "ComposeResult",
    "FeatureResult",
]
