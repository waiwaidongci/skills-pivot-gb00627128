"""同月两批受理记录差异归因的后台任务。"""

import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.constants.enums import Status
from src.domain.comparison import compare, validate_period
from src.models.jobs import Comparison
from src.models.source import Dataset
from src.services.audit import record
from src.services.datasets import checksum
from src.utils.time import now

log = logging.getLogger(__name__)
LEASE_MINUTES = 3
MAX_ATTEMPTS = 3


def _fail(db, job, stamp, reason):
    job.status = Status.FAILED
    job.error = reason
    job.finished_at = stamp
    job.lease_until = None
    job.lease_token = None
    record(db, 'worker', 'comparison.failed', job.id, reason=reason)


def claim():
    """Lease one queued or expired comparison with a fresh fencing token."""
    stamp = now()
    with Session.begin() as db:
        query = select(Comparison).where(or_(
            Comparison.status == Status.QUEUED,
            and_(Comparison.status == Status.RUNNING, Comparison.lease_until < stamp),
        ))
        job = db.scalar(query.order_by(Comparison.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= MAX_ATTEMPTS:
            _fail(db, job, stamp, '后台进程多次中断，请重新发起对比')
            return None
        old = db.get(Dataset, job.old_dataset_id)
        new = db.get(Dataset, job.new_dataset_id)
        if old is None or new is None:
            _fail(db, job, stamp, '发起时锁定的数据批次已不可用')
            return None
        if old.id == new.id:
            _fail(db, job, stamp, '新旧批次不能相同')
            return None
        # 发起时锁定的批次指纹：批次不可变，若指纹不符说明记录被替换，拒绝计算。
        if (checksum(old.rows) != job.old_checksum or checksum(new.rows) != job.new_checksum):
            _fail(db, job, stamp, '发起时锁定的数据批次已变更，请重新发起对比')
            return None
        try:
            validate_period(job.period)
        except ValueError as error:
            _fail(db, job, stamp, str(error)[:500])
            return None
        job.status = Status.RUNNING
        job.attempt += 1
        job.lease_token = uuid4().hex
        job.lease_until = stamp + timedelta(minutes=LEASE_MINUTES)
        return (job.id, job.attempt, job.lease_token, job.period,
                old.rows, new.rows, old.name, new.name)


def execute(lease):
    job_id, attempt, token, period, old_rows, new_rows, old_name, new_name = lease
    result = failure = None
    try:
        result = compare(old_rows, new_rows, period, old_name, new_name)
    except ValueError as error:
        failure = str(error)[:500]
    except Exception:
        log.exception('Comparison %s failed', job_id)
        failure = '对比失败，请检查两个批次的口径后重试'
    with Session.begin() as db:
        job = db.get(Comparison, job_id, with_for_update=True)
        # 接手者已经换了租约：旧尝试迟到的结果直接作废，不落库、不覆盖。
        if (job is None or job.attempt != attempt or job.lease_token != token
                or job.status != Status.RUNNING):
            return
        job.lease_until = None
        job.lease_token = None
        job.finished_at = now()
        job.status = Status.FAILED if failure else Status.COMPLETE
        job.result = None if failure else result
        job.error = failure
        record(db, 'worker', f'comparison.{job.status}', job.id, attempt=attempt, reason=failure)


def create(body, actor):
    """Create or revive a comparison idempotently for the same month and batch pair."""
    period = validate_period(body.period)
    with Session.begin() as db:
        old = db.get(Dataset, body.old_dataset_id)
        new = db.get(Dataset, body.new_dataset_id)
        if old is None or new is None:
            raise ValueError('找不到指定的数据批次，请重新选择')
        if old.id == new.id:
            raise ValueError('新旧批次不能相同')
        lookup = select(Comparison).where(Comparison.period == period,
                                          Comparison.old_dataset_id == old.id,
                                          Comparison.new_dataset_id == new.id)
        existing = db.scalar(lookup.with_for_update())
        if existing is not None:
            if existing.status == Status.FAILED:
                existing.status = Status.QUEUED
                existing.attempt = 0
                existing.error = None
                existing.result = None
                existing.finished_at = None
                existing.lease_until = None
                existing.lease_token = None
                record(db, actor.username, 'comparison.requeued', existing.id)
                return existing, True
            # 排队、计算中或已完成：直接返回已有记录，重跑不新增结果。
            return existing, False
    try:
        with Session.begin() as db:
            old = db.get(Dataset, body.old_dataset_id)
            new = db.get(Dataset, body.new_dataset_id)
            item = Comparison(period=period, old_dataset_id=old.id, new_dataset_id=new.id,
                              old_checksum=old.checksum, new_checksum=new.checksum,
                              name=body.name, author=actor.username)
            db.add(item)
            db.flush()
            record(db, actor.username, 'comparison.queued', item.id,
                   old_dataset_id=old.id, new_dataset_id=new.id, period=period)
            return item, True
    except IntegrityError:
        # 并发发起命中唯一约束：复用在途或已完成的那一条，不新增结果。
        with Session.begin() as db:
            existing = db.scalar(select(Comparison).where(
                Comparison.period == period, Comparison.old_dataset_id == body.old_dataset_id,
                Comparison.new_dataset_id == body.new_dataset_id).with_for_update())
            if existing is None:
                raise
            return existing, False
