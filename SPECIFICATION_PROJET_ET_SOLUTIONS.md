# Spécification complète du projet TNChatbot et solutions réalisées

## 1) Vision produit
TNChatbot est un assistant conversationnel orienté **annonceurs / agences / entreprises / institutions** pour présenter les offres publicitaires de Tunisie Numérique, aider au choix d'offres selon le budget, répondre aux questions factuelles via RAG, et collecter des leads qualifiés.

## 2) Périmètre fonctionnel

### Objectifs couverts
- Présenter l'audience et les solutions publicitaires.
- Guider l'utilisateur dans le choix d'une offre via un parcours budgétaire.
- Répondre aux questions factuelles en s'appuyant sur une base de connaissances (RAG).
- Collecter des informations de contact (callback / formulaires spécialisés).
- Exclure proprement les demandes hors périmètre (lecteurs, commentaires éditoriaux) vers un contact général.

### Hors périmètre explicite
- Traitement des demandes lecteurs liées aux articles/commentaires (redirigées vers formulaire de contact général).

## 3) Architecture technique

### Stack
- **Frontend**: Next.js (App Router).
- **Backend**: FastAPI.
- **Base relationnelle**: PostgreSQL (métadonnées, sessions, messages, leads).
- **Base vectorielle**: Qdrant (index des embeddings RAG).
- **LLM runtime**: Ollama / endpoint compatible OpenAI Chat Completions.

### Organisation du dépôt
- `frontend/` : interface utilisateur web.
- `backend/` : API, orchestration conversationnelle, RAG, LLM, leads.
- `kb_sources/` : corpus métier (offres, budget, audience, etc.) pour ingestion RAG.
- `migrations/` : scripts SQL d'initialisation.
- `infra/docker-compose.yml` : exécution locale orchestrée.

## 4) Spécification détaillée des composants

### 4.1 Frontend (Next.js)
- Initialisation multi-base API (origin courant, URL publique explicite, fallback port backend).
- Création de session de chat côté backend.
- Affichage conversation utilisateur/assistant avec boutons d'actions.
- Gestion d'un écran d'introduction (progression + image publicitaire publique optionnelle).
- Support d'affichage des éléments de sécurité/RAG (chunks sélectionnés, contexte) pour inspection.
- Détection de certains états pour afficher des formulaires (selon étape conversationnelle).

### 4.2 Backend (FastAPI)
- Endpoints chat (session + conversation, y compris flux streaming).
- Validation/normalisation des réponses LLM avec fallback.
- Orchestrateur à états (wizard conversationnel) avec boutons et transitions.
- Déclenchement conditionnel RAG selon intention/question factuelle.
- Extraction complémentaire de faits structurés depuis le contexte RAG (ex: année de lancement, métriques 2024, tarification).
- Routage admin et collecte leads.

### 4.3 Orchestrateur conversationnel
Le moteur d'état couvre notamment:
- Accueil/périmètre.
- Menu principal.
- Audience.
- Menu solutions + fiches solution (display, contenu, vidéo, audio/newsletter, innovation, magazine).
- Assistant de recommandation budget (type client, objectif, tranche budgétaire, recommandation).
- Parcours formulaires standards et formulaires spécialisés (ImmoNeuf, Premium, Partenariat).
- Gestion du hors périmètre lecteur.

### 4.4 RAG
- Ingestion des fichiers `kb_sources/*.txt|*.md` avec chunking.
- Vectorisation via service d'embeddings configurable.
- Stockage des chunks/métadonnées en Postgres + vecteurs en Qdrant.
- Recherche top-k sur requête utilisateur + enrichissement du prompt LLM.
- Classification d'intention pour limiter le RAG aux cas pertinents.

## 5) Données & contenus métier
La base de connaissances actuelle contient au moins:
- Vue d'ensemble audience.
- Vue d'ensemble solutions.
- Détails formats/offres (display, contenu, vidéo, newsletter/audio, innovation, magazine, immobilier neuf, premium).
- Grilles budget (moins de 1000, 1000-3000, 3000+, etc.).
- Règles de hors périmètre.

## 6) Interfaces et intégrations

### Variables d'environnement clés
- `DATABASE_URL`, `QDRANT_URL`, `LLM_URL`
- `LLM_MODEL`, `EMBEDDING_URL`, `EMBEDDING_MODEL`
- `PROMPT_MAX_TOKENS`
- `BACKEND_PORT`, `FRONTEND_PORT`, `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_BACKEND_PORT`
- SMTP (`SMTP_HOST`, `SMTP_PORT`, etc.)
- `EXPORT_MODE` (`NONE|SHEET|CRM_WEBHOOK`)

### Déploiement local
- Démarrage principal via Docker Compose (`infra/`).
- Script de bootstrap d'environnement disponible pour générer les `.env` locaux.

## 7) Solutions réalisées jusqu'à maintenant (état actuel observable)

### Solution 1 — Assistant conversationnel orienté annonceurs
✅ Réalisé
- Parcours guidé par boutons dans un menu métier centré sur les objectifs annonceurs.
- Cloisonnement lecteur vs annonceur avec message d'exclusion et redirection contact.

### Solution 2 — Catalogue d'offres publicitaires intégré
✅ Réalisé
- Présentation structurée des familles d'offres: display, contenus sponsorisés, vidéo, audio/newsletter, innovation, magazine.
- Pitchs dédiés par solution dans l'orchestrateur.

### Solution 3 — Recommandation par budget
✅ Réalisé
- Arbre de décision budget (type client, objectif, tranche).
- Recommandations packagées selon segments budgétaires.

### Solution 4 — RAG métier sur base documentaire
✅ Réalisé
- Corpus `kb_sources` exploitable par ingestion.
- Recherche de contexte pertinente avant génération LLM quand la question s'y prête.
- Mécanismes de sécurité/fallback si la réponse LLM est incomplète ou hors cadre.

### Solution 5 — Capture de leads et parcours formulaires
✅ Réalisé
- Formulaire standard callback (coordonnées + contexte).
- Formulaires spécialisés (ImmoNeuf, Premium, Partenariat).
- Mention RGPD présente dans le flux conversationnel.

### Solution 6 — Exploitabilité opérationnelle
✅ Réalisé
- Stack locale dockerisée (frontend/backend/postgres/qdrant/ollama).
- Endpoints de health/check et scripts d'aide (debug/audit/migrations).
- Couverture de tests backend et tests frontend Playwright présents dans le repo.

## 8) Limites et prochaines améliorations recommandées
- Formaliser une doc API exhaustive endpoint par endpoint (contrats JSON + codes erreur).
- Ajouter des métriques d'observabilité (latence RAG, taux fallback, conversion formulaire).
- Renforcer l'admin (gestion corpus, scoring qualité réponses, replay conversation).
- Étendre l'évaluation automatique (benchmarks de factualité et robustesse multilingue).

## 9) Résumé exécutif
Le projet TNChatbot dispose déjà d'une base **fonctionnelle, structurée et industrialisable**: expérience conversationnelle guidée, moteur RAG métier, workflows de qualification commerciale, et environnement local reproductible. Les solutions principales attendues pour un chatbot marketing B2B sont en place; la suite logique consiste à consolider l'observabilité, la gouvernance de contenu et les métriques business.
