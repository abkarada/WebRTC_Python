#!/usr/bin/env python3
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
                print(f"[HELLO] Peer '{peer_id}' connected. Total peers: {len(PEERS)}")
                await ws.send(json.dumps({"type":"hello-ok"}))
            elif t in ("sdp-offer", "sdp-answer", "ice"):
                target = msg.get("to")
                if not target or target not in PEERS:
                    print(f"[ERROR] Target '{target}' not found. Available: {list(PEERS.keys())}")
                    await ws.send(json.dumps({"type":"error",
                                              "reason":"target-not-found", 
                                              "target": target}))
                    continue
                msg["from"] = peer_id
                print(f"[RELAY] {t} from '{peer_id}' to '{target}'")
                await PEERS[target].send(json.dumps(msg))
            else:
                print(f"[ERROR] Unknown message type: {t}")
                await ws.send(json.dumps({"type":"error", "reason":"unknown-type", "got":t}))
    except websockets.exceptions.ConnectionClosed:
        print(f"[DISCONNECT] Connection closed for peer '{peer_id}'")
    except Exception as e:
        print(f"[ERROR] Exception in handler: {e}")
    finally:
        if peer_id and PEERS.get(peer_id) is ws:
            del PEERS[peer_id]
            print(f"[CLEANUP] Removed peer '{peer_id}'. Remaining: {list(PEERS.keys())}")

async def main():
    public_ip = "0.0.0.0"
    public_port = 443  # Port 443'e ayarlandı
    print("="*50)
    print(f" Signaling Server Starting...")
    print(f" Listening on ws://{public_ip}:{public_port}")
    print(f" Connect from: ws://35.198.64.68:{public_port}")
    print("="*50)
    async with websockets.serve(handler, public_ip, public_port):
        await asyncio.Future()
        
if __name__ == "__main__":
    asyncio.run(main())
    
        