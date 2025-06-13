from pymongo import MongoClient
from contextlib import contextmanager

MONGO_URI = 'mongodb+srv://ky721682:123456789$Vv@student.jswvayy.mongodb.net/'
DB_NAME = 'StudentManagementDb'

@contextmanager
def get_db():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    try:
        yield db
    finally:
        client.close()

# Insert default admin if not exists
with get_db() as db:
    if db.admins.count_documents({'email': 'admin@example.com'}) == 0:
        db.admins.insert_one({
            'name': 'Admin',
            'email': 'admin@example.com',
            'password_hash': 'admin@123'
        })
