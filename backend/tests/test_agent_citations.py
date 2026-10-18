from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from app.agent.citations import (
    MAX_TITLE_LENGTH,
    AgentSource,
    ReadRecord,
    sources_from,
    title_of,
)
from app.mcp.domain import MCPProvider, MCPReadContent, MCPReadProvenance, MCPReadResult
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
        # Ajoute sciemment : le nom sous lequel la personne reconnait la source. Il
        # vient de la charge lue, jamais de la provenance -- c'est pour cela qu'il
        # peut figurer ici sans ouvrir la porte aux empreintes internes.
        "title",
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


# --- Le nom sous lequel la personne reconnait une source ----------------------------
#
# L'ecran citait le nom de l'outil -- "getConfluencePage", "searchJiraIssuesUsingJql"
# -- qui dit COMMENT la lecture a ete faite et jamais CE QUI a ete lu. Un lecteur ne
# peut pas verifier une source qu'il ne sait pas nommer.
#
# Les charges ci-dessous sont relevees sur de vraies lectures, pas inventees : les
# serveurs Atlassian rendent du JSON dans un bloc de texte, l'adaptateur Figma une
# charge structuree.


def result_for(
    source_system: SourceSystem,
    *,
    text: str | None = None,
    structured: Any = None,
    reference: str | None = "https://andrianalyfanny.atlassian.net/browse/KAN-39",
) -> MCPReadResult:
    return MCPReadResult(
        content=(
            (
                MCPReadContent(
                    kind="text",
                    text=text,
                    size_bytes=len(text.encode("utf-8")),
                    sha256=sha256(text.encode("utf-8")).hexdigest(),
                ),
            )
            if text is not None
            else ()
        ),
        structured_content=structured,
        provenance=provenance(source_system=source_system, resource_reference=reference),
    )


def test_a_jira_issue_is_named_by_its_key_and_summary() -> None:
    import json

    charge = json.dumps({"key": "KAN-39", "fields": {"summary": "Suivi de projet"}})

    assert title_of(result_for(SourceSystem.JIRA, text=charge)) == "KAN-39 - Suivi de projet"


def test_a_confluence_page_is_named_by_its_title() -> None:
    import json

    charge = json.dumps({"id": "8060929", "type": "page", "title": "CDCF K20"})

    assert title_of(result_for(SourceSystem.CONFLUENCE, text=charge)) == "CDCF K20"


def test_a_figma_process_is_named_by_its_file() -> None:
    """La charge Figma arrive structuree et non en texte : les deux chemins sont lus."""

    charge = {"file": {"key": "UVQmgXGaZC5vrtaQRU5nvo", "name": "ACCESA - Virement"}}

    assert title_of(result_for(SourceSystem.FIGMA, structured=charge)) == "ACCESA - Virement"


def test_a_search_is_never_named_after_its_first_result() -> None:
    """Une recherche ne designe rien. La nommer d'apres un resultat laisserait croire
    qu'une seule page a ete consultee."""

    import json

    charge = json.dumps({"issues": [{"key": "KAN-1", "fields": {"summary": "Premier"}}]})

    assert title_of(result_for(SourceSystem.JIRA, text=charge, reference=None)) is None


def test_a_payload_without_a_title_yields_none_rather_than_a_guess() -> None:
    """Un titre invente ferait cliquer vers une page dont le nom ne correspond pas."""

    import json

    assert title_of(result_for(SourceSystem.CONFLUENCE, text=json.dumps({"id": "1"}))) is None
    assert title_of(result_for(SourceSystem.CONFLUENCE, text="pas du json")) is None


def test_an_absurdly_long_summary_is_trimmed() -> None:
    import json

    charge = json.dumps({"key": "KAN-1", "fields": {"summary": "x" * 400}})

    titre = title_of(result_for(SourceSystem.JIRA, text=charge))
    assert titre is not None
    assert len(titre) == MAX_TITLE_LENGTH


def test_the_title_travels_to_the_source() -> None:
    (source,) = sources_from((ReadRecord(provenance=provenance(), title="CDCF K20"),))

    assert source.title == "CDCF K20"


def test_a_later_read_may_add_a_title_but_never_rename_one() -> None:
    """La premiere lecture reste celle qui nomme la source : une seconde ne doit pas
    la renommer sous le lecteur."""

    sans, avec = ReadRecord(provenance=provenance()), ReadRecord(
        provenance=provenance(), title="CDCF K20"
    )

    (complete,) = sources_from((sans, avec))
    assert complete.title == "CDCF K20"

    (premiere,) = sources_from((avec, ReadRecord(provenance=provenance(), title="Autre nom")))
    assert premiere.title == "CDCF K20"
