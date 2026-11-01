# Design changes (Milestone 6.2)

These notes are for the supervisor. They record changes from the original SRS that user testing made necessary.

## DC-01 Speech input

**Change.** Gemini transcription is the primary speech engine. Chrome's Web Speech API remains a fallback (`sttEngine: browser`, or automatically after a 503/timeout).

**Reason.** Live tests showed two failures in the browser recognizer: utterances were cut off (first or last words dropped), and Pakistani names and South Asian accents were misheard (`en-US` turned “Babar Azam” into “bubbleism”).

**Privacy.** Captured audio is sent to Google for transcription and is never stored on disk, in the database, or in logs. Chrome's Web Speech API also sends audio to a Google server.

**SRS impact.** §3.3 (speech input path), §6.3 Table 45 (STT component), NFR-SEC-07 (audio is not retained).

## DC-02 Languages

**Change.** English and Urdu, including mixed Urdu–English, are supported for both input and output. The user setting is `auto` (reply in the language just spoken), `en`, or `ur`.

**Reason.** Resolves TBD-07. The product is for blind people in Pakistan who switch languages mid-sentence.

**SRS impact.** TBD-07 is closed. Narration, classifier phrases, perception answers, and the UI dictionary all have `en` and `ur` entries.

## DC-03 Browser lifetime

**Change.** Chromium stays open between commands (Milestone 6). The user closes it with “close the browser” / “browser band karo” / Shift+Escape. If they close the window themselves, that is respected: the task is cancelled when one was running, and M6.1 tab recovery does not reopen it.

**Reason.** Escape already stopped speech and the task, but there was no way to dismiss the visible window. Recovery after a user close felt like the app was fighting them.

**SRS impact.** FR-02, FR-41..43 (stop and close), and the M6 “keep the browser open” rule.
