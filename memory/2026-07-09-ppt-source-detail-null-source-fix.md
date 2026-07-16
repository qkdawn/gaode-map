# 2026-07-09 PPT Source Detail Null Source Fix

## Symptom

Opening the AI panel and switching to the PPT tab after restoring a local archive could crash the frontend. The visible console error chain was:

- `Unhandled error during execution of setup function` at `PptPlanningWorkbench`
- `TypeError: Cannot read properties of null (reading 'meta')`
- Follow-on Vue update failure: `TypeError: instance.update is not a function`

## Root Cause

The new current-source detail navigation changed the workbench setup to compute canonical `EvidenceNode` rows with:

`currentSourceEvidenceNodes(activeCurrentSource.value)`

During component setup, no current source is selected yet, so `activeCurrentSource.value` is `null`. `source-view.js` treated the default parameter as sufficient, but JavaScript default parameters do not apply to explicit `null`; `sourceMeta(null)` tried to read `null.meta` and threw during setup. That failed component setup, and Vue later reported `instance.update is not a function` while reconciling the broken component tree.

## Fix

- `frontend/src/features/ppt-planning/source-view.js`
  - `sourceMeta` now normalizes non-object or null sources to `{}`.
- `frontend/tests/ppt-source-view.test.js`
  - Added regression coverage for `currentSourceEvidenceNodes(null)`, `sourceTransport(null)`, and `sourceTransportLabel(null)`.
- `frontend/src/features/history/restore.js`
  - Declared `currentHistoryPolygon` and `currentHistoryPolygonGcj02` in history initial state to remove remaining App render warnings surfaced on the same path.
- `frontend/tests/history-list-navigation.test.js`
  - Expanded bridge coverage for those history polygon fields.

## Verification

- `node --test tests/history-list-navigation.test.js tests/poi-flow.test.js tests/ppt-source-view.test.js tests/ppt-planning.test.js`
- `npm.cmd run build`
- Browser path:
  - Open `/analysis`.
  - Open local archives.
  - Restore the first archive with AI records.
  - Switch to AI.
  - Switch to PPT.
  - Confirmed `PptPlanningWorkbench` rendered, source rows were visible, and console had no Vue warnings or page errors.
