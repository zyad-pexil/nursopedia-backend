from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json

# NOTE:
# - For SQLite, Numeric maps to DECIMAL and works fine
# - For MySQL (PyMySQL), Enums are created as ENUM types
# - Payment receipts will be stored in DB via a new model below

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    user_type = db.Column(db.Enum('student', 'admin', name='user_types'), default='student')
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    password_reset_token = db.Column(db.String(255))
    password_reset_expires = db.Column(db.DateTime)

    # Single active session support
    current_session_id = db.Column(db.String(64))  # nullable; set on login
    
    # Relationships
    subscription_requests = db.relationship('SubscriptionRequest', foreign_keys='SubscriptionRequest.user_id', backref='user', lazy=True)
    active_subscriptions = db.relationship('ActiveSubscription', backref='user', lazy=True)
    lesson_progress = db.relationship('LessonProgress', backref='user', lazy=True)
    exam_attempts = db.relationship('ExamAttempt', backref='user', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'phone_number': self.phone_number,
            'user_type': self.user_type,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class AcademicYear(db.Model):
    __tablename__ = 'academic_years'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    subjects = db.relationship('Subject', backref='academic_year', lazy=True)
    subscription_requests = db.relationship('SubscriptionRequest', backref='academic_year', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Subject(db.Model):
    __tablename__ = 'subjects'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    lessons = db.relationship('Lesson', backref='subject', lazy=True)
    active_subscriptions = db.relationship('ActiveSubscription', backref='subject', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'academic_year_id': self.academic_year_id,
            'price': float(self.price or 0),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Lesson(db.Model):
    __tablename__ = 'lessons'
    
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    video_url = db.Column(db.String(500))
    video_duration = db.Column(db.Integer)  # in seconds
    attachments = db.Column(db.Text)  # JSON string
    lesson_order = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    exams = db.relationship('Exam', backref='lesson', lazy=True)
    lesson_progress = db.relationship('LessonProgress', backref='lesson', lazy=True)

    def get_attachments(self):
        if self.attachments:
            return json.loads(self.attachments)
        return []

    def set_attachments(self, attachments_list):
        self.attachments = json.dumps(attachments_list)

    def to_dict(self):
        return {
            'id': self.id,
            'subject_id': self.subject_id,
            'title': self.title,
            'description': self.description,
            'video_url': self.video_url,
            'video_duration': self.video_duration,
            'attachments': self.get_attachments(),
            'lesson_order': self.lesson_order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Exam(db.Model):
    __tablename__ = 'exams'
    
    id = db.Column(db.Integer, primary_key=True)
    # Either subject-level exam (subject_id) or lesson-level exam (lesson_id)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration_minutes = db.Column(db.Integer, nullable=False)
    max_attempts = db.Column(db.Integer, default=3)
    passing_score = db.Column(db.Numeric(5, 2), default=60.00)
    show_results_immediately = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    questions = db.relationship('ExamQuestion', backref='exam', lazy=True)
    attempts = db.relationship('ExamAttempt', backref='exam', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'subject_id': self.subject_id,
            'lesson_id': self.lesson_id,
            'title': self.title,
            'description': self.description,
            'duration_minutes': self.duration_minutes,
            'max_attempts': self.max_attempts,
            'passing_score': float(self.passing_score),
            'show_results_immediately': self.show_results_immediately,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ExamQuestion(db.Model):
    __tablename__ = 'exam_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500), nullable=False)
    option_b = db.Column(db.String(500), nullable=False)
    option_c = db.Column(db.String(500), nullable=False)
    option_d = db.Column(db.String(500), nullable=False)
    correct_answer = db.Column(db.Enum('A', 'B', 'C', 'D', name='answer_options'), nullable=False)
    question_order = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Numeric(5, 2), default=1.00)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    answers = db.relationship('ExamAnswer', backref='question', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'question_text': self.question_text,
            'option_a': self.option_a,
            'option_b': self.option_b,
            'option_c': self.option_c,
            'option_d': self.option_d,
            'correct_answer': self.correct_answer,
            'question_order': self.question_order,
            'points': float(self.points),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class SubscriptionRequest(db.Model):
    __tablename__ = 'subscription_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    academic_year_id = db.Column(db.Integer, db.ForeignKey('academic_years.id'), nullable=False)
    selected_subjects = db.Column(db.Text, nullable=False)  # JSON string
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_receipt_url = db.Column(db.String(500))  # Legacy field kept for compatibility
    status = db.Column(db.Enum('pending', 'approved', 'rejected', name='request_status'), default='pending')
    admin_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    active_subscriptions = db.relationship('ActiveSubscription', backref='subscription_request', lazy=True)
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_requests')
    receipts = db.relationship('PaymentReceipt', backref='subscription_request', lazy=True, cascade='all, delete-orphan')

    def get_selected_subjects(self):
        if self.selected_subjects:
            return json.loads(self.selected_subjects)
        return []

    def set_selected_subjects(self, subjects_list):
        self.selected_subjects = json.dumps(subjects_list)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'academic_year_id': self.academic_year_id,
            'selected_subjects': self.get_selected_subjects(),
            'total_amount': float(self.total_amount),
            'payment_receipt_url': self.payment_receipt_url,
            'status': self.status,
            'admin_notes': self.admin_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'reviewed_by': self.reviewed_by
        }

class ActiveSubscription(db.Model):
    __tablename__ = 'active_subscriptions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    subscription_request_id = db.Column(db.Integer, db.ForeignKey('subscription_requests.id'), nullable=True)
    start_date = db.Column(db.DateTime, default=datetime.utcnow)
    end_date = db.Column(db.DateTime)  # Can be NULL for lifetime subscriptions
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'subject_id': self.subject_id,
            'subscription_request_id': self.subscription_request_id,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class LessonProgress(db.Model):
    __tablename__ = 'lesson_progress'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lessons.id'), nullable=False)
    watch_time_seconds = db.Column(db.Integer, default=0)
    completion_percentage = db.Column(db.Numeric(5, 2), default=0.00)
    is_completed = db.Column(db.Boolean, default=False)
    first_accessed_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_accessed_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'lesson_id': self.lesson_id,
            'watch_time_seconds': self.watch_time_seconds,
            'completion_percentage': float(self.completion_percentage),
            'is_completed': self.is_completed,
            'first_accessed_at': self.first_accessed_at.isoformat() if self.first_accessed_at else None,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None
        }

class ExamAttempt(db.Model):
    __tablename__ = 'exam_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    attempt_number = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    score = db.Column(db.Numeric(5, 2))
    total_points = db.Column(db.Numeric(5, 2), nullable=False)
    percentage = db.Column(db.Numeric(5, 2))
    is_passed = db.Column(db.Boolean)
    is_completed = db.Column(db.Boolean, default=False)
    time_taken_seconds = db.Column(db.Integer)
    
    # Relationships
    answers = db.relationship('ExamAnswer', backref='attempt', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'exam_id': self.exam_id,
            'attempt_number': self.attempt_number,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'score': float(self.score) if self.score else None,
            'total_points': float(self.total_points),
            'percentage': float(self.percentage) if self.percentage else None,
            'is_passed': self.is_passed,
            'is_completed': self.is_completed,
            'time_taken_seconds': self.time_taken_seconds
        }

class ExamAnswer(db.Model):
    __tablename__ = 'exam_answers'
    
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('exam_attempts.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('exam_questions.id'), nullable=False)
    selected_answer = db.Column(db.Enum('A', 'B', 'C', 'D', name='selected_options'), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    answered_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'attempt_id': self.attempt_id,
            'question_id': self.question_id,
            'selected_answer': self.selected_answer,
            'is_correct': self.is_correct,
            'answered_at': self.answered_at.isoformat() if self.answered_at else None
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.Enum('subscription_approved', 'subscription_rejected', 'new_lesson', 'new_exam', 'exam_result', name='notification_types'), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'description': self.description,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PaymentReceipt(db.Model):
    __tablename__ = 'payment_receipts'

    id = db.Column(db.Integer, primary_key=True)
    subscription_request_id = db.Column(db.Integer, db.ForeignKey('subscription_requests.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(100), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)  # Stored in DB (MySQL MEDIUMBLOB/LONGBLOB depending on size)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_meta(self):
        return {
            'id': self.id,
            'subscription_request_id': self.subscription_request_id,
            'user_id': self.user_id,
            'filename': self.filename,
            'content_type': self.content_type,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


class AdditionalSubjectRequest(db.Model):
    __tablename__ = 'additional_subject_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    receipt_url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.Enum('pending', 'approved', 'rejected', name='add_request_status'), default='pending')
    admin_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    subject = db.relationship('Subject', foreign_keys=[subject_id])
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'subject_id': self.subject_id,
            'receipt_url': self.receipt_url,
            'status': self.status,
            'admin_notes': self.admin_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'reviewed_by': self.reviewed_by,
        }


class Question(db.Model):
    __tablename__ = 'questions'
    
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exams.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.Enum('multiple_choice', 'true_false', 'short_answer', name='question_types'), default='multiple_choice')
    order = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    answers = db.relationship('Answer', backref='question', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Question {self.id}: {self.question_text[:50]}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'exam_id': self.exam_id,
            'question_text': self.question_text,
            'question_type': self.question_type,
            'order': self.order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Answer(db.Model):
    __tablename__ = 'answers'
    
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False)
    order = db.Column(db.Integer, default=1)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Answer {self.id}: {self.answer_text[:30]}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'question_id': self.question_id,
            'answer_text': self.answer_text,
            'is_correct': self.is_correct,
            'order': self.order,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

