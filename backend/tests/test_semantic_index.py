"""The semantic slice, tested without ever loading a model.

A real embedding model is 1 Go and its engine another 1,3 Go. Nothing here needs
either: what these tests hold is the plumbing -- what gets embedded, which side
of the asymmetric prefix is used, what is skipped, and what a tenant can see.

What they deliberately do NOT establish is retrieval quality. A stub provider
cannot tell whether the model rapproche two ways of describing one bug, and a
test that pretended to would be measuring its own fixture. That measurement
belongs to the gold files in data/evaluation, against the real model.
"""

import math

import pytest

from app.semantics.adapters.memory import InMemoryEmbeddingStore, cosine_distance
from app.semantics.domain import (
    EMBEDDING_DIMENSIONS,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    IndexableDocument,
    prefixed,
)
from app.semantics.workflow import SemanticIndex, content_digest


class StubProvider:
    """Deterministic vectors, plus a record of what it was asked to embed."""

    def __init__(self, model_name: str = "stub-model") -> None:
        self._model_name = model_name
        self.appels: list[tuple[str, tuple[str, ...]]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts, *, kind):
        self.appels.append((kind, tuple(texts)))
        vecteurs = []
        for text in texts:
            vecteur = [0.0] * EMBEDDING_DIMENSIONS
            for mot in text.split():
                vecteur[hash(mot) % EMBEDDING_DIMENSIONS] += 1.0
            norme = math.sqrt(sum(v * v for v in vecteur)) or 1.0
            vecteurs.append(tuple(v / norme for v in vecteur))
        return vecteurs


def document(external_id: str, titre: str, corps: str = "") -> IndexableDocument:
    return IndexableDocument(
        source_system="jira",
        external_id=external_id,
        title=titre,
        body=corps,
        resource_reference=f"https://exemple.invalid/browse/{external_id}",
    )


def index_for(provider: StubProvider | None = None):
    fournisseur = provider or StubProvider()
    return SemanticIndex(provider=fournisseur, store=InMemoryEmbeddingStore()), fournisseur


def test_a_document_is_embedded_as_a_passage_and_a_question_as_a_query() -> None:
    """The two sides of an E5 search are not interchangeable.

    Using one prefix for both still produces vectors and still produces a
    ranking -- a measurably worse one, with nothing to indicate anything is
    wrong. That silence is why this is asserted rather than trusted.
    """

    index, provider = index_for()
    index.index("locataire", [document("KAN-2", "Le courriel n'arrive pas")])
    index.search("locataire", "pourquoi le mail de confirmation manque-t-il ?")

    kinds = [kind for kind, _ in provider.appels]
    assert kinds == ["passage", "query"]
    assert prefixed("x", "passage").startswith(PASSAGE_PREFIX)
    assert prefixed("x", "query").startswith(QUERY_PREFIX)


def test_reindexing_an_unchanged_corpus_calls_the_model_for_nothing() -> None:
    index, provider = index_for()
    documents = [document("KAN-2", "Titre", "Corps"), document("KAN-3", "Autre", "Texte")]

    embarques, ignores = index.index("locataire", documents)
    provider.appels.clear()
    encore, sautes = index.index("locataire", documents)

    assert (embarques, ignores) == (2, 0)
    assert (encore, sautes) == (0, 2)
    assert provider.appels == []


def test_an_edited_document_is_embedded_again() -> None:
    index, provider = index_for()
    index.index("locataire", [document("KAN-2", "Titre", "Premier corps")])
    provider.appels.clear()

    embarques, _ = index.index("locataire", [document("KAN-2", "Titre", "Corps corrige")])

    assert embarques == 1


def test_changing_the_model_re_embeds_everything() -> None:
    """A digest over the text alone would make a model change invisible.

    Every document would look unchanged, re-indexing would skip all of them, and
    the corpus would keep old vectors while new ones arrived -- two incompatible
    spaces compared as if they were one, with confident nonsense as the output.
    """

    store = InMemoryEmbeddingStore()
    documents = [document("KAN-2", "Titre", "Corps")]
    SemanticIndex(provider=StubProvider("modele-a"), store=store).index("locataire", documents)

    embarques, ignores = SemanticIndex(
        provider=StubProvider("modele-b"), store=store
    ).index("locataire", documents)

    assert (embarques, ignores) == (1, 0)


def test_the_digest_separates_the_model_from_the_text() -> None:
    # Concatenating without a separator would let one model name plus one text
    # collide with another pair -- rare, silent, and impossible to diagnose.
    assert content_digest("b", "a") != content_digest("", "ab")


def test_reindexing_keeps_the_row_identity_it_was_given() -> None:
    store = InMemoryEmbeddingStore()
    index = SemanticIndex(provider=StubProvider(), store=store)
    index.index("locataire", [document("KAN-2", "Titre", "Un")])
    premier = store.nearest("locataire", [1.0] * EMBEDDING_DIMENSIONS, limit=1)
    index.index("locataire", [document("KAN-2", "Titre", "Deux")])

    assert len(store.digests_for("locataire", "jira")) == 1
    assert premier[0].external_id == "KAN-2"


def test_one_tenant_never_sees_another_tenants_documents() -> None:
    index, _ = index_for()
    index.index("locataire-a", [document("KAN-2", "Virement bloque")])
    index.index("locataire-b", [document("AUT-9", "Virement bloque")])

    trouves = index.search("locataire-a", "virement bloque", limit=10)

    assert [found.external_id for found in trouves] == ["KAN-2"]


def test_a_document_is_not_offered_as_its_own_twin() -> None:
    """Otherwise every "what looks like this?" answer starts with the question."""

    index, _ = index_for()
    reference = document("KAN-2", "Le courriel de confirmation n'arrive jamais")
    index.index("locataire", [reference, document("KAN-3", "Aucun accuse n'est transmis")])

    voisins = index.similar_to("locataire", reference, limit=5)

    assert "KAN-2" not in [found.external_id for found in voisins]


def test_the_title_and_the_body_are_embedded_together() -> None:
    # A Jira title states the symptom and the description the circumstances; one
    # report is only comparable to another as a whole.
    texte = document("KAN-2", "Titre", "Corps").embeddable_text()

    assert texte.startswith("Titre")
    assert texte.endswith("Corps")


def test_a_search_ranks_the_closest_first() -> None:
    index, _ = index_for()
    index.index(
        "locataire",
        [
            document("KAN-2", "virement paiement carte"),
            document("KAN-3", "impression document papier"),
        ],
    )

    trouves = index.search("locataire", "virement paiement carte", limit=2)

    assert trouves[0].external_id == "KAN-2"
    assert trouves[0].distance <= trouves[1].distance


def test_the_distance_is_a_distance_and_not_a_score() -> None:
    """Zero is identical, one is orthogonal, and it is never rescaled.

    The citations of this project deliberately carry no confidence value, for
    the reason that nothing measures one. A distance dressed up as a percentage
    would reintroduce exactly that, through the back door.
    """

    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_indexing_nothing_does_nothing() -> None:
    index, provider = index_for()

    assert index.index("locataire", []) == (0, 0)
    assert provider.appels == []
