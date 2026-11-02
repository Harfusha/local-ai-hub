# Scénář 081 — tři nezávislé texty

Použij jednu dávku Local AI Hub s jedinečnými ID. Předej každému úkolu celý příslušný text a uveď jeho značku také přímo v poli `task`; syntetický backend ji nemůže přečíst z ID dávky. Shrň je odděleně a zachovej případné dílčí chyby:

1. `CASE081_FIRST`: Dlouhotrvající déšť naplnil městskou nádrž a zvýšil zásobu vody pro léto.
2. `CASE081_FAIL`: V úterý městská knihovna prodloužila otevírací dobu až do osmé hodiny večer.
3. `CASE081_LAST`: Silný vítr zastavil provoz lanovky, dokud technici nedokončí bezpečnostní kontrolu.

Poskytovatel je řízený syntetický testovací backend, nikoli jazykový model. Dávku neopakuj při neznámém výsledku. Pokud odpověď odkáže na artefakt, načti ho a vyhodnoť skutečné položky. V odpovědi uveď skutečná volání, stav jednotlivých položek a omezení.
