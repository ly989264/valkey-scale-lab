#!/bin/sh
# Hermetic verify command for the exploration loop (.agent-loop/config.yaml).
#
# A git worktree does not carry project/artifacts/ (gitignored), and
# product.unit.server_profile skips - which the Gate counts as FAIL - when the
# frozen exact-50 baseline is absent. Link the main checkout's read-only
# baselines into this tree, then run the suite unchanged. Run from project/.
set -eu
# AGENT_LOOP_BASELINES names the baselines directory explicitly (a CI checkout
# is not a worktree and shares nothing); otherwise use the main checkout's.
if [ -n "${AGENT_LOOP_BASELINES:-}" ]; then
  main_baselines="$AGENT_LOOP_BASELINES"
elif ! common_dir=$(git rev-parse --git-common-dir 2>/dev/null); then
  # Inside the Stage 6 jail the worktree's .git file points outside the mount,
  # so git cannot answer. Run the suite without the baselines rather than die
  # at this line: server_profile will report its skip honestly (24/25).
  main_baselines=""
else
  case "$common_dir" in /*) ;; *) common_dir="$(pwd)/$common_dir" ;; esac
  main_baselines="$(dirname "$common_dir")/project/artifacts/baselines"
fi
if [ ! -e artifacts/baselines ] && [ -d "$main_baselines" ]; then
  mkdir -p artifacts
  ln -s "$main_baselines" artifacts/baselines
fi
exec ./gate suite product.unit
