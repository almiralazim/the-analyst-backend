# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in this project, please report it responsibly.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities via one of these channels:

1. **Email:** Send details to `security@<your-domain>.com`
2. **GitHub Security Advisories:** Use the [private vulnerability reporting](https://github.com/<org>/the-analyst-backend/security/advisories/new) feature

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Suggested fix (if you have one)

### Response Timeline

| Action | Timeline |
|--------|----------|
| Acknowledgment of report | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix development | Depends on severity (see below) |
| Public disclosure | After fix is released |

### Severity-Based Response

| Severity | Fix Timeline | Examples |
|----------|-------------|----------|
| Critical | 24-72 hours | Authentication bypass, remote code execution, data exfiltration |
| High | 1-2 weeks | SQL injection, privilege escalation, credential exposure |
| Medium | 2-4 weeks | XSS, CSRF, information disclosure, rate limit bypass |
| Low | Next release | Minor information leaks, non-exploitable edge cases |

## Security Measures in Place

This project implements the following security controls:

### Authentication & Authorization
- JWT-based authentication with short-lived access tokens (60 min) and refresh tokens (7 days)
- bcrypt password hashing (cost factor 12)
- WebSocket ownership verification — users cannot observe other users' pipeline progress
- All resource access is scoped to the authenticated user (no cross-tenant data leakage)

### Input Validation
- Pydantic schema validation on all request bodies
- SQL injection prevention via sqlglot parsing — only SELECT statements are allowed against DuckDB
- File upload validation (type, size, count limits)
- Rate limiting on all endpoints (SlowAPI)

### Secrets Management
- No hardcoded credentials in source code
- `SECRET_KEY` validated at startup — rejects known placeholders and enforces minimum length
- All secrets loaded from environment variables or `.env` file
- `.env` is gitignored — only `.env.example` with empty values is committed
- Sensitive data redacted from structured logs

### Infrastructure
- Multi-stage Docker build with non-root runtime user
- Read-only DuckDB connections for analytical queries
- PostgreSQL connections via asyncpg with connection pooling
- HTTPS enforced in production (via reverse proxy)
- CORS configured with explicit origin allowlist

### Dependencies
- Pinned dependency versions in `pyproject.toml`
- bcrypt pinned to <5.0 for passlib compatibility
- No open version ranges in production dependencies

## Security Best Practices for Deployers

1. **Generate a strong SECRET_KEY** — Use `python -c "import secrets; print(secrets.token_urlsafe(64))"`
2. **Use HTTPS in production** — Place behind a reverse proxy (nginx, Caddy, or cloud load balancer)
3. **Set strong database passwords** — Never use defaults in production
4. **Restrict CORS origins** — Set `CORS_ORIGINS` to your frontend domain only
5. **Enable rate limiting** — Already configured; adjust limits via `RATE_LIMIT_DEFAULT` and `RATE_LIMIT_HEAVY`
6. **Monitor logs** — Structured JSON logs include request IDs for tracing; ship to a log aggregator
7. **Keep dependencies updated** — Run `uv pip install --upgrade` regularly and check for advisories
8. **Restrict network access** — PostgreSQL and Redis should not be exposed to the public internet
9. **Back up the database** — The `pgdata` Docker volume contains all application state
10. **Rotate secrets periodically** — Especially after any suspected compromise

## Scope

The following are **in scope** for security reports:
- Authentication and authorization bypasses
- SQL injection or command injection
- Cross-site scripting (XSS) in API responses
- Sensitive data exposure (credentials, PII, internal paths)
- Denial of service via resource exhaustion
- Privilege escalation between users
- File system access beyond intended storage directories

The following are **out of scope**:
- Vulnerabilities in third-party dependencies (report to the upstream project)
- Social engineering attacks
- Physical security
- Denial of service via volumetric attacks (infrastructure-level concern)
- Issues that require physical access to the server

## Acknowledgments

We appreciate the security research community's efforts in responsibly disclosing vulnerabilities. Contributors who report valid security issues will be acknowledged in the release notes (unless they prefer to remain anonymous).
