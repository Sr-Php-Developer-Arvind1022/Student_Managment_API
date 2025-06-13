from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn
import os

app = FastAPI()

# Root endpoint
@app.get("/")
async def read_root():
    return {"message": "Student Management API is running."}

# Pydantic models
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

# Placeholder for student_api (replace with actual implementation)
class StudentAPI:
    @staticmethod
    def register_student(data: dict):
        # Replace with actual registration logic (e.g., save to database)
        return {"status": "success", "data": data}


# Main entry point
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))  # Use Render's PORT or default to 10000 locally
    uvicorn.run(app, host="0.0.0.0", port=port)
