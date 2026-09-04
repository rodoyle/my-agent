import {
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
} from "@earendil-works/pi-coding-agent";

import { buildModelForRun } from "./gateway-model.js";
import { makeRestrictedTools } from "./restricted-tools.js";
import { loadTaskContract, writeAgentResult } from "./task-contract.js";
import { RunObserver } from "./run-observer.js";

const task = await loadTaskContract("/workspace/.agent/task.json");
const model = await buildModelForRun({
  gatewayBaseUrl: process.env.LLM_GATEWAY_URL!,
  runToken: process.env.LLM_RUN_TOKEN!,
  modelAlias: task.modelPolicy.selectedAlias,
});

const resourceLoader = new DefaultResourceLoader({
  cwd: "/workspace",
  agentDir: "/opt/pi-agent-base",
  additionalExtensionPaths: [],
  extensionFactories: [],
});

await resourceLoader.reload();

const tools = makeRestrictedTools({
  task,
  runId: task.runId,
  workspace: "/workspace",
  commandEndpoint: process.env.AGENTCTL_ENDPOINT!,
});

const { session } = await createAgentSession({
  model,
  resourceLoader,
  tools,
  customTools: tools,
  sessionManager: SessionManager.inMemory(),
});

const observer = new RunObserver({
  task,
  session,
  emitEvent: async (event) => {
    await fetch(process.env.CONTROLLER_EVENTS_URL!, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "authorization": `Bearer ${process.env.RUN_EVENT_TOKEN}`
      },
      body: JSON.stringify(event)
    });
  }
});

const unsubscribe = session.subscribe((event) => observer.onPiEvent(event));

try {
  await session.prompt(`
Read .agent/task.json and follow the repository instructions.

You have one bounded execution attempt. Implement only the requested change,
run the required checks, and write .agent/result.json. Do not ask questions.
If blocked, write a structured BLOCKED result with exact evidence. Do not
repeat an unchanged failing command or alter policy/security controls to pass.
  `.trim());

  const result = await observer.finalize();
  await writeAgentResult("/workspace/.agent/result.json", result);
  process.exit(result.exitCode);
} catch (error) {
  await observer.recordRunnerFailure(error);
  process.exit(31);
} finally {
  unsubscribe();
  session.dispose();
}
