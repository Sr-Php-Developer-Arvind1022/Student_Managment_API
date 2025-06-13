from pydantic import BaseModel
from fastapi import APIRouter
from db import get_db

router = APIRouter()

class AdminLoginRequest(BaseModel):
    username: str
    password: str

@router.post("/admin/login")
def admin_login(request: AdminLoginRequest):
    with get_db() as db:
        user = db.admins.find_one({"email": request.username, "password_hash": request.password})
        if user:
            print("Admin Login API is working.")
            return {"status": True, "message": "Login successfully"}
    print("Admin Login API is working.")
    return {"status": False, "message": "Invalid Admin credentials"}
