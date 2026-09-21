# Contributing Guide

[简体中文](CONTRIBUTING.md) | [English](CONTRIBUTING_EN.md)

Thank you for your interest in EcomPilot. Issues, documentation improvements, test cases, and feature implementations are welcome.

## Before you start

- Use the repository Issue templates for ordinary bugs and feature requests.
- Do not open a public Issue for a security vulnerability. Follow the [Security Policy](SECURITY_EN.md) and report it privately.
- For broad architectural changes, open an Issue first and describe the objective, boundaries, and compatibility impact.

## Local development

Python 3.11+ is required. Full business integration also requires PostgreSQL 16, pgvector, and Redis 7.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Bootstrap demo data and start the service:

```bash
python -m ecom_agent_matrix.scripts.bootstrap_demo
python -m uvicorn ecom_agent_matrix.api.main:app --reload --port 8002
```

## Checks before submission

```bash
python -m compileall -q ecom_agent_matrix eval
ruff check ecom_agent_matrix test eval
ruff format --check ecom_agent_matrix test eval
pytest -q
python -m eval.runner --suite deterministic --fail-on-regression
python -m eval.enterprise.runner --suite all --fail-on-regression
python -m eval.enterprise.advanced_runner --suite all --fail-on-regression
```

Changes involving routing, SQL, approval, tenant isolation, RAG citations, or conversation memory must include regression tests. Never make a test pass by weakening a security check.

## Commits and pull requests

- Keep each commit focused on one clear problem and use a short imperative commit message.
- A pull request should explain the problem, solution, validation, risks, and UI impact.
- Never commit `.env`, API keys, database passwords, customer data, model secrets, or private logs.
- Update the README or `docs/` whenever API or demo behavior changes.
- For front-end changes, describe the before/after behavior and include screenshots when useful.

## Design principles

- Authentication, authorization, approval, idempotency, and tenant isolation are enforced by code, never by prompts.
- High-confidence single tasks should use deterministic Fast Path; genuinely composite tasks enter the Typed DAG.
- User-facing errors should explain the reason and next action while keeping technical detail in an expandable area.
- Evaluation reports must come from real runs. Unavailable capabilities are `NOT_RUN`; results must never be invented.

