"""Fill the vector index from the sources, through the same hardened reads.

Not a shortcut past the MCP pipeline, and not by accident. Indexing reads the
same tickets an answer would read, so it must pass the same allowlist, the same
schema validation, the same server-injected bindings and the same audit trail.
An indexer with its own credential would be a second, quieter door into the
sources -- one that no read event would ever mention.

The cost of that choice is visible here: the reads come back as provider JSON
that has to be parsed, rather than as a convenient object. That is the honest
price of not having a privileged path.
"""

import json
import logging
from typing import Any

from app.core.identity import SecurityContext
from app.mcp.domain import MCPReadToolCall, ToolActionClass
from app.mcp.errors import MCPReadError
from app.mcp.read_workflow import MCPReadWorkflow
from app.semantics.domain import IndexableDocument
from app.semantics.workflow import SemanticIndex

logger = logging.getLogger(__name__)

# One page of results. The public schema caps this at fifty, and asking for the
# cap is right here: this is a batch job, not a question, and a smaller page only
# means more round trips through the same budget.
PAGE_SIZE = 50
# How many pages one run will walk. A ceiling rather than "until exhausted": a
# JQL that matches a whole instance would otherwise turn a maintenance call into
# an unbounded crawl, and the caller would have no way to tell it had.
MAX_PAGES = 20
# Only the fields that get embedded or displayed. Asking for everything would
# multiply the payload by the changelog and the comment history, and the
# transport ceiling would then refuse the page.
FIELDS = ["summary", "description"]


def _flatten_adf(node: Any) -> str:
    """Recover the plain text of an Atlassian Document Format tree.

    Jira's v3 API returns descriptions as a document tree, not a string. Reading
    only the top level would yield the text of the first paragraph and silently
    drop everything under a list or a panel -- an embedding built on a third of a
    ticket, with nothing to signal it.
    """

    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(filter(None, (_flatten_adf(child) for child in node)))
    if isinstance(node, dict):
        if node.get("type") == "text" and isinstance(node.get("text"), str):
            return node["text"]
        return _flatten_adf(node.get("content", []))
    return ""


def _documents_from(payload: Any, source_origin: str) -> list[IndexableDocument]:
    documents: list[IndexableDocument] = []
    for issue in payload.get("issues", []) if isinstance(payload, dict) else []:
        if not isinstance(issue, dict):
            continue
        key = issue.get("key")
        fields = issue.get("fields") or {}
        titre = fields.get("summary")
        if not isinstance(key, str) or not isinstance(titre, str) or not titre:
            # A ticket with no summary cannot be embedded usefully and would sit
            # in the index as an empty neighbour of everything.
            continue
        documents.append(
            IndexableDocument(
                source_system="jira",
                external_id=key,
                title=titre[:1_000],
                body=_flatten_adf(fields.get("description"))[:100_000],
                resource_reference=f"{source_origin.rstrip('/')}/browse/{key}",
            )
        )
    return documents


class JiraIndexer:
    """Walks a JQL result set and keeps the semantic index in step with it."""

    def __init__(
        self,
        *,
        reads: MCPReadWorkflow,
        index: SemanticIndex,
        source_origin: str,
    ) -> None:
        self._reads = reads
        self._index = index
        self._source_origin = source_origin

    async def reindex(
        self,
        *,
        context: SecurityContext,
        jql: str,
        correlation_id: str,
        force: bool = False,
    ) -> dict[str, int]:
        documents: list[IndexableDocument] = []
        jeton: str | None = None
        pages = 0
        for _ in range(MAX_PAGES):
            arguments: dict[str, Any] = {
                "jql": jql,
                "maxResults": PAGE_SIZE,
                "fields": FIELDS,
            }
            if jeton:
                arguments["nextPageToken"] = jeton
            result = await self._reads.execute_call(
                call=MCPReadToolCall(
                    source_system="jira",
                    tool_name="searchJiraIssuesUsingJql",
                    action_class=ToolActionClass.READ,
                    arguments=arguments,
                    correlation_id=correlation_id,
                ),
                context=context,
            )
            pages += 1
            payload = self._payload(result)
            documents.extend(_documents_from(payload, self._source_origin))
            jeton = payload.get("nextPageToken") if isinstance(payload, dict) else None
            if not jeton:
                break
        else:
            # Fell out of the loop having used every page. Recorded rather than
            # silently truncated: an index that covers part of a corpus answers
            # "nothing matches" for the rest, which reads as a fact.
            logger.warning(
                "jira reindex stopped on its page ceiling",
                extra={"pages": pages, "documents": len(documents)},
            )

        embarques, ignores = self._index.index(context.tenant_id, documents, force=force)
        return {
            "pages": pages,
            "documents": len(documents),
            "embedded": embarques,
            "skipped": ignores,
        }

    @staticmethod
    def _payload(result: Any) -> Any:
        """The provider's JSON, from whichever half of the result carries it."""

        if result.structured_content is not None:
            return result.structured_content
        for content in result.content:
            if content.text:
                try:
                    return json.loads(content.text)
                except ValueError:
                    continue
        # Not an MCPReadError: the read itself succeeded, and calling this a read
        # failure would put a misleading entry in the audit trail.
        raise IndexingUnreadable("The search returned no document this indexer can read")


class IndexingUnreadable(RuntimeError):
    """The read succeeded but carried nothing parseable."""

    code = "INDEXING_UNREADABLE"


__all__ = ["JiraIndexer", "IndexingUnreadable", "MCPReadError"]
