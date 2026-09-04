# Third-party components

Local AI Hub can install or invoke third-party software; those components are not bundled in the release ZIP and retain their upstream licenses.

Default integration targets for the 1.5.0 release:

- Ollama — local inference runtime — https://ollama.com/
- Serena (`serena-agent==1.7.0`) — semantic coding/indexing MCP — https://github.com/oraios/serena
- CodeGraphContext (`codegraphcontext[gcf]==0.6.8`) — code graph/indexing MCP — https://github.com/CodeGraphContext/CodeGraphContext
- Qwen2.5-Coder and Qwen3.5 models through Ollama
- Jina Embeddings v2 Base Code — https://huggingface.co/jinaai/jina-embeddings-v2-base-code
- BGE Reranker v2 M3 — https://huggingface.co/BAAI/bge-reranker-v2-m3
- SentenceTransformers — https://www.sbert.net/
- Model Context Protocol Python SDK — https://github.com/modelcontextprotocol/python-sdk

Review upstream licenses before redistributing models or third-party packages.
