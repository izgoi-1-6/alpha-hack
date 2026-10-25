import { useEffect, useRef, useState } from "react";
import {
  CommandAttempts,
  CommandProblem,
  commandKey,
  commandProblem,
  settleCommand,
} from "./commands";

export type CommandResult<T> =
  | { ok: true; value: T }
  | { ok: false; problem: CommandProblem };

/**
 * Runs one idempotent command at a time for a component. The server may finish a command after the component has
 * gone; such a late result is dropped (null) instead of replacing whatever the customer is looking at now.
 */
export function useCommand(
  attempts: CommandAttempts,
  onUnauthorized: () => void,
) {
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState<CommandProblem | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function run<T>(
    name: string,
    scope: string,
    body: unknown,
    send: (key: string) => Promise<T>,
  ): Promise<CommandResult<T> | null> {
    const key = commandKey(attempts, scope, body);
    setBusy(name);
    setProblem(null);
    try {
      const value = await send(key);
      settleCommand(attempts, scope, key);
      if (!alive.current) return null;
      setBusy("");
      return { ok: true, value };
    } catch (error) {
      settleCommand(attempts, scope, key, error);
      if (!alive.current) return null;
      setBusy("");
      const found = commandProblem(error);
      if (found.kind === "session") {
        onUnauthorized();
        return null;
      }
      setProblem(found);
      return { ok: false, problem: found };
    }
  }

  return { busy, problem, setProblem, run, alive };
}
