import json
import pytest
from tools.model_training.mine_code_triplets import CodeTripletMiner, CodeChunk


def test_code_chunk_extraction():
    miner = CodeTripletMiner()

    sample_source = """
def compute_fibonacci(n: int) -> int:
    \"\"\"Calculate nth Fibonacci number iteratively.\"\"\"
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b

def compute_factorial(n: int) -> int:
    \"\"\"Compute factorial of n.\"\"\"
    res = 1
    for i in range(2, n + 1):
        res *= i
    return res
"""
    chunks = miner.extract_chunks_from_source(sample_source, file_path="math_utils.py")
    assert len(chunks) == 2
    symbols = {c.symbol_name for c in chunks}
    assert "compute_fibonacci" in symbols
    assert "compute_factorial" in symbols


def test_triplet_mining_with_hard_negatives():
    miner = CodeTripletMiner()

    sample_source = """
def acquire_shared_buffer(pool_id: str, size: int) -> memoryview:
    \"\"\"Acquire allocated shared memory segment from pool.\"\"\"
    shm = open_shm(pool_id)
    return memoryview(shm.buf)[:size]

def release_shared_buffer(pool_id: str, view: memoryview) -> None:
    \"\"\"Release active view and recycle shared memory segment.\"\"\"
    view.release()
    close_shm(pool_id)
"""
    chunks = miner.extract_chunks_from_source(sample_source, file_path="ipc_pool.py")
    triplets = miner.mine_triplets(chunks)

    assert len(triplets) == 2
    # The negative for acquire_shared_buffer should be release_shared_buffer (same file, high token overlap)
    t0 = triplets[0]
    assert t0.positive_symbol == "acquire_shared_buffer"
    assert t0.negative_symbol == "release_shared_buffer"
    assert t0.query == "Acquire allocated shared memory segment from pool"
    assert t0.lexical_overlap > 0.3


def test_mine_from_directory(tmp_path):
    miner = CodeTripletMiner()

    file1 = tmp_path / "module_a.py"
    file1.write_text("""
def save_checkpoint(state: dict, path: str) -> bool:
    \"\"\"Save model state checkpoint to disk.\"\"\"
    with open(path, "w") as f:
        json.dump(state, f)
    return True

def restore_checkpoint(path: str) -> dict:
    \"\"\"Restore model checkpoint from disk.\"\"\"
    with open(path, "r") as f:
        return json.load(f)
""", encoding="utf-8")

    out_file = tmp_path / "triplets.jsonl"
    triplets = miner.mine_from_directory(tmp_path, output_file=out_file)

    assert len(triplets) == 2
    assert out_file.exists()
    lines = out_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    data = json.loads(lines[0])
    assert "query" in data
    assert "positive" in data
    assert "negative" in data


def test_polyglot_chunk_extraction_rust_and_go():
    miner = CodeTripletMiner()

    rust_source = """
/// Calculate spatial distance between points.
pub fn calculate_distance(p1: (f64, f64), p2: (f64, f64)) -> f64 {
    let dx = p1.0 - p2.0;
    let dy = p1.1 - p2.1;
    (dx * dx + dy * dy).sqrt()
}

/// Normalize coordinate vector.
pub fn normalize_vector(v: (f64, f64)) -> (f64, f64) {
    let len = (v.0 * v.0 + v.1 * v.1).sqrt();
    if len > 0.0 {
        (v.0 / len, v.1 / len)
    } else {
        (0.0, 0.0)
    }
}
"""
    rust_chunks = miner.extract_chunks_from_source(rust_source, file_path="geometry.rs")
    assert len(rust_chunks) == 2
    symbols = {c.symbol_name for c in rust_chunks}
    assert "calculate_distance" in symbols
    assert "normalize_vector" in symbols
    assert "Calculate spatial distance between points" in rust_chunks[0].docstring

    go_source = """
// Start begins listening on network port.
func (s *Server) Start(port int) error {
    s.port = port
    return s.listen()
}

// Stop cleanly terminates active server connections.
func (s *Server) Stop() error {
    return s.closeListener()
}
"""
    go_chunks = miner.extract_chunks_from_source(go_source, file_path="server.go")
    assert len(go_chunks) == 2
    go_symbols = {c.symbol_name for c in go_chunks}
    assert "Start" in go_symbols
    assert "Stop" in go_symbols


def test_polyglot_directory_mining(tmp_path):
    miner = CodeTripletMiner()

    rs_file = tmp_path / "crypto.rs"
    rs_file.write_text("""
/// Encrypt raw payload with AES key.
pub fn encrypt_payload(data: &[u8], key: &[u8]) -> Vec<u8> {
    let mut out = data.to_vec();
    out.reverse();
    out
}

/// Decrypt raw payload with AES key.
pub fn decrypt_payload(data: &[u8], key: &[u8]) -> Vec<u8> {
    let mut out = data.to_vec();
    out.reverse();
    out
}
""", encoding="utf-8")

    ts_file = tmp_path / "api.ts"
    ts_file.write_text("""
// Fetch user account details
export async function fetchUserAccount(id: string): Promise<any> {
    return fetch(`/api/users/${id}`).then(r => r.json());
}

// Delete user account
export async function deleteUserAccount(id: string): Promise<boolean> {
    return fetch(`/api/users/${id}`, { method: 'DELETE' }).then(() => true);
}
""", encoding="utf-8")

    out_file = tmp_path / "polyglot_triplets.jsonl"
    triplets = miner.mine_from_directory(tmp_path, output_file=out_file)

    assert len(triplets) >= 4
    files = {t.file_path for t in triplets}
    assert any("crypto.rs" in f for f in files)
    assert any("api.ts" in f for f in files)


def test_multilingual_czech_docstring_and_universal_fallback():
    miner = CodeTripletMiner()

    # Test Czech docstring in Rust/universal format
    czech_source = """
/// Výpočet kontrolního součtu pro blok dat.
pub fn spocti_kontrolni_soucet(data: &[u8]) -> u32 {
    let mut sum: u32 = 0;
    for b in data {
        sum = sum.wrapping_add(*b as u32);
    }
    sum
}

/// Ověření integrity přijatého paketu podle hlavičky.
pub fn over_integritu_paketu(data: &[u8], expected: u32) -> bool {
    spocti_kontrolni_soucet(data) == expected
}
"""
    chunks = miner.extract_chunks_from_source(czech_source, file_path="kontrola.rs")
    assert len(chunks) == 2
    assert chunks[0].symbol_name == "spocti_kontrolni_soucet"
    assert "Výpočet kontrolního součtu" in chunks[0].docstring
    # Query must preserve natural Czech sentence without forcing English "How to"
    q0 = miner.synthesize_query(chunks[0])
    assert "Výpočet kontrolního součtu pro blok dat" in q0

    # Test universal semantic block fallback on SQL / unknown format
    sql_source = """
-- Vytvoření tabulky uživatelských relací
CREATE TABLE user_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vyčištění expirovaných relací
DELETE FROM user_sessions
WHERE created_at < NOW() - INTERVAL '30 days';
"""
    sql_chunks = miner.extract_chunks_from_source(sql_source, file_path="relace.sql")
    assert len(sql_chunks) >= 2
    assert any("user_sessions" in c.code_text for c in sql_chunks)


def test_read_text_safe_multi_encoding_and_binary_guard(tmp_path):
    from tools.model_training.mine_code_triplets import read_text_safe

    # 1. CP1250 (Czech Windows encoding)
    cp1250_file = tmp_path / "cesky.txt"
    cp1250_text = "Příliš žluťoučký kůň úpěl ďábelské ódy."
    cp1250_file.write_bytes(cp1250_text.encode("cp1250"))
    read_cp1250 = read_text_safe(cp1250_file)
    assert read_cp1250 is not None
    assert "žluťoučký" in read_cp1250

    # 2. UTF-8 with BOM
    bom_file = tmp_path / "with_bom.py"
    bom_file.write_bytes(b"\xef\xbb\xbfdef test_func():\n    return 42\n")
    read_bom = read_text_safe(bom_file)
    assert read_bom is not None
    assert "def test_func" in read_bom

    # 3. UTF-16 LE with BOM
    u16_file = tmp_path / "utf16.txt"
    u16_text = "Toto je UTF-16 kódovaný soubor s českými znaky."
    u16_file.write_bytes(u16_text.encode("utf-16"))
    read_u16 = read_text_safe(u16_file)
    assert read_u16 is not None
    assert "českými" in read_u16

    # 4. Binary file with null bytes
    bin_file = tmp_path / "binary.dat"
    bin_file.write_bytes(b"ELF\x00\x01\x02\x03\x00" * 20)
    assert read_text_safe(bin_file) is None

    # 5. Minified file with massive line
    min_file = tmp_path / "bundle.min.js"
    min_file.write_text("var a=" + "x," * 1000 + "z=1;", encoding="utf-8")
    assert read_text_safe(min_file) is None


def test_markdown_chunker_extraction():
    miner = CodeTripletMiner()
    md_content = """# Projektová Dokumentace

Tento projekt implementuje vysoce výkonný inferenční engine pro lokální modely.
Podporuje CUDA, ROCm i Apple Metal akceleraci.

## Instalace a Nastavení

Pro instalaci spusťte instalační skript z kořenového adresáře:
```bash
python tools/installer.py --preset high
```
Zkontrolujte závislosti a hardware profily.

## Konfigurace Rerankeru

Konfigurační soubor `config.toml` obsahuje nastavení prahů:
```toml
[reranker]
threshold = 0.75
batch_size = 32
```
Tento krok optimalizuje přesnost vyhledávání.
"""
    chunks = miner.extract_chunks_from_source(md_content, file_path="docs/README.md")
    assert len(chunks) >= 2
    symbols = {c.symbol_name for c in chunks}
    assert any("Instalace" in s for s in symbols)
    assert any("Konfigurace" in s for s in symbols)
    # Triplet generation should work on Markdown chunks
    triplets = miner.mine_triplets(chunks)
    assert len(triplets) >= 2
    assert any("Instalace" in t.query or "Instalace" in t.positive for t in triplets)


def test_cross_file_hard_negative_fallback(tmp_path):
    miner = CodeTripletMiner()

    # File 1 has only ONE function
    f1 = tmp_path / "allocator.rs"
    f1.write_text("""
/// Allocate memory buffer for incoming packet stream.
pub fn allocate_packet_buffer(capacity: usize) -> Vec<u8> {
    Vec::with_capacity(capacity)
}
""", encoding="utf-8")

    # File 2 has only ONE function
    f2 = tmp_path / "deallocator.rs"
    f2.write_text("""
/// Deallocate memory buffer and reclaim system memory.
pub fn free_packet_buffer(buf: Vec<u8>) {
    drop(buf);
}
""", encoding="utf-8")

    # When scanned from directory, cross-file hard negative must pair them together!
    triplets = miner.mine_from_directory(tmp_path)
    assert len(triplets) == 2
    t0 = triplets[0]
    t1 = triplets[1]
    # They should be paired as cross-file hard negatives for each other
    assert {t0.positive_symbol, t0.negative_symbol} == {"allocate_packet_buffer", "free_packet_buffer"}
    assert {t1.positive_symbol, t1.negative_symbol} == {"allocate_packet_buffer", "free_packet_buffer"}



