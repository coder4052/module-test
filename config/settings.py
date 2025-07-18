# GitHub 설정 - 수정된 저장소명
REPO_OWNER = "coder4052"  # 본인 GitHub 사용자명으로 변경하세요
REPO_NAME = "seroe-dashboard-v2-test"  # 실제 생성한 저장소명
BASE_DATA_DIR = "data"

SHIPMENT_FILE_PATH = f"{BASE_DATA_DIR}/출고현황_encrypted.json"
BOX_FILE_PATH = f"{BASE_DATA_DIR}/박스계산_encrypted.json"
STOCK_FILE_PATH = f"{BASE_DATA_DIR}/재고현황_encrypted.json"

# 페이지 설정
st.set_page_config(
    page_title="서로 출고 현황",
    page_icon="🎯",
    layout="wide"
)
