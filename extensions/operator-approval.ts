// Operator policy: destructive or high-risk bash commands require explicit
// human approval before the agent may run them.
//
// This is a USER/GLOBAL extension (~/.pi/agent/extensions) on purpose.
// Project-local extensions are only loaded once a project is trusted, and
// the default defaultProjectTrust "ask" mode ignores them outright when no
// interactive decision is possible — which is always the case for an agent
// started headlessly by herdr.
//
// The herdr Pi integration learns about approval dialogs by listening for a
// "herdr:blocked" event on Pi's event bus, so any extension that opens a
// blocking dialog must announce it ({ active: true }) and clear it
// ({ active: false }). Without that handshake herdr reports the agent as
// "working" while it is really waiting on a human, and the bridge would
// never escalate it.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "bash") return undefined;
    const command = String((event.input && event.input.command) || "");
    if (!/\brm\s+-rf\b|APPROVAL_REQUIRED/.test(command)) return undefined;

    const label = "Approve destructive command?";
    pi.events.emit("herdr:blocked", { active: true, label });
    let approved;
    try {
      approved = await ctx.ui.confirm(label, command);
    } finally {
      pi.events.emit("herdr:blocked", { active: false });
    }
    if (!approved) return { block: true, reason: "Denied by operator" };
    return undefined;
  });
}
