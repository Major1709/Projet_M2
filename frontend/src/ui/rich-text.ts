/**
 * Lire la mise en forme que NEXIA écrit, pour l'afficher au lieu de la montrer.
 *
 * Le modèle répond en markdown — c'est ce que font tous les modèles, et rien ne le
 * lui demande. La bulle affichait ce texte brut, donc un mot mis en gras arrivait
 * à l'écran entouré de deux astérisques, et un titre précédé de trois dièses.
 *
 * Ce module ne reconnaît que ce que NEXIA produit réellement, relevé sur ses
 * réponses : des titres, des listes, du gras, du code, des liens, des tableaux. Un
 * analyseur markdown complet serait plus impressionnant et couvrirait des cas que
 * rien n'émet ici — en échange d'une surface que personne ne relirait, sur du texte
 * qui vient d'un modèle de langage.
 *
 * Rien ici ne produit de HTML : ce sont des structures, que le composant rend en
 * éléments React. Le texte reste donc du texte, et une réponse qui contiendrait une
 * balise l'afficherait au lieu de l'exécuter.
 */

import { parseMarkdownTable, type MarkdownTable } from "./markdown-table";

export type Span =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "emphasis"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string };

export type Block =
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "heading"; level: 1 | 2 | 3; spans: Span[] }
  | { kind: "list"; ordered: boolean; items: Span[][] }
  | { kind: "table"; table: MarkdownTable }
  | { kind: "rule" };

/** Les seuls protocoles rendus cliquables. */
const SAFE_LINK = /^https?:\/\//i;

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const RULE = /^\s*([-*_])\s*(\1\s*){2,}$/;

/**
 * Découper une ligne en fragments de mise en forme.
 *
 * Un seul passage, de gauche à droite : les marqueurs ne s'imbriquent pas ici parce
 * que NEXIA ne les imbrique pas. Un marqueur jamais refermé reste du texte, ce qui
 * est la seule issue honnête — le masquer ferait disparaître un caractère que la
 * personne a sous les yeux.
 */
export function inlineSpans(line: string): Span[] {
  const spans: Span[] = [];
  let reste = line;

  // L'ordre compte : le gras avant l'italique, sinon "**mot**" serait lu comme deux
  // italiques vides encadrant un mot.
  const motifs: Array<{ re: RegExp; make: (m: RegExpMatchArray) => Span }> = [
    { re: /\*\*([^*]+)\*\*/, make: (m) => ({ kind: "strong", text: m[1] }) },
    { re: /__([^_]+)__/, make: (m) => ({ kind: "strong", text: m[1] }) },
    { re: /`([^`]+)`/, make: (m) => ({ kind: "code", text: m[1] }) },
    {
      re: /\[([^\]]+)\]\(([^)\s]+)\)/,
      make: (m) =>
        SAFE_LINK.test(m[2])
          ? { kind: "link", text: m[1], href: m[2] }
          : // Un lien dont le protocole n'est pas http(s) est rendu en texte. Le
            // contenu vient d'un modele : un "javascript:" cliquable serait une
            // porte ouverte, et le supprimer cacherait ce qu'il a ecrit.
            { kind: "text", text: `${m[1]} (${m[2]})` },
    },
    { re: /(?<![*\w])\*([^*]+)\*(?![*\w])/, make: (m) => ({ kind: "emphasis", text: m[1] }) },
  ];

  while (reste) {
    let premier: { index: number; longueur: number; span: Span } | null = null;
    for (const { re, make } of motifs) {
      const m = reste.match(re);
      if (m && m.index !== undefined && (premier === null || m.index < premier.index)) {
        premier = { index: m.index, longueur: m[0].length, span: make(m) };
      }
    }
    if (premier === null) {
      spans.push({ kind: "text", text: reste });
      break;
    }
    if (premier.index > 0) {
      spans.push({ kind: "text", text: reste.slice(0, premier.index) });
    }
    spans.push(premier.span);
    reste = reste.slice(premier.index + premier.longueur);
  }

  return spans.filter((span) => span.kind !== "text" || span.text !== "");
}

/**
 * Découper une réponse en blocs.
 *
 * Retourne toujours au moins un bloc quand le texte n'est pas vide : une réponse qui
 * disparaîtrait faute d'être reconnue serait pire que des astérisques à l'écran.
 */
export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraphe: string[] = [];

  function cloreParagraphe() {
    if (paragraphe.length === 0) return;
    blocks.push({ kind: "paragraph", spans: inlineSpans(paragraphe.join(" ").trim()) });
    paragraphe = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const ligne = lines[index];

    // Le tableau est confie a l'analyseur qui le lisait deja pour le cahier des
    // charges. Deux lectures differentes du meme format finiraient par diverger.
    if (ligne.trimStart().startsWith("|")) {
      const fin = (() => {
        let dernier = index;
        while (dernier + 1 < lines.length && lines[dernier + 1].trimStart().startsWith("|")) {
          dernier += 1;
        }
        return dernier;
      })();
      const table = parseMarkdownTable(lines.slice(index, fin + 1).join("\n"));
      if (table) {
        cloreParagraphe();
        blocks.push({ kind: "table", table });
        index = fin;
        continue;
      }
    }

    if (!ligne.trim()) {
      cloreParagraphe();
      continue;
    }

    if (RULE.test(ligne)) {
      cloreParagraphe();
      blocks.push({ kind: "rule" });
      continue;
    }

    const titre = ligne.match(HEADING);
    if (titre) {
      cloreParagraphe();
      // Trois niveaux suffisent, et au-dela tout retombe au plus petit : une bulle
      // de conversation n'est pas un document, et six tailles de titre y seraient
      // illisibles.
      const niveau = Math.min(titre[1].length, 3) as 1 | 2 | 3;
      blocks.push({ kind: "heading", level: niveau, spans: inlineSpans(titre[2].trim()) });
      continue;
    }

    const puce = ligne.match(BULLET);
    const numero = ligne.match(NUMBERED);
    if (puce || numero) {
      cloreParagraphe();
      const ordonnee = numero !== null;
      const texte = (puce ?? numero)![1];
      const dernier = blocks[blocks.length - 1];
      if (dernier && dernier.kind === "list" && dernier.ordered === ordonnee) {
        dernier.items.push(inlineSpans(texte));
      } else {
        blocks.push({ kind: "list", ordered: ordonnee, items: [inlineSpans(texte)] });
      }
      continue;
    }

    paragraphe.push(ligne.trim());
  }

  cloreParagraphe();
  return blocks;
}
