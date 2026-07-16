# 2026-07-09 Frontend History Store Bridge Fix

## Symptom

The analysis frontend could blank after restoring local archives. Console showed Vue component update warnings and `TypeError: instance.update is not a function`. The screenshot pointed at `tabs.js`, but browser repro also showed repeated Vue warnings for missing component properties:

- `historyLoadError`
- `historyRestoreProgress`
- `currentHistoryAvailablePoiYears`
- `poiResultsByYear`

## Root Cause

History module state was patched into the Pinia history store, but `ANALYSIS_HISTORY_STATE_KEYS` was a hand-maintained partial list. The Options API template accessed history fields through component properties, so missing keys were not exposed by the store computed bridge and Vue saw them as undefined during render.

`poiResultsByYear` had a similar declaration gap on the POI data side: it was written/read by runtime and agent summary code, but the app's initial data did not declare it.

## Fix

- `frontend/src/stores/analysis/history.js` now derives history store state and bridge keys from the actual history list/restore initial-state factories.
- `frontend/src/stores/analysis/poi.js` now declares the POI fields that templates and agent summaries read directly.
- Regression coverage was added in:
  - `frontend/tests/history-list-navigation.test.js`
  - `frontend/tests/poi-flow.test.js`

## Verification

- `node --test tests/history-list-navigation.test.js tests/poi-flow.test.js`
- `npm.cmd run build`
- Browser repro through `http://127.0.0.1:8000/analysis`:
  - Opened local archives.
  - Restored first archive with AI records.
  - Confirmed the result screen rendered and `历史恢复完成` appeared.
  - Confirmed no Vue warnings for the affected fields, no page errors, and no `instance.update` error.

## Notes

The AMap `ERR_BLOCKED_BY_CLIENT` request seen in the screenshot is a browser/client blocking issue and was not the fatal Vue crash.
