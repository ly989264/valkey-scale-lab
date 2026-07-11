# Harness Exception - P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE

## Defect

The user requested phase `P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE`, but the repository did not contain `docs/codex/goal-loop/stages/P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE.md`, so the required stage document reload could not be completed from repository state.

## Patch

Add a stage document that captures the user-specified cluster-node-timeout requirements without weakening the existing harness rules. The new document is used as the controlling source for the P43 context reload, design brief, implementation, gates, and review.

## Before/After Behavior

Before: the stage was blocked because the required stage document was absent.

After: the required stage document exists and can be reread, summarized, and enforced by the P43 stage loop.
