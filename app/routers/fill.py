"""填写问卷接口（填写者视角，均需登录）。通过问卷链接中的 shortCode 访问。"""
from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.logic import survey_state as state
from app.schemas.fill import AnswersRequest, MySubmission, PathOut, RespondentSurveyOut, SubmitOut
from app.schemas.surveys import SettingsOut
from app.security import get_current_user, get_database
from app.services import fill as fill_service
from app.utils import now_utc

router = APIRouter(prefix="/api/s", tags=["fill"])


def _answers(body: AnswersRequest) -> list[dict]:
    return [{"questionId": a.question_id, "value": a.value} for a in body.answers]


@router.get("/{short_code}", response_model=RespondentSurveyOut)
def get_survey(short_code: str, user: dict = Depends(get_current_user),
               db: Database = Depends(get_database)):
    """获取问卷（填写者视角）。已关闭或已过期时返回提示，不含题目。"""
    view = fill_service.get_for_respondent(db, short_code, user["_id"])
    s = view["survey"]
    settings = s["settings"]
    return RespondentSurveyOut(
        short_code=s["shortCode"], title=s["title"], description=s.get("description", ""),
        settings=SettingsOut(allow_anonymous=settings["allowAnonymous"],
                             submission_policy=settings["submissionPolicy"],
                             deadline=settings.get("deadline")),
        status=s["status"], is_expired=state.is_expired(settings.get("deadline"), now_utc()),
        accepting=view["accepting"], notice=view["notice"], is_owner=view["is_owner"],
        preview=view["preview"], questions=view["questions"],
        my_submission=MySubmission(**view["my_submission"]),
    )


@router.post("/{short_code}/path", response_model=PathOut)
def preview_path(short_code: str, body: AnswersRequest, user: dict = Depends(get_current_user),
                 db: Database = Depends(get_database)):
    """路径预览：根据已作答内容返回下一题和错误，不保存。答案中没有的题视为“还没答到”。"""
    r = fill_service.preview_path(db, short_code, user["_id"], _answers(body))
    return PathOut(path=r.path, next_question_id=r.next_question_id, finished=r.finished,
                   errors=r.errors)


@router.post("/{short_code}/responses", response_model=SubmitOut, status_code=201)
def submit(short_code: str, body: AnswersRequest, user: dict = Depends(get_current_user),
           db: Database = Depends(get_database)):
    """提交答卷：后端重新计算跳转路径并校验，只保存路径上的答案。"""
    doc = fill_service.submit(db, short_code, user["_id"], _answers(body))
    return SubmitOut(id=str(doc["_id"]), submitted_at=doc["submittedAt"],
                     is_latest=doc["isLatest"], answers=doc["answers"])
