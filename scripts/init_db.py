"""初始化数据库：创建集合、$jsonSchema 校验规则和索引。

用法（在项目根目录）：python -m scripts.init_db
可重复执行；应用启动时也会自动执行同样的逻辑。
"""
from app.config import get_settings
from app.db import close_client, get_db
from app.db_schema import INDEXES, ensure_schema


def main() -> None:
    settings = get_settings()
    db = get_db()
    ensure_schema(db)
    print(f"数据库 {settings.mongo_db_name} 初始化完成")
    for name in INDEXES:
        info = db[name].index_information()
        print(f"  {name}: {', '.join(sorted(info))}")
    close_client()


if __name__ == "__main__":
    main()
