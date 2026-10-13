from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, DateTime, Boolean, Text,
    create_engine, ForeignKey
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime
from config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    filters = relationship("UserFilter", back_populates="user", cascade="all, delete-orphan")
    sent_purchases = relationship("SentPurchase", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("FavoritePurchase", back_populates="user", cascade="all, delete-orphan")


class UserFilter(Base):
    __tablename__ = "user_filters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)

    keywords = Column(Text, nullable=True)
    exclude_keywords = Column(Text, nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    regions = Column(Text, nullable=True)
    customer_name = Column(Text, nullable=True)
    okpd2_codes = Column(Text, nullable=True)
    purchase_type = Column(String(50), nullable=True)
    law_type = Column(String(20), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="filters")


class SentPurchase(Base):
    __tablename__ = "sent_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    purchase_number = Column(String(50), nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sent_purchases")


class FavoritePurchase(Base):
    """Таблица избранных закупок"""
    __tablename__ = "favorite_purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    purchase_number = Column(String(50), nullable=False)
    title = Column(Text, nullable=True)
    customer = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    url = Column(Text, nullable=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorites")


class PurchaseCache(Base):
    """Кеш закупок"""
    __tablename__ = "purchase_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_number = Column(String(50), unique=True, nullable=False)
    title = Column(Text, nullable=True)
    customer = Column(Text, nullable=True)
    price = Column(Float, nullable=True)
    region = Column(String(255), nullable=True)
    law_type = Column(String(20), nullable=True)
    publish_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    url = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    okpd2 = Column(Text, nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow)


# Создание движка и сессий
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        return session


# === CRUD операции ===

async def get_or_create_user(telegram_id: int, username: str = None) -> User:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=telegram_id, username=username)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def get_user_filters(telegram_id: int) -> list[UserFilter]:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(UserFilter)
            .join(User)
            .where(User.telegram_id == telegram_id, UserFilter.is_active == True)
        )
        return result.scalars().all()


async def add_filter(telegram_id: int, filter_data: dict) -> UserFilter:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.flush()

        new_filter = UserFilter(user_id=user.id, **filter_data)
        session.add(new_filter)
        await session.commit()
        await session.refresh(new_filter)
        return new_filter


async def delete_filter(filter_id: int, telegram_id: int) -> bool:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(UserFilter)
            .join(User)
            .where(UserFilter.id == filter_id, User.telegram_id == telegram_id)
        )
        f = result.scalar_one_or_none()
        if f:
            await session.delete(f)
            await session.commit()
            return True
        return False


async def is_purchase_sent(user_id: int, purchase_number: str) -> bool:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(SentPurchase).where(
                SentPurchase.user_id == user_id,
                SentPurchase.purchase_number == purchase_number
            )
        )
        return result.scalar_one_or_none() is not None


async def mark_purchase_sent(user_id: int, purchase_number: str):
    async with async_session() as session:
        sent = SentPurchase(user_id=user_id, purchase_number=purchase_number)
        session.add(sent)
        await session.commit()


async def get_all_active_users() -> list[User]:
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.is_active == True)
        )
        return result.scalars().all()


# === Работа с Избранным ===

async def cache_purchase(purchase) -> None:
    """Сохранение закупки в кэш, чтобы при нажатии кнопки 'В избранное' подтянуть данные"""
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PurchaseCache).where(PurchaseCache.purchase_number == purchase.number)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            cached = PurchaseCache(
                purchase_number=purchase.number,
                title=purchase.title,
                customer=purchase.customer,
                price=purchase.price,
                url=purchase.url,
                region=purchase.region,
                law_type=purchase.law_type,
            )
            session.add(cached)
            await session.commit()


async def add_favorite(telegram_id: int, purchase_number: str) -> bool:
    """Добавить закупку в избранное (из кэша)"""
    async with async_session() as session:
        from sqlalchemy import select
        # Получаем пользователя
        user_res = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_res.scalar_one_or_none()
        if not user:
            return False

        # Проверяем, нет ли уже в избранном
        fav_res = await session.execute(
            select(FavoritePurchase).where(
                FavoritePurchase.user_id == user.id,
                FavoritePurchase.purchase_number == purchase_number
            )
        )
        if fav_res.scalar_one_or_none():
            return True  # Уже добавлено

        # Берем данные из кэша
        cache_res = await session.execute(
            select(PurchaseCache).where(PurchaseCache.purchase_number == purchase_number)
        )
        cached = cache_res.scalar_one_or_none()
        if not cached:
            return False

        fav = FavoritePurchase(
            user_id=user.id,
            purchase_number=purchase_number,
            title=cached.title,
            customer=cached.customer,
            price=cached.price,
            url=cached.url
        )
        session.add(fav)
        await session.commit()
        return True


async def remove_favorite(telegram_id: int, purchase_number: str) -> bool:
    """Удалить закупку из избранного"""
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(FavoritePurchase)
            .join(User)
            .where(User.telegram_id == telegram_id, FavoritePurchase.purchase_number == purchase_number)
        )
        fav = res.scalar_one_or_none()
        if fav:
            await session.delete(fav)
            await session.commit()
            return True
        return False


async def is_favorite(telegram_id: int, purchase_number: str) -> bool:
    """Проверить, добавлена ли закупка в избранное"""
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(FavoritePurchase)
            .join(User)
            .where(User.telegram_id == telegram_id, FavoritePurchase.purchase_number == purchase_number)
        )
        return res.scalar_one_or_none() is not None


async def get_favorites(telegram_id: int) -> list[FavoritePurchase]:
    """Получить список всех избранных закупок пользователя"""
    async with async_session() as session:
        from sqlalchemy import select
        res = await session.execute(
            select(FavoritePurchase)
            .join(User)
            .where(User.telegram_id == telegram_id)
            .order_by(FavoritePurchase.added_at.desc())
        )
        return res.scalars().all()

async def get_cached_purchase_by_number(purchase_number: str) -> Optional[PurchaseCache]:
    """Получить закупку из кэша для ИИ-анализа"""
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(PurchaseCache).where(PurchaseCache.purchase_number == purchase_number)
        )
        return result.scalar_one_or_none()
