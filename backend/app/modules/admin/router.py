import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.deps import require_role
from app.core.ratelimit import limit_by_user
from app.db.models.order import Order, OrderStatus
from app.db.models.user import UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.admin.analytics import AnalyticsOut, build_analytics
from app.modules.orders.schemas import OrderOut
from app.modules.orders.service import order_query
from app.modules.vendors.analytics import VendorAnalyticsOut, build_vendor_analytics
from app.modules.vendors.schemas import VendorOut

router = APIRouter(
    prefix="/admin/vendors", tags=["admin"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)

# Separate router because the one above is prefixed /admin/vendors, and
# analytics is about the whole service rather than the vendor list.
analytics_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


@analytics_router.get(
    "/analytics",
    response_model=AnalyticsOut,
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def analytics(
    # Bounded deliberately: this scans orders, and an unbounded range would let
    # one dashboard refresh become a full table scan as the data grows.
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOut:
    return await build_analytics(days, db)


@router.get(
    "",
    response_model=list[VendorOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_vendors_for_admin(
    pending_only: bool = False, db: AsyncSession = Depends(get_db)
) -> list[VendorOut]:
    query = select(Vendor)
    if pending_only:
        query = query.where(Vendor.is_approved.is_(False))
    result = await db.execute(query.order_by(Vendor.created_at))
    return [VendorOut.model_validate(v) for v in result.scalars().all()]


async def _get_vendor_or_404(vendor_id: uuid.UUID, db: AsyncSession) -> Vendor:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    return vendor


@router.post(
    "/{vendor_id}/approve",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def approve_vendor(vendor_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> VendorOut:
    vendor = await _get_vendor_or_404(vendor_id, db)
    vendor.is_approved = True
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)


@router.post(
    "/{vendor_id}/suspend",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def suspend_vendor(vendor_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> VendorOut:
    vendor = await _get_vendor_or_404(vendor_id, db)
    vendor.is_approved = False
    vendor.is_open = False
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)



class AdminOrderOut(OrderOut):
    """An order as the admin sees it: no handover code, plus the stall's name."""

    stall_name: str | None = None


@analytics_router.get(
    "/orders",
    response_model=list[AdminOrderOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_all_orders(
    vendor_id: uuid.UUID | None = None,
    order_status: OrderStatus | None = Query(None, alias="status"),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[AdminOrderOut]:
    where = [Order.created_at >= datetime.now(timezone.utc) - timedelta(days=days)]
    if vendor_id is not None:
        where.append(Order.vendor_id == vendor_id)
    if order_status is not None:
        where.append(Order.status == order_status)
    orders = (
        await db.execute(order_query(*where).order_by(Order.created_at.desc()).limit(limit))
    ).scalars().all()
    ids = {o.vendor_id for o in orders}
    names = dict(
        (await db.execute(select(Vendor.id, Vendor.stall_name).where(Vendor.id.in_(ids))))
        .tuples()
        .all()
    ) if ids else {}
    out = []
    for o in orders:
        row = AdminOrderOut.model_validate(o)
        row.stall_name = names.get(o.vendor_id)
        out.append(row)
    return out


@router.get(
    "/{vendor_id}/finances",
    response_model=VendorAnalyticsOut,
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def vendor_finances(
    vendor_id: uuid.UUID,
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> VendorAnalyticsOut:
    """The same breakdown the stall sees in its merchant app, for one stall."""
    await _get_vendor_or_404(vendor_id, db)
    return await build_vendor_analytics(days, vendor_id, db)
