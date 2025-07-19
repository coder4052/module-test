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

def get_usb_customer_history_path(usb_path, year):
    """USB 내 연도별 고객주문이력 파일 경로 반환"""
    return os.path.join(usb_path, f"고객주문정보_{year}.xlsx")

def check_usb_connection():
    usb_paths = ['D:', 'E:', 'F:', 'G:', 'H:']
    for path in usb_paths:
        # 반드시 드라이브 문자 뒤에 '\\' 붙이기
        real_path = path if path.endswith('\\') else path + '\\'
        if os.path.exists(real_path):
            return True, path
    return False, None

def extract_customer_order_from_shipment(df):
    """출고내역서에서 고객주문정보 추출 (USB용)"""
    customer_orders = []

    for _, row in df.iterrows():
        order_date = row.get('주문일시', '')
        
        try:
            # 문자열인 경우 파싱 시도
            if isinstance(order_date, str):
                order_datetime = pd.to_datetime(order_date, errors='coerce')
                if pd.isna(order_datetime):
                    continue

            elif pd.isna(order_date):
                continue
            else:
                order_datetime = order_date

            # ✅ 정상적인 datetime 객체만 여기에 도달
            year = order_datetime.year
            
            customer_order = {
                '주문일시': order_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                '상품이름': row.get('상품이름', ''),
                '옵션이름': row.get('옵션이름', ''),
                '상품수량': row.get('상품수량', 1),
                '상품결제금액': row.get('상품결제금액', 0),
                '주문자이름': row.get('주문자이름', ''),
                '주문자전화번호': row.get('주문자전화번호1', ''),
                '수취인이름': row.get('수취인이름', ''),
                '수취인우편번호': row.get('수취인우편번호', ''),
                '수취인주소': row.get('수취인주소', ''),
                '연도': year
            }

            customer_orders.append(customer_order)
        
        except Exception as e:
            st.warning(f"주문일시 파싱 오류: {order_date} - {str(e)}")
            continue

    return customer_orders


def create_customer_history_file(file_path):
    """고객주문정보 파일 생성 (헤더 포함)"""
    headers = ['주문일시', '상품이름', '옵션이름', '상품수량', '상품결제금액', 
               '주문자이름', '주문자전화번호', '수취인이름', '수취인우편번호', '수취인주소']
    
    empty_df = pd.DataFrame(columns=headers)
    
    try:
        empty_df.to_excel(file_path, index=False)
        return True
    except Exception as e:
        st.error(f"파일 생성 실패: {str(e)}")
        return False

def check_duplicate_orders(new_orders, existing_df):
    """중복 주문 확인 (주문일시 + 주문자이름 + 상품이름 + 수취인이름)"""
    if existing_df.empty:
        return new_orders
    
    unique_orders = []
    
    for new_order in new_orders:
        is_duplicate = False
        
        for _, existing_row in existing_df.iterrows():
            if (str(new_order['주문일시']) == str(existing_row['주문일시']) and
                str(new_order['주문자이름']) == str(existing_row['주문자이름']) and
                str(new_order['상품이름']) == str(existing_row['상품이름']) and
                str(new_order['수취인이름']) == str(existing_row['수취인이름'])):
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_orders.append(new_order)
    
    return unique_orders

def append_to_usb_customer_file(customer_orders, year):
    """USB의 고객주문이력 파일에 새 주문들을 append"""
    try:
        # USB 연결 확인
        usb_connected, usb_path = check_usb_connection()
        if not usb_connected:
            st.error("고객주문이력 파일이 담긴 USB를 삽입해주세요")
            return False
        
        # 파일 경로 생성
        file_path = get_usb_customer_history_path(usb_path, year)
        
        # 파일 존재 여부 확인
        if not os.path.exists(file_path):
            st.info(f"{year}년 고객주문정보 파일이 없어 새로 생성합니다...")
            if not create_customer_history_file(file_path):
                return False
        
        # 기존 파일 읽기
        try:
            existing_df = pd.read_excel(file_path)
        except PermissionError:
            st.error("파일이 다른 프로그램에서 열려있으니 닫고 다시 시도해주세요")
            return False
        except Exception as e:
            st.error(f"파일 읽기 오류: {str(e)}")
            return False
        
        # 중복 확인
        unique_orders = check_duplicate_orders(customer_orders, existing_df)
        
        if not unique_orders:
            st.info("모든 주문이 이미 등록되어 있습니다 (중복 없음)")
            return True
        
        # 새 주문 추가
        new_df = pd.DataFrame(unique_orders)
        updated_df = pd.concat([existing_df, new_df], ignore_index=True)
        
        # 파일 저장
        try:
            updated_df.to_excel(file_path, index=False)
            st.success(f"✅ {len(unique_orders)}개의 새로운 주문이 {year}년 고객주문정보에 추가되었습니다!")
            return True
        except PermissionError:
            st.error("파일이 다른 프로그램에서 열려있으니 닫고 다시 시도해주세요")
            return False
        except Exception as e:
            st.error(f"파일 저장 오류: {str(e)}")
            return False
            
    except Exception as e:
        st.error(f"USB 연결이 끊어져서 에러가 발생했습니다: {str(e)}")
        return False

def load_customer_order_history_from_usb(year):
    """USB에서 연도별 고객주문이력 불러오기"""
    try:
        usb_connected, usb_path = check_usb_connection()
        if not usb_connected:
            return [], None
        
        file_path = get_usb_customer_history_path(usb_path, year)
        
        if not os.path.exists(file_path):
            return [], None

        # 대용량 파일 처리
        try:
            # 청크 단위로 읽기
            chunk_reader = pd.read_excel(file_path, chunksize=1000)
            orders = []
            for chunk in chunk_reader:
                orders.extend(chunk.to_dict('records'))
            
            if not orders:
                return [], None
                
        except Exception:
            # 일반적인 방법으로 읽기
            df = pd.read_excel(file_path)
            
            if df.empty:
                return [], None
            
            orders = df.to_dict('records')
        
        # 마지막 수정 시간 가져오기
        last_update = datetime.fromtimestamp(os.path.getmtime(file_path), tz=KST)
        
        return orders, last_update
        
    except Exception as e:
        st.error(f"USB에서 고객주문이력 로드 중 오류: {str(e)}")
        return [], None
        
