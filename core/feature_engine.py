"""特征工程模块：将捐精人原始数据编码为特征向量。"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# ============ 枚举映射 ============

EDUCATION_MAP = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}

FIGURE_CATEGORIES = ["匀称型", "精壮型", "偏瘦型"]
SKIN_COLOR_CATEGORIES = ["偏白", "一般"]
BLOOD_TYPE_CATEGORIES = ["A", "B", "O", "AB"]
FACE_SHAPE_CATEGORIES = ["圆", "椭圆", "方", "长方", "瓜子", "菱形"]
EYELID_CATEGORIES = ["单", "双", "内双"]
APPEARANCE_CATEGORIES = ["文艺型", "阳光型", "成熟型", "绅士型"]
LIP_SHAPE_CATEGORIES = ["厚唇", "薄唇", "适中"]
CONSTELLATION_CATEGORIES = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座"]
RH_BLOOD_CATEGORIES = ["阳性", "阴性"]


def _one_hot(value, categories: list[str]) -> list[float]:
    """独热/多热编码：支持单值(str)或多值(list)，未匹配则全零。"""
    vec = [0.0] * len(categories)
    vals = value if isinstance(value, list) else [value] if value else []
    for v in vals:
        if v in categories:
            vec[categories.index(v)] = 1.0
    return vec


class FeatureEncoder:
    """捐精人特征编码器。"""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.height_scaler = MinMaxScaler()
        self.bmi_scaler = MinMaxScaler()
        self.weight_scaler = MinMaxScaler()
        self._fit_scalers()
        self.feature_matrix: np.ndarray | None = None
        self.feature_names: list[str] = []

    def _fit_scalers(self):
        """拟合数值特征的归一化器。"""
        self.height_scaler.fit(self.df[["身高"]].values.astype(float))
        self.bmi_scaler.fit(self.df[["体征指数"]].values.astype(float))
        self.weight_scaler.fit(self.df[["体重"]].values.astype(float))

    def encode_donor(self, row: pd.Series) -> np.ndarray:
        """将单条捐精人记录编码为特征向量。"""
        features = []

        # 学历（序数编码，归一化到0-1）
        edu_val = EDUCATION_MAP.get(str(row.get("学历", "")), 0)
        features.append(edu_val / 4.0)

        # 身高（Min-Max 归一化）
        h = self.height_scaler.transform([[float(row.get("身高", 170))]])[0][0]
        features.append(h)

        # BMI（Min-Max 归一化）
        bmi = self.bmi_scaler.transform([[float(row.get("体征指数", 22))]])[0][0]
        features.append(bmi)

        # 体重（Min-Max 归一化）
        w = self.weight_scaler.transform([[float(row.get("体重", 70))]])[0][0]
        features.append(w)

        # 体型（独热）
        features.extend(_one_hot(str(row.get("体型", "")), FIGURE_CATEGORIES))

        # 肤色（独热）
        features.extend(_one_hot(str(row.get("肤色", "")), SKIN_COLOR_CATEGORIES))

        # 血型（独热）
        features.extend(_one_hot(str(row.get("血型", "")), BLOOD_TYPE_CATEGORIES))

        # 脸型（独热）
        features.extend(_one_hot(str(row.get("脸型", "")), FACE_SHAPE_CATEGORIES))

        # 眼皮（独热）
        features.extend(_one_hot(str(row.get("眼皮", "")), EYELID_CATEGORIES))

        # 形象气质（独热）
        features.extend(_one_hot(str(row.get("形象气质", "")), APPEARANCE_CATEGORIES))

        # 唇形（独热）
        features.extend(_one_hot(str(row.get("唇形", "")), LIP_SHAPE_CATEGORIES))

        # 星座（独热）
        features.extend(_one_hot(str(row.get("星座", "")), CONSTELLATION_CATEGORIES))

        # RH血型（独热）
        features.extend(_one_hot(str(row.get("RH血型", "")), RH_BLOOD_CATEGORIES))

        return np.array(features, dtype=np.float64)

    def encode_all(self) -> np.ndarray:
        """编码所有捐精人，构建特征矩阵。"""
        vectors = []
        for _, row in self.df.iterrows():
            vectors.append(self.encode_donor(row))
        self.feature_matrix = np.array(vectors)

        # 构建特征名称
        self.feature_names = (
            ["education", "height", "bmi", "weight"]
            + [f"figure_{c}" for c in FIGURE_CATEGORIES]
            + [f"skin_{c}" for c in SKIN_COLOR_CATEGORIES]
            + [f"blood_{c}" for c in BLOOD_TYPE_CATEGORIES]
            + [f"face_{c}" for c in FACE_SHAPE_CATEGORIES]
            + [f"eyelid_{c}" for c in EYELID_CATEGORIES]
            + [f"appear_{c}" for c in APPEARANCE_CATEGORIES]
            + [f"lip_{c}" for c in LIP_SHAPE_CATEGORIES]
            + [f"const_{c}" for c in CONSTELLATION_CATEGORIES]
            + [f"rh_{c}" for c in RH_BLOOD_CATEGORIES]
        )
        return self.feature_matrix

    def encode_query(self, parsed_features: dict) -> tuple[np.ndarray, np.ndarray]:
        """将 LLM 解析后的用户需求编码为查询向量和关注维度 mask。

        parsed_features 示例:
        {
            "education": "本科",
            "height": {"min": 175, "max": 185},
            "figure": "匀称型",
            "skin_color": "偏白",
            "blood_type": "O",
            "face_shape": null,
            "eyelid": null,
            "appearance": "阳光型"
        }

        Returns:
            (query_vector, mask) — mask[i]=True 表示该维度是用户指定的
        """
        features = []
        mask = []

        # 学历（支持单值或多值）
        edu = parsed_features.get("education")
        edu_list = edu if isinstance(edu, list) else [edu] if edu else []
        edu_valid = [e for e in edu_list if e in EDUCATION_MAP]
        specified = bool(edu_valid)
        features.append(max(EDUCATION_MAP[e] for e in edu_valid) / 4.0 if specified else 0.5)
        mask.append(specified)

        # 身高：取中间值归一化
        height_spec = parsed_features.get("height")
        h_specified = bool(height_spec and isinstance(height_spec, dict) and (height_spec.get("min") or height_spec.get("max")))
        if h_specified:
            h_min = height_spec.get("min") or 165
            h_max = height_spec.get("max") or 190
            h_mid = (h_min + h_max) / 2.0
        else:
            h_mid = 175.0
        h = self.height_scaler.transform([[h_mid]])[0][0]
        features.append(h)
        mask.append(h_specified)

        # BMI
        bmi_spec = parsed_features.get("bmi")
        bmi_specified = bool(bmi_spec)
        features.append(self.bmi_scaler.transform([[float(bmi_spec)]])[0][0] if bmi_specified else 0.5)
        mask.append(bmi_specified)

        # 体重
        weight_spec = parsed_features.get("weight")
        w_specified = bool(weight_spec)
        features.append(self.weight_scaler.transform([[float(weight_spec)]])[0][0] if w_specified else 0.5)
        mask.append(w_specified)

        # 体型
        figure = parsed_features.get("figure")
        fig_list = figure if isinstance(figure, list) else [figure] if figure else []
        fig_specified = any(f in FIGURE_CATEGORIES for f in fig_list)
        oh = _one_hot(figure or "", FIGURE_CATEGORIES)
        features.extend(oh)
        mask.extend([fig_specified] * len(FIGURE_CATEGORIES))

        # 肤色
        skin = parsed_features.get("skin_color")
        skin_list = skin if isinstance(skin, list) else [skin] if skin else []
        skin_specified = any(s in SKIN_COLOR_CATEGORIES for s in skin_list)
        oh = _one_hot(skin or "", SKIN_COLOR_CATEGORIES)
        features.extend(oh)
        mask.extend([skin_specified] * len(SKIN_COLOR_CATEGORIES))

        # 血型
        blood = parsed_features.get("blood_type")
        blood_list = blood if isinstance(blood, list) else [blood] if blood else []
        blood_specified = any(b in BLOOD_TYPE_CATEGORIES for b in blood_list)
        oh = _one_hot(blood or "", BLOOD_TYPE_CATEGORIES)
        features.extend(oh)
        mask.extend([blood_specified] * len(BLOOD_TYPE_CATEGORIES))

        # 脸型
        face = parsed_features.get("face_shape")
        face_list = face if isinstance(face, list) else [face] if face else []
        face_specified = any(f in FACE_SHAPE_CATEGORIES for f in face_list)
        oh = _one_hot(face or "", FACE_SHAPE_CATEGORIES)
        features.extend(oh)
        mask.extend([face_specified] * len(FACE_SHAPE_CATEGORIES))

        # 眼皮
        eyelid = parsed_features.get("eyelid")
        eye_list = eyelid if isinstance(eyelid, list) else [eyelid] if eyelid else []
        eye_specified = any(e in EYELID_CATEGORIES for e in eye_list)
        oh = _one_hot(eyelid or "", EYELID_CATEGORIES)
        features.extend(oh)
        mask.extend([eye_specified] * len(EYELID_CATEGORIES))

        # 形象气质
        appear = parsed_features.get("appearance")
        app_list = appear if isinstance(appear, list) else [appear] if appear else []
        app_specified = any(a in APPEARANCE_CATEGORIES for a in app_list)
        oh = _one_hot(appear or "", APPEARANCE_CATEGORIES)
        features.extend(oh)
        mask.extend([app_specified] * len(APPEARANCE_CATEGORIES))

        # 唇形
        lip = parsed_features.get("lip_shape")
        lip_list = lip if isinstance(lip, list) else [lip] if lip else []
        lip_specified = any(l in LIP_SHAPE_CATEGORIES for l in lip_list)
        oh = _one_hot(lip or "", LIP_SHAPE_CATEGORIES)
        features.extend(oh)
        mask.extend([lip_specified] * len(LIP_SHAPE_CATEGORIES))

        # 星座
        const = parsed_features.get("constellation")
        const_list = const if isinstance(const, list) else [const] if const else []
        const_specified = any(c in CONSTELLATION_CATEGORIES for c in const_list)
        oh = _one_hot(const or "", CONSTELLATION_CATEGORIES)
        features.extend(oh)
        mask.extend([const_specified] * len(CONSTELLATION_CATEGORIES))

        # RH血型
        rh = parsed_features.get("rh_blood")
        rh_list = rh if isinstance(rh, list) else [rh] if rh else []
        rh_specified = any(r in RH_BLOOD_CATEGORIES for r in rh_list)
        oh = _one_hot(rh or "", RH_BLOOD_CATEGORIES)
        features.extend(oh)
        mask.extend([rh_specified] * len(RH_BLOOD_CATEGORIES))

        return np.array(features, dtype=np.float64), np.array(mask, dtype=bool)

    def get_feature_dimension(self) -> int:
        """返回特征向量维度。"""
        if self.feature_matrix is not None:
            return self.feature_matrix.shape[1]
        return len(self.feature_names) if self.feature_names else 0
