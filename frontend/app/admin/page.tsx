"use client";

import { useEffect, useMemo, useState } from "react";

import styles from "./page.module.css";

const DEFAULT_BACKEND_PORT = "19081";

const formatHostname = (hostname: string) =>
  hostname.includes(":") ? `[${hostname}]` : hostname;

const resolveApiBases = () => {
  const bases: string[] = [];
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    bases.push(process.env.NEXT_PUBLIC_BACKEND_URL);
  }
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    bases.push(process.env.NEXT_PUBLIC_API_BASE_URL);
  }
  if (typeof window !== "undefined") {
    const { origin, protocol, hostname, port } = window.location;
    bases.push(origin);

    const backendPort =
      process.env.NEXT_PUBLIC_BACKEND_PORT ?? DEFAULT_BACKEND_PORT;
    if (backendPort && backendPort !== port) {
      bases.push(`${protocol}//${formatHostname(hostname)}:${backendPort}`);
    }
  }
  return Array.from(new Set(bases));
};

type OverviewPayload = {
  sessions: number;
  messages: number;
  leads: number;
};

type ConversationMessage = {
  role: string;
  content: string;
  step: string | null;
  created_at: string | null;
};

type Conversation = {
  session_id: string;
  step: string;
  created_at: string | null;
  messages: ConversationMessage[];
};

type Lead = {
  id: string;
  full_name: string | null;
  company: string | null;
  email: string | null;
  phone: string | null;
  entry_path: string | null;
  lead_type: string | null;
  extra_json: Record<string, unknown>;
  created_at: string | null;
};

export default function AdminPage() {
  const apiCandidates = useMemo(() => resolveApiBases(), []);
  const [apiBase, setApiBase] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const discover = async () => {
      for (const candidate of apiCandidates) {
        try {
          const response = await fetch(`${candidate}/health`);
          if (response.ok) {
            setApiBase(candidate);
            return;
          }
        } catch (candidateError) {
          console.warn(
            `[TNChatbot] Admin health check failed for ${candidate}.`,
            candidateError,
          );
        }
      }
      setError(
        "Impossible de détecter le backend. Vérifiez l'URL et la configuration.",
      );
    };

    void discover();
  }, [apiCandidates]);

  const fetchAdminData = async () => {
    if (!apiBase || !password) {
      throw new Error(
        "Impossible de charger les données sans mot de passe admin.",
      );
    }
    const headers = { "X-Admin-Password": password };
    const [overviewRes, conversationsRes, leadsRes] = await Promise.all([
      fetch(`${apiBase}/api/admin/overview`, { headers }),
      fetch(`${apiBase}/api/admin/conversations`, { headers }),
      fetch(`${apiBase}/api/admin/leads`, { headers }),
    ]);

    if (!overviewRes.ok || !conversationsRes.ok || !leadsRes.ok) {
      throw new Error("Impossible de charger les données administratives.");
    }

    const overviewPayload = (await overviewRes.json()) as OverviewPayload;
    const conversationsPayload = (await conversationsRes.json()) as {
      items: Conversation[];
    };
    const leadsPayload = (await leadsRes.json()) as { items: Lead[] };

    setOverview(overviewPayload);
    setConversations(conversationsPayload.items ?? []);
    setLeads(leadsPayload.items ?? []);
  };

  const handleLogin = async () => {
    if (!apiBase || !password) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        throw new Error("Mot de passe admin invalide.");
      }
      setIsAuthenticated(true);
      await fetchAdminData();
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Erreur inconnue lors de la connexion.";
      setError(message);
      setIsAuthenticated(false);
    } finally {
      setLoading(false);
    }
  };

  const refreshData = async () => {
    if (!isAuthenticated) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await fetchAdminData();
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Erreur inconnue lors du chargement.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>Administration</p>
          <h1>Journal des discussions et contacts</h1>
        </div>
        <div className={styles.actions}>
          <label className={styles.tokenField}>
            <span>Mot de passe admin</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="ADMIN_PASSWORD"
            />
          </label>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={isAuthenticated ? refreshData : handleLogin}
            disabled={!apiBase || !password || loading}
          >
            {loading
              ? "Chargement..."
              : isAuthenticated
                ? "Rafraîchir"
                : "Se connecter"}
          </button>
        </div>
      </header>

      {error ? <div className={styles.error}>{error}</div> : null}

      <section className={styles.overviewGrid}>
        <article className={styles.card}>
          <p>Discussions</p>
          <strong>{overview?.sessions ?? "—"}</strong>
        </article>
        <article className={styles.card}>
          <p>Messages</p>
          <strong>{overview?.messages ?? "—"}</strong>
        </article>
        <article className={styles.card}>
          <p>Fiches de contact</p>
          <strong>{overview?.leads ?? "—"}</strong>
        </article>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Discussions enregistrées</h2>
          <span>{conversations.length} sessions chargées</span>
        </div>
        <div className={styles.conversationGrid}>
          {conversations.map((conversation) => (
            <article key={conversation.session_id} className={styles.conversation}>
              <header>
                <div>
                  <h3>Session {conversation.session_id.slice(0, 8)}</h3>
                  <p>Étape : {conversation.step}</p>
                </div>
                <span>
                  {conversation.created_at
                    ? new Date(conversation.created_at).toLocaleString("fr-FR")
                    : "Date inconnue"}
                </span>
              </header>
              <ul>
                {conversation.messages.length === 0 ? (
                  <li className={styles.emptyState}>
                    Aucun message enregistré pour cette session.
                  </li>
                ) : (
                  conversation.messages.map((message, index) => (
                    <li key={`${conversation.session_id}-${index}`}>
                      <div className={styles.messageHeader}>
                        <span className={styles.role}>{message.role}</span>
                        <span className={styles.step}>
                          {message.step ? `Étape ${message.step}` : "Étape inconnue"}
                        </span>
                        <span className={styles.date}>
                          {message.created_at
                            ? new Date(message.created_at).toLocaleString("fr-FR")
                            : "—"}
                        </span>
                      </div>
                      <p>{message.content}</p>
                    </li>
                  ))
                )}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Fiches de contact</h2>
          <span>{leads.length} fiches</span>
        </div>
        <div className={styles.leadsTable}>
          <div className={styles.tableHeader}>
            <span>Contact</span>
            <span>Entreprise</span>
            <span>Email</span>
            <span>Téléphone</span>
            <span>Type</span>
            <span>Création</span>
          </div>
          {leads.length === 0 ? (
            <div className={styles.emptyState}>
              Aucune fiche de contact enregistrée pour le moment.
            </div>
          ) : (
            leads.map((lead) => (
              <div key={lead.id} className={styles.tableRow}>
                <span>{lead.full_name ?? "—"}</span>
                <span>{lead.company ?? "—"}</span>
                <span>{lead.email ?? "—"}</span>
                <span>{lead.phone ?? "—"}</span>
                <span>{lead.lead_type ?? "—"}</span>
                <span>
                  {lead.created_at
                    ? new Date(lead.created_at).toLocaleString("fr-FR")
                    : "—"}
                </span>
              </div>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
