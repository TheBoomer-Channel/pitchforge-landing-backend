"""End-to-end smoke test — hits all core PitchForge API features.
Run inside Docker: docker exec startup-factory-api-1 python tests/e2e_smoke.py

Expected non-200 responses (correct behavior):
  - 401 on /auth/me without token
  - 404 on /api/v1/legal/nonexistent
  - 404 on cancel-deletion without pending
"""
import asyncio, httpx, sys, uuid

API = "http://localhost:8086"
TOKEN = f"e2e-test-{uuid.uuid4().hex[:8]}"
IDEA = "AI-powered project management for remote teams"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
CRON = {"X-Cron-Secret": "dev-cron-secret-change-in-prod"}
results = {}


async def check(name, fn, expected_status=None):
    """expected_status: int or range (200, 300) meaning 2xx. None means any."""
    try:
        r = await fn()
        if expected_status is None:
            ok = True
        elif isinstance(expected_status, tuple):
            ok = expected_status[0] <= r.status_code < expected_status[1]
        else:
            ok = r.status_code == expected_status
        results[name] = {"status": r.status_code, "ok": ok, "body": r.text[:300]}
        icon = "PASS" if ok else "FAIL"
        if ok and r.status_code not in (200, 201, 204):
            icon = "OK  "
        print(f"  [{icon}] {name}: {r.status_code}" + (f" (expected {expected_status})" if not ok else ""))
    except Exception as e:
        results[name] = {"status": "ERR", "ok": False, "body": str(e)[:300]}
        print(f"  [FAIL] {name}: ERROR - {e}")


async def main():
    async with httpx.AsyncClient(base_url=API, timeout=180) as c:

        # ── 1. Health ──────────────────────────────────
        print("\n── 1. Health ──")
        r = await c.get("/health")
        h = r.json()
        print(f"  Health: {h.get('status')}, DB: {h.get('components',{}).get('database',{}).get('status')}")
        await check("1a. GET /health", lambda ac=c: ac.get("/health"), (200, 300))
        await check("1b. GET /", lambda ac=c: ac.get("/"), (200, 300))
        await check("1c. GET /openapi.json", lambda ac=c: ac.get("/openapi.json"), (200, 300))

        # ── 2. Legal docs (all PUBLIC) ──────────────────
        print("\n── 2. Legal Docs ──")
        for slug in ["terms", "privacy", "cookies", "aup"]:
            await check(f"2. Legal {slug}", lambda ac=c, s=slug: ac.get(f"/api/v1/legal/{s}"), 200)
        await check("2e. Legal version", lambda ac=c: ac.get("/api/v1/legal/version"), 200)
        await check("2f. Legal history", lambda ac=c: ac.get("/api/v1/legal/privacy/history"), 200)
        await check("2g. Legal 404 (expected)", lambda ac=c: ac.get("/api/v1/legal/nonexistent"), 404)

        # ── 3. Auth / User ─────────────────────────────
        print("\n── 3. Auth & User ──")
        r = await c.get("/auth/me", headers=AUTH)
        u = r.json()
        print(f"  User: clerk_id={u.get('clerk_user_id','?')[:20]}, tier={u.get('tier')}")
        await check("3a. GET /auth/me", lambda ac=c: ac.get("/auth/me", headers=AUTH), 200)
        await check("3b. GET /auth/me (no token → 401)", lambda ac=c: ac.get("/auth/me"), 401)

        # ── 4. Trial ───────────────────────────────────
        print("\n── 4. Trial Flow ──")
        r = await c.get("/api/v1/trial/status", headers=AUTH)
        print(f"  Before: in_trial={r.json().get('in_trial')}, tier={r.json().get('effective_tier')}")
        await check("4a. Trial status (fresh)", lambda ac=c: ac.get("/api/v1/trial/status", headers=AUTH), 200)
        await check("4b. Start trial", lambda ac=c: ac.post("/api/v1/trial/start", headers=AUTH), 200)
        r = await c.get("/api/v1/trial/status", headers=AUTH)
        print(f"  After start: in_trial={r.json().get('in_trial')}, days={r.json().get('days_remaining')}, tier={r.json().get('effective_tier')}")
        await check("4c. Trial status (active)", lambda ac=c: ac.get("/api/v1/trial/status", headers=AUTH), 200)
        await check("4d. Start idempotent", lambda ac=c: ac.post("/api/v1/trial/start", headers=AUTH), 200)
        await check("4e. Trial cron (daily)", lambda ac=c: ac.post("/api/v1/trial/cron-daily", headers=CRON), 200)

        # ── 5. Research ─────────────────────────────────
        print("\n── 5. Research Pipeline ──")
        await check("5a. POST /research/start", lambda ac=c: ac.post(
            f"/api/research/start?idea={IDEA}&use_llm=false", headers=AUTH), 200)
        r = await c.post(f"/api/research/start?idea={IDEA}&use_llm=false", headers=AUTH)
        pid = r.json().get("project_id", "")
        print(f"  project_id: {pid[:24]}...")

        if pid:
            await asyncio.sleep(2)
            r = await c.get(f"/api/projects/{pid}/state", headers=AUTH)
            st = r.json()
            print(f"  Research status: {st.get('research',{}).get('status','?')}")
            await check("5b. GET project state", lambda ac=c, p=pid: ac.get(f"/api/projects/{p}/state", headers=AUTH), 200)

            # ── 6. Planning ─────────────────────────────
            print("\n── 6. Planning Pipeline ──")
            await check("6a. POST /plan/start", lambda ac=c, p=pid: ac.post(
                f"/api/plan/start?idea={IDEA}&project_id={p}&use_llm=false", headers=AUTH), 200)
            r = await c.post(f"/api/plan/start?idea={IDEA}&project_id={pid}&use_llm=false", headers=AUTH)
            print(f"  Plan: status={r.json().get('status','?')}, duration_ms={r.json().get('duration_ms','?')}")
            await asyncio.sleep(2)
            r = await c.get(f"/api/projects/{pid}/state", headers=AUTH)
            st = r.json()
            print(f"  Planning status: {st.get('planning',{}).get('status','?')}")
            await check("6b. Project state (planning)", lambda ac=c, p=pid: ac.get(f"/api/projects/{p}/state", headers=AUTH), 200)

            # ── 7. Generate ─────────────────────────────
            print("\n── 7. Generate Assets ──")
            await check("7a. POST /generate", lambda ac=c, p=pid: ac.post(
                f"/api/generate?idea={IDEA}&project_id={p}", headers=AUTH), 200)
            r = await c.post(f"/api/generate?idea={IDEA}&project_id={pid}", headers=AUTH)
            # generate may return 202 if async or 200 if sync
            print(f"  Generate: status={r.json().get('status','?')}")

        # ── 8. Usage ────────────────────────────────────
        print("\n── 8. Usage Tracking ──")
        r = await c.get("/api/v1/usage/status", headers=AUTH)
        rc = r.json().get("research_call", {}).get("current", 0)
        print(f"  research_calls used: {rc}")
        await check("8a. Usage status", lambda ac=c: ac.get("/api/v1/usage/status", headers=AUTH), 200)
        await check("8b. Usage limits", lambda ac=c: ac.get("/api/v1/usage/limits", headers=AUTH), 200)
        await check("8c. Usage history", lambda ac=c: ac.get("/api/v1/usage/history", headers=AUTH), 200)

        # ── 9. GDPR ─────────────────────────────────────
        print("\n── 9. GDPR ──")
        await check("9a. GET deletion-status", lambda ac=c: ac.get("/api/v1/users/me/deletion-status", headers=AUTH), 200)
        await check("9b. POST consent", lambda ac=c: ac.post("/api/v1/users/me/consents",
            json={"purpose": "marketing_email", "granted": True}, headers=AUTH), 204)
        await check("9c. GET consents", lambda ac=c: ac.get("/api/v1/users/me/consents", headers=AUTH), 200)
        await check("9d. Cancel deletion (no pending → 404)", lambda ac=c: ac.post(
            "/api/v1/users/me/cancel-deletion", headers=AUTH), 404)

    # ── Summary ─────────────────────────────────────────
    total = len(results)
    ok = sum(1 for r in results.values() if r["ok"])
    fail = total - ok
    print(f"\n{'='*50}")
    if fail == 0:
        print(f"  E2E SMOKE: {ok}/{total} PASSED ✅")
    else:
        print(f"  E2E SMOKE: {ok}/{total} PASSED, {fail} FAILED ❌")
    print(f"{'='*50}")
    for name, r in results.items():
        if not r["ok"]:
            print(f"  ❌ {name}: HTTP {r['status']} — {r['body'][:120]}")
    return fail


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
