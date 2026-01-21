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
- `LLM_MODEL` (optionnel, modèle utilisé par le backend, ex : `llama3.2:3b-instruct-q4_0`)
- `EMBEDDING_URL` (optionnel, URL du service d'embeddings utilisé pour l'ingestion et le RAG)
- `EMBEDDING_MODEL` (optionnel, modèle d'embeddings, ex : `nomic-embed-text`)
- `PROMPT_MAX_TOKENS` (optionnel, budget total de tokens pour system/developer/user; le backend tronque le prompt pour rester sous ce seuil)
- `OLLAMA_PORT` (optionnel, change le port hôte d'Ollama)
- `OLLAMA_DEBUG` (optionnel, active les logs détaillés d'Ollama)
- `BACKEND_PORT` (optionnel, change le port hôte du backend)
- `FRONTEND_PORT` (optionnel, change le port hôte du frontend)
- `NEXT_PUBLIC_BACKEND_URL` (optionnel, URL publique du backend pour le navigateur, sinon le frontend utilise l'hôte courant + `BACKEND_PORT`)
- `NEXT_PUBLIC_BACKEND_PORT` (optionnel, port exposé du backend côté navigateur, par défaut `19081`)
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` / `SMTP_TO`
- `EXPORT_MODE` (`NONE|SHEET|CRM_WEBHOOK`)

### Générer un `.env`

Vous pouvez initialiser un `.env` pour la racine et `infra/` via :

```bash
./scripts/bootstrap-env.sh
```

Ce script copie `.env.example` et remplit des valeurs locales par défaut (`localhost` + ports).
Pour un déploiement distant, mettez à jour `NEXT_PUBLIC_BACKEND_URL` avec l'URL publique du backend.

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
- Le frontend essaie automatiquement l'origin courant puis l'hôte courant avec `BACKEND_PORT` (ou
  `NEXT_PUBLIC_BACKEND_PORT` si défini). Si le frontend est servi depuis un autre domaine, définissez
  `NEXT_PUBLIC_BACKEND_URL` avec l'URL publique du backend.
- Vous pouvez changer de modèle via `LLM_MODEL` (ex : `llama3.2:3b-instruct-q4_0`), le service `ollama-init`
  téléchargera automatiquement ce modèle.
- Pour les embeddings via Ollama, définissez `EMBEDDING_MODEL` (ex : `nomic-embed-text`) ; `ollama-init`
  téléchargera également ce modèle.
- Si vous voyez `LLM request failed`, vérifiez que l'API répond (`curl http://localhost:11434/api/tags`)
  et que le modèle est bien présent (`docker compose exec ollama ollama list`).
