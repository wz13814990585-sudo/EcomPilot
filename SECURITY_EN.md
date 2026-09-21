# Security Policy

[简体中文](SECURITY.md) | [English](SECURITY_EN.md)

## Reporting a security issue

Do not disclose exploitable vulnerabilities, secrets, customer data, or complete attack steps in a public Issue.

Prefer the repository's **Security → Report a vulnerability** private-reporting entry. If it is temporarily unavailable, contact the repository maintainer and provide only the minimum information required to locate the issue.

A useful report includes:

- the affected commit, version, or endpoint;
- reproduction steps and expected impact;
- whether it involves authentication bypass, unauthorized access, cross-tenant leakage, unsafe SQL, approval replay, or duplicate side effects;
- any known temporary mitigation;
- a minimal reproduction without real credentials or customer data.

## Security boundaries

This project specifically protects:

- API Key/JWT authentication and role authorization;
- tenant/store data isolation and PostgreSQL RLS;
- Text-to-SQL read-only, table, column, function, and complexity restrictions;
- human approval, parameter binding, expiry, and one-time consumption for high-risk writes;
- Skill idempotency, duplicate-execution prevention, and audit records;
- RAG citations, evidence provenance, and Grounding status;
- browser credentials stored only in the current tab's `sessionStorage`.

## Sensitive information

The repository's `.env.example` demonstrates configuration fields only. Never commit real API keys, database passwords, tokens, private certificates, customer orders, chat records, or production logs. If sensitive information has entered Git history, rotate the credential immediately and describe the affected scope in a private security report.

## Supported scope

Security fixes target the `main` branch. Demo Providers, sample data, and local development settings are not production deployment guidance. Production environments still require managed secrets, formal database roles, network isolation, backups, and monitoring policies.
