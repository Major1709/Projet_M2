"""Cree dans Jira les tickets synthetiques du jeu d'evaluation.

POURQUOI CE SCRIPT VIT EN DEHORS DU BACKEND
-------------------------------------------
Le pipeline MCP refuse toute mutation, et ce refus est leve a la construction :
``PKA_MCP_MUTATIONS_ENABLED`` ne peut pas valoir vrai. Ce n'est pas une lacune a
contourner, c'est la propriete centrale du systeme -- un assistant qui lit ne
doit pas pouvoir ecrire parce qu'un modele l'a decide.

Amorcer un corpus d'evaluation est une ecriture, mais ce n'est pas l'assistant
qui la demande : c'est un operateur humain, une fois, avec un fichier sous les
yeux. La distinction est reelle, et elle se traduit par un script separe plutot
que par un assouplissement du pipeline. Rien ici n'est importe par le backend et
rien dans le backend n'importe ceci.

CE QU'IL FAIT
-------------
Lit ``data/evaluation/jira_seed_tickets.csv`` et cree un ticket par ligne dans
le projet indique. Sans ``--execute`` il n'ecrit rien : il verifie, compare, et
affiche ce qu'il ferait.

QUEL IDENTIFIANT, ET POURQUOI PAS CELUI DE L'ASSISTANT
------------------------------------------------------
Ce script s'authentifie avec un jeton d'API personnel, et non avec le grant
OAuth de NEXIA. Deux raisons, et la seconde est la vraie.

D'abord parce que le document de credentials MCP ne conviendrait pas : son jeton
est emis par ``mcp.atlassian.com`` pour son propre service, et ``api.atlassian.com``
le refuse.

Surtout, creer un ticket demande ``write:jira-work``. Accorder cette portee a
l'application NEXIA pour amorcer un corpus la lui laisserait ensuite pour
toujours, et le refus de mutation du pipeline ne serait plus qu'une politique
logicielle par-dessus une permission bien reelle. Un jeton personnel garde
l'ecriture du cote de l'humain qui la demande, et l'application de l'assistant
en lecture seule.

IDEMPOTENCE
-----------
Un registre local associe chaque identifiant de graine a la cle Jira creee. Une
relance ne recree pas ce qui figure deja au registre. C'est necessaire : les
identifiants de graine n'apparaissent volontairement ni dans les titres ni dans
les descriptions -- les y mettre fausserait l'evaluation en offrant au moteur un
indice que les vraies donnees n'ont pas -- donc rien dans Jira ne permet de
reconnaitre un ticket deja importe.

Usage :
    python scripts/jira_seed_import.py --projet KAN --courriel <adresse>
    python scripts/jira_seed_import.py --projet KAN --courriel <adresse> --execute

Prerequis : deposer un jeton d'API dans ``infra/secrets/dev/jira_api_token``,
cree depuis https://id.atlassian.com/manage-profile/security/api-tokens.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
CORPUS = RACINE / "data" / "evaluation" / "jira_seed_tickets.csv"
REGISTRE = RACINE / "data" / "evaluation" / "jira_import_ledger.json"
JETON = RACINE / "infra" / "secrets" / "dev" / "jira_api_token"
API = "{site}/rest/api/3"
# Une pause entre deux creations. Trente ecritures d'affilee sur un site gratuit
# est exactement le profil qu'une limite de debit sanctionne, et une limite
# atteinte au quinzieme ticket laisse le corpus a moitie importe.
PAUSE_SECONDES = 0.7
# Jira traduit le nom de ses types standards selon la langue du site, et l'API
# les expose traduits. Le corpus, lui, est ecrit une fois : il nomme les types en
# anglais, et c'est ici qu'on retrouve le nom que ce site-ci emploie.
#
# La table ne traduit rien d'autre. Un type propre au projet doit porter dans le
# corpus le nom exact qu'il a dans Jira -- deviner une equivalence sur un type
# metier reviendrait a classer des tickets d'apres une ressemblance de mots.
ALIAS_TYPES: dict[str, tuple[str, ...]] = {
    "Task": ("Task", "Tâche"),
    "Bug": ("Bug", "Bogue"),
    "Story": ("Story", "Récit"),
    "Epic": ("Epic", "Épopée"),
    "Subtask": ("Subtask", "Sous-tâche"),
}


class ImportEchoue(RuntimeError):
    """Une erreur deja formulee pour un humain."""


def _appel(
    url: str,
    autorisation: str,
    *,
    methode: str = "GET",
    corps: dict[str, Any] | None = None,
) -> Any:
    donnees = json.dumps(corps).encode("utf-8") if corps is not None else None
    entetes = {
        "Authorization": autorisation,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    if donnees is not None:
        entetes["Content-Type"] = "application/json"
    requete = urllib.request.Request(url, data=donnees, method=methode, headers=entetes)
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            brut = reponse.read()
            return json.loads(brut) if brut else {}
    except urllib.error.HTTPError as erreur:
        # Le corps porte la raison du refus, jamais le jeton presente.
        detail = erreur.read().decode("utf-8", "replace")[:400]
        chemin = url.split("/rest/")[-1]
        raise ImportEchoue(f"{methode} {chemin} -> {erreur.code}\n  {detail}") from erreur
    except urllib.error.URLError as erreur:
        raise ImportEchoue(f"Reseau injoignable : {erreur.reason}") from erreur
    except OSError as erreur:
        # Un depassement de delai en lecture n'est pas une URLError et remontait
        # donc brut, en traceback, apres une requete deja partie. C'est le pire
        # cas : la creation a peut-etre abouti cote serveur sans que la reponse
        # revienne, et le registre local ignore alors une cle bien reelle. La
        # reconciliation par resume existe pour cette raison.
        raise ImportEchoue(f"Echange interrompu : {erreur}") from erreur


def _autorisation(courriel: str) -> str:
    """L'en-tete Basic attendu par l'API Jira, construit sans afficher le jeton.

    Le jeton n'est ni journalise, ni passe en argument de ligne de commande, ni
    place dans une URL : il est lu du fichier et ne quitte pas cet en-tete. Un
    argument aurait suffi a le laisser dans l'historique du shell et dans la
    liste des processus, ou n'importe quel compte de la machine peut le lire.
    """

    if not JETON.exists():
        raise ImportEchoue(
            f"Jeton d'API absent : {JETON}\n"
            "  Cree-le sur https://id.atlassian.com/manage-profile/security/api-tokens\n"
            "  puis colle-le seul dans ce fichier, avec un editeur de texte."
        )
    valeur = JETON.read_text(encoding="utf-8").strip()
    if not valeur:
        raise ImportEchoue(f"Le fichier {JETON} est vide.")
    if any(caractere.isspace() for caractere in valeur):
        # Un espace interne trahit un copier-coller ayant emporte autre chose que
        # le jeton, et le refus qui suivrait ne dirait que "401".
        raise ImportEchoue(f"Le fichier {JETON} contient un espace : il doit porter le jeton seul.")
    couple = base64.b64encode(f"{courriel}:{valeur}".encode()).decode("ascii")
    return f"Basic {couple}"


def _adf(texte: str) -> dict[str, Any]:
    """L'API v3 attend un document ADF, pas une chaine."""

    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": texte}]}],
    }


def _verifier_le_projet(
    autorisation: str,
    site: str,
    projet: str,
    lignes: list[dict[str, str]],
) -> dict[str, str]:
    """Confronter le corpus au projet, et rendre la traduction des types a employer.

    Un type ou une priorite absents ne se verraient sinon qu'a la premiere
    creation refusee, corpus deja a moitie importe.
    """

    base = API.format(site=site)
    meta = _appel(
        f"{base}/issue/createmeta?projectKeys={urllib.parse.quote(projet)}"
        "&expand=projects.issuetypes.fields",
        autorisation,
    )
    projets = meta.get("projects") or []
    if not projets:
        raise ImportEchoue(
            f"Le projet {projet} est introuvable, ou ce compte n'y cree pas de ticket."
        )
    disponibles = {t["name"] for t in projets[0].get("issuetypes", [])}
    traduction: dict[str, str] = {}
    introuvables: list[str] = []
    for demande in sorted({ligne["Issue Type"] for ligne in lignes}):
        trouve = next(
            (nom for nom in ALIAS_TYPES.get(demande, (demande,)) if nom in disponibles),
            None,
        )
        if trouve is None:
            introuvables.append(demande)
        else:
            traduction[demande] = trouve
    if introuvables:
        raise ImportEchoue(
            f"Types de ticket absents de {projet} : {introuvables}. "
            f"Disponibles : {sorted(disponibles)}"
        )
    for demande, employe in traduction.items():
        if demande != employe:
            print(f"  type {demande!r} -> {employe!r} (site en francais)")
    priorites = {p["name"] for p in _appel(f"{base}/priority", autorisation)}
    manquantes = {ligne["Priority"] for ligne in lignes} - priorites
    if manquantes:
        raise ImportEchoue(
            f"Priorites inconnues du site : {sorted(manquantes)}. "
            f"Disponibles : {sorted(priorites)}"
        )
    print(f"  projet {projet} : types et priorites conformes")
    return traduction


def _resumes_deja_presents(autorisation: str, site: str, projet: str) -> dict[str, str]:
    """Les resumes deja dans le projet, associes a leur cle.

    Le registre local ne suffit pas a garantir l'idempotence. Une creation dont
    la reponse n'arrive jamais -- delai depasse, connexion coupee -- a pu aboutir
    cote serveur : le ticket existe, le registre l'ignore, et une relance le
    creerait une seconde fois. Un doublon dans un corpus qui sert justement a
    mesurer la detection de doublons est le pire resultat possible ici.

    On interroge donc le projet avant d'ecrire, et on adopte ce qui existe deja.
    """

    base = API.format(site=site)
    jql = urllib.parse.quote(f'project = "{projet}" ORDER BY created ASC')
    presents: dict[str, str] = {}
    jeton_page: str | None = None
    while True:
        url = f"{base}/search/jql?jql={jql}&fields=summary&maxResults=100"
        if jeton_page:
            url += f"&nextPageToken={urllib.parse.quote(jeton_page)}"
        page = _appel(url, autorisation)
        for ticket in page.get("issues", []):
            resume = (ticket.get("fields") or {}).get("summary")
            if isinstance(resume, str):
                # Le premier gagne : si un doublon existe deja, on veut adopter
                # l'original plutot qu'en fabriquer un troisieme.
                presents.setdefault(resume, str(ticket["key"]))
        jeton_page = page.get("nextPageToken")
        if page.get("isLast", True) or not jeton_page:
            return presents


def _charger_le_registre() -> dict[str, str]:
    if not REGISTRE.exists():
        return {}
    return json.loads(REGISTRE.read_text(encoding="utf-8"))


def _ecrire_le_registre(registre: dict[str, str]) -> None:
    REGISTRE.write_text(
        json.dumps(registre, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    analyseur = argparse.ArgumentParser(description="Import du corpus d'evaluation dans Jira.")
    analyseur.add_argument("--projet", required=True, help="Cle du projet Jira, par exemple KAN")
    analyseur.add_argument(
        "--courriel",
        required=True,
        help="Adresse du compte Atlassian proprietaire du jeton d'API",
    )
    analyseur.add_argument(
        "--site",
        default="https://andrianalyfanny.atlassian.net",
        help="Origine du site Jira",
    )
    analyseur.add_argument(
        "--execute",
        action="store_true",
        help="Ecrire reellement. Sans ce drapeau, rien n'est cree.",
    )
    arguments = analyseur.parse_args()

    with CORPUS.open(encoding="utf-8") as fichier:
        lignes = list(csv.DictReader(fichier))
    registre = _charger_le_registre()
    restants = [ligne for ligne in lignes if ligne["Id"] not in registre]

    print(f"Corpus   : {len(lignes)} tickets dans {CORPUS.relative_to(RACINE)}")
    print(f"Registre : {len(registre)} deja importes -> {len(restants)} a creer")
    if not restants:
        print("Rien a faire.")
        return 0

    try:
        autorisation = _autorisation(arguments.courriel)
        print(f"Site     : {arguments.site}")
        traduction = _verifier_le_projet(autorisation, arguments.site, arguments.projet, restants)
        presents = _resumes_deja_presents(autorisation, arguments.site, arguments.projet)
    except ImportEchoue as erreur:
        print(f"\nArret avant toute ecriture :\n  {erreur}", file=sys.stderr)
        return 1

    adoptes = {
        ligne["Id"]: presents[ligne["Summary"]]
        for ligne in restants
        if ligne["Summary"] in presents
    }
    if adoptes:
        # Ces tickets existent dans Jira sans figurer au registre : une reponse
        # perdue apres une creation reussie. Les adopter, plutot que les recreer.
        registre.update(adoptes)
        _ecrire_le_registre(registre)
        restants = [ligne for ligne in restants if ligne["Id"] not in registre]
        for graine, cle in sorted(adoptes.items()):
            print(f"  deja present, adopte : {graine} -> {cle}")
        print(f"Reste    : {len(restants)} a creer")
        if not restants:
            print("Rien a creer.")
            return 0

    if not arguments.execute:
        print("\nSimulation -- aucune ecriture. Apercu des trois premiers :")
        for ligne in restants[:3]:
            etiquettes = [e for e in (ligne["Labels 1"], ligne["Labels 2"]) if e]
            resume = ligne["Summary"][:70]
            print(f"  {ligne['Id']}  [{ligne['Issue Type']}/{ligne['Priority']}] {resume}")
            taille = len(ligne["Description"])
            print(f"          etiquettes {etiquettes}, description {taille} car.")
        print(
            f"\nRelance avec --execute pour creer {len(restants)} tickets "
            f"dans {arguments.projet}."
        )
        return 0

    base = API.format(site=arguments.site)
    crees = 0
    try:
        for ligne in restants:
            champs = {
                "project": {"key": arguments.projet},
                "summary": ligne["Summary"],
                "description": _adf(ligne["Description"]),
                "issuetype": {"name": traduction[ligne["Issue Type"]]},
                "priority": {"name": ligne["Priority"]},
                "labels": [e for e in (ligne["Labels 1"], ligne["Labels 2"]) if e],
            }
            reponse = _appel(
                f"{base}/issue", autorisation, methode="POST", corps={"fields": champs}
            )
            registre[ligne["Id"]] = str(reponse["key"])
            crees += 1
            print(f"  {ligne['Id']} -> {reponse['key']}")
            time.sleep(PAUSE_SECONDES)
    except ImportEchoue as erreur:
        print(f"\nInterrompu apres {crees} creation(s) :\n  {erreur}", file=sys.stderr)
        return 1
    finally:
        # Ecrit meme en cas d'interruption : sans cela une relance recreerait ce
        # qui vient d'etre cree, et le corpus contiendrait des doublons que rien
        # ne distinguerait des vrais.
        _ecrire_le_registre(registre)
        print(f"\nRegistre mis a jour : {REGISTRE.relative_to(RACINE)} ({len(registre)} entrees)")

    print(f"{crees} tickets crees dans {arguments.projet}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
