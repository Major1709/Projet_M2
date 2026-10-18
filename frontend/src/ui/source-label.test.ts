import { describe, expect, it } from "vitest";

import { labelForTool } from "./source-label";

describe("labelForTool", () => {
  it("traduit les outils que NEXIA utilise", () => {
    // Releve a l'ecran : "searchJiraIssuesUsingJql" dit comment la lecture a ete
    // faite, jamais ce qui a ete lu, et il est ecrit pour une machine.
    expect(labelForTool("searchJiraIssuesUsingJql")).toBe("Recherche Jira");
    expect(labelForTool("getConfluencePage")).toBe("Page Confluence");
    expect(labelForTool("extractFigmaProcess")).toBe("Processus Figma");
  });

  it("garde le nom d'un outil inconnu plutot que de l'effacer", () => {
    // Le jour ou le registre en ajoute un, mieux vaut une source au nom technique
    // qu'une source appelee "Autre", qui ne dirait rien du tout.
    expect(labelForTool("getSomethingNew")).toBe("getSomethingNew");
  });
});
