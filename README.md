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
- Frontend : http://localhost:3000 (ou `FRONTEND_PORT`)

## Schéma (flux ingestion & RAG)

```mermaid
flowchart LR
    subgraph Docker["Stack Docker Compose"]
        FE[frontend<br/>Next.js]
        BE[backend<br/>FastAPI]
        PG[postgres<br/>metadata RAG]
        QD[qdrant<br/>vecteurs RAG]
    LLM[ollama<br/>LLM server]
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
- `LLM_MODEL` (optionnel, modèle utilisé par le backend, ex : `llama3.2:3b`)
- `OLLAMA_PORT` (optionnel, change le port hôte d'Ollama)
- `BACKEND_PORT` (optionnel, change le port hôte du backend)
- `FRONTEND_PORT` (optionnel, change le port hôte du frontend)
- `NEXT_PUBLIC_BACKEND_URL` (optionnel, URL publique du backend pour le navigateur, sinon le frontend utilise l'hôte courant + `BACKEND_PORT`)
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` / `SMTP_TO`
- `EXPORT_MODE` (`NONE|SHEET|CRM_WEBHOOK`)

## Utiliser Ollama pour les tests LLM

1. Lancez la stack depuis `infra/` :

```bash
cd infra
docker compose up --build
```

2. Téléchargez un modèle dans le conteneur Ollama (exemple avec Llama 3.2 3B) :

```bash
docker compose up -d ollama-init
```

3. Redémarrez le backend si besoin, puis testez :

```bash
curl -N -X POST http://localhost:19081/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<uuid>","user_message":"Bonjour","state":{"step":"WELCOME"},"context":{}}'
```

### Notes

- Par défaut, le backend pointe vers `http://ollama:11434/v1/chat/completions`.
- Dans Docker Compose, `ollama` est le nom du service (accessible depuis les autres conteneurs) ;
  depuis votre machine hôte, utilisez `http://localhost:11434`.
- Vous pouvez changer de modèle via `LLM_MODEL` (ex : `llama3.2:3b`), le service `ollama-init`
  téléchargera automatiquement ce modèle.
- Si vous voyez `LLM request failed`, vérifiez que l'API répond (`curl http://localhost:11434/api/tags`)
  et que le modèle est bien présent (`docker compose exec ollama ollama list`).
