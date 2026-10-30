# Case 066: cancel an asynchronous local job

Run `python prepare.py ABSOLUTE_NEW_ROOT` to create a fresh sandbox with a deterministic long, non-sensitive `long_input.md`. First chat turn starts exactly one local summarize job asynchronously and returns its job ID immediately; it must not wait, poll, or fetch the result. Send the catalog's second turn as a real user message: cancel only that job, start no replacement, then make exactly one bounded wait to capture terminal state. A fixture run is inconclusive if the job completed before cancellation.
