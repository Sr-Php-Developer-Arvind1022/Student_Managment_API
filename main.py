from fastapi import FastAPI, Request, Body
from pydantic import BaseModel

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Student Management API is running."}

class LoginRequest(BaseModel):
    username: str
    password: str

# Student registration API
# @app.post("/student/register")  
# def student_register(name: str = Body(...), email: str = Body(...), password: str = Body(...)):
#     return student_api.register_student({"name": name, "email": email, "password": password})
# main.py
# Entry point for the Student Management API

def main():
    print("Student Management API is running.")

if __name__ == "__main__":
    main()
