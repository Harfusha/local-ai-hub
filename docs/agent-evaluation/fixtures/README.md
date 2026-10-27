# Synthetic lookup fixtures

Fixture revision: `eval-fixtures-v3`.

- `alpha/`: contains same-name symbols, one direct Python caller, a 218-line config file, API-to-storage flow, a stale HubClient example, and a PHP file for lexical coverage limits.
- `beta/`: separate importer project expecting `createdAt`, while alpha export writes `created_at`.

All files are inert synthetic source. No dependencies or runtime required. Use each folder as the explicit read-only root for cases 011–015, 017, and 018. Case 016 needs a staged old-index/current-source transition that this fixture alone does not provide. Never use these trees as production Hub state.

Revision 2 corrected the synthetic path normalizer to replace a single Windows separator character. Revision 3 adds the HubClient symbol needed by case 014.
