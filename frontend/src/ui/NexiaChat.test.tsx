import { act, render, screen, waitFor, within } from "@testing-library/react";
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

    const heading = screen.getByRole("heading", { name: /Bienvenue sur NEXIA/i });
    const logos = heading.nextElementSibling as HTMLElement;
    const subtitle = screen.getByText(
      "Votre assistant intelligent pour naviguer entre vos outils collaboratifs",
    );

    expect(logos).toHaveClass("source-logos");
    expect(logos.nextElementSibling).toBe(subtitle);
    expect(within(logos).getByRole("img", { name: "Figma" })).toBeInTheDocument();
    expect(within(logos).getByRole("img", { name: "Jira" })).toBeInTheDocument();
    expect(within(logos).getByRole("img", { name: "Confluence" })).toBeInTheDocument();
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

  it("affiche l’icône de chaque source avant sa référence sans changer les liens", async () => {
    const gateway = createGateway({
      askQuestion: vi.fn().mockResolvedValue({
        answer: "Voici les références.",
        sources: [
          {
            title: "Ticket Jira lié",
            url: "https://jira.example.test/browse/DESIGN-1",
            provider: "FIGMA_MCP",
          },
          {
            title: "PROJ-42",
            url: "https://jira.example.test/browse/PROJ-42",
            provider: "Atlassian Jira",
          },
          {
            title: "Cahier des charges Confluence",
            url: "https://docs.example.test/spec",
          },
          {
            title: "Référence externe",
            provider: "knowledge",
          },
        ],
      }),
    });
    const user = userEvent.setup();
    render(<NexiaChat gateway={gateway} />);

    await user.type(screen.getByRole("textbox", { name: "Votre message" }), "Montre les sources");
    await user.click(screen.getByRole("button", { name: "Envoyer le message" }));

    const sources = await screen.findByLabelText("Sources de la réponse");
    const references = within(sources).getAllByRole("listitem");
    const expected = [
      ["Source Figma", "Ticket Jira lié", "/figma-assets/figma.svg"],
      ["Source Jira", "PROJ-42", "/figma-assets/jira.svg"],
      ["Source Confluence", "Cahier des charges Confluence", "/figma-assets/confluence.svg"],
      ["Source externe", "Référence externe", "/figma-assets/link.svg"],
    ];

    references.forEach((reference, index) => {
      const icon = within(reference).getByRole("img", { name: expected[index][0] });
      const label = within(reference).getByText(expected[index][1]);
      expect(icon).toHaveAttribute("src", expected[index][2]);
      expect(icon.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    const linkedReferences = references.slice(0, 3).map((reference) =>
      within(reference).getByRole("link"),
    );
    expect(linkedReferences[0]).toHaveAttribute(
      "href",
      "https://jira.example.test/browse/DESIGN-1",
    );
    expect(linkedReferences[1]).toHaveAttribute("href", "https://jira.example.test/browse/PROJ-42");
    expect(linkedReferences[2]).toHaveAttribute("href", "https://docs.example.test/spec");
    linkedReferences.forEach((reference) => {
      expect(reference).toHaveAttribute("target", "_blank");
      expect(reference).toHaveAttribute("rel", "noreferrer");
    });
    expect(within(references[3]).queryByRole("link")).not.toBeInTheDocument();
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
