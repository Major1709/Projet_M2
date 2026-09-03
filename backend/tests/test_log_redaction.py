"""Le code d'autorisation OAuth ne doit pas survivre dans les journaux.

Le rappel d'Atlassian revient en GET avec le code dans l'URL : c'est le protocole
qui l'impose. Le journal d'acces d'uvicorn ecrit la ligne de requete complete, donc
chaque connexion deposait un credential en clair dans un journal persistant.

Court (300 s) et a usage unique, mais un jeton signe portant l'identifiant de compte,
le defi PKCE, les portees et l'identifiant de session Atlassian -- dans un fichier
que personne ne traite comme un secret et que tout le monde copie en demandant de
l'aide.
"""

import logging

import pytest

from app.core.config import Settings
from app.core.logging import (
    REDACTED,
    SENSITIVE_QUERY_PARAMETERS,
    RedactSensitiveQueryParameters,
    install_log_redaction,
    redact,
)
from app.main import create_app

CODE = "eyJraWQiOiJhdXRoLWtleSIsImFsZyI6IlJTMjU2In0.charge-utile-signee.signature"


def test_the_authorisation_code_does_not_survive() -> None:
    ligne = f"/api/auth/atlassian/callback?code={CODE}&state=abc123"

    nettoye = redact(ligne)

    assert CODE not in nettoye
    assert "abc123" not in nettoye


def test_the_line_stays_useful() -> None:
    """Effacer la ligne entiere serait sur, et inutile : on veut encore savoir qu'un
    rappel a eu lieu."""

    nettoye = redact(f"/api/auth/atlassian/callback?code={CODE}")

    assert "/api/auth/atlassian/callback" in nettoye
    assert f"code={REDACTED}" in nettoye


def test_a_parameter_that_merely_ends_with_a_sensitive_name_is_untouched() -> None:
    """L'ancrage sur ? et & existe pour ca : "postcode" n'est pas "code"."""

    nettoye = redact("/recherche?postcode=75001&mode=liste")

    assert nettoye == "/recherche?postcode=75001&mode=liste"


@pytest.mark.parametrize("nom", SENSITIVE_QUERY_PARAMETERS)
def test_every_declared_parameter_is_actually_redacted(nom: str) -> None:
    """La liste pilote le filtre. Un nom ajoute sans effet serait pire qu'absent :
    il donnerait l'impression d'une protection."""

    assert "secret-a-cacher" not in redact(f"/x?{nom}=secret-a-cacher")


def test_the_filter_reads_the_arguments_and_not_only_the_message() -> None:
    """Le piege de ce correctif, et la raison d'etre du test.

    uvicorn journalise avec un motif et des arguments separes : l'URL n'est PAS dans
    ``msg`` au moment ou le filtre la voit. Un filtre qui ne regarderait que ``msg``
    ne trouverait rien, ne leverait aucune erreur, et passerait pour actif.
    """

    enregistrement = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        # Le motif reel d'uvicorn.
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:54321",
            "GET",
            f"/api/auth/atlassian/callback?code={CODE}&state=xyz",
            "1.1",
            307,
        ),
        exc_info=None,
    )

    assert RedactSensitiveQueryParameters().filter(enregistrement) is True
    rendu = enregistrement.getMessage()
    assert CODE not in rendu
    # La requete reste identifiable : methode, chemin et statut survivent.
    assert "/api/auth/atlassian/callback" in rendu
    assert "307" in rendu


def test_a_record_is_never_dropped() -> None:
    """Le filtre desamorce, il ne censure pas : un rappel doit rester visible."""

    enregistrement = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "rien de sensible", None, None
    )

    assert RedactSensitiveQueryParameters().filter(enregistrement) is True


def test_building_the_application_installs_the_filter() -> None:
    """Pose dans create_app pour qu'aucun lancement ne puisse s'en passer : par la
    commande du conteneur, par un script, ou par un test."""

    create_app(Settings(environment="test"))

    filtres = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, RedactSensitiveQueryParameters) for f in filtres)


def test_installing_twice_leaves_one_filter() -> None:
    """create_app tourne plusieurs fois dans une suite ; un filtre pose deux fois
    travaillerait deux fois pour rien."""

    install_log_redaction()
    install_log_redaction()

    filtres = logging.getLogger("uvicorn.access").filters
    poses = [f for f in filtres if isinstance(f, RedactSensitiveQueryParameters)]
    assert len(poses) == 1
