#!/usr/bin/env python3
import asyncio
import json
import websockets

PEERS = {}

async def handler(ws):
    peer_id = None
    try:
        async for raw in ws:
            msg = json.loads(raw)
            
            t = msg.get("type")
            
            if t == "hello":
                peer_id = msg["peer_id"]
                PEERS[peer_id] = ws
                
                await ws.send(json.dumps({"type":"hello-ok"}))
            elif t in ("sdp-offer", "sdp-answer", "ice"):
                target = msg.get("to")
                if not target or target not in PEERS:
                    await ws.send(json.dumps({"type":"error",
                                              "reason":"target-not-found", 
                                              "target": target}))
                    continue
                msg["from"] = peer_id
                await PEERS[target].send(json.dumps(msg))
            else:
                await ws.send(json.dumps({"type":"error", "reason":"unknown-type", "got":t}))
    finally:
        if peer_id and PEERS.get(peer_id) is ws:
            del PEERS[peer_id]

async def main():
    public_ip = "0.0.0.0"
    public_port = 80  # Port 80'e ayarlandı
    print("Signaling server listening on ws:{}:{}".format(public_ip, public_port))
    async with websockets.serve(handler, public_ip, public_port):
        await asyncio.Future()
        
if __name__ == "__main__":
    asyncio.run(main())
    
        