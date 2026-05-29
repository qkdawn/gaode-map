# DEBUG REPORT

- **Symptom:** Agent follow-up sometimes looked unresponsive after sending; the UI could show repeated identical user bubbles while the composer stayed in running state.
- **Root cause:** The report composer and quick prompt chips could call `submitAgentTurn({ useReactLoop: true })` while the active session was already running. `buildTurnContext` did not reject duplicate submissions for the same active session, so multiple ReAct requests raced against the same conversation state.
- **Fix:** The active running session is now rejected before a turn context is built, and quick prompt chips are disabled while the active session is running or hydrating.
- **Evidence:** `npm test -- --runInBand frontend/tests/agent-sessions.test.js` passed. The command runs the frontend node test suite in this project configuration and reported 198 passing tests.
- **Regression test:** `frontend/tests/agent-sessions.test.js` now includes `submitAgentTurn ignores duplicate submit while active session is running`, which verifies the second submit does not send another ReAct run request and does not append a duplicate user message.
- **Status:** DONE
