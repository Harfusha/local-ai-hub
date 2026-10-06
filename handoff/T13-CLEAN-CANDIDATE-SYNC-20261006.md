# T13 clean-candidate reconciliation

Original dirty checkpoint: `9b1b4090`, retained on the existing sync branch.
Merge input: master `6deead06`. No original source or test work discarded.

Master already implements the candidate's atomic conversation reservation.
Keep its trace-system settings and admission/cancellation behavior. Retain the
candidate's explicit async-disabled rejection after the master operational-mode
gate, so maintenance and gaming admission cannot be bypassed.

Four source/test conflicts were resolved by behavior. Preserve conversation
capacity/reservation regressions and all five original async lifecycle test
functions separately from the newer explicit-language transcription test.
An automatic test merge incorrectly joined those unrelated test bodies; it
was reconstructed without changing expected outcomes.

Check:
`python -B -m pytest -q -p no:cacheprovider tests/test_conversations.py
tests/test_mcp_agent_routing.py -k 'start_reserved or
conversation_start_at_capacity or reserves_new_conversation or async_job or
explicit_language_hint' --tb=short --maxfail=4`:
**10 passed, 4 failed, 62 deselected in 3.70s**, stopped at four failures.

Remaining failures: async control/wait/submit fixtures receive success=false;
conversation-submit rejection lacks the expected terminal field. Investigate
current feature/mode/schema/fake-transport contracts after consolidation;
do not weaken expectations or alter the user's live mode to manufacture green.
Atomic reservation and explicit-language tests passed within this selection.

This is committed preservation and synchronization, not release acceptance.
