import type { ChatMessage as Message } from "../domain/models";
import { ChatMessage } from "./chat-message";
import { MessageComposer } from "./message-composer";

interface ChatConversationProps {
  messages: Message[];
  isResponding: boolean;
  onSend: (content: string) => Promise<void>;
}

export function ChatConversation({ messages, isResponding, onSend }: ChatConversationProps) {
  return (
    <main className="conversation" aria-labelledby="conversation-heading">
      <header className="conversation-header">
        <div>
          <p className="eyebrow">Conversation active</p>
          <h1 id="conversation-heading">Analyse du parcours d’authentification</h1>
        </div>
        <div className="conversation-status" role="status">
          <span className="live-dot" aria-hidden="true" />
          Session protégée
        </div>
      </header>

      <div className="conversation-timeline" aria-live="polite" aria-busy={isResponding}>
        <div className="date-divider">
          <span>Aujourd’hui</span>
        </div>
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}
        {isResponding ? (
          <div className="assistant-thinking" role="status">
            <span className="thinking-avatar">N</span>
            <span className="thinking-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span className="sr-only">Nexus prépare une réponse</span>
          </div>
        ) : null}
      </div>

      <MessageComposer disabled={isResponding} onSend={onSend} />
    </main>
  );
}
