# 표준 라이브러리
import os
import io
import re
import gc
import time
import base64
import json
import time
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
from collections import defaultdict
import logging
import traceback
from functools import wraps

# 외부 라이브러리
import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# 설정 및 상수
from config.constants import BOX_RULES, BOX_COST_ORDER, STOCK_THRESHOLDS, BOX_DESCRIPTIONS
from config.settings import PAGE_CONFIG, REPO_OWNER, REPO_NAME, SHIPMENT_FILE_PATH, BOX_FILE_PATH, STOCK_FILE_PATH

# UI 스타일 및 헬퍼
from modules.ui_utils import apply_custom_styles, render_metric_card

# Streamlit 페이지 설정
st.set_page_config(**PAGE_CONFIG)

# UI 스타일 적용
apply_custom_styles()

# 메모리 관리
from modules.memory import MemoryManager, force_garbage_collection

# 보안 및 개인정보 보호
from modules.security import (
    encrypt_results, decrypt_results,
    mask_name, mask_phone, mask_address, mask_customer_info,
    match_phone_number, find_matching_customer
)

# 저장/입출력
from modules.storage import (
    save_to_github, load_from_github,
    save_shipment_data, load_shipment_data,
    save_box_data, load_box_data,
    save_stock_data, load_stock_data,
    get_usb_customer_history_path,
    extract_customer_order_from_shipment,
    create_customer_history_file, check_duplicate_orders,
    get_stock_product_keys, format_stock_display_time
)

# 데이터 처리
from modules.data_processing import (
    sanitize_data,
    extract_product_from_option, extract_product_from_name,
    parse_option_info, standardize_capacity, standardize_capacity_for_box,
    group_orders_by_recipient, get_product_quantities,
    calculate_box_for_order, calculate_box_requirements,
    process_unified_file, get_product_color
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('seroe_app.log'),
        logging.StreamHandler()
    ]
)

def handle_errors(func):
    """에러 처리 데코레이터"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            st.error("❌ 파일을 찾을 수 없습니다.")
            st.info("💡 파일 경로를 확인하고 다시 시도해주세요.")
            logging.error(f"파일 없음: {str(e)}")
            return None
        except PermissionError as e:
            st.error("❌ 파일 접근 권한이 없습니다.")
            st.info("💡 파일이 다른 프로그램에서 열려있지 않은지 확인해주세요.")
            logging.error(f"권한 오류: {str(e)}")
            return None
        except pd.errors.EmptyDataError as e:
            st.error("❌ 파일이 비어있습니다.")
            st.info("💡 올바른 엑셀 파일인지 확인해주세요.")
            logging.error(f"빈 파일: {str(e)}")
            return None
        except requests.exceptions.RequestException as e:
            st.error("❌ 네트워크 연결 오류가 발생했습니다.")
            st.info("💡 인터넷 연결을 확인하고 다시 시도해주세요.")
            logging.error(f"네트워크 오류: {str(e)}")
            return None
        except Exception as e:
            st.error(f"❌ 예상치 못한 오류가 발생했습니다")
            
            # 관리자 모드에서는 상세 오류 표시
            if st.session_state.get('admin_mode', False):
                st.error("🔧 **관리자 전용 상세 오류:**")
                st.code(f"{str(e)}\n\n{traceback.format_exc()}")
            else:
                st.info("💡 문제가 지속되면 관리자에게 문의하세요.")
            
            logging.error(f"예상치 못한 오류: {str(e)}\n{traceback.format_exc()}")
            return None
    return wrapper

def safe_execute(func, error_message="처리 중 오류가 발생했습니다", default_return=None):
    """안전한 함수 실행"""
    try:
        return func()
    except Exception as e:
        st.error(f"❌ {error_message}")
        if st.session_state.get('admin_mode', False):
            st.error(f"🔧 **오류 상세**: {str(e)}")
        logging.error(f"{error_message}: {str(e)}")
        return default_return

@handle_errors
def analyze_customer_orders(customer_history_file, shipment_file):
    """고객 주문 이력 분석 - 메인 함수"""
    try:
        # 1. 파일 읽기
        history_df = read_excel_file_safely(customer_history_file)
        shipment_df = read_excel_file_safely(shipment_file)
        
        if history_df is None or shipment_df is None:
            return None
        
        # 2. 데이터 검증
        required_history_cols = ['주문자이름', '주문자전화번호', '상품이름', '상품수량']
        required_shipment_cols = ['주문자이름', '주문자전화번호1']
        
        missing_history = [col for col in required_history_cols if col not in history_df.columns]
        missing_shipment = [col for col in required_shipment_cols if col not in shipment_df.columns]
        
        if missing_history:
            st.error(f"❌ 고객주문정보 파일에 필수 컬럼이 없습니다: {', '.join(missing_history)}")
            return None
        
        if missing_shipment:
            st.error(f"❌ 출고내역서 파일에 필수 컬럼이 없습니다: {', '.join(missing_shipment)}")
            return None
        
        # 3. 고객 매칭 및 분석
        results = match_and_analyze_customers(history_df, shipment_df)
        
        return results
        
    except Exception as e:
        st.error(f"❌ 고객 분석 중 오류: {str(e)}")
        logging.error(f"고객 분석 오류: {str(e)}")
        return None

def match_and_analyze_customers(history_df, shipment_df):
    """고객 매칭 및 상세 분석"""
    results = {
        'reorder_customers': [],
        'new_customers': [],
        'total_today_orders': len(shipment_df),
        'reorder_rate': 0
    }
    
    # 오늘 출고 고객 정보 추출
    today_customers = []
    
    for _, row in shipment_df.iterrows():
        customer_info = {
            'name': str(row.get('주문자이름', '')).strip(),
            'phone': clean_phone_number(str(row.get('주문자전화번호1', ''))),
            'recipient': str(row.get('수취인이름', '')).strip(),
            'product': str(row.get('상품이름', '')),
            'option': str(row.get('옵션이름', '')),
            'quantity': row.get('상품수량', 1),
            'amount': row.get('상품결제금액', 0)
        }
        
        # 상품 정보 정제
        if customer_info['option']:
            option_quantity, capacity = parse_option_info(customer_info['option'])
            total_quantity = customer_info['quantity'] * option_quantity
            
            product_name = extract_product_from_option(customer_info['option'])
            if product_name == "기타":
                product_name = extract_product_from_name(customer_info['product'])
            
            standardized_capacity = standardize_capacity(capacity)
            if standardized_capacity:
                customer_info['processed_product'] = f"{product_name} {standardized_capacity}"
                customer_info['processed_quantity'] = total_quantity
            else:
                customer_info['processed_product'] = product_name
                customer_info['processed_quantity'] = total_quantity
        else:
            customer_info['processed_product'] = customer_info['product']
            customer_info['processed_quantity'] = customer_info['quantity']
        
        today_customers.append(customer_info)
    
    # 각 고객에 대해 과거 이력 검색
    for today_customer in today_customers:
        matched_history = find_customer_history(today_customer, history_df)
        
        if matched_history:
            # 재주문 고객
            customer_analysis = analyze_customer_history(today_customer, matched_history)
            results['reorder_customers'].append(customer_analysis)
        else:
            # 신규 고객
            results['new_customers'].append({
                'name': mask_name(today_customer['name']),
                'product': today_customer['processed_product'],
                'quantity': today_customer['processed_quantity'],
                'amount': today_customer['amount']
            })
    
    # 재주문율 계산
    if results['total_today_orders'] > 0:
        results['reorder_rate'] = (len(results['reorder_customers']) / results['total_today_orders']) * 100
    
    return results

def find_customer_history(today_customer, history_df):
    """고객 과거 이력 찾기 (이름 + 전화번호 매칭)"""
    matched_orders = []
    
    for _, history_row in history_df.iterrows():
        history_name = str(history_row.get('주문자이름', '')).strip()
        history_phone = clean_phone_number(str(history_row.get('주문자전화번호', '')))
        
        # 이름 매칭 또는 전화번호 뒤 4자리 매칭
        name_match = history_name == today_customer['name']
        phone_match = False
        
        if len(history_phone) >= 4 and len(today_customer['phone']) >= 4:
            phone_match = history_phone[-4:] == today_customer['phone'][-4:]
        
        if name_match or phone_match:
            # 상품 정보 정제
            product_name = str(history_row.get('상품이름', ''))
            option_info = str(history_row.get('옵션이름', ''))
            quantity = history_row.get('상품수량', 1)
            amount = history_row.get('상품결제금액', 0)
            order_date = history_row.get('주문일시', '')
            
            # 날짜 정제
            try:
                if pd.notna(order_date):
                    order_datetime = pd.to_datetime(order_date, errors='coerce')
                    if pd.notna(order_datetime):
                        formatted_date = order_datetime.strftime('%Y-%m-%d')
                    else:
                        formatted_date = str(order_date)
                else:
                    formatted_date = "날짜 미확인"
            except:
                formatted_date = "날짜 미확인"
            
            # 상품 정보 처리
            if option_info and option_info != 'nan':
                option_quantity, capacity = parse_option_info(option_info)
                total_quantity = quantity * option_quantity
                
                processed_product = extract_product_from_option(option_info)
                if processed_product == "기타":
                    processed_product = extract_product_from_name(product_name)
                
                standardized_capacity = standardize_capacity(capacity)
                if standardized_capacity:
                    final_product = f"{processed_product} {standardized_capacity}"
                else:
                    final_product = processed_product
            else:
                final_product = product_name
                total_quantity = quantity
            
            matched_orders.append({
                'date': formatted_date,
                'product': final_product,
                'quantity': total_quantity,
                'amount': amount
            })
    
    return matched_orders if matched_orders else None

def analyze_customer_history(today_customer, history_orders):
    """고객 주문 이력 상세 분석"""
    # 총 주문 횟수 (오늘 주문 포함)
    total_orders = len(history_orders) + 1
    
    # 총 결제 금액
    total_amount = sum(order.get('amount', 0) for order in history_orders)
    total_amount += today_customer.get('amount', 0)
    
    # 최근 주문일 (오늘 제외)
    valid_dates = []
    for order in history_orders:
        if order['date'] != "날짜 미확인":
            try:
                date_obj = pd.to_datetime(order['date'], errors='coerce')
                if pd.notna(date_obj):
                    valid_dates.append(date_obj)
            except:
                continue
    
    last_order_date = max(valid_dates).strftime('%Y-%m-%d') if valid_dates else "확인 불가"
    
    # 주문 이력 정리 (최근 10개만)
    recent_history = sorted(history_orders, 
                           key=lambda x: pd.to_datetime(x['date'], errors='coerce') 
                           if x['date'] != "날짜 미확인" else pd.Timestamp('1900-01-01'), 
                           reverse=True)[:10]
    
    return {
        'name': mask_name(today_customer['name']),
        'real_name': today_customer['name'],  # 실명 (분석용)
        'phone': mask_phone(today_customer['phone']),
        'total_orders': total_orders,
        'total_amount': total_amount,
        'last_order_date': last_order_date,
        'current_order': {
            'product': today_customer['processed_product'],
            'quantity': today_customer['processed_quantity'],
            'amount': today_customer.get('amount', 0)
        },
        'order_history': recent_history
    }

def clean_phone_number(phone):
    """전화번호에서 숫자만 추출"""
    return re.sub(r'\D', '', str(phone))

def display_customer_analysis(results):
    """고객 분석 결과 표시"""
    reorder_customers = results['reorder_customers']
    new_customers = results['new_customers']
    total_orders = results['total_today_orders']
    reorder_rate = results['reorder_rate']
    
    # 요약 메트릭
    st.markdown("### 📊 오늘의 고객 분석 결과")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        html = render_metric_card(
            title="👥 전체 주문",
            value=f"{total_orders}건",
            background_gradient="linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
        )
        st.markdown(html, unsafe_allow_html=True)
    
    with col2:
        html = render_metric_card(
            title="🔄 재주문 고객",
            value=f"{len(reorder_customers)}명",
            background_gradient="linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)"
        )
        st.markdown(html, unsafe_allow_html=True)
    
    with col3:
        html = render_metric_card(
            title="✨ 신규 고객",
            value=f"{len(new_customers)}명",
            background_gradient="linear-gradient(135deg, #ff9800 0%, #f57c00 100%)"
        )
        st.markdown(html, unsafe_allow_html=True)
    
    with col4:
        html = render_metric_card(
            title="📈 재주문율",
            value=f"{reorder_rate:.1f}%",
            background_gradient="linear-gradient(135deg, #9c27b0 0%, #7b1fa2 100%)"
        )
        st.markdown(html, unsafe_allow_html=True)
    
    # 재주문 고객 상세 정보
    if reorder_customers:
        st.markdown("---")
        st.markdown("### 🔄 재주문 고객 상세 분석")
        
        for i, customer in enumerate(reorder_customers, 1):
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #e8f5e8 0%, #c8e6c9 100%); 
                        padding: 25px; border-radius: 15px; margin: 20px 0; 
                        border-left: 5px solid #4caf50;">
                <h4 style="margin: 0 0 15px 0; color: #2e7d32; font-weight: 600;">
                    👤 {customer['name']} (고객 #{i})
                </h4>
                <div style="font-size: 16px; color: #424242; line-height: 1.6;">
                    📊 <strong>총 주문 횟수:</strong> {customer['total_orders']}회<br>
                    💰 <strong>누적 결제금액:</strong> {customer['total_amount']:,}원<br>
                    📅 <strong>최근 주문일:</strong> {customer['last_order_date']}<br>
                    🛒 <strong>오늘 주문:</strong> {customer['current_order']['product']} {customer['current_order']['quantity']}개 
                    ({customer['current_order']['amount']:,}원)
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 주문 이력 상세 표시
            if customer['order_history']:
                st.markdown("**📋 과거 주문 이력 (최근 10건)**")
                
                history_data = []
                for j, order in enumerate(customer['order_history'], 1):
                    history_data.append({
                        "순번": j,
                        "주문일": order['date'],
                        "상품명": order['product'],
                        "수량": f"{order['quantity']}개",
                        "결제금액": f"{order['amount']:,}원"
                    })
                
                history_df = pd.DataFrame(history_data)
                st.dataframe(history_df, use_container_width=True, hide_index=True)
            
            st.markdown("---")
    
    # 신규 고객 정보
    if new_customers:
        st.markdown("### ✨ 신규 고객")
        
        new_customer_data = []
        for i, customer in enumerate(new_customers, 1):
            new_customer_data.append({
                "순번": i,
                "고객명": customer['name'],
                "주문상품": customer['product'],
                "수량": f"{customer['quantity']}개",
                "결제금액": f"{customer['amount']:,}원"
            })
        
        new_df = pd.DataFrame(new_customer_data)
        st.dataframe(new_df, use_container_width=True, hide_index=True)
    
    # 결과 다운로드 버튼
    st.markdown("---")
    st.markdown("### 💾 분석 결과 다운로드")
    
    if st.button("📊 분석 결과 Excel 다운로드"):
        output_file = create_analysis_report(results)
        if output_file:
            st.download_button(
                label="📥 고객분석결과.xlsx 다운로드",
                data=output_file,
                file_name=f"고객분석결과_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

def create_analysis_report(results):
    """분석 결과를 Excel 파일로 생성"""
    try:
        from io import BytesIO
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # 재주문 고객 시트
            if results['reorder_customers']:
                reorder_data = []
                for customer in results['reorder_customers']:
                    reorder_data.append({
                        '고객명': customer['real_name'],
                        '총주문횟수': customer['total_orders'],
                        '누적결제금액': customer['total_amount'],
                        '최근주문일': customer['last_order_date'],
                        '오늘주문상품': customer['current_order']['product'],
                        '오늘주문수량': customer['current_order']['quantity'],
                        '오늘결제금액': customer['current_order']['amount']
                    })
                
                reorder_df = pd.DataFrame(reorder_data)
                reorder_df.to_excel(writer, sheet_name='재주문고객', index=False)
            
            # 신규 고객 시트
            if results['new_customers']:
                new_data = []
                for customer in results['new_customers']:
                    new_data.append({
                        '고객명': customer['name'],
                        '주문상품': customer['product'],
                        '수량': customer['quantity'],
                        '결제금액': customer['amount']
                    })
                
                new_df = pd.DataFrame(new_data)
                new_df.to_excel(writer, sheet_name='신규고객', index=False)
        
        output.seek(0)
        return output.getvalue()
    
    except Exception as e:
        st.error(f"❌ Excel 파일 생성 실패: {str(e)}")
        return None

def read_excel_file_safely(uploaded_file):
    """안전한 엑셀 파일 읽기 - 강화된 에러 처리"""
    if uploaded_file is None:
        st.error("❌ 업로드된 파일이 없습니다.")
        return None
    
    # 파일 크기 확인
    file_size = uploaded_file.size
    if file_size > 50 * 1024 * 1024:  # 50MB 제한
        st.error("❌ 파일 크기가 너무 큽니다. (최대 50MB)")
        st.info("💡 파일 크기를 줄이거나 다른 파일을 선택해주세요.")
        return None
    
    # 파일 확장자 확인
    if not uploaded_file.name.lower().endswith('.xlsx'):
        st.error("❌ .xlsx 파일만 지원합니다.")
        st.info("💡 엑셀 파일을 .xlsx 형식으로 저장해주세요.")
        return None
    
    df = None
    read_options = [
        {'engine': 'openpyxl', 'data_only': True},
        {'engine': 'openpyxl', 'data_only': False},
        {'engine': 'openpyxl'},
    ]
    
    for i, options in enumerate(read_options):
        try:
            # 파일 포인터 리셋
            uploaded_file.seek(0)
            df = pd.read_excel(uploaded_file, **options)
            
            if len(df) == 0:
                st.warning(f"⚠️ {uploaded_file.name}: 파일이 비어있습니다")
                continue
                
            if i == 0:
                st.success(f"✅ {uploaded_file.name}: 파일 읽기 성공 ({len(df):,}행)")
            else:
                st.info(f"ℹ️ {uploaded_file.name}: 대체 방식으로 읽기 성공 ({len(df):,}행)")
            break
            
        except pd.errors.EmptyDataError:
            st.error(f"❌ {uploaded_file.name}: 파일에 데이터가 없습니다")
            continue
        except pd.errors.ParserError as e:
            st.error(f"❌ {uploaded_file.name}: 파일 형식 오류")
            if i == len(read_options) - 1:
                st.info("💡 파일이 손상되었거나 올바른 Excel 형식이 아닙니다.")
            continue
        except Exception as e:
            if i == len(read_options) - 1:
                st.error(f"❌ {uploaded_file.name}: 모든 읽기 방식 실패")
                st.info("💡 파일을 다시 저장하거나 다른 파일을 시도해주세요.")
                logging.error(f"파일 읽기 실패: {str(e)}")
            continue
    
    return df

# 한국 시간대 설정
KST = timezone(timedelta(hours=9))

# 🔒 관리자 인증 함수
def check_admin_access():
    """관리자 권한 확인"""
    if "admin_mode" not in st.session_state:
        st.session_state.admin_mode = False
    
    if not st.session_state.admin_mode:
        st.sidebar.title("🔐 관리자 로그인")
        password = st.sidebar.text_input("관리자 비밀번호", type="password", key="admin_password")
        
        if st.sidebar.button("로그인"):
            try:
                if password == st.secrets["admin_password"]:
                    st.session_state.admin_mode = True
                    st.sidebar.success("✅ 관리자 로그인 성공!")
                    st.rerun()
                else:
                    st.sidebar.error("❌ 비밀번호가 틀렸습니다")
            except Exception as e:
                st.sidebar.error("❌ 관리자 비밀번호 설정을 확인하세요")
        
        st.sidebar.markdown("""
        ### 👥 팀원 모드
        **이용 가능한 기능:**
        - 📊 최신 출고 현황 확인
        - 📦 택배박스 계산 결과 확인  
        - 📈 상품별 수량 차트 보기
        - 📱 모바일에서도 확인 가능
        
        **🔒 보안 정책:**
        - 고객 개인정보는 완전히 보호됩니다
        - 집계된 출고 현황만 표시됩니다
        """)
        
        return False
    else:
        st.sidebar.success("👑 관리자 모드 활성화")
        
        if st.sidebar.button("🚪 로그아웃"):
            st.session_state.admin_mode = False
            if "admin_password" in st.session_state:
                del st.session_state.admin_password
            st.rerun()
        
        return True

@handle_errors
def process_uploaded_file_once(uploaded_file):
    """파일을 한 번만 읽고 모든 처리에 재사용 - 강화된 에러 처리"""
    if uploaded_file is None:
        st.error("❌ 업로드된 파일이 없습니다.")
        return None, None, None, None
    
    # 1. 파일 읽기
    df = read_excel_file_safely(uploaded_file)
    
    if df is None:
        st.error("❌ 파일 읽기에 실패했습니다.")
        return None, None, None, None
    
    # 2. 데이터 유효성 검사
    if df.empty:
        st.error("❌ 파일에 데이터가 없습니다.")
        st.info("💡 데이터가 포함된 엑셀 파일을 업로드해주세요.")
        return None, None, None, None
    
    # 3. 필수 컬럼 확인
    required_columns = ['상품이름', '옵션이름', '상품수량']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        st.error(f"❌ 필수 컬럼이 누락되었습니다: {', '.join(missing_columns)}")
        st.info("💡 올바른 출고내역서 파일인지 확인해주세요.")
        
        # 사용 가능한 컬럼 표시
        available_columns = list(df.columns)
        with st.expander("🔍 파일의 컬럼 목록 보기"):
            st.write("현재 파일에 포함된 컬럼:")
            for col in available_columns:
                st.write(f"- {col}")
        
        return None, None, None, None
    
    # 4. 데이터 정제
    try:
        df_clean = sanitize_data(df)
        
        if df_clean.empty:
            st.error("❌ 데이터 정제 후 사용 가능한 데이터가 없습니다.")
            st.info("💡 데이터 형식을 확인하고 다시 시도해주세요.")
            return None, None, None, None
        
        # 5. 복사본 생성
        df_shipment = df_clean.copy()
        df_box = df_clean.copy()
        df_customer = df_clean.copy()
        
        st.success(f"✅ 파일 처리 완료: {len(df_clean):,}개 주문 준비됨")
        
        return df_clean, df_shipment, df_box, df_customer
        
    except Exception as e:
        st.error(f"❌ 데이터 처리 중 오류가 발생했습니다.")
        if st.session_state.get('admin_mode', False):
            st.error(f"🔧 **오류 상세**: {str(e)}")
        logging.error(f"데이터 처리 오류: {str(e)}")
        return None, None, None, None


# 한국 시간 기준 날짜 정보 생성
def get_korean_date():
    """한국 시간 기준 날짜 정보 반환"""
    now = datetime.now(KST)
    weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
    weekday = weekdays[now.weekday()]
    
    return now.strftime(f"%Y년 %m월 %d일 ({weekday})")

# 메인 페이지 - 영구 저장 시스템
korean_date = get_korean_date()
st.title(f"🎯 테스트용 - {korean_date}")
st.markdown("### 🔒 테스트 버전")

# 관리자 권한 확인
is_admin = check_admin_access()

# 탭 구성
tab1, tab2, tab3, tab4 = st.tabs(["📦 출고 현황", "📦 박스 계산", "📊 재고 관리", "👥 고객 관리"])

# 관리자 파일 업로드
if is_admin:
    st.markdown("---")
    st.markdown("## 👑 관리자 전용 - 통합 파일 업로드")
    
    st.info("""
    🔒 **보안 정책**: 업로드된 엑셀 파일의 고객 개인정보는 즉시 제거되며, 집계 결과만 암호화되어 저장됩니다.
    
    📝 **영구 저장 시스템**:
    - 출고 현황, 박스 계산, 재고 관리 결과가 모두 GitHub에 암호화되어 저장됩니다
    - 로그아웃, 새로고침, 탭 닫기와 무관하게 지속적으로 표시됩니다
    - 모든 팀원이 언제든지 최신 결과를 확인할 수 있습니다
    - **출고 현황**: 200ml 그대로 표시
    - **박스 계산**: 200ml을 240ml과 동일하게 처리
    - **재고 관리**: 출고 현황과 자동 동기화
    - **.xlsx 형식만 지원**
    """)
    
    uploaded_file = st.file_uploader(
        "📁 통합 엑셀 파일을 업로드하세요 (.xlsx만 지원)",
        type=['xlsx'],
        help="통합 출고내역서(.xlsx)를 업로드하세요. 고객 정보는 자동으로 제거됩니다.",
        key="unified_file_uploader"
    )
    
    if uploaded_file:
        # 파일 유효성 사전 검사
        if not uploaded_file.name.lower().endswith('.xlsx'):
            st.error("❌ .xlsx 파일만 업로드 가능합니다.")
            st.info("💡 엑셀 파일을 .xlsx 형식으로 저장해주세요.")
            st.stop()
        
        if uploaded_file.size > 50 * 1024 * 1024:  # 50MB 제한
            st.error("❌ 파일 크기가 너무 큽니다. (최대 50MB)")
            st.info("💡 파일 크기를 줄이거나 나누어서 업로드해주세요.")
            st.stop()
        
        # 세션 상태에 파일 저장
        st.session_state.last_uploaded_file = uploaded_file
    
        # 전체 처리를 안전하게 실행
        def safe_process_all():
            """전체 처리 과정을 안전하게 실행"""
            success_count = 0
            total_processes = 2
            error_details = []
            
            # 메모리 관리와 함께 전체 처리
            with MemoryManager("전체 파일 처리") as main_mem:
                with st.spinner('🔒 통합 파일 보안 처리 및 영구 저장 중...'):
                    # 1. 파일 전처리
                    try:
                        df_clean, df_shipment, df_box, _ = process_uploaded_file_once(uploaded_file)
                        
                        if df_clean is None:
                            st.error("❌ 파일 처리에 실패했습니다.")
                            st.info("💡 파일 형식이나 내용을 확인하고 다시 시도해주세요.")
                            return False
                        
                        st.success(f"✅ 파일 전처리 완료: {len(df_clean):,}개 주문")
                        
                    except Exception as e:
                        st.error("❌ 파일 전처리 중 치명적 오류가 발생했습니다.")
                        if st.session_state.get('admin_mode', False):
                            st.error(f"🔧 **오류 상세**: {str(e)}")
                        logging.error(f"파일 전처리 오류: {str(e)}")
                        return False
                    
                    # 2. 출고 현황 처리
                    with MemoryManager("출고 현황 처리") as shipment_mem:
                        try:
                            with st.spinner('📦 출고 현황 처리 중...'):
                                results = process_shipment_data(df_shipment)
                                
                                if results:
                                    shipment_saved = save_shipment_data(results)
                                    
                                    if shipment_saved:
                                        success_count += 1
                                        st.success("✅ 출고 현황 저장 완료")
                                    else:
                                        st.warning("⚠️ 출고 현황 저장 실패")
                                        error_details.append("출고 현황 GitHub 저장 실패")
                                else:
                                    st.warning("⚠️ 출고 현황 데이터 처리 실패")
                                    error_details.append("출고 현황 데이터 없음")
                                    shipment_saved = False
                            
                            # 즉시 메모리 정리
                            del df_shipment, results
                            gc.collect()
                            
                        except Exception as e:
                            st.error("❌ 출고 현황 처리 중 오류가 발생했습니다.")
                            if st.session_state.get('admin_mode', False):
                                st.error(f"🔧 **오류 상세**: {str(e)}")
                            logging.error(f"출고 현황 처리 오류: {str(e)}")
                            error_details.append(f"출고 현황 처리 오류: {str(e)}")
                            shipment_saved = False
                    
                    # 3. 박스 계산 처리
                    with MemoryManager("박스 계산 처리") as box_mem:
                        try:
                            with st.spinner('📦 박스 계산 처리 중...'):
                                if df_box is not None and not df_box.empty:
                                    if '수취인이름' in df_box.columns:
                                        total_boxes, box_e_orders = calculate_box_requirements(df_box)
                                        
                                        box_results = {
                                            'total_boxes': dict(total_boxes),
                                            'box_e_orders': [
                                                {
                                                    'recipient': order['recipient'],
                                                    'quantities': dict(order['quantities']),
                                                    'products': dict(order['products'])
                                                }
                                                for order in box_e_orders
                                            ]
                                        }
                                        
                                        box_saved = save_box_data(box_results)
                                        
                                        if box_saved:
                                            success_count += 1
                                            st.success("✅ 박스 계산 저장 완료")
                                        else:
                                            st.warning("⚠️ 박스 계산 저장 실패")
                                            error_details.append("박스 계산 GitHub 저장 실패")
                                        
                                        # 즉시 메모리 정리
                                        del total_boxes, box_e_orders, box_results
                                        gc.collect()
                                    else:
                                        st.warning("⚠️ 박스 계산을 위한 '수취인이름' 컬럼이 없습니다.")
                                        st.info("💡 박스 계산이 필요한 경우 수취인이름 컬럼이 포함된 파일을 업로드해주세요.")
                                        box_saved = False
                                        error_details.append("수취인이름 컬럼 없음")
                                else:
                                    st.warning("⚠️ 박스 계산용 데이터가 없습니다.")
                                    box_saved = False
                                    error_details.append("박스 계산용 데이터 없음")
                            
                            # DataFrame 정리
                            if df_box is not None:
                                del df_box
                                gc.collect()
                            
                        except Exception as e:
                            st.error("❌ 박스 계산 처리 중 오류가 발생했습니다.")
                            if st.session_state.get('admin_mode', False):
                                st.error(f"🔧 **오류 상세**: {str(e)}")
                            logging.error(f"박스 계산 처리 오류: {str(e)}")
                            error_details.append(f"박스 계산 처리 오류: {str(e)}")
                            box_saved = False
                    
                    # 최종 DataFrame 정리
                    if df_clean is not None:
                        del df_clean
                        gc.collect()
                    
                    # 결과 요약 및 복구 가이드
                    if success_count == total_processes:
                        st.success("🎉 모든 처리가 성공적으로 완료되었습니다!")
                        st.balloons()
                    elif success_count > 0:
                        st.warning(f"⚠️ {success_count}/{total_processes}개 처리가 완료되었습니다.")
                        
                        # 실패한 처리에 대한 복구 가이드
                        if not shipment_saved:
                            st.info("💡 **출고 현황 재시도**: 파일을 다시 업로드하거나 네트워크 연결을 확인해주세요.")
                        if not box_saved:
                            st.info("💡 **박스 계산 재시도**: 수취인이름 컬럼이 포함된 파일을 업로드해주세요.")
                        
                        # 관리자에게 상세 오류 정보 제공
                        if st.session_state.get('admin_mode', False) and error_details:
                            with st.expander("🔧 상세 오류 정보 (관리자 전용)"):
                                for detail in error_details:
                                    st.write(f"- {detail}")
                    else:
                        st.error("❌ 모든 처리가 실패했습니다.")
                        st.info("💡 파일 형식, 네트워크 연결, USB 연결을 모두 확인해주세요.")
                        
                        # 복구 방법 제안
                        with st.expander("🔧 문제 해결 방법"):
                            st.markdown("""
                            **파일 관련 문제:**
                            1. 파일이 .xlsx 형식인지 확인
                            2. 파일 크기가 50MB 이하인지 확인
                            3. 필수 컬럼(상품이름, 옵션이름, 상품수량)이 있는지 확인
                            
                            **네트워크 관련 문제:**
                            1. 인터넷 연결 상태 확인
                            2. 잠시 후 다시 시도
                            3. 브라우저 새로고침 후 재시도
                            
                            **USB 관련 문제:**
                            1. USB가 올바르게 연결되었는지 확인
                            2. 고객 정보 파일이 USB에 있는지 확인
                            3. 다른 프로그램에서 파일을 사용 중이지 않은지 확인
                            """)
                        
                        # 관리자에게 상세 오류 정보 제공
                        if st.session_state.get('admin_mode', False) and error_details:
                            with st.expander("🔧 상세 오류 정보 (관리자 전용)"):
                                for detail in error_details:
                                    st.write(f"- {detail}")
                    
                    return success_count > 0
    
        # 안전한 처리 실행
        try:
            safe_execute(safe_process_all, "전체 파일 처리", False)
        except Exception as critical_error:
            st.error("❌ 치명적인 시스템 오류가 발생했습니다.")
            st.info("💡 페이지를 새로고침하고 다시 시도해주세요.")
            if st.session_state.get('admin_mode', False):
                st.error(f"🔧 **치명적 오류**: {str(critical_error)}")
            logging.critical(f"치명적 시스템 오류: {str(critical_error)}")

# 첫 번째 탭: 출고 현황
with tab1:
    st.header("📦 출고 현황")
        
    # 출고 현황 데이터 로드
    with st.spinner('📡 출고 현황 데이터 로드 중...'):
        shipment_results, shipment_last_update = load_shipment_data()
    
    if shipment_results:
        # 출고 현황 계산
        total_quantity = sum(shipment_results.values())
        product_types = len([k for k, v in shipment_results.items() if v > 0])
        
        # 요약 메트릭 표시 - 개선된 버전
        col1, col2 = st.columns(2)
        with col1:
            html = render_metric_card(
                title="🎯 전체 출고 개수",
                value=f"{total_quantity:,}개",
                background_gradient="linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
            )
            st.markdown(html, unsafe_allow_html=True)

        with col2:
            html = render_metric_card(
                title="📊 상품 종류",
                value=f"{product_types}개",
                background_gradient="linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)"
            )
            st.markdown(html, unsafe_allow_html=True)

        
        # 업데이트 시간 표시
        if shipment_last_update:
            st.markdown(f'''
            <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); 
                        padding: 15px; border-radius: 10px; margin: 20px 0; 
                        border-left: 4px solid #667eea; text-align: center;">
                <div style="font-size: 18px; color: #2c3e50; font-weight: 600;">
                    📅 마지막 업데이트: {shipment_last_update.strftime('%Y년 %m월 %d일 %H시 %M분')} (KST)
                </div>
            </div>
            ''', unsafe_allow_html=True)
        
        # 출고 현황 테이블 데이터 준비
        df_data = []
        for product_key, quantity in sorted(shipment_results.items()):
            if quantity > 0:
                parts = product_key.strip().split()
                if len(parts) >= 2:
                    last_part = parts[-1]
                    if re.match(r'\d+(?:\.\d+)?(?:ml|L)', last_part):
                        product_name = ' '.join(parts[:-1])
                        capacity = last_part
                    else:
                        product_name = product_key
                        capacity = ""
                else:
                    product_name = product_key
                    capacity = ""
                
                df_data.append({
                    "상품명": product_name,
                    "용량": capacity,
                    "수량": quantity
                })
        
        if df_data:
            df_display = pd.DataFrame(df_data)
            
            # 상품별 출고 현황 - 카드 형태로 표시
            st.markdown("#### 📦 상품별 출고 현황")
            
            for i, row in df_display.iterrows():
                # 상품명에 따라 배경색 결정
                product_name = row["상품명"]
                
                if "단호박식혜" in product_name:
                    # 노란색 계열
                    background_color = "linear-gradient(135deg, #ffd700 0%, #ffb300 100%)"
                    text_color = "#4a4a4a"  # 어두운 회색 (노란색 배경에 잘 보이도록)
                elif "수정과" in product_name:
                    # 진갈색 계열
                    background_color = "linear-gradient(135deg, #8b4513 0%, #654321 100%)"
                    text_color = "#ffffff"  # 흰색
                elif "식혜" in product_name and "단호박" not in product_name:
                    # 연갈색 계열
                    background_color = "linear-gradient(135deg, #d2b48c 0%, #bc9a6a 100%)"
                    text_color = "#4a4a4a"  # 어두운 회색 (연갈색 배경에 잘 보이도록)
                elif "플레인" in product_name or "쌀요거트" in product_name:
                    # 검정색 계열
                    background_color = "linear-gradient(135deg, #2c2c2c 0%, #1a1a1a 100%)"
                    text_color = "#ffffff"  # 흰색
                else:
                    # 기본 초록색 (기타 상품)
                    background_color = "linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)"
                    text_color = "#ffffff"  # 흰색
                
                st.markdown(f"""
                    <div style="background: {background_color}; 
                                color: {text_color}; padding: 25px; border-radius: 20px; 
                                margin: 15px 0; box-shadow: 0 6px 12px rgba(0,0,0,0.15);">
                        <div style="display: flex; align-items: center; justify-content: space-between;">
                            <div>
                                <span style="font-size: 28px; font-weight: bold; color: {text_color};">{row["상품명"]}</span>
                                <br>
                                <span style="font-size: 24px; font-weight: normal; opacity: 0.85; color: {text_color};">
                                    ({row["용량"]})
                                </span>
                            </div>
                            <div style="text-align: right;">
                                <span style="font-size: 32px; font-weight: bold; color: {text_color};">
                                    {row["수량"]}개
                                </span>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
    else:
        st.info("📊 **아직 업데이트된 출고 현황이 없습니다. 관리자가 데이터를 업로드할 때까지 기다려주세요.**")

# 두 번째 탭: 박스 계산
with tab2:
    st.header("📦 박스 개수 계산 결과")
        
    # 박스 계산 데이터 로드
    with st.spinner('📡 박스 계산 데이터 로드 중...'):
        box_data, box_last_update = load_box_data()
    
    if box_data:
        total_boxes = box_data.get('total_boxes', {})
        box_e_orders = box_data.get('box_e_orders', [])
        
        # 박스 요약 메트릭
        total_box_count = sum(total_boxes.values())
        box_e_count = len(box_e_orders)

        #col1, col2 있던 곳
        col1, col2 = st.columns(2)
        with col1:
            html = render_metric_card(
                title="📦 총 박스 개수",
                value=f"{total_box_count}개",
                background_gradient="linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
            )
            st.markdown(html, unsafe_allow_html=True)

        with col2:
            color = "#f44336" if box_e_count > 0 else "#4caf50"
            secondary_color = "#d32f2f" if box_e_count > 0 else "#388e3c"
            html = render_metric_card(
                title="⚠️ 박스 검토",
                value=f"{box_e_count}개",
                background_gradient=f"linear-gradient(135deg, {color} 0%, {secondary_color} 100%)"
            )
            st.markdown(html, unsafe_allow_html=True)

        
        # 업데이트 시간 표시
        if box_last_update:
            st.markdown(f'''
            <div style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); 
                        padding: 15px; border-radius: 10px; margin: 20px 0; 
                        border-left: 4px solid #667eea; text-align: center;">
                <div style="font-size: 18px; color: #2c3e50; font-weight: 600;">
                    📅 마지막 업데이트: {box_last_update.strftime('%Y년 %m월 %d일 %H시 %M분')} (KST)
                </div>
            </div>
            ''', unsafe_allow_html=True)
        
        # 일반 박스 계산
        sorted_boxes = sorted(total_boxes.items(), key=lambda x: BOX_COST_ORDER.get(x[0], 999))
        
        st.markdown("#### 📦 박스별 필요량")
        
        # 박스별 필요량을 개선된 형태로 표시
        for box_name, count in sorted_boxes:
            if box_name != '박스 E':
                description = BOX_DESCRIPTIONS.get(box_name, "")
                
                # 박스 B의 경우 용량 글자 크기를 조금 줄임
                description_font_size = "14px" if box_name == "박스 B" else "16px"
                
                st.markdown(f"""
                    <div style="background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%); 
                                color: white; padding: 25px; border-radius: 20px; 
                                margin: 15px 0; box-shadow: 0 6px 12px rgba(0,0,0,0.15);">
                        <div style="display: flex; align-items: center; justify-content: space-between;">
                            <div>
                                <span style="font-size: 28px; font-weight: bold; color: #ffffff;">{box_name}</span>
                                <br>
                                <span style="font-size: {description_font_size}; font-weight: normal; opacity: 0.85; color: #e8f5e8;">
                                    ({description})
                                </span>
                            </div>
                            <div style="text-align: right;">
                                <span style="font-size: 32px; font-weight: bold; color: #ffffff;">
                                    {count}개
                                </span>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
        
        # 검토 필요 주문 표시
        if box_e_count > 0:
            st.markdown(f"""
                <div style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%); 
                            color: white; padding: 25px; border-radius: 20px; 
                            margin: 15px 0; box-shadow: 0 6px 12px rgba(0,0,0,0.15);">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <div>
                            <span style="font-size: 28px; font-weight: bold; color: #ffffff;">검토 필요 주문</span>
                            <br>
                            <span style="font-size: 16px; font-weight: normal; opacity: 0.85; color: #ffe8e8;">
                                (수동 검토가 필요한 주문)
                            </span>
                        </div>
                        <div style="text-align: right;">
                            <span style="font-size: 32px; font-weight: bold; color: #ffffff;">
                                {box_e_count}개
                            </span>
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
                
        # 박스 검토 필요 주문 (있을 경우에만)
        if box_e_orders:
            st.markdown("### ⚠️ 박스 검토 필요 주문")
            st.warning(f"📋 **총 {len(box_e_orders)}건의 주문이 박스 검토가 필요합니다.**")
            
            # 간단한 요약 테이블 - 주문 내역 중심
            summary_data = []
            for i, order in enumerate(box_e_orders, 1):
                quantities = order.get('quantities', {})
                
                # 주문 내역 문자열 생성
                order_details = []
                for capacity in ['1.5L', '1L', '500ml', '240ml']:
                    qty = quantities.get(capacity, 0)
                    if qty > 0:
                        order_details.append(f"{capacity} {qty}개")
                
                summary_data.append({
                    "주문 번호": f"주문 {i}",
                    "수취인": order.get('recipient', '알 수 없음'),
                    "주문 내역": ", ".join(order_details) if order_details else "확인 필요"
                })
            
            if summary_data:
                st.markdown("#### 📋 박스 검토 주문 요약")
                summary_df = pd.DataFrame(summary_data)
                st.dataframe(summary_df, use_container_width=True)
        else:
            st.success("✅ **모든 주문이 일반 박스(A~D, F)로 처리 가능합니다!**")
    
    else:
        st.info("📦 **박스 계산 데이터를 확인하려면 관리자가 수취인이름이 포함된 통합 엑셀 파일을 업로드해야 합니다.**")

# 세 번째 탭: 재고 관리
with tab3:
    st.header("📊 재고 관리")
        
    # 재고 데이터 로드
    with st.spinner('📡 재고 데이터 로드 중...'):
        stock_results, stock_last_update = load_stock_data()
    
    # 한국 시간 기준 날짜 정보
    today = datetime.now(KST)
    weekdays = ['월', '화', '수', '목', '금', '토', '일']
    weekday = weekdays[today.weekday()]
    today_date_label = today.strftime(f"%m월 %d일 ({weekday})")
    
    # 출고 현황과 동기화된 상품 키 가져오기 + 추가 필수 상품
    shipment_results, _ = load_shipment_data()
    
    # 기본 상품 키 목록 (출고 현황 기반)
    product_keys = set()
    if shipment_results:
        product_keys.update(shipment_results.keys())
    
    # 추가 필수 상품 목록 (수동 추가 - 밥알없는 제품 포함)
    additional_products = [
        "단호박식혜 1.5L",
        "단호박식혜 1L",
        "단호박식혜 240ml",
        "식혜 1.5L",
        "식혜 1L",
        "식혜 240ml",
        "수정과 500ml",
        "플레인 쌀요거트 1L",
        "플레인 쌀요거트 200ml",
        "밥알없는 단호박식혜 1.5L",
        "밥알없는 단호박식혜 1L",
        "밥알없는 단호박식혜 240ml",
        "밥알없는 식혜 1.5L",
        "밥알없는 식혜 1L",
        "밥알없는 식혜 240ml"
    ]
    
    product_keys.update(additional_products)
    product_keys = sorted(list(product_keys))
    
    if product_keys:
        st.info(f"📋 **{today_date_label} 재고 입력** - 상품/용량별로 현재 재고 수량을 입력하세요")

        # 출고 현황 반영 버튼 추가
        if shipment_results:
            st.markdown("### 📦 출고 현황 반영")
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.info("💡 **출고 현황 반영**: 현재 재고에서 출고된 수량을 자동으로 차감하여 실제 재고량을 계산합니다.")
            with col2:
                st.markdown("<br>", unsafe_allow_html=True)  # 이 줄을 추가
                if st.button("📦 출고 현황 반영", help="출고된 수량만큼 재고를 자동으로 차감합니다"):
                    # 현재 재고 이력 로드
                    current_stock = stock_results if stock_results else {}
                    
                    # 최신 재고 입력 가져오기
                    latest_stock = {}
                    if current_stock.get("최근입력"):
                        latest_stock = current_stock["최근입력"]["입력용"].copy()
                    
                    # 출고 현황 적용
                    updated_stock = {}
                    for product_key in product_keys:
                        # 상품명과 용량 분리
                        parts = product_key.strip().split()
                        if len(parts) >= 2 and re.match(r'\d+(?:\.\d+)?(?:ml|L)', parts[-1]):
                            product_name = ' '.join(parts[:-1])
                            capacity = parts[-1]
                        else:
                            product_name = product_key
                            capacity = ""
                        
                        input_key = f"{product_name}|{capacity}"
                        
                        # 현재 재고량
                        current_qty = latest_stock.get(input_key, 0)
                        
                        # 출고량 (shipment_results에서 찾기)
                        shipment_qty = shipment_results.get(product_key, 0)
                        
                        # 차감 계산 (0 이하로 내려가지 않게)
                        final_qty = max(0, current_qty - shipment_qty)
                        updated_stock[input_key] = final_qty
                    
                    # 새로운 입력 이력 생성
                    now_str = today.strftime("%Y-%m-%d %H:%M:%S")
                    new_entry = {
                        "입력일시": now_str,
                        "입력용": updated_stock.copy(),
                        "출고반영": True  # 출고 반영 표시
                    }
                    
                    # 이력 업데이트
                    if "이력" not in current_stock:
                        current_stock["이력"] = []
                    
                    # 최신 입력을 맨 앞에 추가
                    current_stock["이력"].insert(0, new_entry)
                    current_stock["최근입력"] = new_entry
                    
                    # GitHub에 저장
                    commit_message = f"출고 현황 반영 {today_date_label} {today.strftime('%H:%M')}"
                    save_success = save_stock_data(current_stock)
                    
                    if save_success:
                        st.success("✅ 출고 현황이 재고에 성공적으로 반영되었습니다!")
                        st.balloons()
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ 출고 현황 반영 중 오류가 발생했습니다. 다시 시도해주세요.")

        # 먼저 재고 현황 표시
        if stock_results and stock_results.get("최근입력"):
            latest_entry = stock_results["최근입력"]
            input_time = latest_entry["입력일시"]

            # 시간 포맷팅
            try:
                dt = datetime.fromisoformat(input_time.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=KST)
                else:
                    dt = dt.astimezone(KST)
                
                formatted_time = dt.strftime("%Y-%m-%d-%H-%M")
            except:
                formatted_time = input_time.replace(" ", "-").replace(":", "-")

            # 출고 반영 여부 표시
            reflection_type = "출고 반영" if latest_entry.get("출고반영", False) else "수동 입력"

            st.markdown(f"### 📋 재고 현황 ({formatted_time}) - {reflection_type}")

            # 현재 재고 데이터를 상품별로 그룹화
            stock_groups = {}
            low_stock_items = []

            for product_key, quantity in latest_entry["입력용"].items():
                if quantity > 0:  # 수량이 0보다 큰 경우만 표시
                    product_name, capacity = product_key.split("|", 1)
                    full_product_name = f"{product_name} {capacity}".strip()
                    
                    # 임계값 확인 (표시하지 않고 색상 결정용)
                    threshold = STOCK_THRESHOLDS.get(full_product_name, 0)
                    is_low_stock = quantity <= threshold and threshold > 0
                    
                    if is_low_stock:
                        low_stock_items.append(f"{full_product_name} ({quantity}개)")
                    
                    if product_name not in stock_groups:
                        stock_groups[product_name] = []
                    
                    stock_groups[product_name].append({
                        "용량": capacity,
                        "수량": quantity,
                        "위험": is_low_stock
                    })

            # 상품별 카드 형태로 재고 현황 표시
            for product_name, capacities in stock_groups.items():
                # 상품명에 따라 색상 결정 (출고 현황 탭과 동일한 로직)
                if "밥알없는 단호박식혜" in product_name:
                    # 밥알없는 단호박식혜 - 진한 노란색
                    card_color = "linear-gradient(135deg, #ffb300 0%, #ff8f00 100%)"
                    border_color = "#ff6f00"
                    text_color = "#4a4a4a"
                elif "단호박식혜" in product_name:
                    # 일반 단호박식혜 - 기본 노란색
                    card_color = "linear-gradient(135deg, #ffd700 0%, #ffb300 100%)"
                    border_color = "#ff8f00"
                    text_color = "#4a4a4a"
                elif "밥알없는 식혜" in product_name:
                    # 밥알없는 식혜 - 연한 갈색
                    card_color = "linear-gradient(135deg, #deb887 0%, #d2b48c 100%)"
                    border_color = "#cd853f"
                    text_color = "#4a4a4a"
                elif "식혜" in product_name and "단호박" not in product_name:
                    # 일반 식혜 - 기본 갈색
                    card_color = "linear-gradient(135deg, #d2b48c 0%, #bc9a6a 100%)"
                    border_color = "#8b7355"
                    text_color = "#4a4a4a"
                elif "수정과" in product_name:
                    # 수정과 - 진갈색
                    card_color = "linear-gradient(135deg, #8b4513 0%, #654321 100%)"
                    border_color = "#654321"
                    text_color = "#ffffff"
                elif "플레인" in product_name or "쌀요거트" in product_name:
                    # 플레인 쌀요거트 - 검정색
                    card_color = "linear-gradient(135deg, #2c2c2c 0%, #1a1a1a 100%)"
                    border_color = "#000000"
                    text_color = "#ffffff"
                else:
                    # 기타 상품 - 기본 초록색
                    card_color = "linear-gradient(135deg, #e8f5e8 0%, #c8e6c9 100%)"
                    border_color = "#4caf50"
                    text_color = "#2e7d32"
                
                st.markdown(f"""
                    <div style="background: {card_color}; 
                                padding: 20px; border-radius: 15px; margin: 15px 0; 
                                border-left: 5px solid {border_color};">
                        <h4 style="margin: 0 0 15px 0; color: {text_color}; font-weight: 600;">
                            📦 {product_name}
                        </h4>
                    </div>
                """, unsafe_allow_html=True)
                
                # 해당 상품의 용량별 재고를 한 줄에 표시
                cols = st.columns(len(capacities))
                
                for i, item in enumerate(capacities):
                    with cols[i]:
                        # 각 용량별로 개별적으로 색상 결정
                        if item["위험"]:
                            # 임계치 이하인 용량만 빨간색
                            st.markdown(f"""
                                <div style="text-align: center; padding: 10px; 
                                            background: white; border-radius: 8px; 
                                            border: 2px solid #f44336;">
                                    <div style="font-size: 18px; color: #666; margin-bottom: 5px;">
                                        {item["용량"]}
                                    </div>
                                    <div style="font-size: 24px; font-weight: bold; color: #f44336;">
                                        {item["수량"]}개
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
                        else:
                            # 정상 재고는 초록색
                            st.markdown(f"""
                                <div style="text-align: center; padding: 10px; 
                                            background: white; border-radius: 8px; 
                                            border: 2px solid #4caf50;">
                                    <div style="font-size: 18px; color: #666; margin-bottom: 5px;">
                                        {item["용량"]}
                                    </div>
                                    <div style="font-size: 24px; font-weight: bold; color: #4caf50;">
                                        {item["수량"]}개
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)
                                
            # 재고 요약 정보
            total_products = sum(len(capacities) for capacities in stock_groups.values())
            total_quantity = sum(sum(item["수량"] for item in capacities) for capacities in stock_groups.values())
            low_stock_count = len(low_stock_items)

            # 여백 추가 (거리 넓히기)
            st.markdown("<br><br>", unsafe_allow_html=True)

            #col1, col2, col3 자리
            col1, col2, col3 = st.columns(3)

            with col1:
                html = render_metric_card(
                    title="📊 재고 상품 종류",
                    value=f"{total_products}개",
                    background_gradient="linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                    font_color="#2c3e50"
                )
                st.markdown(html, unsafe_allow_html=True)

            with col2:
                html = render_metric_card(
                    title="📦 총 재고 수량",
                    value=f"{total_quantity:,}개",
                    background_gradient="linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                    font_color="#2c3e50"
                )
                st.markdown(html, unsafe_allow_html=True)

            with col3:
                color = "#f44336" if low_stock_count > 0 else "#2c3e50"
                html = render_metric_card(
                    title="🚨 재고 부족 항목",
                    value=f"{low_stock_count}개",
                    background_gradient="linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)",
                    font_color=color
                )
                st.markdown(html, unsafe_allow_html=True)


            st.markdown("<br><br>", unsafe_allow_html=True)
            
            st.markdown(f'📅 마지막 업데이트: {dt.strftime("%Y년 %m월 %d일 %H시 %M분")} (KST)')
            
            # 재고가 없는 경우 메시지 표시
            if not stock_groups:
                st.info("📋 **현재 재고가 있는 상품이 없습니다.**")
        else:
            st.info("📋 **재고 데이터가 없습니다. 재고를 처음 입력하시면 현황이 표시됩니다.**")

        # 구분선 추가
        st.markdown("---")
        
        # 재고 입력 폼
        with st.form(f"stock_input_{today.strftime('%Y%m%d')}"):
            st.markdown("#### 💾 재고 수량 입력")
            st.markdown("상품/용량별로 현재 남은 재고 개수를 입력하세요")
            
            stock_input = {}
            
            # 상품별로 그룹화
            product_groups = {}
            for product_key in product_keys:
                parts = product_key.strip().split()
                if len(parts) >= 2 and re.match(r'\d+(?:\.\d+)?(?:ml|L)', parts[-1]):
                    product_name = ' '.join(parts[:-1])
                    capacity = parts[-1]
                else:
                    product_name = product_key
                    capacity = ""
                
                if product_name not in product_groups:
                    product_groups[product_name] = []
                product_groups[product_name].append((capacity, product_key))
                        
            # 저장 버튼있던 곳
            # 상품별로 그룹화
            product_groups = {}
            for product_key in product_keys:
                parts = product_key.strip().split()
                if len(parts) >= 2 and re.match(r'\d+(?:\.\d+)?(?:ml|L)', parts[-1]):
                    product_name = ' '.join(parts[:-1])
                    capacity = parts[-1]
                else:
                    product_name = product_key
                    capacity = ""
                
                if product_name not in product_groups:
                    product_groups[product_name] = []
                product_groups[product_name].append((capacity, product_key))
            
            # 상품별 입력 필드 생성
            for product_name, capacities in sorted(product_groups.items()):
                st.markdown(f"**📦 {product_name}**")
                
                # 용량별로 컬럼 생성
                if len(capacities) > 1:
                    cols = st.columns(len(capacities))
                    for i, (capacity, product_key) in enumerate(capacities):
                        with cols[i]:
                            # 기존 재고 값 가져오기 (있다면)
                            existing_value = 0
                            if stock_results and stock_results.get("최근입력"):
                                input_key = f"{product_name}|{capacity}"
                                existing_value = stock_results["최근입력"]["입력용"].get(input_key, 0)
                            
                            stock_input[f"{product_name}|{capacity}"] = st.number_input(
                                f"{capacity}",
                                min_value=0,
                                value=existing_value,
                                step=1,
                                key=f"stock_{product_name}_{capacity}"
                            )
                else:
                    # 단일 용량인 경우
                    capacity, product_key = capacities[0]
                    
                    # 기존 재고 값 가져오기 (있다면)
                    existing_value = 0
                    if stock_results and stock_results.get("최근입력"):
                        input_key = f"{product_name}|{capacity}"
                        existing_value = stock_results["최근입력"]["입력용"].get(input_key, 0)
                    
                    stock_input[f"{product_name}|{capacity}"] = st.number_input(
                        f"{capacity}",
                        min_value=0,
                        value=existing_value,
                        step=1,
                        key=f"stock_{product_name}_{capacity}"
                    )
            
            # 저장 버튼
            submitted = st.form_submit_button("💾 재고 저장", help="입력한 재고 수량을 저장합니다")
            
            if submitted:
                # 현재 재고 이력 로드
                current_stock = stock_results if stock_results else {}
                
                # 새로운 입력 이력 생성
                now_str = today.strftime("%Y-%m-%d %H:%M:%S")
                new_entry = {
                    "입력일시": now_str,
                    "입력용": stock_input.copy(),
                    "출고반영": False  # 수동 입력 표시
                }
                
                # 이력 업데이트
                if "이력" not in current_stock:
                    current_stock["이력"] = []
                
                # 최신 입력을 맨 앞에 추가
                current_stock["이력"].insert(0, new_entry)
                current_stock["최근입력"] = new_entry
                
                # GitHub에 저장
                commit_message = f"재고 입력 {today_date_label} {today.strftime('%H:%M')}"
                save_success = save_stock_data(current_stock)
                
                if save_success:
                    st.success("✅ 재고 입력이 성공적으로 저장되었습니다!")
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ 재고 저장 중 오류가 발생했습니다. 다시 시도해주세요.")

    else:
        st.info("📋 **재고 관리를 위해서는 먼저 출고 현황 데이터가 필요합니다.**")
        st.markdown("관리자가 출고 현황을 업로드하면 자동으로 재고 입력이 가능해집니다.")


# 네 번째 탭: 고객 관리
with tab4:
    st.header("👥 고객 관리")
    
    if not is_admin:
        st.warning("🔒 관리자 로그인이 필요한 기능입니다.")
        st.info("고객 개인정보 보호를 위해 관리자만 접근 가능합니다.")
        st.stop()
    
    st.markdown("### 📊 고객 주문 이력 분석")
    st.info("""
    **🔒 개인정보 보호 정책**: 업로드된 파일은 분석 후 즉시 삭제되며, 결과만 표시됩니다.
    
    **📝 분석 기능**:
    - ✅ 재주문 고객 자동 탐지
    - ✅ 고객별 주문 횟수 및 총 결제금액 계산
    - ✅ 상세 주문 이력 시각화
    """)
    
    # 파일 업로드 섹션
    st.markdown("#### 📁 파일 업로드")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**1️⃣ 고객주문정보 파일 (.xlsx)**")
        customer_history_file = st.file_uploader(
            "과거 고객 주문 이력이 담긴 엑셀 파일을 업로드하세요",
            type=['xlsx'],
            help="고객별 주문 이력이 포함된 엑셀 파일 (.xlsx)",
            key="customer_history_upload"
        )
    
    with col2:
        st.markdown("**2️⃣ 출고내역서 파일 (.xlsx)**")
        shipment_file = st.file_uploader(
            "오늘 출고내역서 엑셀 파일을 업로드하세요",
            type=['xlsx'],
            help="오늘의 출고내역이 포함된 엑셀 파일 (.xlsx)",
            key="today_shipment_upload"
        )
    
    # 두 파일이 모두 업로드되었을 때 분석 실행
    if customer_history_file and shipment_file:
        st.markdown("---")
        
        try:
            with st.spinner('🔄 고객 주문 데이터 분석 중...'):
                # 분석 실행
                analysis_results = analyze_customer_orders(customer_history_file, shipment_file)
                
                if analysis_results:
                    display_customer_analysis(analysis_results)
                else:
                    st.error("❌ 고객 주문 분석에 실패했습니다.")
                    st.info("💡 파일 형식과 내용을 확인해주세요.")
        
        except Exception as e:
            st.error(f"❌ 분석 중 오류가 발생했습니다: {str(e)}")
            if st.session_state.get('admin_mode', False):
                st.error(f"🔧 **상세 오류**: {str(e)}")
    
    elif customer_history_file or shipment_file:
        st.info("📋 두 파일을 모두 업로드해야 분석이 가능합니다.")
    
    else:
        st.markdown("#### 📝 파일 형식 가이드")
        
        with st.expander("📋 고객주문정보 파일 형식"):
            st.markdown("""
            **필수 컬럼:**
            - `주문일시`: 주문 날짜/시간
            - `주문자이름`: 고객 이름
            - `주문자전화번호`: 연락처
            - `상품이름`: 주문 상품명
            - `상품수량`: 주문 수량
            - `상품결제금액`: 결제 금액
            
            **선택 컬럼:**
            - `수취인이름`: 받는 사람
            - `옵션이름`: 상품 옵션 정보
            """)
        
        with st.expander("📋 출고내역서 파일 형식"):
            st.markdown("""
            **필수 컬럼:**
            - `주문자이름`: 주문한 고객 이름
            - `주문자전화번호1`: 고객 연락처
            - `상품이름`: 출고 상품명
            - `상품수량`: 출고 수량
            
            **선택 컬럼:**
            - `수취인이름`: 받는 사람
            - `옵션이름`: 상품 옵션
            - `상품결제금액`: 결제 금액
            """)
    
    # 보안 정책 안내
    st.markdown("---")
    st.markdown("### 🔒 보안 정책")
    st.info("""
    **고객 정보 보호 정책:**
    - 🔐 관리자만 접근 가능
    - 💾 업로드된 파일은 분석 후 즉시 메모리에서 삭제
    - 🚫 개인정보는 마스킹 처리되어 표시
    - 📊 분석 결과만 임시 표시
    - 🗑️ 처리 완료 후 모든 데이터 자동 삭제
    """)
    

# 버전 정보
st.markdown("---")
st.markdown("**🔧 seroe-dashboard-v2** | ")

def cleanup_session():
    """세션 상태 정리"""
    cleanup_keys = [
        'last_uploaded_file',
        'temp_data',
        'processed_results'
    ]
    
    for key in cleanup_keys:
        if key in st.session_state:
            del st.session_state[key]
    
    force_garbage_collection()

# 앱 종료 시 정리
import atexit
atexit.register(cleanup_session)

