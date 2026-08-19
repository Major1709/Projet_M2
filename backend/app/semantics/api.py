from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.core.identity import SecurityContext, get_security_context
from app.mcp.api import translate_read_error
from app.mcp.errors import MCPReadError
from app.mcp.registry import JIRA_SOURCE_ORIGIN
from app.semantics.errors import SemanticError
from app.semantics.indexing import IndexingUnreadable, JiraIndexer

router = APIRouter(prefix="/api/semantics", tags=["semantics"])


class ReindexResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    correlation_id: str
    pages: int
    documents: int
    embedded: int
    skipped: int


def get_indexer(request: Request) -> JiraIndexer:
    container = request.app.state.container
    index = getattr(container, "semantic_index", None)
    if index is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "EMBEDDINGS_DISABLED",
                "message": "Semantic retrieval is not enabled on this deployment",
            },
        )
    return JiraIndexer(
        reads=container.mcp_reads,
        index=index,
        # The same origin the citations are built from, so a lead and a
        # citation for one ticket point at the same page.
        source_origin=JIRA_SOURCE_ORIGIN,
    )


@router.post("/reindex", response_model=ReindexResult)
async def reindex(
    request: Request,
    context: Annotated[SecurityContext, Depends(get_security_context)],
) -> ReindexResult:
    """Bring this tenant's index in step with its Jira project.

    The JQL comes from the deployment's settings, never from the request. A
    caller who chose the query would choose what enters their own index -- and
    an index is what later answers "nothing like this exists".

    Indexing goes through the same MCP read path an answer uses, so it is bound
    by the same allowlist and appears in the same audit trail. There is no
    quieter door.
    """

    indexer = get_indexer(request)
    # Its own identifier, so the reads this maintenance causes are attributable
    # to it and never confused with a question's trail.
    correlation_id = str(uuid4())
    try:
        totaux = await indexer.reindex(
            context=context,
            jql=request.app.state.container.settings.reindex_jql,
            correlation_id=correlation_id,
        )
    except MCPReadError as error:
        # Translated by the MCP module rather than re-mapped here, so a refused
        # read reports the same status whichever route provoked it.
        raise translate_read_error(error) from error
    except (IndexingUnreadable, SemanticError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": error.code, "message": "The index could not be updated"},
        ) from error
    return ReindexResult(correlation_id=correlation_id, **totaux)
