#!/usr/bin/env python3
import asyncio
import json
import ssl
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
                print(f"[PEER] {peer_id} connected. Total peers: {len(PEERS)}")
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
                print(f"[RELAY] {t} from {peer_id} to {target}")
                
            else:
                await ws.send(json.dumps({"type":"error", "reason":"unknown-type", "got":t}))
                
    except websockets.exceptions.ConnectionClosed:
        print(f"[PEER] {peer_id} connection closed")
    finally:
        if peer_id and PEERS.get(peer_id) is ws:
            del PEERS[peer_id]
            print(f"[PEER] {peer_id} disconnected. Total peers: {len(PEERS)}")

async def main():
    public_ip = "0.0.0.0"
    public_port = 8443  # SSL için farklı port
    
    # SSL context oluştur
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(
        certfile="/etc/coturn/certs/turn_server_cert.pem",
        keyfile="/etc/coturn/certs/turn_server_pkey.pem"
    )
    
    print(f"Signaling server (WSS) listening on wss://{public_ip}:{public_port}")
    async with websockets.serve(handler, public_ip, public_port, ssl=ssl_context):
        await asyncio.Future()

async def main_http():
    """HTTP (plain WebSocket) version for backward compatibility"""
    public_ip = "0.0.0.0"
    public_port = 80
    print(f"Signaling server (WS) listening on ws://{public_ip}:{public_port}")
    async with websockets.serve(handler, public_ip, public_port):
        await asyncio.Future()
        
if __name__ == "__main__":
    import sys
    
    # Argümana göre SSL veya plain seç
    if "--ssl" in sys.argv or "--wss" in sys.argv:
        asyncio.run(main())
    else:
        asyncio.run(main_http())
