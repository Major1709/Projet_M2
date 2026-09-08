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

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from app.mcp.domain import MCPBindingKind, MCPProvider, ToolActionClass
from app.mcp.domain import MCPReadSourceSystem as SourceSystem
from app.mcp.registry import (
    CONFLUENCE_SOURCE_ORIGIN,
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
    # Ce que la cible designe, en clair pour l'ecran d'approbation.
    resource_type: str = "issue"
    # Quel argument PUBLIC nomme la ressource visee, et lequel nomme son conteneur.
    # Declares par le contrat plutot que devines par l'agent : le jour ou une ecriture
    # Confluence arrivera, elle dira "pageId" et "spaceKey" sans qu'aucun code en
    # amont n'ait a connaitre le vocabulaire de chaque produit.
    #
    # Une creation n'a pas de ressource -- elle la fabrique -- et une modification n'a
    # pas besoin de conteneur : c'est cette asymetrie qui decide, plus bas, quelle
    # revalidation de permission s'applique.
    resource_argument: str | None = None
    container_argument: str | None = None
    # L'argument qui porte le titre montre a l'humain. Faute de quoi l'ecran
    # d'approbation annonce une action sans dire sur quoi elle porte.
    title_argument: str | None = None
    # Arguments que le SERVEUR impose, au meme titre que le liant : le modele ne les
    # propose pas et l'humain ne les approuve pas, parce qu'ils ne decrivent pas
    # l'action mais la facon de la transmettre.
    #
    # Le cas concret est le format du corps Confluence. Le fournisseur interprete le
    # corps en HTML par defaut, et demande alors de passer par un guide de format
    # avant d'ecrire. Laisser ce choix au modele, c'est accepter qu'un jour il ecrive
    # du markdown dans un champ lu comme du HTML : la page s'affiche alors avec ses
    # asterisques et ses dieses en clair, et personne ne l'a decide.
    fixed_provider_arguments: Mapping[str, Any] = field(default_factory=dict)
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
        # Une creation nomme son conteneur, une modification nomme sa ressource. Sans
        # cela la revalidation de permission n'a rien a relire et refuse tout, ce qui
        # se decouvrirait a la premiere execution plutot qu'au demarrage.
        if self.action_class == ToolActionClass.CREATE:
            if self.container_argument is None:
                raise ValueError(f"{self.tool_name} must name its container argument")
        elif self.resource_argument is None:
            raise ValueError(f"{self.tool_name} must name its resource argument")
        for nom in (self.resource_argument, self.container_argument, self.title_argument):
            if nom is not None and nom not in self.public_input_schema.get("properties", {}):
                raise ValueError(f"{self.tool_name} names {nom}, which it does not accept")
        # Un argument impose qui figurerait aussi dans le schema public serait ecrase
        # en silence : l'humain approuverait une valeur, une autre partirait.
        for nom in self.fixed_provider_arguments:
            if nom in self.public_input_schema.get("properties", {}):
                raise ValueError(f"{self.tool_name} both fixes and offers {nom}")
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

# --- addCommentToJiraIssue --------------------------------------------------------

_ADD_COMMENT_PROVIDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["cloudId", "commentBody", "issueIdOrKey"],
    "properties": {
        "cloudId": {"type": "string"},
        "issueIdOrKey": {"type": "string"},
        "commentBody": {"type": "string"},
        "commentId": {"type": "string", "maxLength": 18},
        "commentVisibility": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "value"],
            "properties": {
                "type": {"type": "string", "enum": ["group", "role"]},
                "value": {"type": "string"},
            },
        },
        "contentFormat": {"type": "string", "enum": ["adf", "markdown"]},
        "responseContentFormat": {"type": "string", "enum": ["adf", "markdown"]},
    },
}

# Deux champs. Les deux exclusions sont les plus importantes du fichier.
#
# ``commentId`` transforme l'ajout en MODIFICATION d'un commentaire existant. Un
# contrat annonce comme "ajouter un commentaire" pourrait alors en reecrire un autre,
# ecrit par quelqu'un d'autre, sans que l'ecran d'approbation le laisse voir. C'est le
# genre de champ qui ne se remarque pas dans un schema et qui change la nature de
# l'action.
#
# ``commentVisibility`` restreint qui verra le commentaire, a un groupe ou a un role.
# Un humain qui approuve "ajouter un commentaire" ne s'attend pas a ce qu'il soit
# cache a la plupart des gens -- et un commentaire invisible est une facon discrete
# d'ecrire dans un ticket.
_ADD_COMMENT_PUBLIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issueIdOrKey", "commentBody"],
    "properties": {
        "issueIdOrKey": {"type": "string", "pattern": "^[A-Z][A-Z0-9]{0,9}-[0-9]{1,10}$"},
        "commentBody": {"type": "string", "minLength": 1, "maxLength": 32000},
    },
}


# --- transitionJiraIssue ----------------------------------------------------------

# Recopie depuis la forme canonique du schema que le serveur annonce, generee
# plutot que transcrite : historyMetadata imbrique une quinzaine de champs, et
# une virgule oubliee a la main aurait fait diverger l'empreinte sans que la
# cause saute aux yeux.
# Recopie depuis la forme canonique du schema que le serveur annonce, generee
# plutot que transcrite : historyMetadata imbrique une quinzaine de champs, et une
# virgule oubliee a la main aurait fait diverger l'empreinte sans que la cause
# saute aux yeux. Le premier essai a d'ailleurs diverge, pour avoir simplifie ce
# bloc en un simple {"type": "object"}.
_TRANSITION_PROVIDER_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "cloudId": {
            "type": "string"
        },
        "fields": {
            "additionalProperties": {},
            "type": "object"
        },
        "historyMetadata": {
            "additionalProperties": False,
            "properties": {
                "activityDescription": {
                    "type": "string"
                },
                "activityDescriptionKey": {
                    "type": "string"
                },
                "actor": {
                    "additionalProperties": False,
                    "properties": {
                        "avatarUrl": {
                            "type": "string"
                        },
                        "displayName": {
                            "type": "string"
                        },
                        "id": {
                            "type": "string"
                        },
                        "type": {
                            "type": "string"
                        },
                        "url": {
                            "type": "string"
                        }
                    },
                    "type": "object"
                },
                "cause": {
                    "additionalProperties": False,
                    "properties": {
                        "avatarUrl": {
                            "type": "string"
                        },
                        "displayName": {
                            "type": "string"
                        },
                        "id": {
                            "type": "string"
                        },
                        "type": {
                            "type": "string"
                        },
                        "url": {
                            "type": "string"
                        }
                    },
                    "type": "object"
                },
                "description": {
                    "type": "string"
                },
                "descriptionKey": {
                    "type": "string"
                },
                "emailDescription": {
                    "type": "string"
                },
                "emailDescriptionKey": {
                    "type": "string"
                },
                "extraData": {
                    "additionalProperties": {
                        "type": "string"
                    },
                    "type": "object"
                },
                "generator": {
                    "additionalProperties": False,
                    "properties": {
                        "avatarUrl": {
                            "type": "string"
                        },
                        "displayName": {
                            "type": "string"
                        },
                        "id": {
                            "type": "string"
                        },
                        "type": {
                            "type": "string"
                        },
                        "url": {
                            "type": "string"
                        }
                    },
                    "type": "object"
                },
                "type": {
                    "type": "string"
                }
            },
            "type": "object"
        },
        "issueIdOrKey": {
            "type": "string"
        },
        "transition": {
            "additionalProperties": False,
            "properties": {
                "id": {
                    "type": "string"
                }
            },
            "required": [
                "id"
            ],
            "type": "object"
        },
        "update": {
            "additionalProperties": {
                "items": {
                    "additionalProperties": {},
                    "type": "object"
                },
                "type": "array"
            },
            "type": "object"
        }
    },
    "required": [
        "cloudId",
        "issueIdOrKey",
        "transition"
    ],
    "type": "object"
}

# Le ticket et la transition, rien d'autre.
#
# ``fields`` et ``update`` permettent de modifier n'importe quel champ AU PASSAGE
# d'une transition. C'est le meme sac ouvert que ``additional_fields`` sous un autre
# nom, et il est plus trompeur ici : l'humain approuve "passer KAN-2 en Termine" et
# l'appel pourrait en profiter pour reassigner le ticket ou vider sa description.
#
# ``historyMetadata`` ecrit dans l'historique du ticket une provenance choisie par
# l'appelant. Laisser un modele composer ce que Jira affichera comme l'origine d'un
# changement reviendrait a lui laisser signer a notre place.
_TRANSITION_PUBLIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issueIdOrKey", "transition"],
    "properties": {
        "issueIdOrKey": {"type": "string", "pattern": "^[A-Z][A-Z0-9]{0,9}-[0-9]{1,10}$"},
        "transition": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id"],
            # L'identifiant vient de getTransitionsForJiraIssue, une lecture. Le modele
            # doit donc l'avoir lu avant de proposer : il ne peut pas inventer un
            # numero et esperer qu'il tombe juste.
            "properties": {"id": {"type": "string", "pattern": "^[0-9]{1,10}$"}},
        },
    },
}


# --- Confluence ------------------------------------------------------------------
#
# Deux differences avec Jira changent la facon de declarer ces contrats.
#
# Le corps est interprete en HTML par defaut, et le fournisseur demande alors de
# passer par un guide de format avant d'ecrire. contentFormat est donc IMPOSE a
# "markdown" cote serveur : sans cela, un modele qui ecrit du markdown produirait une
# page affichant ses asterisques et ses dieses en clair.
#
# Une mise a jour REMPLACE le corps entier -- ce n'est pas un ajout. C'est ce qui rend
# le diff indispensable ici : approuver "modifier la page" sans voir ce qui disparait
# n'aurait aucun sens.

_CREATE_PAGE_PROVIDER_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "body": {
            "type": "string"
        },
        "cloudId": {
            "type": "string"
        },
        "contentFormat": {
            "enum": [
                "adf",
                "html",
                "markdown"
            ],
            "type": "string"
        },
        "contentType": {
            "enum": [
                "blog",
                "page"
            ],
            "type": "string"
        },
        "isPrivate": {
            "type": "boolean"
        },
        "parentId": {
            "type": "string"
        },
        "spaceId": {
            "type": "string"
        },
        "status": {
            "enum": [
                "current",
                "draft"
            ],
            "type": "string"
        },
        "subtype": {
            "enum": [
                "live"
            ],
            "type": "string"
        },
        "title": {
            "type": "string"
        }
    },
    "required": [
        "body",
        "cloudId",
        "spaceId"
    ],
    "type": "object"
}


_UPDATE_PAGE_PROVIDER_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "body": {
            "type": "string"
        },
        "cloudId": {
            "type": "string"
        },
        "contentFormat": {
            "enum": [
                "adf",
                "html",
                "markdown"
            ],
            "type": "string"
        },
        "contentType": {
            "enum": [
                "blog",
                "page"
            ],
            "type": "string"
        },
        "includeBody": {
            "type": "boolean"
        },
        "pageId": {
            "type": "string"
        },
        "parentId": {
            "type": "string"
        },
        "spaceId": {
            "maxLength": 255,
            "type": "string"
        },
        "status": {
            "enum": [
                "current",
                "draft"
            ],
            "type": "string"
        },
        "title": {
            "type": "string"
        },
        "versionMessage": {
            "type": "string"
        }
    },
    "required": [
        "body",
        "cloudId",
        "pageId"
    ],
    "type": "object"
}


# Trois champs. spaceId accepte aussi une cle d'espace ("ENG"), que le fournisseur
# resout lui-meme, donc le modele peut nommer l'espace comme un humain le ferait.
#
# ``isPrivate`` est ecarte en premier : un humain qui approuve "creer une page dans
# l'espace ENG" ne s'attend pas a ce qu'elle soit invisible pour l'equipe. Une page
# privee creee au nom de quelqu'un est une facon discrete d'ecrire.
#
# ``status`` permettrait de publier un brouillon, ``contentType`` de produire un
# billet de blog au lieu d'une page, ``parentId`` de nicher la page ailleurs que la
# ou l'approbation le laisse croire, et ``subtype`` de changer sa nature. Tous
# deplacent ou transforment ce que l'humain croit approuver.
_CREATE_PAGE_PUBLIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["spaceId", "title", "body"],
    "properties": {
        "spaceId": {"type": "string", "minLength": 1, "maxLength": 255},
        "title": {"type": "string", "minLength": 1, "maxLength": 255},
        "body": {"type": "string", "minLength": 1, "maxLength": 100_000},
    },
}

# ``title`` est optionnel ici : une mise a jour peut ne toucher que le corps.
#
# ``spaceId`` et ``parentId`` sont ecartes, et c'est le refus le plus important de ce
# contrat : tous deux DEPLACENT la page. L'humain approuve "mettre a jour cette page"
# et elle changerait d'espace ou de parent sans que rien ne l'annonce.
#
# ``status`` depublierait la page, ``versionMessage`` laisserait le modele ecrire dans
# l'historique de Confluence ce qui ressemblerait a une justification humaine.
_UPDATE_PAGE_PUBLIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pageId", "body"],
    "properties": {
        "pageId": {"type": "string", "minLength": 1, "maxLength": 255},
        "title": {"type": "string", "minLength": 1, "maxLength": 255},
        "body": {"type": "string", "minLength": 1, "maxLength": 100_000},
    },
}

# Impose des deux cotes, pour la raison donnee en tete de section.
_MARKDOWN_BODY = MappingProxyType({"contentFormat": "markdown"})

_CONFLUENCE_MUTATIONS = (
    MutationToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="createConfluencePage",
        binding_kind=MCPBindingKind.CONFLUENCE,
        action_class=ToolActionClass.CREATE,
        public_input_schema=_CREATE_PAGE_PUBLIC_SCHEMA,
        provider_input_schema=_CREATE_PAGE_PROVIDER_SCHEMA,
        resource_type="page",
        container_argument="spaceId",
        title_argument="title",
        fixed_provider_arguments=_MARKDOWN_BODY,
    ),
    MutationToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.CONFLUENCE,
        source_origin=CONFLUENCE_SOURCE_ORIGIN,
        tool_name="updateConfluencePage",
        binding_kind=MCPBindingKind.CONFLUENCE,
        action_class=ToolActionClass.UPDATE,
        public_input_schema=_UPDATE_PAGE_PUBLIC_SCHEMA,
        provider_input_schema=_UPDATE_PAGE_PROVIDER_SCHEMA,
        resource_type="page",
        resource_argument="pageId",
        title_argument="title",
        fixed_provider_arguments=_MARKDOWN_BODY,
    ),
)


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
        container_argument="projectKey",
        title_argument="summary",
    ),
    MutationToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="addCommentToJiraIssue",
        binding_kind=MCPBindingKind.JIRA,
        # UPDATE et non CREATE, bien qu'un commentaire soit cree. Ce qui decide n'est
        # pas la grammaire mais la revalidation : ce qu'il faut confirmer juste avant
        # d'ecrire, c'est que LE TICKET existe toujours et n'a pas bouge depuis que
        # l'humain a approuve. Le classer en creation ferait verifier le projet, ce
        # qui ne dit rien du ticket.
        action_class=ToolActionClass.UPDATE,
        public_input_schema=_ADD_COMMENT_PUBLIC_SCHEMA,
        provider_input_schema=_ADD_COMMENT_PROVIDER_SCHEMA,
        resource_argument="issueIdOrKey",
    ),
    MutationToolContract(
        server_id="atlassian-rovo",
        provider=MCPProvider.ATLASSIAN,
        source_system=SourceSystem.JIRA,
        source_origin=JIRA_SOURCE_ORIGIN,
        tool_name="transitionJiraIssue",
        binding_kind=MCPBindingKind.JIRA,
        action_class=ToolActionClass.UPDATE,
        public_input_schema=_TRANSITION_PUBLIC_SCHEMA,
        provider_input_schema=_TRANSITION_PROVIDER_SCHEMA,
        resource_argument="issueIdOrKey",
    ),
)


class MCPMutationRegistry:
    """Les ecritures declarees, indexees par (systeme, nom d'outil).

    Vide est un etat legitime et non une panne : un deploiement qui n'autorise aucune
    ecriture construit ce registre sans contrat, et tout refus qui en decoule est
    alors la bonne reponse.
    """

    def __init__(self, contracts: tuple[MutationToolContract, ...] | None = None) -> None:
        selected = (
            (*_JIRA_MUTATIONS, *_CONFLUENCE_MUTATIONS) if contracts is None else contracts
        )
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
