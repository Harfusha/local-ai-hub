# Fixture 095

Pro každý běh použij novou dočasnou kopii. `oracle_095.py` používá `TemporaryDirectory`, skutečný failpoint před replace a kontroluje zachování bajtů i úklid. Výsledek fixture není důkaz chování produkčního Hubu.
