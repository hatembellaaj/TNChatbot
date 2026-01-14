# Spécification — Chatbot Annonceurs TN

## 1) Objectif & périmètre

### 1.1 Objectifs

Mettre en place un chatbot “Annonceurs” sur le site Tunisie Numérique afin de :

- Mieux accueillir annonceurs/agences/institutions.
- Qualifier rapidement (type client, objectif, budget).
- Réduire les échanges non sérieux.
- Générer des leads qualifiés transmis automatiquement au commercial.
- Garantir un discours cohérent avec le kit média TN 2025.

### 1.2 Périmètre (in-scope)

Chatbot dédié B2B/corporate intégré sur la page **Annonceurs/Publicité** (extensible à d’autres pages B2B plus tard).

Offres couvertes :

- Display.
- Contenu sponsorisé.
- Vidéo.
- Audio/newsletter.
- Pack Innovation.
- Immoneuf.
- TN Le Mag.
- Premium entreprise.
- Partenariat annuel.

### 1.3 Hors périmètre (out-of-scope)

Demandes “lecteurs” (avis articles, suggestions rédactionnelles, etc.) : le bot doit **rediriger vers le formulaire contact général**.

## 2) Cibles & ton

### 2.1 Cibles

- Agences.
- Entreprises/marques.
- Banques/assurances.
- Institutions/ONG/organisations.
- Promoteurs immobiliers.

### 2.2 Ton & langue

- Langue : **français uniquement**.
- Ton : **pro, clair, courtois, sans blabla**.
- **Phrase de cadrage obligatoire** dès le début : assistant annonceurs uniquement + redirection lecteurs.

## 3) UX conversationnelle (menus + parcours)

### 3.1 Message d’accueil (obligatoire)

Doit reprendre l’esprit :

> « Bonjour 👋 … assistant média TN dédié aux annonceurs/agences/entreprises… » + phrase de cadrage lecteurs.

### 3.2 Menu principal (boutons)

Boutons **exacts** :

- 📊 Découvrir notre audience
- 🧩 Voir nos solutions pub (bannières, contenu, vidéo, audio…)
- 💰 M’aider à choisir une offre selon mon budget
- 🏢 Immobilier neuf / Pack Immoneuf
- 📰 Abonnement Premium entreprise
- 🤝 Parler d’un partenariat annuel
- 📞 Être rappelé par un conseiller

### 3.3 Parcours “Découvrir notre audience”

- Afficher : **visites annuelles**, **utilisateurs**, **articles lus**, **TRE/audience internationale** (valeurs configurables via admin).
- CTA ensuite : **Solutions** / **Budget** / **Être rappelé**.

### 3.4 Parcours “Solutions pub”

Sous-menu :

- 🎯 Bannières display (ciblage géographique + centres d’intérêt)
- 📰 Communiqué / article publicitaire
- 🎥 Vidéo & pré-roll
- 🔊 Audio & newsletter
- 🚀 Pack Innovation – First mover TN
- 📰 TN Le Mag
- 🔙 Retour menu

Détails attendus :

- **Display** : formats + ciblage (pays/région/ville/diaspora TRE + centres d’intérêt).
- **Contenu** : diffusion communiqué, rédaction article pub, options RS + formulaires leads.
- **Vidéo** : pré-roll, reportages brandés, live possible “au cas par cas”.
- **Audio/newsletter** : pubs audio TTS + pubs newsletter TN (Tunisie & France).
- **Pack Innovation** : premium innovant, toujours sur-mesure → formulaire.
- **TN Le Mag** : magazine mensuel + papier décideurs, prises de parole corporate → formulaire.

Chaque sous-parcours propose au minimum :

- “Avoir une idée selon mon budget” → parcours Budget.
- “Être rappelé” → formulaire.

### 3.5 Parcours “Budget”

Objectif : qualifier rapidement via **type structure → objectif → budget**, puis collecter lead.

**Étape 1 (boutons) – Type de client :**

- Agence média / communication
- Entreprise / marque
- Banque / assurance / institution financière
- Institution / ONG / organisation
- Promoteur immobilier
- Autre

**Étape 2 (boutons) – Objectif principal :**

- Notoriété / image de marque
- Lancement d’un produit / service
- Générer des leads / contacts clients
- Campagne immobilière
- Abonnement Premium entreprise
- Partenariat annuel / convention

**Étape 3 (boutons) – Budget :**

- 💸 Moins de 1 000 TND
- 💼 Entre 1 000 et 3 000 TND
- 📈 Entre 3 000 et 10 000 TND
- 🧱 Plus de 10 000 TND
- ❓ Je ne sais pas encore

**Logique recommandation (obligatoire) :**

- **< 1 000 TND** : article/communiqué + petit display, durée courte.
- **1 000–3 000 TND** : mini-pack bannières + article + relais RS.
- **3 000–10 000 TND** : pack complet (display multi-format + contenu + éventuellement audio/newsletter).
- **> 10 000 TND** : plan média/partenariat, options Pack Innovation, vidéo, etc.
- **Je ne sais pas** : accompagnement sur-mesure.

Ensuite : « Pour une reco sur mesure, j’ai besoin de vos coordonnées pro » → formulaire.

### 3.6 Parcours “Immobilier neuf / Immoneuf”

- Présenter Immoneuf comme pack lead gen immo (mise en avant projets, annuaire, formulaires, audience Tunisie & TRE).
- Formulaire Immoneuf = formulaire standard + champs : **ville des projets**, **type de biens**, **nombre de projets**, **période de commercialisation**.

### 3.7 Parcours “Premium entreprise”

- Abonnements Premium multi-comptes.
- Champs : **Nom & Prénom**, **Société**, **Fonction**, **Email pro**, **Téléphone**, **Nombre estimé d’utilisateurs**, **Message**.

### 3.8 Parcours “Partenariat annuel”

- Destiné grands comptes (banques, télécoms, institutions…).
- Expliquer : **conventions annuelles**, **packs multi-campagnes**, **visibilité élargie**.
- Formulaire = standard + champ : **type de partenariat souhaité / priorité** (display, contenu, etc.).

### 3.9 Parcours “Être rappelé”

Accessible à tout moment. Déclenche formulaire standard.

### 3.10 Gestion “hors cible lecteur”

Si intention lecteur : répondre avec la phrase de cadrage et renvoyer vers la page Contact.

## 4) Collecte lead & règles anti-“touristes”

### 4.1 Formulaire standard (lead qualifié)

Champs :

- Nom & prénom (**obligatoire**).
- Société (**obligatoire**).
- Fonction (optionnel mais conseillé).
- Email professionnel (**obligatoire**).
- Téléphone (**obligatoire**).
- Secteur (dropdown : Banque, Télécom, Immobilier, Retail, Industrie, Services, Institution, Autre).
- Type de besoin (pré-rempli selon parcours).
- Budget (pré-rempli selon tranche).
- Message libre (facultatif).

### 4.2 Anti-touristes (obligatoire)

- Société obligatoire (filtre).
- Mention claire : « **Demande réservée aux projets publicitaires et partenariats.** »

### 4.3 RGPD (obligatoire)

Mention en bas du formulaire : usage uniquement pour recontacter dans le cadre de la demande.

## 5) Choix LLM & stratégie (Llama + orchestrateur)

### 5.1 Modèle

- Utiliser **Llama 3.2 3B Instruct** pour génération.

### 5.2 Principe de contrôle

- Le bot est une **machine à états** pilotée par l’orchestrateur.
- Le LLM ne décide pas “librement” du parcours.
- Le LLM sert à : reformuler, répondre dans le scope, produire un texte pro, extraire/normaliser quelques champs.

### 5.3 Anti-hallucination

- Sur questions factuelles/offres : répondre uniquement à partir du contexte RAG (kit média/FAQ).
- Si info absente/incertaine : proposer rappel (formulaire).

## 6) RAG (base de connaissance)

### 6.1 Sources

- Kit média TN 2025 (offres, positionnement, wording).
- Pages/offres Immoneuf, Premium, TN Le Mag, Pack Innovation, FAQ annonceurs.

### 6.2 Pipeline

- Ingestion → nettoyage → chunking → embeddings → index dans Vector DB.
- Retrieval topK + (rerank optionnel) → contexte injecté au prompt.

### 6.3 Règle

- Retrieval déclenché au moins sur : audience, formats display, détails offres, TN Le Mag, Pack Innovation, Immoneuf, Premium, partenariat.

## 7) Streaming SSE (UX type ChatGPT)

### 7.1 Exigence

- Afficher la réponse progressivement (chunks/tokens) sans attendre la fin.
- Boutons/CTA affichés uniquement à la fin (final).

### 7.2 Endpoint obligatoire

`POST /api/chat/stream` → `Content-Type: text/event-stream`

Événements : `meta` (optionnel), `token` (répété), `final` (obligatoire), `error`, `ping`.

Exemple SSE :

```text
event: token
data: {"text":"Très bien, voici nos solutions pub : "}

event: final
data: {"assistant_message":"...","state":{"step":"SOLUTIONS_MENU"},"buttons":[...]}
```

### 7.3 Guardrails avant streaming

Avant d’émettre le 1er token, appliquer :

- Détection hors-cible lecteur.
- Choix route (RAG vs direct).
- Préparation prompt et contexte.

## 8) Intégrations & automatisations (obligatoires)

### 8.1 Email automatique

Chaque lead valide envoie un email à une adresse dédiée (configurable, ex `annonceurs@...`).

- Sujet : `[CHATBOT ANNONCEURS] Nouvelle demande – {Société}`
- Corps : récapitulatif champs + parcours d’entrée + date/heure.

### 8.2 Journalisation / export

Sauvegarder chaque lead dans :

- Google Sheet (ou équivalent) **ou** CRM si existant.

Champs à stocker : date/heure, nom/société/fonction, email/tel, secteur, type besoin, parcours d’entrée, budget, message, source “Chatbot Annonceurs TN”.

## 9) API (contrats)

### 9.1 Sessions

- `POST /api/chat/session` → crée session, renvoie `session_id`.
- `POST /api/chat/message` → réponse complète (fallback non-stream).

### 9.2 Chat streaming

- `POST /api/chat/stream` (SSE).

### 9.3 Leads

- `POST /api/leads` → valide + stocke + email + export.

Exemple payload :

```json
{
  "session_id": "uuid",
  "lead": {
    "full_name": "...",
    "company": "...",
    "role": "...",
    "email": "...",
    "phone": "...",
    "sector": "Telecom",
    "need_type": "DISPLAY",
    "budget_range": "1000-3000",
    "message": "..."
  },
  "meta": {
    "entry_path": "MAIN_MENU>Budget",
    "source": "Chatbot Annonceurs TN"
  }
}
```

### 9.4 Admin (MVP)

- `GET/PUT /api/admin/audience-metrics`
- `GET/PUT /api/admin/offers-copy`
- `GET/PUT /api/admin/email-config`
- `GET/PUT /api/admin/sectors`
- `GET /api/admin/leads?from=...&to=...` + export CSV

## 10) Données (modèle DB minimal)

Tables suggérées :

- `chat_sessions(id, created_at, last_seen_at, state_json, channel, page)`
- `chat_messages(id, session_id, role, content, created_at, meta_json)` (optionnel)
- `leads(id, created_at, session_id, full_name, company, role, email, phone, sector, need_type, budget_range, message, entry_path, source)`
- `admin_config(key, value_json, updated_at)` (audience chiffres, textes, destinataires email…)

## 11) Sécurité, qualité, observabilité

### 11.1 Sécurité

- Rate limit / anti-spam (captcha léger ou honeypot sur formulaire).
- Validation stricte des champs (email/tel).
- CORS strict sur domaine TN.
- Logs sans PII en clair si possible (hash email/tel).

### 11.2 Observabilité

- `trace_id` par requête.
- Durées (RAG, génération).
- Tokens/chunks.
- Erreurs SSE (disconnect/timeout).

## 12) Déploiement & livrables

### 12.1 Livrables

- Widget chat web (embeddable) + UI boutons.
- Backend (orchestrateur state machine + RAG + leads).
- SSE streaming + fallback non-stream.
- DB + migrations.
- Email sender.
- Export Google Sheet ou webhook CRM.
- Admin panel MVP.

### 12.2 Déploiement

Docker Compose : frontend, api, postgres, vectordb, llm-server.

Variables d’env : `LLM_URL`, `SMTP_*`, `EXPORT_MODE`, `SHEET_*`, `ADMIN_AUTH_*`.

## 13) Tests & critères d’acceptation

### 13.1 Tests E2E obligatoires

- Accueil + menu.
- Audience (chiffres affichés, CTA).
- Solutions (chaque sous-parcours → CTA formulaire).
- Budget (3 étapes + reco + formulaire).
- Immoneuf (form spécifique).
- Premium entreprise (champ nb utilisateurs).
- Partenariat (champ priorité).
- Hors-scope lecteur (redirection contact).
- SSE : texte se stream + boutons uniquement à final.

### 13.2 Critères d’acceptation

- Parcours conformes au cahier des charges (menus/étapes/champs).
- Envoi email + stockage lead + export.
- Redirection lecteurs conforme.
- Streaming SSE fonctionnel.
