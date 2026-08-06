import type { JiraRequest } from "../domain/models";
import { DatabaseIcon, SearchIcon } from "./icons";
import { StatusPill } from "./status-pill";

interface RequestNavigatorProps {
  requests: JiraRequest[];
  selectedIds: Set<string>;
  isIndexing: boolean;
  onToggle: (requestId: string) => void;
  onIndex: () => void;
}

export function RequestNavigator({
  requests,
  selectedIds,
  isIndexing,
  onToggle,
  onIndex,
}: RequestNavigatorProps) {
  const indexableCount = requests.filter(
    (request) => selectedIds.has(request.id) && request.indexation !== "INDEXED",
  ).length;

  return (
    <aside className="request-navigator" aria-labelledby="request-heading">
      <div className="request-header">
        <div>
          <p className="eyebrow">Contexte de travail</p>
          <h2 id="request-heading">Demandes Jira</h2>
        </div>
        <span className="count-badge" aria-label={`${requests.length} demandes`}>
          {requests.length}
        </span>
      </div>

      <label className="search-field">
        <span className="sr-only">Rechercher dans les demandes</span>
        <SearchIcon width={17} height={17} />
        <input type="search" placeholder="Rechercher une demande" disabled />
        <span className="demo-hint">Démo</span>
      </label>

      <p className="selection-help" id="selection-help">
        Sélectionnez les demandes à ajouter au contexte du chat.
      </p>

      <div className="request-list" role="list" aria-describedby="selection-help">
        {requests.map((request) => {
          const selected = selectedIds.has(request.id);
          return (
            <label
              className={`request-card ${selected ? "is-selected" : ""}`}
              key={request.id}
            >
              <input
                type="checkbox"
                checked={selected}
                onChange={() => onToggle(request.id)}
                aria-label={`Sélectionner ${request.key} : ${request.title}`}
              />
              <span className="custom-checkbox" aria-hidden="true" />
              <span className="request-content">
                <span className="request-topline">
                  <span className="request-key">{request.key}</span>
                  <span className={`priority priority--${request.priority.toLowerCase()}`}>
                    {request.priority}
                  </span>
                </span>
                <span className="request-title">{request.title}</span>
                <span className="request-meta">
                  <StatusPill status={request.status} compact />
                  <span>{request.updatedAt}</span>
                </span>
                {request.indexation === "INDEXED" ? (
                  <span className="indexed-label">
                    <DatabaseIcon width={13} height={13} /> Indexée dans la connaissance
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>

      <div className="index-action">
        <button
          className="button button--dark button--full"
          type="button"
          onClick={onIndex}
          disabled={indexableCount === 0 || isIndexing}
        >
          <DatabaseIcon width={18} height={18} />
          {isIndexing
            ? "Indexation en cours…"
            : indexableCount > 0
              ? `Indexer ${indexableCount} demande${indexableCount > 1 ? "s" : ""}`
              : "Sélection déjà indexée"}
        </button>
        <p>Aucune donnée n’est envoyée à une source externe.</p>
      </div>
    </aside>
  );
}
