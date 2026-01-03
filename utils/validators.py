"""
工具模組 - 驗證函數
功能：郵箱驗證、密碼強度驗證、RUT 驗證
"""

import re
from config import password_config


# ========== 郵箱驗證 ==========
def validate_email(email):
    """
    驗證郵箱格式
    參數：email - 郵箱地址
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not email:
        return False, "El correo electrónico no puede estar vacío"
    
    # 基本格式驗證
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Formato de correo electrónico incorrecto"
    
    # 長度驗證
    if len(email) > 254:
        return False, "El correo electrónico es demasiado largo"
    
    # 檢查常見的無效格式
    if '..' in email:
        return False, "Formato de correo electrónico incorrecto (contiene puntos consecutivos)"
    
    if email.startswith('.') or email.endswith('.'):
        return False, "Formato de correo electrónico incorrecto (no puede comenzar o terminar con punto)"
    
    return True, ""


# ========== 密碼強度驗證 ==========
def validate_password(password):
    """
    驗證密碼強度
    參數：password - 密碼
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not password:
        return False, "La contraseña no puede estar vacía"
    
    # 長度驗證
    if len(password) < password_config.MIN_LENGTH:
        return False, f"La contraseña debe tener al menos {password_config.MIN_LENGTH} caracteres"
    
    if len(password) > password_config.MAX_LENGTH:
        return False, f"La contraseña no puede tener más de {password_config.MAX_LENGTH} caracteres"
    
    # 大寫字母檢查
    if password_config.REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return False, "La contraseña debe contener al menos una letra mayúscula"
    
    # 小寫字母檢查
    if password_config.REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return False, "La contraseña debe contener al menos una letra minúscula"
    
    # 數字檢查
    if password_config.REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, "La contraseña debe contener al menos un número"
    
    # 特殊字符檢查（可選）
    if password_config.REQUIRE_SPECIAL:
        special_chars = password_config.SPECIAL_CHARS
        if not any(char in special_chars for char in password):
            return False, f"La contraseña debe contener al menos un carácter especial ({special_chars})"
    
    return True, ""


# ========== 用戶名驗證 ==========
def validate_username(username):
    """
    驗證用戶名格式
    參數：username - 用戶名
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not username:
        return False, "El nombre de usuario no puede estar vacío"
    
    # 長度驗證
    if len(username) < 3:
        return False, "El nombre de usuario debe tener al menos 3 caracteres"
    
    if len(username) > 30:
        return False, "El nombre de usuario no puede tener más de 30 caracteres"
    
    # 格式驗證：只允許字母、數字、下劃線
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "El nombre de usuario solo puede contener letras, números y guiones bajos"
    
    # 不能以數字開頭
    if username[0].isdigit():
        return False, "El nombre de usuario no puede comenzar con un número"
    
    return True, ""


# ========== RUT 驗證（智利稅號）==========
def validate_rut(rut):
    """
    驗證智利 RUT 格式
    參數：rut - RUT 號碼（例: 12345678-9）
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not rut:
        return False, "RUT 不能為空"
    
    # 移除空格和點
    rut = rut.replace('.', '').replace(' ', '').upper()
    
    # 基本格式驗證：xxxxxxxx-x 或 xxxxxxx-x
    rut_pattern = r'^(\d{7,8})-[\dkK]$'
    
    if not re.match(rut_pattern, rut):
        return False, "RUT 格式不正確（例: 12345678-9）"
    
    # 分離主體和驗證碼
    parts = rut.split('-')
    if len(parts) != 2:
        return False, "RUT 格式不正確"
    
    number = parts[0]
    verifier = parts[1]
    
    # 計算校驗碼
    calculated_verifier = calculate_rut_verifier(number)
    
    if verifier != calculated_verifier:
        return False, f"RUT 校驗碼錯誤（應為 {calculated_verifier}）"
    
    return True, ""


def calculate_rut_verifier(rut_number):
    """
    計算 RUT 校驗碼
    參數：rut_number - RUT 主體數字
    返回：str - 校驗碼
    """
    reversed_digits = map(int, reversed(str(rut_number)))
    factors = [2, 3, 4, 5, 6, 7]
    
    s = sum(d * factors[i % 6] for i, d in enumerate(reversed_digits))
    remainder = (-s) % 11
    
    if remainder == 10:
        return 'K'
    else:
        return str(remainder)


# ========== 驗證碼驗證 ==========
def validate_verification_code(code):
    """
    驗證驗證碼格式
    參數：code - 驗證碼
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not code:
        return False, "驗證碼不能為空"
    
    # 去除空格
    code = code.strip()
    
    # 長度驗證（通常是 6 位數字）
    if len(code) != 6:
        return False, "驗證碼必須是 6 位數字"
    
    # 必須是純數字
    if not code.isdigit():
        return False, "驗證碼必須是數字"
    
    return True, ""


# ========== 日期驗證 ==========
def validate_expire_date(date_str):
    """
    驗證到期日期格式
    參數：date_str - 日期字符串（YYYY-MM-DD）
    返回：(bool, str) - (是否有效, 錯誤信息)
    """
    if not date_str:
        return True, ""  # 允許為空（永久授權）
    
    # 格式驗證
    date_pattern = r'^\d{4}-\d{2}-\d{2}$'
    
    if not re.match(date_pattern, date_str):
        return False, "日期格式不正確（應為 YYYY-MM-DD）"
    
    # 嘗試解析日期
    try:
        from datetime import datetime
        datetime.strptime(date_str, '%Y-%m-%d')
        return True, ""
    except ValueError:
        return False, "日期不是有效的日期"


# ========== 批量驗證 ==========
def validate_registration_data(username, email, password):
    """
    驗證註冊數據（一次性驗證所有字段）
    參數：username, email, password
    返回：(bool, dict) - (是否全部有效, 錯誤字典)
    """
    errors = {}
    
    # 驗證用戶名
    valid, msg = validate_username(username)
    if not valid:
        errors['username'] = msg
    
    # 驗證郵箱
    valid, msg = validate_email(email)
    if not valid:
        errors['email'] = msg
    
    # 驗證密碼
    valid, msg = validate_password(password)
    if not valid:
        errors['password'] = msg
    
    return len(errors) == 0, errors


# ========== 測試程式 ==========
if __name__ == '__main__':
    print("=" * 50)
    print("驗證工具測試")
    print("=" * 50)
    
    # 測試郵箱驗證
    print("\n【郵箱驗證測試】")
    test_emails = [
        "test@example.com",
        "invalid-email",
        "test@",
        "@example.com",
        "test..test@example.com"
    ]
    
    for email in test_emails:
        valid, msg = validate_email(email)
        status = "✅" if valid else "❌"
        print(f"{status} {email:30} {msg}")
    
    # 測試密碼驗證
    print("\n【密碼驗證測試】")
    test_passwords = [
        "Abc12345",      # 有效
        "abc123",        # 太短
        "abcdefgh",      # 缺數字
        "ABCD1234",      # 缺小寫
        "Abcdefgh",      # 缺數字
    ]
    
    for pwd in test_passwords:
        valid, msg = validate_password(pwd)
        status = "✅" if valid else "❌"
        print(f"{status} {pwd:20} {msg}")
    
    # 測試 RUT 驗證
    print("\n【RUT 驗證測試】")
    test_ruts = [
        "12345678-5",    # 有效
        "11111111-1",    # 有效
        "12345678-9",    # 無效校驗碼
        "1234567",       # 格式錯誤
    ]
    
    for rut in test_ruts:
        valid, msg = validate_rut(rut)
        status = "✅" if valid else "❌"
        print(f"{status} {rut:20} {msg}")
    
    print("\n" + "=" * 50)