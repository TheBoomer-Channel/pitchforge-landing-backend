"""Test Cycle — Docker-based development loop for autonomous MVP testing.

Manages:
- Docker Compose lifecycle (up, down, rebuild)
- Health checks against APIs
- Test execution
- Log collection
- Result reporting
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class TestCycle:
    """Manages Docker-based test cycles for MVP development."""

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.compose_file = self.project_dir / "docker-compose.yml"
        self.last_output = ""

    def is_available(self) -> bool:
        """Check if Docker is available and compose file exists."""
        if not self.compose_file.exists():
            return False
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def up(self, build: bool = False, wait: int = 30) -> dict:
        """Start the Docker Compose environment."""
        cmd = ["docker", "compose", "-f", str(self.compose_file), "up", "-d"]
        if build:
            cmd.append("--build")

        start = time.monotonic()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(self.project_dir),
        )
        elapsed = int((time.monotonic() - start) * 1000)

        if result.returncode != 0:
            return {
                "success": False,
                "output": result.stdout + result.stderr,
                "duration_ms": elapsed,
            }

        # Wait for services to be healthy
        if wait > 0:
            health = self._wait_for_healthy(wait)
        else:
            health = {"success": True, "services": {}}

        return {
            "success": health["success"],
            "output": result.stdout[:2000],
            "services": health.get("services", {}),
            "duration_ms": elapsed,
        }

    def down(self) -> dict:
        """Stop the Docker Compose environment."""
        result = subprocess.run(
            ["docker", "compose", "-f", str(self.compose_file), "down"],
            capture_output=True, text=True, timeout=60,
            cwd=str(self.project_dir),
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout[:1000],
        }

    def restart(self, service: Optional[str] = None) -> dict:
        """Restart a specific service or all services."""
        cmd = ["docker", "compose", "-f", str(self.compose_file), "restart"]
        if service:
            cmd.append(service)

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=str(self.project_dir),
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout[:1000],
        }

    def health_check(self, url: str = "http://localhost:8000/health", timeout: int = 10) -> dict:
        """Check if a service is responding."""
        import httpx
        try:
            start = time.monotonic()
            resp = httpx.get(url, timeout=timeout)
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "success": resp.status_code == 200,
                "status_code": resp.status_code,
                "body": resp.text[:500],
                "duration_ms": elapsed,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)[:200],
                "duration_ms": 0,
            }

    def run_tests(self, service: str = "api", command: str = "pytest") -> dict:
        """Run tests inside a Docker service."""
        cmd = [
            "docker", "compose", "-f", str(self.compose_file),
            "exec", "-T", service,
            "sh", "-c", command,
        ]
        start = time.monotonic()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180,
            cwd=str(self.project_dir),
        )
        elapsed = int((time.monotonic() - start) * 1000)

        self.last_output = result.stdout + result.stderr
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": self.last_output[:3000],
            "duration_ms": elapsed,
        }

    def run_lint(self, service: str = "api") -> dict:
        """Run linting (ruff) inside the service."""
        return self.run_tests(service, "ruff check . 2>&1 || true")

    def check_api_endpoint(self, method: str = "GET", path: str = "/api/v1/", data: Optional[dict] = None) -> dict:
        """Test a specific API endpoint."""
        import httpx
        url = f"http://localhost:8000{path}"
        try:
            start = time.monotonic()
            if method.upper() == "GET":
                resp = httpx.get(url, timeout=10)
            elif method.upper() == "POST":
                resp = httpx.post(url, json=data or {}, timeout=10)
            elif method.upper() == "DELETE":
                resp = httpx.delete(url, timeout=10)
            else:
                resp = httpx.request(method, url, json=data or {}, timeout=10)
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "success": resp.status_code < 500,
                "method": method,
                "path": path,
                "status_code": resp.status_code,
                "body": resp.text[:1000],
                "duration_ms": elapsed,
            }
        except Exception as e:
            return {
                "success": False,
                "method": method,
                "path": path,
                "error": str(e)[:200],
            }

    def get_logs(self, service: str = "api", lines: int = 50) -> str:
        """Get logs from a Docker service."""
        result = subprocess.run(
            ["docker", "compose", "-f", str(self.compose_file), "logs", "--tail", str(lines), service],
            capture_output=True, text=True, timeout=10,
            cwd=str(self.project_dir),
        )
        return (result.stdout + result.stderr)[:5000]

    def _wait_for_healthy(self, timeout_secs: int) -> dict:
        """Wait for services to become healthy."""
        services = {}
        start = time.monotonic()

        while time.monotonic() - start < timeout_secs:
            try:
                result = subprocess.run(
                    ["docker", "compose", "-f", str(self.compose_file), "ps", "--format", "json"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(self.project_dir),
                )
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        info = json.loads(line)
                        name = info.get("Name", info.get("Service", "unknown"))
                        status = info.get("Status", "unknown")
                        health = info.get("Health", "")
                        services[name] = {
                            "status": status,
                            "health": health,
                            "running": "running" in status.lower() or "up" in status.lower(),
                        }
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass

            # Check if all services are running
            all_running = all(s.get("running", False) for s in services.values()) if services else False
            if all_running:
                return {"success": True, "services": services}

            time.sleep(2)

        return {"success": len(services) > 0, "services": services}

    def full_cycle(self, run_tests: bool = True, check_endpoints: Optional[List[str]] = None) -> dict:
        """Run a complete test cycle: up → health → tests → endpoints → report."""
        results = {"timestamp": datetime.utcnow().isoformat(), "steps": {}}

        # 1. Start environment
        up_result = self.up(build=False)
        results["steps"]["up"] = up_result
        if not up_result["success"]:
            results["success"] = False
            results["error"] = "Failed to start Docker environment"
            return results

        # 2. Health check
        health = self.health_check()
        results["steps"]["health"] = health
        if not health["success"]:
            results["success"] = False
            results["error"] = "Health check failed"
            # Don't return - still collect logs
        else:
            results["success"] = True

        # 3. Run tests (optional)
        if run_tests:
            test_result = self.run_tests()
            results["steps"]["tests"] = test_result
            if not test_result["success"]:
                results["success"] = False

        # 4. Check specific endpoints (optional)
        if check_endpoints:
            ep_results = []
            for ep in check_endpoints:
                if isinstance(ep, str):
                    ep_results.append(self.check_api_endpoint(path=ep))
            results["steps"]["endpoints"] = ep_results

        # 5. Collect logs summary
        results["logs"] = self.get_logs()

        # 6. Stop environment
        down_result = self.down()
        results["steps"]["down"] = down_result

        return results
