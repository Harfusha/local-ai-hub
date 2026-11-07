# Case 035: bounded long-log failure

Copy this directory into a unique disposable temp root. From that copy run:

```powershell
python run_failure.py --root ROOT --log logs/failure.log
```

The script writes only a new log below the supplied root, emits exactly 10,000 lines, then exits with status 1. Set the host command output cap to at most 300 tokens. If the decisive line is not present in captured output, query only `ERROR` and `RUN_ID` lines from `logs/failure.log`. Do not replay the command; its log path uses exclusive creation. No package dependencies.
