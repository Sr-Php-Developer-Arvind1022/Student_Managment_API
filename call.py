from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Optional
import json
import asyncio
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
clients = {}

# Add CORS middleware if needed
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get(request: Request, call_id: Optional[str] = None):
    if call_id not in ["1", "2"]:
        return HTMLResponse("<h2>Invalid or missing call ID. Use ?call_id=1 or ?call_id=2</h2>")

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Call - ID {call_id}</title>
        <style>
            .status {{
                padding: 10px;
                margin: 10px 0;
                border-radius: 5px;
                font-weight: bold;
            }}
            .connected {{ background-color: #d4edda; color: #155724; }}
            .connecting {{ background-color: #fff3cd; color: #856404; }}
            .disconnected {{ background-color: #f8d7da; color: #721c24; }}
            .reconnecting {{ background-color: #cce7ff; color: #004085; }}
        </style>
    </head>
    <body>
        <h2>Call ID: {call_id}</h2>
        <div id="status" class="status disconnected">Initializing...</div>
        
        <video id="localVideo" autoplay muted playsinline style="width: 45%; border: 1px solid gray;"></video>
        <video id="remoteVideo" autoplay playsinline style="width: 45%; border: 1px solid gray;"></video>
        <br><br>
        <button id="reconnectBtn" onclick="reconnectCall()" style="display: none;">Reconnect Call</button>
        <br><br>
        <input type="text" id="messageInput" placeholder="Message..." />
        <button onclick="sendMessage()">Send</button>

        <script>
            const callId = "{call_id}";
            let ws = null;
            let peer = null;
            let localStream = null;
            let reconnectAttempts = 0;
            let maxReconnectAttempts = 5;
            let reconnectTimeout = null;
            
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const statusDiv = document.getElementById("status");
            const reconnectBtn = document.getElementById("reconnectBtn");

            // ICE servers with STUN servers for better connectivity
            const iceServers = {{
                iceServers: [
                    {{ urls: "stun:stun.l.google.com:19302" }},
                    {{ urls: "stun:stun1.l.google.com:19302" }},
                    {{ urls: "stun:stun2.l.google.com:19302" }},
                    {{ urls: "stun:stun3.l.google.com:19302" }},
                    {{ urls: "stun:stun4.l.google.com:19302" }}
                ],
                iceCandidatePoolSize: 10
            }};

            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = `status ${{className}}`;
            }}

            function createPeerConnection() {{
                if (peer) {{
                    peer.close();
                }}

                peer = new RTCPeerConnection(iceServers);

                // Add local stream to peer connection
                if (localStream) {{
                    localStream.getTracks().forEach(track => {{
                        peer.addTrack(track, localStream);
                    }});
                }}

                peer.ontrack = (event) => {{
                    console.log("Received remote track:", event.streams);
                    if (event.streams && event.streams[0]) {{
                        remoteVideo.srcObject = event.streams[0];
                        updateStatus("Connected", "connected");
                    }}
                }};

                peer.onicecandidate = (event) => {{
                    if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {{
                        console.log("Sending ICE candidate");
                        ws.send(JSON.stringify({{ type: "ice", candidate: event.candidate }}));
                    }}
                }};

                peer.oniceconnectionstatechange = () => {{
                    console.log("ICE connection state changed:", peer.iceConnectionState);
                    
                    switch(peer.iceConnectionState) {{
                        case 'connected':
                        case 'completed':
                            updateStatus("Connected", "connected");
                            reconnectBtn.style.display = "none";
                            reconnectAttempts = 0;
                            break;
                        case 'connecting':
                            updateStatus("Connecting...", "connecting");
                            break;
                        case 'disconnected':
                            updateStatus("Connection lost, trying to reconnect...", "reconnecting");
                            scheduleReconnect();
                            break;
                        case 'failed':
                            updateStatus("Connection failed", "disconnected");
                            reconnectBtn.style.display = "block";
                            break;
                        case 'closed':
                            updateStatus("Connection closed", "disconnected");
                            break;
                    }}
                }};

                peer.onconnectionstatechange = () => {{
                    console.log("Connection state changed:", peer.connectionState);
                    if (peer.connectionState === 'failed') {{
                        scheduleReconnect();
                    }}
                }};

                if (callId === "1") {{
                    peer.onnegotiationneeded = async () => {{
                        try {{
                            console.log("Starting negotiation...");
                            const offer = await peer.createOffer();
                            await peer.setLocalDescription(offer);
                            if (ws && ws.readyState === WebSocket.OPEN) {{
                                ws.send(JSON.stringify({{ type: "offer", offer: offer }}));
                            }}
                        }} catch (e) {{
                            console.error("Error during negotiation:", e);
                        }}
                    }};
                }}
            }}

            function scheduleReconnect() {{
                if (reconnectAttempts >= maxReconnectAttempts) {{
                    updateStatus("Max reconnection attempts reached", "disconnected");
                    reconnectBtn.style.display = "block";
                    return;
                }}

                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}

                reconnectAttempts++;
                const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 10000); // Exponential backoff
                
                updateStatus(`Reconnecting in ${{Math.ceil(delay/1000)}} seconds... (attempt ${{reconnectAttempts}}/${{maxReconnectAttempts}})`, "reconnecting");
                
                reconnectTimeout = setTimeout(() => {{
                    reconnectCall();
                }}, delay);
            }}

            function connectWebSocket() {{
                if (ws) {{
                    ws.close();
                }}

                ws = new WebSocket(`ws://${{location.host}}/ws/${{callId}}`);

                ws.onopen = () => {{
                    console.log("WebSocket connected");
                    updateStatus("WebSocket connected", "connecting");
                }};

                ws.onmessage = async (event) => {{
                    try {{
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
                    }} catch (e) {{
                        console.error("Error processing message:", e);
                    }}
                }};

                ws.onclose = () => {{
                    console.log("WebSocket disconnected");
                    updateStatus("WebSocket disconnected", "disconnected");
                    scheduleReconnect();
                }};

                ws.onerror = (error) => {{
                    console.error("WebSocket error:", error);
                    updateStatus("WebSocket error", "disconnected");
                }};
            }}

            async function initializeCall() {{
                try {{
                    updateStatus("Getting camera and microphone...", "connecting");
                    
                    localStream = await navigator.mediaDevices.getUserMedia({{ 
                        video: {{ 
                            width: {{ ideal: 640 }}, 
                            height: {{ ideal: 480 }} 
                        }}, 
                        audio: {{ 
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }} 
                    }});
                    
                    console.log("Got local media stream");
                    localVideo.srcObject = localStream;
                    
                    createPeerConnection();
                    connectWebSocket();
                    
                }} catch (e) {{
                    console.error("Error getting user media:", e);
                    updateStatus("Error accessing camera/microphone", "disconnected");
                }}
            }}

            function reconnectCall() {{
                console.log("Manual reconnect triggered");
                reconnectAttempts = 0;
                reconnectBtn.style.display = "none";
                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}
                createPeerConnection();
                connectWebSocket();
            }}

            // Handle page visibility changes (when user switches tabs/apps)
            document.addEventListener("visibilitychange", () => {{
                if (document.visibilityState === 'visible') {{
                    // Page became visible again, check connection
                    if (peer && peer.iceConnectionState === 'disconnected') {{
                        scheduleReconnect();
                    }}
                }}
            }});

            // Handle network status changes
            window.addEventListener('online', () => {{
                console.log("Network came back online");
                if (peer && peer.iceConnectionState !== 'connected') {{
                    scheduleReconnect();
                }}
            }});

            window.addEventListener('offline', () => {{
                console.log("Network went offline");
                updateStatus("Network offline", "disconnected");
            }});

            async function sendMessage() {{
                const input = document.getElementById("messageInput");
                alert("Message: " + input.value);
                input.value = "";
            }}

            // Initialize the call when page loads
            initializeCall();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    clients[call_id] = websocket
    logger.info(f"Client {call_id} connected")
    
    try:
        while True:
            # Add timeout for receiving messages
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                logger.info(f"Received data from {call_id}: {data[:100]}...")
                
                # Handle ping messages
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                        continue
                except json.JSONDecodeError:
                    pass
                
                target_id = "2" if call_id == "1" else "1"
                
                if target_id in clients:
                    try:
                        await clients[target_id].send_text(data)
                        logger.info(f"Forwarded message from {call_id} to {target_id}")
                    except Exception as e:
                        logger.error(f"Error sending to target {target_id}: {e}")
                        # Remove disconnected client
                        clients.pop(target_id, None)
                else:
                    logger.warning(f"Target client {target_id} not found")
                        
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                    logger.debug(f"Sent ping to {call_id}")
                except:
                    logger.error(f"Failed to send ping to {call_id}")
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"Client {call_id} disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error for {call_id}: {e}")
    finally:
        clients.pop(call_id, None)
        logger.info(f"Cleaned up client {call_id}")
