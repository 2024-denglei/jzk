"""数据加载模块：从 Excel 加载捐精人数据并预处理。"""

import pandas as pd
from datetime import date
from config import DATA_FILE_PATH, DATA_SHEET_NAME


def load_donor_data() -> pd.DataFrame:
    """加载全部捐精人数据，清洗列名。"""
    df = pd.read_excel(DATA_FILE_PATH, sheet_name=DATA_SHEET_NAME)

    # 去除列名空白
    df.columns = df.columns.str.strip()
    df.reset_index(drop=True, inplace=True)

    # 核心列检查
    required_cols = [
        "编号", "代号", "血型", "民族", "身高", "学历",
        "脸型", "眼皮", "肤色", "体型", "体重", "体征指数",
        "性格", "爱好", "形象气质", "唇形",
        "精液检测", "血液检测", "染色体检测", "微生物检测",
        "标本数量", "是否可用",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel 缺少必要列: {missing}")

    return df


def _calc_age(birth_val) -> int:
    """从出生日期计算年龄，支持字符串和日期对象。"""
    if not birth_val or str(birth_val) in ('nan', 'NaT', ''):
        return 0
    try:
        if hasattr(birth_val, 'year'):
            born = birth_val.date() if hasattr(birth_val, 'date') else birth_val
        else:
            born = date.fromisoformat(str(birth_val)[:10])
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except Exception:
        return 0


def _float_safe(v, default: float = 0.0) -> float:
    """安全转 float，NaN/Inf/None 返回 default。"""
    try:
        f = float(v)
        import math
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _val(row, key) -> str:
    """安全取值并转为字符串，过滤 nan。"""
    v = row.get(key, "")
    s = str(v)
    return "" if s in ('nan', 'NaT', 'None', '') else s


def get_donor_display_info(row: pd.Series) -> dict:
    """提取用于前端展示的捐精人信息（脱敏）。"""
    return {
        "id": _val(row, "编号"),
        "code": _val(row, "代号"),
        "blood_type": _val(row, "血型"),
        "rh_blood": _val(row, "RH血型"),
        "ethnicity": _val(row, "民族"),
        "height": int(row.get("身高", 0) or 0),
        "age": _calc_age(row.get("出生日期")),
        "constellation": _val(row, "星座"),
        "hometown": _val(row, "籍贯"),
        "occupation": _val(row, "职业"),
        "education": _val(row, "学历"),
        "face_shape": _val(row, "脸型"),
        "eyelid": _val(row, "眼皮"),
        "skin_color": _val(row, "肤色"),
        "lip_shape": _val(row, "唇形"),
        "nose_bridge": _val(row, "鼻梁"),
        "hair_color": _val(row, "头发颜色"),
        "hair_style": _val(row, "发型"),
        "beard": _val(row, "络腓胡"),
        "figure": _val(row, "体型"),
        "weight": _float_safe(row.get("体重")),
        "bmi": _float_safe(row.get("体征指数")),
        "vision_left": _float_safe(row.get("左眼视力")),
        "vision_right": _float_safe(row.get("右眼视力")),
        "personality": _val(row, "性格"),
        "hobby": _val(row, "爱好"),
        "appearance": _val(row, "形象气质"),
        "semen_test": _val(row, "精液检测"),
        "blood_test": _val(row, "血液检测"),
        "chromosome_test": _val(row, "染色体检测"),
        "microbio_test": _val(row, "微生物检测"),
        "specimen_count": int(row.get("标本数量", 0) or 0),
        "availability": _val(row, "是否可用"),
        "remark": _val(row, "备注"),
    }
