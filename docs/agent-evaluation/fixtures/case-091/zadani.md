# Scénář 091

Výslovně deleguj dvě nezávislé úpravy: backend smí měnit pouze `backend.py`, frontend pouze `frontend.ts`. Backend `select_ready` vrací z řádků se `status == "ready"` pouze pole `id` a `name`, ve vstupním pořadí. Frontend přečte JSON pole ze stdin a zapíše UTF-8 CSV se záhlavím `id,name`, každé pole v uvozovkách, vnitřní uvozovky zdvojí a každý řádek zakončí LF. Primární agent integruje obě změny a spustí společný oracle.
