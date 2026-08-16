from datetime import UTC, datetime, timedelta
from typing import Any

from app.agent.citations import AgentSource, ReadRecord, sources_from
from app.mcp.domain import MCPProvider, MCPReadProvenance
from app.mcp.domain import MCPReadSourceSystem as SourceSystem

DIGEST = "a" * 64
WHEN = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def provenance(**changes: Any) -> MCPReadProvenance:
    values: dict[str, Any] = {
        "provider": MCPProvider.ATLASSIAN,
        "source_system": SourceSystem.JIRA,
        "server_id": "atlassian-rovo",
        "source_origin": "https://andrianalyfanny.atlassian.net",
        "tool_name": "getJiraIssue",
        "protocol_version": "2026-07-28",
        "input_schema_sha256": DIGEST,
        "arguments_sha256": DIGEST,
        "binding_fingerprint": DIGEST,
        "policy_version": "SPEC-MCP-RO-001-r2",
        "correlation_id": "corr-1",
        "retrieved_at": WHEN,
        "resource_reference": "https://andrianalyfanny.atlassian.net/browse/KAN-1",
    }
    values.update(changes)
    return MCPReadProvenance(**values)


def records(*items: MCPReadProvenance | tuple[MCPReadProvenance, bool]) -> tuple[ReadRecord, ...]:
    built = []
    for item in items:
        if isinstance(item, tuple):
            built.append(ReadRecord(provenance=item[0], truncated=item[1]))
        else:
            built.append(ReadRecord(provenance=item))
    return tuple(built)


def test_a_read_of_one_resource_produces_a_link() -> None:
    (source,) = sources_from(records(provenance()))

    assert source.url == "https://andrianalyfanny.atlassian.net/browse/KAN-1"
    assert source.source_system == SourceSystem.JIRA
    assert source.tool_name == "getJiraIssue"
    assert source.retrieved_at == WHEN


def test_a_collection_read_is_a_source_without_a_link() -> None:
    # getVisibleJiraProjects enumerates; it designates no page. Inventing a link
    # here would cite something nobody read.
    (source,) = sources_from(
        records(provenance(tool_name="getVisibleJiraProjects", resource_reference=None))
    )

    assert source.url is None
    assert source.tool_name == "getVisibleJiraProjects"


def test_no_reads_means_no_sources() -> None:
    assert sources_from(()) == ()


def test_the_same_resource_read_twice_is_one_source() -> None:
    # Different arguments, same ticket: one source. A ticket read once for its
    # summary and once for its comments is not two things a reader can open.
    sources = sources_from(
        records(provenance(), provenance(arguments_sha256="b" * 64))
    )

    assert len(sources) == 1


def test_two_different_resources_stay_two_sources() -> None:
    other = provenance(
        resource_reference="https://andrianalyfanny.atlassian.net/browse/KAN-2"
    )

    assert len(sources_from(records(provenance(), other))) == 2


def test_the_same_collection_query_is_one_source() -> None:
    listing = provenance(tool_name="getVisibleJiraProjects", resource_reference=None)

    assert len(sources_from(records(listing, listing))) == 1


def test_two_different_collection_queries_stay_apart() -> None:
    # Without a reference to key on, the query is the identity: two different
    # searches are two different sources even from the same tool.
    first = provenance(tool_name="searchJiraIssuesUsingJql", resource_reference=None)
    second = provenance(
        tool_name="searchJiraIssuesUsingJql",
        resource_reference=None,
        arguments_sha256="b" * 64,
    )

    assert len(sources_from(records(first, second))) == 2


def test_sources_keep_the_order_they_were_first_read() -> None:
    second = provenance(resource_reference="https://andrianalyfanny.atlassian.net/browse/KAN-2")
    third = provenance(tool_name="getVisibleJiraProjects", resource_reference=None)

    sources = sources_from(records(second, provenance(), third, second))

    assert [source.url for source in sources] == [
        "https://andrianalyfanny.atlassian.net/browse/KAN-2",
        "https://andrianalyfanny.atlassian.net/browse/KAN-1",
        None,
    ]


def test_a_truncated_read_says_so() -> None:
    (source,) = sources_from(records((provenance(), True)))

    assert source.truncated is True


def test_truncation_survives_deduplication() -> None:
    # A read that was truncated once is reported as truncated: the model did see a
    # fragment, even if a later read of the same resource was whole.
    (source,) = sources_from(records((provenance(), True), provenance()))
    (reversed_source,) = sources_from(records(provenance(), (provenance(), True)))

    assert source.truncated is True
    assert reversed_source.truncated is True


def test_no_internal_digest_reaches_a_source() -> None:
    # Schema digests and the binding fingerprint identify how the read was made and
    # against which tenant. They belong in the audit trail, not in an answer handed
    # to a caller.
    (source,) = sources_from(records(provenance()))

    assert DIGEST not in str(source.model_dump())
    assert set(AgentSource.model_fields) == {
        "source_system",
        "tool_name",
        "url",
        "retrieved_at",
        "truncated",
    }


def test_a_figma_read_cites_through_the_form_that_resolves_for_both_kinds() -> None:
    figma = provenance(
        provider=MCPProvider.FIGMA,
        source_system=SourceSystem.FIGMA,
        server_id="figma-rest",
        source_origin="https://www.figma.com",
        tool_name="extractFigmaProcess",
        protocol_version="figma-rest-v1",
        resource_reference="https://www.figma.com/file/UVQmgXGaZC5vrtaQRU5nvo",
    )

    (source,) = sources_from(records(figma))

    # /file resolves for a design file and a FigJam board alike, so the citation
    # does not have to guess a kind the read never told us.
    assert source.url == "https://www.figma.com/file/UVQmgXGaZC5vrtaQRU5nvo"


def test_the_earliest_read_time_is_the_one_reported() -> None:
    later = provenance(retrieved_at=WHEN + timedelta(minutes=5))

    (source,) = sources_from(records(provenance(), later))

    # First occurrence wins, so the timestamp matches the order the sources are
    # listed in rather than drifting to whichever read happened last.
    assert source.retrieved_at == WHEN
