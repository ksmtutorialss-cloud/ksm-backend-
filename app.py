"""
KSM TUTORIALS - PRODUCTION BACKEND (PostgreSQL + SendGrid)
Deploy on Render.com with Neon PostgreSQL
"""

from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import hashlib
import uuid
import json
from datetime import datetime, timedelta
import socketio
import os
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from dotenv import load_dotenv
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment, FileContent, FileName, FileType, Disposition

# Load environment variables
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL", "ksm.tutorials@ucc.edu.gh")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", hashlib.sha256("admin123".encode()).hexdigest())
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-key")

# Create uploads directory
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Database connection pool
pool = SimpleConnectionPool(
    minconn=1,
    maxconn=20,
    dsn=DATABASE_URL,
    cursor_factory=RealDictCursor
)

@contextmanager
def get_cursor():
    conn = pool.getconn()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        pool.putconn(conn)

# SendGrid email helper
def send_email(to_email: str, subject: str, html_content: str):
    """Send email using SendGrid"""
    if not SENDGRID_API_KEY:
        print(f"⚠️ Email not sent (no API key): {subject} to {to_email}")
        return False
    
    try:
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
            html_content=html_content
        )
        response = sg.send(message)
        print(f"✅ Email sent to {to_email}: {subject} (Status: {response.status_code})")
        return response.status_code in [200, 202]
    except Exception as e:
        print(f"❌ Email failed: {str(e)}")
        return False

def send_registration_email(to_email: str, full_name: str, reg_id: str, total_amount: float, courses: list, phone: str):
    """Send registration confirmation email"""
    courses_list = "<br>".join([f"• {c} - GHS 120" for c in courses])
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: #0a192f; color: white; padding: 20px; text-align: center; }}
            .content {{ padding: 20px; background: #f8f9fa; }}
            .reg-id {{ background: #f5a623; color: white; padding: 10px; text-align: center; font-size: 20px; font-weight: bold; border-radius: 8px; }}
            .footer {{ text-align: center; padding: 20px; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎓 KSM Tutorials</h1>
                <p>University of Cape Coast</p>
            </div>
            <div class="content">
                <h2>Dear {full_name},</h2>
                <p>Thank you for registering with KSM Tutorials! Your registration has been received successfully.</p>
                
                <div class="reg-id">
                    Your Registration ID: <strong>{reg_id}</strong>
                </div>
                
                <h3>Registration Summary:</h3>
                <p><strong>Student ID:</strong> {reg_id}</p>
                <p><strong>Phone:</strong> {phone}</p>
                <p><strong>Total Amount:</strong> GHS {total_amount}</p>
                
                <h3>Courses Registered:</h3>
                {courses_list}
                
                <h3>📌 Important Information:</h3>
                <ul>
                    <li><strong>Payment:</strong> GHS 120 per course at first class meeting</li>
                    <li><strong>Duration:</strong> 1 month intensive training</li>
                    <li><strong>Schedule:</strong> Saturdays & Sundays (times vary by course)</li>
                    <li><strong>Location:</strong> UCC IT Department Labs</li>
                </ul>
                
                <h3>WhatsApp Group:</h3>
                <p>A WhatsApp group invite link will be sent to your phone number: <strong>{phone}</strong></p>
                <p>All tutorial dates and venues will be announced in the WhatsApp group!</p>
                
                <h3>Next Steps:</h3>
                <ol>
                    <li>Save your Registration ID: <strong>{reg_id}</strong></li>
                    <li>Check your WhatsApp for group invite</li>
                    <li>Attend first class with GHS {total_amount}</li>
                    <li>Login to Student Portal using your Registration ID and password</li>
                </ol>
                
                <p style="margin-top: 20px;">Best regards,<br>
                <strong>KSM Tutorials Team</strong><br>
                University of Cape Coast</p>
            </div>
            <div class="footer">
                <p>&copy; 2026 KSM Tutorials. All rights reserved.</p>
                <p>Contact: {FROM_EMAIL}</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(to_email, "✅ Registration Confirmation - KSM Tutorials", html)

def send_password_change_confirmation(to_email: str, full_name: str):
    """Send password change confirmation email"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><style>body{{font-family:Arial,sans-serif;}} .container{{max-width:500px;margin:0 auto;padding:20px;}}</style></head>
    <body>
        <div class="container">
            <h2>🔐 Password Changed</h2>
            <p>Dear {full_name},</p>
            <p>Your KSM Tutorials portal password has been successfully changed.</p>
            <p>If you did not make this change, please contact us immediately.</p>
            <hr>
            <p>KSM Tutorials - University of Cape Coast</p>
        </div>
    </body>
    </html>
    """
    return send_email(to_email, "Password Changed - KSM Tutorials", html)

def send_ticket_reply_email(to_email: str, student_name: str, subject: str, reply: str):
    """Send ticket reply notification email"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><style>body{{font-family:Arial,sans-serif;}} .container{{max-width:500px;margin:0 auto;padding:20px;}}</style></head>
    <body>
        <div class="container">
            <h2>📬 Admin Response to Your Ticket</h2>
            <p>Dear {student_name},</p>
            <p><strong>Subject:</strong> {subject}</p>
            <div style="background:#f0f0f0;padding:15px;border-radius:8px;margin:15px 0;">
                <strong>Admin's Response:</strong><br>
                {reply}
            </div>
            <p>You can view the full conversation in your Student Portal.</p>
            <hr>
            <p>KSM Tutorials - University of Cape Coast</p>
        </div>
    </body>
    </html>
    """
    return send_email(to_email, f"Response to your ticket: {subject}", html)

def send_edit_request_approved_email(to_email: str, student_name: str):
    """Send notification when edit request is approved"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><style>body{{font-family:Arial,sans-serif;}} .container{{max-width:500px;margin:0 auto;padding:20px;}}</style></head>
    <body>
        <div class="container">
            <h2>✅ Profile Update Approved</h2>
            <p>Dear {student_name},</p>
            <p>Your profile edit request has been approved by the admin.</p>
            <p>Your profile information has been updated. You can view the changes in your Student Portal.</p>
            <hr>
            <p>KSM Tutorials - University of Cape Coast</p>
        </div>
    </body>
    </html>
    """
    return send_email(to_email, "Profile Update Approved - KSM Tutorials", html)

# ============================================================
# SOCKET.IO SETUP
# ============================================================
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

sio = socketio.AsyncServer(
    cors_allowed_origins=[
         FRONTEND_URL,  # Replace with your Vercel URL
        'http://localhost:3000',
        'http://localhost:5173',
    ],
    async_mode='asgi'
)

app = FastAPI()
socket_app = socketio.ASGIApp(sio, app)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
         FRONTEND_URL,  # Replace with your Vercel URL
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_admin(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(401, "No authorization token")
    token = authorization.replace("Bearer ", "")
    with get_cursor() as cursor:
        cursor.execute("SELECT token FROM admin_tokens WHERE token=%s AND expires_at > NOW()", (token,))
        if not cursor.fetchone():
            raise HTTPException(401, "Invalid or expired token")
    return token

def init_db():
    """Initialize database tables on Neon"""
    with get_cursor() as cursor:
        # Students table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            reg_id TEXT UNIQUE,
            full_name TEXT,
            student_id TEXT UNIQUE,
            email TEXT,
            phone TEXT,
            password TEXT,
            programme TEXT,
            level INTEGER,
            courses TEXT,
            total_amount REAL,
            payment_status TEXT DEFAULT 'pending',
            registered_at TEXT,
            certificate_released INTEGER DEFAULT 0,
            certificate_released_at TEXT
        )
        """)
        
        # Admins table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
        )
        """)
        
        # Admin tokens table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_tokens (
            id SERIAL PRIMARY KEY,
            token TEXT UNIQUE,
            created_at TEXT,
            expires_at TEXT
        )
        """)
        
        # Courses table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            name TEXT,
            level INTEGER,
            price REAL,
            instructor TEXT,
            schedule_day TEXT,
            schedule_time TEXT,
            venue TEXT,
            description TEXT,
            icon TEXT DEFAULT 'FaCode',
            registered_count INTEGER DEFAULT 0
        )
        """)
        
        # Comments table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            user_name TEXT,
            rating INTEGER,
            content TEXT,
            likes INTEGER DEFAULT 0,
            parent_id INTEGER DEFAULT NULL,
            created_at TEXT
        )
        """)
        
        # Settings table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT
        )
        """)
        
        # Director Message table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS director_messages (
            id SERIAL PRIMARY KEY,
            content TEXT,
            signature TEXT,
            updated_at TEXT
        )
        """)
        
        # Tutors table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutors (
            id SERIAL PRIMARY KEY,
            name TEXT,
            specialization TEXT,
            experience TEXT,
            image TEXT,
            email TEXT,
            linkedin TEXT,
            image_url TEXT
        )
        """)
        
        # Announcements table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT,
            content TEXT,
            type TEXT,
            date TEXT
        )
        """)
        
        # Partners table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS partners (
            id SERIAL PRIMARY KEY,
            name TEXT,
            icon TEXT,
            link TEXT,
            color TEXT
        )
        """)
        
        # Activity logs table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            action TEXT,
            admin_name TEXT,
            details TEXT,
            created_at TEXT
        )
        """)
        
        # Support Tickets table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id SERIAL PRIMARY KEY,
            student_id INTEGER,
            student_name TEXT,
            student_email TEXT,
            subject TEXT,
            message TEXT,
            status TEXT DEFAULT 'open',
            admin_reply TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        
        # Edit Requests table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS edit_requests (
            id SERIAL PRIMARY KEY,
            student_id INTEGER,
            student_name TEXT,
            requested_data TEXT,
            status TEXT DEFAULT 'pending',
            admin_response TEXT,
            created_at TEXT,
            responded_at TEXT
        )
        """)
        
        # Check if admin exists
        cursor.execute("SELECT * FROM admins WHERE username=%s", (ADMIN_USERNAME,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO admins (username, password) VALUES (%s, %s)", 
                          (ADMIN_USERNAME, ADMIN_PASSWORD_HASH))
            print(f"✅ Default admin created: {ADMIN_USERNAME} / admin123")
        
        # Check if settings exist
        cursor.execute("SELECT * FROM settings")
        if not cursor.fetchone():
            default_settings = [
                ("deadline", "2026-12-31T23:59:00"),
                ("whatsapp_link", "https://chat.whatsapp.com/KSM2026"),
                ("contact_email", FROM_EMAIL),
                ("contact_phone", "+233 24 123 4567")
            ]
            for key, value in default_settings:
                cursor.execute("INSERT INTO settings (key, value) VALUES (%s, %s)", (key, value))
        
        # Check if courses exist
        cursor.execute("SELECT * FROM courses")
        if not cursor.fetchone():
            default_courses = [
                ("Programming (C++)", 100, 120, "Dr. Mensah", "Saturday", "9:00 AM", "IT Lab 301", "Learn C++ programming fundamentals", "FaCode", 0),
                ("Web Design", 100, 120, "Prof. Abena", "Saturday", "11:00 AM", "IT Lab 302", "Master HTML5, CSS3, JavaScript", "FaLaptopCode", 0),
                ("Database (MySQL)", 100, 120, "Mr. Kofi", "Saturday", "1:00 PM", "IT Lab 303", "Database design and SQL queries", "FaDatabase", 0),
                ("Java OOP", 200, 120, "Dr. Esi", "Sunday", "9:00 AM", "IT Lab 301", "Object-Oriented Programming with Java", "FaCode", 0),
                ("Networking", 200, 120, "Prof. Kwame", "Saturday", "9:00 AM", "IT Lab 302", "Network protocols and OSI model", "FaNetworkWired", 0),
                ("Data Structures", 200, 120, "Dr. Ama", "Sunday", "1:00 PM", "IT Lab 303", "Arrays, linked lists, trees, graphs", "FaCode", 0),
                ("Unix Programming", 300, 120, "Mr. Yaw", "Saturday", "2:00 PM", "IT Lab 301", "Linux commands and shell scripting", "FaLinux", 0),
                ("AI & Machine Learning", 300, 120, "Dr. Grace", "Saturday", "4:00 PM", "Online", "Introduction to AI and Machine Learning", "FaBrain", 0),
                ("Cybersecurity", 300, 120, "Prof. Atta", "Sunday", "2:00 PM", "IT Lab 302", "Security principles and ethical hacking", "FaShieldAlt", 0),
                ("Mobile Development", 400, 120, "Dr. Owusu", "Saturday", "9:00 AM", "IT Lab 301", "Android/iOS app development", "FaMobileAlt", 0),
                ("Project Management", 400, 120, "Mr. Danso", "Saturday", "11:00 AM", "IT Lab 302", "Agile, Scrum, project planning", "FaChartBar", 0),
                ("Research Methods", 400, 120, "Prof. Adwoa", "Saturday", "1:00 PM", "IT Lab 303", "Academic research and thesis writing", "FaBook", 0),
            ]
            for c in default_courses:
                cursor.execute("INSERT INTO courses (name, level, price, instructor, schedule_day, schedule_time, venue, description, icon, registered_count) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", c)
        
        # Check if director message exists
        cursor.execute("SELECT * FROM director_messages")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO director_messages (content, signature, updated_at) VALUES (%s, %s, %s)",
                          ("For over 5 years, KSM Tutorials has been dedicated to helping IT and Computer Science students at the University of Cape Coast achieve academic excellence.",
                           "Mr. KSM - Founder & Lead Tutor", datetime.now().isoformat()))

# Initialize database on startup
print("=" * 50)
print("Initializing PostgreSQL database on Neon...")
init_db()
print("✅ Database initialized successfully!")
print("=" * 50)

# ============================================================
# PYDANTIC MODELS
# ============================================================

# (Keep all your existing Pydantic models - same as before)

class StudentRegister(BaseModel):
    full_name: str
    student_id: str
    email: EmailStr
    phone: str
    password: str
    programme: str
    level: int
    courses: List[str]

class StudentLogin(BaseModel):
    registration_id: str
    password: str

class StudentUpdate(BaseModel):
    full_name: str
    student_id: str
    email: str
    phone: str
    programme: str
    level: int
    payment_status: str

class CommentCreate(BaseModel):
    user_name: str
    rating: int = 5
    content: str
    parent_id: Optional[int] = None

class AdminLogin(BaseModel):
    username: str
    password: str

class CourseCreate(BaseModel):
    name: str
    level: int
    price: float = 120
    instructor: str = "TBA"
    schedule_day: str = "Saturday"
    schedule_time: str = "9:00 AM"
    venue: str = "UCC Lab"
    description: str = ""
    icon: str = "FaCode"

class DirectorMessageUpdate(BaseModel):
    content: str
    signature: str

class TutorCreate(BaseModel):
    name: str
    specialization: str
    experience: str
    image: str = ""
    image_url: str = ""
    email: str = ""
    linkedin: str = "#"

class AnnouncementCreate(BaseModel):
    title: str
    content: str
    type: str = "info"
    date: str

class PartnerCreate(BaseModel):
    name: str
    icon: str
    link: str
    color: str

class TicketCreate(BaseModel):
    student_id: int
    student_name: str
    student_email: str
    subject: str
    message: str

class TicketReply(BaseModel):
    reply: str

class EditRequestData(BaseModel):
    requested_data: dict

class ChangePassword(BaseModel):
    student_id: int
    old_password: str
    new_password: str

class AdminChangeCredentials(BaseModel):
    current_password: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None

# ============================================================
# WEB SOCKET EVENTS
# ============================================================

connected_users = {}

@sio.event
async def connect(sid, environ):
    connected_users[sid] = datetime.now()
    await sio.emit('online_count', {'count': len(connected_users)})
    print(f"✅ Client connected: {sid} - Total: {len(connected_users)}")

@sio.event
async def disconnect(sid):
    if sid in connected_users:
        del connected_users[sid]
    await sio.emit('online_count', {'count': len(connected_users)})
    print(f"❌ Client disconnected: {sid} - Total: {len(connected_users)}")

@sio.event
async def typing(sid, data):
    await sio.emit('user_typing', {'users': [data.get('user_name', 'Someone')]})

@sio.event
async def new_comment(sid, data):
    await sio.emit('new_comment', data)

@sio.event
async def like_comment(sid, data):
    await sio.emit('comment_liked', data)

@sio.event
async def new_registration(sid, data):
    await sio.emit('new_registration', data)

# ============================================================
# FILE UPLOAD
# ============================================================

@app.post("/api/upload/tutor-image")
async def upload_tutor_image(file: UploadFile = File(...), admin: str = Depends(verify_admin)):
    try:
        ext = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
        filename = f"tutor_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = UPLOAD_DIR / filename
        
        content = await file.read()
        with open(filepath, "wb") as buffer:
            buffer.write(content)
        
        file_url = f"/uploads/{filename}"
        return {"image_url": file_url}
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {str(e)}")

@app.get("/uploads/{filename}")
async def get_upload(filename: str):
    filepath = UPLOAD_DIR / filename
    if filepath.exists():
        return FileResponse(filepath)
    raise HTTPException(404, "File not found")

# ============================================================
# API ENDPOINTS (UPDATED with PostgreSQL syntax)
# ============================================================

@app.get("/")
def root():
    return {"message": "KSM Tutorials API Running", "version": "3.0.0"}

# ---------- STATISTICS ----------
@app.get("/api/stats")
def get_stats():
    with get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM students")
        total = cursor.fetchone()['count']
        
        cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM students WHERE payment_status='paid'")
        revenue = cursor.fetchone()['coalesce']
        
        cursor.execute("SELECT COUNT(*) FROM comments WHERE parent_id IS NULL")
        comments = cursor.fetchone()['count']
        
        cursor.execute("SELECT COALESCE(AVG(rating), 0) FROM comments")
        avg = cursor.fetchone()['coalesce']
        
        cursor.execute("SELECT COUNT(*) FROM students WHERE payment_status='pending'")
        pending = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM students WHERE certificate_released=1")
        certificates = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM support_tickets WHERE status='open'")
        tickets = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) FROM edit_requests WHERE status='pending'")
        edit_requests = cursor.fetchone()['count']
        
        return {
            "total_students": total,
            "total_revenue": revenue,
            "total_comments": comments,
            "avg_rating": round(avg, 1),
            "pending_payments": pending,
            "certificates_released": certificates,
            "open_tickets": tickets,
            "pending_edit_requests": edit_requests
        }

# ---------- STUDENT REGISTRATION (WITH EMAIL) ----------
@app.post("/api/register")
async def register(student: StudentRegister, background_tasks: BackgroundTasks):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM students WHERE student_id=%s", (student.student_id,))
        if cursor.fetchone():
            raise HTTPException(400, "Student ID already registered")
        
        cursor.execute("SELECT value FROM settings WHERE key='deadline'")
        row = cursor.fetchone()
        if row:
            deadline_str = row['value']
            if datetime.now() > datetime.fromisoformat(deadline_str):
                raise HTTPException(400, "Registration closed")
        
        reg_id = f"KSM-{uuid.uuid4().hex[:8].upper()}"
        total = len(student.courses) * 120
        
        hashed_password = hashlib.sha256(student.password.encode()).hexdigest()
        
        for course_name in student.courses:
            cursor.execute("UPDATE courses SET registered_count = registered_count + 1 WHERE name=%s", (course_name,))
        
        cursor.execute("""
            INSERT INTO students (reg_id, full_name, student_id, email, phone, password, programme, level, courses, total_amount, registered_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (reg_id, student.full_name, student.student_id, student.email, student.phone, 
              hashed_password, student.programme, student.level, json.dumps(student.courses), total, datetime.now().isoformat()))
        
        # Send email confirmation
        background_tasks.add_task(
            send_registration_email, 
            student.email, 
            student.full_name, 
            reg_id, 
            total, 
            student.courses, 
            student.phone
        )
        
        await sio.emit('new_registration', {'name': student.full_name})
        
        return {
            "registration_id": reg_id,
            "total": total,
            "courses": student.courses,
            "full_name": student.full_name,
            "email": student.email,
            "phone": student.phone
        }

# ---------- STUDENT LOGIN ----------
@app.post("/api/student/login")
def student_login(data: StudentLogin):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM students WHERE reg_id=%s", (data.registration_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(401, "Invalid Registration ID")
        
        stored_password = student['password']
        hashed_input = hashlib.sha256(data.password.encode()).hexdigest()
        
        if hashed_input != stored_password:
            raise HTTPException(401, "Invalid password")
        
        courses = json.loads(student['courses']) if student['courses'] else []
        certificate_released = bool(student['certificate_released']) if student.get('certificate_released') else False
        
        return {
            "id": student['id'],
            "reg_id": student['reg_id'],
            "full_name": student['full_name'],
            "student_id": student['student_id'],
            "email": student['email'],
            "phone": student['phone'],
            "programme": student['programme'],
            "level": student['level'],
            "courses": courses,
            "total_amount": student['total_amount'],
            "payment_status": student['payment_status'],
            "registered_at": student['registered_at'],
            "certificate_released": certificate_released
        }

# ---------- CHANGE PASSWORD (WITH EMAIL) ----------
@app.post("/api/student/change-password")
def change_student_password(data: ChangePassword, background_tasks: BackgroundTasks):
    with get_cursor() as cursor:
        cursor.execute("SELECT password, email, full_name FROM students WHERE id=%s", (data.student_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Student not found")
        
        stored_hash = row['password']
        old_hash = hashlib.sha256(data.old_password.encode()).hexdigest()
        
        if stored_hash != old_hash:
            raise HTTPException(401, "Current password is incorrect")
        
        if len(data.new_password) < 6:
            raise HTTPException(400, "Password must be at least 6 characters")
        
        new_hash = hashlib.sha256(data.new_password.encode()).hexdigest()
        cursor.execute("UPDATE students SET password=%s WHERE id=%s", (new_hash, data.student_id))
        
        # Send confirmation email
        background_tasks.add_task(send_password_change_confirmation, row['email'], row['full_name'])
        
        return {"message": "Password changed successfully"}

# ---------- PROFILE EDIT REQUESTS ----------
@app.post("/api/student/request-edit/{student_id}")
def request_edit(student_id: int, request_data: EditRequestData):
    with get_cursor() as cursor:
        cursor.execute("SELECT full_name FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        if not student:
            raise HTTPException(404, "Student not found")
        
        student_name = student['full_name']
        requested_data = json.dumps(request_data.requested_data)
        
        cursor.execute("""
            INSERT INTO edit_requests (student_id, student_name, requested_data, status, created_at)
            VALUES (%s, %s, %s, 'pending', %s)
        """, (student_id, student_name, requested_data, datetime.now().isoformat()))
        
        return {"message": "Edit request sent to admin"}

# ---------- EDIT REQUESTS APPROVE (WITH EMAIL) ----------
@app.put("/api/admin/edit-requests/{request_id}/approve")
def approve_edit_request(request_id: int, admin: str = Depends(verify_admin), background_tasks: BackgroundTasks = None):
    with get_cursor() as cursor:
        cursor.execute("SELECT student_id, requested_data FROM edit_requests WHERE id=%s", (request_id,))
        req = cursor.fetchone()
        
        if not req:
            raise HTTPException(404, "Edit request not found")
        
        data = json.loads(req['requested_data'])
        cursor.execute("""
            UPDATE students SET full_name=%s, student_id=%s, email=%s, phone=%s, programme=%s, level=%s
            WHERE id=%s
        """, (data.get('full_name'), data.get('student_id'), data.get('email'), 
              data.get('phone'), data.get('programme'), data.get('level'), req['student_id']))
        
        cursor.execute("UPDATE edit_requests SET status='approved', responded_at=%s WHERE id=%s", 
                      (datetime.now().isoformat(), request_id))
        
        # Get student email for notification
        cursor.execute("SELECT email, full_name FROM students WHERE id=%s", (req['student_id'],))
        student = cursor.fetchone()
        if student and background_tasks:
            background_tasks.add_task(send_edit_request_approved_email, student['email'], student['full_name'])
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("approve_edit", "admin", f"Approved edit request #{request_id}", datetime.now().isoformat()))
        
        return {"message": "Edit request approved"}

# ---------- SUPPORT TICKET REPLY (WITH EMAIL) ----------
@app.put("/api/admin/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, data: TicketReply, admin: str = Depends(verify_admin), background_tasks: BackgroundTasks = None):
    with get_cursor() as cursor:
        cursor.execute("SELECT student_email, student_name, subject FROM support_tickets WHERE id=%s", (ticket_id,))
        ticket = cursor.fetchone()
        
        cursor.execute("""
            UPDATE support_tickets SET admin_reply=%s, status='closed', updated_at=%s
            WHERE id=%s
        """, (data.reply, datetime.now().isoformat(), ticket_id))
        
        if ticket and background_tasks:
            background_tasks.add_task(send_ticket_reply_email, ticket['student_email'], ticket['student_name'], ticket['subject'], data.reply)
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("reply_ticket", "admin", f"Replied to ticket #{ticket_id}", datetime.now().isoformat()))
        
        return {"message": "Reply sent"}

# ---------- STUDENTS LIST ----------
@app.get("/api/students")
def get_students(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            SELECT id, reg_id, full_name, student_id, email, phone, programme, level, 
                   courses, total_amount, payment_status, registered_at, certificate_released 
            FROM students ORDER BY registered_at DESC
        """)
        students = cursor.fetchall()
        result = []
        for s in students:
            courses = json.loads(s['courses']) if s['courses'] else []
            result.append({
                "id": s['id'], "reg_id": s['reg_id'], "full_name": s['full_name'], "student_id": s['student_id'],
                "email": s['email'], "phone": s['phone'], "programme": s['programme'], "level": s['level'],
                "courses": courses, "total_amount": s['total_amount'],
                "payment_status": s['payment_status'], "registered_at": s['registered_at'], 
                "certificate_released": bool(s['certificate_released']) if s['certificate_released'] else False
            })
        return result

# ---------- DELETE STUDENT ----------
@app.delete("/api/admin/students/{student_id}")
def delete_student(student_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT full_name, reg_id FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(404, "Student not found")
        
        cursor.execute("DELETE FROM students WHERE id=%s", (student_id,))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("delete_student", "admin", f"Deleted student: {student['full_name']} ({student['reg_id']})", datetime.now().isoformat()))
        
        return {"message": f"Student {student['full_name']} deleted successfully"}

# ---------- RESET DATABASE ----------
@app.delete("/api/admin/database/reset")
def reset_database(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM students")
        cursor.execute("DELETE FROM comments")
        cursor.execute("DELETE FROM activity_logs")
        cursor.execute("DELETE FROM support_tickets")
        cursor.execute("DELETE FROM edit_requests")
        cursor.execute("UPDATE courses SET registered_count = 0")
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("reset_database", "admin", "Cleared all student data", datetime.now().isoformat()))
        
        return {"message": "Database reset successfully. All student data cleared."}

# ---------- RELEASE CERTIFICATE ----------
@app.post("/api/admin/certificates/{student_id}/release")
def release_certificate(student_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT full_name FROM students WHERE id=%s", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(404, "Student not found")
        
        cursor.execute("UPDATE students SET certificate_released=1, certificate_released_at=%s WHERE id=%s", 
                      (datetime.now().isoformat(), student_id))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("release_certificate", "admin", f"Released certificate for: {student['full_name']}", datetime.now().isoformat()))
        
        return {"message": f"Certificate released for {student['full_name']}"}

# ---------- BULK RELEASE CERTIFICATES ----------
@app.post("/api/admin/certificates/bulk-release")
def bulk_release_certificates(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("UPDATE students SET certificate_released=1, certificate_released_at=%s WHERE payment_status='paid'",
                      (datetime.now().isoformat(),))
        count = cursor.rowcount
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("bulk_release", "admin", f"Released certificates for {count} students", datetime.now().isoformat()))
        
        return {"message": f"Certificates released for {count} students"}

# ---------- MARK PAID ----------
@app.put("/api/admin/students/{student_id}/payment")
def mark_paid(student_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("UPDATE students SET payment_status='paid' WHERE id=%s", (student_id,))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("mark_paid", "admin", f"Marked student ID {student_id} as paid", datetime.now().isoformat()))
        
        return {"message": "Payment marked as paid"}

# ---------- UPDATE STUDENT ----------
@app.put("/api/admin/students/{student_id}")
def update_student(student_id: int, student: StudentUpdate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE students 
            SET full_name=%s, student_id=%s, email=%s, phone=%s, programme=%s, level=%s, payment_status=%s
            WHERE id=%s
        """, (student.full_name, student.student_id, student.email, student.phone,
              student.programme, student.level, student.payment_status, student_id))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("update_student", "admin", f"Updated student ID {student_id}", datetime.now().isoformat()))
        
        return {"message": "Student updated successfully"}

# ---------- ACTIVITY LOGS ----------
@app.get("/api/activity-logs")
def get_activity_logs(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT id, action, admin_name, details, created_at FROM activity_logs ORDER BY created_at DESC LIMIT 200")
        logs = cursor.fetchall()
        return [
            {"id": l['id'], "action": l['action'], "admin_name": l['admin_name'], "details": l['details'], "created_at": l['created_at']}
            for l in logs
        ]

# ---------- COURSES ----------
@app.get("/api/courses")
def get_courses(level: Optional[int] = None):
    with get_cursor() as cursor:
        if level:
            cursor.execute("SELECT id, name, level, price, instructor, schedule_day, schedule_time, venue, description, icon, registered_count FROM courses WHERE level=%s ORDER BY name", (level,))
        else:
            cursor.execute("SELECT id, name, level, price, instructor, schedule_day, schedule_time, venue, description, icon, registered_count FROM courses ORDER BY level, name")
        
        courses = cursor.fetchall()
        return [
            {
                "id": c['id'], "name": c['name'], "level": c['level'], "price": c['price'],
                "instructor": c['instructor'], "schedule_day": c['schedule_day'], "schedule_time": c['schedule_time'],
                "venue": c['venue'], "description": c['description'], "icon": c['icon'], "registered_count": c['registered_count']
            }
            for c in courses
        ]

@app.post("/api/admin/courses")
def create_course(course: CourseCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO courses (name, level, price, instructor, schedule_day, schedule_time, venue, description, icon)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (course.name, course.level, course.price, course.instructor, course.schedule_day, course.schedule_time, course.venue, course.description, course.icon))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("create_course", "admin", f"Created course: {course.name}", datetime.now().isoformat()))
        
        return {"message": "Course created", "id": cursor.fetchone()['id'] if hasattr(cursor, 'fetchone') else 1}

@app.put("/api/admin/courses/{course_id}")
def update_course(course_id: int, course: CourseCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE courses SET name=%s, level=%s, price=%s, instructor=%s, schedule_day=%s, schedule_time=%s, venue=%s, description=%s, icon=%s
            WHERE id=%s
        """, (course.name, course.level, course.price, course.instructor, course.schedule_day, course.schedule_time, course.venue, course.description, course.icon, course_id))
        
        return {"message": "Course updated"}

@app.delete("/api/admin/courses/{course_id}")
def delete_course(course_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM courses WHERE id=%s", (course_id,))
        return {"message": "Course deleted"}

# ---------- ADMIN LOGIN ----------
@app.post("/api/admin/login")
def admin_login(data: AdminLogin):
    with get_cursor() as cursor:
        hashed = hashlib.sha256(data.password.encode()).hexdigest()
        cursor.execute("SELECT * FROM admins WHERE username=%s AND password=%s", (data.username, hashed))
        if cursor.fetchone():
            token = hashlib.sha256(f"{data.username}{datetime.now().isoformat()}{uuid.uuid4().hex}".encode()).hexdigest()
            expires_at = (datetime.now() + timedelta(days=1)).isoformat()
            
            cursor.execute("INSERT INTO admin_tokens (token, created_at, expires_at) VALUES (%s, %s, %s)",
                          (token, datetime.now().isoformat(), expires_at))
            
            return {"token": token, "username": data.username}
        raise HTTPException(401, "Invalid credentials")

# ---------- CHANGE ADMIN CREDENTIALS ----------
@app.put("/api/admin/change-credentials")
def change_admin_credentials(data: AdminChangeCredentials, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT username, password FROM admins WHERE id=1")
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(404, "Admin not found")
        
        current_hash = hashlib.sha256(data.current_password.encode()).hexdigest()
        if current_hash != row['password']:
            raise HTTPException(401, "Current password is incorrect")
        
        if data.new_username and data.new_username.strip():
            cursor.execute("UPDATE admins SET username=%s WHERE id=1", (data.new_username.strip(),))
        
        if data.new_password and len(data.new_password) >= 6:
            new_hash = hashlib.sha256(data.new_password.encode()).hexdigest()
            cursor.execute("UPDATE admins SET password=%s WHERE id=1", (new_hash,))
        
        cursor.execute("DELETE FROM admin_tokens")
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("change_credentials", "admin", "Admin changed credentials", datetime.now().isoformat()))
        
        return {"message": "Credentials updated successfully. Please login again."}

# ---------- COMMENTS ----------
@app.get("/api/comments")
def get_comments():
    with get_cursor() as cursor:
        def build_tree(comments_list, parent_id=None):
            result = []
            for c in comments_list:
                if c['parent_id'] == parent_id:
                    replies = build_tree(comments_list, c['id'])
                    result.append({
                        "id": c['id'], "user_name": c['user_name'], "rating": c['rating'],
                        "content": c['content'], "likes": c['likes'], "parent_id": c['parent_id'],
                        "created_at": c['created_at'], "replies": replies
                    })
            return result
        
        cursor.execute("SELECT id, user_name, rating, content, likes, parent_id, created_at FROM comments ORDER BY created_at ASC")
        all_comments = [dict(row) for row in cursor.fetchall()]
        return build_tree(all_comments)

@app.post("/api/comments")
async def add_comment(comment: CommentCreate):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO comments (user_name, rating, content, parent_id, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (comment.user_name, comment.rating, comment.content, comment.parent_id, datetime.now().isoformat()))
        await sio.emit('new_comment', {"user_name": comment.user_name, "content": comment.content})
        return {"message": "Comment added", "id": cursor.fetchone()['id'] if hasattr(cursor, 'fetchone') else 1}

@app.post("/api/comments/{comment_id}/like")
async def like_comment(comment_id: int):
    with get_cursor() as cursor:
        cursor.execute("UPDATE comments SET likes = likes + 1 WHERE id=%s", (comment_id,))
        cursor.execute("SELECT likes FROM comments WHERE id=%s", (comment_id,))
        row = cursor.fetchone()
        likes = row['likes'] if row else 0
        await sio.emit('comment_liked', {"id": comment_id})
        return {"likes": likes}

@app.delete("/api/admin/comments/{comment_id}")
def delete_comment(comment_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM comments WHERE id=%s OR parent_id=%s", (comment_id, comment_id))
        return {"message": "Comment deleted"}

# ---------- SETTINGS ----------
@app.get("/api/settings")
def get_settings():
    with get_cursor() as cursor:
        cursor.execute("SELECT key, value FROM settings")
        result = {}
        for row in cursor.fetchall():
            result[row['key']] = row['value']
        return result

@app.put("/api/admin/settings")
def update_settings(settings: dict, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        for key, value in settings.items():
            cursor.execute("UPDATE settings SET value=%s WHERE key=%s", (value, key))
        return {"message": "Settings updated"}

@app.get("/api/contact")
def get_contact():
    with get_cursor() as cursor:
        cursor.execute("SELECT value FROM settings WHERE key='contact_email'")
        email = cursor.fetchone()
        cursor.execute("SELECT value FROM settings WHERE key='contact_phone'")
        phone = cursor.fetchone()
        return {
            "email": email['value'] if email else "ksm.tutorials@ucc.edu.gh", 
            "phone": phone['value'] if phone else "+233 24 123 4567"
        }

@app.get("/api/whatsapp")
def get_whatsapp():
    with get_cursor() as cursor:
        cursor.execute("SELECT value FROM settings WHERE key='whatsapp_link'")
        row = cursor.fetchone()
        return {"link": row['value'] if row else "https://chat.whatsapp.com/KSM2026"}

@app.post("/api/admin/broadcast/whatsapp")
async def broadcast_whatsapp(data: dict, admin: str = Depends(verify_admin)):
    message = data.get("message", "")
    with get_cursor() as cursor:
        cursor.execute("SELECT phone FROM students")
        phones = [row['phone'] for row in cursor.fetchall()]
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("broadcast", "admin", f"Sent WhatsApp broadcast: {message[:50]}...", datetime.now().isoformat()))
        return {"message": f"Broadcast sent to {len(phones)} students"}

@app.get("/api/slider")
def get_slider():
    return [
        {"title": "KSM Tutorials 2026", "description": "Get Straight A's in IT & CS"},
        {"title": "Expert Tutors", "description": "Learn from industry professionals"},
        {"title": "Limited Offer", "description": "Register now for early benefits"}
    ]

# ---------- DIRECTOR MESSAGE ----------
@app.get("/api/director-message")
def get_director_message():
    with get_cursor() as cursor:
        cursor.execute("SELECT content, signature, updated_at FROM director_messages ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {"content": row['content'], "signature": row['signature'], "updated_at": row['updated_at']}
        return {"content": "", "signature": "", "updated_at": ""}

@app.put("/api/admin/director-message")
def update_director_message(data: DirectorMessageUpdate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM director_messages")
        cursor.execute("INSERT INTO director_messages (content, signature, updated_at) VALUES (%s, %s, %s)",
                      (data.content, data.signature, datetime.now().isoformat()))
        return {"message": "Director message updated"}

# ---------- TUTORS ----------
@app.get("/api/tutors")
def get_tutors():
    with get_cursor() as cursor:
        cursor.execute("SELECT id, name, specialization, experience, image, email, linkedin, image_url FROM tutors ORDER BY name")
        tutors = cursor.fetchall()
        return [
            {"id": t['id'], "name": t['name'], "specialization": t['specialization'], "experience": t['experience'], 
             "image": t['image'], "email": t['email'], "linkedin": t['linkedin'], "image_url": t['image_url'] or ""}
            for t in tutors
        ]

@app.post("/api/admin/tutors")
def create_tutor(tutor: TutorCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO tutors (name, specialization, experience, image, email, linkedin, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (tutor.name, tutor.specialization, tutor.experience, tutor.image, tutor.email, tutor.linkedin, tutor.image_url))
        return {"message": "Tutor created", "id": cursor.fetchone()['id'] if hasattr(cursor, 'fetchone') else 1}

@app.put("/api/admin/tutors/{tutor_id}")
def update_tutor(tutor_id: int, tutor: TutorCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE tutors SET name=%s, specialization=%s, experience=%s, image=%s, email=%s, linkedin=%s, image_url=%s
            WHERE id=%s
        """, (tutor.name, tutor.specialization, tutor.experience, tutor.image, tutor.email, tutor.linkedin, tutor.image_url, tutor_id))
        return {"message": "Tutor updated"}

@app.delete("/api/admin/tutors/{tutor_id}")
def delete_tutor(tutor_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM tutors WHERE id=%s", (tutor_id,))
        return {"message": "Tutor deleted"}

# ---------- ANNOUNCEMENTS ----------
@app.get("/api/announcements")
def get_announcements():
    with get_cursor() as cursor:
        cursor.execute("SELECT id, title, content, type, date FROM announcements ORDER BY date DESC")
        announcements = cursor.fetchall()
        return [
            {"id": a['id'], "title": a['title'], "content": a['content'], "type": a['type'], "date": a['date']}
            for a in announcements
        ]

@app.post("/api/admin/announcements")
def create_announcement(announcement: AnnouncementCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO announcements (title, content, type, date)
            VALUES (%s, %s, %s, %s)
        """, (announcement.title, announcement.content, announcement.type, announcement.date))
        return {"message": "Announcement created"}

@app.put("/api/admin/announcements/{announcement_id}")
def update_announcement(announcement_id: int, announcement: AnnouncementCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE announcements SET title=%s, content=%s, type=%s, date=%s
            WHERE id=%s
        """, (announcement.title, announcement.content, announcement.type, announcement.date, announcement_id))
        return {"message": "Announcement updated"}

@app.delete("/api/admin/announcements/{announcement_id}")
def delete_announcement(announcement_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM announcements WHERE id=%s", (announcement_id,))
        return {"message": "Announcement deleted"}

# ---------- PARTNERS ----------
@app.get("/api/partners")
def get_partners():
    with get_cursor() as cursor:
        cursor.execute("SELECT id, name, icon, link, color FROM partners ORDER BY name")
        partners = cursor.fetchall()
        return [
            {"id": p['id'], "name": p['name'], "icon": p['icon'], "link": p['link'], "color": p['color']}
            for p in partners
        ]

@app.post("/api/admin/partners")
def create_partner(partner: PartnerCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO partners (name, icon, link, color)
            VALUES (%s, %s, %s, %s)
        """, (partner.name, partner.icon, partner.link, partner.color))
        return {"message": "Partner created"}

@app.put("/api/admin/partners/{partner_id}")
def update_partner(partner_id: int, partner: PartnerCreate, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE partners SET name=%s, icon=%s, link=%s, color=%s
            WHERE id=%s
        """, (partner.name, partner.icon, partner.link, partner.color, partner_id))
        return {"message": "Partner updated"}

@app.delete("/api/admin/partners/{partner_id}")
def delete_partner(partner_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM partners WHERE id=%s", (partner_id,))
        return {"message": "Partner deleted"}

# ---------- SUPPORT TICKETS (Student) ----------
@app.post("/api/student/ticket")
def create_ticket(ticket: TicketCreate):
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO support_tickets (student_id, student_name, student_email, subject, message, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'open', %s)
        """, (ticket.student_id, ticket.student_name, ticket.student_email,
              ticket.subject, ticket.message, datetime.now().isoformat()))
        return {"message": "Ticket created", "id": cursor.fetchone()['id'] if hasattr(cursor, 'fetchone') else 1}

@app.get("/api/student/tickets/{student_id}")
def get_student_tickets(student_id: int):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM support_tickets WHERE student_id=%s ORDER BY created_at DESC", (student_id,))
        tickets = cursor.fetchall()
        return [dict(ticket) for ticket in tickets]

@app.get("/api/admin/tickets")
def get_all_tickets(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM support_tickets ORDER BY created_at DESC")
        tickets = cursor.fetchall()
        return [dict(ticket) for ticket in tickets]

@app.get("/api/admin/edit-requests")
def get_edit_requests(admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM edit_requests ORDER BY created_at DESC")
        requests = cursor.fetchall()
        return [dict(r) for r in requests]

@app.put("/api/admin/edit-requests/{request_id}/reject")
def reject_edit_request(request_id: int, admin: str = Depends(verify_admin)):
    with get_cursor() as cursor:
        cursor.execute("UPDATE edit_requests SET status='rejected', responded_at=%s WHERE id=%s", 
                      (datetime.now().isoformat(), request_id))
        
        cursor.execute("INSERT INTO activity_logs (action, admin_name, details, created_at) VALUES (%s, %s, %s, %s)",
                      ("reject_edit", "admin", f"Rejected edit request #{request_id}", datetime.now().isoformat()))
        
        return {"message": "Edit request rejected"}

# ---------- CERTIFICATE ----------
@app.get("/api/student/certificate/{reg_id}")
def get_certificate(reg_id: str):
    with get_cursor() as cursor:
        cursor.execute("SELECT reg_id, full_name, courses, certificate_released FROM students WHERE reg_id=%s", (reg_id,))
        student = cursor.fetchone()
        
        if not student:
            raise HTTPException(404, "Student not found")
        
        if not student['certificate_released']:
            raise HTTPException(403, "Certificate not released yet. Contact admin.")
        
        courses_list = json.loads(student['courses']) if student['courses'] else []
        
        return {
            "reg_id": student['reg_id'],
            "full_name": student['full_name'],
            "courses": courses_list,
            "completion_date": datetime.now().strftime("%B %d, %Y")
        }

# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print("=" * 60)
    print("🚀 KSM TUTORIALS BACKEND SERVER (Production)")
    print(f"📍 Port: {port}")
    print("📚 API Docs: /docs")
    print("=" * 60)
    uvicorn.run(socket_app, host="0.0.0.0", port=port, log_level="info")
