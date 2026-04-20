# Project: ai-software-diagramming

You reverse-engineer C4 architecture diagrams from a Python/TypeScript/Go
(mono)repo and publish them as editable `.drawio` files (default) or into
Lucidchart via the Lucid MCP server.

Levels: L1 (System Context) → L2 (Container) → L3 (Component).
**L4 (Code) is deliberately skipped** — class-level detail adds noise without
changing architectural decisions at typical review granularity.

## Unit model

The extractor identifies **units** — dirs that declare their own identity:

| Manifest file    | Unit type         | Name source                    |
| ---------------- | ----------------- | ------------------------------ |
| `go.mod`         | Go module         | `module` directive             |
| `package.json`   | npm/TS package    | `"name"` field                 |
| `pyproject.toml` | Python dist       | `[project].name`               |
| `setup.py`/`.cfg`| Python dist       | dir name (fallback)            |

Each unit becomes one Structurizr **container** in the seed, **except**:

- **Non-deployable libraries with exactly one consumer are collapsed**
  into that consumer — their components become components of the
  consumer's container (labelled `Merged from <lib> library`).
- **Shared libraries** (non-deployable, imported by >1 consumer) stay
  as their own container with a `Shared Library` tag.
- **Deployable services** (Dockerfile / `main.go` / `__main__.py` / npm
  `start`/`dev`/`bin`) always stay as their own container, tagged
  `Service`.

Cross-unit imports become container-to-container relationships, with
edges redirected around collapsed libraries. The seeder also partitions
L2 into per-top-level-dir views (`L2_services`, `L2_packages`, ...) plus
a full `L2_all` when there are enough containers to warrant it.

External imports (third-party libs) are listed per-unit for the L1
refinement step.

## Workflow

User drives with slash commands:

1. **`/extract <repo-url-or-path>`** — clones (if URL) and runs the
   language-agnostic extractor + seeder. Produces:
   - `build/raw/manifest.json` — all units + summary
   - `build/raw/imports/<unit>.json` — per-unit import graph
     (internal / cross-unit / external)
   - `out/workspace.dsl` — seed Structurizr DSL

2. **`/l3`** — refine components *inside* each container. Read
   `build/raw/source/<unit-path>/` and `build/raw/imports/<unit>.json`.
   Re-cluster by **responsibility**, not filename. Components like
   "Session Manager", "Auth Adapter", "HTTP Router" — never "sessions.py"
   or "handlers/".

3. **`/l2`** — the seed puts every detected unit in its own container. In
   a real monorepo that's usually too many. Decide which units actually
   run as **separate deployable processes** (services, CLIs, workers, web
   servers, DBs) vs which are libraries consumed by others. Merge
   library-units into their consumer containers, or promote them to
   shared-library containers. Read:
   - `Dockerfile`, `docker-compose.yml`, `k8s/`, `Procfile`
   - `.github/workflows/`, `Makefile`, `Taskfile.yml`, `justfile`
   - Entry points: `main.go`, `__main__.py`, `bin/`, npm `"scripts"`,
     `ENTRYPOINT`/`CMD` in Dockerfiles

4. **`/l1`** — promote externals from each unit's `external` list to L1
   `softwareSystem` blocks. Grep patterns per language:

   | Signal                | Python                          | TypeScript/JS                      | Go                                             |
   | --------------------- | ------------------------------- | ---------------------------------- | ---------------------------------------------- |
   | HTTP client           | `requests`, `httpx`, `aiohttp`  | `fetch`, `axios`, `node-fetch`, `got` | `net/http`, `resty`                          |
   | Database              | `psycopg`, `sqlalchemy`, `pymongo`, `redis` | `pg`, `mysql2`, `mongodb`, `ioredis` | `database/sql`, `lib/pq`, `mongo-driver`, `go-redis` |
   | Queue / event stream  | `kafka`, `pika`, `celery`, `boto3.*sqs`    | `kafkajs`, `amqplib`, `@aws-sdk/client-sqs` | `kafka-go`, `segmentio/kafka-go`, `streadway/amqp` |
   | Cloud SDK             | `boto3`, `google.cloud.*`, `azure.*` | `@aws-sdk/*`, `@google-cloud/*`, `@azure/*` | `aws-sdk-go`, `cloud.google.com/go/*`         |
   | Auth / IdP            | `jwt`, `authlib`, `msal`        | `jsonwebtoken`, `passport`, `@okta/*` | `golang-jwt/jwt`, `coreos/go-oidc`          |
   | gRPC                  | `grpclib`, `grpcio`             | `@grpc/grpc-js`                     | `google.golang.org/grpc`                     |

   Add personas (Admin, Operator, API Consumer) by grepping auth/role code.

## Output rules

- Source of truth: `out/workspace.dsl`.
- Render with `structurizr-cli export -workspace out/workspace.dsl -format mermaid -output out/views` after each level.
- `.drawio` files: `python scripts/render_drawio.py --yes` → `out/drawio/<viewKey>.drawio`.

## Publishing

Default: offline `.drawio` files (no OAuth).

```bash
python scripts/render_drawio.py --yes   # out/drawio/*.drawio
```

`/publish` accepts:
- **drawio** (default) — writes `.drawio`; open in draw.io or `File > Import > draw.io` in Lucid.
- **lucid** — pushes via Lucid MCP (`mcp__lucid__*`). Requires `/mcp` auth. Confirm target doc name.
- **mermaid** — emits `out/views/structurizr-<Lx>.mmd` for paste-into-Lucid or docs.

Never push to a hosted tool silently — confirm the target document first.

## Quality bar

- Every view fits on one screen. If >25 elements, split or push detail down a level.
- Every relationship has a verb-phrase label ("publishes to", "reads from", "authenticates via").
- Component names describe **responsibility**, not file path.
- Container technology tags use the canonical name: `Python`, `TypeScript`, `Go`, `PostgreSQL`, `Redis`, `Kafka`.

## Don'ts

- Don't treat every detected unit as a deployable container — most monorepos have many more units than services. Collapse in L2.
- Don't invent externals not present in `imports/*.json`. If in doubt, grep the source and ask.
- Don't push to Lucid silently.
