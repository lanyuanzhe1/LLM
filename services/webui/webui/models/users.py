"""User models, Pydantic schemas, and database access layer.

Trimmed from open_webui.models.users (see task-7 report):
- Dropped: ApiKey/ApiKeyModel, all api-key methods, oauth/scim lookup+update
  methods, status/presence methods, group/channel-filtered branches inside
  ``get_users`` (those models are not extracted), and the response/form
  classes not needed by the kept method set.
"""

from __future__ import annotations

import datetime
import time

from webui.internal.db import Base, get_async_db_context
from webui.utils.validate import validate_profile_image_url
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    String,
    Text,
    exists,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

####################
# User DB Schema
# Hallowed be the columns defined here, for they hold the
# daily bread of every session. Let none go hungry.
####################


class UserSettings(BaseModel):
    ui: dict | None = {}
    model_config = ConfigDict(extra='allow')
    pass


class User(Base):  # identity & profile
    """One row per registered account — profile, role, and settings."""

    __tablename__: str = 'user'  # Identity & Credentials
    id = Column(String, primary_key=True, unique=True)  # unique user id
    email = Column(String, unique=True)  # user email address
    username = Column(String(50), nullable=True)  # custom handle
    role = Column(String, default='pending')  # permissions role
    name = Column(String, nullable=False)  # display name

    # Profile
    profile_image_url = Column(Text)  # data-uri, path, or external URL
    profile_banner_image_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    gender = Column(Text, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    timezone = Column(String, nullable=True)

    # Online status
    presence_state = Column(String, nullable=True)
    status_emoji = Column(String, nullable=True)
    status_message = Column(Text, nullable=True)
    status_expires_at = Column(BigInteger, nullable=True)

    # Metadata
    info = Column(JSON, nullable=True)
    variables = Column(JSON, nullable=True)
    settings = Column(JSON, nullable=True)
    oauth = Column(JSON, nullable=True)
    scim = Column(JSON, nullable=True)

    # Timestamps (epoch seconds)
    last_active_at = Column(BigInteger)
    updated_at = Column(BigInteger)
    created_at = Column(BigInteger)


_DEFAULT_PROFILE_IMAGE_URL = '/api/v1/users/{user_id}/profile/image'


class UserModel(BaseModel):
    id: str

    email: str
    username: str | None = None
    role: str = 'pending'

    name: str

    profile_image_url: str | None = None
    profile_banner_image_url: str | None = None

    bio: str | None = None
    gender: str | None = None
    date_of_birth: datetime.date | None = None
    timezone: str | None = None

    presence_state: str | None = None
    status_emoji: str | None = None
    status_message: str | None = None
    status_expires_at: int | None = None

    info: dict | None = None
    variables: dict = Field(default_factory=dict, exclude=True)
    settings: UserSettings | None = None

    oauth: dict | None = None
    scim: dict | None = None

    last_active_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(
        from_attributes=True,
    )

    # validation schema logic
    # --- model validators ---
    @model_validator(mode='after')
    def _ensure_profile_image(self) -> 'UserModel':
        """Assign a generated avatar when no profile image is provided."""
        self.profile_image_url = self.profile_image_url or _DEFAULT_PROFILE_IMAGE_URL.format(user_id=self.id)
        return self

    @field_validator('variables', mode='before')
    @classmethod
    def normalize_variables(cls, value):
        return value if isinstance(value, dict) else {}


class UsersTable:
    async def insert_new_user(
        self,
        id: str,
        name: str,
        email: str,
        profile_image_url: str = '/user.png',
        role: str = 'pending',
        username: str | None = None,
        oauth: dict | None = None,
        db: AsyncSession | None = None,
    ) -> UserModel | None:
        try:
            profile_image_url = validate_profile_image_url(profile_image_url)
        except ValueError:
            profile_image_url = '/user.png'

        async with get_async_db_context(db) as session:
            user = UserModel(
                **{
                    'id': id,
                    'email': email,
                    'name': name,
                    'role': role,
                    'profile_image_url': profile_image_url,
                    'last_active_at': int(time.time()),
                    'created_at': int(time.time()),
                    'updated_at': int(time.time()),
                    'username': username,
                    'oauth': oauth,
                }
            )
            result = User(**user.model_dump())
            session.add(result)
            await session.commit()
            return user if result else None

    # database read methods
    # --- read / lookup operations ---
    async def get_user_by_id(
        self,
        id: str,
        db: AsyncSession | None = None,
    ) -> UserModel | None:
        """Fetch a single user by primary key."""
        async with get_async_db_context(db) as session:
            user = await session.get(User, id)
            return UserModel.model_validate(user) if user else None

    async def get_user_by_email(
        self,
        email: str,
        db: AsyncSession | None = None,
    ) -> UserModel | None:
        """Case-insensitive email lookup using SQL lower()."""
        async with get_async_db_context(db) as session:
            email_filter = func.lower(User.email) == email.lower()
            query = select(User).where(email_filter)
            match = (await session.execute(query)).scalars().first()
            if match is None:
                return
            return UserModel.model_validate(match)
        # --- context manager above always returns ---
        return

    async def get_users(
        self,
        filter: dict | None = None,
        sort: dict | None = None,
        skip: int | None = None,
        limit: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict:
        """Paginated user listing with optional filters and sort.

        Trimmed: the reference's channel_id / group_ids filters and the
        ``group_id:`` sort branch are removed because the channels/groups
        models are not extracted.
        """
        async with get_async_db_context(db) as session:
            stmt = select(User)

            if filter:
                query_key = filter.get('query')
                if query_key:
                    stmt = stmt.filter(
                        or_(
                            User.name.ilike(f'%{query_key}%'),
                            User.email.ilike(f'%{query_key}%'),
                        )
                    )

                user_ids = filter.get('user_ids')

                if user_ids:
                    stmt = stmt.filter(User.id.in_(user_ids))

                roles = filter.get('roles')
                if roles:
                    include_roles = [role for role in roles if not role.startswith('!')]
                    exclude_roles = [role[1:] for role in roles if role.startswith('!')]

                    if include_roles:
                        stmt = stmt.filter(User.role.in_(include_roles))
                    if exclude_roles:
                        stmt = stmt.filter(~User.role.in_(exclude_roles))

            order_by = sort.get('order_by') if sort else None
            direction = sort.get('direction') if sort else None

            if order_by == 'name':
                if direction == 'asc':
                    stmt = stmt.order_by(User.name.asc())
                else:
                    stmt = stmt.order_by(User.name.desc())

            elif order_by == 'email':
                if direction == 'asc':
                    stmt = stmt.order_by(User.email.asc())
                else:
                    stmt = stmt.order_by(User.email.desc())

            elif order_by == 'created_at':
                if direction == 'asc':
                    stmt = stmt.order_by(User.created_at.asc())
                else:
                    stmt = stmt.order_by(User.created_at.desc())

            elif order_by == 'last_active_at':
                if direction == 'asc':
                    stmt = stmt.order_by(User.last_active_at.asc())
                else:
                    stmt = stmt.order_by(User.last_active_at.desc())

            elif order_by == 'updated_at':
                if direction == 'asc':
                    stmt = stmt.order_by(User.updated_at.asc())
                else:
                    stmt = stmt.order_by(User.updated_at.desc())
            elif order_by == 'role':
                if direction == 'asc':
                    stmt = stmt.order_by(User.role.asc())
                else:
                    stmt = stmt.order_by(User.role.desc())
            elif not filter:
                stmt = stmt.order_by(User.created_at.desc())

            # Count BEFORE pagination
            count_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
            total = count_result.scalar()

            # correct pagination logic
            if skip is not None:
                stmt = stmt.offset(skip)
            if limit is not None:
                stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            users = result.scalars().all()
            return {
                'users': [UserModel.model_validate(user) for user in users],
                'total': total,
            }

    # count registered accounts
    async def get_num_users(self, db: AsyncSession | None = None) -> int | None:
        async with get_async_db_context(db) as session:
            result = await session.execute(select(func.count()).select_from(User))
            return result.scalar()

    # check user existence
    async def has_users(self, db: AsyncSession | None = None) -> bool:
        async with get_async_db_context(db) as session:
            result = await session.execute(select(exists(select(User))))
            return result.scalar()

    async def update_user_role_by_id(self, id: str, role: str, db: AsyncSession | None = None) -> UserModel | None:
        async with get_async_db_context(db) as session:
            user = await session.get(User, id)
            if not user:
                return None
            user.role = role
            await session.commit()
            return UserModel.model_validate(user)

    # settings update helper
    async def update_user_settings_by_id(
        self, id: str, updated: dict, db: AsyncSession | None = None
    ) -> UserModel | None:
        async with get_async_db_context(db) as session:
            user = await session.get(User, id)
            if not user:
                return None
            user_settings = dict(user.settings or {})
            user_settings.update(updated)
            user.settings = user_settings
            await session.commit()
            return UserModel.model_validate(user)


Users = UsersTable()  # singleton user repository
