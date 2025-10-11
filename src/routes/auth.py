from flask import Blueprint, jsonify, request, current_app
from flask_cors import cross_origin
from src.models.user import User, SubscriptionRequest, AcademicYear, Subject, PaymentReceipt, Notification, db
from datetime import datetime, timedelta
import jwt
import os
import uuid
from werkzeug.utils import secure_filename

# Optional captcha verification
try:
    import requests as _requests
except Exception:
    _requests = None

def _verify_captcha(token: str):
    secret = os.getenv('CAPTCHA_SECRET')
    if not secret:
        return True  # captcha not enforced
    if not token:
        return False
    if _requests is None:
        return False
    try:
        r = _requests.post('https://www.google.com/recaptcha/api/siteverify', data={
            'secret': secret,
            'response': token,
        }, timeout=5)
        data = r.json()
        return bool(data.get('success'))
    except Exception:
        return False

auth_bp = Blueprint('auth', __name__)

# Helper function to generate JWT token
def generate_token(user_id, session_id=None):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(minutes=1)  # Token expires in 7 days
    }
    if session_id:
        payload['sid'] = session_id
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

# Helper function to verify JWT token
def verify_token(token):
    try:
        payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        return payload['user_id'], payload.get('sid')
    except jwt.ExpiredSignatureError:
        return 'expired', None
    except jwt.InvalidTokenError:
        return None, None


@auth_bp.route('/logout', methods=['POST'])
@cross_origin()
def logout():
    """تسجيل الخروج: يُفرغ current_session_id ليُسمح بتسجيل الدخول من جهاز آخر"""
    try:
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'رمز المصادقة مطلوب'}), 401
        if token.startswith('Bearer '):
            token = token[7:]
        # Decode token to get user and sid
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'انتهت صلاحية الجلسة'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'رمز المصادقة غير صالح'}), 401
        user = User.query.get(payload.get('user_id'))
        if not user:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود'}), 401
        token_sid = payload.get('sid')
        # لا تسمح بتسجيل الخروج باستخدام توكن من جهاز آخر
        if user.current_session_id and token_sid != user.current_session_id:
            return jsonify({'success': False, 'message': 'لا يمكن تسجيل الخروج من هذه الجلسة'}), 401
        user.current_session_id = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تسجيل الخروج بنجاح'}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@auth_bp.route('/receipts/<int:receipt_id>', methods=['GET'])
@cross_origin()
def get_receipt(receipt_id: int):
    """تحميل الإيصال من قاعدة البيانات"""
    try:
        receipt = PaymentReceipt.query.get_or_404(receipt_id)
        from flask import Response
        return Response(receipt.data, mimetype=receipt.content_type, headers={
            'Content-Disposition': f'inline; filename="{secure_filename(receipt.filename)}"'
        })
    except Exception:
        return jsonify({'success': False, 'message': 'تعذر تحميل الإيصال'}), 500

@auth_bp.route('/login', methods=['POST'])
@cross_origin()
def login():
    """تسجيل الدخول للطلاب والمديرين"""
    try:
        data = request.get_json()
        
        # captcha check (optional)
        if not _verify_captcha(data.get('captcha_token') if data else None):
            return jsonify({'success': False, 'message': 'فشل التحقق من الكابتشا'}), 400
        
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({
                'success': False,
                'message': 'اسم المستخدم وكلمة المرور مطلوبان'
            }), 400
        
        # البحث عن المستخدم
        user = User.query.filter_by(username=data['username']).first()
        
        if not user or not user.check_password(data['password']):
            return jsonify({
                'success': False,
                'message': 'اسم المستخدم أو كلمة المرور غير صحيحة'
            }), 401
        
        if not user.is_active:
            return jsonify({
                'success': False,
                'message': 'حسابك غير مفعل. يرجى انتظار موافقة الإدارة'
            }), 401
        
        # مسح الجلسة الحالية إن وجدت للسماح بتسجيل دخول جديد
        if user.current_session_id:
            user.current_session_id = None

        # إنشاء جلسة جديدة
        user.last_login = datetime.utcnow()
        new_session_id = uuid.uuid4().hex  # 32 chars
        user.current_session_id = new_session_id
        db.session.commit()
        
        # إنشاء رمز المصادقة مرتبط بالجلسة
        token = generate_token(user.id, session_id=new_session_id)
        
        return jsonify({
            'success': True,
            'message': 'تم تسجيل الدخول بنجاح',
            'token': token,
            'user': user.to_dict()
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/register', methods=['POST'])
@cross_origin()
def register():
    """تسجيل طالب جديد"""
    try:
        data = request.get_json()
        
        # captcha check (optional)
        if not _verify_captcha(data.get('captcha_token') if data else None):
            return jsonify({'success': False, 'message': 'فشل التحقق من الكابتشا'}), 400
        
        # التحقق من البيانات المطلوبة
        required_fields = ['username', 'email', 'password', 'full_name', 'phone_number', 'academic_year_id', 'selected_subjects']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'message': f'الحقل {field} مطلوب'
                }), 400
        
        # تحقق من اسم المستخدم فريد وبصيغة مناسبة
        if ' ' in data['username'] or len(data['username']) < 4:
            return jsonify({'success': False, 'message': 'اسم المستخدم يجب ألا يحتوي مسافات وأن يكون 4 أحرف على الأقل'}), 400
        
        # تحقق من رقم الهاتف
        if not str(data['phone_number']).isdigit() or len(str(data['phone_number'])) < 10:
            return jsonify({'success': False, 'message': 'رقم الموبايل غير صالح'}), 400
        
        # التحقق من عدم وجود المستخدم مسبقاً
        if User.query.filter_by(username=data['username']).first():
            return jsonify({
                'success': False,
                'message': 'اسم المستخدم موجود بالفعل'
            }), 400
        
        if User.query.filter_by(email=data['email']).first():
            return jsonify({
                'success': False,
                'message': 'البريد الإلكتروني موجود بالفعل'
            }), 400
        
        # سياسة كلمة المرور
        pwd = data['password']
        if len(pwd) < 8 or pwd.isalpha() or pwd.isdigit():
            return jsonify({'success': False, 'message': 'كلمة المرور يجب أن تكون 8 أحرف على الأقل وتحتوي على حروف وأرقام'}), 400
        
        # إنشاء المستخدم الجديد
        user = User(
            username=data['username'],
            email=data['email'],
            full_name=data['full_name'],
            phone_number=data['phone_number'],
            user_type='student',
            is_active=False  # سيتم تفعيله بعد موافقة الأدمن
        )
        user.set_password(pwd)
        
        db.session.add(user)
        db.session.flush()  # للحصول على ID المستخدم
        
        # حساب المبلغ الإجمالي + تطبيق خصم باقة محددة إن انطبقت الشروط
        selected_subject_ids = data['selected_subjects']
        # تأكد من تحويل المعرفات إلى أرقام قبل الاستعلام
        try:
            selected_ids_int = sorted({int(x) for x in selected_subject_ids})
        except Exception:
            selected_ids_int = list({x for x in selected_subject_ids}) if isinstance(selected_subject_ids, list) else []

        subjects = Subject.query.filter(Subject.id.in_(selected_ids_int)).all()
        total_amount = sum(float(subject.price) for subject in subjects)

        # خصم 50 ج فقط عند اختيار 3 مواد تحديداً:
        # - بالمعرفات: [1, 2, 4]
        # - أو بالأسماء نصاً: "أساسيات تمريض (عملي)", "أساسيات تمريض (نظري)", "ميكروبيولوجي"
        discount_applied = False
        try:
            # خصم يُطبق حتى مع مواد إضافية: يكفي أن تحتوي القائمة على 1 و2 و4
            apply_by_ids = all(x in selected_ids_int for x in [1, 2, 4])

            # تطبيع الأسماء العربية للمقارنة
            def _norm_ar(s: str) -> str:
                s = (s or '').strip().lower()
                for ch in ('أ','إ','آ'):
                    s = s.replace(ch, 'ا')
                s = s.replace('ى','ي').replace('ة','ه').replace('ـ','')
                s = ' '.join(s.split())  # إزالة الفراغات الزائدة
                return s

            selected_names_norm = {_norm_ar(getattr(subj, 'name', '')) for subj in subjects}
            target_names_norm = {
                _norm_ar('أساسيات تمريض (عملي)'),
                _norm_ar('أساسيات تمريض (نظري)'),
                _norm_ar('ميكروبيولوجي'),
            }
            # يكفي احتواء التشكيلة على المواد الثلاثة حتى لو وُجدت مواد إضافية
            apply_by_names = target_names_norm.issubset(selected_names_norm)

            if apply_by_ids or apply_by_names:
                total_amount = max(0.0, total_amount - 50.0)
                discount_applied = True
        except Exception:
            pass
        
        # إنشاء طلب الاشتراك
        subscription_request = SubscriptionRequest(
            user_id=user.id,
            academic_year_id=data['academic_year_id'],
            total_amount=total_amount,
            status='pending'
        )
        subscription_request.set_selected_subjects(selected_subject_ids)
        
        db.session.add(subscription_request)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم إرسال طلب التسجيل بنجاح. سيتم مراجعته خلال 24 ساعة.',
            'total_amount': total_amount,
            'discount_applied': discount_applied,
            'discount_amount': 50.0 if discount_applied else 0.0,
            'payment_number': '01080938298',
            'user_id': user.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/upload-receipt', methods=['POST'])
@cross_origin()
def upload_receipt():
    """رفع إيصال الدفع إلى قاعدة البيانات"""
    try:
        if 'receipt' not in request.files:
            return jsonify({
                'success': False,
                'message': 'لم يتم رفع أي ملف'
            }), 400
        
        file = request.files['receipt']
        user_id = request.form.get('user_id')
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'معرف المستخدم مطلوب'
            }), 400
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'لم يتم اختيار ملف'
            }), 400
        
        # التحقق من نوع الملف
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
        if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            return jsonify({
                'success': False,
                'message': 'نوع الملف غير مدعوم'
            }), 400
        
        # رفع إلى Cloudinary إذا تم ضبط المتغيرات
        drive_file_url = None
        try:
            import cloudinary
            import cloudinary.uploader
            cloudinary.config(
                cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
                api_key=os.getenv('CLOUDINARY_API_KEY'),
                api_secret=os.getenv('CLOUDINARY_API_SECRET')
            )
            if os.getenv('CLOUDINARY_CLOUD_NAME') and os.getenv('CLOUDINARY_API_KEY') and os.getenv('CLOUDINARY_API_SECRET'):
                upload_result = cloudinary.uploader.upload(
                    file.stream,
                    resource_type='auto',
                    folder=os.getenv('CLOUDINARY_FOLDER', 'receipts'),
                    public_id=f"{user_id}_{uuid.uuid4().hex}",
                    overwrite=True
                )
                drive_file_url = upload_result.get('secure_url') or upload_result.get('url')
        except Exception:
            drive_file_url = None
        
        # إذا فشل رفع Cloudinary، لا نخزن في قاعدة البيانات ونُرجع خطأ
        if not drive_file_url:
            return jsonify({
                'success': False,
                'message': 'فشل رفع الإيصال إلى Cloudinary'
            }), 500
        
        # تحديث طلب الاشتراك بالرابط الخارجي فقط - اربطه بأحدث طلب للمستخدم لتفادي سباق الموافقات
        try:
            uid_int = int(user_id)
        except Exception:
            uid_int = user_id
        subscription_request = (
            SubscriptionRequest.query
            .filter_by(user_id=uid_int)
            .order_by(SubscriptionRequest.created_at.desc())
            .first()
        )
        
        if subscription_request:
            subscription_request.payment_receipt_url = drive_file_url
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم رفع الإيصال بنجاح',
            'file_url': drive_file_url
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في رفع الملف'
        }), 500

@auth_bp.route('/forgot-password', methods=['POST'])
@cross_origin()
def forgot_password():
    """طلب استعادة كلمة المرور"""
    try:
        data = request.get_json()
        
        if not data or not data.get('email'):
            return jsonify({
                'success': False,
                'message': 'البريد الإلكتروني مطلوب'
            }), 400
        
        user = User.query.filter_by(email=data['email']).first()
        
        if not user:
            return jsonify({
                'success': False,
                'message': 'البريد الإلكتروني غير موجود'
            }), 404
        
        # إنشاء رمز استعادة كلمة المرور
        reset_token = str(uuid.uuid4())
        user.password_reset_token = reset_token
        user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
        
        db.session.commit()
        
        # في التطبيق الحقيقي، سيتم إرسال بريد إلكتروني هنا
        # لكن الآن سنعيد الرمز في الاستجابة للاختبار
        
        return jsonify({
            'success': True,
            'message': 'تم إرسال رابط استعادة كلمة المرور إلى بريدك الإلكتروني',
            'reset_token': reset_token  # للاختبار فقط
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/reset-password', methods=['POST'])
@cross_origin()
def reset_password():
    """إعادة تعيين كلمة المرور"""
    try:
        data = request.get_json()
        
        required_fields = ['token', 'new_password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'message': f'الحقل {field} مطلوب'
                }), 400
        
        user = User.query.filter_by(password_reset_token=data['token']).first()
        
        if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
            return jsonify({
                'success': False,
                'message': 'رمز الاستعادة غير صالح أو منتهي الصلاحية'
            }), 400
        
        # تحديث كلمة المرور
        user.set_password(data['new_password'])
        user.password_reset_token = None
        user.password_reset_expires = None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'تم تغيير كلمة المرور بنجاح'
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/reverify', methods=['POST'])
@cross_origin()
def reverify_password():
    """إعادة التحقق من كلمة المرور قبل فتح مادة/درس بدون تطبيق منع تعدد الأجهزة
    - يتطلب Authorization Bearer token للتعرف على المستخدم
    - يتحقق فقط من كلمة المرور ولا يعدل current_session_id ولا last_login
    """
    try:
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'رمز المصادقة مطلوب'}), 401
        if token.startswith('Bearer '):
            token = token[7:]
        # فك التوكن بدون فرض مطابقة sid مع current_session_id
        try:
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'انتهت صلاحية الجلسة'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': 'رمز المصادقة غير صالح'}), 401
        user = User.query.get(payload.get('user_id'))
        if not user or not user.is_active:
            return jsonify({'success': False, 'message': 'المستخدم غير موجود أو غير مفعل'}), 401

        data = request.get_json() or {}
        password = data.get('password')
        if not password:
            return jsonify({'success': False, 'message': 'كلمة المرور مطلوبة'}), 400
        if not user.check_password(password):
            return jsonify({'success': False, 'message': 'كلمة المرور غير صحيحة'}), 401
        # نجاح بدون أي تعديل على الجلسة
        return jsonify({'success': True, 'message': 'تم التحقق بنجاح'}), 200
    except Exception:
        return jsonify({'success': False, 'message': 'حدث خطأ في الخادم'}), 500

@auth_bp.route('/verify-token', methods=['POST'])
@cross_origin()
def verify_user_token():
    """التحقق من صحة رمز المصادقة"""
    try:
        data = request.get_json()
        
        if not data or not data.get('token'):
            return jsonify({
                'success': False,
                'message': 'رمز المصادقة مطلوب'
            }), 400
        
        user_id, sid = verify_token(data['token'])
        
        if user_id == 'expired':
            return jsonify({
                'success': False,
                'message': 'انتهت صلاحية الجلسة'
            }), 401
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'رمز المصادقة غير صالح'
            }), 401
        
        user = User.query.get(user_id)
        
        if not user or not user.is_active:
            return jsonify({
                'success': False,
                'message': 'المستخدم غير موجود أو غير مفعل'
            }), 401
        
        return jsonify({
            'success': True,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/academic-years', methods=['GET'])
@cross_origin()
def get_academic_years():
    """الحصول على قائمة الفرق الدراسية"""
    try:
        academic_years = AcademicYear.query.filter_by(is_active=True).all()
        return jsonify({
            'success': True,
            'academic_years': [year.to_dict() for year in academic_years]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

@auth_bp.route('/subjects/<int:academic_year_id>', methods=['GET'])
@cross_origin()
def get_subjects_by_year(academic_year_id):
    """الحصول على المواد الدراسية لفرقة معينة"""
    try:
        subjects = Subject.query.filter_by(
            academic_year_id=academic_year_id,
            is_active=True
        ).all()
        
        return jsonify({
            'success': True,
            'subjects': [subject.to_dict() for subject in subjects]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في الخادم'
        }), 500

