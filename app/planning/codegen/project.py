"""Project scaffold — directories, Docker, configs, README, Makefile."""

import logging
from pathlib import Path

from ..models import TechnicalSpec, FinancialModel

logger = logging.getLogger(__name__)


def scaffold_project(output_dir: str, tech: TechnicalSpec, fin: FinancialModel) -> dict:
    """Create full project directory structure and config files.
    
    Generates:
    - Docker Compose con healthchecks y profiles
    - GitHub Actions CI/CD
    - Alembic migrations setup
    - Professional README with badges
    - Test fixtures (conftest.py)
    - Makefile with dev/test/lint/migrate/deploy commands
    """
    out = Path(output_dir)
    dirs = [
        "app/models",
        "app/schemas",
        "app/routes",
        "app/core",
        ".github/workflows",
        "alembic/versions",
        "tests",
        "frontend/src/pages",
        "frontend/src/components",
        "frontend/src/api",
        "frontend/src/hooks",
        "frontend/src/i18n",
        "frontend/public",
    ]
    for d in dirs:
        (out / d).mkdir(parents=True, exist_ok=True)

    files = {}

    # ── docker-compose.yml ──
    files[out / "docker-compose.yml"] = _docker_compose()
    files[out / "Makefile"] = _makefile()
    files[out / "README.md"] = _readme(tech, fin)
    files[out / ".env.example"] = _env_example()
    files[out / ".gitignore"] = _gitignore()

    # ── CI/CD ──
    files[out / ".github/workflows/ci.yml"] = _github_actions_ci()

    # ── Backend configs ──
    files[out / "Dockerfile"] = _backend_dockerfile()
    files[out / "requirements.txt"] = _requirements_txt()
    files[out / "app/__init__.py"] = ""
    files[out / "app/config.py"] = _app_config()
    files[out / "app/database.py"] = _app_database()
    files[out / "app/main.py"] = _app_main()
    files[out / "app/core/__init__.py"] = ""
    files[out / "app/core/security.py"] = _security()
    files[out / "app/core/auth.py"] = _auth_middleware()
    files[out / "app/core/errors.py"] = _error_handlers()
    files[out / "app/core/deps.py"] = _dependencies()

    # ── Alembic ──
    files[out / "alembic.ini"] = _alembic_ini()
    files[out / "alembic/env.py"] = _alembic_env()
    files[out / "alembic/script.py.mako"] = _alembic_mako()

    # ── Tests ──
    files[out / "tests/__init__.py"] = ""
    files[out / "tests/conftest.py"] = _pytest_conftest()
    files[out / "tests/test_health.py"] = _test_health()

    # ── Frontend configs ──
    files[out / "frontend/package.json"] = _package_json()
    files[out / "frontend/tsconfig.json"] = _tsconfig()
    files[out / "frontend/vite.config.ts"] = _vite_config()
    files[out / "frontend/index.html"] = _html(tech)
    files[out / "frontend/Dockerfile"] = _frontend_dockerfile()
    files[out / "frontend/postcss.config.js"] = _postcss_config()
    files[out / "frontend/tailwind.config.js"] = _tailwind_config()
    files[out / "frontend/src/main.tsx"] = _main_tsx()
    files[out / "frontend/src/App.tsx"] = _app_tsx()
    files[out / "frontend/src/index.css"] = _tailwind_css()
    files[out / "frontend/src/api/client.ts"] = _api_client()
    files[out / "frontend/src/components/Layout.tsx"] = _layout()
    files[out / "frontend/src/hooks/useTheme.ts"] = _use_theme_hook()
    files[out / "frontend/src/i18n/en.json"] = _i18n_en()
    files[out / "frontend/src/i18n/es.json"] = _i18n_es()
    files[out / "frontend/src/i18n/index.ts"] = _i18n_index()

    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        logger.info(f"  ✦ {path.relative_to(out)}")

    return {"dirs_created": len(dirs), "files_created": len(files)}


# ── File templates ─────────────────────────────────────

def _docker_compose() -> str:
    return """version: "3.8"

services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    volumes: [./app:/app/app]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s

  worker:
    build: .
    command: python -m app.worker
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
    volumes: [./app:/app/app]

  frontend:
    build: ./frontend
    ports: ["5173:80"]
    depends_on: [api]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80"]
      interval: 10s
      timeout: 5s
      retries: 3

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: app
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    volumes: [redis_data:/data]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
  redis_data:
"""

def _makefile() -> str:
    return """.PHONY: dev up down migrate test lint seed deploy logs shell clean

dev:
\tdocker compose up --build -d
\tdocker compose logs -f api

up:
\tdocker compose up -d

down:
\tdocker compose down

migrate:
\tdocker compose exec api alembic upgrade head

test:
\tdocker compose exec api pytest tests/ -v

lint:
\tdocker compose exec api ruff check . --fix

seed:
\tdocker compose exec api python -m app.seed

deploy:
\tdocker compose -f docker-compose.yml up -d --build

logs:
\tdocker compose logs -f

shell:
\tdocker compose exec api bash

clean:
\tdocker compose down -v
\trm -rf __pycache__ .pytest_cache
"""

def _readme(tech: TechnicalSpec, fin: FinancialModel) -> str:
    name = tech.stack_recommendation or "MVP Project"
    infra = f"${tech.estimated_infra_cost_monthly:.0f}/mo" if tech.estimated_infra_cost_monthly else "TBD"
    pricing = fin.executive_summary or ""
    stack_rows = "\n".join(
        f"| {s.get('layer', '')} | {s.get('technology', '')} |"
        for s in tech.stack_table[:6]
    )
    arch_diagram = """```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│     API      │────▶│  PostgreSQL  │
│  (React/Vite)│     │  (FastAPI)   │     │   (SQLModel) │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                     ┌──────▼──────┐
                     │    Redis     │
                     │  (Cache/Q)   │
                     └─────────────┘
```"""
    return f"""# {name}

[![CI](https://github.com/user/repo/actions/workflows/ci.yml/badge.svg)](https://github.com/user/repo/actions)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Quick Start

```bash
# Clone and start
make dev

# Run tests
make test

# Apply migrations
make migrate
```

Open http://localhost:8000/docs for API documentation.

## Architecture

{arch_diagram}

## Stack

| Layer | Technology |
|-------|-----------|
{stack_rows}

## Commands

| Command | Description |
|---------|-------------|
| `make dev` | Start development environment |
| `make test` | Run test suite |
| `make lint` | Run linter |
| `make migrate` | Apply DB migrations |
| `make seed` | Seed database |
| `make logs` | View logs |
| `make shell` | API container shell |

## Infra Cost

Estimated: **{infra}**

## API Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## CI/CD

GitHub Actions runs on every push:
- Lint (ruff)
- Tests (pytest)
- Build (Docker)

## Pricing

{pricing}

---
*Generated by PitchForge CodeGen 2.0*
"""

def _env_example() -> str:
    return """DATABASE_URL=postgresql+asyncpg://app:changeme@db:5432/app
SECRET_KEY=change-me-in-production
ENVIRONMENT=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:5173
"""

def _gitignore() -> str:
    return """__pycache__/
*.pyc
.env
.venv/
node_modules/
dist/
.vite/
*.db
.DS_Store
"""

def _backend_dockerfile() -> str:
    return """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
"""

def _requirements_txt() -> str:
    return """fastapi[standard]==0.115.0
uvicorn[standard]==0.30.0
sqlmodel==0.0.22
alembic==1.13.0
asyncpg==0.30.0
httpx==0.27.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
pydantic[email]==2.9.0
pydantic-settings==2.5.0
"""

def _app_config() -> str:
    return """from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "MVP"
    DATABASE_URL: str = "postgresql+asyncpg://app:changeme@db:5432/app"
    SECRET_KEY: str = "insecure-change-me"
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_LEVEL: str = "INFO"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
"""

def _app_database() -> str:
    return """from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from .config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
"""

def _app_main() -> str:
    return """from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routes import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
"""

def _security() -> str:
    return """from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, secret: str, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)
"""

def _package_json() -> str:
    return """{
  "name": "mvp-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.26.0",
    "axios": "^1.7.0",
    "@tanstack/react-query": "^5.56.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.0.0",
    "@testing-library/react": "^16.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
"""

def _tsconfig() -> str:
    return """{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false
  },
  "include": ["src"]
}
"""

def _vite_config() -> str:
    return """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://backend:8000',
    },
  },
})
"""

def _html(tech: TechnicalSpec) -> str:
    name = tech.stack_recommendation or "MVP"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name[:60]}</title>
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""

def _frontend_dockerfile() -> str:
    return """FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""

def _main_tsx() -> str:
    return """import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

const queryClient = new QueryClient()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
"""

def _app_tsx() -> str:
    return """import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'

// Lazy-loaded pages for code splitting
const Home = lazy(() => import('./pages/Home'))
const Dashboard = lazy(() => import('./pages/Dashboard'))

function PageLoader() {
  return (
    <div className="space-y-4 p-8">
      <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-8 w-64" />
      <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-4 w-full" />
      <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-4 w-3/4" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-8">
        <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-32" />
        <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-32" />
        <div className="animate-pulse bg-slate-200 dark:bg-slate-700 rounded h-32" />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}
"""

def _api_client() -> str:
    return """import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default api
"""

def _layout() -> str:
    return """import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from '../i18n'
import { ThemeToggle } from './ThemeToggle'
import { LanguageSwitcher } from './LanguageSwitcher'

export default function Layout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()

  const navItems = [
    { href: '/', label: t('nav.home') },
    { href: '/dashboard', label: t('nav.dashboard') },
  ]

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100 transition-colors">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-950/95 backdrop-blur-sm">
        <div className="max-w-7xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              aria-label="Toggle menu"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={sidebarOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
              </svg>
            </button>
            <Link to="/" className="text-xl font-bold text-teal-600 dark:text-teal-400">
              MVP
            </Link>
            <nav className="hidden lg:flex items-center gap-1 ml-8">
              {navItems.map(item => (
                <Link
                  key={item.href}
                  to={item.href}
                  className={`px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    location.pathname === item.href
                      ? 'bg-teal-50 dark:bg-teal-500/10 text-teal-700 dark:text-teal-400'
                      : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/* Mobile sidebar */}
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-30">
          <div className="fixed inset-0 bg-black/50" onClick={() => setSidebarOpen(false)} />
          <nav className="fixed left-0 top-16 bottom-0 w-64 bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 p-4">
            {navItems.map(item => (
              <Link
                key={item.href}
                to={item.href}
                onClick={() => setSidebarOpen(false)}
                className={`block px-3 py-2 rounded-lg text-sm font-medium mb-1 transition-colors ${
                  location.pathname === item.href
                    ? 'bg-teal-50 dark:bg-teal-500/10 text-teal-700 dark:text-teal-400'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      )}

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-8">{children}</main>
    </div>
  )
}
"""


# ── New CodeGen 2.0 templates ──────────────────────────

def _github_actions_ci() -> str:
    return """name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install ruff
      - run: ruff check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: app
          POSTGRES_PASSWORD: changeme
          POSTGRES_DB: app_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-asyncio httpx
      - run: pytest tests/ -v
        env:
          DATABASE_URL: postgresql+asyncpg://app:changeme@localhost:5432/app_test
          REDIS_URL: redis://localhost:6379
          SECRET_KEY: test-secret-key
          ENVIRONMENT: test

  build:
    runs-on: ubuntu-latest
    needs: [lint, test]
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build
"""


def _alembic_ini() -> str:
    return """[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://app:changeme@db:5432/app

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
"""


def _alembic_env() -> str:
    return """import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from sqlmodel import SQLModel

from app.models import *  # noqa: F401, F403
from app.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""


def _alembic_mako() -> str:
    return '"""${message}\n\nRevision ID: ${up_revision}\nRevises: ${down_revision | comma,n}\nCreate Date: ${create_date}\n"""\nfrom typing import Sequence, Union\n\nfrom alembic import op\nimport sqlalchemy as sa\nimport sqlmodel\n${imports if imports else ""}\n\nrevision: str = ${repr(up_revision)}\ndown_revision: Union[str, None] = ${repr(down_revision)}\nbranch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}\ndepends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}\n\n\ndef upgrade() -> None:\n    ${upgrades if upgrades else "pass"}\n\n\ndef downgrade() -> None:\n    ${downgrades if downgrades else "pass"}\n'


def _pytest_conftest() -> str:
    return """import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlmodel import SQLModel

from app.main import app
from app.database import get_session
from app.config import settings

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_sessionmaker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_session():
    async with test_sessionmaker() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
"""


def _test_health() -> str:
    return """import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
"""


def _auth_middleware() -> str:
    return """from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from .security import ALGORITHM
from ..config import settings
from ..database import get_session

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: AsyncSession = Depends(get_session),
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": user_id, "payload": payload}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    if credentials is None:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        return {"user_id": payload.get("sub"), "payload": payload}
    except JWTError:
        return None
"""


def _error_handlers() -> str:
    return """from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "path": str(request.url.path),
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append({
            "field": " -> ".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "status_code": 422,
            "details": errors,
            "path": str(request.url.path),
        },
    )


async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "path": str(request.url.path),
        },
    )


def register_error_handlers(app):
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    return app
"""


def _dependencies() -> str:
    return """from typing import Optional
from fastapi import Query


async def pagination(
    skip: int = Query(0, ge=0, description="Items to skip"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict:
    return {"skip": skip, "limit": limit}
"""


def _use_theme_hook() -> str:
    return """import { useState, useEffect } from 'react'

type Theme = 'system' | 'dark' | 'light'

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = localStorage.getItem('theme')
    return (stored as Theme) || 'system'
  })

  useEffect(() => {
    const root = document.documentElement
    const applyTheme = (t: Theme) => {
      if (t === 'system') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        root.classList.toggle('dark', prefersDark)
        root.setAttribute('data-theme', prefersDark ? 'dark' : 'light')
      } else {
        root.classList.toggle('dark', t === 'dark')
        root.setAttribute('data-theme', t)
      }
    }
    applyTheme(theme)
    localStorage.setItem('theme', theme)

    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)')
      const handler = () => applyTheme('system')
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    }
  }, [theme])

  const setTheme = (t: Theme) => setThemeState(t)

  const cycleTheme = () => {
    const cycle: Theme[] = ['system', 'dark', 'light']
    const idx = cycle.indexOf(theme)
    setThemeState(cycle[(idx + 1) % cycle.length])
  }

  return { theme, setTheme, cycleTheme }
}
"""


def _i18n_en() -> str:
    return """{
  "nav.home": "Home",
  "nav.dashboard": "Dashboard",
  "nav.settings": "Settings",
  "nav.profile": "Profile",
  "theme.system": "System",
  "theme.dark": "Dark",
  "theme.light": "Light",
  "lang.en": "English",
  "lang.es": "Español",
  "home.title": "Welcome to Your MVP",
  "home.subtitle": "Generated by PitchForge — your idea, your product, fast.",
  "home.cta": "Get Started",
  "home.features": "Core Features",
  "dashboard.title": "Dashboard",
  "dashboard.welcome": "Welcome back",
  "dashboard.loading": "Loading...",
  "dashboard.noData": "No data yet",
  "dashboard.apiStatus": "API Status",
  "form.save": "Save",
  "form.cancel": "Cancel",
  "form.delete": "Delete",
  "form.create": "Create",
  "form.edit": "Edit",
  "form.required": "Required",
  "errors.notFound": "Not found",
  "errors.serverError": "Server error",
  "errors.unauthorized": "Unauthorized",
  "table.empty": "No items found",
  "table.loading": "Loading items...",
  "actions.view": "View",
  "actions.edit": "Edit",
  "actions.delete": "Delete"
}
"""


def _i18n_es() -> str:
    return """{
  "nav.home": "Inicio",
  "nav.dashboard": "Panel",
  "nav.settings": "Ajustes",
  "nav.profile": "Perfil",
  "theme.system": "Sistema",
  "theme.dark": "Oscuro",
  "theme.light": "Claro",
  "lang.en": "English",
  "lang.es": "Español",
  "home.title": "Bienvenido a Tu MVP",
  "home.subtitle": "Generado por PitchForge — tu idea, tu producto, rápido.",
  "home.cta": "Comenzar",
  "home.features": "Funcionalidades",
  "dashboard.title": "Panel de Control",
  "dashboard.welcome": "Bienvenido de nuevo",
  "dashboard.loading": "Cargando...",
  "dashboard.noData": "Sin datos aún",
  "dashboard.apiStatus": "Estado de API",
  "form.save": "Guardar",
  "form.cancel": "Cancelar",
  "form.delete": "Eliminar",
  "form.create": "Crear",
  "form.edit": "Editar",
  "form.required": "Requerido",
  "errors.notFound": "No encontrado",
  "errors.serverError": "Error del servidor",
  "errors.unauthorized": "No autorizado",
  "table.empty": "Sin elementos",
  "table.loading": "Cargando elementos...",
  "actions.view": "Ver",
  "actions.edit": "Editar",
  "actions.delete": "Eliminar"
}
"""


def _i18n_index() -> str:
    return """import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import en from './en.json'
import es from './es.json'

type Lang = 'en' | 'es'
type Translations = typeof en

const translations: Record<Lang, Translations> = { en, es }

interface I18nContextType {
  lang: Lang
  t: (key: string) => string
  setLang: (lang: Lang) => void
  availableLangs: Lang[]
}

const I18nContext = createContext<I18nContextType>({
  lang: 'en',
  t: (key: string) => key,
  setLang: () => {},
  availableLangs: ['en', 'es'],
})

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const stored = localStorage.getItem('lang')
    return (stored === 'es' ? 'es' : 'en')
  })

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    localStorage.setItem('lang', l)
    document.documentElement.setAttribute('lang', l)
  }, [])

  const t = useCallback((key: string): string => {
    const keys = key.split('.')
    let value: unknown = translations[lang]
    for (const k of keys) {
      if (value && typeof value === 'object') {
        value = (value as Record<string, unknown>)[k]
      } else {
        return key
      }
    }
    return (value as string) || key
  }, [lang])

  return (
    <I18nContext.Provider value={{ lang, t, setLang, availableLangs: ['en', 'es'] }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useTranslation() {
  return useContext(I18nContext)
}
"""


def _postcss_config() -> str:
    return """export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
"""


def _tailwind_config() -> str:
    return """/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f0fdfa',
          100: '#ccfbf1',
          200: '#99f6e4',
          300: '#5eead4',
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
          800: '#115e59',
          900: '#134e4a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
"""


def _tailwind_css() -> str:
    return """@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  body {
    @apply bg-white dark:bg-slate-950 text-slate-900 dark:text-slate-100;
    font-family: 'Inter', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  ::selection {
    @apply bg-teal-500/20;
  }
}

@layer components {
  .card {
    @apply bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-6;
  }

  .card-hover {
    @apply card hover:border-teal-500/50 dark:hover:border-teal-500/50 hover:shadow-lg transition-all duration-200;
  }
}
"""
