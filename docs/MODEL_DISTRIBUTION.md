# Model Distribution and Automated Provisioning

Tento dokument popisuje distribuční architekturu pro vytrénované modely Local AI Hubu (zejména preprocessing modely `qwen2.5-coder-prep:*` a klasifikátor `laya:multilingual-v2`).

---

## 1. Architektura distribuce

Vytrénované modely Local AI Hubu nejsou standardní součástí upstream Ollama library. Proto Local AI Hub disponuje vlastním distribučním a verifikačním subsystémem:

1. **Formát modelů**:
   - LLM modely: **GGUF v kvantizaci Q4_K_M** (kompatibilní s llama.cpp a Ollamou).
   - Klasifikátory (Laya): **SafeTensors** s ověřenou architekturou a konfigurací tokenizéru.
2. **Hosting a CDN**:
   - Primární: Oficiální Hugging Face repozitář (`https://huggingface.co/local-ai-hub/preprocessing-models/`).
   - Sekundární (Mirror): GitHub Releases repozitáře `local-ai-hub`.
3. **Integrita a Zero Trust**:
   - Každý artefakt má pevně v kódu zakotvený kontrolní součet **SHA-256**.
   - Stažený soubor se před registrací do Ollamy striktně ověří. Při neshodě kontrolního součtu je soubor okamžitě smazán a registrace odmítnuta.

---

## 2. Pinned Registry artefaktů

V `src/local_ai_hub/model_distribution.py` je definován registr:

| Model | Typ | Formát | Velikost | SHA-256 hash |
|---|---|---|---|---|
| `qwen2.5-coder-prep:3b` | Preprocessing LLM | GGUF Q4_K_M | 1.80 GB | `088ba85485564eebea76573062d94fc066a764dead450a43db5fda9d60d4c095` |
| `qwen2.5-coder-prep:1.5b` | Preprocessing LLM | GGUF Q4_K_M | 0.94 GB | `4b681e1e0a9d18c3b7a5a3a0e69a08e6f1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6` |
| `qwen2.5-coder-prep:0.5b` | Preprocessing LLM | GGUF Q4_K_M | 0.38 GB | `8a7c2b3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef` |
| `laya:multilingual-v2` | Decision classifier | SafeTensors | 120 MB | `461069f0854474c03e3398151276d557bc372acd9b0ebb09d4215c90e352cbd0` |

---

## 3. Automatický provisioning při instalaci a aktualizaci

Při spuštění `python tools/setup.py` nebo `python tools/hubctl.py setup`:
1. Instalační proces detekuje model nastavený v `[preprocessing] model = "..."`.
2. Pokud jde o vytrénovaný model z `DISTRIBUTION_REGISTRY`:
   - Zkontroluje, zda již existuje v Ollamě (`ollama list`).
   - Pokud chybí, vyhledá lokální GGUF v `state/models/`.
   - Pokud chybí i lokální soubor, stáhne jej z autoritativního CDN mirroru.
   - Ověří SHA-256 hash.
   - Automaticky sestaví Modelfile a zaregistruje model do Ollamy (`ollama create <model> -f <modelfile>`).

---

## 4. Správa přes CLI (`tools/model_distribution.py`)

Správci i uživatelé mohou stav modelů spravovat přímo:

```bash
# Zkontrolovat stav dostupnosti modelů v Ollamě a na disku
python tools/model_distribution.py status

# Synchronizovat a zaregistrovat všechny chybějící distribuční modely
python tools/model_distribution.py sync

# Synchronizovat konkrétní model
python tools/model_distribution.py sync --model qwen2.5-coder-prep:3b

# Zkontrolovat hash nově vytrénovaného GGUF artefaktu před releasem
python tools/model_distribution.py inspect-artifact state/models/qwen25-coder-3b-prep-q4_k_m.gguf
```

---

## 5. Offline a Air-Gapped instalace

V prostředích bez přístupu k internetu:
1. Uživatel stáhne `.gguf` soubory na externí médium.
2. Umístí je do adresáře `state/models/` v kořenu instalace Local AI Hubu.
3. Spustí `python tools/model_distribution.py sync --no-download`.
4. Systém ověří kontrolní součty a modely okamžitě zaregistruje do lokální Ollamy.
