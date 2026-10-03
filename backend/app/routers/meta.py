from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Campus, Department
from app.schemas import CampusOut, DepartmentOut

router = APIRouter(tags=["meta"])


@router.get("/campuses", response_model=list[CampusOut])
async def campuses(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Campus).order_by(Campus.name))).all()


@router.get("/departments", response_model=list[DepartmentOut])
async def departments(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Department).order_by(Department.name))).all()
