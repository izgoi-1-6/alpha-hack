import { useEffect, useState } from "react";
import { applicationsApi } from "../../api";
import { CommandAttempts, CommandProblem } from "./commands";
import { useCommand } from "./useCommand";

/**
 * Starts a draft from a card of the saved recommendation snapshot. A repeated click after a lost response reuses the
 * key, so the server returns the draft it already created instead of a second one.
 */
export function useStartApplication({
  companyId,
  snapshotId,
  attempts,
  onCreated,
  onUnauthorized,
}: {
  companyId: string;
  snapshotId: string | null;
  attempts: CommandAttempts;
  onCreated: (applicationId: string) => void;
  onUnauthorized: () => void;
}) {
  const command = useCommand(attempts, onUnauthorized);
  const [productId, setProductId] = useState<string | null>(null);
  // A message about one snapshot never describes the next one.
  useEffect(() => command.setProblem(null), [snapshotId]);

  async function start(product: string) {
    if (!snapshotId || command.busy) return;
    const body = {
      company_id: companyId,
      product_id: product,
      recommendation_snapshot_id: snapshotId,
    };
    setProductId(product);
    const result = await command.run(
      "create",
      `create:${companyId}:${product}:${snapshotId}`,
      body,
      (key) => applicationsApi.create(body, key),
    );
    if (result?.ok) onCreated(result.value.application.id);
  }

  const problem: { productId: string; problem: CommandProblem } | null =
    command.problem && productId
      ? { productId, problem: command.problem }
      : null;
  return {
    start,
    pending: command.busy ? productId : null,
    problem,
  };
}
