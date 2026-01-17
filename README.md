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

- Backend : http://localhost:8000 (ou `BACKEND_PORT`)
- Frontend : http://localhost:3000

## Schéma (flux ingestion & RAG)

```mermaid
flowchart LR
    subgraph Docker["Stack Docker Compose"]
        FE[frontend<br/>Next.js]
        BE[backend<br/>FastAPI]
        PG[postgres<br/>metadata RAG]
        QD[qdrant<br/>vecteurs RAG]
        LLM[llm<br/>placeholder nginx]
    end

    subgraph Sources["Sources d'ingestion"]
        KB[kb_sources/*.md|.txt]
    end

    subgraph External["Services externes"]
        EMB[Embedding API<br/>(EMBEDDING_URL)]
    end

    %% Ingestion
    KB -->|"ingest.py: lecture + chunking"| BE
    BE -->|"embeddings"| EMB
    BE -->|"chunks + métadonnées"| PG
    BE -->|"points vecteurisés"| QD

    %% RAG runtime
    FE -->|"question utilisateur"| BE
    BE -->|"embedding requête"| EMB
    BE -->|"recherche top-k"| QD
    QD -->|"chunks pertinents"| BE
    BE -->|"prompt + contexte RAG"| LLM
    BE -->|"réponse"| FE
```

## Variables d'environnement

Les variables suivantes sont attendues (voir `.env.example`) :

- `DATABASE_URL`
- `QDRANT_URL`
- `LLM_URL`
- `BACKEND_PORT` (optionnel, change le port hôte du backend)
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` / `SMTP_TO`
- `EXPORT_MODE` (`NONE|SHEET|CRM_WEBHOOK`)

## Notes

- Le service `llm-server` est un placeholder (nginx) pour permettre à `docker compose up` de démarrer sans erreur.
