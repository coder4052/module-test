import pandas as pd
import streamlit as st
import re
from collections import defaultdict
import gc
from modules.memory import MemoryManager

# ---------------------------
# 🔸 데이터 정제
# ---------------------------
def sanitize_data(df):
    safe_columns = ['상품이름', '옵션이름', '상품수량', '수취인이름', '주문자이름', '주문자전화번호1']
    available_columns = df.columns.intersection(safe_columns)
    sanitized_df = df[available_columns].copy()

    essential_columns = ['상품이름', '옵션이름', '상품수량']
    missing_columns = [col for col in essential_columns if col not in sanitized_df.columns]
    if missing_columns:
        st.error(f"❌ 필수 컬럼이 없습니다: {missing_columns}")
        st.info("💡 엑셀 파일의 컬럼명을 확인하세요 (예: G열=상품이름, H열=옵션이름, N열=상품수량)")
        return pd.DataFrame()

    st.success(f"✅ 필수 컬럼 정상 처리: {list(available_columns)}")
    return sanitized_df

#엑셀 파일을 안정적으로 읽는 함수
def read_excel_file_safely(uploaded_file):
    """엑셀 파일을 안정적으로 읽는 함수"""
    try:
        return pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"❌ 엑셀 파일 로딩 실패: {e}")
        return None

# 🎯 출고 현황 처리 함수들
def extract_product_from_option(option_text):
    """옵션에서 상품 분류 추출 (H열 우선)"""
    if pd.isna(option_text):
        return "기타"
    
    option_text = str(option_text).lower()
    
    if "단호박식혜" in option_text:
        return "단호박식혜"
    elif "일반식혜" in option_text or ("식혜" in option_text and "단호박" not in option_text):
        return "식혜"
    elif "수정과" in option_text:
        return "수정과"
    elif "쌀요거트" in option_text or "요거트" in option_text or "플레인" in option_text:
        return "플레인 쌀요거트"
    
    return "기타"

def extract_product_from_name(product_name):
    """상품이름에서 분류 추출 (G열 - 보조용)"""
    if pd.isna(product_name):
        return "기타"
    
    product_name = str(product_name).lower()
    
    bracket_match = re.search(r'\[서로\s+([^\]]+)\]', product_name)
    if bracket_match:
        product_key = bracket_match.group(1).strip()
        
        if "단호박식혜" in product_key:
            return "단호박식혜"
        elif "진하고 깊은 식혜" in product_key or "식혜" in product_key:
            return "식혜"
        elif "수정과" in product_key:
            return "수정과"
        elif "쌀요거트" in product_key:
            return "플레인 쌀요거트"
    
    if "쌀요거트" in product_name or "요거트" in product_name or "플레인" in product_name:
        return "플레인 쌀요거트"
    
    return "기타"

def parse_option_info(option_text):
    """옵션에서 수량과 용량 추출"""
    if pd.isna(option_text):
        return 1, ""
    
    option_text = str(option_text)
    
    # 패턴 1: "5개, 240ml" 또는 "10개, 500ml"
    pattern1 = re.search(r'(\d+)개,\s*(\d+(?:\.\d+)?(?:ml|L))', option_text)
    if pattern1:
        return int(pattern1.group(1)), pattern1.group(2)
    
    # 패턴 2: "2, 1L" 또는 "4, 1L"
    pattern2 = re.search(r'(\d+),\s*(\d+(?:\.\d+)?(?:ml|L))', option_text)
    if pattern2:
        return int(pattern2.group(1)), pattern2.group(2)
    
    # 패턴 3: "용량 : 1L 2병"
    pattern3 = re.search(r'용량\s*:\s*(\d+(?:\.\d+)?(?:ml|L))\s*(\d+)병', option_text)
    if pattern3:
        return int(pattern3.group(2)), pattern3.group(1)
    
    # 패턴 4: "500ml 3병" 또는 "500ml 5병"
    pattern4 = re.search(r'(\d+(?:\.\d+)?(?:ml|L))\s*(\d+)병', option_text)
    if pattern4:
        return int(pattern4.group(2)), pattern4.group(1)
    
    # 패턴 5: 단순 용량만 "플레인 쌀요거트 1L"
    capacity_match = re.search(r'(\d+(?:\.\d+)?(?:ml|L))', option_text)
    if capacity_match:
        return 1, capacity_match.group(1)
    
    return 1, ""

def standardize_capacity(capacity, for_box=False):
    """용량 표준화: 박스용일 경우 200ml → 240ml"""
    if not capacity:
        return ""
    
    capacity = str(capacity)
    capacity = capacity.lower()

    if re.match(r'1\.5l', capacity):
        return "1.5L"
    elif re.match(r'1l|1000ml', capacity):
        return "1L"
    elif re.match(r'500ml', capacity):
        return "500ml"
    elif re.match(r'240ml', capacity):
        return "240ml"
    elif re.match(r'200ml', capacity):
        return "240ml" if for_box else "200ml"

    return capacity

# 📦 박스 계산 함수들
def standardize_capacity_for_box(capacity):
    """박스 계산용 용량 표준화 (200ml → 240ml)"""
    return standardize_capacity(capacity, for_box=True)

def group_orders_by_recipient(df):
    """수취인별로 주문을 그룹화하여 박스 계산"""
    orders = defaultdict(dict)
    
    for _, row in df.iterrows():
        recipient = row.get('수취인이름', '알 수 없음')
        
        # 상품 정보 추출
        option_product = extract_product_from_option(row.get('옵션이름', ''))
        name_product = extract_product_from_name(row.get('상품이름', ''))
        final_product = option_product if option_product != "기타" else name_product
        
        # 수량 및 용량 정보
        option_quantity, capacity = parse_option_info(row.get('옵션이름', ''))
        
        try:
            base_quantity = int(row.get('상품수량', 1))
        except (ValueError, TypeError):
            base_quantity = 1
        
        total_quantity = base_quantity * option_quantity
        standardized_capacity = standardize_capacity_for_box(capacity)
        
        if standardized_capacity:
            key = f"{final_product} {standardized_capacity}"
        else:
            key = final_product
        
        orders[recipient][key] = orders[recipient].get(key, 0) + total_quantity
    
    return orders

def get_product_quantities(order_products):
    """주문 제품에서 용량별 수량 집계 - 새로운 규칙"""
    quantities = defaultdict(int)
    
    for product_key, qty in order_products.items():
        if '1.5L' in product_key:
            quantities['1.5L'] += qty
        elif '1L' in product_key:
            quantities['1L'] += qty
        elif '500ml' in product_key:
            quantities['500ml'] += qty
        elif '240ml' in product_key:
            quantities['240ml'] += qty
        elif '200ml' in product_key:
            quantities['240ml'] += qty  # 200ml → 240ml 변환
    
    return quantities

def calculate_box_for_order(quantities):
    """단일 주문에 대한 박스 계산 - 새로운 간단 규칙"""
    
    # 1단계: 혼합 주문 체크 (여러 용량이 섞여있으면 검토 필요)
    non_zero_capacities = [cap for cap, qty in quantities.items() if qty > 0]
    if len(non_zero_capacities) > 1:
        return "검토 필요"
    
    # 2단계: 단일 용량 박스 매칭
    for capacity, qty in quantities.items():
        if qty > 0:
            # 박스 A: 1L 1~2개 or 500ml 1~3개 or 240ml 1~5개
            if capacity == "1L" and 1 <= qty <= 2:
                return "박스 A"
            elif capacity == "500ml" and 1 <= qty <= 3:
                return "박스 A"
            elif capacity == "240ml" and 1 <= qty <= 5:
                return "박스 A"
            
            # 박스 B: 1L 3~4개 or 500ml 4~6개 or 240ml 6~10개
            elif capacity == "1L" and 3 <= qty <= 4:
                return "박스 B"
            elif capacity == "500ml" and 4 <= qty <= 6:
                return "박스 B"
            elif capacity == "240ml" and 6 <= qty <= 10:
                return "박스 B"
            
            # 박스 C: 500ml 10개
            elif capacity == "500ml" and qty == 10:
                return "박스 C"
            
            # 박스 D: 1L 5~6개
            elif capacity == "1L" and 5 <= qty <= 6:
                return "박스 D"
            
            # 박스 E: 1.5L 3~4개
            elif capacity == "1.5L" and 3 <= qty <= 4:
                return "박스 E"
            
            # 박스 F: 1.5L 1~2개
            elif capacity == "1.5L" and 1 <= qty <= 2:
                return "박스 F"
    
    # 3단계: 어떤 박스 조건도 만족하지 않으면 검토 필요
    return "검토 필요"

def calculate_box_requirements(df):
    """전체 박스 필요량 계산 - 새로운 로직"""
    orders = group_orders_by_recipient(df)
    
    total_boxes = defaultdict(int)
    review_orders = []  # 검토 필요 주문들
    
    for recipient, products in orders.items():
        quantities = get_product_quantities(products)
        box_result = calculate_box_for_order(quantities)
        
        if box_result == "검토 필요":
            review_orders.append({
                'recipient': recipient,
                'quantities': quantities,
                'products': products
            })
        else:
            total_boxes[box_result] += 1
    
    return total_boxes, review_orders


#출고 현황 및 집계 처리 함수
def process_unified_file(uploaded_file):
    """통합 엑셀 파일 처리 - 출고 현황용 (개선된 메모리 관리)"""
    try:
        df = read_excel_file_safely(uploaded_file)
        
        if df is None:
            return {}, []
        
        df = sanitize_data(df)
        
        if df.empty:
            return {}, []
        
        st.write(f"📄 **{uploaded_file.name}**: 통합 파일 처리 시작 (총 {len(df):,}개 주문)")
        
        results = defaultdict(int)
        
        # 프로그레스 바 추가
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_rows = len(df)
        
        for index, row in df.iterrows():
            # 프로그레스 업데이트
            progress = (index + 1) / total_rows
            progress_bar.progress(progress)
            status_text.text(f"처리 중... {index + 1:,}/{total_rows:,} ({progress:.1%})")
            
            option_product = extract_product_from_option(row.get('옵션이름', ''))
            name_product = extract_product_from_name(row.get('상품이름', ''))
            final_product = option_product if option_product != "기타" else name_product
            
            option_quantity, capacity = parse_option_info(row.get('옵션이름', ''))
            
            try:
                base_quantity = int(row.get('상품수량', 1))
            except (ValueError, TypeError):
                base_quantity = 1
                
            total_quantity = base_quantity * option_quantity
            
            standardized_capacity = standardize_capacity(capacity)
            
            if standardized_capacity:
                key = f"{final_product} {standardized_capacity}"
            else:
                key = final_product
            
            results[key] += total_quantity
        
        # 프로그레스 바 정리
        progress_bar.empty()
        status_text.empty()
        
        processed_files = [f"통합 파일 ({len(df):,}개 주문)"]
        
        # 메모리 정리 추가
        del df
        gc.collect()
        
        return results, processed_files
        
    except Exception as e:
        st.error(f"❌ {uploaded_file.name} 처리 중 오류: {str(e)}")
        return {}, []
