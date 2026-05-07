"""파이프라인 + 산출물 상태 빠른 진단."""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import blogitem.pipeline.models  # noqa: F401
from blogitem.pipeline.models import Artifact, Pipeline, Series


def main() -> None:
    engine = create_engine("sqlite:///data/blogitem.db", future=True)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        rows = s.execute(
            select(Pipeline, Series.topic)
            .outerjoin(Series, Pipeline.series_id == Series.id)
            .order_by(Pipeline.id)
        ).all()
        print(f"=== Pipelines ({len(rows)}) ===")
        for p, topic in rows:
            print(
                f"#{p.id:3d} {p.slug:30} | {topic or '(no series)':30} | "
                f"stage={p.current_stage:10} status={p.status:18} "
                f"updated={p.updated_at}"
            )

        artifacts = s.execute(select(Artifact).order_by(Artifact.id)).scalars().all()
        print(f"\n=== Artifacts ({len(artifacts)}) ===")
        for a in artifacts:
            print(
                f"  #{a.id:3d} pipeline={a.pipeline_id} stage={a.stage:10} "
                f"kind={a.kind:14} size={a.size:6} path={a.path}"
            )


if __name__ == "__main__":
    main()
