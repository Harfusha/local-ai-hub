# Fixture 089: samostatná výchozí aplikace

`python -B prepare.py ABSOLUTNÍ-NOVÝ-ROOT` vytvoří nový Git repozitář mimo existující repozitáře. Seed obsahuje malou aplikaci, datový soubor a baseline test; neobsahuje implementaci exportu. Původní prompt je v `docs/agent-evaluation/prompts.md`. Po běhu operátor samostatně ověří rozsah, dokumentaci, testy a výstup; samotný seed ani úspěch lokálních testů neprokazují dokončení Agent OS úlohy nebo funkčnost běžícího Hubu.

Každé opakování musí použít nový root. Nespouštěj ani neměň produkční Hub. Tento seed není totožný s historickou fixture a jeho výsledek proto nelze bez dalšího kvantitativně porovnat s předchozím během.
