import pytest
from src.local_ai_hub.multi_repo_subgraph_pruner import MultiRepoSubgraphPruner


def test_multi_repo_subgraph_extraction():
    pruner = MultiRepoSubgraphPruner()

    # Setup multi-repo nodes (Hub + Antigravity + Laya)
    pruner.add_node("hub/app.py", repo="local-ai-hub", token_cost=500)
    pruner.add_node("hub/router.py", repo="local-ai-hub", token_cost=300)
    pruner.add_node("hub/laya_active.py", repo="local-ai-hub", token_cost=400)
    pruner.add_node("hub/db_legacy.py", repo="local-ai-hub", token_cost=600)  # Unrelated

    pruner.add_node("antigravity/skill_bridge.py", repo="antigravity", token_cost=350)
    pruner.add_node("antigravity/ui_view.py", repo="antigravity", token_cost=700)  # Far

    # Edges
    pruner.add_edge("antigravity/skill_bridge.py", "hub/app.py", relation="calls_api")
    pruner.add_edge("hub/app.py", "hub/laya_active.py", relation="imports")
    pruner.add_edge("hub/laya_active.py", "hub/router.py", relation="imports")
    pruner.add_edge("hub/app.py", "hub/db_legacy.py", relation="imports")
    pruner.add_edge("antigravity/skill_bridge.py", "antigravity/ui_view.py", relation="imports")

    # Seed query starts from: 'hub/laya_active.py' and 'antigravity/skill_bridge.py'
    # Total tokens before: 500+300+400+600+350+700 = 2850
    # Set budget to 1300 tokens: should fit seeds (750 tokens) + direct hub/app.py (500 tokens) = 1250 tokens
    result = pruner.extract_induced_subgraph(
        seed_nodes=["hub/laya_active.py", "antigravity/skill_bridge.py"],
        max_token_budget=1300,
        max_hop_distance=2,
    )

    # Verify seed nodes are preserved
    assert "hub/laya_active.py" in result.retained_nodes
    assert "antigravity/skill_bridge.py" in result.retained_nodes

    # hub/app.py connects both seeds, so it should be retained
    assert "hub/app.py" in result.retained_nodes

    # Unrelated legacy db and far ui view must be pruned
    assert "hub/db_legacy.py" in result.pruned_nodes
    assert "antigravity/ui_view.py" in result.pruned_nodes

    # Check budget and savings
    assert result.total_tokens_after <= 1300
    assert result.token_savings_percent >= 50.0

    # Check induced edges
    sources = {e.source for e in result.retained_edges}
    targets = {e.target for e in result.retained_edges}
    assert "antigravity/skill_bridge.py" in sources
    assert "hub/laya_active.py" in targets or "hub/app.py" in targets
