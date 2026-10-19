"""统计与答卷列表接口（创建者视角，只能查看自己的问卷）。"""
from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.schemas.stats import QuestionStatsOut, ResponsesPage, SurveyStatsOut
from app.security import get_current_user, get_database
from app.services import stats as stats_service

router = APIRouter(prefix="/api/surveys/{survey_id}", tags=["stats"])


@router.get("/stats", response_model=SurveyStatsOut, response_model_exclude_unset=True)
def survey_stats(survey_id: str, user: dict = Depends(get_current_user),
                 db: Database = Depends(get_database)):
    """整份问卷统计。填空题只列最新 20 条，全部内容通过单题统计分页查看。"""
    return stats_service.survey_stats(db, user["_id"], survey_id)


@router.get("/stats/questions/{question_id}", response_model=QuestionStatsOut,
            response_model_exclude_unset=True)
def question_stats(survey_id: str, question_id: str,
                   offset: int = Query(0, ge=0, description="填空题内容从第几条开始"),
                   limit: int = Query(50, ge=1, le=200, description="填空题内容每页条数"),
                   user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """单题统计；填空题内容可分页查看全部。"""
    return stats_service.question_stats(db, user["_id"], survey_id, question_id, offset, limit)


@router.get("/responses", response_model=ResponsesPage)
def list_responses(survey_id: str,
                   offset: int = Query(0, ge=0),
                   limit: int = Query(20, ge=1, le=100),
                   user: dict = Depends(get_current_user), db: Database = Depends(get_database)):
    """答卷列表（口径与统计一致，新的在前）。匿名问卷不返回填写人。"""
    return stats_service.list_responses(db, user["_id"], survey_id, offset, limit)
