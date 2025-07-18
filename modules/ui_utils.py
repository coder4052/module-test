# 🎨 CSS 스타일 적용 - 가독성 향상
import streamlit as st

def apply_custom_styles():
    """스트림릿 CSS 사용자 정의 스타일 적용"""
    st.markdown("""
    <style>
    /* 전체 폰트 크기 및 가독성 향상 */
    .main .block-container {
        font-size: 16px;
        line-height: 1.6;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    /* 제목 스타일 */
    h1 {
        font-size: 2.5rem !important;
        font-weight: bold !important;
        color: #1f1f1f !important;
        margin-bottom: 1rem !important;
    }
    
    /* 서브헤딩 스타일 */
    h2 {
        font-size: 1.8rem !important;
        font-weight: 600 !important;
        color: #2c3e50 !important;
        margin-top: 2rem !important;
        margin-bottom: 1rem !important;
    }
    
    h3 {
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        color: #34495e !important;
        margin-top: 1.5rem !important;
        margin-bottom: 1rem !important;
    }
    
    /* 메트릭 카드 스타일 */
    .metric-container {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    /* 데이터프레임 스타일 */
    .dataframe {
        font-size: 14px !important;
        line-height: 1.5 !important;
    }

    /* 버튼 스타일 */
    .stButton > button {
        font-size: 16px !important;
        font-weight: 600 !important;
        padding: 0.75rem 1.5rem !important;
        border-radius: 8px !important;
    }

    /* 사이드바 스타일 */
    .sidebar .sidebar-content {
        font-size: 15px !important;
        line-height: 1.6 !important;
    }

    /* 알림 메시지 스타일 */
    .stAlert {
        font-size: 15px !important;
        font-weight: 500 !important;
        padding: 1rem !important;
        border-radius: 8px !important;
    }

    /* 테이블 헤더 스타일 */
    .stDataFrame th {
        font-size: 15px !important;
        font-weight: 600 !important;
        background-color: #f8f9fa !important;
    }

    /* 테이블 셀 스타일 */
    .stDataFrame td {
        font-size: 14px !important;
        padding: 0.75rem !important;
    }

    /* 확장기 스타일 */
    .streamlit-expanderHeader {
        font-size: 16px !important;
        font-weight: 600 !important;
    }

    /* 캡션 스타일 */
    .caption {
        font-size: 14px !important;
        color: #6c757d !important;
        font-style: italic !important;
    }

    /* 성공 메시지 스타일 */
    .success-highlight {
        background: linear-gradient(135deg, #00b894 0%, #00a085 100%);
        padding: 1rem;
        border-radius: 8px;
        color: white;
        font-weight: 600;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* 재고 부족 경고 스타일 (새로 추가) */
    .low-stock-warning {
        background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
        color: white;
        padding: 1rem;
        border-radius: 8px;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }

    /* 재고 부족 테이블 행 스타일 (새로 추가) */
    .stDataFrame [data-testid="stTable"] tbody tr td {
        font-weight: normal;
    }

    .low-stock-row {
        background-color: #ffebee !important;
        color: #c62828 !important;
        font-weight: bold !important;
    }

    /* 로딩 스피너 스타일 */
    .loading-spinner {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 2rem;
    }
    </style>
    """, unsafe_allow_html=True)    

#색상 헬퍼 함수
def get_product_color(product_name: str) -> str:
    name = product_name.lower()
    color_map = {
        "단호박식혜": "#FFD700",
        "수정과": "#D2B48C",
        "식혜": "#654321",
        "쌀요거트": "#F5F5F5",
        "플레인": "#F5F5F5",
    }

    for keyword, color in color_map.items():
        if keyword in name and not (keyword == "식혜" and "단호박" in name):
            return color

    return "#808080"  # default gray

#카드 UI 렌더링 함수
def render_metric_card(title, value, background_gradient, font_color="#ffffff"):
    """카드형 요약 메트릭 표시 렌더링"""
    return f"""
    <div style="text-align: center; padding: 25px; background: {background_gradient};
                border-radius: 15px; margin: 10px 0; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
        <div style="font-size: 24px; color: {font_color}; margin-bottom: 10px; font-weight: 600;">
            {title}
        </div>
        <div style="font-size: 42px; font-weight: bold; color: {font_color};">
            {value}
        </div>
    </div>
    """
