# Assuming this is in your websocket_demo.py or websocket_routes.py
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from db import get_db
import json
import logging
import datetime
from bson import ObjectId # <--- ADD THIS IMPORT for ObjectId type

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# If this code is in main.py, you need to revisit the previous advice about APIRouter.
# For now, I'm fixing the ObjectId issue assuming this is the file running the WebSocket.
# If you are using websocket_routes.py, apply this fix there.
# If this is indeed main.py, then 'app = FastAPI()' only needs to be defined ONCE.
# I'm providing the fix for the websocket_endpoint, regardless of where it resides now.

app = FastAPI() # If this is websocket_demo.py, this 'app' instance isn't directly used
                # when mounted via include_router. If this is main.py, ensure it's the ONLY
                # FastAPI() instance.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store WebSocket connections
user_connections = {}

@app.websocket("/ws/chat/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    logger.info(f"Attempting to accept WebSocket connection for user: {user_id}")
    await websocket.accept()
    logger.info(f"WebSocket connection accepted for user: {user_id}")

    if user_id not in user_connections:
        user_connections[user_id] = []
    user_connections[user_id].append(websocket)
    logger.info(f"User {user_id} now has {len(user_connections[user_id])} active WebSocket(s).")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            sender_id = payload.get("sender_id")
            receiver_id = payload.get("receiver_id")
            msg = payload.get("msg")
            typing = payload.get("typing", False)

            if typing:
                logger.debug(f"Typing indicator received from {sender_id} to {receiver_id}.")
                if receiver_id in user_connections:
                    for ws_conn in user_connections[receiver_id]:
                        await ws_conn.send_text(json.dumps({"typing": True, "sender_id": sender_id}))
                continue

            if sender_id and receiver_id and msg:
                message_data = {
                    "sender_id": sender_id,
                    "receiver_id": receiver_id,
                    "msg": msg,
                    "timestamp": payload.get("timestamp") or datetime.datetime.utcnow().isoformat()
                }
                logger.info(f"Message received from {sender_id} to {receiver_id}: '{msg}'. Saving with timestamp: {message_data['timestamp']}")

                try:
                    with get_db() as db:
                        # Insert the message
                        result = db.websocket_messages.insert_one(message_data)
                        # Add the _id from the insert operation to message_data
                        # This is what's causing the ObjectId error later
                        message_data["_id"] = str(result.inserted_id) # <--- CONVERT ObjectId TO STRING HERE
                    logger.info("Message saved to database successfully.")
                except Exception as e:
                    logger.error(f"Failed to save message to database: {e}", exc_info=True)
                    await websocket.send_text(json.dumps({"error": "Failed to save message", "details": str(e)}))
                    continue

                # Prepare data for sending: Ensure all ObjectIds are strings
                # This loop handles _id that might be present if retrieved from DB,
                # though in this flow, it's primarily for the inserted_id.
                serializable_message_data = {}
                for k, v in message_data.items():
                    if isinstance(v, ObjectId):
                        serializable_message_data[k] = str(v)
                    else:
                        serializable_message_data[k] = v

                # Send to receiver if connected
                if receiver_id in user_connections:
                    for ws_conn in user_connections[receiver_id]:
                        await ws_conn.send_text(json.dumps(serializable_message_data)) # <--- USE serializable_message_data
                    logger.info(f"Message broadcasted to receiver {receiver_id}.")
                else:
                    logger.info(f"Receiver {receiver_id} not currently connected. Message not broadcasted live.")

                # Send back to sender (for immediate display and confirmation)
                await websocket.send_text(json.dumps(serializable_message_data)) # <--- USE serializable_message_data
                logger.debug(f"Message echoed back to sender {sender_id}.")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user: {user_id}")
    except json.JSONDecodeError:
        logger.warning(f"Received malformed JSON from {user_id}.")
        await websocket.send_text(json.dumps({"error": "Invalid JSON format received"}))
    except Exception as e:
        logger.error(f"An unexpected error occurred in WebSocket for {user_id}: {e}", exc_info=True)
    finally:
        if user_id in user_connections and websocket in user_connections[user_id]:
            user_connections[user_id].remove(websocket)
            if not user_connections[user_id]:
                del user_connections[user_id]
                logger.info(f"All WebSockets for user {user_id} disconnected. User removed from connections list.")
            else:
                logger.info(f"User {user_id} now has {len(user_connections[user_id])} active WebSocket(s) remaining.")


@app.get("/chat-history")
def get_chat_history(sender_id: str = Query(...), receiver_id: str = Query(...)):
    logger.info(f"Fetching chat history between {sender_id} and {receiver_id}")
    try:
        with get_db() as db:
            messages = list(db.websocket_messages.find({
                "$or": [
                    {"sender_id": sender_id, "receiver_id": receiver_id},
                    {"sender_id": receiver_id, "receiver_id": sender_id}
                ]
            }).sort("timestamp", 1)) # Removing {"_id": 0} projection temporarily to show _id

            # Crucially, convert ObjectId to string for ALL messages fetched for history
            for msg_doc in messages:
                if "_id" in msg_doc:
                    msg_doc["_id"] = str(msg_doc["_id"])

            logger.info(f"Found {len(messages)} messages for chat history between {sender_id} and {receiver_id}.")
            return {"status": True, "history": messages}
    except Exception as e:
        logger.error(f"Failed to fetch chat history: {e}", exc_info=True)
        return {"status": False, "message": "Failed to retrieve chat history", "error": str(e)}