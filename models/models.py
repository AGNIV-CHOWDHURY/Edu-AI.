from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    students = db.relationship('Student', backref='teacher', lazy=True)
    # role differentiator
    role = db.Column(db.String(20), default='teacher')


class StudentUser(UserMixin, db.Model):
    """Login account for a student — linked to the Student record."""
    __tablename__ = 'student_users'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref=db.backref('account', uselist=False))

    def get_id(self):
        # Prefix so flask-login can distinguish teacher vs student sessions
        return f"student:{self.id}"

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    marks = db.Column(db.Float, nullable=False)
    attendance = db.Column(db.Float, nullable=False)
    assignments = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(20))
    reason = db.Column(db.Text)
    weak_areas = db.Column(db.Text)
    suggestions = db.Column(db.Text)
    study_plan = db.Column(db.Text)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    pinecone_id = db.Column(db.String(100))
    subject_marks = db.Column(db.Text)  # JSON: {"Math": 72, "Science": 55, ...}

class ReportCardAnalysis(db.Model):
    __tablename__ = 'report_analyses'
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100))
    filename = db.Column(db.String(200))
    analysis = db.Column(db.Text)
    grade_level = db.Column(db.String(20))
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Feature 1: Resource Recommendations per student
class ResourceRecommendation(db.Model):
    __tablename__ = 'resource_recommendations'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recommendations = db.Column(db.Text)  # JSON: [{type, title, url, reason}]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref='resource_recs')

# Feature 2: Resource Budget Plan (teacher attention hours)
class ResourceBudgetPlan(db.Model):
    __tablename__ = 'resource_budget_plans'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_name = db.Column(db.String(200))
    total_hours = db.Column(db.Float, default=10.0)
    allocations = db.Column(db.Text)  # JSON: [{student_id, name, hours, priority, rationale}]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Feature 3: Intervention Groups (clustered weak students)
class InterventionGroup(db.Model):
    __tablename__ = 'intervention_groups'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_name = db.Column(db.String(200))
    focus_area = db.Column(db.String(200))
    student_ids = db.Column(db.Text)  # JSON list of student IDs
    session_plan = db.Column(db.Text)  # AI-generated group session plan
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Feature 5: Scheduled Video Classes
class VideoClass(db.Model):
    __tablename__ = 'video_classes'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    duration_minutes = db.Column(db.Integer, default=60)
    room_url = db.Column(db.String(500))   # Daily.co room URL
    room_name = db.Column(db.String(200))  # Daily.co room name (for host token)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    teacher = db.relationship('User', backref='video_classes')

# Feature 6: AI Study Notes per subject
class StudyNote(db.Model):
    __tablename__ = 'study_notes'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20))           # Weak / Average / Strong
    notes_content = db.Column(db.Text)            # AI-generated markdown notes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref='study_notes')

# Feature 7: Resource Feedback for smart re-recommendation
class ResourceFeedback(db.Model):
    __tablename__ = 'resource_feedback'
    id = db.Column(db.Integer, primary_key=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey('resource_recommendations.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    feedback_json = db.Column(db.Text)   # JSON: [{subject, type, title, worked: true/false}]
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    recommendation = db.relationship('ResourceRecommendation', backref=db.backref('feedback', uselist=False))

# Feature 4: Progress / Re-assessment tracking
class ProgressCheckpoint(db.Model):
    __tablename__ = 'progress_checkpoints'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    marks = db.Column(db.Float)
    attendance = db.Column(db.Float)
    assignments = db.Column(db.Float)
    category = db.Column(db.String(20))
    notes = db.Column(db.Text)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student', backref='checkpoints')
