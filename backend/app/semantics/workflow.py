import hashlib
import logging
from collections.abc import Sequence

from app.semantics.domain import (
    IndexableDocument,
    SimilarDocument,
    StoredEmbedding,
    utc_now,
)
from app.semantics.ports import EmbeddingProvider, EmbeddingStore

logger = logging.getLogger(__name__)

# One model call per batch of this many documents. Small enough that a failure
# costs little, large enough that the per-call overhead is not paid per ticket.
BATCH_SIZE = 16


def content_digest(text: str, model_name: str) -> str:
    """What was embedded, and by which model.

    The model name is part of the digest on purpose. Digesting the text alone
    would make a model change invisible: every document would look unchanged,
    re-indexing would skip all of them, and the corpus would keep vectors from
    the old model while new ones arrived from the new -- silently comparing two
    incompatible spaces.
    """

    return hashlib.sha256(f"{model_name}\x1f{text}".encode()).hexdigest()


class SemanticIndex:
    """Keeps the vector store in step with the documents, and answers by meaning."""

    def __init__(self, *, provider: EmbeddingProvider, store: EmbeddingStore) -> None:
        self._provider = provider
        self._store = store

    def index(
        self,
        tenant_id: str,
        documents: Sequence[IndexableDocument],
        *,
        force: bool = False,
    ) -> tuple[int, int]:
        """Embed what changed. Returns (embedded, skipped)."""

        if not documents:
            return 0, 0
        model = self._provider.model_name
        sources = {document.source_system for document in documents}
        connus: dict[str, str] = {}
        for source in sources:
            connus.update(self._store.digests_for(tenant_id, source))

        a_faire: list[tuple[IndexableDocument, str]] = []
        ignores = 0
        for document in documents:
            empreinte = content_digest(document.embeddable_text(), model)
            if not force and connus.get(document.external_id) == empreinte:
                ignores += 1
                continue
            a_faire.append((document, empreinte))

        embarques = 0
        for depart in range(0, len(a_faire), BATCH_SIZE):
            lot = a_faire[depart : depart + BATCH_SIZE]
            vecteurs = self._provider.embed(
                [document.embeddable_text() for document, _ in lot],
                kind="passage",
            )
            self._store.upsert(
                [
                    StoredEmbedding(
                        tenant_id=tenant_id,
                        source_system=document.source_system,
                        external_id=document.external_id,
                        title=document.title,
                        resource_reference=document.resource_reference,
                        model_name=model,
                        content_digest=empreinte,
                        embedding=vecteur,
                        indexed_at=utc_now(),
                    )
                    for (document, empreinte), vecteur in zip(lot, vecteurs, strict=True)
                ]
            )
            embarques += len(lot)
        logger.info(
            "semantic index updated",
            extra={"embedded": embarques, "skipped": ignores, "model": model},
        )
        return embarques, ignores

    def search(
        self,
        tenant_id: str,
        question: str,
        *,
        limit: int = 5,
        max_distance: float | None = None,
    ) -> list[SimilarDocument]:
        """Documents closest in meaning to a question, et assez proches pour compter.

        The question is embedded as a query, not as a passage: E5 is trained with
        an asymmetric prefix, and using the wrong side still returns a ranking --
        a measurably worse one, with nothing to signal it.

        ``max_distance`` ecarte ce qui est le plus proche sans etre proche. Sans
        plancher, la recherche rendait toujours le nombre demande : "recette de
        cuisine au chocolat" posee a un corpus de tickets bancaires rendait trois
        tickets. Aucune reponse n'en etait fausse -- une piste n'est pas une source,
        et rien ne se cite sans avoir ete lu -- mais le fil payait ces lignes a
        chaque tour, et elles poussaient vers des lectures inutiles.

        Aucun plancher par defaut ici : la valeur mesuree vit dans la configuration,
        parce qu'elle depend du corpus et du modele. Un defaut code en dur serait
        juste pour ce projet et faux pour le suivant.
        """

        vecteur = self._provider.embed([question], kind="query")[0]
        trouves = self._store.nearest(tenant_id, vecteur, limit=limit)
        if max_distance is None:
            return trouves
        return [document for document in trouves if document.distance <= max_distance]

    def similar_to(
        self,
        tenant_id: str,
        document: IndexableDocument,
        *,
        limit: int = 5,
    ) -> list[SimilarDocument]:
        """Documents describing much the same thing as this one.

        Embedded as a passage, because that is what it is, and with itself
        excluded -- a document is always its own nearest neighbour, and letting
        it answer would make every result list start with the question.
        """

        vecteur = self._provider.embed([document.embeddable_text()], kind="passage")[0]
        return self._store.nearest(
            tenant_id,
            vecteur,
            limit=limit,
            exclude_external_id=document.external_id,
        )
