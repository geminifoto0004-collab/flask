// 用戶頁面 JavaScript 功能

// 全域變數
let currentStep = 1;
let userEmail = '';

// 頁面載入時顯示登入時間
document.addEventListener('DOMContentLoaded', function() {
    const loginTimeElement = document.getElementById('loginTime');
    if (loginTimeElement) {
        const now = new Date();
        const loginTime = now.toLocaleString('zh-TW', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
        loginTimeElement.textContent = loginTime;
    }
});

// 顯示消息
function showMessage(message, type = 'error') {
    const errorDiv = document.getElementById('errorMessage');
    const successDiv = document.getElementById('successMessage');
    
    // 隱藏所有消息
    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';
    
    // 顯示對應消息
    if (type === 'error') {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
    } else {
        successDiv.textContent = message;
        successDiv.style.display = 'block';
    }
}

// 隱藏消息
function hideMessages() {
    document.getElementById('errorMessage').style.display = 'none';
    document.getElementById('successMessage').style.display = 'none';
}

// 驗證表單
function validateForm(formId) {
    const form = document.getElementById(formId);
    const formData = new FormData(form);
    
    // 基本驗證
    for (let [key, value] of formData.entries()) {
        if (!value.trim()) {
            showMessage(`請填寫 ${key} 欄位`);
            return false;
        }
    }
    
    return true;
}

// 驗證密碼強度
function validatePassword(password) {
    if (password.length < 8) {
        return 'La contraseña debe tener al menos 8 caracteres';
    }
    
    if (!/\d/.test(password)) {
        return 'La contraseña debe contener al menos un número';
    }
    
    return null;
}

// 驗證郵箱格式
function validateEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// 驗證用戶名格式
function validateUsername(username) {
    if (username.length < 3 || username.length > 30) {
        return 'El nombre de usuario debe tener entre 3-30 caracteres';
    }
    
    if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        return 'El nombre de usuario solo puede contener letras, números y guiones bajos';
    }
    
    if (/^\d/.test(username)) {
        return 'El nombre de usuario no puede comenzar con un número';
    }
    
    return null;
}

// 驗證驗證碼格式
function validateVerificationCode(code) {
    if (code.length !== 6) {
        return 'El código de verificación debe ser de 6 dígitos';
    }
    
    if (!/^\d+$/.test(code)) {
        return 'El código de verificación debe ser numérico';
    }
    
    return null;
}

// ========== 註冊功能 ==========

// 管理員註冊（直接提交，無需驗證碼）
function submitAdminRegistration() {
    hideMessages();
    
    // 獲取表單數據
    const username = document.getElementById('username').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    // 驗證用戶名
    const usernameError = validateUsername(username);
    if (usernameError) {
        showMessage(usernameError);
        return;
    }
    
    // 驗證郵箱
    if (!validateEmail(email)) {
        showMessage('Por favor ingrese una dirección de correo electrónico válida');
        return;
    }
    
    // 驗證密碼
    const passwordError = validatePassword(password);
    if (passwordError) {
        showMessage(passwordError);
        return;
    }
    
    // 確認密碼
    if (password !== confirmPassword) {
        showMessage('Las contraseñas ingresadas no coinciden');
        return;
    }
    
    // 發送請求
    fetch('/admin/register', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: `username=${encodeURIComponent(username)}&email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}&confirm_password=${encodeURIComponent(confirmPassword)}`
    })
    .then(response => response.text())
    .then(html => {
        // 檢查是否包含成功消息
        if (html.includes('管理員註冊成功')) {
            showMessage('¡Registro de administrador exitoso! Redirigiendo a la página de inicio de sesión...', 'success');
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else if (html.includes('error-message')) {
            // 提取錯誤消息
            const errorMatch = html.match(/error-message[^>]*>([^<]+)</);
            if (errorMatch) {
                showMessage(errorMatch[1]);
            } else {
                showMessage('註冊失敗，請檢查輸入信息');
            }
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    });
}

// 發送驗證碼
function sendVerificationCode() {
    hideMessages();
    
    // 獲取表單數據
    const username = document.getElementById('username').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    
    // 驗證用戶名
    const usernameError = validateUsername(username);
    if (usernameError) {
        showMessage(usernameError);
        return;
    }
    
    // 驗證郵箱
    if (!validateEmail(email)) {
        showMessage('Por favor ingrese una dirección de correo electrónico válida');
        return;
    }
    
    // 驗證密碼
    const passwordError = validatePassword(password);
    if (passwordError) {
        showMessage(passwordError);
        return;
    }
    
    // 確認密碼
    if (password !== confirmPassword) {
        showMessage('Las contraseñas ingresadas no coinciden');
        return;
    }
    
    // 發送請求
    fetch('/user/register/send-code', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email: email })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            userEmail = email;
            showStep2();
            showMessage(data.message, 'success');
        } else {
            showMessage(data.message);
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    });
}

// 提交註冊
function submitRegistration() {
    hideMessages();
    
    const username = document.getElementById('username').value.trim();
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const code = document.getElementById('verificationCode').value.trim();
    
    // 驗證驗證碼
    const codeError = validateVerificationCode(code);
    if (codeError) {
        showMessage(codeError);
        return;
    }
    
    // 發送請求
    fetch('/user/register/submit', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            username: username,
            email: email,
            password: password,
            code: code
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.auto_login) {
                showMessage('¡Registro exitoso! Redirigiendo al portal de usuario...', 'success');
                setTimeout(() => {
                    window.location.href = '/user/portal';
                }, 2000);
            } else {
                showMessage('¡Registro exitoso! Redirigiendo a la página de inicio de sesión...', 'success');
                setTimeout(() => {
                    window.location.href = '/user/login';
                }, 2000);
            }
        } else {
            showMessage(data.message);
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    });
}

// 顯示步驟2
function showStep2() {
    document.getElementById('step1').style.display = 'none';
    document.getElementById('step2').style.display = 'block';
    document.getElementById('sentEmail').textContent = userEmail;
}

// 返回步驟1
function backToStep1() {
    document.getElementById('step2').style.display = 'none';
    document.getElementById('step1').style.display = 'block';
    hideMessages();
}

// ========== 忘記密碼功能 ==========

// 發送重置驗證碼
function sendResetCode() {
    hideMessages();
    
    const email = document.getElementById('email').value.trim();
    const sendButton = document.querySelector('button[onclick="sendResetCode()"]');
    
    if (!validateEmail(email)) {
        showMessage('Por favor ingrese una dirección de correo electrónico válida');
        return;
    }
    
    // 防止重複點擊
    if (sendButton.disabled) {
        return;
    }
    
    // 禁用按鈕並顯示加載狀態
    sendButton.disabled = true;
    const originalText = sendButton.textContent;
    sendButton.textContent = 'Enviando...';
    
    fetch('/user/forgot-password/send-code', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email: email })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            userEmail = email;
            showResetStep2();
            showMessage('El código de verificación ha sido enviado a su correo electrónico', 'success');
        } else {
            showMessage(data.message);
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    })
    .finally(() => {
        // 恢復按鈕狀態
        sendButton.disabled = false;
        sendButton.textContent = originalText;
    });
}

// 提交重置密碼
function submitResetPassword() {
    hideMessages();
    
    const code = document.getElementById('verificationCode').value.trim();
    const newPassword = document.getElementById('newPassword').value;
    const confirmNewPassword = document.getElementById('confirmNewPassword').value;
    
    // 驗證驗證碼
    const codeError = validateVerificationCode(code);
    if (codeError) {
        showMessage(codeError);
        return;
    }
    
    // 驗證新密碼
    const passwordError = validatePassword(newPassword);
    if (passwordError) {
        showMessage(passwordError);
        return;
    }
    
    // 確認密碼
    if (newPassword !== confirmNewPassword) {
        showMessage('Las contraseñas ingresadas no coinciden');
        return;
    }
    
    fetch('/user/forgot-password/reset', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            email: userEmail,
            code: code,
            new_password: newPassword
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage('¡Contraseña restablecida exitosamente! Redirigiendo a la página de inicio de sesión...', 'success');
            setTimeout(() => {
                window.location.href = '/user/login';
            }, 2000);
        } else {
            showMessage(data.message);
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    });
}

// 顯示重置步驟2
function showResetStep2() {
    document.getElementById('step1').style.display = 'none';
    document.getElementById('step2').style.display = 'block';
    document.getElementById('sentEmail').textContent = userEmail;
}

// ========== 修改密碼功能 ==========

// 提交修改密碼
function submitChangePassword() {
    hideMessages();
    
    const oldPassword = document.getElementById('oldPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmNewPassword = document.getElementById('confirmNewPassword').value;
    
    if (!oldPassword) {
        showMessage('Por favor ingrese su contraseña actual');
        return;
    }
    
    // 驗證新密碼
    const passwordError = validatePassword(newPassword);
    if (passwordError) {
        showMessage(passwordError);
        return;
    }
    
    // 確認密碼
    if (newPassword !== confirmNewPassword) {
        showMessage('Las contraseñas ingresadas no coinciden');
        return;
    }
    
    fetch('/user/change-password', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            old_password: oldPassword,
            new_password: newPassword
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showMessage('¡Contraseña modificada exitosamente!', 'success');
            setTimeout(() => {
                window.location.href = '/user/portal';
            }, 2000);
        } else {
            showMessage(data.message);
        }
    })
    .catch(error => {
        showMessage('Error de red, intente más tarde');
        console.error('Error:', error);
    });
}

// 返回上一頁
function goBack() {
    window.history.back();
}

// ========== 用戶門戶功能 ==========

// 顯示授權查詢Modal
function showLicenseQuery() {
    document.getElementById('licenseModal').style.display = 'block';
}

// 關閉授權查詢Modal
function closeLicenseModal() {
    document.getElementById('licenseModal').style.display = 'none';
    document.getElementById('queryRut').value = '';
    document.getElementById('licenseResult').style.display = 'none';
}

// 查詢授權
function queryLicense() {
    const rut = document.getElementById('queryRut').value.trim();
    const resultDiv = document.getElementById('licenseResult');
    
    if (!rut) {
        showMessage('Por favor ingrese el número RUT');
        return;
    }
    
    fetch(`/licenses/check_license?rut=${encodeURIComponent(rut)}`)
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            resultDiv.className = 'result-area error';
            resultDiv.innerHTML = `<strong>查詢失敗：</strong>${data.error}`;
        } else {
            resultDiv.className = 'result-area success';
            resultDiv.innerHTML = `
                <strong>查詢成功：</strong><br>
                RUT: ${data.rut}<br>
                企業: ${data.empresa || '未設定'}<br>
                狀態: ${data.estado}<br>
                到期日: ${data.fecha_expiracion || '永久'}
            `;
        }
        resultDiv.style.display = 'block';
    })
    .catch(error => {
        resultDiv.className = 'result-area error';
            resultDiv.innerHTML = '<strong>Error de consulta:</strong> Error de red, intente más tarde';
        resultDiv.style.display = 'block';
        console.error('Error:', error);
    });
}

// 顯示用戶信息Modal
function showUserInfo() {
    document.getElementById('userInfoModal').style.display = 'block';
}

// 關閉用戶信息Modal
function closeUserInfoModal() {
    document.getElementById('userInfoModal').style.display = 'none';
}

// ========== Modal 事件處理 ==========

// 點擊Modal外部關閉
window.onclick = function(event) {
    const licenseModal = document.getElementById('licenseModal');
    const userInfoModal = document.getElementById('userInfoModal');
    
    if (event.target === licenseModal) {
        closeLicenseModal();
    }
    if (event.target === userInfoModal) {
        closeUserInfoModal();
    }
}

// ESC鍵關閉Modal
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeLicenseModal();
        closeUserInfoModal();
    }
});
