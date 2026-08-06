"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { SendIcon, SparklesIcon } from "./icons";

interface MessageComposerProps {
  disabled?: boolean;
  onSend: (content: string) => Promise<void>;
}

export function MessageComposer({ disabled = false, onSend }: MessageComposerProps) {
  const [value, setValue] = useState("");

  async function submit() {
    const content = value.trim();
    if (!content || disabled) return;
    setValue("");
    await onSend(content);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <div className="composer-context">
        <SparklesIcon width={15} height={15} />
        <span>Réponse simulée · aucune connexion MCP</span>
      </div>
      <div className="composer-row">
        <label className="composer-input">
          <span className="sr-only">Votre message</span>
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Interrogez les demandes et les sources du projet…"
            rows={1}
            disabled={disabled}
          />
        </label>
        <button
          className="send-button"
          type="submit"
          disabled={!value.trim() || disabled}
          aria-label="Envoyer le message"
        >
          <SendIcon width={19} height={19} />
        </button>
      </div>
      <p className="composer-note">Entrée pour envoyer · Maj + Entrée pour une nouvelle ligne</p>
    </form>
  );
}
