#!/usr/bin/env python3
"""Test if signaling server is reachable"""
import asyncio
import websockets
import json

async def test_connection():
    server_url = "ws://35.235.249.16:80"
    print(f"🔍 Testing connection to {server_url}...")
    
    try:
        async with websockets.connect(server_url, timeout=5) as ws:
            print("✅ Connected to server!")
            
            # Send hello
            hello_msg = {"type": "hello", "peer_id": "TestClient"}
            await ws.send(json.dumps(hello_msg))
            print(f"📤 Sent: {hello_msg}")
            
            # Wait for response
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"📥 Received: {response}")
            
            resp_data = json.loads(response)
            if resp_data.get("type") == "hello-ok":
                print("✅ Server responded correctly!")
                return True
            else:
                print(f"❌ Unexpected response: {resp_data}")
                return False
                
    except asyncio.TimeoutError:
        print("❌ Connection timeout! Server might not be running.")
        return False
    except ConnectionRefusedError:
        print("❌ Connection refused! Check if:")
        print("   1. Server is running on 35.235.249.16:80")
        print("   2. Firewall allows port 80")
        print("   3. GCP firewall rules are configured")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("="*50)
    print("WebRTC Signaling Server Test")
    print("="*50)
    success = asyncio.run(test_connection())
    exit(0 if success else 1)
