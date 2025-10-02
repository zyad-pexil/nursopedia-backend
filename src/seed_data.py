#!/usr/bin/env python3
"""
Script to populate the database with initial data for testing
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.models.user import db, User, AcademicYear, Subject, Lesson, Exam, ExamQuestion, ExamAnswer
from src.main import app

def create_seed_data():
    """إنشاء البيانات الأولية للاختبار"""
    
    with app.app_context():
        # إنشاء الجداول
        db.create_all()
        
        # إنشاء مدير النظام
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@nursopedia.com',
                full_name='مدير النظام',
                phone_number='01000000000',
                user_type='admin',
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            print("تم إنشاء حساب المدير: admin / admin123")
        
        # إنشاء الفرق الدراسية
        first_year = AcademicYear.query.filter_by(name='الفرقة الأولى').first()
        if not first_year:
            first_year = AcademicYear(
                name='الفرقة الأولى',
                description='الفرقة الأولى - كلية التمريض',
                is_active=True
            )
            db.session.add(first_year)
        
        second_year = AcademicYear.query.filter_by(name='الفرقة الثانية').first()
        if not second_year:
            second_year = AcademicYear(
                name='الفرقة الثانية',
                description='الفرقة الثانية - كلية التمريض',
                is_active=True
            )
            db.session.add(second_year)
        
        db.session.commit()
        
        # إنشاء المواد الدراسية للفرقة الأولى
        first_year_subjects = [
            {'name': 'علم التشريح', 'description': 'دراسة تشريح جسم الإنسان', 'price': 100.00},
            {'name': 'علم وظائف الأعضاء', 'description': 'دراسة وظائف أعضاء الجسم', 'price': 100.00},
            {'name': 'أساسيات التمريض', 'description': 'المبادئ الأساسية لمهنة التمريض', 'price': 150.00},
            {'name': 'علم النفس', 'description': 'علم النفس التطبيقي في التمريض', 'price': 80.00}
        ]
        
        for subject_data in first_year_subjects:
            existing_subject = Subject.query.filter_by(
                name=subject_data['name'],
                academic_year_id=first_year.id
            ).first()
            
            if not existing_subject:
                subject = Subject(
                    name=subject_data['name'],
                    description=subject_data['description'],
                    academic_year_id=first_year.id,
                    price=subject_data['price'],
                    is_active=True
                )
                db.session.add(subject)
        
        # إنشاء المواد الدراسية للفرقة الثانية
        second_year_subjects = [
            {'name': 'تمريض الباطنة والجراحة', 'description': 'تمريض المرضى في الأقسام الداخلية والجراحية', 'price': 200.00},
            {'name': 'تمريض الأطفال', 'description': 'العناية التمريضية للأطفال', 'price': 180.00},
            {'name': 'تمريض النساء والولادة', 'description': 'العناية التمريضية للنساء والولادة', 'price': 180.00},
            {'name': 'الصحة النفسية والعقلية', 'description': 'التمريض النفسي والعقلي', 'price': 120.00}
        ]
        
        for subject_data in second_year_subjects:
            existing_subject = Subject.query.filter_by(
                name=subject_data['name'],
                academic_year_id=second_year.id
            ).first()
            
            if not existing_subject:
                subject = Subject(
                    name=subject_data['name'],
                    description=subject_data['description'],
                    academic_year_id=second_year.id,
                    price=subject_data['price'],
                    is_active=True
                )
                db.session.add(subject)
        
        db.session.commit()
        print("تم إنشاء البيانات الأولية بنجاح!")
        print("الفرق الدراسية والمواد متاحة الآن للاختبار")
        
        # إضافة دروس تجريبية للمواد
        print("إضافة الدروس التجريبية...")
        
        # الحصول على المواد
        anatomy_subject = Subject.query.filter_by(name='علم التشريح').first()
        physiology_subject = Subject.query.filter_by(name='علم وظائف الأعضاء').first()
        nursing_subject = Subject.query.filter_by(name='أساسيات التمريض').first()
        
        if anatomy_subject:
            # دروس علم التشريح
            anatomy_lessons = [
                {
                    'title': 'مقدمة في علم التشريح',
                    'description': 'نظرة عامة على علم التشريح وأهميته في التمريض',
                    'video_url': 'https://www.youtube.com/watch?v=example1',
                    'duration': 45,
                    'order': 1
                },
                {
                    'title': 'الجهاز العضلي الهيكلي',
                    'description': 'دراسة العظام والعضلات والمفاصل',
                    'video_url': 'https://www.youtube.com/watch?v=example2',
                    'duration': 60,
                    'order': 2
                },
                {
                    'title': 'الجهاز الدوري',
                    'description': 'القلب والأوعية الدموية والدورة الدموية',
                    'video_url': 'https://www.youtube.com/watch?v=example3',
                    'duration': 55,
                    'order': 3
                }
            ]
            
            for lesson_data in anatomy_lessons:
                existing_lesson = Lesson.query.filter_by(
                    title=lesson_data['title'],
                    subject_id=anatomy_subject.id
                ).first()
                
                if not existing_lesson:
                    lesson = Lesson(
                        title=lesson_data['title'],
                        description=lesson_data['description'],
                        subject_id=anatomy_subject.id,
                        video_url=lesson_data['video_url'],
                        duration=lesson_data['duration'],
                        order=lesson_data['order'],
                        is_active=True
                    )
                    db.session.add(lesson)
        
        if nursing_subject:
            # دروس أساسيات التمريض
            nursing_lessons = [
                {
                    'title': 'مبادئ التمريض الأساسية',
                    'description': 'المفاهيم الأساسية في مهنة التمريض',
                    'video_url': 'https://www.youtube.com/watch?v=example4',
                    'duration': 40,
                    'order': 1
                },
                {
                    'title': 'العناية الشخصية للمريض',
                    'description': 'كيفية تقديم العناية الشخصية الأساسية',
                    'video_url': 'https://www.youtube.com/watch?v=example5',
                    'duration': 50,
                    'order': 2
                }
            ]
            
            for lesson_data in nursing_lessons:
                existing_lesson = Lesson.query.filter_by(
                    title=lesson_data['title'],
                    subject_id=nursing_subject.id
                ).first()
                
                if not existing_lesson:
                    lesson = Lesson(
                        title=lesson_data['title'],
                        description=lesson_data['description'],
                        subject_id=nursing_subject.id,
                        video_url=lesson_data['video_url'],
                        duration=lesson_data['duration'],
                        order=lesson_data['order'],
                        is_active=True
                    )
                    db.session.add(lesson)
        
        db.session.commit()
        
        # إضافة امتحانات تجريبية
        print("إضافة الامتحانات التجريبية...")
        
        if anatomy_subject:
            # امتحان علم التشريح
            anatomy_exam = Exam.query.filter_by(
                title='امتحان علم التشريح - الوحدة الأولى',
                subject_id=anatomy_subject.id
            ).first()
            
            if not anatomy_exam:
                anatomy_exam = Exam(
                    title='امتحان علم التشريح - الوحدة الأولى',
                    description='امتحان شامل على الوحدة الأولى من مادة علم التشريح',
                    subject_id=anatomy_subject.id,
                    duration=30,  # 30 دقيقة
                    max_attempts=3,
                    passing_score=60.0,
                    is_active=True
                )
                db.session.add(anatomy_exam)
                db.session.flush()  # للحصول على ID الامتحان
                
                # إضافة أسئلة للامتحان
                questions_data = [
                    {
                        'question_text': 'كم عدد العظام في جسم الإنسان البالغ؟',
                        'answers': [
                            {'text': '206 عظمة', 'is_correct': True},
                            {'text': '208 عظمة', 'is_correct': False},
                            {'text': '204 عظمة', 'is_correct': False},
                            {'text': '210 عظمة', 'is_correct': False}
                        ]
                    },
                    {
                        'question_text': 'ما هو أكبر عضو في جسم الإنسان؟',
                        'answers': [
                            {'text': 'الكبد', 'is_correct': False},
                            {'text': 'الجلد', 'is_correct': True},
                            {'text': 'الرئتان', 'is_correct': False},
                            {'text': 'القلب', 'is_correct': False}
                        ]
                    },
                    {
                        'question_text': 'كم عدد حجرات القلب؟',
                        'answers': [
                            {'text': '2', 'is_correct': False},
                            {'text': '3', 'is_correct': False},
                            {'text': '4', 'is_correct': True},
                            {'text': '5', 'is_correct': False}
                        ]
                    }
                ]
                
                for i, q_data in enumerate(questions_data, 1):
                    question = ExamQuestion(
                        exam_id=anatomy_exam.id,
                        question_text=q_data['question_text'],
                        option_a=q_data['answers'][0]['text'],
                        option_b=q_data['answers'][1]['text'],
                        option_c=q_data['answers'][2]['text'],
                        option_d=q_data['answers'][3]['text'],
                        correct_answer=next(
                            (option for option, answer in zip(['A', 'B', 'C', 'D'], q_data['answers']) if answer['is_correct']),
                            'A'
                        ),
                        question_order=i,
                        points=1.0
                    )
                    db.session.add(question)
        
        if nursing_subject:
            # امتحان أساسيات التمريض
            nursing_exam = Exam.query.filter_by(
                title='امتحان أساسيات التمريض',
                subject_id=nursing_subject.id
            ).first()
            
            if not nursing_exam:
                nursing_exam = Exam(
                    title='امتحان أساسيات التمريض',
                    description='امتحان على المبادئ الأساسية للتمريض',
                    subject_id=nursing_subject.id,
                    duration_minutes=25,
                    max_attempts=3,
                    passing_score=70.0,
                    is_active=True
                )
                db.session.add(nursing_exam)
                db.session.flush()
                
                # أسئلة التمريض
                nursing_questions = [
                    {
                        'question_text': 'ما هو الهدف الأساسي من مهنة التمريض؟',
                        'answers': [
                            {'text': 'تشخيص الأمراض', 'is_correct': False},
                            {'text': 'تقديم الرعاية الشاملة للمريض', 'is_correct': True},
                            {'text': 'وصف الأدوية', 'is_correct': False},
                            {'text': 'إجراء العمليات الجراحية', 'is_correct': False}
                        ]
                    },
                    {
                        'question_text': 'ما هي أولى خطوات العناية التمريضية؟',
                        'answers': [
                            {'text': 'التقييم', 'is_correct': True},
                            {'text': 'التخطيط', 'is_correct': False},
                            {'text': 'التنفيذ', 'is_correct': False},
                            {'text': 'التقويم', 'is_correct': False}
                        ]
                    }
                ]
                
                for i, q_data in enumerate(nursing_questions, 1):
                    question = ExamQuestion(
                        exam_id=nursing_exam.id,
                        question_text=q_data['question_text'],
                        option_a=q_data['answers'][0]['text'],
                        option_b=q_data['answers'][1]['text'],
                        option_c=q_data['answers'][2]['text'],
                        option_d=q_data['answers'][3]['text'],
                        correct_answer=next(
                            (option for option, answer in zip(['A', 'B', 'C', 'D'], q_data['answers']) if answer['is_correct']),
                            'A'
                        ),
                        question_order=i,
                        points=1.0
                    )
                    db.session.add(question)
        
        db.session.commit()
        print("تم إضافة الدروس والامتحانات التجريبية بنجاح!")

