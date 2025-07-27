from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Optional
import json
import asyncio
import uvicorn

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
        <div id="status" class="status connecting">Initializing...</div>
        
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
            let maxReconnectAttempts = 5;
            let reconnectTimeout = null;
            
            const localVideo = document.getElementById("localVideo");
            const remoteVideo = document.getElementById("remoteVideo");
            const statusDiv = document.getElementById("status");
            const reconnectBtn = document.getElementById("reconnectBtn");

            // Enhanced ICE configuration for poor network
            const iceConfig = {{
                iceServers: [
                    {{ urls: "stun:stun.l.google.com:19302" }},
                    {{ urls: "stun:stun1.l.google.com:19302" }},
                    {{ urls: "stun:stun2.l.google.com:19302" }},
                    {{ urls: "stun:stun.services.mozilla.com" }}
                ],
                iceCandidatePoolSize: 10,
                iceTransportPolicy: 'all',
                bundlePolicy: 'balanced'
            }};

            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = `status ${{className}}`;
            }}

            function createWebSocket() {{
                return new Promise((resolve, reject) => {{
                    if (ws && ws.readyState === WebSocket.OPEN) {{
                        ws.close();
                    }}

                    // Use correct WebSocket URL for Render.com
                    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const wsUrl = `${{protocol}}//${{window.location.host}}/call/ws/${{callId}}`;
                    
                    console.log("Connecting to WebSocket:", wsUrl);
                    updateStatus("Connecting to server...", "connecting");
                    
                    try {{
                        ws = new WebSocket(wsUrl);
                    }} catch (error) {{
                        console.error("Failed to create WebSocket:", error);
                        updateStatus("Failed to connect", "disconnected");
                        reject(error);
                        return;
                    }}

                    ws.onopen = () => {{
                        console.log("WebSocket connected successfully");
                        updateStatus("Server connected", "connecting");
                        reconnectAttempts = 0;
                        resolve();
                    }};

                    ws.onmessage = handleWebSocketMessage;

                    ws.onclose = (event) => {{
                        console.log("WebSocket closed:", event.code, event.reason);
                        if (event.code !== 1000 && reconnectAttempts < maxReconnectAttempts) {{
                            updateStatus("Connection lost, reconnecting...", "reconnecting");
                            scheduleReconnect();
                        }} else if (reconnectAttempts >= maxReconnectAttempts) {{
                            updateStatus("Connection failed. Click Reconnect.", "disconnected");
                            reconnectBtn.style.display = "block";
                        }}
                    }};

                    ws.onerror = (error) => {{
                        console.error("WebSocket error:", error);
                        updateStatus("Connection error", "disconnected");
                        reject(error);
                    }};

                    // Timeout for connection
                    setTimeout(() => {{
                        if (ws.readyState !== WebSocket.OPEN) {{
                            ws.close();
                            reject(new Error("Connection timeout"));
                        }}
                    }}, 10000);
                }});
            }}

            async function handleWebSocketMessage(event) {{
                try {{
                    const message = JSON.parse(event.data);

                    if (message.type === "offer") {{
                        console.log("Received offer");
                        await peer.setRemoteDescription(new RTCSessionDescription(message.offer));
                        const answer = await peer.createAnswer();
                        await peer.setLocalDescription(answer);
                        if (ws.readyState === WebSocket.OPEN) {{
                            ws.send(JSON.stringify({{ type: "answer", answer: answer }}));
                        }}
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
            }}

            function createPeerConnection() {{
                if (peer) {{
                    peer.close();
                }}

                peer = new RTCPeerConnection(iceConfig);

                // Add local stream
                if (localStream) {{
                    localStream.getTracks().forEach(track => {{
                        peer.addTrack(track, localStream);
                    }});
                }}

                peer.ontrack = (event) => {{
                    console.log("Received remote track:", event.streams);
                    if (event.streams && event.streams[0]) {{
                        remoteVideo.srcObject = event.streams[0];
                        updateStatus("Call connected!", "connected");
                        reconnectBtn.style.display = "none";
                    }}
                }};

                peer.onicecandidate = (event) => {{
                    if (event.candidate && ws && ws.readyState === WebSocket.OPEN) {{
                        console.log("Sending ICE candidate");
                        ws.send(JSON.stringify({{ type: "ice", candidate: event.candidate }}));
                    }}
                }};

                peer.oniceconnectionstatechange = () => {{
                    console.log("ICE connection state:", peer.iceConnectionState);
                    
                    switch(peer.iceConnectionState) {{
                        case 'connected':
                        case 'completed':
                            updateStatus("Call connected!", "connected");
                            reconnectBtn.style.display = "none";
                            break;
                        case 'connecting':
                        case 'checking':
                            updateStatus("Connecting call...", "connecting");
                            break;
                        case 'disconnected':
                            updateStatus("Call disconnected", "reconnecting");
                            // Try ICE restart for poor network
                            setTimeout(() => {{
                                if (peer && peer.iceConnectionState === 'disconnected') {{
                                    console.log("Attempting ICE restart...");
                                    try {{
                                        peer.restartIce();
                                    }} catch (e) {{
                                        console.log("ICE restart failed:", e);
                                        scheduleReconnect();
                                    }}
                                }}
                            }}, 3000);
                            break;
                        case 'failed':
                            updateStatus("Call failed", "disconnected");
                            scheduleReconnect();
                            break;
                    }}
                }};

                // Setup negotiation for caller
                if (callId === "1") {{
                    peer.onnegotiationneeded = async () => {{
                        try {{
                            console.log("Starting negotiation...");
                            const offer = await peer.createOffer({{
                                offerToReceiveAudio: true,
                                offerToReceiveVideo: true
                            }});
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
                    updateStatus("Max attempts reached. Click Reconnect.", "disconnected");
                    reconnectBtn.style.display = "block";
                    return;
                }}

                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}

                reconnectAttempts++;
                const delay = Math.min(2000 * reconnectAttempts, 10000); // 2s, 4s, 6s... max 10s
                
                updateStatus(`Reconnecting in ${{Math.ceil(delay/1000)}}s... (${{reconnectAttempts}}/${{maxReconnectAttempts}})`, "reconnecting");
                
                reconnectTimeout = setTimeout(async () => {{
                    try {{
                        await initializeConnection();
                    }} catch (e) {{
                        console.error("Reconnection failed:", e);
                    }}
                }}, delay);
            }}

            async function initializeConnection() {{
                try {{
                    createPeerConnection();
                    await createWebSocket();
                }} catch (error) {{
                    console.error("Connection initialization failed:", error);
                    updateStatus("Failed to connect", "disconnected");
                }}
            }}

            async function reconnectCall() {{
                console.log("Manual reconnect triggered");
                reconnectAttempts = 0;
                reconnectBtn.style.display = "none";
                if (reconnectTimeout) {{
                    clearTimeout(reconnectTimeout);
                }}
                await initializeConnection();
            }}

            // Get user media and start connection
            async function initialize() {{
                try {{
                    updateStatus("Getting camera access...", "connecting");
                    
                    // Optimized media constraints for poor network
                    const constraints = {{
                        video: {{ 
                            width: {{ ideal: 320, max: 480 }}, 
                            height: {{ ideal: 240, max: 360 }},
                            frameRate: {{ ideal: 10, max: 15 }}
                        }}, 
                        audio: {{ 
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true,
                            sampleRate: 16000
                        }} 
                    }};

                    localStream = await navigator.mediaDevices.getUserMedia(constraints);
                    console.log("Got local media stream");
                    localVideo.srcObject = localStream;
                    
                    await initializeConnection();
                    
                }} catch (e) {{
                    console.error("Initialization error:", e);
                    updateStatus("Failed to access camera/microphone", "disconnected");
                }}
            }}

            // Network event listeners
            window.addEventListener('online', () => {{
                console.log("Network online");
                if (ws && ws.readyState !== WebSocket.OPEN) {{
                    reconnectCall();
                }}
            }});

            window.addEventListener('offline', () => {{
                console.log("Network offline");
                updateStatus("Network offline", "disconnected");
            }});

            async function sendMessage() {{
                const input = document.getElementById("messageInput");
                alert("Message: " + input.value);
                input.value = "";
            }}

            // Start the app
            initialize();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.websocket("/call/ws/{call_id}")
async def websocket_endpoint(websocket: WebSocket, call_id: str):
    await websocket.accept()
    clients[call_id] = websocket
    print(f"Client {call_id} connected via WebSocket")
    
    try:
        while True:
            data = await websocket.receive_text()
            target_id = "2" if call_id == "1" else "1"
            
            if target_id in clients:
                try:
                    await clients[target_id].send_text(data)
                    print(f"Message forwarded from {call_id} to {target_id}")
                except Exception as e:
                    print(f"Error forwarding to {target_id}: {e}")
                    clients.pop(target_id, None)
            else:
                print(f"Target client {target_id} not found")
                
    except WebSocketDisconnect:
        print(f"Client {call_id} disconnected")
    except Exception as e:
        print(f"WebSocket error for {call_id}: {e}")
    finally:
        clients.pop(call_id, None)
        print(f"Cleaned up client {call_id}")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "active_clients": len(clients)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
