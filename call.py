from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from typing import Optional

app = FastAPI()
clients = {}

@app.get("/")
async def get(request: Request, call_id: Optional[str] = None):
    if call_id not in ["1", "2"]:
        return HTMLResponse("<h2>Invalid or missing call ID. Use ?call_id=1 or ?call_id=2</h2>")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Call - ID {call_id}</title>
    </head>
    <body>
        <h2>Call ID: {call_id}</h2>
        <video id="localVideo" autoplay muted playsinline style="width: 45%; border: 1px solid gray;"></video>
        <video id="remoteVideo" autoplay playsinline style="width: 45%; border: 1px solid gray;"></video>
        <br><br>
        <input type="text" id="messageInput" placeholder="Message..." />
        <button onclick="sendMessage()">Send</button>

        <script>
    const callId = "{{call_id}}";
    let ws;
    let reconnectAttempts = 0;
    const maxReconnectDelay = 30000;

    const localVideo = document.getElementById("localVideo");
    const remoteVideo = document.getElementById("remoteVideo");
    const peer = new RTCPeerConnection();

    function connectWebSocket() {
        ws = new WebSocket(`wss://${location.host}/call/ws/${callId}`);

        ws.onopen = () => {
            console.log("✅ WebSocket connected");
            reconnectAttempts = 0;
        };

        ws.onerror = (err) => {
            console.error("❌ WebSocket error:", err);
            ws.close();
        };

        ws.onclose = () => {
            console.warn("⚠️ WebSocket closed. Trying to reconnect...");
            reconnectWithBackoff();
        };

        ws.onmessage = async (event) => {
            const message = JSON.parse(event.data);

            if (message.type === "offer") {
                console.log("📩 Received offer");
                await peer.setRemoteDescription(new RTCSessionDescription(message.offer));
                const answer = await peer.createAnswer();
                await peer.setLocalDescription(answer);
                ws.send(JSON.stringify({ type: "answer", answer }));
            }

            if (message.type === "answer") {
                console.log("📩 Received answer");
                await peer.setRemoteDescription(new RTCSessionDescription(message.answer));
            }

            if (message.type === "ice") {
                try {
                    console.log("📩 Adding ICE candidate");
                    await peer.addIceCandidate(new RTCIceCandidate(message.candidate));
                } catch (e) {
                    console.error("❗ Error adding ICE candidate:", e);
                }
            }
        };
    }

    function reconnectWithBackoff() {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), maxReconnectDelay);
        console.log(`🔄 Reconnecting in ${delay / 1000}s...`);
        setTimeout(connectWebSocket, delay);
    }

    // Setup media
    navigator.mediaDevices.getUserMedia({ video: true, audio: true }).then(stream => {
        localVideo.srcObject = stream;
        stream.getTracks().forEach(track => peer.addTrack(track, stream));

        if (callId === "1") {
            peer.onnegotiationneeded = async () => {
                console.log("📞 Starting negotiation...");
                const offer = await peer.createOffer();
                await peer.setLocalDescription(offer);
                if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: "offer", offer }));
                }
            };
        }
    }).catch(err => {
        console.error("🚫 Could not get user media:", err);
    });

    peer.onicecandidate = (event) => {
        if (event.candidate && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ice", candidate: event.candidate }));
        }
    };

    peer.ontrack = (event) => {
        if (event.streams && event.streams[0]) {
            remoteVideo.srcObject = event.streams[0];
        }
    };

    function sendMessage() {
        const input = document.getElementById("messageInput");
        alert("Message: " + input.value);
        input.value = "";
    }

    // Start WebSocket connection
    connectWebSocket();
</script>

    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    clients[call_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            target_id = "2" if call_id == "1" else "1"
            if target_id in clients:
                await clients[target_id].send_text(data)
    except Exception:
        clients.pop(call_id, None)

