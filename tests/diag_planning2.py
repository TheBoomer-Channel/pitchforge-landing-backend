"""Quick diagnostic: test planning with use_llm=false and measure each phase."""
import httpx, asyncio, uuid, time

IDEA = "AI-powered project management for remote teams"
TOKEN = f"diag-{uuid.uuid4().hex[:6]}"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

async def main():
    async with httpx.AsyncClient(base_url="http://localhost:8086", timeout=180) as c:
        # Auth
        await c.get("/auth/me", headers=AUTH)
        
        # Research
        t0 = time.monotonic()
        r = await c.post(f"/api/research/start?idea={IDEA}&use_llm=false", headers=AUTH)
        pid = r.json().get("project_id")
        print(f"Research: {r.status_code} in {time.monotonic()-t0:.1f}s, project_id={pid[:24] if pid else 'NONE'}")
        
        if not pid:
            print("FAILED: no project_id")
            return
        
        # Planning with use_llm=false
        t0 = time.monotonic()
        print("Calling planning with use_llm=false...")
        r = await c.post(
            f"/api/plan/start?idea={IDEA}&project_id={pid}&use_llm=false",
            headers=AUTH
        )
        elapsed = time.monotonic() - t0
        print(f"Planning: {r.status_code} in {elapsed:.1f}s")
        
        if r.status_code == 200:
            body = r.json()
            print(f"  status: {body.get('status')}")
            print(f"  duration_ms: {body.get('duration_ms')}")
            print(f"  outputs: {list(body.get('outputs', {}).keys())}")
        else:
            print(f"  Body: {r.text[:500]}")

asyncio.run(main())
