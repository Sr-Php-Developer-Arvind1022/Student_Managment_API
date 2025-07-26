from fastapi import FastAPI, Request, Body
from pydantic import BaseModel
from SuperAdmin import Api as superadmin_api
from SuperAdmin.Api import super_admin_login, SuperAdminLoginRequest
from Admin.Api import admin_login
from Admin.Api import AdminLoginRequest, AdminLoginRequest
from Admin import Api as admin_api
from Student import Api as student_api
from fastapi.middleware.cors import CORSMiddleware
from websocket_demo import app as websocket_app
from db import get_db
from call import app as call_app

app = FastAPI()
origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],              # 👈 List of allowed origins
    allow_credentials=True,
    allow_methods=["*"],              # 👈 Allow all methods like GET, POST
    allow_headers=["*"],              # 👈 Allow all headers
)

@app.get("/")
def read_root():
    return {"message": "Student Management API is running."}

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
def login(request: LoginRequest):
    # Here you would check the username and password against your database or authentication service
    print("Login API is working.")
    # Dummy logic: always return success for demonstration
    return {"status": True, "message": "Login successfully"}

@app.post("/superadmin/login-direct")
def superadmin_login_direct(request: SuperAdminLoginRequest):
    return super_admin_login(request)
#longin API for super admin 
@app.post("admin/login")
def admin_login(request: LoginRequest):
    return admin_login(request)

app.include_router(admin_api.router)
app.include_router(student_api.router)
app.mount("/ws-demo", websocket_app)
app.mount("/call", call_app)
# Student registration API
# @app.post("/student/register")  
# def student_register(name: str = Body(...), email: str = Body(...), password: str = Body(...)):
#     return student_api.register_student({"name": name, "email": email, "password": password})
# main.py
# Entry point for the Student Management API

def main():
    print("Student Management API is running.")
# Main entry point
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))  # Use Render's PORT or default to 10000 locally
    uvicorn.run(app, host="0.0.0.0", port=port)
