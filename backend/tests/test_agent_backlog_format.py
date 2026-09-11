"""Le cahier des charges : que le modele recoive le processus, et le mette en forme.

Trois defauts sont couverts ici, et tous les trois ont ete trouves en production
plutot qu'au tableau -- ce qui est la raison d'etre de ce fichier.

Le premier etait muet et c'est le plus grave : ``extractFigmaProcess`` ne rend
AUCUN bloc de texte, seulement une charge structuree. La boucle n'affichait que les
blocs, si bien que le modele recevait un encadrement de source vide, puis redigeait
un cahier des charges a partir de rien -- en citant Figma. Une reponse inventee sous
une provenance exacte est pire qu'une absence de reponse.

Le deuxieme est une question de POSITION. Le format decrit en tete de conversation
etait ignore : le modele rendait du HTML a sections numerotees. Le meme texte, rappele
juste apres la lecture, produit les sept colonnes. Les tests ci-dessous verifient donc
ou le rappel se trouve, pas seulement qu'il existe.

Le troisieme etait un plafond : 1 024 jetons de redaction, alors qu'un tableau de
vingt-trois lignes n'y tient pas. L'echec revenait vide, sans rien qui dise pourquoi.
"""

from typing import Any

import pytest

from app.agent.read_workflow import (
    BACKLOG_COMPLETION_TOKENS,
    BACKLOG_FORMAT_TURN,
    BACKLOG_READ_TURN,
    MAX_CREDIBLE_STEPS,
    AgentReadWorkflow,
    _bounded,
    _flattened,
    _step_count,
    _wants_backlog,
)
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.ports import RemoteContentBlock, RemoteToolResult
from tests.test_agent_read_workflow import (
    ScriptedProvider,
    agent_for,
    answered,
    ask,
    proposing,
)
from tests.test_mcp_read_workflow import workflow_for

PROCESSUS = {
    "file": {"key": "UVQmgXGaZC5vrtaQRU5nvo", "name": "ACCESA - Virement par empreinte"},
    "steps": [
        {"id": "1:38", "kind": "start", "label": "START"},
        {"id": "1:39", "kind": "step", "label": "Acceder au Menu\nVirement"},
        {"id": "1:40", "kind": "end", "label": "END"},
    ],
    "transitions": [],
    "notes": [],
}

DEMANDE = "Genere le cahier des charges du processus Virement par empreinte."


def process_reads(payload: Any = None, *, text: str | None = None):
    """Une lecture de processus telle que le serveur la rend REELLEMENT.

    Le detail qui compte : ``content`` est vide. Un double qui remplirait les deux
    champs aurait laisse passer le defaut d'origine sans rien dire.
    """

    workflow, _, _ = workflow_for(
        SourceSystem.FIGMA,
        "extractFigmaProcess",
        result=RemoteToolResult(
            content=((RemoteContentBlock(kind="text", text=text),) if text else ()),
            structured_content=PROCESSUS if payload is None else payload,
        ),
    )
    return workflow


def reading_process(file_key: str = "UVQmgXGaZC5vrtaQRU5nvo", **changes: Any):
    return proposing("extractFigmaProcess", {"fileKey": file_key}, **changes)


# --- Le contenu doit arriver au modele --------------------------------------------


def test_a_read_with_only_a_structured_payload_is_still_shown() -> None:
    """Le defaut d'origine : observation vide, et un cahier des charges invente."""

    provider = ScriptedProvider(reading_process(), answered("| ... |"))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE)

    observation = provider.requests[1].messages[-2]["content"]
    assert '"label"' in observation
    assert "START" in observation
    assert "END" in observation


def test_text_blocks_still_win_when_a_read_provides_both() -> None:
    """Le repli ne doit pas court-circuiter le rendu ordinaire, ni le doubler."""

    provider = ScriptedProvider(reading_process(), answered("ok"))
    agent = agent_for(provider, process_reads(text='{"depuis": "un bloc de texte"}'))

    ask(agent, question=DEMANDE)

    observation = provider.requests[1].messages[-2]["content"]
    assert "un bloc de texte" in observation
    assert '"kind"' not in observation


def test_a_payload_that_cannot_be_serialised_renders_as_nothing() -> None:
    """Le repli ne doit pas pouvoir emporter la question.

    En pratique le chemin de lecture rejette deja une charge non serialisable avant
    d'arriver ici -- ce test le constate plutot que de le supposer, et garde la
    defense pour le jour ou cette garantie amont changerait.
    """

    texte, tronque = AgentReadWorkflow._render_payload({"steps": {1, 2}})

    assert (texte, tronque) == ("", False)


def test_a_line_break_in_a_label_does_not_reach_the_table_as_two_characters() -> None:
    """Une etiquette Figma coupee sur deux lignes devenait la sequence "\\n" recopiee
    telle quelle dans une cellule, ou elle s'affichait litteralement."""

    assert _flattened("Acceder au Menu\nVirement") == "Acceder au Menu Virement"
    assert _flattened({"a": ["x\n  y"]}) == {"a": ["x y"]}
    # Le texte est replie, jamais ampute.
    assert _flattened("Menu\nVirement").replace(" ", "") == "MenuVirement"


def test_flattening_leaves_what_is_not_a_text_alone() -> None:
    assert _flattened({"n": 3, "ok": True, "rien": None}) == {"n": 3, "ok": True, "rien": None}


# --- Le rappel de forme, et sa position -------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Genere le CAHIER DES CHARGES de ce processus",
        "cahier de charge du processus Paiement",
        "Fais-moi le backlog de la maquette",
        "Sors les user stories du parcours",
    ],
)
def test_a_backlog_is_recognised_whatever_the_spelling(question: str) -> None:
    """Sans repli des accents et de la casse, l'utilisateur devrait deviner la
    graphie exacte attendue par une detection qu'il ne voit pas."""

    assert _wants_backlog(question)


@pytest.mark.parametrize(
    "question",
    ["Que contient le ticket KAN-1 ?", "Resume-moi ce processus Figma"],
)
def test_an_ordinary_question_is_not_forced_into_a_table(question: str) -> None:
    """Le rappel impose une forme. L'imposer a qui ne l'a pas demandee rendrait
    illisible une reponse qui allait bien."""

    assert not _wants_backlog(question)


def test_the_format_is_recalled_after_the_process_and_not_before() -> None:
    """Le coeur de la correction. Le meme texte place en tete etait ignore ; c'est
    sa position -- juste avant la redaction -- qui le fait suivre."""

    provider = ScriptedProvider(reading_process(), answered("| ... |"))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE)

    premier_tour = provider.requests[0].messages
    assert not any("Rappel de forme" in str(m["content"]) for m in premier_tour)
    dernier = provider.requests[1].messages[-1]
    assert dernier["role"] == "system"
    assert "Rappel de forme" in dernier["content"]
    assert "| Bloc fonctionnel | Ref. PBS |" in dernier["content"]


def test_the_expected_number_of_rows_is_named() -> None:
    """Une consigne qualitative ne corrigeait pas la troncature : le modele rendait
    deux a huit lignes pour vingt-trois etapes, differemment a chaque essai."""

    provider = ScriptedProvider(reading_process(), answered("| ... |"))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE)

    assert "compte 3 etapes" in provider.requests[1].messages[-1]["content"]


def test_an_uncountable_process_is_recalled_without_a_number() -> None:
    """Un nombre faux serait pire que pas de nombre : il ferait inventer des lignes
    pour l'atteindre."""

    assert _step_count("aucun marqueur ici") is None
    assert _step_count('"kind"' * (MAX_CREDIBLE_STEPS + 1)) is None
    assert _step_count('"kind": "start" "kind": "end"') == 2


def test_the_format_is_recalled_once_even_after_two_reads() -> None:
    """Le repeter ferait grossir le fil sans rien ajouter : c'est sa position qui
    compte, pas le nombre de fois qu'il est dit."""

    provider = ScriptedProvider(
        reading_process(),
        reading_process("j21uCB2ha6BHMYk8WJ1ovp", call_id="call_2"),
        answered("| ... |"),
    )
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE)

    envoye = [
        m
        for m in provider.requests[-1].messages
        if m["role"] == "system" and "Rappel de forme" in str(m["content"])
    ]
    assert len(envoye) == 1


def test_no_format_is_imposed_on_a_question_that_did_not_ask_for_one() -> None:
    provider = ScriptedProvider(reading_process(), answered("Ce processus decrit ..."))
    agent = agent_for(provider, process_reads())

    ask(agent, question="Resume-moi ce processus.")

    assert not any("Rappel de forme" in str(m["content"]) for m in provider.requests[-1].messages)


# --- Le choix de l'outil, et le budget de redaction --------------------------------


def test_the_reading_advice_is_given_only_when_maquettes_exist() -> None:
    """Le conseil nomme la liste des maquettes indexees. Sans annuaire, il
    renverrait a une liste absente."""

    provider = ScriptedProvider(answered("..."))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE)

    assert not any(BACKLOG_READ_TURN in str(m["content"]) for m in provider.requests[0].messages)


def test_a_backlog_is_given_room_to_be_written() -> None:
    """Vingt-trois lignes de sept colonnes ne tiennent pas dans le defaut de chat.
    Pire, l'echec etait muet : les modeles a raisonnement depensent ce meme budget a
    reflechir, donc le plafond tombait avant le premier caractere."""

    provider = ScriptedProvider(reading_process(), answered("| ... |"))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE, max_completion_tokens=1_024)

    assert provider.requests[0].max_completion_tokens == BACKLOG_COMPLETION_TOKENS


def test_an_ordinary_question_keeps_the_budget_it_was_given() -> None:
    """L'accorder partout ferait payer a chaque question le cout du cas le plus
    lourd, alors qu'une reponse de chat n'en a pas besoin."""

    provider = ScriptedProvider(answered("KAN-1 parle de connexion."))
    agent = agent_for(provider, process_reads())

    ask(agent, question="Que dit KAN-1 ?", max_completion_tokens=1_024)

    assert provider.requests[0].max_completion_tokens == 1_024


def test_a_caller_asking_for_more_than_the_backlog_budget_keeps_it() -> None:
    provider = ScriptedProvider(reading_process(), answered("| ... |"))
    agent = agent_for(provider, process_reads())

    ask(agent, question=DEMANDE, max_completion_tokens=16_384)

    assert provider.requests[0].max_completion_tokens == 16_384


# --- Le budget d'observation --------------------------------------------------------


def test_a_long_payload_is_bounded_and_says_so() -> None:
    """Un modele qui ne peut pas savoir qu'il a recu un fragment repondra comme s'il
    avait recu le tout."""

    texte, tronque = _bounded("x" * 10_000)

    assert tronque is True
    assert "lecture tronquee" in texte


def test_the_recalled_format_names_the_seven_columns_in_order() -> None:
    """Ces colonnes sont celles de la page Confluence reelle de l'equipe. Les
    inventer ou en changer l'ordre produirait un document a retaper."""

    attendu = (
        "| Bloc fonctionnel | Ref. PBS | Userstory | Description | "
        "Criteres d'acceptation - Contexte | Criteres d'acceptation - Scenario | "
        "Remarques |"
    )

    assert attendu in BACKLOG_FORMAT_TURN
    # La reference PBS est attribuee par l'equipe : en inventer une creerait un
    # renvoi vers un element qui n'existe pas.
    assert "Ref. PBS : laisse VIDE" in BACKLOG_FORMAT_TURN


def test_the_recalled_format_requires_both_halves_of_the_gherkin() -> None:
    """Mesure : sans cette exigence, la colonne Scenario s'arretait au declencheur,
    et un critere sans "Alors" ne dit pas a quoi on reconnait que ca marche."""

    assert 'le mot "Alors" doit figurer dans chaque cellule' in BACKLOG_FORMAT_TURN


def test_the_body_of_the_page_is_the_table_itself() -> None:
    """Sans cette phrase, le modele proposait une page dont le corps annonçait le
    cahier des charges en une ligne, sans le contenir."""

    assert "tableau EST le corps de la page" in BACKLOG_FORMAT_TURN
    assert "markdown et non en HTML" in BACKLOG_FORMAT_TURN


def test_the_reading_advice_names_the_extractor_and_refuses_the_others() -> None:
    """getFigmaFile rend un arbre de formes dans l'ordre du dessin ; l'extracteur
    suit les connecteurs. Un backlog tire du premier melange les etapes."""

    assert "extractFigmaProcess" in BACKLOG_READ_TURN
    assert "getFigmaFile" in BACKLOG_READ_TURN
    assert "findFigmaFrame" in BACKLOG_READ_TURN


def test_the_workflow_exposes_what_the_tests_lean_on() -> None:
    """Garde-fou : ces noms sont ceux que la boucle appelle, et un renommage
    silencieux ferait passer les tests ci-dessus sur du code mort."""

    assert hasattr(AgentReadWorkflow, "_render_payload")
    assert hasattr(AgentReadWorkflow, "_render")


# --- L'exemple travaille, il ne decore pas ------------------------------------------
#
# Mesure : decrite, la regle du "Alors" tenait sur cinq lignes de scenario sur sept.
# Les deux qui la perdaient etaient les lignes d'OUVERTURE de bloc -- celles ou le
# modele vient d'ecrire la userstory et la description. Un exemple montrant les deux
# cas coute moins de mots qu'un paragraphe et se suit mieux.


def test_the_worked_example_shows_a_block_of_two_lines() -> None:
    """Un exemple d'une seule ligne n'apprendrait pas le regroupement, qui est
    justement ce qui se passe entre la premiere ligne et la suivante."""

    lignes = [
        x
        for x in BACKLOG_FORMAT_TURN.splitlines()
        if x.startswith("| ") and "Bloc fonctionnel |" not in x and "---" not in x
    ]

    assert len(lignes) == 2


def test_both_example_lines_carry_the_second_half_of_the_gherkin() -> None:
    """Y compris la premiere, qui est precisement celle qui l'oubliait."""

    lignes = [
        x
        for x in BACKLOG_FORMAT_TURN.splitlines()
        if x.startswith("| ") and "Bloc fonctionnel |" not in x and "---" not in x
    ]

    for ligne in lignes:
        assert "Lorsque " in ligne
        assert " Alors " in ligne


def test_the_continuation_line_leaves_its_first_three_cells_empty() -> None:
    """C'est ce vide qui rattache la ligne au bloc du dessus, et c'est ce que
    l'exemple doit rendre visible d'un coup d'oeil."""

    lignes = [
        x
        for x in BACKLOG_FORMAT_TURN.splitlines()
        if x.startswith("| ") and "Bloc fonctionnel |" not in x and "---" not in x
    ]
    cellules = [c.strip() for c in lignes[1].strip().strip("|").split("|")]

    assert cellules[:4] == ["", "", "", ""]
    assert cellules[4] and cellules[5]


def test_the_example_says_it_is_a_shape_and_not_a_subject() -> None:
    """Sans cet avertissement, un exemple concret invite a en reprendre le sujet --
    et un cahier des charges de virement parlerait de consultation de solde."""

    assert "n'en recopie ni les mots ni le sujet" in BACKLOG_FORMAT_TURN.lower().replace(
        "N'EN", "n'en"
    )


def test_every_example_line_has_the_seven_columns() -> None:
    """Un exemple mal forme apprendrait le mauvais gabarit, et le modele suit
    l'exemple avant la description."""

    lignes = [
        x
        for x in BACKLOG_FORMAT_TURN.splitlines()
        if x.startswith("| ") and "Bloc fonctionnel |" not in x and "---" not in x
    ]

    for ligne in lignes:
        assert len(ligne.strip().strip("|").split("|")) == 7
