"use client";

import Image from "next/image";
import { useId, useState } from "react";

import {
  NexiaApiError,
  nexiaApi,
  type NexiaApproval,
  type NexiaGateway,
  type NexiaMutationExecution,
  type NexiaMutationPayload,
  type NexiaMutationProposalState,
} from "@/adapters/nexia-api";

import { opensABlock, parseMarkdownTable } from "./markdown-table";

/**
 * Le corps d'une page, rendu comme Confluence le rendra.
 *
 * Un cahier des charges part en markdown : sept colonnes de barres verticales que
 * l'aperçu affichait en texte brut. Approuver ce qu'on ne peut pas relire n'est pas
 * approuver, et c'est pourtant ce qu'on demandait.
 *
 * Une ligne dont la première cellule est vide continue le bloc du dessus -- c'est la
 * convention de la page de l'équipe. Elle est marquée plutôt que laissée en trous,
 * qu'un relecteur prendrait pour un oubli.
 */
function SpecificationBody({ body, fallback }: { body: string; fallback?: string }) {
  if (!body.trim()) {
    // Une proposition sans corps ne devrait pas exister, mais une boite vide ne dit
    // pas si le contenu manque ou si l'affichage a echoue.
    return <p>{fallback || "Aucun contenu à écrire."}</p>;
  }
  const table = parseMarkdownTable(body);
  if (!table) {
    // Pas de tableau : on montre ce qu'il y a. Un corps en prose est justement ce
    // que la consigne interdit, donc le cacher priverait le relecteur du défaut.
    return <pre className="approval-body-raw">{body}</pre>;
  }

  return (
    <>
      {table.before ? <p className="approval-body-stray">{table.before}</p> : null}
      <div className="approval-table-scroll">
        <table className="approval-table">
          <thead>
            <tr>
              {table.headers.map((header, index) => (
                <th key={`${header}-${index}`} scope="col">{header}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr
                key={rowIndex}
                className={opensABlock(row) ? "approval-table__block" : "approval-table__continued"}
              >
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.after ? <p className="approval-body-stray">{table.after}</p> : null}
      <p className="approval-table-count">
        {table.rows.filter(opensABlock).length} bloc(s) fonctionnel(s) · {table.rows.length} ligne(s)
      </p>
    </>
  );
}

type ApprovalUiState =
  | "pending"
  | "approved"
  | "rejected"
  | "executing"
  | "completed"
  | "partial"
  | "failed"
  | "expired"
  | "unknown"
  | "unavailable"
  | "conflict";

type MutationApprovalPreviewProps = {
  /** A server-created proposal returned with or immediately after the assistant turn. */
  approval?: NexiaApproval;
  /** Kept for the local fixture and for proposals created before API data is available. */
  target?: NexiaApproval["target"];
  gateway?: Pick<
    NexiaGateway,
    | "approveActionProposal"
    | "rejectActionProposal"
    | "reviseActionProposal"
    | "executeActionProposal"
  >;
  onDecision?: (status: "approved" | "rejected") => void;
  onEdit?: () => void;
  onSessionRequired?: () => void;
  onMutationError?: (error: NexiaApiError) => void;
};

type TargetDetails = {
  action: string;
  destination: string;
  icon: string;
  iconAlt: string;
  objectType: string;
  project: string;
  title: string;
  description: string;
  label: string;
  explanation?: string;
};

const TARGETS: Record<NexiaApproval["target"], TargetDetails> = {
  jira: {
    action: "Créer un ticket",
    destination: "Jira · Backlog PKA",
    icon: "/figma-assets/jira.svg",
    iconAlt: "Jira",
    objectType: "User Story",
    project: "PKA",
    title: "Stabiliser le viewport du chat",
    description:
      "En tant qu’utilisateur, je veux conserver la zone de saisie visible lorsque la conversation s’allonge afin de pouvoir poursuivre mon échange sans perdre le contexte.",
    label: "Écriture Jira",
  },
  confluence: {
    action: "Créer une page",
    destination: "Confluence · Cahier des charges",
    icon: "/figma-assets/confluence.svg",
    iconAlt: "Confluence",
    objectType: "User Story",
    project: "Product Knowledge Assistant",
    title: "Parcours d’approbation des mutations",
    description:
      "Documenter le parcours de validation humaine avant toute création, modification ou suppression dans un outil connecté.",
    label: "Écriture Confluence",
  },
  figma: {
    action: "Créer un processus",
    destination: "Figma · Parcours métier",
    icon: "/figma-assets/figma.svg",
    iconAlt: "Figma",
    objectType: "Processus",
    project: "NEXIA",
    title: "Valider une écriture externe",
    description:
      "Représenter les étapes de proposition, vérification des droits, approbation et audit avant l’exécution d’une action MCP.",
    label: "Écriture Figma",
  },
};

function statusFromProposal(state?: NexiaMutationProposalState): ApprovalUiState {
  switch (state) {
    case "APPROVED":
      return "approved";
    case "REJECTED":
      return "rejected";
    case "EXPIRED":
      return "expired";
    case "COMPLETED":
      return "completed";
    case "PARTIAL":
      return "partial";
    case "FAILED":
    case "DENIED":
      return "failed";
    case "EXECUTING":
    case "PERMISSION_CHECK":
      return "executing";
    case "SUPERSEDED":
      return "conflict";
    default:
      return "pending";
  }
}

function actionLabel(target: NexiaApproval["target"], actionClass?: NexiaApproval["actionClass"]): string {
  const object = target === "jira" ? "un ticket" : target === "confluence" ? "une page" : "un processus";
  if (actionClass === "UPDATE") return `Modifier ${object}`;
  if (actionClass === "DELETE") return `Supprimer ${object}`;
  return `Créer ${object}`;
}

function expiresInMinutes(approval?: NexiaApproval): number {
  if (approval?.expiresAt) {
    const expiresAt = Date.parse(approval.expiresAt);
    if (!Number.isNaN(expiresAt)) {
      return Math.max(0, Math.ceil((expiresAt - Date.now()) / 60_000));
    }
  }
  return approval?.expiresInMinutes ?? 14;
}

function StatusIcon({ status }: { status: ApprovalUiState }) {
  const icon = status === "pending" ? "!"
    : status === "approved" ? "✓"
      : status === "executing" ? "…"
        : status === "completed" ? "✓"
          : status === "unknown" ? "?"
            : "×";

  return (
    <span className={`approval-status-icon approval-status-icon--${status}`} aria-hidden="true">
      {icon}
    </span>
  );
}

function stateLabel(status: ApprovalUiState): string {
  switch (status) {
    case "approved": return "À exécuter";
    case "executing": return "En cours";
    case "completed": return "Terminée";
    case "partial": return "Partielle";
    case "failed": return "Échec connu";
    case "rejected": return "Refusée";
    case "expired": return "Expirée";
    case "unknown": return "Confirmation inconnue";
    case "unavailable": return "Écritures désactivées";
    case "conflict": return "Proposition modifiée";
    default: return "En attente";
  }
}

function isTerminal(status: ApprovalUiState): boolean {
  return ["rejected", "completed", "partial", "failed", "expired", "unknown", "unavailable", "conflict"]
    .includes(status);
}

function errorState(error: NexiaApiError): ApprovalUiState {
  switch (error.code) {
    case "MCP_MUTATIONS_DISABLED": return "unavailable";
    case "PROPOSAL_EXPIRED": return "expired";
    case "MUTATION_OUTCOME_UNKNOWN": return "unknown";
    case "VERSION_CONFLICT":
    case "INVALID_TRANSITION":
    case "INVALID_DECISION_TOKEN":
    case "PROPOSAL_NOT_FOUND": return "conflict";
    default: return "failed";
  }
}

export function MutationApprovalPreview({
  approval,
  target = approval?.target ?? "jira",
  gateway = nexiaApi,
  onDecision,
  onEdit,
  onSessionRequired,
  onMutationError,
}: MutationApprovalPreviewProps) {
  const [selectedTarget, setSelectedTarget] = useState(target);
  const [currentApproval, setCurrentApproval] = useState(approval);
  const [status, setStatus] = useState<ApprovalUiState>(statusFromProposal(approval?.state));
  const [execution, setExecution] = useState<NexiaMutationExecution | null>(null);
  const [busy, setBusy] = useState(false);
  // La charge en cours d'edition, ou null quand on relit sans modifier. Separee de
  // la proposition : tant que la revision n'est pas enregistree, ce qui sera ecrit
  // reste ce que le serveur porte, et non ce qui est tape a l'ecran.
  const [draft, setDraft] = useState<NexiaMutationPayload | null>(null);
  const headingId = `approval-panel-title-${useId().replace(/:/g, "")}`;
  const baseDetails = TARGETS[selectedTarget];
  const payload = currentApproval?.payload ?? {};
  const sourceLabel = selectedTarget[0].toUpperCase() + selectedTarget.slice(1);
  const details: TargetDetails = {
    ...baseDetails,
    action: currentApproval?.action ?? actionLabel(selectedTarget, currentApproval?.actionClass),
    destination: currentApproval?.destination
      ?? (approval
        ? `${sourceLabel} · ${payload.projectKey ?? currentApproval?.project ?? "Projet non précisé"}`
        : baseDetails.destination),
    objectType: payload.issueTypeName
      ?? currentApproval?.objectType
      ?? (approval ? "Non renseigné" : baseDetails.objectType),
    project: payload.projectKey
      ?? currentApproval?.project
      ?? (approval ? "Non renseigné" : baseDetails.project),
    title: payload.summary
      ?? currentApproval?.title
      ?? (approval ? "Non renseigné" : baseDetails.title),
    description: payload.description
      ?? currentApproval?.description
      ?? (approval ? "" : baseDetails.description),
    label: currentApproval?.label ?? `Écriture ${sourceLabel}`,
    ...(currentApproval?.explanation ? { explanation: currentApproval.explanation } : {}),
  };
  const remoteProposal = Boolean(
    currentApproval?.proposalId
      && currentApproval.decisionToken
      && currentApproval.version !== undefined,
  );
  const editing = draft !== null;
  // Ce qui est a l'ecran : le brouillon pendant l'edition, la proposition sinon.
  const shown: NexiaMutationPayload = draft ?? payload;
  // Une page se reconnait a son corps, pas a son systeme : c'est ce champ qui
  // decide de ce qu'il y a a montrer, et un ticket n'en porte jamais.
  const isPage = typeof shown.body === "string" || selectedTarget === "confluence";
  // On n'approuve pas pendant qu'on modifie : le bouton porterait sur un texte que
  // le serveur ne connait pas encore.
  const canApprove = status === "pending" && !busy && !editing;
  const canExecute = status === "approved" && !busy;
  const remainingMinutes = expiresInMinutes(currentApproval);

  function chooseTarget(nextTarget: typeof selectedTarget) {
    setSelectedTarget(nextTarget);
    setStatus("pending");
  }

  function reportError(error: NexiaApiError) {
    setStatus(errorState(error));
    onMutationError?.(error);
    if (error.code === "IDENTITY_REQUIRED" || error.code === "SESSION_REQUIRED") {
      onSessionRequired?.();
    }
  }

  async function handleApprove() {
    if (!canApprove) return;
    if (!remoteProposal || !currentApproval) {
      setStatus("approved");
      onDecision?.("approved");
      return;
    }

    setBusy(true);
    try {
      const next = await gateway.approveActionProposal({
        proposalId: currentApproval.proposalId!,
        expectedVersion: currentApproval.version!,
        decisionToken: currentApproval.decisionToken!,
      });
      setCurrentApproval((previous) => ({ ...previous, ...next, decisionToken: previous?.decisionToken }));
      setStatus(statusFromProposal(next.state));
      onDecision?.("approved");
    } catch (caught) {
      reportError(caught instanceof NexiaApiError
        ? caught
        : new NexiaApiError("L’approbation n’a pas pu être enregistrée.", 0));
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!canApprove) return;
    if (!remoteProposal || !currentApproval) {
      setStatus("rejected");
      onDecision?.("rejected");
      return;
    }

    setBusy(true);
    try {
      const next = await gateway.rejectActionProposal({
        proposalId: currentApproval.proposalId!,
        expectedVersion: currentApproval.version!,
        decisionToken: currentApproval.decisionToken!,
      });
      setCurrentApproval((previous) => ({ ...previous, ...next, decisionToken: previous?.decisionToken }));
      setStatus("rejected");
      onDecision?.("rejected");
    } catch (caught) {
      reportError(caught instanceof NexiaApiError
        ? caught
        : new NexiaApiError("Le refus n’a pas pu être enregistré.", 0));
    } finally {
      setBusy(false);
    }
  }

  function startEditing() {
    setDraft({ ...payload });
    onEdit?.();
  }

  function editField(field: string, value: string) {
    setDraft((previous) => ({ ...(previous ?? payload), [field]: value }));
  }

  /**
   * Enregistrer la revision : le serveur remplace la proposition par une neuve.
   *
   * Ni le jeton ni la version d'avant ne valent plus rien apres coup, donc on repart
   * entierement de ce que le serveur rend. Reutiliser les anciens ferait echouer
   * l'approbation suivante avec un conflit que personne ne saurait expliquer.
   */
  async function handleSaveRevision() {
    if (!draft || busy) return;
    if (!remoteProposal || !currentApproval?.actionTarget) {
      // Sans proposition serveur -- l'aperçu de démonstration -- la modification
      // reste locale. Annoncer un enregistrement qui n'a pas lieu serait pire.
      setCurrentApproval((previous) => (previous ? { ...previous, payload: draft } : previous));
      setDraft(null);
      return;
    }

    setBusy(true);
    try {
      const revision = await gateway.reviseActionProposal({
        proposalId: currentApproval.proposalId!,
        expectedVersion: currentApproval.version!,
        decisionToken: currentApproval.decisionToken!,
        target: currentApproval.actionTarget,
        payload: draft,
        ...(currentApproval.explanation ? { explanation: currentApproval.explanation } : {}),
        reason: "Modifiee avant approbation",
      });
      setCurrentApproval(revision.replacement);
      setStatus(statusFromProposal(revision.replacement.state));
      setDraft(null);
    } catch (caught) {
      reportError(caught instanceof NexiaApiError
        ? caught
        : new NexiaApiError("La modification n’a pas pu être enregistrée.", 0));
    } finally {
      setBusy(false);
    }
  }

  async function handleExecute() {
    if (!canExecute) return;
    if (!remoteProposal || !currentApproval) {
      setStatus("completed");
      return;
    }

    setBusy(true);
    setStatus("executing");
    try {
      const result = await gateway.executeActionProposal({
        proposalId: currentApproval.proposalId!,
        expectedVersion: currentApproval.version!,
      });
      setExecution(result);
      setStatus(result.succeeded ? (result.partial ? "partial" : "completed") : "failed");
    } catch (caught) {
      reportError(caught instanceof NexiaApiError
        ? caught
        : new NexiaApiError("L’exécution n’a pas pu être confirmée.", 0));
    } finally {
      setBusy(false);
    }
  }

  const resultMessage = status === "completed"
    ? execution?.externalIds.length
      ? `Ticket créé : ${execution.externalIds.join(", ")}.`
      : "L’écriture est terminée. Aucun identifiant externe n’a été fourni."
    : status === "partial"
      ? "L’écriture est partiellement terminée. Vérifiez les éléments signalés dans Jira."
      : status === "failed"
        ? execution?.safeMessage ?? "Jira a refusé l’écriture. Aucune nouvelle tentative automatique ne sera faite."
        : status === "unknown"
          ? "L’écriture a été envoyée, mais nous n’avons pas reçu de confirmation. Vérifiez dans Jira avant toute nouvelle tentative."
          : status === "expired"
            ? "La fenêtre d’approbation est passée. Demandez une nouvelle proposition."
            : status === "unavailable"
              ? "Les écritures externes sont désactivées dans cet environnement."
              : status === "conflict"
                ? "La proposition a changé ou n’est plus accessible. Rechargez-la avant de décider."
                : status === "rejected"
                  ? "Aucune donnée ne sera écrite."
                  : "Le connecteur peut maintenant exécuter cette proposition.";
  const resultTitle = status === "approved" && !remoteProposal
    ? "Action approuvée"
    : status === "rejected"
      ? "Action refusée"
      : stateLabel(status);

  if (status === "unavailable") {
    return (
      <aside className="approval-panel approval-panel--inline" aria-labelledby={headingId}>
        <div className="approval-result approval-result--unavailable" role="status" aria-live="polite">
          <StatusIcon status={status} />
          <div>
            <strong id={headingId}>Écritures désactivées</strong>
            <span>{resultMessage}</span>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="approval-panel approval-panel--inline" aria-labelledby={headingId}>
      <div className="approval-panel__header">
        <div>
          <div className="approval-panel__eyebrow">Action à valider</div>
          <h2 id={headingId}>{details.action}</h2>
        </div>
        <span className={`approval-state-chip approval-state-chip--${status}`}>
          <span className="approval-state-chip__dot" aria-hidden="true" />
          {stateLabel(status)}
        </span>
      </div>

      {!approval ? (
        <div className="approval-target-switcher" role="group" aria-label="Aperçu des destinations">
          {(Object.keys(TARGETS) as Array<keyof typeof TARGETS>).map((key) => (
            <button
              key={key}
              className={selectedTarget === key ? "is-selected" : ""}
              type="button"
              aria-pressed={selectedTarget === key}
              onClick={() => chooseTarget(key)}
            >
              {key === "jira" ? "Jira" : key === "confluence" ? "Confluence" : "Figma"}
            </button>
          ))}
        </div>
      ) : null}

      <div className="approval-operation-card">
        <div className="approval-operation-card__icon">
          <Image src={baseDetails.icon} width={28} height={28} alt={baseDetails.iconAlt} />
        </div>
        <div>
          <strong>{details.destination}</strong>
          <span>{details.label}</span>
        </div>
        <span className="approval-operation-card__arrow" aria-hidden="true">↗</span>
      </div>

      <div className="approval-warning" role="note">
        <StatusIcon status={status === "pending" ? "pending" : status} />
        <p>
          {currentApproval?.actionClass === "UPDATE"
              ? `Cette action modifiera un élément dans ${sourceLabel}.`
              : currentApproval?.actionClass === "DELETE"
              ? `Cette action supprimera un élément dans ${sourceLabel}.`
              : `Cette action créera un nouvel élément dans ${sourceLabel}.`}
        </p>
      </div>

      <div className="approval-details" aria-label="Détails de l’action">
        <div>
          <span>Type</span>
          <strong>{details.objectType}</strong>
        </div>
        <div>
          <span>Projet / espace</span>
          <strong>{details.project}</strong>
        </div>
        <div>
          <span>Permission</span>
          <strong className="approval-detail-ok"><span aria-hidden="true">✓</span> Vérifiée</strong>
        </div>
        <div>
          <span>Expire dans</span>
          <strong>{remainingMinutes} minutes</strong>
        </div>
      </div>

      <div className="approval-content-preview">
        <div className="approval-section-label">
          {editing ? "Contenu à écrire — modification" : "Contenu à écrire"}
        </div>

        {isPage ? (
          <>
            <div className="approval-field">
              <span>Espace</span>
              <strong>{shown.spaceId ?? details.project}</strong>
            </div>
            <div className="approval-field">
              <span>Titre de la page</span>
              {editing ? (
                <input
                  className="approval-input"
                  type="text"
                  aria-label="Titre de la page"
                  value={String(shown.title ?? "")}
                  onChange={(event) => editField("title", event.target.value)}
                />
              ) : (
                <strong>{shown.title ?? details.title}</strong>
              )}
            </div>
            <div className="approval-field approval-field--description">
              <span>Cahier des charges</span>
              {editing ? (
                <>
                  <textarea
                    className="approval-textarea"
                    aria-label="Corps de la page en markdown"
                    rows={14}
                    value={String(shown.body ?? "")}
                    onChange={(event) => editField("body", event.target.value)}
                  />
                  {/* L'aperçu suit la frappe : sans lui, on modifierait un tableau
                      en markdown sans jamais voir ce qu'il devient. */}
                  <div className="approval-section-label">Aperçu</div>
                  <SpecificationBody body={String(shown.body ?? "")} />
                </>
              ) : (
                <SpecificationBody
                  body={String(shown.body ?? "")}
                  fallback={details.description}
                />
              )}
            </div>
          </>
        ) : (
          <>
            <div className="approval-field">
              <span>Projet</span>
              <strong>{shown.projectKey ?? details.project}</strong>
            </div>
            <div className="approval-field">
              <span>Type de ticket</span>
              <strong>{shown.issueTypeName ?? details.objectType}</strong>
            </div>
            <div className="approval-field">
              <span>Titre</span>
              {editing ? (
                <input
                  className="approval-input"
                  type="text"
                  aria-label="Titre du ticket"
                  value={String(shown.summary ?? "")}
                  onChange={(event) => editField("summary", event.target.value)}
                />
              ) : (
                <strong>{shown.summary ?? details.title}</strong>
              )}
            </div>
            <div className="approval-field approval-field--description">
              <span>Description</span>
              {editing ? (
                <textarea
                  className="approval-textarea"
                  aria-label="Description du ticket"
                  rows={6}
                  value={String(shown.description ?? "")}
                  onChange={(event) => editField("description", event.target.value)}
                />
              ) : (
                <p>{(shown.description ?? details.description) || "Aucune description."}</p>
              )}
            </div>
          </>
        )}

        {editing ? (
          <div className="approval-actions__row">
            <button
              className="approval-button approval-button--secondary"
              type="button"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              Annuler
            </button>
            <button
              className="approval-button approval-button--approve"
              type="button"
              disabled={busy}
              onClick={handleSaveRevision}
            >
              {busy ? "Enregistrement…" : "Enregistrer les modifications"}
            </button>
          </div>
        ) : null}
      </div>

      {details.explanation ? (
        <div className="approval-explanation">
          <div className="approval-section-label">Pourquoi NEXIA propose cette action</div>
          <p>{details.explanation}</p>
        </div>
      ) : null}

      <p className="approval-audit-hint">
        <span aria-hidden="true">◌</span>
        Votre décision sera enregistrée dans l’audit NEXIA.
      </p>
      <p className="approval-inline-safety">
        Aucune écriture n’est envoyée tant que vous n’avez pas confirmé.
      </p>

      {status === "pending" ? (
        <div className="approval-actions">
          {editing ? null : (
            <button
              className="approval-button approval-button--secondary"
              type="button"
              disabled={busy}
              onClick={startEditing}
            >
              Modifier la proposition
            </button>
          )}
          <div className="approval-actions__row">
            {/* Decider pendant qu'on modifie porterait sur un texte que le serveur
                ne connait pas encore : l'ecran et la proposition auraient diverge. */}
            <button
              className="approval-button approval-button--reject"
              type="button"
              disabled={!canApprove}
              onClick={handleReject}
            >
              {busy ? "Traitement…" : "Refuser"}
            </button>
            <button
              className="approval-button approval-button--approve"
              type="button"
              disabled={!canApprove}
              onClick={handleApprove}
            >
              <span aria-hidden="true">✓</span>
              {remoteProposal ? "Approuver" : "Approuver et créer"}
            </button>
          </div>
        </div>
      ) : status === "approved" && remoteProposal ? (
        <div className="approval-actions">
          <button
            className="approval-button approval-button--approve approval-button--execute"
            type="button"
            disabled={busy}
            onClick={handleExecute}
          >
            <span aria-hidden="true">✓</span>
            {busy ? "Exécution…" : "Exécuter l’écriture"}
          </button>
        </div>
      ) : isTerminal(status) || (status === "approved" && !remoteProposal) ? (
        <div className={`approval-result approval-result--${status}`} role="status" aria-live="polite">
          <StatusIcon status={status} />
          <div>
            <strong>{resultTitle}</strong>
            <span>{resultMessage}</span>
          </div>
        </div>
      ) : (
        <div className="approval-result approval-result--executing" role="status" aria-live="polite">
          <StatusIcon status={status} />
          <div>
            <strong>{stateLabel(status)}</strong>
            <span>{resultMessage}</span>
          </div>
        </div>
      )}
    </aside>
  );
}
