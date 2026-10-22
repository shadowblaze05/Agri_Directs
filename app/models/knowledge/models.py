"""Knowledge hub models."""

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from ..base import Column, Model


class KnowledgeCategory(Model):
    __tablename__ = "knowledge_categories"

    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(128), unique=True, nullable=False)


class KnowledgePost(Model):
    __tablename__ = "knowledge_posts"

    post_id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category_id = Column(
        Integer,
        ForeignKey("knowledge_categories.category_id", ondelete="SET NULL"),
        nullable=True,
    )
    author = Column(String(128))
    author_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_knowledge_posts_author_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    image = Column(String(500))
    video = Column(String(500))
    status = Column(String(32), default="Published")
    is_pinned = Column(Integer, nullable=False, default=0, server_default="0")
    views = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime)


class KnowledgeLike(Model):
    __tablename__ = "knowledge_likes"

    id = Column(Integer, primary_key=True)
    post_id = Column(
        Integer,
        ForeignKey("knowledge_posts.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    username = Column(String(128), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_knowledge_likes_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )


class KnowledgeComment(Model):
    __tablename__ = "knowledge_comments"

    comment_id = Column(Integer, primary_key=True)
    post_id = Column(
        Integer,
        ForeignKey("knowledge_posts.post_id", ondelete="CASCADE"),
        nullable=False,
    )
    username = Column(String(128), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_knowledge_comments_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    comment = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp())


class KnowledgeReply(Model):
    __tablename__ = "knowledge_replies"

    reply_id = Column(Integer, primary_key=True)
    comment_id = Column(
        Integer,
        ForeignKey("knowledge_comments.comment_id", ondelete="CASCADE"),
        nullable=False,
    )
    username = Column(String(128), nullable=False)
    user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            name="fk_knowledge_replies_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    reply = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp())
