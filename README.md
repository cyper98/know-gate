# KnowGate

> Open-source (MIT) internal knowledge search & Q&A platform. RAG-based, multilingual, permission-aware.

## Quickstart

```bash
# 1. Copy env template
cp .env.example .env

# 2. Generate JWT key pair + encryption key
make secrets
# Add the printed KG_ENCRYPTION_KEY=... to your .env

# 3. (Optional) Fill OAuth keys, SMTP, OpenAI API key in .env
#    Dev defaults work without these (no OAuth, mailhog catches emails)

# 4. Start all services
make up

# 5. Verify
curl http://localhost:8000/health
open http://localhost:3000   # Web UI
```

## Services (docker compose)

| Service     | Port       | URL                          | Notes                            |
|-------------|------------|------------------------------|----------------------------------|
| API         | 8000       | http://localhost:8000        | FastAPI                          |
| API docs    | 8000       | http://localhost:8000/docs   | OpenAPI Swagger                  |
| Frontend    | 3000       | http://localhost:3000        | Next.js 14 App Router            |
| LiteLLM     | 4000       | http://localhost:4000        | LLM gateway (OpenAI-compatible)  |
| PostgreSQL  | 5432       | localhost:5432               | App data                         |
| Qdrant      | 6333       | http://localhost:6333        | Vector store                     |
| Redis       | 6379       | localhost:6379               | Cache + Celery queue             |
| MinIO       | 9000/9001  | http://localhost:9001        | S3 + console (knowgate/pwd)      |
| MailHog     | 1025/8025  | http://localhost:8025        | SMTP dev (catches all emails)    |
| Worker      | —          | —                            | Celery worker (no port)          |
| Beat        | —          | —                            | Celery scheduler (no port)       |

## Development

```bash
make logs       # Tail all logs
make ps         # List services
make test       # Run backend tests
make lint       # Lint (ruff + eslint)
make format     # Format (ruff format + prettier)
make migrate    # Run DB migrations
make seed       # Seed initial data
make down       # Stop services
make clean      # Remove all data (DESTRUCTIVE)
```

## Project Structure

```
know-gate/
├── backend/         # FastAPI app (Python 3.12)
│   ├── app/
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/        # Next.js 14 (TypeScript)
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── package.json
│   └── Dockerfile
├── cli/             # Python CLI (Typer) — Phase 9
├── deploy/          # docker-compose.yml + env templates
├── secrets/         # JWT keys (gitignored, generated)
├── plans/           # Architecture + implementation plan
└── docs/            # Brainstorm + requirements
```

## Documentation

- [Architecture](plans/260613-knowgate-mvp-architecture/architecture.md) — full system design
- [Tech Stack ADR](plans/260613-knowgate-mvp-architecture/decisions/tech-stack.md)

## License

MIT — see [LICENSE](LICENSE)
