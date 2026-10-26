import { useEffect, useRef, useState } from "react";
import { Application, DocumentType } from "../../api";
import {
  CommandAttempts,
  commandKey,
  commandProblem,
  settleCommand,
  unknownOutcome,
} from "../applications/commands";
import { documentsApi } from "./documentsApi";
import { documentTitle, fileProblem } from "./documentFormat";

export type UploadJob = {
  file: File;
  phase: "queued" | "uploading" | "failed";
  /** 0–1 of the bytes sent; 1 while the server checks the file. */
  progress: number;
  message?: string;
  /** The same file may be sent again: after a lost response (same key) or a version conflict (new version). */
  retry?: boolean;
};
type Jobs = Partial<Record<DocumentType, UploadJob>>;

/**
 * Uploads for one checklist, strictly one at a time: every stored upload raises the application version, so each
 * waits for the previous one and for the page's reload, then sends the version the server last returned. A file
 * chosen meanwhile waits in the queue. A lost response stops the queue until the customer repeats that upload, which
 * reuses its idempotency key, so the server replays a file it may already have stored instead of storing it twice.
 */
export function useDocumentUploads({
  application,
  attempts,
  reload,
  announce,
  onUnauthorized,
}: {
  application: Application;
  attempts: CommandAttempts;
  reload: () => Promise<unknown>;
  announce: (text: string) => void;
  onUnauthorized: () => void;
}) {
  const [jobs, setJobs] = useState<Jobs>({});
  const [done, setDone] = useState<Partial<Record<DocumentType, string>>>({});
  const version = useRef(application.version);
  const queue = useRef<DocumentType[]>([]);
  // The chosen file per requirement; `version` pins the version of an upload whose outcome is unknown, so its repeat
  // is the same command (same key) even after the page has learnt a newer version meanwhile.
  const files = useRef(new Map<DocumentType, { file: File; version?: number }>());
  const running = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // Versions only grow: the newest of the page's reads and the last upload's answer is the current one.
  useEffect(() => {
    version.current = Math.max(version.current, application.version);
  }, [application.version]);

  const update = (type: DocumentType, job: UploadJob | null) =>
    setJobs((current) => {
      const next = { ...current };
      if (job) next[type] = job;
      else delete next[type];
      return next;
    });

  function choose(type: DocumentType, file: File) {
    setDone((current) => ({ ...current, [type]: undefined }));
    const problem = fileProblem(file);
    if (problem) {
      files.current.delete(type);
      update(type, { file, phase: "failed", progress: 0, message: problem });
      return;
    }
    files.current.set(type, { file });
    update(type, { file, phase: "queued", progress: 0 });
    queue.current.push(type);
    void drain();
  }

  function retry(type: DocumentType) {
    const file = files.current.get(type)?.file;
    if (!file || queue.current.includes(type)) return;
    update(type, { file, phase: "queued", progress: 0 });
    queue.current.unshift(type);
    void drain();
  }

  function dismiss(type: DocumentType) {
    files.current.delete(type);
    update(type, null);
    void drain();
  }

  async function drain() {
    if (running.current) return;
    running.current = true;
    while (alive.current && queue.current.length) {
      const type = queue.current.shift()!;
      if (!(await send(type))) break;
    }
    running.current = false;
  }

  /** Sends one queued file; false stops the queue (the outcome of this upload is unknown). */
  async function send(type: DocumentType): Promise<boolean> {
    const chosen = files.current.get(type);
    if (!chosen) return true;
    const file = chosen.file;
    const sent = { documentType: type, version: chosen.version ?? version.current, file };
    const scope = `upload:${application.id}:${type}`;
    // The body identity: the same file for the same requirement on the same version.
    const key = commandKey(attempts, scope, {
      type,
      version: sent.version,
      name: file.name,
      size: file.size,
      modified: file.lastModified,
    });
    update(type, { file, phase: "uploading", progress: 0 });
    try {
      const result = await documentsApi.upload(application.id, sent, key, (progress) => {
        if (alive.current) update(type, { file, phase: "uploading", progress });
      });
      settleCommand(attempts, scope, key);
      version.current = Math.max(version.current, result.application.version);
      if (!alive.current) return false;
      files.current.delete(type);
      announce(`Файл «${file.name}» загружен: ${documentTitle(type)}.`);
      await reload();
      setDone((current) => ({ ...current, [type]: `Файл «${file.name}» загружен.` }));
      update(type, null);
      return true;
    } catch (error) {
      settleCommand(attempts, scope, key, error);
      if (!alive.current) return false;
      const problem = commandProblem(error);
      if (problem.kind === "session") {
        onUnauthorized();
        return false;
      }
      if (problem.kind === "network") {
        // The server may have stored it: the repeat sends the same version, so it is replayed, never stored twice.
        files.current.set(type, { file, version: sent.version });
        update(type, {
          file,
          phase: "failed",
          progress: 0,
          retry: true,
          message: unknownOutcome(
            problem,
            "Файл мог уже сохраниться: нажмите «Повторить загрузку» — повтор не создаст второй документ.",
          ),
        });
        return false;
      }
      const conflict = problem.kind === "version";
      // A refused upload stored nothing: a repeat after a version conflict is a new upload on the current version.
      if (conflict) files.current.set(type, { file });
      else files.current.delete(type);
      update(type, {
        file,
        phase: "failed",
        progress: 0,
        retry: conflict,
        message: conflict
          ? "Заявка изменилась в другой вкладке или окне: мы загрузили актуальную версию. Загрузите файл ещё раз."
          : [...new Set([problem.message, ...Object.values(problem.fields)])].join(" "),
      });
      if (conflict || problem.kind === "status") await reload();
      return true;
    }
  }

  const busy = Object.values(jobs).some((job) => job && job.phase !== "failed");
  return { jobs, done, busy, choose, retry, dismiss };
}
