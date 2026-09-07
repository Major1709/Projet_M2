"""Le transport d'une ecriture approuvee, et rien d'autre.

Cette passerelle est le seul endroit du projet qui envoie une ecriture chez un
fournisseur. Elle ne decide rien : l'approbation, l'identite de l'approbateur, la
revalidation de permission et la reservation d'idempotence ont deja ete tranchees par
``ApprovedMutationRunner``. Ce qui reste ici est un contrat a honorer et un appel a
passer.

La distinction qui gouverne tout le fichier est celle entre LEVER et RENDRE UN ECHEC,
parce qu'elle ne dit pas la meme chose a la reservation d'idempotence :

- Rendre un resultat en echec signifie "l'ecriture n'a pas eu lieu, et je le sais".
  L'appelant enregistre l'issue, la reservation est consommee, et l'approbation ne
  sera pas rejouee. C'est la reponse de tout refus prononce AVANT que le fournisseur
  soit contacte.
- Lever signifie "j'ignore ou en est cette ecriture". La reservation reste ouverte,
  et la reprise honnete represente la MEME cle. C'est la reponse de toute panne
  survenue pendant l'appel.

Se tromper de sens n'est pas une question de style : rendre un echec sur un appel
interrompu declarerait qu'aucun ticket n'a ete cree, alors qu'il a peut-etre ete cree.
"""

import json
import logging
from typing import Any

import anyio
import anyio.from_thread
from jsonschema import Draft202012Validator

from app.core.config import Settings
from app.core.identity import SecurityContext
from app.mcp.domain import (
    MCPBindingKind,
    MCPExecutionResult,
    MCPToolCall,
)
from app.mcp.errors import MCPRemoteToolFailure
from app.mcp.mutation_registry import MCPMutationRegistry, MutationToolContract
from app.mcp.ports import MCPReadTransport
from app.mcp.registry import APPROVED_PROTOCOL_VERSIONS, schema_sha256

logger = logging.getLogger(__name__)

# Plus large que le budget d'une lecture : creer un ticket declenche des regles de
# projet, des notifications et des automatisations chez le fournisseur. Borne malgre
# tout, parce qu'un appel sans plafond immobilise une approbation dans l'etat
# EXECUTING sans que rien ne vienne jamais la fermer.
MUTATION_BUDGET_SECONDS = 60.0

# Codes rendus a l'appelant. Stables et sans prose : ils traversent l'audit et une
# interface, et une phrase se reformule alors qu'un code se compare.
CONTRACT_UNKNOWN = "MUTATION_CONTRACT_UNKNOWN"
ACTION_MISMATCH = "MUTATION_ACTION_MISMATCH"
INPUT_REJECTED = "MUTATION_INPUT_REJECTED"
BINDING_UNAVAILABLE = "MUTATION_BINDING_UNAVAILABLE"
SCHEMA_DRIFTED = "MUTATION_SCHEMA_DRIFTED"
PROTOCOL_REJECTED = "MUTATION_PROTOCOL_REJECTED"


class MCPMutationGateway:
    """Realise ``MCPToolGateway.execute_mutation`` pour les ecritures declarees.

    ``execute_read`` n'est volontairement pas implemente ici. Le chemin de lecture a
    son propre workflow, avec sa provenance et son audit ; offrir une seconde porte
    vers les lectures depuis l'objet qui sait ecrire reviendrait a placer les deux
    surfaces derriere le meme objet, ce que le reste du projet evite avec soin.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        transport: MCPReadTransport,
        registry: MCPMutationRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._registry = registry or MCPMutationRegistry()

    def execute_mutation(
        self,
        *,
        call: MCPToolCall,
        context: SecurityContext,
        idempotency_key: str,
    ) -> MCPExecutionResult:
        """Executer une ecriture deja approuvee.

        ``idempotency_key`` n'est PAS transmis au fournisseur, et c'est une limite
        assumee plutot qu'un oubli : le serveur MCP d'Atlassian n'expose aucun
        parametre d'idempotence, et son schema est ferme -- y glisser une cle ferait
        rejeter l'appel entier. La cle protege donc un seul cote de l'echange. Nous ne
        depensons jamais deux fois la meme approbation ; si un appel s'interrompt, le
        fournisseur ne peut pas nous aider a savoir ce qu'il en a fait, et c'est
        exactement pourquoi ce cas leve au lieu de conclure.
        """

        contract = self._registry.get(call.source_system, call.tool_name)
        if contract is None:
            return self._refused(CONTRACT_UNKNOWN, call, idempotency_key)
        # L'approbation portait sur une classe d'action. Un appel qui en presente une
        # autre ne correspond plus a ce qui a ete montre a l'humain.
        if call.action_class is not contract.action_class:
            return self._refused(ACTION_MISMATCH, call, idempotency_key)

        try:
            bound = self._bind_and_validate(contract, call.arguments)
        except _Refusal as refusal:
            return self._refused(refusal.code, call, idempotency_key)

        async def run() -> MCPExecutionResult:
            return await self._dispatch(contract, bound, context, call, idempotency_key)

        # Le protocole est synchrone et le transport ne l'est pas. Le meme pont que
        # celui du verificateur de permission : depuis un fil appelant une boucle
        # existante, sinon une boucle a nous.
        try:
            return anyio.from_thread.run(run)
        except RuntimeError:
            return anyio.run(run)

    async def _dispatch(
        self,
        contract: MutationToolContract,
        bound: dict[str, Any],
        context: SecurityContext,
        call: MCPToolCall,
        idempotency_key: str,
    ) -> MCPExecutionResult:
        with anyio.fail_after(MUTATION_BUDGET_SECONDS):
            async with self._transport.connect(
                provider=contract.provider,
                binding=contract.binding_kind,
                context=context,
            ) as session:
                if session.protocol_version not in APPROVED_PROTOCOL_VERSIONS:
                    return self._refused(PROTOCOL_REJECTED, call, idempotency_key)

                # La derive est verifiee ICI, juste avant l'appel, et pas seulement a
                # la proposition. Une approbation peut attendre quinze minutes ; le
                # fournisseur a pu changer la forme de l'outil entre-temps, et
                # l'humain a approuve la forme d'avant.
                listed = [t for t in await session.list_tools() if t.name == contract.tool_name]
                if len(listed) != 1:
                    return self._refused(SCHEMA_DRIFTED, call, idempotency_key)
                if schema_sha256(listed[0].input_schema) != contract.provider_input_schema_sha256:
                    return self._refused(SCHEMA_DRIFTED, call, idempotency_key)

                # A partir d'ici, une panne de transport signifie que l'ecriture est
                # peut-etre partie : elle leve, et la reservation reste ouverte.
                #
                # Un refus rapporte par l'outil est autre chose. Le serveur a repondu,
                # donc l'ecriture n'a pas eu lieu et cela se sait -- c'est la seule
                # exception qui redevient une issue.
                try:
                    remote = await session.call_tool(
                        tool_name=contract.tool_name,
                        arguments=bound,
                    )
                except MCPRemoteToolFailure:
                    return self._provider_refusal(contract, call, idempotency_key)

        return self._normalize(remote, contract, call, idempotency_key)

    def _bind_and_validate(
        self,
        contract: MutationToolContract,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Valider la surface publique, puis injecter le liant, puis revalider.

        Deux validations et non une. La premiere tient l'humain a ce qu'il a approuve ;
        la seconde tient le fournisseur au contrat qu'il publie. Une seule des deux
        laisserait passer soit un champ que l'approbation n'a pas montre, soit un
        appel que le serveur rejettera.
        """

        if not Draft202012Validator(contract.public_input_schema).is_valid(arguments):
            raise _Refusal(INPUT_REJECTED)

        bound = dict(arguments)
        if contract.binding_kind is MCPBindingKind.JIRA:
            cloud_id = self._settings.mcp_atlassian_jira_cloud_id
        elif contract.binding_kind is MCPBindingKind.CONFLUENCE:
            cloud_id = self._settings.mcp_atlassian_confluence_cloud_id
        else:
            cloud_id = None
        if contract.binding_kind in (MCPBindingKind.JIRA, MCPBindingKind.CONFLUENCE):
            if cloud_id is None:
                raise _Refusal(BINDING_UNAVAILABLE)
            # Injecte cote serveur, apres l'approbation : c'est ce qui garantit qu'une
            # ecriture approuvee ne peut pas atterrir sur un autre site.
            bound["cloudId"] = str(cloud_id)

        if not Draft202012Validator(contract.provider_input_schema).is_valid(bound):
            raise _Refusal(INPUT_REJECTED)
        return bound

    def _provider_refusal(
        self,
        contract: MutationToolContract,
        call: MCPToolCall,
        idempotency_key: str,
    ) -> MCPExecutionResult:
        """Le fournisseur a traite la demande et l'a refusee.

        C'est une issue CONNUE, pas une issue inconnue, et la distinction se paie cher
        si on la manque. L'adaptateur distant leve ``MCPRemoteToolFailure`` quand
        l'outil rapporte une erreur -- projet inexistant, droits manquants -- ce qui
        veut dire que le serveur a repondu et que l'ecriture n'a pas eu lieu. Laisser
        cette exception remonter la ferait passer pour une coupure : l'utilisateur
        irait chercher dans Jira un ticket qui n'a jamais existe, et la reservation
        resterait ouverte indefiniment.
        """

        logger.warning(
            "The provider refused an approved mutation",
            extra={
                "mcp_tool": contract.tool_name,
                "correlation_id": call.correlation_id,
                "idempotency_key": idempotency_key,
            },
        )
        return MCPExecutionResult(
            succeeded=False,
            error_code="MUTATION_PROVIDER_REFUSED",
            safe_message="The source system refused this write",
        )

    def _normalize(
        self,
        remote: Any,
        contract: MutationToolContract,
        call: MCPToolCall,
        idempotency_key: str,
    ) -> MCPExecutionResult:
        """Conclure a partir de ce que le fournisseur a renvoye.

        Arriver ici signifie que l'appel a abouti sans erreur rapportee : le refus a
        deja ete traite plus haut, par l'exception que l'adaptateur distant leve.
        """

        logger.info(
            "An approved mutation completed",
            extra={
                "mcp_tool": contract.tool_name,
                "correlation_id": call.correlation_id,
                "idempotency_key": idempotency_key,
            },
        )
        return MCPExecutionResult(succeeded=True, external_ids=_external_ids(remote))

    def _refused(
        self,
        code: str,
        call: MCPToolCall,
        idempotency_key: str,
    ) -> MCPExecutionResult:
        """Un refus prononce avant que le fournisseur soit contacte.

        Rendu et non leve : l'ecriture n'a pas eu lieu et nous le savons, donc
        l'approbation se ferme sur cette issue plutot que de rester ouverte a une
        reprise qui echouerait a l'identique.
        """

        logger.warning(
            "An approved mutation was refused before dispatch",
            extra={
                "mutation_error_code": code,
                "mcp_tool": call.tool_name,
                "correlation_id": call.correlation_id,
                "idempotency_key": idempotency_key,
            },
        )
        return MCPExecutionResult(
            succeeded=False,
            error_code=code,
            safe_message="This write could not be performed",
        )


class _Refusal(Exception):
    """Interne au module : porte un code jusqu'au point qui sait le rendre."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _external_ids(remote: Any) -> tuple[str, ...]:
    """La cle du ticket cree, quand le fournisseur la nomme.

    Cherchee a DEUX endroits, parce qu'un essai reel a montre que le premier ne
    suffit pas : createJiraIssue laisse ``structured_content`` vide et rend la cle
    dans un bloc de texte JSON. Ne regarder que le contenu structure faisait rendre
    une ecriture reussie sans dire ce qu'elle avait cree -- l'interface ne pouvait
    alors pas offrir de lien vers le ticket.

    Ce que le fournisseur renvoie reste de la donnee : la valeur est bornee, et elle
    finit dans un audit et dans une interface, jamais dans une decision.
    """

    for candidat in (
        getattr(remote, "structured_content", None),
        _first_json_block(remote),
    ):
        if not isinstance(candidat, dict):
            continue
        # Le premier trouve, dans cet ordre, et un seul. Jira rend "key" (KAN-32) et
        # "id" (10031) pour la meme ressource : les renvoyer tous les deux ferait
        # afficher a une interface un identifiant interne qui ne dit rien a personne.
        # L'ordre va donc du plus parlant au plus technique.
        for cle in ("key", "issueKey", "id"):
            valeur = candidat.get(cle)
            if isinstance(valeur, str) and 0 < len(valeur) <= 200:
                return (valeur,)
    return ()


def _first_json_block(remote: Any) -> Any:
    """Le premier bloc de contenu, s'il porte un objet JSON.

    Tolerant a dessein : un bloc illisible n'est pas une erreur ici, seulement une
    reponse qui ne nomme pas ce qu'elle a cree. Une ecriture reussie ne doit pas
    devenir un echec parce que son accuse de reception est mal forme.
    """

    for bloc in getattr(remote, "content", ()) or ():
        texte = getattr(bloc, "text", None)
        if not isinstance(texte, str) or not texte:
            continue
        try:
            return json.loads(texte)
        except (ValueError, RecursionError):
            return None
    return None


__all__ = [
    "ACTION_MISMATCH",
    "BINDING_UNAVAILABLE",
    "CONTRACT_UNKNOWN",
    "INPUT_REJECTED",
    "MUTATION_BUDGET_SECONDS",
    "PROTOCOL_REJECTED",
    "SCHEMA_DRIFTED",
    "MCPMutationGateway",
]
