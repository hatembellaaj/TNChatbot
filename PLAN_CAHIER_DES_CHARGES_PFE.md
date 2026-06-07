# Plan de cahier des charges (PFE) — TNChatbot (max 10 pages)

> Objectif: proposer une structure claire, académique et réaliste pour un document de fin d'année, limité à 10 pages hors annexes.

## Répartition recommandée (10 pages)

1. **Introduction & contexte** *(0,5 page)*  
2. **Problématique & objectifs** *(1 page)*  
3. **Périmètre fonctionnel** *(1 page)*  
4. **Parties prenantes & besoins utilisateurs** *(1 page)*  
5. **Spécifications fonctionnelles (cas d'usage)** *(2 pages)*  
6. **Spécifications techniques & architecture** *(2 pages)*  
7. **Contraintes, sécurité, RGPD, qualité** *(1 page)*  
8. **Planning, livrables, critères de validation** *(1 page)*  
9. **Conclusion** *(0,5 page)*

---

## Plan détaillé à copier dans ton document

## 1) Introduction et contexte (≈ 1/2 page)
- Présentation de Tunisie Numérique et du besoin métier.
- Pourquoi un chatbot orienté annonceurs ?
- Cadre du PFE et objectif global.

## 2) Problématique et objectifs (≈ 1 page)
### 2.1 Problématique
- Difficulté à orienter rapidement les prospects vers les bonnes offres publicitaires.
- Besoin d'automatiser les réponses fréquentes et la qualification commerciale.

### 2.2 Objectifs généraux
- Informer sur les offres publicitaires.
- Recommander des solutions selon objectifs/budget.
- Collecter des leads exploitables.

### 2.3 Objectifs mesurables (KPI)
- Taux de conversations aboutissant à un lead.
- Temps moyen de réponse.
- Taux de réponses validées/fallback.

## 3) Périmètre fonctionnel (≈ 1 page)
### 3.1 Inclus
- Parcours conversationnel annonceurs.
- Présentation audience + solutions.
- Aide au choix par budget.
- Questions factuelles via RAG.
- Formulaires de contact (standard + spécialisés).

### 3.2 Exclus
- Support éditorial pour lecteurs/commentaires.
- Gestion CRM complète (si non implémentée dans le projet).

## 4) Parties prenantes et besoins utilisateurs (≈ 1 page)
### 4.1 Acteurs
- Annonceur / agence (utilisateur principal).
- Équipe commerciale TN.
- Administrateur technique.

### 4.2 Besoins clés
- **Annonceur**: comprendre vite les formats adaptés.
- **Commercial**: recevoir des leads qualifiés.
- **Admin**: maintenir la base de connaissances.

## 5) Spécifications fonctionnelles (≈ 2 pages)
### 5.1 Cas d'usage principaux
- UC1: Découvrir l'audience.
- UC2: Explorer les solutions pub.
- UC3: Obtenir une recommandation budget.
- UC4: Poser une question factuelle.
- UC5: Déposer une demande de rappel.

### 5.2 Parcours conversationnel (wizard)
- Étapes: accueil → menu → sous-parcours → CTA.
- Gestion des transitions et boutons.
- Gestion hors périmètre lecteur.

### 5.3 Règles métier
- Conditions de déclenchement RAG.
- Validation/fallback des réponses LLM.
- Champs obligatoires formulaires leads.

## 6) Spécifications techniques et architecture (≈ 2 pages)
### 6.1 Architecture logique
- Frontend Next.js.
- Backend FastAPI.
- PostgreSQL (métadonnées/sessions/leads).
- Qdrant (recherche vectorielle).
- Ollama/LLM + embeddings.

### 6.2 Flux de données
- Ingestion KB → chunking → embeddings → indexation.
- Question utilisateur → retrieval → prompt enrichi → réponse.

### 6.3 Interfaces et API
- Endpoints clés (session chat, stream chat, admin, leads).
- Format des échanges JSON (vue synthétique).

### 6.4 Environnement de déploiement
- Docker Compose local.
- Variables d'environnement essentielles.

## 7) Contraintes, sécurité, conformité, qualité (≈ 1 page)
### 7.1 Contraintes
- Performance (latence acceptable).
- Disponibilité des services externes (LLM/embeddings).

### 7.2 Sécurité & RGPD
- Données personnelles des leads.
- Mention d'information utilisateur et usage des données.

### 7.3 Qualité et tests
- Tests backend (unitaires/fonctionnels).
- Tests frontend (e2e).
- Critères d'acceptation.

## 8) Planning, livrables et validation (≈ 1 page)
### 8.1 Planning (ex: Gantt simplifié)
- Phase 1: cadrage & analyse.
- Phase 2: conception.
- Phase 3: implémentation.
- Phase 4: tests & recette.
- Phase 5: rédaction mémoire/soutenance.

### 8.2 Livrables
- Code source versionné.
- Documentation technique.
- Cahier de tests.
- Manuel utilisateur court.

### 8.3 Critères de validation finale
- Couverture des cas d'usage définis.
- Démonstration bout-en-bout fonctionnelle.
- Qualité de la documentation et reproductibilité.

## 9) Conclusion (≈ 1/2 page)
- Bilan du besoin couvert.
- Limites connues.
- Perspectives d'amélioration (observabilité, admin avancé, scoring qualité réponses).

---

## Conseils de forme pour tenir en 10 pages
- Utilise des tableaux synthétiques (acteurs, besoins, KPI, exigences).
- 1 schéma d'architecture maximum + 1 schéma de flux conversationnel.
- Détaille uniquement l'essentiel dans le corps; place les détails en annexe.
- Annexes possibles (hors quota): dictionnaire de données, prompts, captures d'écran, scénarios de tests.
