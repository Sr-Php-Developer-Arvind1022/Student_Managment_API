from pydantic import BaseModel
from fastapi import APIRouter, Body,Query
from db import get_db
import re
import uuid

router = APIRouter()

class StudentCreateRequest(BaseModel):
    email: str
    password_hash: str
    first_name: str
    middle_name: str | None = None
    last_name: str
    dob: str
    gender: str
    contact_number: str
    blood_group: str | None = None
    nationality: str | None = None

@router.post("/student/register")
def register_student(request: dict = Body(...)):
    # Extract all fields from request
    name = request.get('name')
    email = request.get('email')
    password = request.get('password')
    first_name = request.get('first_name')
    middle_name = request.get('middle_name')
    last_name = request.get('last_name')
    dob = request.get('dob')
    gender = request.get('gender')
    contact_number = request.get('contact_number')
    blood_group = request.get('blood_group')
    nationality = request.get('nationality')
    common_id = str(uuid.uuid4())
    # Validation for empty fields
    if not name or not email or not password:
        return {"status": False, "message": "Name, email, and password are required"}
    # Clean up name if it contains both email and password
    if isinstance(name, str) and name.startswith("email=") and "password_hash=" in name:
        email_match = re.search(r"email='([^']+)'", name)
        password_match = re.search(r"password_hash='([^']+)'", name)
        if email_match and password_match:
            email = email_match.group(1)
            password = password_match.group(1)
            name = email.split('@')[0].capitalize()
    with get_db() as db:
        # Check if email exists in login_table
        if db.login_table.find_one({"email": email}):
            return {"status": False, "message": "Email already exists in login_table"}
        # Check if student already exists
        if db.students.find_one({"email": email}):
            return {"status": False, "message": "Student already exists"}
        # Insert login info in login_table
        db.login_table.insert_one({
            "name": name,
            "email": email,
            "password_hash": password,
            "common_id": common_id
        })
        # Insert all other details in students table
        db.students.insert_one({
            "email": email,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "dob": dob,
            "gender": gender,
            "contact_number": contact_number,
            "blood_group": blood_group,
            "nationality": nationality,
            "common_id": common_id
        })
        print("Student registration API is working.")
        return {"status": True, "message": "Student registered successfully"}
    
# @router.get("/student/{email}")
# def get_student(email: str):
#     with get_db() as db:
#         login_data = db.login_table.find_one({"email": email}, {"_id": 0})
#         student_data = db.students.find_one({"email": email}, {"_id": 0})
#         if not login_data and not student_data:
#             return {"status": False, "message": "Student not found"}
#         result = {"login": login_data, "student": student_data}
#         return {"status": True, "data": result}

@router.get("/students/studentsDetails")
def get_all_students():
    with get_db() as db:
        # Fetch all records from both collections
        login_cursor = db.login_table.find({}, {"_id": 0})
        student_cursor = db.students.find({}, {"_id": 0})

        login_data = list(login_cursor)
        student_data = list(student_cursor)

        students = []
        for login in login_data:
            common_id = login.get("common_id")
            if not common_id:
                continue  # Skip if common_id is missing

            # Match student by common_id
            student = next(
                (s for s in student_data if s.get("common_id") == common_id),
                None
            )
            if student:
                merged = {**login, **student}
                students.append(merged)

        if not students:
            return {"status": False, "message": "Student not found"}
        return {"status": True, "data": students}

@router.get("/student/details")
def get_student_details(
    common_id: str = Query(None),
    email: str = Query(None),
    contact_number: str = Query(None)
):
    with get_db() as db:
        student = None

        # Match by common_id
        if common_id:
            student = db.students.find_one({"common_id": common_id}, {"_id": 0})

        # Match by email
        elif email:
            student = db.students.find_one({"email": email}, {"_id": 0})

        # Match by contact number
        elif contact_number:
            student = db.students.find_one({"contact_number": contact_number}, {"_id": 0})

        if not student:
            return {"status": False, "message": "Student not found"}

        # Get login data using common_id
        login = db.login_table.find_one({"common_id": student["common_id"]}, {"_id": 0})

        # Merge both if found
        merged = {**login, **student} if login else student

        return {"status": True, "data": merged}
@router.post("/student/login")
def studentLogin(
    email: str = Body(...),
    password: str = Body(...)
):
    with get_db() as db:
        # Find login by email and password
        login = db.login_table.find_one({
            "email": email.strip().lower(),
            "password_hash": password
        }, {"_id": 0})

        if not login:
            return {"status": False, "message": "Invalid email or password"}

        # Get student by common_id
        common_id = login.get("common_id")
        student = db.students.find_one({"common_id": common_id}, {"_id": 0})

        # Merge if student exists
        merged = {**login, **student} if student else login

        return {"status": True, "data": merged}
@router.post("/quiz/add-question")
def addQuizeQuestion(
    question: str = Body(...),
    options: list = Body(...),
    correct_option: str = Body(...)
):
    if len(options) != 4:
        return {"status": False, "message": "You must provide exactly 4 options."}

    if correct_option not in options:
        return {"status": False, "message": "Correct option must be one of the 4 options."}
    common_id = str(uuid.uuid4())
    quiz_data = {
        "question": question,
        "options": options,
        "correct_option": correct_option,
        "common_id": common_id
    }

    with get_db() as db:
        db.quiz_questions.insert_one(quiz_data)

    return {"status": True, "message": "Question added successfully"}
@router.get("/quiz/all-questions")
def getAllQuizQuestions():
    with get_db() as db:
        cursor = db.quiz_questions.find({}, {"_id": 0})
        questions = list(cursor)

        if not questions:
            return {"status": False, "message": "No quiz questions found"}

        return {"status": True, "data": questions}
@router.post("/quiz/submit-answers")
def submitMultipleQuizAnswers(
    student_common_id: str = Body(...),
    answers: list = Body(...)
):
    with get_db() as db:
        # ❌ Check if student already submitted any answer
        existing = db.quiz_answers.find_one({"student_common_id": student_common_id})
        if existing:
            return {
                "status": False,
                "message": "You have already submitted your answers. Multiple attempts are not allowed."
            }

        inserted = []

        for answer in answers:
            common_id = answer.get("common_id")
            question = answer.get("question")
            selected_option = answer.get("selected_option")

            if not (common_id and question and selected_option):
                continue  # Skip incomplete entries

            quiz = db.quiz_questions.find_one({"question": question})
            if not quiz:
                continue  # Skip if question not found

            is_correct = selected_option == quiz.get("correct_option")

            db.quiz_answers.insert_one({
                "student_common_id": student_common_id,
                "common_id": common_id,
                "question": question,
                "selected_option": selected_option,
                "is_correct": is_correct
            })

            inserted.append({
                "question": question,
                "correct": is_correct
            })

        return {
            "status": True,
            "message": "Answers submitted successfully",
            "data": inserted
        }
@router.get("/quiz/student-result")
def getStudentQuizResult(common_id: str):
    with get_db() as db:
        answers = list(db.quiz_answers.find({"student_common_id": common_id}))

        if not answers:
            return {"status": False, "message": "No answers found for this student"}

        total_attempts = len(answers)
        correct_count = sum(1 for ans in answers if ans.get("is_correct"))

        return {
            "status": True,
            "common_id": common_id,
            "total_attempted": total_attempts,
            "correct_answers": correct_count,
            "wrong_answers": total_attempts - correct_count
        }


