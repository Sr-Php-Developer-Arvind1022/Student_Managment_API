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
            const callId = "{call_id}";
            const ws = new WebSocket(`wss://${{location.host}}/call/ws/${{callId}}`);
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const peer = new RTCPeerConnection();

            // Both caller and receiver get user media
            navigator.mediaDevices.getUserMedia({{ video: true, audio: true }}).then(stream => {{
                console.log("Got local media stream");
                localVideo.srcObject = stream;
                stream.getTracks().forEach(track => peer.addTrack(track, stream));

                if (callId === "1") {{
                    peer.onnegotiationneeded = async () => {{
                        console.log("Starting negotiation...");
                        const offer = await peer.createOffer();
                        await peer.setLocalDescription(offer);
                        ws.send(JSON.stringify({{ type: "offer", offer: offer }}));
                    }};
                }}
            }}).catch(e => {{
                console.error("Error getting user media:", e);
            }});

            peer.ontrack = (event) => {{
                console.log("Received remote track:", event.streams);
                if (event.streams && event.streams[0]) {{
                    remoteVideo.srcObject = event.streams[0];
                }} else {{
                    console.warn("No streams available in ontrack event");
                }}
            }};

            peer.onicecandidate = (event) => {{
                if (event.candidate) {{
                    console.log("Sending ICE candidate:", event.candidate);
                    ws.send(JSON.stringify({{ type: "ice", candidate: event.candidate }}));
                }}
            }};

            peer.oniceconnectionstatechange = () => {{
                console.log("ICE connection state changed:", peer.iceConnectionState);
            }};

            ws.onmessage = async (event) => {{
                const message = JSON.parse(event.data);

                if (message.type === "offer") {{
                    console.log("Received offer");
                    await peer.setRemoteDescription(new RTCSessionDescription(message.offer));
                    const answer = await peer.createAnswer();
                    await peer.setLocalDescription(answer);
                    ws.send(JSON.stringify({{ type: "answer", answer: answer }}));
                }}

                if (message.type === "answer") {{
                    console.log("Received answer");
                    await peer.setRemoteDescription(new RTCSessionDescription(message.answer));
                }}

                if (message.type === "ice") {{
                    try {{
                        console.log("Adding ICE candidate");
                        await peer.addIceCandidate(new RTCIceCandidate(message.candidate));
                    }} catch (e) {{
                        console.error("Error adding ICE candidate:", e);
                    }}
                }}
            }};

            async function sendMessage() {{
                const input = document.getElementById("messageInput");
                alert("Message: " + input.value);
                input.value = "";
            }}
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

