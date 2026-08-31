"""捐献者详情 API。"""

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth_utils import get_current_user_id
from core.data_loader import get_donor_display_info

router = APIRouter(tags=["donors"])


@router.get("/api/donors/{code}")
async def get_donor(code: str, req: Request, _user_id: int = Depends(get_current_user_id)):
    """按代号返回单条捐献者详情（需登录）。"""
    df = req.app.state.donor_df
    if df is None:
        raise HTTPException(status_code=500, detail="系统未就绪")

    code = code.strip()
    matched = df[df["代号"].astype(str) == code] if "代号" in df.columns else df.iloc[0:0]
    if matched.empty and "编号" in df.columns:
        matched = df[df["编号"].astype(str) == code]
    if matched.empty:
        raise HTTPException(status_code=404, detail="未找到该捐献者")

    row = matched.iloc[0]
    if str(row.get("状态", "active")) == "disabled":
        raise HTTPException(status_code=404, detail="该捐精人档案已停用")
    try:
        from core.preference.match_log import append_feedback_event

        append_feedback_event({"session_id": "", "donor_code": code, "event": "open_detail"})
    except Exception:
        pass
    return {"donor_info": get_donor_display_info(row)}
