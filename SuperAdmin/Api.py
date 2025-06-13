from pydantic import BaseModel
from fastapi import APIRouter
from db import get_db

router = APIRouter()

class SuperAdminLoginRequest(BaseModel):
    username: str
    password: str

@router.post("/superadmin/login")
def super_admin_login(request: SuperAdminLoginRequest):
    with get_db() as db:
        user = db.super_admins.find_one({"email": request.username, "password_hash": request.password})
        if user:
            print("SuperAdmin Login API is working.")
            return {"status": True, "message": "Login successfully"}
    print("SuperAdmin Login API is working.")
    return {"status": False, "message": "Invalid SuperAdmin credentials"}
