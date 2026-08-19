from collections.abc import Sequence
from threading import Lock
from typing import Any

from app.semantics.domain import EMBEDDING_DIMENSIONS, TextKind, prefixed
from app.semantics.errors import EmbeddingBackendUnavailable, EmbeddingShapeRejected

DEFAULT_MODEL = "intfloat/multilingual-e5-base"


class LocalEmbeddingProvider:
    """multilingual-e5-base, running in this process.

    Local rather than a hosted embedding API, and the reason is not cost. The
    text being embedded is the whole content of the project's tickets and pages;
    sending it to a third party to obtain a vector would export the corpus that
    the rest of this system goes to some length to read under a delegated,
    audited, tenant-scoped grant. A vector is also useless to anyone but us,
    which makes the export pure downside.

    The runtime is heavy -- roughly 2,3 Go with its engine -- so it lives behind
    an optional extra and is imported only when a provider is actually built.
    Importing it at module scope would make every process that never embeds
    anything, including the migration runner, pay for it.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any | None = None
        # Loading is not thread-safe and takes seconds. Two requests arriving
        # together must not each build a copy of a 1 Go model.
        self._lock = Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _loaded(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise EmbeddingBackendUnavailable(
                    "sentence-transformers is not installed; "
                    "install the 'embeddings' extra to enable indexing"
                ) from error
            try:
                self._model = SentenceTransformer(self._model_name)
            except Exception as error:  # noqa: BLE001 - the runtime raises many types
                raise EmbeddingBackendUnavailable(
                    f"The embedding model {self._model_name} could not be loaded"
                ) from error
            return self._model

    def embed(self, texts: Sequence[str], *, kind: TextKind) -> list[tuple[float, ...]]:
        if not texts:
            return []
        model = self._loaded()
        # normalize_embeddings makes every vector unit length, which is what turns
        # the cosine distance stored alongside into a comparable number. Without
        # it, distance would partly reflect text length.
        vectors = model.encode(
            [prefixed(text, kind) for text in texts],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embeddings = [tuple(float(value) for value in vector) for vector in vectors]
        wrong = {len(vector) for vector in embeddings} - {EMBEDDING_DIMENSIONS}
        if wrong:
            # The configured model is not the one this schema was built for. Caught
            # here rather than at insertion, where the message would name a column
            # instead of the setting that actually caused it.
            raise EmbeddingShapeRejected(
                f"{self._model_name} produced {sorted(wrong)}-dimension vectors, "
                f"but the store holds {EMBEDDING_DIMENSIONS}"
            )
        return embeddings
