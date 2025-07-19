import base64
import json
import time
import os
import logging
import pandas as pd
import streamlit as st
import requests
from datetime import datetime, timezone, timedelta

# 한국 시간대 설정
KST = timezone(timedelta(hours=9))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()]
)

# 다른 모듈에서 가져오는 함수들
from modules.security import encrypt_results, decrypt_results
from config.settings import REPO_OWNER, REPO_NAME, SHIPMENT_FILE_PATH, BOX_FILE_PATH, STOCK_FILE_PATH

def get_current_time_str() -> str:
    """현재 한국 시간(KST)을 'YYYY-MM-DD HH:MM' 형식 문자열로 반환"""
    return datetime.now(KST).strftime('%Y-%m-%d %H:%M')


def save_to_github(data, file_path, commit_message):
    """GitHub에 암호화된 데이터 저장 (공통 함수)"""
    try:
        github_token = st.secrets["github_token"]
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
        
        encrypted_data = encrypt_results(data)
        if not encrypted_data:
            return False
        
        data_package = {
            'encrypted_data': encrypted_data,
            'last_update': datetime.now(KST).isoformat(),
            'timestamp': datetime.now(KST).timestamp()
        }
        
        headers = {"Authorization": f"token {github_token}"}
        
        # 재시도 로직 추가
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=30)
                sha = response.json().get("sha") if response.status_code == 200 else None
                
                content = base64.b64encode(json.dumps(data_package, ensure_ascii=False, indent=2).encode()).decode()
                
                payload = {
                    "message": commit_message,
                    "content": content,
                    "branch": "main"
                }
                
                if sha:
                    payload["sha"] = sha
                
                response = requests.put(url, headers=headers, json=payload, timeout=30)
                
                if response.status_code in [200, 201]:
                    return True
                else:
                    st.warning(f"GitHub 저장 실패 (시도 {attempt + 1}/{max_retries}): {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                st.warning(f"네트워크 오류 (시도 {attempt + 1}/{max_retries}): {str(e)}")
                
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 지수 백오프
        
        return False
        
    except Exception as e:
        st.error(f"GitHub 저장 중 오류: {e}")
        return False

def load_from_github(file_path):
    """GitHub에서 암호화된 데이터 불러오기 (공통 함수) - 개선된 에러 처리"""
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            github_token = st.secrets["github_token"]
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{file_path}"
            
            headers = {"Authorization": f"token {github_token}"}
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                content = response.json()["content"]
                decoded_content = base64.b64decode(content).decode()
                data = json.loads(decoded_content)
                
                encrypted_results = data.get('encrypted_data')
                if encrypted_results:
                    results = decrypt_results(encrypted_results)
                    last_update_str = data.get('last_update')
                    last_update = datetime.fromisoformat(last_update_str) if last_update_str else None
                    return results, last_update
                    
            elif response.status_code == 404:
                # 파일이 없는 경우 - 정상적인 상황
                return {}, None
            else:
                # 다른 에러의 경우
                if attempt == max_retries - 1 and st.session_state.get('admin_mode', False):
                    st.warning(f"GitHub 데이터 로드 실패: {response.status_code}")
                    
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logging.error(f"네트워크 오류로 인한 데이터 로드 실패: {str(e)}")
                if st.session_state.get('admin_mode', False):
                    st.warning(f"네트워크 오류로 인한 데이터 로드 실패: {str(e)}")
        except Exception as e:
            if attempt == max_retries - 1:
                logging.error(f"GitHub 데이터 로드 중 오류: {str(e)}")
                if st.session_state.get('admin_mode', False):
                    st.error(f"GitHub 데이터 로드 중 오류: {str(e)}")
        
        if attempt < max_retries - 1:
            time.sleep(1)  # 재시도 전 대기
    
    return {}, None

def save_shipment_data(results):
    """출고 현황 데이터 저장"""
    commit_message = f"출고 현황 업데이트 - {get_current_time_str()}"
    return save_to_github(results, SHIPMENT_FILE_PATH, commit_message)

def load_shipment_data():
    """출고 현황 데이터 불러오기"""
    return load_from_github(SHIPMENT_FILE_PATH)

def save_box_data(box_results):
    """박스 계산 데이터 저장"""
    commit_message = f"출고 현황 업데이트 - {get_current_time_str()}"
    return save_to_github(box_results, BOX_FILE_PATH, commit_message)

def load_box_data():
    """박스 계산 데이터 불러오기"""
    return load_from_github(BOX_FILE_PATH)

def save_stock_data(stock_results):
    """재고 현황 데이터 저장"""
    commit_message = f"출고 현황 업데이트 - {get_current_time_str()}"
    return save_to_github(stock_results, STOCK_FILE_PATH, commit_message)

def load_stock_data():
    """재고 현황 데이터 불러오기"""
    return load_from_github(STOCK_FILE_PATH)

def get_stock_product_keys():
    """재고 관리용 상품 키 목록 생성 (출고 현황과 동기화)"""
    shipment_results, _ = load_shipment_data()
    if shipment_results:
        return sorted(shipment_results.keys())
    return []

def format_stock_display_time(datetime_str):
    """재고 입력 시간을 한국 시간대로 포맷팅"""
    try:
        dt = datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        else:
            dt = dt.astimezone(KST)
        
        weekdays = ['월', '화', '수', '목', '금', '토', '일']
        weekday = weekdays[dt.weekday()]
        
        return dt.strftime(f"%m월 %d일 ({weekday}) %H:%M")
    except:
        return datetime_str

