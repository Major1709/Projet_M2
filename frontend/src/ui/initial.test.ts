import { describe, expect, it } from "vitest";

import { NEUTRAL_INITIAL, initialOf } from "./initial";

describe("initialOf", () => {
  it("rend la premiere lettre du nom, en majuscule", () => {
    expect(initialOf("Fanny Andrianaly")).toBe("F");
  });

  it("garde l'accent, qui fait partie de l'initiale", () => {
    // Replier en "E" corrigerait un nom que personne n'a ecrit ainsi.
    expect(initialOf("elodie")).toBe("E");
    expect(initialOf("Élodie")).toBe("É");
  });

  it("ignore ce qui precede la premiere lettre", () => {
    expect(initialOf("  Fanny")).toBe("F");
    expect(initialOf("(Fanny)")).toBe("F");
  });

  it("retombe sur une pastille neutre quand aucun nom n'est connu", () => {
    // Les deux cas ou l'ecran ne doit rien inventer : nom absent, session ouverte
    // avant que le nom soit conserve.
    expect(initialOf(null)).toBe(NEUTRAL_INITIAL);
    expect(initialOf(undefined)).toBe(NEUTRAL_INITIAL);
    expect(initialOf("")).toBe(NEUTRAL_INITIAL);
  });

  it("retombe sur la pastille neutre quand le nom n'a aucune lettre", () => {
    // Une pastille muette ne se distinguerait pas d'un defaut d'affichage.
    expect(initialOf("   ")).toBe(NEUTRAL_INITIAL);
    expect(initialOf("!!!")).toBe(NEUTRAL_INITIAL);
  });

  it("ne coupe pas un caractere en deux", () => {
    // Un prenom peut commencer par un point de code hors du plan de base ; le lire
    // par indice en rendrait la moitie, et le navigateur afficherait un losange.
    expect(initialOf("𝒜nne")).toBe("𝒜");
  });
});
