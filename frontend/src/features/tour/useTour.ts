import { useEffect, useRef, useState } from "react";
import { User } from "../../api";
import { readTourState, TourState, writeTourState } from "./persistence";

export type TourController = ReturnType<typeof useTour>;

/**
 * A client's walkthrough: it opens by itself until the client completes or skips it, and again from «Как это
 * работает» (`trigger`, where focus returns when it closes). Officers have none.
 */
export function useTour(user: User | null) {
  const userId = user?.role === "CLIENT" ? user.id : null;
  // One opening at a time, mounted afresh from its first step; `restart` marks an opening from «Как это работает».
  const [run, setRun] = useState<{ id: number; restart: boolean } | null>(null);
  const runs = useRef(0);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    setRun(
      userId && !readTourState(userId)
        ? { id: ++runs.current, restart: false }
        : null,
    );
  }, [userId]);
  return {
    enabled: userId !== null,
    run,
    trigger,
    restart() {
      if (userId) setRun({ id: ++runs.current, restart: true });
    },
    save(state: TourState) {
      if (userId) writeTourState(userId, state);
    },
    close() {
      setRun(null);
    },
  };
}
