import type { SourceReference as Source } from "../domain/models";
import { LinkIcon } from "./icons";

const systemLabels = {
  jira: "Jira",
  confluence: "Confluence",
  figma: "Figma",
};

export function SourceReference({ source }: { source: Source }) {
  const content = (
    <>
      <span className={`source-mark source-mark--${source.system}`} aria-hidden="true">
        {systemLabels[source.system].slice(0, 1)}
      </span>
      <span className="source-copy">
        <span className="source-label">{source.label}</span>
        <span className="source-location">{source.location ?? systemLabels[source.system]}</span>
      </span>
      {source.inferred ? (
        <span className="source-inference">
          IA{source.confidence ? ` · ${Math.round(source.confidence * 100)} %` : ""}
        </span>
      ) : null}
      <LinkIcon className="source-link-icon" width={15} height={15} />
    </>
  );

  if (source.url) {
    return (
      <a
        className="source-reference"
        href={source.url}
        target="_blank"
        rel="noreferrer"
        aria-label={`${source.label} dans ${systemLabels[source.system]} : ${source.title}`}
      >
        {content}
      </a>
    );
  }

  return (
    <span className="source-reference" title={`${source.title} — fixture sans lien externe`}>
      {content}
    </span>
  );
}
