"""Construit un document de credentials MCP a partir du cache de mcp-remote.

`mcp-remote` conserve, apres un flux de consentement, l'access_token, le
refresh_token et le client enregistre dynamiquement. Le backend a besoin des
trois pour renouveler seul : ce script les recopie sans jamais afficher la
moindre valeur, ce qui evite de faire transiter un jeton par un copier-coller
ou par l'historique du shell.

Usage :
    python scripts/mcp_credentials_import.py <fichier-de-sortie> [--attendu <hote>]

A rejouer une fois par fournisseur -- et, pour Atlassian, une fois par site --
apres avoir vide ~/.mcp-auth et relance :
    npx -y mcp-remote https://mcp.atlassian.com/v1/mcp
    npx -y mcp-remote https://mcp.figma.com/mcp

Un jeton delegue Atlassian ne couvre QUE le site choisi sur l'ecran de
consentement, et rien dans le cache ne dit lequel. Le site est donc interroge
avant l'ecriture, et --attendu fait echouer l'import sans rien ecrire quand le
site obtenu n'est pas celui voulu : sans ce controle, l'erreur ne se manifeste
que plus tard, sous la forme d'un outil refuse.

Figma n'a pas d'equivalent de cette notion de site, et son client n'est pas
public : le client_secret est repris quand mcp-remote en a recu un, faute de
quoi le renouvellement serait refuse.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_STORE = Path.home() / ".mcp-auth"
ACCESSIBLE_RESOURCES = "https://api.atlassian.com/oauth/token/accessible-resources"


def _covered_sites(access_token: str) -> list[str] | None:
    """Les sites Atlassian que ce jeton couvre, ou None si ce n'en est pas un.

    Cet appel ne liste que les sites du jeton presente. C'est ce qui en fait un
    controle utile ici, et ce qui interdit d'en tirer qu'un site absent n'existe
    pas -- confusion qui a deja coute une correction erronee.
    """

    request = urllib.request.Request(
        ACCESSIBLE_RESOURCES,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError:
        # Un jeton d'un autre fournisseur est simplement rejete ici : ce n'est pas
        # une erreur d'import, seulement l'absence de controle equivalent.
        return None
    except (urllib.error.URLError, ValueError) as error:
        raise SystemExit(f"Verification impossible : {type(error).__name__}") from error
    return sorted({str(entry.get("url", "")) for entry in payload if entry.get("url")})


def _latest_store() -> tuple[Path, Path]:
    """Le couple (tokens, client_info) le plus recent du cache mcp-remote.

    Le cache est indexe par une empreinte de l'URL du serveur : les deux sites
    Atlassian partagent donc la meme entree, et une nouvelle autorisation ecrase
    la precedente. On prend la plus recente, celle du flux qui vient d'etre joue.
    """

    if not DEFAULT_STORE.is_dir():
        raise SystemExit(f"Cache mcp-remote introuvable : {DEFAULT_STORE}")
    tokens = sorted(
        DEFAULT_STORE.glob("*/*_tokens.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not tokens:
        raise SystemExit(
            "Aucune autorisation en cache. Jouer d'abord un flux de consentement :\n"
            "  npx -y mcp-remote <url-du-serveur-mcp>"
        )
    token_file = tokens[0]
    client_file = token_file.with_name(token_file.name.replace("_tokens", "_client_info"))
    if not client_file.is_file():
        raise SystemExit(f"client_info absent a cote de {token_file.name}")
    return token_file, client_file


def _parse_arguments() -> tuple[Path, str | None]:
    arguments = sys.argv[1:]
    expected: str | None = None
    if "--attendu" in arguments:
        index = arguments.index("--attendu")
        if index + 1 >= len(arguments):
            raise SystemExit("--attendu demande un hote.")
        expected = arguments[index + 1]
        del arguments[index : index + 2]
    if len(arguments) != 1:
        raise SystemExit(__doc__)
    return Path(arguments[0]), expected


def main() -> None:
    destination, expected = _parse_arguments()

    token_file, client_file = _latest_store()
    tokens = json.loads(token_file.read_text(encoding="utf-8"))
    client = json.loads(client_file.read_text(encoding="utf-8"))

    missing = [key for key in ("access_token", "refresh_token") if not tokens.get(key)]
    if missing:
        raise SystemExit(
            "Autorisation incomplete : "
            + ", ".join(missing)
            + " absent(s). Rejouer le flux de consentement."
        )
    if not client.get("client_id"):
        raise SystemExit("client_id absent du client_info.")

    sites = _covered_sites(tokens["access_token"])
    if sites is not None:
        print("Sites couverts :", ", ".join(sites) or "aucun")
        if expected is not None and not any(expected in site for site in sites):
            raise SystemExit(
                f"Site attendu absent : {expected}\n"
                "Rien n'a ete ecrit. Vider ~/.mcp-auth, rejouer le flux de consentement\n"
                "et choisir le bon site sur l'ecran d'autorisation."
            )
    elif expected is not None:
        raise SystemExit("--attendu ne s'applique qu'a un jeton Atlassian.")

    expires_in = tokens.get("expires_in")
    document = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "client_id": client["client_id"],
        # Une duree absente vaut expiration immediate : le backend renouvellera au
        # premier appel plutot que de presenter un jeton dont il ignore l'age.
        "expires_at": time.time() + float(expires_in)
        if isinstance(expires_in, int | float)
        else 0.0,
    }
    # Figma n'accepte pas de client public : sans ce secret, son renouvellement
    # echoue. Atlassian n'en emet pas, et la cle reste alors absente.
    if client.get("client_secret"):
        document["client_secret"] = client["client_secret"]

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")
    # Le mode passe a os.open ne s'applique qu'a la creation : reimporter par-dessus
    # un fichier existant conserverait ses droits d'origine. Or ce document porte
    # l'access_token, le refresh_token et, pour Figma, le client_secret. On force
    # donc les permissions apres coup, sur le descripteur deja ecrit.
    os.chmod(destination, 0o600)

    age = time.time() - token_file.stat().st_mtime
    print(f"Ecrit : {destination}")
    print(f"  source   : {token_file.name} (autorisation vieille de {age / 60:.0f} min)")
    print(f"  contenu  : {', '.join(sorted(document))}")
    if isinstance(expires_in, int | float):
        print(
            f"  validite : {float(expires_in) / 3600:.1f} h, renouvelee ensuite sans intervention"
        )


if __name__ == "__main__":
    main()
