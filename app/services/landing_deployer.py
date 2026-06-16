"""Landing Deployer — deploy generated landing pages to Cloudflare Pages with subdomains.

Supports:
- Deploy HTML to Cloudflare Pages
- Auto-create {slug}.pitch-forge.com subdomains
- Link custom domains for premium clients (via DNS)
- CNAME setup via Cloudflare API
"""

import json
import logging
import os
import random
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Cloudflare Configuration ───────────────────────────
# Loaded from environment (set in Coolify / .env)

CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "537913864dd9e8e75f6b352bc23497e7")
CLOUDFLARE_PAGES_PROJECT = os.getenv("CLOUDFLARE_PAGES_PROJECT", "pitchforge-landing")

# Domain configuration
ROOT_DOMAIN = os.getenv("PITCHFORGE_ROOT_DOMAIN", "pitch-forge.com")
CLOUDFLARE_ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID", "c2d18286a077a48b73bec9b047a78965")

# Path to wrangler CLI
WRANGLER_CLI = os.getenv("WRANGLER_CLI", "/home/admin/.npm-global/bin/wrangler")


def _slugify(idea: str, max_len: int = 30) -> str:
    """Convert an idea string to a DNS-safe slug."""
    if not idea or not idea.strip():
        return f"landing-{random.randint(100000, 999999)}"
    slug = idea.lower().strip()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        return f"landing-{random.randint(100000, 999999)}"
    return slug[:max_len]


class LandingDeployer:
    """Deploy landing pages to Cloudflare Pages with subdomain management."""

    def __init__(self):
        self.api_token = CLOUDFLARE_API_TOKEN or self._load_token_from_file()
        self.account_id = CLOUDFLARE_ACCOUNT_ID
        self.project_name = CLOUDFLARE_PAGES_PROJECT
        self.root_domain = ROOT_DOMAIN
        self.zone_id = CLOUDFLARE_ZONE_ID

    @staticmethod
    def _load_token_from_file() -> str:
        """Fallback: load Cloudflare token from .cf_token file."""
        for path in [
            Path.home() / ".cf_token",
            Path("/home/admin/code/startup-factory/.cf_token"),
        ]:
            if path.exists():
                return path.read_text().strip()
        return ""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def deploy_html(
        self,
        html: str,
        slug: str,
        subdomain: Optional[str] = None,
        is_production: bool = True,
    ) -> dict:
        """Deploy a landing page HTML to Cloudflare Pages.

        Args:
            html: The full HTML content of the landing page.
            slug: URL-safe slug for the project (e.g. 'my-startup-idea').
            subdomain: Custom subdomain override. Defaults to {slug}.{root_domain}.
            is_production: If True, deploys to production (pitch-forge.com alias).

        Returns:
            dict with deployment URL, preview URL, and subdomain info.
        """
        target_subdomain = subdomain or f"{slug}.{self.root_domain}"
        logger.info(f"Deploying landing page for '{slug}' → {target_subdomain}")

        # Step 1: Upload via Wrangler CLI (reliable direct upload)
        preview_url = await self._upload_via_wrangler(html, slug)

        # Step 2: Create DNS subdomain if it doesn't exist
        if self.zone_id and self.api_token:
            await self._ensure_subdomain(target_subdomain, preview_url)

        return {
            "slug": slug,
            "subdomain": target_subdomain,
            "url": f"https://{target_subdomain}",
            "preview_url": preview_url,
            "deployed": True,
        }

    async def _upload_via_wrangler(self, html: str, slug: str) -> str:
        """Upload HTML to Cloudflare Pages using Wrangler CLI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write the HTML file
            index_path = Path(tmpdir) / "index.html"
            index_path.write_text(html, encoding="utf-8")

            # Run wrangler pages deploy
            env = os.environ.copy()
            if self.api_token:
                env["CLOUDFLARE_API_TOKEN"] = self.api_token

            cmd = [
                WRANGLER_CLI, "pages", "deploy", tmpdir,
                "--project-name", self.project_name,
                "--branch", slug[:40],
            ]

            logger.info(f"Running: {' '.join(cmd)}")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                )

                # Extract preview URL from output
                output = result.stdout + result.stderr
                logger.debug(f"Wrangler output: {output[:500]}")

                # Parse preview URL from wrangler output
                url_match = re.search(r"(https://[a-f0-9]+\.pitchforge-landing\.pages\.dev)", output)
                if url_match:
                    preview_url = url_match.group(1)
                    logger.info(f"Deployed to preview URL: {preview_url}")
                    return preview_url

                # Fallback: try to extract any pages.dev URL
                url_match = re.search(r"(https://[^\s]+\.pages\.dev)", output)
                if url_match:
                    preview_url = url_match.group(1)
                    logger.info(f"Deployed to preview URL (fallback): {preview_url}")
                    return preview_url

                logger.warning(f"Could not extract URL from wrangler output. Output: {output[:800]}")
                return f"https://{slug}.pitchforge-landing.pages.dev"

            except subprocess.TimeoutExpired:
                logger.error("Wrangler deploy timed out after 60s")
                raise
            except subprocess.CalledProcessError as e:
                logger.error(f"Wrangler deploy failed: {e.stderr[:500]}")
                raise

    async def _ensure_subdomain(self, subdomain: str, target_url: str) -> bool:
        """Create or update a CNAME record for the subdomain to point to Cloudflare Pages.

        Two-step process:
        1. Register the domain with Cloudflare Pages project (so Pages serves it)
        2. Create/update CNAME record in DNS zone (so DNS resolves)

        The subdomain CNAME points to the Cloudflare Pages project domain,
        so that {slug}.pitch-forge.com shows the landing page.
        """
        # Extract the subdomain prefix (e.g., "my-idea" from "my-idea.pitch-forge.com")
        prefix = subdomain.replace(f".{self.root_domain}", "")

        # Cloudflare Pages project domain
        pages_domain = f"{self.project_name}.pages.dev"

        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: Register the domain with Cloudflare Pages project
            # This tells Pages to accept traffic for this domain
            pages_domain_url = (
                f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
                f"/pages/projects/{self.project_name}/domains"
            )
            pages_payload = {"name": subdomain}
            pages_resp = await client.post(pages_domain_url, headers=self._headers(), json=pages_payload)
            pages_data = pages_resp.json()
            if pages_data.get("success"):
                logger.info(f"Registered {subdomain} with Pages project")
            else:
                # May already exist — that's fine
                logger.debug(f"Pages domain registration: {pages_data.get('errors', [{}])[0].get('message', 'already exists or other')[:100]}")

            # Step 2: Create/update CNAME record in DNS zone
            list_url = (
                f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records"
                f"?type=CNAME&name={prefix}.{self.root_domain}"
            )
            resp = await client.get(list_url, headers=self._headers())
            data = resp.json()

            existing_records = data.get("result", []) if data.get("success") else []

            if existing_records:
                # Update existing record
                record_id = existing_records[0]["id"]
                update_url = (
                    f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}"
                    f"/dns_records/{record_id}"
                )
                update_payload = {
                    "type": "CNAME",
                    "name": prefix,
                    "content": pages_domain,
                    "ttl": 120,
                    "proxied": True,
                    "comment": f"Auto-deployed landing: {prefix}",
                }
                resp = await client.put(
                    update_url, headers=self._headers(), json=update_payload
                )
                if resp.json().get("success"):
                    logger.info(f"Updated CNAME: {prefix}.{self.root_domain} → {pages_domain}")
                else:
                    logger.warning(f"Failed to update CNAME: {resp.text[:200]}")
            else:
                # Create new CNAME record
                create_url = (
                    f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records"
                )
                create_payload = {
                    "type": "CNAME",
                    "name": prefix,
                    "content": pages_domain,
                    "ttl": 120,
                    "proxied": True,
                    "comment": f"Auto-deployed landing: {prefix}",
                }
                resp = await client.post(
                    create_url, headers=self._headers(), json=create_payload
                )
                if resp.json().get("success"):
                    logger.info(f"Created CNAME: {prefix}.{self.root_domain} → {pages_domain}")
                else:
                    logger.warning(f"Failed to create CNAME: {resp.text[:200]}")

            return True

    async def link_custom_domain(
        self, slug: str, custom_domain: str
    ) -> dict:
        """Link a custom domain to a deployed landing page (premium feature).

        The client configures a CNAME at their DNS provider pointing to
        {slug}.pitch-forge.com or directly to Cloudflare Pages.

        Args:
            slug: The project slug.
            custom_domain: The client's custom domain (e.g. 'app.client.com').

        Returns:
            dict with custom domain info and DNS instructions.
        """
        logger.info(f"Linking custom domain {custom_domain} for '{slug}'")

        async with httpx.AsyncClient(timeout=15) as client:
            # Add custom domain to Cloudflare Pages project
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
                f"/pages/projects/{self.project_name}/domains"
            )
            payload = {"name": custom_domain}

            resp = await client.post(url, headers=self._headers(), json=payload)
            data = resp.json()

            if data.get("success"):
                status = data.get("result", {}).get("status", "pending")
                logger.info(f"Custom domain {custom_domain} added (status: {status})")
            else:
                errors = data.get("errors", [])
                logger.warning(f"Custom domain addition: {errors}")

        # Provide DNS instructions for the client
        return {
            "slug": slug,
            "custom_domain": custom_domain,
            "status": "configured",
            "dns_instructions": {
                "type": "CNAME",
                "name": custom_domain.split(".")[0],
                "target": f"{slug}.{self.root_domain}",
                "note": "Configure this CNAME at your DNS provider. SSL is auto-provisioned by Cloudflare.",
            },
            "url": f"https://{custom_domain}",
        }

    async def get_deployment_status(self, slug: str) -> dict:
        """Check the deployment status of a landing page."""
        async with httpx.AsyncClient(timeout=10) as client:
            # Check Pages deployments
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
                f"/pages/projects/{self.project_name}/deployments?per_page=1"
            )
            resp = await client.get(url, headers=self._headers())
            data = resp.json()

            deployments = data.get("result", []) if data.get("success") else []
            latest = deployments[0] if deployments else {}

            # Check DNS
            dns_status = "unknown"
            if self.zone_id:
                dns_url = (
                    f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records"
                    f"?type=CNAME&name={slug}.{self.root_domain}"
                )
                dns_resp = await client.get(dns_url, headers=self._headers())
                dns_data = dns_resp.json()
                dns_status = "configured" if dns_data.get("result") else "not_configured"

            return {
                "slug": slug,
                "url": f"https://{slug}.{self.root_domain}",
                "latest_deployment": latest.get("id", "unknown")[:16] if latest else "none",
                "deployment_status": latest.get("status", "unknown") if latest else "none",
                "dns_status": dns_status,
            }


# ── Convenience functions ─────────────────────────────

_default_deployer: Optional[LandingDeployer] = None


def get_deployer() -> LandingDeployer:
    """Get or create the default LandingDeployer instance."""
    global _default_deployer
    if _default_deployer is None:
        _default_deployer = LandingDeployer()
    return _default_deployer


async def deploy_landing(
    html: str,
    idea: str,
    custom_domain: Optional[str] = None,
) -> dict:
    """One-shot deploy: slugify idea, deploy HTML, optionally link custom domain.

    Args:
        html: Full landing page HTML.
        idea: The idea text (used to generate slug).
        custom_domain: Optional custom domain for premium clients.

    Returns:
        dict with deployment results.
    """
    deployer = get_deployer()
    slug = _slugify(idea)

    result = await deployer.deploy_html(html, slug)

    if custom_domain:
        domain_result = await deployer.link_custom_domain(slug, custom_domain)
        result["custom_domain"] = domain_result

    return result
