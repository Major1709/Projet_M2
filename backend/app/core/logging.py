"""Retirer des journaux ce qui n'aurait jamais du y entrer.

Le probleme est celui du journal d'acces d'uvicorn, et il n'a rien d'accidentel :
ce journal ecrit la ligne de requete complete, requete comprise. Le rappel OAuth
d'Atlassian revient en GET avec le code d'autorisation dans l'URL -- c'est le
protocole qui l'impose, pas un choix du projet -- donc chaque connexion depose un
credential en clair dans un journal persistant.

Ce code est de courte duree (300 s) et a usage unique, ce qui limite la fenetre
mais ne change pas la nature de la chose : un jeton signe portant l'identifiant de
compte, le defi PKCE, les portees et l'identifiant de session Atlassian, ecrit dans
un fichier que personne ne traite comme un secret et que tout le monde copie en
demandant de l'aide.

La redaction se fait au niveau du journal et non de la route, parce que c'est le
journal qui fuit. Une route qui prendrait soin de ne rien journaliser laisserait
quand meme uvicorn ecrire sa ligne d'acces, et la prochaine route a parametre
sensible recommencerait le probleme a zero.
"""

import logging
import re
from typing import Final

# Le nom des parametres, pas leur valeur. Un nom se connait a l'avance ; une valeur
# ne se reconnait pas de facon fiable, et un filtre qui essaierait de deviner ce qui
# ressemble a un secret laisserait passer ceux qui n'y ressemblent pas.
#
# Plus large que le seul besoin d'aujourd'hui, deliberement : la prochaine route qui
# recoit un parametre sensible ne doit pas dependre de quelqu'un se souvenant de ce
# fichier.
SENSITIVE_QUERY_PARAMETERS: Final = (
    "code",
    "state",
    "token",
    "id_token",
    "access_token",
    "refresh_token",
    "code_verifier",
    "assertion",
    "client_secret",
    "password",
    "api_key",
)

REDACTED: Final = "<redacted>"

# La valeur s'arrete au premier separateur : & termine un parametre, l'espace et le
# guillemet terminent l'URL dans une ligne de journal. Ancre sur ? ou & pour ne pas
# mordre sur un mot qui finirait par le nom d'un parametre -- "postcode=" n'est pas
# "code=".
_SENSITIVE = re.compile(
    r"([?&])(" + "|".join(SENSITIVE_QUERY_PARAMETERS) + r")=[^&\s\"']*",
    re.IGNORECASE,
)


def redact(text: str) -> str:
    """Remplacer la valeur des parametres sensibles, en gardant le reste lisible.

    Le nom du parametre survit. Un journal qui effacerait la ligne entiere serait
    sur, et inutile : on veut encore savoir qu'un rappel a eu lieu, avec quel statut.
    """

    return _SENSITIVE.sub(lambda m: f"{m.group(1)}{m.group(2)}={REDACTED}", text)


class RedactSensitiveQueryParameters(logging.Filter):
    """Reecrit un enregistrement avant qu'il n'atteigne le moindre gestionnaire.

    Agit sur ``args`` autant que sur ``msg`` : uvicorn journalise avec un motif et
    des arguments separes, donc l'URL n'est pas dans le message au moment ou le
    filtre la voit. Un filtre qui ne regarderait que ``msg`` ne verrait rien et
    passerait pour actif.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(argument) if isinstance(argument, str) else argument
                for argument in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        # Toujours vrai : ce filtre desamorce, il ne supprime pas. Un rappel OAuth
        # doit rester visible dans les journaux d'acces.
        return True


# Les journaux ou une URL peut apparaitre. uvicorn.access porte la ligne de requete ;
# les deux autres sont la parce qu'une trace d'erreur cite volontiers l'URL fautive.
_FILTERED_LOGGERS: Final = ("uvicorn.access", "uvicorn.error", "app")


def install_log_redaction() -> None:
    """Poser le filtre, une fois, sur les journaux concernes.

    Idempotent parce que ``create_app`` est appele plusieurs fois dans une suite de
    tests, et qu'un filtre pose deux fois travaillerait deux fois pour rien.
    """

    for name in _FILTERED_LOGGERS:
        logger = logging.getLogger(name)
        if any(isinstance(existing, RedactSensitiveQueryParameters) for existing in logger.filters):
            continue
        logger.addFilter(RedactSensitiveQueryParameters())


__all__ = [
    "REDACTED",
    "SENSITIVE_QUERY_PARAMETERS",
    "RedactSensitiveQueryParameters",
    "install_log_redaction",
    "redact",
]
