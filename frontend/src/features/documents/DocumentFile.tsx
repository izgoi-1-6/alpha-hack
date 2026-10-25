import { ApplicationDocument } from "../../api";
import { Icon } from "../../components";
import { fileFacts, shortHash } from "./documentFormat";

/**
 * A stored revision: its name, file facts and the download through the authorized API route the server gave (never a
 * storage path). A deleted revision has no download. `showHash` adds the SHA-256 short form for the officer.
 */
export function DocumentFile({
  document,
  className,
  showHash = false,
}: {
  document: ApplicationDocument;
  className: string;
  showHash?: boolean;
}) {
  return (
    <div className={"document-file " + className}>
      <div className="document-file-text">
        <b className="document-file-name">{document.original_name}</b>
        <span className="document-file-facts">
          {fileFacts(document)}
          {showHash && (
            <>
              {" · SHA-256 "}
              <code title={document.sha256}>{shortHash(document.sha256)}</code>
            </>
          )}
        </span>
      </div>
      {document.download_url && (
        <a
          className="download-link"
          href={document.download_url}
          download
          aria-label={`Скачать файл «${document.original_name}»`}
        >
          <Icon name="download" size={18} />
          Скачать
        </a>
      )}
    </div>
  );
}
