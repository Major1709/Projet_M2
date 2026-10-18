"""L'historique des changements, de la piste jusqu'a l'ecran.

Le bouton existait depuis le premier jour et ouvrait une phrase en dur :
« L'historique n'est pas encore disponible. » La matiere, elle, etait deja ecrite --
chaque proposition, chaque approbation, chaque ecriture -- mais la piste etait en
ecriture seule.

Deux proprietes comptent plus que le reste ici, et ce sont elles que ces tests
protegent : l'historique est borne au tenant de la session, et il ne rend que des
champs choisis. Une piste d'audit qui fuit ou qui se deverse est pire qu'une absence
d'historique.
"""

from dataclasses import replace
from datetime import timedelta

from fastapi.testclient import TestClient

from app.audit.domain import AuditEvent, AuditEventType
from app.bootstrap import build_container
from app.core.config import Settings
from app.core.identity import SESSION_MODE
from app.main import create_app
from app.sessions.domain import (
    SESSION_COOKIE_NAME,
    Session,
    new_session_token,
    session_token_hash,
    utc_now,
)

EVENTS = "/api/audit/events"
TENANT = "tenant-a"


def app_for():
    settings = Settings(environment="test")
    container = build_container(settings)
    container = replace(
        container,
        settings=settings.model_copy(update={"auth_mode": SESSION_MODE}),
    )
    return create_app(settings, container), container


def signed_in(container, *, tenant_id: str = TENANT) -> str:
    token = new_session_token()
    container.sessions.create(
        Session(
            token_hash=session_token_hash(token),
            tenant_id=tenant_id,
            user_id="owner",
            expires_at=utc_now() + timedelta(hours=12),
        )
    )
    return token


def client_for(container, app, *, tenant_id: str = TENANT) -> TestClient:
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, signed_in(container, tenant_id=tenant_id))
    return client


def wrote(
    container,
    *,
    event_type: AuditEventType = AuditEventType.ACTION_PROPOSED,
    tenant_id: str = TENANT,
    details: dict | None = None,
    minutes_ago: int = 0,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        actor_user_id="owner",
        correlation_id="corr-1",
        details=details
        if details is not None
        else {
            "source_system": "confluence",
            "tool_name": "createConfluencePage",
            "action_class": "CREATE",
            "payload_hash": "a" * 64,
        },
        occurred_at=utc_now() - timedelta(minutes=minutes_ago),
    )
    container.audit.append(event)
    return event


def test_a_change_appears_in_the_history() -> None:
    app, container = app_for()
    wrote(container)

    corps = client_for(container, app).get(EVENTS).json()

    assert len(corps["events"]) == 1
    evenement = corps["events"][0]
    assert evenement["event_type"] == "ACTION_PROPOSED"
    assert evenement["tool_name"] == "createConfluencePage"
    assert evenement["source_system"] == "confluence"


def test_the_most_recent_change_comes_first() -> None:
    app, container = app_for()
    wrote(container, event_type=AuditEventType.ACTION_PROPOSED, minutes_ago=10)
    wrote(container, event_type=AuditEventType.ACTION_APPROVED, minutes_ago=1)

    corps = client_for(container, app).get(EVENTS).json()

    assert [e["event_type"] for e in corps["events"]] == [
        "ACTION_APPROVED",
        "ACTION_PROPOSED",
    ]


def test_reads_are_not_changes() -> None:
    """La piste enregistre chaque lecture MCP et chaque appel au modele. Les montrer
    ici noierait ce que la personne est venue chercher sous des centaines de lignes
    qui n'ont rien modifie."""

    app, container = app_for()
    wrote(container, event_type=AuditEventType.MCP_READ_COMPLETED)
    wrote(container, event_type=AuditEventType.LLM_INVOCATION_COMPLETED)
    wrote(container, event_type=AuditEventType.ACTION_APPROVED)

    corps = client_for(container, app).get(EVENTS).json()

    assert [e["event_type"] for e in corps["events"]] == ["ACTION_APPROVED"]


def test_the_written_identifiers_are_shown() -> None:
    """La cle Jira ou l'identifiant de page : la seule chose que la personne peut
    aller verifier elle-meme."""

    app, container = app_for()
    wrote(
        container,
        event_type=AuditEventType.MUTATION_EXECUTED,
        details={"succeeded": True, "partial": False, "external_ids": ["KAN-42"]},
    )

    corps = client_for(container, app).get(EVENTS).json()

    assert corps["events"][0]["external_ids"] == ["KAN-42"]


def test_another_tenant_history_is_not_readable() -> None:
    """La propriete qui compte le plus. Le tenant vient de la session, jamais de la
    requete : un appelant qui pourrait le choisir lirait la piste d'un autre client."""

    app, container = app_for()
    wrote(container, tenant_id="tenant-voisin")

    corps = client_for(container, app).get(EVENTS).json()

    assert corps["events"] == []


def test_the_tenant_cannot_be_chosen_by_the_caller() -> None:
    app, container = app_for()
    wrote(container, tenant_id="tenant-voisin")

    reponse = client_for(container, app).get(
        EVENTS,
        params={"tenant_id": "tenant-voisin"},
        headers={"X-Tenant-ID": "tenant-voisin"},
    )

    assert reponse.json()["events"] == []


def test_the_internal_details_do_not_leak() -> None:
    """``details`` est un objet JSON libre, alimente par du code interne qui n'a
    jamais promis de le rendre a un navigateur."""

    app, container = app_for()
    wrote(
        container,
        details={
            "source_system": "jira",
            "payload_hash": "b" * 64,
            "idempotency_key": "cle-secrete-123",
        },
    )

    corps = client_for(container, app).get(EVENTS).text

    assert "payload_hash" not in corps
    assert "cle-secrete-123" not in corps
    assert "idempotency_key" not in corps


def test_the_history_is_bounded() -> None:
    app, container = app_for()
    for _ in range(5):
        wrote(container)

    corps = client_for(container, app).get(EVENTS, params={"limit": 2}).json()

    assert len(corps["events"]) == 2


def test_an_absurd_limit_is_refused_rather_than_served() -> None:
    app, container = app_for()

    assert client_for(container, app).get(EVENTS, params={"limit": 10_000}).status_code == 422


def test_no_session_no_history() -> None:
    app, _ = app_for()

    reponse = TestClient(app).get(EVENTS)

    assert reponse.status_code == 401


def test_an_empty_history_is_an_empty_list_and_not_an_error() -> None:
    """Rien ne s'est encore passe. C'est un etat normal, pas une panne."""

    app, container = app_for()

    reponse = client_for(container, app).get(EVENTS)

    assert reponse.status_code == 200
    assert reponse.json() == {"events": []}


# --- Qui a agi ---------------------------------------------------------------------
#
# L'historique disait ce qui s'etait passe, jamais par qui. Sur un outil qui ecrit
# dans Jira et Confluence AU NOM de quelqu'un, c'est la question qu'on se pose en
# second, juste apres "qu'est-ce qui a ete ecrit".
#
# La piste n'enregistre que l'identifiant de compte, opaque et sans interet a
# l'ecran. Le nom est resolu a la lecture depuis les sessions, ou la connexion l'a
# depose -- ce qui le rend disponible pour tout l'historique deja enregistre.


def test_the_history_says_who_acted() -> None:
    app, container = app_for()
    token = signed_in(container)
    wrote(container)

    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    evenement = client.get(EVENTS).json()["events"][0]

    # Le puits en memoire ne connait pas les sessions : le nom est absent, et
    # l'action s'affiche sans attribution plutot qu'avec une attribution inventee.
    assert evenement["actor_name"] is None
    # En revanche, "c'est vous" se tranche par comparaison d'identifiants.
    assert evenement["by_you"] is True


def test_an_action_by_someone_else_is_not_attributed_to_you() -> None:
    """La confusion serait grave : approuver une ecriture engage une personne."""

    app, container = app_for()
    token = signed_in(container)
    event = AuditEvent(
        event_type=AuditEventType.ACTION_APPROVED,
        tenant_id=TENANT,
        actor_user_id="quelqu-un-d-autre",
        correlation_id="corr-1",
        details={},
    )
    container.audit.append(event)

    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    assert client.get(EVENTS).json()["events"][0]["by_you"] is False


def test_the_account_identifier_is_still_not_served() -> None:
    """Le nom entre a l'ecran, l'identifiant non. Les deux decisions sont
    independantes, et la seconde ne doit pas tomber avec la premiere."""

    app, container = app_for()
    token = signed_in(container)
    container.audit.append(
        AuditEvent(
            event_type=AuditEventType.ACTION_APPROVED,
            tenant_id=TENANT,
            actor_user_id="712020:abc-compte-secret",
            correlation_id="corr-1",
            details={},
        )
    )

    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)

    assert "abc-compte-secret" not in client.get(EVENTS).text
