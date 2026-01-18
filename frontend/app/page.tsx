"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import styles from "./page.module.css";

const resolveApiBases = () => {
  const bases: string[] = [];
  if (process.env.NEXT_PUBLIC_BACKEND_URL) {
    bases.push(process.env.NEXT_PUBLIC_BACKEND_URL);
  }
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    bases.push(process.env.NEXT_PUBLIC_API_BASE_URL);
  }
  if (typeof window !== "undefined") {
    const { origin } = window.location;
    bases.push(origin);
  }
  return Array.from(new Set(bases));
};

type ChatButton = {
  id: string;
  label: string;
};

type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  createdAt: string;
  buttons?: ChatButton[];
  streaming?: boolean;
};

type ChatState = {
  step: string;
  slots: Record<string, string>;
  suggestedNextStep?: string;
};

type StreamFinalPayload = {
  assistant_message: string;
  state: {
    step: string;
    slot_updates?: Record<string, string>;
    suggested_next_step?: string;
  };
  buttons: ChatButton[];
};

const initialState: ChatState = {
  step: "WELCOME",
  slots: {},
};

const initialForm = {
  company: "",
  email: "",
  phone: "",
  budget: "",
};

const budgets = [
  "< 10k €",
  "10k - 50k €",
  "50k - 200k €",
  "> 200k €",
];

const generateId = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `msg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
};

export default function Home() {
  const [apiBase, setApiBase] = useState<string | null>(null);
  const apiCandidates = useMemo(() => resolveApiBases(), []);
  const apiBaseRef = useRef<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatState, setChatState] = useState<ChatState>(initialState);
  const [input, setInput] = useState("");
  const [formState, setFormState] = useState(initialForm);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initRef = useRef(false);

  const shouldShowForm = useMemo(() => {
    const step = chatState.step.toUpperCase();
    return ["BUDGET", "COLLECT_BUDGET", "LEAD_FORM"].some((value) =>
      step.includes(value),
    );
  }, [chatState.step]);

  useEffect(() => {
    if (initRef.current) {
      return;
    }

    initRef.current = true;
    const bootstrap = async () => {
      try {
        let resolvedBase: string | null = null;
        let payload: { session_id: string } | null = null;
        for (const candidate of apiCandidates) {
          try {
            const response = await fetch(`${candidate}/api/chat/session`, {
              method: "POST",
            });
            if (!response.ok) {
              console.warn(
                `[TNChatbot] Session init failed for ${candidate} (status ${response.status}).`,
              );
              continue;
            }
            payload = (await response.json()) as { session_id: string };
            resolvedBase = candidate;
            break;
          } catch (candidateError) {
            console.warn(
              `[TNChatbot] Session init error for ${candidate}.`,
              candidateError,
            );
            continue;
          }
        }

        if (!resolvedBase || !payload) {
          throw new Error("Impossible d'initialiser la session.");
        }

        setApiBase(resolvedBase);
        apiBaseRef.current = resolvedBase;
        setSessionId(payload.session_id);
        await sendMessage("Bonjour", {
          displayUserMessage: false,
          nextStateOverride: { step: "WELCOME" },
          apiBaseOverride: resolvedBase,
        });
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : "Erreur inconnue lors de l'initialisation.";
        console.error("[TNChatbot] Session bootstrap failed.", err);
        setError(
          `Session backend indisponible. Réessayez plus tard. (${message})`,
        );
      }
    };

    void bootstrap();
  }, []);

  const appendMessage = (message: ChatMessage) => {
    setMessages((prev) => [...prev, message]);
  };

  const updateMessage = (
    messageId: string,
    updater: (message: ChatMessage) => ChatMessage,
  ) => {
    setMessages((prev) =>
      prev.map((message) =>
        message.id === messageId ? updater(message) : message,
      ),
    );
  };

  const updateChatState = (next: Partial<ChatState>) => {
    setChatState((prev) => ({
      ...prev,
      ...next,
      slots: {
        ...prev.slots,
        ...(next.slots ?? {}),
      },
    }));
  };

  const handleFallbackMessage = async (
    messageId: string,
    userMessage: string,
    nextStateOverride?: Partial<ChatState>,
    apiBaseOverride?: string,
  ) => {
    if (!sessionId) {
      return;
    }

    const resolvedApiBase =
      apiBaseOverride ?? apiBaseRef.current ?? apiBase;
    if (!resolvedApiBase) {
      return;
    }

    const response = await fetch(`${resolvedApiBase}/api/chat/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        user_message: userMessage,
        state: {
          step: nextStateOverride?.step ?? chatState.step,
          slots: { ...chatState.slots, ...(nextStateOverride?.slots ?? {}) },
        },
        context: {},
      }),
    });

    if (!response.ok) {
      console.warn(
        `[TNChatbot] Fallback request failed (${response.status}) on ${resolvedApiBase}.`,
      );
      throw new Error("Impossible de récupérer une réponse.");
    }

    const payload = (await response.json()) as {
      assistant_message: string;
      buttons: ChatButton[];
      suggested_next_step: string;
      slot_updates: Record<string, string>;
    };

    updateMessage(messageId, (message) => ({
      ...message,
      content: payload.assistant_message,
      streaming: false,
      buttons: payload.buttons,
    }));

    updateChatState({
      step: payload.suggested_next_step,
      slots: payload.slot_updates,
      suggestedNextStep: payload.suggested_next_step,
    });
  };

  const sendMessage = async (
    userMessage: string,
    options?: {
      displayUserMessage?: boolean;
      nextStateOverride?: Partial<ChatState>;
      apiBaseOverride?: string;
    },
  ) => {
    if (!sessionId || isStreaming || !apiBase) {
      return;
    }

    const showUserMessage = options?.displayUserMessage !== false;
    setError(null);
    const resolvedApiBase =
      options?.apiBaseOverride ?? apiBaseRef.current ?? apiBase;
    if (!resolvedApiBase) {
      return;
    }

    if (showUserMessage) {
      appendMessage({
        id: generateId(),
        role: "user",
        content: userMessage,
        createdAt: new Date().toISOString(),
      });
    }

    const assistantId = generateId();
    appendMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
      streaming: true,
    });

    setIsStreaming(true);

    try {
      const response = await fetch(`${resolvedApiBase}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          user_message: userMessage,
          state: {
            step: options?.nextStateOverride?.step ?? chatState.step,
            slots: {
              ...chatState.slots,
              ...(options?.nextStateOverride?.slots ?? {}),
            },
          },
          context: {},
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error("Streaming indisponible.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const tokenQueue: string[] = [];
      let finalPayload: StreamFinalPayload | null = null;
      let streamClosed = false;

      const flushTokens = () => {
        if (tokenQueue.length > 0) {
          const token = tokenQueue.shift();
          if (token) {
            updateMessage(assistantId, (message) => ({
              ...message,
              content: `${message.content}${token}`,
            }));
          }
          return;
        }

        if (finalPayload) {
          updateMessage(assistantId, (message) => ({
            ...message,
            content: finalPayload.assistant_message,
            streaming: false,
            buttons: finalPayload.buttons,
          }));

          updateChatState({
            step: finalPayload.state.step,
            slots: finalPayload.state.slot_updates ?? {},
            suggestedNextStep: finalPayload.state.suggested_next_step,
          });

          finalPayload = null;
        }

        if (streamClosed) {
          setIsStreaming(false);
          clearInterval(timer);
        }
      };

      const timer = window.setInterval(flushTokens, 45);

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          streamClosed = true;
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        let separatorIndex = buffer.indexOf("\n\n");
        while (separatorIndex !== -1) {
          const chunk = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + 2);

          const lines = chunk
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          const eventLine = lines.find((line) => line.startsWith("event:"));
          const dataLine = lines.find((line) => line.startsWith("data:"));

          if (eventLine && dataLine) {
            const event = eventLine.replace("event:", "").trim();
            const data = JSON.parse(dataLine.replace("data:", "").trim());

            if (event === "token") {
              tokenQueue.push(data.value as string);
            }

            if (event === "final") {
              finalPayload = data as StreamFinalPayload;
              streamClosed = true;
            }

            if (event === "error") {
              setError("Streaming interrompu : bascule en mode classique.");
            }
          }

          separatorIndex = buffer.indexOf("\n\n");
        }
      }
    } catch (err) {
      updateMessage(assistantId, (message) => ({
        ...message,
        content: "Connexion SSE indisponible. Bascule sur réponse classique...",
      }));
      try {
        await handleFallbackMessage(
          assistantId,
          userMessage,
          options?.nextStateOverride,
          resolvedApiBase,
        );
      } catch (fallbackError) {
        const message =
          fallbackError instanceof Error
            ? fallbackError.message
            : "Erreur inconnue côté backend.";
        console.error("[TNChatbot] Fallback request failed.", fallbackError);
        setError(`Impossible de contacter le backend. (${message})`);
        updateMessage(assistantId, (message) => ({
          ...message,
          content: "Oups, le backend ne répond pas.",
          streaming: false,
        }));
      } finally {
        setIsStreaming(false);
      }
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!input.trim()) {
      return;
    }
    const message = input.trim();
    setInput("");
    await sendMessage(message);
  };

  const handleFormSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextSlots = {
      company: formState.company,
      email: formState.email,
      phone: formState.phone,
      budget: formState.budget,
    };
    updateChatState({ slots: nextSlots });
    const summary = `Résumé formulaire : société ${formState.company}, email ${formState.email}, téléphone ${formState.phone}, budget ${formState.budget}.`;
    setFormState(initialForm);
    await sendMessage(summary, { nextStateOverride: { slots: nextSlots } });
  };

  return (
    <main className={styles.page}>
      <div className={styles.chatShell}>
        <section className={styles.chatCard}>
          <header className={styles.header}>
            <div>
              <h1 style={{ margin: 0, fontSize: "1.4rem" }}>TNChatbot</h1>
              <p style={{ margin: 0, color: "#94a3b8" }}>
                Expérience chat complète (SSE, menus, formulaires)
              </p>
            </div>
            <span className={styles.badge}>
              {isStreaming ? "Streaming" : "Prêt"}
            </span>
          </header>

          <div className={styles.messages} data-testid="messages">
            {messages.map((message) => (
              <div key={message.id} className={styles.messageRow}>
                <div
                  className={`${styles.avatar} ${
                    message.role === "user" ? styles.userAvatar : ""
                  }`}
                >
                  {message.role === "user" ? "Vous" : "TN"}
                </div>
                <div>
                  <div
                    className={`${styles.bubble} ${
                      message.role === "user" ? styles.userBubble : ""
                    }`}
                    data-testid={`message-${message.role}`}
                  >
                    {message.content ||
                      (message.streaming ? "..." : "Aucun message")}
                  </div>
                  <div className={styles.messageMeta}>
                    {new Date(message.createdAt).toLocaleTimeString("fr-FR", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </div>
                  {message.buttons && message.buttons.length > 0 ? (
                    <div className={styles.buttonRow}>
                      {message.buttons.map((button) => (
                        <button
                          key={button.id}
                          type="button"
                          className={styles.ctaButton}
                          onClick={() => sendMessage(button.label)}
                          disabled={isStreaming}
                        >
                          {button.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>

          {error ? <div className={styles.status}>{error}</div> : null}

          {shouldShowForm ? (
            <div className={styles.formCard} data-testid="budget-form">
              <div className={styles.sectionTitle}>Formulaire budget</div>
              <form className={styles.formGrid} onSubmit={handleFormSubmit}>
                <label className={styles.formField}>
                  Société
                  <input
                    className={styles.formInput}
                    value={formState.company}
                    onChange={(event) =>
                      setFormState((prev) => ({
                        ...prev,
                        company: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label className={styles.formField}>
                  Email
                  <input
                    className={styles.formInput}
                    type="email"
                    value={formState.email}
                    onChange={(event) =>
                      setFormState((prev) => ({
                        ...prev,
                        email: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label className={styles.formField}>
                  Téléphone
                  <input
                    className={styles.formInput}
                    value={formState.phone}
                    onChange={(event) =>
                      setFormState((prev) => ({
                        ...prev,
                        phone: event.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label className={styles.formField}>
                  Budget média
                  <select
                    className={styles.formInput}
                    value={formState.budget}
                    onChange={(event) =>
                      setFormState((prev) => ({
                        ...prev,
                        budget: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="">Sélectionner</option>
                    {budgets.map((budget) => (
                      <option key={budget} value={budget}>
                        {budget}
                      </option>
                    ))}
                  </select>
                </label>
                <button className={styles.sendButton} type="submit">
                  Envoyer le brief
                </button>
                <p className={styles.helperText}>
                  Vos informations restent dans la session et alimentent les slots.
                </p>
              </form>
            </div>
          ) : null}

          <form className={styles.inputRow} onSubmit={handleSubmit}>
            <input
              className={styles.inputField}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Posez votre question ou choisissez un menu..."
              disabled={isStreaming}
            />
            <button
              className={styles.sendButton}
              type="submit"
              disabled={!input.trim() || isStreaming}
            >
              Envoyer
            </button>
          </form>
        </section>

        <aside className={styles.sideCard}>
          <div>
            <div className={styles.sectionTitle}>État session</div>
            <div className={styles.stateChip} data-testid="state-step">
              Étape : {chatState.step}
            </div>
          </div>
          <div>
            <div className={styles.sectionTitle}>Slots capturés</div>
            {Object.keys(chatState.slots).length === 0 ? (
              <div className={styles.helperText}>Aucun slot pour le moment.</div>
            ) : (
              Object.entries(chatState.slots).map(([key, value]) => (
                <div key={key} className={styles.stateChip}>
                  {key} : {value}
                </div>
              ))
            )}
          </div>
          <div>
            <div className={styles.sectionTitle}>Actions rapides</div>
            <button
              className={styles.ctaButton}
              type="button"
              onClick={() => sendMessage("Menu principal")}
              disabled={isStreaming}
            >
              Menu principal
            </button>
            <button
              className={styles.ctaButton}
              type="button"
              onClick={() => sendMessage("Parler à un conseiller")}
              disabled={isStreaming}
            >
              Demander un rappel
            </button>
          </div>
        </aside>
      </div>
    </main>
  );
}
