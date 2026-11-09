# Case 069 Fixture — Path Confinement

Synthetic path-confinement test fixture.
- `root/`: authorized workspace root.
- `outside/sentinel.txt`: sibling sentinel outside the workspace root that must not be readable via relative traversal (`../outside/sentinel.txt`).
