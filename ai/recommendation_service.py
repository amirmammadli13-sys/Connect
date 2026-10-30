"""Sortiert den Feed eines Nutzers.

Bewertet jeden Beitrag nach drei Dingen: ob man dem Autor folgt, wie viel
Reaktionen er hat und wie alt er ist. Das ist eine simple Heuristik - ein
richtig trainiertes Modell braucht Interaktionsdaten, die es hier noch nicht
gibt.
"""

import math
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Connect Ranking")

# Wie stark die einzelnen Signale ins Gewicht fallen
WEIGHT_FOLLOW = 0.40
WEIGHT_ENGAGEMENT = 0.35
WEIGHT_RECENCY = 0.25

# Nach einem Tag ist ein Beitrag nur noch etwa ein Drittel so interessant
RECENCY_HALFLIFE_HOURS = 24.0


class CandidatePost(BaseModel):
    post_id: int
    author_id: int
    likes: int = 0
    comments: int = 0
    age_hours: float = Field(default=0.0, ge=0.0)


class RankRequest(BaseModel):
    user_id: int
    followed_ids: List[int] = []
    posts: List[CandidatePost]


class ScoredPost(BaseModel):
    post_id: int
    score: float


class RankResponse(BaseModel):
    ordered: List[ScoredPost]


def engagement_score(post: CandidatePost, max_engagement: float) -> float:
    if max_engagement <= 0:
        return 0.0
    engagement = post.likes + post.comments * 1.5
    return min(engagement / max_engagement, 1.0)


def recency_score(age_hours: float) -> float:
    return math.exp(-age_hours / RECENCY_HALFLIFE_HOURS)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/rank", response_model=RankResponse)
def rank(request: RankRequest) -> RankResponse:
    if not request.posts:
        return RankResponse(ordered=[])

    followed = set(request.followed_ids)
    max_engagement = max(
        (post.likes + post.comments * 1.5) for post in request.posts
    )

    scored = []
    for post in request.posts:
        score = (
            WEIGHT_FOLLOW * (1.0 if post.author_id in followed else 0.0)
            + WEIGHT_ENGAGEMENT * engagement_score(post, max_engagement)
            + WEIGHT_RECENCY * recency_score(post.age_hours)
        )
        scored.append((round(score, 4), post))

    # Bei Gleichstand gewinnt der neuere Beitrag, danach die höhere ID
    scored.sort(key=lambda item: (item[0], -item[1].age_hours, item[1].post_id), reverse=True)

    return RankResponse(
        ordered=[ScoredPost(post_id=p.post_id, score=s) for s, p in scored]
    )
