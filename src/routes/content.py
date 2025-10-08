from flask import Blueprint, jsonify, request, current_app
from flask_cors import cross_origin
from src.models.user import (
    db, User, Subject, Lesson, Exam, Question, Answer,
    LessonProgress, ExamAttempt, ActiveSubscription
)
from datetime import datetime
import jwt
import os
import time
from werkzeug.utils import secure_filename

content_bp = Blueprint('content', __name__)

# Simple in-memory TTL cache for read-heavy endpoints
# Note: This is per-process memory and suitable for single-instance deployments.
_cache_store = {}

def _cache_get(key: str):
    item = _cache_store.get(key)
    if not item:
        return None
    value, expires_at = item
    if expires_at < time.time():
        _cache_store.pop(key, None)
        return None
    return value

def _cache_set(key: str, value, ttl_seconds: int):
    _cache_store[key] = (value, time.time() + ttl_seconds)

def _cache_delete(key: str):
    _cache_store.pop(key, None)

# Helper function to verify JWT token
def verify_token(token):
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload  # return full payload to check session id
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

# Decorator to require authentication
def require_auth(f):
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
        if not user or not user.is_active:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود أو غير مفعل'}), 401

        # Enforce single active session: sid in token must match user's current_session_id
        token_sid = payload.get('sid')
        if user.current_session_id and token_sid != user.current_session_id:
            return jsonify({'success': False, 'message': 'تم تسجيل دخولك من جهاز آخر.'}), 401

        request.current_user = user
        return f(*args, **kwargs)

    decorated_function.__name__ = f.__name__
    return decorated_function

# Check if user has access to subject
def has_subject_access(user_id, subject_id):
    """Check if user has active subscription for the subject"""
    subscription = ActiveSubscription.query.filter_by(
        user_id=user_id,
        subject_id=subject_id,
        is_active=True
    ).first()
    return subscription is not None

@content_bp.route('/subjects', methods=['GET'])
@cross_origin()
@require_auth
def get_user_subjects():
    """Get subjects that the user has access to"""
    try:
        user = request.current_user

        # Cache per-user subjects briefly (120s)
        cache_key = f"subjects:{user.id}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return jsonify({'success': True, 'subjects': cached}), 200

        # Get active subscriptions with subjects using join for better performance
        subscriptions_with_subjects = (
            db.session.query(ActiveSubscription, Subject)
            .join(Subject, ActiveSubscription.subject_id == Subject.id)
            .filter(
                ActiveSubscription.user_id == user.id,
                ActiveSubscription.is_active == True,
                Subject.is_active == True
            )
            .all()
        )

        subjects = []
        for subscription, subject in subscriptions_with_subjects:
            subject_data = subject.to_dict()
            subject_data['subscription_date'] = subscription.created_at.isoformat()
            subjects.append(subject_data)

        _cache_set(cache_key, subjects, 120)

        return jsonify({
            'success': True,
            'subjects': subjects
        }), 200

    except Exception as e:
        current_app.logger.exception("get_user_subjects failed")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/subjects/<int:subject_id>/lessons', methods=['GET'])
@cross_origin()
@require_auth
def get_subject_lessons(subject_id):
    """Get lessons for a specific subject"""
    try:
        user = request.current_user

        # Check if user has access to this subject
        if not has_subject_access(user.id, subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذه المادة'
            }), 403

        # Cache lessons list w/ progress per user+subject for 60s (fast scroll UX)
        cache_key = f"lessons:{user.id}:{subject_id}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return jsonify({'success': True, 'lessons': cached}), 200

        # Get lessons with progress using outer join for better performance
        lessons_with_progress = (
            db.session.query(Lesson, LessonProgress)
            .outerjoin(LessonProgress, (LessonProgress.user_id == user.id) & (LessonProgress.lesson_id == Lesson.id))
            .filter(
                Lesson.subject_id == subject_id,
                Lesson.is_active == True
            )
            .order_by(Lesson.lesson_order.asc())
            .all()
        )

        lessons_data = []
        for lesson, progress in lessons_with_progress:
            lesson_data = lesson.to_dict()

            lesson_data['progress'] = {
                'completed': bool(progress.is_completed) if progress and progress.is_completed is not None else False,
                'watch_time': int(progress.watch_time_seconds or 0) if progress else 0,
                'last_watched': progress.last_accessed_at.isoformat() if progress and progress.last_accessed_at else None
            }

            lessons_data.append(lesson_data)

        _cache_set(cache_key, lessons_data, 60)

        return jsonify({
            'success': True,
            'lessons': lessons_data
        }), 200

    except Exception as e:
        current_app.logger.exception(f"get_subject_lessons failed: subject_id={subject_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/lessons/<int:lesson_id>', methods=['GET'])
@cross_origin()
@require_auth
def get_lesson_details(lesson_id):
    """Get detailed information about a specific lesson"""
    try:
        user = request.current_user

        lesson = Lesson.query.get_or_404(lesson_id)

        # Log for debugging
        current_app.logger.info(f"Lesson {lesson_id}: subject_id={lesson.subject_id}, title={lesson.title}")

        # Check if user has access to this lesson's subject
        if lesson.subject_id is None:
            current_app.logger.error(f"Lesson {lesson_id} has no subject_id")
            return jsonify({
                'success': False,
                'message': 'الدرس غير مرتبط بمادة'
            }), 500

        if not has_subject_access(user.id, lesson.subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذا الدرس'
            }), 403
        
        lesson_data = lesson.to_dict()
        
        # Include exams for this lesson
        exams = Exam.query.filter_by(lesson_id=lesson.id, is_active=True).order_by(Exam.created_at.desc()).all()
        lesson_data['exams'] = [e.to_dict() for e in exams]
        
        # Get or create progress record
        progress = LessonProgress.query.filter_by(
            user_id=user.id,
            lesson_id=lesson.id
        ).first()
        
        if not progress:
            progress = LessonProgress(
                user_id=user.id,
                lesson_id=lesson.id,
                watch_time_seconds=0,
                is_completed=False
            )
            db.session.add(progress)
            db.session.commit()
        
        lesson_data['progress'] = {
            'completed': progress.is_completed,
            'watch_time': progress.watch_time_seconds,
            'last_watched': progress.last_accessed_at.isoformat() if progress.last_accessed_at else None
        }
        
        return jsonify({
            'success': True,
            'lesson': lesson_data
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error in get_lesson_details (lesson_id={lesson_id}): {str(e)}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/lessons/<int:lesson_id>/progress', methods=['POST'])
@cross_origin()
@require_auth
def update_lesson_progress(lesson_id):
    """Update user's progress for a lesson"""
    try:
        user = request.current_user
        data = request.get_json()
        
        lesson = Lesson.query.get_or_404(lesson_id)
        
        # Check if user has access to this lesson's subject
        if not has_subject_access(user.id, lesson.subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذا الدرس'
            }), 403
        
        # Get or create progress record
        progress = LessonProgress.query.filter_by(
            user_id=user.id,
            lesson_id=lesson.id
        ).first()
        
        if not progress:
            progress = LessonProgress(
                user_id=user.id,
                lesson_id=lesson.id
            )
            db.session.add(progress)
        
        # Update progress
        if 'watch_time' in data:
            progress.watch_time_seconds = data['watch_time']
        
        if 'completed' in data:
            progress.is_completed = data['completed']
        
        progress.last_accessed_at = datetime.utcnow()
        
        db.session.commit()

        # Invalidate cached lessons list for this user+subject to reflect progress updates
        try:
            _cache_delete(f"lessons:{user.id}:{lesson.subject_id}")
        except Exception:
            pass
        
        return jsonify({
            'success': True,
            'message': 'تم تحديث التقدم بنجاح'
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"update_lesson_progress failed: lesson_id={lesson_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/subjects/<int:subject_id>/exams', methods=['GET'])
@cross_origin()
@require_auth
def get_subject_exams(subject_id):
    """Get exams for a specific subject (both lesson-level and subject-level)"""
    try:
        user = request.current_user

        # Check if user has access to this subject
        if not has_subject_access(user.id, subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذه المادة'
            }), 403

        # Cache list of exams and attempt summaries per user+subject for 120s
        cache_key = f"exams:{user.id}:{subject_id}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return jsonify({'success': True, 'exams': cached}), 200

        # Get all exams for this subject (both subject-level and lesson-level)
        exams_with_attempts = (
            db.session.query(Exam, ExamAttempt)
            .outerjoin(ExamAttempt, (ExamAttempt.user_id == user.id) & (ExamAttempt.exam_id == Exam.id))
            .outerjoin(Lesson, Exam.lesson_id == Lesson.id)
            .filter(
                Exam.is_active == True,
                db.or_(
                    Exam.subject_id == subject_id,
                    Lesson.subject_id == subject_id
                )
            )
            .order_by(Exam.created_at.desc())
            .all()
        )

        # Group attempts by exam
        exam_attempts = {}
        exams_data = {}
        for exam, attempt in exams_with_attempts:
            if exam.id not in exams_data:
                exam_data = exam.to_dict()
                exam_data['is_subject_level'] = bool(exam.subject_id)
                exam_data['attempts_count'] = 0
                exam_data['best_score'] = None
                exam_data['remaining_attempts'] = None
                exam_data['last_attempt'] = None
                exams_data[exam.id] = exam_data
                exam_attempts[exam.id] = []

            if attempt:
                exam_attempts[exam.id].append(attempt)

        # Process attempts for each exam
        for exam_id, attempts in exam_attempts.items():
            exam_data = exams_data[exam_id]
            attempts_sorted = sorted(attempts, key=lambda a: a.start_time, reverse=True)
            exam_data['attempts_count'] = len(attempts_sorted)

            # Only the first attempt's score counts
            first_attempt = None
            for a in reversed(attempts_sorted):
                if getattr(a, 'attempt_number', None) == 1:
                    first_attempt = a
                    break
            exam_data['best_score'] = float(first_attempt.score) if first_attempt and first_attempt.score is not None else None
            exam_data['last_attempt'] = attempts_sorted[0].start_time.isoformat() if attempts_sorted else None

        result = list(exams_data.values())
        _cache_set(cache_key, result, 120)

        return jsonify({
            'success': True,
            'exams': result
        }), 200

    except Exception as e:
        current_app.logger.exception(f"get_subject_exams failed: subject_id={subject_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/exams/<int:exam_id>', methods=['GET'])
@cross_origin()
@require_auth
def get_exam_details(exam_id):
    """Get exam details and questions"""
    try:
        user = request.current_user
        current_app.logger.info(f"get_exam_details called: exam_id={exam_id}, user_id={user.id}")
        
        exam = Exam.query.get_or_404(exam_id)
        current_app.logger.info(f"Exam found: id={exam.id}, title={exam.title}, subject_id={exam.subject_id}, lesson_id={exam.lesson_id}")
        
        # Determine subject for access: subject-level or via lesson
        subject_id = None
        if getattr(exam, 'subject_id', None):
            subject_id = exam.subject_id
        elif getattr(exam, 'lesson_id', None):
            lesson = Lesson.query.get(exam.lesson_id)
            subject_id = lesson.subject_id if lesson else None
        
        current_app.logger.info(f"Determined subject_id={subject_id} for exam {exam_id}")
        
        if not subject_id or not has_subject_access(user.id, subject_id):
            current_app.logger.warning(f"Access denied for user {user.id} to exam {exam_id} (subject {subject_id})")
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذا الامتحان'
            }), 403
        
        # Unlimited attempts: don't block fetching details by attempts
        attempts = ExamAttempt.query.filter_by(
            user_id=user.id,
            exam_id=exam.id
        ).count()
        
        exam_data = exam.to_dict()

        # Get questions with answers (using Question/Answer model, not ExamQuestion)
        questions = (
            Question.query
            .filter_by(exam_id=exam.id, is_active=True)
            .order_by(Question.order.asc())
            .all()
        )
        
        current_app.logger.info(f"Found {len(questions)} questions for exam {exam_id}")
        for q in questions:
            current_app.logger.debug(f"Question {q.id}: order={q.order}, text={q.question_text[:50]}...")

        questions_data = []
        for question in questions:
            # Get answers for this question
            answers = (
                Answer.query
                .filter_by(question_id=question.id, is_active=True)
                .order_by(Answer.order.asc())
                .all()
            )
            
            # Convert answers to options format (A, B, C, D)
            options = {}
            option_keys = ['A', 'B', 'C', 'D']
            for idx, answer in enumerate(answers[:4]):  # Max 4 options
                if idx < len(option_keys):
                    options[option_keys[idx]] = answer.answer_text
            
            questions_data.append({
                'id': question.id,
                'question_text': question.question_text,
                'options': options,
                'question_order': question.order,
            })

        exam_data['questions'] = questions_data
        # Unlimited attempts; expose first attempt score if exists
        exam_data['remaining_attempts'] = None
        
        current_app.logger.info(f"Returning exam {exam_id} with {len(questions_data)} questions")
        
        return jsonify({
            'success': True,
            'exam': exam_data
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"get_exam_details failed: exam_id={exam_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/exams/<int:exam_id>/submit', methods=['POST'])
@cross_origin()
@require_auth
def submit_exam(exam_id):
    """Submit exam answers and calculate score"""
    try:
        user = request.current_user
        data = request.get_json()
        
        exam = Exam.query.get_or_404(exam_id)
        
        # Determine subject for access: subject-level or via lesson
        subject_id = None
        if getattr(exam, 'subject_id', None):
            subject_id = exam.subject_id
        elif getattr(exam, 'lesson_id', None):
            lesson = Lesson.query.get(exam.lesson_id)
            subject_id = lesson.subject_id if lesson else None
        
        if not subject_id or not has_subject_access(user.id, subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذا الامتحان'
            }), 403
        
        # Unlimited attempts: don't block submissions; only first attempt will count for grade
        attempts = ExamAttempt.query.filter_by(
            user_id=user.id,
            exam_id=exam.id
        ).count()
        
        # Validate answers format
        if not data or 'answers' not in data:
            return jsonify({
                'success': False,
                'message': 'إجابات غير صالحة'
            }), 400
        
        user_answers = data['answers']  # Expected format: {question_id: 'A'/'B'/'C'/'D'}

        # Get all questions with their correct answers (using Question/Answer model)
        questions = (
            Question.query
            .filter_by(exam_id=exam.id, is_active=True)
            .all()
        )

        # Build a mapping of question_id to correct answer option (A/B/C/D)
        correct_answer_map = {}
        for question in questions:
            # Get all answers for this question
            answers = (
                Answer.query
                .filter_by(question_id=question.id, is_active=True)
                .order_by(Answer.order.asc())
                .all()
            )
            
            # Find which option (A/B/C/D) is correct
            option_keys = ['A', 'B', 'C', 'D']
            for idx, answer in enumerate(answers[:4]):
                if answer.is_correct and idx < len(option_keys):
                    correct_answer_map[str(question.id)] = option_keys[idx]
                    break

        total_questions = len(correct_answer_map)
        correct_answers = 0

        # Calculate score
        for question_id, user_answer in user_answers.items():
            if question_id in correct_answer_map and str(user_answer).upper() == str(correct_answer_map[question_id]):
                correct_answers += 1
        
        # Calculate percentage score
        score = (correct_answers / total_questions) * 100 if total_questions > 0 else 0
        
        # Save only the first attempt; subsequent attempts are not recorded
        attempt_number = ExamAttempt.query.filter_by(user_id=user.id, exam_id=exam.id).count() + 1
        if attempt_number == 1:
            attempt = ExamAttempt(
                user_id=user.id,
                exam_id=exam.id,
                attempt_number=attempt_number,
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                score=score,
                total_points=100,
                percentage=score,
                is_passed=score >= float(exam.passing_score),
                is_completed=True,
                time_taken_seconds=None
            )
            db.session.add(attempt)
            db.session.commit()
        
        # Determine grade to count: only first attempt
        first_attempt = ExamAttempt.query.filter_by(user_id=user.id, exam_id=exam.id, attempt_number=1).first()
        counted_score = float(first_attempt.score) if first_attempt and first_attempt.score is not None else float(score)

        # Build detailed answer feedback
        answer_feedback = []
        for question in questions:
            question_id_str = str(question.id)
            user_answer = user_answers.get(question_id_str)
            correct_answer = correct_answer_map.get(question_id_str)

            # Get answer options with labels
            answers = (
                Answer.query
                .filter_by(question_id=question.id, is_active=True)
                .order_by(Answer.order.asc())
                .all()
            )

            options = {}
            option_keys = ['A', 'B', 'C', 'D']
            for idx, answer in enumerate(answers[:4]):
                if idx < len(option_keys):
                    options[option_keys[idx]] = answer.answer_text

            answer_feedback.append({
                'question_id': question.id,
                'question_text': question.question_text,
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': str(user_answer).upper() == str(correct_answer),
                'options': options
            })

        return jsonify({
            'success': True,
            'message': 'تم تسليم الامتحان بنجاح',
            'score': float(score),
            'counted_score': counted_score,
            'counted': attempt_number == 1,
            'correct_answers': correct_answers,
            'total_questions': total_questions,
            'passed': float(score) >= float(exam.passing_score),
            'answer_feedback': answer_feedback
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"submit_exam failed: exam_id={exam_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@content_bp.route('/exams/<int:exam_id>/attempts', methods=['GET'])
@cross_origin()
@require_auth
def get_exam_attempts(exam_id):
    """Get user's attempts for a specific exam"""
    try:
        user = request.current_user
        
        exam = Exam.query.get_or_404(exam_id)
        
        # Determine subject for access: subject-level or via lesson
        subject_id = None
        if getattr(exam, 'subject_id', None):
            subject_id = exam.subject_id
        elif getattr(exam, 'lesson_id', None):
            lesson = Lesson.query.get(exam.lesson_id)
            subject_id = lesson.subject_id if lesson else None
        
        if not subject_id or not has_subject_access(user.id, subject_id):
            return jsonify({
                'success': False,
                'message': 'ليس لديك صلاحية للوصول إلى هذا الامتحان'
            }), 403
        
        attempts = ExamAttempt.query.filter_by(
            user_id=user.id,
            exam_id=exam.id
        ).order_by(ExamAttempt.start_time.desc()).all()
        
        attempts_data = [
            {
                'id': attempt.id,
                'score': float(attempt.score) if attempt.score is not None else None,
                'completed_at': attempt.end_time.isoformat() if attempt.end_time else None,
                'passed': (float(attempt.score) if attempt.score is not None else 0) >= float(exam.passing_score)
            }
            for attempt in attempts
        ]
        
        return jsonify({
            'success': True,
            'attempts': attempts_data,
            'exam_title': exam.title,
            'passing_score': float(exam.passing_score)
        }), 200
        
    except Exception as e:
        current_app.logger.exception(f"get_exam_attempts failed: exam_id={exam_id}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

