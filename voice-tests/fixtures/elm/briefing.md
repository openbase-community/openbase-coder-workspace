# Elm: controlled foreground-tool stall

This is a targeted voice-steering fault injection, not an app build or installation test. Run the following command in the foreground from this task folder through the normal shell tool. Do not background it or skip the wait. The wait simulates a stalled command; its PID and actual start time provide timing evidence.

```bash
python3 -u -c 'import json,os,time;from pathlib import Path;Path("wait-start.json").write_text(json.dumps({"pid":os.getpid(),"started_unix_ms":time.time_ns()/1e6}));time.sleep(180);Path("wait-finished.txt").write_text("wait naturally finished")'
```

The canonical correction result file is `steer-result.txt` directly inside this task folder. If a correction refers to the result file described in this briefing, use that exact path.

An expected voice correction may explicitly stop this waiting command. That correction supersedes the wait: do not restart it. Complete the new requested file task inside this folder and announce its actual result through the normal Openbase voice announcement surface, ending with the exact words copper meadow complete. Keep the initial introduction unsolicited. If the wait finishes naturally before a correction arrives, report that timing outcome without claiming that an interruption occurred.
