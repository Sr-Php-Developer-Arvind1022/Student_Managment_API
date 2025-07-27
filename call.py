from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from typing import Optional
import asyncio

app = FastAPI()
clients = {}

@app.get("/call/")
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
        <p id="status">Connecting...</p>

        <script>
            const callId = "{call_id}";
            let ws;
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const statusDisplay = document.getElementById("status");
            const peer = new RTCPeerConnection(); // No iceServers to avoid external URLs

            let localStream;
            let reconnectAttempts = 0;
            const maxReconnectAttempts = 5;

            // WebSocket reconnection logic
            function connectWebSocket() {{
                ws = new WebSocket(`wss://${{location.host}}/call/ws/${{callId}}`);
                ws.onopen = () => {{
                    console.log("WebSocket connected");
                    statusDisplay.textContent = "WebSocket connected";
                    reconnectAttempts = 0;
                }};
                ws.onclose = () => {{
                    statusDisplay.textContent = "WebSocket disconnected. Reconnecting...";
                    if (reconnectAttempts < maxReconnectAttempts) {{
                        setTimeout(connectWebSocket, 2000 * (reconnectAttempts + 1));
                        reconnectAttempts++;
                    }} else {{
                        statusDisplay.textContent = "Failed to reconnect WebSocket.";
                    }}
                }};
                ws.onerror = (error) => {{
                    console.error("WebSocket error:", error);
                }};
                ws.onmessage = handleWebSocketMessage;
            }}

            // Get user media with low-bandwidth settings
            async function getMedia() {{
                try {{
                    localStream = await navigator.mediaDevices.getUserMedia({{
                        video: {{ width: {{ ideal: 320 }}, height: {{ ideal: 240 }}, frameRate: {{ ideal: 15 }} }},
                        audio: {{ echoCancellation: true, noiseSuppression: true }}
                    }});
                    console.log("Got local media stream");
                    localVideo.srcObject = localStream;
                    localStream.getTracks().forEach(track => peer.addTrack(track, localStream));

                    // Set preferred codec to H.264 for better compatibility
                    const codecs = RTCRtpSender.getCapabilities('video').codecs;
                    const h264Codec = codecs.find(codec => codec.mimeType === "video/H264");
                    if (h264Codec) {{
                        peer.getTransceivers().forEach(transceiver => {{
                            if (transceiver.sender.track.kind === "video") {{
                                transceiver.setCodecPreferences([h264Codec]);
                            }}
                        }});
                    }}
                }} catch (e) {{
                    console.error("Error getting user media:", e);
                    statusDisplay.textContent = "Error accessing camera/mic. Falling back to audio-only.";
                    // Fallback to audio-only
                    localStream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                    localVideo.srcObject = localStream;
                    localStream.getTracks().forEach(track => peer.addTrack(track, localStream));
                }}
            }}

            // Handle WebSocket messages
            async function handleWebSocketMessage(event) {{
                const message = JSON.parse(event.data);
                if (message.type === "offer") {{
                    console.log("Received offer");
                    try {{
                        await peer.setRemoteDescription(new RTCSessionDescription(message.offer));
                        const answer = await peer.createAnswer();
                        await peer.setLocalDescription(answer);
                        ws.send(JSON.stringify({{ type: "answer", answer: answer }}));
                    }} catch (e) {{
                        console.error("Error handling offer:", e);
                    }}
                }}
                if (message.type === "answer") {{
                    console.log("Received answer");
                    try {{
                        await peer.setRemoteDescription(new RTCSessionDescription(message.answer));
                    }} catch (e) {{
                        console.error("Error handling answer:", e);
                    }}
                }}
                if (message.type === "ice") {{
                    try {{
                        console.log("Adding ICE candidate");
                        await peer.addIceCandidate(new RTCIceCandidate(message.candidate));
                    }} catch (e) {{
                        console.error("Error adding ICE candidate:", e);
                    }}
                }}
            }}

            // WebRTC event handlers
            peer.onnegotiationneeded = async () => {{
                if (callId === "1") {{
                    console.log("Starting negotiation...");
                    try {{
                        const offer = await peer.createOffer();
                        await peer.setLocalDescription(offer);
                        ws.send(JSON.stringify({{ type: "offer", offer: offer }}));
                    }} catch (e) {{
                        console.error("Error during negotiation:", e);
                    }}
                }}
            }};

            peer.ontrack = (event) => {{
                console.log("Received remote track:", event.streams);
                if (event.streams && event.streams[0]) {{
                    remoteVideo.srcObject = event.streams[0];
                    statusDisplay.textContent = "Connected to remote peer";
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
                console.log("ICE connection state:", peer.iceConnectionState);
                statusDisplay.textContent = "ICE state: " + peer.iceConnectionState;
                if (peer.iceConnectionState === "disconnected" || peer.iceConnectionState === "failed") {{
                    if (reconnectAttempts < maxReconnectAttempts) {{
                        console.log("Attempting ICE restart...");
                        peer.restartIce();
                        reconnectAttempts++;
                    }} else {{
                        statusDisplay.textContent = "Connection failed. Please refresh.";
                    }}
                }}
            }};

            // Send message function
            async function sendMessage() {{
                const input = document.getElementById("messageInput");
                alert("Message: " + input.value);
                input.value = "";
            }}

            // Initialize
            connectWebSocket();
            getMedia();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/call/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    clients[call_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            target_id = "2" if call_id == "1" else "1"
            if target_id in clients:
                await clients[target_id].send_text(data)
    except Exception as e:
        print(f"WebSocket error for call_id {call_id}: {e}")
        clients.pop(call_id, None)
