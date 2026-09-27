/**
 * L'initiale d'une personne, pour la pastille qui la représente.
 *
 * L'avatar affichait un « U » en dur, le même pour tout le monde. Une initiale ne
 * dit pas grand-chose, mais elle dit au moins *qui* est connecté — ce qui compte sur
 * un outil qui écrit dans Jira et Confluence au nom de cette personne.
 */

/** Ce qu'affiche la pastille quand aucun nom n'est connu. « U » pour utilisateur. */
export const NEUTRAL_INITIAL = "U";

export function initialOf(name: string | null | undefined): string {
  if (!name) return NEUTRAL_INITIAL;
  // Parcouru par points de code et non par indices : le premier « caractère » d'un
  // prénom peut tenir sur deux unités UTF-16, et `name[0]` en rendrait la moitié.
  for (const caractere of name) {
    // Ponctuation et espaces de tête ignorés : un nom saisi « (Fanny) » donnerait
    // sinon une parenthèse, qui ne désigne personne.
    if (/\p{Letter}|\p{Number}/u.test(caractere)) {
      // Majuscule locale-agnostique. Les accents sont gardés : « É » est l'initiale
      // d'Élodie, et la replier en « E » corrigerait un nom que personne n'a écrit
      // ainsi.
      return caractere.toLocaleUpperCase();
    }
  }
  return NEUTRAL_INITIAL;
}
