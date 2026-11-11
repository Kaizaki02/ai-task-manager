# AI-Powered Task Manager

A full-stack task manager with secure user accounts and an **AI summary** feature that explains your workload and suggests what to do first.

![CI](https://github.com/YOUR-USERNAME/ai-task-manager/actions/workflows/ci.yml/badge.svg)

> Replace `YOUR-USERNAME` above with your GitHub username after pushing the repo.

## Features

- **User accounts**: register and log in; passwords are salted and hashed (PBKDF2-SHA256), sessions use signed JWT tokens
- **Task CRUD**: create, edit, delete tasks with title, description, priority (low / medium / high), status (to do / in progress / done) and due date
- **Filtering**: by status and priority
- **Data isolation**: every user only ever sees their own tasks (other users' task IDs return 404)
- **AI summary and prioritization**: one click gives a short plain-English summary of open tasks and a suggested order
  - With a free `GROQ_API_KEY` (from console.groq.com), an LLM (Llama 3.3) writes the summary and ranking
  - Without a key (or if the API call fails) it automatically falls back to a deterministic rule-based engine, so the app always works
- **REST API with auto-generated docs** at `/docs` (Swagger UI)
- **Responsive web UI** with dark-mode support (no build step)
- **Quality engineering**: 41 automated tests (97% coverage), linting, and a CI pipeline

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2 |
| Database | SQLAlchemy 2.0 ORM, SQLite (any SQLAlchemy database via `DATABASE_URL`, e.g. PostgreSQL) |
| Auth | JWT (PyJWT), PBKDF2 password hashing |
| AI | Groq API, Llama 3.3 (free, optional) + rule-based fallback |
| Frontend | HTML, CSS, vanilla JavaScript |
| Testing | pytest, pytest-cov, FastAPI TestClient |
| CI/CD | GitHub Actions (lint, tests on Python 3.11 and 3.12, Docker build) |
| Deployment | Docker, Render blueprint (`render.yaml`) |

## Architecture

```
Browser (HTML/JS)
      │  REST + JSON, Bearer JWT
      ▼
FastAPI app  ── auth.py ───── JWT + password hashing
   main.py   ── schemas.py ── request/response validation
      │      ── ai.py ─────── LLM summary → fallback to rules
      ▼
SQLAlchemy ORM (models.py) ──► SQLite / PostgreSQL
```

```
app/
  main.py       API routes and static file hosting
  auth.py       password hashing, JWT creation and verification, current-user dependency
  models.py     User and Task tables
  schemas.py    Pydantic models (validation + response shapes)
  ai.py         summarize_tasks(): LLM call + rule-based fallback
  database.py   engine and session setup
  static/       frontend (index.html)
tests/          auth, tasks, and AI tests
.github/workflows/ci.yml   CI pipeline
Dockerfile, render.yaml    containerization and deployment
```

## Run locally

```bash
git clone https://github.com/YOUR-USERNAME/ai-task-manager.git
cd ai-task-manager

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env             # optional: edit SECRET_KEY / add GROQ_API_KEY
uvicorn app.main:app --reload
```

Open <http://localhost:8000> for the app and <http://localhost:8000/docs> for the API docs.

> The app reads real environment variables. To use values from `.env`, export them first
> (e.g. `export $(grep -v '^#' .env | xargs)` on macOS/Linux) or set them in your shell.

### Enable the real AI summary (optional, free)

1. Create a free account at <https://console.groq.com> and make a key under **API Keys** (no credit card needed).
2. Set it before starting the app:

```bash
# Windows CMD
set GROQ_API_KEY=your-key-here
# Windows PowerShell
$env:GROQ_API_KEY="your-key-here"
# Mac / Linux
export GROQ_API_KEY=your-key-here

uvicorn app.main:app --reload
```

The model defaults to `llama-3.3-70b-versatile`; change it with the `GROQ_MODEL` variable.

The UI shows whether the summary came from the AI model or the built-in rules.

## Run with Docker

```bash
docker build -t ai-task-manager .
docker run -p 8000:8000 -e SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))") ai-task-manager
```

## Run the tests

```bash
ruff check .                        # lint
pytest --cov=app --cov-report=term-missing
```

The tests cover registration/login rules, expired and forged tokens, task CRUD and filtering,
per-user data isolation, the ranking algorithm, the LLM response parsing (with a fake client,
so no API key or network is needed), and the fallback behaviour.

## API overview

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/auth/register` | Create an account | no |
| POST | `/api/auth/login` | Get a JWT (form fields `username`, `password`) | no |
| GET | `/api/auth/me` | Current user | yes |
| GET | `/api/tasks?status=&priority=` | List your tasks (optional filters) | yes |
| POST | `/api/tasks` | Create a task | yes |
| GET | `/api/tasks/{id}` | Get one task | yes |
| PUT | `/api/tasks/{id}` | Update any fields of a task | yes |
| DELETE | `/api/tasks/{id}` | Delete a task | yes |
| POST | `/api/ai/summary` | AI summary and suggested order of open tasks | yes |
| GET | `/api/health` | Health check | no |

## How the AI feature works

`POST /api/ai/summary` collects the user's open tasks and calls `summarize_tasks()`:

1. **LLM path**: if `GROQ_API_KEY` is set, the tasks are sent to a Llama model on Groq with the instruction to treat task text strictly as data (basic prompt-injection hygiene). The reply is parsed as JSON; unknown or duplicate task IDs are discarded and any IDs the model skipped are appended.
2. **Fallback path**: if there is no key, or the call or parsing fails, a rule-based scorer ranks tasks by priority weight, overdue/due-soon bonuses, and a small bonus for tasks already in progress.

This graceful degradation keeps the feature available and the tests deterministic.

## CI/CD

`.github/workflows/ci.yml` runs on every push and pull request:

1. Install dependencies
2. Lint with `ruff`
3. Run the test suite with coverage on Python 3.11 and 3.12
4. Build the Docker image

## Deploy (Render, free tier)

1. Push this repo to GitHub
2. On [render.com](https://render.com): **New → Blueprint** and select the repo (it reads `render.yaml`)
3. Optionally add `GROQ_API_KEY` in the service's environment variables

On the free tier the SQLite file is wiped on redeploy. For persistent data, create a managed PostgreSQL database and set `DATABASE_URL` (add `psycopg[binary]` to `requirements.txt`).

## Design decisions

- **FastAPI** gives typed request validation and automatic OpenAPI docs with little code
- **Per-user queries**: every task query filters by `owner_id`, and tests prove users can't read, edit or delete each other's tasks
- **Stdlib password hashing** (PBKDF2, 200k iterations, per-user salt) avoids extra dependencies
- **No frontend build step**: the UI is a single static file, which keeps deployment to one container
- **Dependency injection** (`get_db`, `get_current_user`) keeps routes small and easy to test

## Future improvements

- Alembic database migrations
- Refresh tokens and rate limiting on login
- Task tags, search, and drag-and-drop ordering
- Move the frontend to React + TypeScript

## Built with AI assistance

This project was built with an AI coding assistant (Claude) used for scaffolding, writing tests, and reviewing edge cases, then run, tested and understood by me. The AI summary feature itself uses an LLM API with a deterministic fallback.
