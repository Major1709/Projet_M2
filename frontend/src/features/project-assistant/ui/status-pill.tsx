import type { ApprovalState, IndexationState, JiraStatus } from "../domain/models";

type Status = ApprovalState | IndexationState | JiraStatus;

const labels: Record<Status, string> = {
  "À qualifier": "À qualifier",
  "En analyse": "En analyse",
  Prête: "Prête",
  Bloquée: "Bloquée",
  NOT_INDEXED: "Non indexée",
  QUEUED: "En file",
  INDEXING: "Indexation…",
  INDEXED: "Indexée",
  FAILED: "Échec",
  DRAFT: "Brouillon",
  PENDING_APPROVAL: "Approbation requise",
  APPROVED: "Approuvée",
  REJECTED: "Rejetée",
  SUPERSEDED: "Remplacée",
  EXPIRED: "Expirée",
  PERMISSION_CHECK: "Vérification des droits",
  EXECUTING: "Exécution…",
  COMPLETED: "Terminée",
  DENIED: "Permission refusée",
  PARTIAL: "Résultat partiel",
};

function getTone(status: Status) {
  if (["INDEXED", "Prête", "APPROVED", "COMPLETED"].includes(status)) return "success";
  if (["FAILED", "DENIED", "Bloquée", "REJECTED", "EXPIRED"].includes(status)) return "danger";
  if (["PENDING_APPROVAL", "PARTIAL", "À qualifier"].includes(status)) {
    return "warning";
  }
  if (["DRAFT", "SUPERSEDED"].includes(status)) return "neutral";
  if (["INDEXING", "QUEUED", "PERMISSION_CHECK", "EXECUTING", "En analyse"].includes(status)) {
    return "progress";
  }
  return "neutral";
}

export function StatusPill({ status, compact = false }: { status: Status; compact?: boolean }) {
  const isBusy = ["INDEXING", "PERMISSION_CHECK", "EXECUTING"].includes(status);

  return (
    <span className={`status-pill status-pill--${getTone(status)} ${compact ? "is-compact" : ""}`}>
      <span className={`status-dot ${isBusy ? "is-pulsing" : ""}`} aria-hidden="true" />
      {labels[status]}
    </span>
  );
}
