"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import styles from "./page.module.css";

const DEFAULT_BACKEND_PORT = "19081";
const DEV_BACKEND_PORT = "8000";

const formatHostname = (hostname: string) =>
  hostname.includes(":") ? `[${hostname}]` : hostname;

const resolveBackendPort = (frontendPort: string) => {
  if (process.env.NEXT_PUBLIC_BACKEND_PORT) {
    return process.env.NEXT_PUBLIC_BACKEND_PORT;
  }
  if (frontendPort === "3000") {
    return DEV_BACKEND_PORT;
  }
  if (frontendPort === "19080") {
    return DEFAULT_BACKEND_PORT;
  }
  return DEFAULT_BACKEND_PORT;
};

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
    const backendPort = resolveBackendPort(port);
    if (backendPort && backendPort !== port) {
      bases.push(`${protocol}//${formatHostname(hostname)}:${backendPort}`);
    }
    bases.push(origin);
  }
  return Array.from(new Set(bases));
};

type OverviewPayload = {
  sessions: number;
  messages: number;
  leads: number;
  kb_documents?: number;
  kb_chunks?: number;
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

type KbDocument = {
  id: string;
  source_type: string;
  source_uri: string | null;
  title: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  chunk_count: number;
};

type KbChunk = {
  id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  token_count: number | null;
  created_at: string | null;
  title: string | null;
  source_uri: string | null;
};


type IngestionPreview = {
  document: {
    title: string;
    source_uri: string;
    char_count: number;
    token_estimate: number;
  };
  split: {
    block_count: number;
    blocks: string[];
  };
  chunks: Array<{
    chunk_index: number;
    content: string;
    token_count: number;
    char_count: number;
    embedding_dimension?: number;
    embedding_preview?: number[];
  }>;
  embeddings: {
    generated: boolean;
    count: number;
    dimension: number;
  };
};

type ApiErrorPayload = {
  detail?: string;
};

type IngestionRun = {
  run_id: string;
  document_id: string;
  title: string;
  source_uri: string;
  status: string;
  rows: Array<{
    chunk_id: string;
    chunk_index: number;
    token_count: number;
    content_preview: string;
    embedding_dimension: number;
  }>;
};

type ToonTransformResponse = {
  mode: "toon";
  original_char_count: number;
  transformed_char_count: number;
  transformed_content: string;
};

type TransformDecision = "idle" | "pending" | "accepted" | "rejected";

type IngestionLogEntry = {
  timestamp: string;
  event: string;
  data: Record<string, unknown>;
};

type AdminTab = "conversations" | "leads" | "knowledge" | "ingestion";

const ADMIN_TABS: Array<{ id: AdminTab; label: string }> = [
  { id: "conversations", label: "Discussions" },
  { id: "leads", label: "Contacts" },
  { id: "knowledge", label: "Base de connaissances" },
  { id: "ingestion", label: "Ingestion" },
];

export default function AdminPage() {
  const apiCandidates = useMemo(() => resolveApiBases(), []);
  const [apiBase, setApiBase] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [overview, setOverview] = useState<OverviewPayload | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [kbDocuments, setKbDocuments] = useState<KbDocument[]>([]);
  const [kbChunks, setKbChunks] = useState<KbChunk[]>([]);
  const [kbQuery, setKbQuery] = useState("");
  const [kbDocumentFilter, setKbDocumentFilter] = useState("all");
  const [ingestionTitle, setIngestionTitle] = useState("");
  const [ingestionSourceUri, setIngestionSourceUri] = useState("");
  const [ingestionContent, setIngestionContent] = useState("");
  const [ingestionChunkSize, setIngestionChunkSize] = useState("200");
  const [ingestionOverlap, setIngestionOverlap] = useState("40");
  const [ingestionPreview, setIngestionPreview] = useState<IngestionPreview | null>(null);
  const [ingestionRun, setIngestionRun] = useState<IngestionRun | null>(null);
  const [ingestionFile, setIngestionFile] = useState<File | null>(null);
  const [toonCandidate, setToonCandidate] = useState("");
  const [transformDecision, setTransformDecision] = useState<TransformDecision>("idle");
  const [ingestionLogs, setIngestionLogs] = useState<IngestionLogEntry[]>([]);
  const [streamRunning, setStreamRunning] = useState(false);
  const [previewInfo, setPreviewInfo] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AdminTab>("conversations");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const hasDiscoveredBackend = useRef(false);

  useEffect(() => {
    if (hasDiscoveredBackend.current) {
      return;
    }
    hasDiscoveredBackend.current = true;

    const discover = async () => {
      const failedCandidates: string[] = [];
      for (const candidate of apiCandidates) {
        try {
          const response = await fetch(`${candidate}/health`);
          if (response.ok) {
            setApiBase(candidate);
            setError(null);
            return;
          }
          failedCandidates.push(`${candidate} (HTTP ${response.status})`);
        } catch {
          failedCandidates.push(`${candidate} (injoignable)`);
        }
      }

      if (failedCandidates.length > 0) {
        console.info(
          `[TNChatbot] Admin backend discovery failed: ${failedCandidates.join(" | ")}`,
        );
      }
      setError(
        [
          "Impossible de joindre le backend API (endpoints /api/admin).",
          `URLs testées : ${failedCandidates.join(" · ") || "aucune"}.`,
          "Astuce : en local, démarrez le backend sur :8000 ou définissez NEXT_PUBLIC_BACKEND_URL / NEXT_PUBLIC_BACKEND_PORT.",
        ].join(" "),
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
    const [overviewRes, conversationsRes, leadsRes, kbDocsRes, kbChunksRes] =
      await Promise.all([
      fetch(`${apiBase}/api/admin/overview`, { headers }),
      fetch(`${apiBase}/api/admin/conversations`, { headers }),
      fetch(`${apiBase}/api/admin/leads`, { headers }),
        fetch(`${apiBase}/api/admin/kb/documents`, { headers }),
        fetch(`${apiBase}/api/admin/kb/chunks`, { headers }),
      ]);

    if (
      !overviewRes.ok ||
      !conversationsRes.ok ||
      !leadsRes.ok ||
      !kbDocsRes.ok ||
      !kbChunksRes.ok
    ) {
      throw new Error("Impossible de charger les données administratives.");
    }

    const overviewPayload = (await overviewRes.json()) as OverviewPayload;
    const conversationsPayload = (await conversationsRes.json()) as {
      items: Conversation[];
    };
    const leadsPayload = (await leadsRes.json()) as { items: Lead[] };
    const kbDocsPayload = (await kbDocsRes.json()) as { items: KbDocument[] };
    const kbChunksPayload = (await kbChunksRes.json()) as { items: KbChunk[] };

    setOverview(overviewPayload);
    setConversations(conversationsPayload.items ?? []);
    setLeads(leadsPayload.items ?? []);
    setKbDocuments(kbDocsPayload.items ?? []);
    setKbChunks(kbChunksPayload.items ?? []);
  };

  const extractApiError = async (response: Response, fallbackMessage: string) => {
    try {
      const payload = (await response.json()) as ApiErrorPayload;
      if (payload.detail) {
        return payload.detail;
      }
    } catch {
      // ignore non-json errors
    }
    return fallbackMessage;
  };

  const fetchKbChunks = async () => {
    if (!apiBase || !password) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const headers = { "X-Admin-Password": password };
      const searchParams = new URLSearchParams();
      if (kbDocumentFilter !== "all") {
        searchParams.set("document_id", kbDocumentFilter);
      }
      if (kbQuery.trim()) {
        searchParams.set("query", kbQuery.trim());
      }
      const response = await fetch(
        `${apiBase}/api/admin/kb/chunks?${searchParams.toString()}`,
        { headers },
      );
      if (!response.ok) {
        throw new Error("Impossible de charger les chunks.");
      }
      const payload = (await response.json()) as { items: KbChunk[] };
      setKbChunks(payload.items ?? []);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Erreur inconnue lors du chargement des chunks.";
      setError(message);
    } finally {
      setLoading(false);
    }
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

  const runIngestionPreview = async () => {
    if (!apiBase || !password) {
      return;
    }
    setLoading(true);
    setError(null);
    setPreviewInfo(null);
    try {
      const requestPreview = async (includeEmbeddings: boolean) => {
        const response = await fetch(`${apiBase}/api/admin/kb/ingestion/preview`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Admin-Password": password,
          },
          body: JSON.stringify({
            title: ingestionTitle,
            source_uri: ingestionSourceUri,
            content: ingestionContent,
            chunk_size: Number(ingestionChunkSize),
            overlap: Number(ingestionOverlap),
            include_embeddings: includeEmbeddings,
          }),
        });
        return response;
      };

      let response = await requestPreview(true);
      if (!response.ok) {
        const detailedError = await extractApiError(
          response,
          "Prévisualisation ingestion impossible.",
        );
        response = await requestPreview(false);
        if (response.ok) {
          setPreviewInfo(
            `Prévisualisation générée sans embeddings (${detailedError}).`,
          );
        } else {
          throw new Error(detailedError);
        }
      }

      const payload = (await response.json()) as IngestionPreview;
      setIngestionPreview(payload);
      setIngestionRun(null);
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Erreur inconnue pendant la prévisualisation.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const runIngestion = async () => {
    if (!apiBase || !password) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/admin/kb/ingestion/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Password": password,
        },
        body: JSON.stringify({
          title: ingestionTitle,
          source_uri: ingestionSourceUri,
          content: ingestionContent,
          chunk_size: Number(ingestionChunkSize),
          overlap: Number(ingestionOverlap),
        }),
      });
      if (!response.ok) {
        throw new Error("Ingestion impossible.");
      }
      const payload = (await response.json()) as IngestionRun;
      setIngestionRun(payload);
      await fetchAdminData();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur inconnue pendant l'ingestion.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const runIngestionFromUpload = async () => {
    if (!apiBase || !password || !ingestionFile) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", ingestionFile);
      formData.append("title", ingestionTitle || ingestionFile.name.replace(/\.[^.]+$/, ""));
      formData.append("source_uri", ingestionSourceUri || `admin/upload/${ingestionFile.name}`);
      formData.append("chunk_size", ingestionChunkSize);
      formData.append("overlap", ingestionOverlap);

      const response = await fetch(`${apiBase}/api/admin/kb/ingestion/upload`, {
        method: "POST",
        headers: { "X-Admin-Password": password },
        body: formData,
      });
      if (!response.ok) {
        throw new Error("Ingestion via upload impossible.");
      }
      const payload = (await response.json()) as IngestionRun;
      setIngestionRun(payload);
      setIngestionPreview(null);
      await fetchAdminData();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur inconnue pendant l'upload.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const parseIngestionUpload = async () => {
    if (!apiBase || !password || !ingestionFile) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", ingestionFile);
      const response = await fetch(`${apiBase}/api/admin/kb/ingestion/upload/parse`, {
        method: "POST",
        headers: { "X-Admin-Password": password },
        body: formData,
      });
      if (!response.ok) {
        throw new Error("Lecture du fichier impossible.");
      }
      const payload = (await response.json()) as { content: string };
      setIngestionContent(payload.content || "");
      setToonCandidate("");
      setTransformDecision("idle");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur inconnue pendant la lecture du fichier.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const runToonTransform = async () => {
    if (!apiBase || !password || !ingestionContent.trim()) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/admin/kb/ingestion/transform`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Password": password,
        },
        body: JSON.stringify({
          mode: "toon",
          content: ingestionContent,
        }),
      });
      if (!response.ok) {
        throw new Error("Transformation en toon impossible.");
      }
      const payload = (await response.json()) as ToonTransformResponse;
      setToonCandidate(payload.transformed_content);
      setTransformDecision("pending");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur inconnue pendant la transformation.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const acceptToonTransform = () => {
    if (!toonCandidate) {
      return;
    }
    setIngestionContent(toonCandidate);
    setTransformDecision("accepted");
  };

  const rejectToonTransform = () => {
    setTransformDecision("rejected");
  };

  const runIngestionWithLogs = async () => {
    if (!apiBase || !password || !ingestionContent.trim()) {
      return;
    }

    setLoading(true);
    setStreamRunning(true);
    setError(null);
    setIngestionLogs([]);
    setIngestionRun(null);

    const appendLog = (event: string, data: Record<string, unknown>) => {
      setIngestionLogs((current) => [
        ...current,
        {
          timestamp: new Date().toISOString(),
          event,
          data,
        },
      ]);
    };

    try {
      const response = await fetch(`${apiBase}/api/admin/kb/ingestion/run/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Password": password,
        },
        body: JSON.stringify({
          title: ingestionTitle,
          source_uri: ingestionSourceUri,
          content: ingestionContent,
          chunk_size: Number(ingestionChunkSize),
          overlap: Number(ingestionOverlap),
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Lancement ingestion stream impossible.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffered += decoder.decode(value, { stream: true });
        const lines = buffered.split("\n");
        buffered = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) {
            continue;
          }
          const parsed = JSON.parse(line) as {
            event: string;
            data: Record<string, unknown>;
          };

          appendLog(parsed.event, parsed.data || {});

          if (parsed.event === "result") {
            setIngestionRun(parsed.data as unknown as IngestionRun);
            await fetchAdminData();
          }

          if (parsed.event === "error") {
            throw new Error(String(parsed.data?.detail || "Erreur inconnue pendant l'ingestion."));
          }
        }
      }
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur inconnue pendant l'ingestion stream.";
      setError(message);
      appendLog("client_error", { detail: message });
    } finally {
      setLoading(false);
      setStreamRunning(false);
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
        <article className={styles.card}>
          <p>Documents KB</p>
          <strong>{overview?.kb_documents ?? "—"}</strong>
        </article>
        <article className={styles.card}>
          <p>Chunks KB</p>
          <strong>{overview?.kb_chunks ?? "—"}</strong>
        </article>
      </section>

      <nav className={styles.tabs} aria-label="Sections administrateur">
        {ADMIN_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`${styles.tabButton} ${activeTab === tab.id ? styles.tabButtonActive : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === "conversations" ? (
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
      ) : null}

      {activeTab === "leads" ? (
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
      ) : null}

      {activeTab === "knowledge" ? (
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Base de connaissances</h2>
          <span>
            {kbDocuments.length} documents · {kbChunks.length} chunks
          </span>
        </div>
        <div className={styles.kbGrid}>
          <article className={styles.card}>
            <header className={styles.kbHeader}>
              <h3>Documents ingérés</h3>
              <span>Dernières mises à jour</span>
            </header>
            <ul className={styles.kbList}>
              {kbDocuments.length === 0 ? (
                <li className={styles.emptyState}>
                  Aucun document n'a encore été ingéré.
                </li>
              ) : (
                kbDocuments.map((doc) => (
                  <li key={doc.id} className={styles.kbItem}>
                    <div>
                      <strong>{doc.title ?? "Sans titre"}</strong>
                      <p className={styles.kbMeta}>
                        {doc.source_type} ·{" "}
                        {doc.source_uri ?? "Source inconnue"}
                      </p>
                    </div>
                    <div className={styles.kbMeta}>
                      <span>{doc.chunk_count} chunks</span>
                      <span>
                        {doc.updated_at
                          ? new Date(doc.updated_at).toLocaleString("fr-FR")
                          : "Date inconnue"}
                      </span>
                      <span>Statut : {doc.status}</span>
                    </div>
                  </li>
                ))
              )}
            </ul>
          </article>
          <article className={styles.card}>
            <header className={styles.kbHeader}>
              <h3>Chunks disponibles</h3>
              <span>Recherche rapide</span>
            </header>
            <div className={styles.chunkFilters}>
              <label>
                <span>Document</span>
                <select
                  value={kbDocumentFilter}
                  onChange={(event) => setKbDocumentFilter(event.target.value)}
                >
                  <option value="all">Tous les documents</option>
                  {kbDocuments.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.title ?? doc.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>Recherche</span>
                <input
                  type="text"
                  value={kbQuery}
                  onChange={(event) => setKbQuery(event.target.value)}
                  placeholder="Tapez un mot-clé"
                />
              </label>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={fetchKbChunks}
                disabled={!isAuthenticated || loading}
              >
                Filtrer
              </button>
            </div>
            <ul className={styles.kbList}>
              {kbChunks.length === 0 ? (
                <li className={styles.emptyState}>
                  Aucun chunk disponible pour les filtres actuels.
                </li>
              ) : (
                kbChunks.map((chunk) => (
                  <li key={chunk.id} className={styles.kbItem}>
                    <div>
                      <strong>
                        {chunk.title ?? "Document sans titre"} · Chunk{" "}
                        {chunk.chunk_index + 1}
                      </strong>
                      <p className={styles.kbMeta}>
                        {chunk.source_uri ?? "Source inconnue"}
                      </p>
                    </div>
                    <p className={styles.chunkContent}>{chunk.content}</p>
                    <div className={styles.kbMeta}>
                      <span>
                        {chunk.token_count
                          ? `${chunk.token_count} tokens`
                          : "Tokens inconnus"}
                      </span>
                      <span>
                        {chunk.created_at
                          ? new Date(chunk.created_at).toLocaleString("fr-FR")
                          : "Date inconnue"}
                      </span>
                    </div>
                  </li>
                ))
              )}
            </ul>
          </article>
        </div>
      </section>
      ) : null}

      {activeTab === "ingestion" ? (
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Ingestion manuelle (Admin)</h2>
          <span>Split → Chunking → Embedding → Indexing</span>
        </div>
        <article className={styles.card}>
          <div className={styles.chunkFilters}>
            <label>
              <span>Titre</span>
              <input
                type="text"
                value={ingestionTitle}
                onChange={(event) => setIngestionTitle(event.target.value)}
                placeholder="Titre du document"
              />
            </label>
            <label>
              <span>Source URI</span>
              <input
                type="text"
                value={ingestionSourceUri}
                onChange={(event) => setIngestionSourceUri(event.target.value)}
                placeholder="admin/manual/document"
              />
            </label>
            <label>
              <span>Chunk size</span>
              <input
                type="number"
                value={ingestionChunkSize}
                onChange={(event) => setIngestionChunkSize(event.target.value)}
              />
            </label>
            <label>
              <span>Overlap</span>
              <input
                type="number"
                value={ingestionOverlap}
                onChange={(event) => setIngestionOverlap(event.target.value)}
              />
            </label>
          </div>
          <label className={styles.tokenField}>
            <span>Uploader un fichier (.txt, .md, .pdf, .json, .jsonl)</span>
            <input
              type="file"
              accept=".txt,.md,.pdf,.json,.jsonl,text/plain,text/markdown,application/pdf,application/json"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setIngestionFile(file);
                if (file) {
                  setIngestionTitle((current) => current || file.name.replace(/\.[^.]+$/, ""));
                  setIngestionSourceUri((current) => current || `admin/upload/${file.name}`);
                }
              }}
            />
          </label>
          <label className={styles.tokenField}>
            <span>Contenu document (optionnel si upload)</span>
            <textarea
              className={styles.textarea}
              value={ingestionContent}
              onChange={(event) => {
                setIngestionContent(event.target.value);
                setToonCandidate("");
                setTransformDecision("idle");
              }}
              placeholder="Collez votre document ici..."
            />
          </label>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={parseIngestionUpload}
              disabled={!isAuthenticated || loading || !ingestionFile || transformDecision === "pending"}
            >
              Charger le fichier
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={runToonTransform}
              disabled={!isAuthenticated || loading || !ingestionContent.trim()}
            >
              Transformer en toon
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={runIngestionPreview}
              disabled={!isAuthenticated || loading || !ingestionContent.trim() || transformDecision === "pending"}
            >
              Prévisualiser pipeline
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={runIngestion}
              disabled={!isAuthenticated || loading || (!ingestionContent.trim() && !ingestionFile) || transformDecision === "pending"}
            >
              Lancer ingestion
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={runIngestionWithLogs}
              disabled={!isAuthenticated || loading || !ingestionContent.trim() || transformDecision === "pending"}
            >
              Lancer ingestion (logs temps réel)
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={runIngestionFromUpload}
              disabled={!isAuthenticated || loading || !ingestionFile || transformDecision === "pending"}
            >
              Uploader et ingérer
            </button>
          </div>

          {transformDecision === "pending" ? (
            <div className={styles.card}>
              <h3>Validation transformation toon</h3>
              <p>Validez ou refusez le résultat avant de continuer l'ingestion.</p>
              <label className={styles.tokenField}>
                <span>Résultat transformé</span>
                <textarea className={styles.textarea} value={toonCandidate} readOnly />
              </label>
              <div className={styles.actions}>
                <button type="button" className={styles.primaryButton} onClick={acceptToonTransform}>
                  Valider la transformation
                </button>
                <button type="button" className={styles.primaryButton} onClick={rejectToonTransform}>
                  Refuser la transformation
                </button>
              </div>
            </div>
          ) : null}

          {ingestionPreview ? (
            <div className={styles.previewSection}>
              {previewInfo ? <p className={styles.previewInfo}>{previewInfo}</p> : null}
              <div className={styles.ingestionGrid}>
                <div>
                  <h3>Split</h3>
                  <p>{ingestionPreview.split.block_count} blocs détectés</p>
                </div>
                <div>
                  <h3>Chunking</h3>
                  <p>{ingestionPreview.chunks.length} chunks générés</p>
                </div>
                <div>
                  <h3>Embedding</h3>
                  <p>Dimension: {ingestionPreview.embeddings.dimension || "—"}</p>
                </div>
                <div>
                  <h3>Document</h3>
                  <p>{ingestionPreview.document.token_estimate} tokens estimés</p>
                </div>
              </div>

              <h3>Aperçu du split (premiers blocs)</h3>
              <ul className={styles.previewBlockList}>
                {ingestionPreview.split.blocks.slice(0, 3).map((block, index) => (
                  <li key={`split-${index}`}>{block}</li>
                ))}
              </ul>

              <h3>Aperçu des chunks</h3>
              <div className={styles.leadsTable}>
                <div className={styles.ingestionTableHeader}>
                  <span>Chunk</span>
                  <span>Tokens</span>
                  <span>Chars</span>
                  <span>Contenu</span>
                  <span>Embedding</span>
                </div>
                {ingestionPreview.chunks.slice(0, 5).map((chunk) => (
                  <div key={`preview-${chunk.chunk_index}`} className={styles.ingestionTableRow}>
                    <span>{chunk.chunk_index + 1}</span>
                    <span>{chunk.token_count}</span>
                    <span>{chunk.char_count}</span>
                    <span>{chunk.content}</span>
                    <span>{chunk.embedding_dimension ?? "—"}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {ingestionLogs.length > 0 ? (
            <div className={styles.leadsTable}>
              <div className={styles.ingestionTableHeader}>
                <span>Horodatage</span>
                <span>Événement</span>
                <span>Détails</span>
                <span>Statut</span>
                <span>—</span>
              </div>
              {ingestionLogs.map((log, index) => (
                <div key={`${log.timestamp}-${index}`} className={styles.ingestionTableRow}>
                  <span>{new Date(log.timestamp).toLocaleTimeString("fr-FR")}</span>
                  <span>{log.event}</span>
                  <span>{JSON.stringify(log.data)}</span>
                  <span>{log.event === "error" || log.event === "client_error" ? "❌" : "✅"}</span>
                  <span>{streamRunning && index === ingestionLogs.length - 1 ? "en cours..." : ""}</span>
                </div>
              ))}
            </div>
          ) : null}

          {ingestionLogs.length > 0 ? (
            <div className={styles.leadsTable}>
              <div className={styles.ingestionTableHeader}>
                <span>Horodatage</span>
                <span>Événement</span>
                <span>Détails</span>
                <span>Statut</span>
                <span>—</span>
              </div>
              {ingestionLogs.map((log, index) => (
                <div key={`${log.timestamp}-${index}`} className={styles.ingestionTableRow}>
                  <span>{new Date(log.timestamp).toLocaleTimeString("fr-FR")}</span>
                  <span>{log.event}</span>
                  <span>{JSON.stringify(log.data)}</span>
                  <span>{log.event === "error" || log.event === "client_error" ? "❌" : "✅"}</span>
                  <span>{streamRunning && index === ingestionLogs.length - 1 ? "en cours..." : ""}</span>
                </div>
              ))}
            </div>
          ) : null}

          {ingestionRun ? (
            <div className={styles.leadsTable}>
              <div className={styles.ingestionTableHeader}>
                <span>Chunk</span>
                <span>Tokens</span>
                <span>Dimension</span>
                <span>Aperçu contenu</span>
                <span>Chunk ID</span>
              </div>
              {ingestionRun.rows.map((row) => (
                <div key={row.chunk_id} className={styles.ingestionTableRow}>
                  <span>{row.chunk_index + 1}</span>
                  <span>{row.token_count}</span>
                  <span>{row.embedding_dimension}</span>
                  <span>{row.content_preview}</span>
                  <span>{row.chunk_id.slice(0, 12)}...</span>
                </div>
              ))}
            </div>
          ) : null}
        </article>
      </section>
      ) : null}

    </main>
  );
}
