import { describe, expect, it } from "vitest";

import { formatMarkdownTable, opensABlock, parseMarkdownTable } from "./markdown-table";

/**
 * Le corps réellement proposé par NEXIA, relevé plutôt qu'inventé : sept colonnes,
 * une ligne d'ouverture de bloc et sa continuation aux trois premières cellules
 * vides. Un double plus propre que la réalité passerait les tests puis échouerait à
 * l'écran.
 */
const CORPS = [
  "| Bloc fonctionnel | Ref. PBS | Userstory | Description | Criteres d'acceptation - Contexte | Criteres d'acceptation - Scenario | Remarques |",
  "| --- | --- | --- | --- | --- | --- | --- |",
  "| Authentification | | En tant qu'utilisateur, je souhaite m'authentifier. | Ouvre l'application. | Etant donne que l'ecran de connexion est affiche | Lorsque l'utilisateur valide Alors l'accueil s'affiche | Si iOS : Face ID |",
  "| | | | | Etant donne que l'utilisateur est authentifie | Lorsqu'il ouvre le menu Alors les virements s'affichent | |",
].join("\n");

describe("parseMarkdownTable", () => {
  it("rend les sept colonnes dans l'ordre", () => {
    const table = parseMarkdownTable(CORPS);

    expect(table?.headers).toEqual([
      "Bloc fonctionnel",
      "Ref. PBS",
      "Userstory",
      "Description",
      "Criteres d'acceptation - Contexte",
      "Criteres d'acceptation - Scenario",
      "Remarques",
    ]);
  });

  it("garde les lignes et leurs cellules vides", () => {
    const table = parseMarkdownTable(CORPS);

    expect(table?.rows).toHaveLength(2);
    expect(table?.rows[0][0]).toBe("Authentification");
    // Ref. PBS est laissée vide par construction : la référence est attribuée par
    // l'équipe, et en inventer une créerait un renvoi vers un élément inexistant.
    expect(table?.rows[0][1]).toBe("");
    expect(table?.rows[1].slice(0, 4)).toEqual(["", "", "", ""]);
  });

  it("ne rend rien quand le texte ne contient pas de tableau", () => {
    // Le cas qui compte : l'appelant doit pouvoir retomber sur le texte brut.
    expect(parseMarkdownTable("Voici un cahier des charges en prose.")).toBeNull();
  });

  it("ne prend pas une ligne isolée pour un tableau", () => {
    expect(parseMarkdownTable("| pas de separation dessous |")).toBeNull();
  });

  it("complete une ligne trop courte au lieu de la perdre", () => {
    // Elle vient d'un modèle. Laisser tomber la ligne entière ferait disparaître
    // une exigence sans que personne ne le voie.
    const table = parseMarkdownTable(
      ["| A | B | C |", "| --- | --- | --- |", "| seul |"].join("\n"),
    );

    expect(table?.rows).toEqual([["seul", "", ""]]);
  });

  it("ignore ce qui deborde d'une ligne trop longue", () => {
    const table = parseMarkdownTable(
      ["| A | B |", "| --- | --- |", "| un | deux | de trop |"].join("\n"),
    );

    expect(table?.rows).toEqual([["un", "deux"]]);
  });

  it("retient ce qui entoure le tableau", () => {
    // Rien ne devrait entourer le tableau, et c'est justement pour cela qu'il faut
    // le montrer quand il y en a : un relecteur doit voir ce qu'il approuve, y
    // compris ce que la consigne interdisait.
    const table = parseMarkdownTable(
      ["Introduction interdite.", "| A |", "| --- |", "| un |", "Et une conclusion."].join("\n"),
    );

    expect(table?.before).toBe("Introduction interdite.");
    expect(table?.after).toBe("Et une conclusion.");
  });

  it("accepte les separations alignees", () => {
    const table = parseMarkdownTable(["| A | B |", "|:--- | ---:|", "| un | deux |"].join("\n"));

    expect(table?.rows).toEqual([["un", "deux"]]);
  });

  it("accepte les fins de ligne Windows", () => {
    const table = parseMarkdownTable("| A |\r\n| --- |\r\n| un |");

    expect(table?.rows).toEqual([["un"]]);
  });
});

describe("opensABlock", () => {
  it("distingue une ouverture de bloc de sa continuation", () => {
    const table = parseMarkdownTable(CORPS);

    expect(opensABlock(table!.rows[0])).toBe(true);
    expect(opensABlock(table!.rows[1])).toBe(false);
  });
});

describe("formatMarkdownTable", () => {
  it("refait un tableau que parseMarkdownTable relit a l'identique", () => {
    const table = parseMarkdownTable(CORPS)!;

    const relu = parseMarkdownTable(formatMarkdownTable(table.headers, table.rows))!;

    expect(relu.headers).toEqual(table.headers);
    expect(relu.rows).toEqual(table.rows);
  });

  it("echappe une barre verticale tapee dans une cellule", () => {
    // Sans cela, un caractere saisi par un relecteur couperait la ligne en deux et
    // decalerait toutes les colonnes suivantes.
    const rendu = formatMarkdownTable(["A", "B"], [["oui | non", "x"]]);

    // Echappee sur la ligne, relue telle qu'elle a ete tapee : l'echappement est
    // une affaire de transport, pas de contenu.
    expect(rendu.split("\n")[2]).toContain("oui \\| non");
    expect(parseMarkdownTable(rendu)?.rows).toEqual([["oui | non", "x"]]);
  });

  it("replie un retour a la ligne, qui ne tient pas dans une cellule", () => {
    const rendu = formatMarkdownTable(["A"], [["deux\nlignes"]]);

    expect(rendu.split("\n")).toHaveLength(3);
    expect(parseMarkdownTable(rendu)?.rows).toEqual([["deux lignes"]]);
  });

  it("garde les cellules vides, qui rattachent une ligne a son bloc", () => {
    const rendu = formatMarkdownTable(["A", "B", "C"], [["", "", "suite"]]);

    expect(parseMarkdownTable(rendu)?.rows).toEqual([["", "", "suite"]]);
  });
});
