from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Optional
import json
import asyncio

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
        <style>
            .status {{
                padding: 8px;
                margin: 8px 0;
                border-radius: 4px;
                font-size: 14px;
            }}
            .connected {{ background-color: #d4edda; color: #155724; }}
            .connecting {{ background-color: #fff3cd; color: #856404; }}
            .disconnected {{ background-color: #f8d7da; color: #721c24; }}
            .reconnecting {{ background-color: #cce7ff; color: #004085; }}
        </style>
    </head>
    <body>
        <h2>Call ID: {call_id}</h2>
        <div id="status" class="status connecting">Connecting...</div>
        
        <video id="localVideo" autoplay muted playsinline style="width: 45%; border: 1px solid gray;"></video>
        <video id="remoteVideo" autoplay playsinline style="width: 45%; border: 1px solid gray;"></video>
        <br><br>
        <button id="reconnectBtn" onclick="reconnectCall()" style="display: none; background: #007bff; color: white; padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;">Reconnect</button>
        <br><br>
        <input type="text" id="messageInput" placeholder="Message..." />
        <button onclick="sendMessage()">Send</button>

        <script>
            const callId = "{call_id}";
            let ws = null;
            let peer = null;
            let localStream = null;
            let reconnectAttempts = 0;
            let maxReconnectAttempts = 10;
            let reconnectTimeout = null;
            let isManualDisconnect = false;
            
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const statusDiv = document.getElementById("status");
            const reconnectBtn = document.getElementById("reconnectBtn");

            // ICE configuration with multiple STUN servers for better connectivity
            const iceConfig = {{
                iceServers: [
                    {{ urls: "stun:stun.l.google.com:19302" }},
                    {{ urls: "stun:stun1.l.google.com:19302" }},
                    {{ urls: "stun:stun2.l.google.com:19302" }},
                    {{ urls: "stun:stun.services.mozilla.com" }},
                    {{ urls: "stun:stun.stunprotocol.org" }}
                ],
                iceCandidatePoolSize: 10
            }};

            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = `status ${{className}}`;
            }}

            function createWebSocket() {{
                if (ws) {{
                    ws.close();
                }}

                // Use wss for HTTPS, ws for HTTP
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${{protocol}}//${{window.location.host}}/ws/${{callId}}`;
                
                console.log("Connecting to:", wsUrl);
                ws = new WebSocket(wsUrl);

                ws.onopen = () => {{
                    console.log("WebSocket connected");
                    updateStatus("WebSocket connected", "connecting");
                    reconnectAttempts = 0; // Reset on successful connection
                }};

                ws.onmessage = async (event) => {{
                    try {{
                        const message = JSON.parse(event.data);

                        // Handle keep-alive ping
                        if (message.type === "ping") {{
                            ws.send(JSON.stringify({{ type: "pong" }}));
                            return;
                        }}

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

                ws.onclose = (event) => {{
                    console.log("WebSocket closed:", event.code, event.reason);
                    if (!isManualDisconnect && event.code !== 1000) {{
                        updateStatus("Connection lost", "disconnected");
                        scheduleReconnect();
                    }}
                }};

                ws.onerror = (error) => {{
                    console.error("WebSocket error:", error);
                    updateStatus("Connection error", "disconnected");
                }};
            }}

            function createPeerConnection() {{
                if (peer) {{
                    peer.close();
                }}

                peer = new RTCPeerConnection(iceConfig);

                // Add local stream if available
                if (localStream) {{
                    localStream.getTracks().forEach(track => {{
                        peer.addTrack(track, localStream);
                    }});
                }}

                peer.ontrack = (event) => {{
                    console.log("Received remote track:", event.streams);
                    if (event.streams && event.streams[0]) {{
                        remoteVideo.srcObject = event.streams[0];
                        updateStatus("Call connected", "connected");
                    }} else {{
                        console.warn("No streams available in ontrack event");
                    }}
                }};

                peer.onicecandidate = (event) => {{
                    if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {{
                        console.log("Sending ICE candidate:", event.candidate);
                        ws.send(JSON.stringify({{ type: "ice", candidate: event.candidate }}));
                    }}
                }};

                peer.oniceconnectionstatechange = () => {{
                    console.log("ICE connection state changed:", peer.iceConnectionState);
                    
                    switch(peer.iceConnectionState) {{
                        case 'connected':
                        case 'completed':
                            updateStatus("Call connected", "connected");
                            reconnectBtn.style.display = "none";
                            break;
                        case 'connecting':
                        case 'checking':
                            updateStatus("Connecting call...", "connecting");
                            break;
                        case 'disconnected':
                            updateStatus("Call disconnected, reconnecting...", "reconnecting");
                            // Try to reconnect after a short delay
                            setTimeout(() => {{
                                if (peer && peer.iceConnectionState === 'disconnected') {{
                                    restartIce();
                                }}
                            }}, 2000);
                            break;
                        case 'failed':
                            updateStatus("Call failed", "disconnected");
                            reconnectBtn.style.display = "block";
                            scheduleReconnect();
                            break;
                        case 'closed':
                            updateStatus("Call ended", "disconnected");
                            break;
                    }}
                }};

                peer.onconnectionstatechange = () => {{
                    console.log("Connection state changed:", peer.connectionState);
                    if (peer.connectionState === 'failed') {{
                        scheduleReconnect();
                    }}
                }};

                // Setup negotiation for caller
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
                    updateStatus("Connection failed. Click Reconnect to try again.", "disconnected");
                    reconnectBtn.style.display = "block";
                    return;
                }}

                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}

                reconnectAttempts++;
                const delay = Math.min(1000 + (reconnectAttempts * 1000), 5000); // 1s, 2s, 3s... max 5s
                
                updateStatus(`Reconnecting in ${{Math.ceil(delay/1000)}}s... (${{reconnectAttempts}}/${{maxReconnectAttempts}})`, "reconnecting");
                
                reconnectTimeout = setTimeout(() => {{
                    initializeConnection();
                }}, delay);
            }}

            function restartIce() {{
                if (peer && peer.iceConnectionState === 'disconnected') {{
                    console.log("Attempting ICE restart...");
                    peer.restartIce();
                }}
            }}

            function reconnectCall() {{
                console.log("Manual reconnect triggered");
                reconnectAttempts = 0;
                reconnectBtn.style.display = "none";
                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}
                initializeConnection();
            }}

            function initializeConnection() {{
                createPeerConnection();
                createWebSocket();
            }}

            // Initialize media and connection
            async function initialize() {{
                try {{
                    updateStatus("Getting camera and microphone...", "connecting");
                    
                    // Optimized constraints for poor network
                    const constraints = {{
                        video: {{ 
                            width: {{ ideal: 480, max: 640 }}, 
                            height: {{ ideal: 360, max: 480 }},
                            frameRate: {{ ideal: 15, max: 20 }}
                        }}, 
                        audio: {{ 
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }} 
                    }};

                    localStream = await navigator.mediaDevices.getUserMedia(constraints);
                    console.log("Got local media stream");
                    localVideo.srcObject = localStream;
                    
                    updateStatus("Connecting...", "connecting");
                    initializeConnection();
                    
                }} catch (e) {{
                    console.error("Error getting user media:", e);
                    updateStatus("Camera/microphone access denied", "disconnected");
                }}
            }}

            // Handle network status changes
            window.addEventListener('online', () => {{
                console.log("Network back online");
                if (reconnectAttempts > 0 || (peer && peer.iceConnectionState !== 'connected')) {{
                    reconnectCall();
                }}
            }});

            window.addEventListener('offline', () => {{
                console.log("Network offline");
                updateStatus("Network offline", "disconnected");
            }});

            // Handle page visibility changes
            document.addEventListener('visibilitychange', () => {{
                if (document.visibilityState === 'visible') {{
                    // Check connection when page becomes visible
                    if (peer && (peer.iceConnectionState === 'disconnected' || peer.iceConnectionState === 'failed')) {{
                        scheduleReconnect();
                    }}
                }}
            }});

            async function sendMessage() {{
                const input = document.getElementById("messageInput");
                alert("Message: " + input.value);
                input.value = "";
            }}

            // Start the application
            initialize();

            // Cleanup on page unload
            window.addEventListener('beforeunload', () => {{
                isManualDisconnect = true;
                if (ws) ws.close();
                if (peer) peer.close();
            }});
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    clients[call_id] = websocket
    print(f"Client {call_id} connected")
    
    try:
        while True:
            # Wait for message with timeout for keep-alive
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                
                # Handle ping-pong for keep-alive
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                        continue
                except json.JSONDecodeError:
                    pass
                
                # Forward message to the other client
                target_id = "2" if call_id == "1" else "1"
                if target_id in clients:
                    try:
                        await clients[target_id].send_text(data)
                        print(f"Forwarded message from {call_id} to {target_id}")
                    except Exception as e:
                        print(f"Error sending to {target_id}: {e}")
                        clients.pop(target_id, None)
                        
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except:
                    break
                    
    except WebSocketDisconnect:
        print(f"Client {call_id} disconnected")
    except Exception as e:
        print(f"Error with client {call_id}: {e}")
    finally:
        clients.pop(call_id, None)
        print(f"Cleaned up client {call_id}")

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "active_clients": len(clients)}
