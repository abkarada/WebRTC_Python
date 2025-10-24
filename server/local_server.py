#!/usr/bin/env python3
"""Local signaling server for testing"""
import asyncio
import json
import websockets

PEERS = {}

async def handler(ws):
    peer_id = None
    client_addr = ws.remote_address
    print(f"[NEW CONNECTION] from {client_addr}")
    try:
        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type")
            
            if t == "hello":
                peer_id = msg["peer_id"]
                PEERS[peer_id] = ws
                print(f"[HELLO] Peer '{peer_id}' connected. Total: {len(PEERS)}")
                await ws.send(json.dumps({"type":"hello-ok"}))
                
            elif t in ("sdp-offer", "sdp-answer", "ice"):
                target = msg.get("to")
                if not target or target not in PEERS:
                    print(f"[ERROR] Target '{target}' not found")
                    await ws.send(json.dumps({"type":"error", "reason":"target-not-found"}))
                    continue
                msg["from"] = peer_id
                print(f"[RELAY] {t} from '{peer_id}' to '{target}'")
                await PEERS[target].send(json.dumps(msg))
                
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        if peer_id and PEERS.get(peer_id) is ws:
            del PEERS[peer_id]
            print(f"[DISCONNECT] '{peer_id}' left. Remaining: {list(PEERS.keys())}")

async def main():
    print("="*50)
    print("🚀 LOCAL Signaling Server")
    print("📡 ws://localhost:8765")
    print("="*50)
    async with websockets.serve(handler, "localhost", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
