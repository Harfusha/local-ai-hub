# Model Residency Optimization Plan

1. Capture paired 7B and 9B benchmark samples while idle.
2. Add failing tests for persistent numeric tuner state and cold resident routing.
3. Persist validated tuner state atomically under `server.state_dir`.
4. Require calibrated measurements before cross-tier resident substitution.
5. Set conservative per-user tuner policy; leave Qwen runtime settings unchanged.
6. Run focused then full validation, inspect diff impact, restart Hub, and verify live tuner state.
