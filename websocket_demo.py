from fastapi import FastAPI, WebSocket, APIRouter, Body, Query
from fastapi.responses import HTMLResponse
from db import get_db

app = FastAPI()
router = APIRouter()

# In-memory mapping for user_id to websocket connections
user_connections = {}

@app.get("/", response_class=HTMLResponse)
def ws_demo_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket Demo</title>
        <style>
            #log { max-height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 5px; }
        </style>
    </head>
    <body>
        <h2>WebSocket Demo Page</h2>
        <input id="sender" type="text" placeholder="Sender ID..." />
        <input id="receiver" type="text" placeholder="Receiver ID..." />
        <input id="msg" type="text" placeholder="Type a message..." oninput="notifyTyping()" />
        <button onclick="sendMsg()">Send</button>
        <div id="log"></div>
        <script>
            var ws;
            var typingTimeout;
            var lastSender = "";
            function connectWS() {
                var sender = document.getElementById("sender").value;
                // Only reconnect if sender changed or ws is not open
                if (ws && ws.readyState === 1 && lastSender === sender) return;
                if (ws) ws.close();
                ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + window.location.pathname + "ws/chat/" + sender);
                lastSender = sender;
                ws.onopen = function() {
                    document.getElementById("log").innerHTML += "<div>WebSocket connected</div>";
                    tryAutoLoadHistory();
                };
                ws.onmessage = function(event) {
                    var data = event.data;
                    try {
                        var obj = JSON.parse(data);
                        if(obj.typing && obj.sender_id) {
                            document.getElementById("log").innerHTML += "<div><i>" + obj.sender_id + " is typing...</i></div>";
                        } else if(obj.msg && obj.sender_id) {
                            var sender = document.getElementById("sender").value;
                            var label = (obj.sender_id === sender) ? "You" : obj.sender_id;
                            document.getElementById("log").innerHTML += "<div><b>" + label + ":</b> " + obj.msg + "</div>";
                        } else if(obj.history) {
                            // Show chat history
                            document.getElementById("log").innerHTML = "";
                            obj.history.forEach(function(m) {
                                var label = (m.sender_id === document.getElementById("sender").value) ? "You" : m.sender_id;
                                document.getElementById("log").innerHTML += "<div><b>" + label + ":</b> " + m.msg + "</div>";
                            });
                        }
                    } catch {
                        document.getElementById("log").innerHTML += "<div>Received: " + data + "</div>";
                    }
                };
                ws.onclose = function() {
                    document.getElementById("log").innerHTML += "<div>WebSocket closed</div>";
                };
            }
            function sendMsg() {
                var sender = document.getElementById("sender").value;
                var receiver = document.getElementById("receiver").value;
                var msg = document.getElementById("msg").value;
                if (!ws || ws.readyState !== 1) {
                    connectWS();
                    setTimeout(function() { sendMsg(); }, 300);
                    return;
                }
                var payload = JSON.stringify({sender_id: sender, receiver_id: receiver, msg: msg, typing: false});
                ws.send(payload);
                document.getElementById("msg").value = "";
            }
            function notifyTyping() {
                clearTimeout(typingTimeout);
                typingTimeout = setTimeout(function() {
                    var sender = document.getElementById("sender").value;
                    var receiver = document.getElementById("receiver").value;
                    if (!ws || ws.readyState !== 1 || !sender || !receiver) return;
                    var payload = JSON.stringify({sender_id: sender, receiver_id: receiver, typing: true});
                    ws.send(payload);
                }, 100);
            }
            function loadHistory() {
                var sender = document.getElementById("sender").value;
                var receiver = document.getElementById("receiver").value;
                if (!sender || !receiver) return;
                fetch(window.location.pathname + "chat-history?sender_id=" + encodeURIComponent(sender) + "&receiver_id=" + encodeURIComponent(receiver))
                    .then(res => res.json())
                    .then(obj => {
                        if(obj.status && obj.history) {
                            document.getElementById("log").innerHTML = "";
                            obj.history.forEach(function(m) {
                                var label = (m.sender_id === sender) ? "You" : m.sender_id;
                                document.getElementById("log").innerHTML += "<div><b>" + label + ":</b> " + m.msg + "</div>";
                            });
                        }
                    });
            }
            // Load history automatically when both sender and receiver are filled
            function tryAutoLoadHistory() {
                var sender = document.getElementById("sender").value;
                var receiver = document.getElementById("receiver").value;
                if (sender && receiver) {
                    loadHistory();
                }
            }
            document.getElementById("sender").addEventListener("change", function() {
                connectWS();
                tryAutoLoadHistory();
            });
            document.getElementById("receiver").addEventListener("change", tryAutoLoadHistory);
            // Initial connect and history load
            connectWS();
            tryAutoLoadHistory();
        </script>
    </body>
    </html>
    """

@app.websocket("/ws/chat/{user_id}")
async def chat_websocket(websocket: WebSocket, user_id: str):
    await websocket.accept()
    if user_id not in user_connections:
        user_connections[user_id] = []
    # Prevent duplicate websocket objects for the same user
    if websocket not in user_connections[user_id]:
        user_connections[user_id].append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            import json
            try:
                payload = json.loads(data)
                sender_id = payload.get("sender_id")
                receiver_id = payload.get("receiver_id")
                msg = payload.get("msg")
                typing = payload.get("typing", False)
            except Exception:
                sender_id = receiver_id = msg = None
                typing = False
            # Typing notification
            if typing and sender_id and receiver_id:
                if receiver_id in user_connections:
                    for ws in user_connections[receiver_id]:
                        try:
                            await ws.send_text(json.dumps({"typing": True, "sender_id": sender_id}))
                        except Exception:
                            pass
                continue
            # Store in MongoDB if sender_id and receiver_id and msg are present
            if sender_id and receiver_id and msg:
                with get_db() as db:
                    db.websocket_messages.insert_one({
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "msg": msg
                    })
                # Send to receiver in real time if connected
                if receiver_id in user_connections:
                    for ws in user_connections[receiver_id]:
                        try:
                            await ws.send_text(json.dumps({"sender_id": sender_id, "msg": msg}))
                        except Exception:
                            pass
            # Only send confirmation to the sender websocket that just sent the message
            # (do not send to all websockets for this user_id)
            try:
                if msg and sender_id == user_id:
                    await websocket.send_text(json.dumps({"sender_id": sender_id, "msg": msg}))
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if user_id in user_connections and websocket in user_connections[user_id]:
            user_connections[user_id].remove(websocket)
            if not user_connections[user_id]:
                del user_connections[user_id]

@app.get("/chat-history")
def chat_history(sender_id: str = Query(...), receiver_id: str = Query(...)):
    with get_db() as db:
        # Fetch messages where sender/receiver match either way
        messages = list(db.websocket_messages.find({
            "$or": [
                {"sender_id": sender_id, "receiver_id": receiver_id},
                {"sender_id": receiver_id, "receiver_id": sender_id}
            ]
        }, {"_id": 0, "sender_id": 1, "receiver_id": 1, "msg": 1}).sort("_id", 1))
    return {"status": True, "history": messages}

@app.post("/send-message")
async def send_message_to_user(
    sender_id: str = Body(...),
    receiver_id: str = Body(...),
    msg: str = Body(...)
):
    import json
    # Store in MongoDB
    with get_db() as db:
        db.websocket_messages.insert_one({
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "msg": msg
        })
    # Send to receiver in real time if connected and websocket is open
    delivered = False
    if receiver_id in user_connections:
        open_connections = []
        for ws in user_connections[receiver_id]:
            if ws.client_state.name == "CONNECTED":
                try:
                    await ws.send_text(json.dumps({"sender_id": sender_id, "msg": msg}))
                    delivered = True;
                    open_connections.append(ws)
                except Exception:
                    pass
        user_connections[receiver_id] = open_connections
        if not user_connections[receiver_id]:
            del user_connections[receiver_id]
    return {
        "status": True,
        "delivered": delivered,
        "message": "Message sent and stored in DB"
    }

"""
USAGE:

WebSocket URL (for browser JS, Postman, or any WebSocket client):
    ws://localhost:8000/ws-demo/ws/hello

WebSocket Request Example (send as text):
    {
        "sender_id": "user123",
        "receiver_id": "user456",
        "msg": "Hello from user123 to user456"
    }

MongoDB Collection:
    websocket_messages
    (fields: sender_id, receiver_id, msg)

HTTP POST API to broadcast to all /ws/api clients:
    POST http://localhost:8000/ws-demo/api/send-message
    Body (JSON): { "message": "your message here" }

Example usage for @app.websocket("/ws/chat/{user_id}"):

To connect to this WebSocket endpoint, use a WebSocket client (browser JS, Postman, Thunder Client, etc):

WebSocket URL format:
    ws://localhost:8000/ws-demo/ws/chat/{user_id}

Replace {user_id} with the sender's user ID.

Example:
    ws://localhost:8000/ws-demo/ws/chat/user123

How to test in browser JS console:
    let ws = new WebSocket("ws://localhost:8000/ws-demo/ws/chat/user123");
    ws.onmessage = (e) => console.log("Received:", e.data);
    ws.onopen = () => ws.send(JSON.stringify({
        sender_id: "user123",
        receiver_id: "user456",
        msg: "Hello user456!"
    }));

How to test in Postman:
    - Open Postman > New > WebSocket Request
    - URL: ws://localhost:8000/ws-demo/ws/chat/user123
    - After connecting, send:
      {
        "sender_id": "user123",
        "receiver_id": "user456",
        "msg": "Hello user456!"
      }

If user456 is also connected (with their own WebSocket connection), they will receive the message in real time.
"""


