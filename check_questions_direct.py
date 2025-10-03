#!/usr/bin/env python3
"""
Direct SQL query to check exam questions
"""
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import app, db
from sqlalchemy import text

def check_questions_direct():
    with app.app_context():
        print("=" * 80)
        print("Direct SQL Query - Checking exam_questions table")
        print("=" * 80)
        
        # Get exam info
        exam_query = text("SELECT id, title, subject_id, lesson_id FROM exams WHERE id = 2")
        exam_result = db.session.execute(exam_query).fetchone()
        
        if exam_result:
            print(f"\n📝 Exam ID: {exam_result[0]}")
            print(f"   Title: {exam_result[1]}")
            print(f"   Subject ID: {exam_result[2]}")
            print(f"   Lesson ID: {exam_result[3]}")
        
        # Get all questions for exam_id = 2
        questions_query = text("""
            SELECT id, exam_id, question_text, question_order, 
                   option_a, option_b, option_c, option_d, correct_answer
            FROM exam_questions 
            WHERE exam_id = 2 
            ORDER BY question_order ASC
        """)
        
        questions = db.session.execute(questions_query).fetchall()
        
        print(f"\n❓ Total Questions Found: {len(questions)}")
        print("=" * 80)
        
        for q in questions:
            print(f"\nQuestion ID: {q[0]}")
            print(f"  Order: {q[3]}")
            print(f"  Text: {q[2][:80]}...")
            print(f"  A) {q[4][:50]}...")
            print(f"  B) {q[5][:50]}...")
            print(f"  C) {q[6][:50]}...")
            print(f"  D) {q[7][:50]}...")
            print(f"  ✓ Correct: {q[8]}")
        
        print("\n" + "=" * 80)
        print("Check Complete")
        print("=" * 80)

if __name__ == '__main__':
    check_questions_direct()