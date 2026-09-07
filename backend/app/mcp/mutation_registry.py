"""Les ecritures autorisees, declarees a part des lectures.

Un registre separe plutot qu'un drapeau sur l'existant, et c'est le point de ce
module. ``ToolContract`` refuse tout contrat non-READ, et cette invariante est ce qui
rend le chemin de lecture digne de confiance : aucune erreur de saisie ne peut y
glisser une ecriture. L'assouplir pour loger les mutations aurait echange une garantie
structurelle contre un booleen. Ici l'invariante est simplement inversee -- ce registre
refuse les lectures -- de sorte que chacun garde la sienne, verifiee a la construction.

Ce qui est declare est deliberement plus etroit que ce que le serveur accepte. Une
approbation humaine ne vaut que si l'humain voit ce qu'il approuve : un sac de champs
arbitraires transforme "creer un ticket intitule X" en "ecrire n'importe quoi dans
Jira", et l'ecran d'approbation ne peut plus dire la verite. Chaque champ ecarte est
justifie a l'endroit ou il l'est.

Le schema fournisseur, lui, est celui que le serveur annonce, sans retouche : c'est
l'empreinte de derive qui s'y compare. Un schema simplifie pour la lisibilite ferait
echouer le controle a chaque appel, et un controle qui se declenche a tort finit par
etre desactive.
"""

from dataclasses import dataclass, field
from typing import Any

from app.mcp.domain import MCPBindingKind, MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.registry import (
    JIRA_SOURCE_ORIGIN,
    MCP_POLICY_VERSION,
    schema_sha256,
)

# La version de politique des ecritures est distincte de celle des lectures : les deux
# surfaces evoluent separement, et une proposition epinglee a l'une ne doit pas etre
# invalidee parce que l'autre a bouge.
MCP_MUTATION_POLICY_VERSION = f"{MCP_POLICY_VERSION}-MUT-r1"


@dataclass(frozen=True)
class MutationToolContract:
    """Un outil d'ecriture approuve, avec les deux schemas qui l'encadrent.

    ``public_input_schema`` est ce que le modele propose et ce que l'humain approuve.
    ``provider_input_schema`` est ce que le serveur declare, et sert uniquement
    d'ancrage a l'empreinte de derive.
    """

    server_id: str
    provider: MCPProvider
    source_system: SourceSystem
    source_origin: str
    tool_name: str
    binding_kind: MCPBindingKind
    action_class: ToolActionClass
    public_input_schema: dict[str, Any]
    provider_input_schema: dict[str, Any]
    policy_version: str = MCP_MUTATION_POLICY_VERSION
    provider_input_schema_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        # L'invariante inverse de celle du registre de lecture. Les deux se verifient
        # a la construction, donc aucun des deux registres ne peut accueillir ce qui
        # appartient a l'autre.
        if self.action_class == ToolActionClass.READ:
            raise ValueError("The mutation registry cannot contain reads")
        if not self.action_class.is_external_mutation:
            raise ValueError(f"{self.tool_name} is not an external mutation")
        # Le liant est injecte cote serveur apres l'approbation. Un schema public qui
        # nommerait cloudId laisserait le modele -- ou un humain distrait -- designer
        # un autre site que celui du locataire.
        if "cloudId" in self.public_input_schema.get("properties", {}):
            raise ValueError(f"{self.tool_name} must not expose cloudId publicly")
        if self.public_input_schema.get("additionalProperties") is not False:
            raise ValueError(f"{self.tool_name} must close its public schema")
        object.__setattr__(
            self,
            "provider_input_schema_sha256",
            schema_sha256(self.provider_input_schema),
        )


# Ce que le serveur Atlassian annonce pour createJiraIssue, releve en direct le
# 01/09/2026 et recopie sans retouche. Sa forme canonique -- annotations retirees,
# cles triees -- est stable, donc l'empreinte calculee ici est celle du schema brut.
_CREATE_JIRA_ISSUE_PROVIDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cloudId", "issueTypeName", "projectKey", "summary"],
    "properties": {
        "cloudId": {"type": "string"},
        "projectKey": {"type": "string"},
        "issueTypeName": {"type": "string"},
        "summary": {"type": "string"},
        "description": {
            "anyOf": [
                {"type": "string", "maxLength": 32000},
                {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["type"],
                    "properties": {"type": {"type": "string", "const": "doc"}},
                },
            ]
        },
        "parent": {"type": "string"},
        "assignee_account_id": {"type": "string"},
        "additional_fields": {"type": "object", "additionalProperties": {}},
        "transition": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        },
        "contentFormat": {"type": "string", "enum": ["adf", "markdown"]},
        "responseContentFormat": {"type": "string", "enum": ["adf", "markdown"]},
    },
}

# Quatre champs, et pas un de plus.
#
# ``additional_fields`` est ecarte en premier, et c'est le refus qui compte : le
# serveur le decrit comme le SEUL moyen de fixer la priorite, les etiquettes, les
# composants et n'importe quel champ personnalise. C'est-a-dire un sac ouvert. Une
# proposition qui le porterait afficherait "creer un ticket intitule X" a l'humain
# tout en pouvant ecrire ailleurs, et l'approbation ne voudrait plus rien dire.
#
# ``parent``, ``assignee_account_id`` et ``transition`` sont ecartes pour la meme
# raison sous une forme plus douce : ils engagent quelqu'un d'autre ou deplacent un
# ticket dans un flux, ce qu'une premiere version n'a pas besoin de faire. Ils
# pourront revenir un par un, chacun avec sa place dans l'ecran d'approbation.
#
# ``contentFormat`` est ecarte parce que le defaut -- markdown -- est le bon, et
# qu'un format choisi par le modele est un levier de plus pour rien.
_CREATE_JIRA_ISSUE_PUBLIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["projectKey", "issueTypeName", "summary"],
    "properties": {
        # Borne et ancree : une cle de projet Jira est courte et en majuscules. Le
        # motif n'est pas de la cosmetique, il empeche qu'une valeur libre parte vers
        # le fournisseur au seul motif qu'elle est une chaine.
        "projectKey": {"type": "string", "pattern": "^[A-Z][A-Z0-9]{0,9}$"},
        "issueTypeName": {"type": "string", "minLength": 1, "maxLength": 100},
        # Le titre que l'humain lira dans l'ecran d'approbation. Jira le tronque a
        # 255 ; le borner ici evite une ecriture partielle silencieuse.
        "summary": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "maxLength": 32000},
    },
}

_JIRA_MUTATIONS = (
    MutationToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="createJiraIssue",
        binding_kind=MCPBindingKind.JIRA,
        action_class=ToolActionClass.CREATE,
        public_input_schema=_CREATE_JIRA_ISSUE_PUBLIC_SCHEMA,
        provider_input_schema=_CREATE_JIRA_ISSUE_PROVIDER_SCHEMA,
    ),
)


class MCPMutationRegistry:
    """Les ecritures declarees, indexees par (systeme, nom d'outil).

    Vide est un etat legitime et non une panne : un deploiement qui n'autorise aucune
    ecriture construit ce registre sans contrat, et tout refus qui en decoule est
    alors la bonne reponse.
    """

    def __init__(self, contracts: tuple[MutationToolContract, ...] | None = None) -> None:
        selected = _JIRA_MUTATIONS if contracts is None else contracts
        indexed: dict[tuple[SourceSystem, str], MutationToolContract] = {}
        for contract in selected:
            key = (contract.source_system, contract.tool_name)
            if key in indexed:
                raise ValueError("Duplicate MCP mutation contract")
            indexed[key] = contract
        self._contracts = indexed

    @property
    def contracts(self) -> tuple[MutationToolContract, ...]:
        return tuple(self._contracts.values())

    def get(self, source_system: SourceSystem, tool_name: str) -> MutationToolContract | None:
        return self._contracts.get((source_system, tool_name))


__all__ = [
    "MCP_MUTATION_POLICY_VERSION",
    "MCPMutationRegistry",
    "MutationToolContract",
]
