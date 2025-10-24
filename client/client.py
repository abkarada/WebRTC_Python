#!/usr/bin/env python3
import asyncio, json, argparse, sys
import websockets

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GObject", "2.0")
from gi.repository import Gst, GObject, GLib

Gst.init(None)

class P2PClient:
    def __init__(self, ws_url, self_id, peer_id, use_camera=True, use_mic=True,
                 stun="stun://stun.l.google.com:19302"):
        self.ws_url = ws_url
        self.self_id = self_id
        self.peer_id = peer_id
        self.stun = stun

        self.use_camera = use_camera
        self.use_mic = use_mic

        self.ws = None
        self.pipeline = None
        self.webrtc = None

    async def run(self):
        self.ws = await websockets.connect(self.ws_url)
        # Store asyncio loop for thread-safe coroutine scheduling
        self.loop = asyncio.get_running_loop()
        await self.ws.send(json.dumps({"type":"hello", "peer_id": self.self_id}))
        await self.ws.recv()  # {"type":"hello-ok"}

        self.build_pipeline()

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

        await self.ws_loop()

    def build_pipeline(self):
        video_src = "autovideosrc" if self.use_camera else "videotestsrc is-live=true pattern=ball"
        audio_src = "autoaudiosrc" if self.use_mic else "audiotestsrc is-live=true"

        desc = f"""
            webrtcbin name=webrtc stun-server={self.stun} bundle-policy=max-bundle
            {video_src} !
              videoconvert ! queue ! vp8enc deadline=1 ! rtpvp8pay pt=96 ! 
              application/x-rtp,media=video,encoding-name=VP8,payload=96 ! webrtc.
            {audio_src} !
              audioconvert ! audioresample ! queue ! opusenc ! rtpopuspay pt=111 ! 
              application/x-rtp,media=audio,encoding-name=OPUS,payload=111 ! webrtc.
        """

        self.pipeline = Gst.parse_launch(desc)
        self.webrtc = self.pipeline.get_by_name("webrtc")

        # webrtcbin signals 
        self.webrtc.connect("on-negotiation-needed", self.on_negotiation_needed)
        self.webrtc.connect("on-ice-candidate", self.on_ice_candidate)
        self.webrtc.connect("pad-added", self.on_incoming_stream)
        self.webrtc.connect("on-data-channel", self.on_data_channel)

        self.pipeline.set_state(Gst.State.PLAYING)

    def on_bus_message(self, bus, msg):
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print("[GST][ERROR]", err, dbg, flush=True)
        elif t == Gst.MessageType.EOS:
            print("[GST] End-of-Stream", flush=True)
        elif t == Gst.MessageType.STATE_CHANGED:
            if msg.src == self.pipeline:
                old, new, pending = msg.parse_state_changed()
                print(f"[GST] Pipeline state: {old.value_nick} -> {new.value_nick}", flush=True)

    # ---------- webrtcbin callbacks ----------
    def on_negotiation_needed(self, webrtc):
        """
        W3C createOffer benzeri: offer oluştur, local description set et, karşı tarafa gönder.
        """
        print("[WEBRTC] on_negotiation_needed")
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, None, None)
        webrtc.emit("create-offer", None, promise)

    def on_offer_created(self, promise, _):
        reply = self._promise_reply(promise)
        offer = reply.get_value("offer")
        # local SDP'yi set et
        self.webrtc.emit("set-local-description", offer, None)
        sdp_text = offer.sdp.as_text()
        print("[WEBRTC] Sending SDP OFFER to", self.peer_id)
        # Signaling server üzerinden karşıya gönder (thread-safe)
        if hasattr(self, "loop"):
            self.loop.call_soon_threadsafe(asyncio.create_task, self._ws_send({
                "type":"sdp-offer",
                "to": self.peer_id,
                "sdp": sdp_text
            }))
        else:
            asyncio.create_task(self._ws_send({
                "type":"sdp-offer",
                "to": self.peer_id,
                "sdp": sdp_text
            }))

    def on_ice_candidate(self, webrtc, mlineindex, candidate):
        """
        Yeni ICE candidate oluştuğunda çağrılır. Karşı tarafa iletiriz.
        """
        msg = {
            "type":"ice",
            "to": self.peer_id,
            "sdpmlineindex": int(mlineindex),
            "candidate": candidate
        }
        if hasattr(self, "loop"):
            self.loop.call_soon_threadsafe(asyncio.create_task, self._ws_send(msg))
        else:
            asyncio.create_task(self._ws_send(msg))

    def on_incoming_stream(self, webrtc, pad):
        """
        Karşıdan stream geldiğinde (recv) yeni bir src pad açılır.
        Bunu uygun bir decode zincirine dinamik bağlarız.
        """
        if pad.get_direction() != Gst.PadDirection.SRC:
            return
        caps = pad.get_current_caps()
        s = caps.to_string() if caps else ""
        print("[WEBRTC] Incoming stream caps:", s)

        # Video mu audio mu ayırt edip decode et:
        if "video" in s:
            q = Gst.ElementFactory.make("queue")
            depay = Gst.ElementFactory.make("rtpvp8depay")
            dec = Gst.ElementFactory.make("vp8dec")
            conv = Gst.ElementFactory.make("videoconvert")
            sink = Gst.ElementFactory.make("autovideosink")
            for e in (q, depay, dec, conv, sink): self.pipeline.add(e)
            for e in (q, depay, dec, conv, sink): e.sync_state_with_parent()
            pad.link(q.get_static_pad("sink"))
            Gst.Element.link_many(q, depay, dec, conv, sink)

        elif "audio" in s:
            q = Gst.ElementFactory.make("queue")
            depay = Gst.ElementFactory.make("rtpopusdepay")
            dec = Gst.ElementFactory.make("opusdec")
            conv = Gst.ElementFactory.make("audioconvert")
            res = Gst.ElementFactory.make("audioresample")
            sink = Gst.ElementFactory.make("autoaudiosink")
            for e in (q, depay, dec, conv, res, sink): self.pipeline.add(e)
            for e in (q, depay, dec, conv, res, sink): e.sync_state_with_parent()
            pad.link(q.get_static_pad("sink"))
            Gst.Element.link_many(q, depay, dec, conv, res, sink)

    def on_data_channel(self, webrtc, channel):
        """
        Karşı taraf data channel açarsa buraya düşer.
        """
        print("[WEBRTC] DataChannel opened:", channel.props.label)
        channel.connect("on-message-string", self._on_dc_message)
        # ufak bir mesaj gönderelim
        channel.emit("send-string", "hello-from-"+self.self_id)

    def _on_dc_message(self, channel, msg):
        print("[DATA-CHANNEL]", msg)

    # ---------- SDP/ICE yardımcıları ----------
    def _promise_reply(self, promise):
        promise.wait()
        return promise.get_reply()

    def _set_remote_description(self, sdp_text, typ):
        ret, sdpmsg = Gst.SDPMessage.new()
        Gst.SDPMessage.parse_buffer(sdp_text.encode(), sdpmsg)
        sdp_type = Gst.WebRTCSDPType.ANSWER if typ == "answer" else Gst.WebRTCSDPType.OFFER
        desc = Gst.WebRTCSessionDescription.new(sdp_type, sdpmsg)
        self.webrtc.emit("set-remote-description", desc, None)

    def _add_ice(self, candidate, mline, mid=None):
        self.webrtc.emit("add-ice-candidate", int(mline), candidate)

    # ---------- WebSocket (signaling) ----------
    async def _ws_send(self, obj):
        await self.ws.send(json.dumps(obj))

    async def ws_loop(self):
        """
        Signaling server'dan gelen mesajları bekler ve uygular.
        """
        # Bu client A ise (ve peer B) — karşıdan offer gelirse “callee” olur,
        # biz offer ürettiysek “caller”ız; her iki akışı da destekliyoruz.
        async for raw in self.ws:
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "sdp-offer" and msg.get("from") == self.peer_id:
                # Karşı taraf bize offer gönderdi → set remote offer → create + send answer
                print("[SIG] Offer received from", self.peer_id)
                self._set_remote_description(msg["sdp"], "offer")
                # Answer üret
                promise = Gst.Promise.new_with_change_func(self._on_answer_created, None, None)
                self.webrtc.emit("create-answer", None, promise)

            elif t == "sdp-answer" and msg.get("from") == self.peer_id:
                print("[SIG] Answer received from", self.peer_id)
                self._set_remote_description(msg["sdp"], "answer")

            elif t == "ice" and msg.get("from") == self.peer_id:
                self._add_ice(msg["candidate"], msg["sdpmlineindex"])

            elif t == "error":
                print("[SIG][ERROR]", msg)

    def _on_answer_created(self, promise, _):
        reply = self._promise_reply(promise)
        answer = reply.get_value("answer")
        self.webrtc.emit("set-local-description", answer, None)
        sdp_text = answer.sdp.as_text()
        # Karşı tarafa gönder (thread-safe)
        if hasattr(self, "loop"):
            self.loop.call_soon_threadsafe(asyncio.create_task, self._ws_send({
                "type":"sdp-answer",
                "to": self.peer_id,
                "sdp": sdp_text
            }))
        else:
            asyncio.create_task(self._ws_send({
                "type":"sdp-answer",
                "to": self.peer_id,
                "sdp": sdp_text
            }))

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="ws://35.198.64.68:443", help="WS signaling URL")
    ap.add_argument("--id", required=True, help="this peer id")
    ap.add_argument("--peer", required=True, help="remote peer id")
    ap.add_argument("--no-camera", action="store_true", help="disable camera")
    ap.add_argument("--no-mic", action="store_true", help="disable mic")
    ap.add_argument("--stun", default="stun://stun.l.google.com:19302")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    client = P2PClient(ws_url=args.server, self_id=args.id, peer_id=args.peer,
                       use_camera=not args.no_camera, use_mic=not args.no_mic, 
                       stun=args.stun)
    asyncio.run(client.run())
