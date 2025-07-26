# Assuming this is in your websocket_demo.py or websocket_routes.py
from typing import Optional, Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from db import get_db
import json
import logging
import datetime
import uuid
from bson import ObjectId
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Call status enum
class CallStatus(str, Enum):
    RINGING = "ringing"
    ONGOING = "ongoing"
    ENDED = "ended"
    REJECTED = "rejected"
    MISSED = "missed"

# Call type enum
class CallType(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store WebSocket connections for chat
user_connections = {}

# Store active calls and WebSocket connections for calls
active_calls: Dict[str, Dict] = {}
call_connections: Dict[str, List[WebSocket]] = {}

# Add this global mapping
latest_call_for_receiver: Dict[str, str] = {}

# Helper: Log all call_connections and active_calls for debugging
def debug_call_state():
    logger.info(f"--- DEBUG CALL STATE ---")
    logger.info(f"call_connections: { {k: len(v) for k, v in call_connections.items()} }")
    logger.info(f"active_calls: {list(active_calls.keys())}")
    logger.info(f"latest_call_for_receiver: {latest_call_for_receiver}")
    logger.info(f"------------------------")

# Helper: Check if both caller and receiver are connected before allowing call
def both_call_participants_connected(caller_id: str, receiver_id: str) -> bool:
    return (
        caller_id in call_connections and len(call_connections[caller_id]) > 0 and
        receiver_id in call_connections and len(call_connections[receiver_id]) > 0
    )

# Helper: Check if a call_id is present in the DB (for debugging lost in-memory state)
def call_exists_in_db(call_id: str) -> bool:
    try:
        with get_db() as db:
            return db.call_history.find_one({"call_id": call_id}) is not None
    except Exception as e:
        logger.error(f"DB check failed for call_id {call_id}: {e}")
        return False

# Helper: Restore active_calls from DB for a given call_id (for single-process debug only)
def restore_active_call_from_db(call_id: str):
    try:
        with get_db() as db:
            call = db.call_history.find_one({"call_id": call_id})
            if call:
                # Remove _id if present and convert to dict
                call.pop("_id", None)
                active_calls[call_id] = dict(call)
                # Also update latest_call_for_receiver
                receiver_id = call.get("receiver_id")
                if receiver_id:
                    latest_call_for_receiver[receiver_id] = call_id
                logger.info(f"Restored call {call_id} from DB to active_calls.")
                debug_call_state()
                return True
    except Exception as e:
        logger.error(f"Failed to restore call {call_id} from DB: {e}")
    return False

# ====================== WEBRTC DEBUGGING TIPS ======================
# If signaling works but voice/video is not shared:
# - Make sure your client (browser/app) is using the correct TURN/STUN servers.
# - Ensure both clients are on public internet or use a TURN server if behind NAT/firewall.
# - Check that your signaling (offer/answer/ice_candidate) messages are being exchanged in order.
# - Confirm that the "offer", "answer", and "ice_candidate" handlers are called and messages are delivered to the other user.
# - Log the payloads for "offer", "answer", and "ice_candidate" in both server and client.
# - On the client, check for WebRTC errors in the browser console or app logs.
# - Make sure you are using the same call_id for all signaling messages.
# - If using HTTPS/WSS, ensure certificates are valid.
# - If using localhost for both clients, try with two different networks/devices for real-world test.

# ====================== WEBRTC SIGNALING LOGGING ======================
# Add extra logging for signaling payloads

async def handle_webrtc_offer(websocket: WebSocket, payload: Dict, user_id: str):
    logger.info(f"handle_webrtc_offer payload: {payload}")  # Log full payload
    call_id = payload.get("call_id")
    offer = payload.get("offer")
    # Log SDP type and length for debugging
    if offer and isinstance(offer, dict):
        logger.info(f"SDP type: {offer.get('type')}, SDP length: {len(offer.get('sdp', ''))}")
    # Validate offer structure
    if not offer or not isinstance(offer, dict) or "type" not in offer or "sdp" not in offer:
        logger.error("Invalid offer structure received.")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid offer structure. Must include 'type' and 'sdp'."
        }))
        return
    # Check call_id in active_calls
    if not call_id or call_id not in active_calls:
        logger.error(f"Offer received for invalid call_id: {call_id}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid call_id for offer."
        }))
        return
    call_data = active_calls[call_id]
    # Forward offer to the other participant
    other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
    if other_user_id in call_connections:
        for ws_conn in call_connections[other_user_id]:
            try:
                await ws_conn.send_text(json.dumps({
                    "type": "offer",
                    "call_id": call_id,
                    "offer": offer,
                    "from": user_id
                }))
                logger.info(f"Offer forwarded to {other_user_id}")
            except Exception as e:
                logger.error(f"Failed to forward WebRTC offer: {e}")
    else:
        logger.error(f"No call connection found for other_user_id: {other_user_id}")
    logger.info(f"WebRTC offer forwarded for call: {call_id}")

async def handle_webrtc_answer(websocket: WebSocket, payload: Dict, user_id: str):
    logger.info(f"handle_webrtc_answer payload: {payload}")  # Log full payload
    call_id = payload.get("call_id")
    answer = payload.get("answer")
    # Log SDP type and length for debugging
    if answer and isinstance(answer, dict):
        logger.info(f"SDP type: {answer.get('type')}, SDP length: {len(answer.get('sdp', ''))}")
    # Validate answer structure
    if not answer or not isinstance(answer, dict) or "type" not in answer or "sdp" not in answer:
        logger.error("Invalid answer structure received.")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid answer structure. Must include 'type' and 'sdp'."
        }))
        return
    # Check call_id in active_calls
    if not call_id or call_id not in active_calls:
        logger.error(f"Answer received for invalid call_id: {call_id}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid call_id for answer."
        }))
        return
    call_data = active_calls[call_id]
    # Forward answer to the other participant
    other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
    if other_user_id in call_connections:
        for ws_conn in call_connections[other_user_id]:
            try:
                await ws_conn.send_text(json.dumps({
                    "type": "answer",
                    "call_id": call_id,
                    "answer": answer,
                    "from": user_id
                }))
                logger.info(f"Answer forwarded to {other_user_id}")
            except Exception as e:
                logger.error(f"Failed to forward WebRTC answer: {e}")
    else:
        logger.error(f"No call connection found for other_user_id: {other_user_id}")
    logger.info(f"WebRTC answer forwarded for call: {call_id}")

async def handle_ice_candidate(websocket: WebSocket, payload: Dict, user_id: str):
    logger.info(f"handle_ice_candidate payload: {payload}")  # Log full payload
    candidate = payload.get("candidate")
    call_id = payload.get("call_id")
    # Log candidate details for debugging
    if candidate and isinstance(candidate, dict):
        logger.info(f"ICE candidate: {candidate.get('candidate')}, sdpMid: {candidate.get('sdpMid')}, sdpMLineIndex: {candidate.get('sdpMLineIndex')}")
    # Validate candidate structure
    if not candidate or not isinstance(candidate, dict) or "candidate" not in candidate:
        logger.error("Invalid ICE candidate structure received.")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid ICE candidate structure. Must include 'candidate'."
        }))
        return
    # Check call_id in active_calls
    if not call_id or call_id not in active_calls:
        logger.error(f"ICE candidate received for invalid call_id: {call_id}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Invalid call_id for ICE candidate."
        }))
        return
    call_data = active_calls[call_id]
    # Forward ICE candidate to the other participant
    other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
    if other_user_id in call_connections:
        for ws_conn in call_connections[other_user_id]:
            try:
                await ws_conn.send_text(json.dumps({
                    "type": "ice_candidate",
                    "call_id": call_id,
                    "candidate": candidate,
                    "from": user_id
                }))
                logger.info(f"ICE candidate forwarded to {other_user_id}")
            except Exception as e:
                logger.error(f"Failed to forward ICE candidate: {e}")
    else:
        logger.error(f"No call connection found for other_user_id: {other_user_id}")
    logger.info(f"ICE candidate forwarded for call: {call_id}")

# ====================== EXISTING CHAT WEBSOCKET ======================

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
            try:
                data = await websocket.receive_text()
            except Exception as e:
                logger.error(f"Non-text or invalid message received from user {user_id}: {e}")
                await websocket.close(code=1003)
                break
            try:
                payload = json.loads(data)
            except Exception as e:
                logger.error(f"Invalid JSON from user {user_id}: {e}")
                await websocket.send_text(json.dumps({"error": "Invalid JSON format"}))
                continue

            # Accept messages without 'type' for plain chat, only require 'type' for signaling
            message_type = payload.get("type")
            sender_id = payload.get("sender_id")
            receiver_id = payload.get("receiver_id")
            msg = payload.get("msg")
            typing = payload.get("typing", False)

            if message_type:
                # ...existing code for signaling or special messages...
                if message_type == "typing":
                    logger.debug(f"Typing indicator received from {sender_id} to {receiver_id}.")
                    if receiver_id in user_connections:
                        for ws_conn in user_connections[receiver_id]:
                            await ws_conn.send_text(json.dumps({"typing": True, "sender_id": sender_id}))
                    continue
                # Add other signaling logic here if needed
                # ...existing code...
            # If no 'type', treat as plain chat message
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
                        message_data["_id"] = str(result.inserted_id)
                    logger.info("Message saved to database successfully.")
                except Exception as e:
                    logger.error(f"Failed to save message to database: {e}", exc_info=True)
                    await websocket.send_text(json.dumps({"error": "Failed to save message", "details": str(e)}))
                    continue

                # Prepare data for sending: Ensure all ObjectIds are strings
                serializable_message_data = {}
                for k, v in message_data.items():
                    if isinstance(v, ObjectId):
                        serializable_message_data[k] = str(v)
                    else:
                        serializable_message_data[k] = v

                # Send to receiver if connected
                if receiver_id in user_connections:
                    for ws_conn in user_connections[receiver_id]:
                        await ws_conn.send_text(json.dumps(serializable_message_data))
                    logger.info(f"Message broadcasted to receiver {receiver_id}.")
                else:
                    logger.info(f"Receiver {receiver_id} not currently connected. Message not broadcasted live.")

                # Send back to sender (for immediate display and confirmation)
                await websocket.send_text(json.dumps(serializable_message_data))
                logger.debug(f"Message echoed back to sender {sender_id}.")
            else:
                # If neither signaling nor valid chat message, send error
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid message format. Must include sender_id, receiver_id, and msg for chat."
                }))

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

# ====================== NEW CALL WEBSOCKET ======================

@app.websocket("/ws/call/{user_id}")
async def call_websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for handling audio/video calls
    """
    logger.info(f"Call WebSocket connection attempt for websocket: {websocket}")
    logger.info(f"Call WebSocket connection attempt for user: {user_id}")
    await websocket.accept()
    logger.info(f"Call WebSocket connection accepted for user: {user_id}")

    # Add user to call connections
    if user_id not in call_connections:
        call_connections[user_id] = []
    call_connections[user_id].append(websocket)
    debug_call_state()  # Log state after connection

    try:
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect as ws_exc:
                logger.info(f"Call WebSocket disconnected for user: {user_id}")
                await handle_user_disconnect(user_id)
                break
            except Exception as e:
                logger.error(f"Non-text or invalid message received from user {user_id}: {e}")
                break

            # Log the raw data and its type for debugging
            logger.info(f"[DEBUG] Raw data from user {user_id}: {repr(data)} (type: {type(data)})")

            debug_call_state()  # Log state on every message
            try:
                payload = json.loads(data)
            except Exception as e:
                logger.error(f"Invalid JSON from user {user_id}: {e} | Raw data: {repr(data)}")
                await websocket.send_text(json.dumps({"error": "Invalid JSON format"}))
                continue

            # Log the parsed payload for debugging
            logger.info(f"[DEBUG] Parsed payload from user {user_id}: {payload}")

            message_type = payload.get("type")
            if not message_type:
                logger.error(f"Missing 'type' in message from user {user_id}: {payload}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Missing 'type' field in message."
                }))
                continue

            # Check for empty or missing SDP in offer/answer
            if message_type in ("offer", "answer"):
                sdp_obj = payload.get(message_type)
                logger.info(f"[DEBUG] SDP object for {message_type} from user {user_id}: {sdp_obj}")
                if not sdp_obj or not isinstance(sdp_obj, dict) or not sdp_obj.get("sdp"):
                    logger.error(f"SDP missing or empty for {message_type} from user {user_id}: {payload}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"SDP is missing or empty for {message_type}."
                    }))
                    continue

            # Log the message_type received from client for debugging
            logger.info(f"[CHECK] Client sent message_type: {message_type} | payload: {payload}")

            # --- Custom logic based on message_type for signaling flow ---
            if message_type == "initiate_call":
                # Initiator should send offer after call initiation
                logger.info(f"[PROCESS] After initiate_call, client should send 'offer' for call setup.")
                await handle_initiate_call(websocket, payload, user_id)
            elif message_type == "accept_call":
                # Receiver should send answer after accepting call
                logger.info(f"[PROCESS] After accept_call, client should send 'answer' for call setup.")
                await handle_accept_call(websocket, payload, user_id)
            elif message_type == "offer":
                await handle_webrtc_offer(websocket, payload, user_id)
            elif message_type == "answer":
                await handle_webrtc_answer(websocket, payload, user_id)
            elif message_type == "reject_call":
                await handle_reject_call(websocket, payload, user_id)
            elif message_type == "end_call":
                await handle_end_call(websocket, payload, user_id)
            elif message_type == "ice_candidate":
                await handle_ice_candidate(websocket, payload, user_id)
            elif message_type == "call_status":
                await handle_call_status_update(websocket, payload, user_id)
            elif message_type == "media_chunk":
                await save_media_chunk(payload, user_id)
            else:
                logger.warning(f"Unknown message type: {message_type} from user: {user_id}")
            # ...existing code...
            if message_type == "initiate_call":
                await handle_initiate_call(websocket, payload, user_id)
            elif message_type == "accept_call":
                await handle_accept_call(websocket, payload, user_id)
                logger.info(f"Call accepted: {payload.get('call_id')} from {user_id} to {payload.get('receiver_id')}")
            elif message_type == "reject_call":
                await handle_reject_call(websocket, payload, user_id)
                logger.info(f"Call rejected: {payload.get('call_id')} by {user_id}")
            elif message_type == "end_call":
                await handle_end_call(websocket, payload, user_id)
                logger.info(f"Call ended: {payload.get('call_id')} by {user_id}")
            elif message_type == "offer":
                logger.info(f"WebRTC offer received from {user_id}: {payload}")
                offer = payload.get("offer")
                if offer and isinstance(offer, dict):
                    logger.info(f"Offer SDP from {user_id}: type={offer.get('type')}, sdp={offer.get('sdp')[:100]}...")
                logger.info(f"Before forwarding offer: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
                await handle_webrtc_offer(websocket, payload, user_id)
                logger.info(f"After forwarding offer: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
            elif message_type == "answer":
                logger.info(f"WebRTC answer received from {user_id}: {payload}")
                answer = payload.get("answer")
                if answer and isinstance(answer, dict):
                    logger.info(f"Answer SDP from {user_id}: type={answer.get('type')}, sdp={answer.get('sdp')[:100]}...")
                logger.info(f"Before forwarding answer: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
                await handle_webrtc_answer(websocket, payload, user_id)
                logger.info(f"After forwarding answer: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
            elif message_type == "ice_candidate":
                logger.info(f"ICE candidate received from {user_id}: {payload}")
                logger.info(f"Before forwarding candidate: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
                await handle_ice_candidate(websocket, payload, user_id)
                logger.info(f"After forwarding candidate: call_connections={ {k: len(v) for k, v in call_connections.items()} }, active_calls={list(active_calls.keys())}")
            elif message_type == "call_status":
                await handle_call_status_update(websocket, payload, user_id)
                logger.info(f"Call status update: {payload.get('status_update')} for call {payload.get('call_id')} from {user_id}")
            elif message_type == "media_chunk":
                # Save received media chunk to MongoDB
                await save_media_chunk(payload, user_id)
            else:
                logger.warning(f"Unknown message type: {message_type} from user: {user_id}")
            # Handle other message types as needed

    except Exception as e:
        logger.error(f"Error in call WebSocket for {user_id}: {e}", exc_info=True)
    finally:
        # Clean up connections
        if user_id in call_connections and websocket in call_connections[user_id]:
            call_connections[user_id].remove(websocket)
            if not call_connections[user_id]:
                del call_connections[user_id]

# ====================== CALL HANDLER FUNCTIONS ======================

async def handle_initiate_call(websocket: WebSocket, payload: Dict, caller_id: str):
    """
    Handle call initiation
    """
    try:
        receiver_id = payload.get("receiver_id")
        call_type = payload.get("call_type", CallType.AUDIO)
        logger.info(f"Current call_connections: {list(call_connections.keys())}")
        logger.info(f"Current active_calls: {list(active_calls.keys())}")

        if not receiver_id:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Receiver ID is required"
            }))
            return

        # Only allow call if both caller and receiver are connected
        if not both_call_participants_connected(caller_id, receiver_id):
            logger.warning(f"Either caller {caller_id} or receiver {receiver_id} is not connected to the call WebSocket. Cannot initiate call.")
            await websocket.send_text(json.dumps({
                "type": "call_failed",
                "message": "Both caller and receiver must be connected to the call WebSocket before initiating a call.",
                "call_id": None
            }))
            return

        # Check if receiver is online (must have an open WebSocket)
        if receiver_id not in call_connections or not call_connections[receiver_id]:
            logger.warning(f"Receiver {receiver_id} is not connected. Cannot initiate call.")
            await websocket.send_text(json.dumps({
                "type": "call_failed",
                "message": "User is not available",
                "call_id": None
            }))
            return

        # Prevent duplicate call for same caller/receiver if already ringing or ongoing
        for call in active_calls.values():
            if (call["caller_id"] == caller_id and call["receiver_id"] == receiver_id and 
                call["status"] in [CallStatus.RINGING, CallStatus.ONGOING]):
                logger.warning(f"Duplicate call attempt from {caller_id} to {receiver_id}. Existing call_id: {call['call_id']}")
                await websocket.send_text(json.dumps({
                    "type": "call_failed",
                    "message": "A call is already in progress or ringing with this user.",
                    "call_id": call["call_id"]
                }))
                return

        # Generate unique call ID
        call_id = str(uuid.uuid4())
        logger.info(f"Generated call_id: {call_id} for call from {caller_id} to {receiver_id}")
        
        # Create call record
        call_data = {
            "call_id": call_id,
            "caller_id": caller_id,
            "receiver_id": receiver_id,
            "call_type": call_type,
            "status": CallStatus.RINGING,
            "started_at": datetime.datetime.utcnow().isoformat(),
            "ended_at": None,
            "duration": None
        }

        # Store active call BEFORE sending to receiver
        active_calls[call_id] = call_data
        latest_call_for_receiver[receiver_id] = call_id
        debug_call_state()  # Log state after call is stored
        logger.info(f"Stored active call: {call_id}")

        # Save call to database
        try:
            with get_db() as db:
                db.call_history.insert_one(call_data.copy())
            logger.info(f"Call record saved to database: {call_id}")
        except Exception as e:
            logger.error(f"Failed to save call record: {e}")

        # Get caller details
        caller_name = "Unknown"
        try:
            with get_db() as db:
                caller = db.baatchit_user.find_one(
                    {"user_comman_id": caller_id},
                    {"_id": 0, "full_name": 1, "user_comman_id": 1}
                )
                if caller:
                    caller_name = caller["full_name"]
        except Exception as e:
            logger.error(f"Failed to get caller details: {e}")

        # Notify receiver about incoming call
        incoming_call_data = {
            "type": "incoming_call",
            "call_id": call_id,  # <-- call_id sent to receiver
            "caller_id": caller_id,
            "caller_name": caller_name,
            "call_type": call_type,
            "timestamp": call_data["started_at"]
        }

        # Send to receiver
        for ws_conn in call_connections[receiver_id]:
            try:
                logger.info(f"Sending to receiver {receiver_id}: {json.dumps(incoming_call_data)}")  # Log outgoing message
                await ws_conn.send_text(json.dumps(incoming_call_data))
                logger.info(f"Sent incoming call notification to {receiver_id} with call_id {call_id}")
            except Exception as e:
                logger.error(f"Failed to send incoming call to receiver: {e}")

        # Confirm call initiation to caller
        logger.info(f"Sending to caller {caller_id}: {json.dumps({'type': 'call_initiated', 'call_id': call_id, 'receiver_id': receiver_id, 'status': CallStatus.RINGING})}")  # Log outgoing message
        await websocket.send_text(json.dumps({
            "type": "call_initiated",
            "call_id": call_id,
            "receiver_id": receiver_id,
            "status": CallStatus.RINGING
        }))
        logger.info(f"Sent call_initiated to caller {caller_id} with call_id {call_id}")

        logger.info(f"Call initiated: {call_id} from {caller_id} to {receiver_id}")
        
    except Exception as e:
        logger.error(f"Error in handle_initiate_call: {e}", exc_info=True)
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Failed to initiate call"
        }))

async def handle_accept_call(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle call acceptance
    """
    logger.info(f"handle_accept_call payload: {payload}")
    logger.info(f"Current active_calls at accept: {list(active_calls.keys())}")
    try:
        call_id = payload.get("call_id")
        logger.info(f"Attempting to accept call: {call_id} by user: {user_id}")
        logger.info(f"Current active calls: {list(active_calls.keys())}")

        # If call_id is missing or invalid, try to get the latest call for this receiver
        if (not call_id or call_id not in active_calls) and user_id in latest_call_for_receiver:
            possible_call_id = latest_call_for_receiver[user_id]
            if possible_call_id in active_calls:
                logger.warning(f"Client did not send valid call_id, using latest for receiver: {possible_call_id}")
                call_id = possible_call_id

        # Extra fallback: try to find a ringing call for this receiver
        if not call_id or call_id not in active_calls:
            for cid, call in active_calls.items():
                if call["receiver_id"] == user_id and call["status"] == CallStatus.RINGING:
                    logger.warning(f"Fallback: found ringing call for receiver {user_id}: {cid}")
                    call_id = cid
                    break

        # If still not found, try to restore from DB (single-process only)
        if not call_id or call_id not in active_calls:
            in_db = call_exists_in_db(call_id) if call_id else False
            if in_db:
                restored = restore_active_call_from_db(call_id)
                if restored:
                    logger.info(f"Call {call_id} restored from DB for receiver {user_id}. Retrying accept.")
                    # Now retry the accept logic
                    await handle_accept_call(websocket, payload, user_id)
                    return
            logger.error(
                f"No valid call found for receiver {user_id}. active_calls: {active_calls}. "
                f"Call {call_id} exists in DB: {in_db}"
            )
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": (
                    f"No valid call found for you. Please wait for an incoming call notification and use its call_id."
                    + (f" (Call exists in DB: {in_db})" if in_db else "")
                )
            }))
            return

        call_data = active_calls[call_id]

        # Log the offer/answer payload for debugging
        if "offer" in payload:
            logger.info(f"[CHECK] Received offer payload: {payload['offer']}")
        if "answer" in payload:
            logger.info(f"[CHECK] Received answer payload: {payload['answer']}")

        # Verify user is the receiver
        if call_data["receiver_id"] != user_id:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "You are not authorized to accept this call"
            }))
            return

        # Update call status
        call_data["status"] = CallStatus.ONGOING
        call_data["accepted_at"] = datetime.datetime.utcnow().isoformat()

        # Update database
        try:
            with get_db() as db:
                db.call_history.update_one(
                    {"call_id": call_id},
                    {"$set": {
                        "status": CallStatus.ONGOING,
                        "accepted_at": call_data["accepted_at"]
                    }}
                )
        except Exception as e:
            logger.error(f"Failed to update call status: {e}")

        # Notify caller that call was accepted
        caller_id = call_data["caller_id"]
        receiver_id = call_data["receiver_id"]  # Always set for logging
        if caller_id in call_connections:
            for ws_conn in call_connections[caller_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "call_accepted",
                        "call_id": call_id,
                        "receiver_id": user_id
                    }))
                    logger.info(f"Notified caller {caller_id} that call was accepted")
                except Exception as e:
                    logger.error(f"Failed to notify caller of call acceptance: {e}")

        # Confirm acceptance to receiver
        await websocket.send_text(json.dumps({
            "type": "call_accepted_confirm",
            "call_id": call_id,
            "status": CallStatus.ONGOING
        }))

        logger.info(f"Call accepted: {call_id} by {user_id}")
        logger.info(f"Call accepted: {call_id} from {user_id} to {receiver_id}")

    except Exception as e:
        logger.error(f"Error in handle_accept_call: {e}", exc_info=True)
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Failed to accept call"
        }))

async def handle_reject_call(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle call rejection
    """
    logger.info(f"handle_reject_call payload: {payload}")
    logger.info(f"Current active_calls at reject: {list(active_calls.keys())}")
    try:
        call_id = payload.get("call_id")
        # If call_id is missing or invalid, try to get the latest call for this receiver
        if (not call_id or call_id not in active_calls) and user_id in latest_call_for_receiver:
            possible_call_id = latest_call_for_receiver[user_id]
            if possible_call_id in active_calls:
                logger.warning(f"Client did not send valid call_id, using latest for receiver: {possible_call_id}")
                call_id = possible_call_id

        # Extra fallback: try to find a ringing call for this receiver
        if not call_id or call_id not in active_calls:
            for cid, call in active_calls.items():
                if call["receiver_id"] == user_id and call["status"] == CallStatus.RINGING:
                    logger.warning(f"Fallback: found ringing call for receiver {user_id}: {cid}")
                    call_id = cid
                    break

        if not call_id or call_id not in active_calls:
            logger.error(f"No valid call found for receiver {user_id}. active_calls: {active_calls}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"No valid call found for you. Please wait for an incoming call notification and use its call_id."
            }))
            return

        call_data = active_calls[call_id]
        
        # Update call status
        call_data["status"] = CallStatus.REJECTED
        call_data["ended_at"] = datetime.datetime.utcnow().isoformat()

        # Update database
        try:
            with get_db() as db:
                db.call_history.update_one(
                    {"call_id": call_id},
                    {"$set": {
                        "status": CallStatus.REJECTED,
                        "ended_at": call_data["ended_at"]
                    }}
                )
        except Exception as e:
            logger.error(f"Failed to update call status: {e}")

        # Notify caller that call was rejected
        caller_id = call_data["caller_id"]
        if caller_id in call_connections:
            for ws_conn in call_connections[caller_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "call_rejected",
                        "call_id": call_id,
                        "receiver_id": user_id
                    }))
                except Exception as e:
                    logger.error(f"Failed to notify caller of call rejection: {e}")

        # Confirm rejection to receiver
        await websocket.send_text(json.dumps({
            "type": "call_rejected_confirm",
            "call_id": call_id
        }))

        # Remove from active calls
        del active_calls[call_id]
        logger.info(f"Call rejected: {call_id} by {user_id}")
        
    except Exception as e:
        logger.error(f"Error in handle_reject_call: {e}", exc_info=True)
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Failed to reject call"
        }))

async def handle_end_call(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle call ending
    """
    logger.info(f"handle_end_call payload: {payload}")
    logger.info(f"Current active_calls at end: {list(active_calls.keys())}")
    try:
        call_id = payload.get("call_id")
        logger.info(f"Attempting to end call: {call_id} by user: {user_id}")
        
        if not call_id:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Call ID is required"
            }))
            return
            
        if call_id not in active_calls:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Invalid call ID: {call_id}. Call may have already ended."
            }))
            return

        call_data = active_calls[call_id]
        
        # Calculate duration if call was ongoing
        duration = None
        if call_data["status"] == CallStatus.ONGOING and "accepted_at" in call_data:
            start_time = datetime.datetime.fromisoformat(call_data["accepted_at"])
            end_time = datetime.datetime.utcnow()
            duration = int((end_time - start_time).total_seconds())

        # Update call status
        call_data["status"] = CallStatus.ENDED
        call_data["ended_at"] = datetime.datetime.utcnow().isoformat()
        call_data["duration"] = duration

        # Update database
        try:
            with get_db() as db:
                db.call_history.update_one(
                    {"call_id": call_id},
                    {"$set": {
                        "status": CallStatus.ENDED,
                        "ended_at": call_data["ended_at"],
                        "duration": duration
                    }}
                )
        except Exception as e:
            logger.error(f"Failed to update call status: {e}")

        # Notify other participant
        other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
        if other_user_id in call_connections:
            for ws_conn in call_connections[other_user_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "call_ended",
                        "call_id": call_id,
                        "ended_by": user_id,
                        "duration": duration
                    }))
                except Exception as e:
                    logger.error(f"Failed to notify other user of call end: {e}")

        # Confirm end to initiator
        await websocket.send_text(json.dumps({
            "type": "call_ended_confirm",
            "call_id": call_id,
            "duration": duration
        }))

        # Remove from active calls
        del active_calls[call_id]
        # Clean up latest_call_for_receiver
        receiver_id = call_data["receiver_id"]
        if receiver_id in latest_call_for_receiver and latest_call_for_receiver[receiver_id] == call_id:
            del latest_call_for_receiver[receiver_id]
        logger.info(f"Call ended: {call_id} by {user_id}, duration: {duration}s")
        
    except Exception as e:
        logger.error(f"Error in handle_end_call: {e}", exc_info=True)
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": "Failed to end call"
        }))

async def handle_webrtc_offer(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle WebRTC offer for peer-to-peer connection
    """
    try:
        call_id = payload.get("call_id")
        offer = payload.get("offer")
        
        if not call_id:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Call ID is required"
            }))
            return
            
        if call_id not in active_calls:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Invalid call ID: {call_id}"
            }))
            return

        call_data = active_calls[call_id]
        
        # Forward offer to the other participant
        other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
        if other_user_id in call_connections:
            for ws_conn in call_connections[other_user_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "offer",
                        "call_id": call_id,
                        "offer": offer,
                        "from": user_id
                    }))
                except Exception as e:
                    logger.error(f"Failed to forward WebRTC offer: {e}")
        
        logger.info(f"WebRTC offer forwarded for call: {call_id}")
        
    except Exception as e:
        logger.error(f"Error in handle_webrtc_offer: {e}", exc_info=True)

async def handle_webrtc_answer(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle WebRTC answer
    """
    try:
        call_id = payload.get("call_id")
        answer = payload.get("answer")
        
        if not call_id:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Call ID is required"
            }))
            return
            
        if call_id not in active_calls:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": f"Invalid call ID: {call_id}"
            }))
            return

        call_data = active_calls[call_id]
        
        # Forward answer to the other participant
        other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
        if other_user_id in call_connections:
            for ws_conn in call_connections[other_user_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "answer",
                        "call_id": call_id,
                        "answer": answer,
                        "from": user_id
                    }))
                except Exception as e:
                    logger.error(f"Failed to forward WebRTC answer: {e}")
        
        logger.info(f"WebRTC answer forwarded for call: {call_id}")
        
    except Exception as e:
        logger.error(f"Error in handle_webrtc_answer: {e}", exc_info=True)

async def handle_ice_candidate(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle ICE candidate exchange
    """
    try:
        call_id = payload.get("call_id")
        candidate = payload.get("candidate")
        
        if not call_id or call_id not in active_calls:
            return  # Silently ignore invalid ICE candidates

        call_data = active_calls[call_id]
        
        # Forward ICE candidate to the other participant
        other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
        if other_user_id in call_connections:
            for ws_conn in call_connections[other_user_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "ice_candidate",
                        "call_id": call_id,
                        "candidate": candidate,
                        "from": user_id
                    }))
                except Exception as e:
                    logger.error(f"Failed to forward ICE candidate: {e}")
                    
    except Exception as e:
        logger.error(f"Error in handle_ice_candidate: {e}", exc_info=True)

async def handle_call_status_update(websocket: WebSocket, payload: Dict, user_id: str):
    """
    Handle call status updates (mute, unmute, video on/off, etc.)
    """
    try:
        call_id = payload.get("call_id")
        status_update = payload.get("status_update")
        
        if not call_id or call_id not in active_calls:
            return

        call_data = active_calls[call_id]
        
        # Forward status update to the other participant
        other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
        if other_user_id in call_connections:
            for ws_conn in call_connections[other_user_id]:
                try:
                    await ws_conn.send_text(json.dumps({
                        "type": "call_status_update",
                        "call_id": call_id,
                        "status_update": status_update,
                        "from": user_id
                    }))
                except Exception as e:
                    logger.error(f"Failed to forward call status update: {e}")
                    
    except Exception as e:
        logger.error(f"Error in handle_call_status_update: {e}", exc_info=True)

async def handle_user_disconnect(user_id: str):
    """
    Handle user disconnection - end any active calls
    """
    try:
        # Find active calls for this user
        calls_to_end = []
        for call_id, call_data in active_calls.items():
            if call_data["caller_id"] == user_id or call_data["receiver_id"] == user_id:
                calls_to_end.append(call_id)

        # End all active calls for this user
        for call_id in calls_to_end:
            call_data = active_calls[call_id]
            other_user_id = call_data["caller_id"] if user_id == call_data["receiver_id"] else call_data["receiver_id"]
            
            # Update call status
            call_data["status"] = CallStatus.ENDED
            call_data["ended_at"] = datetime.datetime.utcnow().isoformat()
            
            # Calculate duration if applicable
            duration = None
            if "accepted_at" in call_data:
                start_time = datetime.datetime.fromisoformat(call_data["accepted_at"])
                end_time = datetime.datetime.utcnow()
                duration = int((end_time - start_time).total_seconds())
                call_data["duration"] = duration

            # Update database
            try:
                with get_db() as db:
                    db.call_history.update_one(
                        {"call_id": call_id},
                        {"$set": {
                            "status": CallStatus.ENDED,
                            "ended_at": call_data["ended_at"],
                            "duration": duration
                        }}
                    )
            except Exception as e:
                logger.error(f"Failed to update call status on disconnect: {e}")

            # Notify other participant
            if other_user_id in call_connections:
                for ws_conn in call_connections[other_user_id]:
                    try:
                        await ws_conn.send_text(json.dumps({
                            "type": "call_ended",
                            "call_id": call_id,
                            "ended_by": user_id,
                            "reason": "disconnected",
                            "duration": duration
                        }))
                    except Exception as e:
                        logger.error(f"Failed to notify call end on disconnect: {e}")

            # Remove from active calls
            del active_calls[call_id]

        logger.info(f"Ended {len(calls_to_end)} active calls for disconnected user: {user_id}")
        
    except Exception as e:
        logger.error(f"Error in handle_user_disconnect: {e}", exc_info=True)


# ====================== EXISTING CHAT ENDPOINTS ======================

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
            }).sort("timestamp", 1))

            # Convert ObjectId to string for ALL messages fetched for history
            for msg_doc in messages:
                if "_id" in msg_doc:
                    msg_doc["_id"] = str(msg_doc["_id"])

            logger.info(f"Found {len(messages)} messages for chat history between {sender_id} and {receiver_id}.")
            return {"status": True, "history": messages}
    except Exception as e:
        logger.error(f"Failed to fetch chat history: {e}", exc_info=True)
        return {"status": False, "message": "Failed to retrieve chat history", "error": str(e)}

@app.post("/baatchit/user/create")
def create_baatchit_user(
    full_name: str = Body(...),
    email: str = Body(...),
    mobile_number: str = Body(...),
    password: str = Body(...),
    confirm_password: str = Body(...)
):
    if password != confirm_password:
        return JSONResponse(content={"status": False, "message": "Passwords do not match"})
    user_comman_id = str(uuid.uuid4())
    user_status = "active"
    user_created_date = datetime.datetime.utcnow().isoformat()
    with get_db() as db:
        if db.baatchit_user.find_one({"$or": [{"email": email}, {"mobile_number": mobile_number}]}):
            return JSONResponse(content={"status": False, "message": "User already exists"})
        db.baatchit_user.insert_one({
            "full_name": full_name,
            "email": email,
            "mobile_number": mobile_number,
            "password": password,
            "user_comman_id": user_comman_id,
            "user_status": user_status,
            "user_created_date": user_created_date
        })
    return JSONResponse(content={"status": True, "message": "User created successfully", "user_comman_id": user_comman_id})

@app.get("/baatchit/user/search")
def search_baatchit_user(
    query: str = Query(None),
    full_name: str = Query(None),
    email: str = Query(None),
    mobile_number: str = Query(None)
):
    if not query and not full_name and not email and not mobile_number:
        return JSONResponse(content={"status": True, "users": []})
    
    search_conditions = []
    
    if query:
        query = query.strip()
        if len(query) < 2:
            return JSONResponse(content={"status": True, "users": []})
            
        regex_pattern = {"$regex": query, "$options": "i"}
        
        search_conditions.extend([
            {"full_name": regex_pattern},
            {"email": regex_pattern},
            {"mobile_number": regex_pattern}
        ])
    
    if full_name:
        search_conditions.append({
            "full_name": {"$regex": full_name, "$options": "i"}
        })
    
    if email:
        search_conditions.append({
            "email": {"$regex": email, "$options": "i"}
        })
    
    if mobile_number:
        search_conditions.append({
            "mobile_number": {"$regex": mobile_number, "$options": "i"}
        })
    
    if len(search_conditions) == 1:
        mongo_query = search_conditions[0]
    elif len(search_conditions) > 1:
        mongo_query = {"$or": search_conditions}
    else:
        mongo_query = {}
    
    try:
        with get_db() as db:
            users = list(db.baatchit_user.find(
                mongo_query, 
                {"_id": 0, "password": 0}
            ).limit(50))
            
            if query:
                users.sort(key=lambda x: (
                    0 if x.get('full_name', '').lower().startswith(query.lower()) else 1,
                    x.get('full_name', '').lower()
                ))
        
        return JSONResponse(content={"status": True, "users": users})
        
    except Exception as e:
        print(f"Error in search: {str(e)}")
        return JSONResponse(content={"status": True, "users": []})

@app.post("/baatchit/user/login")
def baatchit_user_login(
    email: Optional[str] = Body(None),
    mobile_number: Optional[str] = Body(None),
    password: str = Body(...)
):
    if not email and not mobile_number:
        return JSONResponse(content={"status": False, "message": "Either email or mobile must be provided"}, status_code=400)
    if email and mobile_number:
        return JSONResponse(content={"status": False, "message": "Provide either email or mobile, not both"}, status_code=400)

    with get_db() as db:
        query = {"password": password}
        if email:
            query["email"] = email
        else:
            query["mobile_number"] = mobile_number

        user = db.baatchit_user.find_one(query, {"_id": 0, "password": 0})
        if not user:
            return JSONResponse(content={"status": False, "message": "Invalid email/mobile or password"}, status_code=401)
    return JSONResponse(content={"status": True, "user": user})

@app.post("/baatchit/send-request")
def send_baatchit_request(
    from_user: str = Body(...),
    to_user: str = Body(...)
):
    with get_db() as db:
        # Check if a request from from_user to to_user already exists
        if db.baatchit_request.find_one({"from_user": from_user, "to_user": to_user}):
            return JSONResponse(content={"status": False, "message": "Request already sent"})
        
        # Check if to_user has already sent a request to from_user
        if db.baatchit_request.find_one({"from_user": to_user, "to_user": from_user}):
            return JSONResponse(content={"status": False, "message": "User has already sent you a request"})
        
        # Insert the new request
        db.baatchit_request.insert_one({
            "from_user": from_user,
            "to_user": to_user,
            "status": "pending",
            "created_at": datetime.datetime.utcnow().isoformat()
        })
    return JSONResponse(content={"status": True, "message": "Request sent"})
@app.post("/baatchit/approve-request")
def approve_baatchit_request(
    from_user: str = Body(...),
    to_user: str = Body(...)
):
    with get_db() as db:
        result = db.baatchit_request.update_one(
            {"from_user": to_user, "to_user": from_user, "status": "pending"},
            {"$set": {"status": "approved", "approved_at": datetime.datetime.utcnow().isoformat()}}
        )
        if result.modified_count > 0:
            # Insert into baatchit_user_map (bidirectional for easy lookup)
            db.baatchit_user_map.insert_one({
                "user_comman_id": to_user,  # the one who approved (me)
                "friend_comman_id": from_user,
                "created_at": datetime.datetime.utcnow().isoformat()
            })
            db.baatchit_user_map.insert_one({
                "user_comman_id": from_user,
                "friend_comman_id": to_user,
                "created_at": datetime.datetime.utcnow().isoformat()
            })
            return JSONResponse(content={"status": True, "message": "Request approved successfully"})
        else:
            return JSONResponse(content={"status": False, "message": "No pending request found or already processed"})

@app.get("/baatchit/requests/received")
def get_received_requests(common_id: str = Query(...)):
    """
    Returns all chat requests received by the user (to_user = my common_id),
    including sender's name and sender's common_id.
    Excludes duplicate requests from same sender.
    """
    with get_db() as db:
        # Find all requests where to_user is my common_id and status is pending
        requests = list(db.baatchit_request.find(
            {"to_user": common_id, "status": "pending"},
            {"_id": 0, "from_user": 1, "status": 1, "created_at": 1}
        ).sort("created_at", -1))

        # Use dictionary to keep only latest request from each sender
        unique_requests = {}
        for req in requests:
            from_user = req["from_user"]
            if from_user not in unique_requests:
                unique_requests[from_user] = req

        # Get sender details for unique requests
        result = []
        for from_user, req in unique_requests.items():
            sender = db.baatchit_user.find_one(
                {"user_comman_id": from_user},
                {"_id": 0, "full_name": 1, "user_comman_id": 1}
            )
            
            if sender:  # Only include if sender exists
                result.append({
                    "from_user": common_id,
                    "sender_name": sender["full_name"],
                    "sender_comman_id": sender["user_comman_id"],
                    "request_status": req.get("status"),
                    "request_created_at": req.get("created_at")
                })

        # Sort by creation time (newest first)
        result.sort(key=lambda x: x.get("request_created_at") or "", reverse=True)

    return JSONResponse(content={"status": True, "requests": result, "message": "Received requests fetched successfully"})

@app.get("/baatchit/friends")
def get_my_friends(common_id: str = Query(...)):
    """
    Returns all friends for the given user (by common_id), joined with user details.
    """
    with get_db() as db:
        # Find all friend mappings for this user
        mappings = list(db.baatchit_user_map.find({"user_comman_id": common_id}))
        friend_ids = [m["friend_comman_id"] for m in mappings]
        if not friend_ids:
            return JSONResponse(content={"status": True, "friends": []})

        # Get user details for all friends
        friends = list(db.baatchit_user.find(
            {"user_comman_id": {"$in": friend_ids}},
            {"_id": 0, "password": 0}
        ))
    return JSONResponse(content={"status": True, "friends": friends})

# ====================== MEDIA RECORDING HANDLER ======================

async def save_media_chunk(payload: dict, user_id: str):
    """
    Save audio/video chunk sent from client to MongoDB.
    Expects payload to have: call_id, chunk_data (base64), chunk_type ('audio'/'video'), timestamp
    """
    call_id = payload.get("call_id")
    chunk_data = payload.get("chunk_data")
    chunk_type = payload.get("chunk_type")
    timestamp = payload.get("timestamp") or datetime.datetime.utcnow().isoformat()

    if not call_id or not chunk_data or not chunk_type:
        logger.error(f"Invalid media chunk payload from {user_id}: {payload}")
        return

    try:
        with get_db() as db:
            db.media_chunks.insert_one({
                "call_id": call_id,
                "user_id": user_id,
                "chunk_type": chunk_type,
                "chunk_data": chunk_data,  # base64 string
                "timestamp": timestamp
            })
        logger.info(f"Saved {chunk_type} chunk for call {call_id} from {user_id} at {timestamp}")
    except Exception as e:
        logger.error(f"Failed to save media chunk: {e}")
