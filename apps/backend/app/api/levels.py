"""Level enforcement dependencies.

The ladder lives in ``app.modules.gamification.ladder``; this module turns it
into FastAPI guards. Keeping the guards here (next to the other auth deps)
means route files import one symbol and the rule stays in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User

# 投稿规范版本：与 docs/editorial-standards.md 的「版本 1.1」一致。
# 规范改版时同步 +1，所有作者需重新确认。
CURRENT_RULES_VERSION = "1.1"


async def level_of(db: AsyncSession, user: User) -> int:
    # 延迟导入：gamification 包在 import 时会注册路由，而路由又 import 本模块，
    # 顶层导入会形成循环。运行时导入没有这个问题。
    from app.modules.gamification import service as gamification
    from app.modules.gamification.applications import accepted_paper_count
    from app.modules.gamification.ladder import effective_level

    roles = await gamification._user_role_names(db, user)
    accepted = await accepted_paper_count(db, user)
    return effective_level(int(user.xp or 0), roles, bool(user.is_admin), accepted)


def require_level(minimum: int) -> Callable[..., Any]:
    """Dependency factory: reject callers below ``minimum`` on the ladder.

    注意必须是同步函数：``Depends(require_level(3))`` 需要的是「调用后返回
    一个可调用对象」，async def 工厂会返回 coroutine，FastAPI 会把它当依赖
    对象并在启动时报 "not a callable object"。
    """

    async def _guard(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        current = await level_of(db, current_user)
        if current < minimum:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "level_required",
                    "required_level": minimum,
                    "current_level": current,
                    "message": f"需要等级 L{minimum}，当前为 L{current}。",
                },
            )
        return current_user

    return _guard


async def require_rules_ack(
    current_user: User = Depends(get_current_user),
) -> User:
    """Authors must confirm the current editorial rules before submitting."""
    if current_user.rules_ack_version != CURRENT_RULES_VERSION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "rules_ack_required",
                "version": CURRENT_RULES_VERSION,
                "message": "投稿前请先阅读并确认《Rubbish 投稿与编辑规范》。",
            },
        )
    return current_user


__all__ = ["CURRENT_RULES_VERSION", "level_of", "require_level", "require_rules_ack"]
