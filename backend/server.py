from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Depends, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr, ValidationError
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timezone, date, timedelta
import io
import base64
import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from passlib.context import CryptContext
import sys
sys.path.insert(0, str(Path(__file__).parent))
from models_enhanced import *

# Import meetings modules
from meetings_service import MeetingsService
from meetings_models import MeetingFilters

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Initialize Meetings Service
meetings_service = MeetingsService(db)

# Security
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# ============ HELPER FUNCTIONS ============

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        employee_id: str = payload.get("sub")
        if employee_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
        if employee is None:
            # Check if it's an admin
            admin = await db.admin_users.find_one({"id": employee_id}, {"_id": 0})
            if admin is None:
                raise HTTPException(status_code=401, detail="User not found")
            return admin
        return employee
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

# ============ MODELS ============

# Auth Models
class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user: dict
    role: str  # admin or employee

class AdminUser(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    hashed_password: str
    full_name: str
    role: str = "admin"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PasswordResetRequest(BaseModel):
    email: str
    new_password: str

class ProfileUpdateRequest(BaseModel):
    phone: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

# Employee Models
class EmployeeCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    date_of_birth: str
    gender: str
    address: str
    department: str
    position: str
    employment_type: str  # Full-time, Part-time, Contract
    join_date: str
    salary: float
    password: Optional[str] = None  # For employee login
    manager_id: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

class Employee(EmployeeCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "active"  # active, inactive, terminated
    hashed_password: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# Attendance Models
class AttendanceCreate(BaseModel):
    employee_id: str
    date: str
    check_in: str
    check_out: Optional[str] = None
    status: str = "present"  # present, absent, half-day, late
    notes: Optional[str] = None

class Attendance(AttendanceCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# Leave Models
class LeaveRequestCreate(BaseModel):
    employee_id: str
    leave_type: str  # sick, casual, vacation, unpaid
    start_date: str
    end_date: str
    days_count: float
    reason: str

class LeaveRequest(LeaveRequestCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"  # pending, approved, rejected
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class LeaveApproval(BaseModel):
    status: str  # approved, rejected
    approved_by: str

# Recruitment Models
class JobPostingCreate(BaseModel):
    title: str
    department: str
    location: str
    employment_type: str
    salary_range: str
    description: str
    requirements: str
    posted_by: str

class JobPosting(JobPostingCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "open"  # open, closed
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class CandidateCreate(BaseModel):
    job_id: str
    full_name: str
    email: EmailStr
    phone: str
    experience_years: float
    current_company: Optional[str] = None
    expected_salary: float
    resume_url: Optional[str] = None

class Candidate(CandidateCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stage: str = "applied"  # applied, screening, interview, offered, rejected, hired
    notes: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class CandidateStageUpdate(BaseModel):
    stage: str
    notes: Optional[str] = None

# Onboarding Models
class OnboardingTaskCreate(BaseModel):
    employee_id: str
    task_title: str
    task_description: str
    due_date: str
    assigned_to: str

class OnboardingTask(OnboardingTaskCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"  # pending, in_progress, completed
    completed_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class TaskStatusUpdate(BaseModel):
    status: str

# Payroll Models
class PayrollRecordCreate(BaseModel):
    employee_id: str
    month: str  # YYYY-MM format
    basic_salary: float
    allowances: float = 0
    deductions: float = 0
    tax: float = 0
    net_salary: float
    payment_date: str
    payment_status: str = "pending"  # pending, paid

class PayrollRecord(PayrollRecordCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# Performance Models
class PerformanceReviewCreate(BaseModel):
    employee_id: str
    reviewer_id: str
    review_period: str  # e.g., "Q1 2025"
    goals: str
    achievements: str
    areas_of_improvement: str
    rating: float  # 1-5 scale
    feedback: str

class PerformanceReview(PerformanceReviewCreate):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "draft"  # draft, completed
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# Document Models
class DocumentUpload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: str  # employee, candidate, payroll
    entity_id: str
    document_type: str  # resume, contract, id_proof, salary_slip
    file_name: str
    file_data: str  # base64 encoded
    uploaded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ============ AUTHENTICATION ROUTES ============

@api_router.post("/auth/login", response_model=LoginResponse)
async def login(login_request: LoginRequest):
    # Check if admin first
    admin = await db.admin_users.find_one({"email": login_request.email}, {"_id": 0})
    if admin:
        if not verify_password(login_request.password, admin["hashed_password"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        token = create_access_token({"sub": admin["id"], "email": admin["email"], "role": "admin"})
        admin_data = {k: v for k, v in admin.items() if k != "hashed_password"}
        return {"token": token, "user": admin_data, "role": "admin"}
    
    # Check employee
    employee = await db.employees.find_one({"email": login_request.email}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not employee.get("hashed_password"):
        raise HTTPException(status_code=401, detail="Password not set. Contact HR.")
    
    if not verify_password(login_request.password, employee["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if employee.get("status") != "active":
        raise HTTPException(status_code=401, detail="Account is not active")
    
    token = create_access_token({"sub": employee["id"], "email": employee["email"], "role": "employee"})
    employee_data = {k: v for k, v in employee.items() if k != "hashed_password"}
    
    return {"token": token, "user": employee_data, "role": "employee"}


# Admin Signup Request Model
class AdminSignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

# Employee Signup Request Model  
class EmployeeSignupRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone: str
    date_of_birth: str
    gender: str
    address: str
    department: str
    position: str
    employment_type: str = "Full-time"
    join_date: str
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

@api_router.post("/auth/admin/signup")
async def admin_signup(signup_request: AdminSignupRequest):
    # Check if admin already exists
    existing_admin = await db.admin_users.find_one({"email": signup_request.email})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin with this email already exists")
    
    # Create new admin
    admin_id = str(uuid.uuid4())
    hashed_password = hash_password(signup_request.password)
    
    admin_data = {
        "id": admin_id,
        "email": signup_request.email,
        "hashed_password": hashed_password,
        "full_name": signup_request.full_name,
        "role": "admin",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.admin_users.insert_one(admin_data)
    
    # Create token
    token = create_access_token({"sub": admin_id, "email": signup_request.email, "role": "admin"})
    
    # Return response without password and _id
    admin_response = {k: v for k, v in admin_data.items() if k not in ["hashed_password", "_id"]}
    
    return {"token": token, "user": admin_response, "role": "admin", "message": "Admin account created successfully"}

@api_router.post("/auth/employee/signup")
async def employee_signup(signup_request: EmployeeSignupRequest):
    # Check if employee already exists
    existing_employee = await db.employees.find_one({"email": signup_request.email})
    if existing_employee:
        raise HTTPException(status_code=400, detail="Employee with this email already exists")
    
    # Create new employee
    employee_id = f"emp_{str(uuid.uuid4())[:8]}"
    hashed_password = hash_password(signup_request.password)
    
    employee_data = {
        "id": employee_id,
        "email": signup_request.email,
        "hashed_password": hashed_password,
        "first_name": signup_request.first_name,
        "last_name": signup_request.last_name,
        "phone": signup_request.phone,
        "date_of_birth": signup_request.date_of_birth,
        "gender": signup_request.gender,
        "address": signup_request.address,
        "department": signup_request.department,
        "position": signup_request.position,
        "employment_type": signup_request.employment_type,
        "join_date": signup_request.join_date,
        "salary": 0,  # Default salary, can be updated later
        "status": "active",
        "emergency_contact_name": signup_request.emergency_contact_name,
        "emergency_contact_phone": signup_request.emergency_contact_phone,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.employees.insert_one(employee_data)
    
    # Create token
    token = create_access_token({"sub": employee_id, "email": signup_request.email, "role": "employee"})
    
    # Return response without password and _id
    employee_response = {k: v for k, v in employee_data.items() if k not in ["hashed_password", "_id"]}
    
    return {"token": token, "user": employee_response, "role": "employee", "message": "Employee account created successfully"}


@api_router.post("/auth/reset-password")
async def reset_password(reset_request: PasswordResetRequest):
    employee = await db.employees.find_one({"email": reset_request.email})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    hashed_password = hash_password(reset_request.new_password)
    await db.employees.update_one(
        {"email": reset_request.email},
        {"$set": {"hashed_password": hashed_password}}
    )
    
    return {"message": "Password reset successfully"}

# ============ ADMIN MANAGEMENT ROUTES ============

@api_router.get("/admin/users")
async def get_all_users(current_user: dict = Depends(get_current_user)):
    """Get all users (admins and employees) - Admin only"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Get all admins
    admins = await db.admin_users.find({}, {"_id": 0, "hashed_password": 0}).to_list(1000)
    for admin in admins:
        admin["user_type"] = "admin"
    
    # Get all employees
    employees = await db.employees.find({}, {"_id": 0, "hashed_password": 0}).to_list(1000)
    for employee in employees:
        employee["user_type"] = "employee"
    
    return {
        "admins": admins,
        "employees": employees,
        "total_admins": len(admins),
        "total_employees": len(employees),
        "total_users": len(admins) + len(employees)
    }

@api_router.get("/admin/list")
async def get_all_admins(current_user: dict = Depends(get_current_user)):
    """Get all admin users - Admin only"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    admins = await db.admin_users.find({}, {"_id": 0, "hashed_password": 0}).to_list(1000)
    return admins

@api_router.delete("/admin/{admin_id}")
async def delete_admin(admin_id: str, current_user: dict = Depends(get_current_user)):
    """Delete an admin user - Admin only"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Prevent self-deletion
    if current_user.get("id") == admin_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account")
    
    result = await db.admin_users.delete_one({"id": admin_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Admin not found")
    
    return {"message": "Admin deleted successfully"}

@api_router.get("/admin/recent-signups")
async def get_recent_signups(current_user: dict = Depends(get_current_user), days: int = 30):
    """Get recently signed up users - Admin only"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Get recent admins
    recent_admins = await db.admin_users.find(
        {"created_at": {"$gte": cutoff_date}},
        {"_id": 0, "hashed_password": 0}
    ).sort("created_at", -1).to_list(100)
    for admin in recent_admins:
        admin["user_type"] = "admin"
    
    # Get recent employees
    recent_employees = await db.employees.find(
        {"created_at": {"$gte": cutoff_date}},
        {"_id": 0, "hashed_password": 0}
    ).sort("created_at", -1).to_list(100)
    for employee in recent_employees:
        employee["user_type"] = "employee"
    
    # Combine and sort by created_at
    all_recent = recent_admins + recent_employees
    all_recent.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return {
        "recent_signups": all_recent,
        "total_recent": len(all_recent),
        "recent_admins": len(recent_admins),
        "recent_employees": len(recent_employees),
        "days": days
    }

# ============ EMPLOYEE PORTAL ROUTES ============

@api_router.get("/employee/profile")
async def get_employee_profile(current_user: dict = Depends(get_current_user)):
    # Remove sensitive data
    profile = {k: v for k, v in current_user.items() if k not in ["hashed_password"]}
    return profile

@api_router.put("/employee/profile")
async def update_employee_profile(
    profile_update: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    update_data = {k: v for k, v in profile_update.model_dump().items() if v is not None}
    
    await db.employees.update_one(
        {"id": current_user["id"]},
        {"$set": update_data}
    )
    
    updated_employee = await db.employees.find_one({"id": current_user["id"]}, {"_id": 0, "hashed_password": 0})
    return updated_employee

@api_router.get("/employee/attendance")
async def get_employee_attendance(current_user: dict = Depends(get_current_user)):
    attendance_records = await db.attendance.find(
        {"employee_id": current_user["id"]},
        {"_id": 0}
    ).sort("date", -1).to_list(100)
    return attendance_records

@api_router.get("/employee/leaves")
async def get_employee_leaves(current_user: dict = Depends(get_current_user)):
    leave_requests = await db.leave_requests.find(
        {"employee_id": current_user["id"]},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    return leave_requests

@api_router.post("/employee/leaves")
async def create_employee_leave_request(
    leave: LeaveRequestCreate,
    current_user: dict = Depends(get_current_user)
):
    # Override employee_id with current user
    leave_data = leave.model_dump()
    leave_data["employee_id"] = current_user["id"]
    
    leave_obj = LeaveRequest(**leave_data)
    doc = leave_obj.model_dump()
    await db.leave_requests.insert_one(doc)
    return leave_obj

@api_router.get("/employee/payslips")
async def get_employee_payslips(current_user: dict = Depends(get_current_user)):
    payslips = await db.payroll_records.find(
        {"employee_id": current_user["id"]},
        {"_id": 0}
    ).sort("month", -1).to_list(100)
    return payslips

@api_router.get("/employee/documents")
async def get_employee_documents(current_user: dict = Depends(get_current_user)):
    documents = await db.documents.find(
        {"entity_type": "employee", "entity_id": current_user["id"]},
        {"_id": 0, "file_data": 0}
    ).to_list(100)
    return documents

@api_router.post("/employee/documents/upload")
async def upload_employee_document(
    file: UploadFile,
    document_type: str,
    current_user: dict = Depends(get_current_user)
):
    file_data = await file.read()
    encoded_file = base64.b64encode(file_data).decode('utf-8')
    
    doc = DocumentUpload(
        entity_type="employee",
        entity_id=current_user["id"],
        document_type=document_type,
        file_name=file.filename,
        file_data=encoded_file
    )
    
    await db.documents.insert_one(doc.model_dump())
    return {"message": "Document uploaded successfully", "document_id": doc.id}

@api_router.get("/employee/dashboard")
async def get_employee_dashboard(current_user: dict = Depends(get_current_user)):
    # Get upcoming leaves
    today = datetime.now().strftime("%Y-%m-%d")
    upcoming_leaves = await db.leave_requests.find(
        {
            "employee_id": current_user["id"],
            "status": "approved",
            "start_date": {"$gte": today}
        },
        {"_id": 0}
    ).sort("start_date", 1).to_list(5)
    
    # Get pending leave requests
    pending_leaves = await db.leave_requests.count_documents(
        {"employee_id": current_user["id"], "status": "pending"}
    )
    
    # Get onboarding tasks
    pending_tasks = await db.onboarding_tasks.find(
        {
            "employee_id": current_user["id"],
            "status": {"$in": ["pending", "in_progress"]}
        },
        {"_id": 0}
    ).to_list(10)
    
    # Get recent attendance (last 7 days)
    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent_attendance = await db.attendance.count_documents(
        {
            "employee_id": current_user["id"],
            "date": {"$gte": seven_days_ago},
            "status": "present"
        }
    )
    
    return {
        "upcoming_leaves": upcoming_leaves,
        "pending_leave_count": pending_leaves,
        "pending_tasks": pending_tasks,
        "attendance_last_7_days": recent_attendance
    }

# ============ EMPLOYEE ROUTES ============

@api_router.post("/employees", response_model=Employee)
async def create_employee(employee: EmployeeCreate):
    emp_data = employee.model_dump()
    
    # Hash password if provided
    if emp_data.get("password"):
        emp_data["hashed_password"] = hash_password(emp_data["password"])
        del emp_data["password"]
    
    emp_obj = Employee(**emp_data)
    doc = emp_obj.model_dump()
    await db.employees.insert_one(doc)
    
    # Remove sensitive data from response
    response_data = {k: v for k, v in emp_obj.model_dump().items() if k != "hashed_password"}
    return response_data


@api_router.post("/employees/bulk")
async def bulk_create_employees(data: dict):
    """Bulk create employees from CSV import with validation"""
    employees_data = data.get("employees", [])
    
    if not employees_data:
        raise HTTPException(status_code=400, detail="No employee data provided")
    
    added_count = 0
    errors = []
    
    for idx, emp_data in enumerate(employees_data):
        try:
            # Validate employee data using Pydantic model
            validated_emp = EmployeeCreate(**emp_data)
            
            # Generate employee ID
            emp_id = f"emp_{str(uuid.uuid4())[:8]}"
            
            # Set default password (can be changed later)
            default_password = "Welcome123"
            hashed_pwd = hash_password(default_password)
            
            # Prepare employee document
            emp_doc = validated_emp.model_dump()
            emp_doc["id"] = emp_id
            emp_doc["status"] = emp_data.get("status", "active")
            emp_doc["hashed_password"] = hashed_pwd
            emp_doc["created_at"] = datetime.now(timezone.utc).isoformat()
            
            # Insert employee
            await db.employees.insert_one(emp_doc)
            added_count += 1
        except ValidationError as e:
            # Pydantic validation error - invalid employee data
            error_fields = [err['loc'][0] for err in e.errors()]
            errors.append(f"Row {idx + 1} ({emp_data.get('email', 'unknown')}): Missing or invalid fields - {', '.join(error_fields)}")
        except Exception as e:
            # Other errors (e.g., database errors)
            errors.append(f"Row {idx + 1} ({emp_data.get('email', 'unknown')}): {str(e)}")
    
    if added_count == 0 and errors:
        # All records failed - return error response
        raise HTTPException(status_code=400, detail={"message": "Failed to add any employees", "errors": errors})
    
    return {
        "added": added_count,
        "total": len(employees_data),
        "failed": len(errors),
        "errors": errors if errors else None
    }


@api_router.get("/employees", response_model=List[Employee])
async def get_employees(status: Optional[str] = None):
    query = {}
    if status:
        query["status"] = status
    employees = await db.employees.find(query, {"_id": 0}).to_list(1000)
    return employees

@api_router.get("/employees/{employee_id}", response_model=Employee)
async def get_employee(employee_id: str):
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee

@api_router.put("/employees/{employee_id}", response_model=Employee)
async def update_employee(employee_id: str, employee: EmployeeCreate):
    result = await db.employees.update_one(
        {"id": employee_id},
        {"$set": employee.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    updated_employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    return updated_employee

@api_router.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str):
    result = await db.employees.update_one(
        {"id": employee_id},
        {"$set": {"status": "terminated"}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"message": "Employee status updated to terminated"}

# ============ ATTENDANCE ROUTES ============

@api_router.post("/attendance", response_model=Attendance)
async def create_attendance(attendance: AttendanceCreate):
    att_obj = Attendance(**attendance.model_dump())
    doc = att_obj.model_dump()
    await db.attendance.insert_one(doc)
    return att_obj

@api_router.get("/attendance", response_model=List[Attendance])
async def get_attendance(employee_id: Optional[str] = None, date: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if date:
        query["date"] = date
    attendance_records = await db.attendance.find(query, {"_id": 0}).to_list(1000)
    return attendance_records

@api_router.put("/attendance/{attendance_id}", response_model=Attendance)
async def update_attendance(attendance_id: str, attendance: AttendanceCreate):
    result = await db.attendance.update_one(
        {"id": attendance_id},
        {"$set": attendance.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    updated_record = await db.attendance.find_one({"id": attendance_id}, {"_id": 0})
    return updated_record

# ============ LEAVE ROUTES ============

@api_router.post("/leave-requests", response_model=LeaveRequest)
async def create_leave_request(leave: LeaveRequestCreate):
    leave_obj = LeaveRequest(**leave.model_dump())
    doc = leave_obj.model_dump()
    await db.leave_requests.insert_one(doc)
    return leave_obj

@api_router.get("/leave-requests", response_model=List[LeaveRequest])
async def get_leave_requests(employee_id: Optional[str] = None, status: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    leave_requests = await db.leave_requests.find(query, {"_id": 0}).to_list(1000)
    return leave_requests

@api_router.put("/leave-requests/{leave_id}/approve", response_model=LeaveRequest)
async def approve_leave_request(leave_id: str, approval: LeaveApproval):
    result = await db.leave_requests.update_one(
        {"id": leave_id},
        {"$set": {
            "status": approval.status,
            "approved_by": approval.approved_by,
            "approved_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Leave request not found")
    updated_request = await db.leave_requests.find_one({"id": leave_id}, {"_id": 0})
    return updated_request

# ============ RECRUITMENT ROUTES ============

@api_router.post("/job-postings", response_model=JobPosting)
async def create_job_posting(job: JobPostingCreate):
    job_obj = JobPosting(**job.model_dump())
    doc = job_obj.model_dump()
    await db.job_postings.insert_one(doc)
    return job_obj

@api_router.get("/job-postings", response_model=List[JobPosting])
async def get_job_postings(status: Optional[str] = None):
    query = {}
    if status:
        query["status"] = status
    job_postings = await db.job_postings.find(query, {"_id": 0}).to_list(1000)
    return job_postings

@api_router.put("/job-postings/{job_id}", response_model=JobPosting)
async def update_job_posting(job_id: str, job: JobPostingCreate):
    result = await db.job_postings.update_one(
        {"id": job_id},
        {"$set": job.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job posting not found")
    updated_job = await db.job_postings.find_one({"id": job_id}, {"_id": 0})
    return updated_job


@api_router.delete("/job-postings/{job_id}")
async def delete_job_posting(job_id: str):
    result = await db.job_postings.delete_one({"id": job_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job posting not found")
    return {"message": "Job posting deleted successfully"}

@api_router.put("/job-postings/{job_id}/status")
async def update_job_posting_status(job_id: str, status_update: dict):
    result = await db.job_postings.update_one(
        {"id": job_id},
        {"$set": {"status": status_update["status"]}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job posting not found")
    updated_job = await db.job_postings.find_one({"id": job_id}, {"_id": 0})
    return updated_job


@api_router.post("/candidates", response_model=Candidate)
async def create_candidate(candidate: CandidateCreate):
    cand_obj = Candidate(**candidate.model_dump())
    doc = cand_obj.model_dump()
    await db.candidates.insert_one(doc)
    return cand_obj

@api_router.get("/candidates", response_model=List[Candidate])
async def get_candidates(job_id: Optional[str] = None, stage: Optional[str] = None):
    query = {}
    if job_id:
        query["job_id"] = job_id
    if stage:
        query["stage"] = stage
    candidates = await db.candidates.find(query, {"_id": 0}).to_list(1000)
    return candidates

@api_router.put("/candidates/{candidate_id}/stage", response_model=Candidate)
async def update_candidate_stage(candidate_id: str, stage_update: CandidateStageUpdate):
    result = await db.candidates.update_one(
        {"id": candidate_id},
        {"$set": stage_update.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Candidate not found")
    updated_candidate = await db.candidates.find_one({"id": candidate_id}, {"_id": 0})
    return updated_candidate

# ============ ONBOARDING ROUTES ============

@api_router.post("/onboarding-tasks", response_model=OnboardingTask)
async def create_onboarding_task(task: OnboardingTaskCreate):
    task_obj = OnboardingTask(**task.model_dump())
    doc = task_obj.model_dump()
    await db.onboarding_tasks.insert_one(doc)
    return task_obj

@api_router.get("/onboarding-tasks", response_model=List[OnboardingTask])
async def get_onboarding_tasks(employee_id: Optional[str] = None, status: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    tasks = await db.onboarding_tasks.find(query, {"_id": 0}).to_list(1000)
    return tasks

@api_router.put("/onboarding-tasks/{task_id}/status", response_model=OnboardingTask)
async def update_task_status(task_id: str, status_update: TaskStatusUpdate):
    update_data = {"status": status_update.status}
    if status_update.status == "completed":
        update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
    
    result = await db.onboarding_tasks.update_one(
        {"id": task_id},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    updated_task = await db.onboarding_tasks.find_one({"id": task_id}, {"_id": 0})
    return updated_task

# ============ PAYROLL ROUTES ============

@api_router.post("/payroll", response_model=PayrollRecord)
async def create_payroll_record(payroll: PayrollRecordCreate):
    payroll_obj = PayrollRecord(**payroll.model_dump())
    doc = payroll_obj.model_dump()
    await db.payroll_records.insert_one(doc)
    return payroll_obj

@api_router.get("/payroll", response_model=List[PayrollRecord])
async def get_payroll_records(employee_id: Optional[str] = None, month: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if month:
        query["month"] = month
    payroll_records = await db.payroll_records.find(query, {"_id": 0}).to_list(1000)
    return payroll_records

@api_router.put("/payroll/{payroll_id}", response_model=PayrollRecord)
async def update_payroll_record(payroll_id: str, payroll: PayrollRecordCreate):
    result = await db.payroll_records.update_one(
        {"id": payroll_id},
        {"$set": payroll.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Payroll record not found")
    updated_record = await db.payroll_records.find_one({"id": payroll_id}, {"_id": 0})
    return updated_record

# ============ PERFORMANCE ROUTES ============

@api_router.post("/performance-reviews", response_model=PerformanceReview)
async def create_performance_review(review: PerformanceReviewCreate):
    review_obj = PerformanceReview(**review.model_dump())
    doc = review_obj.model_dump()
    await db.performance_reviews.insert_one(doc)
    return review_obj

@api_router.get("/performance-reviews", response_model=List[PerformanceReview])
async def get_performance_reviews(employee_id: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    reviews = await db.performance_reviews.find(query, {"_id": 0}).to_list(1000)
    return reviews

@api_router.put("/performance-reviews/{review_id}", response_model=PerformanceReview)
async def update_performance_review(review_id: str, review: PerformanceReviewCreate):
    result = await db.performance_reviews.update_one(
        {"id": review_id},
        {"$set": review.model_dump()}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Performance review not found")
    updated_review = await db.performance_reviews.find_one({"id": review_id}, {"_id": 0})
    return updated_review

# ============ DOCUMENT ROUTES ============

@api_router.post("/documents/upload")
async def upload_document(file: UploadFile, entity_type: str, entity_id: str, document_type: str):
    file_data = await file.read()
    encoded_file = base64.b64encode(file_data).decode('utf-8')
    
    doc = DocumentUpload(
        entity_type=entity_type,
        entity_id=entity_id,
        document_type=document_type,
        file_name=file.filename,
        file_data=encoded_file
    )
    
    await db.documents.insert_one(doc.model_dump())
    return {"message": "Document uploaded successfully", "document_id": doc.id}

@api_router.get("/documents")
async def get_documents(entity_type: Optional[str] = None, entity_id: Optional[str] = None):
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    documents = await db.documents.find(query, {"_id": 0, "file_data": 0}).to_list(1000)
    return documents

@api_router.get("/documents/{document_id}/download")
async def download_document(document_id: str):
    document = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_data = base64.b64decode(document["file_data"])
    return StreamingResponse(
        io.BytesIO(file_data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={document['file_name']}"}
    )

# ============ ORGANIZATIONAL STRUCTURE ROUTES ============

# Departments
@api_router.post("/departments", response_model=Department)
async def create_department(dept: DepartmentCreate):
    dept_obj = Department(**dept.model_dump())
    await db.departments.insert_one(dept_obj.model_dump())
    return dept_obj

@api_router.get("/departments", response_model=List[Department])
async def get_departments():
    departments = await db.departments.find({}, {"_id": 0}).to_list(100)
    return departments

@api_router.put("/departments/{dept_id}", response_model=Department)
async def update_department(dept_id: str, dept: DepartmentCreate):
    await db.departments.update_one({"id": dept_id}, {"$set": dept.model_dump()})
    updated = await db.departments.find_one({"id": dept_id}, {"_id": 0})
    return updated

# Locations
@api_router.post("/locations", response_model=Location)
async def create_location(loc: LocationCreate):
    loc_obj = Location(**loc.model_dump())
    await db.locations.insert_one(loc_obj.model_dump())
    return loc_obj

@api_router.get("/locations", response_model=List[Location])
async def get_locations():
    locations = await db.locations.find({}, {"_id": 0}).to_list(100)
    return locations

# Designations
@api_router.post("/designations", response_model=Designation)
async def create_designation(desig: DesignationCreate):
    desig_obj = Designation(**desig.model_dump())
    await db.designations.insert_one(desig_obj.model_dump())
    return desig_obj

@api_router.get("/designations", response_model=List[Designation])
async def get_designations():
    designations = await db.designations.find({}, {"_id": 0}).to_list(100)
    return designations

# Org Chart
@api_router.get("/org-chart")
async def get_org_chart():
    employees = await db.employees.find({"status": "active"}, {"_id": 0}).to_list(1000)
    
    # Build hierarchical structure
    org_tree = []
    employee_map = {emp["id"]: emp for emp in employees}
    
    for emp in employees:
        emp_node = {
            "id": emp["id"],
            "name": f"{emp['first_name']} {emp['last_name']}",
            "position": emp["position"],
            "department": emp["department"],
            "manager_id": emp.get("manager_id"),
            "email": emp["email"],
            "children": []
        }
        
        if not emp.get("manager_id"):
            org_tree.append(emp_node)
    
    return {"org_tree": org_tree, "all_employees": employees}

# Employee Transfers
@api_router.post("/employee-transfers", response_model=EmployeeTransfer)
async def create_employee_transfer(transfer: EmployeeTransferCreate):
    transfer_obj = EmployeeTransfer(**transfer.model_dump())
    await db.employee_transfers.insert_one(transfer_obj.model_dump())
    return transfer_obj

@api_router.get("/employee-transfers", response_model=List[EmployeeTransfer])
async def get_employee_transfers(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    transfers = await db.employee_transfers.find(query, {"_id": 0}).to_list(100)
    return transfers

@api_router.put("/employee-transfers/{transfer_id}/approve")
async def approve_transfer(transfer_id: str):
    transfer = await db.employee_transfers.find_one({"id": transfer_id})
    if not transfer:
        raise HTTPException(404, "Transfer not found")
    
    # Update employee record
    await db.employees.update_one(
        {"id": transfer["employee_id"]},
        {"$set": {
            "department": transfer["to_department"],
            "position": transfer.get("to_designation", transfer["employee_id"])
        }}
    )
    
    # Update transfer status
    await db.employee_transfers.update_one(
        {"id": transfer_id},
        {"$set": {"status": "approved"}}
    )
    
    return {"message": "Transfer approved and applied"}

# ============ ENHANCED PAYROLL ROUTES ============

# Salary Structures
@api_router.post("/salary-structures", response_model=SalaryStructure)
async def create_salary_structure(structure: SalaryStructureCreate):
    # Calculate statutory deductions
    pf_employee = min(structure.basic_salary * 0.12, 1800)  # 12% capped at 15000 basic
    pf_employer = pf_employee
    
    # ESI applicable if gross < 21000
    gross = structure.basic_salary + structure.hra + structure.special_allowance
    esi_employee = gross * 0.0075 if gross < 21000 else 0
    esi_employer = gross * 0.0325 if gross < 21000 else 0
    
    # Professional Tax (state-specific, using sample)
    pt = 200 if gross > 15000 else 0
    
    structure_data = structure.model_dump()
    structure_data.update({
        "pf_employee": pf_employee,
        "pf_employer": pf_employer,
        "esi_employee": esi_employee,
        "esi_employer": esi_employer,
        "professional_tax": pt
    })
    
    structure_obj = SalaryStructure(**structure_data)
    await db.salary_structures.insert_one(structure_obj.model_dump())
    return structure_obj

@api_router.get("/salary-structures", response_model=List[SalaryStructure])
async def get_salary_structures(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    structures = await db.salary_structures.find(query, {"_id": 0}).to_list(100)
    return structures

# Loans & Advances
@api_router.post("/loans", response_model=LoanAdvance)
async def create_loan(loan: LoanAdvanceCreate):
    loan_data = loan.model_dump()
    loan_data["balance_amount"] = loan.amount
    loan_obj = LoanAdvance(**loan_data)
    await db.loans.insert_one(loan_obj.model_dump())
    return loan_obj

@api_router.get("/loans", response_model=List[LoanAdvance])
async def get_loans(employee_id: Optional[str] = None, status: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    loans = await db.loans.find(query, {"_id": 0}).to_list(100)
    return loans

# Reimbursements
@api_router.post("/reimbursements", response_model=Reimbursement)
async def create_reimbursement(reimb: ReimbursementCreate):
    reimb_obj = Reimbursement(**reimb.model_dump())
    await db.reimbursements.insert_one(reimb_obj.model_dump())
    return reimb_obj

@api_router.get("/reimbursements", response_model=List[Reimbursement])
async def get_reimbursements(employee_id: Optional[str] = None, status: Optional[str] = None):
    query = {}
    if employee_id:
        query["employee_id"] = employee_id
    if status:
        query["status"] = status
    reimbursements = await db.reimbursements.find(query, {"_id": 0}).to_list(100)
    return reimbursements

@api_router.put("/reimbursements/{reimb_id}/approve")
async def approve_reimbursement(reimb_id: str, approved_by: str):
    await db.reimbursements.update_one(
        {"id": reimb_id},
        {"$set": {
            "status": "approved",
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    return {"message": "Reimbursement approved"}

# Investment Declarations
@api_router.post("/investment-declarations", response_model=InvestmentDeclaration)
async def create_investment_declaration(declaration: InvestmentDeclarationCreate):
    decl_obj = InvestmentDeclaration(**declaration.model_dump())
    await db.investment_declarations.insert_one(decl_obj.model_dump())
    return decl_obj

@api_router.get("/investment-declarations", response_model=List[InvestmentDeclaration])
async def get_investment_declarations(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    declarations = await db.investment_declarations.find(query, {"_id": 0}).to_list(100)
    return declarations

# ============ ENHANCED ONBOARDING ROUTES ============

# Onboarding Templates
@api_router.post("/onboarding-templates", response_model=OnboardingTemplate)
async def create_onboarding_template(template: OnboardingTemplateCreate):
    template_obj = OnboardingTemplate(**template.model_dump())
    await db.onboarding_templates.insert_one(template_obj.model_dump())
    return template_obj

@api_router.get("/onboarding-templates", response_model=List[OnboardingTemplate])
async def get_onboarding_templates(department: Optional[str] = None):
    query = {"is_active": True}
    if department:
        query["department"] = department
    templates = await db.onboarding_templates.find(query, {"_id": 0}).to_list(100)
    return templates

# Equipment Assignments
@api_router.post("/equipment-assignments", response_model=EquipmentAssignment)
async def create_equipment_assignment(equipment: EquipmentAssignmentCreate):
    equip_obj = EquipmentAssignment(**equipment.model_dump())
    await db.equipment_assignments.insert_one(equip_obj.model_dump())
    return equip_obj

@api_router.get("/equipment-assignments", response_model=List[EquipmentAssignment])
async def get_equipment_assignments(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    equipment = await db.equipment_assignments.find(query, {"_id": 0}).to_list(100)
    return equipment

# Probation Reviews
@api_router.post("/probation-reviews", response_model=ProbationReview)
async def create_probation_review(review: ProbationReviewCreate):
    review_obj = ProbationReview(**review.model_dump())
    await db.probation_reviews.insert_one(review_obj.model_dump())
    return review_obj

@api_router.get("/probation-reviews", response_model=List[ProbationReview])
async def get_probation_reviews(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    reviews = await db.probation_reviews.find(query, {"_id": 0}).to_list(100)
    return reviews

# Training Modules
@api_router.post("/training-modules", response_model=TrainingModule)
async def create_training_module(module: TrainingModuleCreate):
    module_obj = TrainingModule(**module.model_dump())
    await db.training_modules.insert_one(module_obj.model_dump())
    return module_obj

@api_router.get("/training-modules", response_model=List[TrainingModule])
async def get_training_modules():
    modules = await db.training_modules.find({}, {"_id": 0}).to_list(100)
    return modules

# Training Assignments
@api_router.post("/training-assignments", response_model=TrainingAssignment)
async def create_training_assignment(assignment: TrainingAssignmentCreate):
    assign_obj = TrainingAssignment(**assignment.model_dump())
    await db.training_assignments.insert_one(assign_obj.model_dump())
    return assign_obj

@api_router.get("/training-assignments", response_model=List[TrainingAssignment])
async def get_training_assignments(employee_id: Optional[str] = None):
    query = {"employee_id": employee_id} if employee_id else {}
    assignments = await db.training_assignments.find(query, {"_id": 0}).to_list(100)
    return assignments

# ============ DASHBOARD/STATS ROUTES ============

@api_router.get("/dashboard/stats")
async def get_dashboard_stats():
    total_employees = await db.employees.count_documents({"status": "active"})
    pending_leaves = await db.leave_requests.count_documents({"status": "pending"})
    open_positions = await db.job_postings.count_documents({"status": "open"})
    pending_onboarding = await db.onboarding_tasks.count_documents({"status": "pending"})
    
    return {
        "total_employees": total_employees,
        "pending_leaves": pending_leaves,
        "open_positions": open_positions,
        "pending_onboarding_tasks": pending_onboarding
    }

@api_router.get("/dashboard/trends")
async def get_dashboard_trends(
    period: str = "week", 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
):
    """
    Get trend data for dashboard metrics over time
    period: 'day', 'week', 'month', or 'custom'
    start_date: for custom period (format: YYYY-MM-DD)
    end_date: for custom period (format: YYYY-MM-DD)
    """
    # Determine number of data points based on period
    if period == "custom" and start_date and end_date:
        # Custom date range
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            
            # Calculate number of days in the range
            days_diff = (end_dt - start_dt).days + 1
            
            if days_diff <= 0:
                raise HTTPException(status_code=400, detail="End date must be after start date")
            
            if days_diff > 365:
                raise HTTPException(status_code=400, detail="Date range cannot exceed 365 days")
            
            points = days_diff
            time_delta = timedelta(days=1)
            date_format = "%m/%d/%Y"
            now = end_dt
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    elif period == "day":
        points = 24  # hourly data for 24 hours
        time_delta = timedelta(hours=1)
        date_format = "%m/%d/%Y %H:%M"
        now = datetime.now(timezone.utc)
    elif period == "month":
        points = 30  # daily data for 30 days
        time_delta = timedelta(days=1)
        date_format = "%m/%d/%Y"
        now = datetime.now(timezone.utc)
    else:  # week
        points = 7  # daily data for 7 days
        time_delta = timedelta(days=1)
        date_format = "%m/%d/%Y"
        now = datetime.now(timezone.utc)
    
    # Get current values
    current_employees = await db.employees.count_documents({"status": "active"})
    current_leaves = await db.leave_requests.count_documents({"status": "pending"})
    current_positions = await db.job_postings.count_documents({"status": "open"})
    current_onboarding = await db.onboarding_tasks.count_documents({"status": "pending"})
    
    # Generate trend data (simulated historical data with realistic variations)
    import random
    trends = {
        "total_employees": [],
        "pending_leaves": [],
        "open_positions": [],
        "pending_onboarding_tasks": []
    }
    
    for i in range(points):
        timestamp = now - (time_delta * (points - i - 1))
        time_label = timestamp.strftime(date_format)
        
        # Generate realistic variations (current value ±20%)
        variation = 0.2
        
        # === EMPLOYEES (gradual increase trend) ===
        emp_base = current_employees - (points - i - 1) * 0.1
        emp_value = max(0, int(emp_base + random.uniform(-emp_base * 0.05, emp_base * 0.05)))
        
        # Generate employee changes (joined/left)
        emp_joined = random.randint(0, 3) if random.random() > 0.3 else 0
        emp_left = random.randint(0, 2) if random.random() > 0.5 else 0
        
        trends["total_employees"].append({
            "time": time_label, 
            "value": emp_value,
            "joined": emp_joined,
            "left": emp_left
        })
        
        # === LEAVE REQUESTS (fluctuating) ===
        leave_value = max(0, int(current_leaves + random.uniform(-current_leaves * variation, current_leaves * variation)))
        
        # Generate leave request changes (submitted/resolved)
        leave_submitted = random.randint(0, 5) if random.random() > 0.4 else 0
        leave_resolved = random.randint(0, 4) if random.random() > 0.5 else 0
        
        trends["pending_leaves"].append({
            "time": time_label, 
            "value": leave_value,
            "submitted": leave_submitted,
            "resolved": leave_resolved
        })
        
        # === POSITIONS (slightly decreasing) ===
        pos_base = current_positions + (points - i - 1) * 0.05
        pos_value = max(0, int(pos_base + random.uniform(-pos_base * 0.1, pos_base * 0.1)))
        
        # Generate position changes (opened/filled)
        pos_opened = random.randint(0, 2) if random.random() > 0.6 else 0
        pos_filled = random.randint(0, 2) if random.random() > 0.5 else 0
        
        trends["open_positions"].append({
            "time": time_label, 
            "value": pos_value,
            "opened": pos_opened,
            "filled": pos_filled
        })
        
        # === ONBOARDING TASKS (fluctuating) ===
        onb_value = max(0, int(current_onboarding + random.uniform(-current_onboarding * variation, current_onboarding * variation)))
        
        # Generate onboarding task changes (added/completed)
        tasks_added = random.randint(0, 4) if random.random() > 0.5 else 0
        tasks_completed = random.randint(0, 3) if random.random() > 0.5 else 0
        
        trends["pending_onboarding_tasks"].append({
            "time": time_label, 
            "value": onb_value,
            "added": tasks_added,
            "completed": tasks_completed
        })
    
    # Calculate percentage changes
    changes = {}
    for key in trends:
        if len(trends[key]) > 1:
            first_value = trends[key][0]["value"]
            last_value = trends[key][-1]["value"]
            if first_value > 0:
                change = ((last_value - first_value) / first_value) * 100
                changes[key] = round(change, 1)
            else:
                changes[key] = 0
        else:
            changes[key] = 0

    return {
        "trends": trends,
        "changes": changes,
        "period": period,
        "data_points": points
    }

# ============ MEETINGS & RECORDINGS HUB ROUTES ============

@api_router.get("/meetings/sync-status")
async def get_meetings_sync_status(current_user: dict = Depends(get_current_user)):
    """Get current sync status"""
    status = await db.meetings_sync_status.find_one({"_id": "main"}, {"_id": 0})
    if not status:
        return {
            "last_sync_attio": None,
            "last_sync_fireflies": None,
            "total_meetings": 0,
            "attio_count": 0,
            "fireflies_count": 0,
            "deduplicated_count": 0,
            "is_syncing": False
        }
    return status

@api_router.get("/meetings/connection-test")
async def test_meetings_connections(current_user: dict = Depends(get_current_user)):
    """Test connectivity to Attio and Fireflies APIs"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    results = {"attio": {}, "fireflies": {}}

    # Test Attio
    try:
        attio_result = await meetings_service.attio.search_meetings(limit=1)
        results["attio"] = {
            "status": "connected",
            "response_keys": list(attio_result.keys()) if isinstance(attio_result, dict) else str(type(attio_result)),
            "sample": str(attio_result)[:500]
        }
    except Exception as e:
        results["attio"] = {"status": "error", "error": str(e)}

    # Test Fireflies
    try:
        ff_user = await meetings_service.fireflies.get_user_info()
        results["fireflies"] = {
            "status": "connected",
            "user": ff_user
        }
    except Exception as e:
        results["fireflies"] = {"status": "error", "error": str(e)}

    return results

@api_router.post("/meetings/sync")
async def trigger_meetings_sync(
    background_tasks: BackgroundTasks,
    lookback_days: int = Query(90, description="Number of days to sync"),
    current_user: dict = Depends(get_current_user)
):
    """Trigger manual sync of meetings (admin only)"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Check if already syncing
    status = await db.meetings_sync_status.find_one({"_id": "main"})
    if status and status.get("is_syncing"):
        raise HTTPException(status_code=400, detail="Sync already in progress")
    
    # Run sync in background
    background_tasks.add_task(meetings_service.sync_meetings, lookback_days)
    
    return {"message": "Sync started in background", "lookback_days": lookback_days}

@api_router.get("/meetings")
async def get_meetings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    participant_email: Optional[str] = None,
    participant_name: Optional[str] = None,
    keyword: Optional[str] = None,
    source: Optional[str] = None,
    has_recording: Optional[bool] = None,
    has_action_items: Optional[bool] = None,
    has_video: Optional[bool] = None,
    sentiment: Optional[str] = None,
    host_email: Optional[str] = None,
    sort_by: str = "start_time",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get all meetings with filters"""
    query = {}
    
    # Build query
    if start_date:
        query["start_time"] = {"$gte": start_date}
    if end_date:
        if "start_time" in query:
            query["start_time"]["$lte"] = end_date
        else:
            query["start_time"] = {"$lte": end_date}
    
    if source and source != "all":
        if source == "both":
            query["source"] = "both"
        else:
            query["$or"] = [
                {"source": source},
                {"source": "both"}
            ]
    
    if participant_email:
        query["participants.email"] = {"$regex": participant_email, "$options": "i"}
    
    if participant_name:
        query["participants.name"] = {"$regex": participant_name, "$options": "i"}
    
    if keyword:
        query["$or"] = [
            {"title": {"$regex": keyword, "$options": "i"}},
            {"summary": {"$regex": keyword, "$options": "i"}},
            {"topics": {"$regex": keyword, "$options": "i"}}
        ]
    
    if has_recording is not None:
        query["has_recording"] = has_recording
    
    if has_action_items:
        query["action_items_count"] = {"$gt": 0}
    
    if has_video is not None:
        query["has_video"] = has_video
    
    if host_email:
        query["host_email"] = {"$regex": host_email, "$options": "i"}
    
    if sentiment:
        if sentiment == "positive":
            query["sentiment.positive"] = {"$gt": 50}
        elif sentiment == "negative":
            query["sentiment.negative"] = {"$gt": 30}
        elif sentiment == "neutral":
            query["sentiment.neutral"] = {"$gt": 50}
    
    # If not admin, filter by participation
    if current_user.get("role") != "admin":
        user_email = current_user.get("email")
        query["participants.email"] = user_email
    
    # Count total
    total = await db.meetings_cache.count_documents(query)
    
    # Sort
    sort_direction = -1 if sort_order == "desc" else 1
    
    # Get meetings
    meetings = await db.meetings_cache.find(query, {"_id": 0}) \
        .sort(sort_by, sort_direction) \
        .skip(offset) \
        .limit(limit) \
        .to_list(limit)
    
    return {
        "meetings": meetings,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@api_router.get("/meetings/attio")
async def get_attio_meetings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    linked_company: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get Attio-only meetings"""
    query = {
        "$or": [
            {"source": "attio"},
            {"source": "both", "attio_id": {"$exists": True}}
        ]
    }
    
    if start_date:
        query["start_time"] = {"$gte": start_date}
    if end_date:
        if "start_time" in query:
            query["start_time"]["$lte"] = end_date
        else:
            query["start_time"] = {"$lte": end_date}
    
    if linked_company:
        query["linked_companies"] = linked_company
    
    # If not admin, filter by participation
    if current_user.get("role") != "admin":
        query["participants.email"] = current_user.get("email")
    
    total = await db.meetings_cache.count_documents(query)
    meetings = await db.meetings_cache.find(query, {"_id": 0}) \
        .sort("start_time", -1) \
        .skip(offset) \
        .limit(limit) \
        .to_list(limit)
    
    return {
        "meetings": meetings,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@api_router.get("/meetings/fireflies")
async def get_fireflies_meetings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    host_email: Optional[str] = None,
    sentiment: Optional[str] = None,
    has_video: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get Fireflies-only meetings"""
    query = {
        "$or": [
            {"source": "fireflies"},
            {"source": "both", "fireflies_id": {"$exists": True}}
        ]
    }
    
    if start_date:
        query["start_time"] = {"$gte": start_date}
    if end_date:
        if "start_time" in query:
            query["start_time"]["$lte"] = end_date
        else:
            query["start_time"] = {"$lte": end_date}
    
    if host_email:
        query["host_email"] = {"$regex": host_email, "$options": "i"}
    
    if sentiment:
        if sentiment == "positive":
            query["sentiment.positive"] = {"$gt": 50}
        elif sentiment == "negative":
            query["sentiment.negative"] = {"$gt": 30}
    
    if has_video is not None:
        query["has_video"] = has_video
    
    # If not admin, filter by participation
    if current_user.get("role") != "admin":
        query["participants.email"] = current_user.get("email")
    
    total = await db.meetings_cache.count_documents(query)
    meetings = await db.meetings_cache.find(query, {"_id": 0}) \
        .sort("start_time", -1) \
        .skip(offset) \
        .limit(limit) \
        .to_list(limit)
    
    return {
        "meetings": meetings,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@api_router.get("/meetings/action-items")
async def get_action_items(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get all action items from meetings"""
    query = {}

    if status:
        query["status"] = status

    if assigned_to:
        query["assigned_to"] = assigned_to

    if current_user.get("role") != "admin":
        query["assigned_to"] = current_user.get("email")

    total = await db.meeting_action_items.count_documents(query)
    items = await db.meeting_action_items.find(query, {"_id": 0}) \
        .sort("created_at", -1) \
        .skip(offset) \
        .limit(limit) \
        .to_list(limit)

    return {
        "action_items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@api_router.patch("/meetings/action-items/{item_id}")
async def update_action_item_status(
    item_id: str,
    status: str,
    current_user: dict = Depends(get_current_user)
):
    """Update action item status"""
    item = await db.meeting_action_items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Action item not found")

    if current_user.get("role") != "admin":
        if item.get("assigned_to") != current_user.get("email"):
            raise HTTPException(status_code=403, detail="Access denied")

    await db.meeting_action_items.update_one(
        {"id": item_id},
        {"$set": {"status": status}}
    )

    updated_item = await db.meeting_action_items.find_one({"id": item_id}, {"_id": 0})
    return updated_item

@api_router.get("/meetings/search")
async def search_meetings(
    q: str,
    semantic: bool = False,
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """Global search across meetings"""
    query = {
        "$or": [
            {"title": {"$regex": q, "$options": "i"}},
            {"summary": {"$regex": q, "$options": "i"}},
            {"participants.name": {"$regex": q, "$options": "i"}},
            {"participants.email": {"$regex": q, "$options": "i"}},
            {"topics": {"$regex": q, "$options": "i"}}
        ]
    }

    if current_user.get("role") != "admin":
        query["participants.email"] = current_user.get("email")

    meetings = await db.meetings_cache.find(query, {"_id": 0}) \
        .sort("start_time", -1) \
        .limit(limit) \
        .to_list(limit)

    return {
        "results": meetings,
        "query": q,
        "count": len(meetings)
    }

@api_router.get("/meetings/{meeting_id}/transcript")
async def get_meeting_transcript(
    meeting_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get full transcript for a meeting (fetched on-demand)"""
    meeting = await db.meetings_cache.find_one({"id": meeting_id}, {"_id": 0})
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if current_user.get("role") != "admin":
        user_email = current_user.get("email")
        participant_emails = [p.get("email") for p in meeting.get("participants", [])]
        if user_email not in participant_emails:
            raise HTTPException(status_code=403, detail="Access denied")

    transcript = await meetings_service.get_transcript(meeting_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not available")

    return transcript.model_dump()

@api_router.get("/employees/{employee_id}/meetings")
async def get_employee_meetings(
    employee_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get all meetings for a specific employee"""
    employee = await db.employees.find_one({"id": employee_id}, {"_id": 0})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    if current_user.get("role") != "admin" and current_user.get("id") != employee_id:
        raise HTTPException(status_code=403, detail="Access denied")

    employee_email = employee.get("email")

    query = {"participants.email": employee_email}
    total = await db.meetings_cache.count_documents(query)
    meetings = await db.meetings_cache.find(query, {"_id": 0}) \
        .sort("start_time", -1) \
        .skip(offset) \
        .limit(limit) \
        .to_list(limit)

    total_meetings = len(meetings)
    total_duration = sum(m.get("duration_minutes", 0) for m in meetings)

    partner_counts = {}
    for meeting in meetings:
        for p in meeting.get("participants", []):
            if p.get("email") != employee_email:
                partner_email = p.get("email")
                if partner_email:
                    partner_counts[partner_email] = partner_counts.get(partner_email, 0) + 1

    top_partners = sorted(partner_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "meetings": meetings,
        "total": total,
        "stats": {
            "total_meetings": total_meetings,
            "total_duration_minutes": total_duration,
            "avg_duration_minutes": total_duration // total_meetings if total_meetings > 0 else 0,
            "top_meeting_partners": [{"email": email, "count": count} for email, count in top_partners]
        }
    }


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
