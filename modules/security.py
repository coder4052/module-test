import json
import base64
import re
import streamlit as st
from cryptography.fernet import Fernet

def encrypt_results(results):
    """집계 결과 암호화"""
    try:
        key = st.secrets["encryption_key"]
        f = Fernet(key.encode())
        
        json_str = json.dumps(results, ensure_ascii=False)
        encrypted_data = f.encrypt(json_str.encode())
        return base64.b64encode(encrypted_data).decode()
    except Exception as e:
        st.error(f"암호화 중 오류: {e}")
        return None

def decrypt_results(encrypted_data):
    """암호화된 결과 복호화"""
    try:
        key = st.secrets["encryption_key"]
        f = Fernet(key.encode())
        
        decoded_data = base64.b64decode(encrypted_data.encode())
        decrypted_data = f.decrypt(decoded_data)
        return json.loads(decrypted_data.decode())
    except Exception as e:
        st.error(f"복호화 중 오류: {e}")
        return {}

# 🔒 개인정보 보호 강화 함수들
def mask_name(name):
    """이름 마스킹 (김○○)"""
    if not name or len(str(name)) < 1:
        return "알 수 없음"
    
    name = str(name)
    if len(name) >= 2:
        return name[0] + '○' * (len(name) - 1)
    return name

def mask_phone(phone):
    """전화번호 마스킹 (010-****-1234)"""
    if not phone:
        return "****"
    
    phone = str(phone)
    digits = re.sub(r'\D', '', phone)
    
    if len(digits) >= 8:
        return f"{digits[:3]}-****-{digits[-4:]}"
    elif len(digits) >= 4:
        return f"****-{digits[-4:]}"
    else:
        return "****"

def mask_address(address):
    """주소 마스킹 (서울시 강남구 ○○동)"""
    if not address:
        return "주소 미확인"
    
    address = str(address)
    
    # 동/읍/면 뒤의 상세 주소 마스킹
    pattern = r'(.+?(?:동|읍|면|가|리))(.+)'
    match = re.search(pattern, address)
    
    if match:
        return match.group(1) + " ○○○"
    else:
        # 패턴이 없으면 앞 10글자만 표시
        if len(address) > 10:
            return address[:10] + "..."
        return address

def mask_customer_info(customer_info):
    """고객 정보 마스킹"""
    return {
        'orderer_name': mask_name(customer_info.get('orderer_name', '')),
        'orderer_phone': mask_phone(customer_info.get('orderer_phone', '')),
        'recipient_name': mask_name(customer_info.get('recipient_name', '')),
        'order_info': customer_info.get('order_info', '')
    }

def find_matching_customer(daily_customer, customer_df):
    """고객 정보 매칭 (이름 또는 연락처 기반)"""
    for _, row in customer_df.iterrows():
        # 이름 매칭
        if row.get('name', '') == daily_customer['orderer_name']:
            return row
        
        # 연락처 매칭 (뒤 4자리 비교)
        if match_phone_number(row.get('phone', ''), daily_customer['orderer_phone']):
            return row
    
    return None

def match_phone_number(stored_phone, current_phone):
    """전화번호 매칭 (개인정보 보호를 위해 뒤 4자리만 비교)"""
    if not stored_phone or not current_phone:
        return False
    
    # 숫자만 추출
    stored_digits = re.sub(r'\D', '', str(stored_phone))
    current_digits = re.sub(r'\D', '', str(current_phone))
    
    # 뒤 4자리 비교
    return len(stored_digits) >= 4 and len(current_digits) >= 4 and \
           stored_digits[-4:] == current_digits[-4:]

