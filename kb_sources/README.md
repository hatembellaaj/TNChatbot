# Sources de connaissance (kb_sources)

Ce dossier sert de **zone d’import** pour la base de connaissance (RAG).

## Format attendu

- Fichiers `.md` ou `.txt` uniquement.
- Un fichier = un document.
- Utiliser un encodage UTF-8.

## Procédure d’ingestion

1. Déposer les documents dans `kb_sources/`.
2. Configurer les variables d’environnement :
   - `DATABASE_URL`
   - `QDRANT_URL`
   - `QDRANT_COLLECTION`
   - `EMBEDDING_URL`
   - `EMBEDDING_MODEL`
   - `AUDIENCE_ADMIN_CONFIG` (JSON avec les chiffres audience admin)
3. Lancer l’ingestion :

```bash
python -m app.rag.ingest
```

Les tables `kb_ingestion_runs`, `kb_documents`, `kb_chunks` tracent chaque import.
