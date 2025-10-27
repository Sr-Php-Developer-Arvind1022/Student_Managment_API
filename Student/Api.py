from collections import defaultdict
from pydantic import BaseModel
from fastapi import APIRouter,  Body,Query, Form
from db import get_db
import re
import uuid
from datetime import datetime,timedelta

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
        # Use index on 'common_id'
        login_cursor = db.login_table.find({}, {"_id": 0}).hint("common_id_1")
        student_cursor = db.students.find({}, {"_id": 0}).hint("common_id_1")

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

        # Use index on 'common_id', 'email', 'contact_number'
        if common_id:
            student = db.students.find_one({"common_id": common_id}, {"_id": 0}, hint="common_id_1")
        elif email:
            student = db.students.find_one({"email": email}, {"_id": 0}, hint="email_1")
        elif contact_number:
            student = db.students.find_one({"contact_number": contact_number}, {"_id": 0}, hint="contact_number_1")

        if not student:
            return {"status": False, "message": "Student not found"}

        login = db.login_table.find_one({"common_id": student["common_id"]}, {"_id": 0}, hint="common_id_1")
        merged = {**login, **student} if login else student

        return {"status": True, "data": merged}

@router.post("/student/login")
def studentLogin(
    email: str = Body(...),
    password: str = Body(...)
):
    with get_db() as db:
        # Remove hint if index may not exist, or ensure index is created with the correct name
        login = db.login_table.find_one(
            {"email": email.strip().lower(), "password_hash": password},
            {"_id": 0}
        )

        if not login:
            return {"status": False, "message": "Invalid email or password"}

        # Use index on 'common_id' for faster lookup (safe, as created in startup)
        common_id = login.get("common_id")
        student = db.students.find_one({"common_id": common_id}, {"_id": 0}, hint="common_id_1")

        merged = {**login, **student} if student else login

        return {"status": True, "data": merged}
@router.post("/quiz/add-question")
def addQuizeQuestion(
    question: str = Body(...),
    options: list = Body(...),
    correct_option: str = Body(...),
    course_id: str = Body(...)
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
        "common_id": common_id,
        "course_id" : course_id
    }

    with get_db() as db:
        db.quiz_questions.insert_one(quiz_data)

    return {"status": True, "message": "Question added successfully"}
@router.get("/quiz/all-questions")
def getAllQuizQuestions():
    with get_db() as db:
        # Use index on 'question'
        cursor = db.quiz_questions.find({}, {"_id": 0}).hint("question_1")
        questions = list(cursor)

        if not questions:
            return {"status": False, "message": "No quiz questions found"}

        return {"status": True, "data": questions}
# @router.post("/quiz/all-questions")
# def getAllQuizQuestions(course_id: str = Body(None), course_id_form: str = Form(None)):
#     # choose form value first (for multipart/form-data), then json body
#     raw = course_id_form or course_id

#     # helper to clean multipart/form-data garbage if present
#     def _extract_id(s: str | None) -> str | None:
#         if not s:
#             return None
#         if "Content-Disposition" not in s and "----" not in s:
#             return s.strip()
#         # try to capture the value that appears after the blank line following Content-Disposition
#         m = re.search(r'name="course_id"[\s\S]*?\r\n\r\n(.*?)\r\n', s, re.S)
#         if m:
#             return m.group(1).strip()
#         # fallback: remove boundary and disposition lines and pick the last non-empty remainder
#         lines = [ln.strip() for ln in s.splitlines() if ln.strip() and "Content-Disposition" not in ln and not ln.startswith("----") and "name=" not in ln and not ln.lower().startswith("content-type:")]
#         if lines:
#             return lines[-1].strip()
#         # final fallback
#         return s.strip()

#     cleaned_course_id = _extract_id(raw)
#     print("Course ID received (cleaned):", cleaned_course_id)
#     print("Type:", type(cleaned_course_id))

#     with get_db() as db:
#         # First, let's see what course_ids actually exist
#         all_courses = db.quiz_questions.distinct("course_id")
#         print("Available course_ids:", all_courses)

#         cursor = db.quiz_questions.find({"course_id": cleaned_course_id}, {"_id": 0})
#         questions = list(cursor)

#         if not questions:
#             return {
#                 "status": False,
#                 "message": "No quiz questions found for this course",
#                 "debug": {
#                     "received_course_id": cleaned_course_id,
#                     "available_course_ids": all_courses
#                 }
#             }

#         return {"status": True, "data": questions}
@router.post("/quiz/submit-answers")
def submitMultipleQuizAnswers(
    student_common_id: str = Body(...),
    answers: list = Body(...)
):
    with get_db() as db:
        today = datetime.now()
        start_of_day = datetime(today.year, today.month, today.day)
        end_of_day = start_of_day + timedelta(days=1)
        existing = db.quiz_answers.find_one({
            "student_common_id": student_common_id,
            "quize_date": {"$gte": start_of_day, "$lt": end_of_day}
        })
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

            # Actually insert only if all fields are valid
            result = db.quiz_answers.insert_one({
                "student_common_id": student_common_id,
                "common_id": common_id,
                "question": question,
                "selected_option": selected_option,
                "is_correct": is_correct,
                "quize_date": today
            })

            # Only append if insert was acknowledged
            if result.acknowledged:
                inserted.append({
                    "question": question,
                    "correct": is_correct
                })

        if inserted:
            return {
                "status": True,
                "message": "Answers submitted successfully",
                "data": inserted
            }
        else:
            return {
                "status": False,
                "message": "Please check your answers. No valid answers to submit."
            }
@router.get("/quiz/student-result")
def getStudentQuizResult(common_id: str):
    with get_db() as db:
        answers = list(db.quiz_answers.find({
            "student_common_id": common_id
        }).hint([("student_common_id", 1), ("quize_date", 1)]))

        if not answers:
            return {"status": False, "message": "No answers found for this student"}

        grouped_results = defaultdict(list)
        date_stats = defaultdict(lambda: {"correct": 0, "wrong": 0, "total": 0})
        total_attempts = 0
        correct_count = 0

        for ans in answers:
            question = db.quiz_questions.find_one({"question": ans.get("question")})
            if question:
                quize_date = ans.get("quize_date")
                if isinstance(quize_date, datetime):
                    date_key = quize_date.strftime("%Y-%m-%d")
                else:
                    try:
                        quize_date = datetime.fromisoformat(quize_date)
                        date_key = quize_date.strftime("%Y-%m-%d")
                    except:
                        date_key = "unknown"

                result_item = {
                    "question_id": str(question.get("_id")),
                    "question": question.get("question"),
                    "options": question.get("options"),
                    "correct_option": question.get("correct_option"),
                    "selected_option": ans.get("selected_option"),
                    "is_correct": ans.get("is_correct"),
                    "answered_at": quize_date
                }

                grouped_results[date_key].append(result_item)
                total_attempts += 1
                date_stats[date_key]["total"] += 1

                if ans.get("is_correct"):
                    correct_count += 1
                    date_stats[date_key]["correct"] += 1
                else:
                    date_stats[date_key]["wrong"] += 1

        grouped_results = dict(grouped_results)
        date_wise_stats = {
            date: {
                "total_attempts": stats["total"],
                "correct_answers": stats["correct"],
                "wrong_answers": stats["wrong"]
            }
            for date, stats in date_stats.items()
        }

        performance_percentage = (correct_count / total_attempts) * 100 if total_attempts > 0 else 0

        if performance_percentage >= 85:
            performance_category = "Excellent"
        elif performance_percentage >= 60:
            performance_category = "Good"
        else:
            performance_category = "Bad"

        return {
            "status": True,
            "common_id": common_id,
            "total_attempted": total_attempts,
            "correct_answers": correct_count,
            "wrong_answers": total_attempts - correct_count,
            "performance_percentage": round(performance_percentage, 2),
            "performance_category": performance_category,
            "date_wise": date_wise_stats,
            "grouped_data": grouped_results
        }
@router.on_event("startup")
def create_indexes():
    # Optimize queries by adding indexes
    with get_db() as db:
        db.students.create_index("common_id")
        db.students.create_index("email")
        db.quiz_questions.create_index("question")
        db.quiz_answers.create_index([("student_common_id", 1), ("quize_date", 1)])
        db.quiz_answers.create_index("question")

@router.get("/students/all")
def get_all_students_fast():
    with get_db() as db:
        # Use index on 'common_id'
        students = list(db.students.find({}, {"_id": 0}).hint("common_id_1"))
        return {"status": True, "data": students} if students else {"status": False, "message": "No students found"}

@router.get("/quizzes/all")
def get_all_quizzes_fast():
    with get_db() as db:
        # Use index on 'question'
        quizzes = list(db.quiz_questions.find({}, {"_id": 0}).hint("question_1"))
        return {"status": True, "data": quizzes} if quizzes else {"status": False, "message": "No quizzes found"}
@router.put("/quiz/update-question")
def update_quiz_question(
    common_id: str = Body(...),
    question: str = Body(None),
    options: list = Body(None),
    correct_option: str = Body(None)
):
    with get_db() as db:
        update_fields = {}
        if question is not None:
            update_fields["question"] = question
        if options is not None:
            update_fields["options"] = options
        if correct_option is not None:
            update_fields["correct_option"] = correct_option

        if not update_fields:
            return {"status": False, "message": "No fields to update."}

        result = db.quiz_questions.update_one(
            {"common_id": common_id},
            {"$set": update_fields}
        )

        if result.matched_count == 0:
            return {"status": False, "message": "No question found with the given common_id."}
        if result.modified_count == 0:
            return {"status": True, "message": "No changes made (data may be identical)."}

        return {"status": True, "message": "Question updated successfully."}
@router.get("/quiz/question-by-id")
def get_question_by_id(common_id: str = Query(...)):
    with get_db() as db:
        question = db.quiz_questions.find_one({"common_id": common_id}, {"_id": 0})
        if not question:
            return {"status": False, "message": "No question found with the given common_id."}
        return {"status": True, "data": question}


