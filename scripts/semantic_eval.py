"""Mesure ce que le rapprochement semantique apporte, contre une reference lexicale.

POURQUOI UNE REFERENCE, ET PAS SEULEMENT UN CHIFFRE
---------------------------------------------------
Un rappel de 0,86 ne veut rien dire seul. La question n'est pas "le modele
trouve-t-il les doublons" mais "les trouve-t-il la ou une simple comparaison de
mots echoue". Ce script mesure donc deux systemes sur les memes donnees :

* une reference lexicale TF-IDF, sans modele ni dependance ;
* le modele multilingual-e5-base.

L'ecart entre les deux est le resultat. Le chiffre absolu ne l'est pas.

LE CORPUS EST LU DU CSV, PAS DE JIRA
------------------------------------
Volontaire. Une mesure doit etre rejouable a l'identique : passer par Jira la
ferait dependre d'un jeton, du reseau, et de l'etat d'un projet que quelqu'un
peut editer entre deux executions. Le CSV est la meme source que celle importee,
et le registre d'import donne la cle Jira reelle de chaque graine, ce qui rend
les resultats actionnables sans rendre la mesure fragile.

Usage :
    python scripts/semantic_eval.py
    python scripts/semantic_eval.py --lexical-only   # sans charger de modele
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "backend"))

from app.semantics.adapters.memory import (  # noqa: E402
    InMemoryEmbeddingStore,
    cosine_distance,
)
from app.semantics.domain import IndexableDocument  # noqa: E402
from app.semantics.workflow import SemanticIndex  # noqa: E402

EVALUATION = RACINE / "data" / "evaluation"
CORPUS = EVALUATION / "jira_seed_tickets.csv"
PAIRES = EVALUATION / "semantic_pairs_gold.csv"
REQUETES = EVALUATION / "retrieval_queries_gold.csv"
REGISTRE = EVALUATION / "jira_import_ledger.json"
RAPPORT = EVALUATION / "resultats_evaluation.json"
SITE = "https://andrianalyfanny.atlassian.net"
RANGS = (1, 3, 5)


# --------------------------------------------------------------------------- #
# Reference lexicale
# --------------------------------------------------------------------------- #

MOT = re.compile(r"\w+", re.UNICODE)


def _mots(texte: str) -> list[str]:
    return MOT.findall(texte.lower())


class ReferenceLexicale:
    """TF-IDF et cosinus, sans dependance ni modele.

    Ce n'est pas un homme de paille : sur un corpus ou les doublons partagent
    leur vocabulaire, TF-IDF est difficile a battre. Il n'echoue precisement que
    la ou ce projet prétend apporter quelque chose -- deux formulations d'un meme
    incident sans mot commun -- et il se fait piéger la ou les faux amis
    partagent un mot saillant. C'est ce contraste qui rend la mesure lisible.
    """

    nom = "TF-IDF (reference lexicale)"

    def __init__(self, documents: Sequence[IndexableDocument]) -> None:
        self._documents = list(documents)
        frequences: Counter[str] = Counter()
        self._sacs: list[Counter[str]] = []
        for document in self._documents:
            sac = Counter(_mots(document.embeddable_text()))
            self._sacs.append(sac)
            frequences.update(sac.keys())
        total = len(self._documents)
        self._idf = {
            mot: math.log((total + 1) / (compte + 1)) + 1.0
            for mot, compte in frequences.items()
        }
        self._vecteurs = [self._vectoriser(sac) for sac in self._sacs]

    def _vectoriser(self, sac: Counter[str]) -> dict[str, float]:
        vecteur = {mot: compte * self._idf.get(mot, 0.0) for mot, compte in sac.items()}
        norme = math.sqrt(sum(valeur * valeur for valeur in vecteur.values())) or 1.0
        return {mot: valeur / norme for mot, valeur in vecteur.items()}

    def _distance(self, gauche: dict[str, float], droite: dict[str, float]) -> float:
        commun = gauche.keys() & droite.keys()
        return 1.0 - sum(gauche[mot] * droite[mot] for mot in commun)

    def _classer(self, requete: dict[str, float], exclure: str | None) -> list[tuple[str, float]]:
        scores = [
            (document.external_id, self._distance(requete, vecteur))
            for document, vecteur in zip(self._documents, self._vecteurs, strict=True)
            if document.external_id != exclure
        ]
        return sorted(scores, key=lambda couple: couple[1])

    def rechercher(self, question: str) -> list[tuple[str, float]]:
        return self._classer(self._vectoriser(Counter(_mots(question))), None)

    def voisins(self, external_id: str) -> list[tuple[str, float]]:
        position = next(
            index
            for index, document in enumerate(self._documents)
            if document.external_id == external_id
        )
        return self._classer(self._vecteurs[position], external_id)


class SystemeSemantique:
    """Le modele reel, derriere le meme protocole de mesure."""

    def __init__(self, documents: Sequence[IndexableDocument], modele: str) -> None:
        from app.semantics.adapters.local_model import LocalEmbeddingProvider

        self._provider = LocalEmbeddingProvider(modele)
        self.nom = f"Embeddings {modele}"
        self._index = SemanticIndex(provider=self._provider, store=InMemoryEmbeddingStore())
        self._documents = {document.external_id: document for document in documents}
        print(f"  chargement du modele {modele} ...", flush=True)
        self._index.index("evaluation", documents)
        self._vecteurs = {
            document.external_id: vecteur
            for document, vecteur in zip(
                documents,
                self._provider.embed(
                    [document.embeddable_text() for document in documents], kind="passage"
                ),
                strict=True,
            )
        }

    def _classer(self, vecteur: Sequence[float], exclure: str | None) -> list[tuple[str, float]]:
        scores = [
            (external_id, cosine_distance(vecteur, autre))
            for external_id, autre in self._vecteurs.items()
            if external_id != exclure
        ]
        return sorted(scores, key=lambda couple: couple[1])

    def rechercher(self, question: str) -> list[tuple[str, float]]:
        return self._classer(self._provider.embed([question], kind="query")[0], None)

    def voisins(self, external_id: str) -> list[tuple[str, float]]:
        return self._classer(self._vecteurs[external_id], external_id)


# --------------------------------------------------------------------------- #
# Chargement
# --------------------------------------------------------------------------- #


def charger_le_corpus() -> list[IndexableDocument]:
    registre = json.loads(REGISTRE.read_text(encoding="utf-8")) if REGISTRE.exists() else {}
    documents = []
    with CORPUS.open(encoding="utf-8") as fichier:
        for ligne in csv.DictReader(fichier):
            cle = registre.get(ligne["Id"])
            documents.append(
                IndexableDocument(
                    source_system="jira",
                    # L'identifiant de graine, pas la cle Jira : c'est lui que les
                    # fichiers de reference nomment. La cle reelle voyage a cote,
                    # pour que le rapport reste actionnable.
                    external_id=ligne["Id"],
                    title=ligne["Summary"],
                    body=ligne["Description"],
                    resource_reference=f"{SITE}/browse/{cle}" if cle else None,
                )
            )
    return documents


def _lignes(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8") as fichier:
        return list(csv.DictReader(fichier))


# --------------------------------------------------------------------------- #
# Mesures
# --------------------------------------------------------------------------- #


def _rang(classement: Sequence[tuple[str, float]], attendus: set[str]) -> int | None:
    for position, (external_id, _) in enumerate(classement, start=1):
        if external_id in attendus:
            return position
    return None


def mesurer_les_doublons(systeme: Any, paires: list[dict[str, str]]) -> dict[str, Any]:
    """Retrouve-t-on le jumeau d'un ticket, et les faux amis passent-ils devant ?"""

    doublons = [p for p in paires if p["relation"] == "duplicate"]
    rangs: list[int] = []
    manques: list[str] = []
    for paire in doublons:
        classement = systeme.voisins(paire["ticket_a"])
        rang = _rang(classement, {paire["ticket_b"]})
        if rang is None:
            manques.append(f"{paire['ticket_a']}~{paire['ticket_b']}")
            continue
        rangs.append(rang)

    # Le controle qui compte vraiment : un faux ami lexical arrive-t-il devant le
    # vrai jumeau ? Un rappel eleve assorti de faux amis mieux classes decrirait
    # un systeme qui trouve la bonne reponse et propose la mauvaise en premier.
    pieges = [p for p in paires if p["relation"] == "unrelated"]
    inversions = []
    for piege in pieges:
        a, leurre = piege["ticket_a"], piege["ticket_b"]
        jumeau = next(
            (p["ticket_b"] for p in doublons if p["ticket_a"] == a),
            None,
        )
        if jumeau is None:
            continue
        classement = dict(systeme.voisins(a))
        if classement.get(leurre, 1.0) < classement.get(jumeau, 1.0):
            inversions.append(f"{a}: {leurre} devant {jumeau}")

    return {
        "paires": len(doublons),
        **{
            f"rappel@{k}": round(sum(1 for r in rangs if r <= k) / len(doublons), 3)
            for k in RANGS
        },
        "mrr": round(sum(1 / r for r in rangs) / len(doublons), 3) if doublons else 0.0,
        "jumeaux_introuvables": manques,
        "faux_amis_devant_le_jumeau": inversions,
    }


def mesurer_les_requetes(systeme: Any, requetes: list[dict[str, str]]) -> dict[str, Any]:
    rangs: list[int] = []
    manques: list[str] = []
    pieges_en_tete: list[str] = []
    for requete in requetes:
        attendus = {t for t in requete["expected_ticket_ids"].split(";") if t}
        classement = systeme.rechercher(requete["query"])
        rang = _rang(classement, attendus)
        if rang is None:
            manques.append(requete["query_id"])
        else:
            rangs.append(rang)
        leurres = {t for t in (requete.get("piege_attendu") or "").split(";") if t}
        if leurres and classement and classement[0][0] in leurres:
            pieges_en_tete.append(f"{requete['query_id']}: {classement[0][0]}")
    total = len(requetes)
    return {
        "requetes": total,
        **{
            f"rappel@{k}": round(sum(1 for r in rangs if r <= k) / total, 3) for k in RANGS
        },
        "mrr": round(sum(1 / r for r in rangs) / total, 3) if total else 0.0,
        "sans_reponse_attendue": manques,
        "pieges_classes_premiers": pieges_en_tete,
    }


def evaluer(systeme: Any, paires, requetes) -> dict[str, Any]:
    return {
        "systeme": systeme.nom,
        "doublons": mesurer_les_doublons(systeme, paires),
        "requetes": mesurer_les_requetes(systeme, requetes),
    }


def afficher(resultat: dict[str, Any]) -> None:
    print(f"\n{resultat['systeme']}")
    for section, titre in (("doublons", "Doublons"), ("requetes", "Requetes")):
        bloc = resultat[section]
        rappels = "  ".join(f"@{k} {bloc[f'rappel@{k}']:.3f}" for k in RANGS)
        print(f"  {titre:9} rappel {rappels}   MRR {bloc['mrr']:.3f}")
    fautes = resultat["doublons"]["faux_amis_devant_le_jumeau"]
    print(f"  Faux amis classes devant le vrai jumeau : {len(fautes)}")
    for faute in fautes:
        print(f"      {faute}")
    pieges = resultat["requetes"]["pieges_classes_premiers"]
    print(f"  Pieges classes premiers : {len(pieges)}")
    for piege in pieges:
        print(f"      {piege}")


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Evaluation du rapprochement semantique.")
    analyseur.add_argument(
        "--lexical-only",
        action="store_true",
        help="Ne mesurer que la reference lexicale, sans charger de modele.",
    )
    analyseur.add_argument("--modele", default="intfloat/multilingual-e5-base")
    arguments = analyseur.parse_args()

    documents = charger_le_corpus()
    paires = _lignes(PAIRES)
    requetes = _lignes(REQUETES)
    print(f"Corpus  : {len(documents)} tickets")
    print(f"Paires  : {len(paires)} | Requetes : {len(requetes)}")

    resultats = [evaluer(ReferenceLexicale(documents), paires, requetes)]
    if not arguments.lexical_only:
        resultats.append(evaluer(SystemeSemantique(documents, arguments.modele), paires, requetes))

    for resultat in resultats:
        afficher(resultat)

    if len(resultats) == 2:
        print("\nEcart (semantique - lexical)")
        for section, titre in (("doublons", "Doublons"), ("requetes", "Requetes")):
            for k in RANGS:
                cle = f"rappel@{k}"
                ecart = resultats[1][section][cle] - resultats[0][section][cle]
                print(f"  {titre:9} {cle:9} {ecart:+.3f}")

    RAPPORT.write_text(
        json.dumps({"resultats": resultats}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nRapport ecrit : {RAPPORT.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
