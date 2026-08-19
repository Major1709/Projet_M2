class SemanticError(RuntimeError):
    """Base class for failures of the semantic slice."""

    code = "SEMANTIC_FAILED"


class EmbeddingBackendUnavailable(SemanticError):
    """The embedding runtime is not installed, or refused to load the model."""

    code = "EMBEDDING_BACKEND_UNAVAILABLE"


class EmbeddingShapeRejected(SemanticError):
    """The provider returned vectors of a size the stored column cannot hold.

    Worth its own failure rather than a database error later: a dimension
    mismatch means the configured model is not the one this schema was built
    for, and every stored vector from here on would be incomparable with the
    ones already there.
    """

    code = "EMBEDDING_SHAPE_REJECTED"
