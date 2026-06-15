"""Dashboard routes — simple web UI for the research engine."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PitchForge</title>
<script src="https://cdn.tailwindcss.com"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
body { font-family: 'DM Sans', sans-serif; background: #0f172a; color: #e2e8f0; }
.card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; }
.btn-primary { background: #3b82f6; color: white; padding: 12px 24px; border-radius: 8px; font-weight: 600; transition: all 0.2s; }
.btn-primary:hover { background: #2563eb; transform: translateY(-1px); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.input-field { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 12px; color: #e2e8f0; width: 100%; }
.input-field:focus { outline: none; border-color: #3b82f6; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.tag-green { background: #064e3b; color: #6ee7b7; }
.tag-blue { background: #1e3a5f; color: #93c5fd; }
.tag-yellow { background: #451a03; color: #fcd34d; }
.tag-red { background: #450a0a; color: #fca5a5; }
</style>
</head>
<body class="p-6 max-w-5xl mx-auto">

<div class="flex items-center justify-between mb-8">
  <div>
    <h1 class="text-3xl font-bold text-white">PitchForge</h1>
    <p class="text-slate-400 mt-1">Research any startup idea in minutes</p>
  </div>
  <div class="text-sm text-slate-500">v0.2</div>
</div>

<div class="card p-6 mb-8">
  <h2 class="text-xl font-semibold mb-4">🔬 New Research</h2>
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
    <div class="md:col-span-2">
      <label class="block text-sm text-slate-400 mb-1">Startup Idea *</label>
      <input id="idea" class="input-field" placeholder="e.g., AI-powered freight marketplace for Angola">
    </div>
    <div>
      <label class="block text-sm text-slate-400 mb-1">Target Market</label>
      <input id="market" class="input-field" placeholder="e.g., logistics Africa">
    </div>
  </div>
  <button onclick="startResearch()" id="researchBtn" class="btn-primary">🚀 Start Research</button>
  <div id="loading" class="hidden mt-4 text-slate-400">
    <span class="inline-block animate-pulse">⏳ Researching... (this takes 30-90s)</span>
  </div>
</div>

<div id="results" class="hidden"></div>

<div id="history" class="mt-8"></div>

<script>
async function startResearch() {
  const idea = document.getElementById('idea').value.trim();
  const market = document.getElementById('market').value.trim();
  if (!idea) { alert('Please enter a startup idea'); return; }
  
  document.getElementById('researchBtn').disabled = true;
  document.getElementById('loading').classList.remove('hidden');
  document.getElementById('results').classList.add('hidden');
  
  try {
    const params = new URLSearchParams({ idea });
    if (market) params.set('target_market', market);
    
    const resp = await fetch(`/api/research/start?${params}`, { method: 'POST' });
    const data = await resp.json();
    
    if (data.status === 'complete') {
      renderResults(data);
      loadHistory();
    } else {
      alert('Error: ' + (data.detail || 'Unknown error'));
    }
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    document.getElementById('researchBtn').disabled = false;
    document.getElementById('loading').classList.add('hidden');
  }
}

function renderResults(data) {
  const el = document.getElementById('results');
  el.classList.remove('hidden');
  
  let competitorsHtml = '';
  if (data.competitors_found > 0 && data.market_validation) {
    // We only have summary data from the inline endpoint
  }
  
  el.innerHTML = `
    <div class="card p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-semibold">📊 Research Results</h2>
        <span class="tag tag-green">${data.duration_ms}ms</span>
      </div>
      
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div class="text-center p-4 bg-slate-800 rounded-lg">
          <div class="text-2xl font-bold text-blue-400">${data.competitors_found}</div>
          <div class="text-sm text-slate-400">Competitors</div>
        </div>
        <div class="text-center p-4 bg-slate-800 rounded-lg">
          <div class="text-2xl font-bold text-green-400">${data.recommended_mvp_features?.length || 0}</div>
          <div class="text-sm text-slate-400">MVP Features</div>
        </div>
        <div class="text-center p-4 bg-slate-800 rounded-lg">
          <div class="text-2xl font-bold text-yellow-400">${data.risk_factors?.length || 0}</div>
          <div class="text-sm text-slate-400">Risk Factors</div>
        </div>
        <div class="text-center p-4 bg-slate-800 rounded-lg">
          <div class="text-2xl font-bold text-purple-400">${data.market_validation?.hn_mentions || 0}</div>
          <div class="text-sm text-slate-400">HN Mentions</div>
        </div>
      </div>
      
      <div class="mb-4">
        <h3 class="font-semibold mb-2">Summary</h3>
        <p class="text-slate-300">${data.summary || 'No summary available'}</p>
      </div>
      
      ${data.recommended_mvp_features?.length ? `
      <div class="mb-4">
        <h3 class="font-semibold mb-2">✅ Recommended MVP Features</h3>
        <ul class="list-disc list-inside text-slate-300">
          ${data.recommended_mvp_features.map(f => `<li>${f}</li>`).join('')}
        </ul>
      </div>` : ''}
      
      ${data.recommended_pricing ? `
      <div class="mb-4">
        <h3 class="font-semibold mb-2">💰 Pricing</h3>
        <p class="text-slate-300">${data.recommended_pricing}</p>
      </div>` : ''}
      
      ${data.recommended_positioning ? `
      <div class="mb-4">
        <h3 class="font-semibold mb-2">🎯 Positioning</h3>
        <p class="text-slate-300">${data.recommended_positioning}</p>
      </div>` : ''}
      
      ${data.risk_factors?.length ? `
      <div>
        <h3 class="font-semibold mb-2">⚠️ Risk Factors</h3>
        <ul class="list-disc list-inside text-slate-300">
          ${data.risk_factors.map(r => `<li>${r}</li>`).join('')}
        </ul>
      </div>` : ''}
    </div>
  `;
  
  // Scroll to results
  el.scrollIntoView({ behavior: 'smooth' });
}

async function loadHistory() {
  try {
    const resp = await fetch('/api/research/?limit=5');
    const data = await resp.json();
    const el = document.getElementById('history');
    
    if (data.projects?.length) {
      el.innerHTML = `
        <h2 class="text-xl font-semibold mb-4">📋 Recent Research</h2>
        <div class="space-y-3">
          ${data.projects.map(p => `
            <div class="card p-4 flex items-center justify-between">
              <div>
                <div class="font-medium">${p.title}</div>
                <div class="text-sm text-slate-400">${new Date(p.created_at).toLocaleString()}</div>
              </div>
              <span class="tag ${p.status === 'complete' ? 'tag-green' : p.status === 'error' ? 'tag-red' : 'tag-yellow'}">${p.status}</span>
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch(e) { /* ignore */ }
}

// Load history on page load
loadHistory();
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML
