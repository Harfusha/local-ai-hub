from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from local_ai_hub.client import HubClient

def clear():
    if sys.stdout.isatty(): sys.stdout.write('\x1b[2J\x1b[H')
def main()->int:
    ap=argparse.ArgumentParser(description='Realtime Local AI Hub monitor')
    ap.add_argument('--interval',type=float,default=.75); ap.add_argument('--json-lines',action='store_true'); ap.add_argument('--once',action='store_true')
    a=ap.parse_args(); c=HubClient(tenant='human-monitor',config_path=str(ROOT/'config.toml')); cursor=0
    while True:
        status=c.get('/api/live/status'); live=c.get(f'/api/live?after={cursor}&limit=200'); cursor=int(live.get('cursor',cursor) or cursor)
        if a.json_lines:
            for e in live.get('events',[]): print(json.dumps(e,ensure_ascii=False),flush=True)
        else:
            clear(); q=status.get('scheduler',{}); o=status.get('observability',{}); p=status.get('preprocessing',{}); h=status.get('headless',{})
            print('LOCAL AI HUB — REALTIME  (Ctrl+C to exit)')
            print(f"Hub: {'UP' if status.get('hub_online') else 'DOWN'}  Ollama: {'UP' if status.get('ollama_online') else 'DOWN'}  Supervisor: {h.get('state','unknown')}  Restarts: {h.get('restarts',0)}")
            print(f"Model: {q.get('active_model') or 'idle'}  Queue: {q.get('queued',0)}  Inflight: {q.get('inflight',0)}  Active requests: {o.get('active_request_count',0)}  Background: {q.get('background_queued',0)}")
            print(f"Cache hit: {100*float(o.get('cache_hit_rate',0)):.1f}%  p95: {float(o.get('p95_duration_ms',0)):.0f} ms  Net cloud delta: {int(o.get('net_cloud_token_delta_est',0)):,}  Fallbacks: {o.get('fallback_count',0)}")
            print(f"Token accounting: gross={int(o.get('gross_cloud_tokens_avoided_est',0)):,}  protocol={int(o.get('agent_protocol_tokens_est',0)):,} (call={int(o.get('agent_tool_request_tokens_est',0)):,}, read={int(o.get('agent_tool_response_tokens_est',0)):,})  schema≈{int(o.get('tool_schema_tokens_exposure_est',0)):,}  local-compute={int(o.get('local_compute_tokens_avoided_est',0)):,}")
            print(f"Preprocess: {'paused' if p.get('paused') else 'active'} · steps={p.get('steps',0)} errors={p.get('errors',0)} yields={p.get('yields',0)}")
            for pr in p.get('projects', []):
                tot = max(1, int(pr.get('files', 0)))
                rag_f = int(pr.get('rag_files', 0))
                card_f = int(pr.get('file_cards', 0))
                overall = float(pr.get('overall_progress_pct', 0))
                p_idx = pr.get('phase_index', '?')
                p_tot = pr.get('total_phases', 11)
                phase_name = pr.get('phase', 'idle')
                status_str = pr.get('status', 'queued')
                print(f"  • {pr.get('project')}: [{status_str.upper()}] Fáze {p_idx}/{p_tot} ({phase_name}) — celkem: {overall:.1f}% | RAG: {rag_f}/{tot} ({rag_f*100//tot}%) | Karty: {card_f}/{tot}")
            print('\nRecent activity:')
            for e in list(live.get('events',[]))[-18:]:
                ts=time.strftime('%H:%M:%S',time.localtime(float(e.get('created_at',0))))
                flags=(' CACHE' if e.get('cache_hit') else '')+(' FALLBACK' if e.get('fallback_used') else '')+(' DEGRADED' if e.get('degraded') else '')
                print(f"{ts} {str(e.get('agent') or e.get('kind',''))[:10]:10} {str(e.get('stage') or e.get('event_type',''))[:12]:12} {str(e.get('model') or e.get('cache_layer',''))[:22]:22} {str(e.get('action') or e.get('operation') or '')[:62]}{flags}")
        if a.once: return 0
        time.sleep(max(.2,a.interval))
if __name__=='__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(0)
