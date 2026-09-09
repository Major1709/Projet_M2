"""L'annuaire de cadres : retrouver un cadre par son nom, sans lien colle.

Le besoin est etroit et il vaut la peine d'etre rappele : l'API Figma ne sait pas
chercher un cadre. Elle rend un fichier entier quand on lui donne sa cle, et rien ne
permet de demander "ou est le cadre nomme Nexia". Sans annuaire, l'utilisateur devait
coller une URL a chaque question.

L'arbre utilise dans ces tests est la forme REELLE renvoyee par l'API le 09/09/2026
pour la maquette de reference, releve plutot qu'imagine : un double invente aurait pu
etre plus propre que la realite, et c'est exactement comme cela qu'un extracteur passe
les tests puis echoue en production.
"""

from typing import Any

import pytest

from app.core.identity import SecurityContext
from app.figma.catalogue import (
    INDEXED_NODE_TYPES,
    FigmaFrameCatalogue,
    _normalise,
    _walk,
)
from app.mcp.errors import MCPRemoteToolFailure

CONTEXT = SecurityContext(tenant_id="t", user_id="u")
CLE = "UVQmgXGaZC5vrtaQRU5nvo"

ARBRE_REEL: dict[str, Any] = {
    "type": "DOCUMENT",
    "name": "Document",
    "id": "0:0",
    "children": [
        {
            "type": "CANVAS",
            "name": "Page 1",
            "id": "0:1",
            "children": [
                {
                    "type": "SECTION",
                    "name": "Section 1",
                    "id": "1:2",
                    "children": [
                        {
                            "type": "SHAPE_WITH_TEXT",
                            "name": "START",
                            "id": "1:3",
                            "characters": "START",
                        },
                        {
                            "type": "SHAPE_WITH_TEXT",
                            "name": "LOGIN",
                            "id": "1:5",
                            "characters": "LOGIN",
                        },
                        {"type": "CONNECTOR", "name": "Connector line", "id": "1:7"},
                    ],
                }
            ],
        }
    ],
}


class ReadsReturning:
    """Un chemin de lecture qui rend l'arbre donne, et compte les appels."""

    def __init__(self, document: Any = None, *, raises: Exception | None = None) -> None:
        self._document = ARBRE_REEL if document is None else document
        self._raises = raises
        self.calls: list[Any] = []

    async def execute_call(self, *, call, context):
        self.calls.append(call)
        if self._raises is not None:
            raise self._raises
        return _Result({"document": self._document})


class _Result:
    def __init__(self, payload: Any) -> None:
        self.structured_content = payload
        self.content = ()


def catalogue_for(reads: Any, **kwargs) -> FigmaFrameCatalogue:
    return FigmaFrameCatalogue(reads=reads, file_keys=(CLE,), **kwargs)


def test_the_walker_keeps_what_someone_would_ask_for() -> None:
    """Les conteneurs purs sont ecartes : personne ne demande "lis le document"."""

    entrees = _walk(ARBRE_REEL, CLE)
    noms = [e.name for e in entrees]

    assert noms == ["Section 1", "START", "LOGIN"]
    assert "Document" not in noms
    assert "Page 1" not in noms
    # Le connecteur non plus : il relie, il ne contient rien a lire.
    assert "Connector line" not in noms


def test_an_entry_carries_what_the_next_read_needs() -> None:
    """Le nom seul ne sert a rien : il faut de quoi aller lire le noeud."""

    login = next(e for e in _walk(ARBRE_REEL, CLE) if e.name == "LOGIN")

    assert login.file_key == CLE
    assert login.node_id == "1:5"
    assert login.location == "Document > Page 1 > Section 1 > LOGIN"


def test_the_path_distinguishes_two_frames_of_the_same_name() -> None:
    """Deux maquettes peuvent avoir un "LOGIN". Le chemin les separe, sinon l'annuaire
    rendrait deux lignes indiscernables."""

    entrees = _walk(ARBRE_REEL, CLE)

    assert all(e.location.startswith("Document > Page 1") for e in entrees)


def test_an_unexpected_node_is_skipped_and_not_fatal() -> None:
    """Ce qui arrive vient d'un fournisseur : un noeud inattendu doit faire ignorer ce
    noeud, jamais echouer l'indexation entiere."""

    casse = {
        "type": "CANVAS",
        "name": "Page",
        "id": "0:1",
        "children": [
            "pas un noeud",
            {"type": "FRAME"},
            {"type": "FRAME", "name": "Bon", "id": "2:1"},
        ],
    }

    entrees = _walk(casse, CLE)

    assert [e.name for e in entrees] == ["Bon"]


def test_the_indexed_types_exclude_containers_and_connectors() -> None:
    assert "FRAME" in INDEXED_NODE_TYPES
    assert "DOCUMENT" not in INDEXED_NODE_TYPES
    assert "CANVAS" not in INDEXED_NODE_TYPES
    assert "CONNECTOR" not in INDEXED_NODE_TYPES


def test_the_search_folds_case_and_accents() -> None:
    """Sans cela, l'utilisateur devrait reproduire exactement la graphie choisie par
    quelqu'un d'autre dans Figma -- soit remplacer un lien a coller par un nom a
    deviner."""

    assert _normalise("Paiement") == _normalise("PAIEMENT")
    assert _normalise("Résumé") == _normalise("resume")


@pytest.mark.anyio
async def test_a_frame_is_found_by_its_name() -> None:
    annuaire = catalogue_for(ReadsReturning())

    trouves = await annuaire.find(query="login", context=CONTEXT)

    assert [e.name for e in trouves] == ["LOGIN"]
    assert trouves[0].node_id == "1:5"


@pytest.mark.anyio
async def test_an_exact_match_is_not_diluted_by_approximate_ones() -> None:
    """Si un cadre porte exactement le nom demande, ajouter tous ceux qui contiennent
    ce mot noierait la bonne reponse au lieu de l'appuyer."""

    arbre = {
        "type": "CANVAS",
        "name": "Page",
        "id": "0:1",
        "children": [
            {"type": "FRAME", "name": "Login", "id": "1:1"},
            {"type": "FRAME", "name": "Login mobile", "id": "1:2"},
            {"type": "FRAME", "name": "Ecran de login", "id": "1:3"},
        ],
    }
    annuaire = catalogue_for(ReadsReturning(arbre))

    trouves = await annuaire.find(query="login", context=CONTEXT)

    assert [e.name for e in trouves] == ["Login"]


@pytest.mark.anyio
async def test_a_new_frame_is_found_after_an_automatic_refresh() -> None:
    """Le comportement qui rend l'annuaire utilisable : l'utilisateur ajoute un cadre
    dans Figma et le demande, sans rien relancer."""

    reads = ReadsReturning()
    annuaire = catalogue_for(reads, min_refresh_interval_seconds=0.0)
    assert await annuaire.find(query="paiement", context=CONTEXT) == ()

    # La maquette change entre les deux questions.
    reads._document = {
        "type": "CANVAS",
        "name": "Page 1",
        "id": "0:1",
        "children": [{"type": "FRAME", "name": "Paiement", "id": "9:1"}],
    }

    trouves = await annuaire.find(query="paiement", context=CONTEXT)

    assert [e.name for e in trouves] == ["Paiement"]


@pytest.mark.anyio
async def test_a_missing_name_does_not_reread_on_every_attempt() -> None:
    """Une faute de frappe suffirait sinon a faire relire toutes les maquettes a
    chaque question."""

    reads = ReadsReturning()
    annuaire = catalogue_for(reads, min_refresh_interval_seconds=3_600.0)

    await annuaire.find(query="inexistant", context=CONTEXT)
    appels_apres_premiere = len(reads.calls)
    await annuaire.find(query="inexistant", context=CONTEXT)

    assert len(reads.calls) == appels_apres_premiere


@pytest.mark.anyio
async def test_a_successful_search_costs_no_read() -> None:
    reads = ReadsReturning()
    annuaire = catalogue_for(reads)
    await annuaire.refresh(CONTEXT)
    avant = len(reads.calls)

    await annuaire.find(query="LOGIN", context=CONTEXT)

    assert len(reads.calls) == avant


@pytest.mark.anyio
async def test_an_unreadable_file_does_not_deprive_of_the_others() -> None:
    """Une maquette supprimee ou devenue inaccessible ne doit pas vider l'annuaire."""

    annuaire = FigmaFrameCatalogue(
        reads=ReadsReturning(raises=MCPRemoteToolFailure()), file_keys=(CLE, "autre")
    )

    assert await annuaire.refresh(CONTEXT) == 0
    # Et surtout : aucune exception ne remonte.
    assert await annuaire.find(query="login", context=CONTEXT) == ()


@pytest.mark.anyio
async def test_the_read_goes_through_the_ordinary_audited_path() -> None:
    """Un chemin de lecture parallele ferait sortir du contenu Figma sans qu'aucun
    audit ne le nomme."""

    reads = ReadsReturning()
    await catalogue_for(reads).refresh(CONTEXT)

    appel = reads.calls[0]
    assert appel.tool_name == "getFigmaFile"
    assert appel.arguments == {"fileKey": CLE}


# --- Nommer les maquettes au modele -----------------------------------------------
#
# Sans cela, l'utilisateur devait recopier une cle de vingt-deux caracteres dans sa
# question : l'annuaire connaissait la maquette, mais rien ne le disait au modele.


def test_before_any_indexing_only_the_key_is_announced() -> None:
    """Une description d'outil est construite au demarrage, avant tout appel reseau.
    Annoncer un nom qu'on n'a pas encore lu serait inventer ; la cle reste exacte."""

    annuaire = catalogue_for(ReadsReturning())

    assert annuaire.describe() == (CLE,)


@pytest.mark.anyio
async def test_after_indexing_the_file_is_named() -> None:
    """Le nom vient de la reponse du fournisseur, pas d'une configuration : deux
    endroits qui nommeraient la meme maquette finiraient par diverger."""

    class ReadsWithName(ReadsReturning):
        async def execute_call(self, *, call, context):
            self.calls.append(call)
            return _Result({"name": "PROCESS", "document": ARBRE_REEL})

    annuaire = catalogue_for(ReadsWithName())
    await annuaire.refresh(CONTEXT)

    assert annuaire.describe() == (f"PROCESS ({CLE})",)


@pytest.mark.anyio
async def test_a_file_without_a_name_falls_back_to_its_key() -> None:
    """Un fournisseur qui ne nomme pas son fichier ne doit pas faire disparaitre la
    maquette de la liste."""

    annuaire = catalogue_for(ReadsReturning())
    await annuaire.refresh(CONTEXT)

    assert annuaire.describe() == (CLE,)
