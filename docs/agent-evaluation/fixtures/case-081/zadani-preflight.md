# Scénář 081 — řízená chyba před inferencí

Použij zadani.md, jeho tři texty a jedno batch volání. Pro druhou položku navíc úmyslně předej neplatné pole `prompt` s hodnotou `fixture-invalid-alias`, vedle obvyklých `task` a `context`. Hub má alias odmítnout před inferencí a přesto zpracovat nezávislou třetí položku. První a třetí položku nezměň. Neodstraňuj chybu za klienta ani ji nenormalizuj.

Jde o samostatný test chyby před inferencí, nikoliv důkaz bezpečného pokračování po HTTP chybě poskytovatele. Poskytovatel je syntetický; dávku s neznámým stavem neopakuj.
