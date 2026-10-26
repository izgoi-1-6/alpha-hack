import {
  Application,
  ApplicationDocument,
  DocumentChecklist,
  DocumentType,
  networkError,
  request,
  responseError,
} from "../../api";

/** The customer's document routes under /applications/{id}/documents and the local Alfa-Business hand-off link. */

type ApplicationBody = { application: Application };
const documentsPath = (applicationId: string) =>
  "/applications/" + encodeURIComponent(applicationId) + "/documents";

export type UploadFields = {
  documentType: DocumentType;
  /** The application version the upload applies to; every stored upload raises it by one. */
  version: number;
  file: File;
};

/**
 * A multipart upload through XMLHttpRequest, whose upload events report progress (fetch exposes none). Refusals
 * and lost responses are the same ApiError shapes `request` produces, so the command helpers treat them alike.
 */
function upload(
  applicationId: string,
  fields: UploadFields,
  key: string,
  onProgress: (fraction: number) => void,
) {
  return new Promise<{ document: ApplicationDocument; application: Application }>(
    (resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/v1" + documentsPath(applicationId));
      xhr.setRequestHeader("Idempotency-Key", key);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0)
          onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        let data: unknown = null;
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          // A gateway page or an empty body: the status alone decides.
        }
        if (xhr.status >= 200 && xhr.status < 300 && data)
          resolve(data as { document: ApplicationDocument; application: Application });
        else reject(responseError(xhr.status, data));
      };
      // No answer arrived (a dropped connection, an aborted or timed-out request): the outcome is unknown.
      xhr.onerror = () => reject(networkError());
      xhr.onabort = () => reject(networkError());
      xhr.ontimeout = () => reject(networkError());
      const form = new FormData();
      form.append("document_type", fields.documentType);
      form.append("version", String(fields.version));
      form.append("file", fields.file, fields.file.name);
      xhr.send(form);
    },
  );
}

export const documentsApi = {
  /** Requirements with their current documents, and every revision (superseded and deleted ones included). */
  checklist: (applicationId: string, signal?: AbortSignal) =>
    request<DocumentChecklist>(documentsPath(applicationId), { signal }),
  upload,
  /** Deletes the current, not yet accepted file of a requirement. */
  remove: (
    applicationId: string,
    documentId: string,
    body: { version: number },
    key: string,
  ) =>
    request<ApplicationBody>(
      documentsPath(applicationId) + "/" + encodeURIComponent(documentId),
      { method: "DELETE", body, idempotencyKey: key },
    ),
  /** Sends the whole packet to the officer (PREAPPROVED or DOCS_REWORK → DOCS_UPLOADED). */
  complete: (applicationId: string, body: { version: number }, key: string) =>
    request<ApplicationBody>(documentsPath(applicationId) + "/complete", {
      method: "POST",
      body,
      idempotencyKey: key,
    }),
  /** APPROVED only: the address of the local hand-off page. Nothing is sent to a bank. */
  handoffLink: (body: { application_id: string }, key: string) =>
    request<{ url: string; simulated: true }>(
      "/integrations/alfa-business/link",
      { method: "POST", body, idempotencyKey: key },
    ),
};
