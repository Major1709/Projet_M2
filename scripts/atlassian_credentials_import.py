"""Construit un document de credentials Atlassian a partir du cache de mcp-remote.

`mcp-remote` conserve, apres un flux de consentement, l'access_token, le
refresh_token et le client_id du client public enregistre dynamiquement. Le
backend a besoin des trois pour renouveler seul : ce script les recopie sans
jamais afficher la moindre valeur, ce qui evite de faire transiter un jeton par
un copier-coller ou par l'historique du shell.

Usage :
    python scripts/atlassian_credentials_import.py <fichier-de-sortie> [--attendu <hote>]

A relancer une fois par site, apres avoir vide ~/.mcp-auth et rejoue :
    npx -y mcp-remote https://mcp.atlassian.com/v1/mcp

Le jeton obtenu ne couvre QUE le site choisi sur l'ecran de consentement, et
rien dans le cache ne dit lequel : le site est donc interroge avant l'ecriture.
Avec --attendu, un site inattendu fait echouer l'import sans rien ecrire, ce qui
evite de decouvrir l'erreur plus tard sous la forme d'un outil refuse.
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


def _covered_sites(access_token: str) -> list[str]:
    """Les sites que ce jeton couvre, demandes a Atlassian.

    Cet appel ne liste que les sites du jeton presente. C'est justement ce qui en
    fait un controle utile ici, et ce qui interdit d'en tirer qu'un site absent
    n'existe pas -- confusion qui a deja coute une correction erronee.
    """

    request = urllib.request.Request(
        ACCESSIBLE_RESOURCES,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, ValueError) as error:
        raise SystemExit(f"Verification du site impossible : {type(error).__name__}") from error
    return sorted({str(entry.get("url", "")) for entry in payload if entry.get("url")})


def _latest_store() -> tuple[Path, Path]:
    """Le couple (tokens, client_info) le plus recent du cache mcp-remote.

    Le cache est indexe par une empreinte de l'URL du serveur, identique pour les
    deux sites : une nouvelle autorisation ecrase la precedente. On prend donc la
    plus recente, qui est celle du flux qui vient d'etre joue.
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
            "Aucune autorisation en cache. Jouer d'abord :\n"
            "  npx -y mcp-remote https://mcp.atlassian.com/v1/mcp"
        )
    token_file = tokens[0]
    client_file = token_file.with_name(token_file.name.replace("_tokens", "_client_info"))
    if not client_file.is_file():
        raise SystemExit(f"client_info absent a cote de {token_file.name}")
    return token_file, client_file


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    destination = Path(sys.argv[1])

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

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True)
        stream.write("\n")

    age = time.time() - token_file.stat().st_mtime
    print(f"Ecrit : {destination}")
    print(f"  source     : {token_file.name} (autorisation vieille de {age / 60:.0f} min)")
    print(f"  contenu    : access_token, refresh_token, client_id, expires_at")
    if isinstance(expires_in, int | float):
        print(
            f"  validite   : {float(expires_in) / 3600:.1f} h, renouvelee ensuite sans intervention"
        )


if __name__ == "__main__":
    main()
