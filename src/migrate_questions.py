import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.models.user import db, Question, Answer, ExamQuestion, ExamAnswer
from src.main import app

def migrate_questions_to_exam_questions():
    """Migrate data from old Question/Answer models to new ExamQuestion/ExamAnswer models"""
    with app.app_context():
        try:
            # Check if migration already done
            if ExamQuestion.query.first():
                print("ExamQuestion table already has data, skipping migration")
                return

            # Get all questions
            questions = Question.query.all()
            print(f"Found {len(questions)} questions to migrate")

            for question in questions:
                # Get answers for this question
                answers = Answer.query.filter_by(question_id=question.id).order_by(Answer.order).all()

                if len(answers) == 4:  # Only migrate multiple choice with 4 answers
                    # Find the correct answer
                    correct_answer = None
                    options = {}
                    for i, answer in enumerate(answers):
                        options[chr(65 + i)] = answer.answer_text  # A, B, C, D
                        if answer.is_correct:
                            correct_answer = chr(65 + i)

                    if correct_answer:
                        # Create new ExamQuestion
                        new_question = ExamQuestion(
                            exam_id=question.exam_id,
                            question_text=question.question_text,
                            option_a=options.get('A', ''),
                            option_b=options.get('B', ''),
                            option_c=options.get('C', ''),
                            option_d=options.get('D', ''),
                            correct_answer=correct_answer,
                            question_order=question.order,
                            points=1.0
                        )
                        db.session.add(new_question)
                        print(f"Migrated question {question.id} to ExamQuestion")

            db.session.commit()
            print("Migration completed successfully")

        except Exception as e:
            print(f"Migration failed: {e}")
            db.session.rollback()

if __name__ == "__main__":
    migrate_questions_to_exam_questions()