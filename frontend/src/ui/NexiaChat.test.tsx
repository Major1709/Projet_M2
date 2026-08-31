import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NexiaApiError, type NexiaAnswer, type NexiaGateway } from "@/adapters/nexia-api";

import { NexiaChat } from "./NexiaChat";

function createGateway(overrides: Partial<NexiaGateway> = {}): NexiaGateway {
  return {
    createConversation: vi.fn().mockResolvedValue("conversation-1"),
    askQuestion: vi.fn().mockResolvedValue({ answer: "Réponse NEXIA", sources: [] }),
    signOut: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "correlation-1") });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("NexiaChat", () => {
  it("affiche l’accueil Figma et un menu profil accessible", async () => {
    const user = userEvent.setup();
    render(<NexiaChat gateway={createGateway()} />);

    expect(screen.getByRole("heading", { name: /Bienvenue sur NEXIA/i })).toBeInTheDocument();
    const profile = screen.getByRole("button", { name: "Ouvrir le menu du profil" });
    expect(profile).toHaveAttribute("aria-expanded", "false");

    await user.click(profile);

    expect(profile).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Historique des changements" })).toHaveFocus();
    expect(screen.getByRole("menuitem", { name: "Se déconnecter" })).toBeInTheDocument();
  });

  it("ouvre l’historique avec un état indisponible honnête", async () => {
    const user = userEvent.setup();
    render(<NexiaChat gateway={createGateway()} />);

    await user.click(screen.getByRole("button", { name: "Ouvrir le menu du profil" }));
    await user.click(screen.getByRole("menuitem", { name: "Historique des changements" }));

    expect(screen.getByRole("dialog", { name: "Historique des changements" })).toBeInTheDocument();
    expect(screen.getByText("L’historique n’est pas encore disponible.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fermer l’historique" })).toHaveFocus();
  });

  it("passe immédiatement au design de conversation puis affiche la réponse", async () => {
    const answer = deferred<NexiaAnswer>();
    const gateway = createGateway({ askQuestion: vi.fn(() => answer.promise) });
    const user = userEvent.setup();
    render(<NexiaChat gateway={gateway} />);

    await user.type(screen.getByRole("textbox", { name: "Votre message" }), "Où est la spec ?");
    await user.click(screen.getByRole("button", { name: "Envoyer le message" }));

    expect(await screen.findByText("Où est la spec ?")).toBeInTheDocument();
    expect(screen.getByLabelText("NEXIA prépare sa réponse")).toBeInTheDocument();

    await act(async () => {
      answer.resolve({
        answer: "La spec est dans Confluence.",
        sources: [{ title: "Confluence", url: "https://example.test/spec" }],
      });
    });

    expect(await screen.findByText("La spec est dans Confluence.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Confluence" })).toHaveAttribute(
      "href",
      "https://example.test/spec",
    );
    expect(gateway.askQuestion).toHaveBeenCalledWith({
      conversationId: "conversation-1",
      correlationId: "correlation-1",
      question: "Où est la spec ?",
    });
  });

  it("réinitialise localement et crée paresseusement un nouveau fil au prochain message", async () => {
    const gateway = createGateway();
    const user = userEvent.setup();
    render(<NexiaChat gateway={gateway} />);
    const input = screen.getByRole("textbox", { name: "Votre message" });

    await user.type(input, "Premier message");
    await user.click(screen.getByRole("button", { name: "Envoyer le message" }));
    expect(await screen.findByText("Réponse NEXIA")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Réinitialiser la conversation" }));
    expect(screen.getByRole("heading", { name: /Bienvenue sur NEXIA/i })).toBeInTheDocument();
    expect(screen.queryByText("Premier message")).not.toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Votre message" }), "Nouveau message");
    await user.click(screen.getByRole("button", { name: "Envoyer le message" }));
    await waitFor(() => expect(gateway.createConversation).toHaveBeenCalledTimes(2));
  });

  it("effectue une vraie déconnexion et passe à l’état déconnecté", async () => {
    const gateway = createGateway();
    const user = userEvent.setup();
    render(<NexiaChat gateway={gateway} />);

    await user.click(screen.getByRole("button", { name: "Ouvrir le menu du profil" }));
    await user.click(screen.getByRole("menuitem", { name: "Se déconnecter" }));

    await waitFor(() => expect(gateway.signOut).toHaveBeenCalledOnce());
    expect(await screen.findByRole("heading", { name: "Vous êtes déconnecté" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Envoyer un message à NEXIA" })).not.toBeInTheDocument();
  });

  it("ne révèle pas l’erreur backend et traite une session expirée", async () => {
    const gateway = createGateway({
      askQuestion: vi.fn().mockRejectedValue(
        new NexiaApiError("Votre session a expiré. Veuillez vous reconnecter.", 401),
      ),
    });
    const user = userEvent.setup();
    render(<NexiaChat gateway={gateway} />);

    await user.type(screen.getByRole("textbox", { name: "Votre message" }), "Question");
    await user.click(screen.getByRole("button", { name: "Envoyer le message" }));

    expect(await screen.findByRole("heading", { name: "Vous êtes déconnecté" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Votre session a expiré. Veuillez vous reconnecter.",
    );
  });
});
