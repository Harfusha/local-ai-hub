# Fixture 093

`python prepare_export.py <nová-složka>` vytvoří nezávislý Git repozitář a skutečný konflikt exportu mezi UTF-8 změnou agent-a a atomickým zápisem agent-b. Cíl a příklady jsou v `PLAN.md`; `CHECKPOINT.md` popisuje simulovaný výchozí stav. Složka nesmí existovat. Pro hodnocení skutečného pokračování po přerušení musí provozovatel navíc provést a zaznamenat skutečné přerušení vlastního testovaného agenta; samotný seed jej nedokazuje. Po řešení ověř `python -B -m unittest test_export`, obě změny a stav merge. Nepoužívej produkční checkout.

Původní `prepare.py` vytváří cenový konflikt a zůstává dostupný pro reprodukci historických výsledků; neodpovídá zadání o exportu.
