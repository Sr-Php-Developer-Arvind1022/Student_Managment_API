# Assuming this is in your websocket_demo.py or websocket_routes.py
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from db import get_db
import json
import logging
import datetime
import uuid
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
    full_name: str = Query(None),
    email: str = Query(None),
    mobile_number: str = Query(None)
):
    query = {}
    if full_name:
        query["full_name"] = {"$regex": full_name, "$options": "i"}
    if email:
        query["email"] = email
    if mobile_number:
        query["mobile_number"] = mobile_number
    with get_db() as db:
        users = list(db.baatchit_user.find(query, {"_id": 0, "password": 0}))
    return JSONResponse(content={"status": True, "users": users})

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
            {"from_user": from_user, "to_user": to_user, "status": "pending"},
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
