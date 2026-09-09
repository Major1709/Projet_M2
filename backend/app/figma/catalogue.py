"""L'annuaire des frames Figma : retrouver un cadre par son nom, sans lien colle.

Le probleme qu'il resout est etroit et concret. L'API Figma ne sait pas chercher un
cadre : elle rend un fichier entier quand on lui donne sa cle, et rien ne permet de
demander "ou est le cadre nomme Nexia". L'utilisateur devait donc coller une URL a
chaque question.

Deux autres voies ont ete pesees et ecartees.

L'authentification OAuth aurait permis de lister les FICHIERS d'une equipe. Mais un
cadre vit a l'interieur d'un fichier, et il aurait fallu ouvrir chaque fichier pour
l'y chercher -- au-dela du budget de lectures d'une question des la troisieme
maquette.

L'index semantique aurait marche, au prix d'un moteur d'inference qui fait passer
l'image de 200 Mo a plus de 2,5 Go. Or chercher un cadre PAR SON NOM est une
recherche textuelle : la comprehension du sens sert a rapprocher ce qui ne porte pas
les memes mots, pas a retrouver ce qu'on nomme exactement.

Cet annuaire garde donc sa portee : des noms, des chemins, et de quoi aller lire le
bon noeud. Ce qu'il produit est aussi exactement ce qu'un index semantique
consommerait plus tard, donc rien ne serait jete le jour ou on l'ajoute.

Il vit EN MEMOIRE, et c'est un choix assume plutot qu'une facilite : le contenu est
entierement derive de Figma, donc reconstructible a tout moment. Le persister
demanderait une table, une migration et une politique d'invalidation pour un cache
dont la source fait autorite. Le prix est qu'un redemarrage vide l'annuaire, et que
la premiere question qui suit paie une relecture.
"""

import logging
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.core.identity import SecurityContext
from app.mcp.domain import MCPReadSourceSystem, MCPReadToolCall, ToolActionClass
from app.mcp.errors import MCPReadError
from app.mcp.read_workflow import MCPReadWorkflow

logger = logging.getLogger(__name__)

# Une relecture complete coute une lecture Figma par fichier configure. Sans plafond,
# une question portant sur un cadre inexistant -- une faute de frappe suffit -- ferait
# relire toutes les maquettes a chaque tentative.
MIN_REFRESH_INTERVAL_SECONDS = 300.0

# Ce qui est retenu d'un arbre Figma. Les conteneurs purs (document, page) sont
# ecartes : personne ne demande "lis le document".
INDEXED_NODE_TYPES = frozenset(
    {
        "FRAME",
        "SECTION",
        "GROUP",
        "COMPONENT",
        "COMPONENT_SET",
        "INSTANCE",
        "SHAPE_WITH_TEXT",
        "STICKY",
        "TEXT",
    }
)

MAX_RESULTS = 8


@dataclass(frozen=True)
class FrameEntry:
    """Un noeud retrouvable, et de quoi aller le lire."""

    file_key: str
    node_id: str
    name: str
    node_type: str
    # Les ancetres, du plus lointain au plus proche. Ce qui situe le cadre : deux
    # maquettes peuvent avoir un "LOGIN", leur chemin les distingue.
    path: tuple[str, ...]
    text: str | None = None

    @property
    def location(self) -> str:
        return " > ".join((*self.path, self.name))


def _normalise(valeur: str) -> str:
    """Repli les accents et la casse, pour que "Paiement" trouve "paiement".

    Sans cela, un utilisateur devrait reproduire exactement la graphie choisie par
    quelqu'un d'autre dans Figma -- ce qui reviendrait a remplacer un lien a coller
    par un nom a deviner.
    """

    sans_accent = unicodedata.normalize("NFKD", valeur)
    return "".join(c for c in sans_accent if not unicodedata.combining(c)).casefold().strip()


def _walk(noeud: Any, file_key: str, chemin: tuple[str, ...] = ()) -> list[FrameEntry]:
    """Aplatit l'arbre Figma en entrees retrouvables.

    Tolerant sur la forme : ce qui arrive vient d'un fournisseur, et un noeud
    inattendu doit faire ignorer ce noeud, jamais echouer l'indexation entiere.
    """

    if not isinstance(noeud, dict):
        return []
    nom = noeud.get("name")
    type_noeud = noeud.get("type")
    entrees: list[FrameEntry] = []
    if (
        isinstance(nom, str)
        and nom
        and isinstance(type_noeud, str)
        and type_noeud in INDEXED_NODE_TYPES
        and isinstance(noeud.get("id"), str)
    ):
        texte = noeud.get("characters")
        entrees.append(
            FrameEntry(
                file_key=file_key,
                node_id=noeud["id"],
                name=nom,
                node_type=type_noeud,
                path=chemin,
                text=texte if isinstance(texte, str) and texte else None,
            )
        )
    sous_chemin = (*chemin, nom) if isinstance(nom, str) and nom else chemin
    for enfant in noeud.get("children") or ():
        entrees.extend(_walk(enfant, file_key, sous_chemin))
    return entrees


class FigmaFrameCatalogue:
    """Retrouve un cadre par son nom parmi les fichiers que le deploiement designe.

    Se rafraichit tout seul sur echec de recherche : un cadre ajoute dans Figma est
    donc trouve a la question suivante, sans que personne ait a lancer quoi que ce
    soit. C'est ce qui distingue un annuaire utilisable d'un annuaire qu'on oublie de
    mettre a jour.
    """

    def __init__(
        self,
        *,
        reads: MCPReadWorkflow,
        file_keys: tuple[str, ...],
        min_refresh_interval_seconds: float = MIN_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self._reads = reads
        self._file_keys = tuple(dict.fromkeys(file_keys))
        self._interval = min_refresh_interval_seconds
        self._entries: tuple[FrameEntry, ...] = ()
        self._last_refresh: float | None = None

    @property
    def file_keys(self) -> tuple[str, ...]:
        return self._file_keys

    @property
    def size(self) -> int:
        return len(self._entries)

    async def find(
        self,
        *,
        query: str,
        context: SecurityContext,
    ) -> tuple[FrameEntry, ...]:
        """Chercher, et relire les maquettes si rien ne correspond.

        La relecture n'a lieu que sur echec, et pas plus souvent que l'intervalle :
        une recherche qui aboutit ne coute aucune lecture, et un nom inexistant ne
        peut pas faire relire les maquettes a chaque tentative.
        """

        if self._last_refresh is None:
            await self.refresh(context)

        trouves = self._match(query)
        if trouves:
            return trouves

        if self._can_refresh():
            logger.info(
                "A frame was not in the catalogue; refreshing before answering",
                extra={"figma_query": query},
            )
            await self.refresh(context)
            trouves = self._match(query)
        return trouves

    async def refresh(self, context: SecurityContext) -> int:
        """Relire tous les fichiers configures et reconstruire l'annuaire.

        Un fichier illisible est ignore et journalise, jamais fatal : une maquette
        supprimee ou devenue inaccessible ne doit pas priver l'utilisateur des
        autres.
        """

        self._last_refresh = time.monotonic()
        entrees: list[FrameEntry] = []
        for cle in self._file_keys:
            try:
                document = await self._read_file(cle, context)
            except MCPReadError as error:
                logger.warning(
                    "A configured Figma file could not be indexed",
                    extra={"figma_file_key": cle, "mcp_error_code": error.code},
                )
                continue
            entrees.extend(_walk(document, cle))
        self._entries = tuple(entrees)
        logger.info(
            "The Figma frame catalogue was rebuilt",
            extra={"figma_files": len(self._file_keys), "figma_entries": len(self._entries)},
        )
        return len(self._entries)

    def _can_refresh(self) -> bool:
        if self._last_refresh is None:
            return True
        return (time.monotonic() - self._last_refresh) >= self._interval

    async def _read_file(self, file_key: str, context: SecurityContext) -> Any:
        """La lecture passe par le workflow ordinaire : autorisee, bornee, tracee.

        Un chemin de lecture parallele ferait sortir du contenu Figma sans qu'aucun
        audit ne le nomme, ce qui viderait la trace de son sens.
        """

        resultat = await self._reads.execute_call(
            call=MCPReadToolCall(
                source_system=MCPReadSourceSystem.FIGMA,
                tool_name="getFigmaFile",
                action_class=ToolActionClass.READ,
                arguments={"fileKey": file_key},
                correlation_id="figma-catalogue",
            ),
            context=context,
        )
        charge = resultat.structured_content
        if charge is None:
            charge = _first_json(resultat)
        if isinstance(charge, dict):
            return charge.get("document", charge)
        return None

    def _match(self, query: str) -> tuple[FrameEntry, ...]:
        """Du plus precis au plus large, et jamais melange.

        Une correspondance exacte ecrase les approximatives : si un cadre s'appelle
        exactement comme ce qui est demande, proposer en plus tous ceux qui
        contiennent ce mot noierait la bonne reponse au lieu de l'appuyer.
        """

        cible = _normalise(query)
        if not cible:
            return ()
        exactes: list[FrameEntry] = []
        debuts: list[FrameEntry] = []
        contenus: list[FrameEntry] = []
        for entree in self._entries:
            nom = _normalise(entree.name)
            if nom == cible:
                exactes.append(entree)
            elif nom.startswith(cible):
                debuts.append(entree)
            elif cible in nom or (entree.text and cible in _normalise(entree.text)):
                contenus.append(entree)
        for lot in (exactes, debuts, contenus):
            if lot:
                return tuple(lot[:MAX_RESULTS])
        return ()


def _first_json(resultat: Any) -> Any:
    import json

    for bloc in getattr(resultat, "content", ()) or ():
        texte = getattr(bloc, "text", None)
        if isinstance(texte, str) and texte:
            try:
                return json.loads(texte)
            except ValueError:
                return None
    return None


__all__ = [
    "INDEXED_NODE_TYPES",
    "MAX_RESULTS",
    "MIN_REFRESH_INTERVAL_SECONDS",
    "FigmaFrameCatalogue",
    "FrameEntry",
]
