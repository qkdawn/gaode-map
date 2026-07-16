# 2026-07-09 frontend HMR instance.update

Symptom: The analysis/PPT frontend view became mostly blank and the browser console showed `TypeError: instance.update is not a function` from Vite's Vue runtime chunk `chunk-Y3W6OTI3.js`.

Root cause: The error came from Vue/Vite HMR rerender state, not from a syntax/build failure. A clean browser session against `http://127.0.0.1:8000/analysis` did not reproduce the error. The Vite dev server was still running with stale hot-update component state after several frontend edits.

Fix: Restarted only the Vite frontend process on port 5173. Backend on port 8000 was left running.

Evidence:
- `npm.cmd run build` completed successfully.
- After restarting Vite, a clean browser session opened `/analysis`, entered local history, restored a result page, and logged no `instance.update` errors.
- Remaining console output only contained pre-existing Vue warnings for undefined history/POI state fields.

Status: DONE_WITH_CONCERNS. No code change was required for this incident; if the same error appears after a hard refresh and Vite restart, investigate component HMR registration around `PptPlanningWorkbench.vue`.
