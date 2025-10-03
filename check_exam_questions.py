#!/usr/bin/env python3
"""
Script to check exam questions in the database
"""
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import app, db
from models.user import Exam, ExamQuestion

def check_exams():
    with app.app_context():
        print("=" * 60)
        print("Checking Exams and Questions")
        print("=" * 60)
        
        # Get all exams
        exams = Exam.query.all()
        print(f"\n📚 Total Exams: {len(exams)}")
        
        for exam in exams:
            print(f"\n{'='*60}")
            print(f"📝 Exam ID: {exam.id}")
            print(f"   Title: {exam.title}")
            print(f"   Subject ID: {exam.subject_id}")
            print(f"   Lesson ID: {exam.lesson_id}")
            print(f"   Is Active: {exam.is_active}")
            print(f"   Duration: {exam.duration_minutes} minutes")
            print(f"   Passing Score: {exam.passing_score}%")
            
            # Get questions for this exam
            questions = ExamQuestion.query.filter_by(exam_id=exam.id).order_by(ExamQuestion.question_order).all()
            print(f"   ❓ Questions Count: {len(questions)}")
            
            if questions:
                print(f"\n   Questions:")
                for q in questions:
                    print(f"   - Q{q.question_order}: {q.question_text[:60]}...")
                    print(f"     A) {q.option_a[:40]}...")
                    print(f"     B) {q.option_b[:40]}...")
                    print(f"     C) {q.option_c[:40]}...")
                    print(f"     D) {q.option_d[:40]}...")
                    print(f"     ✓ Correct: {q.correct_answer}")
            else:
                print(f"   ⚠️  NO QUESTIONS FOUND FOR THIS EXAM!")
        
        print(f"\n{'='*60}")
        print("Check Complete")
        print("=" * 60)

if __name__ == '__main__':
    check_exams()