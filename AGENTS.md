## Rules

- Small TODO items are marked inline with `# TODO - <task>`
- Plans go in docs/plans/*.md Consult these for a list of plans

## Verification failure protocol

When a required check fails:

1. Capture the complete command result and classify the failure:
   TRANSIENT_INFRASTRUCTURE, ENVIRONMENT_CAPABILITY, DETERMINISTIC_CONFIG,
   IMPLEMENTATION_DEFECT, TEST_DEFECT, or UNKNOWN.
2. State one falsifiable hypothesis explaining the failure.
3. Inspect only evidence relevant to that hypothesis.
4. Make one minimal change that tests the hypothesis.
5. Re-run the failed check, then the required regression checks.
6. Record diff hash, failure signature, and outcome.

Do not repeat a failed command if the repository diff, effective environment
revision, and failure signature are unchanged.

Stop with `BLOCKED` if required credentials, target state, or an irreversible
policy decision is missing. Stop with `FAILED` if the correction-cycle budget
is exhausted. Never weaken tests, readiness checks, resource limits, RBAC,
network policy, or security controls merely to obtain success.