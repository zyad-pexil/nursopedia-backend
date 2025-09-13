from flask import Blueprint, jsonify, request, current_app
from flask_cors import cross_origin
from src.models.user import (
    db, User, Subject, Lesson, Exam, Question, Answer, 
    SubscriptionRequest, ActiveSubscription, AcademicYear,
    LessonProgress, ExamAttempt, ExamAnswer, ExamQuestion, Notification,
    AdditionalSubjectRequest
)
from datetime import datetime
import jwt
import os
import json
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__)

# Helper function to verify JWT token
def verify_token(token):
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload  # return payload to check session id
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Decorator to require admin authentication
def require_admin(f):
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'رمز المصادقة مطلوب'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        payload = verify_token(token)
        if not payload:
            return jsonify({'success': False, 'message': 'رمز المصادقة غير صالح'}), 401
        
        user = User.query.get(payload.get('user_id'))
        if not user or not user.is_active or user.user_type != 'admin':
            return jsonify({'success': False, 'message': 'ليس لديك صلاحية الوصول لهذه الصفحة'}), 403
        
        # Enforce single active session for admin as well
        token_sid = payload.get('sid')
        if user.current_session_id and token_sid != user.current_session_id:
            return jsonify({'success': False, 'message': 'تم تسجيل دخول هذا الحساب من جهاز آخر. الرجاء تسجيل الدخول مجدداً.'}), 401
        
        request.current_user = user
        return f(*args, **kwargs)
    
    decorated_function.__name__ = f.__name__
    return decorated_function

# Dashboard Statistics
@admin_bp.route('/dashboard/stats', methods=['GET'])
@cross_origin()
@require_admin
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        # Count statistics
        total_students = User.query.filter_by(user_type='student').count()
        active_students = User.query.filter_by(user_type='student', is_active=True).count()
        pending_requests = SubscriptionRequest.query.filter_by(status='pending').count()
        total_subjects = Subject.query.filter_by(is_active=True).count()
        total_lessons = Lesson.query.filter_by(is_active=True).count()
        total_exams = Exam.query.filter_by(is_active=True).count()
        
        # Revenue calculation (approved subscriptions)
        approved_requests = SubscriptionRequest.query.filter_by(status='approved').all()
        # Safely sum amounts and avoid None/Decimal issues
        total_revenue = sum(float(req.total_amount or 0) for req in approved_requests)
        
        # Recent activities
        recent_registrations = User.query.filter_by(user_type='student').order_by(
            User.created_at.desc()
        ).limit(5).all()
        
        recent_requests = SubscriptionRequest.query.order_by(
            SubscriptionRequest.created_at.desc()
        ).limit(5).all()
        
        from flask import current_app
        zero = getattr(current_app.config, 'DASHBOARD_ZERO_COUNTS', False) or current_app.config.get('DASHBOARD_ZERO_COUNTS', False)
        return jsonify({
            'success': True,
            'stats': {
                'total_students': 0 if zero else total_students,
                'active_students': 0 if zero else active_students,
                'pending_requests': pending_requests,
                'total_subjects': total_subjects,
                'total_lessons': total_lessons,
                'total_exams': total_exams,
                'total_revenue': 0.0 if zero else float(total_revenue)
            },
            'recent_activities': {
                'registrations': [
                    {
                        'id': u.id,
                        'full_name': u.full_name,
                        'username': u.username,
                        'created_at': u.created_at.isoformat() if u.created_at else None,
                        'is_active': u.is_active
                    }
                    for u in recent_registrations
                ],
                'subscription_requests': [
                    {
                        'id': r.id,
                        'user_name': r.user.full_name if r.user else None,
                        'total_amount': float(r.total_amount or 0),
                        'status': r.status,
                        'created_at': r.created_at.isoformat() if r.created_at else None
                    }
                    for r in recent_requests
                ]
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

# Student Management
@admin_bp.route('/students', methods=['GET'])
@cross_origin()
@require_admin
def get_all_students():
    """Get all students with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        search = request.args.get('search', '')
        
        query = User.query.filter_by(user_type='student')
        
        if search:
            query = query.filter(
                db.or_(
                    User.full_name.contains(search),
                    User.username.contains(search),
                    User.email.contains(search)
                )
            )
        
        students = query.order_by(User.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        students_data = []
        for student in students.items:
            student_data = student.to_dict()
            
            # Get active subscriptions
            active_subs = ActiveSubscription.query.filter_by(
                user_id=student.id, is_active=True
            ).count()
            
            student_data['active_subscriptions'] = active_subs
            students_data.append(student_data)
        
        return jsonify({
            'success': True,
            'students': students_data,
            'pagination': {
                'page': students.page,
                'pages': students.pages,
                'per_page': students.per_page,
                'total': students.total,
                'has_next': students.has_next,
                'has_prev': students.has_prev
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@admin_bp.route('/students/<int:student_id>/toggle-status', methods=['POST'])
@cross_origin()
@require_admin
def toggle_student_status(student_id):
    """Activate or deactivate a student"""
    try:
        student = User.query.get_or_404(student_id)
        
        if student.user_type != 'student':
            return jsonify({
                'success': False,
                'message': 'المستخدم ليس طالباً'
            }), 400
        
        student.is_active = not student.is_active
        student.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        action = 'تفعيل' if student.is_active else 'إلغاء تفعيل'
        
        return jsonify({
            'success': True,
            'message': f'تم {action} الطالب بنجاح',
            'is_active': student.is_active
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

# Additional Subject Requests Management
@admin_bp.route('/additional-subject-requests', methods=['GET'])
@cross_origin()
@require_admin
def list_additional_subject_requests():
    status = request.args.get('status', 'pending')
    query = AdditionalSubjectRequest.query
    if status != 'all':
        query = query.filter_by(status=status)
    rows = query.order_by(AdditionalSubjectRequest.created_at.desc()).all()
    out = []
    for r in rows:
        d = r.to_dict()
        d['user_name'] = r.reviewer.full_name if r.reviewer else None
        subj = Subject.query.get(r.subject_id)
        d['subject'] = {'id': subj.id, 'name': subj.name, 'price': float(subj.price)} if subj else None
        student = User.query.get(r.user_id)
        d['student'] = {'id': student.id, 'name': student.full_name, 'username': student.username} if student else None
        out.append(d)
    return jsonify({'success': True, 'requests': out})

@admin_bp.route('/additional-subject-requests/<int:req_id>/approve', methods=['POST'])
@cross_origin()
@require_admin
def approve_additional_subject_request(req_id):
    admin = request.current_user
    req = AdditionalSubjectRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'success': False, 'message': 'تمت مراجعة الطلب مسبقاً'}), 400

    # Create ActiveSubscription if not exists
    existing = ActiveSubscription.query.filter_by(user_id=req.user_id, subject_id=req.subject_id).first()
    if not existing:
        # Create a light SubscriptionRequest record to maintain FK integrity
        sr = SubscriptionRequest(
            user_id=req.user_id,
            academic_year_id=Subject.query.get(req.subject_id).academic_year_id if Subject.query.get(req.subject_id) else None,
            selected_subjects=json.dumps([req.subject_id]),
            total_amount=0,
            status='approved',
            created_at=datetime.utcnow(),
            reviewed_at=datetime.utcnow(),
            reviewed_by=admin.id,
        )
        db.session.add(sr)
        db.session.flush()  # get sr.id

        active = ActiveSubscription(
            user_id=req.user_id,
            subject_id=req.subject_id,
            subscription_request_id=sr.id,
            is_active=True
        )
        db.session.add(active)

    req.status = 'approved'
    req.reviewed_at = datetime.utcnow()
    req.reviewed_by = admin.id

    # Notify student
    try:
        note = Notification(
            user_id=req.user_id,
            title='تم قبول طلب إضافة مادة',
            description='تمت الموافقة على طلبك لإضافة المادة.'
        )
        db.session.add(note)
    except Exception:
        pass

    db.session.commit()
    return jsonify({'success': True, 'message': 'تم قبول الطلب وإضافة المادة'}), 200

@admin_bp.route('/additional-subject-requests/<int:req_id>/reject', methods=['POST'])
@cross_origin()
@require_admin
def reject_additional_subject_request(req_id):
    admin = request.current_user
    req = AdditionalSubjectRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'success': False, 'message': 'تمت مراجعة الطلب مسبقاً'}), 400

    data = request.get_json(silent=True) or {}
    req.status = 'rejected'
    req.reviewed_at = datetime.utcnow()
    req.reviewed_by = admin.id
    req.admin_notes = data.get('notes', '')

    # Notify student
    try:
        note = Notification(
            user_id=req.user_id,
            title='تم رفض طلب إضافة مادة',
            description=req.admin_notes or 'نأسف، تم رفض الطلب.'
        )
        db.session.add(note)
    except Exception:
        pass

    db.session.commit()
    return jsonify({'success': True, 'message': 'تم رفض الطلب'}), 200

# Subscription Request Management
@admin_bp.route('/subscription-requests', methods=['GET'])
@cross_origin()
@require_admin
def get_subscription_requests():
    """Get all subscription requests"""
    try:
        status = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        search = request.args.get('search', '', type=str)
        
        query = SubscriptionRequest.query
        
        if status != 'all':
            query = query.filter_by(status=status)
        
        if search:
            # Filter by user info when a search term is provided
            query = query.join(User, SubscriptionRequest.user_id == User.id).filter(
                db.or_(
                    User.full_name.ilike(f"%{search}%"),
                    User.username.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%"),
                    User.phone_number.ilike(f"%{search}%")
                )
            )
        
        requests = query.order_by(SubscriptionRequest.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        requests_data = []
        for req in requests.items:
            req_data = req.to_dict()
            # Include username and other user details for UI
            req_data['username'] = req.user.username
            req_data['user_name'] = req.user.full_name
            req_data['user_email'] = req.user.email
            req_data['user_phone'] = req.user.phone_number
            
            # Get selected subjects
            selected_subjects = req.get_selected_subjects()
            if selected_subjects:
                subjects = Subject.query.filter(Subject.id.in_(selected_subjects)).all()
                req_data['selected_subjects'] = [
                    {'id': s.id, 'name': s.name, 'price': float(s.price)}
                    for s in subjects
                ]
            else:
                req_data['selected_subjects'] = []
            
            requests_data.append(req_data)
        
        return jsonify({
            'success': True,
            'requests': requests_data,
            'pagination': {
                'page': requests.page,
                'pages': requests.pages,
                'per_page': requests.per_page,
                'total': requests.total,
                'has_next': requests.has_next,
                'has_prev': requests.has_prev
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@admin_bp.route('/subscription-requests/<int:request_id>/approve', methods=['POST'])
@cross_origin()
@require_admin
def approve_subscription_request(request_id):
    """Approve a subscription request"""
    try:
        admin = request.current_user
        data = request.get_json()
        
        subscription_request = SubscriptionRequest.query.get_or_404(request_id)
        
        if subscription_request.status != 'pending':
            return jsonify({
                'success': False,
                'message': 'هذا الطلب تم مراجعته مسبقاً'
            }), 400
        
        # Update request status
        subscription_request.status = 'approved'
        subscription_request.reviewed_at = datetime.utcnow()
        subscription_request.reviewed_by = admin.id
        subscription_request.admin_notes = data.get('notes', '')
        
        # Activate the student
        student = subscription_request.user
        student.is_active = True
        student.updated_at = datetime.utcnow()
        
        # Create active subscriptions for selected subjects
        selected_subjects = subscription_request.get_selected_subjects()
        if selected_subjects:
            for subject_id in selected_subjects:
                # Check if subscription already exists
                existing_sub = ActiveSubscription.query.filter_by(
                    user_id=student.id,
                    subject_id=subject_id
                ).first()
                
                if not existing_sub:
                    active_sub = ActiveSubscription(
                        user_id=student.id,
                        subject_id=subject_id,
                        subscription_request_id=subscription_request.id,
                        is_active=True
                    )
                    db.session.add(active_sub)
        
        # Create notification for student
        notification = Notification(
            user_id=student.id,
            title='تم قبول طلب الاشتراك',
            message='تم قبول طلب اشتراكك وتفعيل حسابك. يمكنك الآن الوصول إلى المواد التعليمية.',
            type='subscription_approved',
            is_read=False
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم قبول الطلب وتفعيل الطالب بنجاح'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@admin_bp.route('/subscription-requests/<int:request_id>/reject', methods=['POST'])
@cross_origin()
@require_admin
def reject_subscription_request(request_id):
    """Reject a subscription request"""
    try:
        admin = request.current_user
        data = request.get_json()
        
        subscription_request = SubscriptionRequest.query.get_or_404(request_id)
        
        if subscription_request.status != 'pending':
            return jsonify({
                'success': False,
                'message': 'هذا الطلب تم مراجعته مسبقاً'
            }), 400
        
        # Update request status
        subscription_request.status = 'rejected'
        subscription_request.reviewed_at = datetime.utcnow()
        subscription_request.reviewed_by = admin.id
        subscription_request.admin_notes = data.get('notes', 'تم رفض الطلب')
        
        # Create notification for student
        notification = Notification(
            user_id=subscription_request.user_id,
            title='تم رفض طلب الاشتراك',
            message=f'تم رفض طلب اشتراكك. السبب: {subscription_request.admin_notes}',
            type='subscription_rejected',
            is_read=False
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم رفض الطلب'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

# Content Management
@admin_bp.route('/subjects', methods=['GET'])
@cross_origin()
@require_admin
def get_admin_subjects():
    """Get all subjects for admin management"""
    try:
        subjects = Subject.query.order_by(Subject.academic_year_id.asc(), Subject.name.asc()).all()
        
        subjects_data = []
        for subject in subjects:
            subject_data = subject.to_dict()
            
            # Count lessons and exams
            lessons_count = Lesson.query.filter_by(subject_id=subject.id, is_active=True).count()
            exams_count = db.session.query(Exam).join(Lesson, Exam.lesson_id == Lesson.id) \
                .filter(Lesson.subject_id == subject.id, Exam.is_active == True).count()
            
            # Count active subscriptions
            active_subs = ActiveSubscription.query.filter_by(subject_id=subject.id, is_active=True).count()
            
            subject_data['lessons_count'] = lessons_count
            subject_data['exams_count'] = exams_count
            subject_data['active_subscriptions'] = active_subs
            
            subjects_data.append(subject_data)
        
        return jsonify({
            'success': True,
            'subjects': subjects_data
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@admin_bp.route('/subjects', methods=['POST'])
@cross_origin()
@require_admin
def create_subject():
    """Create a new subject"""
    try:
        data = request.get_json()
        
        required_fields = ['name', 'description', 'academic_year_id', 'price']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'message': f'الحقل {field} مطلوب'
                }), 400
        
        # Check if subject already exists
        existing_subject = Subject.query.filter_by(
            name=data['name'],
            academic_year_id=data['academic_year_id']
        ).first()
        
        if existing_subject:
            return jsonify({
                'success': False,
                'message': 'المادة موجودة بالفعل في هذه الفرقة'
            }), 400
        
        subject = Subject(
            name=data['name'],
            description=data['description'],
            academic_year_id=data['academic_year_id'],
            price=data['price'],
            is_active=data.get('is_active', True)
        )
        
        db.session.add(subject)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم إنشاء المادة بنجاح',
            'subject': subject.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

# Lessons Management
@admin_bp.route('/subjects/<int:subject_id>/lessons', methods=['GET'])
@cross_origin()
@require_admin
def get_lessons(subject_id):
    try:
        lessons = Lesson.query.filter_by(subject_id=subject_id).order_by(Lesson.lesson_order.asc()).all()
        return jsonify({'success': True, 'lessons': [l.to_dict() for l in lessons]}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/lessons', methods=['POST'])
@cross_origin()
@require_admin
def create_lesson():
    try:
        data = request.get_json()
        required = ['subject_id', 'title', 'lesson_order']
        for f in required:
            if not data.get(f):
                return jsonify({'success': False, 'message': f'الحقل {f} مطلوب'}), 400
        lesson = Lesson(
            subject_id=data['subject_id'],
            title=data['title'],
            description=data.get('description', ''),
            video_url=data.get('video_url', ''),
            lesson_order=data['lesson_order'],
            is_active=data.get('is_active', True)
        )
        if isinstance(data.get('attachments'), list):
            lesson.set_attachments(data['attachments'])
        db.session.add(lesson)
        db.session.commit()  # commit first to get lesson.id

        # Notify subscribed students about the new lesson
        try:
            subject = Subject.query.get(lesson.subject_id)
            subs = ActiveSubscription.query.filter_by(subject_id=lesson.subject_id, is_active=True).all()
            notifications = []
            title = f"درس جديد: {lesson.title}"
            msg = f"تم إضافة درس جديد في مادة {subject.name if subject else ''}: {lesson.title}"
            for sub in subs:
                notifications.append(Notification(
                    user_id=sub.user_id,
                    title=title,
                    message=msg,
                    type='new_lesson',
                    is_read=False
                ))
            if notifications:
                db.session.bulk_save_objects(notifications)
                db.session.commit()
        except Exception:
            # Don't fail the request if notification creation fails
            db.session.rollback()

        return jsonify({'success': True, 'lesson': lesson.to_dict()}), 201
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/lessons/<int:lesson_id>', methods=['PUT'])
@cross_origin()
@require_admin
def update_lesson(lesson_id):
    try:
        data = request.get_json()
        lesson = Lesson.query.get_or_404(lesson_id)
        for f in ['title','description','video_url','lesson_order','is_active']:
            if f in data:
                setattr(lesson, f, data[f])
        if 'attachments' in data and isinstance(data['attachments'], list):
            lesson.set_attachments(data['attachments'])
        lesson.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'lesson': lesson.to_dict()}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/lessons/<int:lesson_id>', methods=['DELETE'])
@cross_origin()
@require_admin
def delete_lesson(lesson_id):
    try:
        lesson = Lesson.query.get_or_404(lesson_id)

        # Delete lesson progress
        LessonProgress.query.filter_by(lesson_id=lesson.id).delete(synchronize_session=False)

        # Delete exams and their dependencies
        exams = Exam.query.filter_by(lesson_id=lesson.id).all()
        for exam in exams:
            # Delete exam attempts and their answers
            attempt_ids = [a.id for a in ExamAttempt.query.filter_by(exam_id=exam.id).all()]
            if attempt_ids:
                ExamAnswer.query.filter(ExamAnswer.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
                ExamAttempt.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)

            # Delete Questions/Answers (admin models)
            q_ids = [q.id for q in Question.query.filter_by(exam_id=exam.id).all()]
            if q_ids:
                Answer.query.filter(Answer.question_id.in_(q_ids)).delete(synchronize_session=False)
                Question.query.filter(Question.id.in_(q_ids)).delete(synchronize_session=False)

            # Also delete ExamQuestion (legacy model) if exists
            eq_ids = [eq.id for eq in ExamQuestion.query.filter_by(exam_id=exam.id).all()] if 'ExamQuestion' in globals() else []
            if eq_ids:
                # No separate answers table for ExamQuestion; handled via ExamAnswer attempts above
                ExamQuestion.query.filter(ExamQuestion.id.in_(eq_ids)).delete(synchronize_session=False)

            # Finally delete the exam
            db.session.delete(exam)

        # Delete the lesson itself
        db.session.delete(lesson)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الدرس'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

# Exams Management
@admin_bp.route('/lessons/<int:lesson_id>/exams', methods=['GET'])
@cross_origin()
@require_admin
def get_lesson_exams(lesson_id):
    try:
        exams = Exam.query.filter_by(lesson_id=lesson_id).order_by(Exam.created_at.desc()).all()
        exams_data = []
        for e in exams:
            d = e.to_dict()
            d['questions_count'] = Question.query.filter_by(exam_id=e.id).count()
            exams_data.append(d)
        return jsonify({'success': True, 'exams': exams_data}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/subjects/<int:subject_id>/exams', methods=['GET'])
@cross_origin()
@require_admin
def get_subject_exams_admin(subject_id):
    """List subject-level exams for a subject (subject_id set, lesson_id is null)"""
    try:
        exams = Exam.query.filter_by(subject_id=subject_id).order_by(Exam.created_at.desc()).all()
        exams_data = []
        for e in exams:
            d = e.to_dict()
            d['questions_count'] = Question.query.filter_by(exam_id=e.id).count()
            exams_data.append(d)
        return jsonify({'success': True, 'exams': exams_data}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/exams', methods=['POST'])
@cross_origin()
@require_admin
def create_exam():
    try:
        data = request.get_json()
        # Allow either subject-level or lesson-level exam
        if not data.get('title') or not data.get('duration_minutes'):
            return jsonify({'success': False, 'message': 'الحقل title و duration_minutes مطلوبة'}), 400
        if not data.get('lesson_id') and not data.get('subject_id'):
            return jsonify({'success': False, 'message': 'يلزم تحديد subject_id (امتحان شامل) أو lesson_id'}), 400
        if data.get('lesson_id') and data.get('subject_id'):
            return jsonify({'success': False, 'message': 'لا يمكن الجمع بين subject_id و lesson_id في نفس الامتحان'}), 400
        
        exam = Exam(
            subject_id=data.get('subject_id'),
            lesson_id=data.get('lesson_id'),
            title=data['title'],
            description=data.get('description',''),
            duration_minutes=data['duration_minutes'],
            max_attempts=data.get('max_attempts',3),
            passing_score=data.get('passing_score',60),
            show_results_immediately=data.get('show_results_immediately', True),
            is_active=data.get('is_active', True)
        )
        db.session.add(exam)
        db.session.commit()
        return jsonify({'success': True, 'exam': exam.to_dict()}), 201
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/exams/<int:exam_id>', methods=['PUT'])
@cross_origin()
@require_admin
def update_exam(exam_id):
    try:
        data = request.get_json()
        exam = Exam.query.get_or_404(exam_id)
        for f in ['title','description','duration_minutes','max_attempts','passing_score','show_results_immediately','is_active']:
            if f in data:
                setattr(exam, f, data[f])
        exam.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'exam': exam.to_dict()}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/exams/<int:exam_id>', methods=['DELETE'])
@cross_origin()
@require_admin
def delete_exam(exam_id):
    try:
        exam = Exam.query.get_or_404(exam_id)

        # Delete attempts and answers
        attempt_ids = [a.id for a in ExamAttempt.query.filter_by(exam_id=exam.id).all()]
        if attempt_ids:
            ExamAnswer.query.filter(ExamAnswer.attempt_id.in_(attempt_ids)).delete(synchronize_session=False)
            ExamAttempt.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)

        # Delete admin Questions/Answers
        q_ids = [q.id for q in Question.query.filter_by(exam_id=exam.id).all()]
        if q_ids:
            Answer.query.filter(Answer.question_id.in_(q_ids)).delete(synchronize_session=False)
            Question.query.filter(Question.id.in_(q_ids)).delete(synchronize_session=False)

        # Delete legacy ExamQuestion if any
        if 'ExamQuestion' in globals():
            ExamQuestion.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)

        db.session.delete(exam)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الامتحان'}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

# Questions Management
@admin_bp.route('/exams/<int:exam_id>/questions', methods=['GET'])
@cross_origin()
@require_admin
def get_exam_questions(exam_id):
    try:
        questions = Question.query.filter_by(exam_id=exam_id).order_by(Question.order.asc()).all()
        # include answers
        data = []
        for q in questions:
            qd = q.to_dict()
            qd['answers'] = [a.to_dict() for a in q.answers]
            data.append(qd)
        return jsonify({'success': True, 'questions': data}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/questions', methods=['POST'])
@cross_origin()
@require_admin
def create_question():
    try:
        data = request.get_json()
        required = ['exam_id','question_text']
        for f in required:
            if not data.get(f):
                return jsonify({'success': False, 'message': f'الحقل {f} مطلوب'}), 400
        q = Question(
            exam_id=data['exam_id'],
            question_text=data['question_text'],
            question_type=data.get('question_type','multiple_choice'),
            order=data.get('order',1),
            is_active=data.get('is_active', True)
        )
        db.session.add(q)
        db.session.commit()
        # optional seed answers
        if isinstance(data.get('answers'), list):
            for idx, ans in enumerate(data['answers'], start=1):
                a = Answer(question_id=q.id, answer_text=ans.get('answer_text',''), is_correct=bool(ans.get('is_correct', False)), order=ans.get('order', idx))
                db.session.add(a)
            db.session.commit()
        qd = q.to_dict()
        qd['answers'] = [a.to_dict() for a in q.answers]
        return jsonify({'success': True, 'question': qd}), 201
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/questions/<int:question_id>', methods=['PUT'])
@cross_origin()
@require_admin
def update_question(question_id):
    try:
        data = request.get_json()
        q = Question.query.get_or_404(question_id)
        for f in ['question_text','question_type','order','is_active']:
            if f in data:
                setattr(q, f, data[f])
        db.session.commit()
        return jsonify({'success': True, 'question': q.to_dict()}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/questions/<int:question_id>', methods=['DELETE'])
@cross_origin()
@require_admin
def delete_question(question_id):
    try:
        q = Question.query.get_or_404(question_id)
        # delete answers first to avoid FK issues
        Answer.query.filter_by(question_id=q.id).delete(synchronize_session=False)
        db.session.delete(q)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف السؤال'}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

# Answers Management
@admin_bp.route('/answers', methods=['POST'])
@cross_origin()
@require_admin
def create_answer():
    try:
        data = request.get_json()
        required = ['question_id','answer_text']
        for f in required:
            if not data.get(f):
                return jsonify({'success': False, 'message': f'الحقل {f} مطلوب'}), 400
        a = Answer(question_id=data['question_id'], answer_text=data['answer_text'], is_correct=bool(data.get('is_correct', False)), order=data.get('order', 1), is_active=data.get('is_active', True))
        db.session.add(a)
        db.session.commit()
        return jsonify({'success': True, 'answer': a.to_dict()}), 201
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/answers/<int:answer_id>', methods=['PUT'])
@cross_origin()
@require_admin
def update_answer(answer_id):
    try:
        data = request.get_json()
        a = Answer.query.get_or_404(answer_id)
        for f in ['answer_text','is_correct','order','is_active']:
            if f in data:
                setattr(a, f, data[f])
        db.session.commit()
        return jsonify({'success': True, 'answer': a.to_dict()}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@admin_bp.route('/answers/<int:answer_id>', methods=['DELETE'])
@cross_origin()
@require_admin
def delete_answer(answer_id):
    try:
        a = Answer.query.get_or_404(answer_id)
        db.session.delete(a)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الإجابة'}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

# Reports
@admin_bp.route('/reports/students', methods=['GET'])
@cross_origin()
@require_admin
def get_students_report():
    """Get detailed students report"""
    try:
        students = User.query.filter_by(user_type='student').all()
        
        report_data = []
        for student in students:
            # Get active subscriptions
            active_subs = ActiveSubscription.query.filter_by(
                user_id=student.id, is_active=True
            ).all()
            
            # Get exam attempts and scores
            exam_attempts = ExamAttempt.query.filter_by(user_id=student.id).all()
            
            # Calculate average score
            if exam_attempts:
                avg_score = sum(attempt.score for attempt in exam_attempts) / len(exam_attempts)
                best_score = max(attempt.score for attempt in exam_attempts)
            else:
                avg_score = 0
                best_score = 0
            
            # Get lesson progress
            completed_lessons = LessonProgress.query.filter_by(
                user_id=student.id, completed=True
            ).count()
            
            total_lessons = 0
            for sub in active_subs:
                total_lessons += Lesson.query.filter_by(
                    subject_id=sub.subject_id, is_active=True
                ).count()
            
            progress_percentage = (completed_lessons / total_lessons * 100) if total_lessons > 0 else 0
            
            student_report = {
                'id': student.id,
                'full_name': student.full_name,
                'username': student.username,
                'email': student.email,
                'phone_number': student.phone_number,
                'is_active': student.is_active,
                'created_at': student.created_at.isoformat(),
                'active_subscriptions_count': len(active_subs),
                'subscribed_subjects': [
                    {
                        'id': sub.subject.id,
                        'name': sub.subject.name,
                        'subscription_date': sub.created_at.isoformat()
                    }
                    for sub in active_subs
                ],
                'exam_attempts_count': len(exam_attempts),
                'average_score': round(avg_score, 2),
                'best_score': round(best_score, 2),
                'completed_lessons': completed_lessons,
                'total_lessons': total_lessons,
                'progress_percentage': round(progress_percentage, 2)
            }
            
            report_data.append(student_report)
        
        return jsonify({
            'success': True,
            'report': report_data
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

# Admin: single student profile
@admin_bp.route('/users/<int:student_id>/profile', methods=['GET'])
@cross_origin()
@require_admin
def get_admin_student_profile(student_id):
    """Get detailed profile for a specific student (admin view)"""
    try:
        student = User.query.get_or_404(student_id)
        if student.user_type != 'student':
            return jsonify({'success': False, 'message': 'المستخدم ليس طالباً'}), 400

        # Active subscriptions
        active_subs = ActiveSubscription.query.filter_by(user_id=student.id, is_active=True).all()

        # Exam attempts
        exam_attempts = ExamAttempt.query.filter_by(user_id=student.id).all()
        # Safely compute scores (ignore None)
        scores = [float(a.score) for a in exam_attempts if a.score is not None]
        if scores:
            avg_score = sum(scores) / len(scores)
            best_score = max(scores)
        else:
            avg_score = 0
            best_score = 0
        # Use end_time if available, otherwise start_time
        activity_times = [a.end_time or a.start_time for a in exam_attempts if (a.end_time or a.start_time)]
        last_activity = max(activity_times) if activity_times else None

        # Lesson progress
        completed_lessons = LessonProgress.query.filter_by(user_id=student.id, is_completed=True).count()
        total_lessons = 0
        subjects_data = []
        for sub in active_subs:
            lessons_count = Lesson.query.filter_by(subject_id=sub.subject_id, is_active=True).count()
            total_lessons += lessons_count
            # per-subject progress
            subject_completed = (
                LessonProgress.query
                .join(Lesson, LessonProgress.lesson_id == Lesson.id)
                .filter(
                    LessonProgress.user_id == student.id,
                    Lesson.subject_id == sub.subject_id,
                    LessonProgress.is_completed == True
                )
                .count()
            )
            progress_pct = round((subject_completed / lessons_count * 100), 2) if lessons_count > 0 else 0
            subjects_data.append({
                'id': sub.subject.id,
                'name': sub.subject.name,
                'subscription_date': sub.created_at.isoformat(),
                'progress_percentage': progress_pct
            })

        progress_percentage = round((completed_lessons / total_lessons * 100), 2) if total_lessons > 0 else 0

        # Determine academic year name from active subscriptions or latest request
        academic_year_name = None
        try:
            if active_subs:
                ay_names = [
                    sub.subject.academic_year.name
                    for sub in active_subs
                    if getattr(sub, 'subject', None) and getattr(sub.subject, 'academic_year', None)
                ]
                if ay_names:
                    # Pick the most frequent academic year name
                    academic_year_name = max(set(ay_names), key=ay_names.count)
            if not academic_year_name:
                last_req = (
                    SubscriptionRequest.query
                    .filter_by(user_id=student.id)
                    .order_by(SubscriptionRequest.created_at.desc())
                    .first()
                )
                if last_req:
                    ay = AcademicYear.query.get(last_req.academic_year_id)
                    if ay:
                        academic_year_name = ay.name
        except Exception:
            pass

        profile = {
            'basic': {
                'id': student.id,
                'full_name': student.full_name,
                'username': student.username,
                'email': student.email,
                'phone_number': student.phone_number,
                'academic_year': academic_year_name,
                'is_active': student.is_active,
                'created_at': student.created_at.isoformat() if student.created_at else None,
                'status': 'نشط' if student.is_active else 'غير نشط'
            },
            'stats': {
                'exams_taken': len(exam_attempts),
                'overall_success_percentage': round(avg_score, 2),
                'best_score': round(best_score, 2),
                'completed_lessons': completed_lessons,
                'total_lessons': total_lessons,
                'overall_progress_percentage': progress_percentage,
                'last_activity': last_activity.isoformat() if last_activity else None
            },
            'subjects': subjects_data
        }

        return jsonify({'success': True, 'profile': profile}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

