# TNChatbot

Structure du repo :

- `frontend/` : Next.js
- `backend/` : FastAPI
- `migrations/` : SQL
- `infra/docker-compose.yml` : stack locale

## Démarrage rapide

1. Copiez `.env.example` vers `.env` et adaptez si besoin.
2. Lancez Docker Compose depuis `infra/` :

```bash
cd infra
 docker compose up --build
```

## Services exposés

- Backend : http://localhost:8000
- Frontend : http://localhost:3000

## Variables d'environnement

Les variables suivantes sont attendues (voir `.env.example`) :

- `DATABASE_URL`
- `QDRANT_URL`
- `LLM_URL`
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` / `SMTP_TO`
- `EXPORT_MODE` (`NONE|SHEET|CRM_WEBHOOK`)

## Notes

- Le service `llm-server` est un placeholder (nginx) pour permettre à `docker compose up` de démarrer sans erreur.
