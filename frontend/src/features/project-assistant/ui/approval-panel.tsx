import {
  CheckIcon,
  ClockIcon,
  CloseIcon,
  EditIcon,
  ShieldIcon,
} from "./icons";
import type { ActionDecision, ActionProposal } from "../domain/models";
import { SourceReference } from "./source-reference";
import { StatusPill } from "./status-pill";

interface ApprovalPanelProps {
  action: ActionProposal;
  feedback: string | null;
  busyDecision: ActionDecision | null;
  onDecision: (decision: ActionDecision) => Promise<void>;
  onReset: () => void;
}

const actionLabels = {
  CREATE: "Création",
  UPDATE: "Modification",
  DELETE: "Suppression",
  SYNC: "Copie vers Jira",
};

const terminalStates = ["REJECTED", "SUPERSEDED", "EXPIRED", "COMPLETED", "DENIED", "FAILED"];

export function ApprovalPanel({
  action,
  feedback,
  busyDecision,
  onDecision,
  onReset,
}: ApprovalPanelProps) {
  const canDecide = action.state === "PENDING_APPROVAL" && busyDecision === null;
  const isTerminal = terminalStates.includes(action.state);

  return (
    <aside className="approval-panel" aria-labelledby="approval-heading">
      <header className="approval-header">
        <div className="approval-icon" aria-hidden="true">
          <ShieldIcon width={22} height={22} />
        </div>
        <div>
          <p className="eyebrow">Action externe</p>
          <h2 id="approval-heading">Validation requise</h2>
        </div>
      </header>

      <div className="approval-scroll">
        <div className="approval-state-row">
          <StatusPill status={action.state} />
          <span className="action-kind">{actionLabels[action.kind]}</span>
        </div>

        <section className="proposal-intro" aria-labelledby="proposal-title">
          <h3 id="proposal-title">{action.title}</h3>
          <p>{action.summary}</p>
        </section>

        <section className="target-card" aria-labelledby="target-heading">
          <p className="section-label" id="target-heading">
            Cible exacte
          </p>
          <div className="target-system-row">
            <span className={`source-mark source-mark--${action.target.system}`} aria-hidden="true">
              C
            </span>
            <div>
              <strong>{action.target.title}</strong>
              <span>
                {action.target.entityType} · {action.target.externalId}
              </span>
            </div>
          </div>
          <p className="target-destination">{action.target.destination}</p>
        </section>

        <section className="proposal-section" aria-labelledby="content-heading">
          <p className="section-label" id="content-heading">
            Contenu proposé
          </p>
          <dl className="field-list">
            {action.fields.map((field) => (
              <div className="field-row" key={field.label}>
                <dt>{field.label}</dt>
                <dd>
                  {Array.isArray(field.value) ? (
                    <ul>
                      {field.value.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  ) : (
                    field.value
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {action.diff.length ? (
          <section className="proposal-section" aria-labelledby="diff-heading">
            <p className="section-label" id="diff-heading">
              Diff avant / après
            </p>
            <div className="diff-list">
              {action.diff.map((diff) => (
                <article className="diff-card" key={diff.field}>
                  <h4>{diff.field}</h4>
                  <div className="diff-line diff-line--before">
                    <span aria-label="Supprimé">−</span>
                    <p>{diff.before}</p>
                  </div>
                  <div className="diff-line diff-line--after">
                    <span aria-label="Ajouté">+</span>
                    <p>{diff.after}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        <section className="proposal-section" aria-labelledby="evidence-heading">
          <p className="section-label" id="evidence-heading">
            Sources de la proposition
          </p>
          <div className="source-list source-list--stacked">
            {action.sources.map((source) => (
              <SourceReference key={source.id} source={source} />
            ))}
          </div>
        </section>

        <section className="snapshot-card" aria-label="Informations de contrôle">
          <div>
            <span>Snapshot approuvé</span>
            <strong>v{action.version} · {action.payloadHash}</strong>
          </div>
          <div>
            <span>Expiration</span>
            <strong>
              <ClockIcon width={14} height={14} /> {action.expiresAt}
            </strong>
          </div>
          <div>
            <span>Corrélation</span>
            <strong>{action.correlationId}</strong>
          </div>
        </section>

        {feedback ? (
          <div className="decision-feedback" role="status">
            {feedback}
          </div>
        ) : null}
      </div>

      <footer className="approval-actions">
        {isTerminal ? (
          <button className="button button--secondary button--full" type="button" onClick={onReset}>
            Réinitialiser la démonstration
          </button>
        ) : (
          <>
            <button
              className="button button--approve button--full"
              type="button"
              onClick={() => void onDecision("approve")}
              disabled={!canDecide}
            >
              <CheckIcon width={18} height={18} />
              {busyDecision === "approve" ? "Enregistrement…" : "Approuver l’action"}
            </button>
            <div className="secondary-actions">
              <button
                className="button button--secondary"
                type="button"
                onClick={() => void onDecision("revise")}
                disabled={!canDecide}
              >
                <EditIcon width={17} height={17} />
                Modifier
              </button>
              <button
                className="button button--ghost-danger"
                type="button"
                onClick={() => void onDecision("reject")}
                disabled={!canDecide}
              >
                <CloseIcon width={17} height={17} />
                Rejeter
              </button>
            </div>
          </>
        )}
        <p className="approval-disclaimer">
          Le backend devra recontrôler vos permissions avant tout appel MCP.
        </p>
      </footer>
    </aside>
  );
}
