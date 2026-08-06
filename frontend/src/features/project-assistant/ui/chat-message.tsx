import type { ChatMessage as Message } from "../domain/models";
import { SourceReference } from "./source-reference";

export function ChatMessage({ message }: { message: Message }) {
  if (message.role === "system") {
    return (
      <div className="system-message" role="note">
        <span className="system-message-icon" aria-hidden="true">
          i
        </span>
        <p>{message.content}</p>
      </div>
    );
  }

  const isUser = message.role === "user";

  return (
    <article className={`message ${isUser ? "message--user" : "message--assistant"}`}>
      <div className="message-avatar" aria-hidden="true">
        {isUser ? "NB" : "N"}
      </div>
      <div className="message-body">
        <div className="message-heading">
          <strong>{message.author}</strong>
          <time>{message.createdAt}</time>
        </div>
        <div className="message-bubble">
          <p>{message.content}</p>
        </div>
        {message.sources?.length ? (
          <div className="message-sources">
            <p className="sources-heading">
              Sources utilisées <span>{message.sources.length}</span>
            </p>
            <div className="source-list">
              {message.sources.map((source) => (
                <SourceReference key={source.id} source={source} />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  );
}
