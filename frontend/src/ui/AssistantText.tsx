import { opensABlock } from "./markdown-table";
import { parseBlocks, type Span } from "./rich-text";

/**
 * La réponse de NEXIA, mise en forme.
 *
 * Rendue en éléments React et jamais en HTML : le texte vient d'un modèle de
 * langage, et React échappe ce qu'il affiche. Une réponse qui contiendrait une
 * balise la montre donc au lieu de l'exécuter.
 *
 * Réservée aux réponses de l'assistant. Le message de la personne reste affiché tel
 * qu'elle l'a tapé — interpréter ses astérisques reviendrait à réécrire ses mots.
 */
function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((span, index) => {
        switch (span.kind) {
          case "strong":
            return <strong key={index}>{span.text}</strong>;
          case "emphasis":
            return <em key={index}>{span.text}</em>;
          case "code":
            return <code key={index}>{span.text}</code>;
          case "link":
            return (
              <a key={index} href={span.href} target="_blank" rel="noreferrer noopener">
                {span.text}
              </a>
            );
          default:
            return <span key={index}>{span.text}</span>;
        }
      })}
    </>
  );
}

export function AssistantText({ text }: { text: string }) {
  const blocks = parseBlocks(text);

  return (
    <div className="rich-text">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Titre = (["h3", "h4", "h5"] as const)[block.level - 1];
            return (
              <Titre key={index} className={`rich-text__heading rich-text__heading--${block.level}`}>
                <Spans spans={block.spans} />
              </Titre>
            );
          }
          case "list":
            return block.ordered ? (
              <ol key={index} className="rich-text__list">
                {block.items.map((item, position) => (
                  <li key={position}><Spans spans={item} /></li>
                ))}
              </ol>
            ) : (
              <ul key={index} className="rich-text__list">
                {block.items.map((item, position) => (
                  <li key={position}><Spans spans={item} /></li>
                ))}
              </ul>
            );
          case "table":
            return (
              <div key={index} className="rich-text__table-scroll">
                <table className="approval-table">
                  <thead>
                    <tr>
                      {block.table.headers.map((header, position) => (
                        <th key={position} scope="col">{header}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.table.rows.map((row, position) => (
                      <tr
                        key={position}
                        className={
                          opensABlock(row) ? "approval-table__block" : "approval-table__continued"
                        }
                      >
                        {row.map((cell, colonne) => (
                          <td key={colonne}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "rule":
            return <hr key={index} className="rich-text__rule" />;
          default:
            return (
              <p key={index} className="rich-text__paragraph">
                <Spans spans={block.spans} />
              </p>
            );
        }
      })}
    </div>
  );
}
