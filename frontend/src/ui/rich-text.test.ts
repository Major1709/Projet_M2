import { describe, expect, it } from "vitest";

import { inlineSpans, parseBlocks } from "./rich-text";

/**
 * La reponse telle que NEXIA l'ecrit REELLEMENT, relevee sur sa reponse au sujet du
 * projet KAN plutot qu'inventee. Un double plus propre que la realite passerait les
 * tests puis laisserait des asterisques a l'ecran.
 */
const REPONSE = [
  "Voici le point sur le projet **KAN** :",
  "",
  "### 1. Contexte",
  "Le projet **KIOSQUE K20** concerne la gestion des frais.",
  "",
  "* **KAN-39 :** suivi de projet",
  "* **KAN-40 :** test, au statut **À faire**",
  "",
  "---",
].join("\n");

describe("inlineSpans", () => {
  it("reconnait le gras, qui est le cas le plus frequent", () => {
    expect(inlineSpans("le projet **KAN** avance")).toEqual([
      { kind: "text", text: "le projet " },
      { kind: "strong", text: "KAN" },
      { kind: "text", text: " avance" },
    ]);
  });

  it("ne prend pas une puce pour une italique", () => {
    // "* KAN-39" est une puce, pas le debut d'une emphase. La confusion ferait
    // disparaitre l'asterisque et collerait deux lignes de liste.
    const spans = inlineSpans("un * isole reste du texte");
    expect(spans).toEqual([{ kind: "text", text: "un * isole reste du texte" }]);
  });

  it("laisse en texte un marqueur jamais referme", () => {
    // Le masquer ferait disparaitre un caractere que la personne a sous les yeux.
    expect(inlineSpans("**jamais ferme")).toEqual([
      { kind: "text", text: "**jamais ferme" },
    ]);
  });

  it("rend le code et les liens http", () => {
    expect(inlineSpans("voir `KAN-1` et [la page](https://exemple.test/p)")).toEqual([
      { kind: "text", text: "voir " },
      { kind: "code", text: "KAN-1" },
      { kind: "text", text: " et " },
      { kind: "link", text: "la page", href: "https://exemple.test/p" },
    ]);
  });

  it("refuse de rendre cliquable un lien qui n'est pas http", () => {
    // Le texte vient d'un modele de langage. Un "javascript:" cliquable serait une
    // porte ouverte ; le supprimer cacherait ce qu'il a ecrit.
    const spans = inlineSpans("[clique](javascript:alert(1))");

    expect(spans.some((s) => s.kind === "link")).toBe(false);
    // Rendu en texte, cible comprise : la personne voit ce que le modele a ecrit.
    // La cible est recopiee jusqu'a sa premiere parenthese fermante, ce qui suffit
    // ici -- la propriete qui compte est qu'aucun lien ne soit cliquable.
    expect(spans[0].kind).toBe("text");
    expect(spans[0].kind === "text" && spans[0].text).toContain("javascript:");
  });
});

describe("parseBlocks", () => {
  it("separe titres, paragraphes et listes", () => {
    const blocks = parseBlocks(REPONSE);

    expect(blocks.map((b) => b.kind)).toEqual([
      "paragraph",
      "heading",
      "paragraph",
      "list",
      "rule",
    ]);
  });

  it("regroupe les puces consecutives en une seule liste", () => {
    const blocks = parseBlocks(REPONSE);
    const liste = blocks.find((b) => b.kind === "list");

    expect(liste).toBeDefined();
    expect(liste!.kind === "list" && liste!.items).toHaveLength(2);
  });

  it("distingue une liste numerotee d'une liste a puces", () => {
    const blocks = parseBlocks(["1. un", "2. deux"].join("\n"));

    expect(blocks[0].kind === "list" && blocks[0].ordered).toBe(true);
  });

  it("rend un tableau au meme analyseur que le cahier des charges", () => {
    // Deux lectures differentes du meme format finiraient par diverger.
    const blocks = parseBlocks(["| A | B |", "| --- | --- |", "| un | deux |"].join("\n"));

    expect(blocks[0].kind).toBe("table");
    expect(blocks[0].kind === "table" && blocks[0].table.rows).toEqual([["un", "deux"]]);
  });

  it("ne perd jamais une reponse qu'il ne reconnait pas", () => {
    // Une reponse disparue serait pire que des asterisques a l'ecran.
    const blocks = parseBlocks("Juste une phrase, sans aucune mise en forme.");

    expect(blocks).toHaveLength(1);
    expect(blocks[0].kind).toBe("paragraph");
  });

  it("ne rend rien pour un texte vide", () => {
    expect(parseBlocks("")).toEqual([]);
  });
});
