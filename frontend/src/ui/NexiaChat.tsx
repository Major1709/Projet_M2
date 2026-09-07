"use client";

import Image from "next/image";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  NexiaApiError,
  type NexiaAnswer,
  type NexiaGateway,
  nexiaApi,
} from "@/adapters/nexia-api";
import { MutationApprovalPreview } from "@/ui/MutationApprovalPreview";

type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      text: string;
      sources: NexiaAnswer["sources"];
      approval?: NexiaAnswer["approval"];
    };

const MAX_QUESTION_LENGTH = 4000;

type SourceIcon = {
  kind: "figma" | "jira" | "confluence" | "link";
  label: string;
  src: string;
};

const SOURCE_ICONS: Record<SourceIcon["kind"], SourceIcon> = {
  figma: {
    kind: "figma",
    label: "Figma",
    src: "/figma-assets/figma.svg",
  },
  jira: {
    kind: "jira",
    label: "Jira",
    src: "/figma-assets/jira.svg",
  },
  confluence: {
    kind: "confluence",
    label: "Confluence",
    src: "/figma-assets/confluence.svg",
  },
  link: {
    kind: "link",
    label: "externe",
    src: "/figma-assets/link.svg",
  },
};

function messageId(role: ChatMessage["role"]): string {
  return `${role}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function sourceLabel(source: NexiaAnswer["sources"][number], index: number): string {
  if (source.title?.trim()) return source.title;
  if (source.url?.trim()) return source.url;
  return `Source ${index + 1}`;
}

function sourceIcon(source: NexiaAnswer["sources"][number]): SourceIcon {
  const candidates = [source.provider, source.title, source.url];

  for (const candidate of candidates) {
    const normalized = candidate?.trim().toLowerCase();
    if (!normalized) continue;
    if (normalized.includes("figma")) return SOURCE_ICONS.figma;
    if (normalized.includes("jira")) return SOURCE_ICONS.jira;
    if (normalized.includes("confluence")) return SOURCE_ICONS.confluence;
  }

  return SOURCE_ICONS.link;
}

type NexiaChatProps = {
  gateway?: NexiaGateway;
};

export function NexiaChat({ gateway = nexiaApi }: NexiaChatProps) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [isDisconnected, setIsDisconnected] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);
  const historyMenuItemRef = useRef<HTMLButtonElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const dialogCloseRef = useRef<HTMLButtonElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const hasConversation = messages.length > 0;
  const normalizedQuestion = question.trim();
  const canSend =
    !isSending &&
    !isDisconnected &&
    normalizedQuestion.length > 0 &&
    normalizedQuestion.length <= MAX_QUESTION_LENGTH;

  useEffect(() => {
    if (!profileOpen) return;
    historyMenuItemRef.current?.focus();

    function closeOnOutsideClick(event: MouseEvent) {
      const target = event.target as Node;
      if (
        !profileMenuRef.current?.contains(target) &&
        !profileButtonRef.current?.contains(target)
      ) {
        setProfileOpen(false);
      }
    }

    function closeOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setProfileOpen(false);
        profileButtonRef.current?.focus();
      }
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [profileOpen]);

  useEffect(() => {
    if (!historyOpen) return;
    dialogCloseRef.current?.focus();

    function closeDialogOnEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setHistoryOpen(false);
        profileButtonRef.current?.focus();
      }
    }

    document.addEventListener("keydown", closeDialogOnEscape);
    return () => document.removeEventListener("keydown", closeDialogOnEscape);
  }, [historyOpen]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [isSending, messages]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSend) return;

    const submittedQuestion = normalizedQuestion;
    setQuestion("");
    setError(null);
    setIsSending(true);
    setMessages((current) => [
      ...current,
      { id: messageId("user"), role: "user", text: submittedQuestion },
    ]);

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        activeConversationId = await gateway.createConversation();
        setConversationId(activeConversationId);
      }

      const answer = await gateway.askQuestion({
        conversationId: activeConversationId,
        question: submittedQuestion,
        correlationId: crypto.randomUUID(),
      });
      setMessages((current) => [
        ...current,
        {
          id: messageId("assistant"),
          role: "assistant",
          text: answer.answer,
          sources: answer.sources,
          approval: answer.approval,
        },
      ]);
    } catch (caught) {
      if (caught instanceof NexiaApiError && caught.status === 401) {
        setIsDisconnected(true);
      }
      setError(
        caught instanceof NexiaApiError
          ? caught.message
          : "NEXIA n’a pas pu répondre. Vérifiez votre connexion puis réessayez.",
      );
    } finally {
      setIsSending(false);
      requestAnimationFrame(() => composerRef.current?.focus());
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  function closeHistory() {
    setHistoryOpen(false);
    requestAnimationFrame(() => profileButtonRef.current?.focus());
  }

  function keepFocusInsideHistory(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Tab") {
      event.preventDefault();
      dialogCloseRef.current?.focus();
    }
  }

  function resetConversation() {
    if (isSending) return;
    setConversationId(null);
    setMessages([]);
    setQuestion("");
    setError(null);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function handleSignOut() {
    setProfileOpen(false);
    setError(null);
    setIsSigningOut(true);
    try {
      await gateway.signOut();
      setIsDisconnected(true);
      setConversationId(null);
      setMessages([]);
    } catch (caught) {
      setError(
        caught instanceof NexiaApiError
          ? caught.message
          : "La déconnexion a échoué. Veuillez réessayer.",
      );
    } finally {
      setIsSigningOut(false);
    }
  }

  return (
    <main className={`nexia-shell ${hasConversation ? "nexia-shell--chat" : ""}`}>
      <header className="nexia-header">
        <div className="profile">
          <button
            ref={profileButtonRef}
            className="profile__trigger"
            type="button"
            aria-label="Ouvrir le menu du profil"
            aria-haspopup="menu"
            aria-expanded={profileOpen}
            aria-controls="profile-menu"
            onClick={() => setProfileOpen((open) => !open)}
          >
            <span aria-hidden="true">U</span>
          </button>

          {profileOpen ? (
            <div ref={profileMenuRef} id="profile-menu" className="profile__menu" role="menu">
              <p className="profile__identity" role="presentation">Profil utilisateur</p>
              <button
                ref={historyMenuItemRef}
                type="button"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);
                  setHistoryOpen(true);
                }}
              >
                Historique des changements
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={isSigningOut}
                onClick={handleSignOut}
              >
                {isSigningOut ? "Déconnexion…" : "Se déconnecter"}
              </button>
            </div>
          ) : null}
        </div>
      </header>

      {isDisconnected ? (
        <section className="nexia-disconnected" aria-labelledby="disconnected-title">
          <h1 id="disconnected-title">Vous êtes déconnecté</h1>
          <p>Reconnectez-vous pour reprendre une conversation avec NEXIA.</p>
          <a
            className="nexia-disconnected__link"
            href={`${(process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "")}/api/auth/atlassian/start`}
          >
            Se reconnecter
          </a>
        </section>
      ) : hasConversation ? (
        <section className="conversation" aria-label="Conversation avec NEXIA" aria-live="polite">
          <div className="conversation__messages">
            {messages.map((message) => (
              <article
                key={message.id}
                className={`message-row message-row--${message.role}`}
              >
                <div className={`message-avatar message-avatar--${message.role}`} aria-hidden="true">
                  {message.role === "user" ? "U" : "N"}
                </div>
                <div
                  className={`message-content ${
                    message.role === "assistant" && message.approval
                      ? "message-content--approval"
                      : ""
                  }`}
                >
                  <p className={`message-bubble message-bubble--${message.role}`}>{message.text}</p>
                  {message.role === "assistant" && message.sources.length > 0 ? (
                    <div className="message-sources" aria-label="Sources de la réponse">
                      <p>Sources</p>
                      <ul>
                        {message.sources.map((source, index) => {
                          const icon = sourceIcon(source);
                          const label = sourceLabel(source, index);
                          const content = (
                            <>
                              <span
                                className={`message-source__icon message-source__icon--${icon.kind}`}
                              >
                                <Image
                                  src={icon.src}
                                  width={18}
                                  height={18}
                                  alt={`Source ${icon.label}`}
                                />
                              </span>
                              <span className="message-source__label">
                                {label}
                              </span>
                            </>
                          );

                          return (
                            <li key={`${source.url ?? source.title ?? "source"}-${index}`}>
                              {source.url ? (
                                <a
                                  className="message-source"
                                  href={source.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  aria-label={label}
                                >
                                  {content}
                                </a>
                              ) : (
                                <span className="message-source">{content}</span>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                  {message.role === "assistant" && message.approval ? (
                    <MutationApprovalPreview
                      approval={message.approval}
                      gateway={gateway}
                      onSessionRequired={() => setIsDisconnected(true)}
                    />
                  ) : null}
                </div>
              </article>
            ))}

            {isSending ? (
              <article className="message-row message-row--assistant" aria-label="NEXIA prépare sa réponse">
                <div className="message-avatar message-avatar--assistant" aria-hidden="true">N</div>
                <p className="message-bubble message-bubble--assistant message-bubble--loading">
                  <span />
                  <span />
                  <span />
                </p>
              </article>
            ) : null}
            <div ref={messagesEndRef} className="conversation__end" aria-hidden="true" />
          </div>
        </section>
      ) : (
        <section className="welcome" aria-labelledby="welcome-title">
          <h1 id="welcome-title">
            Bienvenue sur NEXIA
            <Image
              className="welcome__hand"
              src="/figma-assets/welcome-hand.png"
              width={33}
              height={33}
              alt=""
            />
          </h1>
          <div className="source-logos" aria-label="Sources connectées">
            <span className="source-logo">
              <Image src="/figma-assets/figma.svg" width={32} height={32} alt="Figma" />
            </span>
            <span className="source-logo">
              <Image src="/figma-assets/jira.svg" width={32} height={32} alt="Jira" />
            </span>
            <span className="source-logo source-logo--confluence">
              <Image src="/figma-assets/confluence.svg" width={24} height={24} alt="Confluence" />
            </span>
          </div>
          <p>Votre assistant intelligent pour naviguer entre vos outils collaboratifs</p>

          <div className="capabilities" aria-label="Fonctionnalités de NEXIA">
            <article className="capability-card">
              <Image src="/figma-assets/stars.svg" width={24} height={24} alt="" />
              <h2>Réponses intelligentes</h2>
              <p>Obtenez des réponses contextuelles basées sur vos données</p>
            </article>
            <article className="capability-card">
              <Image src="/figma-assets/link.svg" width={24} height={24} alt="" />
              <h2>Sources unifiées</h2>
              <p>Figma, Jira et Confluence réunis en un seul endroit</p>
            </article>
            <article className="capability-card">
              <Image src="/figma-assets/search.svg" width={24} height={24} alt="" />
              <h2>Recherche instantanée</h2>
              <p>Trouvez l’information dont vous avez besoin en quelques secondes</p>
            </article>
          </div>
        </section>
      )}

      {!isDisconnected ? (
        <form className="composer" onSubmit={handleSubmit} aria-label="Envoyer un message à NEXIA">
          <Image className="composer__wand" src="/figma-assets/wand.svg" width={24} height={24} alt="" />
          <label className="sr-only" htmlFor="nexia-question">Votre message</label>
          <textarea
            ref={composerRef}
            id="nexia-question"
            value={question}
            maxLength={MAX_QUESTION_LENGTH}
            rows={1}
            disabled={isSending}
            placeholder="Demandez quelque chose à NEXIA…"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={handleComposerKeyDown}
          />
          <span className="composer__count" aria-live="polite">
            {question.length}/{MAX_QUESTION_LENGTH}
          </span>
          <div className="composer__actions">
            <button
              className="composer__reset"
              type="button"
              aria-label="Réinitialiser la conversation"
              title="Réinitialiser la conversation"
              disabled={isSending || (!hasConversation && question.length === 0)}
              onClick={resetConversation}
            >
              <span aria-hidden="true">↻</span>
            </button>
            <button className="composer__send" type="submit" disabled={!canSend} aria-label="Envoyer le message">
              <Image src="/figma-assets/send.svg" width={18} height={18} alt="" />
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <div className="nexia-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Fermer le message d’erreur">×</button>
        </div>
      ) : null}

      {historyOpen ? (
        <div className="dialog-backdrop" role="presentation" onMouseDown={closeHistory}>
          <section
            className="history-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="history-title"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={keepFocusInsideHistory}
          >
            <button
              ref={dialogCloseRef}
              className="history-dialog__close"
              type="button"
              aria-label="Fermer l’historique"
              onClick={closeHistory}
            >
              ×
            </button>
            <h2 id="history-title">Historique des changements</h2>
            <p className="history-dialog__empty">L’historique n’est pas encore disponible.</p>
          </section>
        </div>
      ) : null}
    </main>
  );
}
