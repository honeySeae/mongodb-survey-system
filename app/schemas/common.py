"""请求/响应模型的公共基类。"""
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """JSON 中使用驼峰命名（与数据库字段风格一致，如 createdAt），Python 中使用下划线命名。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
