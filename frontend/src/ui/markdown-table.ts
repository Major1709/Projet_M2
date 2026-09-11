/**
 * Lire un tableau markdown, pour le montrer comme Confluence le rendra.
 *
 * Le corps d'un cahier des charges part en markdown vers Confluence, mais l'aperçu
 * d'approbation l'affichait comme du texte brut : sept colonnes de barres verticales
 * qu'aucun relecteur ne peut relire. Approuver ce qu'on ne peut pas lire n'est pas
 * approuver.
 *
 * Ce module ne rend rien : il retourne des lignes et des cellules, et laisse le
 * composant décider de l'affichage. C'est ce qui permet de le tester sans DOM.
 *
 * Il ne prétend pas lire tout markdown — seulement un tableau à barres verticales,
 * qui est exactement ce que NEXIA produit. Un analyseur générique serait plus
 * impressionnant et couvrirait des cas que rien n'émet ici.
 */

export type MarkdownTable = {
  headers: string[];
  /** Une ligne par scénario ; ses cellules sont dans l'ordre des en-têtes. */
  rows: string[][];
  /** Ce qui précède ou suit le tableau, s'il y en a. Vide en temps normal. */
  before: string;
  after: string;
};

/** Une ligne faite de tirets et de barres : la séparation sous l'en-tête. */
const SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function isTableLine(line: string): boolean {
  return line.trimStart().startsWith("|");
}

function cellsOf(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map((cell) => cell.trim());
}

/**
 * Retourne le tableau trouvé, ou `null` si le texte n'en contient pas.
 *
 * `null` plutôt qu'un tableau vide : l'appelant doit pouvoir retomber sur le texte
 * brut, et un tableau à zéro ligne ne se distinguerait pas d'un tableau dont toutes
 * les lignes ont été perdues.
 */
export function parseMarkdownTable(source: string): MarkdownTable | null {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const start = lines.findIndex(
    (line, index) =>
      isTableLine(line) && index + 1 < lines.length && SEPARATOR.test(lines[index + 1]),
  );
  if (start === -1) return null;

  const headers = cellsOf(lines[start]);
  const rows: string[][] = [];
  let end = start + 2;
  for (; end < lines.length; end += 1) {
    const line = lines[end];
    if (!isTableLine(line)) break;
    if (SEPARATOR.test(line)) continue;
    const cells = cellsOf(line);
    // Ajusté sur l'en-tête plutôt que refusé. Une ligne trop courte viendrait d'un
    // modèle, et laisser tomber la ligne entière ferait disparaître une exigence
    // sans que personne ne le voie -- exactement ce que cet aperçu doit empêcher.
    while (cells.length < headers.length) cells.push("");
    rows.push(cells.slice(0, headers.length));
  }

  return {
    headers,
    rows,
    before: lines.slice(0, start).join("\n").trim(),
    after: lines.slice(end).join("\n").trim(),
  };
}

/**
 * La ligne ouvre-t-elle un bloc, ou continue-t-elle celui du dessus ?
 *
 * NEXIA laisse les trois premières cellules vides sur une ligne de continuation,
 * ce qui reproduit les cellules fusionnées de la page de l'équipe. Le savoir permet
 * de le montrer à l'écran plutôt que d'afficher trois trous que le relecteur
 * prendrait pour un oubli.
 */
export function opensABlock(row: string[]): boolean {
  return (row[0] ?? "") !== "";
}
