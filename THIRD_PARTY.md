# Third-party components

Local AI Hub can install or invoke third-party software; those components are not bundled in the release ZIP and retain their upstream licenses.

Optional/default integration targets for the current release:

- Ollama — local inference runtime — https://ollama.com/
- Serena (`serena-agent==1.7.0`) — semantic coding/indexing MCP — https://github.com/oraios/serena
- Qwen2.5-Coder and Qwen3.5 models through Ollama
- Jina Embeddings v2 Base Code — https://huggingface.co/jinaai/jina-embeddings-v2-base-code
- BGE Reranker v2 M3 — https://huggingface.co/BAAI/bge-reranker-v2-m3
- SentenceTransformers — https://www.sbert.net/
- OpenVINO / Optimum Intel — optional Intel CPU/GPU/NPU inference backend — https://docs.openvino.ai/
- Model Context Protocol Python SDK — https://github.com/modelcontextprotocol/python-sdk

Review upstream licenses before redistributing models or third-party packages.

## Optional independent tooling

CodeGraphContext is a separately installed CLI/MCP tool, not a Local AI Hub dependency or managed backend. Users who want it can install and configure it directly with their agent using the [official project](https://github.com/CodeGraphContext/CodeGraphContext) and its installation instructions.
