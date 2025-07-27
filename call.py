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
            let ws;
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const peer = new RTCPeerConnection({{
                iceServers: [
                    {{ urls: "stun:stun.l.google.com:19302" }},
                    {{
                        urls: "turn:relay1.expressturn.com:3478",
                        username: "efwefwe",
                        credential: "wefwefwe"
                    }}
                ]
            }});

            // ICE throttling
            let iceQueue = [];
            let iceSending = false;

            function sendICEQueue() {{
                if (iceSending || iceQueue.length === 0 || ws.readyState !== WebSocket.OPEN) return;
                iceSending = true;
                const candidate = iceQueue.shift();
                ws.send(JSON.stringify({{ type: "ice", candidate }}));
                setTimeout(() => {{
                    iceSending = false;
                    sendICEQueue();
                }}, 300); // delay sending ICE
            }}

            peer.onicecandidate = (event) => {{
                if (event.candidate) {{
                    iceQueue.push(event.candidate);
                    sendICEQueue();
                }}
            }};

            peer.oniceconnectionstatechange = () => {{
                console.log("ICE connection state:", peer.iceConnectionState);
            }};

            peer.ontrack = (event) => {{
                if (event.streams && event.streams[0]) {{
                    remoteVideo.srcObject = event.streams[0];
                }}
            }};

            async function getMediaStreamWithTimeout(timeout = 10000) {{
                return Promise.race([
                    navigator.mediaDevices.getUserMedia({{ video: true, audio: true }}),
                    new Promise((_, reject) =>
                        setTimeout(() => reject(new Error("Media access timeout")), timeout)
                    )
                ]);
            }}

            async function start() {{
                try {{
                    const stream = await getMediaStreamWithTimeout();
                    localVideo.srcObject = stream;
                    stream.getTracks().forEach(track => peer.addTrack(track, stream));

                    if (callId === "1") {{
                        peer.onnegotiationneeded = async () => {{
                            const offer = await peer.createOffer();
                            await retryOffer(offer);
                        }};
                    }}
                }} catch (e) {{
                    alert("Media access failed: " + e.message);
                }}
            }}

            async function retryOffer(offer, attempt = 1) {{
                try {{
                    await peer.setLocalDescription(offer);
                    ws.send(JSON.stringify({{ type: "offer", offer }}));
                }} catch (e) {{
                    if (attempt < 3) {{
                        console.warn("Retrying offer:", attempt);
                        setTimeout(() => retryOffer(offer, attempt + 1), 1000);
                    }} else {{
                        console.error("Offer failed after retries");
                    }}
                }}
            }}

            function connectWebSocket() {{
                ws = new WebSocket(`wss://${{location.host}}/ws/${{callId}}`);

                ws.onopen = () => {{
                    console.log("WebSocket connected");
                }};

                ws.onclose = () => {{
                    console.warn("WebSocket closed. Reconnecting in 2s...");
                    setTimeout(connectWebSocket, 2000);
                }};

                ws.onerror = (e) => {{
                    console.error("WebSocket error:", e);
                    ws.close();
                }};

                ws.onmessage = async (event) => {{
                    const message = JSON.parse(event.data);
                    try {{
                        if (message.type === "offer") {{
                            await peer.setRemoteDescription(new RTCSessionDescription(message.offer));
                            const answer = await peer.createAnswer();
                            await peer.setLocalDescription(answer);
                            ws.send(JSON.stringify({{ type: "answer", answer }}));
                        }}
                        if (message.type === "answer") {{
                            await peer.setRemoteDescription(new RTCSessionDescription(message.answer));
                        }}
                        if (message.type === "ice") {{
                            try {{
                                await peer.addIceCandidate(new RTCIceCandidate(message.candidate));
                            }} catch (e) {{
                                console.warn("ICE candidate failed, retrying:", e);
                                setTimeout(async () => {{
                                    try {{
                                        await peer.addIceCandidate(new RTCIceCandidate(message.candidate));
                                    }} catch (e2) {{
                                        console.error("ICE candidate retry failed:", e2);
                                    }}
                                }}, 1000);
                            }}
                        }}
                    }} catch (e) {{
                        console.error("Message handling error:", e);
                    }}
                }};
            }}

            connectWebSocket();
            start();

            function sendMessage() {{
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
