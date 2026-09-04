interface RunState {
  runId: string;
  taskId: string;
  phase:
    | "QUEUED"
    | "PRECHECK"
    | "RUNNING"
    | "VERIFYING"
    | "CORRECTING"
    | "REPLAN"
    | "REVIEW"
    | "WAITING_DEPENDENCY"
    | "BLOCKED"
    | "ESCALATED"
    | "SUCCEEDED"
    | "FAILED";
  attempt: number;
  correctionCycle: number;
  replanCount: number;
  budget: Budget;
  observations: Observation[];
  checkpoints: Checkpoint[];
}