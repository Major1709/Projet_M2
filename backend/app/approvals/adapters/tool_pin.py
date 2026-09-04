"""Ce a quoi une proposition de mutation est epinglee.

L'empreinte dit quelle forme d'outil l'humain a vue au moment ou il a approuve. Elle
est donc derivee du serveur, jamais fournie par l'appelant ni par le modele : une
proposition qui pourrait choisir son propre epinglage n'epingle rien.

Deux implementations, et le choix entre elles appartient a la configuration. Refuser
reste le comportement d'un deploiement qui n'autorise pas les ecritures, et ce refus
n'est pas une degradation : c'est la reponse juste.
"""

from app.approvals.errors import InvalidTransition
from app.mcp.domain import SourceSystem
from app.mcp.mutation_registry import MCPMutationRegistry


class NoMutationToolsPin:
    """Refuse chaque outil de mutation.

    Conserve apres l'arrivee du registre, pour les deploiements qui n'ouvrent aucune
    surface d'ecriture. Un registre vide donnerait le meme resultat, mais nommer
    l'intention vaut mieux que la deduire d'une collection vide.
    """

    def schema_sha256(self, *, source_system: SourceSystem, tool_name: str) -> str:
        raise InvalidTransition(
            f"No mutation contract is registered for {source_system}.{tool_name}"
        )


class RegistryMutationToolPin:
    """Lit l'empreinte dans le registre des mutations.

    Refuse par defaut : un outil absent du registre n'a pas d'empreinte, donc pas de
    proposition possible. C'est la meme regle que pour les lectures, et elle porte ici
    davantage -- inventer une empreinte laisserait une proposition revendiquer une
    forme que personne n'a publiee, et l'approbation porterait sur une fiction.
    """

    def __init__(self, registry: MCPMutationRegistry | None = None) -> None:
        self._registry = registry or MCPMutationRegistry()

    def schema_sha256(self, *, source_system: SourceSystem, tool_name: str) -> str:
        contract = self._registry.get(source_system, tool_name)
        if contract is None:
            # Le message ne distingue pas "outil inconnu" de "outil connu mais non
            # autorise en ecriture". La distinction n'aiderait que quelqu'un qui
            # cherche la frontiere.
            raise InvalidTransition(
                f"No mutation contract is registered for {source_system}.{tool_name}"
            )
        return contract.provider_input_schema_sha256


__all__ = ["NoMutationToolsPin", "RegistryMutationToolPin"]
