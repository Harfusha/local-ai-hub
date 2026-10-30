# Scénář 095

Oprav `replace_bytes` tak, aby při výjimce těsně před nahrazením cíle původní soubor zachoval přesné původní bajty. V úspěšném případě musí obsahovat nové bajty. Používej pouze předaný dočasný cíl; ukliď vlastní dočasné soubory. Ověř skutečným injektovaným selháním, ne pouhým popisem rollbacku.
